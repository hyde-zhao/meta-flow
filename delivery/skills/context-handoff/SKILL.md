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

## 前置条件

- [ ] 目标 Agent 已明确
- [ ] `process/` 下相关输入文档已生成

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

## 输出文件 / 输出模板

输出为上下文加载清单；不依赖模板文件。

## 约束

- 只加载正式对象，不加载其他 Agent 的历史推理过程
- 活跃 `CR-*`、当前 Story 与当前阶段状态必须优先纳入
- 只使用当前工作区路径（`process/`、`checkpoints/`、`delivery/`）
- 不得把完整对话、全量 `process/stories/`、历史失败轮次或无关 HLD 批量传给子 agent
- production 项目交付前必须携带 `delivery_routing` 决策；未确认输出路径时，下游不得写交付件

## 验收标准

- [ ] 输出清单能支持目标 Agent 完成当前任务
- [ ] 不包含无关阶段草稿或历史失败轮次
- [ ] 活跃变更与当前 Story 上下文已纳入
- [ ] Codex 子 agent 上下文包包含复用键和明确的关闭时机

## 不适用边界

- 只是查询文件内容，不涉及 Agent 交接
- 目标 Agent 未明确

## Gotchas

- Story 执行阶段通常同时存在 Wave 级和 Story 级上下文，不能只给其中一层
- 文档太多时应优先给“当前正式版本”，不要把历史稿与现行稿混装
