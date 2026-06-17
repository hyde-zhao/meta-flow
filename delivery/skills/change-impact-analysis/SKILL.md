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

受理变更请求，创建标准化 `CR-*.md` 或 fast-lane 轻量变更记录，执行五维度影响分析，判定 `rollback_to`、审批要求与是否需要从 `fast-lane` 升级到 `standard`，并同步更新当前工作流状态。CR 关闭或 CP8 终验时若产生后续事项，维护 follow-up tracking 台账和 CR 跟踪索引；只有用户决定推进某一候选项时，才从台账转为正式 CR 文件。

## 适用场景

- 用户直接提出需求变更
- ISSUE 升级为结构性变更
- 执行反馈触发需求、设计或验证口径调整
- CP8 终验发现后续 CR 候选、Spike 候选、风险接受项、不授权范围或取消 / deferred 项，需要建立可追溯台账

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] `process/STATE.md` 已存在且当前阶段明确
- [ ] 变更原因和影响范围已提供，或可从 ISSUE / RUN-EXEC 推断

## 必须读取的输入

- `process/STATE.md`
- 当前变更描述
- 相关 ISSUE / RUN-EXEC / 上游文档（若存在）
- 受影响的正式对象（如 `REQUIREMENTS.md`、`HLD.md`、`DEVELOPMENT-PLAN.yaml` 等）

## 知识来源

- `skills/change-impact-analysis/templates/CR-TEMPLATE.md`：CR 结构基线
- `skills/change-impact-analysis/templates/FOLLOW-UP-TRACKING-TEMPLATE.md`：CP8 后续事项台账结构基线
- `skills/change-impact-analysis/templates/CR-INDEX-TEMPLATE.yaml`：CR 跟踪索引结构基线
- `meta-flow check cr-tracking`：`STATE.md.active_change`、正式 CR、follow-up 台账和 `CR-INDEX.yaml` 的一致性检查
- 当前工作流状态与正式文档：影响分析的事实来源
- `AGENTS.md`：阶段、门控与回退语义

## 执行步骤

1. 冻结当前推进动作，记录 `pending_action` 或等价待处理动作。
2. 生成新的 `CR-*.md` 编号并初始化模板。
3. 从需求层、场景层、计划层、安全层、交付层五个维度进行影响分析。
4. 对每个受影响正式文档填写“文档处理决策”：新增 / 原文档更新 / 归档 / 不变。
5. 若处理方式为“原文档更新”，必须写明旧基线保留方式，并要求目标文档追加 `## 修订记录`。
6. 若变更影响 Story、LLD、接口契约、文件所有权、`dev_gate` 或实现设计，必须列出 CR 影响范围内全部 Story，形成设计证据批次；批次内全部 full-lld / technical-note / waived 证据和 CP5 自动预检完成并统一人工确认前，不得实施任何 Story。
7. 若当前为 `workflow_mode=fast-lane`，先执行快速模式升级判定：命中架构、权限、安装路径、外部接口、文件所有权冲突、多 Story 依赖或不可逆迁移时，必须升级为 `standard`。
8. 给出 `impact_level`、`rollback_to`、`workflow_mode_after_change` 和审批结论。
9. 将活跃变更单写回状态对象，并明确后续收敛路径。
10. 若 CP8 或变更收敛阶段出现后续事项，只维护 `process/changes/CR-{id}-FOLLOW-UP-TRACKING-YYYY-MM-DD.md` 台账，并同步 `process/STATE.md.cr_tracking` 与 `process/changes/CR-INDEX.yaml`；不得预创建 `CR-020` 到 `CR-028` 这类尚未启动的正式 CR 文件。
11. 当用户决定推进某一候选项时，先执行 CR 冲突预检：读取台账、`STATE.md.active_change`、`STATE.md.cr_tracking`、`process/changes/CR-INDEX.yaml`、所有 `status=open|active|blocked` 的正式 CR，以及候选项的影响面。
12. 冲突预检必须比较：受影响正式文档、Story / LLD 批次、文件 owner、外部接口、权限 / 安全边界、运行授权、风险接受项和来源决策 ID。
13. `candidate` / `spike_candidate` 不占执行锁；转为正式 CR 后才允许把台账状态改为 `active`。若已有未完成 CR 且影响面重叠，默认不得并行推进，必须让用户在合并到现有 CR、保持候选等待、标记 `blocked`、拆分无冲突子集或标记 `superseded` 中选择。
14. 冲突预检通过后，再创建正式 `process/changes/CR-0xx-<slug>-YYYY-MM-DD.md`，并把台账中对应状态改为 `active`，链接正式 CR 文件，同时刷新 `STATE.md.cr_tracking` 与 `CR-INDEX.yaml`。
15. 正式 CR 创建后，台账只保留索引字段：状态、正式 CR 路径、当前门控、阻塞原因、下一步、相关 active CR / blocked_by / superseded_by；详细需求、影响分析和文档处理决策放入正式 CR 文件。
16. 正式 CR 关闭后回写台账状态为 `closed`，并同步 `STATE.md.cr_tracking`、`CR-INDEX.yaml` 和 CR frontmatter；候选项取消时写 `cancelled` 或 `superseded`，不得删除原行。
17. 每次新增台账、启动候选 CR、关闭 CR 或状态查询发现冲突后，若存在 `meta-flow check cr-tracking`，必须运行或记录跳过原因；发现 `STATE.md.active_change` 指向已关闭 CR、多个 active CR 未授权、台账 candidate 已有正式 CR 文件等问题时，先修正索引或发起人工决策。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 变更单 | `process/changes/CR-{id}.md` | `skills/change-impact-analysis/templates/CR-TEMPLATE.md` |
| 后续事项台账 | `process/changes/CR-{id}-FOLLOW-UP-TRACKING-YYYY-MM-DD.md` | `skills/change-impact-analysis/templates/FOLLOW-UP-TRACKING-TEMPLATE.md` |
| CR 跟踪索引 | `process/changes/CR-INDEX.yaml` | `skills/change-impact-analysis/templates/CR-INDEX-TEMPLATE.yaml` |

## 约束

- 必须先完成五维度分析，再允许修改正式对象
- 必须先完成文档处理决策，再允许修改 `USE-CASES.md`、`REQUIREMENTS.md` 或其他正式文档
- 影响 Story / LLD / 实现设计的 CR 必须先完成 CR 影响范围内全部设计证据的统一设计和 CP5 批次人工确认，不得逐个 Story 确认后逐个开发
- CR 编号递增，不复用
- `impact_level`、`rollback_to`、审批结论必须显式落地
- fast-lane 只允许低风险轻量实现；命中升级条件时必须切回 `standard`
- CR 必须统一复用 `skills/change-impact-analysis/templates/CR-TEMPLATE.md` 口径
- 后续 CR 候选只能先进入 follow-up tracking 台账，状态取值为 `candidate`、`active`、`blocked`、`spike_candidate`、`converted-to-spike`、`closed`、`cancelled`、`superseded`
- 台账不得承载长需求正文；正式 CR 创建后，台账只保留索引，不重复详细内容
- `process/changes/CR-INDEX.yaml` 或 `STATE.md.cr_tracking` 必须能机器读取 active / blocked / candidate / spike_candidate / stale_status_conflicts，不能只依赖 Markdown 正文归纳
- 新 CR 创建或候选 CR 转 active 前必须完成 CR 冲突预检；影响面重叠时不得静默并行推进
- `process/STATE.md.active_change` 非空时，新 CR 默认进入候选 / blocked 等待，除非冲突预检证明影响面完全不重叠且用户确认可并行
- 需求 / 场景变更默认采用增量更新；不得用新草案整体替换旧基线
- 旧需求或旧场景不得直接删除，至少保留为既有基线、历史需求 / 场景、被 CR 替换对象，或在 CR 中完整摘录并建立映射关系
- “废弃内容要彻底删除”只适用于已确认废弃的目录、路径变量、章节和实施步骤；不得用于删除仍需追溯的需求或场景基线

## 验收标准

- [ ] `CR-*.md` frontmatter 完整
- [ ] 五个维度均有明确结论
- [ ] 每个受影响正式文档均填写文档处理决策
- [ ] 原文档更新已说明旧基线保留方式，并要求目标文档包含 `## 修订记录`
- [ ] `rollback_to` 与审批结论已填写
- [ ] 若影响 Story / LLD / 实现设计，LLD 设计批次边界和批次确认门禁已填写
- [ ] 当前状态已记录活跃变更单
- [ ] CP8 后续事项已按关闭范围、不授权范围、风险接受项、后续 CR 候选项、取消 / deferred 项分流
- [ ] 后续 CR 候选只进入 follow-up tracking 台账，未预创建尚未启动的正式 CR 文件
- [ ] 候选 CR 转 active 或新 CR 创建前已完成冲突预检，并记录处理结论
- [ ] `STATE.md.cr_tracking` / `process/changes/CR-INDEX.yaml` 已同步 active、blocked、candidate、spike_candidate 和状态冲突
- [ ] `meta-flow check cr-tracking` 对当前台账和正式 CR 返回 PASS，或已记录需要人工处理的冲突

## 不适用边界

- 只是修正文案或拼写且不影响正式对象
- 当前请求只要求问题分类，不要求进入变更管理

## Gotchas

- 执行反馈驱动的变更经常同时影响验证和交付层，不能只分析需求层
- 若变更触发回退，不得跳过人工检查点直接继续下游阶段
- “修订”不是“重写最新真相源”：需求和场景文档必须优先保留可追溯基线，再追加或修改新内容
- CP8 后续事项不等于立即启动一组 CR；提前创建空 CR 会制造假进度和维护负担
- follow-up tracking 是 backlog，不是状态索引的替代品；缺少 `cr_tracking` / `CR-INDEX.yaml` 时，host-orchestrator 查询当前 CR 很容易只看见 active 正式 CR 而漏掉 candidate
