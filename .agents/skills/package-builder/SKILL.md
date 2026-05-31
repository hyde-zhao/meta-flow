---
name: package-builder
description: >-
  保留原有 skill 名称以兼容旧触发词，但职责已切换为生成安装脚本。
  当需要交付 Linux / Windows 安装脚本时使用。触发词包括：安装脚本、安装到项目、
  用户级安装、平台安装。
argument-hint: "可选：指定目标平台（claude/codex/openclaw）或安装范围（project/user）"
user-invokable: true
status: active
---
<!-- myflow-managed: version=1.0.0 canonical-commit=fe24c81 generated=2026-05-31T04:12:07Z -->

## 目标

读取已验证产物与安装清单，生成跨平台安装脚本与安装清单说明。

## 适用场景

- 验证通过后，需要交付安装方式
- 需要生成项目级 / 用户级安装脚本

## 前置条件

- [ ] `VERIFICATION-REPORT.md` 无 BLOCKING 项
- [ ] `INSTALL-MANIFEST.yaml` 已生成

## 必须读取的输入

- `delivery/doc/VERIFICATION-REPORT.md`
- `delivery/doc/INSTALL-MANIFEST.yaml`
- `delivery/doc/PLATFORM-CONTRACTS.yaml`
- `process/PLATFORM-INSTALL-SPEC.md`
- 已验证产物目录

## 知识来源

- 安装清单与平台规则
- `delivery/doc/PLATFORM-CONTRACTS.yaml` 是平台安装路径单一真相源
- 当前安装脚本能力边界
- `meta-flow` 当前 canonical 安装器：`delivery/scripts/install.py`、`delivery/scripts/install.ps1`、`delivery/scripts/install.sh`
- 仓库侧可能存在额外打包辅助脚本，但这类脚本不属于 `delivery/` 安装产物，也不作为安装脚本分析真相源

## 执行步骤

1. 读取安装清单、`delivery/doc/PLATFORM-CONTRACTS.yaml` 和平台规则，并先对照 `meta-flow` 的 `delivery/scripts/install.py`、`delivery/scripts/install.ps1`、`delivery/scripts/install.sh` 确认真实文件名与路径。
2. 生成 `install.py`、`install.ps1`、`install.sh`。
3. 若目标包含 Codex，必须从 `delivery/doc/PLATFORM-CONTRACTS.yaml` 取路径：subagent 写入 `.codex/agents/<name>.toml` 或 `~/.codex/agents/<name>.toml`；Skill 写入 `.agents/skills/<skill>/SKILL.md` 或 `~/.agents/skills/<skill>/SKILL.md`。
4. Codex subagent 严格遵循官方 schema：必填 `name`、`description`、`developer_instructions`；仅允许官方可选字段 `nickname_candidates`、`model`、`model_reasoning_effort`、`sandbox_mode`、`mcp_servers`、`skills.config`；不得写 `version`、`instructions` 或其他非标准顶层字段。
5. Codex 安装时必须为 canonical subagent 写入 `nickname_candidates` 命令别名：`meta-po`、`meta-pm`、`meta-se`、`meta-doc` 各 5 个，`meta-dev` 与 `meta-qa` 各 10 个。按百家姓顺序依次分配：`meta-po -> po-zhao/po-qian/po-sun/po-li/po-zhou`、`meta-pm -> pm-wu/pm-zheng/pm-wang/pm-feng/pm-chen`、`meta-se -> se-chu/se-wei/se-jiang/se-shen/se-han`、`meta-dev -> dev-yang/dev-zhu/dev-qin/dev-you/dev-xu/dev-he/dev-lv/dev-shi/dev-zhang/dev-kong`、`meta-qa -> qa-he/qa-lv/qa-shi/qa-zhang/qa-kong/qa-cao/qa-yan/qa-hua/qa-jin/qa-wei`、`meta-doc -> doc-cao/doc-yan/doc-hua/doc-jin/doc-wei`。
6. Claude Code 文件型 subagent 不使用 nickname；安装时必须写入不同 `color`：`meta-po=red`、`meta-pm=orange`、`meta-se=yellow`、`meta-dev=green`、`meta-qa=cyan`、`meta-doc=purple`。
7. 安装器必须封装 `ensure_directory()` / `ensure_file_target()`：写入任何文件、复制任何树、生成 manifest 前，逐级检查父路径组件；存在且为目录则继续，不存在则创建，存在但不是目录则输出明确错误并终止。
8. 安装 CLI 必须支持 `meta-flow install <platform>` 与 `meta-flow uninstall <platform>`；`--platform` 仅作为 legacy 兼容入口保留。`meta-flow install --help`、`meta-flow install <platform> --help`、`meta-flow uninstall --help`、`meta-flow uninstall <platform> --help` 都必须输出可读帮助。
9. 用 `platform-validator` 校验 DryRun 输出、目录结构、Codex subagent schema、Codex nickname、Claude Code color、Codex `.codex/skills` 负向断言和路径组件冲突场景。

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
- 安装脚本中的平台路径必须由 `delivery/doc/PLATFORM-CONTRACTS.yaml` 驱动；不得在 agent/skill/rule 分支中各自硬编码路径矩阵
- 禁止裸用 `mkdir(parents=True, exist_ok=True)` 作为唯一目录保障；所有写文件、复制文件、复制目录和回滚恢复都必须先调用统一路径前置校验
- 分析和产出安装脚本时，仓库根上下文中的 canonical 路径必须写为 `delivery/scripts/install.py`、`delivery/scripts/install.ps1`、`delivery/scripts/install.sh`；只有当 `delivery/` 被单独分发为仓库根时，才使用 `scripts/install.py`、`scripts/install.ps1`、`scripts/install.sh`
- Codex subagent 的指令正文必须写入 `developer_instructions`；canonical agent Markdown 正文映射到该字段，不得另造 `instructions` 顶层字段
- 若 canonical source 或渲染结果出现 `version` 等非官方 Codex subagent 顶层字段，必须视为错误并阻断交付
- canonical agent 的 `name` 不因命令别名改变；`po-zhao` 等只进入 Codex `nickname_candidates`，不得替换 `meta-po`、`meta-dev` 等状态机角色名
- Claude Code 只用 `color` 区分 subagent，不新增伪 nickname 字段
- Codex Skill 禁止写入 `.codex/skills` 或 `~/.codex/skills`，guardrail 必须覆盖负向断言
- 目标路径任一父级组件被普通文件占用时，安装器必须 fail fast，输出 `安装路径被非目录占用: <path>` 和可操作修复提示，不得暴露 Python traceback

## 验收标准

- [ ] 3 个安装脚本已生成
- [ ] 支持 claude / codex / openclaw 与 project / user 两类安装
- [ ] DryRun 输出可被 `platform-validator` 校验
- [ ] `meta-flow install <platform>` 与 `meta-flow uninstall <platform>` 可用，多层级 `-h` / `--help` 可用
- [ ] Codex 安装产物中的 `.codex/agents/*.toml` 仅包含官方 schema 字段，且 `developer_instructions` 非空
- [ ] Codex Skill dry-run 输出包含 `.agents/skills/<skill>/SKILL.md` 或 `~/.agents/skills/<skill>/SKILL.md`，且不包含 `.codex/skills`
- [ ] 目标路径被文件占用时，安装器必须 fail fast，并输出可操作修复提示；例如 `<target>/.codex` 为普通文件时，Codex project agent 安装不得出现 `Traceback` 或 `NotADirectoryError`

## 不适用边界

- 当前产物尚未验证通过
- 当前任务只需校验结构，不需生成脚本

## Gotchas

- 安装器最容易静默带出未验证中间文件，清单驱动必须严格限定复制范围
- DryRun 输出和真实安装逻辑必须共用同一映射规则，避免校验与执行分叉
- Codex 不识别 `version`，而且不会把 `instructions` 当成 subagent 指令体；必须写成 `developer_instructions`
- Claude Code 支持 `color` frontmatter，但不支持 Codex 风格的 `nickname_candidates`
- 不要把 “Codex Agent 在 `.codex/agents`” 类比成 “Codex Skill 在 `.codex/skills`”；两者发现路径不同
- 干净目录安装通过不代表安装器健壮；必须验证路径组件被文件占用时能安全失败
- 仓库侧辅助打包脚本若存在，也必须留在仓库级 `scripts/`，不要把它们放回 `delivery/scripts/`
- 不要把安装脚本参考面写成 `scripts/install.*` 或其他模糊旧路径；需要输出精确文件名
