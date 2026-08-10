"""Execution Control 的 closed typed contract 与稳定摘要。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, ClassVar

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

EXECUTION_ACTIONS = frozenset(
    {
        "RETRY_CURRENT_LAYER",
        "REWORK_CURRENT_SLICE",
        "REQUIRE_DESIGN_CLARIFICATION",
        "WAIT_IN_CONTAINER",
        "CLASSIFY_BEFORE_CONTINUE",
        "RECOVER_PARTIAL_AND_STOP",
        "COMPLETE_CURRENT_LAYER_ONLY",
    }
)
CONTAINER_ROLES = frozenset({"primary", "auxiliary", "repair"})
ACTIVATION_MODES = frozenset({"shadow", "enforce-new", "canonical"})
ACTIVATION_DECISIONS = frozenset({"READY", "BLOCKED"})
ADMISSION_DECISIONS = frozenset({"READY", "BLOCKED"})
INVALIDATABLE_LAYERS = frozenset({"targeted", "compatibility", "full", "closure"})
FINGERPRINT_KEYS = frozenset(
    {
        "facts",
        "scope",
        "authorization",
        "contract",
        "consumer",
        "ownership",
        "slice",
        "test",
        "source",
        "profile",
    }
)


def _closed_mapping(
    payload: Mapping[str, Any],
    expected: frozenset[str],
    *,
    subject: str,
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


def _positive_int(value: Any, *, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be one lowercase SHA-256 digest")
    return value


def _oid(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _OID_RE.fullmatch(value):
        raise ValueError(f"{field} must be one lowercase Git OID")
    return value


def _safe_ref(value: Any, *, field: str, allow_empty: bool = False) -> str:
    if value == "" and allow_empty:
        return ""
    if not isinstance(value, str) or not value or any(char in value for char in "\r\n\\"):
        raise ValueError(f"{field} must be one safe relative ref")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} must be one safe relative ref")
    return path.as_posix()


def _string_list(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return tuple(value)


def _normalize_codes(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{field} must be a tuple")
    normalized = tuple(sorted({_safe_code(value, field=field) for value in values}))
    if len(normalized) != len(values):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _normalize_layers(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError("invalidated_layers must be a tuple")
    if any(value not in INVALIDATABLE_LAYERS for value in values):
        raise ValueError("invalidated_layers contains an unsupported layer")
    normalized = tuple(sorted(set(values)))
    if len(normalized) != len(values):
        raise ValueError("invalidated_layers must not contain duplicates")
    return normalized


def _normalize_refs(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{field} must be a tuple")
    normalized = tuple(sorted({_safe_ref(value, field=field) for value in values}))
    if len(normalized) != len(values):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _normalize_fingerprints(
    values: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    if not isinstance(values, tuple) or not all(
        isinstance(item, tuple) and len(item) == 2 for item in values
    ):
        raise ValueError("fingerprints must be one tuple of key/digest pairs")
    mapping = dict(values)
    if len(mapping) != len(values) or frozenset(mapping) != FINGERPRINT_KEYS:
        raise ValueError("fingerprints must contain the exact canonical fingerprint keys")
    return tuple(sorted((key, _sha256(value, field=f"fingerprints.{key}")) for key, value in mapping.items()))


def _fingerprints_from_mapping(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise ValueError("fingerprints must be a mapping")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise ValueError("fingerprints must map strings to strings")
    return tuple((key, item) for key, item in value.items())


def _canonical_value(value: Any) -> Any:
    if hasattr(value, "as_dict") and callable(value.as_dict):
        return _canonical_value(value.as_dict())
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) and key for key in value):
            raise ValueError("canonical mappings require non-empty string keys")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise ValueError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_digest(value: Any) -> str:
    """对 closed semantic payload 计算稳定 lowercase SHA-256。"""

    rendered = json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionUnitV1:
    unit_id: str
    root_concept: str
    slice_id: str
    container_role: str
    revision: int
    supersedes_unit_id: str
    contract_ref: str
    contract_digest: str

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "unit_id",
            "root_concept",
            "slice_id",
            "container_role",
            "revision",
            "supersedes_unit_id",
            "contract_ref",
            "contract_digest",
        }
    )

    def __post_init__(self) -> None:
        _safe_id(self.unit_id, field="unit_id")
        _safe_id(self.root_concept, field="root_concept")
        _safe_id(self.slice_id, field="slice_id")
        if self.container_role not in CONTAINER_ROLES:
            raise ValueError("container_role is unsupported")
        _positive_int(self.revision, field="revision")
        _safe_ref(self.contract_ref, field="contract_ref")
        _sha256(self.contract_digest, field="contract_digest")
        if self.revision == 1 and self.supersedes_unit_id:
            raise ValueError("revision 1 must not declare supersedes_unit_id")
        if self.revision > 1:
            _safe_id(self.supersedes_unit_id, field="supersedes_unit_id")

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        work_id: str | None = None,
    ) -> ExecutionUnitV1:
        value = _closed_mapping(payload, cls.FIELDS, subject=cls.__name__)
        unit = cls(**{field: value[field] for field in cls.FIELDS})
        if work_id is not None:
            unit.validate_for_work(work_id)
        return unit

    def validate_for_work(self, work_id: str) -> None:
        if self.unit_id != _safe_id(work_id, field="work_id"):
            raise ValueError("unit_id must equal work_id")

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "root_concept": self.root_concept,
            "slice_id": self.slice_id,
            "container_role": self.container_role,
            "revision": self.revision,
            "supersedes_unit_id": self.supersedes_unit_id,
            "contract_ref": self.contract_ref,
            "contract_digest": self.contract_digest,
        }


@dataclass(frozen=True, slots=True)
class ContainerBudgetV1:
    primary_max: int
    auxiliary_max: int
    repair_max: int
    concurrent_write_max: int

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"primary_max", "auxiliary_max", "repair_max", "concurrent_write_max"}
    )

    def __post_init__(self) -> None:
        for field in self.FIELDS:
            _non_negative_int(getattr(self, field), field=field)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ContainerBudgetV1:
        value = _closed_mapping(payload, cls.FIELDS, subject=cls.__name__)
        return cls(**{field: value[field] for field in cls.FIELDS})

    @classmethod
    def policy_v1(cls) -> ContainerBudgetV1:
        return cls(1, 0, 0, 1)

    def as_dict(self) -> dict[str, int]:
        return {
            "primary_max": self.primary_max,
            "auxiliary_max": self.auxiliary_max,
            "repair_max": self.repair_max,
            "concurrent_write_max": self.concurrent_write_max,
        }


@dataclass(frozen=True, slots=True)
class FindingIdentityV1:
    root_concept: str
    slice_id: str
    check_group_id: str
    canonical_finding_code: str
    contract_revision: int
    target_scope_digest: str

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "root_concept",
            "slice_id",
            "check_group_id",
            "canonical_finding_code",
            "contract_revision",
            "target_scope_digest",
        }
    )

    def __post_init__(self) -> None:
        _safe_id(self.root_concept, field="root_concept")
        _safe_id(self.slice_id, field="slice_id")
        _safe_id(self.check_group_id, field="check_group_id")
        _safe_code(self.canonical_finding_code, field="canonical_finding_code")
        _positive_int(self.contract_revision, field="contract_revision")
        _sha256(self.target_scope_digest, field="target_scope_digest")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> FindingIdentityV1:
        """只解析已派生的 canonical payload；生命周期/CLI 不暴露本入口。"""

        value = _closed_mapping(payload, cls.FIELDS, subject=cls.__name__)
        return cls(**{field: value[field] for field in cls.FIELDS})

    def as_dict(self) -> dict[str, Any]:
        return {
            "root_concept": self.root_concept,
            "slice_id": self.slice_id,
            "check_group_id": self.check_group_id,
            "canonical_finding_code": self.canonical_finding_code,
            "contract_revision": self.contract_revision,
            "target_scope_digest": self.target_scope_digest,
        }


@dataclass(frozen=True, slots=True)
class FailureRouteV1:
    classification_digest: str
    slice_route_digest: str
    attempt_plan_digest: str
    execution_action: str
    occurrence: int

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "classification_digest",
            "slice_route_digest",
            "attempt_plan_digest",
            "execution_action",
            "occurrence",
        }
    )

    def __post_init__(self) -> None:
        _sha256(self.classification_digest, field="classification_digest")
        _sha256(self.slice_route_digest, field="slice_route_digest")
        _sha256(self.attempt_plan_digest, field="attempt_plan_digest")
        if self.execution_action not in EXECUTION_ACTIONS:
            raise ValueError("execution_action is unsupported")
        _positive_int(self.occurrence, field="occurrence")
        if self.occurrence >= 3 and self.execution_action != "REQUIRE_DESIGN_CLARIFICATION":
            raise ValueError("third occurrence must require design clarification")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> FailureRouteV1:
        value = _closed_mapping(payload, cls.FIELDS, subject=cls.__name__)
        return cls(**{field: value[field] for field in cls.FIELDS})

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification_digest": self.classification_digest,
            "slice_route_digest": self.slice_route_digest,
            "attempt_plan_digest": self.attempt_plan_digest,
            "execution_action": self.execution_action,
            "occurrence": self.occurrence,
        }


@dataclass(frozen=True, slots=True)
class ClosureAuditV1:
    audit_scope: str
    cohort_revision: int
    dangling_container_count: int
    dangling_dispatch_count: int
    dangling_result_count: int
    dangling_evidence_count: int
    dangling_projection_count: int
    dangling_receipt_count: int
    grandfathered_legacy_count: int
    grandfathered_legacy_refs: tuple[str, ...]
    fingerprints: tuple[tuple[str, str], ...]

    COUNTER_FIELDS: ClassVar[tuple[str, ...]] = (
        "dangling_container_count",
        "dangling_dispatch_count",
        "dangling_result_count",
        "dangling_evidence_count",
        "dangling_projection_count",
        "dangling_receipt_count",
    )
    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "audit_scope",
            "cohort_revision",
            *COUNTER_FIELDS,
            "grandfathered_legacy_count",
            "grandfathered_legacy_refs",
            "fingerprints",
        }
    )

    def __post_init__(self) -> None:
        _safe_id(self.audit_scope, field="audit_scope")
        _positive_int(self.cohort_revision, field="cohort_revision")
        for field in (*self.COUNTER_FIELDS, "grandfathered_legacy_count"):
            _non_negative_int(getattr(self, field), field=field)
        refs = _normalize_refs(self.grandfathered_legacy_refs, field="grandfathered_legacy_refs")
        if self.grandfathered_legacy_count != len(refs):
            raise ValueError("grandfathered_legacy_count must match grandfathered_legacy_refs")
        object.__setattr__(self, "grandfathered_legacy_refs", refs)
        object.__setattr__(self, "fingerprints", _normalize_fingerprints(self.fingerprints))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ClosureAuditV1:
        value = _closed_mapping(payload, cls.FIELDS, subject=cls.__name__)
        args = {field: value[field] for field in cls.FIELDS}
        args["grandfathered_legacy_refs"] = _string_list(
            value["grandfathered_legacy_refs"],
            field="grandfathered_legacy_refs",
        )
        args["fingerprints"] = _fingerprints_from_mapping(value["fingerprints"])
        return cls(**args)

    @property
    def dangling_count(self) -> int:
        return sum(getattr(self, field) for field in self.COUNTER_FIELDS)

    @property
    def cohort_pass(self) -> bool:
        return self.dangling_count == 0

    @property
    def strict_project_pass(self) -> bool:
        return self.cohort_pass and self.grandfathered_legacy_count == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "audit_scope": self.audit_scope,
            "cohort_revision": self.cohort_revision,
            **{field: getattr(self, field) for field in self.COUNTER_FIELDS},
            "grandfathered_legacy_count": self.grandfathered_legacy_count,
            "grandfathered_legacy_refs": list(self.grandfathered_legacy_refs),
            "fingerprints": dict(self.fingerprints),
        }


@dataclass(frozen=True, slots=True)
class AdmissionFactsV1:
    release_oid: str
    process_oid: str
    dirty_path_digest: str
    scope_digest: str
    authorization_digest: str
    profile_digest: str
    inventory_digest: str
    target_preimage_digest: str
    project_active_owner_digest: str

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "release_oid",
            "process_oid",
            "dirty_path_digest",
            "scope_digest",
            "authorization_digest",
            "profile_digest",
            "inventory_digest",
            "target_preimage_digest",
            "project_active_owner_digest",
        }
    )

    def __post_init__(self) -> None:
        _oid(self.release_oid, field="release_oid")
        _oid(self.process_oid, field="process_oid")
        for field in self.FIELDS - {"release_oid", "process_oid"}:
            _sha256(getattr(self, field), field=field)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> AdmissionFactsV1:
        value = _closed_mapping(payload, cls.FIELDS, subject=cls.__name__)
        return cls(**{field: value[field] for field in cls.FIELDS})

    def as_dict(self) -> dict[str, str]:
        return {field: getattr(self, field) for field in sorted(self.FIELDS)}


@dataclass(frozen=True, slots=True)
class AdmissionPlanV1:
    decision: str
    facts_digest: str
    scope_digest: str
    candidate_digest: str
    conflicts: tuple[str, ...]
    planned_domain_mutation_count: int
    coordination_required: bool

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "decision",
            "facts_digest",
            "scope_digest",
            "candidate_digest",
            "conflicts",
            "planned_domain_mutation_count",
            "coordination_required",
        }
    )

    def __post_init__(self) -> None:
        if self.decision not in ADMISSION_DECISIONS:
            raise ValueError("admission decision is unsupported")
        for field in ("facts_digest", "scope_digest", "candidate_digest"):
            _sha256(getattr(self, field), field=field)
        conflicts = _normalize_codes(self.conflicts, field="conflicts")
        object.__setattr__(self, "conflicts", conflicts)
        if self.planned_domain_mutation_count != 0:
            raise ValueError("an admission plan must have zero planned domain mutations")
        if type(self.coordination_required) is not bool:
            raise ValueError("coordination_required must be a boolean")
        if self.decision == "READY" and conflicts:
            raise ValueError("READY admission must not contain conflicts")
        if self.decision == "BLOCKED" and not conflicts:
            raise ValueError("BLOCKED admission requires conflicts")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> AdmissionPlanV1:
        value = _closed_mapping(payload, cls.FIELDS, subject=cls.__name__)
        args = {field: value[field] for field in cls.FIELDS}
        args["conflicts"] = _string_list(value["conflicts"], field="conflicts")
        return cls(**args)

    @property
    def blocked(self) -> bool:
        return self.decision == "BLOCKED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "facts_digest": self.facts_digest,
            "scope_digest": self.scope_digest,
            "candidate_digest": self.candidate_digest,
            "conflicts": list(self.conflicts),
            "planned_domain_mutation_count": self.planned_domain_mutation_count,
            "coordination_required": self.coordination_required,
        }


@dataclass(frozen=True, slots=True)
class ActivationDecisionV1:
    policy_revision: int
    mode: str
    cohort_revision: int
    decision: str
    enforced: bool
    grandfathered: bool
    reason_codes: tuple[str, ...]
    invalidated_layers: tuple[str, ...]

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "policy_revision",
            "mode",
            "cohort_revision",
            "decision",
            "enforced",
            "grandfathered",
            "reason_codes",
            "invalidated_layers",
        }
    )

    def __post_init__(self) -> None:
        _positive_int(self.policy_revision, field="policy_revision")
        _positive_int(self.cohort_revision, field="cohort_revision")
        if self.mode not in ACTIVATION_MODES:
            raise ValueError("activation mode is unsupported")
        if self.decision not in ACTIVATION_DECISIONS:
            raise ValueError("activation decision is unsupported")
        if type(self.enforced) is not bool or type(self.grandfathered) is not bool:
            raise ValueError("enforced and grandfathered must be booleans")
        reasons = _normalize_codes(self.reason_codes, field="reason_codes")
        layers = _normalize_layers(self.invalidated_layers)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "invalidated_layers", layers)
        if self.decision == "BLOCKED" and not reasons:
            raise ValueError("BLOCKED activation requires reason_codes")
        if self.mode == "canonical" and (
            self.decision != "READY"
            or not self.enforced
            or self.grandfathered
            or layers
        ):
            raise ValueError("canonical activation requires current enforced evidence")
        if self.mode == "shadow" and self.enforced:
            raise ValueError("shadow activation must not be enforced")
        if self.mode == "enforce-new" and not self.enforced:
            raise ValueError("enforce-new activation must be enforced")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ActivationDecisionV1:
        value = _closed_mapping(payload, cls.FIELDS, subject=cls.__name__)
        args = {field: value[field] for field in cls.FIELDS}
        args["reason_codes"] = _string_list(value["reason_codes"], field="reason_codes")
        args["invalidated_layers"] = _string_list(
            value["invalidated_layers"],
            field="invalidated_layers",
        )
        return cls(**args)

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_revision": self.policy_revision,
            "mode": self.mode,
            "cohort_revision": self.cohort_revision,
            "decision": self.decision,
            "enforced": self.enforced,
            "grandfathered": self.grandfathered,
            "reason_codes": list(self.reason_codes),
            "invalidated_layers": list(self.invalidated_layers),
        }
