"""Ledger retention and archive support for Meta Flow event ledgers."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from meta_flow.evals.runner import parse_yaml_subset
from meta_flow.state import event_ledger
from meta_flow.state.current import BASE_LEDGER_RELS, now_utc


DEFAULT_POLICY_REL = Path("process/policies/LEDGER-RETENTION.yaml")
ARCHIVE_ROOT_REL = Path("process/archive/ledger")
DEFAULT_WINDOW_DAYS = 90
DEFAULT_KEEP_LATEST_N_EVENTS = 500
DEFAULT_KEEP_LATEST_N_CR = 20
MARKER_EVENT_TYPE = "ledger_compacted"
KNOWN_LEDGER_RELS = {
    **event_ledger.KNOWN_LEDGER_RELS,
    **{rel.name.removesuffix("-LEDGER.ndjson").lower().replace("-", "_"): rel for rel in BASE_LEDGER_RELS},
}


@dataclass(frozen=True)
class RetentionPolicy:
    window_days: int = DEFAULT_WINDOW_DAYS
    keep_latest_n_events: int = DEFAULT_KEEP_LATEST_N_EVENTS
    keep_latest_n_cr: int = DEFAULT_KEEP_LATEST_N_CR
    archive_rule: str = "summary-index-backup"


@dataclass(frozen=True)
class CompactPlan:
    project_root: Path
    ledger_path: Path
    ledger_type: str
    policy: RetentionPolicy
    total_events: int
    keep_count: int
    archive_count: int
    source_hash: str
    kept_events: tuple[dict[str, Any], ...]
    archived_events: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...] = ()

    @property
    def will_write(self) -> bool:
        return self.archive_count > 0


class LedgerCompactionError(ValueError):
    """Raised when ledger compaction cannot be planned or applied safely."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    if not path.is_file():
        return ""
    return _sha256_bytes(path.read_bytes())


def _clean_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "_line_no"}


def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_under_project(project_root: Path, value: Path) -> Path:
    candidate = value if value.is_absolute() else project_root / value
    return candidate.resolve()


def guard_ledger_path(project_root: Path, ledger_path: Path) -> Path:
    root = project_root.resolve()
    resolved = _resolve_under_project(root, ledger_path)
    try:
        rel = resolved.relative_to(root)
    except ValueError as exc:
        raise LedgerCompactionError(f"ledger path is outside project root: {ledger_path}") from exc
    rel_text = rel.as_posix()
    if rel_text == "process/quant-lab" or rel_text.startswith("process/quant-lab/"):
        raise LedgerCompactionError(f"ledger path is forbidden: {rel_text}")
    if not rel_text.startswith("process/"):
        raise LedgerCompactionError(f"ledger path must stay under process/: {rel_text}")
    if ".." in rel.parts:
        raise LedgerCompactionError(f"ledger path contains unsafe traversal: {ledger_path}")
    return resolved


def _default_policy() -> RetentionPolicy:
    return RetentionPolicy()


def _positive_int(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LedgerCompactionError(f"retention policy {key} must be a positive integer")
    return value


def load_retention_policy(path: Path | None = None, *, project_root: Path | None = None) -> RetentionPolicy:
    if path is None:
        if project_root is None:
            return _default_policy()
        path = project_root.resolve() / DEFAULT_POLICY_REL
    if not path.is_file():
        return _default_policy()
    data = parse_yaml_subset(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise LedgerCompactionError("retention policy must be a mapping")
    default = data.get("default") if isinstance(data.get("default"), dict) else data
    allowed = {"schema_version", "default", "ledgers", "window_days", "keep_latest_n_events", "keep_latest_n_cr", "archive_rule"}
    unknown = sorted(str(key) for key in data if key not in allowed)
    if unknown:
        raise LedgerCompactionError("retention policy has unknown fields: " + ", ".join(unknown))
    if data.get("schema_version", 1) != 1:
        raise LedgerCompactionError("retention policy schema_version must be 1")
    return RetentionPolicy(
        window_days=_positive_int(default, "window_days", DEFAULT_WINDOW_DAYS),
        keep_latest_n_events=_positive_int(default, "keep_latest_n_events", DEFAULT_KEEP_LATEST_N_EVENTS),
        keep_latest_n_cr=_positive_int(default, "keep_latest_n_cr", DEFAULT_KEEP_LATEST_N_CR),
        archive_rule=str(default.get("archive_rule") or "summary-index-backup"),
    )


def _parse_timestamp(event: dict[str, Any]) -> datetime | None:
    raw = event.get("timestamp") or event.get("created_at") or event.get("checked_at") or event.get("completed_at") or event.get("spawned_at")
    if not raw:
        return None
    try:
        text = str(raw).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _event_cr_ref(event: dict[str, Any]) -> str:
    for key in ("cr_id", "cr_ref", "active_change"):
        value = event.get(key)
        if value:
            return str(value)
    return ""


def _kept_indices(events: list[dict[str, Any]], policy: RetentionPolicy) -> set[int]:
    kept: set[int] = set(range(max(0, len(events) - policy.keep_latest_n_events), len(events)))
    cutoff = datetime.now(timezone.utc) - timedelta(days=policy.window_days)
    for index, event in enumerate(events):
        timestamp = _parse_timestamp(event)
        if timestamp and timestamp >= cutoff:
            kept.add(index)
    seen_cr: set[str] = set()
    for index in range(len(events) - 1, -1, -1):
        cr_ref = _event_cr_ref(events[index])
        if not cr_ref or cr_ref in seen_cr:
            continue
        seen_cr.add(cr_ref)
        kept.add(index)
        if len(seen_cr) >= policy.keep_latest_n_cr:
            break
    return kept


def _event_range(events: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    if not events:
        return {"first_line": None, "last_line": None, "first_event_id": "", "last_event_id": ""}
    first = events[0]
    last = events[-1]
    return {
        "first_line": first.get("_line_no"),
        "last_line": last.get("_line_no"),
        "first_event_id": first.get("event_id") or first.get("dispatch_id") or first.get("run_id") or "",
        "last_event_id": last.get("event_id") or last.get("dispatch_id") or last.get("run_id") or "",
    }


def plan_ledger_compaction(
    ledger_path: Path,
    *,
    project_root: Path,
    policy: RetentionPolicy | None = None,
    ledger_type: str = "",
) -> CompactPlan:
    root = project_root.resolve()
    safe_path = guard_ledger_path(root, ledger_path)
    events, errors = event_ledger.load_events(safe_path)
    if errors:
        raise LedgerCompactionError("; ".join(errors))
    policy = policy or _default_policy()
    if not events:
        return CompactPlan(root, safe_path, ledger_type or _infer_ledger_type(safe_path), policy, 0, 0, 0, file_hash(safe_path), (), (), ("event ledger is empty",))
    kept = _kept_indices(events, policy)
    kept_events = tuple(_clean_event(event) for index, event in enumerate(events) if index in kept)
    archived_events = tuple(_clean_event(event) for index, event in enumerate(events) if index not in kept)
    return CompactPlan(
        project_root=root,
        ledger_path=safe_path,
        ledger_type=ledger_type or _infer_ledger_type(safe_path),
        policy=policy,
        total_events=len(events),
        keep_count=len(kept_events),
        archive_count=len(archived_events),
        source_hash=file_hash(safe_path),
        kept_events=kept_events,
        archived_events=archived_events,
    )


def _infer_ledger_type(path: Path) -> str:
    for ledger_type, rel in event_ledger.KNOWN_LEDGER_RELS.items():
        if path.name == rel.name:
            return ledger_type
    name = path.name.upper()
    if "CR-LEDGER" in name:
        return "cr"
    if "STORY-LEDGER" in name:
        return "story"
    if "READ-EXPANSION" in name:
        return "read_expansion"
    return "generic"


def _archive_paths(plan: CompactPlan, *, created_at: str) -> tuple[Path, Path, Path]:
    stamp = created_at.replace(":", "").replace("+", "Z").replace("-", "")
    archive_root = plan.project_root / ARCHIVE_ROOT_REL
    summary = archive_root / plan.ledger_type / f"{plan.ledger_path.stem}-{stamp}.summary.json"
    backup = archive_root / "backups" / f"{plan.ledger_path.stem}-{plan.source_hash[:12]}-{stamp}.bak.ndjson"
    index = archive_root / "ledger-archive-index.json"
    return summary, backup, index


def _build_summary(plan: CompactPlan, *, created_at: str, backup_ref: str, index_ref: str) -> dict[str, Any]:
    event_types: dict[str, int] = {}
    ids: list[str] = []
    for event in plan.archived_events:
        event_type = str(event.get("event_type") or "-")
        event_types[event_type] = event_types.get(event_type, 0) + 1
        event_id = event.get("event_id") or event.get("dispatch_id") or event.get("run_id")
        if event_id and len(ids) < 20:
            ids.append(str(event_id))
    return {
        "schema_version": 1,
        "created_at": created_at,
        "source_ledger": _rel(plan.project_root, plan.ledger_path),
        "ledger_type": plan.ledger_type,
        "retention": {
            "window_days": plan.policy.window_days,
            "keep_latest_n_events": plan.policy.keep_latest_n_events,
            "keep_latest_n_cr": plan.policy.keep_latest_n_cr,
        },
        "range": _event_range(plan.archived_events),
        "event_count": plan.archive_count,
        "kept_event_count": plan.keep_count,
        "hash_before": plan.source_hash,
        "event_type_counts": event_types,
        "sample_event_ids": ids,
        "backup_ref": backup_ref,
        "index_ref": index_ref,
        "restore_hint": f"restore from {backup_ref} after verifying hash_before={plan.source_hash}",
    }


def _marker_event(plan: CompactPlan, *, created_at: str, summary_ref: str, index_ref: str, backup_ref: str) -> dict[str, Any]:
    return {
        "event_id": f"ledger-compacted-{plan.source_hash[:12]}",
        "event_type": MARKER_EVENT_TYPE,
        "timestamp": created_at,
        "source_ledger": _rel(plan.project_root, plan.ledger_path),
        "ledger_type": plan.ledger_type,
        "archive_ref": summary_ref,
        "index_ref": index_ref,
        "backup_ref": backup_ref,
        "range": _event_range(plan.archived_events),
        "event_count": plan.archive_count,
        "hash_before": plan.source_hash,
        "restore_hint": f"copy {backup_ref} back to {plan.ledger_path.name}",
    }


def _write_ndjson(path: Path, events: tuple[dict[str, Any], ...]) -> None:
    payload = "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events)
    path.write_text(payload, encoding="utf-8")


def _load_index(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": 1, "entries": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("entries"), list):
        raise LedgerCompactionError(f"archive index is invalid: {path}")
    return data


def apply_compaction(plan: CompactPlan) -> dict[str, Any]:
    if file_hash(plan.ledger_path) != plan.source_hash:
        raise LedgerCompactionError("ledger hash changed before apply; aborting without writes")
    if not plan.will_write:
        return {"status": "noop", "archive_count": 0, "source_ledger": _rel(plan.project_root, plan.ledger_path)}

    created_at = now_utc()
    summary_path, backup_path, index_path = _archive_paths(plan, created_at=created_at)
    summary_ref = _rel(plan.project_root, summary_path)
    backup_ref = _rel(plan.project_root, backup_path)
    index_ref = _rel(plan.project_root, index_path)
    original_payload = plan.ledger_path.read_bytes()
    marker = _marker_event(
        plan,
        created_at=created_at,
        summary_ref=summary_ref,
        index_ref=index_ref,
        backup_ref=backup_ref,
    )
    compacted_events = (*plan.kept_events, marker)

    try:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_bytes(original_payload)
        summary = _build_summary(plan, created_at=created_at, backup_ref=backup_ref, index_ref=index_ref)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        entry = {
            "created_at": created_at,
            "source_ledger": _rel(plan.project_root, plan.ledger_path),
            "ledger_type": plan.ledger_type,
            "range": summary["range"],
            "event_count": plan.archive_count,
            "kept_event_count": plan.keep_count,
            "hash_before": plan.source_hash,
            "hash_after": "",
            "summary_ref": summary_ref,
            "backup_ref": backup_ref,
            "restore_hint": summary["restore_hint"],
        }
        _write_ndjson(plan.ledger_path, compacted_events)
        hash_after = file_hash(plan.ledger_path)
        entry["hash_after"] = hash_after
        errors, _warnings = event_ledger.validate_event_ledger(plan.ledger_path, ledger_type=plan.ledger_type)
        if errors:
            raise LedgerCompactionError("post-apply event check failed: " + "; ".join(errors))
        index = _load_index(index_path)
        index["entries"].append(entry)
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"status": "applied", **entry, "index_ref": index_ref}
    except Exception:
        plan.ledger_path.write_bytes(original_payload)
        raise


def select_ledgers(selector: str, *, project_root: Path) -> list[tuple[Path, str]]:
    root = project_root.resolve()
    if selector == "all":
        selected: list[tuple[Path, str]] = []
        seen: set[Path] = set()
        for ledger_type, rel in sorted(KNOWN_LEDGER_RELS.items()):
            path = root / rel
            resolved = path.resolve()
            if path.is_file() and resolved not in seen:
                seen.add(resolved)
                selected.append((path, _infer_ledger_type(path)))
        return selected
    if selector in event_ledger.KNOWN_LEDGER_RELS:
        return [(root / event_ledger.KNOWN_LEDGER_RELS[selector], selector)]
    path = guard_ledger_path(root, Path(selector))
    return [(path, _infer_ledger_type(path))]


def format_plan(plan: CompactPlan, *, apply: bool = False) -> str:
    mode = "APPLY" if apply else "DRY-RUN"
    lines = [
        f"Ledger Compact {mode}",
        f"- ledger: {_rel(plan.project_root, plan.ledger_path)}",
        f"- ledger_type: {plan.ledger_type}",
        f"- total_events: {plan.total_events}",
        f"- keep_events: {plan.keep_count}",
        f"- archive_events: {plan.archive_count}",
        f"- source_hash: {plan.source_hash}",
        f"- retention: window_days={plan.policy.window_days}, keep_latest_n_events={plan.policy.keep_latest_n_events}, keep_latest_n_cr={plan.policy.keep_latest_n_cr}",
    ]
    if not apply:
        lines.append("- writes: none; pass --apply to create backup, archive summary, archive index, and compact marker")
    for warning in plan.warnings:
        lines.append(f"- WARN: {warning}")
    return "\n".join(lines)


def _print_help() -> None:
    print(
        "usage: meta-flow ledger compact --ledger <type|path|all> [--policy PATH] [--project-root PATH] [--apply]\n\n"
        "Commands:\n"
        "  compact  Plan or apply retention/archive compaction for process NDJSON event ledgers.\n\n"
        "Safety:\n"
        "  Defaults to dry-run and writes nothing. Use --apply to write backup, archive summary,\n"
        "  archive index, compacted ledger marker, and post-apply compatibility checks.\n"
        "  This command does not render STATE.current.json or replace meta-flow state compact.\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return 0
    command = args[0]
    if command != "compact":
        raise SystemExit(f"未知 ledger 命令: {command}. 目前支持: compact")
    parser = argparse.ArgumentParser(
        prog="meta-flow ledger compact",
        description=(
            "Plan or apply retention/archive compaction for process NDJSON event ledgers. "
            "Dry-run is the default; --apply writes backup, archive summary, archive index, and compact marker."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--ledger", required=True, help="Known type, explicit process ledger path, or all.")
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(args[1:])
    root = parsed.project_root.resolve()
    try:
        policy = load_retention_policy(parsed.policy, project_root=root)
        plans = [
            plan_ledger_compaction(path, project_root=root, policy=policy, ledger_type=ledger_type)
            for path, ledger_type in select_ledgers(parsed.ledger, project_root=root)
        ]
        if not plans:
            print("Ledger Compact DRY-RUN")
            print("- selected ledgers: 0")
            return 0
        for plan in plans:
            print(format_plan(plan, apply=parsed.apply))
            if parsed.apply:
                result = apply_compaction(plan)
                print("Apply Result: " + json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except LedgerCompactionError as exc:
        print(f"Ledger Compact FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
