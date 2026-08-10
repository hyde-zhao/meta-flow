"""Execution Control 的 finding identity、occurrence 与失败路由组合器。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from meta_flow.execution_control.contract import (
    AdmissionPlanV1,
    ExecutionUnitV1,
    FailureRouteV1,
    FindingIdentityV1,
    canonical_digest,
)
from meta_flow.policies.failure_routing import (
    VALIDATION_LAYER_ORDER,
    classify_failure,
    route_slice_failure,
)
from meta_flow.semantics.attempt import ReworkPlan, plan_rework
from meta_flow.state.event_ledger import (
    FindingLedgerProjectionV1,
    FindingObservationEventV1,
    project_execution_control_ledger,
    project_finding_occurrence,
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _closed_mapping(
    payload: Mapping[str, Any], expected: frozenset[str], *, subject: str
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{subject} must be a mapping")
    actual = frozenset(payload)
    if actual != expected:
        missing = ",".join(sorted(expected - actual)) or "-"
        extra = ",".join(sorted(actual - expected)) or "-"
        raise ValueError(f"{subject} fields mismatch: missing={missing}; extra={extra}")
    return payload


def _safe_id(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"{field} must be one safe identifier")
    return value


def _safe_code(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_CODE_RE.fullmatch(value):
        raise ValueError(f"{field} must be one safe code")
    return value


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be one lowercase SHA-256 digest")
    return value


def _safe_ref(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or any(char in value for char in "\r\n\\"):
        raise ValueError(f"{field} must be one safe relative ref")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} must be one safe relative ref")
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class FrozenFailureResultItemV1:
    """冻结 required-check 中唯一、可用于派生 finding 的 canonical item。"""

    item_id: str
    check_group_id: str
    status: str
    reason_codes: tuple[str, ...]

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"item_id", "check_group_id", "status", "reason_codes"}
    )

    def __post_init__(self) -> None:
        _safe_id(self.item_id, field="item_id")
        _safe_id(self.check_group_id, field="check_group_id")
        _safe_code(self.status, field="status")
        if self.status not in {"PASS", "FAIL", "BLOCKED"}:
            raise ValueError("frozen result item status is not routable")
        if len(self.reason_codes) != 1:
            raise ValueError("frozen result item requires exactly one canonical reason code")
        _safe_code(self.reason_codes[0], field="reason_codes")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> FrozenFailureResultItemV1:
        value = _closed_mapping(payload, cls.FIELDS, subject=cls.__name__)
        reasons = value["reason_codes"]
        if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
            raise ValueError("reason_codes must be a list of strings")
        return cls(
            item_id=value["item_id"],
            check_group_id=value["check_group_id"],
            status=value["status"],
            reason_codes=tuple(reasons),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "check_group_id": self.check_group_id,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class FrozenFailureContractV1:
    """ExecutionUnit contract_ref 中绑定 required-check identity 的 closed profile。"""

    schema_version: int
    kind: str
    root_concept: str
    slice_id: str
    contract_revision: int
    required_check_ids: tuple[str, ...]
    payload_digest: str

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "kind",
            "root_concept",
            "slice_id",
            "contract_revision",
            "required_check_ids",
            "payload_digest",
        }
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.kind != "execution_failure_contract":
            raise ValueError("unsupported execution failure contract revision")
        _safe_id(self.root_concept, field="root_concept")
        _safe_id(self.slice_id, field="slice_id")
        if type(self.contract_revision) is not int or self.contract_revision < 1:
            raise ValueError("contract_revision must be a positive integer")
        checks = tuple(
            sorted({_safe_id(item, field="required_check_ids") for item in self.required_check_ids})
        )
        if not checks or len(checks) != len(self.required_check_ids):
            raise ValueError("required_check_ids must be non-empty and unique")
        object.__setattr__(self, "required_check_ids", checks)
        _sha256(self.payload_digest, field="payload_digest")
        if self.payload_digest != canonical_digest(self._payload_without_digest()):
            raise ValueError("execution failure contract payload digest mismatch")

    @classmethod
    def build(
        cls,
        *,
        root_concept: str,
        slice_id: str,
        contract_revision: int,
        required_check_ids: tuple[str, ...],
    ) -> FrozenFailureContractV1:
        seed = {
            "schema_version": 1,
            "kind": "execution_failure_contract",
            "root_concept": root_concept,
            "slice_id": slice_id,
            "contract_revision": contract_revision,
            "required_check_ids": list(required_check_ids),
        }
        return cls.from_mapping({**seed, "payload_digest": canonical_digest(seed)})

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> FrozenFailureContractV1:
        value = _closed_mapping(payload, cls.FIELDS, subject=cls.__name__)
        checks = value["required_check_ids"]
        if not isinstance(checks, list) or not all(isinstance(item, str) for item in checks):
            raise ValueError("required_check_ids must be a list of strings")
        return cls(
            schema_version=value["schema_version"],
            kind=value["kind"],
            root_concept=value["root_concept"],
            slice_id=value["slice_id"],
            contract_revision=value["contract_revision"],
            required_check_ids=tuple(checks),
            payload_digest=value["payload_digest"],
        )

    def _payload_without_digest(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "root_concept": self.root_concept,
            "slice_id": self.slice_id,
            "contract_revision": self.contract_revision,
            "required_check_ids": list(self.required_check_ids),
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self._payload_without_digest(), "payload_digest": self.payload_digest}


def load_frozen_failure_contract(path: Path) -> tuple[FrozenFailureContractV1, str]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"execution failure contract is unreadable: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("execution failure contract must be one JSON object")
    return FrozenFailureContractV1.from_mapping(payload), hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class FrozenFailureEvidenceV1:
    """由 canonical checker 冻结、由 lifecycle 仅按 ref 消费的 closed evidence。"""

    schema_version: int
    kind: str
    unit_id: str
    check_profile_digest: str
    required_check_ids: tuple[str, ...]
    contract_revision: int
    target_scope_digest: str
    check_result_digest: str
    result_items: tuple[FrozenFailureResultItemV1, ...]
    observed_at: str
    payload_digest: str

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "kind",
            "unit_id",
            "check_profile_digest",
            "required_check_ids",
            "contract_revision",
            "target_scope_digest",
            "check_result_digest",
            "result_items",
            "observed_at",
            "payload_digest",
        }
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.kind != "frozen_failure_evidence":
            raise ValueError("unsupported frozen failure evidence revision")
        _safe_id(self.unit_id, field="unit_id")
        _sha256(self.check_profile_digest, field="check_profile_digest")
        _sha256(self.target_scope_digest, field="target_scope_digest")
        _sha256(self.check_result_digest, field="check_result_digest")
        _sha256(self.payload_digest, field="payload_digest")
        if type(self.contract_revision) is not int or self.contract_revision < 1:
            raise ValueError("contract_revision must be a positive integer")
        if not isinstance(self.observed_at, str) or not self.observed_at.strip():
            raise ValueError("observed_at is required")
        normalized_checks = tuple(sorted({_safe_id(item, field="required_check_ids") for item in self.required_check_ids}))
        if len(normalized_checks) != len(self.required_check_ids) or not normalized_checks:
            raise ValueError("required_check_ids must be non-empty and unique")
        object.__setattr__(self, "required_check_ids", normalized_checks)
        if len(self.result_items) != 1:
            raise ValueError("frozen failure evidence requires exactly one result item")
        item = self.result_items[0]
        if item.check_group_id not in normalized_checks:
            raise ValueError("result check group is absent from the frozen required profile")
        if self.check_result_digest != canonical_digest(item):
            raise ValueError("check_result_digest does not match the canonical result item")
        if self.payload_digest != canonical_digest(self._payload_without_digest()):
            raise ValueError("frozen failure evidence payload digest mismatch")

    @classmethod
    def build(
        cls,
        *,
        unit_id: str,
        check_profile_digest: str,
        required_check_ids: tuple[str, ...],
        contract_revision: int,
        target_scope_digest: str,
        result_item: FrozenFailureResultItemV1,
        observed_at: str,
    ) -> FrozenFailureEvidenceV1:
        seed = {
            "schema_version": 1,
            "kind": "frozen_failure_evidence",
            "unit_id": unit_id,
            "check_profile_digest": check_profile_digest,
            "required_check_ids": list(required_check_ids),
            "contract_revision": contract_revision,
            "target_scope_digest": target_scope_digest,
            "check_result_digest": canonical_digest(result_item),
            "result_items": [result_item.as_dict()],
            "observed_at": observed_at,
        }
        return cls.from_mapping({**seed, "payload_digest": canonical_digest(seed)})

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> FrozenFailureEvidenceV1:
        value = _closed_mapping(payload, cls.FIELDS, subject=cls.__name__)
        checks = value["required_check_ids"]
        items = value["result_items"]
        if not isinstance(checks, list) or not all(isinstance(item, str) for item in checks):
            raise ValueError("required_check_ids must be a list of strings")
        if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
            raise ValueError("result_items must be a list of mappings")
        return cls(
            schema_version=value["schema_version"],
            kind=value["kind"],
            unit_id=value["unit_id"],
            check_profile_digest=value["check_profile_digest"],
            required_check_ids=tuple(checks),
            contract_revision=value["contract_revision"],
            target_scope_digest=value["target_scope_digest"],
            check_result_digest=value["check_result_digest"],
            result_items=tuple(FrozenFailureResultItemV1.from_mapping(item) for item in items),
            observed_at=value["observed_at"],
            payload_digest=value["payload_digest"],
        )

    def _payload_without_digest(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "unit_id": self.unit_id,
            "check_profile_digest": self.check_profile_digest,
            "required_check_ids": list(self.required_check_ids),
            "contract_revision": self.contract_revision,
            "target_scope_digest": self.target_scope_digest,
            "check_result_digest": self.check_result_digest,
            "result_items": [item.as_dict() for item in self.result_items],
            "observed_at": self.observed_at,
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self._payload_without_digest(), "payload_digest": self.payload_digest}


def load_frozen_failure_evidence(path: Path) -> FrozenFailureEvidenceV1:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"frozen failure evidence is unreadable: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("frozen failure evidence must be one JSON object")
    return FrozenFailureEvidenceV1.from_mapping(payload)


@dataclass(frozen=True, slots=True)
class FailureAttemptV1:
    previous_work_id: str
    next_work_id: str
    previous_thread_id: str
    next_thread_id: str
    previous_attempt_id: str
    next_attempt_id: str
    previous_dispatch_id: str
    next_dispatch_id: str
    source_changed: bool = False
    command_changed: bool = False
    worktree_policy: str = "root-branch-only"

    def plan(self, *, failed_layer: str) -> ReworkPlan:
        return plan_rework(
            previous_work_id=self.previous_work_id,
            next_work_id=self.next_work_id,
            previous_thread_id=self.previous_thread_id,
            next_thread_id=self.next_thread_id,
            previous_attempt_id=self.previous_attempt_id,
            next_attempt_id=self.next_attempt_id,
            previous_dispatch_id=self.previous_dispatch_id,
            next_dispatch_id=self.next_dispatch_id,
            failed_layer=failed_layer,
            source_changed=self.source_changed,
            command_changed=self.command_changed,
            worktree_policy=self.worktree_policy,
        )


def _attempt_plan_payload(plan: ReworkPlan) -> dict[str, Any]:
    return {
        "decision": plan.decision,
        "reuse_work": plan.reuse_work,
        "reuse_thread": plan.reuse_thread,
        "new_attempt": plan.new_attempt,
        "new_dispatch": plan.new_dispatch,
        "create_worktree": plan.create_worktree,
        "restart_layer": plan.restart_layer,
        "layers": list(plan.layers),
        "reason_codes": list(plan.reason_codes),
    }


@dataclass(frozen=True, slots=True)
class FindingObservationPlanV1:
    decision: str
    conflicts: tuple[str, ...]
    evidence_ref: str
    identity: FindingIdentityV1 | None
    identity_digest: str
    route: FailureRouteV1 | None
    event: FindingObservationEventV1 | None
    append_required: bool
    expected_ledger_preimage_digest: str
    planned_domain_mutation_count: int = 0

    @property
    def blocked(self) -> bool:
        return self.decision == "BLOCKED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "conflicts": list(self.conflicts),
            "evidence_ref": self.evidence_ref,
            "identity": self.identity.as_dict() if self.identity else None,
            "identity_digest": self.identity_digest,
            "route": self.route.as_dict() if self.route else None,
            "event": self.event.as_dict() if self.event else None,
            "append_required": self.append_required,
            "expected_ledger_preimage_digest": self.expected_ledger_preimage_digest,
            "planned_domain_mutation_count": self.planned_domain_mutation_count,
        }


def blocked_observation_plan(
    *conflicts: str,
    evidence_ref: str = "",
    expected_ledger_preimage_digest: str = "",
) -> FindingObservationPlanV1:
    return FindingObservationPlanV1(
        decision="BLOCKED",
        conflicts=tuple(sorted(set(conflicts))) or ("FINDING_OBSERVATION_INVALID",),
        evidence_ref=evidence_ref,
        identity=None,
        identity_digest="",
        route=None,
        event=None,
        append_required=False,
        expected_ledger_preimage_digest=expected_ledger_preimage_digest,
    )


def _action_for_route(
    *, item_status: str, slice_decision: str, occurrence: int
) -> str:
    if occurrence >= 3:
        return "REQUIRE_DESIGN_CLARIFICATION"
    if item_status == "PASS":
        return "COMPLETE_CURRENT_LAYER_ONLY"
    if item_status == "BLOCKED":
        return "WAIT_IN_CONTAINER"
    return {
        "RETRY_LAYER": "RETRY_CURRENT_LAYER",
        "REWORK_CURRENT_SLICE": "REWORK_CURRENT_SLICE",
        "RECOVERY_REQUIRED": "RECOVER_PARTIAL_AND_STOP",
        "BLOCKED": "CLASSIFY_BEFORE_CONTINUE",
    }.get(slice_decision, "CLASSIFY_BEFORE_CONTINUE")


def plan_finding_observation(
    unit: ExecutionUnitV1,
    contract: FrozenFailureContractV1,
    evidence: FrozenFailureEvidenceV1,
    *,
    evidence_ref: str,
    facts: Mapping[str, Any],
    failed_layer: str,
    attempt: FailureAttemptV1,
    ledger_events: tuple[Mapping[str, Any], ...] = (),
    ledger_projection: FindingLedgerProjectionV1 | None = None,
    ledger_preimage_digest: str,
) -> FindingObservationPlanV1:
    """组合 canonical owners；本函数不读取文件、不写 ledger。"""

    ref = _safe_ref(evidence_ref, field="evidence_ref")
    _sha256(ledger_preimage_digest, field="ledger_preimage_digest")
    if failed_layer not in VALIDATION_LAYER_ORDER:
        return blocked_observation_plan(
            "FAILURE_ROUTE_INPUT_INVALID",
            evidence_ref=ref,
            expected_ledger_preimage_digest=ledger_preimage_digest,
        )
    if (
        contract.root_concept != unit.root_concept
        or contract.slice_id != unit.slice_id
        or contract.contract_revision != unit.revision
        or evidence.unit_id != unit.unit_id
        or evidence.contract_revision != unit.revision
        or evidence.check_profile_digest != unit.contract_digest
        or evidence.required_check_ids != contract.required_check_ids
    ):
        return blocked_observation_plan(
            "FROZEN_CONTRACT_OR_EVIDENCE_BINDING_MISMATCH",
            evidence_ref=ref,
            expected_ledger_preimage_digest=ledger_preimage_digest,
        )
    item = evidence.result_items[0]
    identity = FindingIdentityV1(
        root_concept=unit.root_concept,
        slice_id=unit.slice_id,
        check_group_id=item.check_group_id,
        canonical_finding_code=item.reason_codes[0],
        contract_revision=evidence.contract_revision,
        target_scope_digest=evidence.target_scope_digest,
    )
    identity_digest = canonical_digest(identity)
    projected_ledger = ledger_projection or project_execution_control_ledger(ledger_events)
    projection = project_finding_occurrence(
        projected_ledger, identity_digest=identity_digest
    )
    if projection.decision != "PASS":
        return blocked_observation_plan(
            *projection.finding_codes,
            evidence_ref=ref,
            expected_ledger_preimage_digest=ledger_preimage_digest,
        )
    rework = attempt.plan(failed_layer=failed_layer)
    attempt_digest = canonical_digest(_attempt_plan_payload(rework))

    append_required = item.status != "PASS"
    observation_key_digest = ""
    replay = False
    if append_required:
        observation_key_digest = canonical_digest(
            {
                "unit_id": unit.unit_id,
                "attempt_id": attempt.next_attempt_id,
                "check_result_digest": evidence.check_result_digest,
                "identity_digest": identity_digest,
            }
        )
        replay = observation_key_digest in projected_ledger.by_observation_key
    next_occurrence = (
        projection.occurrence
        if replay
        else projection.occurrence + 1
        if append_required
        else max(projection.occurrence, 1)
    )
    classification = classify_failure(facts)
    if item.status == "PASS":
        if classification.failure_class != "UNKNOWN":
            return blocked_observation_plan(
                "FROZEN_PASS_FACTS_CONFLICT",
                evidence_ref=ref,
                expected_ledger_preimage_digest=ledger_preimage_digest,
            )
        classification_payload = {"decision": "PASS", "reason_codes": list(item.reason_codes)}
        slice_payload = {
            "decision": "PASS",
            "failed_layer": failed_layer,
            "invalidated_layers": [],
        }
        slice_decision = "PASS"
    else:
        if item.reason_codes[0] not in classification.reason_codes:
            return blocked_observation_plan(
                "FROZEN_REASON_CLASSIFICATION_MISMATCH",
                evidence_ref=ref,
                expected_ledger_preimage_digest=ledger_preimage_digest,
            )
        try:
            slice_route = route_slice_failure(
                failure_class=classification.failure_class,
                failed_layer=failed_layer,
                current_slice_id=unit.slice_id,
            )
        except ValueError:
            return blocked_observation_plan(
                "FAILURE_ROUTE_INPUT_INVALID",
                evidence_ref=ref,
                expected_ledger_preimage_digest=ledger_preimage_digest,
            )
        classification_payload = classification.as_dict()
        slice_payload = slice_route.as_dict()
        slice_decision = slice_route.decision

    action = _action_for_route(
        item_status=item.status,
        slice_decision=slice_decision,
        occurrence=next_occurrence,
    )
    if action in {"RETRY_CURRENT_LAYER", "REWORK_CURRENT_SLICE"} and rework.decision != "READY":
        return blocked_observation_plan(
            *rework.reason_codes,
            evidence_ref=ref,
            expected_ledger_preimage_digest=ledger_preimage_digest,
        )
    route = FailureRouteV1(
        classification_digest=canonical_digest(classification_payload),
        slice_route_digest=canonical_digest(slice_payload),
        attempt_plan_digest=attempt_digest,
        execution_action=action,
        occurrence=next_occurrence,
    )
    event: FindingObservationEventV1 | None = None
    if append_required:
        event = FindingObservationEventV1.build(
            event_id=f"EC-OBS-{observation_key_digest[:32]}",
            unit_id=unit.unit_id,
            attempt_id=attempt.next_attempt_id,
            evidence_ref=ref,
            check_result_digest=evidence.check_result_digest,
            observation_key_digest=observation_key_digest,
            identity_digest=identity_digest,
            contract_revision=evidence.contract_revision,
            classification_digest=route.classification_digest,
            slice_route_digest=route.slice_route_digest,
            attempt_plan_digest=route.attempt_plan_digest,
            observed_at=evidence.observed_at,
        )
    return FindingObservationPlanV1(
        decision="READY",
        conflicts=(),
        evidence_ref=ref,
        identity=identity,
        identity_digest=identity_digest,
        route=route,
        event=event,
        append_required=append_required,
        expected_ledger_preimage_digest=ledger_preimage_digest,
    )


def coordination_plan_for_observation(plan: FindingObservationPlanV1) -> AdmissionPlanV1:
    """把 S3 plan 适配到 S2 的同一个 project lock；不创建第二种 lock。"""

    if plan.blocked or plan.identity is None:
        raise ValueError("blocked finding plan cannot acquire the project lock")
    return AdmissionPlanV1(
        decision="READY",
        facts_digest=canonical_digest(
            {
                "identity_digest": plan.identity_digest,
                "ledger_preimage_digest": plan.expected_ledger_preimage_digest,
            }
        ),
        scope_digest=plan.identity.target_scope_digest,
        candidate_digest=canonical_digest(plan),
        conflicts=(),
        planned_domain_mutation_count=0,
        coordination_required=True,
    )


@dataclass(frozen=True, slots=True)
class FailureObservationApplyResultV1:
    decision: str
    conflicts: tuple[str, ...]
    route: FailureRouteV1 | None
    occurrence: int
    domain_mutation_count: int
    coordination_mutation_count: int
    durable_lock_count: int
    idempotent: bool


__all__ = [
    "FailureAttemptV1",
    "FailureObservationApplyResultV1",
    "FindingObservationPlanV1",
    "FrozenFailureContractV1",
    "FrozenFailureEvidenceV1",
    "FrozenFailureResultItemV1",
    "blocked_observation_plan",
    "coordination_plan_for_observation",
    "load_frozen_failure_evidence",
    "load_frozen_failure_contract",
    "plan_finding_observation",
]
