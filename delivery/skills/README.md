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
9. 涉及功能 Agent 调度的 Skill 必须区分 handoff 与真实执行证据；CP6 / CP7 必须读取 `Agent Dispatch Evidence`，不得用 handoff 文件替代子 agent 运行结果。

## Agent → Skill 关系

| Agent | 主要阶段 / 场景 | 使用 Skill | 用途 |
|---|---|---|---|
| `meta-po` | `init`、状态推进、变更管理、问题分流、并行调度、检查点控制 | `state-router`、`checkpoint-manager`、`change-impact-analysis`、`issue-routing`、`context-handoff`、`review-artifact-protocol` | 推进状态、受理变更、路由问题、装配交接上下文，维护阶段委托交互、LLD clarification question broker、LLD / Dev / QA 并行队列，生成和收敛 CP0-CP8 检查点，维护 CP2/CP3 discussion log/checkpoint、关键决策门控、Decision Brief、待人工决策清单、fast-lane 和自动子 agent 调度证据 |
| `meta-pm` | `requirement-clarification` | `use-case-discovery`、`requirement-clarifier`、`scenario-expansion`、`requirement-extraction`、`scope-normalization`、`checkpoint-manager`、`review-artifact-protocol` | 被阶段委托期间直接与用户发现**产物类型感知**场景，执行 Scenario Gray Areas、识别真实用户意图、认知盲区、Deferred Ideas 与交付出口，澄清需求歧义、提取需求、确认草案可提交 meta-po，输出 CP1 / CP2 自动检查结果和 CP2 Decision Brief 输入 |
| `meta-se` | `solution-design`、`story-planning` | `hld-designer`、`phase-designer`、`dependency-mapper`、`wave-planner`、`story-manager`、`dag-validator`、`checkpoint-manager`、`review-artifact-protocol` | 被阶段委托期间直接与用户完成 Architecture Gray Areas、advisor table-first 讨论和 HLD 草案确认，生成含适用性矩阵、Use Case → Architecture Traceability、场景模拟和自审记录的 HLD；CP3 后拆解 Story、建立依赖类型和文件所有权并校验计划 |
| `meta-dev` | `story-planning`、`story-execution` | `lld-designer`、`checkpoint-manager`、`claude-agent-writer`、`review-artifact-protocol` | 按 Story 输出 LLD 和 CP5 自动预检；并行 LLD 中只写 clarification item，由 meta-po broker 提问；等待全部目标 Story 的 LLD 统一确认后，在当前 Wave 的 `dev_gate` 满足时实现并输出 CP6；CP7 失败时按原 Story 范围回修并重提 CP6 |
| `meta-qa` | `ready-for-verification` 后 | `dangerous-command-scan`、`platform-validator`、`package-builder`、`coverage-checker`、`runtime-risk-review`、`permission-boundary-check`、`context-manifest-builder`、`checkpoint-manager`、`review-artifact-protocol` | 执行质量验证、安全审计、安装脚本与安装结构校验，输出 CP7 / CP8 检查结果；CP7 失败时输出可执行缺陷清单供 meta-po 路由回修 |
| `meta-doc` | `documentation` | `workflow-renderer`、`review-artifact-protocol` | 将已验证产物组织为可读交付文档，说明 CP0-CP8、关键决策门控、fast-lane、自动子 agent 调度和用户操作，并在 review_mode 复用统一评审协议 |
| `meta-dm`（已废弃） | 历史 Story 规划 | `phase-designer`、`wave-planner`、`dependency-mapper`、`story-manager`、`dag-validator` | 仅供历史参考，现由 `meta-se` 接管 |

## Skill → Canonical Agent 关系

| Skill | Canonical Agent | 说明 |
|---|---|---|
| `state-router` | `meta-po` | 状态机推进与回退，并维护 `workflow_mode`、`orchestrator_session.subagent_auto_dispatch`、`delegated_interaction`、`agent_lifecycle.active_agents`、子 agent 调度证据、`parallel_execution` 队列、`lld_clarification_queue`、依赖门控与复用/关闭登记 |
| `checkpoint-manager` | `meta-po` | CP0-CP8 检查点契约、自动检查结果、关键人工审查稿、Decision Brief 和待人工决策清单的 canonical 规则；CP2 / CP3 校验 discussion log / checkpoint 或 N/A 原因；CP4 为自动预检并汇入 CP5；CP5 校验 clarification 队列收敛；CP8 汇总交付范围、安装验证、文档缺口和遗留风险决策项；CP6 / CP7 校验 `Agent Dispatch Evidence` |
| `change-impact-analysis` | `meta-po` | 需求/设计变更管理；负责文档处理决策、旧基线映射、CR 执行链路、fast-lane 升级判定、自动终验授权和变更追溯门禁 |
| `issue-routing` | `meta-po` | ISSUE 分类与路由 |
| `context-handoff` | `meta-po` | 阶段切换时的最小上下文装配；支持 `delegated-user-interaction` 与 `lld-clarification-broker` handoff 语义；Codex 默认 `fork_context=false`，只传必要文件与状态片段；handoff frontmatter 必须包含 `dispatch` 区，不能把 handoff 当作执行完成证据 |
| `use-case-discovery` | `meta-pm` | 阶段零调研后的场景发现与 `USE-CASES.md` 生成 / 增量更新，并输出治理字段、交付出口路由、Scenario Gray Areas、认知盲区、Deferred Ideas、头脑风暴候选和修订记录 |
| `requirement-clarifier` | `meta-pm` | 多轮澄清需求 |
| `scenario-expansion` | `meta-pm` | 从需求扩展使用场景 |
| `requirement-extraction` | `meta-pm` | 结构化需求提取与 `REQUIREMENTS.md` 增量更新 |
| `scope-normalization` | `meta-pm` | 需求归一化与去重 |
| `review-artifact-protocol` | `meta-po` | Review gate 的 findings / summary 模板与结构校验脚本；支持 CP3 advisor table-first 输入，并区分方案形成输入与 HLD 后评审意见 |
| `hld-designer` | `meta-se` | Architecture Gray Areas、advisor discussion 输入和正式 HLD 生成；HLD 模板包含适用性矩阵、Use Case → Architecture Traceability、关键场景模拟和自审记录 |
| `phase-designer` | `meta-se` | 划分执行阶段 |
| `dependency-mapper` | `meta-se` | 建立 Story / 任务依赖 |
| `wave-planner` | `meta-se` | 规划全量 LLD 后的 Dev / QA Wave 并行策略、依赖类型、dev_gate 和文件所有权门控 |
| `story-manager` | `meta-se` | 生成 Story 卡片、Backlog、Story 状态汇总，并维护依赖类型与文件所有权字段 |
| `dag-validator` | `meta-se` | 校验计划依赖图 |
| `lld-designer` | `meta-dev` | Story LLD 设计；并行 LLD 阶段通过 clarification queue 记录实现灰区，输出后等待全部目标 Story 的 LLD 统一确认，不直接进入实现 |
| `claude-agent-writer` | `meta-dev` | Claude Agent 产物规范 |
| `dangerous-command-scan` | `meta-qa` | 危险命令与注入风险扫描 |
| `platform-validator` | `meta-qa` | 基于 `delivery/doc/PLATFORM-CONTRACTS.yaml` 校验安装目标、DryRun 和 Codex 禁止路径 |
| `package-builder` | `meta-qa` | 基于 `delivery/doc/PLATFORM-CONTRACTS.yaml` 生成平台安装脚本 |
| `coverage-checker` | `meta-qa` | 覆盖度检查 |
| `runtime-risk-review` | `meta-qa` | 运行时风险复核 |
| `permission-boundary-check` | `meta-qa` | 权限边界检查 |
| `context-manifest-builder` | `meta-qa` | 生成执行上下文清单 |
| `workflow-renderer` | `meta-doc` | 交付文档渲染 |
| `issue-drafter` | 问题处理链路 | 常与 `issue-routing`、`change-impact-analysis` 配合 |
| `run-feedback-parser` | 执行反馈链路 | 常为 `issue-drafter` / `issue-routing` 上游 |
| `file-to-markdown` | 文档导入链路 | 按需用于外部资料转 Markdown |
| `regression-subset-builder` | 修复验证链路 | 问题修复后收缩回归范围 |

## `meta-pm` 相邻 Skill 边界

| Skill | 主输入 / 主输出 | 边界说明 |
|---|---|---|
| `use-case-discovery` | `REQUEST.md`、`INPUT-INDEX.md`、`CLARIFICATION-LOG.md`、`USE-CASES.md`、`CR-*.md` → `USE-CASES.md`、`process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md`、`process/checks/CP2-DISCUSSION-CHECKPOINT.json` | 负责发现、补全、确认用户使用场景，处理 Scenario Gray Areas、认知盲区和 Deferred Ideas，并维护治理字段、覆盖自检表与修订记录；不提取需求条目 |
| `requirement-clarifier` | `REQUEST.md`、`REQUIREMENTS.md`、`CLARIFICATION-LOG.md` → `CLARIFICATION-LOG.md` | 只处理需求歧义、未决问题和澄清轮次；不替代场景发现 |
| `requirement-extraction` | `USE-CASES.md` / `REQUEST.md` / `CR-*.md` → `REQUIREMENTS.md` | 直接消费正式场景工件及其治理字段提取需求；CR 更新时保留旧需求基线，不重做场景访谈 |
| `scenario-expansion` | `REQUIREMENTS.md` → `SCENARIOS.yaml`、`TEST-MATRIX.md` | 面向测试覆盖与验证场景；不用于用户场景发现或需求歧义澄清 |

## 非正式 / 未交付占位说明

以下名称曾在个别 Agent 提示词中出现，但**当前不在 `skills/` 目录中交付**，因此不纳入正式映射：

- `vendor-profile-loader`
- `constraint-normalizer`

## 检视记录（2026-04-22）

1. 已删除废弃 Skill `solution-designer`；HLD 设计的 canonical Skill 仅保留 `hld-designer`。
2. `vendor-profile-loader`、`constraint-normalizer` 仍在部分 Agent 提示词或历史文档中出现，但它们不是 `skills/` 目录下的正式交付 Skill；后续若继续收敛，应统一清理这些非正式占位引用。

## Skill 模板交叉引用

> 本章节记录 Skill 间因消费同一正式工件而产生的模板交叉引用关系。
> 消费者 Skill 不直接引用模板路径，只依赖产出 Skill 写入工作区正式工件的内容契约。

| 正式工件 | 模板持有 Skill | 消费者 Skill | 说明 |
|---|---|---|---|
| `CR-*.md` | `change-impact-analysis` | `issue-routing`、`state-router`、`use-case-discovery`、`requirement-extraction` | `change-impact-analysis` 维护文档处理决策、旧基线映射、执行链路和自动终验授权；`state-router` 消费 CR 执行链与预授权条件做检查点恢复和状态推进，下游按文档处理决策做增量更新 |
| `USE-CASES.md` | `use-case-discovery` | `requirement-extraction` | `use-case-discovery` 维护正式场景工件、治理字段、覆盖自检表与修订记录；`requirement-extraction` 直接消费该工件 |
| `CP2-SCENARIO-DISCUSSION-LOG.md` / `CP2-DISCUSSION-CHECKPOINT.json` | `use-case-discovery` / `checkpoint-manager` | `meta-po`、`checkpoint-manager`、`hld-designer` | 记录 Scenario Gray Areas、用户选择、freeform 确认、Deferred Ideas 和 canonical refs；用于审计和恢复，不替代 `USE-CASES.md` / `REQUIREMENTS.md` |
| `REQUIREMENTS.md` | `requirement-extraction` | `scope-normalization` | `requirement-extraction` 维护需求条目、修订记录与变更记录；`scope-normalization` 归一化已生成的需求 |
| `CLARIFICATION-LOG.md` | `requirement-clarifier` | `use-case-discovery` | 澄清轮次由 `requirement-clarifier` 维护；场景发现摘要由 `use-case-discovery` 追加 |
| `Review Findings / Review Summary` | `review-artifact-protocol` | `meta-po`、`meta-pm`、`meta-se`、`meta-dev`、`meta-qa`、`meta-doc` | review gate 的共享模板与 validator 由公共 Skill 持有，reviewer lane 输出 findings，summary 提供 Decision Brief 输入；需要人工确认的 review 结论必须带推荐方案、至少 1 个备选方案和优劣分析 |
| `HLD.md` | `hld-designer` | `meta-po`、`checkpoint-manager`、`phase-designer`、`story-manager` | HLD 模板持有 Architecture Gray Areas、适用性矩阵、Use Case → Architecture Traceability、关键场景模拟和自审结构；CP3 通过后作为 Story 拆解输入 |
| `CP3-HLD-DISCUSSION-LOG.md` / `CP3-DISCUSSION-CHECKPOINT.json` | `hld-designer` / `review-artifact-protocol` / `checkpoint-manager` | `meta-po`、`checkpoint-manager`、`hld-designer` | 记录 Architecture Gray Areas、advisor table、方案形成输入、HLD 后审查意见和切换条件；用于审计和恢复，不替代正式 HLD / ADR / Decision Brief |
| `CP0-CP8 检查结果` | `checkpoint-manager` | `state-router`、`meta-po`、`meta-pm`、`meta-se`、`meta-dev`、`meta-qa`、`meta-doc` | 自动检查结果写 `process/checks/CP*.md`；CP2 / CP3 / CP5 / CP8 人工审查稿写 `checkpoints/CP*.md`；CP4 自动结果汇入 CP5；state-router 以结果文件判定是否可推进 |
| `STATE.md` | `state-router` | `checkpoint-manager`、`context-handoff` | `STATE.md.orchestrator_session` 保存唯一 `meta-po` 会话、自动子 agent 调度授权、人工确认恢复和 recovery 证据；`STATE.md.delegated_interaction` 保存阶段委托交互；`STATE.md.checkpoints` 保存每个 CP 的结果文件路径和同步状态；`parallel_execution.lld_clarification_queue` 保存 LLD 实现灰区队列；`agent_lifecycle.active_agents` 保存功能子 agent 调度证据 |
| `STORY-*.md` | `story-manager` | `state-router`、`wave-planner`、`meta-dev`、`meta-po` | Story 卡片包含依赖类型、file_ownership、lld_gate、dev_gate，是并行队列计算输入 |
| `STORY-*-LLD.md` | `lld-designer` | `meta-dev`、`meta-po`、`meta-qa` | LLD 由 `lld-designer` 模板持有；包含“实现灰区与取舍记录”，全部目标 Story 的 LLD 统一确认后，开发与验证均直接消费该工件 |

## Reviewer Dispatch

| Reviewer lane | Primary agent | Default focus | Typical targets |
|---|---|---|---|
| `lane-product` | `meta-pm` | 场景覆盖、画像、成功指标、范围一致性、原始需求 / 场景基线保留和修订记录 | `USE-CASES.md`、`REQUIREMENTS.md`、场景密集型 HLD 章节 |
| `lane-architecture` | `meta-se` | Architecture Gray Areas、边界、依赖、ADR 与计划一致性 | `HLD.md`、`ARCHITECTURE-DECISION.md`、`STORY-BACKLOG.md`、`STORY-*-LLD.md` |
| `lane-implementation` | `meta-dev` | 可实现性、文件归属、平台约束 | `STORY-*-LLD.md`、Agent / Skill 设计稿、安装规格 |
| `lane-quality` | `meta-qa` | 可验证性、失败路径、安全与安装风险 | `STORY-*-LLD.md`、验证文档、安装清单 |
| `lane-docs` | `meta-doc` | 可读性、用户说明与交付完整性 | `README.md`、`USER-MANUAL.md`、操作手册 |

## Review Gate Rollout

1. 第 1 阶段：先覆盖 `HLD.md` 与 `STORY-*-LLD.md`。
2. 第 2 阶段：扩展到 `ARCHITECTURE-DECISION.md` 与 `STORY-BACKLOG.md`。
3. 第 3 阶段：扩展到 `README.md`、`USER-MANUAL.md` 与发布文档。

Review-gated 产物默认复用 `review-artifact-protocol` Skill 提供的模板，并可通过其 `scripts/validate_review_artifact.py` 做结构校验。

CP3 advisor discussion 默认使用 table-first 输入：`Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch`。方案形成输入和 HLD 后评审意见必须分开记录。
