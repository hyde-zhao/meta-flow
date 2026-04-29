---
name: change-impact-analysis
description: >-
  当用户发起需求变更、ISSUE 升级为结构性变更、或执行反馈驱动的设计调整时使用。
  触发词包括：需求变更、修改需求、变更影响、发起变更、CR。
  适用场景：元工作流任意阶段的变更管理。
argument-hint: "变更原因、变更类型（add/modify/delete）、影响范围描述"
user-invokable: true
status: active
---

## 目标

受理变更请求，创建标准化 `CR-*.md`，执行五维度影响分析，判定 `rollback_to` 与审批要求，并同步更新当前工作流状态。

## 适用场景

- 用户直接提出需求变更
- ISSUE 升级为结构性变更
- 执行反馈触发需求、设计或验证口径调整

## 前置条件

- [ ] `process/STATE.md` 已存在且当前阶段明确
- [ ] 变更原因和影响范围已提供，或可从 ISSUE / RUN-EXEC 推断

## 必须读取的输入

- `process/STATE.md`
- 当前变更描述
- 相关 ISSUE / RUN-EXEC / 上游文档（若存在）
- 受影响的正式对象（如 `REQUIREMENTS.md`、`HLD.md`、`DEVELOPMENT-PLAN.yaml` 等）

## 知识来源

- `skills/change-impact-analysis/templates/CR-TEMPLATE.md`：CR 结构基线
- 当前工作流状态与正式文档：影响分析的事实来源
- `AGENTS.md`：阶段、门控与回退语义

## 执行步骤

1. 冻结当前推进动作，记录 `pending_action` 或等价待处理动作。
2. 生成新的 `CR-*.md` 编号并初始化模板。
3. 从需求层、场景层、计划层、安全层、交付层五个维度进行影响分析。
4. 对每个受影响正式文档填写“文档处理决策”：新增 / 原文档更新 / 归档 / 不变。
5. 若处理方式为“原文档更新”，必须写明旧基线保留方式，并要求目标文档追加 `## 修订记录`。
6. 给出 `impact_level`、`rollback_to` 和审批结论。
7. 将活跃变更单写回状态对象，并明确后续收敛路径。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 变更单 | `process/changes/CR-{id}.md` | `skills/change-impact-analysis/templates/CR-TEMPLATE.md` |

## 约束

- 必须先完成五维度分析，再允许修改正式对象
- 必须先完成文档处理决策，再允许修改 `USE-CASES.md`、`REQUIREMENTS.md` 或其他正式文档
- CR 编号递增，不复用
- `impact_level`、`rollback_to`、审批结论必须显式落地
- CR 必须统一复用 `skills/change-impact-analysis/templates/CR-TEMPLATE.md` 口径
- 需求 / 场景变更默认采用增量更新；不得用新草案整体替换旧基线
- 旧需求或旧场景不得直接删除，至少保留为既有基线、历史需求 / 场景、被 CR 替换对象，或在 CR 中完整摘录并建立映射关系
- “废弃内容要彻底删除”只适用于已确认废弃的目录、路径变量、章节和实施步骤；不得用于删除仍需追溯的需求或场景基线

## 验收标准

- [ ] `CR-*.md` frontmatter 完整
- [ ] 五个维度均有明确结论
- [ ] 每个受影响正式文档均填写文档处理决策
- [ ] 原文档更新已说明旧基线保留方式，并要求目标文档包含 `## 修订记录`
- [ ] `rollback_to` 与审批结论已填写
- [ ] 当前状态已记录活跃变更单

## 不适用边界

- 只是修正文案或拼写且不影响正式对象
- 当前请求只要求问题分类，不要求进入变更管理

## Gotchas

- 执行反馈驱动的变更经常同时影响验证和交付层，不能只分析需求层
- 若变更触发回退，不得跳过人工检查点直接继续下游阶段
- “修订”不是“重写最新真相源”：需求和场景文档必须优先保留可追溯基线，再追加或修改新内容
