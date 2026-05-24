---
name: context-handoff
description: >-
  当阶段切换时需要为下一个 Agent 装配最小必要上下文时使用。
  触发词包括：上下文交接、装配上下文、阶段切换、交接给。
  适用场景：Orchestrator 将控制权移交给下一个功能 Agent。
argument-hint: "目标 Agent 名称"
user-invokable: false
status: active
---

## 目标

根据目标 Agent 的职责，从工作区中筛选最小必要上下文，并明确哪些内容不应加载，确保交接简洁、不越权，并控制 Codex 子 agent token 消耗。

## 适用场景

- `meta-po` 向 `meta-pm` / `meta-se` / `meta-dev` / `meta-qa` / `meta-doc` 交接
- 阶段切换或 Story 执行中角色切换
- `requirement-clarification` / `solution-design` 启用阶段委托直连用户时，生成 `delegated-user-interaction` 语义的 handoff
- 并行 LLD 写作出现实现灰区时，生成或更新 `lld-clarification-broker` 语义的 broker handoff / queue 摘要

## 前置条件

- [ ] 目标 Agent 已明确
- [ ] `process/` 下相关输入文档已生成
- [ ] `process/STATE.md.agent_lifecycle.platform_capabilities.subagent_dispatch` 已完成探测或明确标记为 unavailable

## 必须读取的输入

- `process/STATE.md`
- 目标 Agent 对应阶段的正式对象
- 活跃 `CR-*` / 当前 Story 卡片（若存在）

## 知识来源

- `AGENTS.md`：角色职责与阶段定义
- `process/STATE.md`：当前阶段、当前 Wave、活跃变更
- 正式对象的文件路径与 frontmatter：决定是否需要加载

## 执行步骤

1. 识别目标 Agent 的职责边界。
2. 选择该 Agent 完成当前任务所需的最小文件集合。
3. 显式列出不应加载的历史草稿、中间推理和无关产物。
4. 若存在活跃变更单或当前 Story，补入对应上下文。
5. Codex 下默认 `fork_context=false`，只发送本 Skill 产出的上下文包；不得传递完整会话历史，只有并行收益明确且经 meta-po 记录理由时，才允许 fork。
6. 输出子 agent 复用键：`role + workflow_id + change_id + story_id + wave_id`，供 meta-po 查询 `STATE.md.agent_lifecycle.active_agents`。
7. 输出 handoff frontmatter 的 `semantic` 与 `dispatch` 区，区分 `stage-dispatch`、`delegated-user-interaction`、`lld-clarification-broker`、`handoff-created`、`agent_spawned` 和 `agent_completed`；handoff 文件不得自行声明目标 agent 已完成，除非已有平台调度证据。

## Handoff 语义

| semantic | 使用场景 | 交互权 | 收敛方式 |
|---|---|---|---|
| `stage-dispatch` | 普通阶段或 Story 任务交接 | 由 meta-po 继续对用户发起正式门控 | 目标 Agent 产出后回到 meta-po |
| `delegated-user-interaction` | `meta-pm` 的需求澄清阶段、`meta-se` 的 HLD 设计阶段 | 阶段内由目标 Agent 直接向用户提问并接收回复 | 目标 Agent 写 `return_summary_path`，meta-po 回收后发起 CP2 / CP3 |
| `lld-clarification-broker` | 多个 meta-dev 并行 LLD 写作时收集实现灰区 | meta-dev 不直接并发问用户；meta-po 作为 question broker 统一提问 | meta-po 写回 `lld_clarification_queue.items[].answer` 并分发给对应 meta-dev |

当 `semantic=delegated-user-interaction` 时，handoff 必须同时写入 `STATE.md.delegated_interaction` 的字段来源；当 `semantic=lld-clarification-broker` 时，handoff 必须引用 `STATE.md.parallel_execution.lld_clarification_queue` 和当前 `active_question_batch`。

## Handoff Dispatch Frontmatter 与 Agent Dispatch Evidence

所有 `process/handoffs/*.md` 必须包含以下字段：

```yaml
dispatch:
  required: true
  semantic: "stage-dispatch|delegated-user-interaction|lld-clarification-broker"
  mode: "subagent"
  platform: "codex|claude|openclaw|unknown"
  agent_role: "meta-dev"
  agent_path: ""
  tool_name: ""
  agent_id: ""
  agent_name: ""
  thread_id: ""
  spawned_at: ""
  resumed_at: ""
  completed_at: ""
  evidence: ""
  fallback_reason: ""
  approved_by: ""
  approved_at: ""
```

字段语义：

- `mode=subagent`：必须由平台子 agent 能力执行。Codex 必须记录 `spawn_agent`、`resume_agent` 或 `send_input` 的返回标识。
- `mode=inline-fallback`：仅在平台不可用且用户明确批准时使用，必须填写 `fallback_reason`、`approved_by`、`approved_at`。
- `mode=handoff-only`：只创建交接文件，不代表目标 agent 已执行；不得把业务任务标记为完成。
- `semantic=delegated-user-interaction`：允许被委托 Agent 在阶段内直接与用户多轮交互，但不得发起 CP2 / CP3 正式人工检查点。
- `semantic=lld-clarification-broker`：只允许 meta-po 汇总和提问；并行 meta-dev 只能写 clarification item，不能各自打断用户。

完成判定：

1. `dispatch.required=true` 且 `mode=subagent` 时，`agent_id` 或 `thread_id`、`tool_name`、`spawned_at` 或 `resumed_at`、`completed_at` 必须非空，才允许把目标任务标记为 `agent_completed`。
2. 只有 `from_agent` / `to_agent` / `status=completed`，但 `dispatch` 证据为空时，审计结论必须为 `not-subagent-executed`。
3. CP6 / CP7 读取 handoff 时必须检查本 `dispatch` 区；缺少证据时不得推进 Story 到 `ready-for-verification` 或 `verified`。

## 输出文件 / 输出模板

输出为上下文加载清单；不依赖模板文件。

## 约束

- 只加载正式对象，不加载其他 Agent 的历史推理过程
- 活跃 `CR-*`、当前 Story 与当前阶段状态必须优先纳入
- 只使用当前工作区路径（`process/`、`checkpoints/`、`delivery/`）
- 不得把完整对话、全量 `process/stories/`、历史失败轮次或无关 HLD 批量传给子 agent
- production 项目交付前必须携带 `delivery_routing` 决策；未确认输出路径时，下游不得写交付件
- handoff 文件只是调度输入和审计载体；不得用 handoff 文档代替 `spawn_agent` / `resume_agent` / `send_input` 或平台 Task/Subagent 调用

## 验收标准

- [ ] 输出清单能支持目标 Agent 完成当前任务
- [ ] 不包含无关阶段草稿或历史失败轮次
- [ ] 活跃变更与当前 Story 上下文已纳入
- [ ] Codex 子 agent 上下文包包含复用键和明确的关闭时机
- [ ] 阶段委托 handoff 能对应 `STATE.md.delegated_interaction`
- [ ] LLD clarification broker handoff 能对应 `STATE.md.parallel_execution.lld_clarification_queue`
- [ ] handoff frontmatter 含 `dispatch` 区，且能区分子 agent 执行、仅交接、用户批准的 inline fallback

## 不适用边界

- 只是查询文件内容，不涉及 Agent 交接
- 目标 Agent 未明确

## Gotchas

- Story 执行阶段通常同时存在 Wave 级和 Story 级上下文，不能只给其中一层
- 文档太多时应优先给“当前正式版本”，不要把历史稿与现行稿混装
- 阶段委托只是交互方式，不是门控授权；CP2 / CP3 正式确认仍必须回到 meta-po
- LLD broker 的队列答案必须回写到正式 LLD 或 DEV-LOG，不能只停留在对话里
