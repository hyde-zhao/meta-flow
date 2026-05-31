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

canonical role 仍为 `meta-*`，用于状态机、handoff、检查点和审计。平台展示按下表安装：

| canonical role | Codex 命令 / nickname_candidates | Claude Code color |
|---|---|---|
| `meta-po` | `po-zhao`、`po-qian`、`po-sun`、`po-li`、`po-zhou` | `red` |
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

主编排器入口是 `meta-po`。首次启动一个正式交付工作流时，建议直接给出目标、平台和约束：

```text
@meta-po 开始
目标：为 <agent / skill / workflow 名称> 产出正式方案
平台：Claude Code、Codex
要求：先澄清需求，再给我 HLD，确认后再拆 Story
```

常用控制语句：

```text
@meta-po 当前状态
@meta-po 下一步
@meta-po 继续
@meta-po 快速修改
@meta-po 回退到 CP3 HLD 架构评审前
```

### 6.1 标准推进顺序

1. `meta-po` 初始化请求并写入 CP0 自动检查结果。
2. `meta-po` 将需求澄清阶段委托给 `meta-pm`。你可以直接与 `meta-pm` 多轮讨论 Scenario Gray Areas：先识别 3-4 个会影响交付的灰区，让你选择 1-3 个重点讨论；未选但有价值的想法进入 Deferred Ideas。随后沉淀 `USE-CASES.md` 和 `REQUIREMENTS.md`，写入 CP1 / CP2 自动检查结果，并在你确认“可提交给 meta-po 汇总”后交还。
3. CP2 Decision Brief 人工确认通过后，`meta-po` 将 HLD 设计阶段委托给 `meta-se`。你可以直接与 `meta-se` 讨论 Architecture Gray Areas 和 advisor table；advisor lane 使用 `Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch` 表格形成候选方案输入。随后 `meta-se` 输出包含适用性矩阵、Use Case → Architecture Traceability 和关键场景模拟的 `HLD.md` 与 CP3 自动预检，并在你确认“HLD 草案可提交给 meta-po 发起 CP3”后交还。
4. CP3 人工确认通过后，`meta-se` 输出 `STORY-BACKLOG.md`、`DEVELOPMENT-PLAN.yaml` 和 CP4 自动预检。CP4 不再单独人工确认，其摘要汇入 CP5。
5. `meta-po` 仍处于 story-planning，按 Story DAG 确定覆盖全部目标 Story 的 LLD 设计批次，组织 `meta-dev` 并行输出全部 `STORY-{id}-{story_slug}-LLD.md` 和 CP5 自动预检。多个 `meta-dev` 遇到实现灰区时只写 clarification queue，由 `meta-po` 合并后一次性问你，再把答案分发回对应 `meta-dev`。队列收敛后，meta-po 发起一次全量人工确认。
6. 全量 CP5 确认后进入 story-execution；当前 Wave Story 的 `dev_gate` 满足后，`meta-po` 自动按 Wave 调度 `meta-dev`，并在 `STATE.md.agent_lifecycle` 与 handoff `dispatch` 中记录证据；实现完成后写入 CP6 编码完成检查结果。
7. 每个 Story 开发完成后，`meta-po` 自动调度 `meta-qa` 执行验证，并记录调度证据；验证完成后写入 CP7。CP7 失败时回到 `meta-dev` 修复并再次验证。
8. `meta-doc` 最后输出 README 和 USER-MANUAL，CP8 Decision Brief 和人工终验通过后进入 delivered。

### 6.2 检查点文件

所有检查点都包含 Entry Criteria、Checklist、Exit Criteria、Deliverables。自动检查点必须写入逐项检查结果；CP2 / CP3 / CP5 / CP8 人工检查点必须有可审查的 Decision Brief、待人工决策清单和 checklist 文件。待人工决策清单会汇总本轮所有需要你确认的问题，状态机对象是 `STATE.md.human_gate_decisions.pending_human_decisions[]`；每项包含决策 ID、决策类型、推荐方案、至少 1 个备选方案（优先 2 个）、优劣分析、影响 / 风险和回退 / 切换条件。

| CP | 名称 | 类型 | 文件 |
|----|------|------|------|
| CP0 | 原始请求受理门 | 自动 | `process/checks/CP0-REQUEST-INTAKE.md` |
| CP1 | 用户场景完备门 | 自动 | `process/checks/CP1-USE-CASE-COMPLETENESS.md` |
| CP2 | 需求基线门 | 自动预检 + 人工 | `process/checks/CP2-REQUIREMENTS-BASELINE.md`；`checkpoints/CP2-REQUIREMENTS-BASELINE.md` |
| CP3 | HLD 架构评审门 | 自动预检 + 人工 | `process/checks/CP3-HLD-CONSISTENCY.md`；`checkpoints/CP3-HLD-REVIEW.md` |
| CP4 | Story 拆解与并行安全门 | 自动预检（汇入 CP5） | `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md` |
| CP5 | Story LLD 可实现性门 | 全量自动预检 + 人工 | `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`；`checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` |
| CP6 | Story 编码完成门 | 滚动自动 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` |
| CP7 | Story 验证完成门 | 滚动自动 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` |
| CP8 | 交付就绪门 | 自动预检 + 人工 | `process/checks/CP8-DELIVERY-READINESS.md`；`checkpoints/CP8-DELIVERY-READINESS.md` |

CP6 / CP7 自动检查结果必须包含 `Agent Dispatch Evidence` 小节，用来证明 `meta-dev` / `meta-qa` 是真实子 agent 执行，而不是只有 handoff 文档。

CP2 / CP3 还会生成讨论追溯文件：

| 阶段 | Discussion Log | Discussion Checkpoint | 记录内容 |
|---|---|---|---|
| CP2 | `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md` | `process/checks/CP2-DISCUSSION-CHECKPOINT.json` | Scenario Gray Areas、用户选择、freeform 确认、Deferred Ideas、canonical refs |
| CP3 | `process/discussions/CP3-HLD-DISCUSSION-LOG.md` | `process/checks/CP3-DISCUSSION-CHECKPOINT.json` | Architecture Gray Areas、advisor table、方案形成输入、HLD 后审查意见、切换条件 |

这些 Discussion Log 用于审计和中断恢复，不替代正式产物。后续 Agent 仍以 `USE-CASES.md`、`REQUIREMENTS.md`、`HLD.md`、`ARCHITECTURE-DECISION.md`、Decision Brief 或必要的 `HLD-CONTEXT.md` 为准。

复杂项目未来可扩展为异步 power mode，例如生成 `process/discussions/CP2-QUESTIONS.json/html` 或 `CP3-QUESTIONS.json/html` 让用户批量回答问题。本版本不默认生成这些文件，也不把它们作为检查点前置条件。

### 6.3 阶段委托与 LLD 问题队列

阶段委托让 `meta-pm` / `meta-se` 在本阶段直接与你沟通，减少 meta-po 传话：

- `STATE.md.delegated_interaction` 会记录当前委托的 `phase`、`agent_role`、`agent_id/thread_id`、`handoff_path`、`status`、`started_at`、`returned_at` 和 `return_summary_path`。
- 委托期间，如果你在 meta-po 线程补充需求或 HLD 意见，meta-po 应把内容转给被委托 Agent，而不是自己改写需求或 HLD。
- 被委托 Agent 只能完成本阶段草案和交还摘要；CP2 / CP3 正式人工确认仍由 meta-po 发起。

LLD clarification queue 用来避免多个 `meta-dev` 同时打断你：

- 队列位置是 `STATE.md.parallel_execution.lld_clarification_queue`。
- 每个 item 至少包含 `id`、`story_id`、`owner_agent`、`question`、`options`、`recommendation`、`pros_cons`、`impact_surface`、`blocks_lld`、`answer`、`status`；其中 `options` 必须表达 1 个推荐方案和至少 1 个备选方案。
- `blocks_lld=true` 的未回答项会阻止 CP5；非阻断 OPEN / Spike 可以进入 CP5，但必须在 Decision Brief、LLD 和 DEV-LOG 中说明影响、owner 和重访条件。

合格证据包括：

- Codex `spawn_agent` / `resume_agent` / `send_input` 的返回标识
- Claude Code / OpenClaw 的 Task/Subagent 标识
- `STATE.md.agent_lifecycle.active_agents` 中非空的 `agent_id` 或 `thread_id`
- handoff `dispatch` 中的 `tool_name`、`spawned_at` / `resumed_at`、`completed_at`

只有 `to_agent: meta-dev`、`to_agent: meta-qa` 或 handoff `status=completed`，不能作为子 agent 执行证据。

如果当前运行模式无法拉起子 agent，meta-po 必须阻断并说明原因。用户明确批准后，才允许 `dispatch.mode=inline-fallback`，并必须写明 `fallback_reason`、`approved_by`、`approved_at`。这种结果应表述为 meta-po 代执行，不能表述为 meta-dev / meta-qa 独立完成。

用户启动正式工作流后，同工作流内默认允许 `meta-po` 自动拉起所需功能 Agent。该授权只覆盖真实子 agent 调度，不覆盖 inline fallback。

### 6.4 fast-lane 快速模式

`fast-lane` 适用于低风险轻量实现、小型规则 / Skill / Agent 修改和文档更新。它可以减少需求、HLD、LLD 的文档厚度和人工门数量，但不能跳过 CP6 / CP7、Agent Dispatch Evidence 或 CP8 终验摘要。

命中架构、权限、安全、平台安装、外部接口、文件所有权冲突或多 Story 依赖时，必须升级为 `standard`。

Scenario / Architecture Gray Areas 不会把所有小修改强制升级成长流程。fast-lane 下如果 discussion log / checkpoint 不适用，自动检查会写明 N/A 原因；验证、调度证据和 CP8 终验摘要仍然保留。

### 6.5 人工确认操作

meta-po 发起人工检查时会提示 checklist 文件路径，例如：

```text
请审查：checkpoints/CP3-HLD-REVIEW.md
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

审查后可以在对应 `checkpoints/CP*.md` 的“人工审查结果”中填写结论，也可以直接在对话中回复。Claude Code 可继续使用结构化选择。Codex 只有在当前工具面明确提供可用的 `request_user_input` / 选择 UI 时才使用结构化选择；否则默认使用 exact 文本确认。系统对用户只展示三个推荐回复：`approve`、`修改: <具体修改点>`、`reject`；历史别名 `1/通过`、`2/修改: ...`、`3/不通过` 仅作为兼容解析，不作为主要提示文案。`approve` 表示接受待人工决策清单内全部推荐方案；需要调整单项时，用 `修改: <决策 ID>=<具体修改点>`。

```text
approve                  # 确认通过
修改: <具体修改点>        # 需要修改
reject                   # 不通过并回退
```

不匹配上述 exact 输入时，meta-po 不得推进状态。

用户直接在对话中确认时，meta-po 仍必须把结论回填到对应 `checkpoints/CP*.md`。

人工门禁消息本身也会被校验：必须包含 checklist 路径、自动预检结论、待决策项数量、待决策表格和三个 exact 回复。如果存在待决策项但消息没有打印表格，门禁发起视为不合规。真实运行、凭据、安全、外部接口、数据写入、publish、live / 交易类事项必须列为不授权项；`approve` 只接受表内推荐方案，不代表授权这些操作。

### 6.5.1 CP8 follow-up tracking

CP8 终验会把遗留事项分流到 follow-up tracking 台账，而不是一次性预创建多个正式 CR 文件：

| 分类 | 含义 | 用户可调整内容 |
|---|---|---|
| 关闭范围 | 本轮已完成并关闭 | 关闭证据或范围描述 |
| 不授权范围 | 设计 / 文档通过不代表授权执行 | 未来授权条件、是否转正式 CR |
| 风险接受项 | 用户接受风险后放行 | 接受条件、回退条件、owner |
| 后续 CR 候选项 | 只进入台账，未启动正式 CR | 标题、owner、重访条件、是否转 Spike |
| 取消 / deferred 项 | 明确不做或延后 | 取消理由、可重启条件 |

台账路径形如 `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md`。状态取值包括 `candidate`、`active`、`blocked`、`spike_candidate`、`converted-to-spike`、`closed`、`cancelled`、`superseded`。当你决定推进某一候选项时，meta-po 才创建正式 CR，并把台账状态改为 `active`。

启动候选项时，在对话中给出“启动后续 CR”、台账路径、候选编号和目标摘要：

```text
@meta-po 启动后续 CR
台账：process/changes/CR-019-FOLLOW-UP-TRACKING-2026-05-31.md
候选编号：CR-020
目标：推进 Windows gateway 实机部署准入
```

meta-po 会执行以下动作：

| 步骤 | 动作 | 输出 |
|---|---|---|
| 1 | 读取台账候选项、`STATE.md.active_change`、`STATE.md.cr_tracking`、`CR-INDEX.yaml` 和活跃 CR | 判断是否已有未完成 CR |
| 2 | 执行 CR 冲突预检 | 输出影响面、重叠对象和推荐处理 |
| 3 | 无冲突或用户确认处理方式后创建正式 CR | `process/changes/CR-0xx-<slug>-YYYY-MM-DD.md` |
| 4 | 回写台账 | 状态改为 `active`，填写正式 CR 路径、当前门控、阻塞原因和下一步 |
| 5 | 进入普通 CR 流程 | 五维度影响分析、门禁、实现和验证 |

候选项没有启动时只是 backlog，不会和新的 CR 冲突。已启动但未完成的 CR 会占用执行语义：如果新 CR 与它影响同一正式文档、Story、文件 owner、外部接口、安全 / 运行授权或风险接受项，meta-po 不得静默并行推进，必须发起冲突决策。可选处理包括：合并到现有 CR、保持候选等待、标记为 `blocked`、拆分无冲突子集先做、或标记为 `superseded` 并链接替代 CR。

查看当前 CR 时，使用：

```text
@meta-po 当前状态
检查还有哪些 CR 需要推进，建议如何推进
```

meta-po 必须输出五类清单：`active formal CR`、`blocked formal CR`、`follow-up candidate`、`spike_candidate`、`stale_status_conflicts`。`candidate` 和 `spike_candidate` 不是执行锁，但必须作为 backlog 展示；如果 `STATE.md.active_change` 指向已关闭 CR，或正式 active CR 没有回写台账 / `CR-INDEX.yaml`，必须先列为状态冲突。存在 `scripts/check_cr_tracking_consistency.py` 时，可用以下命令独立检查：

```bash
uv run --python 3.11 python scripts/check_cr_tracking_consistency.py --project-root .
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
- `process/USE-CASES.md`：查看 `engagement_mode`、`scenario_subject_type`、`scenario_subject_id`

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
- `production` 外部项目：先扫描目标项目 `README.md`、`README.*` 与 `docs/` 是否有交付物、发布、构建或包结构说明
- README/docs 存在交付约定：按目标项目约定输出，并在 HLD / Story 中引用依据
- README/docs 没有交付约定：meta-po / meta-se 先提出建议目录，等待用户确认后才写入

用户确认前，production 项目不得默认创建当前仓库 `delivery/` 交付件。

## 9. 验证环境准备

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
