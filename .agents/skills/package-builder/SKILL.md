---
name: package-builder
description: >-
  当需要将已验证的 Agent/Skill 产物打包为各平台安装包时使用。
  触发词包括：打包、生成安装包、平台打包、构建安装包、生成平台包。
  适用场景：packaging 阶段，所有 Story 验证通过后。
argument-hint: "可选：指定目标平台（copilot/claude-code/codex/openclaw）或仅构建单平台"
user-invokable: true
status: active
---

## 目标

读取已验证的 Agent/Skill 产物和 `PACKAGE-MANIFEST.yaml`，按 `PLATFORM-INSTALL-SPEC.md` 规范构建各平台安装目录，生成 SHA256 哈希校验清单。

## 适用范围

- 适用阶段：`packaging`
- 触发时机：`VERIFICATION-REPORT.md` 无 BLOCKING 项，且 meta-po 唤醒 meta-qa 执行打包
- 输出消费方：用户（安装使用）、meta-doc（文档引用）、安装脚本

## 前置条件

- [ ] `.workflow-meta/VERIFICATION-REPORT.md` 存在且无 BLOCKING 未通过项
- [ ] `.workflow-meta/PACKAGE-MANIFEST.yaml` 已生成（列出所有产物文件）
- [ ] `.workflow-meta/PLATFORM-INSTALL-SPEC.md` 已存在（含各平台规范）

## 4 平台构建规则

### GitHub Copilot

```
packages/copilot/
└── .github/
    └── copilot/
        ├── copilot-instructions.md   ← meta-po 全局指令（必填）
        └── skills/
            └── <skill-name>.md       ← 所有 Skill 文件
```

### Claude Code

```
packages/claude-code/
└── .claude/
    ├── CLAUDE.md                     ← meta-po 系统提示词入口（必填）
    ├── agents/
    │   └── <agent-name>.md
    └── skills/
        └── <skill-name>.md
```

### Codex

```
packages/codex/
└── .codex/
    ├── agents/
    │   └── <agent-name>.yaml         ← YAML 格式（需从 Markdown 转换）
    └── skills/
        └── <skill-name>.md
```

### OpenClaw

```
packages/openclaw/
└── .openclaw/
    ├── manifest.yaml                 ← 必填，列出所有 Agent 和 Skill
    ├── agents/
    │   └── <agent-name>.md
    └── skills/
        └── <skill-name>.md
```

## 执行步骤

1. 读取 `PACKAGE-MANIFEST.yaml`，获取所有产物文件列表
2. 按目标平台创建安装目录结构
3. 复制对应文件到各平台目录（Codex 需转换为 YAML 格式）
4. 生成 `packages/<target>/INSTALL-CHECKSUMS.sha256`（每个文件的 SHA256 哈希）
5. 更新 `PACKAGE-MANIFEST.yaml`，补充 `sha256` 字段
6. 调用 `platform-validator` Skill 校验目录结构
7. 如校验通过，输出打包完成报告

## Codex YAML 格式转换规则

Markdown Agent 文件转换为 YAML 时：
```yaml
name: <agent-name>
description: <从 Markdown 首行提取>
version: <从 Frontmatter 提取>
instructions: |
  <Markdown 正文内容>
```

## 执行约束

- 不允许在 `VERIFICATION-REPORT.md` 存在 BLOCKING 未通过项时执行打包
- SHA256 哈希必须在复制完成后计算（不能使用源文件哈希）
- 打包目录中不得包含 `.workflow-meta/` 的中间过程文件

## 输出文件

| 文件 | 说明 |
|------|------|
| `packages/copilot/` | GitHub Copilot 安装包 |
| `packages/claude-code/` | Claude Code 安装包 |
| `packages/codex/` | Codex 安装包 |
| `packages/openclaw/` | OpenClaw 安装包 |
| `packages/<target>/INSTALL-CHECKSUMS.sha256` | 各平台 SHA256 校验文件 |

## 验收标准

- [ ] 所有目标平台目录已创建
- [ ] 每个平台的主入口文件存在且非空
- [ ] SHA256 校验文件已生成
- [ ] `platform-validator` 校验通过
- [ ] `PACKAGE-MANIFEST.yaml` 中所有产物文件有 `sha256` 字段
