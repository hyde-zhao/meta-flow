"""Machine-readable checkpoint result schema and summary rendering."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from meta_flow.checks.token_budget import DEFAULT_READ_DENY_PATTERNS
from meta_flow.context_pack import read_expansion
from meta_flow.policies import failure_routing
from meta_flow.state import event_ledger
from meta_flow.state.current import now_utc


CHECKPOINT_LEDGER_REL = Path("process/state/CHECKPOINT-LEDGER.ndjson")
ITEM_STATUSES = {"PASS", "FAIL", "BLOCKED", "N/A", "WAIVED"}
GENERAL_DECISIONS = {"PASS", "FAIL", "BLOCKED", "WAIVED"}
CP7_DECISIONS = GENERAL_DECISIONS | {"PASS_WITH_RISK", "NEEDS_REWORK", "NEEDS_DESIGN_CLARIFICATION"}
SEVERITIES = {"BLOCKER", "HIGH", "MEDIUM", "LOW", "INFO"}
CHECKPOINT_RE = re.compile(r"^CP[0-8]$")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _ref_path(value: Any) -> str:
    if isinstance(value, dict):
        raw = str(value.get("path") or value.get("ref") or "")
    else:
        raw = str(value or "")
    return raw.split("#", 1)[0]


def _matches_any(rel_path: str, patterns: tuple[str, ...]) -> bool:
    from fnmatch import fnmatch

    return any(rel_path == pattern or fnmatch(rel_path, pattern) for pattern in patterns)


def _deny_default_refs(result: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("context_ref", "evidence_ref"):
        path = _ref_path(result.get(key))
        if path and _matches_any(path, DEFAULT_READ_DENY_PATTERNS):
            refs.append(path)
    for item in _as_list(result.get("items")):
        if not isinstance(item, dict):
            continue
        for ref in _as_list(item.get("evidence_refs")):
            path = _ref_path(ref)
            if path and _matches_any(path, DEFAULT_READ_DENY_PATTERNS):
                refs.append(path)
    return sorted(set(refs))


def allowed_decisions(checkpoint: str) -> set[str]:
    if checkpoint == "CP7":
        return CP7_DECISIONS
    return GENERAL_DECISIONS


def load_cp_result(path: Path) -> dict[str, Any]:
    return _read_json(path.resolve())


def validate_cp_result(result_path: Path, *, project_root: Path | None = None) -> tuple[list[str], list[str]]:
    result_path = result_path.resolve()
    if not result_path.is_file():
        return [f"CP result missing: {result_path}"], []
    errors: list[str] = []
    warnings: list[str] = []
    try:
        result = load_cp_result(result_path)
    except ValueError as exc:
        return [str(exc)], []
    root = project_root.resolve() if project_root else result_path.parent.parent.parent

    if result.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    checkpoint = str(result.get("checkpoint") or result.get("checkpoint_id") or "")
    if not CHECKPOINT_RE.fullmatch(checkpoint):
        errors.append(f"checkpoint must be CP0..CP8: {checkpoint or '-'}")
    decision = str(result.get("decision") or "")
    if decision not in allowed_decisions(checkpoint):
        errors.append(f"invalid decision for {checkpoint or 'checkpoint'}: {decision or '-'}")
    for key in ("items", "blockers", "waivers"):
        if key not in result:
            errors.append(f"missing required field: {key}")
    items = result.get("items") or []
    if not isinstance(items, list) or not items:
        errors.append("items must be a non-empty list")
        items = []
    blocking_item_seen = False
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append(f"item {index}: must be an object")
            continue
        for key in ("id", "name", "status", "severity", "evidence_refs"):
            if key not in item:
                errors.append(f"item {index}: missing required field: {key}")
        status = str(item.get("status") or "")
        if status not in ITEM_STATUSES:
            errors.append(f"item {index}: invalid status: {status or '-'}")
        severity = str(item.get("severity") or "")
        if severity not in SEVERITIES:
            errors.append(f"item {index}: invalid severity: {severity or '-'}")
        evidence_refs = item.get("evidence_refs")
        if evidence_refs is not None and not isinstance(evidence_refs, list):
            errors.append(f"item {index}: evidence_refs must be a list")
        if status in {"FAIL", "BLOCKED"} and severity in {"BLOCKER", "HIGH"}:
            blocking_item_seen = True
        if status == "WAIVED" and not item.get("waiver_ref"):
            errors.append(f"item {index}: WAIVED requires waiver_ref")

    blockers = result.get("blockers") or []
    waivers = result.get("waivers") or []
    if not isinstance(blockers, list):
        errors.append("blockers must be a list")
        blockers = []
    if not isinstance(waivers, list):
        errors.append("waivers must be a list")
    if (blocking_item_seen or blockers) and decision in {"PASS", "PASS_WITH_RISK"}:
        errors.append("decision cannot be PASS/PASS_WITH_RISK when blocking items exist")
    if checkpoint in {"CP6", "CP7"}:
        if not result.get("story_id"):
            errors.append(f"{checkpoint} result requires story_id")
        if not result.get("context_ref"):
            errors.append(f"{checkpoint} result requires context_ref")
        if not result.get("evidence_ref"):
            errors.append(f"{checkpoint} result requires evidence_ref")
        if not result.get("dispatch_refs"):
            errors.append(f"{checkpoint} result requires dispatch_refs")
    deny_refs = _deny_default_refs(result)
    if deny_refs:
        read_expansion_refs = [str(item) for item in _as_list(result.get("read_expansion_refs")) if str(item)]
        if not read_expansion_refs:
            errors.append(
                "deny-default references require read_expansion_refs: " + ", ".join(deny_refs)
            )
        elif project_root:
            ledger_events, ledger_errors = read_expansion.load_events(read_expansion.default_ledger_path(root))
            if ledger_errors:
                errors.extend(f"read expansion ledger: {error}" for error in ledger_errors)
            event_ids = {str(event.get("event_id") or "") for event in ledger_events}
            requested_paths = {str(event.get("requested_path") or "") for event in ledger_events if event.get("event_id") in read_expansion_refs}
            missing_events = sorted(set(read_expansion_refs) - event_ids)
            if missing_events:
                errors.append("read_expansion_refs missing from READ-EXPANSION-LEDGER: " + ", ".join(missing_events))
            missing_paths = sorted(path for path in deny_refs if path not in requested_paths)
            if missing_paths:
                errors.append("read_expansion_refs do not cover deny-default refs: " + ", ".join(missing_paths))
    governance_errors, governance_warnings = failure_routing.validate_result_governance(root, result)
    errors.extend(governance_errors)
    warnings.extend(governance_warnings)
    for ref_key in ("context_ref", "evidence_ref"):
        rel = str(result.get(ref_key) or "")
        if rel and project_root and not (root / rel).exists():
            warnings.append(f"{ref_key} not found on disk: {rel}")
    return errors, warnings


def render_summary(result: dict[str, Any]) -> str:
    checkpoint = result.get("checkpoint") or result.get("checkpoint_id") or "-"
    story_id = result.get("story_id") or "-"
    cr_id = result.get("cr_id") or "-"
    decision = result.get("decision") or "-"
    lines = [
        f"# {checkpoint} Summary",
        "",
        f"Decision: {decision}",
        f"Story: {story_id}",
        f"CR: {cr_id}",
        f"Context: {result.get('context_ref') or '-'}",
        f"Evidence: {result.get('evidence_ref') or '-'}",
        f"Dispatch: {', '.join(str(item) for item in _as_list(result.get('dispatch_refs'))) or '-'}",
        "",
        "## Blocking Items",
    ]
    blockers = _as_list(result.get("blockers"))
    if blockers:
        for item in blockers:
            lines.append(f"- {item}")
    else:
        lines.append("None.")
    lines.extend(["", "## Check Items", "", "| ID | Status | Severity | Name |", "|---|---|---|---|"])
    for item in _as_list(result.get("items")):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {item.get('id', '-')} | {item.get('status', '-')} | {item.get('severity', '-')} | {item.get('name', '-')} |"
        )
    lines.extend(["", "## Next", "", str(result.get("next_route") or "-"), ""])
    return "\n".join(lines)


def render_summary_file(result_path: Path, *, output: Path | None = None) -> Path:
    result = load_cp_result(result_path)
    output_path = output.resolve() if output else result_path.with_suffix(".summary.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_summary(result), encoding="utf-8")
    return output_path


def build_checkpoint_event(project_root: Path, result_path: Path) -> dict[str, Any]:
    root = project_root.resolve()
    result_path = result_path.resolve()
    result = load_cp_result(result_path)
    checkpoint = str(result.get("checkpoint") or result.get("checkpoint_id") or "")
    event_id = str(result.get("event_id") or f"{checkpoint}-{result.get('story_id') or result.get('cr_id') or 'global'}")
    return {
        "event_id": event_id,
        "event_type": "checkpoint_result",
        "checkpoint": checkpoint,
        "decision": result.get("decision"),
        "result_ref": _rel(root, result_path),
        "summary_ref": _rel(root, result_path.with_suffix(".summary.md")),
        "story_id": result.get("story_id"),
        "cr_id": result.get("cr_id"),
        "context_ref": result.get("context_ref"),
        "evidence_ref": result.get("evidence_ref"),
        "dispatch_refs": _as_list(result.get("dispatch_refs")),
        "checked_at": result.get("checked_at") or now_utc(),
    }


def append_checkpoint_ledger(project_root: Path, *, result_path: Path, ledger: Path | None = None) -> Path:
    root = project_root.resolve()
    event = build_checkpoint_event(root, result_path)
    ledger_path = ledger.resolve() if ledger else root / CHECKPOINT_LEDGER_REL
    return event_ledger.append_event(ledger_path, event)


def _print_cp_help() -> None:
    print(
        "usage: meta-flow cp <result-check|render-summary|ledger-append> [options]\n\n"
        "Commands:\n"
        "  result-check    Validate a machine-readable CP result JSON.\n"
        "  render-summary  Render a compact Markdown summary from CP result JSON.\n"
        "  ledger-append   Append a checkpoint_result event to CHECKPOINT-LEDGER.ndjson.\n\n"
        "Examples:\n"
        "  meta-flow cp result-check --result process/checks/CP6-STORY.result.json --project-root .\n"
        "  meta-flow cp render-summary --result process/checks/CP6-STORY.result.json\n"
        "  meta-flow cp ledger-append --result process/checks/CP6-STORY.result.json --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_cp_help()
        return 0
    command = args[0]
    if command == "result-check":
        parser = argparse.ArgumentParser(prog="meta-flow cp result-check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--result", dest="result_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_cp_result(parsed.result_path, project_root=parsed.project_root)
        print("CP Result Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "render-summary":
        parser = argparse.ArgumentParser(prog="meta-flow cp render-summary")
        parser.add_argument("--result", dest="result_path", type=Path, required=True)
        parser.add_argument("--output", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        path = render_summary_file(parsed.result_path, output=parsed.output)
        print(f"wrote: {path}")
        return 0
    if command == "ledger-append":
        parser = argparse.ArgumentParser(prog="meta-flow cp ledger-append")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--result", dest="result_path", type=Path, required=True)
        parser.add_argument("--ledger", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        path = append_checkpoint_ledger(parsed.project_root, result_path=parsed.result_path, ledger=parsed.ledger)
        print(f"appended: {path}")
        return 0
    raise SystemExit(f"未知 cp 命令: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
