---
cr_id: "CR-{id}"
cr_type: "feature"
cr_kind: "requirement-change"
lifecycle_status: "active"
readiness_status: "not_ready"
gate_status: "cp2_pending"
gate_profile: "full"
status: "open" # legacy compatibility; prefer lifecycle_status/readiness_status/gate_status
impact_level: "low|medium|high"
workflow_mode_before: "standard|fast-lane"
workflow_mode_after_change: "standard|fast-lane"
fast_lane_upgrade_reason: ""
rollback_to: ""
approval_result: "pending"
created_at: ""
created_by: "host-orchestrator"
approved_by: ""
approved_at: ""
source: "user|issue|run-exec|cp8-follow-up"
linked_issue: ""
parent_cr: ""
source_checkpoint: ""
source_decision_id: ""
follow_up_type: ""
risk_class: ""
owner: ""
revisit_condition: ""
acceptance_criteria: ""
close_condition: ""
cr_index_path: "process/changes/CR-INDEX.yaml"
current_requirement_baseline_path: "process/baseline/CURRENT-REQUIREMENT-BASELINE.yaml"
historical_baseline_status: "active"
reframed_by: []
reframe_summary: ""
goal_ref: ""
goal_statement: ""
user_goal_impact: ""
approval_focus: "scope|architecture|security|implementation|runtime|risk|follow_up"
split_rationale: ""
why_not_merge_with_parent: ""
why_not_story_or_task: ""
decision_burden: "none|low|medium|high"
approve_effect: ""
reject_effect: ""
not_authorized_by_approve: []
product_baseline_refresh_required: false
required_phase: ""
required_agent: ""
required_gate: ""
block_story_decomposition_until: ""
affected_product_docs: []
affected_use_cases: []
routing_design_ref: ""
---

## 变更描述

[用户或 Agent 提出的变更内容]

## 目标影响摘要

| 字段 | 内容 |
|---|---|
| 目标引用 | `goal_ref` |
| 整体目标 | `goal_statement` |
| 用户目标影响 | `user_goal_impact` |
| 本 CR 为什么值得独立推进 | `split_rationale` |
| approve 后会发生什么 | `approve_effect` |
| reject / 不确认会阻塞什么 | `reject_effect` |
| 决策负担 | `decision_burden` |

## 拆分理由

| 问题 | 结论 |
|---|---|
| 为什么不合并到 parent / active CR | `why_not_merge_with_parent` |
| 为什么不是 Story / task / follow-up | `why_not_story_or_task` |
| 触发独立 CR 的边界 | 目标 / 风险 / 授权 / 发布 / 回滚 / 审计 / 文件 owner |

## CP8 Follow-up 来源

> 仅当 `source=cp8-follow-up` 时填写。该正式 CR 由 follow-up tracking 台账中的候选项转入，不代表原 CP8 终验被重新打开，除非本 CR 的影响分析要求回退。

| 字段 | 内容 |
|---|---|
| 父级 CR | `parent_cr` |
| 来源检查点 | `source_checkpoint` |
| 来源决策 ID | `source_decision_id` |
| follow-up 类型 | `follow_up_type` |
| 风险等级 | `risk_class` |
| owner | `owner` |
| 重访条件 | `revisit_condition` |
| 验收标准 | `acceptance_criteria` |
| 关闭条件 | `close_condition` |

## CR 类型与门禁策略

| 字段 | 内容 |
|---|---|
| CR 类型 | `cr_type` |
| Legacy CR kind | `cr_kind` |
| 生命周期状态 | `lifecycle_status` |
| 就绪状态 | `readiness_status` |
| 门禁状态 | `gate_status` |
| 门禁模板 | `gate_profile` |

| CR 类型 | 用途 | 默认门禁模板 |
|---|---|---|
| `product-scope` | 改变产品范围、用户场景或需求基线 | `architecture-major` |
| `architecture` | 改架构边界、接口契约、模块边界或 ADR | `architecture-major` |
| `feature` | 已确认设计后的 Feature / Story 实现交付 | `standard-code` |
| `refactor` | 不改变外部契约的内部结构调整 | `standard-code` |
| `bugfix` | 缺陷修复和回归补充 | `standard-code` |
| `docs` | 说明文档、README、用户手册等 | `docs-lite` |
| `process` | 台账、checker、索引、归档、流程治理修复 | `process-lite` |
| `runtime` | 真实运行 / 凭据 / 账户 / NAS / 交易类授权或边界 | `runtime-high-risk` |
| `release` | 发布、安装、迁移、回滚、交付收敛 | `standard-code` / `runtime-high-risk` |
| `experiment` | 受控探索，不承诺交付 | `process-lite` |

## Checkpoint Index

> 本节只维护同一 CR 下 CP0-CP8 的状态摘要和 ref，不以内联章节作为检查点真相源。
> 自动 CP 的机器真相源必须是 `process/checks/CP*.result.json`；人工门禁 CP 的完整审查稿必须是 `process/checkpoints/CP*.md`；状态事件必须进入 `process/state/CHECKPOINT-LEDGER.ndjson` 或 `process/state/GATE-LEDGER.ndjson`。
> 不得把 CP result、Decision Brief、review 全文或历史 checkpoint 详情复制进 CR 正文。关闭 CR 后，本节仅保留 status + ref 指针。

| CP | 状态 | 机器结果 ref | 人工门禁 ref | Context ref | Ledger event ref | 摘要 |
|---|---|---|---|---|---|---|
| CP0 | pending / pass / fail / blocked / waived | `process/checks/CP0-*.result.json` | N/A | `process/context/CP0-*.context.json` | `process/state/CHECKPOINT-LEDGER.ndjson` |  |
| CP1 | pending / pass / fail / blocked / waived | `process/checks/CP1-*.result.json` | N/A | `process/context/CP1-*.context.json` | `process/state/CHECKPOINT-LEDGER.ndjson` |  |
| CP2 | pending / approved / rejected / blocked / waived | `process/checks/CP2-*.result.json` | `process/checkpoints/CP2-*.md` | `process/context/CP2-*-CONTEXT.yaml` | `process/state/GATE-LEDGER.ndjson` |  |
| CP3 | pending / approved / rejected / blocked / waived | `process/checks/CP3-*.result.json` | `process/checkpoints/CP3-*.md` | `process/context/CP3-*-CONTEXT.yaml` | `process/state/GATE-LEDGER.ndjson` |  |
| CP4 | pending / pass / fail / blocked / waived | `process/checks/CP4-*.result.json` | N/A | `process/context/CP4-*.context.json` | `process/state/CHECKPOINT-LEDGER.ndjson` | 汇入 CP5 |
| CP5 | pending / approved / rejected / blocked / waived | `process/checks/CP5-*.result.json` | `process/checkpoints/CP5-*.md` | `process/context/CP5-*-CONTEXT.yaml` | `process/state/GATE-LEDGER.ndjson` |  |
| CP6 | pending / pass / fail / blocked / waived | `process/checks/CP6-*.result.json` | N/A | `process/context/stories/*.CP6.work-packet.json` | `process/state/CHECKPOINT-LEDGER.ndjson` |  |
| CP7 | pending / pass / pass_with_risk / fail / blocked / waived | `process/checks/CP7-*.result.json` | N/A | `process/context/stories/*.CP7.verify-packet.json` | `process/state/CHECKPOINT-LEDGER.ndjson` |  |
| CP8 | pending / ready / ready_with_risk / not_ready / released / failed | `process/checks/CP8-*.result.json` | `process/checkpoints/CP8-*.md` | `process/context/CP8-*-CONTEXT.yaml` | `process/state/GATE-LEDGER.ndjson` |  |

## 结构化权限策略

> 默认不授权真实运行、凭据读取、NAS 访问、publish 或交易写入。任何下游任务、脚本、测试或 runbook 要求超出本策略时，必须阻断并转入 `runtime-authorization` CR 或重新发起人工门禁。
> `approve` 只接受本 CR 中的推荐方案；`not_authorized_by_approve` 中的事项必须单独授权。

```yaml
authorization_policy:
  nas:
    access: false
    list: false
    read: false
    write: false
    publish: false
    delete: false
  credentials:
    env_read: false
    secret_read: false
    account_read: false
  runtime:
    qmt: false
    miniqmt: false
    xtquant: false
    gateway: false
  trading:
    submit: false
    cancel: false
    simulation: false
    live: false
```

## 文档处理决策

> 每个受影响正式文档必须填写一行。处理方式只能为：新增 / 原文档更新 / 归档 / 不变。
> 若选择“原文档更新”，必须说明旧内容保留方式，并在目标文档追加 `## 修订记录`。
> 若本 CR 影响 `USE-CASES.md`、`REQUIREMENTS.md`、`SCENARIOS.yaml`、`TEST-MATRIX.md`、`STORY-MAP.md`、`MVP-SCOPE.md` 或产品范围基线，frontmatter 必须设置 `product_baseline_refresh_required=true`、`required_phase="requirement-clarification"`、`required_agent="meta-pm"`、`required_gate="CP2"`、`block_story_decomposition_until="CP2-approved"`，并填写 `affected_product_docs`。

| 受影响文档 | 处理方式 | 旧基线保留方式 | 修订记录位置 | 批准状态 |
|---|---|---|---|---|
| `docs/product/USE-CASES.md` | 新增 / 原文档更新 / 归档 / 不变 | 既有基线 / 历史场景 / 被 CR 替换的场景 / CR 完整摘录与映射 | `## 修订记录` / 不适用 | pending |
| `docs/product/REQUIREMENTS.md` | 新增 / 原文档更新 / 归档 / 不变 | 既有基线 / 历史需求 / 被 CR 替换的需求 / CR 完整摘录与映射 | `## 修订记录` / 不适用 | pending |

## 旧基线映射

| 原基线对象 | 新增 / 修改对象 | 保留策略 | 映射说明 |
|---|---|---|---|
| UC-* / REQ-* / 章节号 | UC-* / REQ-* / 章节号 | 原文保留 / 历史区保留 / CR 摘录保留 | 说明旧内容如何追溯到新内容 |

## 五维度影响分析

| 维度 | 评估问题 | 受影响对象 | 结论（true/false） | 处理动作 |
|------|----------|-----------|--------------------|---------|
| 需求层 | 是否新增、删除或重定义 REQ-* | `REQUIREMENTS.md` |  |  |
| 场景层 | 是否改变测试矩阵覆盖范围 | `SCENARIOS.yaml` / `TEST-MATRIX.md` |  |  |
| 计划层 | 是否改变 Phase、Wave、Story / 任务依赖 | `process/DEVELOPMENT-PLAN.yaml` |  |  |
| 安全层 | 是否引入新的高风险动作或权限要求 | 安全边界 / 审计结论 |  |  |
| 交付层 | 是否需要重新生成交付物或回归子集 | 交付文档 / 回归集 |  |  |

## 回退决策

- 影响范围：局部 / 全局
- 回退到阶段：`rollback_to`
- 需要重新确认的对象：

## 产品基线重整门禁

> 需求 / 场景 / 范围类 CR 只作为审计外壳，不替代产品发现、需求澄清、HLD 或 Story 拆分。CP2 未通过前不得进入 Story 拆解、LLD 设计批次或实现。

- 是否需要产品基线重整：`product_baseline_refresh_required`
- 必须回到阶段：`required_phase`
- 责任 Agent：`required_agent`
- 必须通过门禁：`required_gate`
- Story / LLD / 实现阻断条件：`block_story_decomposition_until`
- 受影响产品文档：`affected_product_docs`
- 受影响 use case：`affected_use_cases`
- 分流设计引用：`routing_design_ref`

| 分流类型 | 适用条件 | 默认路径 | CR 拆分策略 |
|---|---|---|---|
| 大块集中需求 / 目标包 | 同一目标下多个需求点，影响多个 use case / feature / story，或需要 HLD / 多 Story 才能交付 | parent CR / Change Package -> requirement-clarification -> CP2 -> solution-design -> CP3 -> story-planning | 默认不逐条拆 CR；普通开发工作拆 Story |
| 单点产品变更 | 只影响一个明确需求或局部行为，验收边界清晰，风险和授权边界单一 | 单个 CR + 必要的增量 CP2 | 不拆多个 CR |
| 零散后续事项 | 来自 CP8 / feedback / deferred idea，尚未决定推进 | follow-up tracking，用户启动后再冲突预检 | 不预创建正式 CR |
| 运行授权 / 安全接受 | 涉及凭据、真实运行、生产写入、publish、live / trading 或风险接受 | 独立 runtime_authorization / security 决策项 | 不混入普通产品 CR |

## fast-lane 判定

| 条件 | 是否命中 | 说明 |
|---|---|---|
| 仅低风险轻量实现 / 文档 / 规则修改 | true / false |  |
| 修改架构、权限、安全边界或平台安装路径 | true / false | 命中则升级 standard |
| 修改外部接口契约、文件所有权或多 Story 依赖 | true / false | 命中则升级 standard |
| 需要 HLD / LLD 才能解释影响 | true / false | 命中则升级 standard |
| 是否保持 fast-lane | true / false |  |

## LLD 设计批次门禁

> 若本 CR 影响 Story、LLD、接口契约、文件所有权、`dev_gate` 或实现设计，必须填写本节。批次内全部 full-lld / technical-note / waived 证据和 CP5 自动预检完成并统一人工确认前，不得实施任何 Story。

- 是否需要 LLD 设计批次：true / false
- batch_id：`CR-{id}-LLD-BATCH`
- 批次范围来源：CR 影响分析 / 人工指定
- 批次内 Story：
  - `STORY-*`
- 批次人工确认稿：`process/checkpoints/CP5-{batch_id}-LLD-BATCH.md`
- 开发启动条件：
  - [ ] 批次内全部 Story 设计证据已输出（full-lld / technical-note / waived）
  - [ ] 批次内全部 Story CP5 自动预检已通过
  - [ ] 批次 CP5 人工确认结论为 `approved`
  - [ ] 批次内每个 Story 的 `dev_gate` 已满足

## 执行链路

> CR 创建时必须先写明串行依赖、责任角色、门控和恢复点。`host-orchestrator` 负责分派与收敛；功能 Agent 只处理自身职责，不关闭 CR、不推进 `delivered`。

| 顺序 | 责任角色 | 动作 | 输入 | 输出 | 门控 | 完成后下一步 |
|---|---|---|---|---|---|---|
| 1 | `host-orchestrator` | 创建 CR 并分派 | 用户请求 / ISSUE / RUN-EXEC | 本 CR、handoff、调度证据 | CR 已登记 | 等待下游完成 |
| 2 | `meta-dev` | 完成 LLD 设计批次或实施变更 | CR、handoff、相关 Story / 文件 | 批次内 LLD、代码、目录或交付产物变更 | 若影响 Story / LLD / 实现设计：先通过批次 CP5；否则进入 CP6 / 对应验证证据 | 交回 `host-orchestrator` |
| 3 | `meta-doc` | 刷新文档 | CR、当前交付物、变更结果 | README / USER-MANUAL / 文档更新 | 文档自检 | 交回 `host-orchestrator` |
| 4 | `host-orchestrator` | 收敛终验 | 下游结果、CR、检查点 | CP8 自动预检与人工审查稿 | 等待用户确认或有效预授权 | 写入 `pending_user_decision` |
| 5 | `host-orchestrator` | 回填确认并关闭 CR | 用户确认或有效预授权 | CR closed、STATE 更新 | CP8 approved | 推进 `delivered` 或下一阶段 |

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

## 后续事项台账

> CP8 或 CR 收敛时若产生后续事项，只维护台账，不预创建尚未启动的正式 CR 文件。用户决定推进某一项后，再创建正式 CR，并把本节或独立台账中的状态改为 `active`。
> 本节必须同步 `process/changes/CR-INDEX.yaml|json` 与 `process/state/CR-LEDGER.ndjson`，不能只写 Markdown 台账。

- 是否存在后续事项：false
- 台账路径：`process/changes/CR-{id}-FOLLOW-UP-TRACKING-YYYY-MM-DD.md`
- CR 索引路径：`process/changes/CR-INDEX.yaml`
- 一致性检查：`meta-flow check cr-tracking --project-root .`
- 旧状态取值：`candidate` / `active` / `blocked` / `spike_candidate` / `converted-to-spike` / `closed` / `cancelled` / `superseded`
- 新状态字段：`lifecycle_status` / `readiness_status` / `gate_status`

| 候选编号 | 标题 | 状态 | 类型 | 优先级 | 正式 CR 路径 | 相关 active CR / blocked_by / superseded_by | 当前门控 | 阻塞原因 | 下一步 |
|---|---|---|---|---:|---|---|---|---|---|
| FU-CR{id}-001 |  | candidate | CR / Spike | 1 |  |  | 未启动 |  | 等待用户选择是否推进 |

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
