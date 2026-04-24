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

读取已验证产物与安装清单，生成跨平台安装脚本与安装清单说明。

## 适用场景

- 验证通过后，需要交付安装方式
- 需要生成项目级 / 用户级安装脚本

## 前置条件

- [ ] `VERIFICATION-REPORT.md` 无 BLOCKING 项
- [ ] `INSTALL-MANIFEST.yaml` 已生成

## 必须读取的输入

- `process/VERIFICATION-REPORT.md`
- `process/INSTALL-MANIFEST.yaml`
- `process/PLATFORM-INSTALL-SPEC.md`
- 已验证产物目录

## 知识来源

- 安装清单与平台规则
- 当前安装脚本能力边界
- `meta-flow` 当前 canonical 安装器：`delivery/scripts/install.py`、`delivery/scripts/install.ps1`、`delivery/scripts/install.sh`
- 仓库侧若存在其他辅助脚本，也不作为安装脚本分析真相源，且不随 `delivery/` 安装

## 执行步骤

1. 读取安装清单和平台规则，并先对照 `meta-flow` 的 `delivery/scripts/install.py`、`delivery/scripts/install.ps1`、`delivery/scripts/install.sh` 确认真实文件名与路径。
2. 生成 `install.py`、`install.ps1`、`install.sh`。
3. 若目标包含 Codex，必须把 subagent 写入 `.codex/agents/<name>.toml`，并严格遵循官方 schema：必填 `name`、`description`、`developer_instructions`；仅允许官方可选字段 `nickname_candidates`、`model`、`model_reasoning_effort`、`sandbox_mode`、`mcp_servers`、`skills.config`；不得写 `version`、`instructions` 或其他非标准顶层字段。
4. 用 `platform-validator` 校验 DryRun 输出、目录结构和 Codex subagent schema。

## 输出文件 / 输出模板

| 文件 | 路径 | 说明 |
|---|---|---|
| 安装器 | `delivery/scripts/install.py` | 跨平台核心安装器 |
| Windows 入口 | `delivery/scripts/install.ps1` | PowerShell 安装入口 |
| Shell 入口 | `delivery/scripts/install.sh` | shell 安装入口 |

## 约束

- 输入依赖验证报告与安装清单内容，不依赖模板文件存在
- 默认安装目标必须是当前项目目录
- 用户级安装必须显式触发
- 分析和产出安装脚本时，仓库根上下文中的 canonical 路径必须写为 `delivery/scripts/install.py`、`delivery/scripts/install.ps1`、`delivery/scripts/install.sh`；只有当 `delivery/` 被单独分发为仓库根时，才使用 `scripts/install.py`、`scripts/install.ps1`、`scripts/install.sh`
- Codex subagent 的指令正文必须写入 `developer_instructions`；canonical agent Markdown 正文映射到该字段，不得另造 `instructions` 顶层字段
- 若 canonical source 或渲染结果出现 `version` 等非官方 Codex subagent 顶层字段，必须视为错误并阻断交付

## 验收标准

- [ ] 3 个安装脚本已生成
- [ ] 支持 4 平台与 project / user 两类安装
- [ ] DryRun 输出可被 `platform-validator` 校验
- [ ] Codex 安装产物中的 `.codex/agents/*.toml` 仅包含官方 schema 字段，且 `developer_instructions` 非空

## 不适用边界

- 当前产物尚未验证通过
- 当前任务只需校验结构，不需生成脚本

## Gotchas

- 安装器最容易静默带出未验证中间文件，清单驱动必须严格限定复制范围
- DryRun 输出和真实安装逻辑必须共用同一映射规则，避免校验与执行分叉
- Codex 不识别 `version`，而且不会把 `instructions` 当成 subagent 指令体；必须写成 `developer_instructions`
- 不要把安装脚本参考面写成 `scripts/package_builder.py`、`scripts/install.*` 或其他模糊旧路径；需要输出精确文件名
