"""Generic event ledger support for Meta Flow process evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KNOWN_LEDGER_RELS = {
    "checkpoint": Path("process/state/CHECKPOINT-LEDGER.ndjson"),
    "handoff": Path("process/state/HANDOFF-LEDGER.ndjson"),
    "dispatch": Path("process/state/AGENT-DISPATCH-LEDGER.ndjson"),
    "run": Path("process/state/RUN-LEDGER.ndjson"),
    "gate": Path("process/state/GATE-LEDGER.ndjson"),
}

LEDGER_REQUIRED_FIELDS = {
    "checkpoint": ("event_id", "event_type", "checkpoint", "decision", "result_ref"),
    "handoff": ("event_id", "event_type", "stage", "from_role", "to_role", "context_ref", "status"),
    "dispatch": ("dispatch_id", "event_type", "canonical_role", "tool_name", "status"),
    "run": ("event_id", "event_type", "command", "result"),
    "gate": ("event_id", "event_type", "gate", "status"),
}
COMPACT_MARKER_REQUIRED_FIELDS = (
    "event_id",
    "event_type",
    "timestamp",
    "source_ledger",
    "archive_ref",
    "index_ref",
    "backup_ref",
    "event_count",
    "hash_before",
)
DISPATCH_EVENT_REQUIRED_FIELDS = {
    "dispatch_not_required": (
        "dispatch_id",
        "event_type",
        "canonical_role",
        "dispatch_mode",
        "reason",
        "status",
    ),
    "inline_fallback": (
        "dispatch_id",
        "event_type",
        "canonical_role",
        "dispatch_mode",
        "fallback_reason",
        "approved_by",
        "status",
    ),
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} invalid JSON: {exc}") from exc


def _ledger_type_from_path(path: Path) -> str:
    name = path.name.upper()
    if "CHECKPOINT" in name:
        return "checkpoint"
    if "HANDOFF" in name:
        return "handoff"
    if "DISPATCH" in name or "AGENT" in name:
        return "dispatch"
    if "RUN" in name:
        return "run"
    if "GATE" in name:
        return "gate"
    return "generic"


def ledger_path(project_root: Path, ledger_type: str) -> Path:
    rel = KNOWN_LEDGER_RELS.get(ledger_type)
    if rel is None:
        return project_root / ledger_type
    return project_root / rel


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_events(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.is_file():
        return [], [f"event ledger missing: {path}"]
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_no}: invalid JSON: {exc}")
            continue
        if not isinstance(event, dict):
            errors.append(f"line {line_no}: event must be an object")
            continue
        event["_line_no"] = line_no
        events.append(event)
    return events, errors


def append_event(path: Path, event: dict[str, Any]) -> Path:
    if not isinstance(event, dict):
        raise TypeError("event must be an object")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in event.items() if key != "_line_no"}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def build_dispatch_not_required_event(
    *,
    dispatch_id: str,
    canonical_role: str,
    reason: str,
    status: str = "skipped",
    cr_id: str = "",
    checkpoint: str = "",
    result_ref: str = "",
    route_plan_ref: str = "",
    created_at: str = "",
) -> dict[str, Any]:
    event = {
        "dispatch_id": dispatch_id,
        "event_type": "dispatch_not_required",
        "canonical_role": canonical_role,
        "dispatch_mode": "not-required",
        "reason": reason,
        "status": status,
        "created_at": created_at or now_utc(),
    }
    for key, value in {
        "cr_id": cr_id,
        "checkpoint": checkpoint,
        "result_ref": result_ref,
        "route_plan_ref": route_plan_ref,
    }.items():
        if value:
            event[key] = value
    return event


def build_inline_fallback_event(
    *,
    dispatch_id: str,
    canonical_role: str,
    fallback_reason: str,
    approved_by: str,
    status: str = "completed",
    dispatch_trigger: str = "",
    cr_id: str = "",
    checkpoint: str = "",
    result_ref: str = "",
    route_plan_ref: str = "",
    tool_name: str = "host-orchestrator-inline",
    created_at: str = "",
) -> dict[str, Any]:
    event = {
        "dispatch_id": dispatch_id,
        "event_type": "inline_fallback",
        "canonical_role": canonical_role,
        "dispatch_mode": "inline-fallback",
        "fallback_reason": fallback_reason,
        "approved_by": approved_by,
        "tool_name": tool_name,
        "status": status,
        "created_at": created_at or now_utc(),
    }
    for key, value in {
        "cr_id": cr_id,
        "checkpoint": checkpoint,
        "dispatch_trigger": dispatch_trigger,
        "result_ref": result_ref,
        "route_plan_ref": route_plan_ref,
    }.items():
        if value:
            event[key] = value
    return event


def append_dispatch_event(project_root: Path, event: dict[str, Any], *, ledger: Path | None = None) -> Path:
    path = ledger.resolve() if ledger else ledger_path(project_root.resolve(), "dispatch")
    return append_event(path, event)


def validate_event_ledger(path: Path, *, ledger_type: str = "") -> tuple[list[str], list[str]]:
    ledger_type = ledger_type or _ledger_type_from_path(path)
    events, errors = load_events(path)
    warnings: list[str] = []
    if errors:
        return errors, warnings
    if not events:
        warnings.append("event ledger is empty")
        return errors, warnings
    required = LEDGER_REQUIRED_FIELDS.get(ledger_type, ("event_type",))
    seen_ids: set[str] = set()
    for event in events:
        line_no = int(event.get("_line_no") or 0)
        if event.get("event_type") == "ledger_compacted":
            fields = COMPACT_MARKER_REQUIRED_FIELDS
        elif ledger_type == "dispatch":
            fields = DISPATCH_EVENT_REQUIRED_FIELDS.get(str(event.get("event_type") or ""), required)
        else:
            fields = required
        for field in fields:
            if not event.get(field):
                errors.append(f"line {line_no}: missing required field: {field}")
        event_id = str(event.get("event_id") or event.get("dispatch_id") or event.get("run_id") or "")
        if event_id:
            if event_id in seen_ids:
                errors.append(f"line {line_no}: duplicate event id: {event_id}")
            seen_ids.add(event_id)
        else:
            errors.append(f"line {line_no}: missing event_id/dispatch_id/run_id")
        if not any(event.get(field) for field in ("created_at", "checked_at", "spawned_at", "completed_at", "timestamp")):
            warnings.append(f"line {line_no}: event has no timestamp field")
    return errors, warnings


def _print_event_help() -> None:
    print(
        "usage: meta-flow event <append|dispatch-not-required|inline-fallback|check|list> [options]\n\n"
        "Commands:\n"
        "  append  Append one JSON event to an NDJSON ledger.\n"
        "  dispatch-not-required  Append a structured dispatch_not_required event.\n"
        "  inline-fallback        Append a structured inline_fallback dispatch event.\n"
        "  check   Validate a known or generic NDJSON event ledger.\n"
        "  list    Print compact event lines from a ledger.\n\n"
        "Examples:\n"
        "  meta-flow event append --ledger process/state/CHECKPOINT-LEDGER.ndjson --event-file event.json\n"
        "  meta-flow event inline-fallback --dispatch-id ADE-CR045-INLINE-CP6 --canonical-role meta-dev --fallback-reason \"implemented inline\" --approved-by host-orchestrator --project-root .\n"
        "  meta-flow event check --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint\n"
        "  meta-flow event check --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint --mode silent\n"
        "  meta-flow event list --ledger process/state/HANDOFF-LEDGER.ndjson\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_event_help()
        return 0
    command = args[0]
    if command == "append":
        parser = argparse.ArgumentParser(prog="meta-flow event append")
        parser.add_argument("--ledger", type=Path, required=True)
        parser.add_argument("--event-file", type=Path, default=None)
        parser.add_argument("--event-json", default="")
        parsed = parser.parse_args(args[1:])
        if not parsed.event_file and not parsed.event_json:
            raise SystemExit("--event-file or --event-json is required")
        event = _read_json(parsed.event_file) if parsed.event_file else json.loads(parsed.event_json)
        path = append_event(parsed.ledger, event)
        print(f"appended: {path}")
        return 0
    if command == "dispatch-not-required":
        parser = argparse.ArgumentParser(prog="meta-flow event dispatch-not-required")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ledger", type=Path, default=None)
        parser.add_argument("--dispatch-id", required=True)
        parser.add_argument("--canonical-role", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--status", default="skipped")
        parser.add_argument("--cr-id", default="")
        parser.add_argument("--checkpoint", default="")
        parser.add_argument("--result-ref", default="")
        parser.add_argument("--route-plan-ref", default="")
        parsed = parser.parse_args(args[1:])
        event = build_dispatch_not_required_event(
            dispatch_id=parsed.dispatch_id,
            canonical_role=parsed.canonical_role,
            reason=parsed.reason,
            status=parsed.status,
            cr_id=parsed.cr_id,
            checkpoint=parsed.checkpoint,
            result_ref=parsed.result_ref,
            route_plan_ref=parsed.route_plan_ref,
        )
        path = append_dispatch_event(parsed.project_root, event, ledger=parsed.ledger)
        print(f"appended: {path}")
        return 0
    if command == "inline-fallback":
        parser = argparse.ArgumentParser(prog="meta-flow event inline-fallback")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ledger", type=Path, default=None)
        parser.add_argument("--dispatch-id", required=True)
        parser.add_argument("--canonical-role", required=True)
        parser.add_argument("--fallback-reason", required=True)
        parser.add_argument("--approved-by", required=True)
        parser.add_argument("--status", default="completed")
        parser.add_argument("--dispatch-trigger", default="")
        parser.add_argument("--cr-id", default="")
        parser.add_argument("--checkpoint", default="")
        parser.add_argument("--result-ref", default="")
        parser.add_argument("--route-plan-ref", default="")
        parser.add_argument("--tool-name", default="host-orchestrator-inline")
        parsed = parser.parse_args(args[1:])
        event = build_inline_fallback_event(
            dispatch_id=parsed.dispatch_id,
            canonical_role=parsed.canonical_role,
            fallback_reason=parsed.fallback_reason,
            approved_by=parsed.approved_by,
            status=parsed.status,
            dispatch_trigger=parsed.dispatch_trigger,
            cr_id=parsed.cr_id,
            checkpoint=parsed.checkpoint,
            result_ref=parsed.result_ref,
            route_plan_ref=parsed.route_plan_ref,
            tool_name=parsed.tool_name,
        )
        path = append_dispatch_event(parsed.project_root, event, ledger=parsed.ledger)
        print(f"appended: {path}")
        return 0
    if command == "check":
        parser = argparse.ArgumentParser(prog="meta-flow event check")
        parser.add_argument("--ledger", type=Path, required=True)
        parser.add_argument("--type", dest="ledger_type", default="")
        parser.add_argument("--mode", choices=("normal", "silent", "verbose"), default="normal")
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_event_ledger(parsed.ledger, ledger_type=parsed.ledger_type)
        if parsed.mode == "silent":
            if errors:
                print("FAIL: " + "; ".join(errors))
            else:
                print("PASS")
            return 1 if errors else 0
        print("Event Ledger Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "list":
        parser = argparse.ArgumentParser(prog="meta-flow event list")
        parser.add_argument("--ledger", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        events, errors = load_events(parsed.ledger)
        if errors:
            for error in errors:
                print(f"- ERROR: {error}")
            return 1
        for event in events:
            event_id = event.get("event_id") or event.get("dispatch_id") or event.get("run_id") or "-"
            event_type = event.get("event_type") or "-"
            status = event.get("status") or event.get("decision") or event.get("result") or "-"
            print(f"{event_id}\t{event_type}\t{status}")
        return 0
    raise SystemExit(f"未知 event 命令: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
