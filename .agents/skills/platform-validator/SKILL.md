---
name: platform-validator
description: >-
  当需要校验安装目标目录或安装脚本 DryRun 输出是否符合平台规范时使用。
  触发词包括：校验安装、平台验证、结构校验、安装结构检查、目录规范校验。
  适用场景：安装脚本生成后执行；或独立校验现有项目 / 用户级安装目录。
argument-hint: "可选：指定目标平台（claude/codex/openclaw）、scope（project/user）或目标路径"
user-invokable: true
status: active
---

## 目标

校验安装脚本计划写入的目标目录是否符合 `delivery/doc/PLATFORM-CONTRACTS.yaml` 与 `PLATFORM-INSTALL-SPEC.md` 规范，包括目录结构、主入口文件、命名规范、路径组件冲突、Codex 禁止路径、OpenClaw manifest 完整性和 production 交付路由。

## 适用范围

- 适用阶段：`verification` 后、`documentation` 前
- 触发时机：`package-builder` 生成安装脚本后，或用户手动请求校验

## 校验维度

### 维度 1：目录结构（BLOCKING）

按 `delivery/doc/PLATFORM-CONTRACTS.yaml` 中各平台的规范目录树逐一比对；`PLATFORM-INSTALL-SPEC.md` 仅作为可读说明。

| 平台 | 项目级必须存在的路径 | 用户级必须存在的路径 |
|------|----------------------|----------------------|
| claude | `CLAUDE.md`，`.claude/agents/`，`.claude/skills/` | `~/.claude/CLAUDE.md`，`~/.claude/agents/`，`~/.claude/skills/` |
| codex | `AGENTS.md`，`.codex/agents/`，`.agents/skills/` | `~/.codex/AGENTS.md`，`~/.codex/agents/`，`~/.agents/skills/` |
| openclaw | `.openclaw/manifest.yaml`，`.openclaw/agents/`，`.openclaw/skills/` | `~/.openclaw/manifest.yaml`，`~/.openclaw/agents/`，`~/.openclaw/skills/` |

### 维度 2：主入口文件（BLOCKING）

需要入口文件的平台必须存在非空文件：

- Claude Code：`CLAUDE.md`
- Codex：`AGENTS.md`
- OpenClaw：`manifest.yaml`

### 维度 3：命名规范（REQUIRED）

所有 Agent / Skill / 脚本文件名必须符合约定：

- Agent / Skill：kebab-case
- Codex Agent：允许 `.toml`
- 安装脚本：`install.py`、`install.ps1`、`install.sh`

### 维度 4：DryRun 一致性（REQUIRED）

安装脚本的 `--dry-run` 输出必须与 `delivery/doc/PLATFORM-CONTRACTS.yaml` 目标目录规则一致，且默认目标为当前项目目录。Codex Skill dry-run 必须输出 `.agents/skills/<skill>/SKILL.md` 或 `~/.agents/skills/<skill>/SKILL.md`。若 dry-run 执行路径风险检查，发现父路径组件被文件占用时也应明确报错。

### 维度 5：Codex subagent schema（仅 codex，BLOCKING）

若目标平台是 Codex，必须额外校验：

- `.codex/agents/*.toml` 为合法 TOML
- 必填 `name`、`description`、`developer_instructions`
- 只允许官方 schema 字段：`name`、`description`、`developer_instructions`、`nickname_candidates`、`model`、`model_reasoning_effort`、`sandbox_mode`、`mcp_servers`、`skills.config`
- 不得出现 `version`、`instructions` 或其他非标准顶层字段
- `nickname_candidates` 必须符合功能子 agent 命令别名映射：`pm-wu/pm-zheng/pm-wang/pm-feng/pm-chen`、`se-chu/se-wei/se-jiang/se-shen/se-han`、`dev-yang/dev-zhu/dev-qin/dev-you/dev-xu/dev-he/dev-lv/dev-shi/dev-zhang/dev-kong`、`qa-he/qa-lv/qa-shi/qa-zhang/qa-kong/qa-cao/qa-yan/qa-hua/qa-jin/qa-wei`、`doc-cao/doc-yan/doc-hua/doc-jin/doc-wei`

### 维度 5.1：Claude Code subagent color（仅 claude，REQUIRED）

若目标平台是 Claude Code，必须额外校验：

- `.claude/agents/*.md` frontmatter 可解析
- canonical `name` 保持 `meta-*`
- 不写 Codex 风格的 `nickname_candidates`
- `color` 使用允许值：`red`、`blue`、`green`、`yellow`、`purple`、`orange`、`pink`、`cyan`
- 颜色映射符合：`meta-pm=orange`、`meta-se=yellow`、`meta-dev=green`、`meta-qa=cyan`、`meta-doc=purple`

### 维度 5.2：Claude Code AskUserQuestion 权限（仅 claude，BLOCKING）

若目标平台是 Claude Code，必须额外校验用户提问工具权限：

- 允许 direct ask 的功能 subagent 必须在 frontmatter `tools:` 中显式包含 `AskUserQuestion`：`meta-pm`、`meta-se`
- 默认不直接问用户的 agent 不得声明 `AskUserQuestion`：`meta-dev`、`meta-qa`、`meta-doc`
- `AskUserQuestion` 只代表 Claude Code 结构化提问工具权限；Codex 不使用该工具名
- 若 `tools:` 缺失或不含 `AskUserQuestion`，不得仅凭正文中的“可直接向用户提问”放行

### 维度 6：Codex forbidden path（仅 codex，BLOCKING）

若目标平台是 Codex，必须额外校验：

- 项目级 Skill 不得写入 `.codex/skills`
- 用户级 Skill 不得写入 `~/.codex/skills`
- dry-run 与真实安装必须共用同一契约矩阵，不允许 dry-run 单独修正路径

### 维度 7：路径组件冲突（BLOCKING）

安装器必须覆盖脏目录 / 冲突路径安全失败场景：

- 写入任何文件前逐级检查父路径组件
- 目标路径组件不存在则创建，存在且为目录则继续，存在但不是目录则终止
- 冲突错误必须包含 `安装路径被非目录占用: <path>` 和修复提示
- 不得出现 Python traceback、`NotADirectoryError` 或半写入状态

Codex project 安装必须至少构造以下负向用例：

```bash
touch <target>/.codex
meta-flow install codex --scope project --project-dir <target> --component agent --agent meta-pm --skill context-handoff
```

预期：非零退出，错误包含 `安装路径被非目录占用: <target>/.codex`。

### 维度 8：OpenClaw manifest 完整性（仅 openclaw，REQUIRED）

`manifest.yaml` 必须覆盖目标目录中的所有 Agent 和 Skill 文件。

### 维度 9：Production delivery route（BLOCKING）

当 `STATE.md.delivery_routing.engagement_mode=production` 时，必须校验：

- `target_project_root` 非空，并且不是当前 meta-flow 仓库根，除非用户明确要求优化 meta-flow 自身。
- 已扫描目标项目已有交付目录、`README.md` / `README.*` / `docs/`，并记录在 `route_validation.scanned_sources[]`。
- 若目标项目没有交付约定，`requires_user_confirmation=true`，且 `user_confirmed_output_route=true` 前不得写交付物。
- 未经确认不得写入当前仓库 `delivery/agents`、`delivery/skills`、`delivery/rules` 或 `.agents`。
- 禁止目录必须与 `STATE.md.delivery_routing.route_validation.forbidden_roots_when_production[]` 一致。
- `route_validation.status` 必须为 `pass`，或在检查报告中列出 `requires-user-confirmation` / `blocked` 原因。
- 对 production 项目，不得硬引用 meta-flow 本仓库的 `scripts/check_delivery_guardrails.py`；应使用目标 README/docs 的测试、构建、安装 dry-run 或用户确认的验证命令。

## 执行步骤

1. 确定目标平台、scope 与目标路径
2. 读取 `delivery/doc/PLATFORM-CONTRACTS.yaml` 获取路径规则；读取 `PLATFORM-INSTALL-SPEC.md` 作为说明性对照
3. 校验安装脚本默认参数与 DryRun 输出
4. 校验目标目录结构与关键入口文件
5. 构造路径组件被文件占用的负向用例，确认安装器 fail fast 且无 traceback
6. 若目标平台是 Codex，校验 subagent TOML schema 和 `nickname_candidates`
7. 若目标平台是 Claude Code，校验 subagent `color` 和 `AskUserQuestion` 工具权限
8. 校验 `STATE.md.delivery_routing.route_validation` 和 production 禁止写入路径
9. 输出校验报告（含未通过项与修复建议）

## 输出格式

```markdown
## platform-validator 校验报告

### 目标平台：<platform>
### scope：project | user
### 目标路径：<path>

| 维度 | 阻断等级 | 状态 | 说明 |
|------|---------|------|------|
| 目录结构 | BLOCKING | ✅ 通过 | |
| 主入口文件 | BLOCKING | ✅ 通过 | |
| DryRun 一致性 | REQUIRED | ✅ 通过 | 默认安装到当前项目 |
| Codex schema | BLOCKING | ✅ 通过 | 所有 `.codex/agents/*.toml` 均含 `developer_instructions`，且不存在 `version` |
| Agent 展示区分 | REQUIRED | ✅ 通过 | Codex nickname / Claude Code color 符合映射 |
| Claude AskUserQuestion 权限 | BLOCKING | ✅ 通过 | direct ask agent 已声明 `AskUserQuestion`，非 direct ask agent 未声明 |
| Codex forbidden path | BLOCKING | ✅ 通过 | DryRun 和目标目录均未出现 `.codex/skills` |
| 路径组件冲突 | BLOCKING | ✅ 通过 | `.codex` 为普通文件时明确报错且无 traceback |
| Production delivery route | BLOCKING | ✅ 通过 | production 输出路由已确认，未误写 meta-flow 自身交付目录 |
| 命名规范 | REQUIRED | ❌ 未通过 | `MySkill.md` 不符合 kebab-case |

### 综合结论

- BLOCKING 未通过：0 项
- REQUIRED 未通过：1 项
- 总体结论：需修复后重新验证
```

## 执行约束

- 只做校验，不修改任何文件
- 发现 BLOCKING 问题时，阻断交付推进
- 发现 REQUIRED 问题时，记录并通知 host-orchestrator，由 host-orchestrator 决定是否阻断

## 验收标准

- [ ] 所有 BLOCKING 维度校验结果有明确通过/未通过记录
- [ ] 未通过项有具体路径和修复建议
- [ ] 已检查安装脚本 DryRun 行为
- [ ] Codex 目标已检查 subagent TOML schema（若平台为 codex）
- [ ] Codex 目标已检查 `nickname_candidates` 命令别名（若平台为 codex）
- [ ] Claude Code 目标已检查 subagent `color`（若平台为 claude）
- [ ] Claude Code 目标已检查 direct ask agent 的 `AskUserQuestion` 工具权限（若平台为 claude）
- [ ] Codex 目标已检查 `.codex/skills` / `~/.codex/skills` 负向断言（若平台为 codex）
- [ ] 已检查目标路径组件被文件占用时的 fail-fast 行为和错误提示
- [ ] production 模式已检查交付路由、用户确认状态和禁止写入当前仓库 `delivery/` / `.agents` 的边界

## Gotchas

- Codex Skill 的安装路径是 `.agents/skills` 或 `~/.agents/skills`，不是 `.codex/skills` 或 `~/.codex/skills`；dry-run 和真实安装都必须按同一契约检查。
- dry-run 只证明安装计划，不证明文件已经写入目标目录；需要验证实际安装时必须执行非 dry-run 并检查目标文件内容。
- `--scope user` 默认只安装 `rules`，`--scope project` 默认安装 `full`；验证默认行为时不要手动补 `--component` 后再声称覆盖默认值。
- Claude Code 使用 `color` 展示角色，Codex 使用 `nickname_candidates` 命令别名；两者不能互相类比或混写。
- Claude Code 的 `AskUserQuestion` 必须写入需要 direct ask 的 subagent frontmatter `tools:`；只在正文里写“可直接问用户”不够。
- 路径组件冲突检查要覆盖父路径被普通文件占用的情况，不能只检查最终目标文件是否存在。
- production 项目路由失败不是安装器问题；它表示 host-orchestrator 尚未获得目标项目输出目录确认，不应通过安装 dry-run 掩盖。
