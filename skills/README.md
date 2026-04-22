# Skills README — Agent 与 Skill 应用关系

> 本文件记录**当前仓库中已交付的 Agent 与 Skill 的应用关系**。
> 它只覆盖 `skills/` 目录下实际存在的 Skill，不把 Agent 提示词中的历史占位或未交付 Skill 计入正式映射。

## 维护规则

1. 开发、新增、删除或修改 Skill 时，若影响 Agent / Skill 关系或模板交叉引用关系，必须同步更新本文件。
2. 开发或修改 Agent 时，若影响 Skill 的调用、适用或归属关系，必须同步更新本文件。
3. 历史占位或未交付 Skill 不写入正式关系表。

## Agent → Skill 关系

| Agent | 主要阶段 / 场景 | 使用 Skill | 用途 |
|---|---|---|---|
| `meta-po` | `init`、状态推进、变更管理、问题分流 | `state-router`、`change-impact-analysis`、`issue-routing`、`context-handoff` | 推进状态、受理变更、路由问题、装配交接上下文 |
| `meta-pm` | `requirement-clarification` | `use-case-discovery`、`requirement-clarifier`、`scenario-expansion`、`requirement-extraction`、`scope-normalization` | 发现场景、澄清需求歧义、展开测试场景、提取需求、整理需求范围 |
| `meta-se` | `solution-design`（HLD 前）、`story-planning` | `awesome-copilot-fetcher`、`awesome-copilot-analysis`、`hld-designer`、`phase-designer`、`dependency-mapper`、`wave-planner`、`story-manager`、`dag-validator` | 资源获取与借鉴分析、输出 HLD、拆解 Story、建立依赖并校验计划 |
| `meta-dev` | `story-execution` | `lld-designer`、`claude-agent-writer`、`copilot-agent-writer` | 先输出 LLD，再按平台规范实现 Agent 产物 |
| `meta-qa` | `ready-for-verification` 后 | `dangerous-command-scan`、`platform-validator`、`package-builder`、`coverage-checker`、`runtime-risk-review`、`permission-boundary-check`、`context-manifest-builder` | 执行质量验证、安全审计、安装脚本与安装结构校验 |
| `meta-doc` | `documentation` | `workflow-renderer` | 将已验证产物组织为可读交付文档 |
| `meta-dm`（已废弃） | 历史 Story 规划 | `phase-designer`、`wave-planner`、`dependency-mapper`、`story-manager`、`dag-validator` | 仅供历史参考，现由 `meta-se` 接管 |

## Skill → Canonical Agent 关系

| Skill | Canonical Agent | 说明 |
|---|---|---|
| `awesome-copilot-fetcher` | `meta-se` | 拉取 `.input/` 外部资源（`.input/` 为空时由 meta-se 触发）|
| `awesome-copilot-analysis` | `meta-se` | HLD 前借鉴分析，输出 `AWESOME-COPILOT-ANALYSIS.md` |
| `state-router` | `meta-po` | 状态机推进与回退 |
| `change-impact-analysis` | `meta-po` | 需求/设计变更管理 |
| `issue-routing` | `meta-po` | ISSUE 分类与路由 |
| `context-handoff` | `meta-po` | 阶段切换时的最小上下文装配 |
| `use-case-discovery` | `meta-pm` | 阶段零调研后的场景发现与 `USE-CASES.md` 生成 / 更新 |
| `requirement-clarifier` | `meta-pm` | 多轮澄清需求 |
| `scenario-expansion` | `meta-pm` | 从需求扩展使用场景 |
| `requirement-extraction` | `meta-pm` | 结构化需求提取 |
| `scope-normalization` | `meta-pm` | 需求归一化与去重 |
| `hld-designer` | `meta-se` | 正式 HLD 生成 |
| `phase-designer` | `meta-se` | 划分执行阶段 |
| `dependency-mapper` | `meta-se` | 建立 Story / 任务依赖 |
| `wave-planner` | `meta-se` | 规划并行 Wave |
| `story-manager` | `meta-se` | 生成 Story 卡片与 Backlog |
| `dag-validator` | `meta-se` | 校验计划依赖图 |
| `lld-designer` | `meta-dev` | Story 级 LLD 设计 |
| `claude-agent-writer` | `meta-dev` | Claude Agent 产物规范 |
| `copilot-agent-writer` | `meta-dev` | Copilot Agent 产物规范 |
| `dangerous-command-scan` | `meta-qa` | 危险命令与注入风险扫描 |
| `platform-validator` | `meta-qa` | 安装目标与 DryRun 校验 |
| `package-builder` | `meta-qa` | 平台安装脚本生成 |
| `coverage-checker` | `meta-qa` | 覆盖度检查 |
| `runtime-risk-review` | `meta-qa` | 运行时风险复核 |
| `permission-boundary-check` | `meta-qa` | 权限边界检查 |
| `context-manifest-builder` | `meta-qa` | 生成执行上下文清单 |
| `workflow-renderer` | `meta-doc` | 交付文档渲染 |
| `issue-drafter` | 问题处理链路 | 常与 `issue-routing`、`change-impact-analysis` 配合 |
| `run-feedback-parser` | 执行反馈链路 | 常为 `issue-drafter` / `issue-routing` 上游 |
| `file-to-markdown` | 文档导入链路 | 按需用于外部资料转 Markdown |
| `regression-subset-builder` | 修复验证链路 | 问题修复后收缩回归范围 |

## `meta-pm` 相邻 Skill 边界

| Skill | 主输入 / 主输出 | 边界说明 |
|---|---|---|
| `use-case-discovery` | `REQUEST.md`、`INPUT-INDEX.md`、`CLARIFICATION-LOG.md`、`USE-CASES.md` → `USE-CASES.md` | 只负责发现、补全、确认用户使用场景，并维护覆盖自检表；不提取需求条目 |
| `requirement-clarifier` | `REQUEST.md`、`REQUIREMENTS.md`、`CLARIFICATION-LOG.md` → `CLARIFICATION-LOG.md` | 只处理需求歧义、未决问题和澄清轮次；不替代场景发现 |
| `requirement-extraction` | `USE-CASES.md` / `REQUEST.md` → `REQUIREMENTS.md` | 直接消费正式场景工件提取需求；不重做场景访谈 |
| `scenario-expansion` | `REQUIREMENTS.md` → `SCENARIOS.yaml`、`TEST-MATRIX.md` | 面向测试覆盖与验证场景；不用于用户场景发现或需求歧义澄清 |

## 外部资源 Skill

| Skill | 分类 | 说明 |
|---|---|---|
| `awesome-copilot-fetcher` | 资源获取 | 从 `github/awesome-copilot` 拉取 agents/skills/workflows/hooks/instructions/plugins，存放到 `.input/` |
| `awesome-copilot-analysis` | 资源分析 | 对照项目 REQUIREMENTS，分析 `.input/` 中资源的优缺点，输出 `AWESOME-COPILOT-ANALYSIS.md` 供 HLD / meta-dev / meta-qa 引用 |

## 非正式 / 未交付占位说明

以下名称曾在个别 Agent 提示词中出现，但**当前不在 `skills/` 目录中交付**，因此不纳入正式映射：

- `vendor-profile-loader`
- `constraint-normalizer`

## 检视记录（2026-04-22）

1. 已删除废弃 Skill `solution-designer`；HLD 设计的 canonical Skill 仅保留 `hld-designer`。
2. `vendor-profile-loader`、`constraint-normalizer` 仍在部分 Agent 提示词或历史文档中出现，但它们不是 `skills/` 目录下的正式交付 Skill；后续若继续收敛，应统一清理这些非正式占位引用。

## Skill 模板交叉引用

> 本章节记录 Skill 间因消费同一正式工件而产生的模板交叉引用关系。
> 消费者 Skill 不直接引用模板路径，只依赖产出 Skill 写入工作区正式工件的内容契约。

| 正式工件 | 模板持有 Skill | 消费者 Skill | 说明 |
|---|---|---|---|
| `AWESOME-COPILOT-ANALYSIS.md` | `awesome-copilot-analysis` | `hld-designer`、`lld-designer`（via Story dev_context）、`meta-qa`（via hooks 清单）| 分析报告是 HLD 前置输入；meta-dev/meta-qa 消费其第 7.1/7.4 节 |
| `CR-*.md` | `change-impact-analysis` | `issue-routing` | `issue-routing` 只消费 CR 内容契约 |
| `USE-CASES.md` | `use-case-discovery` | `requirement-extraction` | `use-case-discovery` 维护正式场景工件与覆盖自检表；`requirement-extraction` 直接消费该工件 |
| `REQUIREMENTS.md` | `requirement-extraction` | `scope-normalization` | `scope-normalization` 归一化已生成的需求 |
| `CLARIFICATION-LOG.md` | `requirement-clarifier` | `use-case-discovery` | 澄清轮次由 `requirement-clarifier` 维护；场景发现摘要由 `use-case-discovery` 追加 |
| `STATE.md` | `state-router` | （无交叉引用） | |
| `STORY-*.md` | `story-manager` | （无交叉引用） | |
| `STORY-*-LLD.md` | `lld-designer` | （无交叉引用） | |
