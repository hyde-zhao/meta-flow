"""Typed dispatch attempt and immutable thread identity contracts.

This module is deliberately platform-neutral.  It models evidence supplied by
the platform or repository producer; it never upgrades a task label, a handoff
field, or a ledger declaration into a resolved runtime fact.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable


TERMINAL_ATTEMPT_STATUSES = frozenset({"completed", "failed", "interrupted", "cancelled", "superseded"})
NONTERMINAL_ATTEMPT_STATUSES = frozenset({"submitted", "running", "retrying"})
ALL_ATTEMPT_STATUSES = TERMINAL_ATTEMPT_STATUSES | NONTERMINAL_ATTEMPT_STATUSES


@dataclass(frozen=True)
class EvidenceFinding:
    code: str
    object_ref: str
    field: str
    message: str
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class DispatchAttempt:
    dispatch_id: str
    attempt_id: str
    status: str
    source_ref: str
    terminal_result: str | None = None
    supersedes_attempt_id: str | None = None
    thread_id: str | None = None
    agent_id: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ATTEMPT_STATUSES


@dataclass(frozen=True)
class AttemptTransition:
    attempt: DispatchAttempt
    findings: tuple[EvidenceFinding, ...]


@dataclass(frozen=True)
class ThreadRuntimeIdentity:
    """Identity fixed by a verified spawn receipt, not by a ledger label."""

    thread_id: str
    agent_id: str | None
    spawn_receipt_id: str
    resolved_profile: str
    config_sha256: str
    resolved_model: str
    resolved_reasoning_effort: str
    session_id: str
    session_epoch: str
    source_ref: str


def _finding(code: str, attempt: DispatchAttempt, field: str, message: str, *refs: str) -> EvidenceFinding:
    return EvidenceFinding(
        code=code,
        object_ref=attempt.source_ref or f"dispatch:{attempt.dispatch_id}/attempt:{attempt.attempt_id}",
        field=field,
        message=message,
        source_refs=tuple(ref for ref in refs if ref),
    )


def validate_attempt(attempt: DispatchAttempt) -> list[EvidenceFinding]:
    findings: list[EvidenceFinding] = []
    if not attempt.dispatch_id:
        findings.append(_finding("MISSING_DISPATCH_ID", attempt, "dispatch_id", "dispatch_id is required"))
    if not attempt.attempt_id:
        findings.append(_finding("MISSING_ATTEMPT_ID", attempt, "attempt_id", "attempt_id is required"))
    if attempt.status not in ALL_ATTEMPT_STATUSES:
        findings.append(_finding("INVALID_ATTEMPT_STATUS", attempt, "status", f"unsupported attempt status: {attempt.status or '-'}"))
    if attempt.is_terminal and not attempt.terminal_result:
        findings.append(_finding("MISSING_TERMINAL_RESULT", attempt, "terminal_result", "terminal attempt requires terminal_result"))
    if not attempt.source_ref:
        findings.append(_finding("MISSING_SOURCE_REF", attempt, "source_ref", "attempt evidence requires a source_ref"))
    return findings


def advance_attempt(attempt: DispatchAttempt, event: dict[str, Any]) -> AttemptTransition:
    """Apply a single append-only event without allowing terminal reopening."""

    findings = validate_attempt(attempt)
    event_dispatch = str(event.get("dispatch_id") or attempt.dispatch_id)
    event_attempt = str(event.get("attempt_id") or attempt.attempt_id)
    event_status = str(event.get("status") or "")
    if event_dispatch != attempt.dispatch_id:
        findings.append(_finding("DISPATCH_ID_MISMATCH", attempt, "dispatch_id", "event dispatch_id differs from attempt"))
    if event_attempt != attempt.attempt_id:
        findings.append(_finding("ATTEMPT_ID_MISMATCH", attempt, "attempt_id", "event attempt_id differs from attempt"))
    if event_status not in ALL_ATTEMPT_STATUSES:
        findings.append(_finding("INVALID_ATTEMPT_STATUS", attempt, "status", f"unsupported event status: {event_status or '-'}"))
        return AttemptTransition(attempt, tuple(findings))
    if attempt.is_terminal and event_status != "superseded":
        findings.append(_finding("ATTEMPT_ALREADY_TERMINAL", attempt, "status", "terminal attempt cannot transition again"))
        return AttemptTransition(attempt, tuple(findings))
    terminal_result = event.get("terminal_result") or attempt.terminal_result
    updated = replace(attempt, status=event_status, terminal_result=str(terminal_result) if terminal_result else None)
    findings.extend(validate_attempt(updated))
    return AttemptTransition(updated, tuple(findings))


def validate_attempt_graph(attempts: Iterable[DispatchAttempt]) -> list[EvidenceFinding]:
    """Validate identity uniqueness, supersession graph and terminal closure."""

    findings: list[EvidenceFinding] = []
    materialized = list(attempts)
    by_id: dict[tuple[str, str], DispatchAttempt] = {}
    by_attempt_id: dict[str, DispatchAttempt] = {}
    for attempt in materialized:
        findings.extend(validate_attempt(attempt))
        key = (attempt.dispatch_id, attempt.attempt_id)
        if key in by_id:
            findings.append(_finding("DUPLICATE_ATTEMPT_ID", attempt, "attempt_id", "dispatch_id + attempt_id must be unique", by_id[key].source_ref))
        by_id[key] = attempt
        if attempt.attempt_id in by_attempt_id and by_attempt_id[attempt.attempt_id].dispatch_id != attempt.dispatch_id:
            findings.append(_finding("CROSS_DISPATCH_ATTEMPT_ID", attempt, "attempt_id", "attempt_id cannot identify two dispatches", by_attempt_id[attempt.attempt_id].source_ref))
        by_attempt_id[attempt.attempt_id] = attempt
    for attempt in materialized:
        parent = attempt.supersedes_attempt_id
        if parent and parent not in by_attempt_id:
            findings.append(_finding("DANGLING_SUPERSEDES", attempt, "supersedes_attempt_id", "supersedes attempt does not exist"))
        if not attempt.is_terminal:
            findings.append(_finding("MISSING_TERMINAL_CLOSURE", attempt, "status", "execution attempt has no terminal status"))

    for attempt in materialized:
        seen: set[str] = set()
        current = attempt
        while current.supersedes_attempt_id:
            parent_id = current.supersedes_attempt_id
            if parent_id in seen or parent_id == attempt.attempt_id:
                findings.append(_finding("SUPERSEDES_CYCLE", attempt, "supersedes_attempt_id", "supersedes chain contains a cycle"))
                break
            seen.add(parent_id)
            parent = by_attempt_id.get(parent_id)
            if parent is None:
                break
            current = parent
    return sorted(findings, key=lambda item: (item.code, item.object_ref, item.field, item.message))


def validate_thread_identity_change(
    thread: ThreadRuntimeIdentity,
    *,
    requested_profile: str,
    config_sha256: str,
    resolved_model: str | None = None,
    resolved_reasoning_effort: str | None = None,
) -> list[EvidenceFinding]:
    """A followup cannot silently mutate its verified spawn identity."""

    mismatches: list[str] = []
    if requested_profile and requested_profile != thread.resolved_profile:
        mismatches.append("requested_profile")
    if config_sha256 and config_sha256 != thread.config_sha256:
        mismatches.append("config_sha256")
    if resolved_model and resolved_model != thread.resolved_model:
        mismatches.append("resolved_model")
    if resolved_reasoning_effort and resolved_reasoning_effort != thread.resolved_reasoning_effort:
        mismatches.append("resolved_reasoning_effort")
    if not mismatches:
        return []
    return [
        EvidenceFinding(
            code="NEW_SPAWN_REQUIRED",
            object_ref=thread.source_ref,
            field=",".join(mismatches),
            message="followup identity differs from immutable spawn receipt; create a new dispatch/thread",
            source_refs=(thread.spawn_receipt_id,),
        )
    ]
