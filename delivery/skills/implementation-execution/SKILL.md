---
name: implementation-execution
description: >-
  当 Story 设计证据已通过 CP5，进入 story-execution，需要把设计契约转化为代码、Prompt、
  Skill、模板、Schema、安装器、guardrail、测试和文档等工程资产时使用。输出实现前置检查、
  实现对象清单、设计契约映射、单元测试 / Fixture 计划、最小实现切片、验证结果和实现交接摘要。
  触发词包括：实现执行、implementation execution、实现交接、IMPLEMENTATION、CP6 前自检。
argument-hint: "Story ID、实现对象、设计证据路径、目标平台或验证命令"
user-invokable: true
status: active
---

## 目标

把已确认的蓝图、HLD、Feature 设计、Story 设计证据和任务清单转化为可运行、可复用、可验证、可维护、可交接的工程资产，并在 CP6 前留下可审查的实现证据。

实现对象不限于代码，也包括：

| 实现对象 | 示例 | 主要关注点 |
|---|---|---|
| 代码实现 | 函数、类、CLI、服务端逻辑、脚本 | 正确性、可测试性、兼容性、性能、安全 |
| Prompt / Skill 实现 | `SKILL.md`、agent prompt、workflow rules | 角色边界、输入输出契约、决策规则、失败处理 |
| 模板 / Schema 实现 | `*-TEMPLATE.md`、YAML schema、Markdown frontmatter | 字段稳定、下游可消费、结构可检查 |
| 安装器 / 平台适配实现 | install script、platform contracts、agent frontmatter 渲染 | Claude / Codex 差异、权限、安装路径、dry-run |
| Guardrail / 验证实现 | 检查脚本、lint、fixture、契约测试 | 自动阻塞错误、验证设计契约 |
| 文档 / 交接实现 | README、USER-MANUAL、IMPLEMENTATION、handoff summary | 可理解、可恢复、可审计 |

## 适用场景

- Story 已通过全量 CP5，当前 Wave 满足 `dev_gate`。
- 需要修改代码、Prompt、Skill、模板、安装器、guardrail、测试或用户文档。
- Prompt / Skill / Workflow 改造、安装器 / 平台适配、Guardrail 改造或高风险 full-lld Story 需要完整实现说明。
- CP7 `NEEDS_REWORK` 回修时，需要根据缺陷和原设计证据做受控修复；`NEEDS_DESIGN_CLARIFICATION` 不应直接修代码，必须先回设计澄清。

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] Story 状态为 `dev-ready` / `lld-approved` / `package-approved` 或等价可实现状态。
- [ ] CP5 全量人工确认已通过，当前 Story `design_evidence_confirmed=true`。
- [ ] 当前 Wave 可执行，依赖门控和文件所有权门控满足。
- [ ] Story 卡片含 `feature_design_refs`、`lld_policy`、`dev_context`、`validation_context`、`acceptance_criteria` 和任务清单。
- [ ] 目标验证命令、guardrail、dry-run 或 N/A 原因可确定。

## 必须读取的输入

- `process/stories/STORY-{id}-{story_slug}.md`
- Story 设计证据：
  - `process/stories/STORY-{id}-{story_slug}-LLD.md`（`full-lld`）
  - Story 卡片 `## 技术说明` / `lld_gate`（`technical-note` / `waived`）
- `docs/design/HLD.md`
- `docs/design/ARCHITECTURE-DECISION.md`
- `docs/design/FEATURE-DESIGN-MATRIX.md`
- `docs/features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md`（如适用）
- `process/state/QUESTION-LEDGER.ndjson`
- 当前源码、Prompt / Skill、模板、脚本、测试、guardrail 和文档现状
- `delivery/doc/PLATFORM-CONTRACTS.yaml`（涉及平台路径、安装器或 agent / skill 安装时）
- 最新 CP7 / FIXES / REVIEW（验证失败回修时）

## 知识来源

- `skills/implementation-execution/templates/IMPLEMENTATION-TEMPLATE.md`
- Story 卡片、Feature DESIGN / TEST-PLAN / TASKS、LLD 或技术说明
- `checkpoint-manager` 的 CP6 契约
- `quality-review` 的 findings / test report 契约
- `review-artifact-protocol` 的 findings 结构

## 执行步骤

1. **实现前置检查**：确认上游设计、Story 范围、待确认问题、影响范围、验证方式和平台边界均可判定；阻塞项未关闭时不得实现。
2. **识别实现对象**：列出代码、Prompt / Skill、模板 / Schema、安装器、guardrail、测试、文档和交接对象；每项必须有目标和验证方式。
3. **映射设计契约**：从设计证据中抽取 must / should / must-not、输入字段、输出字段、状态变化、权限变化、平台分支和验证规则，映射到具体实现位置。
4. **制定单元测试 / Fixture 计划**：按实现对象选择测试形态；代码 / 状态机 / 安装器 / guardrail 通常必须有单元或契约测试，Prompt / Skill 至少有 fixture 或结构检查，模板至少有结构检查。
5. **制定最小实现切片**：每个切片绑定设计契约、改动对象、输出文件、局部验证和回滚点；避免一次性大范围无验证改动。
6. **按层实现工程资产**：优先模板 / Schema，其次 Prompt / Skill，再代码 / 脚本 / 安装器，再测试 / guardrail，最后用户文档和交接文档；纯代码功能可采用测试先行。
7. **逐切片验证**：每完成一个切片运行局部测试、结构检查、guardrail、dry-run 或格式检查，并记录结果。
8. **平台差异检查**：涉及 Claude / Codex / OpenClaw 时，检查平台专用 schema、AskUserQuestion、request_user_input 降级、安装路径和 dry-run。
9. **整体验证**：运行适用的 `pytest`、guardrail、install dry-run、`git diff --check`、lint / format / 类型检查；未运行项必须说明原因。
10. **输出实现交接摘要**：写入 `IMPLEMENTATION.md` 或 Story 实现摘要，列出完成内容、行为变化、受影响文件、验证、未运行检查、剩余风险和 QA / Review / Doc 关注点。
11. **输出 Story Return Packet**：写入 `process/returns/STORY-*.CP6.return.json`，记录 touched files、contract changes、boundary check、verification commands、risks、waivers 和 next route，并确保可通过 `meta-flow story return-check`。
12. **生成 Evidence Index**：用 `meta-flow story evidence-index --return <return-packet>` 生成 `process/evidence/STORY-*.CP6.index.json`，CP6 摘要只引用该索引，不复制完整证据正文。
13. **反馈设计缺口**：发现 Feature 边界、架构约束、Story 细节、用户确认点或测试验收不足时，写入设计缺口反馈；若改变长期 Feature DESIGN / ADR / HLD，写入 `process/design-deltas/STORY-*.delta.json`。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| Story 实现说明 | `process/stories/STORY-{id}-{story_slug}-IMPLEMENTATION.md` | `skills/implementation-execution/templates/IMPLEMENTATION-TEMPLATE.md` |
| Feature 实现说明 | `docs/features/<feature>/IMPLEMENTATION.md` | `skills/implementation-execution/templates/IMPLEMENTATION-TEMPLATE.md` |
| 实现日志 | `DEV-LOG.md` 或 Story scoped DEV-LOG | Story / 项目既有约定 |
| Story Return Packet | `process/returns/STORY-{id}.CP6.return.json` | `skills/context-manifest-builder/templates/STORY-RETURN-PACKET-TEMPLATE.json` |
| Evidence Index | `process/evidence/STORY-{id}.CP6.index.json` | `skills/context-manifest-builder/templates/EVIDENCE-INDEX-TEMPLATE.json` |
| Design Delta | `process/design-deltas/STORY-{id}.delta.json` | `skills/implementation-design/templates/DESIGN-DELTA-TEMPLATE.json` |
| CP6 自动检查输入 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` | `checkpoint-manager` |

## IMPLEMENTATION 生成规则

| 场景 | 是否强制完整 IMPLEMENTATION |
|---|---|
| 小代码修复 / 纯文档 | 不强制；final summary + CP6 可覆盖 |
| 普通 Story | Story 内实现摘要或 DEV-LOG 可覆盖 |
| Feature 级改造 | 建议生成 |
| Prompt / Skill / Workflow 改造 | 强制生成 |
| 安装器 / Guardrail / 平台适配 | 强制生成 |
| 高风险 full-lld Story | 强制生成 |
| 发布相关改造 | 强制生成 |

## 约束

- 不重新定义用户需求、Feature 边界或 HLD；发现缺口时反馈到上游。
- 不把低置信度假设写成确认事实。
- 不跳过测试和 guardrail 宣称完成；无法运行必须写明原因。
- 不只改 Prompt 而不改模板 / guardrail / 文档；不只改模板而不改 Prompt / Skill 执行规则。
- 不把 handoff 文件当作子 agent 执行完成证据。
- 不在 Codex 产物中写 Claude-only schema；Claude direct ask agent 必须符合 AskUserQuestion 权限规则。
- 不扩大 Story 文件所有权；必须扩大时交回 host-orchestrator 发起 CR 或重新进入设计门。

## 验收标准

- [ ] 实现前置检查完成，阻塞项为 0 或已交回 host-orchestrator。
- [ ] 实现对象清单覆盖代码、Prompt / Skill、模板 / Schema、安装器、guardrail、测试、文档中所有适用对象。
- [ ] 每个设计契约都有实现位置、动作和验证方式。
- [ ] 单元测试 / Fixture / 结构检查计划已按实现对象类型给出；N/A 项有原因。
- [ ] 最小实现切片有局部验证证据。
- [ ] 平台差异检查完成或 N/A 原因明确。
- [ ] 整体验证命令、结果和未运行项已记录。
- [ ] 实现交接摘要包含 QA / Review / Doc 关注点。
- [ ] `process/returns/STORY-*.CP6.return.json` 已记录实际 touched files、boundary check、verification commands 和 next route。
- [ ] `process/evidence/STORY-*.CP6.index.json` 已生成，CP6 检查可引用该索引。
- [ ] 如果实现改变长期设计，`process/design-deltas/STORY-*.delta.json` 已生成并指向目标 Feature DESIGN / ADR / HLD。
- [ ] 设计缺口已反馈到正确层级，不被实现阶段静默吞掉。

## 不适用边界

- 当前仍处于需求、HLD、Feature 设计或 CP5 前设计证据阶段。
- 用户只要求解释代码，不要求修改工程资产。
- 当前任务是独立质量评审，应使用 `quality-review`。

## Gotchas

- 实现不是只写代码；Prompt、Skill、模板、guardrail、安装器和文档都是工程资产。
- CP6 不是“改了文件”的证明；必须证明设计契约已落成、测试或 fixture 已执行、剩余风险已交接。
- Prompt / Skill 的 fixture 不需要验证完整自然语言，但必须验证关键字段、禁止行为、低置信度处理和越权阻断。
- `IMPLEMENTATION.md` 不是所有 Story 都强制生成；强制对象是复杂、高风险、平台、guardrail、安装器和 Prompt / Skill / Workflow 改造。
- 不要等所有切片完成后才第一次测试；局部验证能显著减少返工。
