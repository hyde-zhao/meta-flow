# Meta Flow Delivery Package

本目录是可独立交付的 Meta Flow 产物包，包含：

- `agents/`：交付 Agent 定义
- `skills/`：交付 Skill 定义及其私有运行时资产
- `rules/`：平台规则文件
- `scripts/`：安装器入口
- `doc/PLATFORM-CONTRACTS.yaml`：平台安装路径契约；安装器和校验脚本以此为路径真相源

## CP2 / CP3 讨论增强

标准模式下，Meta Flow 会在两个关键人工门前加强讨论，但不新增 CP 编号或独立人工门：

- CP2 前，`meta-pm` 先识别 3-4 个 `Scenario Gray Areas`，让用户选择 1-3 个重点讨论；未选但有价值的想法进入 `Deferred Ideas`，不污染当前 scope。
- CP3 前，`meta-se` 先识别 `Architecture Gray Areas` 并在阶段委托内直接与用户完成 advisor table-first 讨论；需要额外 reviewer lane 时由 `meta-po` 汇总。advisor lane 优先使用 `Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch` 表格。
- HLD 必须记录适用性矩阵、Use Case → Architecture Traceability、关键场景模拟、优化 / 牺牲 / 切换条件和自审结果。

讨论日志写入 `process/discussions/`，恢复点写入 `process/checks/`：

| 阶段 | Discussion Log | Discussion Checkpoint |
|---|---|---|
| CP2 | `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md` | `process/checks/CP2-DISCUSSION-CHECKPOINT.json` |
| CP3 | `process/discussions/CP3-HLD-DISCUSSION-LOG.md` | `process/checks/CP3-DISCUSSION-CHECKPOINT.json` |

Discussion Log 用于审计和恢复，不替代正式的 `USE-CASES.md`、`REQUIREMENTS.md`、`HLD.md`、`ARCHITECTURE-DECISION.md` 或 Decision Brief。

复杂项目的异步 power mode（如 `process/discussions/CP2-QUESTIONS.json/html`、`CP3-QUESTIONS.json/html`）保留为后续可选增强，本交付包不默认生成这些文件，也不把它们作为验收前置。

## 阶段委托与 LLD 问题队列

Meta Flow 的交互路径分两类：

- `requirement-clarification`：meta-po 启动或复用 `meta-pm` 后，将阶段内用户交互权委托给 `meta-pm`。用户可直接与 `meta-pm` 多轮讨论 Scenario Gray Areas、场景和需求草案；草案确认“可提交给 meta-po 汇总”后，`meta-pm` 写交还摘要，meta-po 回收并发起 CP2。
- `solution-design`：meta-po 启动或复用 `meta-se` 后，将阶段内用户交互权委托给 `meta-se`。用户可直接与 `meta-se` 讨论 Architecture Gray Areas、advisor table 和 HLD 草案；草案确认“可提交给 meta-po 发起 CP3”后，`meta-se` 写交还摘要，meta-po 回收并发起 CP3。
- `story-planning` 的并行 LLD：多个 `meta-dev` 不直接并发问用户。实现灰区写入 `STATE.md.parallel_execution.lld_clarification_queue`，由 meta-po 作为 question broker 合并、排序、批量询问用户、回填答案并分发给对应 `meta-dev`。

阶段委托状态写入 `STATE.md.delegated_interaction`。这只代表阶段内交互权委托，不代表 CP2 / CP3 已通过。LLD clarification 队列存在未回答 `blocks_lld=true` 项时，meta-po 不得发起 CP5；转 OPEN / Spike 的项必须在 CP5 Decision Brief、LLD 和 DEV-LOG 中暴露。

## 工作流检查点

安装后的 Meta Flow 使用 CP0-CP8 检查点。自动检查结果写入目标项目的 `process/checks/CP*.md`；关键人工审查稿写入 `checkpoints/CP*.md`。CP2 / CP3 / CP5 / CP8 由 `meta-po` 发起人工确认，发起前必须生成 Decision Brief 并提示具体 checklist 文件路径，审查后必须回填“人工审查结果”。CP4 只生成自动预检并汇入 CP5。

CP6 / CP7 必须包含 `Agent Dispatch Evidence`。handoff 文件只表示交接，不表示目标 agent 已执行；编码和验证完成必须有真实子 agent 调度证据，或用户明确批准的 `inline-fallback`。

| CP | 名称 | 类型 |
|----|------|------|
| CP0 | 原始请求受理门 | 自动 |
| CP1 | 用户场景完备门 | 自动 |
| CP2 | 需求基线门 | 自动预检 + 人工 |
| CP3 | HLD 架构评审门 | 自动预检 + 人工 |
| CP4 | Story 拆解与并行安全门 | 自动预检（汇入 CP5） |
| CP5 | Story LLD 可实现性门 | 全量 / 批次自动预检 + 人工；含 clarification queue 收敛检查 |
| CP6 | Story 编码完成门 | 滚动自动 |
| CP7 | Story 验证完成门 | 滚动自动 |
| CP8 | 交付就绪门 | 自动预检 + 人工 |

## 子 Agent 调度证据

`meta-po` 调用 `meta-dev`、`meta-qa` 等功能 Agent 时，必须记录平台调度证据：

- Codex：新任务记录 `spawn_agent`，复用任务记录 `resume_agent` 或 `send_input`
- Claude Code / OpenClaw：记录平台 Task/Subagent 标识
- `process/handoffs/*.md` 必须包含 `dispatch` 区，记录 `mode`、`agent_id` / `thread_id`、`tool_name`、`spawned_at` / `resumed_at`、`completed_at`

若当前运行模式不能拉起子 agent，默认阻断。只有用户明确批准时，才允许 `dispatch.mode=inline-fallback`，并必须写明 fallback 原因和批准信息。

用户启动正式工作流后，同工作流内默认允许 `meta-po` 自动拉起所需功能 Agent；该授权只覆盖真实子 agent 调度，不覆盖 inline fallback。

## fast-lane 快速模式

`fast-lane` 用于低风险轻量实现、小型规则 / Skill / Agent 修改和文档更新。它可以减少需求、HLD、LLD 的文档厚度和人工门数量，但不能跳过 CP6 / CP7、Agent Dispatch Evidence 或 CP8 终验摘要。命中架构、权限、安全、平台安装、外部接口、文件所有权冲突或多 Story 依赖时，必须升级到 `standard`。

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

| canonical role | Codex 命令 / nickname_candidates | Claude Code color |
|---|---|---|
| `meta-po` | `po-zhao`、`po-qian`、`po-sun`、`po-li`、`po-zhou` | `red` |
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `orange` |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `yellow` |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu`、`dev-he`、`dev-lv`、`dev-shi`、`dev-zhang`、`dev-kong` | `green` |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong`、`qa-cao`、`qa-yan`、`qa-hua`、`qa-jin`、`qa-wei` | `cyan` |
| `meta-doc` | `doc-cao`、`doc-yan`、`doc-hua`、`doc-jin`、`doc-wei` | `purple` |

canonical role 不变，仍用于状态机、handoff 与检查点审计。Codex 使用 `nickname_candidates` 作为命令别名；Claude Code 文件型 subagent 不使用 nickname，安装器写入 `color` 区分不同子 agent。

## 目录约束

1. `scripts/` 只放安装器入口：`install.py`、`install.sh`、`install.ps1`
2. Skill 私有模板、脚本、示例必须放在 `skills/<skill>/` 目录内
3. Python 缓存文件（`__pycache__/`、`*.pyc`）不得进入交付包
4. Codex Agent 与 Skill 路径分开治理：Agent 在 `.codex/agents` / `~/.codex/agents`，Skill 在 `.agents/skills` / `~/.agents/skills`
5. 安装器写入前会检查路径组件冲突；目标目录任一级被普通文件占用时会 fail fast 并提示修复

## 交付出口路由

当前仓库 `delivery/` 只作为 meta-flow 自身交付包。若工作流服务外部 production 项目，meta-po 必须先扫描目标项目 `README.md` / `README.*` / `docs/` 的交付物或发布约定；存在约定时按目标项目执行，不存在时先提出建议并等待用户确认，不能默认写当前仓库 `delivery/`。

更多使用方式见 `doc/USER-MANUAL.md`。
