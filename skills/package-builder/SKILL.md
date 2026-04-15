---
name: package-builder
description: >-
  保留原有 skill 名称以兼容旧触发词，但职责已切换为生成安装脚本。
  当需要交付 Linux / Windows 安装脚本时使用。触发词包括：安装脚本、安装到项目、
  用户级安装、平台安装。
argument-hint: "可选：指定目标平台（copilot/claude-code/codex/openclaw）或安装范围（project/user）"
user-invokable: true
status: active
---

## 目标

读取已验证的 Agent/Skill 产物和 `INSTALL-MANIFEST.yaml`，生成可直接执行的：

- `.output/scripts/install.py`
- `.output/scripts/install.ps1`
- `.output/scripts/install.sh`

脚本必须支持平台选择、默认安装到当前项目目录、指定项目目录，以及用户级 agent / skill 安装。

## 适用范围

- 适用阶段：`verification` 通过后到 `documentation` 前
- 触发时机：`VERIFICATION-REPORT.md` 无 BLOCKING 项，且 meta-po 唤醒 meta-qa 交付安装方式
- 输出消费方：用户（安装使用）、meta-doc（文档引用）、meta-qa（DryRun 验证）

## 前置条件

- [ ] `.output/doc/VERIFICATION-REPORT.md` 存在且无 BLOCKING 未通过项
- [ ] `.output/doc/INSTALL-MANIFEST.yaml` 已生成（列出所有交付产物）
- [ ] `.output/doc/PLATFORM-INSTALL-SPEC.md` 已存在（含各平台目标路径规范）

## 4 平台目标规则

| 平台 | 项目级默认根目录 | 用户级默认根目录 |
|------|------------------|------------------|
| copilot | `<project>/.github/` | `~/.copilot/` |
| claude-code | `<project>/.claude/` | `~/.claude/` |
| codex | `<project>/.codex/` | `~/.codex/` |
| openclaw | `<project>/.openclaw/` | `~/.openclaw/` |

## 脚本能力要求

1. `install.py` 作为跨平台核心脚本
2. `install.ps1` 调用 `install.py`，用于 Windows
3. `install.sh` 调用 `install.py`，用于 Linux/macOS
4. 参数至少包括：
   - `--platform`
   - `--scope`（`project` / `user`）
   - `--project-dir`
   - `--content`（`all` / `agents` / `skills`）
   - `--agent`
   - `--skill`
   - `--dry-run`

## 执行步骤

1. 读取 `INSTALL-MANIFEST.yaml`，获取 Agent / Skill 清单
2. 按平台规则生成安装目标映射
3. 写出 `install.py`、`install.ps1`、`install.sh`
4. 确认 Codex Agent 支持 Markdown → YAML 转换
5. 确认 OpenClaw 支持 `manifest.yaml` 生成
6. 调用 `platform-validator` 校验默认目标路径与 DryRun 输出
7. 输出安装脚本交付结果

## 执行约束

- 不允许在 `VERIFICATION-REPORT.md` 存在 BLOCKING 未通过项时生成安装脚本
- 默认安装目标必须是当前项目目录，不得静默写入用户目录
- 用户级安装必须通过显式参数触发
- 只允许复制已验证产物，不得把 `.output/` 中间文件装入目标目录

## 输出文件

| 文件 | 说明 |
|------|------|
| `.output/scripts/install.py` | 跨平台核心安装器 |
| `.output/scripts/install.ps1` | Windows 安装入口 |
| `.output/scripts/install.sh` | Linux/macOS 安装入口 |
| `.output/doc/INSTALL-MANIFEST.yaml` | 安装清单与默认路径说明 |

## 验收标准

- [ ] 3 个安装脚本已生成且可读
- [ ] 脚本支持 4 平台选择
- [ ] 脚本默认安装到当前项目目录
- [ ] 脚本支持显式指定项目目录
- [ ] 脚本支持用户级 `agents` / `skills` 安装
- [ ] `platform-validator` 校验通过
