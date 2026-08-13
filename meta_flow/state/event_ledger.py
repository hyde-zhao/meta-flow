"""Generic event ledger support for Meta Flow process evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from meta_flow.execution_control.contract import canonical_digest as execution_control_digest
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import _resolve_runtime_path, _resolve_runtime_ref
from meta_flow.project.read_contract import ReadContextProtocol
from meta_flow.semantics.attempt import (
    ALL_ATTEMPT_STATUSES as ALL_ATTEMPT_STATUSES,
)
from meta_flow.semantics.attempt import (
    NONTERMINAL_ATTEMPT_STATUSES as NONTERMINAL_ATTEMPT_STATUSES,
)
from meta_flow.semantics.attempt import (
    TERMINAL_ATTEMPT_STATUSES as TERMINAL_ATTEMPT_STATUSES,
)
from meta_flow.semantics.attempt import (
    TERMINAL_SUCCESS_RESULTS as TERMINAL_SUCCESS_RESULTS,
)
from meta_flow.semantics.attempt import (
    TERMINAL_SUCCESS_STATUSES as TERMINAL_SUCCESS_STATUSES,
)

PUBLIC_OPERATION_DECLARATIONS = (("event.append", ("meta-flow", "event", "append")),)
KNOWN_LEDGER_RELS = {
    "checkpoint": Path("process/state/CHECKPOINT-LEDGER.ndjson"),
    "handoff": Path("process/state/HANDOFF-LEDGER.ndjson"),
    "dispatch": Path("process/state/AGENT-DISPATCH-LEDGER.ndjson"),
    "run": Path("process/state/RUN-LEDGER.ndjson"),
    "gate": Path("process/state/GATE-LEDGER.ndjson"),
    "execution-control": Path("process/state/EXECUTION-CONTROL-LEDGER.ndjson"),
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
    "dispatch_correction": (
        "event_id",
        "event_type",
        "dispatch_id",
        "attempt_id",
        "corrects_event_id",
        "original_event_digest",
        "correction_fields",
        "reason",
        "evidence_refs",
        "created_at",
    ),
    "dispatch_attempt_closure": (
        "event_id",
        "event_type",
        "dispatch_id",
        "attempt_id",
        "story_id",
        "canonical_role",
        "checkpoint",
        "dispatch_mode",
        "tool_name",
        "closes_event_id",
        "original_event_digest",
        "disposition_key",
        "disposition_source_digest",
        "status",
        "terminal_result",
        "reason",
        "evidence_refs",
        "evidence_digests",
        "created_at",
    ),
}
DISPATCH_DISPOSITION_RESULT_BY_STATUS = {
    "blocked": "BLOCKED",
    "failed": "FAIL",
    "cancelled": "CANCELLED",
    "superseded": "SUPERSEDED",
    "interrupted": "INTERRUPTED",
}
GATE_APPROVAL_KIND_VERSION = 1
_EXECUTION_CONTROL_EVENT_FIELDS = frozenset(
    {
        "event_id",
        "event_type",
        "unit_id",
        "attempt_id",
        "evidence_ref",
        "check_result_digest",
        "observation_key_digest",
        "identity_digest",
        "contract_revision",
        "classification_digest",
        "slice_route_digest",
        "attempt_plan_digest",
        "observed_at",
        "payload_digest",
    }
)
_LOWER_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class GateApprovalKindV1(StrEnum):
    """人工批准的四种互斥语义，只有 checkpoint passage 能推进门禁。"""

    CHECKPOINT_PASSAGE = "checkpoint_passage"
    SCOPE_AMENDMENT = "scope_amendment"
    RECOVERY_AUTHORIZATION = "recovery_authorization"
    EVIDENCE_ACKNOWLEDGEMENT = "evidence_acknowledgement"


@dataclass(frozen=True)
class CanonicalGateApprovalProjectionV1:
    """唯一的 gate approval 投影；下游只能消费 ``passage``。"""

    event_id: str
    approval_kind: str
    passage: bool
    checkpoint: str
    result_ref: str
    cr_id: str
    work_id: str
    scope_version: int
    scope_digest: str
    finding_codes: tuple[str, ...]


_LEGACY_GATE_APPROVAL_MANIFEST_V1 = {
    "CR057-CP8-R1-HUMAN-GATE-APPROVED": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP8",
        "process/checks/CP8-CR-057-DELIVERY-READINESS.result.json",
    ),
    "CR058-CP2-SCOPE-BASELINE-APPROVED": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP2",
        "process/checks/CP2-CR-058-SCOPE-BASELINE.result.json",
    ),
    "CR058-CP3-DESIGN-R2-HUMAN-GATE-APPROVED": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP3",
        "process/checks/CP3-CR-058-DESIGN.result.json",
    ),
    "CR058-CP5-DESIGN-EVIDENCE-R2-HUMAN-GATE-APPROVED": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP5",
        "process/checks/CP5-CR-058-DESIGN-EVIDENCE.result.json",
    ),
    "CR058-CP5-IMPLEMENTATION-SCOPE-R3-HUMAN-GATE-APPROVED": (
        GateApprovalKindV1.SCOPE_AMENDMENT,
        "",
        "",
    ),
    "CR058-CP8-R2-HUMAN-GATE-APPROVED": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP8",
        "process/checks/CP8-CR-058-DELIVERY-READINESS.result.json",
    ),
    "CR058-CP8-R3-HUMAN-GATE-APPROVED": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP8",
        "process/checks/CP8-CR-058-DELIVERY-READINESS.result.json",
    ),
    "GATE-CR061-CP5-CONTRACT-COMPLETION-DELTA-APPROVED-20260727-V1": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP5",
        "process/checks/CP5-CR-061-CONTRACT-COMPLETION-DELTA.result.json",
    ),
    "GATE-CR061-CP8-CONTRACT-COMPLETION-APPROVED-20260727-V1": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP8",
        "process/checks/CP8-CR-061-CONTRACT-COMPLETION.result.json",
    ),
    "GATE-CR061-CP8-PUBLICATION-CONTRACT-APPROVED-20260727-V1": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP8",
        "process/checks/CP8-CR-061-PUBLICATION-CONTRACT.result.json",
    ),
    "GATE-CR061-CP8-HUMAN-GATE-BINDING-APPROVED-20260728-V1": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP8",
        "process/checks/CP8-CR-061-HUMAN-GATE-BINDING.result.json",
    ),
    "GATE-CR062-CP3-CONTROL-PLANE-DESIGN-APPROVED-20260729-V1": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP3",
        "process/checks/CP3-CR-062-DESIGN-SUCCESSOR-V7.result.json",
    ),
    "GATE-CR062-CP5-ALL-STORIES-LLD-APPROVED-20260729-V1": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP5",
        "process/checks/CP5-CR-062-ALL-STORIES.auto-precheck-V4.json",
    ),
    "GATE-CR062-CP5-ALL-STORIES-LLD-APPROVED-20260729-V2": (
        GateApprovalKindV1.CHECKPOINT_PASSAGE,
        "CP5",
        "process/checks/CP5-CR-062-ALL-STORIES.auto-precheck-V5.json",
    ),
    "GATE-CR062-CP6-ADMISSION-ENABLING-APPROVED-20260729-V1": (
        GateApprovalKindV1.SCOPE_AMENDMENT,
        "",
        "",
    ),
    "GATE-CR062-CP6-ADMISSION-LINEAGE-CORRECTION-APPROVED-20260729-V1": (
        GateApprovalKindV1.RECOVERY_AUTHORIZATION,
        "",
        "",
    ),
}
_GATE_APPROVAL_CORRECTION_EVENT = "gate_approval_kind_correction"
_GATE_APPROVAL_CUTOVER_EVENT = "gate_approval_kind_cutover"


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


@dataclass(frozen=True, slots=True)
class FindingObservationEventV1:
    """Execution Control append-only finding observation 的唯一 event wire。"""

    event_id: str
    event_type: str
    unit_id: str
    attempt_id: str
    evidence_ref: str
    check_result_digest: str
    observation_key_digest: str
    identity_digest: str
    contract_revision: int
    classification_digest: str
    slice_route_digest: str
    attempt_plan_digest: str
    observed_at: str
    payload_digest: str

    def __post_init__(self) -> None:
        if self.event_type != "finding_observation":
            raise ValueError("unsupported execution-control event type")
        for field in ("event_id", "unit_id", "attempt_id", "observed_at"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValueError(f"{field} is required")
        if not isinstance(self.evidence_ref, str) or not self.evidence_ref.startswith("process/"):
            raise ValueError("evidence_ref must be one process logical ref")
        if ".." in Path(self.evidence_ref).parts or "\\" in self.evidence_ref:
            raise ValueError("evidence_ref must not escape the process route")
        if type(self.contract_revision) is not int or self.contract_revision < 1:
            raise ValueError("contract_revision must be a positive integer")
        for field in (
            "check_result_digest",
            "observation_key_digest",
            "identity_digest",
            "classification_digest",
            "slice_route_digest",
            "attempt_plan_digest",
            "payload_digest",
        ):
            if not isinstance(getattr(self, field), str) or not _LOWER_SHA256_RE.fullmatch(
                getattr(self, field)
            ):
                raise ValueError(f"{field} must be one lowercase SHA-256 digest")
        expected_key = execution_control_digest(
            {
                "unit_id": self.unit_id,
                "attempt_id": self.attempt_id,
                "check_result_digest": self.check_result_digest,
                "identity_digest": self.identity_digest,
            }
        )
        if self.observation_key_digest != expected_key:
            raise ValueError("finding observation key is not canonically derived")
        if self.event_id != f"EC-OBS-{expected_key[:32]}":
            raise ValueError("finding observation event_id is not canonically derived")
        if self.payload_digest != execution_control_digest(self._payload_without_digest()):
            raise ValueError("finding observation payload digest mismatch")

    @classmethod
    def build(cls, **fields: Any) -> FindingObservationEventV1:
        seed = {**fields, "event_type": "finding_observation"}
        return cls(**seed, payload_digest=execution_control_digest(seed))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> FindingObservationEventV1:
        if (
            not isinstance(payload, Mapping)
            or frozenset(payload) != _EXECUTION_CONTROL_EVENT_FIELDS
        ):
            raise ValueError("finding observation fields mismatch")
        return cls(**{field: payload[field] for field in _EXECUTION_CONTROL_EVENT_FIELDS})

    def _payload_without_digest(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "unit_id": self.unit_id,
            "attempt_id": self.attempt_id,
            "evidence_ref": self.evidence_ref,
            "check_result_digest": self.check_result_digest,
            "observation_key_digest": self.observation_key_digest,
            "identity_digest": self.identity_digest,
            "contract_revision": self.contract_revision,
            "classification_digest": self.classification_digest,
            "slice_route_digest": self.slice_route_digest,
            "attempt_plan_digest": self.attempt_plan_digest,
            "observed_at": self.observed_at,
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self._payload_without_digest(), "payload_digest": self.payload_digest}


@dataclass(frozen=True, slots=True)
class FindingOccurrenceProjectionV1:
    decision: str
    identity_digest: str
    occurrence: int
    event_ids: tuple[str, ...]
    head_digest: str
    finding_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FindingLedgerProjectionV1:
    """一次扫描生成的只读投影；identity/key 查询不再重复扫描 ledger。"""

    decision: str
    finding_codes: tuple[str, ...]
    by_identity: Mapping[str, FindingOccurrenceProjectionV1]
    by_observation_key: Mapping[str, FindingObservationEventV1]


@dataclass(frozen=True, slots=True)
class FindingObservationAppendResultV1:
    decision: str
    conflicts: tuple[str, ...]
    occurrence: int
    head_digest: str
    domain_mutation_count: int
    idempotent: bool


def normalize_terminal_status(value: object) -> str:
    """Normalize status exactly once for every terminal-success consumer."""

    return str(value or "").strip().lower()


def typed_dispatch_attempt_from_event(
    event: Mapping[str, Any],
) -> tuple[TypedDispatchAttemptV1 | None, tuple[str, ...]]:
    """把公开 dispatch evidence 适配为唯一的 typed attempt 契约。"""

    required = (
        "event_id",
        "dispatch_id",
        "attempt_id",
        "story_id",
        "canonical_role",
        "checkpoint",
        "dispatch_mode",
    )
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


def dispatch_correction_index(
    events: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """验证 DispatchCorrectionV1，并按 exact source event id 建立唯一索引。"""

    sources = {
        str(event.get("event_id") or ""): event
        for event in events
        if event.get("event_type") != "dispatch_correction" and str(event.get("event_id") or "")
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    for correction in events:
        if correction.get("event_type") != "dispatch_correction":
            continue
        target_id = str(correction.get("corrects_event_id") or "")
        grouped.setdefault(target_id, []).append(correction)
    valid: dict[str, dict[str, Any]] = {}
    for target_id, candidates in sorted(grouped.items()):
        if len(candidates) != 1:
            errors.append(f"dispatch correction fork: {target_id or '-'}")
            continue
        correction = candidates[0]
        source = sources.get(target_id)
        if source is None:
            errors.append(f"dispatch correction target missing: {target_id or '-'}")
            continue
        fields = correction.get("correction_fields")
        evidence_refs = correction.get("evidence_refs")
        if not isinstance(fields, dict) or set(fields) != {"terminal_result"}:
            errors.append(f"dispatch correction fields invalid: {target_id}")
            continue
        terminal_result = str(fields.get("terminal_result") or "").strip()
        if not terminal_result:
            errors.append(f"dispatch correction terminal_result missing: {target_id}")
            continue
        if (
            source.get("event_type") != "dispatch"
            or not source.get("attempt_id")
            or normalize_terminal_status(source.get("status")) not in TERMINAL_ATTEMPT_STATUSES
        ):
            errors.append(f"dispatch correction source is not a terminal typed event: {target_id}")
            continue
        if source.get("terminal_result"):
            errors.append(f"dispatch correction source already has terminal_result: {target_id}")
            continue
        if str(correction.get("dispatch_id") or "") != str(source.get("dispatch_id") or "") or str(
            correction.get("attempt_id") or ""
        ) != str(source.get("attempt_id") or ""):
            errors.append(f"dispatch correction identity mismatch: {target_id}")
            continue
        expected_digest = canonical_digest(_clean_event(source))
        if str(correction.get("original_event_digest") or "") != expected_digest:
            errors.append(f"dispatch correction original_event_digest mismatch: {target_id}")
            continue
        if (
            not isinstance(evidence_refs, list)
            or not evidence_refs
            or any(
                not isinstance(ref, str) or not ref.startswith("process/") for ref in evidence_refs
            )
        ):
            errors.append(f"dispatch correction evidence_refs invalid: {target_id}")
            continue
        identity = {
            "corrects_event_id": target_id,
            "original_event_digest": expected_digest,
            "dispatch_id": str(source.get("dispatch_id") or ""),
            "attempt_id": str(source.get("attempt_id") or ""),
            "terminal_result": terminal_result,
        }
        expected_event_id = f"DISPATCH-CORRECTION-{canonical_digest(identity)[:32]}"
        if str(correction.get("event_id") or "") != expected_event_id:
            errors.append(f"dispatch correction event_id mismatch: {target_id}")
            continue
        valid[target_id] = correction
    return valid, errors


def dispatch_closure_index(
    events: list[dict[str, Any]],
    *,
    process_root: Path | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """验证由 exact disposition 支持的 append-only dispatch closure。"""

    sources = {
        str(event.get("event_id") or ""): event
        for event in events
        if event.get("event_type") in {"dispatch", "inline_fallback"}
        and str(event.get("event_id") or "")
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for closure in events:
        if closure.get("event_type") == "dispatch_attempt_closure":
            grouped.setdefault(str(closure.get("closes_event_id") or ""), []).append(closure)

    dispositions: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    if grouped and process_root is not None:
        from meta_flow.workflow.terminal_lineage import (
            load_terminal_lineage_dispositions,
        )

        dispositions, disposition_errors = load_terminal_lineage_dispositions(
            process_root.resolve()
        )
        errors.extend(
            f"dispatch closure disposition invalid: {error}" for error in disposition_errors
        )

    valid: dict[str, dict[str, Any]] = {}
    for source_id, candidates in sorted(grouped.items()):
        if len(candidates) != 1:
            errors.append(f"dispatch closure fork: {source_id or '-'}")
            continue
        closure = candidates[0]
        source = sources.get(source_id)
        if source is None:
            errors.append(f"dispatch closure source missing: {source_id or '-'}")
            continue
        dispatch_id = str(source.get("dispatch_id") or "")
        attempt_id = str(source.get("attempt_id") or "")
        expected_source_digest = canonical_digest(_clean_event(source))
        disposition_key = f"dispatch:{dispatch_id}"
        status = normalize_terminal_status(closure.get("status"))
        expected_result = DISPATCH_DISPOSITION_RESULT_BY_STATUS.get(status)
        if source.get("event_type") not in {"dispatch", "inline_fallback"}:
            errors.append(f"dispatch closure source type invalid: {source_id}")
            continue
        if (
            not attempt_id
            or normalize_terminal_status(source.get("status")) in TERMINAL_ATTEMPT_STATUSES
        ):
            errors.append(
                f"dispatch closure source is not a nonterminal typed attempt: {source_id}"
            )
            continue
        if (
            str(closure.get("dispatch_id") or "") != dispatch_id
            or str(closure.get("attempt_id") or "") != attempt_id
        ):
            errors.append(f"dispatch closure identity mismatch: {source_id}")
            continue
        if str(closure.get("original_event_digest") or "") != expected_source_digest:
            errors.append(f"dispatch closure original_event_digest mismatch: {source_id}")
            continue
        if str(closure.get("disposition_key") or "") != disposition_key:
            errors.append(f"dispatch closure disposition_key mismatch: {source_id}")
            continue
        if str(closure.get("disposition_source_digest") or "") != expected_source_digest:
            errors.append(f"dispatch closure disposition_source_digest mismatch: {source_id}")
            continue
        if expected_result is None or str(closure.get("terminal_result") or "") != expected_result:
            errors.append(f"dispatch closure terminal status/result invalid: {source_id}")
            continue
        for field in (
            "story_id",
            "canonical_role",
            "checkpoint",
            "dispatch_mode",
            "tool_name",
        ):
            if str(closure.get(field) or "") != str(source.get(field) or ""):
                errors.append(f"dispatch closure source field mismatch: {source_id}:{field}")
        evidence_refs = closure.get("evidence_refs")
        evidence_digests = closure.get("evidence_digests")
        if (
            not isinstance(evidence_refs, list)
            or not evidence_refs
            or not isinstance(evidence_digests, dict)
            or set(evidence_digests) != set(evidence_refs)
        ):
            errors.append(f"dispatch closure evidence invalid: {source_id}")
            continue
        disposition = dispositions.get(disposition_key) if process_root is not None else None
        if process_root is not None:
            if disposition is None:
                errors.append(f"dispatch closure disposition missing: {source_id}")
                continue
            if (
                str(disposition.get("source_digest") or "") != expected_source_digest
                or normalize_terminal_status(disposition.get("terminal_status")) != status
                or str(disposition.get("reason") or "") != str(closure.get("reason") or "")
                or disposition.get("evidence_refs") != evidence_refs
                or disposition.get("evidence_digests") != evidence_digests
            ):
                errors.append(f"dispatch closure disposition binding mismatch: {source_id}")
                continue
        identity = {
            "closes_event_id": source_id,
            "original_event_digest": expected_source_digest,
            "disposition_key": disposition_key,
            "terminal_status": status,
        }
        expected_event_id = f"DISPATCH-CLOSURE-{canonical_digest(identity)[:32]}"
        if str(closure.get("event_id") or "") != expected_event_id:
            errors.append(f"dispatch closure event_id mismatch: {source_id}")
            continue
        if not any(
            error.startswith(f"dispatch closure source field mismatch: {source_id}:")
            for error in errors
        ):
            valid[source_id] = closure
    return valid, errors


def _effective_dispatch_event(
    event: Mapping[str, Any],
    corrections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    effective = _clean_event(event)
    correction = corrections.get(str(event.get("event_id") or ""))
    if correction is not None:
        fields = correction.get("correction_fields")
        if isinstance(fields, Mapping):
            effective.update(fields)
    return effective


def project_dispatch_attempt(input_value: ProjectionInputV1) -> ProjectionResultV1:
    """Project one dispatch identity without using event_id as a dispatch fallback."""

    matching = [
        event
        for event in input_value.events
        if str(event.get("dispatch_id") or "") == input_value.dispatch_id
    ]
    corrected_attempts = {
        (str(event.get("dispatch_id") or ""), str(event.get("attempt_id") or ""))
        for event in matching
        if event.get("corrects_missing_event_id") is True
    }
    corrections, correction_errors = dispatch_correction_index(
        [dict(event) for event in input_value.events]
    )
    findings: list[str] = list(correction_errors)
    typed: list[TypedDispatchAttemptV1] = []
    for event in matching:
        if str(event.get("event_type") or "") not in {
            "dispatch",
            "inline_fallback",
            "dispatch_attempt_closure",
        }:
            continue
        attempt, errors = typed_dispatch_attempt_from_event(
            _effective_dispatch_event(event, corrections)
        )
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
        return HandoffDispatchRecordV1(
            tuple(sorted((str(key), str(value)) for key, value in dispatch.items()))
        )
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
    if "EXECUTION-CONTROL" in name:
        return "execution-control"
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


def load_events(
    path: Path,
    *,
    read_context: ReadContextProtocol | None = None,
    logical_ref: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.is_file():
        return [], [f"event ledger missing: {path}"]
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    if read_context is None:
        text = path.read_text(encoding="utf-8")
    else:
        if not logical_ref:
            raise ValueError("logical_ref is required with read_context")
        text = read_context.read_text(logical_ref)
    for line_no, line in enumerate(text.splitlines(), 1):
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


def execution_control_ledger_preimage(path: Path) -> str:
    """返回 exact ledger bytes digest；缺失文件的 preimage 是空 bytes。"""

    data = path.read_bytes() if path.is_file() else b""
    return hashlib.sha256(data).hexdigest()


def project_execution_control_ledger(
    events: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
) -> FindingLedgerProjectionV1:
    """一次扫描 closed append-only events，生成 identity/key 的只读索引。"""

    findings: list[str] = []
    seen_event_ids: set[str] = set()
    seen_keys: set[str] = set()
    grouped: dict[str, list[FindingObservationEventV1]] = {}
    by_key: dict[str, FindingObservationEventV1] = {}
    for raw in events:
        clean = {str(key): value for key, value in raw.items() if key != "_line_no"}
        try:
            event = FindingObservationEventV1.from_mapping(clean)
        except (TypeError, ValueError):
            findings.append("EXECUTION_CONTROL_EVENT_INVALID")
            continue
        if event.event_id in seen_event_ids:
            findings.append("EXECUTION_CONTROL_EVENT_ID_DUPLICATE")
        if event.observation_key_digest in seen_keys:
            findings.append("EXECUTION_CONTROL_OBSERVATION_KEY_DUPLICATE")
        seen_event_ids.add(event.event_id)
        seen_keys.add(event.observation_key_digest)
        grouped.setdefault(event.identity_digest, []).append(event)
        by_key.setdefault(event.observation_key_digest, event)
    codes = tuple(sorted(set(findings)))
    decision = "BLOCKED" if codes else "PASS"
    by_identity = {
        identity: FindingOccurrenceProjectionV1(
            decision=decision,
            identity_digest=identity,
            occurrence=len(matching),
            event_ids=tuple(event.event_id for event in matching),
            head_digest=execution_control_digest([event.payload_digest for event in matching]),
            finding_codes=codes,
        )
        for identity, matching in grouped.items()
    }
    return FindingLedgerProjectionV1(
        decision=decision,
        finding_codes=codes,
        by_identity=MappingProxyType(by_identity),
        by_observation_key=MappingProxyType(by_key),
    )


def project_finding_occurrence(
    events: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] | FindingLedgerProjectionV1,
    *,
    identity_digest: str,
) -> FindingOccurrenceProjectionV1:
    """从一次构建的投影 O(1) 查询；兼容 typed events 输入并先构建投影。"""

    if not _LOWER_SHA256_RE.fullmatch(identity_digest):
        raise ValueError("identity_digest must be one lowercase SHA-256 digest")
    projected = (
        events
        if isinstance(events, FindingLedgerProjectionV1)
        else project_execution_control_ledger(events)
    )
    existing = projected.by_identity.get(identity_digest)
    if existing is not None:
        return existing
    return FindingOccurrenceProjectionV1(
        decision=projected.decision,
        identity_digest=identity_digest,
        occurrence=0,
        event_ids=(),
        head_digest=execution_control_digest([]),
        finding_codes=projected.finding_codes,
    )


def append_execution_control_event(
    path: Path,
    event: FindingObservationEventV1,
    *,
    expected_preimage_digest: str,
) -> FindingObservationAppendResultV1:
    """在持有外部 project lock 时按 exact preimage append；重放不抬高 occurrence。"""

    if not _LOWER_SHA256_RE.fullmatch(expected_preimage_digest):
        raise ValueError("expected_preimage_digest must be one lowercase SHA-256 digest")
    current_preimage = execution_control_ledger_preimage(path)
    if current_preimage != expected_preimage_digest:
        return FindingObservationAppendResultV1(
            "BLOCKED", ("EXECUTION_CONTROL_LEDGER_PREIMAGE_DRIFT",), 0, "", 0, False
        )
    if path.is_file():
        events, errors = load_events(path)
        if errors:
            return FindingObservationAppendResultV1(
                "BLOCKED", ("EXECUTION_CONTROL_LEDGER_INVALID",), 0, "", 0, False
            )
    else:
        events = []
    ledger_projection = project_execution_control_ledger(events)
    projection = project_finding_occurrence(
        ledger_projection, identity_digest=event.identity_digest
    )
    if projection.decision != "PASS":
        return FindingObservationAppendResultV1(
            "BLOCKED", projection.finding_codes, projection.occurrence, projection.head_digest, 0, False
        )
    existing = ledger_projection.by_observation_key.get(event.observation_key_digest)
    if existing is not None:
        if existing.payload_digest != event.payload_digest:
            return FindingObservationAppendResultV1(
                "BLOCKED",
                ("EXECUTION_CONTROL_OBSERVATION_REPLAY_MISMATCH",),
                projection.occurrence,
                projection.head_digest,
                0,
                False,
            )
        return FindingObservationAppendResultV1(
            "PASS", (), projection.occurrence, projection.head_digest, 0, True
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            event.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        mutated = int(execution_control_ledger_preimage(path) != expected_preimage_digest)
        return FindingObservationAppendResultV1(
            "PARTIAL_MUTATION",
            ("EXECUTION_CONTROL_EVENT_APPEND_PARTIAL",),
            projection.occurrence,
            projection.head_digest,
            mutated,
            False,
        )
    final = project_finding_occurrence(
        [*events, event.as_dict()], identity_digest=event.identity_digest
    )
    return FindingObservationAppendResultV1(
        "PASS", (), final.occurrence, final.head_digest, 1, False
    )


def _clean_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in event.items() if key != "_line_no"}


def _typed_gate_approval_findings(event: Mapping[str, Any]) -> tuple[str, ...]:
    findings: list[str] = []
    if event.get("approval_kind_version") != GATE_APPROVAL_KIND_VERSION:
        findings.append("GATE_APPROVAL_KIND_VERSION_INVALID")
    try:
        approval_kind = GateApprovalKindV1(str(event.get("approval_kind") or ""))
    except ValueError:
        findings.append("GATE_APPROVAL_KIND_UNKNOWN")
        return tuple(findings)
    for field in ("event_id", "gate", "cr_id", "work_id"):
        if not str(event.get(field) or "").strip():
            findings.append(f"GATE_APPROVAL_{field.upper()}_REQUIRED")
    if str(event.get("decision") or "").lower() != "approve":
        findings.append("GATE_APPROVAL_DECISION_INVALID")
    if str(event.get("status") or "").lower() != "approved":
        findings.append("GATE_APPROVAL_STATUS_INVALID")
    if approval_kind is GateApprovalKindV1.CHECKPOINT_PASSAGE:
        if re.fullmatch(r"CP[0-8]", str(event.get("checkpoint") or "").upper()) is None:
            findings.append("GATE_APPROVAL_CHECKPOINT_REQUIRED")
        if not str(event.get("result_ref") or "").strip():
            findings.append("GATE_APPROVAL_RESULT_REF_REQUIRED")
    elif approval_kind is GateApprovalKindV1.SCOPE_AMENDMENT:
        scope_version = event.get("scope_version")
        if (
            not isinstance(scope_version, int)
            or isinstance(scope_version, bool)
            or scope_version < 1
        ):
            findings.append("GATE_APPROVAL_SCOPE_VERSION_REQUIRED")
        if not str(event.get("scope_digest") or "").strip():
            findings.append("GATE_APPROVAL_SCOPE_DIGEST_REQUIRED")
        if not event.get("authorized_actions"):
            findings.append("GATE_APPROVAL_AUTHORIZED_ACTIONS_REQUIRED")
        if not (event.get("decision_ref") or event.get("checkpoint_ref")):
            findings.append("GATE_APPROVAL_DECISION_REF_REQUIRED")
    elif approval_kind is GateApprovalKindV1.RECOVERY_AUTHORIZATION:
        recovery_ordinal = event.get("recovery_ordinal")
        if (
            not isinstance(recovery_ordinal, int)
            or isinstance(recovery_ordinal, bool)
            or recovery_ordinal < 1
        ):
            findings.append("GATE_APPROVAL_RECOVERY_ORDINAL_REQUIRED")
        if not event.get("authorized_actions"):
            findings.append("GATE_APPROVAL_AUTHORIZED_ACTIONS_REQUIRED")
        if not (event.get("decision_ref") or event.get("checkpoint_ref")):
            findings.append("GATE_APPROVAL_DECISION_REF_REQUIRED")
    else:
        if not event.get("evidence_refs"):
            findings.append("GATE_APPROVAL_EVIDENCE_REFS_REQUIRED")
        if not event.get("evidence_digests"):
            findings.append("GATE_APPROVAL_EVIDENCE_DIGESTS_REQUIRED")
        if not str(event.get("acknowledgement_decision") or "").strip():
            findings.append("GATE_APPROVAL_ACKNOWLEDGEMENT_DECISION_REQUIRED")
    return tuple(sorted(set(findings)))


def _gate_projection(
    event: Mapping[str, Any],
    *,
    approval_kind: GateApprovalKindV1 | None,
    checkpoint: str = "",
    result_ref: str = "",
    findings: tuple[str, ...] = (),
) -> CanonicalGateApprovalProjectionV1:
    scope_version = event.get("scope_version")
    return CanonicalGateApprovalProjectionV1(
        event_id=str(event.get("event_id") or ""),
        approval_kind=str(approval_kind or ""),
        passage=(
            not findings
            and approval_kind is GateApprovalKindV1.CHECKPOINT_PASSAGE
            and bool(checkpoint)
            and bool(result_ref)
        ),
        checkpoint=checkpoint,
        result_ref=result_ref,
        cr_id=str(event.get("cr_id") or ""),
        work_id=str(event.get("work_id") or ""),
        scope_version=(
            scope_version
            if isinstance(scope_version, int) and not isinstance(scope_version, bool)
            else 0
        ),
        scope_digest=str(event.get("scope_digest") or ""),
        finding_codes=tuple(sorted(set(findings))),
    )


def _legacy_gate_corrections(
    events: tuple[Mapping[str, Any], ...],
    legacy_events: dict[str, Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], tuple[str, ...]]:
    corrections = [
        event
        for event in events
        if str(event.get("event_type") or "") == _GATE_APPROVAL_CORRECTION_EVENT
    ]
    cutovers = [
        event
        for event in events
        if str(event.get("event_type") or "") == _GATE_APPROVAL_CUTOVER_EVENT
    ]
    if not corrections and not cutovers:
        return {}, ()
    findings: list[str] = []
    event_ids = [str(event.get("event_id") or "") for event in events]
    if len(event_ids) != len(set(event_ids)):
        findings.append("GATE_APPROVAL_EVENT_ID_DUPLICATE")
    by_original: dict[str, Mapping[str, Any]] = {}
    for correction in corrections:
        original_id = str(correction.get("corrects_event_id") or "")
        original = legacy_events.get(original_id)
        try:
            approval_kind = GateApprovalKindV1(str(correction.get("approval_kind") or ""))
        except ValueError:
            approval_kind = None
        if correction.get("approval_kind_version") != GATE_APPROVAL_KIND_VERSION:
            findings.append("GATE_APPROVAL_CORRECTION_VERSION_INVALID")
        if not original_id or original is None:
            findings.append("GATE_APPROVAL_CORRECTION_TARGET_UNKNOWN")
            continue
        if original_id in by_original:
            findings.append("GATE_APPROVAL_CORRECTION_TARGET_DUPLICATE")
            continue
        if approval_kind is None:
            findings.append("GATE_APPROVAL_CORRECTION_KIND_UNKNOWN")
            continue
        expected_kind, expected_checkpoint, expected_result_ref = _LEGACY_GATE_APPROVAL_MANIFEST_V1[
            original_id
        ]
        if approval_kind is not expected_kind:
            findings.append("GATE_APPROVAL_CORRECTION_KIND_MISMATCH")
        if str(correction.get("original_event_digest") or "") != canonical_digest(
            _clean_event(original)
        ):
            findings.append("GATE_APPROVAL_CORRECTION_DIGEST_MISMATCH")
        if str(correction.get("cr_id") or "") != str(original.get("cr_id") or "") or str(
            correction.get("work_id") or ""
        ) != str(original.get("work_id") or ""):
            findings.append("GATE_APPROVAL_CORRECTION_CROSSES_TARGET")
        if approval_kind is GateApprovalKindV1.CHECKPOINT_PASSAGE and (
            str(correction.get("checkpoint") or "").upper() != expected_checkpoint
            or str(correction.get("result_ref") or "") != expected_result_ref
        ):
            findings.append("GATE_APPROVAL_CORRECTION_PASSAGE_BINDING_MISMATCH")
        by_original[original_id] = correction
    if len(cutovers) != 1:
        findings.append("GATE_APPROVAL_CUTOVER_NOT_UNIQUE")
        return {}, tuple(sorted(set(findings)))
    cutover = cutovers[0]
    correction_ids = sorted(str(correction.get("event_id") or "") for correction in corrections)
    source_events = [
        _clean_event(event)
        for event in events
        if str(event.get("event_type") or "")
        not in {_GATE_APPROVAL_CORRECTION_EVENT, _GATE_APPROVAL_CUTOVER_EVENT}
    ]
    manifest = [
        {
            "event_id": event_id,
            "approval_kind": str(kind),
            "checkpoint": checkpoint,
            "result_ref": result_ref,
        }
        for event_id, (kind, checkpoint, result_ref) in sorted(
            _LEGACY_GATE_APPROVAL_MANIFEST_V1.items()
        )
    ]
    if (
        cutover.get("approval_kind_version") != GATE_APPROVAL_KIND_VERSION
        or str(cutover.get("status") or "") != "complete"
        or int(cutover.get("legacy_event_count") or 0) != len(legacy_events)
        or int(cutover.get("correction_event_count") or 0) != len(corrections)
        or sorted(cutover.get("correction_event_ids") or []) != correction_ids
        or str(cutover.get("gate_ledger_preimage_digest") or "") != canonical_digest(source_events)
        or str(cutover.get("legacy_manifest_digest") or "") != canonical_digest(manifest)
        or not str(cutover.get("plan_digest") or "")
    ):
        findings.append("GATE_APPROVAL_CUTOVER_BINDING_INVALID")
    if set(by_original) != set(_LEGACY_GATE_APPROVAL_MANIFEST_V1):
        findings.append("GATE_APPROVAL_CUTOVER_PARTIAL")
    if findings:
        return {}, tuple(sorted(set(findings)))
    return by_original, ()


def project_gate_approvals(
    events: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
) -> tuple[CanonicalGateApprovalProjectionV1, ...]:
    """投影 typed 与精确 legacy approval，禁止从 gate 文本推断 checkpoint。"""

    source = tuple(events)
    approvals = [
        event for event in source if str(event.get("event_type") or "") == "human_gate_approval"
    ]
    legacy_events = {
        str(event.get("event_id") or ""): event
        for event in approvals
        if event.get("approval_kind_version") is None
        and str(event.get("event_id") or "") in _LEGACY_GATE_APPROVAL_MANIFEST_V1
    }
    legacy_corrections, correction_findings = _legacy_gate_corrections(source, legacy_events)
    migration_present = any(
        str(event.get("event_type") or "")
        in {_GATE_APPROVAL_CORRECTION_EVENT, _GATE_APPROVAL_CUTOVER_EVENT}
        for event in source
    )
    projections: list[CanonicalGateApprovalProjectionV1] = []
    for event in approvals:
        event_id = str(event.get("event_id") or "")
        if event.get("approval_kind_version") is not None:
            findings = _typed_gate_approval_findings(event)
            try:
                approval_kind = GateApprovalKindV1(str(event.get("approval_kind") or ""))
            except ValueError:
                approval_kind = None
            checkpoint = (
                str(event.get("checkpoint") or "").upper()
                if approval_kind is GateApprovalKindV1.CHECKPOINT_PASSAGE
                else ""
            )
            result_ref = (
                str(event.get("result_ref") or "")
                if approval_kind is GateApprovalKindV1.CHECKPOINT_PASSAGE
                else ""
            )
            projections.append(
                _gate_projection(
                    event,
                    approval_kind=approval_kind,
                    checkpoint=checkpoint,
                    result_ref=result_ref,
                    findings=findings,
                )
            )
            continue
        manifest_entry = _LEGACY_GATE_APPROVAL_MANIFEST_V1.get(event_id)
        if manifest_entry is None:
            findings = ["GATE_APPROVAL_LEGACY_UNKNOWN"]
            if (
                str(event.get("decision") or "").lower() != "approve"
                or str(event.get("status") or "").lower() != "approved"
                or not str(event.get("cr_id") or "")
                or not str(event.get("work_id") or "")
            ):
                findings.append("GATE_APPROVAL_LEGACY_BINDING_INVALID")
            projections.append(
                _gate_projection(
                    event,
                    approval_kind=None,
                    findings=tuple(findings),
                )
            )
            continue
        approval_kind, checkpoint, result_ref = manifest_entry
        findings = list(correction_findings)
        if (
            str(event.get("decision") or "").lower() != "approve"
            or str(event.get("status") or "").lower() != "approved"
            or not str(event.get("cr_id") or "")
            or not str(event.get("work_id") or "")
        ):
            findings.append("GATE_APPROVAL_LEGACY_BINDING_INVALID")
        if migration_present and event_id not in legacy_corrections:
            findings.append("GATE_APPROVAL_CUTOVER_PARTIAL")
        projections.append(
            _gate_projection(
                event,
                approval_kind=approval_kind,
                checkpoint=checkpoint,
                result_ref=result_ref,
                findings=tuple(findings),
            )
        )
    return tuple(projections)


def build_gate_approval_kind_migration_plan(
    events: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    *,
    decision_ref: str,
) -> dict[str, Any]:
    """生成 16 correction + 1 cutover 的纯内存计划，永远不写 ledger。"""

    source = tuple(events)
    legacy = {
        str(event.get("event_id") or ""): event
        for event in source
        if str(event.get("event_type") or "") == "human_gate_approval"
        and event.get("approval_kind_version") is None
    }
    blockers: list[str] = []
    legacy_rows = [
        event
        for event in source
        if str(event.get("event_type") or "") == "human_gate_approval"
        and event.get("approval_kind_version") is None
    ]
    if len(legacy) != len(legacy_rows):
        blockers.append("LEGACY_GATE_APPROVAL_ID_DUPLICATE")
    if set(legacy) != set(_LEGACY_GATE_APPROVAL_MANIFEST_V1):
        blockers.append("LEGACY_GATE_APPROVAL_MANIFEST_MISMATCH")
    if any(
        str(event.get("event_type") or "")
        in {_GATE_APPROVAL_CORRECTION_EVENT, _GATE_APPROVAL_CUTOVER_EVENT}
        for event in source
    ):
        blockers.append("GATE_APPROVAL_MIGRATION_ALREADY_PRESENT")
    manifest = [
        {
            "event_id": event_id,
            "approval_kind": str(kind),
            "checkpoint": checkpoint,
            "result_ref": result_ref,
        }
        for event_id, (kind, checkpoint, result_ref) in sorted(
            _LEGACY_GATE_APPROVAL_MANIFEST_V1.items()
        )
    ]
    if blockers:
        return {
            "schema_version": 1,
            "kind": "GateApprovalKindMigrationPlanV1",
            "decision": "BLOCKED",
            "dry_run": True,
            "mutation_count": 0,
            "classification_counts": {},
            "planned_append_count": 0,
            "append_events": [],
            "blockers": sorted(set(blockers)),
            "gate_ledger_preimage_digest": canonical_digest(
                [_clean_event(event) for event in source]
            ),
            "legacy_manifest_digest": canonical_digest(manifest),
            "plan_digest": "",
        }
    corrections: list[dict[str, Any]] = []
    counts = {kind.value: 0 for kind in GateApprovalKindV1}
    for index, (event_id, (approval_kind, checkpoint, result_ref)) in enumerate(
        sorted(_LEGACY_GATE_APPROVAL_MANIFEST_V1.items()), 1
    ):
        original = legacy[event_id]
        counts[approval_kind.value] += 1
        correction: dict[str, Any] = {
            "event_id": f"GATE-APPROVAL-KIND-CORRECTION-{index:02d}-V1",
            "event_type": _GATE_APPROVAL_CORRECTION_EVENT,
            "gate": "GATE_APPROVAL_KIND_V1_MIGRATION",
            "status": "corrected",
            "approval_kind_version": GATE_APPROVAL_KIND_VERSION,
            "approval_kind": approval_kind.value,
            "corrects_event_id": event_id,
            "original_event_digest": canonical_digest(_clean_event(original)),
            "cr_id": str(original.get("cr_id") or ""),
            "work_id": str(original.get("work_id") or ""),
            "decision_ref": decision_ref,
        }
        if approval_kind is GateApprovalKindV1.CHECKPOINT_PASSAGE:
            correction["checkpoint"] = checkpoint
            correction["result_ref"] = result_ref
        corrections.append(correction)
    preimage_digest = canonical_digest([_clean_event(event) for event in source])
    manifest_digest = canonical_digest(manifest)
    plan_seed = {
        "schema_version": 1,
        "kind": "GateApprovalKindMigrationPlanV1",
        "decision": "READY",
        "dry_run": True,
        "mutation_count": 0,
        "classification_counts": counts,
        "gate_ledger_preimage_digest": preimage_digest,
        "legacy_manifest_digest": manifest_digest,
        "correction_events": corrections,
        "decision_ref": decision_ref,
    }
    plan_digest = canonical_digest(plan_seed)
    cutover = {
        "event_id": "GATE-APPROVAL-KIND-CUTOVER-V1",
        "event_type": _GATE_APPROVAL_CUTOVER_EVENT,
        "gate": "GATE_APPROVAL_KIND_V1_MIGRATION",
        "status": "complete",
        "approval_kind_version": GATE_APPROVAL_KIND_VERSION,
        "legacy_event_count": len(legacy),
        "correction_event_count": len(corrections),
        "correction_event_ids": [str(correction["event_id"]) for correction in corrections],
        "gate_ledger_preimage_digest": preimage_digest,
        "legacy_manifest_digest": manifest_digest,
        "plan_digest": plan_digest,
        "decision_ref": decision_ref,
    }
    return {
        **plan_seed,
        "planned_append_count": len(corrections) + 1,
        "append_events": [*corrections, cutover],
        "blockers": [],
        "plan_digest": plan_digest,
    }


def validate_event_before_append(
    path: Path, event: Mapping[str, Any], *, ledger_type: str = ""
) -> dict[str, Any]:
    """Fail before directory creation or file mutation when required fields are absent."""

    if not isinstance(event, Mapping):
        raise TypeError("event must be an object")
    resolved_type = ledger_type or _ledger_type_from_path(path)
    if resolved_type == "execution-control":
        return FindingObservationEventV1.from_mapping(event).as_dict()
    event_type = str(event.get("event_type") or "")
    if event_type == "ledger_compacted":
        required = COMPACT_MARKER_REQUIRED_FIELDS
    elif resolved_type == "dispatch":
        required = DISPATCH_EVENT_REQUIRED_FIELDS.get(
            event_type, LEDGER_REQUIRED_FIELDS["dispatch"]
        )
    else:
        required = LEDGER_REQUIRED_FIELDS.get(resolved_type, ("event_type",))
    missing = [field for field in required if not event.get(field)]
    if resolved_type == "dispatch" and event_type in {"dispatch", "inline_fallback"}:
        _attempt, typed_errors = typed_dispatch_attempt_from_event(event)
        missing.extend(error.removeprefix("MISSING_TYPED_").lower() for error in typed_errors)
    if missing:
        unique = ", ".join(dict.fromkeys(missing))
        raise ValueError(f"invalid {resolved_type} event missing required fields: {unique}")
    if resolved_type == "dispatch" and event_type == "dispatch_correction":
        existing, load_errors = load_events(path)
        if load_errors and path.is_file():
            raise ValueError(
                "dispatch correction source ledger is invalid: " + "; ".join(load_errors)
            )
        _index, correction_errors = dispatch_correction_index([*existing, dict(event)])
        if correction_errors:
            raise ValueError("invalid dispatch correction: " + "; ".join(correction_errors))
    if resolved_type == "dispatch" and event_type == "dispatch_attempt_closure":
        existing, load_errors = load_events(path)
        if load_errors and path.is_file():
            raise ValueError("dispatch closure source ledger is invalid: " + "; ".join(load_errors))
        _index, closure_errors = dispatch_closure_index(
            [*existing, dict(event)],
            process_root=path.parent.parent,
        )
        if closure_errors:
            raise ValueError("invalid dispatch closure: " + "; ".join(closure_errors))
    if resolved_type == "gate" and event_type == "human_gate_approval":
        findings = _typed_gate_approval_findings(event)
        if findings:
            raise ValueError("invalid gate human approval: " + ", ".join(findings))
    return {key: value for key, value in event.items() if key != "_line_no"}


def append_event(path: Path, event: dict[str, Any]) -> Path:
    payload = validate_event_before_append(path, event)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def render_appended_event(
    path: Path,
    event: dict[str, Any],
    *,
    before_text: str | None = None,
) -> str:
    """Render append-only ledger content without mutating the ledger."""

    payload = validate_event_before_append(path, event)
    before = (
        before_text
        if before_text is not None
        else path.read_text(encoding="utf-8")
        if path.is_file()
        else ""
    )
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
        "terminal_result": "PASS"
        if normalize_terminal_status(status) in TERMINAL_SUCCESS_STATUSES
        else "FAIL",
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


def append_dispatch_event(
    project_root: Path, event: dict[str, Any], *, ledger: Path | None = None
) -> Path:
    path = ledger.resolve() if ledger else ledger_path(project_root.resolve(), "dispatch")
    return append_event(path, event)


def validate_event_ledger(
    path: Path,
    *,
    ledger_type: str = "",
    read_context: ReadContextProtocol | None = None,
    logical_ref: str = "",
) -> tuple[list[str], list[str]]:
    ledger_type = ledger_type or _ledger_type_from_path(path)
    events, errors = load_events(
        path,
        read_context=read_context,
        logical_ref=logical_ref,
    )
    warnings: list[str] = []
    if errors:
        return errors, warnings
    if not events:
        warnings.append("event ledger is empty")
        return errors, warnings
    required = LEDGER_REQUIRED_FIELDS.get(ledger_type, ("event_type",))
    correction_index: dict[str, dict[str, Any]] = {}
    closure_index: dict[str, dict[str, Any]] = {}
    if ledger_type == "dispatch":
        correction_index, correction_errors = dispatch_correction_index(events)
        errors.extend(correction_errors)
        closure_index, closure_errors = dispatch_closure_index(
            events,
            process_root=path.parent.parent,
        )
        errors.extend(closure_errors)
    seen_event_ids: set[str] = set()
    typed_attempt_events: dict[tuple[str, str], list[dict[str, Any]]] = {}
    corrected_attempts = {
        (str(event.get("dispatch_id") or ""), str(event.get("attempt_id") or ""))
        for event in events
        if event.get("corrects_missing_event_id") is True
    }
    for event in events:
        line_no = int(event.get("_line_no") or 0)
        if ledger_type == "execution-control":
            try:
                FindingObservationEventV1.from_mapping(_clean_event(event))
            except (TypeError, ValueError) as exc:
                errors.append(f"line {line_no}: invalid execution-control event: {exc}")
        if event.get("event_type") == "ledger_compacted":
            fields = COMPACT_MARKER_REQUIRED_FIELDS
        elif ledger_type == "dispatch":
            fields = DISPATCH_EVENT_REQUIRED_FIELDS.get(
                str(event.get("event_type") or ""), required
            )
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
            warnings.append(
                f"line {line_no}: legacy dispatch event lacks event_id; identity is self-declared-unverifiable"
            )
        elif ledger_type != "dispatch":
            errors.append(f"line {line_no}: missing event_id")

        if (
            ledger_type == "dispatch"
            and event.get("event_type") == "dispatch"
            and not event.get("attempt_id")
        ):
            # Untyped rows predate the attempt contract.  Preserve them as
            # append-only history, but disclose evidence gaps instead of
            # fabricating identity or timing fields.
            if not (event.get("agent_id") or event.get("thread_id")):
                warnings.append(
                    f"line {line_no}: legacy dispatch event lacks agent_id or thread_id"
                )
            if not (event.get("spawned_at") or event.get("resumed_at")):
                warnings.append(
                    f"line {line_no}: legacy dispatch event lacks spawned_at or resumed_at"
                )
            if not event.get("dispatch_trigger"):
                warnings.append(f"line {line_no}: legacy dispatch event lacks dispatch_trigger")
            if normalize_terminal_status(
                event.get("status")
            ) in TERMINAL_SUCCESS_STATUSES and not event.get("completed_at"):
                warnings.append(
                    f"line {line_no}: legacy successful dispatch event lacks completed_at"
                )

        if (
            ledger_type == "dispatch"
            and event.get("event_type") in {"dispatch", "dispatch_attempt_closure"}
            and event.get("attempt_id")
        ):
            dispatch_id = str(event.get("dispatch_id") or "")
            attempt_id = str(event.get("attempt_id") or "")
            status = normalize_terminal_status(event.get("status"))
            if not event_id:
                if (dispatch_id, attempt_id) in corrected_attempts:
                    warnings.append(
                        f"line {line_no}: typed dispatch event_id is covered by append-only correction"
                    )
                else:
                    errors.append(f"line {line_no}: typed dispatch attempt requires event_id")
            if not dispatch_id or not attempt_id:
                errors.append(
                    f"line {line_no}: typed dispatch attempt requires dispatch_id and attempt_id"
                )
            if status in TERMINAL_ATTEMPT_STATUSES and not event.get("terminal_result"):
                if event_id in correction_index:
                    warnings.append(
                        f"line {line_no}: missing terminal_result is covered by dispatch correction "
                        f"{correction_index[event_id].get('event_id')}"
                    )
                else:
                    errors.append(
                        f"line {line_no}: terminal typed dispatch attempt requires terminal_result"
                    )
            typed_attempt_events.setdefault((dispatch_id, attempt_id), []).append(event)
        if not any(
            event.get(field)
            for field in (
                "created_at",
                "checked_at",
                "spawned_at",
                "completed_at",
                "timestamp",
                "observed_at",
            )
        ):
            warnings.append(f"line {line_no}: event has no timestamp field")
    if ledger_type == "dispatch":
        for (dispatch_id, attempt_id), events_for_attempt in sorted(typed_attempt_events.items()):
            statuses = {
                normalize_terminal_status(event.get("status")) for event in events_for_attempt
            }
            if not statuses & TERMINAL_ATTEMPT_STATUSES:
                errors.append(
                    f"dispatch {dispatch_id} attempt {attempt_id}: missing terminal closure"
                )
            if not any(
                event.get("agent_id") or event.get("thread_id") for event in events_for_attempt
            ):
                warnings.append(
                    f"dispatch {dispatch_id} attempt {attempt_id}: missing agent_id or thread_id"
                )
            if not any(
                event.get("spawned_at") or event.get("resumed_at") for event in events_for_attempt
            ):
                warnings.append(
                    f"dispatch {dispatch_id} attempt {attempt_id}: missing spawned_at or resumed_at"
                )
            if not any(event.get("dispatch_trigger") for event in events_for_attempt):
                warnings.append(
                    f"dispatch {dispatch_id} attempt {attempt_id}: missing dispatch_trigger"
                )
            for event in events_for_attempt:
                if normalize_terminal_status(
                    event.get("status")
                ) in TERMINAL_SUCCESS_STATUSES and not event.get("completed_at"):
                    line_no = int(event.get("_line_no") or 0)
                    errors.append(
                        f"line {line_no}: successful typed dispatch terminal event requires completed_at"
                    )
    return errors, warnings


def _print_event_help() -> None:
    print(
        "usage: meta-flow event <append|correction-plan|correction-apply|closure-plan|closure-apply|dispatch-not-required|inline-fallback|dispatch-check|check|list> [options]\n\n"
        "Commands:\n"
        "  append  Append one JSON event to an NDJSON ledger.\n"
        "  correction-plan  Build a zero-write DispatchCorrectionV1 batch plan.\n"
        "  correction-apply Apply an exact OID/preimage-bound correction batch.\n"
        "  closure-plan     Build a zero-write disposition-bound dispatch closure plan.\n"
        "  closure-apply    Apply an exact OID/preimage-bound dispatch closure batch.\n"
        "  dispatch-not-required  Append a structured dispatch_not_required event.\n"
        "  inline-fallback        Append a structured inline_fallback dispatch event.\n"
        "  dispatch-check  Validate typed dispatch event/attempt closure evidence.\n"
        "  check   Validate a known or generic NDJSON event ledger.\n"
        "  list    Print compact event lines from a ledger.\n\n"
        "Examples:\n"
        "  meta-flow event append --ledger process/state/CHECKPOINT-LEDGER.ndjson --event-file event.json\n"
        '  meta-flow event inline-fallback --dispatch-id ADE-CR045-INLINE-CP6 --canonical-role meta-dev --fallback-reason "implemented inline" --approved-by host-orchestrator --project-root .\n'
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
    if command in {"correction-plan", "correction-apply"}:
        from meta_flow.state import dispatch_correction

        parser = argparse.ArgumentParser(prog=f"meta-flow event {command}")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--source-event-id", action="append", required=True)
        parser.add_argument("--terminal-result", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--evidence-ref", action="append", required=True)
        parser.add_argument("--created-at")
        if command == "correction-apply":
            parser.add_argument("--expected-plan-digest", required=True)
            parser.add_argument("--expected-process-oid", required=True)
        parsed = parser.parse_args(args[1:])
        try:
            plan = dispatch_correction.plan_dispatch_corrections(
                parsed.project_root,
                source_event_ids=tuple(parsed.source_event_id),
                terminal_result=parsed.terminal_result,
                reason=parsed.reason,
                evidence_refs=tuple(parsed.evidence_ref),
                created_at=parsed.created_at,
            )
            payload = (
                plan.as_dict()
                if command == "correction-plan"
                else dispatch_correction.apply_dispatch_corrections(
                    parsed.project_root,
                    plan=plan,
                    expected_plan_digest=parsed.expected_plan_digest,
                    expected_process_oid=parsed.expected_process_oid,
                )
            )
        except (OSError, ValueError) as exc:
            payload = {"decision": "BLOCKED", "blockers": [str(exc)], "mutation_count": 0}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if payload.get("decision") in {"READY", "NO_CHANGE", "APPLIED"} else 1
    if command in {"closure-plan", "closure-apply"}:
        from meta_flow.state import dispatch_closure

        parser = argparse.ArgumentParser(prog=f"meta-flow event {command}")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--dispatch-id", action="append", required=True)
        parser.add_argument("--created-at")
        if command == "closure-apply":
            parser.add_argument("--expected-plan-digest", required=True)
            parser.add_argument("--expected-process-oid", required=True)
        parsed = parser.parse_args(args[1:])
        try:
            plan = dispatch_closure.plan_dispatch_closures(
                parsed.project_root,
                dispatch_ids=tuple(parsed.dispatch_id),
                created_at=parsed.created_at,
            )
            payload = (
                plan.as_dict()
                if command == "closure-plan"
                else dispatch_closure.apply_dispatch_closures(
                    parsed.project_root,
                    plan=plan,
                    expected_plan_digest=parsed.expected_plan_digest,
                    expected_process_oid=parsed.expected_process_oid,
                )
            )
        except (OSError, ValueError) as exc:
            payload = {"decision": "BLOCKED", "blockers": [str(exc)], "mutation_count": 0}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if payload.get("decision") in {"READY", "NO_CHANGE", "APPLIED"} else 1
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
        parser.add_argument(
            "--ledger", type=Path, default=Path("process/state/AGENT-DISPATCH-LEDGER.ndjson")
        )
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
            event_id = (
                event.get("event_id") or event.get("dispatch_id") or event.get("run_id") or "-"
            )
            event_type = event.get("event_type") or "-"
            status = event.get("status") or event.get("decision") or event.get("result") or "-"
            print(f"{event_id}\t{event_type}\t{status}")
        return 0
    raise SystemExit(f"未知 event 命令: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
