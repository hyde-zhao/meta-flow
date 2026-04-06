# 平台安装规范（PLATFORM-INSTALL-SPEC）

> 由 meta-se 在方案设计阶段输出，meta-qa 在打包阶段严格遵守。

---

## 平台总览

| 维度 | GitHub Copilot | Claude Code | Codex | OpenClaw |
|------|---------------|-------------|-------|---------|
| 安装根目录 | `.github/copilot/` | `.claude/` | `.codex/` | `.openclaw/` |
| 主入口文件 | `copilot-instructions.md` | `CLAUDE.md` | 无单一入口 | `manifest.yaml` |
| Agent 格式 | Markdown | Markdown | YAML | Markdown |
| Skill 格式 | Markdown | Markdown | Markdown | Markdown |
| 安装方式 | 推送到仓库根 | 复制到项目根 | `codex install` | 平台 UI 加载 |
| 支持 subagent | 部分（Skills） | 是（agents/） | 部分 | 待确认 |

---

## GitHub Copilot

### 目录结构

```
.github/
└── copilot/
    ├── copilot-instructions.md   ← 必填，全局系统提示词
    └── skills/
        └── <skill-name>.md       ← Skill 定义文件
```

### 主入口文件要求

- 文件：`copilot-instructions.md`
- 内容：全局 Copilot 指令，声明主编排器角色和 Skill 发现路径
- 必须非空

### Skill 文件要求

- 路径：`skills/<skill-name>.md`
- 文件名：kebab-case，正则 `^[a-z][a-z0-9-]+\.md$`
- 必须包含 Frontmatter：`name`、`description`、`user-invokable`

### 验证方式

推送到仓库后，在 Copilot CLI 中执行 `/skills` 确认 Skill 被识别。

### 已知限制

- 不支持独立 Agent 提示词文件（Agent 通过 `AGENTS.md` 或 `copilot-instructions.md` 声明）
- Skills 不支持动态参数类型校验

---

## Claude Code

### 目录结构

```
.claude/
├── CLAUDE.md              ← 必填，主系统提示词入口
├── agents/
│   └── <agent-name>.md    ← Agent 系统提示词
└── skills/
    └── <skill-name>.md    ← Skill 定义文件
```

### 主入口文件要求

- 文件：`CLAUDE.md`
- 内容：主 Agent（meta-po）系统提示词
- 必须非空

### Agent 文件要求

- 路径：`agents/<agent-name>.md`
- 文件名：kebab-case
- 建议包含 Frontmatter：`title`、`version`、`description`

### Skill 文件要求

- 路径：`skills/<skill-name>.md`
- 文件名：kebab-case
- 必须包含完整 Frontmatter

### 验证方式

将 `.claude/` 复制到目标项目根目录，重启 Claude Code 后确认 Agent/Skill 被识别。

### 已知限制

- 无官方 subagent 并行执行支持，需通过提示词约定模拟

---

## Codex

### 目录结构

```
.codex/
├── agents/
│   └── <agent-name>.yaml  ← YAML 格式（从 Markdown 转换）
└── skills/
    └── <skill-name>.md    ← Skill 定义文件
```

### Agent 文件要求（YAML 格式）

```yaml
name: <agent-name>
description: <描述>
version: "1.0.0"
instructions: |
  <Markdown 正文内容>
```

### Skill 文件要求

- 与 GitHub Copilot 格式相同

### 验证方式

执行 `codex install packages/codex/` 后确认 Agent 可加载，执行 `codex run <agent-name>` 验证。

### 已知限制

- Agent 格式为 YAML，需从 Markdown 转换
- 不支持复杂状态机，需通过文件系统模拟状态

---

## OpenClaw

### 目录结构

```
.openclaw/
├── manifest.yaml          ← 必填，列出全部 Agent 和 Skill
├── agents/
│   └── <agent-name>.md
└── skills/
    └── <skill-name>.md
```

### manifest.yaml 要求

```yaml
version: "1.0"
agents:
  - name: <agent-name>
    file: agents/<agent-name>.md
skills:
  - name: <skill-name>
    file: skills/<skill-name>.md
```

- 必须列出 `agents/` 和 `skills/` 中所有文件
- `manifest.yaml` 必须非空

### 验证方式

按 OpenClaw 平台文档加载 `manifest.yaml`，在 UI 中确认 Agent 和 Skill 被正确注册。

### 已知限制

- 平台能力待进一步确认
- 建议优先验证 Copilot 和 Claude Code 平台

---

## 跨平台通用约定

| 约定 | 内容 |
|------|------|
| 命名规范 | 文件名使用 kebab-case：`^[a-z][a-z0-9-]+\.(md\|yaml)$` |
| 必填 Frontmatter | 所有 Agent/Skill 文件必须包含 `title`（或 `name`）、`version`、`description` |
| 版本锁定 | `PACKAGE-MANIFEST.yaml` 记录每个产物文件的 SHA256 哈希 |
| 单一职责 | 每个 Skill 文件只描述一个能力 |
| 禁止可执行脚本 | 安装包中不得包含自动执行的 shell 脚本 |
