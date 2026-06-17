# Meta Flow USER-MANUAL

## 1. 安装前准备

- Python 入口统一使用 `uv run --python 3.11 python ...`
- 若从源码仓库根目录执行，安装器路径是 `delivery/scripts/install.py`
- 若 `delivery/` 已作为独立仓库分发，安装器路径是 `scripts/install.py`
- 平台安装路径以 `doc/PLATFORM-CONTRACTS.yaml` 为真相源，README 与本手册只是派生说明

## 2. 常用安装命令

全局命令方式（推荐本地开发使用 editable，以便命令读取当前 checkout 的 `delivery/` 资产）：

```bash
uv tool install --editable .
meta-flow install codex --scope user
meta-flow install codex --scope project --project-dir /path/to/project
```

项目级安装未提供 `--project-dir` 时，交互式终端会提示确认当前目录或输入其他目录；非交互环境必须显式传入 `--project-dir`。

多层级帮助：

```bash
meta-flow --help
meta-flow install --help
meta-flow install codex --help
meta-flow uninstall --help
meta-flow uninstall codex --help
```

从仓库根目录执行：

```bash
uv run --python 3.11 python delivery/scripts/install.py claude
uv run --python 3.11 python delivery/scripts/install.py codex --project-dir /path/to/project
uv run --python 3.11 python delivery/scripts/install.py openclaw --dry-run
```

从 `delivery/` 目录执行：

```bash
cd delivery
uv run --python 3.11 python scripts/install.py claude
uv run --python 3.11 python scripts/install.py codex --scope user
```

包装脚本：

```powershell
scripts\install.ps1 codex --dry-run
```

```bash
bash scripts/install.sh claude --dry-run
```

## 3. 安装内容

- `rules`：平台规则入口（AGENTS.md / CLAUDE.md 等）
- `agent`：平台 Agent 定义 + Skill 定义与 Skill 私有运行时资产
- `full`：同时安装 rules 与 agent

可通过 `--component rules|agent|full` 控制安装范围。默认值：

- `--scope user` 默认只安装 `rules`
- `--scope project` 默认安装 `full`
- `meta-flow uninstall <platform>` 未指定 `--component` 时默认卸载 `full`

legacy `--content agents|skills|rules|all` 保留兼容，但新文档优先使用 `--component`。

## 3.1 Agent 命令与显示区分

canonical role 只覆盖功能子 agent，用于状态机、handoff、检查点和审计。Host Orchestrator 是当前会话主进程职责，不安装为 Codex / Claude Code agent 文件。平台展示按下表安装：

| canonical role | Codex 命令 / nickname_candidates | Claude Code color |
|---|---|---|
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `orange` |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `yellow` |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu`、`dev-he`、`dev-lv`、`dev-shi`、`dev-zhang`、`dev-kong` | `green` |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong`、`qa-cao`、`qa-yan`、`qa-hua`、`qa-jin`、`qa-wei` | `cyan` |
| `meta-doc` | `doc-cao`、`doc-yan`、`doc-hua`、`doc-jin`、`doc-wei` | `purple` |

Codex 安装器把命令别名写入 `.codex/agents/*.toml` 的 `nickname_candidates`。Claude Code 文件型 subagent 不使用 nickname，安装器写入 `color` 字段，通过颜色区分不同子 agent。

## 4. DryRun 与卸载

全局命令方式：

```bash
meta-flow uninstall codex --scope user
meta-flow uninstall codex --scope project --project-dir /path/to/project
meta-flow uninstall claude --scope user --component rules --dry-run
```

脚本入口方式：

```bash
uv run --python 3.11 python delivery/scripts/install.py claude --dry-run
uv run --python 3.11 python delivery/scripts/install.py uninstall codex --scope user
```

`meta-flow uninstall <platform>` 依赖 `~/.meta-flow/delivery/doc/INSTALL-MANIFEST.yaml` 中记录的 `platform + scope + workspace_root` 精确移除已安装文件。默认 `--component full`，也可以使用 `--component rules|agent|full` 卸载对应组件；项目级卸载必须传入和安装时一致的 `--project-dir`，否则无法匹配 manifest 里的 workspace。

如果要移除 `meta-flow` 这个全局命令本身，而不是卸载已写入 Claude Code / Codex / OpenClaw 的规则、Agent 或 Skill，使用：

```bash
uv tool uninstall meta-flow
```

## 5. 默认安装位置

| 平台 | 项目级 Agent | 项目级 Skill | 用户级 Agent | 用户级 Skill |
|------|---------------|---------------|--------------|--------------|
| Claude Code | `<project>/.claude/agents/` | `<project>/.claude/skills/` | `~/.claude/agents/` | `~/.claude/skills/` |
| Codex | `<project>/.codex/agents/` | `<project>/.agents/skills/` | `~/.codex/agents/` | `~/.agents/skills/` |
| OpenClaw | `<project>/.openclaw/agents/` | `<project>/.openclaw/skills/` | `~/.openclaw/agents/` | `~/.openclaw/skills/` |

Codex Skill 不安装到 `.codex/skills` 或 `~/.codex/skills`；安装器 dry-run 和 guardrail 会检查这个负向断言。

如果安装失败并提示 `安装路径被非目录占用: <path>`，说明目标安装目录的某一级已被普通文件占用。请删除、移动或重命名该文件后重试。

## 6. 快速使用 meta-flow

主编排器是当前会话的 Host Orchestrator。首次启动一个正式交付工作流时，建议直接给出目标、平台和约束：

```text
开始
目标：为 <agent / skill / workflow 名称> 产出正式方案
平台：Claude Code、Codex
要求：先澄清需求，再给我 HLD，确认后再拆 Story
```

常用控制语句：

```text
当前状态
下一步
继续
快速修改
回退到 CP3 蓝图 / HLD 架构评审前
```

### 6.0 输出目录

Meta Flow 生成的文档默认分为三类：

| 类型 | 默认目录 | 典型文件 |
|---|---|---|
| 长期可交付文档 | `docs/` | `docs/product/USE-CASES.md`、`docs/design/HLD.md`、`docs/features/<feature>/DESIGN.md`、`docs/quality/TEST-REPORT.md`、`docs/release/DEPLOY-CHECKLIST.md` |
| 运行过程文档 | `process/` | `process/STATE.md`、`process/REQUEST.md`、`process/STORY-BACKLOG.md`、`process/DEVELOPMENT-PLAN.yaml`、`process/stories/STORY-*.md`、`process/stories/STORY-*-IMPLEMENTATION.md`、`process/changes/CR-*.md` |
| 人工确认态 | `process/checkpoints/` | `process/checkpoints/CP2-REQUIREMENTS-BASELINE.md`、`process/checkpoints/CP3-HLD-REVIEW.md`、`process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md`、`process/checkpoints/CP8-DELIVERY-READINESS.md` |

旧项目中已经存在的 `process/USE-CASES.md`、`process/HLD.md`、根目录 `checkpoints/CP*.md` 等路径只作为 legacy fallback 读取；新工作流在无目标项目约定时默认写入 `docs/...` 和 `process/checkpoints/...`。production 项目如果已有交付目录或 README/docs 约定，优先按目标项目约定输出。

### 6.1 标准推进顺序

1. `host-orchestrator` 初始化请求并写入 CP0 自动检查结果。
2. `host-orchestrator` 将需求澄清阶段委托给 `meta-pm`。你可以直接与 `meta-pm` 多轮讨论 Scenario Gray Areas：先识别 3-4 个会影响交付的灰区，让你选择 1-3 个重点讨论；标准模式下至少会出现 1 个 `SGQ-*` 用户可见场景确认问题，并记录你的回答和复述确认；未选但有价值的想法进入 Deferred Ideas。随后沉淀 `USE-CASES.md` 和 `REQUIREMENTS.md`，写入 CP1 / CP2 自动检查结果，并在你确认“可提交给 host-orchestrator 汇总”后交还。
3. CP2 Decision Brief 人工确认通过后，`host-orchestrator` 将 HLD 设计阶段委托给 `meta-se`。你可以直接与 `meta-se` 讨论 Architecture Gray Areas 和 advisor table；advisor lane 使用 `Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch` 表格形成候选方案输入。随后 `meta-se` 输出 `BLUEPRINT.md`、`DOMAIN-MAP.md`、`DEPENDENCY-MAP.md`，并生成包含适用性矩阵、Use Case → Architecture Traceability 和关键场景模拟的 `HLD.md` 与 CP3 自动预检；当你确认“HLD 草案可提交给 host-orchestrator 发起 CP3”后交还。
4. CP3 人工确认通过后，`meta-se` 先输出 `docs/design/FEATURE-DESIGN-MATRIX.md`，判断哪些 Feature 需要 `docs/features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md`，并为每个 Story 标记 `feature_design_refs` 与 `lld_policy=full-lld|technical-note|waived`；随后输出 `STORY-BACKLOG.md`、`DEVELOPMENT-PLAN.yaml` 和 CP4 自动预检。CP4 不再单独人工确认，其摘要汇入 CP5。
5. `host-orchestrator` 仍处于 story-planning，按 Story DAG 确定覆盖全部目标 Story 的设计证据批次，组织 `meta-dev` 并行输出设计证据：高风险 Story 生成完整 `STORY-{id}-{story_slug}-LLD.md`，低风险 Story 在 Story 卡片内补 `## 技术说明`，明确豁免的 Story 写 waived 证据，并全部生成 CP5 自动预检。多个 `meta-dev` 遇到实现灰区时只写 clarification queue，由 `host-orchestrator` 合并后一次性问你，再把答案分发回对应 `meta-dev`。队列收敛后，host-orchestrator 发起一次全量人工确认。
6. 全量 CP5 确认后进入 story-execution；当前 Wave Story 的 `dev_gate` 满足后，`host-orchestrator` 自动按 Wave 调度 `meta-dev`，并在 `STATE.md.agent_lifecycle` 与 handoff `dispatch` 中记录证据。`meta-dev` 先用 `implementation-execution` 形成实现对象清单、设计契约映射、测试 / Fixture 计划、最小实现切片、平台差异和交接摘要；复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / 护栏 / 平台适配 / 发布相关 Story 写完整 `IMPLEMENTATION.md`，低风险 Story 可写 Story 摘要或 DEV-LOG。实现完成后写入 CP6 编码完成检查结果。
7. 每个 Story 开发完成且 CP6 通过后，`host-orchestrator` 自动调度 `meta-qa` 执行验证，并记录调度证据。验证时 `meta-qa` 会使用 `verification-execution` 消费 CP6 实现执行证据、设计证据和 `TEST-MATRIX.md`，输出验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题和剩余风险，再使用 `quality-review` 固化 TEST-REPORT / REVIEW / FIXES 并写入 CP7。CP7 结论为 `PASS` / `WAIVED` 时进入 verified，`PASS_WITH_RISK` 时可推进但风险进入 CP8，`NEEDS_REWORK` 回 meta-dev，`NEEDS_DESIGN_CLARIFICATION` 回 meta-se / host-orchestrator，`BLOCKED` 阻断。
8. `meta-doc` 最后输出 README 和 USER-MANUAL。随后 `meta-qa` 使用 `release-readiness` 先生成 `process/release/RELEASE-CONTEXT.yaml` 和 `process/context/CP8-DELIVERY-CONTEXT.yaml`，再按 `release_artifact_profile=minimal|compact|full` 裁剪发布文档。CP8 的 `release_decision=READY|READY_WITH_RISK` 才可发起人工终验，`NOT_READY` 阻断，`RELEASED|FAILED` 必须有独立真实发布授权；CP8 Decision Brief 和人工终验通过后进入 delivered。

### 6.2 检查点文件

所有检查点都包含 Entry Criteria、Checklist、Exit Criteria、Deliverables。自动检查点必须写入逐项检查结果；CP2 / CP3 / CP5 / CP8 人工检查点必须有可审查的 Decision Brief、待人工决策清单和 checklist 文件。待人工决策清单会汇总本轮所有需要你确认的问题，状态机对象是 `STATE.md.human_gate_decisions.pending_human_decisions[]`；每项包含决策 ID、决策类型、推荐方案、至少 1 个备选方案（优先 2 个）、优劣分析、影响 / 风险和回退 / 切换条件。

CP2 / CP3 / CP5 / CP6 / CP7 / CP8 前后会生成 `process/context/*-CONTEXT.yaml` 阶段上下文胶囊。它不替代正式文档，也不需要用户手工维护；作用是让下游 Agent 先读取摘要、证据路径、决策项、风险和不授权项，只有缺失、冲突、字段不足、人工审计或深度评审时才展开读取完整正式文档，从而减少 token 消耗。

| CP | 名称 | 类型 | 文件 |
|----|------|------|------|
| CP0 | 原始请求受理门 | 自动 | `process/checks/CP0-REQUEST-INTAKE.md` |
| CP1 | 用户场景完备门 | 自动 | `process/checks/CP1-USE-CASE-COMPLETENESS.md` |
| CP2 | 需求基线门 | 自动预检 + 人工 | `process/checks/CP2-REQUIREMENTS-BASELINE.md`；`process/checkpoints/CP2-REQUIREMENTS-BASELINE.md` |
| CP3 | 蓝图 / HLD 架构评审门 | 自动预检 + 人工 | `process/checks/CP3-HLD-CONSISTENCY.md`；`process/checkpoints/CP3-HLD-REVIEW.md` |
| CP4 | Story 拆解与并行安全门 | 自动预检（汇入 CP5） | `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md` |
| CP5 | Story 设计证据可实现性门 | 全量自动预检 + 人工 | `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`；`process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` |
| CP6 | Story 编码完成门 | 滚动自动 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md`，并引用 `IMPLEMENTATION.md` 或低风险实现摘要 |
| CP7 | Story 验证完成门 | 滚动自动 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md`，并引用 `VERIFICATION-REPORT.md`、`TEST-REPORT.md`、`REVIEW.md` 或低风险验证摘要 |
| CP8 | 交付就绪门 | 自动预检 + 人工 | `process/checks/CP8-DELIVERY-READINESS.md`；`process/checkpoints/CP8-DELIVERY-READINESS.md` |

CP6 / CP7 自动检查结果必须包含 `Agent Dispatch Evidence` 小节，用来证明 `meta-dev` / `meta-qa` 是真实子 agent 执行，而不是只有 handoff 文档。CP6 还必须记录实现执行证据路径、证据类型和 N/A 理由。CP7 还必须记录验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题和剩余风险、阶段决策。

软件开发工作流会在这些检查点周围生成额外工程产物：

| 阶段 | 关键产物 | 用途 |
|---|---|---|
| CP2 前 | `docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/product/STORY-MAP.md`、`docs/product/MVP-SCOPE.md`、`docs/product/RELEASE-SLICES.md` | 把用户场景转为工程验证覆盖、产品范围、发布切片和 backlog 输入 |
| CP3 前 | `docs/design/BLUEPRINT.md`、`docs/design/DOMAIN-MAP.md`、`docs/design/DEPENDENCY-MAP.md`、`docs/design/HLD.md` | 先定义 Feature / Epic 边界、领域对象、数据归属和依赖方向，再形成系统架构 |
| CP7 | `docs/quality/VERIFICATION-REPORT.md`、`docs/quality/TEST-REPORT.md`、`docs/quality/REVIEW.md`、`docs/quality/FIXES.md` | 汇总验证对象清单、追踪矩阵、设计契约、分层验证、验证命令、覆盖缺口、review findings、回修 / 设计澄清输入和剩余风险 |
| CP8 | `process/release/RELEASE-CONTEXT.yaml`、`docs/release/RELEASE-NOTES.md`、`docs/release/DEPLOY-CHECKLIST.md`、`docs/release/ROLLBACK.md`、`docs/release/MIGRATION.md`、`docs/release/FEEDBACK.md` | 先用 capsule 摘要控制发布上下文，再按 `release_artifact_profile=minimal|compact|full` 输出发布产物；`release_decision=READY|READY_WITH_RISK` 可进入终验，`NOT_READY` 阻断，`RELEASED|FAILED` 需要独立真实发布授权；`FEEDBACK.md` 不替代 follow-up tracking 台账 |

阶段上下文胶囊默认路径：

| 门禁 | 路径 | 说明 |
|---|---|---|
| CP2 | `process/context/CP2-REQUIREMENT-CONTEXT.yaml` | 需求、场景、范围和待决策摘要 |
| CP3 | `process/context/CP3-DESIGN-CONTEXT.yaml` | 蓝图、HLD、ADR 和架构灰区摘要 |
| CP5 | `process/context/CP5-LLD-CONTEXT.yaml` | Story 设计证据、LLD policy、clarification 队列和文件 owner 摘要 |
| CP6 | `process/context/CP6-IMPLEMENTATION-CONTEXT.yaml` | 当前 Wave / Story 的实现输入和设计契约摘要 |
| CP7 | `process/context/CP7-VERIFICATION-CONTEXT.yaml` | 验证范围、实现证据、测试矩阵和风险摘要 |
| CP8 | `process/context/CP8-DELIVERY-CONTEXT.yaml` | 发布准备、文档缺口、风险接受、不授权项和 follow-up 摘要 |

CP2 / CP3 还会生成讨论追溯文件：

| 阶段 | Discussion Log | Discussion Checkpoint | 记录内容 |
|---|---|---|---|
| CP2 | `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md` | `process/checks/CP2-DISCUSSION-CHECKPOINT.json` | Scenario Gray Areas、用户选择、freeform 确认、Deferred Ideas、canonical refs |
| CP3 | `process/discussions/CP3-HLD-DISCUSSION-LOG.md` | `process/checks/CP3-DISCUSSION-CHECKPOINT.json` | Architecture Gray Areas、advisor table、方案形成输入、HLD 后审查意见、切换条件 |

这些 Discussion Log 用于审计和中断恢复，不替代正式产物。后续 Agent 默认先以 `process/context/*-CONTEXT.yaml` 为读取入口；必要时再展开读取 `docs/product/USE-CASES.md`、`docs/product/REQUIREMENTS.md`、`docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/design/HLD.md`、`docs/design/ARCHITECTURE-DECISION.md`、`docs/design/FEATURE-DESIGN-MATRIX.md` 或 Decision Brief。

复杂项目未来可扩展为异步 power mode，例如生成 `process/discussions/CP2-QUESTIONS.json/html` 或 `CP3-QUESTIONS.json/html` 让用户批量回答问题。本版本不默认生成这些文件，也不把它们作为检查点前置条件。

### 6.3 阶段委托与 LLD 问题队列

阶段委托让 `meta-pm` / `meta-se` 在本阶段直接与你沟通，减少 host-orchestrator 传话：

- `STATE.md.delegated_interaction` 会记录当前委托的 `phase`、`agent_role`、`agent_id/thread_id`、`handoff_path`、`status`、`started_at`、`returned_at` 和 `return_summary_path`。
- 委托期间，如果你在 host-orchestrator 线程补充需求或 HLD 意见，host-orchestrator 应把内容转给被委托 Agent，而不是自己改写需求或 HLD。
- 被委托 Agent 只能完成本阶段草案和交还摘要；CP2 / CP3 正式人工确认仍由 host-orchestrator 发起。

LLD clarification queue 用来避免多个 `meta-dev` 同时打断你：

- 队列位置是 `STATE.md.parallel_execution.lld_clarification_queue`。
- 每个 item 至少包含 `id`、`story_id`、`owner_agent`、`question`、`options`、`recommendation`、`pros_cons`、`impact_surface`、`blocks_lld`、`answer`、`status`；其中 `options` 必须表达 1 个推荐方案和至少 1 个备选方案。
- `blocks_lld=true` 的未回答项会阻止 CP5；非阻断 OPEN / Spike 可以进入 CP5，但必须在 Decision Brief、完整 LLD 或 Story 技术说明、DEV-LOG 中说明影响、owner 和重访条件。

合格证据包括：

- Codex `spawn_agent` / `resume_agent` / `send_input` 的返回标识
- Claude Code / OpenClaw 的 Task/Subagent 标识
- `STATE.md.agent_lifecycle.active_agents` 中非空的 `agent_id` 或 `thread_id`
- handoff `dispatch` 中的 `tool_name`、`spawned_at` / `resumed_at`、`completed_at`

只有 `to_agent: meta-dev`、`to_agent: meta-qa` 或 handoff `status=completed`，不能作为子 agent 执行证据。

如果当前运行模式无法拉起子 agent，host-orchestrator 必须阻断并说明原因。用户明确批准后，才允许 `dispatch.mode=inline-fallback`，并必须写明 `fallback_reason`、`approved_by`、`approved_at`。这种结果应表述为 host-orchestrator 代执行，不能表述为 meta-dev / meta-qa 独立完成。

用户启动正式工作流后，同工作流内默认允许 `host-orchestrator` 自动拉起所需功能 Agent。该授权只覆盖真实子 agent 调度，不覆盖 inline fallback。

### 6.4 fast-lane 快速模式

`fast-lane` 适用于低风险轻量实现、小型规则 / Skill / Agent 修改和文档更新。它可以减少需求、HLD、LLD、IMPLEMENTATION、VERIFICATION 和 release 文档厚度，发布阶段默认使用 `release_artifact_profile=minimal`，但不能跳过 CP6 / CP7、Agent Dispatch Evidence、实现执行证据摘要、验证执行证据摘要、`RELEASE-CONTEXT.yaml` 或 CP8 终验摘要。

命中架构、权限、安全、平台安装、外部接口、文件所有权冲突或多 Story 依赖时，必须升级为 `standard`。

Scenario / Architecture Gray Areas 不会把所有小修改强制升级成长流程。fast-lane 下如果 discussion log / checkpoint 不适用，自动检查会写明 N/A 原因；验证、调度证据和 CP8 终验摘要仍然保留。

### 6.5 人工确认操作

host-orchestrator 发起人工检查时会提示 checklist 文件路径，例如：

```text
请审查：process/checkpoints/CP3-HLD-REVIEW.md
自动预检结论：PASS
本轮待人工决策项：1
如果你回复 approve，表示你接受以下 1 项推荐方案，不表示授权以下 0 项禁止操作。
待人工决策清单：
| 决策 ID | 决策类型 | 待确认问题 | 推荐方案 | 备选方案 | 优劣摘要 | 影响 / 风险 |
|---|---|---|---|---|---|---|
| CP3-DQ-01 | architecture | ... | ... | ... | ... | ... |

不授权项：
- 无

该文件包含本检查点的 Entry Criteria、Checklist、Exit Criteria、Deliverables、自动预检摘要、Decision Brief、待人工决策清单和人工审查结果区。
```

审查后可以在对应 `process/checkpoints/CP*.md` 的“人工审查结果”中填写结论，也可以直接在对话中回复。Claude Code 可继续使用结构化选择，但允许 direct ask 的 subagent 必须在 frontmatter `tools:` 中显式包含 `AskUserQuestion`。Codex 只有在当前工具面明确提供可用的 `request_user_input` / 选择 UI 时才使用结构化选择；否则默认使用 exact 文本确认。系统对用户只展示三个推荐回复：`approve`、`修改: <具体修改点>`、`reject`；历史别名 `1/通过`、`2/修改: ...`、`3/不通过` 仅作为兼容解析，不作为主要提示文案。`approve` 表示接受待人工决策清单内全部推荐方案；需要调整单项时，用 `修改: <决策 ID>=<具体修改点>`。

```text
approve                  # 确认通过
修改: <具体修改点>        # 需要修改
reject                   # 不通过并回退
```

不匹配上述 exact 输入时，host-orchestrator 不得推进状态。

用户直接在对话中确认时，host-orchestrator 仍必须把结论回填到对应 `process/checkpoints/CP*.md`。

人工门禁消息本身也会被校验：必须包含 checklist 路径、自动预检结论、Context Capsule 摘要、决策收集覆盖摘要、待决策项数量、待决策表格或压缩后的 blocking / high-risk 决策摘要和三个 exact 回复。对应 checklist 的 Decision Brief 必须完整，并包含 `Decision Collection Coverage`，列出已扫描来源、候选问题数、纳入待决策数和 N/A / 缺失原因；这样你不需要再打开长文档自行查找是否还有遗漏问题。对话消息可按 `decision_brief_profile=full|compact|summary` 压缩，但不能省略高风险 / 阻断决策、不授权项和完整 checklist 路径。真实运行、凭据、安全、外部接口、数据写入、publish、live / 交易类事项必须列为不授权项；`approve` 只接受表内推荐方案，不代表授权这些操作。

### 6.5.1 CP8 follow-up tracking

CP8 终验会把遗留事项分流到 follow-up tracking 台账，而不是一次性预创建多个正式 CR 文件：

| 分类 | 含义 | 用户可调整内容 |
|---|---|---|
| 关闭范围 | 本轮已完成并关闭 | 关闭证据或范围描述 |
| 不授权范围 | 设计 / 文档通过不代表授权执行 | 未来授权条件、是否转正式 CR |
| 风险接受项 | 用户接受风险后放行 | 接受条件、回退条件、owner |
| 后续 CR 候选项 | 只进入台账，未启动正式 CR | 标题、owner、重访条件、是否转 Spike |
| 取消 / deferred 项 | 明确不做或延后 | 取消理由、可重启条件 |

台账路径形如 `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md`。状态取值包括 `candidate`、`active`、`blocked`、`spike_candidate`、`converted-to-spike`、`closed`、`cancelled`、`superseded`。当你决定推进某一候选项时，host-orchestrator 才创建正式 CR，并把台账状态改为 `active`。

启动候选项时，在对话中给出“启动后续 CR”、台账路径、候选编号和目标摘要：

```text
启动后续 CR
台账：process/changes/CR-019-FOLLOW-UP-TRACKING-2026-05-31.md
候选编号：CR-020
目标：推进 Windows gateway 实机部署准入
```

host-orchestrator 会执行以下动作：

| 步骤 | 动作 | 输出 |
|---|---|---|
| 1 | 读取台账候选项、`STATE.md.active_change`、`STATE.md.cr_tracking`、`CR-INDEX.yaml` 和活跃 CR | 判断是否已有未完成 CR |
| 2 | 执行 CR 冲突预检 | 输出影响面、重叠对象和推荐处理 |
| 3 | 无冲突或用户确认处理方式后创建正式 CR | `process/changes/CR-0xx-<slug>-YYYY-MM-DD.md` |
| 4 | 回写台账 | 状态改为 `active`，填写正式 CR 路径、当前门控、阻塞原因和下一步 |
| 5 | 进入普通 CR 流程 | 五维度影响分析、门禁、实现和验证 |

候选项没有启动时只是 backlog，不会和新的 CR 冲突。已启动但未完成的 CR 会占用执行语义：如果新 CR 与它影响同一正式文档、Story、文件 owner、外部接口、安全 / 运行授权或风险接受项，host-orchestrator 不得静默并行推进，必须发起冲突决策。可选处理包括：合并到现有 CR、保持候选等待、标记为 `blocked`、拆分无冲突子集先做、或标记为 `superseded` 并链接替代 CR。

查看当前 CR 时，使用：

```text
当前状态
检查还有哪些 CR 需要推进，建议如何推进
```

host-orchestrator 必须输出五类清单：`active formal CR`、`blocked formal CR`、`follow-up candidate`、`spike_candidate`、`stale_status_conflicts`。`candidate` 和 `spike_candidate` 不是执行锁，但必须作为 backlog 展示；如果 `STATE.md.active_change` 指向已关闭 CR，或正式 active CR 没有回写台账 / `CR-INDEX.yaml`，必须先列为状态冲突。存在 `meta-flow check cr-tracking` 时，可用以下命令独立检查：

```bash
meta-flow check cr-tracking --project-root .
```

### 6.6 何时显式声明 meta-self-dev

如果这次目标是优化当前元工作流本身，而不是为某个目标产物交付方案，请在第一轮明确说明：

```text
当前是在做 meta 工作流优化，请进入 meta-self-dev 模式。
```

## 7. 工作模式查看与切换

### 7.1 默认规则

- 工作流默认是 `production`
- 只有当你**明确说明**当前是在做“meta 工作流优化 / 自我开发”时，才会切换到 `meta-self-dev`
- 在 `production` 模式下，场景主体默认是目标产物，而不是当前仓库本身
- 在 `production` 模式下，不默认把交付物写入当前仓库 `delivery/`

### 7.2 如何查看当前工作模式

方法一：直接询问当前会话中的主编排器，例如：

```text
你当前在哪个工作模式？
```

方法二：查看过程文件中的 frontmatter 字段：

- `process/REQUEST.md`：查看 `engagement_mode`、`scenario_subject_type`、`scenario_subject_id`
- `docs/product/USE-CASES.md`：查看 `engagement_mode`、`scenario_subject_type`、`scenario_subject_id`

字段含义：

- `engagement_mode=production`：当前是在生产模式下为目标 Agent / Skill / Workflow 产出方案
- `engagement_mode=meta-self-dev`：当前是在优化 meta 工作流自身
- `scenario_subject_type=target-artifact`：当前场景主体是目标产物
- `scenario_subject_type=implementation-carrier`：当前场景主体是当前实现载体 / 当前仓库

### 7.3 如何切换到 meta-self-dev

在需求开始时明确说明当前目标是优化 meta 工作流本身，例如：

```text
当前是在做 meta 工作流优化，请进入 meta-self-dev 模式。
```

或：

```text
这次不是生产项目交付，而是 meta 工作流自我开发。
```

### 7.4 如何切回 production

明确说明当前回到生产模式，并指出真正服务的目标产物，例如：

```text
当前回到 production 模式，目标是为 ptm-tde 这个 agent 梳理用户场景。
```

或：

```text
这次不是优化 meta 工作流本身，而是为目标 workflow 产出正式方案。
```

### 7.5 使用建议

- 若你不特别声明，系统会继续按 `production` 处理
- 如果请求同时提到“整改当前仓库”和“目标 Agent / Skill / Workflow”，又**没有**明确声明 meta 优化，系统会优先把目标产物当作场景主体
- 想避免歧义时，建议在第一轮消息里同时写明：`engagement_mode` 意图 + 目标产物名称

## 8. 交付出口路由

meta-flow 会先判断当前任务是否为自身改进：

- `meta-self-dev` 或用户明确说明“优化 meta-flow / 当前元工作流”：交付件写当前仓库 `delivery/`
- `production` 外部项目：先扫描目标项目已有交付目录、`README.md`、`README.*` 与 `docs/` 是否有交付物、发布、构建或包结构说明
- 已有交付目录或 README/docs 存在交付约定：按目标项目约定输出，并在 HLD / Story 中引用依据
- 目标项目没有已有交付目录且 README/docs 没有交付约定：host-orchestrator / meta-se 先提出建议目录，等待用户确认后才写入

用户确认前，production 项目不得默认创建当前仓库 `delivery/` 交付件。

## 9. 验证环境准备

### 9.1 项目类型与 workflow eval

Meta Flow 不把“纯代码开发”和“工作流开发”拆成两条主流程。它通过两个字段分流：

- `engagement_mode`：只判断当前是 meta-flow 自改进还是 production 交付。
- `target_project_profile.project_kind`：判断目标项目是 `code-project`、`workflow-product`、`agentic-code-product`、`mixed` 或 `unknown`。
- `validation_target.sut_type`：判断当前 Story / 交付对象需要 `code-project`、`generated-workflow`、`prompt-skill-workflow`、`meta-flow-core-code`、`agentic-code-product` 或 `mixed` 验证。

纯代码项目默认继续跑目标项目自己的测试、构建、静态检查和质量评审。只有 generated workflow、prompt-skill、meta-flow-core-code、agentic-code-product 或 mixed 对象才默认要求 workflow eval / prompt bundle 证据。

本地 workflow eval 示例：

```bash
meta-flow eval validate --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml
meta-flow eval run --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/generated-workflow-basic
meta-flow eval suite-health --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md
meta-flow eval run --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/runtime-workflow-basic
meta-flow eval feedback sync --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/feedback/raw
meta-flow eval feedback normalize --in process/evals/feedback/raw --out process/evals/feedback/run-exec
meta-flow eval feedback triage --runs process/evals/feedback/run-exec --out process/evals/feedback/triage
meta-flow eval release-check --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --runs process/evals/runs --profile release --triage process/evals/feedback/triage --format json --json-out process/evals/release-check.json
```

`runtime_artifact` grader 只读取已有运行工作区，用于检查运行态目录、STATE phase、Skill 调用链、Gate、阶段顺序、内容密度、空文件 / 模板残留、delivery、trace chain、coverage 和表格；release-grade 运行证据建议通过 `RUNTIME-SAMPLE-REGISTRY.yaml` 和 `sample_ids` 声明，支持 `partial`、`full`、`regression` profile 和 expected BLOCKED 样本。现场反馈流程是 `feedback source -> normalized RUN-EXEC -> triage -> ISSUE_DRAFT / GAP / BACKLOG / ENVIRONMENT / USAGE / DUPLICATE / NO_ACTION`，不会把所有 feedback 自动升级为 ISSUE；每条 triage 结果都保留 `run_exec_id`。mutation 使用 `meta-flow eval mutate` 生成确定性负例，并为每个 mutation 声明 `expected_failing_grader`；安装映射使用 `meta-flow eval install-check` 检查 manifest、installed root 或 `PLATFORM-CONTRACTS.yaml` 下的平台发现路径。`suite-health` 输出质量趋势，`release-check` 独立输出 `PASS|PASS_WITH_RISK|BLOCKED`，可用 `--format json` 生成机器可读门禁结果。

外部 adapter（Promptfoo / DeepEval / Langfuse / Garak）默认关闭。它们可以做 case / result / trace 映射，但真实网络调用、凭据使用、trace 上传、外部模型评估、publish、live 或 production 写入必须单独授权。

进入验证阶段前，建议由人工提供或确认类似如下的环境配置：

```yaml
environment_id: local-dev
provided_by: human
targets:
  - claude
  - openclaw
approval:
  confirmed: true
notes:
  - "本轮验证只检查安装目录、文件引用和提示词加载"
```

## 10. 排障

1. **提示找不到 `scripts/install.py`**：你在仓库根目录执行了 delivery-root 命令；改用 `delivery/scripts/install.py`
2. **Skill 运行时脚本未找到**：检查目标 Skill 的私有脚本是否位于 `delivery/skills/<skill>/scripts/`
3. **需要确认交付结构是否合规**：仅当当前仓库存在 `scripts/check_delivery_guardrails.py` 时，运行 `uv run --python 3.11 python scripts/check_delivery_guardrails.py`；如果是外部 production 项目且没有该脚本，外部 production 项目不得硬引用 meta-flow 源仓库路径，改按目标 README/docs 的测试、构建、安装 dry-run 或用户确认的验证命令执行。
