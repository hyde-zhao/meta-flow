"""当前切片失败证据与派生状态之间的最小安全关联模型。

本模块只解释调用方已经选定的 current-head 事实，不发现历史、不写状态，
也不扩展 P7 才负责的完整暂停/恢复状态词汇。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FailureTruthStatusV1(StrEnum):
    """CR-073 允许的最小投影安全状态。"""

    HEALTHY = "healthy"
    ORPHAN_FAIL = "orphan_fail"
    PENDING_GATE_MISSING = "pending_gate_missing"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class FailureReceiptFactV1:
    work_id: str
    evidence_ref: str
    evidence_digest: str
    check_result_digest: str
    decision: str
    current: bool = True
    superseded_by: str = ""

    def __post_init__(self) -> None:
        if not self.work_id or not self.evidence_ref:
            raise ValueError("failure receipt fact identity is required")
        for field in ("evidence_digest", "check_result_digest"):
            if not _SHA256_RE.fullmatch(getattr(self, field)):
                raise ValueError(f"{field} must be one lowercase SHA-256 digest")
        if self.decision not in {"FAIL", "BLOCKED", "PASS"}:
            raise ValueError("failure receipt decision is invalid")
        if type(self.current) is not bool:
            raise ValueError("failure receipt current must be boolean")


@dataclass(frozen=True, slots=True)
class FailureObservationFactV1:
    observation_ref: str
    evidence_ref: str
    check_result_digest: str
    registration_status: str
    current: bool = True

    def __post_init__(self) -> None:
        if not self.observation_ref or not self.evidence_ref:
            raise ValueError("failure observation identity is required")
        if not _SHA256_RE.fullmatch(self.check_result_digest):
            raise ValueError("check_result_digest must be one lowercase SHA-256 digest")
        if self.registration_status not in {"recorded", "failed"}:
            raise ValueError("failure observation registration_status is invalid")
        if type(self.current) is not bool:
            raise ValueError("failure observation current must be boolean")


@dataclass(frozen=True, slots=True)
class GateHeadFactV1:
    expected_gate: str
    projected_gate: str
    result_ref: str = ""
    decision: str = ""
    current: bool = True


@dataclass(frozen=True, slots=True)
class RouteExpectationV1:
    expected_pending_gate: str = ""
    automatic_stage_in_progress: bool = False


@dataclass(frozen=True, slots=True)
class FailureCorrelationV1:
    status: FailureTruthStatusV1
    receipt_refs: tuple[str, ...]
    observation_refs: tuple[str, ...]
    finding_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": self.status.value,
            "receipt_refs": list(self.receipt_refs),
            "observation_refs": list(self.observation_refs),
            "finding_codes": list(self.finding_codes),
        }


@dataclass(frozen=True, slots=True)
class ProjectionSafetyFindingV1:
    code: str
    severity: str
    stop_reason: str
    next_action: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "stop_reason": self.stop_reason,
            "next_action": self.next_action,
        }


def correlate_failure_truth(
    receipts: Sequence[FailureReceiptFactV1],
    observations: Sequence[FailureObservationFactV1],
    gate_head: GateHeadFactV1 | None = None,
) -> FailureCorrelationV1:
    """关联 current-slice receipt 与 observation；历史 superseded 事实不参与。"""

    current_receipts = tuple(
        item for item in receipts if item.current and not item.superseded_by
    )
    current_observations = tuple(item for item in observations if item.current)
    receipt_refs = tuple(sorted(item.evidence_ref for item in current_receipts))
    observation_refs = tuple(
        sorted(item.observation_ref for item in current_observations)
    )

    by_work: dict[str, int] = {}
    for receipt in current_receipts:
        by_work[receipt.work_id] = by_work.get(receipt.work_id, 0) + 1
    if any(count > 1 for count in by_work.values()):
        return FailureCorrelationV1(
            FailureTruthStatusV1.BLOCKED,
            receipt_refs,
            observation_refs,
            ("CURRENT_FAILURE_HEAD_AMBIGUOUS",),
        )

    for receipt in current_receipts:
        if receipt.decision not in {"FAIL", "BLOCKED"}:
            continue
        matching = tuple(
            item
            for item in current_observations
            if item.evidence_ref == receipt.evidence_ref
            and item.check_result_digest == receipt.check_result_digest
        )
        if len(matching) > 1:
            return FailureCorrelationV1(
                FailureTruthStatusV1.BLOCKED,
                receipt_refs,
                observation_refs,
                ("FAILURE_OBSERVATION_AMBIGUOUS",),
            )
        if not matching:
            return FailureCorrelationV1(
                FailureTruthStatusV1.ORPHAN_FAIL,
                receipt_refs,
                observation_refs,
                ("ORPHAN_FAIL_RECEIPT",),
            )
        if matching[0].registration_status != "recorded":
            return FailureCorrelationV1(
                FailureTruthStatusV1.BLOCKED,
                receipt_refs,
                observation_refs,
                ("FAILURE_OBSERVATION_REGISTRATION_FAILED",),
            )

    if (
        gate_head is not None
        and gate_head.current
        and gate_head.expected_gate
        and gate_head.projected_gate != gate_head.expected_gate
    ):
        return FailureCorrelationV1(
            FailureTruthStatusV1.PENDING_GATE_MISSING,
            receipt_refs,
            observation_refs,
            ("FORMAL_PENDING_GATE_MISSING",),
        )
    return FailureCorrelationV1(
        FailureTruthStatusV1.HEALTHY,
        receipt_refs,
        observation_refs,
        (),
    )


def evaluate_projection_safety(
    correlation: FailureCorrelationV1,
    route_expectation: RouteExpectationV1 | None = None,
) -> tuple[ProjectionSafetyFindingV1, ...]:
    """把关联状态和 route expectation 收敛为稳定 finding。"""

    expectation = route_expectation or RouteExpectationV1()
    if (
        expectation.expected_pending_gate
        and not expectation.automatic_stage_in_progress
        and correlation.status is FailureTruthStatusV1.HEALTHY
    ):
        return (
            ProjectionSafetyFindingV1(
                "FORMAL_PENDING_GATE_MISSING",
                "ERROR",
                "blocked",
                "blocked",
            ),
        )
    if correlation.status is FailureTruthStatusV1.HEALTHY:
        return ()
    code = correlation.finding_codes[0] if correlation.finding_codes else "FORMAL_TRUTH_BLOCKED"
    return (ProjectionSafetyFindingV1(code, "ERROR", "blocked", "blocked"),)


def project_safe_next_action(
    status: FailureTruthStatusV1 | str,
    *,
    finding_codes: Sequence[str] = (),
) -> dict[str, Any]:
    """为非健康真相生成现有状态词汇可表达的最保守动作。"""

    normalized = FailureTruthStatusV1(status)
    if normalized is FailureTruthStatusV1.HEALTHY:
        return {}
    code = str(next(iter(finding_codes), "FORMAL_TRUTH_BLOCKED"))
    return {
        "type": "blocked",
        "text": f"Formal truth projection is blocked: {code}.",
        "stop_reason": "blocked",
    }


def correlation_from_mapping(payload: Mapping[str, Any] | None) -> FailureCorrelationV1:
    """解析 snapshot 中的 closed failure truth，不接受未知字段。"""

    if payload is None:
        return FailureCorrelationV1(FailureTruthStatusV1.HEALTHY, (), (), ())
    expected = {
        "schema_version",
        "status",
        "receipt_refs",
        "observation_refs",
        "finding_codes",
    }
    if set(payload) != expected or payload.get("schema_version") != 1:
        raise ValueError("failure truth snapshot fields mismatch")
    for field in ("receipt_refs", "observation_refs", "finding_codes"):
        if not isinstance(payload.get(field), list) or not all(
            isinstance(item, str) for item in payload[field]
        ):
            raise ValueError(f"failure truth {field} must be a list of strings")
    return FailureCorrelationV1(
        FailureTruthStatusV1(str(payload["status"])),
        tuple(payload["receipt_refs"]),
        tuple(payload["observation_refs"]),
        tuple(payload["finding_codes"]),
    )


__all__ = [
    "FailureCorrelationV1",
    "FailureObservationFactV1",
    "FailureReceiptFactV1",
    "FailureTruthStatusV1",
    "GateHeadFactV1",
    "ProjectionSafetyFindingV1",
    "RouteExpectationV1",
    "correlate_failure_truth",
    "correlation_from_mapping",
    "evaluate_projection_safety",
    "project_safe_next_action",
]
