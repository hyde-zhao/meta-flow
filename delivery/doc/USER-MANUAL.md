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
meta-flow install --platform codex --scope user
meta-flow install --platform codex --scope project --project-dir /path/to/project
```

项目级安装未提供 `--project-dir` 时，交互式终端会提示确认当前目录或输入其他目录；非交互环境必须显式传入 `--project-dir`。

从仓库根目录执行：

```bash
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code
uv run --python 3.11 python delivery/scripts/install.py --platform codex --project-dir /path/to/project
uv run --python 3.11 python delivery/scripts/install.py --platform openclaw --dry-run
```

从 `delivery/` 目录执行：

```bash
cd delivery
uv run --python 3.11 python scripts/install.py --platform claude-code
uv run --python 3.11 python scripts/install.py --platform codex --scope user
```

包装脚本：

```powershell
scripts\install.ps1 --platform codex --dry-run
```

```bash
bash scripts/install.sh --platform claude-code --dry-run
```

## 3. 安装内容

- `rules`：平台规则入口（AGENTS.md / CLAUDE.md 等）
- `agent`：平台 Agent 定义 + Skill 定义与 Skill 私有运行时资产
- `full`：同时安装 rules 与 agent

可通过 `--component rules|agent|full` 控制安装范围。默认值：

- `--scope user` 默认只安装 `rules`
- `--scope project` 默认只安装 `agent`

legacy `--content agents|skills|rules|all` 保留兼容，但新文档优先使用 `--component`。

## 3.1 Agent 命令与显示区分

canonical role 仍为 `meta-*`，用于状态机、handoff、检查点和审计。平台展示按下表安装：

| canonical role | Codex 命令 / nickname_candidates | Claude Code color |
|---|---|---|
| `meta-po` | `po-zhao`、`po-qian`、`po-sun`、`po-li`、`po-zhou` | `red` |
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `orange` |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `yellow` |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu` | `green` |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong` | `cyan` |
| `meta-doc` | `doc-cao`、`doc-yan`、`doc-hua`、`doc-jin`、`doc-wei` | `purple` |

Codex 安装器把命令别名写入 `.codex/agents/*.toml` 的 `nickname_candidates`。Claude Code 文件型 subagent 不使用 nickname，安装器写入 `color` 字段，通过颜色区分不同子 agent。

## 4. DryRun 与卸载

```bash
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code --dry-run
uv run --python 3.11 python delivery/scripts/install.py --platform codex --scope user --uninstall
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
@meta-po 继续
@meta-po 回退到 CP3 HLD 架构评审前
```

### 6.1 标准推进顺序

1. `meta-po` 初始化请求并写入 CP0 自动检查结果。
2. `meta-pm` 澄清需求，沉淀 `USE-CASES.md` 和 `REQUIREMENTS.md`，写入 CP1 / CP2 自动检查结果。
3. CP2 人工确认通过后，`meta-se` 输出 `HLD.md` 和 CP3 自动预检。
4. CP3 人工确认通过后，`meta-se` 输出 `STORY-BACKLOG.md`、`DEVELOPMENT-PLAN.yaml` 和 CP4 自动预检。
5. CP4 人工确认通过后，`meta-po` 按 Story DAG 确定本轮 LLD 设计批次，组织 `meta-dev` 并行输出批次内全部 `STORY-{id}-{story_slug}-LLD.md` 和 CP5 自动预检，再发起一次批次人工确认。
6. 批次 CP5 确认且批次内 Story 的 `dev_gate` 满足后，`meta-po` 必须通过平台子 agent 能力调度 `meta-dev`，并在 `STATE.md.agent_lifecycle` 与 handoff `dispatch` 中记录证据；实现完成后写入 CP6 编码完成检查结果。
7. `meta-po` 必须通过平台子 agent 能力调度 `meta-qa` 执行验证，并记录调度证据；验证完成后写入 CP7 验证完成检查结果，并生成安装脚本。
8. `meta-doc` 最后输出 README 和 USER-MANUAL，CP8 自动预检和人工终验通过后进入 delivered。

### 6.2 检查点文件

所有检查点都包含 Entry Criteria、Checklist、Exit Criteria、Deliverables。自动检查点必须写入逐项检查结果；人工检查点必须有可审查的 checklist 文件。

| CP | 名称 | 类型 | 文件 |
|----|------|------|------|
| CP0 | 原始请求受理门 | 自动 | `process/checks/CP0-REQUEST-INTAKE.md` |
| CP1 | 用户场景完备门 | 自动 | `process/checks/CP1-USE-CASE-COMPLETENESS.md` |
| CP2 | 需求基线门 | 自动预检 + 人工 | `process/checks/CP2-REQUIREMENTS-BASELINE.md`；`checkpoints/CP2-REQUIREMENTS-BASELINE.md` |
| CP3 | HLD 架构评审门 | 自动预检 + 人工 | `process/checks/CP3-HLD-CONSISTENCY.md`；`checkpoints/CP3-HLD-REVIEW.md` |
| CP4 | Story 拆解与并行安全门 | 自动预检 + 人工 | `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md`；`checkpoints/CP4-STORY-PLAN-REVIEW.md` |
| CP5 | Story LLD 可实现性门 | 批次自动预检 + 人工 | `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`；`checkpoints/CP5-{batch_id}-LLD-BATCH.md` |
| CP6 | Story 编码完成门 | 滚动自动 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` |
| CP7 | Story 验证完成门 | 滚动自动 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` |
| CP8 | 交付就绪门 | 自动预检 + 人工 | `process/checks/CP8-DELIVERY-READINESS.md`；`checkpoints/CP8-DELIVERY-READINESS.md` |

CP6 / CP7 自动检查结果必须包含 `Agent Dispatch Evidence` 小节，用来证明 `meta-dev` / `meta-qa` 是真实子 agent 执行，而不是只有 handoff 文档。

合格证据包括：

- Codex `spawn_agent` / `resume_agent` / `send_input` 的返回标识
- Claude Code / OpenClaw 的 Task/Subagent 标识
- `STATE.md.agent_lifecycle.active_agents` 中非空的 `agent_id` 或 `thread_id`
- handoff `dispatch` 中的 `tool_name`、`spawned_at` / `resumed_at`、`completed_at`

只有 `to_agent: meta-dev`、`to_agent: meta-qa` 或 handoff `status=completed`，不能作为子 agent 执行证据。

如果当前运行模式无法拉起子 agent，meta-po 必须阻断并说明原因。用户明确批准后，才允许 `dispatch.mode=inline-fallback`，并必须写明 `fallback_reason`、`approved_by`、`approved_at`。这种结果应表述为 meta-po 代执行，不能表述为 meta-dev / meta-qa 独立完成。

### 6.3 人工确认操作

meta-po 发起人工检查时会提示 checklist 文件路径，例如：

```text
请审查：checkpoints/CP3-HLD-REVIEW.md
该文件包含本检查点的 Entry Criteria、Checklist、Exit Criteria、Deliverables 和自动预检摘要。
```

审查后可以在对应 `checkpoints/CP*.md` 的“人工审查结果”中填写结论，也可以直接在对话中回复。Claude Code 可继续使用结构化选择。Codex 只有在当前工具面明确提供可用的 `request_user_input` / 选择 UI 时才使用结构化选择；否则默认使用 exact 文本确认。系统对用户只展示三个推荐回复：`approve`、`修改: <具体修改点>`、`reject`；历史别名 `1/通过`、`2/修改: ...`、`3/不通过` 仅作为兼容解析，不作为主要提示文案。

```text
approve                  # 确认通过
修改: <具体修改点>        # 需要修改
reject                   # 不通过并回退
```

不匹配上述 exact 输入时，meta-po 不得推进状态。

用户直接在对话中确认时，meta-po 仍必须把结论回填到对应 `checkpoints/CP*.md`。

### 6.4 何时显式声明 meta-self-dev

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
  - claude-code
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
