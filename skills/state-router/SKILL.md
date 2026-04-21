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

读取并更新 `.meta-workflow/process/STATE.md`，根据当前阶段的退出条件判断是否可推进、是否需要回退、下一步应唤醒哪个 Agent，并保持状态机与 `skills/state-router/templates/STATE-TEMPLATE.md` 一致。

## 适用场景

- 元工作流阶段推进、阶段回退、状态查询
- `meta-po` 在每个阶段完成后进行退出条件判定
- Story 执行阶段内的 Wave / Story 收敛判断

## 前置条件

- [ ] `.meta-workflow/process/STATE.md` 已存在，或允许由 `skills/state-router/templates/STATE-TEMPLATE.md` 初始化
- [ ] 当前阶段相关产物的存在性和确认状态可被检查

## 必须读取的输入

- `.meta-workflow/process/STATE.md`（若已存在）
- `skills/state-router/templates/STATE-TEMPLATE.md`
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
- Story 执行阶段需要读取 `.meta-workflow/process/stories/STORY-*.md`

## 知识来源

- `skills/state-router/templates/STATE-TEMPLATE.md`：状态对象结构与阶段机基线
- `AGENTS.md` / `rules/AGENTS.md`：阶段定义、人工检查点与角色职责
- 各阶段产物 frontmatter 与文件存在性：退出条件的事实来源

## 执行步骤

### 1. 初始化或读取状态

1. 若 `.meta-workflow/process/STATE.md` 不存在，则以 `skills/state-router/templates/STATE-TEMPLATE.md` 初始化。
2. 读取 `current_phase`、`current_agent`、`blocked`、`checkpoints`、`history`。
3. 若 `blocked=true`，先返回阻塞原因，不允许静默推进。

### 2. 按阶段检查退出条件

| 当前阶段 | 退出条件 | 下一阶段 | 默认唤醒 Agent |
|---|---|---|---|
| `init` | `REQUEST.md` 已初始化且请求已登记 | `requirement-clarification` | `meta-pm` |
| `requirement-clarification` | `USE-CASES.md` 与 `REQUIREMENTS.md` 已确认，且无 `BLOCKING` 未决项 | `solution-design` | `meta-se` |
| `solution-design` | `HLD.md` 已确认 | `story-planning` | `meta-se` |
| `story-planning` | `STORY-BACKLOG.md` 与 `DEVELOPMENT-PLAN.yaml` 已确认 | `story-execution` | `meta-dev` |
| `story-execution` | 当前 Wave 内所有 Story 已到达 `verified`，且验证输出已收敛 | 下一 Wave 或 `documentation` | `meta-dev` / `meta-qa` / `meta-doc` |
| `documentation` | `README.md` 与 `USER-MANUAL.md` 已完成终验范围 | `delivered` | `meta-po` |
| `delivered` | 只读归档 | — | — |

### 3. 处理回退

1. 记录回退原因与目标阶段。
2. 将回退动作写入 `history`。
3. 只回退到最近仍可恢复的稳定阶段，不跨越未收敛变更单。

### 4. 回写状态

1. 更新 `current_phase`、`current_agent`、`last_action`、`next_action`、`last_updated`。
2. 推进或回退时追加 `history` 记录。
3. 查询状态时不改变业务内容，但允许刷新 `next_action`。

## 输出文件 / 输出模板

| 对象 | 路径 | 用途 |
|---|---|---|
| 运行时状态 | `.meta-workflow/process/STATE.md` | 当前状态机实例 |
| 状态模板 | `skills/state-router/templates/STATE-TEMPLATE.md` | 初始化与结构基线 |

## 约束

- 只负责状态判断、推进决策与状态回写，不生成需求/设计/实现内容
- 推进前必须验证当前阶段退出条件，不能用“默认通过”代替检查
- 回退必须记录原因、发起方和目标阶段
- 仅使用当前 `.meta-workflow/process/STATE.md` 与 `skills/state-router/templates/STATE-TEMPLATE.md` 契约

## 验收标准

- [ ] `STATE.md` 的阶段与下一步动作与实际产物状态一致
- [ ] 初始化时结构与 `skills/state-router/templates/STATE-TEMPLATE.md` 一致
- [ ] 推进 / 回退操作均追加 `history`
- [ ] 阻塞状态下返回明确阻塞原因

## 不适用边界

- 任务要求生成需求、设计、代码或文档本体
- 当前请求仅需要查看某个单独文件内容，不涉及状态推进

## Gotchas

- `story-execution` 是阶段状态，不替代单个 Story 的生命周期；Story 状态仍以 `story-manager` 维护的卡片为准
- 当存在活跃 `CR-*` 时，应优先收敛变更影响，再判断是否允许推进
- 首次初始化时只允许从 `skills/state-router/templates/STATE-TEMPLATE.md` 复制，不允许凭空脑补字段

