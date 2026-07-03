"""Generic event ledger support for Meta Flow process evidence."""

from __future__ import annotations

import argparse
import json
import sys
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
        fields = COMPACT_MARKER_REQUIRED_FIELDS if event.get("event_type") == "ledger_compacted" else required
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
        "usage: meta-flow event <append|check|list> [options]\n\n"
        "Commands:\n"
        "  append  Append one JSON event to an NDJSON ledger.\n"
        "  check   Validate a known or generic NDJSON event ledger.\n"
        "  list    Print compact event lines from a ledger.\n\n"
        "Examples:\n"
        "  meta-flow event append --ledger process/state/CHECKPOINT-LEDGER.ndjson --event-file event.json\n"
        "  meta-flow event check --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint\n"
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
    if command == "check":
        parser = argparse.ArgumentParser(prog="meta-flow event check")
        parser.add_argument("--ledger", type=Path, required=True)
        parser.add_argument("--type", dest="ledger_type", default="")
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_event_ledger(parsed.ledger, ledger_type=parsed.ledger_type)
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
