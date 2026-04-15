---
project_id: "MFQ-001"
checkpoint: "⑤ 终验"
status: "pending"         # pending | confirmed | rejected
version: ""               # 交付版本号，如 "2.0.0"
reviewed_by: ""
reviewed_at: ""
---

# 终验检查清单 — ptm-tde

> **元工作流检查点 ⑤ — 终验**
> 所有条目通过后，meta-po 将状态置为 `delivered`。

---

## 一、核心产物完整性

### 1.1 Agent 主文件

| 文件 | 检查项 | 状态 |
|------|-------|------|
| `.output/agents/ptm-tde.md` | 文件存在 | ⬜ |
| | Frontmatter 含 name/description/tools | ⬜ |
| | 12 步状态机定义完整 | ⬜ |
| | 16 个 Skill 触发词全部注册 | ⬜ |
| | 5 个用户确认点均有定义 | ⬜ |
| | `.output/` 目录结构与路径规则说明完整 | ⬜ |

### 1.2 Skill 产物（16 个）

| Skill | 文件存在 | Frontmatter 完整 | 执行流程完整 | 验收标准完整 |
|-------|---------|----------------|------------|------------|
| feature-parser | ⬜ | ⬜ | ⬜ | ⬜ |
| scenario-discovery | ⬜ | ⬜ | ⬜ | ⬜ |
| m-analyzer | ⬜ | ⬜ | ⬜ | ⬜ |
| f-analyzer | ⬜ | ⬜ | ⬜ | ⬜ |
| q-analyzer | ⬜ | ⬜ | ⬜ | ⬜ |
| test-point-integrator | ⬜ | ⬜ | ⬜ | ⬜ |
| design-planner | ⬜ | ⬜ | ⬜ | ⬜ |
| process-design | ⬜ | ⬜ | ⬜ | ⬜ |
| parameter-design | ⬜ | ⬜ | ⬜ | ⬜ |
| data-design | ⬜ | ⬜ | ⬜ | ⬜ |
| combination-design | ⬜ | ⬜ | ⬜ | ⬜ |
| state-design | ⬜ | ⬜ | ⬜ | ⬜ |
| coverage-verifier | ⬜ | ⬜ | ⬜ | ⬜ |
| deliverable-renderer | ⬜ | ⬜ | ⬜ | ⬜ |
| change-impact-analyzer | ⬜ | ⬜ | ⬜ | ⬜ |
| bug-gap-analyzer | ⬜ | ⬜ | ⬜ | ⬜ |

### 1.3 工具脚本（2 个）

| 文件 | 存在 | 可运行（无语法错误） | 路径规则遵守 |
|------|------|------------------|------------|
| `.output/scripts/excel_coupling_tool.py` | ⬜ | ⬜ | ⬜ |
| `.output/scripts/mcp_query_client.py` | ⬜ | ⬜ | ⬜ |

---

## 二、安装脚本

| 平台 | 文件 | 存在 | DryRun 通过 | 目录结构校验通过 |
|------|------|------|------------|---------------|
| Linux/macOS | `.output/scripts/install.sh` | ⬜ | ⬜ | ⬜ |
| Windows PowerShell | `.output/scripts/install.ps1` | ⬜ | ⬜ | ⬜ |
| 跨平台 Python | `.output/scripts/install.py` | ⬜ | ⬜ | ⬜ |

**安装模式验证**：

| 安装模式 | 说明 | 验证状态 |
|---------|------|---------|
| 项目级安装（默认） | 安装到当前工作目录 | ⬜ |
| 用户级安装 | 安装到用户全局目录 | ⬜ |
| 指定目录安装 | 通过 `--target` 参数指定 | ⬜ |

---

## 三、文档质量

### 3.1 README.md

| 检查项 | 状态 |
|-------|------|
| 包含概述和理论基础介绍（MFQ&PPDCS）| ⬜ |
| 包含核心特性一览表 | ⬜ |
| 包含各平台安装指南 | ⬜ |
| 包含快速入门示例 | ⬜ |
| 包含 12 步主流程说明 | ⬜ |
| 包含 16 个 Skill 触发词速查表 | ⬜ |
| 包含目录结构说明 | ⬜ |
| 版本号与实际交付版本一致 | ⬜ |

### 3.2 USER-MANUAL.md

| 检查项 | 状态 |
|-------|------|
| 包含安装指南（3 平台）| ⬜ |
| 包含完整工作流步骤说明（步骤 1~10）| ⬜ |
| 包含每个确认点的操作说明 | ⬜ |
| 包含扩展场景说明（变更分析、问题单分析）| ⬜ |
| 包含故障排查（FAQ / Troubleshooting）| ⬜ |
| 包含物理用例字段规范 | ⬜ |

---

## 四、版本信息

| 项目 | 期望值 | 实际值 | 状态 |
|------|--------|--------|------|
| Agent 版本 | {version} | | ⬜ |
| README 版本 | {version} | | ⬜ |
| USER-MANUAL 版本 | {version} | | ⬜ |
| 理论依据引用 | 《海盗派测试分析: MFQ&PPDCS》邰晓梅著 | | ⬜ |

---

## 五、平台适配

| 平台 | Copilot CLI 入口 | Claude Code 入口 | 安装目录规范 |
|------|----------------|----------------|------------|
| GitHub Copilot | `.github/agents/ptm-tde.agent.md` ⬜ | — | ⬜ |
| Claude Code | — | `.claude/agents/ptm-tde.md` ⬜ | ⬜ |

---

## 六、终验结论

| 维度 | 通过 / 未通过 | 备注 |
|------|-------------|------|
| 核心产物完整性 | | |
| 安装脚本可用性 | | |
| 文档质量 | | |
| 版本信息一致性 | | |
| 平台适配 | | |
| **总体结论** | **通过 / 未通过** | |

**确认选项**：
1. ✅ **终验通过** — 所有项目符合要求，项目状态置为 `delivered`
2. ✏️ **有待办项** — 请列出未通过的检查项，修复后重新提交终验
3. ❌ **终验未通过** — 存在严重缺陷，需 meta-qa/meta-doc 修复后重新验证
