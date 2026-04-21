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
| `meta-pm` | `requirement-clarification` | `requirement-clarifier`、`scenario-expansion`、`requirement-extraction`、`scope-normalization` | 澄清场景、展开场景、提取需求、整理需求范围 |
| `meta-se` | `solution-design`、`story-planning` | `hld-designer`、`phase-designer`、`dependency-mapper`、`wave-planner`、`story-manager`、`dag-validator` | 输出 HLD、拆解 Story、建立依赖并校验计划 |
| `meta-dev` | `story-execution` | `lld-designer`、`claude-agent-writer`、`copilot-agent-writer` | 先输出 LLD，再按平台规范实现 Agent 产物 |
| `meta-qa` | `ready-for-verification` 后 | `dangerous-command-scan`、`platform-validator`、`package-builder`、`coverage-checker`、`runtime-risk-review`、`permission-boundary-check`、`context-manifest-builder` | 执行质量验证、安全审计、安装脚本与安装结构校验 |
| `meta-doc` | `documentation` | `workflow-renderer` | 将已验证产物组织为可读交付文档 |
| `meta-dm`（已废弃） | 历史 Story 规划 | `phase-designer`、`wave-planner`、`dependency-mapper`、`story-manager`、`dag-validator` | 仅供历史参考，现由 `meta-se` 接管 |

## Skill → Canonical Agent 关系

| Skill | Canonical Agent | 说明 |
|---|---|---|
| `state-router` | `meta-po` | 状态机推进与回退 |
| `change-impact-analysis` | `meta-po` | 需求/设计变更管理 |
| `issue-routing` | `meta-po` | ISSUE 分类与路由 |
| `context-handoff` | `meta-po` | 阶段切换时的最小上下文装配 |
| `requirement-clarifier` | `meta-pm` | 多轮澄清需求 |
| `scenario-expansion` | `meta-pm` | 从需求扩展使用场景 |
| `requirement-extraction` | `meta-pm` | 结构化需求提取 |
| `scope-normalization` | `meta-pm` | 需求归一化与去重 |
| `hld-designer` | `meta-se` | 正式 HLD 生成 |
| `solution-designer` | `meta-se` | 已废弃；仅保留历史触发词兼容，正式能力已并入 `hld-designer` |
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

## 非正式 / 未交付占位说明

以下名称曾在个别 Agent 提示词中出现，但**当前不在 `skills/` 目录中交付**，因此不纳入正式映射：

- `vendor-profile-loader`
- `constraint-normalizer`

## Skill 模板交叉引用

> 本章节记录 Skill 间因消费同一正式工件而产生的模板交叉引用关系。
> 消费者 Skill 不直接引用模板路径，只依赖产出 Skill 写入 `.meta-workflow/` 正式工件的内容契约。

| 正式工件 | 模板持有 Skill | 消费者 Skill | 说明 |
|---|---|---|---|
| `HLD.md` | `hld-designer` | `solution-designer`（兼容入口） | `solution-designer` 已废弃，不再维护独立模板 |
| `CR-*.md` | `change-impact-analysis` | `issue-routing` | `issue-routing` 只消费 CR 内容契约 |
| `REQUIREMENTS.md` | `requirement-extraction` | `scope-normalization` | `scope-normalization` 归一化已生成的需求 |
| `CLARIFICATION-LOG.md` | `requirement-clarifier` | （无交叉引用） | |
| `STATE.md` | `state-router` | （无交叉引用） | |
| `STORY-*.md` | `story-manager` | （无交叉引用） | |
| `STORY-*-LLD.md` | `lld-designer` | （无交叉引用） | |
