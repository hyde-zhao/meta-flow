---
name: lld-designer
description: >-
  当某个 Story 在开发前需要按 lld_policy 落地为 Low-Level Design（LLD）、Story 技术说明
  或 waived 证据时使用。对 full-lld 输出模块拆分、文件影响范围、数据模型、接口、流程、
  异常处理、测试设计、实施步骤、风险、发布与回滚策略；对 technical-note 更新 Story 内
  `## 技术说明`；对 waived 校验豁免理由和重访条件。全部目标 Story 的设计证据统一确认后再进入实现。
  触发词包括：LLD、详细设计、实现设计、Story 设计、technical-note、lld_policy。
argument-hint: "必填：Story ID；可选：Story 名称 / slug、目标平台或技术栈"
user-invokable: true
status: active
---

## 目标

基于 Story 卡片、已确认的 HLD / ADR、Feature 设计引用、`lld_policy`、依赖类型和文件所有权，输出可直接指导编码、评审与验证的 Story 级设计证据，并在全部目标 Story 的设计证据统一确认前停止，不进入实现。

## 适用场景

- Story 已进入 `lld-ready` / `package-draft` 等待设计状态，准备进入实现前的详细设计或技术说明
- `lld_policy.required_level=full-lld`，需要形成可评审的 Story 级实现蓝图
- `lld_policy.required_level=technical-note`，低风险 Story 只需要在 Story 卡片中形成可审查技术说明
- `lld_policy.required_level=waived`，需要校验豁免理由、风险接受和重访条件

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] `process/stories/STORY-{id}-{story_slug}.md` 已进入 `lld-ready`、`package-draft` 或等价待设计状态
- [ ] `docs/design/HLD.md` 与 `docs/design/ARCHITECTURE-DECISION.md` 已确认
- [ ] Story 卡片已包含 `feature_design_refs` 与 `lld_policy.required_level`
- [ ] `docs/design/FEATURE-DESIGN-MATRIX.md` 已生成；若 Story 引用 required Feature，对应 `docs/features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md` 可读或有 waived 证据
- [ ] 若 Story 涉及平台路径或安装结构，`delivery/doc/PLATFORM-CONTRACTS.yaml` 与 `process/PLATFORM-INSTALL-SPEC.md` 可读

## 必须读取的输入

- `process/stories/STORY-{id}-{story_slug}.md`
- `docs/design/HLD.md`
- `docs/design/ARCHITECTURE-DECISION.md`
- `docs/design/FEATURE-DESIGN-MATRIX.md`
- Story `feature_design_refs` 指向的 `docs/features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md`（如适用）
- `process/context/CP5-LLD-CONTEXT.yaml lld_design_batch`（若已存在）
- `process/state/QUESTION-LEDGER.ndjson` 或 CP5 context queue ref（并行 LLD 写作期间必须读取 / 更新）
- 相关前置 Story、平台约束、共享设计片段或 `CR-*.md`（若存在）

## 知识来源

- `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md`
- Story 卡片中的验收标准与设计约束
- `FEATURE-DESIGN-MATRIX.md` 中的 `lld_policy` 判定和 required / waived 理由
- Feature DESIGN / TEST-PLAN / TASKS 中的下游消费契约
- 上游 HLD / ADR 约束
- `process/HLD-lld-writing-method.md` 的阶段化方法与章节契约
- `delivery/doc/PLATFORM-CONTRACTS.yaml` 的平台路径契约；`PLATFORM-INSTALL-SPEC.md` 仅作为说明性对照

## 执行步骤

### 阶段 1：Ready Check

1. 校验 Story `status=lld-ready`、`package-draft` 或等价待设计状态，且 Story 卡片完整。
2. 校验 `HLD.md`、`ARCHITECTURE-DECISION.md`、`FEATURE-DESIGN-MATRIX.md` 已确认或有 N/A / waived 证据；命中平台路径时读取 `delivery/doc/PLATFORM-CONTRACTS.yaml` 和 `PLATFORM-INSTALL-SPEC.md`。
3. 读取 Story `lld_policy.required_level`：
   - `full-lld`：进入完整 14 章节 LLD。
   - `technical-note`：仅更新 Story 卡片 `## 技术说明`，但必须覆盖文件影响、接口 / 数据、失败路径、测试入口、风险和偏离记录。
   - `waived`：不生成 LLD，校验 Story 卡片存在豁免理由、影响范围、风险接受和重访条件。
4. 若缺少关键输入，立即进入 `blocked`，写清缺失对象和缺失原因。

### 阶段 2：Scope Extraction

1. 提炼 Story 范围、输出文件、平台目标、依赖 Story、Feature 设计引用和设计约束。
2. 若存在共享设计片段、Feature DESIGN 或 `CR-*.md`，在范围提炼阶段显式登记引用。
3. 对 `technical-note` / `waived` 再次确认未命中数据、安全、外部接口、并发、迁移、跨 Story 契约等 `full-lld` 触发条件；命中则升级为 `full-lld` 并写明原因。

### 阶段 3：Contract Mapping

1. 将 Story 约束映射到所需设计证据：
   - `full-lld` 映射到 14 个章节。
   - `technical-note` 映射到 Story `## 技术说明` 的最小字段。
   - `waived` 映射到豁免证据和重访条件。
2. 逐项建立配对关系：
   - 接口 -> 测试入口
   - 异常路径 -> 错误路径测试
   - 文件影响 -> TASK-ID

### 阶段 4：Drafting

1. 若为 `full-lld`，按 14 个规定章节生成 LLD。
2. 若为 `technical-note`，更新 Story 卡片 `## 技术说明`，至少包含：设计依据、文件影响、接口 / 数据 / 权限变化、异常和回退、测试入口、已知风险、偏离记录。
3. 若为 `waived`，更新 Story 卡片 `lld_gate`，写明豁免理由、影响范围、风险接受、重访条件和 CP5 证据路径。
4. 对无数据模型、无图示、无平台差异等场景必须显式写“无新增”或“不适用”，不得留空。

### 阶段 5：Review Prep

1. 生成 `OPEN` / Spike / 风险表 / DoD / 确认区。
2. 若存在关键未决点，必须写明下一动作和责任方。
3. 若未决点需要用户决策且当前处于并行 LLD，写入 `lld_clarification_queue.items[]`，不得直接询问用户；每个 item 必须包含推荐方案、至少 1 个备选方案（优先 2 个）、优劣分析、影响面、是否阻断 LLD 和回退 / 切换条件。只有 `max_parallel_lld=1` 或 CP5 单 Story 返工且唯一活跃 meta-dev 时才允许短问。
4. 将已回答或转 OPEN / Spike 的问题写入对应设计证据：`full-lld` 写入 LLD 的“实现灰区与取舍记录”，`technical-note` 写入 Story 技术说明，`waived` 写入豁免说明；均必须包含问题、推荐方案、备选方案、优劣分析、决策、影响面、证据和重访条件。

### 阶段 6：Checkpoint Handoff

1. 复用 Story 卡片中的 `story_slug`：
   - `full-lld` 写入 `process/stories/STORY-{id}-{story_slug}-LLD.md`。
   - `technical-note` 更新 `process/stories/STORY-{id}-{story_slug}.md` 的 `## 技术说明`。
   - `waived` 更新 Story 卡片中的豁免证据。
2. 若存在 `blocks_lld=true` 且未回答的 clarification item，不得生成通过态 CP5 自动预检；将 Story 标记为 blocked 或 waiting-clarification，并等待 host-orchestrator broker。
3. 将 Story 推进到 `lld-ready-for-review`，并在 CP5 自动预检中标明 `design_evidence_type=full-lld|technical-note|waived`。
4. 停止在全部目标 Story 的设计证据统一确认前，不进入实现。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| Story LLD（仅 `full-lld`） | `process/stories/STORY-{id}-{story_slug}-LLD.md` | `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` |
| Story 技术说明（仅 `technical-note`） | `process/stories/STORY-{id}-{story_slug}.md` 的 `## 技术说明` | `skills/story-manager/templates/STORY-TEMPLATE.md` |
| Story 豁免证据（仅 `waived`） | `process/stories/STORY-{id}-{story_slug}.md` 的 `lld_gate` / `## 技术说明` | `skills/story-manager/templates/STORY-TEMPLATE.md` |

## 约束

- `full-lld` 的 14 个章节必须与 `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` 一一对应
- Story 设计证据 `confirmed=false`、全量 CP5 人工确认未通过、`dev_gate` 未满足或文件所有权冲突时不得进入实现
- 不得为了节省 token 把高风险 Story 降级为 `technical-note`；数据、安全、外部接口、并发、迁移或跨 Story 契约命中时默认 `full-lld`
- 不超出当前 Story 范围
- 发现未决技术点时，必须输出 `OPEN` 或 Spike，禁止伪确定
- 发现实现灰区时，必须优先写入 LLD Clarification Queue；并行 LLD 阶段不得让多个 meta-dev 直接问用户；queue item 必须可被 host-orchestrator 直接汇入 CP5 待人工决策清单
- 若模板章节与说明冲突，以模板契约为准同步修正
- LLD 文件名必须复用 Story 卡片中的 `story_slug`，不得自行再生成第二套命名
- 涉及平台路径、schema 或发现机制时，必须引用 `delivery/doc/PLATFORM-CONTRACTS.yaml` 或官方文档证据；禁止按同平台目录进行类比推断

## 验收标准

- [ ] `full-lld` 覆盖 14 个规定章节；`technical-note` 覆盖最小技术说明字段；`waived` 覆盖豁免理由和重访条件
- [ ] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [ ] 回滚与发布策略明确
- [ ] 输入契约覆盖 Story / HLD / ADR / Feature Matrix / Feature DESIGN / 依赖 / 平台 / CR
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
- `full-lld` 的正式输出是 `STORY-{id}-{story_slug}-LLD.md`；`technical-note` 和 `waived` 的正式输出在 Story 卡片里，不要把关键信息只留在会话说明里
- 降级为 `technical-note` 的目的只是减少不必要 token，不是降低 CP5 审查强度
- clarification queue 的答案必须落回 LLD 和 DEV-LOG；只在对话中答复不能作为 CP5 证据
