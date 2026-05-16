# Agents README — Subagent 注册表

> 本文件记录 `agents/` 目录下实际交付的 canonical subagent 定义。
> 只有已启用且参与安装器渲染的 Agent 才应出现在本表中。

## 维护规则

1. 新增、删除或重命名 `agents/*.md` 时，必须同步更新本文件。
2. 如果 Agent 的职责边界、触发范围或所属阶段发生变化，必须同步更新描述。
3. 已废弃或仅保留历史参考的 Agent 不纳入正式注册表。

## Canonical Subagents

| 名称 | Codex 命令 / nickname_candidates | Claude Code 颜色 | 来源 | 主要阶段 / 场景 | 描述 |
|------|-------------------------------|------------------|------|------------------|------|
| `meta-po` | `po-zhao`、`po-qian`、`po-sun`、`po-li`、`po-zhou` | `red` | first-party | `init`、状态推进、变更管理 | 主编排器，负责初始化、状态流转与人工检查点 |
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `orange` | first-party | `requirement-clarification` | 需求澄清与结构化 |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `yellow` | first-party | `solution-design`、`story-planning` | HLD 设计、Story 拆解与开发计划 |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu` | `green` | first-party | `story-execution` | Story LLD 起草与实现 |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong` | `cyan` | first-party | `ready-for-verification` 后 | 测试策略、质量验收与安装脚本交付 |
| `meta-doc` | `doc-cao`、`doc-yan`、`doc-hua`、`doc-jin`、`doc-wei` | `purple` | first-party | `documentation` | README 与 USER-MANUAL 生成 |

说明：

- canonical 名称仍为 `meta-*`，用于状态机、handoff、`agent_lifecycle.role` 与安装路径。
- Codex 安装器把上表命令写入 `.codex/agents/*.toml` 的 `nickname_candidates`。
- Claude Code 文件型 subagent 不使用 nickname；安装器写入 `color` 字段，通过颜色在任务列表和 transcript 中区分角色。
