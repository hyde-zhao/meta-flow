"""模板/规范治理校验（MFP-0016/0017/0019）。"""

from __future__ import annotations

from meta_flow import templates


def _standard(name: str) -> str:
    assert name in templates.STANDARDS, f"缺少规范: {name}"
    return templates.STANDARDS[name]


def _artifact(name: str) -> str:
    assert name in templates.ARTIFACT_TEMPLATES, f"缺少模板: {name}"
    return templates.ARTIFACT_TEMPLATES[name]


def test_phase_plan_covers_all_five_phases_with_inputs_rules_validation():
    phase = _standard("PHASE.md")
    assert "任务拆解规则" in phase and "验证规则" in phase
    assert "输入" in phase and "输出/过程交付件" in phase and "退出条件" in phase
    for marker in ("P1", "P2", "P3", "P4", "P5"):
        assert f"## {marker}" in phase or f"| {marker}" in phase
    # P1 需求基线/E2E；P2 规格-模块矩阵；P3 按模块 + 跨模块验证；P4 聚类；P5 发布清单
    assert "需求基线" in phase and "E2E" in phase
    assert "规格-模块矩阵" in phase
    assert "跨模块" in phase and "独立验证任务" in phase
    assert "聚类验收" in phase and "单条 REQ 状态" in phase
    assert "发布固定工作清单" in phase


def test_spec_module_matrix_template_has_fields_and_three_examples():
    matrix = _artifact("SPEC-MODULE-MATRIX.md")
    for field in ("spec_id", "主责模块", "参与模块", "接口/契约", "验证任务", "状态"):
        assert field in matrix
    # 一个规格落多模块、一个模块承载多规格、跨模块独立验证任务
    assert "一个规格落多模块" in matrix
    assert "一个模块承载多规格" in matrix
    assert "跨模块验证任务" in matrix
    assert "SPEC-BILL-001" in matrix and "web" in matrix


def test_task_card_dor_and_minimal_fields():
    card = _standard("TASK-CARD.md")
    assert "可独立验证的增量" in card
    assert "每个 BUG/MFP 至少一个自动化用例" in card
    assert "验证方式" in card and "证据" in card
    assert "blocked" in card and "manager 裁决" in card
    task = _artifact("TASK.yaml")
    for field in ("module:", "spec_ids:", "verification:", "evidence:"):
        assert field in task
    assert "command" in task and "evidence" in task


def test_decision_levels_template_and_log_fields():
    decisions = _standard("DECISIONS.md")
    for marker in ("D0", "D1", "D2", "D3", "用户必决", "技术决策", "自动决策"):
        assert marker in decisions
    assert "升级规则" in decisions and "决策日志" in decisions
    log = _artifact("DECISION-LOG.md")
    for field in ("问题", "选项", "默认值", "影响", "确认人", "日期", "结论"):
        assert field in log
    assert "D0" in log and "D2" in log


def test_phase_plan_contains_decisions_cluster_and_release_checklist():
    plan = _artifact("PHASE-PLAN.md")
    assert "决策清单/未决项" in plan
    assert "跨模块规格验证" in plan
    assert "P4 需求聚类验收" in plan and "单条 REQ 状态表" in plan
    assert "P5 发布固定工作清单" in plan
    for item in ("release freeze", "发布说明", "用户手册", "安装/升级 smoke", "归档"):
        assert item in plan
    report = _artifact("PHASE-REPORT.md")
    assert "需求聚类验收与单条 REQ 状态" in report
    assert "决策日志摘要" in report


def test_acceptance_has_cluster_and_release_gate():
    acceptance = _standard("ACCEPTANCE.md")
    assert "P4 需求聚类验收" in acceptance
    assert "聚类覆盖矩阵" in acceptance and "单条 REQ 状态表" in acceptance
    assert "P5 发布固定工作清单" in acceptance
    assert "BLOCKED 不算完成" in acceptance


def test_documentation_necessity_matrix_and_limits():
    documentation = _standard("DOCUMENTATION.md")
    assert "文档必要性矩阵" in documentation
    for marker in ("必须保留", "合并", "归档", "唯一真相", "owner", "读者", "更新时机"):
        assert marker in documentation
    assert "页数/字数上限" in documentation
    assert "任务卡 ≤1 页" in documentation
    assert "引用" in documentation and "禁止复制" in documentation


def test_context_has_hot_warm_cold_and_role_matrix():
    context = _standard("CONTEXT.md")
    for marker in ("热区", "暖区", "冷区", "角色读写矩阵"):
        assert marker in context
    assert "review_scope 内任意大小文件" in context
    assert "must_read" in context and "packet_missing" in context
    assert "TASK.yaml + ledger 是任务真相" in context


def test_agent_templates_include_decisions_and_phase_rules():
    for name in ("AGENT_MANAGER", "AGENT_WORKER"):
        text = getattr(templates, name)
        assert "决策" in text and "D0" in text
    manager = templates.AGENT_MANAGER
    assert "规格-模块矩阵" in manager and "可独立验证的增量" in manager
    worker = templates.AGENT_WORKER
    assert "独立 verify 任务" in worker
    assert "BLOCKED" in worker
