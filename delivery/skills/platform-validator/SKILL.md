---
name: platform-validator
description: >-
  当需要校验安装目标目录或安装脚本 DryRun 输出是否符合平台规范时使用。
  触发词包括：校验安装、平台验证、结构校验、安装结构检查、目录规范校验。
  适用场景：安装脚本生成后执行；或独立校验现有项目 / 用户级安装目录。
argument-hint: "可选：指定目标平台（copilot/claude-code/codex/openclaw）、scope（project/user）或目标路径"
user-invokable: true
status: active
---

## 目标

校验安装脚本计划写入的目标目录是否符合 `PLATFORM-INSTALL-SPEC.md` 规范，包括目录结构、主入口文件、命名规范和 OpenClaw manifest 完整性。

## 适用范围

- 适用阶段：`verification` 后、`documentation` 前
- 触发时机：`package-builder` 生成安装脚本后，或用户手动请求校验

## 校验维度

### 维度 1：目录结构（BLOCKING）

按 `PLATFORM-INSTALL-SPEC.md` 中各平台的规范目录树逐一比对。

| 平台 | 项目级必须存在的路径 | 用户级必须存在的路径 |
|------|----------------------|----------------------|
| copilot | `.github/copilot-instructions.md`，`.github/agents/` 或 `.github/copilot/skills/` | `~/.copilot/agents/` 或 `~/.copilot/skills/` |
| claude-code | `.claude/CLAUDE.md`，`.claude/agents/`，`.claude/skills/` | `~/.claude/CLAUDE.md`，`~/.claude/agents/`，`~/.claude/skills/` |
| codex | `AGENTS.md`，`.codex/agents/`，`.agents/skills/` | `~/.codex/AGENTS.md`，`~/.codex/agents/`，`~/.agents/skills/` |
| openclaw | `.openclaw/manifest.yaml`，`.openclaw/agents/`，`.openclaw/skills/` | `~/.openclaw/manifest.yaml`，`~/.openclaw/agents/`，`~/.openclaw/skills/` |

### 维度 2：主入口文件（BLOCKING）

需要入口文件的平台必须存在非空文件：

- Copilot：`copilot-instructions.md`
- Claude Code：`CLAUDE.md`
- Codex：`AGENTS.md`
- OpenClaw：`manifest.yaml`

### 维度 3：命名规范（REQUIRED）

所有 Agent / Skill / 脚本文件名必须符合约定：

- Agent / Skill：kebab-case
- Copilot Agent：允许 `.agent.md`
- Codex Agent：允许 `.toml`
- 安装脚本：`install.py`、`install.ps1`、`install.sh`

### 维度 4：DryRun 一致性（REQUIRED）

安装脚本的 `--dry-run` 输出必须与目标目录规则一致，且默认目标为当前项目目录。

### 维度 5：OpenClaw manifest 完整性（仅 openclaw，REQUIRED）

`manifest.yaml` 必须覆盖目标目录中的所有 Agent 和 Skill 文件。

## 执行步骤

1. 确定目标平台、scope 与目标路径
2. 读取 `PLATFORM-INSTALL-SPEC.md` 获取路径规则
3. 校验安装脚本默认参数与 DryRun 输出
4. 校验目标目录结构与关键入口文件
5. 输出校验报告（含未通过项与修复建议）

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


