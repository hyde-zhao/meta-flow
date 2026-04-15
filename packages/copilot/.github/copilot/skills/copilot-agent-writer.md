---
name: copilot-agent-writer
description: >-
  当需要为 GitHub Copilot CLI 平台编写自定义 Agent 文件（.github/agents/*.agent.md）时使用。
  触发词包括：写 Copilot Agent、创建自定义 Agent、Copilot CLI Agent、copilot agent.md。
  适用场景：meta-dev 实现 Copilot CLI 平台的 Agent 产物时。
argument-hint: "Agent 名称（kebab-case）、职责描述、触发词、是否限制工具"
user-invokable: true
status: active
---

# GitHub Copilot CLI 自定义 Agent 写作标准

> 规范来源：
> - https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-custom-agents
> - https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-custom-agents-for-cli
> - https://docs.github.com/en/copilot/reference/custom-agents-configuration

---

## 文件规格

| 项目 | 规范 |
|------|------|
| **存放路径（项目级）** | `.github/agents/<name>.agent.md` |
| **存放路径（用户级）** | `~/.copilot/agents/<name>.agent.md` |
| **文件扩展名** | `.agent.md`（必须，不是 `.md`） |
| **文件名** | kebab-case，如 `security-auditor.agent.md` |
| **格式** | YAML Frontmatter + Markdown 正文（系统提示） |
| **正文最大长度** | 30,000 字符 |

---

## Frontmatter 字段完整规范

```yaml
---
name: <display-name>         # 可选：显示名称；省略时使用文件名作为标识符
description: <description>   # 必填：Agent 的职责、能力和触发条件（推理触发的关键）
tools: ["read", "search"]    # 可选：允许使用的工具（列表格式）；省略则继承全部工具
mcp-servers:                 # 可选：MCP 服务器配置（注意：用连字符，不是驼峰）
  server-name:
    type: local
    command: some-command
    args: []
---
```

**必填字段**：`description`（`name` 可选，省略时用文件名）。

---

## 工具别名（tools 字段）

Copilot CLI 使用**工具别名**（不同于 Claude Code 的工具名称）：

| 别名 | 等价名称 | 用途 |
|------|---------|------|
| `read` | `Read`, `NotebookRead` | 读取文件内容 |
| `edit` | `Edit`, `MultiEdit`, `Write`, `NotebookEdit` | 编辑/创建文件 |
| `search` | `Grep`, `Glob` | 搜索文件或内容 |
| `execute` | `shell`, `Bash`, `powershell` | 执行 shell 命令 |
| `agent` | `custom-agent`, `Task` | 调用其他自定义 Agent |
| `web` | `WebSearch`, `WebFetch` | 网络搜索/抓取 |
| `todo` | `TodoWrite` | 任务列表管理 |

```yaml
# 示例：只读 Agent（安全审计）
tools: ["read", "search"]

# 示例：全功能 Agent（省略 tools 或用通配符）
tools: ["*"]

# 示例：禁止所有工具
tools: []
```

---

## 最关键：description 字段写作规范

`description` 决定 Copilot **何时自动推理并使用**此 Agent，以及在 `/agent` 列表中的展示说明。

**必须包含**：

1. **职责描述**：Agent 能做什么
2. **触发场景**：什么情况下应使用此 Agent
3. **触发词（关键词）**：用户输入哪些词会触发此 Agent
4. **范围限制**（可选）：Agent 不做什么

```yaml
# 好的 description（含职责、触发场景、触发词、限制）
description: >-
  Security specialist that reviews code for vulnerabilities, exposed secrets,
  SQL injection, XSS, and authentication bypasses.
  Use when security review, security audit, or code security check is requested.
  Trigger words: seccheck, security audit, security review, vulnerability scan.
  Does NOT modify production code—analysis and reporting only.

# 差的 description（过于简单，无触发信息）
description: A security agent.
```

---

## 调用方式

Copilot 提供三种方式使用自定义 Agent：

| 方式 | 示例 |
|------|------|
| **Slash 命令** | `/agent` → 选择 Agent → 输入提示 |
| **显式指令** | `Use the security-auditor agent on all files in /src/` |
| **推理触发** | `Check TypeScript files for security issues`（匹配 description） |
| **命令行** | `copilot --agent security-auditor --prompt "..."` |

> ⚠️ 命令行 `--agent` 参数使用**文件名**（不含 `.agent.md`），而非 `name` 字段值。

---

## 正文（系统提示）写作规范

1. **聚焦范围**：只描述此 Agent 的专属行为，不重复 Copilot 全局指令
2. **明确输出**：指定期望的输出格式和结构
3. **约束优先**：在正文开头明确 Agent 不做什么（scope limiting）
4. **最大 30,000 字符**：超长时截断，精简语言

```markdown
<!-- 正文模板 -->
你是一个[具体角色]，专注于[精准范围]。

## 职责

- [职责1，动词开头，可量化]
- [职责2]

## 超出范围

- 不修改[类型]文件
- 不执行[操作]

## 输出格式

[清晰描述期望的输出结构，使用 Markdown]
```

---

## 完整示例

```markdown
---
name: requirement-validator
description: >-
  Validates REQUIREMENTS.md files to ensure all requirement entries have
  ID, description, priority, and acceptance criteria.
  Use when asked to validate, check, or audit requirements documents.
  Trigger words: 需求验证, validate requirements, check REQUIREMENTS.md, requirements audit.
  Read-only—does NOT modify any files.
tools: ["read", "search"]
---

你是一个需求文档验证专家，专注于检查 REQUIREMENTS.md 文件的结构完整性。

## 职责

- 读取并解析 REQUIREMENTS.md 中的需求条目表格
- 检查每条需求是否包含：ID、需求描述、优先级、验收条件、来源
- 识别空白字段、格式错误、重复 ID
- 输出验证报告

## 超出范围

- 不修改任何文件
- 不评价需求内容是否合理
- 不与其他文档交叉验证

## 输出格式

```markdown
## 需求验证报告

| 需求 ID | 问题 | 严重程度 |
|---------|------|---------|
| R001    | 缺少验收条件 | HIGH |

**总结**：共 N 条需求，M 条存在问题。
```
```

---

## 与 Claude Code Agent 的关键差异

| 对比项 | Copilot CLI | Claude Code |
|--------|------------|-------------|
| 文件扩展名 | `.agent.md` | `.md` |
| 存放目录 | `.github/agents/` | `.claude/agents/` |
| `name` 字段 | 可选（省略用文件名） | 必填 |
| 工具字段格式 | 别名列表 `["read", "search"]` | 工具名逗号分隔 `Read, Grep` |
| 模型选择 | 不支持 | `model: haiku/sonnet/opus` |
| 权限模式 | 不支持 | `permissionMode` |
| 正文长度限制 | 30,000 字符 | 无明确限制 |
| MCP 配置键 | `mcp-servers`（连字符） | `mcpServers`（驼峰） |

---

## 写作检查清单

完成 Agent 文件后，自检以下项目：

- [ ] 文件扩展名为 `.agent.md`（不是 `.md`）
- [ ] 文件路径为 `.github/agents/<kebab-name>.agent.md`
- [ ] `description` 包含：职责描述 + 触发场景 + 触发词 + 范围限制
- [ ] `tools` 使用 Copilot 别名（`read`/`edit`/`search`/`execute`），不用 Claude 工具名
- [ ] 正文系统提示清晰描述职责、约束和输出格式
- [ ] 正文不超过 30,000 字符
- [ ] 若有 MCP 配置，使用 `mcp-servers`（连字符格式，不是驼峰）
