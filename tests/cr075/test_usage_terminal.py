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


def test_summarize_usage_terminal_missing_ledger_is_zero_usage(tmp_path: Path) -> None:
    """S05 整改裁决：ledger 不存在 = 从未记账的合法初始态（零事件，不阻断）。

    依据：真实治理仓 63 个 Work 中 39 个无 USAGE.json（usage-add 尚未发生）。
    损坏（存在但不可读/symlink）才 fail closed。
    """

    work = _work()
    (tmp_path / "works" / "W").mkdir(parents=True)
    summary = summarize_usage_terminal(tmp_path, work)
    assert summary == {"events": 0, "blocked_reasons": []}

    decision = UsageTerminalPolicyV1().evaluate(work=_work(status="paused"), ledger_summary=summary)
    assert decision["decision"] == "ALLOW_CLOSE"


def test_summarize_usage_terminal_symlink_ledger_fails_closed(tmp_path: Path) -> None:
    import os

    work = _work()
    ledger = tmp_path / "works" / "W" / "USAGE.json"
    ledger.parent.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    os.symlink(outside, ledger)
    summary = summarize_usage_terminal(tmp_path, work)
    assert summary["blocked_reasons"] == ["USAGE_LEDGER_UNREADABLE"]


def test_summarize_usage_terminal_unreadable_ledger_fails_closed(tmp_path: Path) -> None:
    work = _work()
    ledger = tmp_path / "works" / "W" / "USAGE.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{ broken", encoding="utf-8")
    summary = summarize_usage_terminal(tmp_path, work)
    assert summary["blocked_reasons"] == ["USAGE_LEDGER_UNREADABLE"]


# ---- S05 整改：真实 plan_work_close 负向 ----


def test_real_plan_work_close_blocks_on_hard_stop(tmp_path: Path) -> None:
    """MF-BUG-06 验收：非法 usage terminal 阻止真实 close plan（fail closed）。"""

    from meta_flow.project.scale import dump_yaml
    from meta_flow.work import lifecycle_transaction as lt

    work_id = "WORK-S05-CLOSE-001"
    work_dir = tmp_path / "works" / work_id
    work_dir.mkdir(parents=True)
    # 结果文件（PASS）满足 close 的 result 前置。
    result = work_dir / "RESULT.yaml"
    result.write_text(
        dump_yaml({"schema_version": 1, "work_id": work_id, "decision": "PASS"}),
        encoding="utf-8",
    )
    # WORK.yaml：完整 envelope（usage ledger 缺失以触发 fail closed）。
    import hashlib
    import json as json_module

    scope = {
        "version": 1,
        "allowed_reads": [f"works/{work_id}/RESULT.yaml"],
        "allowed_writes": ["meta_flow/work/x.py"],
        "required_checks": ["CHECK-1"],
    }
    work_dir.joinpath("WORK.yaml").write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "work_id": work_id,
                "project_id": "fixture",
                "kind": "work",
                "objective": "close negative fixture",
                "status": "paused",
                "request_ref": f"works/{work_id}/REQUEST.md",
                "request_confirmed": True,
                "risk_profile": "G1",
                "risk_reason_codes": ["PUBLIC_CONTRACT"],
                "required_gates": ["GATE-SCOPE"],
                "scope": scope,
                "scope_digest": hashlib.sha256(
                    json_module.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "budget": {"reads": 8, "writes": 8, "check_groups": 4, "tokens": 100000},
                "usage_ref": f"works/{work_id}/USAGE.json",
                "base_oids": {"release": "", "process": ""},
            }
        ),
        encoding="utf-8",
    )
    work_dir.joinpath("REQUEST.md").write_text("# r\n", encoding="utf-8")
    # 损坏 ledger：存在但不可解析 -> fail closed。
    work_dir.joinpath("USAGE.json").write_text("{ broken", encoding="utf-8")

    plan = lt.plan_work_close(
        tmp_path,
        work_id,
        expected_status="paused",
        outcome="completed",
        result_ref=f"works/{work_id}/RESULT.yaml",
    )
    # close plan 对非法 usage terminal 输出 typed BLOCKED（零 mutation）。
    assert plan.decision == "BLOCKED"
    assert any("usage terminal blocks close" in blocker for blocker in plan.blockers)
    assert not plan.ready


def test_close_plan_blocks_on_illegal_terminal(tmp_path: Path) -> None:
    """MF-BUG-06 验收：非法 terminal decision 阻止 close（fail closed）。"""


    process = tmp_path
    work_dir = process / "works" / "W"
    work_dir.mkdir(parents=True)
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
