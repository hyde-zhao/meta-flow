"""publication policy：operation eligibility + publication 四态聚合（STORY-CR076-S01）。

纯判定模块（无 I/O 副作用）：三层分离的 operation 级 eligibility（消费 risk grade）、
四态聚合与迁移合法表（HLD §6.4）、published-verified 判定（digest-set 逐字段相等 +
全 target SUCCEEDED + freshness）、lineage 稳定性四要素（ADR-076-07）。
窄接口字段名对齐冻结 schema release-bundle-identity-v1，不 import S03 对象。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from meta_flow.release.risk_policy import (
    RiskGrade,
    RiskGradeEvaluationV1,
    build_risk_input_fingerprint,
)

# 资产 digest-set 固定四槽（对齐 PublishedVerifiedReceiptV1.accepted/observed_assets）。
ASSET_FIELDS: tuple[str, ...] = ("wheel", "sdist", "build_receipt", "sidecar")

OPERATION_CP8_EVIDENCE_REQUIRED = "OPERATION_CP8_EVIDENCE_REQUIRED"
OPERATION_AUTHORIZATION_REQUIRED = "OPERATION_AUTHORIZATION_REQUIRED"
RISK_CLASSIFICATION_BLOCKED = "RISK_CLASSIFICATION_BLOCKED"
PUBLICATION_TRANSITION_FORBIDDEN = "PUBLICATION_TRANSITION_FORBIDDEN"


class PublicationPhase(Enum):
    """publication 四态 + 终态（HLD §6.4；published-verified 为唯一 close 前置）。"""

    AWAITING = "awaiting-publication"
    PARTIAL = "publication-partial"
    BLOCKED = "publication-blocked"
    COMPLETE_UNVERIFIED = "publication-complete-unverified"
    PUBLISHED_VERIFIED = "published-verified"


# 状态迁移合法表（Feature DESIGN）：published-verified 为终态；freshness 超窗回退
# complete-unverified 仅由观测层触发，不在聚合函数内。
_PHASE_TRANSITIONS: dict[str, frozenset[str]] = {
    PublicationPhase.AWAITING.value: frozenset(
        {PublicationPhase.PARTIAL.value, PublicationPhase.BLOCKED.value, PublicationPhase.COMPLETE_UNVERIFIED.value}
    ),
    PublicationPhase.PARTIAL.value: frozenset(
        {PublicationPhase.PARTIAL.value, PublicationPhase.BLOCKED.value, PublicationPhase.COMPLETE_UNVERIFIED.value}
    ),
    PublicationPhase.BLOCKED.value: frozenset(
        {PublicationPhase.AWAITING.value, PublicationPhase.BLOCKED.value, PublicationPhase.PARTIAL.value}
    ),
    PublicationPhase.COMPLETE_UNVERIFIED.value: frozenset({PublicationPhase.PUBLISHED_VERIFIED.value}),
    PublicationPhase.PUBLISHED_VERIFIED.value: frozenset(),
}


def phase_transition_allowed(current: str, target: str) -> bool:
    """迁移合法表查询（blocked→awaiting 为显式重规划路径，供发布窗口判定）。"""

    if current not in _PHASE_TRANSITIONS:
        return False
    return target in _PHASE_TRANSITIONS[current]


@dataclass(frozen=True)
class OperationRiskAdmissionV1:
    """plan/admission 阶段写入 plan payload 的 operation 级准入记录（F5 两层语义）。"""

    schema_version: int
    operation_id: str
    grade: str | None
    reason_codes: tuple[str, ...]
    requires_operation_cp8_evidence: bool
    disclosure_required: bool
    policy_fingerprint: str
    input_fingerprint: str
    operation_eligibility: str
    eligibility_blocker: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": "OperationRiskAdmissionV1",
            "operation_id": self.operation_id,
            "grade": self.grade,
            "reason_codes": list(self.reason_codes),
            "requires_operation_cp8_evidence": self.requires_operation_cp8_evidence,
            "disclosure_required": self.disclosure_required,
            "policy_fingerprint": self.policy_fingerprint,
            "input_fingerprint": self.input_fingerprint,
            "operation_eligibility": self.operation_eligibility,
            "eligibility_blocker": self.eligibility_blocker,
        }


def evaluate_operation_publication_admission(
    operation_id: str,
    evaluation: RiskGradeEvaluationV1,
    *,
    operation_cp8_evidence_present: bool = False,
    typed_authorization_present: bool = False,
) -> OperationRiskAdmissionV1:
    """三层分离（F5）：classification 先行（BLOCKED 短路），eligibility 独立判定。

    formal CR 级 CP8 固定（CR-076=G2，不由 policy 决定）；operation 级 grade 决定
    requires_operation_cp8_evidence（G2）/ disclosure_required（G1）；G2 所需 CP8
    evidence 或 typed authorization 未齐 → eligibility BLOCKED（分类结果保留）。
    """

    grade_name = evaluation.grade.name if evaluation.grade is not None else None
    requires_evidence = evaluation.grade is RiskGrade.G2
    disclosure = evaluation.grade is RiskGrade.G1
    if evaluation.decision != "PASS":
        # 两层语义（HLD-AMENDMENT-A1 A3）：classification BLOCKED 短路不评估 eligibility。
        return OperationRiskAdmissionV1(
            schema_version=1,
            operation_id=operation_id,
            grade=None,
            reason_codes=evaluation.reason_codes,
            requires_operation_cp8_evidence=False,
            disclosure_required=False,
            policy_fingerprint=evaluation.policy_fingerprint,
            input_fingerprint="",
            operation_eligibility="BLOCKED",
            eligibility_blocker=RISK_CLASSIFICATION_BLOCKED,
        )
    frozen = build_risk_input_fingerprint(evaluation)
    blocker: str | None = None
    if requires_evidence and not operation_cp8_evidence_present:
        blocker = OPERATION_CP8_EVIDENCE_REQUIRED
    elif requires_evidence and not typed_authorization_present:
        blocker = OPERATION_AUTHORIZATION_REQUIRED
    return OperationRiskAdmissionV1(
        schema_version=1,
        operation_id=operation_id,
        grade=grade_name,
        reason_codes=evaluation.reason_codes,
        requires_operation_cp8_evidence=requires_evidence,
        disclosure_required=disclosure,
        policy_fingerprint=frozen.policy_fingerprint,
        input_fingerprint=frozen.input_fingerprint,
        operation_eligibility="PASS" if blocker is None else "BLOCKED",
        eligibility_blocker=blocker,
    )


@dataclass(frozen=True)
class PublicationTargetOutcome:
    """窄接口（字段名对齐 PublicationReceiptV1.target/outcome）。"""

    target_kind: str
    target_identity: str
    outcome: str
    attempt_digest: str


@dataclass(frozen=True)
class PublicationPhaseDecisionV1:
    """四态聚合结果：非法迁移 BLOCKED（typed blocker，不暴露 traceback）。"""

    decision: str
    phase: str | None
    blocker_code: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "PublicationPhaseDecisionV1",
            "decision": self.decision,
            "phase": self.phase,
            "blocker_code": self.blocker_code,
        }


def aggregate_publication_phase(
    current: str,
    outcomes: Sequence[PublicationTargetOutcome],
    *,
    verified: bool = False,
) -> PublicationPhaseDecisionV1:
    """四态聚合（F6）：任一 FAILED 优先 blocked；全 SUCCEEDED → complete-unverified；
    complete-unverified + verified=True → published-verified（唯一 close 前置）。"""

    try:
        current_phase = PublicationPhase(current)
    except ValueError:
        return PublicationPhaseDecisionV1("BLOCKED", None, PUBLICATION_TRANSITION_FORBIDDEN)
    if current_phase is PublicationPhase.PUBLISHED_VERIFIED:
        return PublicationPhaseDecisionV1("BLOCKED", None, PUBLICATION_TRANSITION_FORBIDDEN)
    if verified:
        if current_phase is not PublicationPhase.COMPLETE_UNVERIFIED:
            return PublicationPhaseDecisionV1("BLOCKED", None, PUBLICATION_TRANSITION_FORBIDDEN)
        return PublicationPhaseDecisionV1("PASS", PublicationPhase.PUBLISHED_VERIFIED.value, None)
    if not outcomes:
        return PublicationPhaseDecisionV1("NO_CHANGE", current_phase.value, None)
    states = {item.outcome for item in outcomes}
    if "FAILED" in states:
        target = PublicationPhase.BLOCKED
    elif "PARTIAL" in states:
        target = PublicationPhase.PARTIAL
    else:
        target = PublicationPhase.COMPLETE_UNVERIFIED
    if target.value not in _PHASE_TRANSITIONS[current_phase.value]:
        return PublicationPhaseDecisionV1("BLOCKED", None, PUBLICATION_TRANSITION_FORBIDDEN)
    decision = "NO_CHANGE" if target is current_phase else "PASS"
    return PublicationPhaseDecisionV1(decision, target.value, None)


@dataclass(frozen=True)
class PublishedVerificationInputsV1:
    """published-verified 判定输入（窄接口，对齐 PublishedVerifiedReceiptV1 字段名）。"""

    accepted_assets: Mapping[str, str]
    observed_assets: Mapping[str, str]
    observed_at: str
    valid_until: str
    target_outcomes: Sequence[PublicationTargetOutcome]


@dataclass(frozen=True)
class PublishedVerificationDecisionV1:
    """VERIFIED 仅当逐字段相等 + 全 target SUCCEEDED + freshness 窗口有效（F7）。"""

    decision: str
    mismatched_fields: tuple[str, ...]
    freshness_valid: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "PublishedVerificationDecisionV1",
            "decision": self.decision,
            "mismatched_fields": list(self.mismatched_fields),
            "freshness_valid": self.freshness_valid,
        }


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def evaluate_published_verification(
    inputs: PublishedVerificationInputsV1, *, now: str | None = None
) -> PublishedVerificationDecisionV1:
    """digest-set 逐字段相等 + 全 target SUCCEEDED + freshness（PP-N05/06/07 分型）。

    NOT_VERIFIED 分型：mismatched_fields 非空=字段差；freshness_valid=False=超窗；
    两者皆无但仍 NOT_VERIFIED=存在非 SUCCEEDED target（PP-N06）。
    """

    mismatched = tuple(
        sorted(
            field
            for field in ASSET_FIELDS
            if inputs.accepted_assets.get(field) != inputs.observed_assets.get(field)
        )
    )
    observed = _parse_instant(inputs.observed_at)
    valid_until = _parse_instant(inputs.valid_until)
    if now is not None:
        current = _parse_instant(now)
        freshness_valid = observed <= current < valid_until
    else:
        freshness_valid = observed < valid_until
    all_succeeded = bool(inputs.target_outcomes) and all(
        item.outcome == "SUCCEEDED" for item in inputs.target_outcomes
    )
    verified = not mismatched and freshness_valid and all_succeeded
    return PublishedVerificationDecisionV1(
        "VERIFIED" if verified else "NOT_VERIFIED",
        mismatched,
        freshness_valid,
    )


@dataclass(frozen=True)
class LineageInputsV1:
    """lineage 稳定性四要素比对物（F8；双仓 source OID 各 40 hex）。"""

    artifact_digests: tuple[str, ...]
    source_oids: tuple[str, str]
    semver: str
    target_kinds: tuple[str, ...]


def lineage_stability_check(previous: LineageInputsV1, current: LineageInputsV1) -> bool:
    """四要素均不变 → 同一 lineage；任一变化 → 新 lineage（ADR-076-07）。"""

    return (
        previous.artifact_digests == current.artifact_digests
        and previous.source_oids == current.source_oids
        and previous.semver == current.semver
        and previous.target_kinds == current.target_kinds
    )


__all__ = [
    "ASSET_FIELDS",
    "OPERATION_AUTHORIZATION_REQUIRED",
    "OPERATION_CP8_EVIDENCE_REQUIRED",
    "LineageInputsV1",
    "OperationRiskAdmissionV1",
    "PublicationPhase",
    "PublicationPhaseDecisionV1",
    "PublicationTargetOutcome",
    "PUBLICATION_TRANSITION_FORBIDDEN",
    "PublishedVerificationDecisionV1",
    "PublishedVerificationInputsV1",
    "RISK_CLASSIFICATION_BLOCKED",
    "aggregate_publication_phase",
    "evaluate_operation_publication_admission",
    "evaluate_published_verification",
    "lineage_stability_check",
    "phase_transition_allowed",
]
