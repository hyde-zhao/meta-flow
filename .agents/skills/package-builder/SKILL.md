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

## 执行步骤

1. 读取安装清单和平台规则。
2. 生成 `install.py`、`install.ps1`、`install.sh`。
3. 用 `platform-validator` 校验 DryRun 输出与目录结构。

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

## 验收标准

- [ ] 3 个安装脚本已生成
- [ ] 支持 4 平台与 project / user 两类安装
- [ ] DryRun 输出可被 `platform-validator` 校验

## 不适用边界

- 当前产物尚未验证通过
- 当前任务只需校验结构，不需生成脚本

## Gotchas

- 安装器最容易静默带出未验证中间文件，清单驱动必须严格限定复制范围
- DryRun 输出和真实安装逻辑必须共用同一映射规则，避免校验与执行分叉
