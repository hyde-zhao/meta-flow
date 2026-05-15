# Meta Flow 问题修改记录

本文件记录本轮已完成或已开始处理的问题，便于后续审计和回归。状态含义：

- `DONE`：已完成修改并通过当时验证。
- `IN_PROGRESS`：已开始修改，仍需验证或继续补齐。
- `FOLLOW_UP`：已识别，建议后续处理。

| 编号 | 问题 | 状态 | 处理记录 |
|---|---|---|---|
| MF-001 | 项目名称和 CLI 仍使用 scope-pack / Scope Pack | DONE | 已改为 `meta-flow` / Meta Flow，并清理主要交付规则和文档中的旧命名。 |
| MF-002 | 安装状态目录仍使用 `~/.meta-workflow` | DONE | 已改为 `~/.meta-flow`，README 和安装器说明同步更新。 |
| MF-003 | project scope 未指定 `--project-dir` 时直接报错 | DONE | 已改为交互式提示确认当前目录或输入目录；非交互场景仍要求显式传入。 |
| MF-004 | 用户级 rules 中残留 meta-flow 旧内容清理需求 | DONE | 已清理用户级 Codex / Claude rules 中的相关 managed 区段。 |
| MF-005 | Codex 下可能拉起多个 meta-po | DONE | 已加入 meta-po 单例、同角色同任务复用和发现双 meta-po 时阻断规则。 |
| MF-006 | LLD 写作、Story 开发和 QA 并行策略不清晰 | DONE | 已明确 LLD / Dev / QA 并行上限、Story DAG、依赖类型和文件所有权门控。 |
| MF-007 | 检查点体系缺少完整 checklist 和自检结果要求 | DONE | 已加入 CP0-CP8，自动检查写 `process/checks/CP*.md`，人工检查写 `checkpoints/CP*.md` 并回填人工结果。 |
| MF-008 | 文档未同步刷新 | DONE | 已刷新 README、delivery README、USER-MANUAL、Skill 标准和相关规则文档。 |
| MF-009 | meta-po 使用 handoff 文档冒充 meta-dev / meta-qa 子 agent 执行 | DONE | 已完成修改：加入子 agent 调度硬门禁、`Agent Dispatch Evidence`、handoff `dispatch` frontmatter、STATE 调度证据字段和 CP6 / CP7 调度证据检查。 |

## MF-009 修改范围

| 文件 | 修改内容 |
|---|---|
| `delivery/agents/meta-po.md` | 增加子 agent 调度硬门禁，要求 Codex 使用 `spawn_agent` / `resume_agent` / `send_input`，禁止 meta-po 无授权代执行。 |
| `delivery/skills/state-router/SKILL.md` | 增加 `agent_lifecycle` 调度证据 schema、完成证据规则，以及 CP6 / CP7 推进前的证据检查。 |
| `delivery/skills/state-router/templates/STATE-TEMPLATE.md` | 增加 `platform_capabilities.subagent_dispatch`、状态枚举和 `Agent Dispatch Evidence` 策略。 |
| `delivery/skills/context-handoff/SKILL.md` | 增加 handoff `dispatch` frontmatter，区分 `subagent`、`handoff-only`、`inline-fallback`。 |
| `delivery/skills/checkpoint-manager/SKILL.md` | 要求 CP6 / CP7 包含 `Agent Dispatch Evidence` 小节，缺证据时只能 `FAIL` 或 `BLOCKED`。 |
| `delivery/rules/AGENTS.md` | 增加子 agent 调度证据和 inline fallback 门禁。 |
| `delivery/rules/CLAUDE.md` | 增加平台 Task/Subagent 证据和 CP6 / CP7 证据要求。 |
| `README.md`、`delivery/README.md`、`delivery/doc/USER-MANUAL.md`、`delivery/skills/README.md` | 同步说明调度证据、检查点和 Skill 关系。 |
| `scripts/check_delivery_guardrails.py` | 增加调度证据相关静态检查，防止后续文档回退。 |

## MF-009 验证结果

- [x] 运行 `PYTHONDONTWRITEBYTECODE=1 uv run --python 3.11 python scripts/check_delivery_guardrails.py`，结果 `OK`
- [x] 运行 `PYTHONDONTWRITEBYTECODE=1 uv run --python 3.11 meta-flow --help`，命令正常输出帮助
- [x] 检查 `rg "Agent Dispatch Evidence|inline-fallback|spawn_agent|resume_agent|send_input"` 覆盖关键文件
- [x] 检查缓存文件；仅发现 `.venv/` 下缓存，属于 `.gitignore` 和 guardrail 排除范围，未新增交付缓存
