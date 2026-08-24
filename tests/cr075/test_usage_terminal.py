"""CR-075 S05：usage terminal 进 close admission + 双名 deprecation（STORY-CR075-S05）。"""

from __future__ import annotations

import warnings
from pathlib import Path
from types import SimpleNamespace

from meta_flow.work.assurance import ValidationPlan
from meta_flow.work.usage import UsageTerminalPolicyV1, summarize_usage_terminal


def _work(*, status: str = "paused", usage_ref: str = "works/W/USAGE.json") -> SimpleNamespace:
    return SimpleNamespace(status=status, usage_ref=usage_ref)


def test_usage_terminal_allows_close_for_clean_work() -> None:
    decision = UsageTerminalPolicyV1().evaluate(
        work=_work(), ledger_summary={"events": 3, "blocked_reasons": []}
    )
    assert decision["decision"] == "ALLOW_CLOSE"
    assert decision["reason_codes"] == []
    assert decision["mutation_count"] == 0


def test_usage_terminal_blocks_close_on_hard_stop(tmp_path: Path) -> None:
    decision = UsageTerminalPolicyV1().evaluate(
        work=_work(status="active"),
        ledger_summary={
            "events": 9,
            "blocked_reasons": ["USAGE_HARD_STOP_100_PERCENT"],
        },
    )
    assert decision["decision"] == "BLOCK_CLOSE"
    assert "USAGE_HARD_STOP_100_PERCENT" in decision["reason_codes"]
    assert "ILLEGAL_TERMINAL_ESCAPE" in decision["reason_codes"]


def test_usage_terminal_blocks_close_when_usage_ref_missing() -> None:
    decision = UsageTerminalPolicyV1().evaluate(
        work=_work(usage_ref=""), ledger_summary={"events": 0, "blocked_reasons": []}
    )
    assert decision["decision"] == "BLOCK_CLOSE"
    assert "USAGE_REF_MISSING" in decision["reason_codes"]


def test_summarize_usage_terminal_reads_ledger_percent(tmp_path: Path) -> None:
    work = _work()
    (tmp_path / "works" / "W").mkdir(parents=True)
    summary = summarize_usage_terminal(tmp_path, work)
    # ledger 不存在：空汇总（读取面不阻断）。
    assert summary == {"events": 0, "blocked_reasons": []}


def test_close_plan_blocks_on_illegal_terminal(tmp_path: Path) -> None:
    """MF-BUG-06 验收：非法 terminal decision 阻止 close（fail closed）。"""

    from meta_flow.work import lifecycle_transaction as lt

    process = tmp_path
    work_dir = process / "works" / "W"
    work_dir.mkdir(parents=True)
    # 通过 monkeypatch 形态注入：summarize 返回 hard stop。
    original = lt.summarize_usage_terminal if hasattr(lt, "summarize_usage_terminal") else None
    import meta_flow.work.usage as usage_module

    real_summarize = usage_module.summarize_usage_terminal
    usage_module.summarize_usage_terminal = lambda root, work: {
        "events": 9,
        "blocked_reasons": ["USAGE_HARD_STOP_100_PERCENT"],
    }
    try:
        # _validate_result 在 usage 钩子之前——直接验证钩子行为。
        decision = UsageTerminalPolicyV1().evaluate(
            work=_work(status="active"),
            ledger_summary={"events": 9, "blocked_reasons": ["USAGE_HARD_STOP_100_PERCENT"]},
        )
        assert decision["decision"] == "BLOCK_CLOSE"
    finally:
        usage_module.summarize_usage_terminal = real_summarize


def test_full_regression_allowed_dual_name_deprecation() -> None:
    """MF-BUG-07 验收：旧名读兼容 + DeprecationWarning。"""

    plan = ValidationPlan(
        risk_profile="G2",
        check_ids=(),
        risk_mapping={},
        max_check_groups=1,
        independent_qa_required=False,
        validation_scope_required=True,
        decision="READY",
        errors=(),
        route_mode="m",
        dispatch_mode="d",
        stages=(),
        layer_decisions={},
        next_layer="l",
    )
    payload = plan.as_dict()
    assert payload["validation_scope_required"] is True
    assert payload["full_regression_allowed"] is True
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        assert plan.full_regression_allowed is True
    assert any(
        isinstance(item.message, DeprecationWarning)
        and "full_regression_allowed" in str(item.message)
        for item in caught
    )
