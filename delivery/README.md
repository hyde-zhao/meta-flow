# Meta Flow Delivery Package

本目录是可独立交付的 Meta Flow 产物包，包含：

- `agents/`：交付 Agent 定义
- `skills/`：交付 Skill 定义及其私有运行时资产
- `rules/`：平台规则文件
- `scripts/`：安装器入口
- `doc/PLATFORM-CONTRACTS.yaml`：平台安装路径契约；安装器和校验脚本以此为路径真相源

## 输出分层

生产项目中的默认输出分为三层：

- `docs/`：长期可交付文档。产品与范围写 `docs/product/`，蓝图 / HLD / ADR / Feature 设计矩阵写 `docs/design/`，Feature 级设计写 `docs/features/<feature>/`，质量报告写 `docs/quality/`，发布资料写 `docs/release/`。
- `process/`：运行过程文档。`STATE.md`、`REQUEST.md`、执行计划、Story 卡片、CR、discussion、handoff 和自动检查结果都留在这里。
- `process/context/`：阶段上下文胶囊。CP2 / CP3 / CP5 / CP6 / CP7 / CP8 的子 agent、人工门禁、验证和发布准备默认先读取这里，减少重复读取全文档。
- `process/checkpoints/`：人工确认态。CP2 / CP3 / CP5 / CP8 的 Decision Brief、checklist 和人工审查结果写入这里。

旧项目里的 `process/USE-CASES.md`、`process/HLD.md`、根目录 `checkpoints/CP*.md` 等路径只作为 legacy fallback 读取；新工作流在无目标项目约定时默认生成到 `docs/...` 与 `process/checkpoints/...`。如果目标项目已有交付目录或 README/docs 已定义自己的文档目录，production 模式必须优先遵守目标约定；无约定时由 host-orchestrator 提出路由建议并等待用户确认。

## CP2 / CP3 讨论增强

标准模式下，Meta Flow 会在两个关键人工门前加强讨论，但不新增 CP 编号或独立人工门：

- CP2 前，`meta-pm` 先识别 3-4 个 `Scenario Gray Areas`，让用户选择 1-3 个重点讨论；未选但有价值的想法进入 `Deferred Ideas`，不污染当前 scope。
- CP3 前，`meta-se` 先识别 `Architecture Gray Areas` 并在阶段委托内直接与用户完成 advisor table-first 讨论；需要额外 reviewer lane 时由 `host-orchestrator` 汇总。advisor lane 优先使用 `Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch` 表格。
- HLD 必须记录适用性矩阵、Use Case → Architecture Traceability、关键场景模拟、优化 / 牺牲 / 切换条件和自审结果。

讨论日志写入 `process/discussions/`，恢复点写入 `process/checks/`：

| 阶段 | Discussion Log | Discussion Checkpoint |
|---|---|---|
| CP2 | `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md` | `process/checks/CP2-DISCUSSION-CHECKPOINT.json` |
| CP3 | `process/discussions/CP3-HLD-DISCUSSION-LOG.md` | `process/checks/CP3-DISCUSSION-CHECKPOINT.json` |

Discussion Log 用于审计和恢复，不替代正式产物。下游 Agent 默认先读取 `process/context/*-CONTEXT.yaml`；必要时再展开读取正式的 `USE-CASES.md`、`REQUIREMENTS.md`、`SCENARIOS.yaml`、`TEST-MATRIX.md`、`HLD.md`、`ARCHITECTURE-DECISION.md`、`FEATURE-DESIGN-MATRIX.md` 或 Decision Brief。

复杂项目的异步 power mode（如 `process/discussions/CP2-QUESTIONS.json/html`、`CP3-QUESTIONS.json/html`）保留为后续可选增强，本交付包不默认生成这些文件，也不把它们作为验收前置。

## 阶段委托与 LLD 问题队列

Meta Flow 的交互路径分两类：

- `requirement-clarification`：host-orchestrator 启动或复用 `meta-pm` 后，将阶段内用户交互权委托给 `meta-pm`。用户可直接与 `meta-pm` 多轮讨论 Scenario Gray Areas、场景和需求草案；草案确认“可提交给 host-orchestrator 汇总”后，`meta-pm` 写交还摘要，host-orchestrator 回收并发起 CP2。
- `solution-design`：host-orchestrator 启动或复用 `meta-se` 后，将阶段内用户交互权委托给 `meta-se`。用户可直接与 `meta-se` 讨论 Architecture Gray Areas、advisor table 和 HLD 草案；草案确认“可提交给 host-orchestrator 发起 CP3”后，`meta-se` 写交还摘要，host-orchestrator 回收并发起 CP3。
- `story-planning` 的并行 LLD：多个 `meta-dev` 不直接并发问用户。实现灰区写入 `STATE.md.parallel_execution.lld_clarification_queue`，由 host-orchestrator 作为 question broker 合并、排序、批量询问用户、回填答案并分发给对应 `meta-dev`。

阶段委托状态写入 `STATE.md.delegated_interaction`。这只代表阶段内交互权委托，不代表 CP2 / CP3 已通过。LLD clarification 队列存在未回答 `blocks_lld=true` 项时，host-orchestrator 不得发起 CP5；转 OPEN / Spike 的项必须在 CP5 Decision Brief、完整 LLD 或 Story 技术说明、DEV-LOG 中暴露。

## 工作流检查点

安装后的 Meta Flow 使用 CP0-CP8 检查点。自动检查结果写入目标项目的 `process/checks/CP*.md`；阶段上下文胶囊写入 `process/context/*-CONTEXT.yaml`；关键人工审查稿写入 `process/checkpoints/CP*.md`。CP2 / CP3 / CP5 / CP8 由 `host-orchestrator` 发起人工确认，发起前必须生成 Context Capsule、Decision Brief 和待人工决策清单，并提示具体 checklist 文件路径。待人工决策清单的状态机对象是 `STATE.md.human_gate_decisions.pending_human_decisions[]`，逐项列出决策 ID、决策类型、待确认问题、推荐方案、至少 1 个备选方案（优先 2 个）、优劣分析、影响 / 风险和回退 / 切换条件；用户回复 `approve` 表示接受清单内全部推荐方案。审查后必须回填“人工审查结果”。CP4 只生成自动预检并汇入 CP5。

人工门禁发起消息必须同时合规：包含 checklist 路径、自动预检结论、Context Capsule 摘要、决策收集覆盖摘要、待决策项数量、待决策表格或压缩后的 blocking / high-risk 决策摘要和三个 exact 回复。checkpoint 文件中的 Decision Brief 必须完整；对话可按 `decision_brief_profile=full|compact|summary` 压缩。真实运行、凭据、安全、外部接口、数据写入、publish、live / 交易类事项必须作为不授权项单独列出；`approve` 不代表授权这些操作。CP8 必须输出 follow-up tracking 分流：关闭范围、不授权范围、风险接受项、后续 CR 候选项、取消 / deferred 项。后续 CR 候选只进入 `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md` 台账，用户决定推进某项时才创建正式 CR。

启动台账中的后续 CR 时，在当前主进程会话中说明“启动后续 CR”并给出台账路径、候选编号和目标摘要。host-orchestrator 必须先读取台账、`STATE.md.active_change`、`STATE.md.cr_tracking`、`process/changes/CR-INDEX.yaml`（若存在）和活跃 `process/changes/CR-*.md`，做 CR 冲突预检。`candidate` / `spike_candidate` 不占执行锁；候选项转正式 CR 后才把台账状态、`cr_tracking` 和 `CR-INDEX.yaml` 改为 `active`，写入正式 CR 路径。若已有未完成 CR 且影响面重叠，默认不得并行推进，必须让用户在合并到现有 CR、保持候选等待、标记 `blocked`、拆分无冲突子集或 `superseded` 中选择。

状态查询必须列出 `active formal CR`、`blocked formal CR`、`follow-up candidate`、`spike_candidate` 和 `stale_status_conflicts`，不能只返回唯一 active CR。若目标项目存在 `meta-flow check cr-tracking`，host-orchestrator 在状态盘点、候选 CR 启动、CR 关闭和 CP8 follow-up 分流后运行或记录跳过原因；该脚本会检查 `STATE.md.active_change`、正式 CR、follow-up 台账和 `CR-INDEX.yaml` 的一致性。

CP6 / CP7 必须包含 `Agent Dispatch Evidence`。handoff 文件只表示交接，不表示目标 agent 已执行；编码和验证完成必须有真实子 agent 调度证据，或用户明确批准的 `inline-fallback`。CP6 还必须记录实现执行证据：复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / 护栏 / 平台适配 / 发布相关 Story 输出完整 `IMPLEMENTATION.md`；低风险 Story 可写 Story 摘要或 DEV-LOG，但必须说明 N/A 理由。CP7 必须记录验证执行证据：验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题和剩余风险、阶段决策。

| CP | 名称 | 类型 |
|----|------|------|
| CP0 | 原始请求受理门 | 自动 |
| CP1 | 用户场景完备门 | 自动 |
| CP2 | 需求基线门 | 自动预检 + 人工 |
| CP3 | 蓝图 / HLD 架构评审门 | 自动预检 + 人工 |
| CP4 | Story 拆解与并行安全门 | 自动预检（汇入 CP5） |
| CP5 | Story 设计证据可实现性门 | 全量 / 批次自动预检 + 人工；含 full-lld / technical-note / waived 证据和 clarification queue 收敛检查 |
| CP6 | Story 编码完成门 | 滚动自动；检查实现执行证据 |
| CP7 | Story 验证完成门 | 滚动自动；检查验证执行证据和结论分级 |
| CP8 | 交付就绪门 | 自动预检 + 人工 |

## 软件开发工作流产物

Meta Flow 的软件开发工作流在 CP2 / CP3 / CP7 / CP8 增加工程化产物，但不新增人工门编号：

| 阶段 | 关键产物 | 边界 |
|---|---|---|
| CP2 前 | `docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/product/STORY-MAP.md`、`docs/product/MVP-SCOPE.md`、`docs/product/RELEASE-SLICES.md` | 用于把用户场景转成工程验证覆盖、产品范围和发布切片；不包含底层实现步骤 |
| CP3 前 | `docs/design/BLUEPRINT.md`、`docs/design/DOMAIN-MAP.md`、`docs/design/DEPENDENCY-MAP.md`、`docs/design/HLD.md` | 蓝图定义 Feature / Epic 边界、领域对象、数据归属和依赖方向；HLD 消费这些边界并给出系统架构 |
| CP6 前 | `process/stories/STORY-*-IMPLEMENTATION.md`、`docs/features/<feature>/IMPLEMENTATION.md`，或 Story 卡片 / DEV-LOG 实现摘要 | 将设计证据转成实现对象、契约映射、测试 / Fixture、最小切片、平台差异、本地验证和交接摘要；复杂 / 高风险等场景强制完整文档，低风险可轻量化 |
| CP7 | `docs/quality/VERIFICATION-REPORT.md`、`docs/quality/TEST-REPORT.md`、`docs/quality/REVIEW.md`、`docs/quality/FIXES.md` | 记录验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、验证命令、覆盖缺口、独立 review findings、回修 / 设计澄清输入和阶段决策；`PASS_WITH_RISK` 风险进入 CP8 |
| CP8 | `process/release/RELEASE-CONTEXT.yaml`、`docs/release/RELEASE-NOTES.md`、`docs/release/DEPLOY-CHECKLIST.md`、`docs/release/ROLLBACK.md`、`docs/release/MIGRATION.md`、`docs/release/FEEDBACK.md` | 发布准备先生成 capsule 摘要，再按 `release_artifact_profile=minimal|compact|full` 裁剪发布产物；`release_decision=READY|READY_WITH_RISK` 可进入终验，`NOT_READY` 阻断，`RELEASED|FAILED` 需要独立真实发布授权；`FEEDBACK.md` 不替代 follow-up tracking 台账 |

## Workflow Eval 与 Prompt Bundle

Meta Flow 通过 `project_kind` 和 `validation_target.sut_type` 在同一主流程内区分纯代码、workflow、prompt-skill、agentic-code 和 mixed 项目。纯代码项目默认使用目标项目原生测试、构建、静态检查和质量评审；workflow / prompt / mixed 对象增加 workflow eval 和 prompt bundle 证据。

本地 eval 命令：

```bash
meta-flow eval validate --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml
meta-flow eval run --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/generated-workflow-basic
meta-flow eval suite-health --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md
meta-flow eval run --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/runtime-workflow-basic
meta-flow eval runtime-run --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --sample RT-GENERIC-FULL-20260617 --platform codex --workspace evals/fixtures/runtime-workflow-basic/runtime/workspace-basic --mode collect --out process/evals/runtime-run
meta-flow eval suite-health --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md
meta-flow eval feedback sync --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/feedback/raw
meta-flow eval feedback normalize --in process/evals/feedback/raw --out process/evals/feedback/run-exec
meta-flow eval feedback triage --runs process/evals/feedback/run-exec --out process/evals/feedback/triage
meta-flow eval release-check --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --runs process/evals/runs --profile release --triage process/evals/feedback/triage --format json --json-out process/evals/release-check.json
```

`WORKFLOW-EVAL.yaml`、`PROMPT-BUNDLE.yaml` 和 `CASE-REGISTRY.yaml` 是 generated workflow / prompt-skill 产物的验证契约。`process/evals/runs/<run-id>/run-summary.json` 是 CP7 的输入证据之一，但 eval run PASS 不等于 CP7 PASS；`verification-execution` 仍必须输出验证对象清单、追踪矩阵、设计契约验证、分层验证计划、问题和风险。

通用 eval 能力包括 `runtime_artifact`、`runtime-run`、`install_mapping`、`feedback sync/normalize/triage/analyze`、`mutate`、`backlog list/check/close`、`suite-health` 和 `release-check`。`runtime_artifact` 只读取已有运行工作区，支持 `RUNTIME-SAMPLE-REGISTRY.yaml`、`sample_ids`、`profile=partial|full|regression`、expected BLOCKED 样本、阶段顺序、内容密度、空文件 / 模板残留、trace chain、Gate、delivery、coverage 和表格检查；`runtime-run` 只负责 dry-run / manual-handoff / collect 证据，生成 RUN-EXEC 与 runtime artifact manifest，不启动 Agent、不判分。真实执行 Agent、git 拉取、外部模型、网络或写远端都必须按授权边界单独处理。feedback 必须先标准化为 RUN-EXEC，再 triage 为 `ISSUE_DRAFT`、`GAP`、`BACKLOG`、`ENVIRONMENT`、`USAGE`、`DUPLICATE` 或 `NO_ACTION`，不能把所有现场反馈自动升级为 ISSUE。`suite-health` 是趋势报告，`release-check` 才是发布门禁，输出 `PASS|PASS_WITH_RISK|BLOCKED` 和机器可读 JSON。

Promptfoo / DeepEval / Langfuse / Garak 默认 disabled。任何网络、凭据、trace 上传、外部模型调用、publish、live 或 production 写入都必须单独形成 `runtime_authorization` 决策项。

## 子 Agent 调度证据

`host-orchestrator` 调用 `meta-dev`、`meta-qa` 等功能 Agent 时，必须记录平台调度证据：

- Codex：新任务记录 `spawn_agent`，复用任务记录 `resume_agent` 或 `send_input`
- Claude Code / OpenClaw：记录平台 Task/Subagent 标识
- `process/handoffs/*.md` 必须包含 `dispatch` 区，记录 `mode`、`canonical_role`、`codex_agent_name`、`reasoning_profile`、`dispatch_trigger`、`agent_id` / `thread_id`、`tool_name`、`spawned_at` / `resumed_at`、`completed_at`

若当前运行模式不能拉起子 agent，默认阻断。只有用户明确批准时，才允许 `dispatch.mode=inline-fallback`，并必须写明 fallback 原因和批准信息。

用户启动正式工作流后，同工作流内默认允许 `host-orchestrator` 自动拉起所需功能 Agent；该授权只覆盖真实子 agent 调度，不覆盖 inline fallback。

CP6 / CP7 的 `Agent Dispatch Evidence` 中若缺少真实工具调用、`codex_agent_name` / `reasoning_profile` / `dispatch_trigger` 或用户批准的 fallback，Story 不得推进到完成态。

## fast-lane 快速模式

`fast-lane` 用于低风险轻量实现、小型规则 / Skill / Agent 修改和文档更新。它可以减少需求、HLD、LLD、IMPLEMENTATION、VERIFICATION 和 release 文档厚度，发布阶段默认使用 `release_artifact_profile=minimal`，但不能跳过 CP6 / CP7、Agent Dispatch Evidence、实现执行证据摘要、验证执行证据摘要、`RELEASE-CONTEXT.yaml` 或 CP8 终验摘要。命中架构、权限、安全、平台安装、外部接口、文件所有权冲突或多 Story 依赖时，必须升级到 `standard`。

CP2 / CP3 的讨论增强不会强行升级所有小修改；fast-lane 下若 discussion log / checkpoint 不适用，自动检查必须记录 N/A 原因。

## 安装

推荐作为全局命令安装（本地开发建议 editable，便于读取当前 checkout 的 `delivery/` 资产）：

```bash
uv tool install --editable .
meta-flow install codex --scope user
meta-flow install codex --scope project --project-dir /path/to/project
meta-flow uninstall codex --scope project --project-dir /path/to/project
meta-flow install codex --help
meta-flow uninstall codex --help
```

项目级安装未提供 `--project-dir` 时，交互式终端会提示确认当前目录或输入其他目录；非交互环境必须显式传入 `--project-dir`。

从仓库根目录运行：

```bash
uv run --python 3.11 python delivery/scripts/install.py claude
```

或把 `delivery/` 作为独立仓库根目录运行：

```bash
cd delivery
uv run --python 3.11 python scripts/install.py claude
```

支持的平台：

- `claude`
- `codex`
- `openclaw`

常用示例：

```bash
meta-flow install codex --scope user --component rules
meta-flow install codex --scope project --component full --project-dir /path/to/project
meta-flow uninstall codex --scope project --component rules --project-dir /path/to/project
uv run --python 3.11 python delivery/scripts/install.py claude --dry-run
```

legacy 兼容示例：

```bash
uv run --python 3.11 python delivery/scripts/install.py codex --scope user --content rules
```

组件参数：

- `rules`：只安装平台规则入口（如 AGENTS.md / CLAUDE.md）。
- `agent`：安装 agents + skills。
- `full`：同时安装 rules 与 agent 组件。

默认值：

- `--scope user` 默认 `--component rules`。
- `--scope project` 默认 `--component full`。
- `meta-flow uninstall <platform>` 未指定 `--component` 时默认卸载 `full`；可用 `--component rules|agent|full` 精确卸载组件。
- legacy `--content all|agents|skills|rules` 保留兼容，但新命令优先使用 `--component`。

## Agent 命令与显示区分

| canonical role | Codex 命令 / nickname_candidates | Codex `model_reasoning_effort` | Claude Code color |
|---|---|---|---|
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `medium` | `orange` |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `high` | `yellow` |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu`、`dev-he`、`dev-lv`、`dev-shi`、`dev-zhang`、`dev-kong` | `medium` | `green` |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong`、`qa-cao`、`qa-yan`、`qa-hua`、`qa-jin`、`qa-wei` | `high` | `cyan` |
| `meta-doc` | `doc-cao`、`doc-yan`、`doc-hua`、`doc-jin`、`doc-wei` | `low` | `purple` |

canonical role 只覆盖功能子 agent，用于状态机、handoff 与检查点审计；Host Orchestrator 是主进程职责，不安装 Codex / Claude Code agent 文件。Codex 使用 `nickname_candidates` 作为命令别名，并显式写入 `model_reasoning_effort`；Claude Code 文件型 subagent 不使用 nickname，安装器写入 `color` 区分不同子 agent。主进程建议父会话在标准 / 复杂工作流中使用 `model_reasoning_effort="high"`，fast-lane 或小范围机械修改可使用 `medium`。

Codex 还会安装动态思考 profile，但 canonical role 不变：`meta-dev-debugger` 用于重复失败和复杂追因（`high`），`meta-se-critical` 用于架构冻结 / contract / 重大 ADR（`xhigh`），`meta-qa-critical` 用于 CP5 / CP7 / CP8、发布前和高风险验证（`xhigh`）。Host Orchestrator 调度时必须在 `active_agents[]` 与 handoff `dispatch` 记录 `canonical_role`、`codex_agent_name`、`reasoning_profile` 和 `dispatch_trigger`。

Codex 主进程启动正式工作流后默认授权真实子 agent 调度；若当前工具面有 `spawn_agent` / `resume_agent` / `send_input`，创建 `mode=subagent` handoff 后必须调用对应工具。只创建 handoff 不能算子 agent 已执行；工具不可用时必须阻断并记录 `subagent_dispatch.available=false`，除非用户明确批准 `inline-fallback`。

## 目录约束

1. `scripts/` 只放安装器入口：`install.py`、`install.sh`、`install.ps1`
2. Skill 私有模板、脚本、示例必须放在 `skills/<skill>/` 目录内
3. Python 缓存文件（`__pycache__/`、`*.pyc`）不得进入交付包
4. Codex Agent 与 Skill 路径分开治理：Agent 在 `.codex/agents` / `~/.codex/agents`，Skill 在 `.agents/skills` / `~/.agents/skills`
5. 安装器写入前会检查路径组件冲突；目标目录任一级被普通文件占用时会 fail fast 并提示修复

## 交付出口路由

当前仓库 `delivery/` 只作为 meta-flow 自身交付包。若工作流服务外部 production 项目，host-orchestrator 必须先扫描目标项目已有交付目录，以及 `README.md` / `README.*` / `docs/` 的交付物或发布约定；存在约定时按目标项目执行，不存在时先提出建议并等待用户确认，不能默认写当前仓库 `delivery/`。

更多使用方式见 `doc/USER-MANUAL.md`。
