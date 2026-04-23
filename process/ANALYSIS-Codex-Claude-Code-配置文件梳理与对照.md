# ANALYSIS：Codex 与 Claude Code 配置文件梳理与对照

> 迁移说明：本文已从 `docs/` 迁移到 `process/`，作为过程实施分析文档保留。

> 目标：基于 `.input/` 目录中的 Codex 与 Claude Code 指导文档，整理两者的配置文件、作用、层级范围与对应关系，重点覆盖 **模型**、**API Key**、**skill / command**、**AGENTS.md / CLAUDE.md**、**rules**、**hooks**、**agents**、**MCP** 等关键配置面。

> 参考来源：  
> Codex 相关：`Config basics – Codex.md`、`Configuration Reference – Codex.md`、`Advanced Configuration – Codex.md`、`Custom instructions with AGENTS.md – Codex.md`、`Agent Skills – Codex.md`、`Hooks – Codex  OpenAI Developers.md`、`Rules – Codex  OpenAI Developers.md`、`Memories – Codex  OpenAI Developers.md`  
> Claude Code 相关：`Claude Code settings.md`、`Model configuration.md`、`Best Practices for Claude Code.md`、`Extend Claude with skills.md`、`Create custom subagents.md`、`Automate workflows with hooks.md`、`Connect Claude Code to tools via MCP.md`、`Output styles.md`、`Troubleshooting.md`、`Configure permissions.md`

---

## 1. 总览结论

**核心差异：**

1. **Codex 是集中式配置模型**：以 `config.toml` 为主入口，模型、Provider、MCP、sandbox、agents、skills 开关等大多挂在同一个 TOML 配置体系下。
2. **Claude Code 是分层拆分模型**：将主设置、全局状态、MCP、持久指令、skills、agents、output styles、legacy commands 分散到多类 JSON / Markdown / 目录结构中。
3. **Codex 更强调 `AGENTS.md + config.toml`**；**Claude Code 更强调 `settings.json + CLAUDE.md + .claude/*` 生态**。
4. **Claude Code 有明确的 Local 层**（`.claude/settings.local.json` / `CLAUDE.local.md`）；Codex 文档中没有与之完全对等的“项目本地但不共享”的独立设置文件层。

**最容易混淆的一点：**

- **Codex 的 rules** 指 `.rules` 文件，是命令执行策略层。
- **Claude Code 的 rules** 常指 `.claude/rules/*.md`，更接近“规则说明/记忆片段/上下文注入”，真正的硬权限控制主要在 `settings.json` 的 `permissions` 字段里。

---

## 2. 配置层级对比

### 2.1 Codex 配置层级

Codex 配置优先级从高到低为：

1. CLI flags / `--config`
2. `--profile <name>` 指定的 profile
3. 项目级 `.codex/config.toml`（从 repo root 到 cwd，多层叠加，近者优先）
4. 用户级 `~/.codex/config.toml`
5. 系统级 `/etc/codex/config.toml`
6. 内置默认值

补充：

- 项目级 `.codex/config.toml` 仅在 **trusted project** 下加载。
- `AGENTS.md` 则是另一条独立的指令发现链：全局 `~/.codex/AGENTS.md` / `AGENTS.override.md` + 项目路径上逐层 `AGENTS.md` / `AGENTS.override.md`。

### 2.2 Claude Code 配置层级

Claude Code 配置优先级从高到低为：

1. Managed（server-managed / MDM / registry / file-based `managed-settings.json`）
2. CLI 参数
3. Local：`.claude/settings.local.json`
4. Project：`.claude/settings.json`
5. User：`~/.claude/settings.json`

相关但独立的配置面：

- `~/.claude.json`：全局状态、OAuth、MCP（user/local scope）、主题、editor mode、缓存等
- `.mcp.json`：项目级 MCP
- `managed-mcp.json`：托管 MCP
- `CLAUDE.md` / `CLAUDE.local.md` / `.claude/rules/*.md`：提示与记忆层

---

## 3. Codex 配置文件清单

### 3.1 主配置与强约束

| 层级 | 文件 / 路径 | 作用 | 关键内容 |
|---|---|---|---|
| 用户级 | `~/.codex/config.toml` | Codex 主配置文件 | 默认模型、provider、sandbox、approval、MCP、agents、skills 开关、日志、shell 环境等 |
| 项目级 | `.codex/config.toml` | 项目覆盖配置 | 与用户级同 schema，按目录层级叠加 |
| 系统级 | `/etc/codex/config.toml` | 系统范围默认配置 | 给机器或组织统一设置默认值 |
| 管理级 | `requirements.toml` | 管理员强约束 | 限制 `approval_policy`、`sandbox_mode`、`web_search`、`features`、`mcp_servers`、`rules` |

**说明：**

- `config.toml` 是 Codex 的绝对主入口。
- `requirements.toml` 不是普通用户配置，而是管理员强制边界。

### 3.2 持久指令与项目规范

| 层级 | 文件 / 路径 | 作用 | 说明 |
|---|---|---|---|
| 用户级 | `~/.codex/AGENTS.md` | 全局持久指令 | 对所有项目生效 |
| 用户级 | `~/.codex/AGENTS.override.md` | 全局临时覆盖指令 | 优先于 `~/.codex/AGENTS.md` |
| 项目级 | `<repo>/AGENTS.md` | 项目根指令 | 团队共享 |
| 项目级 | `<repo>/AGENTS.override.md` | 项目临时覆盖指令 | 同目录内优先于 `AGENTS.md` |
| 项目路径链 | 子目录中的 `AGENTS.md` / `AGENTS.override.md` | 更细粒度局部规范 | Codex 会沿 project root → cwd 逐层发现并拼接 |

补充：

- `project_doc_fallback_filenames` 可把其他文件名也纳入指令发现链。
- `model_instructions_file` 可以作为对内置 instructions 的文件级替代，但它不是项目规范文档的主推荐路径。

### 3.3 Hooks

| 层级 | 文件 / 路径 | 作用 | 说明 |
|---|---|---|---|
| 用户级 | `~/.codex/hooks.json` | 生命周期 hooks | 需要在 `config.toml` 中开启 `[features].codex_hooks = true` |
| 项目级 | `<repo>/.codex/hooks.json` | 项目 hooks | 与用户级 hooks 同时生效，不是高优覆盖而是共同运行 |

### 3.4 Rules

| 层级 | 文件 / 路径 | 作用 | 说明 |
|---|---|---|---|
| 用户级 | `~/.codex/rules/default.rules` | 用户命令执行规则 | TUI 中添加 allow list 规则时会写入这里 |
| Team Config 层 | `rules/*.rules` | 团队或组织规则 | 启动时扫描 team config 中的 `delivery/rules/` 目录 |
| 管理级 | `requirements.toml` 中的 `rules` | 强制限制规则 | 只能是 `prompt` / `forbidden` 等更保守约束 |

**注意：**

- Codex 的 `.rules` 是 **可执行策略**，不是普通说明文档。

### 3.5 Skills / Agents / 运行时状态

| 类别 | 路径 | 作用 | 说明 |
|---|---|---|---|
| Skills（repo） | `.agents/skills/<skill-name>/SKILL.md` | 仓库内技能 | 显式调用偏 `$skill-name` |
| Skills（user） | `~/.agents/skills/<skill-name>/SKILL.md` | 用户级技能 | 跨项目复用 |
| Skills（admin） | `/etc/codex/skills/...` | 管理级技能 | 机器或容器共享 |
| Skills 配置 | `config.toml` 中 `[[skills.config]]` | 对 skill 启停做覆盖 | 可按 path 禁用某个 skill |
| Agents 配置 | `config.toml` 中 `[agents]` / `agents.<name>.*` | 子 agent 角色与限制 | 线程数、深度、角色描述、配置文件路径 |
| 认证缓存 | `~/.codex/auth.json` 或 keyring/keychain | 登录态缓存 | 受 `cli_auth_credentials_store` 控制 |
| 历史 | `~/.codex/history.jsonl` | 历史记录 | 是否持久化由 `history.persistence` 控制 |
| Memories | `~/.codex/memories/` | 本地记忆状态 | 属于运行时状态，不是团队共享配置 |

### 3.6 模型 / API Key / skill command / agents / rules 对应关系

| 关注项 | Codex 对应位置 |
|---|---|
| 模型 | `config.toml` 的 `model`、`model_provider`、`profiles.*` |
| API Key | `model_providers.<id>.env_key` 指向环境变量，如 `OPENAI_API_KEY`、`AZURE_OPENAI_API_KEY`；登录态可落 `auth.json` / keyring |
| skill command | Skills 位于 `.agents/skills/**/SKILL.md`，显式调用偏 `$skill-name` |
| AGENTS.md | `~/.codex/AGENTS.md`、`AGENTS.override.md`、项目路径上的 `AGENTS.md` / `AGENTS.override.md` |
| agents | `config.toml` 的 `[agents]`、`agents.<name>.*` |
| rules | `~/.codex/rules/*.rules`、team config `delivery/rules/`、`requirements.toml` 中的 `rules` |
| hooks | `~/.codex/hooks.json`、`<repo>/.codex/hooks.json` |
| MCP | `config.toml` 的 `[mcp_servers.<id>]` |

---

## 4. Claude Code 配置文件清单

### 4.1 主配置与全局状态

| 层级 | 文件 / 路径 | 作用 | 关键内容 |
|---|---|---|---|
| 用户级 | `~/.claude/settings.json` | 用户设置 | model、permissions、hooks、env、plugins、outputStyle 等 |
| 项目级 | `.claude/settings.json` | 项目共享设置 | 团队共享配置，通常入库 |
| 本地级 | `.claude/settings.local.json` | 项目本地个人设置 | gitignored，本机私有覆盖 |
| 管理级 | `managed-settings.json` / `managed-settings.d/*.json` | 组织托管设置 | 最高优先级，不可被用户或项目覆盖 |
| 用户状态 | `~/.claude.json` | 全局状态中心 | 主题、通知、editor mode、OAuth session、MCP（user/local scope）、per-project state、缓存 |

**重点：**

- `settings.json` 是主设置文件。
- `~/.claude.json` 是状态与部分配置混合的“全局状态仓库”，不是 `settings.json` 的简单副本。

### 4.2 持久指令 / 记忆 / 规则文档

| 层级 | 文件 / 路径 | 作用 | 说明 |
|---|---|---|---|
| 用户级 | `~/.claude/CLAUDE.md` | 全局持久指令 | 适用于所有项目 |
| 项目级 | `CLAUDE.md` | 项目共享指令 | 推荐入库 |
| 项目级 | `.claude/CLAUDE.md` | 项目共享指令的另一位置 | 文档明确允许 |
| 本地级 | `CLAUDE.local.md` | 项目本地个人注释 | 不共享，建议加入 `.gitignore` |
| 用户级 | `~/.claude/rules/*.md` | 用户级规则片段 / 记忆碎片 | 供上下文加载 |
| 项目级 | `.claude/rules/*.md` | 项目级规则片段 / 记忆碎片 | 拆分主题规则，避免单文件过长 |

**说明：**

- `CLAUDE.md` 更像 Claude Code 的“主记忆/主规范”。
- `.claude/rules/*.md` 不是权限策略文件，而是会被加载进上下文的规则文档层。

### 4.3 Skills / Commands / Agents / Output Styles

| 类别 | 路径 | 作用 | 说明 |
|---|---|---|---|
| Skills（user） | `~/.claude/skills/<skill-name>/SKILL.md` | 用户级技能 | 跨项目复用 |
| Skills（project） | `.claude/skills/<skill-name>/SKILL.md` | 项目级技能 | 团队共享 |
| Skills（plugin） | `<plugin>/skills/<skill-name>/SKILL.md` | 插件带入技能 | plugin 命名空间隔离 |
| Legacy commands | `.claude/commands/*.md` | 旧式自定义命令 | 现在已并入 skills，但继续兼容 |
| Agents（user） | `~/.claude/agents/*.md` | 用户级 subagents | Markdown + YAML frontmatter |
| Agents（project） | `.claude/agents/*.md` | 项目级 subagents | 团队共享 |
| Output styles（user） | `~/.claude/output-styles/*.md` | 用户级输出风格 | 仅改变回复风格，不改变知识 |
| Output styles（project） | `.claude/output-styles/*.md` | 项目级输出风格 | 团队共享风格模板 |

**skills 与 commands 的关系：**

- `.claude/commands/deploy.md` 与 `.claude/skills/deploy/SKILL.md` 都可以生成 `/deploy`
- 现在官方推荐 **skills**
- 如果 skill 与 command 同名，**skill 优先**

### 4.4 Hooks

| 层级 | 配置位置 | 作用 | 说明 |
|---|---|---|---|
| 用户 / 项目 / 本地 / 管理 | `settings.json` 中 `hooks` 字段 | 生命周期 hooks | hooks 直接写在 settings JSON 中，不是独立文件 |
| skill 级 | `SKILL.md` frontmatter 中 `hooks` | skill 生命周期 hooks | scoped 到 skill |
| agent 级 | `agents/*.md` frontmatter 中 `hooks` | agent 生命周期 hooks | scoped 到 agent |

### 4.5 MCP

| 层级 | 文件 / 路径 | 作用 | 说明 |
|---|---|---|---|
| Local scope | `~/.claude.json`（按项目路径挂载） | 当前项目私有 MCP | 只对自己、只在当前项目生效 |
| Project scope | `.mcp.json` | 项目共享 MCP | 推荐入库 |
| User scope | `~/.claude.json` | 全局 MCP | 跨项目可用 |
| Managed scope | `managed-mcp.json` | 托管 MCP | 管理员独占控制 |

### 4.6 模型 / API Key / skill command / CLAUDE.md / agents / rules 对应关系

| 关注项 | Claude Code 对应位置 |
|---|---|
| 模型 | `settings.json` 的 `model`、`availableModels`、`modelOverrides`；环境变量 `ANTHROPIC_MODEL`、`CLAUDE_CODE_SUBAGENT_MODEL`、`ANTHROPIC_DEFAULT_*_MODEL` |
| API Key | `ANTHROPIC_API_KEY` 环境变量；或 `settings.json` 的 `apiKeyHelper`；OAuth 会话状态保存在 `~/.claude.json` |
| skill command | Skills 位于 `.claude/skills/**/SKILL.md`，显式调用是 `/skill-name`；旧式 commands 位于 `.claude/commands/*.md` |
| CLAUDE.md | `~/.claude/CLAUDE.md`、`CLAUDE.md`、`.claude/CLAUDE.md`、`CLAUDE.local.md` |
| agents | `~/.claude/agents/*.md`、`.claude/agents/*.md` |
| rules | 硬规则在 `settings.json` 的 `permissions.allow/ask/deny`；软规则在 `~/.claude/rules/*.md`、`.claude/rules/*.md` |
| hooks | `settings.json` 中的 `hooks`，以及 skill/agent frontmatter 的 `hooks` |
| MCP | `~/.claude.json`、`.mcp.json`、`managed-mcp.json` |
| output styles | `outputStyle` + `~/.claude/output-styles/*.md` / `.claude/output-styles/*.md` |

---

## 5. Codex 与 Claude Code 对照表

| 能力面 | Codex | Claude Code | 相同点 | 关键差异 |
|---|---|---|---|---|
| 主配置文件 | `config.toml` | `settings.json` | 都有用户级、项目级、管理级配置 | Codex 更集中；Claude 更拆分 |
| 全局状态文件 | `auth.json` / `history.jsonl` / `memories/` 等分散状态 | `~/.claude.json` | 都保存用户侧运行时状态 | Claude 有明确的统一全局状态文件 |
| 持久指令主文件 | `AGENTS.md` | `CLAUDE.md` | 都是长期提示 / 规范层 | Codex 强调 AGENTS 链；Claude 强调 CLAUDE.md + rules |
| 项目局部覆盖 | 子目录 `AGENTS.md` / `AGENTS.override.md` | `CLAUDE.local.md`、`.claude/settings.local.json`、按需加载子目录 `CLAUDE.md` | 都支持局部化 | Claude 明确区分 Local 与 Project；Codex 更偏目录覆盖 |
| Skills | `.agents/skills/**/SKILL.md` | `.claude/skills/**/SKILL.md` | 都用 `SKILL.md` 目录结构 | Codex 显式调用偏 `$skill-name`；Claude 是 `/skill-name` |
| Commands | 无独立 commands 体系 | `.claude/commands/*.md`（legacy） | 都能承载复用流程 | Codex 没有对等的 `.commands/` 层 |
| Agents / Subagents | `config.toml` 的 `[agents]` | `.claude/agents/*.md` | 都支持子代理 | Codex 偏 TOML；Claude 偏 Markdown 文件 |
| Hooks | `hooks.json` | `settings.json` 的 `hooks` | 都有生命周期自动化 | Codex 用独立文件；Claude 内嵌在 settings |
| Rules / 执行策略 | `.rules` + `requirements.toml` | `permissions` + `.claude/rules/*.md` | 都能约束行为 | Codex `.rules` 是硬执行策略；Claude `.claude/rules/*.md` 是上下文层 |
| MCP | `[mcp_servers]` in `config.toml` | `.mcp.json` / `~/.claude.json` / `managed-mcp.json` | 都支持 user/project/managed 范围 | Codex 把 MCP 并入主配置；Claude 把 MCP 单列成文件体系 |
| 模型配置 | `model` / `model_provider` / `profiles.*` | `model` / `availableModels` / `modelOverrides` + env vars | 都支持默认模型和覆盖 | Claude 对 skill / subagent 还有前置 frontmatter override |
| API Key | provider `env_key` + `auth.json` / keyring | `ANTHROPIC_API_KEY` / `apiKeyHelper` / OAuth in `~/.claude.json` | 都支持环境变量与本地凭据 | Claude 明确区分 API Key 与订阅 OAuth；Codex 更强调 provider 抽象 |
| 输出风格 | `personality`、`model_instructions_file` 等近似能力 | `outputStyle` + `output-styles/*.md` | 都能影响回答风格 | Claude 有专门 output style 文件层 |

---

## 6. 对“模型 / API KEY / skill command / CLAUDE.md / AGENTS.md / rules”的专项对照

| 主题 | Codex | Claude Code |
|---|---|---|
| 模型默认值 | `config.toml` 的 `model` | `settings.json` 的 `model` |
| 模型临时切换 | CLI `--model` / `-m`，会话内 `/model` | CLI `--model`，会话内 `/model` |
| 模型别名 / Provider | `model_provider`、`model_providers.*` | `availableModels`、`modelOverrides`、`ANTHROPIC_DEFAULT_*_MODEL` |
| API Key | provider 的 `env_key` 指向 `OPENAI_API_KEY` / `AZURE_OPENAI_API_KEY` 等 | `ANTHROPIC_API_KEY` 或 `apiKeyHelper` |
| 登录态缓存 | `auth.json` 或 keyring | OAuth / 全局状态在 `~/.claude.json` |
| 主指令文档 | `AGENTS.md` | `CLAUDE.md` |
| 临时/局部指令 | `AGENTS.override.md`、子目录 `AGENTS.md` | `CLAUDE.local.md`、子目录 `CLAUDE.md`、`.claude/rules/*.md` |
| Skills | `.agents/skills/**/SKILL.md`，调用偏 `$skill-name` | `.claude/skills/**/SKILL.md`，调用是 `/skill-name` |
| Commands | 无单独层 | `.claude/commands/*.md`，现已并入 skills |
| Agents | `[agents]` in `config.toml` | `.claude/agents/*.md` |
| Rules | `.rules` 文件，是真命令策略 | `permissions` 是硬规则；`.claude/rules/*.md` 是软规则/记忆文档 |

---

## 7. 实务建议

### 7.1 如果目标是做 Codex 配置梳理

优先关注这几类文件：

1. `~/.codex/config.toml`
2. `.codex/config.toml`
3. `AGENTS.md` / `AGENTS.override.md`
4. `~/.codex/hooks.json` / `<repo>/.codex/hooks.json`
5. `~/.codex/rules/*.rules`
6. `.agents/skills/**/SKILL.md`
7. `requirements.toml`

### 7.2 如果目标是做 Claude Code 配置梳理

优先关注这几类文件：

1. `~/.claude/settings.json`
2. `.claude/settings.json`
3. `.claude/settings.local.json`
4. `~/.claude.json`
5. `CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md`
6. `.claude/rules/*.md`
7. `.claude/skills/**/SKILL.md`
8. `.claude/agents/*.md`
9. `.mcp.json` / `managed-mcp.json`
10. `.claude/output-styles/*.md`
11. `.claude/commands/*.md`（如项目仍在使用 legacy commands）

---

## 8. 最终结论

- **Codex** 更适合被理解为：  
  **`config.toml` + `AGENTS.md` + `hooks.json` + `.rules` + `.agents/skills/`** 的集中式配置系统。

- **Claude Code** 更适合被理解为：  
  **`settings.json` + `~/.claude.json` + `CLAUDE.md` + `.claude/{skills,agents,commands,output-styles,rules}` + `.mcp.json`** 的分层组合式配置系统。

- 若只想快速抓住两者的核心配置面：
  - **Codex**：先看 `config.toml` 与 `AGENTS.md`
  - **Claude Code**：先看 `settings.json`、`~/.claude.json` 与 `CLAUDE.md`
