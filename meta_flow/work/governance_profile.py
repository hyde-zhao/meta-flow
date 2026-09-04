"""CR/Work 治理保障等级及 G3 用户选择合同。

这里的 ``GovernanceRiskProfile`` 与 release publication 的 operation risk grade
是两个不同命名空间。前者决定治理设计深度，后者只决定一次发布操作的授权等级。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

GOVERNANCE_PROFILE_SCHEMA_VERSION = 2
GOVERNANCE_RISK_PROFILES = frozenset({"G0", "G1", "G2", "G3"})
HIGH_ASSURANCE_PROFILES = frozenset({"G2", "G3"})
FULL_DESIGN_PROFILES = frozenset({"G3"})

_CR_ID_RE = re.compile(r"^CR-[0-9]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SELECTION_REASONS = frozenset(
    {"explicit-g3", "full-lld-requested", "legacy-g2-flow"}
)


def _canonical_digest(payload: object) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(rendered.encode("utf-8")).hexdigest()


def _parse_time(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be one RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def effective_governance_profile(risk_profile: str, schema_version: int) -> str:
    """解释持久化等级，同时保持旧 V1 G2 的完整设计语义。"""

    if type(schema_version) is not int or schema_version not in {1, 2}:
        raise ValueError("risk_profile_schema_version must be 1 or 2")
    if risk_profile not in GOVERNANCE_RISK_PROFILES:
        raise ValueError("governance risk profile must be G0, G1, G2, or G3")
    if schema_version == 1:
        if risk_profile == "G3":
            raise ValueError("V1 governance profile does not support G3")
        return "G3" if risk_profile == "G2" else risk_profile
    return risk_profile


def is_high_assurance(risk_profile: str, schema_version: int) -> bool:
    return effective_governance_profile(risk_profile, schema_version) in HIGH_ASSURANCE_PROFILES


def requires_full_design(risk_profile: str, schema_version: int) -> bool:
    return effective_governance_profile(risk_profile, schema_version) in FULL_DESIGN_PROFILES


@dataclass(frozen=True, slots=True)
class G3SelectionRecordV1:
    """用户显式选择完整 LLD 的闭合、可绑定记录。

    第一版仅支持 CR 级选择：任一 Story 要求完整 LLD 时，整个 CR 升为 G3。
    """

    schema_version: int
    kind: str
    cr_id: str
    requested_profile: str
    selection_source: str
    selection_reason: str
    authorization_ref: str
    decided_at: str

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.kind != "G3SelectionRecordV1":
            raise ValueError("G3_SELECTION_SCHEMA_INVALID")
        if not _CR_ID_RE.fullmatch(self.cr_id):
            raise ValueError("G3_SELECTION_CR_ID_INVALID")
        if self.requested_profile != "G3":
            raise ValueError("G3_SELECTION_PROFILE_INVALID")
        if self.selection_source != "user-explicit":
            raise ValueError("G3_SELECTION_SOURCE_INVALID")
        if self.selection_reason not in _SELECTION_REASONS:
            raise ValueError("G3_SELECTION_REASON_INVALID")
        if not isinstance(self.authorization_ref, str) or len(self.authorization_ref) < 8:
            raise ValueError("G3_SELECTION_AUTHORIZATION_REF_INVALID")
        _parse_time(self.decided_at, field="decided_at")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> G3SelectionRecordV1:
        expected = {
            "schema_version",
            "kind",
            "cr_id",
            "requested_profile",
            "selection_source",
            "selection_reason",
            "authorization_ref",
            "decided_at",
        }
        if set(payload) != expected:
            raise ValueError("G3_SELECTION_FIELDS_INVALID")
        return cls(
            schema_version=payload["schema_version"],
            kind=str(payload["kind"]),
            cr_id=str(payload["cr_id"]),
            requested_profile=str(payload["requested_profile"]),
            selection_source=str(payload["selection_source"]),
            selection_reason=str(payload["selection_reason"]),
            authorization_ref=str(payload["authorization_ref"]),
            decided_at=str(payload["decided_at"]),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "cr_id": self.cr_id,
            "requested_profile": self.requested_profile,
            "selection_source": self.selection_source,
            "selection_reason": self.selection_reason,
            "authorization_ref": self.authorization_ref,
            "decided_at": self.decided_at,
        }

    @property
    def digest(self) -> str:
        return _canonical_digest(self.as_dict())

    def binding_errors(
        self,
        *,
        cr_id: str,
        source_oid: str,
        route_revision: int,
        authorization_digest: str = "",
        selection_channel: str = "config",
    ) -> tuple[str, ...]:
        errors: list[str] = []
        if self.cr_id != cr_id:
            errors.append("G3_SELECTION_CR_ID_MISMATCH")
        if not _OID_RE.fullmatch(source_oid):
            errors.append("G3_SELECTION_SOURCE_OID_INVALID")
        if type(route_revision) is not int or route_revision < 1:
            errors.append("G3_SELECTION_ROUTE_REVISION_INVALID")
        if not _SHA256_RE.fullmatch(authorization_digest):
            errors.append("G3_SELECTION_AUTHORIZATION_DIGEST_REQUIRED")
        if selection_channel != "host-injection":
            errors.append("G3_SELECTION_PROVENANCE_INVALID")
        return tuple(errors)


@dataclass(frozen=True, slots=True)
class GovernanceProfileBindingV2:
    """跨 route/context/status/validation 复用的最小等级绑定。"""

    schema_version: int
    risk_profile: str
    effective_profile: str
    selection_source: str
    selection_record_digest: str
    selection_authorization_digest: str
    selection_source_oid: str
    route_revision: int

    def __post_init__(self) -> None:
        if self.schema_version != GOVERNANCE_PROFILE_SCHEMA_VERSION:
            raise ValueError("GOVERNANCE_PROFILE_BINDING_SCHEMA_INVALID")
        expected = effective_governance_profile(self.risk_profile, self.schema_version)
        if self.effective_profile != expected:
            raise ValueError("GOVERNANCE_PROFILE_BINDING_EFFECTIVE_PROFILE_MISMATCH")
        if type(self.route_revision) is not int or self.route_revision < 1:
            raise ValueError("GOVERNANCE_PROFILE_BINDING_ROUTE_REVISION_INVALID")
        if self.risk_profile == "G3":
            if self.selection_source != "user-explicit":
                raise ValueError("GOVERNANCE_PROFILE_BINDING_G3_SOURCE_INVALID")
            if not _SHA256_RE.fullmatch(self.selection_record_digest):
                raise ValueError("GOVERNANCE_PROFILE_BINDING_G3_DIGEST_INVALID")
            if not _SHA256_RE.fullmatch(self.selection_authorization_digest):
                raise ValueError("GOVERNANCE_PROFILE_BINDING_G3_AUTHORIZATION_DIGEST_INVALID")
            if not _OID_RE.fullmatch(self.selection_source_oid):
                raise ValueError("GOVERNANCE_PROFILE_BINDING_G3_SOURCE_OID_INVALID")
        elif (
            self.selection_source != "system-default"
            or self.selection_record_digest
            or self.selection_authorization_digest
            or self.selection_source_oid
        ):
            raise ValueError("GOVERNANCE_PROFILE_BINDING_DEFAULT_SOURCE_INVALID")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "risk_profile": self.risk_profile,
            "effective_profile": self.effective_profile,
            "selection_source": self.selection_source,
            "selection_record_digest": self.selection_record_digest,
            "selection_authorization_digest": self.selection_authorization_digest,
            "selection_source_oid": self.selection_source_oid,
            "route_revision": self.route_revision,
        }

    @property
    def digest(self) -> str:
        return _canonical_digest(self.as_dict())


@dataclass(frozen=True, slots=True)
class GovernanceProfileTransitionV1:
    decision: str
    from_profile: str
    to_profile: str
    route_revision: int
    resume_checkpoint: str
    invalidated_checkpoints: tuple[str, ...]
    reason_codes: tuple[str, ...]
    mutation_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "GovernanceProfileTransitionV1",
            "decision": self.decision,
            "from_profile": self.from_profile,
            "to_profile": self.to_profile,
            "route_revision": self.route_revision,
            "resume_checkpoint": self.resume_checkpoint,
            "invalidated_checkpoints": list(self.invalidated_checkpoints),
            "reason_codes": list(self.reason_codes),
            "mutation_count": self.mutation_count,
        }


def plan_profile_transition(
    current: GovernanceProfileBindingV2,
    requested_profile: str,
    *,
    selection_record: G3SelectionRecordV1 | None = None,
    selection_cr_id: str = "",
    selection_source_oid: str = "",
    selection_authorization_digest: str = "",
    selection_channel: str = "config",
    current_checkpoint: str = "CP2",
) -> GovernanceProfileTransitionV1:
    """规划迟到升级；只给出失效边界，不写 checkpoint 或状态。"""

    if requested_profile not in GOVERNANCE_RISK_PROFILES:
        raise ValueError("requested_profile must be G0, G1, G2, or G3")
    ranks = {"G0": 0, "G1": 1, "G2": 2, "G3": 3}
    current_profile = current.effective_profile
    if ranks[requested_profile] < ranks[current_profile]:
        return GovernanceProfileTransitionV1(
            "BLOCKED",
            current_profile,
            current_profile,
            current.route_revision,
            current_checkpoint,
            (),
            ("DOWNGRADE_REJECTED",),
        )
    if requested_profile == current_profile:
        return GovernanceProfileTransitionV1(
            "NO_CHANGE",
            current_profile,
            current_profile,
            current.route_revision,
            current_checkpoint,
            (),
            (),
        )
    if requested_profile != "G3" or selection_record is None:
        return GovernanceProfileTransitionV1(
            "BLOCKED",
            current_profile,
            current_profile,
            current.route_revision,
            current_checkpoint,
            (),
            ("G3_SELECTION_REQUIRED",),
        )
    binding_errors = selection_record.binding_errors(
        cr_id=selection_cr_id,
        source_oid=selection_source_oid,
        route_revision=current.route_revision + 1,
        authorization_digest=selection_authorization_digest,
        selection_channel=selection_channel,
    )
    if binding_errors:
        return GovernanceProfileTransitionV1(
            "BLOCKED",
            current_profile,
            current_profile,
            current.route_revision,
            current_checkpoint,
            (),
            binding_errors,
        )
    normalized_checkpoint = str(current_checkpoint or "").upper()
    if normalized_checkpoint not in {f"CP{index}" for index in range(9)}:
        raise ValueError("current_checkpoint must be CP0..CP8")
    invalidated = (
        ("CP3", "CP4", "CP5")
        if int(normalized_checkpoint[2:]) >= 3
        else ()
    )
    resume = "CP3" if invalidated else normalized_checkpoint
    return GovernanceProfileTransitionV1(
        "READY",
        current_profile,
        "G3",
        current.route_revision + 1,
        resume,
        invalidated,
        ("USER_REQUESTED_FULL_LLD_G3",),
    )


def build_profile_binding(
    risk_profile: str,
    *,
    schema_version: int = GOVERNANCE_PROFILE_SCHEMA_VERSION,
    selection_record: G3SelectionRecordV1 | None = None,
    selection_authorization_digest: str = "",
    selection_source_oid: str = "",
    route_revision: int = 1,
) -> GovernanceProfileBindingV2:
    if risk_profile == "G3":
        if selection_record is None:
            raise ValueError("G3_SELECTION_REQUIRED")
        source = "user-explicit"
        selection_digest = selection_record.digest
        if not _SHA256_RE.fullmatch(selection_authorization_digest):
            raise ValueError("G3_SELECTION_AUTHORIZATION_DIGEST_REQUIRED")
        if not _OID_RE.fullmatch(selection_source_oid):
            raise ValueError("G3_SELECTION_SOURCE_OID_INVALID")
    else:
        if selection_record is not None:
            raise ValueError("G3_SELECTION_WITH_NON_G3_PROFILE")
        source = "system-default"
        selection_digest = ""
        selection_authorization_digest = ""
        selection_source_oid = ""
    return GovernanceProfileBindingV2(
        schema_version=schema_version,
        risk_profile=risk_profile,
        effective_profile=effective_governance_profile(risk_profile, schema_version),
        selection_source=source,
        selection_record_digest=selection_digest,
        selection_authorization_digest=selection_authorization_digest,
        selection_source_oid=selection_source_oid,
        route_revision=route_revision,
    )


__all__ = [
    "FULL_DESIGN_PROFILES",
    "GOVERNANCE_PROFILE_SCHEMA_VERSION",
    "GOVERNANCE_RISK_PROFILES",
    "HIGH_ASSURANCE_PROFILES",
    "G3SelectionRecordV1",
    "GovernanceProfileBindingV2",
    "GovernanceProfileTransitionV1",
    "build_profile_binding",
    "effective_governance_profile",
    "is_high_assurance",
    "plan_profile_transition",
    "requires_full_design",
]
