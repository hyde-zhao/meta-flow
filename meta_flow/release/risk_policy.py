"""RiskReasonPolicyV1：结构化 risk reason code 的 plan/admission 前移判定（STORY-CR076-S01）。

纯判定模块（无 I/O 副作用）：闭合 7 code 词表确定映射 G0/G1/G2、多原因最高级合并、
fail-closed 三情形（RISK_INPUT_EMPTY / RISK_CODE_UNKNOWN / RISK_INPUT_CONFLICT）、
policy version/fingerprint 绑定与 apply 前重验输入（ADR-076-08 / ADR-076-07）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum

# 状态机语义：G0 < G1 < G2 全序，多原因合并取 max。
RISK_REASON_POLICY_VERSION = "1"


class RiskGrade(IntEnum):
    """operation 级 risk grade（G0 < G1 < G2；CR 级 CP8 不由本枚举决定）。"""

    G0 = 0
    G1 = 1
    G2 = 2

    def __str__(self) -> str:  # pragma: no cover - 表现层
        return self.name


# 闭合词表（F1）：code → grade 确定映射；词表外任何输入 fail-closed。
_CODE_TO_GRADE: dict[str, RiskGrade] = {
    "ORDINARY": RiskGrade.G0,
    "REGISTRY-PUBLIC": RiskGrade.G1,
    "PUBLIC": RiskGrade.G1,
    "SECURITY-BOUNDARY": RiskGrade.G2,
    "CREDENTIAL": RiskGrade.G2,
    "PRODUCTION-WRITE": RiskGrade.G2,
    "LIVE": RiskGrade.G2,
}

# fail-closed blocker 枚举（三情形互斥全覆盖，LLD §8）。
RISK_INPUT_EMPTY = "RISK_INPUT_EMPTY"
RISK_CODE_UNKNOWN = "RISK_CODE_UNKNOWN"
RISK_INPUT_CONFLICT = "RISK_INPUT_CONFLICT"


def risk_reason_policy_fingerprint() -> str:
    """sha256(version + canonical code→grade 有序映射)；词表/版本变更即指纹漂移。"""

    payload = {
        "policy_version": RISK_REASON_POLICY_VERSION,
        "code_to_grade": [
            {"code": code, "grade": _CODE_TO_GRADE[code].name}
            for code in sorted(_CODE_TO_GRADE)
        ],
    }
    canonical = ",".join(
        f'{entry["code"]}={entry["grade"]}' for entry in payload["code_to_grade"]
    )
    return hashlib.sha256(
        f"{RISK_REASON_POLICY_VERSION}|{canonical}".encode()
    ).hexdigest()


@dataclass(frozen=True)
class RiskGradeEvaluationV1:
    """判定结果唯一载体：BLOCKED 时不猜等级（grade=None、blocker 必填）。"""

    schema_version: int
    policy_version: str
    policy_fingerprint: str
    reason_codes: tuple[str, ...]
    grade: RiskGrade | None
    decision: str
    blocker_code: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": "RiskGradeEvaluationV1",
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "reason_codes": list(self.reason_codes),
            "grade": self.grade.name if self.grade is not None else None,
            "decision": self.decision,
            "blocker_code": self.blocker_code,
        }


def _normalize(reason_codes: Sequence[str]) -> tuple[str, ...]:
    """strip、去空、去重、排序（fingerprint 稳定；重复 code 幂等）。"""

    stripped = [str(code).strip() for code in reason_codes]
    return tuple(sorted({code for code in stripped if code}))


def evaluate_risk_grade(reason_codes: Sequence[str]) -> RiskGradeEvaluationV1:
    """闭合词表确定映射 + 多原因最高级合并 + fail-closed（F1..F3）。"""

    fingerprint = risk_reason_policy_fingerprint()
    codes = _normalize(reason_codes)
    if not codes:
        return RiskGradeEvaluationV1(
            schema_version=1,
            policy_version=RISK_REASON_POLICY_VERSION,
            policy_fingerprint=fingerprint,
            reason_codes=codes,
            grade=None,
            decision="BLOCKED",
            blocker_code=RISK_INPUT_EMPTY,
        )
    unknown = [code for code in codes if code not in _CODE_TO_GRADE]
    if unknown:
        # O-S01-1 基线：fail-closed 原样阻断，信息带原始 code 与词表版本，不做 alias 归一化。
        return RiskGradeEvaluationV1(
            schema_version=1,
            policy_version=RISK_REASON_POLICY_VERSION,
            policy_fingerprint=fingerprint,
            reason_codes=codes,
            grade=None,
            decision="BLOCKED",
            blocker_code=RISK_CODE_UNKNOWN,
        )
    grade = max(_CODE_TO_GRADE[code] for code in codes)
    return RiskGradeEvaluationV1(
        schema_version=1,
        policy_version=RISK_REASON_POLICY_VERSION,
        policy_fingerprint=fingerprint,
        reason_codes=codes,
        grade=grade,
        decision="PASS",
        blocker_code=None,
    )


@dataclass(frozen=True)
class RiskInputFingerprintV1:
    """plan 冻结值 / apply 重验比对物（policy fingerprint + codes 联合 digest）。"""

    schema_version: int
    policy_fingerprint: str
    reason_codes: tuple[str, ...]
    input_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": "RiskInputFingerprintV1",
            "policy_fingerprint": self.policy_fingerprint,
            "reason_codes": list(self.reason_codes),
            "input_fingerprint": self.input_fingerprint,
        }


def build_risk_input_fingerprint(evaluation: RiskGradeEvaluationV1) -> RiskInputFingerprintV1:
    """从 PASS evaluation 构造 plan 冻结值。"""

    if evaluation.decision != "PASS":
        raise ValueError("RISK_EVALUATION_NOT_PASS")
    digest = hashlib.sha256(
        "|".join((evaluation.policy_fingerprint, *evaluation.reason_codes)).encode("utf-8")
    ).hexdigest()
    return RiskInputFingerprintV1(
        schema_version=1,
        policy_fingerprint=evaluation.policy_fingerprint,
        reason_codes=evaluation.reason_codes,
        input_fingerprint=digest,
    )


@dataclass(frozen=True)
class RiskRevalidationV1:
    """apply 前重验结果：PASS 或 BLOCKED（blocker 必填）。"""

    decision: str
    blocker_code: str | None = None
    detail: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "RiskRevalidationV1",
            "decision": self.decision,
            "blocker_code": self.blocker_code,
            "detail": list(self.detail),
        }


def revalidate_risk_input(
    frozen: RiskInputFingerprintV1 | dict[str, object],
    current_reason_codes: Sequence[str],
) -> RiskRevalidationV1:
    """apply 前重验（F3/F5）：当前输入与 plan 冻结值不一致即 RISK_INPUT_CONFLICT。

    三情形互斥（LLD §8）：当前输入空/unknown 先行阻断（原 blocker）；
    policy fingerprint 或 codes 联合 digest 漂移 → RISK_INPUT_CONFLICT。
    """

    if isinstance(frozen, RiskInputFingerprintV1):
        frozen_input = frozen
    else:
        raw_codes = frozen.get("reason_codes")
        frozen_input = RiskInputFingerprintV1(
            schema_version=1,
            policy_fingerprint=str(frozen.get("policy_fingerprint") or ""),
            reason_codes=tuple(str(code) for code in raw_codes)
            if isinstance(raw_codes, (list, tuple))
            else (),
            input_fingerprint=str(frozen.get("input_fingerprint") or ""),
        )
    evaluation = evaluate_risk_grade(current_reason_codes)
    if evaluation.decision != "PASS":
        return RiskRevalidationV1("BLOCKED", evaluation.blocker_code, evaluation.reason_codes)
    current = build_risk_input_fingerprint(evaluation)
    if current.policy_fingerprint != frozen_input.policy_fingerprint:
        return RiskRevalidationV1("BLOCKED", RISK_INPUT_CONFLICT, ("policy_fingerprint",))
    if current.input_fingerprint != frozen_input.input_fingerprint:
        return RiskRevalidationV1("BLOCKED", RISK_INPUT_CONFLICT, ("reason_codes",))
    return RiskRevalidationV1("PASS", None, ())


__all__ = [
    "RISK_INPUT_CONFLICT",
    "RISK_INPUT_EMPTY",
    "RISK_CODE_UNKNOWN",
    "RISK_REASON_POLICY_VERSION",
    "RiskGrade",
    "RiskGradeEvaluationV1",
    "RiskInputFingerprintV1",
    "RiskRevalidationV1",
    "build_risk_input_fingerprint",
    "evaluate_risk_grade",
    "revalidate_risk_input",
    "risk_reason_policy_fingerprint",
]
