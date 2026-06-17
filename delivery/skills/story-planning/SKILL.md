---
name: story-planning
description: >-
  当已确认的场景与需求需要收敛为用户故事地图、MVP 范围、发布切片和后续 backlog 时使用。
  触发词包括：Story Map、MVP 范围、发布切片、产品规划、范围确认。
  适用场景：Discovery 完成后、蓝图/架构设计前的产品规划阶段。
argument-hint: "USE-CASES.md、SCENARIOS.yaml 和 REQUIREMENTS.md 路径"
user-invokable: true
status: active
---

## 目标

把已确认的 `USE-CASES.md`、`SCENARIOS.yaml` 与 `REQUIREMENTS.md` 收敛为用户 outcome 导向的规划产物：`STORY-MAP.md`、`MVP-SCOPE.md`、`RELEASE-SLICES.md` 和 `BACKLOG.md`。

## 适用场景

- 场景基线已确认，需要把场景组织为用户活动、任务和 story。
- 需要明确本轮 MVP 做什么、不做什么、后续候选项是什么。
- 需要为蓝图设计提供 Feature / Epic 候选边界和发布切片。

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] `docs/product/USE-CASES.md` 已确认或 CP2 明确允许进入规划草案。
- [ ] `docs/product/SCENARIOS.yaml` 已生成，或 `scenario-expansion` 明确给出 N/A 原因。
- [ ] `docs/product/REQUIREMENTS.md` 已生成，且 BLOCKING 未决项为 0。

## 必须读取的输入

- `docs/product/USE-CASES.md`
- `docs/product/SCENARIOS.yaml`
- `docs/product/REQUIREMENTS.md`
- `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md`（若存在）
- 活跃 `process/changes/CR-*.md`（若本轮由变更触发）

## 知识来源

- `skills/story-planning/templates/STORY-MAP-TEMPLATE.md`
- `skills/story-planning/templates/MVP-SCOPE-TEMPLATE.md`
- `skills/story-planning/templates/RELEASE-SLICES-TEMPLATE.md`
- `skills/story-planning/templates/BACKLOG-TEMPLATE.md`

## 执行步骤

1. 从 use case 和 scenario 中提取用户活动、任务、触发条件和失败路径。
2. 将需求条目映射到 story，story 必须表达用户要达成的结果，不写代码实现步骤。
3. 按用户 outcome 划分 MVP，并显式记录 Out of Scope、Deferred 和后续触发条件。
4. 输出 release slices，说明每个切片的用户价值、前置依赖、验证入口和风险。
5. 将暂缓项、增强项、灰区延后项写入 `BACKLOG.md`，不得静默丢弃。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 用户故事地图 | `docs/product/STORY-MAP.md` | `skills/story-planning/templates/STORY-MAP-TEMPLATE.md` |
| MVP 范围 | `docs/product/MVP-SCOPE.md` | `skills/story-planning/templates/MVP-SCOPE-TEMPLATE.md` |
| 发布切片 | `docs/product/RELEASE-SLICES.md` | `skills/story-planning/templates/RELEASE-SLICES-TEMPLATE.md` |
| 后续 Backlog | `docs/product/BACKLOG.md` | `skills/story-planning/templates/BACKLOG-TEMPLATE.md` |

## 约束

- 不做技术方案、模块拆分或数据库设计；这些属于 `blueprint-design` / `hld-designer` / `implementation-design`。
- 不替代人类做最终优先级决策；需要取舍的范围项必须进入人工决策清单。
- 不删除 CP2 Deferred Ideas；只能转入 MVP、Backlog、Spike 候选或明确 N/A 原因。
- 所有 story 必须能回链到至少一个 use case、scenario 或 requirement。

## 验收标准

- [ ] `STORY-MAP.md` 中每个 story 有来源场景或需求引用。
- [ ] `MVP-SCOPE.md` 明确 In Scope、Out of Scope、Deferred 和成功指标。
- [ ] `RELEASE-SLICES.md` 的切片可按用户价值解释，不只是按代码工作量切分。
- [ ] `BACKLOG.md` 保留延后项来源、延后原因和重启条件。

## 不适用边界

- 需求还未结构化，或场景主体不清。
- 当前任务是实现某个已批准 Story。
- 当前任务只需要修复缺陷，不改变产品范围。

## Gotchas

- 把 story 写成“修改某文件 / 新增某函数”会污染产品规划边界。
- MVP 不能只按开发容量裁剪；必须说明裁剪后用户 outcome 是否仍成立。
- Deferred Ideas 如果不落入 backlog 或决策表，后续会变成不可追溯的范围漂移。
