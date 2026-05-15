---
name: checkpoint-manager
description: >-
  当需要创建、执行、记录或审查 meta-flow 的 CP0-CP8 检查点时使用。
  每个检查点都必须包含 Entry Criteria、Checklist、Exit Criteria、Deliverables；
  自动检查点必须写检查结果，人工检查点必须生成可填写的人工审查稿。
argument-hint: "checkpoint_id、目标阶段、Story ID 或检查对象路径"
user-invokable: true
status: active
---

# checkpoint-manager

## 目标

为 meta-flow 提供统一检查点契约，覆盖：

- 自动检查点：执行检查并写入检查结果。
- 自动预检 + 人工检查点：先写自动预检结果，再生成供用户审查的 checklist 文件。
- Story 级滚动检查点：按 Story 独立记录 LLD、编码完成和验证完成结果。

所有检查点必须采用 IPD 风格的四段结构：

1. Entry Criteria
2. Checklist
3. Exit Criteria
4. Deliverables

## 文件路径约定

| 类型 | 路径 | 说明 |
|---|---|---|
| 自动检查结果 | `process/checks/CP{n}-{slug}.md` | 由 agent 填写，必须包含逐项 PASS / FAIL / N/A / WAIVED |
| 人工审查稿 | `checkpoints/CP{n}-{slug}.md` | 由 meta-po 发起，必须包含 checklist、自动预检摘要、人工审查结果区 |
| Story LLD 人工审查稿 | `checkpoints/CP5-{story_id}-{story_slug}-LLD.md` | 单 Story 或小批次滚动确认 |
| Story 编码完成结果 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` | meta-dev 自检结果，必须包含 Agent Dispatch Evidence |
| Story 验证完成结果 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` | meta-qa 验证结果，必须包含 Agent Dispatch Evidence |

`process/checks/` 属于运行态检查证据；`checkpoints/` 属于人工确认态文件。人工审查时，meta-po 必须在用户提示中给出具体 `checkpoints/...` 路径。

## 结果状态

检查项状态只允许使用：

| 状态 | 含义 |
|---|---|
| `PASS` | 检查通过，证据充分 |
| `FAIL` | 检查失败，必须说明阻断原因 |
| `N/A` | 当前对象不适用，必须说明理由 |
| `WAIVED` | 已知未完全满足，但经人工接受风险，必须写明接受人和原因 |

检查点结论只允许使用：

| 结论 | 含义 |
|---|---|
| `PASS` | 满足出口条件，可推进 |
| `FAIL` | 不满足出口条件，不可推进 |
| `BLOCKED` | 缺少输入或存在阻断，需回退或补充 |
| `WAIVED` | 人工接受风险后放行 |

自动检查点存在任一 `FAIL` 且未被 `WAIVED` 时，结论必须为 `FAIL` 或 `BLOCKED`，不得进入人工确认。

## 通用检查结果模板

自动检查结果文件必须使用以下结构：

```markdown
---
checkpoint_id: "CP{n}"
checkpoint_name: ""
type: "auto | auto_precheck | rolling_auto"
status: "PASS | FAIL | BLOCKED | WAIVED"
owner: ""
created_at: ""
checked_at: ""
target:
  phase: ""
  story_id: ""
  artifacts: []
manual_checkpoint: ""
---

# CP{n} {检查点名称} 检查结果

## Entry Criteria

| 条目 | 状态 | 证据 | 说明 |
|---|---|---|---|
|  | PASS |  |  |

## Checklist

| # | 检查项 | 状态 | 证据 | 处理意见 |
|---|---|---|---|---|
| 1 |  | PASS |  |  |

## Exit Criteria

| 条目 | 状态 | 证据 | 说明 |
|---|---|---|---|
|  | PASS |  |  |

## Deliverables

| 交付物 | 路径 | 状态 | 说明 |
|---|---|---|---|
|  |  | PASS |  |

## 结论

- 结论：`PASS | FAIL | BLOCKED | WAIVED`
- 阻断项：
- 豁免项：
- 下一步：
```

## 通用人工审查稿模板

人工检查点必须使用以下结构：

```markdown
---
checkpoint_id: "CP{n}"
checkpoint_name: ""
type: "manual | auto_then_manual | rolling_auto_then_manual"
status: "pending | approved | changes_requested | rejected"
owner: "meta-po"
created_at: ""
reviewed_by: ""
reviewed_at: ""
auto_check_result: ""
target:
  phase: ""
  story_id: ""
  artifacts: []
---

# CP{n} {检查点名称} 人工审查

## 自动预检摘要

| 预检文件 | 结论 | 阻断项 | 说明 |
|---|---|---|---|
| `process/checks/...` | PASS | 0 |  |

## Entry Criteria

| 条目 | 状态 | 证据 | 审查意见 |
|---|---|---|---|
|  | 待审查 |  |  |

## Checklist

| # | 检查项 | 审查结果 | 证据 | 审查意见 |
|---|---|---|---|---|
| 1 |  | 待审查 |  |  |

## Exit Criteria

| 条目 | 审查结果 | 证据 | 审查意见 |
|---|---|---|---|
|  | 待审查 |  |  |

## Deliverables

| 交付物 | 路径 | 审查结果 | 审查意见 |
|---|---|---|---|
|  |  | 待审查 |  |

## 人工审查结果

- 结论：`approved | changes_requested | rejected`
- 审查人：
- 审查时间：
- 修改意见：
- 风险接受项：
```

meta-po 发起人工检查时必须提示：

```text
请审查：checkpoints/CP{n}-{slug}.md
该文件包含本检查点的 Entry Criteria、Checklist、Exit Criteria、Deliverables 和自动预检摘要。
审查后请在“人工审查结果”中填写结论，也可以直接回复：
1/approve/通过，2/修改: <具体修改点>，3/reject/不通过。
```

## CP0 原始请求受理门

- 类型：自动
- 结果文件：`process/checks/CP0-REQUEST-INTAKE.md`
- 责任方：meta-po
- 阶段：`init -> requirement-clarification`

### Entry Criteria

| 条目 | 说明 |
|---|---|
| 原始请求存在 | 用户已有明确任务、变更请求或 `.input/` 输入 |
| 工作目录可写 | `process/`、`checkpoints/` 可创建 |
| 编排器单例可判定 | Codex 下未发现多个活动 meta-po |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 请求已记录 | `process/REQUEST.md` 包含原始用户目标和约束 |
| 2 | 目标对象明确 | 区分新工作流、修改 meta-flow 本身、外部 production 交付 |
| 3 | engagement mode 明确 | `production` 或 `meta-self-dev` 已设置 |
| 4 | 输出位置明确 | 运行态、确认态、交付态路径可判定 |
| 5 | 干系人或决策人明确 | 至少能判定谁负责人工确认 |
| 6 | 初始优先级明确 | Must / Should / Could 或等价优先级已记录 |
| 7 | 明显冲突已暴露 | 与现有规则冲突的内容已登记为开放问题 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 初始化完成 | `STATE.md`、`REQUEST.md`、`INPUT-INDEX.md` 已就绪 |
| 无阻断开放问题 | 不存在阻止进入场景发现的 BLOCKING 项 |

### Deliverables

- `process/REQUEST.md`
- `process/STATE.md`
- `process/INPUT-INDEX.md`
- `process/checks/CP0-REQUEST-INTAKE.md`

## CP1 用户场景完备门

- 类型：自动
- 结果文件：`process/checks/CP1-USE-CASE-COMPLETENESS.md`
- 责任方：meta-pm
- 阶段：`requirement-clarification`

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP0 通过 | 原始请求已结构化 |
| 场景主体明确 | `scenario_subject_type` 与 `scenario_subject_id` 已判定或有待确认状态 |
| 初步范围明确 | Scope / Out of Scope 有初稿 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 用户角色完整 | 覆盖主要使用者、维护者、审批者或调用方 |
| 2 | 正向场景完整 | Happy Path 从触发到结束闭环 |
| 3 | 异常场景覆盖 | 错误输入、依赖失败、权限不足、超时、回退 |
| 4 | 边界场景覆盖 | 空数据、重复执行、并发、历史兼容、部分失败 |
| 5 | 场景可验证 | 每个关键场景可转为验收标准或测试用例 |
| 6 | 非功能场景存在 | 性能、安全、可靠性、可维护性、可观测性 |
| 7 | 场景优先级明确 | P0/P1/P2 或 MoSCoW 已记录 |
| 8 | 原始需求可追溯 | 场景能追溯到原始请求或变更来源 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| P0 场景无缺失 | 关键用户旅程和异常路径已覆盖 |
| 开放问题有状态 | OPEN / RESOLVED / DEFERRED 均有 owner 或处理计划 |

### Deliverables

- `process/USE-CASES.md`
- `process/CLARIFICATION-LOG.md`
- `process/checks/CP1-USE-CASE-COMPLETENESS.md`

## CP2 需求基线门

- 类型：自动预检 + 人工
- 自动结果文件：`process/checks/CP2-REQUIREMENTS-BASELINE.md`
- 人工审查稿：`checkpoints/CP2-REQUIREMENTS-BASELINE.md`
- 责任方：meta-pm / meta-po

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP1 通过 | 用户场景已形成可追溯基线 |
| 需求草案存在 | `REQUIREMENTS.md` 已生成 |
| 非功能需求有初稿 | 性能、安全、可靠性、兼容性等已列出 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 功能需求完整 | P0/P1 场景均有对应需求 |
| 2 | 非功能需求量化 | NFR 有可检验目标值或明确不适用理由 |
| 3 | 范围清晰 | Scope / Out of Scope 明确 |
| 4 | 验收标准明确 | 每条 P0/P1 需求有 AC |
| 5 | 约束条件记录 | 技术、合规、资源、平台、兼容性约束已记录 |
| 6 | 依赖和风险识别 | 外部依赖、未知技术点、交付风险已登记 |
| 7 | 需求无冲突 | 冲突已解决或有决策记录 |
| 8 | 变更机制明确 | 基线后修改必须走 CR |
| 9 | 追溯矩阵建立 | 原始请求 -> 场景 -> 需求 可追溯 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| P0/P1 需求通过 | 致命问题 = 0，阻塞问题 = 0 |
| 人工确认完成 | `checkpoints/CP2-REQUIREMENTS-BASELINE.md` 结论为 approved |

### Deliverables

- `process/REQUIREMENTS.md`
- `process/checks/CP2-REQUIREMENTS-BASELINE.md`
- `checkpoints/CP2-REQUIREMENTS-BASELINE.md`

## CP3 HLD 架构评审门

- 类型：自动预检 + 人工
- 自动结果文件：`process/checks/CP3-HLD-CONSISTENCY.md`
- 人工审查稿：`checkpoints/CP3-HLD-REVIEW.md`
- 责任方：meta-se / meta-po

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP2 通过 | 需求基线已确认 |
| HLD 草案存在 | `process/HLD.md` 已生成 |
| ADR 候选可读 | 关键决策点已在 HLD 或 ADR 草案中说明 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 需求覆盖 | 所有 P0/P1 需求在架构中有对应设计 |
| 2 | 模块边界清晰 | 职责高内聚、低耦合 |
| 3 | 接口方向明确 | 调用方向、输入输出、错误处理清晰 |
| 4 | 数据流清晰 | 核心数据流、状态流、持久化策略清楚 |
| 5 | ADR 完整 | 关键决策有理由、备选方案和取舍依据 |
| 6 | 风险有缓解 | 技术、依赖、性能风险有应对方案 |
| 7 | NFR 已落地 | 性能、安全、可靠性、可观测性有设计承载 |
| 8 | 失败路径明确 | 超时、失败、回滚、降级、重试策略明确 |
| 9 | 可测试性明确 | 架构支持单测、集成测试、回归测试 |
| 10 | 内部一致 | HLD、ADR、Risk Matrix、NFR 不自相矛盾 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 自动预检通过 | 无未豁免 FAIL |
| 人工确认完成 | HLD 可作为 Story 拆解输入 |

### Deliverables

- `process/HLD.md`
- `process/ARCHITECTURE-DECISION.md` 或 HLD 中 ADR 候选
- `process/checks/CP3-HLD-CONSISTENCY.md`
- `checkpoints/CP3-HLD-REVIEW.md`

## CP4 Story 拆解与并行安全门

- 类型：自动预检 + 人工
- 自动结果文件：`process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md`
- 人工审查稿：`checkpoints/CP4-STORY-PLAN-REVIEW.md`
- 责任方：meta-se / meta-po

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP3 通过 | HLD 已确认 |
| Story 计划存在 | `STORY-BACKLOG.md`、`DEVELOPMENT-PLAN.yaml` 和 Story 卡片已生成 |
| 依赖信息存在 | `depends_on`、依赖类型和文件所有权已填写 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | Story 覆盖需求 | 每条 P0/P1 需求有 Story 覆盖 |
| 2 | Story 粒度合理 | 单 Story 可独立确认、开发、验证 |
| 3 | AC 明确 | 每个 Story 有可验证验收标准 |
| 4 | INVEST 基本满足 | 独立、可协商、有价值、可估算、小、可测试 |
| 5 | 依赖关系完整 | `depends_on` 标清上游 Story |
| 6 | 依赖类型明确 | `contract` / `runtime` / `file-conflict` |
| 7 | DAG 无环 | 依赖图不能出现循环 |
| 8 | 关键路径识别 | 长链路依赖和阻塞点已标记 |
| 9 | 文件所有权明确 | `primary`、`shared`、`merge_owner`、`forbidden` |
| 10 | 并行计划合理 | `lld_ready` / `dev_ready` 可解释 |
| 11 | Wave 不是硬门 | Wave 只作为调度分组，实际以 DAG 和 gate 为准 |
| 12 | QA 策略同步 | Story 如何验证、哪些可并行验证已说明 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| DAG 校验通过 | 无循环依赖 |
| 文件冲突可控 | 未处理冲突 = 0 |
| 首批队列可计算 | `lld_ready` 可解释 |
| 人工确认完成 | Story 边界和并行计划被批准 |

### Deliverables

- `process/STORY-BACKLOG.md`
- `process/DEVELOPMENT-PLAN.yaml`
- `process/stories/STORY-*.md`
- `process/stories/STORY-STATUS.md`
- `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md`
- `checkpoints/CP4-STORY-PLAN-REVIEW.md`

## CP5 Story LLD 可实现性门

- 类型：滚动自动预检 + 滚动人工
- 自动结果文件：`process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`
- 人工审查稿：`checkpoints/CP5-{story_id}-{story_slug}-LLD.md`
- 责任方：meta-dev / meta-po

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP4 通过 | Story 拆解与并行计划已确认 |
| Story 处于 LLD 审查态 | 状态为 `lld-ready-for-review` |
| LLD 已生成 | `STORY-{id}-{story_slug}-LLD.md` 存在 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | LLD 覆盖 AC | 每条验收标准有实现设计 |
| 2 | 与 HLD 一致 | 不违背 HLD / ADR |
| 3 | 文件影响范围明确 | 新增、修改、删除文件写清楚 |
| 4 | 接口契约完整 | 输入、输出、错误码、超时、兼容性 |
| 5 | 数据结构明确 | schema、字段、状态、迁移、默认值 |
| 6 | 控制流明确 | 主流程、异常流程、回退流程 |
| 7 | 依赖输入明确 | 上游 contract/runtime 依赖满足条件清楚 |
| 8 | 并发和一致性考虑 | 竞态、重复执行、事务、幂等已说明 |
| 9 | 安全设计明确 | 权限、输入校验、敏感信息、审计 |
| 10 | 可测试性明确 | 单测点、集成点、Mock 点、验证命令 |
| 11 | dev_gate 可计算 | `lld_confirmed`、`dependencies_satisfied`、`file_conflict_free` 可判定 |
| 12 | 偏差记录机制明确 | 实现偏离 LLD 时必须记录原因和影响 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 自动预检通过 | LLD 可实现性检查无阻断项 |
| 人工确认完成 | Story LLD 被批准 |
| dev_gate 可更新 | Story 可进入 `lld-approved`，满足时进入 `dev_ready` |

### Deliverables

- `process/stories/STORY-{id}-{story_slug}-LLD.md`
- `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`
- `checkpoints/CP5-{story_id}-{story_slug}-LLD.md`
- 更新后的 `process/stories/STORY-STATUS.md`

## CP6 Story 编码完成门

- 类型：滚动自动
- 结果文件：`process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md`
- 责任方：meta-dev

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP5 通过 | Story LLD 已确认 |
| dev_gate 满足 | 依赖和文件所有权允许开发 |
| 实现完成 | Story 任务清单已执行完 |
| meta-dev 调度证据存在 | `STATE.md.agent_lifecycle` 与 handoff `dispatch` 证明 meta-dev 已由子 agent 执行，或存在用户批准的 inline fallback |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | AC 全部实现 | Story 验收标准无遗漏 |
| 2 | 与 LLD 一致 | 偏离 LLD 的地方有记录和理由 |
| 3 | 文件边界合规 | 未越过 `file_ownership.forbidden`，未抢占其他 Story primary 文件 |
| 4 | 代码规范通过 | lint、format、类型检查或项目等价命令通过 |
| 5 | 单元测试通过 | 核心逻辑、边界、异常路径覆盖 |
| 6 | 静态检查通过 | guardrail、安全扫描、静态检查按适用范围通过 |
| 7 | 自测完成 | 正向和主要异常场景已验证 |
| 8 | 文档同步 | README、接口文档、配置说明、变更说明必要时更新 |
| 9 | 状态回写 | Story 状态、任务清单、偏差记录已更新 |
| 10 | 无缓存产物 | `__pycache__`、构建缓存等不进入交付物 |
| 11 | Agent Dispatch Evidence | 存在 meta-dev 的 `agent_id` / `thread_id`、`tool_name`、`spawned_at` 或 `resumed_at`、`completed_at`；或存在用户批准的 `dispatch.mode=inline-fallback` |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 必要命令通过 | 验证命令有证据或 N/A 理由 |
| 无阻塞自查问题 | Story 可进入 `ready-for-verification` |
| 调度证据通过 | meta-dev 执行证据有效；仅 handoff-created 不可放行 |

### Deliverables

- 代码变更
- `DEV-LOG.md`
- `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md`
- 更新后的 Story 状态
- 对应 meta-dev handoff 的 `dispatch` 记录

## CP7 Story 验证完成门

- 类型：滚动自动
- 结果文件：`process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md`
- 责任方：meta-qa

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP6 通过 | Story 处于 `ready-for-verification` |
| 测试上下文可用 | 验证环境或等价验证方式可用 |
| 测试策略存在 | `TEST-STRATEGY.md` 已生成或明确 N/A |
| meta-qa 调度证据存在 | `STATE.md.agent_lifecycle` 与 handoff `dispatch` 证明 meta-qa 已由子 agent 执行，或存在用户批准的 inline fallback |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 功能测试通过 | Story AC 对应测试均通过 |
| 2 | 异常测试通过 | 失败、超时、权限、边界条件覆盖 |
| 3 | 回归影响评估 | 相关旧功能没有明显退化 |
| 4 | 集成验证完成 | contract/runtime 依赖相关集成点通过 |
| 5 | 非功能验证完成 | 性能、安全、可靠性按 Story 适用范围验证 |
| 6 | 缺陷闭环 | P0/P1 缺陷为 0，P2 有处理计划 |
| 7 | 测试证据完整 | 命令、日志、报告、截图或等价证据记录 |
| 8 | 追溯完整 | 需求、Story、LLD、代码、测试结果可串联 |
| 9 | Agent Dispatch Evidence | 存在 meta-qa 的 `agent_id` / `thread_id`、`tool_name`、`spawned_at` 或 `resumed_at`、`completed_at`；或存在用户批准的 `dispatch.mode=inline-fallback` |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 阻塞缺陷为 0 | P0/P1 缺陷 = 0 |
| 验证结论通过 | Story 可进入 `verified` |
| 调度证据通过 | meta-qa 执行证据有效；仅 handoff-created 不可放行 |

### Deliverables

- `VERIFICATION-REPORT.md`
- `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md`
- 缺陷记录或风险接受记录
- 更新后的 `STORY-STATUS.md`
- 对应 meta-qa handoff 的 `dispatch` 记录

## CP8 交付就绪门

- 类型：自动预检 + 人工
- 自动结果文件：`process/checks/CP8-DELIVERY-READINESS.md`
- 人工审查稿：`checkpoints/CP8-DELIVERY-READINESS.md`
- 责任方：meta-qa / meta-doc / meta-po

### Entry Criteria

| 条目 | 说明 |
|---|---|
| 目标 Story 已验证 | 所有目标 Story 处于 `verified` |
| 文档已生成 | README、USER-MANUAL 或等价文档完成 |
| 安装验证完成 | 适用平台的安装或 dry-run 已执行 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 需求闭环 | P0/P1 需求均有实现和验证证据 |
| 2 | Story 闭环 | 目标 Story 均 verified |
| 3 | 文档齐套 | README、USER-MANUAL、必要规则说明完成 |
| 4 | 安装验证通过 | Codex / Claude、project / user scope 按适用范围验证 |
| 5 | 平台规则一致 | AGENTS.md / CLAUDE.md 与实际交付内容一致 |
| 6 | 交付目录合规 | `delivery/agents`、`delivery/skills`、`delivery/rules`、`delivery/scripts` 边界正确 |
| 7 | 缓存和临时文件清理 | 无 `__pycache__`、临时构建产物 |
| 8 | guardrail 通过 | 当前仓库存在 guardrail 时必须通过 |
| 9 | 风险和遗留问题明确 | 遗留问题有状态、owner、后续计划 |
| 10 | 用户终验确认 | 用户明确 approve / 修改 / reject |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 自动预检通过 | 无未豁免 FAIL |
| 人工终验通过 | 用户确认 delivered |

### Deliverables

- `delivery/README.md`
- `delivery/doc/USER-MANUAL.md`
- `delivery/agents/*`
- `delivery/skills/*`
- `delivery/rules/*`
- `delivery/scripts/*`
- `process/checks/CP8-DELIVERY-READINESS.md`
- `checkpoints/CP8-DELIVERY-READINESS.md`

## 执行规则

1. 所有 CP 文件创建或更新后，必须回写 `process/STATE.md.checkpoints` 中的路径和结论。
2. 人工检查点的自动预检未 `PASS` 或 `WAIVED` 前，meta-po 不得发起人工确认。
3. 人工确认通过后，meta-po 必须把人工结论写回对应 `checkpoints/CP*.md` 的“人工审查结果”，并同步更新 `STATE.md`。
4. 如果用户直接在对话中回复 `1/approve/通过`，meta-po 也必须补写人工审查结果文件，不能只改状态。
5. `changes_requested` 必须路由给对应 agent 修订，并在重提时保留旧检查结果作为历史证据。
6. `rejected` 必须回退到检查点定义的目标阶段或 Story 状态。
7. CP6 / CP7 必须包含 `## Agent Dispatch Evidence` 小节；若缺少真实子 agent 证据且没有用户批准的 `inline-fallback`，结论只能是 `FAIL` 或 `BLOCKED`。

CP6 / CP7 的 `Agent Dispatch Evidence` 小节必须使用以下结构：

```markdown
## Agent Dispatch Evidence

| 检查项 | 状态 | 证据 | 说明 |
|---|---|---|---|
| 子 agent 调度模式 | PASS/FAIL/WAIVED | `process/handoffs/...` | `subagent` / `inline-fallback` / `handoff-only` |
| agent 标识 | PASS/FAIL/WAIVED | `STATE.md.agent_lifecycle` | `agent_id` 或 `thread_id` |
| 平台工具证据 | PASS/FAIL/WAIVED | `tool_name` | `spawn_agent` / `resume_agent` / `send_input` / platform task |
| 完成时间 | PASS/FAIL/WAIVED | `completed_at` | 子 agent 返回完成结果的时间 |
| inline fallback 授权 | N/A/WAIVED/FAIL | `approved_by`、`approved_at` | 仅 fallback 时允许 WAIVED |
```

## 验收标准

- [ ] CP0-CP8 均有 Entry Criteria、Checklist、Exit Criteria、Deliverables
- [ ] 自动检查点均生成 `process/checks/CP*.md` 结果文件
- [ ] 人工检查点均生成 `checkpoints/CP*.md` 审查稿
- [ ] meta-po 发起人工确认时明确提示 checklist 文件路径
- [ ] 人工审查后对应 `checkpoints/CP*.md` 已填入结论
- [ ] `STATE.md.checkpoints` 与检查文件状态一致
