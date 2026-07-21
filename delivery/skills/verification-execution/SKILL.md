---
name: verification-execution
description: >-
  当 Story 已通过 CP6、进入 CP7 验证阶段，需要证明交付满足需求、场景、设计契约、
  实现证据、质量标准、平台约束和发布条件时使用。输出验证范围、验证对象清单、
  追踪矩阵、设计契约验证、分层验证计划、自动化 / fixture / dry-run / 人工审查证据、
  问题和剩余风险、阶段决策。
  触发词包括：验证执行、verification execution、CP7、验证对象清单、验证追踪矩阵、PASS_WITH_RISK。
argument-hint: "Story ID、验证范围、TEST-MATRIX、IMPLEMENTATION、目标平台或验证命令"
user-invokable: true
status: active
---


## vNext 过程引用契约

- `process/...` 是过程仓逻辑引用，不是发布仓中的相对物理路径。
- 首次文件系统 I/O 前必须调用 `meta-flow project resolve-ref --project-root <release-root> --logical-ref <process/...> --format json`。
- 只可瞬时使用成功 JSON 中的 `resolved_path`；不得把绝对路径写入治理文件、Prompt 产物或 Git。
- 命令以退出码 2 返回 BLOCKED 时必须停止；不得自行拼 sibling、去掉 `process/`、恢复软链接或回退 legacy。
- legacy-only 操作必须交还 Host Orchestrator，并使用独立 typed authorization；本 Skill 不构造 legacy capability。

## 目标

用可追溯证据证明本次交付是正确的、完整的、可运行的、可维护的、可交接的，并且没有破坏已有行为。

验证不是只跑测试。验证必须覆盖：

| 验证对象 | 示例 | 验证重点 |
|---|---|---|
| 代码 | 函数、类、CLI、脚本、服务逻辑 | 正确性、边界、异常、回归、安全 |
| Prompt / Skill | `SKILL.md`、agent prompt、workflow rules | 角色边界、输入输出、决策规则、禁止行为 |
| 模板 / Schema | Markdown 模板、YAML / JSON schema、frontmatter | 必填字段、结构稳定、下游可消费 |
| 安装器 / 平台适配 | install script、platform contracts、agent 渲染 | Claude / Codex 差异、路径、权限、dry-run |
| Guardrail / Validator | 检查脚本、lint、fixture、契约测试 | 能发现错误、错误信息可行动 |
| 文档 | README、USER-MANUAL、release notes | 用户可理解、路径正确、行为同步 |
| 状态与过程文件 | STATE、CP6、handoff、Decision Brief | 状态一致、证据完整、授权边界明确 |
| 发布产物 | deploy checklist、rollback、migration、feedback | 发布风险、回滚、后续跟踪 |
| Workflow Eval Evidence | `WORKFLOW-EVAL.yaml`、`PROMPT-BUNDLE.yaml`、`CASE-REGISTRY.yaml`、`process/evals/runs/<run-id>/run-summary.json` | generated workflow / prompt-skill / mixed 产物的结构、trace、hash、case、权限和回归稳定性 |

## 适用场景

- Story 已完成 CP6，状态进入 `ready-for-verification`。
- 需要输出 CP7 Story 验证完成门。
- Prompt / Skill / Workflow / 安装器 / Guardrail / 平台适配 / 发布相关变更需要验证。
- CP7 `NEEDS_REWORK` 回修后，需要复验和最小回归验证；`NEEDS_DESIGN_CLARIFICATION` 回来后必须先复核设计契约再验证。
- fast-lane 任务需要保留轻量但可审计的验证摘要。

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] Story 状态为 `ready-for-verification`。
- [ ] CP6 结论为 `PASS` 或 `WAIVED`，且包含 Agent Dispatch Evidence。
- [ ] CP6 已记录实现执行证据路径、证据类型和低风险 N/A 理由。
- [ ] `docs/quality/TEST-STRATEGY.md` 已生成，或 CP7 写明 N/A / WAIVED 原因。
- [ ] 验证环境或等价验证方式可用。
- [ ] `validation_mode` 已判定为 `runtime` / `static-only` / `dry-run-only` / `review-only` / `mixed`。

## 必须读取的输入

- 用户请求与当前 Story 卡片
- `docs/product/SCENARIOS.yaml`
- `docs/product/TEST-MATRIX.md`
- `docs/product/MVP-SCOPE.md`
- `docs/design/BLUEPRINT.md`
- `docs/design/HLD.md`
- `docs/design/ARCHITECTURE-DECISION.md`
- Story 设计证据：`STORY-*-LLD.md`、Story 技术说明或 waived 证据
- CP6 实现执行证据：`STORY-*-IMPLEMENTATION.md`、`docs/features/<feature>/IMPLEMENTATION.md`、Story `implementation_context` 或 DEV-LOG 摘要
- 当前 diff 或实现对象清单
- 测试、fixture、guardrail、dry-run 输出
- `process/STATE.md` 与 handoff / dispatch 证据
- 活跃 `process/changes/CR-*.md`（若验证对象来自变更）
- `validation_target.sut_type` 与 workflow eval evidence（当 Story / CR 涉及 generated workflow、prompt-skill-workflow、meta-flow-core-code、agentic-code-product 或 mixed）

## 知识来源

- `skills/verification-execution/templates/VERIFICATION-TEMPLATE.md`
- `checkpoint-manager` 的 CP7 契约
- `quality-review` 的 TEST-REPORT / REVIEW / FIXES 模板
- `implementation-execution` 的实现证据契约
- `release-readiness` 的 CP8 输入契约
- `review-artifact-protocol` 的 findings 结构

## 执行步骤

1. **读取输入和交付范围**：确认本次验证范围、非范围、上游已接受风险、阻塞条件和验证模式。
2. **建立验证对象清单**：列出所有被改动或被影响的代码、Prompt / Skill、模板 / Schema、安装器、guardrail、文档、状态文件和发布产物；每项必须有验证方式。
3. **建立验证追踪矩阵**：把 Scenario、Requirement、Story、Design Contract、Implementation、Test / Check、Status、Risk 串联起来，暴露“有需求无实现”“有实现无测试”“有测试无追溯”的缺口。
4. **抽取设计契约和质量门禁**：从 Story、LLD、HLD、ADR、Feature DESIGN、IMPLEMENTATION、平台契约中抽取 must / should / must-not、输入输出、状态流转、权限、平台差异、异常处理和验收标准。
5. **制定分层验证计划**：按风险选择静态检查、单元测试、Prompt / Skill fixture、契约测试、集成测试、安装 dry-run、回归测试、人工审查；每项标记必跑、条件触发、N/A 和阻塞条件。
   - `sut_type=code-project`：workflow eval 默认 N/A，除非 Story 显式要求。
   - `sut_type=generated-workflow`：必须消费 workflow eval run evidence，覆盖 schema、状态 / DAG、checkpoint、human gate、trace、permission 和 recovery。
   - `sut_type=prompt-skill-workflow`：必须消费 prompt bundle hash、fixture / rubric、negative 和 regression case。
   - `sut_type=meta-flow-core-code`：必须组合仓库原生检查、delivery guardrail 和 workflow eval 回归样例。
   - `sut_type=agentic-code-product|mixed`：必须按 Story 对象组合 code + workflow + prompt 验证层。
6. **运行静态检查**：记录 `git diff --check`、语法 / schema / frontmatter、缓存文件、敏感信息、路径和链接检查结果。
7. **运行单元测试和 fixture 测试**：代码、状态机、安装器、guardrail、Prompt / Skill 均按适用对象验证；复杂 Prompt / Skill 至少要有 fixture 或人工样例验证。
8. **运行契约测试和集成测试**：验证上游输入与下游消费兼容，例如 TEST-MATRIX 到 TEST-REPORT、IMPLEMENTATION 到 quality-review、install script 到 platform contracts。
9. **运行平台适配和安装 dry-run**：涉及 Claude / Codex / OpenClaw、project / user scope、安装器、AskUserQuestion、request_user_input 降级时必须验证。
10. **执行人工 / 语义质量审查**：检查需求理解、场景覆盖、Prompt 边界、文档可用性、风险低估和 happy path 偏差。
11. **分级记录问题和剩余风险**：按 `BLOCKER` / `HIGH` / `MEDIUM` / `LOW` / `INFO` 记录问题；剩余风险必须有 owner、接受条件和后续动作。
12. **输出阶段决策**：结论只能使用 `PASS`、`PASS_WITH_RISK`、`BLOCKED`、`NEEDS_REWORK`、`NEEDS_DESIGN_CLARIFICATION`、`WAIVED`。
13. **输出 Story Return Packet**：写入 `process/returns/STORY-*.CP7.return.json`，记录验证 touched files、verification commands、risks、waivers、open questions 和 next route，并确保可通过 `meta-flow story return-check`。
14. **生成 Evidence Index**：用 `meta-flow story evidence-index --return <return-packet>` 生成 `process/evidence/STORY-*.CP7.index.json`，CP7 摘要只引用该索引，不复制完整证据正文。
15. **检查设计回写状态**：若 CP6 / CP7 return 或 design delta 标记 `requires_feature_doc_update=true`，在 CP8 前必须运行 `meta-flow design delta-check --require-merged`，未合并不得静默进入 READY。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| Story 验证报告 | `docs/quality/VERIFICATION-REPORT.md` 或 `docs/features/<feature>/VERIFICATION.md` | `skills/verification-execution/templates/VERIFICATION-TEMPLATE.md` |
| 测试报告 | `docs/quality/TEST-REPORT.md` 或 Feature scoped 等价文件 | `quality-review` |
| 评审报告 | `docs/quality/REVIEW.md` 或 Feature scoped 等价文件 | `quality-review` |
| 修复输入 | `docs/quality/FIXES.md` | `quality-review` |
| Story Return Packet | `process/returns/STORY-{id}.CP7.return.json` | `skills/context-manifest-builder/templates/STORY-RETURN-PACKET-TEMPLATE.json` |
| Evidence Index | `process/evidence/STORY-{id}.CP7.index.json` | `skills/context-manifest-builder/templates/EVIDENCE-INDEX-TEMPLATE.json` |
| CP7 检查结果 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` | `checkpoint-manager` |

## 验证报告生成规则

| 场景 | 验证报告形态 |
|---|---|
| 小文案 / 低风险文档修订 | CP7 摘要 + TEST-REPORT N/A 可覆盖 |
| 普通 Story | `VERIFICATION-REPORT.md` 或 TEST-REPORT 中完整章节 |
| Prompt / Skill / Workflow 改造 | 强制完整验证报告，含 fixture 或人工样例验证 |
| 安装器 / Guardrail / 平台适配 | 强制完整验证报告，含 dry-run / guardrail / 负向用例 |
| 高风险 full-lld Story | 强制完整验证报告 |
| 发布相关改造 | 强制完整验证报告，并作为 CP8 输入 |

## validation_mode 判定

| 模式 | 适用条件 | 最小验证要求 |
|---|---|---|
| `runtime` | 需要真实运行或集成执行 | 环境确认、单元 / 集成 / 回归、日志证据 |
| `static-only` | 纯文档、Prompt、模板结构检查 | diff、结构、契约、人工审查 |
| `dry-run-only` | 安装器、平台渲染、规则安装 | dry-run、路径、frontmatter、权限检查 |
| `review-only` | 只做方案或文档质量审查 | review findings、人工 / 语义检查 |
| `mixed` | 同时涉及代码、Prompt、平台或文档 | 按对象清单组合验证 |

## 阶段决策与路由

| 结论 | 含义 | 路由 |
|---|---|---|
| `PASS` | 可进入下一阶段 | Story -> `verified` |
| `PASS_WITH_RISK` | 可进入下一阶段，但风险必须被记录和接受 | Story -> `verified-with-risk` 或 `verified` + CP8 risk acceptance 输入 |
| `BLOCKED` | 信息、环境、授权或阻塞缺陷导致不能继续 | host-orchestrator 阻断推进 |
| `NEEDS_REWORK` | 实现需要返工 | 路由回 meta-dev |
| `NEEDS_DESIGN_CLARIFICATION` | 上游设计或需求需澄清 | 路由回 meta-se / host-orchestrator，必要时重开 CP5 或 CR |
| `WAIVED` | 验证项经批准豁免 | 记录批准来源、影响和重访条件 |

## 约束

- 不修改验收目标；发现验收目标错误时回到 host-orchestrator / meta-se。
- 不直接修复实现；验证输出问题、复现、影响、建议和复验范围。
- 不用“测试通过”替代覆盖矩阵、设计契约、实现证据和平台约束验证。
- 不把无证据的口头判断写成 PASS。
- 不把 eval run 的 PASS 直接写成 CP7 PASS；eval evidence 只是验证证据输入，仍需验证对象清单、追踪矩阵、设计契约验证、分层验证计划和风险判断。
- 不把 `PASS_WITH_RISK` 静默转成 `PASS`；风险必须进入 CP8 Decision Brief 或风险接受记录。
- 不在缺少 meta-qa 调度证据时推进 CP7。

## 验收标准

- [ ] 验证范围和非范围明确。
- [ ] 验证对象清单覆盖全部适用工程资产。
- [ ] 追踪矩阵覆盖 Scenario / Requirement / Story / Design Contract / Implementation / Test / Risk。
- [ ] 设计契约验证清单有来源、验证方式、阻塞性和结果。
- [ ] 分层验证计划包含必跑、条件触发、N/A、未覆盖风险和阻塞条件。
- [ ] 自动化、fixture、dry-run、人工审查证据已记录。
- [ ] `process/returns/STORY-*.CP7.return.json` 已记录验证结论、风险、waiver 和 next route。
- [ ] `process/evidence/STORY-*.CP7.index.json` 已生成，CP7 检查可引用该索引。
- [ ] 需要回写长期设计的 Story design delta 已标记 merged，或 CP8 明确 BLOCKED / NEEDS_DESIGN_CLARIFICATION。
- [ ] 问题清单和剩余风险有等级、owner、状态和下一步。
- [ ] 阶段结论使用允许枚举，并能驱动 state-router 路由。

## 不适用边界

- 当前 Story 尚未通过 CP6。
- 当前任务只是在实现阶段做局部自测，应使用 `implementation-execution`。
- 当前任务是独立 review lane，不进入 CP7，应使用 `quality-review` 的 `review_mode`。

## Gotchas

- 验证对象不是只有代码；Prompt、Skill、模板、安装器、guardrail、文档和状态文件都可能是交付风险来源。
- `TEST-MATRIX.md` 是输入，不自动等于本轮验证追踪矩阵；验证报告必须写明本轮实际验证到哪里。
- Prompt / Skill fixture 不要求逐字匹配自然语言输出，但必须验证关键字段、角色边界、禁止行为和平台差异。
- `PASS_WITH_RISK` 不是“失败”；它可以推进，但必须让风险进入 CP8 风险接受或后续跟踪。
- `VALIDATION-ENV.yaml` 不是所有验证模式都必须完整运行环境；`static-only` / `dry-run-only` / `review-only` 可用等价验证方式，但必须写明理由。
- 外部 Promptfoo / DeepEval / Langfuse / Garak 适配器默认不是 CP7 必跑项；任何网络、凭据、trace 上传或外部模型调用必须先有 `runtime_authorization`。
