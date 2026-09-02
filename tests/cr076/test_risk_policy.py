"""STORY-CR076-S01 targeted 测试：RiskReasonPolicyV1 前移 plan/admission（PP-01..PP-04 + PP-N01/N02）。

权威 = cr076-publication-policy TEST-PLAN + LLD §2.1 F1..F5 / §10。
"""

from __future__ import annotations

import re

from meta_flow.release.risk_policy import (
    RISK_CODE_UNKNOWN,
    RISK_INPUT_CONFLICT,
    RISK_INPUT_EMPTY,
    RISK_REASON_POLICY_VERSION,
    RiskGrade,
    build_risk_input_fingerprint,
    evaluate_risk_grade,
    revalidate_risk_input,
    risk_reason_policy_fingerprint,
)

# PP-01：闭合词表 7 code 确定映射（F1 表）。
EXPECTED_MAPPING = {
    "ORDINARY": RiskGrade.G0,
    "REGISTRY-PUBLIC": RiskGrade.G1,
    "PUBLIC": RiskGrade.G1,
    "SECURITY-BOUNDARY": RiskGrade.G2,
    "CREDENTIAL": RiskGrade.G2,
    "PRODUCTION-WRITE": RiskGrade.G2,
    "LIVE": RiskGrade.G2,
}


def test_pp01_closed_vocabulary_deterministic_mapping() -> None:
    for code, grade in EXPECTED_MAPPING.items():
        evaluation = evaluate_risk_grade([code])
        assert evaluation.decision == "PASS", (code, evaluation)
        assert evaluation.grade is grade
        assert evaluation.blocker_code is None
        assert evaluation.reason_codes == (code,)
    # 词表闭合：无第 8 个 code 可 PASS（词表外全部走 unknown 分支）。
    assert len(EXPECTED_MAPPING) == 7


def test_pp02_max_merge_and_idempotence() -> None:
    # 多原因最高级合并：grade=max(所有 code)。
    assert evaluate_risk_grade(["ORDINARY", "PUBLIC"]).grade is RiskGrade.G1
    assert evaluate_risk_grade(["PUBLIC", "CREDENTIAL"]).grade is RiskGrade.G2
    assert evaluate_risk_grade(["ORDINARY", "REGISTRY-PUBLIC"]).grade is RiskGrade.G1
    assert evaluate_risk_grade(["ORDINARY"]).grade is RiskGrade.G0
    # 重复 code 幂等 + 乱序归一：去重有序存储，fingerprint 输入稳定。
    assert evaluate_risk_grade(["ORDINARY", "ORDINARY", " ORDINARY "]).reason_codes == ("ORDINARY",)
    assert evaluate_risk_grade(["PUBLIC", "ORDINARY"]).reason_codes == evaluate_risk_grade(
        ["ORDINARY", "PUBLIC"]
    ).reason_codes == ("ORDINARY", "PUBLIC")


def test_pp03_fail_closed_blocked_outputs() -> None:
    # 三情形全部 BLOCKED、grade=None（不猜等级）、blocker 必填。
    for codes in ([], ["  ", "\t"], ["自由文本风险"], ["ORDINARY", "UNKNOWN-CODE"]):
        evaluation = evaluate_risk_grade(codes)
        assert evaluation.decision == "BLOCKED", codes
        assert evaluation.grade is None
        assert evaluation.blocker_code in {RISK_INPUT_EMPTY, RISK_CODE_UNKNOWN}


def test_pp_n01_empty_input_blocks() -> None:
    evaluation = evaluate_risk_grade([])
    assert evaluation.decision == "BLOCKED"
    assert evaluation.blocker_code == RISK_INPUT_EMPTY
    assert evaluation.grade is None
    assert evaluation.reason_codes == ()
    evaluation_blank = evaluate_risk_grade(["   "])
    assert evaluation_blank.blocker_code == RISK_INPUT_EMPTY


def test_pp_n02_unknown_code_blocks_with_context() -> None:
    evaluation = evaluate_risk_grade(["ORDINARY", "历史自由文本"])
    assert evaluation.decision == "BLOCKED"
    assert evaluation.blocker_code == RISK_CODE_UNKNOWN
    assert evaluation.grade is None
    # O-S01-1 基线：阻断信息保留原始 code（reason_codes 去重有序存储）与词表版本。
    assert "历史自由文本" in evaluation.reason_codes
    assert evaluation.policy_version == RISK_REASON_POLICY_VERSION


def test_pp04_policy_fingerprint_stable_and_bound() -> None:
    fingerprint = risk_reason_policy_fingerprint()
    # 同实现同输入 → 同值（抗 dict 顺序漂移：内部按 sorted(code) 构造）。
    assert fingerprint == risk_reason_policy_fingerprint()
    assert re.fullmatch(r"[0-9a-f]{64}", fingerprint)
    # fingerprint 不随调用方 codes 变化（只绑定 version + 词表）。
    other = evaluate_risk_grade(["CREDENTIAL"])
    assert other.policy_fingerprint == fingerprint
    # input fingerprint 绑定 codes：codes 变 → 冻结值变（plan/授权失效）。
    g1 = build_risk_input_fingerprint(evaluate_risk_grade(["ORDINARY", "PUBLIC"]))
    g2 = build_risk_input_fingerprint(evaluate_risk_grade(["ORDINARY"]))
    assert g1.input_fingerprint != g2.input_fingerprint
    assert g1.policy_fingerprint == g2.policy_fingerprint


def test_pp_n03_revalidation_conflict_blocks() -> None:
    evaluation = evaluate_risk_grade(["ORDINARY", "PUBLIC"])
    frozen = build_risk_input_fingerprint(evaluation)
    # 同输入 → PASS。
    assert revalidate_risk_input(frozen, ["PUBLIC", "ORDINARY"]).decision == "PASS"
    # codes 漂移 → RISK_INPUT_CONFLICT。
    drifted = revalidate_risk_input(frozen, ["CREDENTIAL"])
    assert drifted.decision == "BLOCKED"
    assert drifted.blocker_code == RISK_INPUT_CONFLICT
    # policy fingerprint 漂移（伪造冻结值）→ RISK_INPUT_CONFLICT。
    tampered = type(frozen)(
        schema_version=1,
        policy_fingerprint="0" * 64,
        reason_codes=frozen.reason_codes,
        input_fingerprint=frozen.input_fingerprint,
    )
    assert revalidate_risk_input(tampered, ["ORDINARY", "PUBLIC"]).blocker_code == RISK_INPUT_CONFLICT
    # 当前输入本身非法（空/词表外）→ 原生 blocker 优先（三情形互斥，LLD §8）。
    assert revalidate_risk_input(frozen, []).blocker_code == RISK_INPUT_EMPTY
    assert revalidate_risk_input(frozen, ["free-text"]).blocker_code == RISK_CODE_UNKNOWN
