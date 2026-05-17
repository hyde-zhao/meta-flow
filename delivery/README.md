# Meta Flow Delivery Package

本目录是可独立交付的 Meta Flow 产物包，包含：

- `agents/`：交付 Agent 定义
- `skills/`：交付 Skill 定义及其私有运行时资产
- `rules/`：平台规则文件
- `scripts/`：安装器入口
- `doc/PLATFORM-CONTRACTS.yaml`：平台安装路径契约；安装器和校验脚本以此为路径真相源

## 工作流检查点

安装后的 Meta Flow 使用 CP0-CP8 检查点。自动检查结果写入目标项目的 `process/checks/CP*.md`；人工审查稿写入 `checkpoints/CP*.md`。人工确认由 `meta-po` 发起，发起时会提示具体 checklist 文件路径，审查后必须回填“人工审查结果”。

CP6 / CP7 必须包含 `Agent Dispatch Evidence`。handoff 文件只表示交接，不表示目标 agent 已执行；编码和验证完成必须有真实子 agent 调度证据，或用户明确批准的 `inline-fallback`。

| CP | 名称 | 类型 |
|----|------|------|
| CP0 | 原始请求受理门 | 自动 |
| CP1 | 用户场景完备门 | 自动 |
| CP2 | 需求基线门 | 自动预检 + 人工 |
| CP3 | HLD 架构评审门 | 自动预检 + 人工 |
| CP4 | Story 拆解与并行安全门 | 自动预检 + 人工 |
| CP5 | Story LLD 可实现性门 | 批次自动预检 + 人工 |
| CP6 | Story 编码完成门 | 滚动自动 |
| CP7 | Story 验证完成门 | 滚动自动 |
| CP8 | 交付就绪门 | 自动预检 + 人工 |

## 子 Agent 调度证据

`meta-po` 调用 `meta-dev`、`meta-qa` 等功能 Agent 时，必须记录平台调度证据：

- Codex：新任务记录 `spawn_agent`，复用任务记录 `resume_agent` 或 `send_input`
- Claude Code / OpenClaw：记录平台 Task/Subagent 标识
- `process/handoffs/*.md` 必须包含 `dispatch` 区，记录 `mode`、`agent_id` / `thread_id`、`tool_name`、`spawned_at` / `resumed_at`、`completed_at`

若当前运行模式不能拉起子 agent，默认阻断。只有用户明确批准时，才允许 `dispatch.mode=inline-fallback`，并必须写明 fallback 原因和批准信息。

## 安装

推荐作为全局命令安装（本地开发建议 editable，便于读取当前 checkout 的 `delivery/` 资产）：

```bash
uv tool install --editable .
meta-flow install --platform codex --scope user
meta-flow install --platform codex --scope project --project-dir /path/to/project
```

项目级安装未提供 `--project-dir` 时，交互式终端会提示确认当前目录或输入其他目录；非交互环境必须显式传入 `--project-dir`。

从仓库根目录运行：

```bash
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code
```

或把 `delivery/` 作为独立仓库根目录运行：

```bash
cd delivery
uv run --python 3.11 python scripts/install.py --platform claude-code
```

支持的平台：

- `claude-code`
- `codex`
- `openclaw`

常用示例：

```bash
meta-flow install --platform codex --scope user --component rules
meta-flow install --platform codex --scope project --component agent --project-dir /path/to/project
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code --dry-run
```

legacy 兼容示例：

```bash
uv run --python 3.11 python delivery/scripts/install.py --platform codex --scope user --content rules
```

组件参数：

- `rules`：只安装平台规则入口（如 AGENTS.md / CLAUDE.md）。
- `agent`：安装 agents + skills。
- `full`：同时安装 rules 与 agent 组件。

默认值：

- `--scope user` 默认 `--component rules`。
- `--scope project` 默认 `--component agent`。
- legacy `--content all|agents|skills|rules` 保留兼容，但新命令优先使用 `--component`。

## Agent 命令与显示区分

| canonical role | Codex 命令 / nickname_candidates | Claude Code color |
|---|---|---|
| `meta-po` | `po-zhao`、`po-qian`、`po-sun`、`po-li`、`po-zhou` | `red` |
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `orange` |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `yellow` |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu` | `green` |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong` | `cyan` |
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
