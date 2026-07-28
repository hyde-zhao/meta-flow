"""Generic event ledger support for Meta Flow process evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.project.process_route import _resolve_runtime_path, _resolve_runtime_ref

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
TERMINAL_SUCCESS_STATUSES = frozenset({"completed", "success", "succeeded", "passed"})
TERMINAL_SUCCESS_RESULTS = frozenset({"pass", "success", "succeeded", "completed"})
TERMINAL_ATTEMPT_STATUSES = frozenset(
    {"completed", "success", "succeeded", "passed", "failed", "interrupted", "cancelled", "superseded"}
)
NONTERMINAL_ATTEMPT_STATUSES = frozenset({"submitted", "running", "retrying"})
ALL_ATTEMPT_STATUSES = TERMINAL_ATTEMPT_STATUSES | NONTERMINAL_ATTEMPT_STATUSES


@dataclass(frozen=True)
class ProjectionInputV1:
    """Single, typed input for terminal-success and dispatch projections."""

    events: tuple[Mapping[str, Any], ...]
    ledger_type: str
    dispatch_id: str = ""


@dataclass(frozen=True)
class ProjectionResultV1:
    """Canonical projector result; consumers must not recreate terminal sets."""

    terminal_success: bool
    terminal_event_ids: tuple[str, ...]
    typed_attempt_ids: tuple[str, ...]
    finding_codes: tuple[str, ...]


@dataclass(frozen=True)
class TypedDispatchAttemptV1:
    """The minimum identity required to claim a real or inline dispatch result."""

    event_id: str
    dispatch_id: str
    attempt_id: str
    story_id: str
    canonical_role: str
    checkpoint: str
    mode: str
    status: str
    terminal_result: str
    approval_ref: str = ""


@dataclass(frozen=True)
class HandoffDispatchRecordV1:
    """Canonical parsed handoff dispatch block, without a second YAML parser owner."""

    values: tuple[tuple[str, str], ...]

    def get(self, key: str, default: str = "") -> str:
        return dict(self.values).get(key, default)


def normalize_terminal_status(value: object) -> str:
    """Normalize status exactly once for every terminal-success consumer."""

    return str(value or "").strip().lower()


def typed_dispatch_attempt_from_event(
    event: Mapping[str, Any],
) -> tuple[TypedDispatchAttemptV1 | None, tuple[str, ...]]:
    """把公开 dispatch evidence 适配为唯一的 typed attempt 契约。"""

    required = ("event_id", "dispatch_id", "attempt_id", "story_id", "canonical_role", "checkpoint", "dispatch_mode")
    missing = [field for field in required if not str(event.get(field) or "").strip()]
    if missing:
        return None, tuple(f"MISSING_TYPED_{field.upper()}" for field in missing)
    mode = str(event["dispatch_mode"])
    approval_ref = str(event.get("approval_ref") or event.get("approved_by") or "")
    if mode == "inline-fallback" and not approval_ref.strip():
        return None, ("MISSING_INLINE_FALLBACK_APPROVAL",)
    return (
        TypedDispatchAttemptV1(
            event_id=str(event["event_id"]),
            dispatch_id=str(event["dispatch_id"]),
            attempt_id=str(event["attempt_id"]),
            story_id=str(event["story_id"]),
            canonical_role=str(event["canonical_role"]),
            checkpoint=str(event["checkpoint"]),
            mode=mode,
            status=normalize_terminal_status(event.get("status")),
            terminal_result=str(event.get("terminal_result") or ""),
            approval_ref=approval_ref,
        ),
        (),
    )


def project_dispatch_attempt(input_value: ProjectionInputV1) -> ProjectionResultV1:
    """Project one dispatch identity without using event_id as a dispatch fallback."""

    matching = [event for event in input_value.events if str(event.get("dispatch_id") or "") == input_value.dispatch_id]
    corrected_attempts = {
        (str(event.get("dispatch_id") or ""), str(event.get("attempt_id") or ""))
        for event in matching
        if event.get("corrects_missing_event_id") is True
    }
    findings: list[str] = []
    typed: list[TypedDispatchAttemptV1] = []
    for event in matching:
        if str(event.get("event_type") or "") not in {"dispatch", "inline_fallback"}:
            continue
        attempt, errors = typed_dispatch_attempt_from_event(event)
        key = (str(event.get("dispatch_id") or ""), str(event.get("attempt_id") or ""))
        if not (not event.get("event_id") and key in corrected_attempts):
            findings.extend(errors)
        if attempt is not None:
            typed.append(attempt)
    if not matching:
        findings.append("DISPATCH_NOT_FOUND")
    if matching and not typed:
        findings.append("TYPED_ATTEMPT_UNAVAILABLE")
    terminal = [
        attempt
        for attempt in typed
        if attempt.status in TERMINAL_SUCCESS_STATUSES
        and normalize_terminal_status(attempt.terminal_result) in TERMINAL_SUCCESS_RESULTS
    ]
    if len(terminal) != 1:
        findings.append("FINAL_ATTEMPT_NOT_UNIQUE_SUCCESS")
    return ProjectionResultV1(
        terminal_success=not findings and len(terminal) == 1,
        terminal_event_ids=tuple(sorted(attempt.event_id for attempt in terminal)),
        typed_attempt_ids=tuple(sorted({attempt.attempt_id for attempt in typed})),
        finding_codes=tuple(sorted(set(findings))),
    )


def project_terminal_successes(input_value: ProjectionInputV1) -> ProjectionResultV1:
    """Canonical terminal-success projector for non-dispatch event consumers."""

    terminal = [
        str(event.get("event_id") or "")
        for event in input_value.events
        if normalize_terminal_status(event.get("status")) in TERMINAL_SUCCESS_STATUSES
    ]
    return ProjectionResultV1(
        terminal_success=bool(terminal),
        terminal_event_ids=tuple(sorted(event_id for event_id in terminal if event_id)),
        typed_attempt_ids=(),
        finding_codes=(),
    )


def parse_handoff_dispatch_record(source: str | Mapping[str, Any]) -> HandoffDispatchRecordV1:
    """Parse the sole supported ``dispatch:`` frontmatter representation."""

    if isinstance(source, Mapping):
        dispatch = source.get("dispatch")
        if not isinstance(dispatch, Mapping):
            raise ValueError("missing dispatch block in frontmatter")
        return HandoffDispatchRecordV1(tuple(sorted((str(key), str(value)) for key, value in dispatch.items())))
    if not source.startswith("---\n"):
        raise ValueError("missing or invalid YAML frontmatter")
    end = source.find("\n---", 4)
    if end == -1:
        raise ValueError("missing or invalid YAML frontmatter")
    dispatch: dict[str, str] = {}
    in_dispatch = False
    for line in source[4:end].splitlines():
        if line.startswith("dispatch:"):
            in_dispatch = True
            continue
        if not in_dispatch:
            continue
        if line and not line.startswith((" ", "\t")):
            break
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        dispatch[key.strip()] = value.strip().strip('"').strip("'")
    if not dispatch:
        raise ValueError("missing dispatch block in frontmatter")
    return HandoffDispatchRecordV1(tuple(sorted(dispatch.items())))


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
        return _resolve_runtime_path(project_root, ledger_type)
    return _resolve_runtime_ref(project_root, rel.as_posix())


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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


def validate_event_before_append(path: Path, event: Mapping[str, Any], *, ledger_type: str = "") -> dict[str, Any]:
    """Fail before directory creation or file mutation when required fields are absent."""

    if not isinstance(event, Mapping):
        raise TypeError("event must be an object")
    resolved_type = ledger_type or _ledger_type_from_path(path)
    event_type = str(event.get("event_type") or "")
    if event_type == "ledger_compacted":
        required = COMPACT_MARKER_REQUIRED_FIELDS
    elif resolved_type == "dispatch":
        required = DISPATCH_EVENT_REQUIRED_FIELDS.get(event_type, LEDGER_REQUIRED_FIELDS["dispatch"])
    else:
        required = LEDGER_REQUIRED_FIELDS.get(resolved_type, ("event_type",))
    missing = [field for field in required if not event.get(field)]
    if resolved_type == "dispatch" and event_type in {"dispatch", "inline_fallback"}:
        _attempt, typed_errors = typed_dispatch_attempt_from_event(event)
        missing.extend(error.removeprefix("MISSING_TYPED_").lower() for error in typed_errors)
    if missing:
        unique = ", ".join(dict.fromkeys(missing))
        raise ValueError(f"invalid {resolved_type} event missing required fields: {unique}")
    return {key: value for key, value in event.items() if key != "_line_no"}


def append_event(path: Path, event: dict[str, Any]) -> Path:
    payload = validate_event_before_append(path, event)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def render_appended_event(path: Path, event: dict[str, Any]) -> str:
    """Render append-only ledger content without mutating the ledger."""

    payload = validate_event_before_append(path, event)
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    if before and not before.endswith("\n"):
        before += "\n"
    return before + json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"


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
    event_id: str,
    dispatch_id: str,
    attempt_id: str,
    story_id: str,
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
        "event_id": event_id,
        "dispatch_id": dispatch_id,
        "attempt_id": attempt_id,
        "story_id": story_id,
        "event_type": "inline_fallback",
        "canonical_role": canonical_role,
        "dispatch_mode": "inline-fallback",
        "fallback_reason": fallback_reason,
        "approved_by": approved_by,
        "tool_name": tool_name,
        "status": status,
        "terminal_result": "PASS" if normalize_terminal_status(status) in TERMINAL_SUCCESS_STATUSES else "FAIL",
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
    seen_event_ids: set[str] = set()
    typed_attempt_events: dict[tuple[str, str], list[dict[str, Any]]] = {}
    corrected_attempts = {
        (str(event.get("dispatch_id") or ""), str(event.get("attempt_id") or ""))
        for event in events
        if event.get("corrects_missing_event_id") is True
    }
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
        event_id = str(event.get("event_id") or "")
        if event_id:
            if event_id in seen_event_ids:
                errors.append(f"line {line_no}: duplicate event_id: {event_id}")
            seen_event_ids.add(event_id)
        elif ledger_type == "dispatch" and event.get("event_type") == "dispatch":
            # Legacy dispatch rows may lack event_id.  They remain readable,
            # but dispatch_id/run_id may never be used as semantic event-id
            # fallbacks because one attempt naturally has several events.
            warnings.append(f"line {line_no}: legacy dispatch event lacks event_id; identity is self-declared-unverifiable")
        elif ledger_type != "dispatch":
            errors.append(f"line {line_no}: missing event_id")

        if ledger_type == "dispatch" and event.get("event_type") == "dispatch" and not event.get("attempt_id"):
            # Untyped rows predate the attempt contract.  Preserve them as
            # append-only history, but disclose evidence gaps instead of
            # fabricating identity or timing fields.
            if not (event.get("agent_id") or event.get("thread_id")):
                warnings.append(f"line {line_no}: legacy dispatch event lacks agent_id or thread_id")
            if not (event.get("spawned_at") or event.get("resumed_at")):
                warnings.append(f"line {line_no}: legacy dispatch event lacks spawned_at or resumed_at")
            if not event.get("dispatch_trigger"):
                warnings.append(f"line {line_no}: legacy dispatch event lacks dispatch_trigger")
            if normalize_terminal_status(event.get("status")) in TERMINAL_SUCCESS_STATUSES and not event.get("completed_at"):
                warnings.append(f"line {line_no}: legacy successful dispatch event lacks completed_at")

        if ledger_type == "dispatch" and event.get("event_type") == "dispatch" and event.get("attempt_id"):
            dispatch_id = str(event.get("dispatch_id") or "")
            attempt_id = str(event.get("attempt_id") or "")
            status = normalize_terminal_status(event.get("status"))
            if not event_id:
                if (dispatch_id, attempt_id) in corrected_attempts:
                    warnings.append(f"line {line_no}: typed dispatch event_id is covered by append-only correction")
                else:
                    errors.append(f"line {line_no}: typed dispatch attempt requires event_id")
            if not dispatch_id or not attempt_id:
                errors.append(f"line {line_no}: typed dispatch attempt requires dispatch_id and attempt_id")
            if status in TERMINAL_ATTEMPT_STATUSES and not event.get("terminal_result"):
                errors.append(f"line {line_no}: terminal typed dispatch attempt requires terminal_result")
            typed_attempt_events.setdefault((dispatch_id, attempt_id), []).append(event)
        if not any(event.get(field) for field in ("created_at", "checked_at", "spawned_at", "completed_at", "timestamp")):
            warnings.append(f"line {line_no}: event has no timestamp field")
    if ledger_type == "dispatch":
        for (dispatch_id, attempt_id), events_for_attempt in sorted(typed_attempt_events.items()):
            statuses = {
                normalize_terminal_status(event.get("status"))
                for event in events_for_attempt
            }
            if not statuses & TERMINAL_ATTEMPT_STATUSES:
                errors.append(f"dispatch {dispatch_id} attempt {attempt_id}: missing terminal closure")
            if not any(event.get("agent_id") or event.get("thread_id") for event in events_for_attempt):
                warnings.append(f"dispatch {dispatch_id} attempt {attempt_id}: missing agent_id or thread_id")
            if not any(event.get("spawned_at") or event.get("resumed_at") for event in events_for_attempt):
                warnings.append(f"dispatch {dispatch_id} attempt {attempt_id}: missing spawned_at or resumed_at")
            if not any(event.get("dispatch_trigger") for event in events_for_attempt):
                warnings.append(f"dispatch {dispatch_id} attempt {attempt_id}: missing dispatch_trigger")
            for event in events_for_attempt:
                if normalize_terminal_status(event.get("status")) in TERMINAL_SUCCESS_STATUSES and not event.get("completed_at"):
                    line_no = int(event.get("_line_no") or 0)
                    errors.append(f"line {line_no}: successful typed dispatch terminal event requires completed_at")
    return errors, warnings


def _print_event_help() -> None:
    print(
        "usage: meta-flow event <append|dispatch-not-required|inline-fallback|dispatch-check|check|list> [options]\n\n"
        "Commands:\n"
        "  append  Append one JSON event to an NDJSON ledger.\n"
        "  dispatch-not-required  Append a structured dispatch_not_required event.\n"
        "  inline-fallback        Append a structured inline_fallback dispatch event.\n"
        "  dispatch-check  Validate typed dispatch event/attempt closure evidence.\n"
        "  check   Validate a known or generic NDJSON event ledger.\n"
        "  list    Print compact event lines from a ledger.\n\n"
        "Examples:\n"
        "  meta-flow event append --ledger process/state/CHECKPOINT-LEDGER.ndjson --event-file event.json\n"
        "  meta-flow event inline-fallback --dispatch-id ADE-CR045-INLINE-CP6 --canonical-role meta-dev --fallback-reason \"implemented inline\" --approved-by host-orchestrator --project-root .\n"
        "  meta-flow event check --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint\n"
        "  meta-flow event check --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint --mode silent\n"
        "  meta-flow event list --ledger process/state/HANDOFF-LEDGER.ndjson\n"
    )


def _resolve_cli_ledger(project_root: Path, ledger: Path) -> Path:
    """Resolve only logical process refs through the active sibling binding."""

    return _resolve_runtime_path(project_root.resolve(), ledger)


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_event_help()
        return 0
    command = args[0]
    if command == "append":
        parser = argparse.ArgumentParser(prog="meta-flow event append")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ledger", type=Path, required=True)
        parser.add_argument("--event-file", type=Path, default=None)
        parser.add_argument("--event-json", default="")
        parsed = parser.parse_args(args[1:])
        if not parsed.event_file and not parsed.event_json:
            raise SystemExit("--event-file or --event-json is required")
        try:
            event = (
                _read_json(parsed.event_file)
                if parsed.event_file
                else json.loads(parsed.event_json)
            )
            append_event(
                _resolve_cli_ledger(parsed.project_root, parsed.ledger),
                event,
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "decision": "BLOCKED",
                        "mutation_count": 0,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 2
        print(f"appended: {parsed.ledger}")
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
        append_dispatch_event(parsed.project_root, event, ledger=parsed.ledger)
        print(f"appended: {parsed.ledger or 'process/state/AGENT-DISPATCH-LEDGER.ndjson'}")
        return 0
    if command == "inline-fallback":
        parser = argparse.ArgumentParser(prog="meta-flow event inline-fallback")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ledger", type=Path, default=None)
        parser.add_argument("--event-id", required=True)
        parser.add_argument("--dispatch-id", required=True)
        parser.add_argument("--attempt-id", required=True)
        parser.add_argument("--story-id", required=True)
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
            event_id=parsed.event_id,
            dispatch_id=parsed.dispatch_id,
            attempt_id=parsed.attempt_id,
            story_id=parsed.story_id,
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
        append_dispatch_event(parsed.project_root, event, ledger=parsed.ledger)
        print(f"appended: {parsed.ledger or 'process/state/AGENT-DISPATCH-LEDGER.ndjson'}")
        return 0
    if command == "check":
        parser = argparse.ArgumentParser(prog="meta-flow event check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ledger", type=Path, required=True)
        parser.add_argument("--type", dest="ledger_type", default="")
        parser.add_argument("--mode", choices=("normal", "silent", "verbose"), default="normal")
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_event_ledger(
            _resolve_cli_ledger(parsed.project_root, parsed.ledger), ledger_type=parsed.ledger_type
        )
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
    if command == "dispatch-check":
        parser = argparse.ArgumentParser(prog="meta-flow event dispatch-check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ledger", type=Path, default=Path("process/state/AGENT-DISPATCH-LEDGER.ndjson"))
        parser.add_argument("--mode", choices=("normal", "silent"), default="normal")
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_event_ledger(
            _resolve_cli_ledger(parsed.project_root, parsed.ledger), ledger_type="dispatch"
        )
        if parsed.mode == "silent":
            print("PASS" if not errors else "FAIL: " + "; ".join(errors))
        else:
            print("Dispatch Evidence Check: " + ("FAIL" if errors else "OK"))
            for warning in warnings:
                print(f"- WARN: {warning}")
            for error in errors:
                print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "list":
        parser = argparse.ArgumentParser(prog="meta-flow event list")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ledger", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        events, errors = load_events(_resolve_cli_ledger(parsed.project_root, parsed.ledger))
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
