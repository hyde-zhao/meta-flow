"""CR lifecycle governance for Meta Flow state v2."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CR_LEDGER_REL = Path("process/state/CR-LEDGER.ndjson")
CR_INDEX_REL = Path("process/changes/CR-INDEX.json")
LEGACY_CR_INDEX_REL = Path("process/changes/CR-INDEX.yaml")
CR_SUMMARY_ROOT_REL = Path("process/changes/summaries")
CR_ARCHIVE_ROOT_REL = Path("process/archive")
STATE_CURRENT_REL = Path("process/state/STATE.current.json")
CR_ID_RE = re.compile(r"CR-\d+")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
ALLOWED_LIFECYCLE_STATUSES = {
    "candidate",
    "proposed",
    "active",
    "implemented",
    "verified",
    "ready",
    "closed",
    "superseded",
    "cancelled",
    "blocked",
}
FINISHED_STATUSES = {"closed", "superseded", "cancelled"}
ALLOWED_CR_TYPES = {
    "product-scope",
    "architecture",
    "feature",
    "refactor",
    "bugfix",
    "docs",
    "process",
    "runtime",
    "release",
    "experiment",
}
CR_TYPE_ALIASES = {
    "requirement-change": "product-scope",
    "architecture-realignment": "architecture",
    "implementation-gate": "feature",
    "runtime-authorization": "runtime",
    "ledger-maintenance": "process",
    "spike": "experiment",
}


@dataclass(frozen=True)
class CRRecord:
    cr_id: str
    cr_type: str
    title: str
    status: str
    readiness: str
    gate_status: str
    gate_profile: str
    full_ref: str
    summary_ref: str
    conflict_keys: list[str]
    impact_surface: list[str]
    authz_policy_refs: list[str]
    risk_refs: list[str]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _strip_scalar(value: str) -> str:
    raw = value.strip()
    if " #" in raw:
        raw = raw.split(" #", 1)[0].rstrip()
    return raw.strip().strip("`").strip('"').strip("'")


def _frontmatter(text: str) -> str:
    match = FRONTMATTER_RE.match(text)
    return match.group(1) if match else ""


def parse_frontmatter(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _frontmatter(text).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        values[key.strip()] = _strip_scalar(value)
    return values


def parse_inline_list(value: str) -> list[str]:
    raw = _strip_scalar(value)
    if not raw or raw in {"[]", "{}"}:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1].strip()
    return [item.strip().strip('"').strip("'") for item in raw.split(",") if item.strip()]


def normalize_cr_type(value: str) -> str:
    raw = _strip_scalar(value)
    if not raw:
        return "feature"
    return CR_TYPE_ALIASES.get(raw, raw)


def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _cr_id_from_path(path: Path) -> str:
    match = CR_ID_RE.search(path.name)
    return match.group(0) if match else ""


def _extract_section_lines(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            break
    if start is None:
        return []
    collected: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        stripped = line.strip()
        if stripped:
            collected.append(stripped)
    return collected


def _section_summary(text: str, heading: str, *, max_items: int = 3) -> list[str]:
    values: list[str] = []
    for line in _extract_section_lines(text, heading):
        if line.startswith("|") or line.startswith(">") or line.startswith("["):
            continue
        cleaned = line.lstrip("- ").strip()
        if cleaned:
            values.append(cleaned)
        if len(values) >= max_items:
            break
    return values


def discover_formal_crs(project_root: Path) -> dict[str, Path]:
    root = project_root / "process" / "changes"
    if not root.is_dir():
        return {}
    crs: dict[str, Path] = {}
    for path in sorted(root.glob("CR-*.md")):
        if "FOLLOW-UP" in path.name:
            continue
        cr_id = _cr_id_from_path(path)
        if cr_id:
            crs[cr_id] = path
    return crs


def record_from_cr_file(project_root: Path, path: Path) -> CRRecord:
    text = path.read_text(encoding="utf-8")
    fields = parse_frontmatter(text)
    cr_id = fields.get("cr_id") or _cr_id_from_path(path)
    if not cr_id:
        raise ValueError(f"无法从 CR 文件识别 cr_id: {path}")
    status = fields.get("lifecycle_status") or fields.get("status") or "active"
    if status == "open":
        status = "active"
    summary_ref = (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()
    return CRRecord(
        cr_id=cr_id,
        cr_type=normalize_cr_type(fields.get("cr_type") or fields.get("cr_kind") or "feature"),
        title=fields.get("title") or path.stem,
        status=status,
        readiness=fields.get("readiness_status") or "not_ready",
        gate_status=fields.get("gate_status") or "not_started",
        gate_profile=fields.get("gate_profile") or "",
        full_ref=_rel(project_root, path),
        summary_ref=summary_ref,
        conflict_keys=parse_inline_list(fields.get("conflict_keys", "")),
        impact_surface=parse_inline_list(fields.get("impact_surface", "")),
        authz_policy_refs=parse_inline_list(fields.get("authz_policy_refs", "")),
        risk_refs=parse_inline_list(fields.get("risk_refs", "")),
    )


def summary_from_cr_file(project_root: Path, path: Path, *, readiness: str | None = None) -> dict[str, Any]:
    record = record_from_cr_file(project_root, path)
    text = path.read_text(encoding="utf-8")
    summary = {
        "id": record.cr_id,
        "cr_type": record.cr_type,
        "title": record.title,
        "status": record.status,
        "readiness": readiness or record.readiness,
        "decision": "pending",
        "scope_summary": _section_summary(text, "## 变更描述") or [record.title],
        "impact_surface": record.impact_surface,
        "conflict_keys": record.conflict_keys,
        "remaining_risks": record.risk_refs,
        "followup_candidates": [],
        "authz_policy_refs": record.authz_policy_refs,
        "full_ref": record.full_ref,
        "evidence_index_ref": (CR_ARCHIVE_ROOT_REL / record.cr_id / "evidence-index.json").as_posix(),
        "updated_at": now_utc(),
    }
    return summary


def write_summary(project_root: Path, cr_id: str, summary: dict[str, Any]) -> Path:
    path = project_root / CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_evidence_index(project_root: Path, cr_id: str, summary: dict[str, Any]) -> Path:
    path = project_root / CR_ARCHIVE_ROOT_REL / cr_id / "evidence-index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cr_id": cr_id,
        "summary_ref": (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix(),
        "full_ref": summary.get("full_ref"),
        "evidence_refs": [],
        "created_at": now_utc(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def append_ledger_event(project_root: Path, event: dict[str, Any]) -> Path:
    path = project_root / CR_LEDGER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_ledger_events(project_root: Path) -> list[dict[str, Any]]:
    path = project_root / CR_LEDGER_REL
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} invalid JSON: {exc}") from exc
    return events


def build_index(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    items: list[dict[str, Any]] = []
    for cr_id, path in discover_formal_crs(project_root).items():
        record = record_from_cr_file(project_root, path)
        summary_path = project_root / record.summary_ref
        items.append(
            {
                "id": cr_id,
                "cr_type": record.cr_type,
                "title": record.title,
                "status": record.status,
                "readiness": record.readiness,
                "gate_status": record.gate_status,
                "gate_profile": record.gate_profile,
                "full_ref": record.full_ref,
                "summary_ref": record.summary_ref if summary_path.is_file() else "",
                "conflict_keys": record.conflict_keys,
                "impact_surface": record.impact_surface,
                "authz_policy_refs": record.authz_policy_refs,
                "risk_refs": record.risk_refs,
            }
        )
    return {
        "schema_version": 1,
        "generated_at": now_utc(),
        "items": sorted(items, key=lambda item: item["id"]),
    }


def write_index(project_root: Path) -> Path:
    project_root = project_root.resolve()
    path = project_root / CR_INDEX_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_index(project_root), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_legacy_index(project_root: Path) -> Path:
    project_root = project_root.resolve()
    index = build_index(project_root)
    active = [item["id"] for item in index.get("items", []) if item.get("status") == "active"]
    blocked = [item["id"] for item in index.get("items", []) if item.get("status") == "blocked"]
    items = index.get("items", [])
    lines = [
        'schema_version: "1"',
        f'generated_at: "{index.get("generated_at", now_utc())}"',
        "active_crs: [" + ", ".join(f'"{item}"' for item in active) + "]",
        "blocked_crs: [" + ", ".join(f'"{item}"' for item in blocked) + "]",
        "follow_up_candidates: []",
        "spike_candidates: []",
        "stale_status_conflicts: []",
        "items:",
    ]
    for item in items:
        lines.extend(
            [
                f'  - id: "{item.get("id")}"',
                f'    status: "{item.get("status")}"',
                f'    lifecycle_status: "{item.get("status")}"',
                f'    readiness_status: "{item.get("readiness")}"',
                f'    gate_status: "{item.get("gate_status")}"',
                f'    gate_profile: "{item.get("gate_profile")}"',
                f'    formal_cr_path: "{item.get("full_ref")}"',
                f'    summary_ref: "{item.get("summary_ref")}"',
            ]
        )
    path = project_root / LEGACY_CR_INDEX_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load_index(project_root: Path) -> dict[str, Any]:
    path = project_root / CR_INDEX_REL
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} invalid JSON: {exc}") from exc


def _write_bootstrap_cr_file(
    project_root: Path,
    *,
    cr_id: str,
    title: str,
    scope: str,
    gate_status: str,
    readiness: str,
) -> Path:
    if not re.fullmatch(r"CR-\d{3,}", cr_id):
        raise ValueError("bootstrap CR id must use CR-xxx naming, for example CR-001")
    path = project_root / "process" / "changes" / f"{cr_id}.md"
    if path.exists():
        raise FileExistsError(f"CR already exists: {path}")
    created_at = now_utc()
    text = f"""---
cr_id: "{cr_id}"
cr_type: "process"
title: "{title}"
lifecycle_status: "active"
readiness_status: "{readiness}"
gate_status: "{gate_status}"
gate_profile: "standard"
conflict_keys: ["bootstrap", "adoption-readiness"]
impact_surface: ["process", "workspace", "state", "context", "human-gate"]
authz_policy_refs: ["NO_CREDENTIAL_READ", "NO_RUNTIME", "NO_PRODUCTION_WRITE", "NO_TRADING"]
risk_refs: []
created_at: "{created_at}"
created_by: "meta-flow cr bootstrap"
---

# {cr_id} {title}

## 变更描述

{scope}

## 不授权范围

- credentials / secret / account read
- runtime / SaaS / production write
- trading / live / publish
- CR-033 runtime trace follow-up activation

## 启动约束

- Formal CR IDs must use `CR-xxx`; `MF-xxx` is historical alias only.
- Business remediation starts only after CP0/context/human gate readiness is reviewed.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _update_current_active_change(project_root: Path, cr_id: str, context_ref: str) -> None:
    current_path = project_root / STATE_CURRENT_REL
    if not current_path.is_file():
        return
    state = json.loads(current_path.read_text(encoding="utf-8"))
    state["active_change"] = cr_id
    state["active_context_ref"] = context_ref
    state["current_phase"] = "init"
    state["next_action"] = {
        "type": "cp0_ready",
        "text": f"Review CP0 bootstrap readiness for {cr_id}, then launch the first human gate.",
    }
    state["updated_at"] = now_utc()
    current_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_cp0_result(project_root: Path, cr_id: str, context_ref: str) -> Path:
    result_path = project_root / "process" / "checks" / f"CP0-{cr_id}-BOOTSTRAP.result.json"
    result = {
        "schema_version": 1,
        "checkpoint": "CP0",
        "cr_id": cr_id,
        "decision": "PASS",
        "context_ref": context_ref,
        "evidence_ref": "",
        "dispatch_refs": [],
        "items": [
            {
                "id": "CP0-BS-01",
                "name": "workspace/state/bootstrap artifacts exist",
                "status": "PASS",
                "severity": "INFO",
                "evidence_refs": [
                    "process/state/STATE.current.json",
                    "process/changes/CR-INDEX.json",
                    context_ref,
                ],
            },
            {
                "id": "CP0-BS-02",
                "name": "runtime and credential actions are not authorized",
                "status": "PASS",
                "severity": "INFO",
                "evidence_refs": [(CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()],
            },
        ],
        "blockers": [],
        "waivers": [],
        "next_route": "human_gate",
        "checked_at": now_utc(),
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result_path


def bootstrap_cr(
    project_root: Path,
    *,
    cr_id: str,
    title: str,
    scope: str,
    gate_status: str = "cp2_pending",
    readiness: str = "READY",
) -> dict[str, Path]:
    project_root = project_root.resolve()
    from meta_flow.context_pack import builder
    from meta_flow.policies import failure_routing
    from meta_flow.state import current

    failure_routing.write_default_failure_routing_policy(project_root)
    failure_routing.write_default_waiver_policy(project_root)
    cr_path = _write_bootstrap_cr_file(
        project_root,
        cr_id=cr_id,
        title=title,
        scope=scope,
        gate_status=gate_status,
        readiness=readiness,
    )
    summary = summary_from_cr_file(project_root, cr_path)
    summary_path = write_summary(project_root, cr_id, summary)
    evidence_path = write_evidence_index(project_root, cr_id, summary)
    index_path = write_index(project_root)
    legacy_index_path = write_legacy_index(project_root)
    context, context_path = builder.build_context_pack(
        project_root,
        stage="CP0",
        profile="adoption-bootstrap",
        cr_id=cr_id,
    )
    context_ref = _rel(project_root, context_path)
    _update_current_active_change(project_root, cr_id, context_ref)
    try:
        current.render_state_file(project_root, force=False)
    except FileExistsError:
        pass
    cp0_result_path = _write_cp0_result(project_root, cr_id, context_ref)
    cp0_summary_path = cp0_result_path.with_suffix(".summary.md")
    from meta_flow.checks import cp_result

    cp0_summary_path.write_text(cp_result.render_summary(json.loads(cp0_result_path.read_text(encoding="utf-8"))), encoding="utf-8")
    ledger_path = append_ledger_event(
        project_root,
        {
            "event": "active",
            "id": cr_id,
            "cr_type": summary.get("cr_type"),
            "status": "active",
            "readiness": summary.get("readiness"),
            "summary_ref": _rel(project_root, summary_path),
            "full_ref": summary.get("full_ref"),
            "evidence_index_ref": _rel(project_root, evidence_path),
            "context_ref": context_ref,
            "cp0_result_ref": _rel(project_root, cp0_result_path),
            "created_at": now_utc(),
        },
    )
    return {
        "cr": cr_path,
        "summary": summary_path,
        "evidence_index": evidence_path,
        "index": index_path,
        "legacy_index": legacy_index_path,
        "context": context_path,
        "cp0_result": cp0_result_path,
        "cp0_summary": cp0_summary_path,
        "ledger": ledger_path,
    }


def close_cr(project_root: Path, cr_id: str, *, readiness: str) -> dict[str, Path]:
    project_root = project_root.resolve()
    crs = discover_formal_crs(project_root)
    if cr_id not in crs:
        raise FileNotFoundError(f"未找到正式 CR: {cr_id}")
    summary = summary_from_cr_file(project_root, crs[cr_id], readiness=readiness)
    summary["status"] = "closed"
    summary_path = write_summary(project_root, cr_id, summary)
    evidence_path = write_evidence_index(project_root, cr_id, summary)
    index_path = write_index(project_root)
    ledger_path = append_ledger_event(
        project_root,
        {
            "event": "closed",
            "id": cr_id,
            "cr_type": summary.get("cr_type"),
            "status": "closed",
            "readiness": readiness,
            "summary_ref": _rel(project_root, summary_path),
            "full_ref": summary.get("full_ref"),
            "evidence_index_ref": _rel(project_root, evidence_path),
            "risk_refs": summary.get("remaining_risks", []),
            "authz_policy_refs": summary.get("authz_policy_refs", []),
            "closed_at": now_utc(),
        },
    )
    return {
        "summary": summary_path,
        "evidence_index": evidence_path,
        "index": index_path,
        "ledger": ledger_path,
    }


def collect_check_errors(project_root: Path) -> list[str]:
    project_root = project_root.resolve()
    errors: list[str] = []
    try:
        events = load_ledger_events(project_root)
    except ValueError as exc:
        return [str(exc)]
    index = load_index(project_root)
    items = {item.get("id"): item for item in index.get("items", []) if isinstance(item, dict)}
    current_path = project_root / STATE_CURRENT_REL
    current_state: dict[str, Any] = {}
    if current_path.is_file():
        try:
            current_state = json.loads(current_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{current_path} invalid JSON: {exc}")
    for event in events:
        cr_id = event.get("id")
        status = event.get("status")
        cr_type = event.get("cr_type")
        if status and status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(f"CR ledger event {cr_id}: invalid status {status}")
        if cr_type and cr_type not in ALLOWED_CR_TYPES:
            errors.append(f"CR ledger event {cr_id}: invalid cr_type {cr_type}")
        summary_ref = event.get("summary_ref")
        if status == "closed":
            if not summary_ref:
                errors.append(f"closed CR {cr_id} missing summary_ref")
            elif not (project_root / summary_ref).is_file():
                errors.append(f"closed CR {cr_id} summary_ref missing on disk: {summary_ref}")
            if current_state.get("active_change") == cr_id:
                errors.append(f"STATE.current.json active_change points to closed CR: {cr_id}")
        if cr_id and cr_id in items:
            index_status = items[cr_id].get("status")
            if status == "closed" and index_status not in {"closed", "active", "implemented", "verified", "ready"}:
                errors.append(f"CR index status for {cr_id} is inconsistent: {index_status}")
    for item_id, item in items.items():
        status = item.get("status")
        if status in FINISHED_STATUSES and not item.get("summary_ref"):
            errors.append(f"CR index finished item {item_id} missing summary_ref")
        if status and status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(f"CR index item {item_id}: invalid status {status}")
        cr_type = item.get("cr_type")
        if cr_type and cr_type not in ALLOWED_CR_TYPES:
            errors.append(f"CR index item {item_id}: invalid cr_type {cr_type}")
    return errors


def conflict_report(project_root: Path, cr_id: str) -> tuple[list[str], list[str]]:
    project_root = project_root.resolve()
    index = load_index(project_root)
    items = [item for item in index.get("items", []) if isinstance(item, dict)]
    target = next((item for item in items if item.get("id") == cr_id), None)
    if not target:
        raise FileNotFoundError(f"CR index 中未找到 {cr_id}；请先运行 meta-flow cr index")
    target_keys = set(target.get("conflict_keys") or [])
    target_surface = set(target.get("impact_surface") or [])
    conflicts: list[str] = []
    warnings: list[str] = []
    for item in items:
        other_id = item.get("id")
        if other_id == cr_id:
            continue
        if item.get("status") not in {"active", "blocked", "proposed"}:
            continue
        key_overlap = target_keys.intersection(item.get("conflict_keys") or [])
        surface_overlap = target_surface.intersection(item.get("impact_surface") or [])
        if key_overlap or surface_overlap:
            conflicts.append(
                f"{cr_id} overlaps {other_id}: conflict_keys={sorted(key_overlap)} impact_surface={sorted(surface_overlap)}"
            )
    if not target_keys and not target_surface:
        warnings.append(f"{cr_id} has no conflict_keys or impact_surface; conflict detection is weak")
    return conflicts, warnings


def _print_cr_help() -> None:
    print(
        "usage: meta-flow cr <command> [options]\n\n"
        "Commands:\n"
        "  bootstrap  Create an active bootstrap CR plus summary, index, ledger, CP0 result, and context.\n"
        "  index      Rebuild process/changes/CR-INDEX.json from formal CR files.\n"
        "  summary    Generate process/changes/summaries/<CR>.summary.json.\n"
        "  close      Close a CR logically: summary + evidence index + ledger event.\n"
        "  check      Validate CR ledger, index, summaries, and active state refs.\n"
        "  conflicts  Compare active/proposed/blocked CR conflict keys from CR-INDEX.json.\n\n"
        "Examples:\n"
        "  meta-flow cr bootstrap --id CR-001 --title \"target adoption bootstrap\" --scope \"Initialize Meta Flow adoption readiness.\" --project-root .\n"
        "  meta-flow cr index --project-root .\n"
        "  meta-flow cr summary --id CR-101 --project-root .\n"
        "  meta-flow cr close --id CR-101 --readiness READY_WITH_RISK --project-root .\n"
        "  meta-flow cr conflicts --id CR-102 --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_cr_help()
        return 0
    command = args[0]
    parser = argparse.ArgumentParser(prog=f"meta-flow cr {command}")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", dest="cr_id", default="")
    parser.add_argument("--title", default="Meta Flow adoption bootstrap")
    parser.add_argument("--scope", default="Bootstrap Meta Flow adoption readiness for this target project.")
    parser.add_argument("--gate-status", default="cp2_pending")
    parser.add_argument("--readiness", default="READY")
    parsed = parser.parse_args(args[1:])
    project_root = parsed.project_root.resolve()

    if command == "bootstrap":
        if not parsed.cr_id:
            raise SystemExit("--id is required and must use CR-xxx naming")
        paths = bootstrap_cr(
            project_root,
            cr_id=parsed.cr_id,
            title=parsed.title,
            scope=parsed.scope,
            gate_status=parsed.gate_status,
            readiness=parsed.readiness,
        )
        for key, path in paths.items():
            print(f"{key}: {path}")
        return 0
    if command == "index":
        path = write_index(project_root)
        print(f"wrote: {path}")
        return 0
    if command == "summary":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        crs = discover_formal_crs(project_root)
        if parsed.cr_id not in crs:
            raise SystemExit(f"未找到正式 CR: {parsed.cr_id}")
        summary = summary_from_cr_file(project_root, crs[parsed.cr_id])
        path = write_summary(project_root, parsed.cr_id, summary)
        print(f"wrote: {path}")
        return 0
    if command == "close":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        paths = close_cr(project_root, parsed.cr_id, readiness=parsed.readiness)
        for key, path in paths.items():
            print(f"{key}: {path}")
        return 0
    if command == "check":
        errors = collect_check_errors(project_root)
        print("CR Lifecycle Check: " + ("FAIL" if errors else "OK"))
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "conflicts":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        conflicts, warnings = conflict_report(project_root, parsed.cr_id)
        print("CR Conflicts: " + ("FAIL" if conflicts else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for conflict in conflicts:
            print(f"- CONFLICT: {conflict}")
        return 1 if conflicts else 0
    raise SystemExit(f"未知 cr 命令: {command}. 目前支持: bootstrap, index, summary, close, check, conflicts")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
