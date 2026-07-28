"""Read expansion event ledger for full-document reads."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from meta_flow.checks.token_budget import DEFAULT_READ_DENY_PATTERNS, estimate_tokens
from meta_flow.context_pack.builder import (
    DEFAULT_FULL_DOC_READ_REASONS,
    READ_EXPANSION_LEDGER_REL,
    load_read_policy,
)
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import (
    _resolve_runtime_path,
    _resolve_runtime_ref,
    require_process_route,
)
from meta_flow.state.current import now_utc
from meta_flow.work.model import load_work
from meta_flow.work.scope import check_scope

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
OPTIONAL_EVENT_FIELDS = {
    "story_id",
    "cr_id",
    "feature_id",
    "notes",
    "supersedes_event_id",
    "work_id",
    "scope_digest",
    "preregistered_by",
    "plan_digest",
}
CORRECTION_IDENTITY_FIELDS = (
    "agent",
    "stage",
    "story_id",
    "cr_id",
    "feature_id",
    "requested_path",
    "context_ref",
)
PREREGISTRATION_ACTION_FIELDS = {
    "operation",
    "input_contract",
    "actor",
    "required_before",
    "requested_refs",
    "reason",
}


@dataclass(frozen=True)
class ReadExpansionPlanV1:
    """Host pre-dispatch read-expansion plan with logical refs only."""

    decision: str
    story_id: str
    stage: str
    context_ref: str
    work_id: str
    scope_digest: str
    requested_refs: tuple[str, ...]
    reason: str
    agent: str
    ledger_ref: str
    planned_mutation_count: int
    mutation_count: int
    blockers: tuple[str, ...]
    plan_digest: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "ReadExpansionPlanV1",
            "decision": self.decision,
            "story_id": self.story_id,
            "stage": self.stage,
            "context_ref": self.context_ref,
            "work_id": self.work_id,
            "scope_digest": self.scope_digest,
            "requested_refs": list(self.requested_refs),
            "reason": self.reason,
            "agent": self.agent,
            "ledger_ref": self.ledger_ref,
            "planned_mutation_count": self.planned_mutation_count,
            "mutation_count": self.mutation_count,
            "blockers": list(self.blockers),
            "plan_digest": self.plan_digest,
        }


@dataclass(frozen=True)
class ReadExpansionApplyResultV1:
    """Result of applying or replaying one prevalidated plan."""

    decision: str
    story_id: str
    context_ref: str
    work_id: str
    scope_digest: str
    requested_refs: tuple[str, ...]
    event_ids: tuple[str, ...]
    ledger_ref: str
    plan_digest: str
    mutation_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "ReadExpansionApplyResultV1",
            "decision": self.decision,
            "story_id": self.story_id,
            "context_ref": self.context_ref,
            "work_id": self.work_id,
            "scope_digest": self.scope_digest,
            "requested_refs": list(self.requested_refs),
            "event_ids": list(self.event_ids),
            "ledger_ref": self.ledger_ref,
            "plan_digest": self.plan_digest,
            "mutation_count": self.mutation_count,
        }


def _as_posix(path: Path | str) -> str:
    return Path(path).as_posix()


def _logical_process_ref(value: Path | str, *, field: str) -> str:
    raw = Path(value)
    if (
        raw.is_absolute()
        or len(raw.parts) < 2
        or raw.parts[0] != "process"
        or any(part in {"", ".", ".."} for part in raw.parts)
    ):
        raise ValueError(f"{field} must be one canonical logical process/... ref")
    return raw.as_posix()


def _rel(project_root: Path, path: Path | str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    root = project_root.resolve()
    resolved = candidate.resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        process_marker = _resolve_runtime_ref(root, "process/.meta-flow-process.yaml")
        process_root = process_marker.parent.resolve(strict=False)
        try:
            process_relative = resolved.relative_to(process_root)
        except ValueError as exc:
            raise ValueError(
                "read expansion path is outside the release and bound process repositories"
            ) from exc
        return f"process/{process_relative.as_posix()}"


def _path_tokens(project_root: Path, rel_path: str) -> int:
    path = _resolve_runtime_path(project_root, rel_path)
    if not path.is_file():
        return 0
    try:
        return estimate_tokens(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return 0


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    return any(rel_path == pattern or fnmatch(rel_path, pattern) for pattern in patterns)


def default_ledger_path(project_root: Path) -> Path:
    return _resolve_runtime_ref(project_root, READ_EXPANSION_LEDGER_REL.as_posix())


def _ledger_path(project_root: Path, ledger: Path | None) -> Path:
    return _resolve_runtime_path(project_root, ledger) if ledger else default_ledger_path(project_root)


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
    supersedes_event_id: str = "",
    work_id: str = "",
    scope_digest: str = "",
    preregistered_by: str = "",
    plan_digest: str = "",
) -> dict[str, Any]:
    root = project_root.resolve()
    rel_path = _rel(root, requested_path)
    read_policy = load_read_policy(root)
    allowed_reasons = set(str(item) for item in read_policy.get("full_doc_read_allowed_when") or DEFAULT_FULL_DOC_READ_REASONS)
    deny_patterns = list(read_policy.get("deny_default_reads") or DEFAULT_READ_DENY_PATTERNS)
    allowed_by_policy = reason in allowed_reasons
    outside_default_read_set = _matches_any(rel_path, deny_patterns)
    event_id = f"RE-{now_utc().replace(':', '').replace('-', '').replace('+', 'Z')}-{uuid.uuid4().hex[:8]}"
    event = {
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
        "work_id": work_id or None,
        "scope_digest": scope_digest or None,
        "preregistered_by": preregistered_by or None,
        "plan_digest": plan_digest or None,
    }
    if supersedes_event_id:
        event["supersedes_event_id"] = supersedes_event_id
    return event


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
    supersedes_event_id: str = "",
    work_id: str = "",
    scope_digest: str = "",
    preregistered_by: str = "",
    plan_digest: str = "",
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
        supersedes_event_id=supersedes_event_id,
        work_id=work_id,
        scope_digest=scope_digest,
        preregistered_by=preregistered_by,
        plan_digest=plan_digest,
    )
    ledger_path = _ledger_path(root, ledger)
    read_policy = load_read_policy(root)
    allowed_reasons = set(
        str(item)
        for item in read_policy.get("full_doc_read_allowed_when")
        or DEFAULT_FULL_DOC_READ_REASONS
    )
    event_errors = validate_event(
        event,
        allowed_reasons=allowed_reasons,
        line_number=0,
    )
    if event_errors:
        raise ValueError(
            "read expansion event is invalid; mutation=0: "
            + "; ".join(error.removeprefix("line 0: ") for error in event_errors)
        )
    if supersedes_event_id:
        existing, parse_errors = load_events(ledger_path)
        if parse_errors:
            raise ValueError(
                "read expansion ledger is invalid; mutation=0: "
                + "; ".join(parse_errors)
            )
        sources = [
            item
            for item in existing
            if item.get("event_id") == supersedes_event_id
        ]
        if len(sources) != 1:
            raise ValueError(
                "read expansion correction requires exactly one source event; mutation=0"
            )
        if any(
            item.get("supersedes_event_id") == supersedes_event_id
            for item in existing
        ):
            raise ValueError(
                "read expansion source event already has a correction; mutation=0"
            )
        source = sources[0]
        source_errors = validate_event(
            source,
            allowed_reasons=allowed_reasons,
            line_number=0,
        )
        if not source_errors:
            raise ValueError(
                "read expansion correction may only supersede an invalid event; mutation=0"
            )
        identity_drift = [
            field
            for field in CORRECTION_IDENTITY_FIELDS
            if source.get(field) != event.get(field)
        ]
        if identity_drift:
            raise ValueError(
                "read expansion correction identity drift: "
                + ", ".join(identity_drift)
                + "; mutation=0"
            )
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event, ledger_path


def _with_plan_digest(plan: ReadExpansionPlanV1) -> ReadExpansionPlanV1:
    payload = plan.as_dict()
    payload.pop("plan_digest", None)
    return replace(plan, plan_digest=canonical_digest(payload))


def _blocked_plan(
    *,
    story_id: str,
    stage: str,
    context_ref: str,
    work_id: str,
    scope_digest: str,
    requested_refs: tuple[str, ...] = (),
    reason: str = "",
    ledger_ref: str = READ_EXPANSION_LEDGER_REL.as_posix(),
    blockers: list[str],
) -> ReadExpansionPlanV1:
    return _with_plan_digest(
        ReadExpansionPlanV1(
            decision="BLOCKED",
            story_id=story_id,
            stage=stage,
            context_ref=context_ref,
            work_id=work_id,
            scope_digest=scope_digest,
            requested_refs=requested_refs,
            reason=reason,
            agent="host-orchestrator",
            ledger_ref=ledger_ref,
            planned_mutation_count=0,
            mutation_count=0,
            blockers=tuple(sorted(set(blockers))),
        )
    )


def _matching_preregistration_events(
    events: list[dict[str, Any]],
    *,
    story_id: str,
    stage: str,
    context_ref: str,
    work_id: str,
    scope_digest: str,
    reason: str,
    requested_ref: str,
) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("event_type") == "read_expansion"
        and str(event.get("story_id") or "") == story_id
        and str(event.get("stage") or "") == stage
        and str(event.get("context_ref") or "") == context_ref
        and str(event.get("work_id") or "") == work_id
        and str(event.get("scope_digest") or "") == scope_digest
        and str(event.get("reason") or "") == reason
        and str(event.get("requested_path") or "") == requested_ref
        and str(event.get("preregistered_by") or "") == "host-orchestrator"
    ]


def build_host_preregistration_plan(
    project_root: Path,
    *,
    story_packet_ref: str,
    work_id: str,
    scope_digest: str,
    reason_override: str = "",
    ledger: Path | None = None,
) -> ReadExpansionPlanV1:
    """Project a Story packet's required Host action without mutating its ledger."""

    root = project_root.resolve()
    context_ref = _logical_process_ref(story_packet_ref, field="story_packet_ref")
    packet_path = _resolve_runtime_ref(root, context_ref)
    if not packet_path.is_file():
        return _blocked_plan(
            story_id="",
            stage="",
            context_ref=context_ref,
            work_id=work_id,
            scope_digest=scope_digest,
            blockers=["STORY_PACKET_MISSING"],
        )
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _blocked_plan(
            story_id="",
            stage="",
            context_ref=context_ref,
            work_id=work_id,
            scope_digest=scope_digest,
            blockers=["STORY_PACKET_INVALID_JSON"],
        )
    if not isinstance(packet, dict):
        return _blocked_plan(
            story_id="",
            stage="",
            context_ref=context_ref,
            work_id=work_id,
            scope_digest=scope_digest,
            blockers=["STORY_PACKET_NOT_OBJECT"],
        )

    story_id = str(packet.get("story_id") or "")
    stage = str(packet.get("stage") or "")
    ledger_ref = str(
        packet.get("required_full_doc_read_log")
        or READ_EXPANSION_LEDGER_REL.as_posix()
    )
    blockers: list[str] = []
    if packet.get("schema_version") != 2:
        blockers.append("STORY_PACKET_SCHEMA_NOT_PREREGISTRATION_CAPABLE")
    try:
        ledger_ref = _logical_process_ref(ledger_ref, field="required_full_doc_read_log")
    except ValueError:
        blockers.append("READ_EXPANSION_LEDGER_REF_INVALID")
        ledger_ref = READ_EXPANSION_LEDGER_REL.as_posix()

    denied = list(
        packet.get("denied_default_reads") or DEFAULT_READ_DENY_PATTERNS
    )
    required_refs = tuple(
        sorted(
            {
                str(entry.get("path") or "")
                for entry in packet.get("read_if_needed") or []
                if isinstance(entry, dict)
                and str(entry.get("trigger") or "")
                and _matches_any(str(entry.get("path") or ""), denied)
            }
        )
    )
    actions = packet.get("pre_dispatch_actions")
    if not isinstance(actions, list) or len(actions) != 1:
        blockers.append("HOST_PREREGISTRATION_ACTION_COUNT_INVALID")
        action: dict[str, Any] = {}
    elif not isinstance(actions[0], dict):
        blockers.append("HOST_PREREGISTRATION_ACTION_INVALID")
        action = {}
    else:
        action = actions[0]
    if action and set(action) != PREREGISTRATION_ACTION_FIELDS:
        blockers.append("HOST_PREREGISTRATION_ACTION_FIELDS_INVALID")
    if str(action.get("operation") or "") != "context.read-log":
        blockers.append("HOST_PREREGISTRATION_OPERATION_INVALID")
    if str(action.get("input_contract") or "") != "ReadExpansionPlanV1":
        blockers.append("HOST_PREREGISTRATION_INPUT_CONTRACT_INVALID")
    if str(action.get("actor") or "") != "host-orchestrator":
        blockers.append("HOST_PREREGISTRATION_ACTOR_INVALID")
    if str(action.get("required_before") or "") != "story-dispatch":
        blockers.append("HOST_PREREGISTRATION_ORDER_INVALID")
    action_refs = tuple(sorted(str(item) for item in action.get("requested_refs") or []))
    if action_refs != required_refs or not required_refs:
        blockers.append("HOST_PREREGISTRATION_REFS_MISMATCH")
    action_reason = str(action.get("reason") or "")
    reason = reason_override or action_reason
    if reason_override and reason_override != action_reason:
        blockers.append("HOST_PREREGISTRATION_REASON_MISMATCH")

    read_policy = load_read_policy(root)
    allowed_reasons = set(
        str(item)
        for item in read_policy.get("full_doc_read_allowed_when")
        or DEFAULT_FULL_DOC_READ_REASONS
    )
    if reason not in allowed_reasons:
        blockers.append("HOST_PREREGISTRATION_REASON_NOT_ALLOWED")
    try:
        route = require_process_route(root)
        work = load_work(route.process_root, work_id)
    except (OSError, ValueError) as exc:
        blockers.append(f"WORK_SCOPE_UNAVAILABLE:{type(exc).__name__}")
        work = None
    if work is not None:
        if work.scope.digest != scope_digest:
            blockers.append("WORK_SCOPE_DIGEST_MISMATCH")
        for requested_ref in required_refs:
            try:
                logical_ref = _logical_process_ref(
                    requested_ref,
                    field="requested_ref",
                )
                process_relative_ref = Path(logical_ref).relative_to("process").as_posix()
                decision = check_scope(
                    work.scope,
                    "read",
                    process_relative_ref,
                )
            except ValueError:
                blockers.append(f"WORK_SCOPE_REF_INVALID:{requested_ref}")
                continue
            if not decision.allowed:
                blockers.append(f"WORK_SCOPE_READ_DENIED:{requested_ref}")
    for requested_ref in required_refs:
        try:
            logical_ref = _logical_process_ref(
                requested_ref,
                field="requested_ref",
            )
        except ValueError:
            blockers.append(f"REQUESTED_REF_INVALID:{requested_ref}")
            continue
        if not _resolve_runtime_ref(root, logical_ref).is_file():
            blockers.append(f"REQUESTED_REF_MISSING:{logical_ref}")

    ledger_path = _ledger_path(root, ledger)
    existing, ledger_errors = load_events(ledger_path)
    blockers.extend(f"READ_EXPANSION_LEDGER_INVALID:{error}" for error in ledger_errors)
    if blockers:
        return _blocked_plan(
            story_id=story_id,
            stage=stage,
            context_ref=context_ref,
            work_id=work_id,
            scope_digest=scope_digest,
            requested_refs=required_refs,
            reason=reason,
            ledger_ref=ledger_ref,
            blockers=blockers,
        )

    missing_refs = tuple(
        requested_ref
        for requested_ref in required_refs
        if not _matching_preregistration_events(
            existing,
            story_id=story_id,
            stage=stage,
            context_ref=context_ref,
            work_id=work_id,
            scope_digest=scope_digest,
            reason=reason,
            requested_ref=requested_ref,
        )
    )
    return _with_plan_digest(
        ReadExpansionPlanV1(
            decision="READY" if missing_refs else "NO_CHANGE",
            story_id=story_id,
            stage=stage,
            context_ref=context_ref,
            work_id=work_id,
            scope_digest=scope_digest,
            requested_refs=required_refs,
            reason=reason,
            agent="host-orchestrator",
            ledger_ref=ledger_ref,
            planned_mutation_count=len(missing_refs),
            mutation_count=0,
            blockers=(),
        )
    )


def apply_host_preregistration_plan(
    project_root: Path,
    plan: ReadExpansionPlanV1,
    *,
    ledger: Path | None = None,
) -> ReadExpansionApplyResultV1:
    """Apply one fresh plan; repeated semantic input returns ``NO_CHANGE``."""

    if plan.decision not in {"READY", "NO_CHANGE"} or plan.blockers:
        raise ValueError("read expansion plan is not applicable; mutation=0")
    fresh = build_host_preregistration_plan(
        project_root,
        story_packet_ref=plan.context_ref,
        work_id=plan.work_id,
        scope_digest=plan.scope_digest,
        reason_override=plan.reason,
        ledger=ledger,
    )
    if fresh.plan_digest != plan.plan_digest:
        raise ValueError("read expansion plan drifted before apply; mutation=0")
    root = project_root.resolve()
    ledger_path = _ledger_path(root, ledger)
    existing, parse_errors = load_events(ledger_path)
    if parse_errors:
        raise ValueError("read expansion ledger is invalid; mutation=0")
    existing_ids: list[str] = []
    missing_refs: list[str] = []
    for requested_ref in plan.requested_refs:
        matches = _matching_preregistration_events(
            existing,
            story_id=plan.story_id,
            stage=plan.stage,
            context_ref=plan.context_ref,
            work_id=plan.work_id,
            scope_digest=plan.scope_digest,
            reason=plan.reason,
            requested_ref=requested_ref,
        )
        if matches:
            existing_ids.extend(str(event.get("event_id") or "") for event in matches)
        else:
            missing_refs.append(requested_ref)
    if not missing_refs:
        return ReadExpansionApplyResultV1(
            decision="NO_CHANGE",
            story_id=plan.story_id,
            context_ref=plan.context_ref,
            work_id=plan.work_id,
            scope_digest=plan.scope_digest,
            requested_refs=plan.requested_refs,
            event_ids=tuple(sorted(item for item in existing_ids if item)),
            ledger_ref=plan.ledger_ref,
            plan_digest=plan.plan_digest,
            mutation_count=0,
        )

    pending = [
        build_event(
            root,
            requested_path=requested_ref,
            reason=plan.reason,
            stage=plan.stage,
            agent=plan.agent,
            context_ref=plan.context_ref,
            story_id=plan.story_id,
            work_id=plan.work_id,
            scope_digest=plan.scope_digest,
            preregistered_by="host-orchestrator",
            plan_digest=plan.plan_digest,
        )
        for requested_ref in missing_refs
    ]
    read_policy = load_read_policy(root)
    allowed_reasons = set(
        str(item)
        for item in read_policy.get("full_doc_read_allowed_when")
        or DEFAULT_FULL_DOC_READ_REASONS
    )
    pending_errors = [
        error
        for event in pending
        for error in validate_event(
            event,
            allowed_reasons=allowed_reasons,
            line_number=0,
        )
    ]
    if pending_errors:
        raise ValueError(
            "read expansion preregistration is invalid; mutation=0: "
            + "; ".join(pending_errors)
        )
    appended_ids: list[str] = []
    for event in pending:
        appended, _path = append_event(
            root,
            requested_path=str(event["requested_path"]),
            reason=str(event["reason"]),
            stage=str(event["stage"]),
            agent=str(event["agent"]),
            context_ref=str(event["context_ref"]),
            story_id=str(event.get("story_id") or ""),
            work_id=str(event.get("work_id") or ""),
            scope_digest=str(event.get("scope_digest") or ""),
            preregistered_by=str(event.get("preregistered_by") or ""),
            plan_digest=str(event.get("plan_digest") or ""),
            ledger=ledger,
        )
        appended_ids.append(str(appended["event_id"]))
    return ReadExpansionApplyResultV1(
        decision="APPLIED",
        story_id=plan.story_id,
        context_ref=plan.context_ref,
        work_id=plan.work_id,
        scope_digest=plan.scope_digest,
        requested_refs=plan.requested_refs,
        event_ids=tuple(sorted([*existing_ids, *appended_ids])),
        ledger_ref=plan.ledger_ref,
        plan_digest=plan.plan_digest,
        mutation_count=len(appended_ids),
    )


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
    ledger_path = _ledger_path(root, ledger)
    events, parse_errors = load_events(ledger_path)
    errors = list(parse_errors)
    warnings: list[str] = []
    read_policy = load_read_policy(root)
    allowed_reasons = set(str(item) for item in read_policy.get("full_doc_read_allowed_when") or DEFAULT_FULL_DOC_READ_REASONS)
    deny_patterns = list(read_policy.get("deny_default_reads") or DEFAULT_READ_DENY_PATTERNS)
    events_by_id = {
        str(event.get("event_id") or ""): (line_number, event)
        for line_number, event in enumerate(events, 1)
        if event.get("event_id")
    }
    valid_corrections: dict[str, tuple[int, dict[str, Any]]] = {}
    for line_number, event in enumerate(events, 1):
        source_id = str(event.get("supersedes_event_id") or "")
        if not source_id:
            continue
        source_entry = events_by_id.get(source_id)
        correction_errors = validate_event(
            event,
            allowed_reasons=allowed_reasons,
            line_number=line_number,
        )
        if source_entry is None:
            errors.append(
                f"line {line_number}: supersedes_event_id not found: {source_id}"
            )
            continue
        source_line, source = source_entry
        if source_line >= line_number:
            errors.append(
                f"line {line_number}: correction source must precede successor"
            )
            continue
        if source_id in valid_corrections:
            errors.append(
                f"line {line_number}: duplicate correction for source: {source_id}"
            )
            continue
        identity_drift = [
            field
            for field in CORRECTION_IDENTITY_FIELDS
            if source.get(field) != event.get(field)
        ]
        if identity_drift:
            errors.append(
                f"line {line_number}: correction identity drift: "
                + ", ".join(identity_drift)
            )
            continue
        if correction_errors:
            errors.extend(correction_errors)
            continue
        valid_corrections[source_id] = (line_number, event)
    seen_ids: set[str] = set()
    for line_number, event in enumerate(events, 1):
        event_id = str(event.get("event_id") or "")
        if event_id in valid_corrections:
            successor_line, successor = valid_corrections[event_id]
            warnings.append(
                f"line {line_number}: invalid event superseded by append-only "
                f"correction {successor.get('event_id')} at line {successor_line}"
            )
        else:
            errors.extend(
                validate_event(
                    event,
                    allowed_reasons=allowed_reasons,
                    line_number=line_number,
                )
            )
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
    ledger_path = _ledger_path(root, ledger)
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
            "  meta-flow context read-log --story-packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --work-id WORK-123 --scope-digest <digest> --dry-run --project-root .\n"
            "  meta-flow context read-log-check --project-root .\n"
        )
        return 0
    command = args[0]
    if command == "read-log":
        parser = argparse.ArgumentParser(prog="meta-flow context read-log")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--ledger", type=Path, default=None)
        parser.add_argument("--path", dest="requested_path", default="")
        parser.add_argument("--reason", default="")
        parser.add_argument("--stage", default="")
        parser.add_argument("--agent", default="")
        parser.add_argument("--context-ref", default="")
        parser.add_argument("--story-id", default="")
        parser.add_argument("--cr-id", default="")
        parser.add_argument("--feature-id", default="")
        parser.add_argument("--notes", default="")
        parser.add_argument("--supersedes-event-id", default="")
        parser.add_argument("--story-packet", default="")
        parser.add_argument("--work-id", default="")
        parser.add_argument("--scope-digest", default="")
        parser.add_argument("--dry-run", action="store_true")
        parsed = parser.parse_args(args[1:])
        if parsed.story_packet:
            try:
                if parsed.requested_path or parsed.context_ref:
                    raise ValueError(
                        "--story-packet cannot be combined with --path/--context-ref; mutation=0"
                    )
                if not parsed.work_id or not parsed.scope_digest:
                    raise ValueError(
                        "--story-packet requires --work-id and --scope-digest; mutation=0"
                    )
                plan = build_host_preregistration_plan(
                    parsed.project_root,
                    story_packet_ref=parsed.story_packet,
                    work_id=parsed.work_id,
                    scope_digest=parsed.scope_digest,
                    reason_override=parsed.reason,
                    ledger=parsed.ledger,
                )
                if plan.decision == "BLOCKED":
                    print(json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True))
                    return 2
                if parsed.dry_run:
                    print(json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True))
                    return 0
                result = apply_host_preregistration_plan(
                    parsed.project_root,
                    plan,
                    ledger=parsed.ledger,
                )
            except (OSError, ValueError) as exc:
                print(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "kind": "ReadExpansionApplyResultV1",
                            "decision": "BLOCKED",
                            "mutation_count": 0,
                            "blockers": [str(exc)],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                return 2
            print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
            return 0
        try:
            if parsed.dry_run:
                raise ValueError("--dry-run requires --story-packet; mutation=0")
            missing = [
                name
                for name, value in {
                    "--path": parsed.requested_path,
                    "--reason": parsed.reason,
                    "--stage": parsed.stage,
                    "--agent": parsed.agent,
                    "--context-ref": parsed.context_ref,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(
                    "manual read-log missing required arguments: "
                    + ", ".join(missing)
                    + "; mutation=0"
                )
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
                supersedes_event_id=parsed.supersedes_event_id,
                ledger=parsed.ledger,
            )
        except (OSError, ValueError) as exc:
            print("Read Expansion Append: BLOCKED")
            print(f"- ERROR: {exc}")
            print("- mutation_count: 0")
            return 2
        print(f"appended: {parsed.ledger or READ_EXPANSION_LEDGER_REL.as_posix()}")
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
