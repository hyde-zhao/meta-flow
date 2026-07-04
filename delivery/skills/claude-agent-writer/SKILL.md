---
name: claude-agent-writer
description: >-
  当需要为 Claude Code 平台编写子 Agent 文件（.claude/agents/*.md）时使用。
  触发词包括：写 Claude Agent、创建 Claude 子代理、Claude subagent、Claude sub-agent。
  适用场景：meta-dev 实现 Claude Code 平台的 Agent 产物时。
argument-hint: "Agent 名称（kebab-case）、职责描述、是否需要限制工具"
user-invokable: true
status: active
---

# Claude Code Sub-agent 写作标准

> 规范来源：https://code.claude.com/docs/zh-CN/sub-agents

---

## 文件规格

| 项目 | 规范 |
|------|------|
| **存放路径** | `.claude/agents/<name>.md` |
| **文件名** | kebab-case，如 `code-reviewer.md` |
| **格式** | YAML Frontmatter + Markdown 正文（系统提示） |

---

## Frontmatter 字段完整规范

```yaml
---
name: <agent-name>           # 必填：小写字母+连字符，唯一标识符
description: <description>   # 必填：Claude 何时委托给此 Agent（关键！）
tools: Read, Grep, Glob      # 可选：允许使用的工具，逗号分隔；省略则继承全部工具
disallowedTools: Write, Edit # 可选：明确禁止的工具
model: sonnet                # 可选：sonnet / opus / haiku / inherit（默认 inherit）
permissionMode: default      # 可选：default / acceptEdits / auto / bypassPermissions / plan
maxTurns: 10                 # 可选：最大 Agent 轮数
skills: skill-name           # 可选：启动时注入的 Skill 内容
memory: project              # 可选：user / project / local（开启跨会话记忆）
background: false            # 可选：true = 始终作为后台任务运行
effort: medium               # 可选：low / medium / high / max（仅 Opus 4.6）
isolation: worktree          # 可选：worktree = 在独立 git worktree 中运行
color: blue                  # 可选：red/blue/green/yellow/purple/orange/pink/cyan
---
```

**必填字段**：`name` + `description`，其余均为可选。

---

## 可用工具名称（tools 字段）

| 工具 | 说明 |
|------|------|
| `Read` | 读取文件内容 |
| `Write` | 创建新文件 |
| `Edit` / `MultiEdit` | 编辑已有文件 |
| `Grep` | 在文件内容中搜索 |
| `Glob` | 按路径模式查找文件 |
| `Bash` | 执行 shell 命令 |
| `WebSearch` / `WebFetch` | 网络搜索/抓取 |
| `TodoWrite` | 任务列表管理 |
| `AskUserQuestion` | 向用户发起结构化提问；仅允许需要 direct ask 的 Agent 使用 |

### AskUserQuestion 授权规则

`AskUserQuestion` 不是默认可用能力。只要 Claude Code subagent 需要直接向用户提问，就必须在 frontmatter 的 `tools:` 中显式包含 `AskUserQuestion`。

Meta Flow canonical agent 的授权边界：

| Agent | 是否声明 `AskUserQuestion` | 原因 |
|---|---:|---|
| `meta-pm` | 是 | `requirement-clarification` 阶段委托内可直接问场景 / 需求 / 范围问题 |
| `meta-se` | 是 | `solution-design` 阶段委托内可直接问蓝图 / 架构 / HLD 问题 |
| `meta-dev` | 否 | 默认写入 LLD clarification queue，由 `host-orchestrator` broker |
| `meta-qa` | 否 | 默认写检查结果或待人工决策项，由 `host-orchestrator` 汇总 |
| `meta-doc` | 否 | 默认写文档缺口或建议，由 `host-orchestrator` 汇总 |

如果某个新 Agent 需要 direct ask，必须同时满足：

1. frontmatter `tools:` 包含 `AskUserQuestion`。
2. 正文说明可直接提问的阶段、问题类型和禁止范围。
3. `context-handoff` 的 `question_permission.can_ask_user=true` 且 `structured_choice_allowed=true`。
4. `platform capability probe record method=direct`。

否则必须走 Host Orchestrator relay、clarification queue 或 exact-text 协议，不得声称可直接使用用户提问工具。

---

## 最关键：description 字段写作规范

`description` 是 Claude 决定**何时自动委托**的唯一依据，必须包含：

1. **触发条件**：明确说明什么任务类型应触发此 Agent
2. **能力边界**：Agent 能做什么、不能做什么
3. **触发词**（可选）：列举关键词让 Claude 更容易识别

```yaml
# 好的 description（含触发条件、能力边界、触发词）
description: >-
  Reviews code changes for quality, security vulnerabilities, and best practices.
  Use this agent when asked to review, audit, or check code quality.
  Trigger phrases: code review, security audit, check code, review PR.
  Does NOT modify any files—read-only analysis only.

# 差的 description（过于模糊）
description: A code reviewer agent.
```

---

## 正文（系统提示）写作规范

正文是 Agent 的**完整系统提示**，有以下要点：

1. **Agent 只接收此系统提示**，不接收 Claude Code 的内置系统提示
2. **必须自给自足**：角色定位、行为边界、输出格式全部在正文中声明
3. **避免依赖外部上下文**（不要引用 Claude Code 的全局指令）
4. **明确输出格式**：描述期望的输出结构

```markdown
<!-- 正文模板 -->
你是一个[角色定位]，专注于[职责范围]。

## 职责

- [具体职责1]
- [具体职责2]

## 约束

- 只操作[类型]文件，不修改[类型]文件
- [其他约束]

## 输出格式

[描述期望的输出结构]
```

---

## 完整示例

```markdown
---
name: story-validator
description: >-
  Validates Story cards in process/stories/ to ensure they conform to
  the 3-piece mandatory format (dev_context + validation_context + acceptance_criteria).
  Use when asked to validate, check, or audit Story cards.
  Trigger phrases: 验证 Story、Story 格式检查、check story card.
  Does NOT modify story content—read-only validation only.
tools: Read, Glob, Grep
model: haiku
---

你是一个 Story 卡片格式验证专家，负责检查 `process/stories/` 目录下的 Story 卡片是否符合 3-piece 强制格式。

## 验证规则

每个 Story 卡片必须包含以下三部分：

1. **dev_context**（开发上下文）：包含输入文件、输出文件、设计约束、命名规范、平台目标
2. **validation_context**（验证上下文）：包含验证入口、验证方式、依赖环境
3. **acceptance_criteria**（量化验收标准）：包含 8 个维度的 checkbox 列表

## 输出格式

对每个 Story 输出：
- Story ID 和标题
- 是否通过（PASS / FAIL）
- 缺失的部分（如有）
- 修复建议（如有）
```

---

## 写作检查清单

完成 Agent 文件后，自检以下项目：

- [ ] `name` 字段为小写 kebab-case
- [ ] `description` 包含明确触发条件（何时使用）和能力边界（不做什么）
- [ ] `tools` 遵循最小权限原则（只列出实际需要的工具）
- [ ] 需要 direct ask 的 Claude Code Agent 已在 `tools` 中显式包含 `AskUserQuestion`
- [ ] 不应直接问用户的 Agent 未声明 `AskUserQuestion`，并说明 relay / queue 路径
- [ ] 正文系统提示自给自足，不依赖外部全局指令
- [ ] 正文包含：角色定位、职责列表、约束说明、输出格式
- [ ] 文件路径符合 `.claude/agents/<kebab-name>.md`

## Gotchas

- Claude Code subagent 使用 frontmatter 的 `color` 区分展示；不要写 Codex 专用的 `nickname_candidates`，也不要把 Codex 命令别名混入 Claude agent 文件。
- canonical role 只覆盖功能 subagent：`meta-pm`、`meta-se`、`meta-dev`、`meta-qa`、`meta-doc`；Host Orchestrator 是主进程职责，不写成 Claude Code subagent。
- 不得重新创建或引用已废弃的 `meta-dm` 作为新产物；Story 拆解职责由 `meta-se` 承担。
- `description` 是 Claude 自动委托的主要依据；只写角色名会导致误触发或不触发，必须写清触发条件、能力边界和不做事项。
- 如果限制 `tools`，正文中的职责必须与工具权限匹配；例如只读 review agent 不应声称会修改文件。
- 忘记在 direct ask agent 的 `tools` 中加入 `AskUserQuestion` 会导致 Claude Code subagent 语义上被允许提问、运行时却无法调用提问工具。
