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

## 文档处理决策

> 每个受影响正式文档必须填写一行。处理方式只能为：新增 / 原文档更新 / 归档 / 不变。
> 若选择“原文档更新”，必须说明旧内容保留方式，并在目标文档追加 `## 修订记录`。

| 受影响文档 | 处理方式 | 旧基线保留方式 | 修订记录位置 | 批准状态 |
|---|---|---|---|---|
| `process/USE-CASES.md` | 新增 / 原文档更新 / 归档 / 不变 | 既有基线 / 历史场景 / 被 CR 替换的场景 / CR 完整摘录与映射 | `## 修订记录` / 不适用 | pending |
| `process/REQUIREMENTS.md` | 新增 / 原文档更新 / 归档 / 不变 | 既有基线 / 历史需求 / 被 CR 替换的需求 / CR 完整摘录与映射 | `## 修订记录` / 不适用 | pending |

## 旧基线映射

| 原基线对象 | 新增 / 修改对象 | 保留策略 | 映射说明 |
|---|---|---|---|
| UC-* / REQ-* / 章节号 | UC-* / REQ-* / 章节号 | 原文保留 / 历史区保留 / CR 摘录保留 | 说明旧内容如何追溯到新内容 |

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

## LLD 设计批次门禁

> 若本 CR 影响 Story、LLD、接口契约、文件所有权、`dev_gate` 或实现设计，必须填写本节。批次内全部 LLD 设计和 CP5 自动预检完成并统一人工确认前，不得实施任何 Story。

- 是否需要 LLD 设计批次：true / false
- batch_id：`CR-{id}-LLD-BATCH`
- 批次范围来源：CR 影响分析 / 人工指定
- 批次内 Story：
  - `STORY-*`
- 批次人工确认稿：`checkpoints/CP5-{batch_id}-LLD-BATCH.md`
- 开发启动条件：
  - [ ] 批次内全部 Story LLD 已输出
  - [ ] 批次内全部 Story CP5 自动预检已通过
  - [ ] 批次 CP5 人工确认结论为 `approved`
  - [ ] 批次内每个 Story 的 `dev_gate` 已满足

## 执行链路

> CR 创建时必须先写明串行依赖、责任角色、门控和恢复点。`meta-po` 负责分派与收敛；功能 Agent 只处理自身职责，不关闭 CR、不推进 `delivered`。

| 顺序 | 责任角色 | 动作 | 输入 | 输出 | 门控 | 完成后下一步 |
|---|---|---|---|---|---|---|
| 1 | `meta-po` | 创建 CR 并分派 | 用户请求 / ISSUE / RUN-EXEC | 本 CR、handoff、调度证据 | CR 已登记 | 等待下游完成 |
| 2 | `meta-dev` | 完成 LLD 设计批次或实施变更 | CR、handoff、相关 Story / 文件 | 批次内 LLD、代码、目录或交付产物变更 | 若影响 Story / LLD / 实现设计：先通过批次 CP5；否则进入 CP6 / 对应验证证据 | 交回 `meta-po` |
| 3 | `meta-doc` | 刷新文档 | CR、当前交付物、变更结果 | README / USER-MANUAL / 文档更新 | 文档自检 | 交回 `meta-po` |
| 4 | `meta-po` | 收敛终验 | 下游结果、CR、检查点 | CP8 自动预检与人工审查稿 | 等待用户确认或有效预授权 | 写入 `pending_user_decision` |
| 5 | `meta-po` | 回填确认并关闭 CR | 用户确认或有效预授权 | CR closed、STATE 更新 | CP8 approved | 推进 `delivered` 或下一阶段 |

## 自动终验授权

> 默认不启用。只有用户在同一轮请求中明确授权时才填写并生效；否则必须等待人工确认。

- 是否启用：false
- 授权范围：仅本 CR / 指定检查点 / 不适用
- 适用检查点：CP8 / 其他
- 自动通过条件：
  - [ ] 自动预检结论为 `PASS`
  - [ ] 无 `BLOCKING`
  - [ ] 无 `REQUIRED`
  - [ ] 授权动作明确包含关闭 CR 和 / 或推进 `delivered`
- 授权原文：
- 授权时间：
- 回填要求：若生效，人工审查稿必须标注 `approval_source=user-preauthorized`

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
