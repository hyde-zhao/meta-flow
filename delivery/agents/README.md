# Agents README — Subagent 注册表

> 本文件记录 `agents/` 目录下实际交付的 canonical subagent 定义。
> 只有已启用且参与安装器渲染的 Agent 才应出现在本表中。

## 维护规则

1. 新增、删除或重命名 `agents/*.md` 时，必须同步更新本文件。
2. 如果 Agent 的职责边界、触发范围或所属阶段发生变化，必须同步更新描述。
3. 已废弃或仅保留历史参考的 Agent 不纳入正式注册表。
4. 软件开发工作流的长期产物默认写入 `docs/`：例如 `docs/product/TEST-MATRIX.md`、`docs/design/BLUEPRINT.md`、`docs/features/<feature>/DESIGN.md`、`docs/quality/TEST-REPORT.md`、`docs/release/DEPLOY-CHECKLIST.md`；过程态仍写 `process/`，人工确认态写 `process/checkpoints/`。发布准备优先写入 `process/release/RELEASE-CONTEXT.yaml` 作为 capsule-first 摘要，再按 `release_artifact_profile=minimal|compact|full` 裁剪发布文档。

## Canonical Subagents

Host Orchestrator 是当前会话主进程职责，不在本目录安装为平台 subagent。本表只列出会被安装器渲染的功能子 agent。

| 名称 | Codex 命令 / nickname_candidates | Claude Code 颜色 | 来源 | 主要阶段 / 场景 | 描述 |
|------|-------------------------------|------------------|------|------------------|------|
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `orange` | first-party | `requirement-clarification` | 被委托期间直接与用户完成 Scenario Gray Areas、真实意图与认知盲区澄清、Deferred Ideas、需求结构化、`docs/product/SCENARIOS.yaml` / `docs/product/TEST-MATRIX.md`、Story Map、MVP Scope、草案可提交确认与 CP2 决策输入 |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `yellow` | first-party | `solution-design`、`story-planning` | 被委托期间直接与用户完成蓝图适用性判定、Architecture Gray Areas、advisor table-first 讨论、HLD 草案确认；CP3 后拆解 Story、必要的 Feature 设计、CP4 自动预检与开发计划 |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu`、`dev-he`、`dev-lv`、`dev-shi`、`dev-zhang`、`dev-kong` | `green` | first-party | `story-planning`、`story-execution` | Story 设计证据起草、LLD clarification item 写入、`implementation-execution` 实现执行证据、实现，以及 CP7 未通过后的修复和再验证交接 |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong`、`qa-cao`、`qa-yan`、`qa-hua`、`qa-jin`、`qa-wei` | `cyan` | first-party | `ready-for-verification` 后 | `verification-execution` 验证执行证据、测试策略、质量验收、测试矩阵验证、独立质量评审、CP7 结论分级、发布就绪、缺陷 / 设计澄清回流与安装脚本交付 |
| `meta-doc` | `doc-cao`、`doc-yan`、`doc-hua`、`doc-jin`、`doc-wei` | `purple` | first-party | `documentation` | README、USER-MANUAL 与关键决策/fast-lane/自动调度追溯说明生成 |

说明：

- canonical 名称仍为 `meta-*`，用于功能子 agent 的状态机、handoff、`agent_lifecycle.role` 与安装路径。
- Codex 安装器把上表命令写入 `.codex/agents/*.toml` 的 `nickname_candidates`。
- Claude Code 文件型 subagent 不使用 nickname；安装器写入 `color` 字段，通过颜色在任务列表和 transcript 中区分角色。
