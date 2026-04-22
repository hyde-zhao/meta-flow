---
cr_id: "CR-{id}"
status: "open"
impact_level: "low|medium|high"
rollback_to: ""
approval_result: "pending"
created_at: ""
created_by: "meta-po"
approved_by: ""
approved_at: ""
source: "user|issue|run-exec"
linked_issue: ""
---

## 变更描述

[用户或 Agent 提出的变更内容]

## 五维度影响分析

| 维度 | 评估问题 | 受影响对象 | 结论（true/false） | 处理动作 |
|------|----------|-----------|--------------------|---------|
| 需求层 | 是否新增、删除或重定义 REQ-* | `REQUIREMENTS.md` |  |  |
| 场景层 | 是否改变测试矩阵覆盖范围 | `SCENARIOS.yaml` / `TEST-MATRIX.md` |  |  |
| 计划层 | 是否改变 Phase、Wave、任务依赖 | `WORKFLOW-PLAN.yaml` |  |  |
| 安全层 | 是否引入新的高风险动作或权限要求 | 安全边界 / 审计结论 |  |  |
| 交付层 | 是否需要重新生成交付物或回归子集 | 交付文档 / 回归集 |  |  |

## 回退决策

- 影响范围：局部 / 全局
- 回退到阶段：`rollback_to`
- 需要重新确认的对象：

## 处理结论

- 审批结论：`approval_result`
- [ ] 自动批准（低风险）
- [ ] 待人工确认（中风险）
- [ ] 待人工审批（高风险）

## 关联对象

| 类型 | 标识 | 说明 |
|---|---|---|
| ISSUE |  |  |
| RUN-EXEC |  |  |
| 其他文档 / 产物 |  |  |
