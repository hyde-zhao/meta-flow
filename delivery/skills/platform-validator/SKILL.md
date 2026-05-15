---
name: platform-validator
description: >-
  当需要校验安装目标目录或安装脚本 DryRun 输出是否符合平台规范时使用。
  触发词包括：校验安装、平台验证、结构校验、安装结构检查、目录规范校验。
  适用场景：安装脚本生成后执行；或独立校验现有项目 / 用户级安装目录。
argument-hint: "可选：指定目标平台（claude-code/codex/openclaw）、scope（project/user）或目标路径"
user-invokable: true
status: active
---

## 目标

校验安装脚本计划写入的目标目录是否符合 `delivery/doc/PLATFORM-CONTRACTS.yaml` 与 `PLATFORM-INSTALL-SPEC.md` 规范，包括目录结构、主入口文件、命名规范、路径组件冲突、Codex 禁止路径和 OpenClaw manifest 完整性。

## 适用范围

- 适用阶段：`verification` 后、`documentation` 前
- 触发时机：`package-builder` 生成安装脚本后，或用户手动请求校验

## 校验维度

### 维度 1：目录结构（BLOCKING）

按 `delivery/doc/PLATFORM-CONTRACTS.yaml` 中各平台的规范目录树逐一比对；`PLATFORM-INSTALL-SPEC.md` 仅作为可读说明。

| 平台 | 项目级必须存在的路径 | 用户级必须存在的路径 |
|------|----------------------|----------------------|
| claude-code | `.claude/CLAUDE.md`，`.claude/agents/`，`.claude/skills/` | `~/.claude/CLAUDE.md`，`~/.claude/agents/`，`~/.claude/skills/` |
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
meta-flow install --platform codex --scope project --project-dir <target> --component agent --agent meta-po --skill context-handoff
```

预期：非零退出，错误包含 `安装路径被非目录占用: <target>/.codex`。

### 维度 8：OpenClaw manifest 完整性（仅 openclaw，REQUIRED）

`manifest.yaml` 必须覆盖目标目录中的所有 Agent 和 Skill 文件。

## 执行步骤

1. 确定目标平台、scope 与目标路径
2. 读取 `delivery/doc/PLATFORM-CONTRACTS.yaml` 获取路径规则；读取 `PLATFORM-INSTALL-SPEC.md` 作为说明性对照
3. 校验安装脚本默认参数与 DryRun 输出
4. 校验目标目录结构与关键入口文件
5. 构造路径组件被文件占用的负向用例，确认安装器 fail fast 且无 traceback
6. 若目标平台是 Codex，校验 subagent TOML schema
7. 输出校验报告（含未通过项与修复建议）

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
| Codex forbidden path | BLOCKING | ✅ 通过 | DryRun 和目标目录均未出现 `.codex/skills` |
| 路径组件冲突 | BLOCKING | ✅ 通过 | `.codex` 为普通文件时明确报错且无 traceback |
| 命名规范 | REQUIRED | ❌ 未通过 | `MySkill.md` 不符合 kebab-case |

### 综合结论

- BLOCKING 未通过：0 项
- REQUIRED 未通过：1 项
- 总体结论：需修复后重新验证
```

## 执行约束

- 只做校验，不修改任何文件
- 发现 BLOCKING 问题时，阻断交付推进
- 发现 REQUIRED 问题时，记录并通知 meta-po，由 meta-po 决定是否阻断

## 验收标准

- [ ] 所有 BLOCKING 维度校验结果有明确通过/未通过记录
- [ ] 未通过项有具体路径和修复建议
- [ ] 已检查安装脚本 DryRun 行为
- [ ] Codex 目标已检查 subagent TOML schema（若平台为 codex）
- [ ] Codex 目标已检查 `.codex/skills` / `~/.codex/skills` 负向断言（若平台为 codex）
- [ ] 已检查目标路径组件被文件占用时的 fail-fast 行为和错误提示
