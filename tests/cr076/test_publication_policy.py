"""STORY-CR076-S01 targeted 测试：eligibility + 四态聚合 + published-verified + lineage
（PP-05/PP-05b/PP-06 + PP-N04..N08）。

权威 = cr076-publication-policy TEST-PLAN + LLD §2.1 F5..F8 / §10。
"""

from __future__ import annotations

from meta_flow.release.publication_policy import (
    OPERATION_AUTHORIZATION_REQUIRED,
    OPERATION_CP8_EVIDENCE_REQUIRED,
    PUBLICATION_TRANSITION_FORBIDDEN,
    RISK_CLASSIFICATION_BLOCKED,
    LineageInputsV1,
    PublicationTargetOutcome,
    aggregate_publication_phase,
    evaluate_operation_publication_admission,
    evaluate_published_verification,
    lineage_stability_check,
    phase_transition_allowed,
)
from meta_flow.release.risk_policy import RiskGrade, evaluate_risk_grade

_ASSETS = {
    "wheel": "a" * 64,
    "sdist": "b" * 64,
    "build_receipt": "c" * 64,
    "sidecar": "d" * 64,
}
_TARGETS_OK = (
    PublicationTargetOutcome("git-tag", "refs/tags/v0.6.1", "SUCCEEDED", "1" * 64),
    PublicationTargetOutcome("registry-upload", "pypi/meta-flow/0.6.1", "SUCCEEDED", "2" * 64),
)


def test_pp05_three_layer_separation() -> None:
    # 第二层：operation 级 grade 决定 evidence/disclosure 标志（第一层 CR 级 CP8 固定，
    # 不由 policy 决定——admission 对象不存在 CR 级字段，只输出 operation 级判定）。
    g0 = evaluate_operation_publication_admission("op-g0", evaluate_risk_grade(["ORDINARY"]))
    assert g0.grade == "G0"
    assert g0.requires_operation_cp8_evidence is False
    assert g0.disclosure_required is False
    assert g0.operation_eligibility == "PASS"
    g1 = evaluate_operation_publication_admission("op-g1", evaluate_risk_grade(["PUBLIC"]))
    assert g1.grade == "G1"
    assert g1.disclosure_required is True
    assert g1.requires_operation_cp8_evidence is False
    assert g1.operation_eligibility == "PASS"
    g2 = evaluate_operation_publication_admission(
        "op-g2",
        evaluate_risk_grade(["CREDENTIAL"]),
        operation_cp8_evidence_present=True,
        typed_authorization_present=True,
    )
    assert g2.grade == "G2"
    assert g2.requires_operation_cp8_evidence is True
    assert g2.operation_eligibility == "PASS"


def test_pp05b_two_layer_classification_eligibility() -> None:
    # classification PASS 但 G2 证据未齐 → eligibility BLOCKED、分类结果保留（HLD-AMENDMENT-A1 A3）。
    missing_evidence = evaluate_operation_publication_admission(
        "op-g2a", evaluate_risk_grade(["CREDENTIAL"])
    )
    assert missing_evidence.grade == "G2"
    assert missing_evidence.operation_eligibility == "BLOCKED"
    assert missing_evidence.eligibility_blocker == OPERATION_CP8_EVIDENCE_REQUIRED
    missing_auth = evaluate_operation_publication_admission(
        "op-g2b",
        evaluate_risk_grade(["CREDENTIAL"]),
        operation_cp8_evidence_present=True,
    )
    assert missing_auth.operation_eligibility == "BLOCKED"
    assert missing_auth.eligibility_blocker == OPERATION_AUTHORIZATION_REQUIRED
    # classification BLOCKED（unknown/空/冲突）→ 短路不评估 eligibility。
    for codes in ([], ["free-text"]):
        admission = evaluate_operation_publication_admission(
            "op-blocked", evaluate_risk_grade(codes)
        )
        assert admission.operation_eligibility == "BLOCKED"
        assert admission.eligibility_blocker == RISK_CLASSIFICATION_BLOCKED
        assert admission.grade is None


def test_pp06_aggregation_transition_table() -> None:
    # 任一 FAILED 优先 blocked；任一 PARTIAL（无 FAILED）→ partial；全 SUCCEEDED → complete-unverified。
    failed_wins = aggregate_publication_phase(
        "awaiting-publication",
        (*_TARGETS_OK, PublicationTargetOutcome("asset-upload", "u", "FAILED", "3" * 64)),
    )
    assert (failed_wins.decision, failed_wins.phase, failed_wins.blocker_code) == (
        "PASS",
        "publication-blocked",
        None,
    )
    assert aggregate_publication_phase(
        "awaiting-publication",
        (PublicationTargetOutcome("git-tag", "refs/tags/v0.6.1", "PARTIAL", "1" * 64),),
    ).phase == "publication-partial"
    assert aggregate_publication_phase("awaiting-publication", _TARGETS_OK).phase == (
        "publication-complete-unverified"
    )
    # 重试路径：partial → partial（幂等重聚合）与 partial → complete 均合法。
    assert aggregate_publication_phase("publication-partial", _TARGETS_OK).decision == "PASS"
    # blocked → partial（重试）合法；blocked → awaiting 为显式重规划路径（查表开放）。
    assert phase_transition_allowed("publication-blocked", "awaiting-publication") is True
    assert aggregate_publication_phase(
        "publication-blocked", (PublicationTargetOutcome("git-tag", "t", "PARTIAL", "4" * 64),)
    ).phase == "publication-partial"
    # awaiting 无 attempt（outcomes 空）→ NO_CHANGE。
    no_change = aggregate_publication_phase("awaiting-publication", ())
    assert no_change.decision == "NO_CHANGE"
    assert no_change.phase == "awaiting-publication"


def test_pp06_published_verified_requires_complete_unverified() -> None:
    # published-verified 唯一入口：complete-unverified + verified=True。
    verified = aggregate_publication_phase("publication-complete-unverified", _TARGETS_OK, verified=True)
    assert verified.decision == "PASS"
    assert verified.phase == "published-verified"
    # 终态封闭。
    terminal = aggregate_publication_phase("published-verified", _TARGETS_OK)
    assert terminal.decision == "BLOCKED"
    assert terminal.blocker_code == PUBLICATION_TRANSITION_FORBIDDEN


def test_pp06_verification_positive() -> None:
    from meta_flow.release.publication_policy import PublishedVerificationInputsV1

    decision = evaluate_published_verification(
        PublishedVerificationInputsV1(
            accepted_assets=_ASSETS,
            observed_assets=dict(_ASSETS),
            observed_at="2026-09-01T00:00:00Z",
            valid_until="2026-09-02T00:00:00Z",
            target_outcomes=_TARGETS_OK,
        ),
        now="2026-09-01T12:00:00Z",
    )
    assert decision.decision == "VERIFIED"
    assert decision.mismatched_fields == ()
    assert decision.freshness_valid is True


def test_pp_n04_illegal_transition_blocks() -> None:
    # awaiting 直跳 published-verified（verified=True）→ BLOCKED typed findings。
    illegal = aggregate_publication_phase("awaiting-publication", _TARGETS_OK, verified=True)
    assert illegal.decision == "BLOCKED"
    assert illegal.phase is None
    assert illegal.blocker_code == PUBLICATION_TRANSITION_FORBIDDEN
    # 未知当前态 → BLOCKED。
    assert aggregate_publication_phase("nonsense-phase", ()).decision == "BLOCKED"


def test_pp_n05_asset_field_mismatch_not_verified() -> None:
    from meta_flow.release.publication_policy import PublishedVerificationInputsV1

    drifted = dict(_ASSETS)
    drifted["wheel"] = "e" * 64
    decision = evaluate_published_verification(
        PublishedVerificationInputsV1(
            accepted_assets=_ASSETS,
            observed_assets=drifted,
            observed_at="2026-09-01T00:00:00Z",
            valid_until="2026-09-02T00:00:00Z",
            target_outcomes=_TARGETS_OK,
        ),
        now="2026-09-01T12:00:00Z",
    )
    assert decision.decision == "NOT_VERIFIED"
    assert decision.mismatched_fields == ("wheel",)
    assert decision.freshness_valid is True


def test_pp_n06_not_all_succeeded_not_verified() -> None:
    from meta_flow.release.publication_policy import PublishedVerificationInputsV1

    decision = evaluate_published_verification(
        PublishedVerificationInputsV1(
            accepted_assets=_ASSETS,
            observed_assets=dict(_ASSETS),
            observed_at="2026-09-01T00:00:00Z",
            valid_until="2026-09-02T00:00:00Z",
            target_outcomes=(
                PublicationTargetOutcome("git-tag", "refs/tags/v0.6.1", "SUCCEEDED", "1" * 64),
                PublicationTargetOutcome("registry-upload", "pypi/meta-flow/0.6.1", "PARTIAL", "2" * 64),
            ),
        ),
        now="2026-09-01T12:00:00Z",
    )
    # 分型：无字段差、freshness 有效、仍 NOT_VERIFIED = 存在非 SUCCEEDED target。
    assert decision.decision == "NOT_VERIFIED"
    assert decision.mismatched_fields == ()
    assert decision.freshness_valid is True


def test_pp_n07_freshness_expired_not_verified() -> None:
    from meta_flow.release.publication_policy import PublishedVerificationInputsV1

    decision = evaluate_published_verification(
        PublishedVerificationInputsV1(
            accepted_assets=_ASSETS,
            observed_assets=dict(_ASSETS),
            observed_at="2026-09-01T00:00:00Z",
            valid_until="2026-09-01T06:00:00Z",
            target_outcomes=_TARGETS_OK,
        ),
        now="2026-09-01T12:00:00Z",
    )
    assert decision.decision == "NOT_VERIFIED"
    assert decision.freshness_valid is False


def test_pp_n08_lineage_four_elements() -> None:
    previous = LineageInputsV1(
        artifact_digests=("a" * 64, "b" * 64),
        source_oids=("c" * 40, "d" * 40),
        semver="0.6.1",
        target_kinds=("git-tag", "registry-upload"),
    )
    assert lineage_stability_check(previous, previous) is True
    # 四要素逐项 perturb：任一变化 → 新 lineage（ADR-076-07）。
    assert lineage_stability_check(
        previous,
        LineageInputsV1(("a" * 64, "e" * 64), previous.source_oids, "0.6.1", previous.target_kinds),
    ) is False
    assert lineage_stability_check(
        previous,
        LineageInputsV1(previous.artifact_digests, ("c" * 40, "f" * 40), "0.6.1", previous.target_kinds),
    ) is False
    assert lineage_stability_check(
        previous,
        LineageInputsV1(previous.artifact_digests, previous.source_oids, "0.6.2", previous.target_kinds),
    ) is False
    assert lineage_stability_check(
        previous,
        LineageInputsV1(previous.artifact_digests, previous.source_oids, "0.6.1", ("git-tag",)),
    ) is False


def test_risk_grade_ordering() -> None:
    # 全序 G0 < G1 < G2（合并取 max 的基础）。
    assert RiskGrade.G0 < RiskGrade.G1 < RiskGrade.G2
    assert max(RiskGrade.G0, RiskGrade.G2) is RiskGrade.G2
