"""STORY-CR076-S01 集成测试：release_order 调用点（PP-07 + PP-N03/N09 + 零变化回归）。

plan_release_advance 写入 admission 记录、check_release_transition apply 前重验、
diagnose_publication_phase 薄委托；不传 risk 参数时既有状态机语义零变化。
权威 = cr076-publication-policy TEST-PLAN + LLD §2.1 F9 / §4 / §10。
"""

from __future__ import annotations

from test_cr072_release_order import _event, _initial, _snapshot

from meta_flow.workflow.release_order import (
    InMemoryReleaseWriter,
    check_release_transition,
    diagnose_publication_phase,
    plan_release_advance,
)


def _plan_fixture(writer: InMemoryReleaseWriter, action: str = "candidate-ready"):
    """构造（state, event, snapshot）三元组；action 默认首个状态机动作。"""

    state = _initial()
    event = _event(state, action)
    snapshot = _snapshot(state, writer)
    return state, event, snapshot


def test_pp07_plan_writes_risk_admission() -> None:
    writer = InMemoryReleaseWriter()
    state, event, snapshot = _plan_fixture(writer)
    plan = plan_release_advance(state, event, snapshot, risk_reason_codes=["ORDINARY", "PUBLIC"])
    assert plan.decision == "PASS", [d.as_dict() for d in plan.diagnostics]
    assert plan.after_state is not None
    # admission 记录进入 plan payload（参与 plan_digest，fingerprint 绑定授权）。
    admission = plan.risk_admission
    assert admission is not None
    assert admission["kind"] == "OperationRiskAdmissionV1"
    assert admission["grade"] == "G1"
    assert admission["disclosure_required"] is True
    assert admission["operation_eligibility"] == "PASS"
    assert plan.as_dict()["risk_admission"] == dict(admission)
    # plan_digest 覆盖 admission：不含该键的 digest 必然不同。
    baseline = plan_release_advance(state, event, snapshot)
    assert baseline.plan_digest != plan.plan_digest


def test_pp07_risk_codes_omitted_keeps_legacy_behavior() -> None:
    """不传 risk_reason_codes → 输出结构与既有语义零变化（向后兼容增量）。"""

    writer = InMemoryReleaseWriter()
    state, event, snapshot = _plan_fixture(writer)
    plan = plan_release_advance(state, event, snapshot)
    assert plan.decision == "PASS"
    assert plan.risk_admission is None
    assert plan.as_dict()["risk_admission"] is None
    # check 不传重验参数 → 零新增 diagnostics。
    result = check_release_transition(state, event)
    assert result.decision == "PASS"
    assert result.diagnostics == ()
    # 无 admission 的 plan digest 与两次独立调用一致（确定性）。
    again = plan_release_advance(state, event, snapshot)
    assert again.plan_digest == plan.plan_digest


def test_pp_n09_plan_rejects_blocked_risk_classification() -> None:
    writer = InMemoryReleaseWriter()
    state, event, snapshot = _plan_fixture(writer)
    plan = plan_release_advance(state, event, snapshot, risk_reason_codes=["历史自由文本"])
    assert plan.decision == "BLOCKED"
    assert plan.after_state is None
    assert plan.planned_mutation_count == 0
    assert plan.risk_admission is None
    # typed findings（结构化 blocker code）而非 traceback。
    codes = {item.code for item in plan.diagnostics}
    assert "RISK_CODE_UNKNOWN" in codes
    empty = plan_release_advance(state, event, snapshot, risk_reason_codes=["   "])
    assert empty.decision == "BLOCKED"
    assert {item.code for item in empty.diagnostics} >= {"RISK_INPUT_EMPTY"}


def test_pp_n03_apply_time_revalidation_blocks_on_drift() -> None:
    writer = InMemoryReleaseWriter()
    state, event, snapshot = _plan_fixture(writer)
    plan = plan_release_advance(state, event, snapshot, risk_reason_codes=["ORDINARY"])
    assert plan.decision == "PASS"
    # 同输入重验 → PASS。
    same = check_release_transition(
        state, event, plan.risk_admission, ["ORDINARY"]
    )
    assert same.decision == "PASS"
    # codes 漂移 → RISK_INPUT_CONFLICT、BLOCKED、mutation=0、授权不消费。
    drifted = check_release_transition(
        state, event, plan.risk_admission, ["CREDENTIAL"]
    )
    assert drifted.decision == "BLOCKED"
    assert drifted.mutation_count == 0
    assert "RISK_INPUT_CONFLICT" in {item.code for item in drifted.diagnostics}
    # fingerprint 漂移（伪造冻结 admission）同样阻断。
    tampered = dict(plan.risk_admission)
    tampered["policy_fingerprint"] = "0" * 64
    tampered_plan = check_release_transition(state, event, tampered, ["ORDINARY"])
    assert tampered_plan.decision == "BLOCKED"
    assert "RISK_INPUT_CONFLICT" in {item.code for item in tampered_plan.diagnostics}


def test_pp07_publication_phase_diagnostic_delegates() -> None:
    diagnostic = diagnose_publication_phase(
        "awaiting-publication",
        [
            {
                "target_kind": "git-tag",
                "target_identity": "refs/tags/v0.6.1",
                "outcome": "SUCCEEDED",
                "attempt_digest": "1" * 64,
            }
        ],
    )
    assert diagnostic["kind"] == "PublicationPhaseDiagnosticV1"
    assert diagnostic["decision"] == "PASS"
    assert diagnostic["phase"] == "publication-complete-unverified"
    assert diagnostic["mutation_count"] == 0
    illegal = diagnose_publication_phase("awaiting-publication", [], verified=True)
    assert illegal["decision"] == "BLOCKED"
    assert illegal["blocker_code"] == "PUBLICATION_TRANSITION_FORBIDDEN"
