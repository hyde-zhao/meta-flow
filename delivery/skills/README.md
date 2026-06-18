# Skills README — Agent 与 Skill 应用关系

> 本文件记录**当前仓库中已交付的 Agent 与 Skill 的应用关系**。
> 它只覆盖 `skills/` 目录下实际存在的 Skill，不把 Agent 提示词中的历史占位或未交付 Skill 计入正式映射。

## 维护规则

1. 开发、新增、删除或修改 Skill 时，若影响 Agent / Skill 关系或模板交叉引用关系，必须同步更新本文件。
2. 开发或修改 Agent 时，若影响 Skill 的调用、适用或归属关系，必须同步更新本文件。
3. 历史占位或未交付 Skill 不写入正式关系表。
4. active Skill 的运行时资产（`templates/`、`scripts/`、`schemas/`、`examples/`）必须留在该 Skill 目录内，不得回流到 `delivery/` 顶层公共目录。
5. active Skill 若在 `SKILL.md` 中引用 `templates/` 或 `scripts/`，必须使用 Skill 相对路径或 `<skill-root>/...`，不得写 `delivery/scripts/*.py` 或依赖 cwd 的 `python scripts/...`。
6. active Skill 一旦新增脚本资产，必须验证 Claude Code / Codex 在 project 与 user scope 下安装后脚本仍可直接执行。
7. 涉及平台安装路径的 Skill 必须以 `delivery/doc/PLATFORM-CONTRACTS.yaml` 为路径真相源；不得按同平台目录进行类比推断。
8. 修改 `USE-CASES.md` / `REQUIREMENTS.md` 时必须先有 CR 文档处理决策，默认增量更新并保留旧基线，同时在目标文档追加 `## 修订记录`。
9. 涉及功能 Agent 调度的 Skill 必须区分 handoff 与真实执行证据；CP6 / CP7 必须读取 `Agent Dispatch Evidence`，并校验 `canonical_role`、`codex_agent_name`、`reasoning_profile`、`dispatch_trigger`、`tool_name`、`agent_id` / `thread_id` 和完成时间，不得用 handoff 文件替代子 agent 运行结果。
10. 长期产品、设计、质量和发布文档默认写入 `docs/product/`、`docs/design/`、`docs/features/`、`docs/quality/`、`docs/release/`；运行状态、计划、Story 执行态、discussion、handoff、CR 和自动检查仍写入 `process/`；人工检查点审查稿写入 `process/checkpoints/`。
11. CP2 / CP3 / CP5 / CP6 / CP7 / CP8 前后的子 agent 交接和人工门禁默认先读取 `process/context/*-CONTEXT.yaml`；只有缺失、冲突、字段不足、人工审计或深度评审时才读取完整正式文档，并记录 `full_doc_read_reason`。

## Agent → Skill 关系

| Agent | 主要阶段 / 场景 | 使用 Skill | 用途 |
|---|---|---|---|
| `host-orchestrator` | `init`、状态推进、变更管理、问题分流、并行调度、检查点控制 | `state-router`、`checkpoint-manager`、`change-impact-analysis`、`issue-routing`、`context-handoff`、`context-manifest-builder`、`review-artifact-protocol` | 推进状态、受理变更、路由问题、装配交接上下文，维护 `context_budget`、`workflow_health`、阶段委托交互、LLD clarification question broker、LLD / Dev / QA 并行队列，生成和收敛 CP0-CP8 检查点，维护 CP2/CP3 discussion log/checkpoint、关键决策门控、结构化 `pending_human_decisions`、Decision Brief、人工门禁发起消息、CP8 follow-up tracking、`cr_tracking` / `CR-INDEX.yaml`、fast-lane、Codex 动态 reasoning profile 路由和自动子 agent 调度证据 |
| `meta-pm` | `requirement-clarification` | `use-case-discovery`、`requirement-clarifier`、`scenario-expansion`、`requirement-extraction`、`scope-normalization`、`story-planning`、`checkpoint-manager`、`review-artifact-protocol` | 被阶段委托期间直接与用户发现**产物类型感知**场景，执行 Scenario Gray Areas、识别真实用户意图、认知盲区、Deferred Ideas 与交付出口，澄清需求歧义，提取需求，展开 `SCENARIOS.yaml` / `TEST-MATRIX.md`，形成 `STORY-MAP.md` / `MVP-SCOPE.md` / `RELEASE-SLICES.md`，确认草案可提交 host-orchestrator，输出 CP1 / CP2 自动检查结果和 CP2 Decision Brief 输入 |
| `meta-se` | `solution-design`、`story-planning` | `blueprint-design`、`hld-designer`、`implementation-design`、`phase-designer`、`dependency-mapper`、`wave-planner`、`story-manager`、`dag-validator`、`checkpoint-manager`、`review-artifact-protocol` | 被阶段委托期间直接与用户完成蓝图适用性判定、Architecture Gray Areas、advisor table-first 讨论和 HLD 草案确认，生成含 Feature / Epic 边界、适用性矩阵、Use Case → Architecture Traceability、场景模拟和自审记录的 HLD；CP3 后拆解 Story、必要时输出 Feature 级设计，建立依赖类型和文件所有权并校验计划 |
| `meta-dev` | `story-planning`、`story-execution` | `lld-designer`、`implementation-execution`、`checkpoint-manager`、`claude-agent-writer`、`review-artifact-protocol` | 按 Story 的 `lld_policy` 输出完整 LLD / 技术说明 / waived 证据和 CP5 自动预检；并行 LLD 中只写 clarification item，由 host-orchestrator broker 提问；等待全部目标 Story 的设计证据统一确认后，在当前 Wave 的 `dev_gate` 满足时调用 `implementation-execution` 生成实现对象清单、设计契约映射、测试 / Fixture 计划、最小实现切片和实现交接摘要，再实现并输出 CP6；CP7 `NEEDS_REWORK` 时按原 Story 范围回修并重提 CP6，`NEEDS_DESIGN_CLARIFICATION` 交由 host-orchestrator 路由回设计澄清 |
| `meta-qa` | `ready-for-verification` 后 | `verification-execution`、`quality-review`、`release-readiness`、`dangerous-command-scan`、`platform-validator`、`package-builder`、`coverage-checker`、`runtime-risk-review`、`permission-boundary-check`、`context-manifest-builder`、`checkpoint-manager`、`review-artifact-protocol` | 执行验证范围确认、验证对象清单、追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、质量验证、安全审计、测试矩阵校验、独立 review、发布就绪检查、安装脚本与安装结构校验，输出 CP7 / CP8 检查结果；发布准备使用 `process/release/RELEASE-CONTEXT.yaml` capsule-first，并按 `release_artifact_profile=minimal|compact|full` 裁剪发布产物；CP7 `NEEDS_REWORK` 时输出可执行缺陷清单供 host-orchestrator 路由回修，`NEEDS_DESIGN_CLARIFICATION` 时交回设计澄清 |
| `meta-doc` | `documentation` | `workflow-renderer`、`review-artifact-protocol` | 将已验证产物组织为可读交付文档，说明 CP0-CP8、关键决策门控、fast-lane、自动子 agent 调度和用户操作，并在 review_mode 复用统一评审协议 |
| `meta-dm`（归档） | 历史 Story 规划 | `phase-designer`、`wave-planner`、`dependency-mapper`、`story-manager`、`dag-validator` | 已从交付面移除，仅保留 `process/archive/meta-dm.md` 供追溯；现由 `meta-se` 接管 |

## Skill → Canonical Agent 关系

| Skill | Canonical Agent | 说明 |
|---|---|---|
| `state-router` | `host-orchestrator` | 状态机推进与回退，并维护 `workflow_mode`、`orchestrator_session.subagent_auto_dispatch`、`delegated_interaction`、`agent_lifecycle.active_agents`、`codex_reasoning_profiles`、子 agent 调度证据、`parallel_execution` 队列、`lld_clarification_queue`、`human_gate_decisions.pending_human_decisions`、`human_gate_decisions.decision_collection_coverage`、`cr_tracking`、CR 状态盘点、依赖门控与复用/关闭登记；Codex 工具面可用时，`mode=subagent` handoff 后必须真实调用 `spawn_agent` / `resume_agent` / `send_input` |
| `checkpoint-manager` | `host-orchestrator` | CP0-CP8 检查点契约、自动检查结果、关键人工审查稿、Decision Brief、Decision Collection Coverage、待人工决策清单和 Human Gate Launch Protocol 的 canonical 规则；CP2 / CP3 校验 discussion log / checkpoint 或 N/A 原因；CP4 为自动预检并汇入 CP5；CP5 校验 clarification 队列收敛；CP8 汇总交付范围、安装验证、文档缺口、遗留风险决策项、不授权范围和后续跟踪分流表；CP6 / CP7 校验 `Agent Dispatch Evidence` |
| `change-impact-analysis` | `host-orchestrator` | 需求/设计变更管理；负责文档处理决策、旧基线映射、CR 执行链路、fast-lane 升级判定、自动终验授权、CP8 follow-up tracking 台账、`CR-INDEX.yaml`、CR 跟踪一致性检查和变更追溯门禁 |
| `issue-routing` | `host-orchestrator` | ISSUE 分类与路由 |
| `context-handoff` | `host-orchestrator` | 阶段切换时的最小上下文装配；默认先传 `process/context/*-CONTEXT.yaml` 与 `context_policy`，支持 `delegated-user-interaction` 与 `lld-clarification-broker` handoff 语义；Codex 默认 `fork_context=false`，只传必要文件与状态片段；handoff frontmatter 必须包含 `dispatch` 区，不能把 handoff 当作执行完成证据 |
| `use-case-discovery` | `meta-pm` | 阶段零调研后的场景发现与 `USE-CASES.md` 生成 / 增量更新，并输出治理字段、交付出口路由、Scenario Gray Areas、`SGQ-*` 用户可见场景确认交互、认知盲区、Deferred Ideas、头脑风暴候选和修订记录 |
| `requirement-clarifier` | `meta-pm` | 多轮澄清需求 |
| `scenario-expansion` | `meta-pm` | 从已确认 use cases / requirements 扩展工程验证场景，输出 `SCENARIOS.yaml` 与 `TEST-MATRIX.md`；不替代 `use-case-discovery` 做上游场景发现 |
| `story-planning` | `meta-pm` | 从 `USE-CASES.md` / `SCENARIOS.yaml` / `REQUIREMENTS.md` 输出 `STORY-MAP.md`、`MVP-SCOPE.md`、`RELEASE-SLICES.md`、`BACKLOG.md` |
| `blueprint-design` | `meta-se` | 从 Story Map / MVP Scope 输出 Feature / Epic 能力边界、领域对象、数据归属和依赖方向 |
| `implementation-design` | `meta-se` | 输出 `docs/design/FEATURE-DESIGN-MATRIX.md`，并为 required Feature / Epic 输出 `features/<feature>/DESIGN.md`、`TEST-PLAN.md`、`TASKS.md`，作为 Story `feature_design_refs`、`lld_policy` 和实现前输入 |
| `requirement-extraction` | `meta-pm` | 结构化需求提取与 `REQUIREMENTS.md` 增量更新 |
| `scope-normalization` | `meta-pm` | 需求归一化与去重 |
| `review-artifact-protocol` | `host-orchestrator` | Review gate 的 findings / summary 模板与结构校验脚本；支持 CP3 advisor table-first 输入，并区分方案形成输入与 HLD 后评审意见 |
| `hld-designer` | `meta-se` | Architecture Gray Areas、advisor discussion 输入和正式 HLD 生成；HLD 模板包含适用性矩阵、Use Case → Architecture Traceability、关键场景模拟和自审记录 |
| `phase-designer` | `meta-se` | 划分执行阶段 |
| `dependency-mapper` | `meta-se` | 建立 Story / 任务依赖 |
| `wave-planner` | `meta-se` | 规划全量设计证据确认后的 Dev / QA Wave 并行策略、依赖类型、dev_gate 和文件所有权门控 |
| `story-manager` | `meta-se` | 生成 Story 卡片、Backlog、Story 状态汇总，并维护依赖类型与文件所有权字段 |
| `dag-validator` | `meta-se` | 校验计划依赖图 |
| `lld-designer` | `meta-dev` | Story 设计证据生成；按 `lld_policy` 输出完整 LLD、Story 技术说明或 waived 证据，并行 LLD 阶段通过 clarification queue 记录实现灰区，输出后等待全部目标 Story 的设计证据统一确认，不直接进入实现 |
| `implementation-execution` | `meta-dev` | Story 实现执行编排；将已确认的设计证据转成实现对象清单、设计契约映射、单元测试 / Fixture 计划、最小实现切片、平台差异检查、集成验证和 QA / Review / Doc 交接摘要；复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / 护栏 / 平台适配 / 发布相关 Story 必须输出 `IMPLEMENTATION.md` |
| `verification-execution` | `meta-qa` | Story 验证执行编排；将需求、场景、设计契约、实现证据和平台约束转为验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题 / 风险和阶段决策；CP7 结论支持 `PASS` / `PASS_WITH_RISK` / `BLOCKED` / `NEEDS_REWORK` / `NEEDS_DESIGN_CLARIFICATION` / `WAIVED` |
| `claude-agent-writer` | `meta-dev` | Claude Agent 产物规范 |
| `dangerous-command-scan` | `meta-qa` | 危险命令与注入风险扫描 |
| `platform-validator` | `meta-qa` | 基于 `delivery/doc/PLATFORM-CONTRACTS.yaml` 校验安装目标、DryRun 和 Codex 禁止路径 |
| `package-builder` | `meta-qa` | 基于 `delivery/doc/PLATFORM-CONTRACTS.yaml` 生成平台安装脚本 |
| `coverage-checker` | `meta-qa` | 覆盖度检查 |
| `runtime-risk-review` | `meta-qa` | 运行时风险复核 |
| `permission-boundary-check` | `meta-qa` | 权限边界检查 |
| `context-manifest-builder` | `host-orchestrator` / `meta-qa` | 生成 CP2 / CP3 / CP5 / CP6 / CP7 / CP8 阶段上下文胶囊 `process/context/*-CONTEXT.yaml`，交付阶段可额外生成 `CONTEXT-MANIFEST.yaml`；用于 capsule-first 和 token budget 控制 |
| `quality-review` | `meta-qa` | 独立质量验证、测试报告、代码评审和修复输入 |
| `release-readiness` | `meta-qa` | 发布上下文胶囊、发布说明、部署检查、回滚、迁移、反馈回流、`release_artifact_profile` 和 `release_decision` |
| `workflow-renderer` | `meta-doc` | 交付文档渲染 |
| `issue-drafter` | 问题处理链路 | 常与 `issue-routing`、`change-impact-analysis` 配合 |
| `run-feedback-parser` | 执行反馈链路 | 常为 `issue-drafter` / `issue-routing` 上游 |
| `file-to-markdown` | 文档导入链路 | 按需用于外部资料转 Markdown |
| `regression-subset-builder` | 修复验证链路 | 问题修复后收缩回归范围 |

## `meta-pm` 相邻 Skill 边界

| Skill | 主输入 / 主输出 | 边界说明 |
|---|---|---|
| `use-case-discovery` | `REQUEST.md`、`INPUT-INDEX.md`、`CLARIFICATION-LOG.md`、`USE-CASES.md`、`CR-*.md` → `USE-CASES.md`、`process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md`、`process/checks/CP2-DISCUSSION-CHECKPOINT.json` | 负责发现、补全、确认用户使用场景，处理 Scenario Gray Areas、`SGQ-*` 用户可见场景确认、认知盲区和 Deferred Ideas，并维护治理字段、覆盖自检表与修订记录；不提取需求条目 |
| `requirement-clarifier` | `REQUEST.md`、`REQUIREMENTS.md`、`CLARIFICATION-LOG.md` → `CLARIFICATION-LOG.md` | 只处理需求歧义、未决问题和澄清轮次；不替代场景发现 |
| `requirement-extraction` | `USE-CASES.md` / `REQUEST.md` / `CR-*.md` → `REQUIREMENTS.md` | 直接消费正式场景工件及其治理字段提取需求；CR 更新时保留旧需求基线，不重做场景访谈 |
| `scenario-expansion` | `USE-CASES.md` / `REQUIREMENTS.md` → `SCENARIOS.yaml`、`TEST-MATRIX.md` | 面向工程测试覆盖与验证场景；不用于用户场景发现或需求歧义澄清 |

## 非正式 / 未交付占位说明

以下名称曾在个别 Agent 提示词中出现，但**当前不在 `skills/` 目录中交付**，因此不纳入正式映射：

- `vendor-profile-loader`
- `constraint-normalizer`

## 检视记录（2026-04-22）

1. 已删除废弃 Skill `solution-designer`；HLD 设计的 canonical Skill 仅保留 `hld-designer`。
2. `vendor-profile-loader`、`constraint-normalizer` 已从 active Agent 提示词中清理；若历史文档仍出现，只能作为旧方案追溯，不得作为可调用 Skill 使用。

## Skill 模板交叉引用

> 本章节记录 Skill 间因消费同一正式工件而产生的模板交叉引用关系。
> 消费者 Skill 不直接引用模板路径，只依赖产出 Skill 写入工作区正式工件的内容契约。

| 正式工件 | 模板持有 Skill | 消费者 Skill | 说明 |
|---|---|---|---|
| `CR-*.md` / `CR-*-FOLLOW-UP-TRACKING-*.md` | `change-impact-analysis` | `issue-routing`、`state-router`、`use-case-discovery`、`requirement-extraction`、`checkpoint-manager` | `change-impact-analysis` 维护文档处理决策、旧基线映射、执行链路、自动终验授权和后续事项台账；`state-router` 消费 CR 执行链与预授权条件做检查点恢复和状态推进，下游按文档处理决策做增量更新；`checkpoint-manager` 在 CP8 中汇总台账分流 |
| `USE-CASES.md` | `use-case-discovery` | `requirement-extraction` | `use-case-discovery` 维护正式场景工件、治理字段、覆盖自检表与修订记录；`requirement-extraction` 直接消费该工件 |
| `SCENARIOS.yaml` / `TEST-MATRIX.md` | `scenario-expansion` | `story-planning`、`implementation-design`、`implementation-execution`、`verification-execution`、`quality-review`、`meta-qa` | `scenario-expansion` 将已确认场景和需求展开为工程验证场景与测试覆盖矩阵；下游按场景 ID / Story ID / Requirement ID 判断覆盖缺口 |
| `STORY-MAP.md` / `MVP-SCOPE.md` / `RELEASE-SLICES.md` / `BACKLOG.md` | `story-planning` | `blueprint-design`、`hld-designer`、`checkpoint-manager` | 产品规划产物用于 CP2 范围确认和 CP3 蓝图 / 架构设计输入；不包含底层实现步骤 |
| `BLUEPRINT.md` / `DOMAIN-MAP.md` / `DEPENDENCY-MAP.md` | `blueprint-design` | `hld-designer`、`implementation-design`、`dependency-mapper`、`wave-planner` | 蓝图产物定义 Feature / Epic 边界、领域对象、数据归属和依赖方向；HLD 消费其边界但仍负责系统架构 |
| `FEATURE-DESIGN-MATRIX.md` | `implementation-design` | `story-manager`、`lld-designer`、`implementation-execution`、`checkpoint-manager`、`state-router`、`host-orchestrator` | Feature 设计适用性矩阵用于判定 required / waived / n/a、Story `feature_design_refs` 与 `lld_policy`；CP4 必须消费它，CP5 必须汇总其设计证据分布，CP6 必须消费其实现证据形态 |
| `features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md` | `implementation-design` | `story-manager`、`lld-designer`、`implementation-execution`、`meta-dev`、`quality-review` | Feature 级实现设计用于 Story 设计证据、任务拆分与测试计划；高风险 Story 仍需 `full-lld`，低风险 Story 可用 Story 技术说明；实现阶段必须把其中的契约、测试计划和任务切片映射到实现证据 |
| `CP2-SCENARIO-DISCUSSION-LOG.md` / `CP2-DISCUSSION-CHECKPOINT.json` | `use-case-discovery` / `checkpoint-manager` | `host-orchestrator`、`checkpoint-manager`、`hld-designer` | 记录 Scenario Gray Areas、`SGQ-*` 用户可见场景确认交互、用户选择、freeform 确认、Deferred Ideas 和 canonical refs；用于审计和恢复，不替代 `USE-CASES.md` / `REQUIREMENTS.md` |
| `REQUIREMENTS.md` | `requirement-extraction` | `scope-normalization` | `requirement-extraction` 维护需求条目、修订记录与变更记录；`scope-normalization` 归一化已生成的需求 |
| `CLARIFICATION-LOG.md` | `requirement-clarifier` | `use-case-discovery` | 澄清轮次由 `requirement-clarifier` 维护；场景发现摘要由 `use-case-discovery` 追加 |
| `Review Findings / Review Summary` | `review-artifact-protocol` | `host-orchestrator`、`meta-pm`、`meta-se`、`meta-dev`、`meta-qa`、`meta-doc` | review gate 的共享模板与 validator 由公共 Skill 持有，reviewer lane 输出 findings，summary 提供 Decision Brief 输入；需要人工确认的 review 结论必须带推荐方案、至少 1 个备选方案和优劣分析 |
| `HLD.md` | `hld-designer` | `host-orchestrator`、`checkpoint-manager`、`phase-designer`、`story-manager` | HLD 模板持有 Architecture Gray Areas、适用性矩阵、Use Case → Architecture Traceability、关键场景模拟和自审结构；CP3 通过后作为 Story 拆解输入 |
| `CP3-HLD-DISCUSSION-LOG.md` / `CP3-DISCUSSION-CHECKPOINT.json` | `hld-designer` / `review-artifact-protocol` / `checkpoint-manager` | `host-orchestrator`、`checkpoint-manager`、`hld-designer` | 记录 Architecture Gray Areas、advisor table、方案形成输入、HLD 后审查意见和切换条件；用于审计和恢复，不替代正式 HLD / ADR / Decision Brief |
| `CP0-CP8 检查结果` | `checkpoint-manager` | `state-router`、`host-orchestrator`、`meta-pm`、`meta-se`、`meta-dev`、`meta-qa`、`meta-doc` | 自动检查结果写 `process/checks/CP*.md`；CP2 / CP3 / CP5 / CP8 人工审查稿写 `process/checkpoints/CP*.md`；CP4 自动结果汇入 CP5；人工门禁发起前必须通过 Decision Brief 与发起消息校验；state-router 以结果文件判定是否可推进 |
| `STATE.md` | `state-router` | `checkpoint-manager`、`context-handoff`、`context-manifest-builder` | `STATE.md.orchestrator_session` 保存唯一 `host-orchestrator` 会话、自动子 agent 调度授权、人工确认恢复和 recovery 证据；`STATE.md.context_budget` 保存 capsule-first、read_profile、全文档读取理由和 `process/context/*-CONTEXT.yaml` 索引；`STATE.md.workflow_health` 保存循环 / 卡顿 / 回修计数器与阈值；`STATE.md.human_gate_decisions` 保存 CP2 / CP3 / CP5 / CP8 的结构化待人工决策队列、Decision Collection Coverage、不授权项和 follow-up 台账路径；`STATE.md.delegated_interaction` 保存阶段委托交互；`STATE.md.checkpoints` 保存每个 CP 的结果文件路径和同步状态；`parallel_execution.lld_clarification_queue` 保存 LLD 实现灰区队列；`agent_lifecycle.active_agents` 保存功能子 agent 调度证据，Codex 下同时保存 `codex_agent_name`、`reasoning_profile`、`dispatch_trigger` 和真实工具证据 |
| `process/context/*-CONTEXT.yaml` | `context-manifest-builder` | `context-handoff`、`checkpoint-manager`、`state-router`、`host-orchestrator`、各功能 Agent | 阶段上下文胶囊是子 agent 和人工门禁默认读取入口；包含 `must_read`、`read_if_needed`、`do_not_read_by_default`、关键事实、风险 / 决策和读取扩展日志；不替代正式产物，冲突时以正式产物为准 |
| `STORY-*.md` | `story-manager` | `state-router`、`wave-planner`、`lld-designer`、`implementation-execution`、`verification-execution`、`meta-dev`、`meta-qa`、`host-orchestrator` | Story 卡片包含依赖类型、file_ownership、`feature_design_refs`、`lld_policy`、`lld_gate`、`dev_gate`、`implementation_gate` 和 `verification_gate`；`technical-note` / `waived` 的正式设计证据也写在 Story 卡片中，低风险 Story 可在卡片内记录实现和验证摘要 |
| `STORY-*-LLD.md` | `lld-designer` | `implementation-execution`、`verification-execution`、`meta-dev`、`host-orchestrator`、`meta-qa` | 仅 `lld_policy.required_level=full-lld` 的 Story 使用该模板；包含“实现灰区与取舍记录”，全部目标 Story 的完整 LLD / 技术说明 / waived 证据统一确认后，开发与验证均直接消费对应工件 |
| `STORY-*-IMPLEMENTATION.md` / `docs/features/<feature>/IMPLEMENTATION.md` | `implementation-execution` | `checkpoint-manager`、`state-router`、`verification-execution`、`quality-review`、`meta-qa`、`meta-doc` | 实现执行证据记录实现对象清单、设计契约映射、测试 / Fixture 计划、最小实现切片、平台差异、本地验证、未覆盖项、回滚和交接摘要；CP6 必须消费，CP7 / 文档阶段用于验证和交付说明 |
| `VERIFICATION-REPORT.md` / `docs/features/<feature>/VERIFICATION.md` | `verification-execution` | `checkpoint-manager`、`state-router`、`quality-review`、`host-orchestrator`、`release-readiness`、`meta-doc` | 验证执行证据记录验证范围、对象清单、追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题、剩余风险和阶段决策；CP7 必须消费，`PASS_WITH_RISK` 必须进入 CP8 风险接受输入 |
| `TEST-REPORT.md` / `REVIEW.md` / `FIXES.md` | `quality-review` | `meta-qa`、`host-orchestrator`、`release-readiness` | 质量评审产物记录测试命令、覆盖缺口、findings、语义审查和回修 / 设计澄清输入；发布准备必须消费其结论 |
| `RELEASE-CONTEXT.yaml` / `RELEASE-NOTES.md` / `DEPLOY-CHECKLIST.md` / `ROLLBACK.md` / `MIGRATION.md` / `FEEDBACK.md` | `release-readiness` | `host-orchestrator`、`checkpoint-manager`、`meta-doc` | 发布准备采用 `process/release/RELEASE-CONTEXT.yaml` capsule-first，按 `release_artifact_profile=minimal|compact|full` 控制文档厚度，并输出 `release_decision=READY|READY_WITH_RISK|NOT_READY|RELEASED|FAILED`；CP8 Decision Brief 消费其摘要；`FEEDBACK.md` 只是反馈入口，不替代 `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md`，需要后续 CR 的事项必须同步 `STATE.md.cr_tracking` |

## Reviewer Dispatch

| Reviewer lane | Primary agent | Default focus | Typical targets |
|---|---|---|---|
| `lane-product` | `meta-pm` | 场景覆盖、画像、成功指标、范围一致性、原始需求 / 场景基线保留和修订记录 | `USE-CASES.md`、`REQUIREMENTS.md`、场景密集型 HLD 章节 |
| `lane-architecture` | `meta-se` | Architecture Gray Areas、边界、依赖、ADR 与计划一致性 | `HLD.md`、`ARCHITECTURE-DECISION.md`、`STORY-BACKLOG.md`、`STORY-*-LLD.md` |
| `lane-implementation` | `meta-dev` | 可实现性、文件归属、平台约束、实现对象与契约闭环 | `STORY-*-LLD.md`、`STORY-*-IMPLEMENTATION.md`、Agent / Skill 设计稿、安装规格 |
| `lane-quality` | `meta-qa` | 可验证性、失败路径、安全、安装风险和阶段决策 | `STORY-*-LLD.md`、`VERIFICATION-REPORT.md`、验证文档、安装清单 |
| `lane-docs` | `meta-doc` | 可读性、用户说明与交付完整性 | `README.md`、`USER-MANUAL.md`、操作手册 |

## Review Gate Rollout

1. 第 1 阶段：先覆盖 `HLD.md` 与 `STORY-*-LLD.md`。
2. 第 2 阶段：扩展到 `ARCHITECTURE-DECISION.md` 与 `STORY-BACKLOG.md`。
3. 第 3 阶段：扩展到 `README.md`、`USER-MANUAL.md` 与发布文档。

Review-gated 产物默认复用 `review-artifact-protocol` Skill 提供的模板，并可通过其 `scripts/validate_review_artifact.py` 做结构校验。

CP3 advisor discussion 默认使用 table-first 输入：`Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch`。方案形成输入和 HLD 后评审意见必须分开记录。
