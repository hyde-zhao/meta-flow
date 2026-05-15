---
name: state-router
description: >-
  当需要推进工作流状态、回退到上一阶段、查询当前进度、或判断下一步应调用哪个 Agent 时使用。
  触发词包括：推进、下一步、当前状态、回退、状态查询、继续。
  适用场景：元工作流全流程的状态管理。
argument-hint: "可选：指定目标阶段、查询字段或回退原因"
user-invokable: true
status: active
---

## 目标

读取并更新 `process/STATE.md`，根据当前阶段的退出条件判断是否可推进、是否需要回退、下一步应唤醒哪个 Agent，并保持状态机与 `skills/state-router/templates/STATE-TEMPLATE.md` 一致。

## 适用场景

- 元工作流阶段推进、阶段回退、状态查询
- `meta-po` 在每个阶段完成后进行退出条件判定
- Story 执行阶段内的 LLD 队列、开发队列、验证队列和依赖门控判断
- CP0-CP8 检查点状态、自动检查结果路径和人工审查结果路径维护

## 前置条件

- [ ] `process/STATE.md` 已存在，或允许由 `skills/state-router/templates/STATE-TEMPLATE.md` 初始化
- [ ] 当前阶段相关产物的存在性和确认状态可被检查

## 必须读取的输入

- `process/STATE.md`（若已存在）
- `skills/state-router/templates/STATE-TEMPLATE.md`
- `skills/checkpoint-manager/SKILL.md`
- 与当前阶段直接相关的上游文档：
  - `REQUEST.md`
  - `USE-CASES.md`
  - `REQUIREMENTS.md`
  - `HLD.md`
  - `ARCHITECTURE-DECISION.md`
  - `STORY-BACKLOG.md`
  - `DEVELOPMENT-PLAN.yaml`
  - `TEST-STRATEGY.md`
  - `README.md`
  - `USER-MANUAL.md`
- Story 执行阶段需要读取 `process/stories/STORY-*.md`、`process/stories/STORY-*-LLD.md` 与 `process/STORY-STATUS.md`

## 知识来源

- `skills/state-router/templates/STATE-TEMPLATE.md`：状态对象结构与阶段机基线
- `AGENTS.md` / `rules/AGENTS.md`：阶段定义、人工检查点与角色职责
- 各阶段产物 frontmatter 与文件存在性：退出条件的事实来源

## 执行步骤

### 1. 初始化或读取状态

1. 若 `process/STATE.md` 不存在，则以 `skills/state-router/templates/STATE-TEMPLATE.md` 初始化。
2. 读取 `current_phase`、`current_agent`、`blocked`、`active_change`、`agent_lifecycle`、`checkpoints`、`parallel_execution`、`history`。
3. 若 `blocked=true`，先返回阻塞原因，不允许静默推进。
4. 若旧 `STATE.md` 的 `checkpoints` 仍是“需求/HLD/Story/终验”旧布尔结构，必须先迁移为 CP0-CP8 结构；迁移动作写入 `history`，不得把旧布尔值当作新检查点已通过。
5. 若 `agent_lifecycle.platform_capabilities.subagent_dispatch` 缺失，必须先补齐并将 `available=false`、`method=unverified` 写入状态；能力未探测前，不得把需要功能 Agent 的任务标记为 `completed`。

### 2. 按阶段检查退出条件

| 当前阶段 | 退出条件 | 下一阶段 | 默认唤醒 Agent |
|---|---|---|---|
| `init` | `process/checks/CP0-REQUEST-INTAKE.md` 结论为 `PASS` 或 `WAIVED` | `requirement-clarification` | `meta-pm` |
| `requirement-clarification` | CP1 自动检查通过，CP2 自动预检通过且 `checkpoints/CP2-REQUIREMENTS-BASELINE.md` 人工结论为 `approved` | `solution-design` | `meta-se` |
| `solution-design` | CP3 自动预检通过且 `checkpoints/CP3-HLD-REVIEW.md` 人工结论为 `approved` | `story-planning` | `meta-se` |
| `story-planning` | CP4 自动预检通过且 `checkpoints/CP4-STORY-PLAN-REVIEW.md` 人工结论为 `approved` | `story-execution` | `meta-dev` |
| `story-execution` | 当前 DAG 中每个目标 Story 均通过 CP5、CP6、CP7，并到达 `verified`，且 CP6/CP7 包含 Agent Dispatch Evidence | 下一调度批次或 `documentation` | `meta-dev` / `meta-qa` / `meta-doc` |
| `documentation` | CP8 自动预检通过且 `checkpoints/CP8-DELIVERY-READINESS.md` 人工结论为 `approved` | `delivered` | `meta-po` |
| `delivered` | 只读归档 | — | — |

推进时只允许读取检查点结果文件和 `STATE.md.checkpoints` 的同步状态；若两者冲突，以检查点结果文件为准，并把冲突写入 `history`。

### 3. 处理回退

1. 记录回退原因与目标阶段。
2. 将回退动作写入 `history`。
3. 只回退到最近仍可恢复的稳定阶段，不跨越未收敛变更单。

### 4. 回写状态

1. 更新 `current_phase`、`current_agent`、`last_action`、`next_action`、`last_updated`。
2. 推进或回退时追加 `history` 记录。
3. 同步 `checkpoints.<cp_id>.status`、`last_result`、`auto_result`、`manual_review` 或滚动 `results[]`。
4. 查询状态时不改变业务内容，但允许刷新 `next_action`。

### 4.1 检查点结果同步

每次推进前必须按 `checkpoint-manager` 契约读取检查点结果：

| 检查点 | 必读文件 | 通过条件 |
|---|---|---|
| CP0 | `process/checks/CP0-REQUEST-INTAKE.md` | 结论为 `PASS` 或 `WAIVED` |
| CP1 | `process/checks/CP1-USE-CASE-COMPLETENESS.md` | 结论为 `PASS` 或 `WAIVED` |
| CP2 | `process/checks/CP2-REQUIREMENTS-BASELINE.md` + `checkpoints/CP2-REQUIREMENTS-BASELINE.md` | 自动预检通过且人工结论 `approved` |
| CP3 | `process/checks/CP3-HLD-CONSISTENCY.md` + `checkpoints/CP3-HLD-REVIEW.md` | 自动预检通过且人工结论 `approved` |
| CP4 | `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md` + `checkpoints/CP4-STORY-PLAN-REVIEW.md` | 自动预检通过且人工结论 `approved` |
| CP5 | `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md` + `checkpoints/CP5-{story_id}-{story_slug}-LLD.md` | 当前 Story 自动预检通过且人工结论 `approved` |
| CP6 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` | 当前 Story 结论为 `PASS` 或 `WAIVED`，且 meta-dev 调度证据通过 |
| CP7 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` | 当前 Story 结论为 `PASS` 或 `WAIVED`，且 meta-qa 调度证据通过 |
| CP8 | `process/checks/CP8-DELIVERY-READINESS.md` + `checkpoints/CP8-DELIVERY-READINESS.md` | 自动预检通过且人工结论 `approved` |

人工检查点文件缺失、未填“人工审查结果”或结论不是 `approved` 时，不得推进。

### 5. Story 并行调度队列

story-execution 阶段必须维护 `parallel_execution`：

1. `lld_ready`：Story 边界稳定、HLD/ADR 已确认、LLD 输入满足且没有 LLD confirmed=true。
2. `lld_running`：正在写 LLD 的 Story，数量不得超过 `max_parallel_lld`。
3. `lld_review`：LLD 已输出，等待单 Story 或小批次确认。
4. `dev_ready`：LLD confirmed=true，`dev_gate` 满足，且 `file_ownership.primary` 不与 `dev_running` 冲突。
5. `dev_running`：正在实现的 Story，数量不得超过 `max_parallel_dev`。
6. `verify_ready`：开发完成并进入 `ready-for-verification` 的 Story。
7. `verify_running`：正在验证的 Story，数量不得超过 `max_parallel_qa`。
8. `blocked_by_dependency`：依赖类型、上游状态或文件所有权阻塞的 Story，必须写明 `blocked_by`、`dependency_type`、`required_status` 或 `conflict_files`。

依赖门控规则：

| 依赖类型 | LLD 队列规则 | 开发队列规则 |
|---|---|---|
| `contract` | 上游接口在 Story 或 LLD 中声明即可进入 LLD | 上游接口冻结且当前 LLD confirmed=true |
| `runtime` | 可进入 LLD，但必须记录运行时风险 | 默认要求上游 `verified` |
| `file-conflict` | 可进入 LLD，但必须记录合并顺序 | 不得与冲突 Story 并行开发 |

### 6. Agent 生命周期登记

Codex 多 agent 模式下，state-router 必须维护 `agent_lifecycle.active_agents`：

1. 新 agent 启动前，按 `role + workflow_id + change_id + story_id + wave_id` 精确查找可复用线程。
2. 命中可复用线程时返回 resume / send_input 建议，不允许重复 spawn。
3. 人工检查点通过、Story LLD 确认完成、实现交接验证、验证报告交付或文档终验完成后，标记对应线程 `status=closing` 并提示 meta-po close。
4. `meta-po` 角色始终单例；若发现 2 个活动 `meta-po`，必须阻断推进并要求人工选择保留线程。
5. `active_agents` 失活或用户手动关闭时，必须在 `history` 记录重建原因，不能静默生成新线程。
6. 若旧 `STATE.md` 缺少 `agent_lifecycle`，必须先按模板补齐结构；补齐本身不代表允许新建 `meta-po`，仍需确认当前 UI 中没有其他活动 `meta-po`。

`active_agents[]` 中每条记录必须使用以下字段。平台没有提供的字段可以为空，但 `completed` 状态必须满足证据规则。

| 字段 | 说明 |
|---|---|
| `role` | 目标功能 Agent，例如 `meta-dev`、`meta-qa` |
| `agent_id` | 平台返回的子 agent 标识；Codex `spawn_agent` 返回值优先写入这里 |
| `agent_name` | 平台返回的昵称或任务名 |
| `thread_id` | 可恢复线程标识；平台无独立 thread 时可与 `agent_id` 相同 |
| `workflow_id` / `change_id` / `story_id` / `wave_id` | 精确复用键 |
| `handoff_path` | 对应 `process/handoffs/*.md` |
| `status` | `handoff-created`、`spawn-requested`、`running`、`completed`、`failed`、`unavailable`、`blocked`、`closing`、`closed` |
| `evidence` | `spawn_agent`、`resume_agent`、`send_input`、`platform-task` 或 `user-approved-inline-fallback` |
| `tool_name` | 实际调用的平台工具名 |
| `spawned_at` / `resumed_at` / `last_seen_at` / `completed_at` / `closed_at` | 生命周期时间 |
| `reusable` | 是否允许同 key 继续复用 |
| `fallback_reason` | 仅 `inline-fallback` 使用，必须写明用户批准原因 |

完成证据规则：

1. `status=completed` 且 `evidence` 为 `spawn_agent` / `resume_agent` / `send_input` / `platform-task` 时，`agent_id` 或 `thread_id` 必须非空，`tool_name` 必须非空，`completed_at` 必须非空。
2. `status=completed` 且 `evidence=user-approved-inline-fallback` 时，必须存在 `fallback_reason`，并在对应 handoff 的 `dispatch.mode` 中写明 `inline-fallback`。
3. 只有 `handoff_path` 或 `to_agent`，但缺少上述证据时，只能标记为 `handoff-created`、`blocked` 或 `unavailable`，不得标记为 `completed`。
4. CP6 / CP7 推进前必须交叉检查 `STATE.md.agent_lifecycle.active_agents` 与对应 handoff frontmatter；任一方缺失证据时，检查点必须失败。

## 输出文件 / 输出模板

| 对象 | 路径 | 用途 |
|---|---|---|
| 运行时状态 | `process/STATE.md` | 当前状态机实例 |
| 状态模板 | `skills/state-router/templates/STATE-TEMPLATE.md` | 初始化与结构基线 |
| 自动检查结果 | `process/checks/CP*.md` | 自动检查点和自动预检证据 |
| 人工审查稿 | `checkpoints/CP*.md` | 人工检查点 checklist 与审查结果 |

## 约束

- 只负责状态判断、推进决策与状态回写，不生成需求/设计/实现内容
- 推进前必须验证当前阶段退出条件，不能用“默认通过”代替检查
- 推进前必须验证对应 CP 结果文件；不能只看文档 frontmatter 的 `confirmed=true`
- 回退必须记录原因、发起方和目标阶段
- Agent 复用必须使用 exact key，不得用模糊角色名匹配替代
- 并行队列必须由 Story DAG、依赖类型和文件所有权计算，不得只按 Wave 名称粗略并行
- 仅使用当前 `process/STATE.md` 与 `skills/state-router/templates/STATE-TEMPLATE.md` 契约

## 验收标准

- [ ] `STATE.md` 的阶段与下一步动作与实际产物状态一致
- [ ] 初始化时结构与 `skills/state-router/templates/STATE-TEMPLATE.md` 一致
- [ ] `STATE.md.checkpoints` 与 `process/checks/CP*.md`、`checkpoints/CP*.md` 的结论一致
- [ ] 推进 / 回退操作均追加 `history`
- [ ] 同一任务同角色不会重复登记活动 agent，检查点完成后有关闭动作
- [ ] `lld_ready` / `dev_ready` / `verify_ready` 的每个 Story 均能解释依赖和文件所有权依据
- [ ] 阻塞状态下返回明确阻塞原因

## 不适用边界

- 任务要求生成需求、设计、代码或文档本体
- 当前请求仅需要查看某个单独文件内容，不涉及状态推进

## Gotchas

- `story-execution` 是阶段状态，不替代单个 Story 的生命周期；Story 状态仍以 `story-manager` 维护的卡片为准
- LLD 可以提前并行写，但开发不能绕过 `dev_gate`；特别是 `runtime` 依赖默认等上游 `verified`
- 同一 Wave 内也可能因文件冲突串行；不同 Wave 的 Story 若依赖和文件所有权满足，也可以提前写 LLD
- 当存在活跃 `CR-*` 时，应优先收敛变更影响，再判断是否允许推进
- 首次初始化时只允许从 `skills/state-router/templates/STATE-TEMPLATE.md` 复制，不允许凭空脑补字段
- 自动检查点失败时，不要发起人工确认；先把失败结果写入 `process/checks/CP*.md` 并路由给责任 agent 修复
