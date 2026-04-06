---
name: platform-validator
description: >-
  当需要校验安装包目录结构是否符合平台规范时使用。
  触发词包括：校验安装包、平台验证、结构校验、安装结构检查、目录规范校验。
  适用场景：packaging 阶段，package-builder 打包后执行；或独立校验现有安装包。
argument-hint: "可选：指定目标平台（copilot/claude-code/codex/openclaw）或包路径"
user-invokable: true
status: active
---

## 目标

校验 `packages/<target>/` 目录是否符合 `PLATFORM-INSTALL-SPEC.md` 规范，包括目录结构、主入口文件、Frontmatter 完整性和命名规范。

## 适用范围

- 适用阶段：`packaging`（打包后自动调用）；也可独立使用
- 触发时机：`package-builder` 完成打包后，或用户手动请求校验

## 校验维度

### 维度 1：目录结构（BLOCKING）

按 `PLATFORM-INSTALL-SPEC.md` 中各平台的规范目录树逐一比对。

| 平台 | 必须存在的路径 |
|------|--------------|
| copilot | `.github/copilot/copilot-instructions.md` |
| claude-code | `.claude/CLAUDE.md`、`.claude/agents/`、`.claude/skills/` |
| codex | `.codex/agents/`、`.codex/skills/` |
| openclaw | `.openclaw/manifest.yaml`、`.openclaw/agents/`、`.openclaw/skills/` |

### 维度 2：主入口文件（BLOCKING）

主入口文件必须存在且内容非空（字节数 > 0）。

### 维度 3：命名规范（REQUIRED）

所有 Agent/Skill 文件名必须符合 kebab-case 规范：
- 正则：`^[a-z][a-z0-9-]+\.(md|yaml)$`
- 不允许大写字母、下划线、空格

### 维度 4：Frontmatter 完整性（REQUIRED）

所有 `.md` 格式 Agent/Skill 文件必须包含 Frontmatter，且以下字段非空：
- `title` 或 `name`
- `version`
- `description`

### 维度 5：OpenClaw manifest 完整性（仅 openclaw 平台，REQUIRED）

`manifest.yaml` 必须列出所有 `agents/` 和 `skills/` 目录中的文件。

## 执行步骤

1. 确定目标平台（参数指定或全部平台）
2. 读取 `PLATFORM-INSTALL-SPEC.md` 获取各平台规范
3. 逐平台执行 5 个维度的校验
4. 汇总校验结果，按阻断等级分类
5. 输出校验报告（含通过项、未通过项和修复建议）

## 输出格式

```markdown
## platform-validator 校验报告

### 目标平台：<platform>

| 维度 | 阻断等级 | 状态 | 说明 |
|------|---------|------|------|
| 目录结构 | BLOCKING | ✅ 通过 | |
| 主入口文件 | BLOCKING | ✅ 通过 | |
| 命名规范 | REQUIRED | ❌ 未通过 | `MySkill.md` 不符合 kebab-case |
| Frontmatter | REQUIRED | ✅ 通过 | |

### 综合结论

- BLOCKING 未通过：0 项
- REQUIRED 未通过：1 项
- 总体结论：REQUIRED 问题需修复后重新打包
```

## 执行约束

- 只做校验，不修改任何文件
- 发现 BLOCKING 问题时，阻断 packaging 阶段推进
- 发现 REQUIRED 问题时，记录并通知 meta-po，由 meta-po 决定是否阻断

## 验收标准

- [ ] 所有 BLOCKING 维度校验结果有明确通过/未通过记录
- [ ] 未通过项有具体文件路径和修复建议
- [ ] 未修改任何被校验文件
