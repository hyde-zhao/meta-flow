"""Read expansion event ledger for full-document reads."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from meta_flow.checks.token_budget import DEFAULT_READ_DENY_PATTERNS, estimate_tokens
from meta_flow.context_pack.builder import (
    DEFAULT_FULL_DOC_READ_REASONS,
    READ_EXPANSION_LEDGER_REL,
    load_read_policy,
)
from meta_flow.state.current import now_utc

REQUIRED_EVENT_FIELDS = {
    "event_id",
    "event_type",
    "agent",
    "stage",
    "requested_path",
    "reason",
    "allowed_by_policy",
    "estimated_tokens",
    "context_ref",
    "created_at",
}
OPTIONAL_EVENT_FIELDS = {"story_id", "cr_id", "feature_id", "notes"}


def _as_posix(path: Path | str) -> str:
    return Path(path).as_posix()


def _rel(project_root: Path, path: Path | str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return candidate.as_posix()


def _path_tokens(project_root: Path, rel_path: str) -> int:
    path = project_root / rel_path
    if not path.is_file():
        return 0
    try:
        return estimate_tokens(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return 0


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    return any(rel_path == pattern or fnmatch(rel_path, pattern) for pattern in patterns)


def default_ledger_path(project_root: Path) -> Path:
    return project_root / READ_EXPANSION_LEDGER_REL


def load_events(ledger_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    if not ledger_path.exists():
        return events, errors
    for line_number, line in enumerate(ledger_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON: {exc}")
            continue
        if not isinstance(event, dict):
            errors.append(f"line {line_number}: event must be an object")
            continue
        events.append(event)
    return events, errors


def build_event(
    project_root: Path,
    *,
    requested_path: str,
    reason: str,
    stage: str,
    agent: str,
    context_ref: str,
    story_id: str = "",
    cr_id: str = "",
    feature_id: str = "",
    notes: str = "",
    authorization_ref: str = "",
) -> dict[str, Any]:
    root = project_root.resolve()
    rel_path = _rel(root, requested_path)
    read_policy = load_read_policy(root)
    allowed_reasons = set(str(item) for item in read_policy.get("full_doc_read_allowed_when") or DEFAULT_FULL_DOC_READ_REASONS)
    deny_patterns = list(read_policy.get("deny_default_reads") or DEFAULT_READ_DENY_PATTERNS)
    allowed_by_policy = reason in allowed_reasons
    outside_default_read_set = _matches_any(rel_path, deny_patterns)
    event_id = f"RE-{now_utc().replace(':', '').replace('-', '').replace('+', 'Z')}-{uuid.uuid4().hex[:8]}"
    return {
        "event_id": event_id,
        "event_type": "read_expansion",
        "agent": agent,
        "stage": stage,
        "story_id": story_id or None,
        "cr_id": cr_id or None,
        "feature_id": feature_id or _feature_from_path(rel_path),
        "requested_path": rel_path,
        "reason": reason,
        "allowed_by_policy": allowed_by_policy,
        "deny_default_match": _matches_any(rel_path, deny_patterns),
        # Keep policy membership distinct from the fact that a read is outside
        # the capsule/default set.  A future producer must not use a prose
        # reason to turn an unauthorized expansion into a permitted one.
        "outside_default_read_set": outside_default_read_set,
        "expansion_authorized": (not outside_default_read_set) or allowed_by_policy or bool(authorization_ref),
        "authorization_reason": reason if outside_default_read_set and (allowed_by_policy or authorization_ref) else None,
        "authorization_ref": authorization_ref or None,
        "estimated_tokens": _path_tokens(root, rel_path),
        "context_ref": context_ref,
        "created_at": now_utc(),
        "notes": notes or None,
    }


def append_event(
    project_root: Path,
    *,
    requested_path: str,
    reason: str,
    stage: str,
    agent: str,
    context_ref: str,
    story_id: str = "",
    cr_id: str = "",
    feature_id: str = "",
    notes: str = "",
    authorization_ref: str = "",
    ledger: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    root = project_root.resolve()
    event = build_event(
        root,
        requested_path=requested_path,
        reason=reason,
        stage=stage,
        agent=agent,
        context_ref=context_ref,
        story_id=story_id,
        cr_id=cr_id,
        feature_id=feature_id,
        notes=notes,
        authorization_ref=authorization_ref,
    )
    ledger_path = ledger.resolve() if ledger else default_ledger_path(root)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event, ledger_path


def validate_event(event: dict[str, Any], *, allowed_reasons: set[str], line_number: int) -> list[str]:
    errors: list[str] = []
    missing = sorted(field for field in REQUIRED_EVENT_FIELDS if field not in event)
    for field in missing:
        errors.append(f"line {line_number}: missing required field: {field}")
    if event.get("event_type") != "read_expansion":
        errors.append(f"line {line_number}: event_type must be read_expansion")
    reason = str(event.get("reason") or "")
    if reason not in allowed_reasons:
        errors.append(f"line {line_number}: reason not allowed by read policy: {reason or '-'}")
    if event.get("allowed_by_policy") is not True:
        errors.append(f"line {line_number}: allowed_by_policy must be true")
    estimated = event.get("estimated_tokens")
    if not isinstance(estimated, int) or estimated < 0:
        errors.append(f"line {line_number}: estimated_tokens must be a non-negative integer")
    requested_path = str(event.get("requested_path") or "")
    if not requested_path:
        errors.append(f"line {line_number}: requested_path must be non-empty")
    outside_default = event.get("outside_default_read_set")
    if outside_default is not None and not isinstance(outside_default, bool):
        errors.append(f"line {line_number}: outside_default_read_set must be boolean")
    if outside_default is True:
        if event.get("expansion_authorized") is not True:
            errors.append(f"line {line_number}: outside-default read requires expansion_authorized=true")
        if not event.get("authorization_reason"):
            errors.append(f"line {line_number}: outside-default read requires authorization_reason")
    return errors


def validate_ledger(project_root: Path, *, ledger: Path | None = None) -> tuple[list[str], list[str]]:
    root = project_root.resolve()
    ledger_path = ledger.resolve() if ledger else default_ledger_path(root)
    events, parse_errors = load_events(ledger_path)
    errors = list(parse_errors)
    warnings: list[str] = []
    read_policy = load_read_policy(root)
    allowed_reasons = set(str(item) for item in read_policy.get("full_doc_read_allowed_when") or DEFAULT_FULL_DOC_READ_REASONS)
    deny_patterns = list(read_policy.get("deny_default_reads") or DEFAULT_READ_DENY_PATTERNS)
    seen_ids: set[str] = set()
    for line_number, event in enumerate(events, 1):
        errors.extend(validate_event(event, allowed_reasons=allowed_reasons, line_number=line_number))
        event_id = str(event.get("event_id") or "")
        if event_id in seen_ids:
            errors.append(f"line {line_number}: duplicate event_id: {event_id}")
        if event_id:
            seen_ids.add(event_id)
        requested_path = str(event.get("requested_path") or "")
        if "outside_default_read_set" not in event:
            warnings.append(f"line {line_number}: legacy read-expansion event has no explicit authorization semantics")
        if requested_path and not _matches_any(requested_path, deny_patterns):
            warnings.append(f"line {line_number}: requested_path is not deny-default; read expansion may be unnecessary: {requested_path}")
    return errors, warnings


def _feature_from_path(rel_path: str) -> str | None:
    parts = Path(rel_path).parts
    if len(parts) >= 3 and parts[0] == "docs" and parts[1] == "features":
        return parts[2]
    return None


def summarize_events(project_root: Path, *, ledger: Path | None = None) -> dict[str, Any]:
    root = project_root.resolve()
    ledger_path = ledger.resolve() if ledger else default_ledger_path(root)
    events, _errors = load_events(ledger_path)
    path_counter: Counter[str] = Counter()
    feature_counter: Counter[str] = Counter()
    reason_counter: Counter[str] = Counter()
    total_tokens = 0
    missing_slot_counter: Counter[str] = Counter()
    for event in events:
        path = str(event.get("requested_path") or "")
        reason = str(event.get("reason") or "")
        feature = str(event.get("feature_id") or _feature_from_path(path) or "")
        if path:
            path_counter[path] += 1
        if feature:
            feature_counter[feature] += 1
        if reason:
            reason_counter[reason] += 1
            if reason in {"field_conflict", "schema_validation_failed"}:
                missing_slot_counter["feature_contract_summary"] += 1
            if reason == "capsule_missing":
                missing_slot_counter["required_context_slot"] += 1
        total_tokens += int(event.get("estimated_tokens") or 0)
    return {
        "ledger": ledger_path.as_posix(),
        "event_count": len(events),
        "frequently_expanded_files": path_counter.most_common(10),
        "frequently_expanded_features": feature_counter.most_common(10),
        "expansion_reason_distribution": reason_counter.most_common(),
        "missing_context_slots": missing_slot_counter.most_common(),
        "estimated_extra_tokens": total_tokens,
        "summary_update_recommendations": build_recommendations(path_counter, reason_counter, missing_slot_counter),
    }


def build_recommendations(
    path_counter: Counter[str],
    reason_counter: Counter[str],
    missing_slot_counter: Counter[str],
) -> list[str]:
    recommendations: list[str] = []
    for path, count in path_counter.most_common(5):
        if count >= 2:
            recommendations.append(f"Update summary for {path}; it was expanded {count} times.")
    for slot, count in missing_slot_counter.most_common(5):
        if count:
            recommendations.append(f"Strengthen Story/context packet slot '{slot}' based on {count} expansion events.")
    if reason_counter.get("field_conflict"):
        recommendations.append("Add contract/status fields to Feature summaries to reduce field_conflict reads.")
    if not recommendations and path_counter:
        recommendations.append("Review expanded files and add compact summaries when expansion repeats.")
    return recommendations


def _print_summary(summary: dict[str, Any]) -> None:
    print("Context Doctor:")
    print(f"ledger: {summary['ledger']}")
    print(f"read_expansion_events: {summary['event_count']}")
    print(f"estimated_extra_tokens: {summary['estimated_extra_tokens']}")
    print("frequently_expanded_files:")
    for path, count in summary["frequently_expanded_files"]:
        print(f"- {path}: {count}")
    if not summary["frequently_expanded_files"]:
        print("- none")
    print("frequently_expanded_features:")
    for feature, count in summary["frequently_expanded_features"]:
        print(f"- {feature}: {count}")
    if not summary["frequently_expanded_features"]:
        print("- none")
    print("expansion_reason_distribution:")
    for reason, count in summary["expansion_reason_distribution"]:
        print(f"- {reason}: {count}")
    if not summary["expansion_reason_distribution"]:
        print("- none")
    print("missing_context_slots:")
    for slot, count in summary["missing_context_slots"]:
        print(f"- {slot}: {count}")
    if not summary["missing_context_slots"]:
        print("- none")
    print("summary_update_recommendations:")
    for item in summary["summary_update_recommendations"]:
        print(f"- {item}")
    if not summary["summary_update_recommendations"]:
        print("- none")


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: meta-flow context <read-log|read-log-check> [options]\n\n"
            "Examples:\n"
            "  meta-flow context read-log --path process/STATE.md --reason human_audit --stage CP6 --agent meta-dev --context-ref process/context/CP6.context.json --project-root .\n"
            "  meta-flow context read-log-check --project-root .\n"
        )
        return 0
    command = args[0]
    if command == "read-log":
        parser = argparse.ArgumentParser(prog="meta-flow context read-log")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ledger", type=Path, default=None)
        parser.add_argument("--path", dest="requested_path", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--stage", required=True)
        parser.add_argument("--agent", required=True)
        parser.add_argument("--context-ref", required=True)
        parser.add_argument("--story-id", default="")
        parser.add_argument("--cr-id", default="")
        parser.add_argument("--feature-id", default="")
        parser.add_argument("--notes", default="")
        parsed = parser.parse_args(args[1:])
        event, ledger_path = append_event(
            parsed.project_root,
            requested_path=parsed.requested_path,
            reason=parsed.reason,
            stage=parsed.stage,
            agent=parsed.agent,
            context_ref=parsed.context_ref,
            story_id=parsed.story_id,
            cr_id=parsed.cr_id,
            feature_id=parsed.feature_id,
            notes=parsed.notes,
            ledger=parsed.ledger,
        )
        print(f"appended: {ledger_path}")
        print(f"event_id: {event['event_id']}")
        return 0
    if command == "read-log-check":
        parser = argparse.ArgumentParser(prog="meta-flow context read-log-check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ledger", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_ledger(parsed.project_root, ledger=parsed.ledger)
        print("Read Expansion Ledger Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "doctor":
        parser = argparse.ArgumentParser(prog="meta-flow doctor context")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ledger", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_ledger(parsed.project_root, ledger=parsed.ledger)
        summary = summarize_events(parsed.project_root, ledger=parsed.ledger)
        _print_summary(summary)
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 read expansion 命令: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
