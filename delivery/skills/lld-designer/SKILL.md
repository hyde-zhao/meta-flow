---
name: lld-designer
description: >-
  当某个 Story 在开发前需要落地为 Low-Level Design（LLD）时使用。
  输出模块拆分、文件影响范围、数据模型、接口、流程、异常处理、测试设计、实施步骤、
  风险、发布与回滚策略，并交由全部目标 Story 的 LLD 统一确认后再进入实现。触发词包括：LLD、详细设计、实现设计、Story 设计。
argument-hint: "必填：Story ID；可选：Story 名称 / slug、目标平台或技术栈"
user-invokable: true
status: active
---

## 目标

基于 Story 卡片、已确认的 HLD、架构约束、依赖类型和文件所有权，输出可直接指导编码、评审与验证的 Story 级 LLD，并在全部目标 Story 的 LLD 统一确认前停止，不进入实现。

## 适用场景

- Story 已进入 `lld-ready` / `package-draft` 等待设计状态，准备进入实现前的详细设计
- 需要形成可评审的 Story 级实现蓝图

## 前置条件

- [ ] `process/stories/STORY-{id}-{story_slug}.md` 已进入 `lld-ready`、`package-draft` 或等价待设计状态
- [ ] `process/HLD.md` 与 `process/ARCHITECTURE-DECISION.md` 已确认
- [ ] 若 Story 涉及平台路径或安装结构，`delivery/doc/PLATFORM-CONTRACTS.yaml` 与 `process/PLATFORM-INSTALL-SPEC.md` 可读

## 必须读取的输入

- `process/stories/STORY-{id}-{story_slug}.md`
- `process/HLD.md`
- `process/ARCHITECTURE-DECISION.md`
- `process/STATE.md.parallel_execution.lld_design_batch`（若已存在）
- `process/STATE.md.parallel_execution.lld_clarification_queue`（并行 LLD 写作期间必须读取 / 更新）
- 相关前置 Story、平台约束、共享设计片段或 `CR-*.md`（若存在）

## 知识来源

- `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md`
- Story 卡片中的验收标准与设计约束
- 上游 HLD / ADR 约束
- `process/HLD-lld-writing-method.md` 的阶段化方法与章节契约
- `delivery/doc/PLATFORM-CONTRACTS.yaml` 的平台路径契约；`PLATFORM-INSTALL-SPEC.md` 仅作为说明性对照

## 执行步骤

### 阶段 1：Ready Check

1. 校验 Story `status=lld-ready`、`package-draft` 或等价待设计状态，且三件套完整。
2. 校验 `HLD.md`、`ARCHITECTURE-DECISION.md` 已确认；命中平台路径时读取 `delivery/doc/PLATFORM-CONTRACTS.yaml` 和 `PLATFORM-INSTALL-SPEC.md`。
3. 若缺少关键输入，立即进入 `blocked`，写清缺失对象和缺失原因。

### 阶段 2：Scope Extraction

1. 提炼 Story 范围、输出文件、平台目标、依赖 Story 和设计约束。
2. 若存在共享设计片段或 `CR-*.md`，在范围提炼阶段显式登记引用。

### 阶段 3：Contract Mapping

1. 将 Story 约束映射到 14 个章节。
2. 逐项建立配对关系：
   - 接口 -> 测试入口
   - 异常路径 -> 错误路径测试
   - 文件影响 -> TASK-ID

### 阶段 4：Drafting

1. 按 14 个规定章节生成 LLD。
2. 对无数据模型、无图示、无平台差异等场景必须显式写“无新增”或“不适用”，不得留空。

### 阶段 5：Review Prep

1. 生成 `OPEN` / Spike / 风险表 / DoD / 确认区。
2. 若存在关键未决点，必须写明下一动作和责任方。
3. 若未决点需要用户决策且当前处于并行 LLD，写入 `lld_clarification_queue.items[]`，不得直接询问用户；每个 item 必须包含推荐方案、至少 1 个备选方案（优先 2 个）、优劣分析、影响面、是否阻断 LLD 和回退 / 切换条件。只有 `max_parallel_lld=1` 或 CP5 单 Story 返工且唯一活跃 meta-dev 时才允许短问。
4. 将已回答或转 OPEN / Spike 的问题写入 LLD 的“实现灰区与取舍记录”，包含问题、推荐方案、备选方案、优劣分析、决策、影响面、证据和重访条件。

### 阶段 6：Checkpoint Handoff

1. 复用 Story 卡片中的 `story_slug`，写入 `process/stories/STORY-{id}-{story_slug}-LLD.md`。
2. 若存在 `blocks_lld=true` 且未回答的 clarification item，不得生成通过态 CP5 自动预检；将 Story 标记为 blocked 或 waiting-clarification，并等待 meta-po broker。
3. 将 Story 推进到 `lld-ready-for-review`。
4. 停止在全部目标 Story 的 LLD 统一确认前，不进入实现。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| Story LLD | `process/stories/STORY-{id}-{story_slug}-LLD.md` | `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` |

## 约束

- 14 个章节必须与 `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` 一一对应
- LLD `confirmed=false`、全量 CP5 人工确认未通过、`dev_gate` 未满足或文件所有权冲突时不得进入实现
- 不超出当前 Story 范围
- 发现未决技术点时，必须输出 `OPEN` 或 Spike，禁止伪确定
- 发现实现灰区时，必须优先写入 LLD Clarification Queue；并行 LLD 阶段不得让多个 meta-dev 直接问用户；queue item 必须可被 meta-po 直接汇入 CP5 待人工决策清单
- 若模板章节与说明冲突，以模板契约为准同步修正
- LLD 文件名必须复用 Story 卡片中的 `story_slug`，不得自行再生成第二套命名
- 涉及平台路径、schema 或发现机制时，必须引用 `delivery/doc/PLATFORM-CONTRACTS.yaml` 或官方文档证据；禁止按同平台目录进行类比推断

## 验收标准

- [ ] LLD 覆盖 14 个规定章节
- [ ] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [ ] 回滚与发布策略明确
- [ ] 输入契约覆盖 Story / HLD / ADR / 依赖 / 平台 / CR
- [ ] 实现灰区与取舍记录已覆盖 queue 问题、用户答案、OPEN / Spike 和重访条件
- [ ] 失败路径覆盖 blocked / 回退 / Spike / LLD 批次确认 / dev_gate 阻断

## 不适用边界

- 当前任务还处于需求或 HLD 设计阶段
- Story 尚未进入 `lld-ready`、`package-draft` 或等价待设计状态
- 当前任务要求直接实现业务产物而非先完成 LLD

## Gotchas

- 若模板章节与说明口径不一致，应以模板契约为准同步修正，不允许双轨并存
- 详细设计不是实现日志，必须保持“可实施”而不是“已完成”
- `ARCHITECTURE-DECISION.md` 是条件必需输入：只要 Story 命中关键取舍、接口边界或平台规范，就必须显式读取
- LLD 的唯一正式输出仍是 `STORY-{id}-{story_slug}-LLD.md`；不要把关键信息拆到会话说明里
- clarification queue 的答案必须落回 LLD 和 DEV-LOG；只在对话中答复不能作为 CP5 证据
