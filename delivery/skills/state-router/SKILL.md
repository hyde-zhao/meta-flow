---
name: state-router
description: >-
  当需要推进工作流状态、回退到上一阶段、查询当前进度、或判断下一步应调用哪个 Agent 时使用。
  触发词包括：推进、下一步、当前状态、回退、状态查询、继续。
  适用场景：元工作流全流程的状态管理。
argument-hint: "可选：指定目标阶段、查询字段或回退原因"
user-invokable: true
status: active
---

## 目标

读取并更新 `process/STATE.md`，根据当前阶段的退出条件判断是否可推进、是否需要回退、下一步应唤醒哪个 Agent，并保持状态机与 `skills/state-router/templates/STATE-TEMPLATE.md` 一致。

## 适用场景

- 元工作流阶段推进、阶段回退、状态查询
- `meta-po` 在每个阶段完成后进行退出条件判定
- Story 执行阶段内的 LLD 设计批次、开发队列、验证队列和依赖门控判断
- `requirement-clarification` / `solution-design` 阶段内的用户交互权委托状态判断
- 并行 LLD 写作期间的 `lld_clarification_queue` 收敛检查
- CP2 / CP3 / CP5 / CP8 前的 `human_gate_decisions.pending_human_decisions[]` 状态队列维护
- CP2 / CP3 / CP5 / CP6 / CP7 / CP8 前后的 `context_budget`、`process/context/*-CONTEXT.yaml` 和全文档读取理由维护
- `workflow_health` 循环 / 卡顿 / 反复回修信号维护
- CP0-CP8 检查点状态、自动检查结果路径和人工审查结果路径维护
- CR 跟踪状态查询：汇总 active / blocked 正式 CR、follow-up candidate、spike_candidate 和状态冲突
- `standard` / `fast-lane` 工作流模式、关键决策门控和同工作流自动子 agent 调度状态维护

## 前置条件

- [ ] `process/STATE.md` 已存在，或允许由 `skills/state-router/templates/STATE-TEMPLATE.md` 初始化
- [ ] 当前阶段相关产物的存在性和确认状态可被检查

## 必须读取的输入

- `process/STATE.md`（若已存在）
- `skills/state-router/templates/STATE-TEMPLATE.md`
- `skills/checkpoint-manager/SKILL.md`
- `scripts/check_cr_tracking_consistency.py`（若存在）：CR 台账、正式 CR 和 `STATE.md.active_change` 一致性预检
- `process/context/*-CONTEXT.yaml`：当前阶段上下文胶囊；默认优先读取
- 与当前阶段直接相关的上游文档（仅在 capsule 缺失、冲突、字段不足、人工审计或深度评审触发时读取全文）：
  - `process/REQUEST.md`
  - `docs/product/USE-CASES.md`
  - `docs/product/REQUIREMENTS.md`
  - `docs/product/SCENARIOS.yaml`
  - `docs/product/TEST-MATRIX.md`
  - `docs/product/STORY-MAP.md`
  - `docs/product/MVP-SCOPE.md`
  - `docs/product/RELEASE-SLICES.md`
  - `docs/product/BACKLOG.md`
  - `docs/design/BLUEPRINT.md`
  - `docs/design/DOMAIN-MAP.md`
  - `docs/design/DEPENDENCY-MAP.md`
  - `docs/design/HLD.md`
  - `docs/design/ARCHITECTURE-DECISION.md`
  - `process/STORY-BACKLOG.md`
  - `process/DEVELOPMENT-PLAN.yaml`
  - `docs/features/<feature>/DESIGN.md`
  - `docs/features/<feature>/TEST-PLAN.md`
  - `docs/features/<feature>/TASKS.md`
  - `docs/quality/TEST-STRATEGY.md`
  - `docs/quality/TEST-REPORT.md`
  - `docs/quality/REVIEW.md`
  - `docs/quality/FIXES.md`
  - `docs/release/RELEASE-NOTES.md`
  - `docs/release/DEPLOY-CHECKLIST.md`
  - `docs/release/ROLLBACK.md`
  - `docs/release/MIGRATION.md`
  - `docs/release/FEEDBACK.md`
  - `process/release/RELEASE-CONTEXT.yaml`
  - `README.md`
  - `USER-MANUAL.md`
- Story 执行阶段需要读取 `process/stories/STORY-*.md`、`process/stories/STORY-*-LLD.md`、`process/stories/STORY-*-IMPLEMENTATION.md` 与 `process/STORY-STATUS.md`

## 知识来源

- `skills/state-router/templates/STATE-TEMPLATE.md`：状态对象结构与阶段机基线
- `AGENTS.md` / `rules/AGENTS.md`：阶段定义、人工检查点与角色职责
- 各阶段产物 frontmatter 与文件存在性：退出条件的事实来源
- `process/changes/CR-INDEX.yaml` 与 `process/changes/CR-*-FOLLOW-UP-TRACKING-*.md`：CR 跟踪索引和后续候选台账
- `context-manifest-builder`：阶段上下文胶囊和最终上下文清单契约；capsule 是默认读取入口，不替代正式产物
- `scenario-expansion` / `story-planning` / `blueprint-design` / `implementation-design` / `implementation-execution` / `verification-execution` / `quality-review` / `release-readiness`：软件开发工作流新增产物契约；模板存在不代表运行态产物已完成

## 执行步骤

### 1. 初始化或读取状态

1. 若 `process/STATE.md` 不存在，则以 `skills/state-router/templates/STATE-TEMPLATE.md` 初始化。
2. 读取 `workflow_mode`、`fast_lane_reason`、`current_phase`、`current_agent`、`blocked`、`active_change`、`orchestrator_session`、`delegated_interaction`、`agent_lifecycle`、`checkpoints`、`parallel_execution`、`human_gate_decisions`、`cr_tracking`、`decision_briefs`、`discussion_checkpoints`、`history`。
3. 若 `blocked=true`，先返回阻塞原因，不允许静默推进。
4. 若旧 `STATE.md` 的 `checkpoints` 仍是“需求/HLD/Story/终验”旧布尔结构，必须先迁移为 CP0-CP8 结构；迁移动作写入 `history`，不得把旧布尔值当作新检查点已通过。
5. 若 `agent_lifecycle.platform_capabilities.subagent_dispatch` 缺失，必须先补齐并将 `available=false`、`method=unverified` 写入状态；能力未探测前，不得把需要功能 Agent 的任务标记为 `completed`。
6. 若 `orchestrator_session` 缺失，必须先按模板补齐并写入 `history`；补齐动作只表示状态结构升级，不表示允许重复启动 `meta-po`。
7. 若用户启动正式工作流且未显式禁用自动调度，`orchestrator_session.subagent_auto_dispatch` 默认为 `enabled`；该授权只覆盖真实子 agent 调度，不覆盖 inline fallback。
8. 若 `discussion_checkpoints` 缺失，必须按模板补齐 CP2 / CP3 discussion log 和 checkpoint 路径；补齐路径不代表讨论已完成。
9. 若 `delegated_interaction` 缺失，必须按模板补齐，默认 `status=none`；补齐不代表已经委托成功。
10. 若 `parallel_execution.lld_clarification_queue` 缺失，必须按模板补齐，默认 `status=idle`、`items=[]`；补齐不代表问题已收敛。
11. 若 `human_gate_decisions` 缺失，必须按模板补齐，默认 `status=idle`、`pending_human_decisions=[]`；补齐不代表当前没有待决策项，发起人工门禁前仍必须从正式产物重新聚合。
12. 若 `cr_tracking` 缺失，必须按模板补齐，默认 `status=not-indexed`、`active_crs=[]`、`blocked_crs=[]`、`follow_up_candidates=[]`、`spike_candidates=[]`、`stale_status_conflicts=[]`；补齐不代表当前没有后续候选 CR，状态查询前仍必须读取台账和正式 CR 文件。
13. 若 `context_budget` 缺失，必须按模板补齐，默认 `require_capsule_first=true`；补齐不代表 capsule 已生成。CP2 / CP3 / CP5 / CP6 / CP7 / CP8 前必须检查对应 `process/context/*-CONTEXT.yaml` 的存在性、状态和 `read_profile`。
14. 若 `workflow_health` 缺失，必须按模板补齐，默认 `status=healthy` 和计数器为 0；每次推进、回退、重试、用户问题重复、CP 失败或 Story 回修时刷新对应计数器。

### 1.1 Context Capsule 与读取预算

state-router 必须把 `context_budget` 当成阶段推进和子 agent 调度的前置状态，而不是文档建议。

| 阶段 / 门禁 | capsule 路径 | 触发时机 | 缺失处理 |
|---|---|---|---|
| CP2 | `process/context/CP2-REQUIREMENT-CONTEXT.yaml` | CP2 自动预检前、meta-pm 交还后、发起 CP2 人工门禁前 | 自动生成或记录 `waived` 理由；缺少且无理由时 CP2 为 `BLOCKED` |
| CP3 | `process/context/CP3-DESIGN-CONTEXT.yaml` | HLD 草案收敛后、CP3 自动预检前 | 自动生成或记录 `waived` 理由；缺少且无理由时 CP3 为 `BLOCKED` |
| CP5 | `process/context/CP5-LLD-CONTEXT.yaml` | 全部 Story 设计证据和 CP4 自动预检完成后 | 自动生成或记录 `waived` 理由；缺少且无理由时不得发起 CP5 |
| CP6 | `process/context/CP6-IMPLEMENTATION-CONTEXT.yaml` | Wave / Story 开发启动前和 CP6 写入前 | 缺少时允许生成最小 Story capsule；不得默认读取全量 LLD 批次 |
| CP7 | `process/context/CP7-VERIFICATION-CONTEXT.yaml` | Story 进入验证前 | 缺少时允许生成验证 capsule；不得默认读取所有历史验证轮次 |
| CP8 | `process/context/CP8-DELIVERY-CONTEXT.yaml` | release context 生成后、CP8 发起前 | 缺少时 CP8 自动预检必须记录 `FAIL` / `BLOCKED` 或明确 `WAIVED` |

规则：

1. 子 agent handoff 必须优先传 capsule 路径和 `context_policy`，不得默认传完整正式文档列表。
2. 若必须读取完整正式文档，必须写入 `context_budget.read_expansion_log[]`，字段至少包含 `at/actor/phase/capsule_path/expanded_to/reason`。
3. `read_profile=minimal` 只允许当前 Story / Feature / Gate 的必读文件；`compact` 允许阶段摘要和关键检查点；`full` 只能用于人工审计、深度评审、冲突排查或用户明确要求。
4. capsule 缺失但下游继续推进时，必须在对应 CP 自动检查中写明 `N/A` / `WAIVED` / `BLOCKED` 原因；不得静默降级为全文档读取。

### 1.2 Workflow Health 失败模式阈值

state-router 每次推进前必须刷新 `workflow_health`：

| 信号 | 计数器 | 默认阈值 | 超限动作 |
|---|---|---:|---|
| 同一问题重复追问 | `same_question_rounds` | 2 | 生成决策项或要求人工仲裁，不再继续追问 |
| HLD 反复修订无新增事实 | `hld_revision_rounds` | 3 | 阻断 CP3，发起架构决策 |
| LLD clarification 队列过大 | `lld_clarification_items` | 8 | 暂停 LLD 并由 meta-po 合并问题批量询问 |
| 同一 CP 重试失败 | `cp_retry_count` | 2 | 路由到责任 Agent 或人工仲裁 |
| 同一 Story 回修次数过多 | `story_rework_count` | 2 | 升级为设计澄清或 CR |
| 产物 hash 连续不变但仍重写 | `unchanged_artifact_hash_rounds` | 2 | 停止重写，要求明确新事实或决策 |
| 阶段轮次过长 | `phase_elapsed_rounds` | 6 | 输出卡顿摘要和下一步决策 |

任一计数器超过阈值时，`workflow_health.status` 必须变为 `stalled`、`blocked` 或 `requires-human-arbitration`，并把下一步写成决策项；不得继续静默重试消耗 token。

### 2. 按阶段检查退出条件

| 当前阶段 | 退出条件 | 下一阶段 | 默认唤醒 Agent |
|---|---|---|---|
| `init` | `process/checks/CP0-REQUEST-INTAKE.md` 结论为 `PASS` 或 `WAIVED` | `requirement-clarification` | `meta-pm` |
| `requirement-clarification` | 阶段委托已交还，CP1 自动检查通过，CP2 自动预检通过且 `process/checkpoints/CP2-REQUIREMENTS-BASELINE.md` 人工结论为 `approved`；`docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/product/STORY-MAP.md`、`docs/product/MVP-SCOPE.md` 存在，或 CP2 自动检查逐项写明 `N/A` / `WAIVED` 原因 | `solution-design` | `meta-se` |
| `solution-design` | 阶段委托已交还，CP3 自动预检通过且 `process/checkpoints/CP3-HLD-REVIEW.md` 人工结论为 `approved`；`docs/design/BLUEPRINT.md`、`docs/design/DOMAIN-MAP.md`、`docs/design/DEPENDENCY-MAP.md` 已生成并被 HLD 消费，`docs/design/ARCHITECTURE-DECISION.md` 的核心 ADR 已确认，或 CP3 自动检查逐项写明 `N/A` / `WAIVED` 原因 | `story-planning` | `meta-se` |
| `story-planning` | `docs/design/FEATURE-DESIGN-MATRIX.md` 已生成，required Feature 设计已生成或 waived，CP4 自动预检通过，`lld_clarification_queue` 无未回答阻断项，全部目标 Story 的完整 LLD / 技术说明 / waived 证据通过 CP5 自动预检且 `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` 人工结论为 `approved` | `story-execution` | `meta-dev` |
| `story-execution` | 全部目标 Story 均通过 CP6、CP7，并到达 `verified` 或 `verified-with-risk`，且 CP6 包含实现执行证据路径 / N/A 原因，CP6/CP7 包含 Agent Dispatch Evidence；CP7 通过 `verification-execution` 产出 `docs/quality/VERIFICATION-REPORT.md` 或等价摘要，包含验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划和合法阶段决策；`TEST-MATRIX.md` 可追溯到 `VERIFICATION-REPORT.md` / `TEST-REPORT.md` / `REVIEW.md`，或 CP7 写明 `N/A` / `WAIVED` 原因 | `documentation` | `meta-dev` / `meta-qa` / `meta-doc` |
| `documentation` | CP8 自动预检通过且 `process/checkpoints/CP8-DELIVERY-READINESS.md` 人工结论为 `approved`；`process/release/RELEASE-CONTEXT.yaml` 已生成且 `release_artifact_profile=minimal|compact|full`、`release_decision=READY|READY_WITH_RISK`；`NOT_READY` 不得发起人工终验；`RELEASED` / `FAILED` 只能在独立真实发布授权后写入；`docs/release/RELEASE-NOTES.md`、`docs/release/DEPLOY-CHECKLIST.md`、`docs/release/ROLLBACK.md`、`docs/release/MIGRATION.md`、`docs/release/FEEDBACK.md` 已按 profile 生成或 CP8 写明 `N/A` / `WAIVED` 原因；CP8 后续事项已按关闭范围 / 不授权范围 / 风险接受项 / 后续 CR 候选项 / 取消或 deferred 项分流，必要时 `human_gate_decisions.follow_up_tracking_path` 可读 | `delivered` | `meta-po` |
| `delivered` | 只读归档 | — | — |

推进时只允许读取检查点结果文件和 `STATE.md.checkpoints` 的同步状态；若两者冲突，以检查点结果文件为准，并把冲突写入 `history`。

### 2.1 阶段委托交互检查

`delegated_interaction` 只描述阶段内谁直接与用户沟通，不改变正式门控归属。

| 阶段 | 合法委托 | 推进要求 |
|---|---|---|
| `requirement-clarification` | `agent_role=meta-pm` | CP2 人工确认前，若 `status=delegated|active|awaiting-user`，不得由 meta-po 代写需求或发起 CP2；必须把用户输入转交给该 meta-pm。只有 `status=returned` 且 `return_summary_path` 可读，才允许生成 CP2 Decision Brief。 |
| `solution-design` | `agent_role=meta-se` | CP3 人工确认前，若 `status=delegated|active|awaiting-user`，不得由 meta-po 代写 HLD 或发起 CP3；必须把用户输入转交给该 meta-se。只有 `status=returned` 且 `return_summary_path` 可读，才允许生成 CP3 Decision Brief。 |
| 其他阶段 | 空或 `status=none|returned|closed` | 不得保留活跃阶段委托；若仍为 active，先收敛或标记 blocked。 |

若用户在 `meta-po` 线程中发送内容，而 `delegated_interaction.status` 表示活跃委托，state-router 必须返回“转交委托 Agent”的下一步建议，而不是推进阶段。

### 2.2 当前状态 / CR 盘点查询

当用户询问“当前状态”“还有哪些 CR 需要推进”“建议如何推进”“待跟踪 CR”等问题时，state-router 不得只返回 `STATE.md.active_change` 或唯一 `status=active` 的正式 CR；必须生成 CR 盘点视图：

1. 读取 `process/STATE.md.active_change`、`STATE.md.orchestrator_session.active_change`、`STATE.md.cr_tracking`、`process/changes/CR-INDEX.yaml`（若存在）、全部 `process/changes/CR-*.md` 正式 CR 和全部 `process/changes/CR-*-FOLLOW-UP-TRACKING-*.md` 台账。
2. 若存在 `scripts/check_cr_tracking_consistency.py`，运行或要求运行该脚本检查 `--project-root .`；若无法运行，必须在回答中说明跳过原因。
3. 输出必须固定分为五类：`active formal CR`、`blocked formal CR`、`follow-up candidate`、`spike_candidate`、`stale_status_conflicts`。
4. `candidate` / `spike_candidate` 是 backlog，不占执行锁，但必须在“还有哪些 CR 需要推进”回答中列出标题、优先级、阻塞前置、下一步和不授权边界。
5. 若 `STATE.md.active_change` 指向已关闭 CR，或与正式 `status=active` 的 CR 不一致，必须先列为 `stale_status_conflicts`；不得因为状态冲突而隐藏 follow-up 台账候选项。
6. 若存在独立 active CR（例如未占用 follow-up 候选编号的临时 CR），必须要求其在台账或 `CR-INDEX.yaml` 中建立 `related_active_cr`、`blocked_by`、`superseded_by` 或等价关系，否则列为同步缺口。
7. 推进建议必须先收敛 active / blocked 正式 CR，再说明哪些 candidate 可启动、哪些必须等待前置 CR、哪些只适合 Spike。

### 3. 处理回退

1. 记录回退原因与目标阶段。
2. 将回退动作写入 `history`。
3. 只回退到最近仍可恢复的稳定阶段，不跨越未收敛变更单。

### 3.1 后续 CR 启动与冲突预检

当用户请求从 follow-up tracking 台账启动候选 CR 时，state-router 必须先做冲突预检，再允许 `change-impact-analysis` 创建正式 CR：

1. 读取台账路径、候选编号、`STATE.md.active_change`、`STATE.md.cr_tracking`、`process/changes/CR-INDEX.yaml`（若存在）和所有未关闭 `process/changes/CR-*.md`。
2. `candidate` / `spike_candidate` 不占执行锁；`active` / `blocked` 的正式 CR 视为未完成。
3. 比较受影响正式文档、Story / LLD 批次、文件 owner、外部接口、权限 / 安全边界、运行授权、风险接受项和来源决策 ID。
4. 若无重叠，允许创建正式 CR，并把台账状态和 `cr_tracking` / `CR-INDEX.yaml` 改为 `active`。
5. 若存在重叠，返回 `blocked` 下一步，不得静默并行推进；meta-po 必须发起人工决策，选项包括合并到现有 CR、保持候选等待、标记 `blocked`、拆分无冲突子集或 `superseded`。

### 4. 回写状态

1. 更新 `current_phase`、`current_agent`、`last_action`、`next_action`、`last_updated`。
2. 推进或回退时追加 `history` 记录。
3. 同步 `checkpoints.<cp_id>.status`、`last_result`、`auto_result`、`manual_review` 或滚动 `results[]`。
4. 查询状态时不改变业务内容，但允许刷新 `next_action`。

### 4.1 检查点结果同步

每次推进前必须按 `checkpoint-manager` 契约读取检查点结果：

| 检查点 | 必读文件 | 通过条件 |
|---|---|---|
| CP0 | `process/checks/CP0-REQUEST-INTAKE.md` | 结论为 `PASS` 或 `WAIVED` |
| CP1 | `process/checks/CP1-USE-CASE-COMPLETENESS.md` | 结论为 `PASS` 或 `WAIVED` |
| CP2 | `process/checks/CP2-REQUIREMENTS-BASELINE.md` + `process/checkpoints/CP2-REQUIREMENTS-BASELINE.md` | 自动预检通过且人工结论 `approved`；`docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/product/STORY-MAP.md`、`docs/product/MVP-SCOPE.md` 存在或自动检查逐项写明 `N/A` / `WAIVED` |
| CP3 | `process/checks/CP3-HLD-CONSISTENCY.md` + `process/checkpoints/CP3-HLD-REVIEW.md` | 自动预检通过且人工结论 `approved`；蓝图适用性已判定，`docs/design/BLUEPRINT.md`、`docs/design/DOMAIN-MAP.md`、`docs/design/DEPENDENCY-MAP.md` 已被 HLD 消费或自动检查逐项写明 `N/A` / `WAIVED`；`docs/design/ARCHITECTURE-DECISION.md` 的核心 ADR 已用推荐 / 备选 / 优劣 / 影响风险 / 回退条件确认 |
| CP4 | `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md` | 自动预检通过；`docs/design/FEATURE-DESIGN-MATRIX.md`、required Feature 设计、Story `feature_design_refs` / `lld_policy`、结果、风险和开放项汇入 CP5 Decision Brief |
| CP5 | 全部目标 Story 的 `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md` + `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` | 全部目标 Story 的完整 LLD / 技术说明 / waived 证据自动预检通过且全量人工结论 `approved` |
| CP6 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` | 当前 Story 结论为 `PASS` 或 `WAIVED`，meta-dev 调度证据通过，且实现执行证据完整：复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / 护栏 / 平台适配 / 发布相关 Story 必须有 `process/stories/STORY-{id}-{story_slug}-IMPLEMENTATION.md` 或 `docs/features/<feature>/IMPLEMENTATION.md`；低风险 Story 至少在 Story 卡片或 DEV-LOG 中记录实现对象清单、设计契约映射、测试 / Fixture 计划、最小实现切片、本地验证与 N/A 理由 |
| CP7 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` | 当前 Story 结论为 `PASS`、`PASS_WITH_RISK` 或 `WAIVED` 时可进入已验证状态；`NEEDS_REWORK` 必须回 meta-dev；`NEEDS_DESIGN_CLARIFICATION` 必须回 meta-se / meta-po；`BLOCKED` 停止推进；meta-qa 调度证据通过；`verification-execution` 已输出 `docs/quality/VERIFICATION-REPORT.md` 或 Feature scoped 等价证据；验证对象清单、验证追踪矩阵、设计契约验证和分层验证计划完整；`TEST-MATRIX.md` 覆盖项已回链到 `VERIFICATION-REPORT.md` / `TEST-REPORT.md` / `REVIEW.md` 或检查结果写明 `N/A` / `WAIVED` |
| CP8 | `process/checks/CP8-DELIVERY-READINESS.md` + `process/checkpoints/CP8-DELIVERY-READINESS.md` | 自动预检通过且人工结论 `approved`；`process/release/RELEASE-CONTEXT.yaml` 可读，且 `release_artifact_profile=minimal|compact|full`、`release_decision=READY|READY_WITH_RISK`；`READY_WITH_RISK` 的风险已进入 Decision Brief / risk acceptance；`docs/release/RELEASE-NOTES.md`、`docs/release/DEPLOY-CHECKLIST.md`、`docs/release/ROLLBACK.md`、`docs/release/MIGRATION.md`、`docs/release/FEEDBACK.md` 已按 profile 生成或自动检查写明 `N/A` / `WAIVED`；若存在 CP8 后续事项，follow-up tracking 台账可读且无未分类项 |

CP2 / CP3 / CP5 / CP8 人工检查点文件缺失、未填“人工审查结果”或结论不是 `approved` 时，不得推进。CP4 不再要求独立人工审查稿。

CP2 推进前必须确认 `discussion_checkpoints.cp2_scenario_discussion` 指向的 log / checkpoint 已存在，或 CP2 自动检查明确写明 N/A / blocked 原因；同时确认 `SCENARIOS.yaml`、`TEST-MATRIX.md`、`STORY-MAP.md`、`MVP-SCOPE.md` 的存在性或逐项 N/A / WAIVED 证据。CP3 推进前同理检查 `discussion_checkpoints.cp3_hld_discussion`，并确认蓝图适用性判定、`BLUEPRINT.md` / `DOMAIN-MAP.md` / `DEPENDENCY-MAP.md` 的存在性或逐项 N/A / WAIVED 证据；核心 ADR 必须在 CP3 Decision Brief 中以关键决策项形式确认，包含推荐、备选、优劣、影响 / 风险和回退 / 切换条件；不得只看 `HLD.md confirmed=true`。

CP2 / CP3 / CP5 / CP8 发起前必须额外确认 `human_gate_decisions`：

- 所有 `Q-*`、`OPEN`、`LCQ-*`、`O-*`、权限 / 安全边界、风险接受、运行授权、外部接口、数据写入、publish、live / 交易类事项已分类为 `resolved-by-user`、`decision-item`、`non-blocking-open`、`converted-to-spike` 或 `n/a-with-reason`。
- `decision-item` 均已写入 `pending_human_decisions[]`，并含 `id/gate/decision_type/question/recommendation/alternatives/pros_cons/impact_risk/rollback_switch/status/source`。
- `decision_collection_coverage[]` 已记录本轮 gate 的来源扫描覆盖，包含每个适用来源的 `source_type/source_path/scan_status/candidate_count/included_decision_count/classification_or_na_reason`。
- 本轮 `pending_human_decisions[]` 与 `process/checkpoints/CP*.md` 的 Decision Brief 决策表一致；若不一致，不得把 `orchestrator_session.status` 置为 `awaiting-user`。
- 门禁消息草稿通过 `scripts/check_human_gate_decision_brief.py --launch-message-file` 校验后，才能发起人工确认。
- 若用户修订了范围、安全、运行授权或风险接受含义，必须把相关 DQ 退回 `open`，重新生成 Decision Brief 和发起消息。

### 5. Story 并行调度队列

story-planning 和 story-execution 阶段必须维护 `parallel_execution`。标准开发时，`lld_design_batch` 必须覆盖全部目标 Story，但每个 Story 的设计证据按 `lld_policy.required_level` 分为 `full-lld`、`technical-note`、`waived`，并在 story-planning 内完成全量 CP5 确认；CR 触发时，`lld_design_batch` 默认等于 CR 影响范围内全部受影响 Story。Wave 只用于进入 story-execution 后的开发/验证调度。

1. `lld_design_batch`：本轮必须先完成设计证据的 Story 集合；标准开发使用 `batch_id=all-stories`、`source=all-stories` 并列出全部目标 Story，CR 使用 `source=change` 并列出全部受影响 Story；每项必须含 `story_id`、`design_evidence_type=full-lld|technical-note|waived`、`evidence_path`、`lld_policy_required_level`。
2. `lld_ready`：全量设计证据批次内 Story 边界稳定、HLD/ADR/FEATURE-DESIGN-MATRIX 已确认、Feature 设计输入满足且没有 design_evidence_confirmed=true。
3. `lld_running`：正在写 LLD 的 Story，数量不得超过 `max_parallel_lld`。
4. `lld_review`：完整 LLD / 技术说明 / waived 证据已输出，等待全部目标 Story 完成设计证据与 CP5 自动预检；不得因单个 Story 或单个 Wave 已就绪就进入开发。
5. `lld_batch_review`：全部目标 Story 均已输出设计证据和 CP5 自动预检，等待 `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` 人工确认。
6. `lld_clarification_queue`：并行 LLD 期间由 meta-dev 写入的实现灰区队列。字段至少包含 `status`、`active_question_batch`、`items[]`；每个 item 至少包含 `id`、`story_id`、`owner_agent`、`question`、`options`、`recommendation`、`impact_surface`、`blocks_lld`、`answer`、`status`。
7. `dev_ready`：进入 story-execution 后，全量 CP5 人工确认 approved，当前 Story 所在 Wave 可执行，当前 Story design_evidence_confirmed=true，`dev_gate` 满足，且 `file_ownership.primary` 不与 `dev_running` 冲突。
8. `dev_running`：正在实现的 Story，数量不得超过 `max_parallel_dev`。
9. `verify_ready`：开发完成并进入 `ready-for-verification` 的 Story；CP6 已记录实现执行证据路径、证据类型、实现对象清单、设计契约映射、测试 / Fixture 计划、切片验证结果和平台差异检查结论，或写明低风险 N/A 理由。
10. `verify_running`：正在验证的 Story，数量不得超过 `max_parallel_qa`。
11. `verified_with_risk`：CP7 结论为 `PASS_WITH_RISK` 的 Story；可进入后续阶段，但剩余风险必须汇入 CP8 Decision Brief / risk acceptance 输入。
12. `needs_rework`：CP7 结论为 `NEEDS_REWORK` 的 Story；必须路由回 meta-dev，复修后重新 CP6 / CP7。
13. `needs_design_clarification`：CP7 结论为 `NEEDS_DESIGN_CLARIFICATION` 的 Story；必须路由回 meta-se / meta-po，必要时重开 CP5 或 CR。
14. `blocked_by_dependency`：依赖类型、上游状态、批次边界或文件所有权阻塞的 Story，必须写明 `blocked_by`、`dependency_type`、`required_status` 或 `conflict_files`。

CP5 发起前必须额外检查 `lld_clarification_queue`：

- `status=awaiting-user|batching|blocked` 时不得发起 CP5。
- 任一 item 满足 `blocks_lld=true` 且 `status` 不是 `answered|resolved|converted-to-spike|waived` 时，不得发起 CP5。
- 非阻断 OPEN / Spike 可进入 CP5，但必须在 `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` 的 Decision Brief 中暴露其影响、owner、重访条件和是否影响跨 Story 契约。
- 用户回答后，meta-po 必须把答案写回 item 的 `answer/status`，再通过 `resume_agent` 或 `send_input` 分发给对应 `owner_agent`。

依赖门控规则：

| 依赖类型 | LLD 队列规则 | 开发队列规则 |
|---|---|---|
| `contract` | 上游接口在 Story 或 LLD 中声明即可进入 LLD | 上游接口冻结且当前 LLD confirmed=true |
| `runtime` | 可进入 LLD，但必须记录运行时风险 | 默认要求上游 `verified` |
| `file-conflict` | 可进入 LLD，但必须记录合并顺序 | 不得与冲突 Story 并行开发 |

### 6. Agent 生命周期登记

Codex 多 agent 模式下，state-router 必须维护 `agent_lifecycle.active_agents`：

1. 新 agent 启动前，按 `role + workflow_id + change_id + story_id + wave_id` 精确查找可复用线程；批次级确认按 `role + workflow_id + change_id + batch_id` 追踪。
2. 命中可复用线程时返回 resume / send_input 建议，不允许重复 spawn。
3. 关键人工检查点通过、Story LLD 确认完成、实现交接验证、验证报告交付或文档终验完成后，标记对应线程 `status=closing` 并提示 meta-po close。
4. `meta-po` 角色始终单例；若发现 2 个活动 `meta-po`，必须阻断推进并要求人工选择保留线程。
5. `active_agents` 失活或用户手动关闭时，必须在 `history` 记录重建原因，不能静默生成新线程。
6. 若旧 `STATE.md` 缺少 `agent_lifecycle`，必须先按模板补齐结构；补齐本身不代表允许新建 `meta-po`，仍需确认当前 UI 中没有其他活动 `meta-po`。

### 6.1 Orchestrator Session 登记

`meta-po` 自身生命周期必须登记在 `orchestrator_session`，不得只依赖 `active_agents[]` 的功能 Agent 记录。

| 字段 | 说明 |
|---|---|
| `role` | 固定为 `meta-po` |
| `agent_id` / `thread_id` | 当前唯一编排器的 Codex agent id / thread id；平台没有独立 thread 时可与 `agent_id` 相同 |
| `status` | `active`、`awaiting-user`、`resuming`、`closed`、`superseded`、`unavailable` |
| `workflow_id` / `active_change` | 当前工作流与活跃变更键 |
| `pending_gate` | 等待人工确认的检查点，例如 `CP8` |
| `pending_checklist_path` | 已提示给用户的人工审查稿路径 |
| `pending_user_decision` | 允许的用户输入与当前等待事项，例如 `approve`、`修改: ...`、`reject`；`1/通过`、`2/修改: ...`、`3/不通过` 仅作历史兼容别名 |
| `pending_decision_ids` | 本轮发起消息中实际展示给用户的 DQ ID；必须与 Decision Brief 和 `human_gate_decisions.pending_human_decisions[]` 一致 |
| `pending_non_authorized_items` | 本轮 approve 不代表授权的事项，尤其是真实运行、凭据、外部接口、数据写入、publish、live / 交易类操作 |
| `resume_instruction` | 用户回复后应优先使用 `resume_agent` / `send_input` 继续同一 `meta-po` 的说明 |
| `subagent_auto_dispatch` | `enabled` / `disabled`；同工作流真实子 agent 调度授权状态 |
| `spawned_at` / `last_seen_at` / `awaiting_since` / `resumed_at` / `closed_at` | 编排器生命周期时间 |
| `previous_agent_id` / `previous_thread_id` | recovery 模式下被替代的旧编排器标识 |
| `superseded_by` | recovery 模式下替代当前编排器的新 agent id / thread id |
| `recovery_reason` | 仅当旧 `meta-po` 不可 resume、已关闭、用户手动终止或平台标识不可用时填写 |

规则：

1. 发起 CP2 / CP3 / CP5 / CP8 关键人工检查点时，必须将 `status=awaiting-user`，并写入 `pending_gate`、`pending_checklist_path`、`pending_user_decision`、`pending_decision_ids`、`pending_non_authorized_items`、`resume_instruction` 和 `awaiting_since`。
2. 用户确认、修改或拒绝后，必须优先复用 `orchestrator_session.agent_id` / `thread_id`，通过 `resume_agent` 或 `send_input` 恢复同一 `meta-po`；不得把“需要重新读取文件事实”作为新建 `meta-po` 的理由。
3. 回填人工结果、关闭 CR、推进阶段或推进 `delivered` 前，必须重新读取 `STATE.md`、对应 `process/checks/CP*.md`、`process/checkpoints/CP*.md`、活跃 `CR-*.md` 和下游输出，并把结果写入 `history`。
4. 只有旧 `meta-po` 不可恢复时，才允许创建新的 recovery `meta-po`；必须将旧 session 标为 `superseded` 或 `closed`，记录 `previous_agent_id`、`previous_thread_id`、`superseded_by`、`recovery_reason` 和 `history`。
5. 若同时发现两个 `status=active|awaiting-user|resuming` 的 `meta-po`，必须阻断推进，要求人工选择保留线程。
6. 若 CR 模板的自动终验授权字段有效，且 CP8 自动预检 `PASS`、无 `BLOCKING` / `REQUIRED`，允许将人工结果写为 `approved` 并标注 `approval_source=user-preauthorized`；否则仍按默认人工确认处理。

`active_agents[]` 中每条记录必须使用以下字段。平台没有提供的字段可以为空，但 `completed` 状态必须满足证据规则。

| 字段 | 说明 |
|---|---|
| `role` | 目标功能 Agent，例如 `meta-dev`、`meta-qa` |
| `agent_id` | 平台返回的子 agent 标识；Codex `spawn_agent` 返回值优先写入这里 |
| `agent_name` | 平台返回的昵称或任务名 |
| `thread_id` | 可恢复线程标识；平台无独立 thread 时可与 `agent_id` 相同 |
| `workflow_id` / `change_id` / `story_id` / `wave_id` | 精确复用键 |
| `handoff_path` | 对应 `process/handoffs/*.md` |
| `status` | `handoff-created`、`spawn-requested`、`running`、`completed`、`failed`、`unavailable`、`blocked`、`closing`、`closed` |
| `evidence` | `spawn_agent`、`resume_agent`、`send_input`、`platform-task` 或 `user-approved-inline-fallback` |
| `tool_name` | 实际调用的平台工具名 |
| `spawned_at` / `resumed_at` / `last_seen_at` / `completed_at` / `closed_at` | 生命周期时间 |
| `reusable` | 是否允许同 key 继续复用 |
| `fallback_reason` | 仅 `inline-fallback` 使用，必须写明用户批准原因 |

完成证据规则：

1. `status=completed` 且 `evidence` 为 `spawn_agent` / `resume_agent` / `send_input` / `platform-task` 时，`agent_id` 或 `thread_id` 必须非空，`tool_name` 必须非空，`completed_at` 必须非空。
2. `status=completed` 且 `evidence=user-approved-inline-fallback` 时，必须存在 `fallback_reason`，并在对应 handoff 的 `dispatch.mode` 中写明 `inline-fallback`。
3. 只有 `handoff_path` 或 `to_agent`，但缺少上述证据时，只能标记为 `handoff-created`、`blocked` 或 `unavailable`，不得标记为 `completed`。
4. CP6 / CP7 推进前必须交叉检查 `STATE.md.agent_lifecycle.active_agents` 与对应 handoff frontmatter；任一方缺失证据时，检查点必须失败。

## 输出文件 / 输出模板

| 对象 | 路径 | 用途 |
|---|---|---|
| 运行时状态 | `process/STATE.md` | 当前状态机实例 |
| 状态模板 | `skills/state-router/templates/STATE-TEMPLATE.md` | 初始化与结构基线 |
| CR 跟踪索引 | `process/changes/CR-INDEX.yaml` | active / blocked / candidate / spike_candidate / conflict 的机器可查询索引 |
| 自动检查结果 | `process/checks/CP*.md` | 自动检查点和自动预检证据 |
| 人工审查稿 | `process/checkpoints/CP*.md` | 人工检查点 checklist 与审查结果 |

## 约束

- 只负责状态判断、推进决策与状态回写，不生成需求/设计/实现内容
- 推进前必须验证当前阶段退出条件，不能用“默认通过”代替检查
- 推进前必须验证对应 CP 结果文件；不能只看文档 frontmatter 的 `confirmed=true`
- CP4 只作为自动预检门；不得要求 `process/checkpoints/CP4-STORY-PLAN-REVIEW.md` 才推进
- 回退必须记录原因、发起方和目标阶段
- Agent 复用必须使用 exact key，不得用模糊角色名匹配替代
- 并行队列必须由 Story DAG、依赖类型和文件所有权计算，不得只按 Wave 名称粗略并行
- 仅使用当前 `process/STATE.md` 与 `skills/state-router/templates/STATE-TEMPLATE.md` 契约

## 验收标准

- [ ] `STATE.md` 的阶段与下一步动作与实际产物状态一致
- [ ] 初始化时结构与 `skills/state-router/templates/STATE-TEMPLATE.md` 一致
- [ ] `STATE.md.checkpoints` 与 `process/checks/CP*.md`、`process/checkpoints/CP*.md` 的结论一致
- [ ] 推进 / 回退操作均追加 `history`
- [ ] 同一任务同角色不会重复登记活动 agent，检查点完成后有关闭动作
- [ ] `lld_ready` / `dev_ready` / `verify_ready` 的每个 Story 均能解释依赖和文件所有权依据
- [ ] 活跃阶段委托不会被 meta-po 越权代写或越权发起 CP2 / CP3
- [ ] CP2 推进前会检查 `SCENARIOS.yaml`、`TEST-MATRIX.md`、`STORY-MAP.md`、`MVP-SCOPE.md` 的存在性或 CP2 N/A / WAIVED 证据
- [ ] CP3 推进前会检查 `BLUEPRINT.md`、`DOMAIN-MAP.md`、`DEPENDENCY-MAP.md` 的存在性、HLD 消费关系或 CP3 N/A / WAIVED 证据
- [ ] CP7 推进前会检查 `verification-execution` 证据、`docs/quality/VERIFICATION-REPORT.md` 或等价摘要，以及 `TEST-MATRIX.md` 到 `VERIFICATION-REPORT.md` / `TEST-REPORT.md` / `REVIEW.md` 的追溯，或 CP7 N/A / WAIVED 证据
- [ ] CP8 推进前会检查 `process/release/RELEASE-CONTEXT.yaml`、`release_artifact_profile`、`release_decision`、`RELEASE-NOTES.md`、`DEPLOY-CHECKLIST.md`、`ROLLBACK.md`、`MIGRATION.md`、`FEEDBACK.md`，或 CP8 N/A / WAIVED 证据
- [ ] `lld_clarification_queue` 无未回答阻断项时才允许进入 CP5
- [ ] 阻塞状态下返回明确阻塞原因
- [ ] 状态查询必须列出 active formal CR、blocked formal CR、follow-up candidate、spike_candidate 和 stale_status_conflicts
- [ ] `scripts/check_cr_tracking_consistency.py` 能识别 `STATE.md.active_change` 指向已关闭 CR、多个 active CR、台账候选与正式 CR 文件不同步等问题

## 不适用边界

- 任务要求生成需求、设计、代码或文档本体
- 当前请求仅需要查看某个单独文件内容，不涉及状态推进

## Gotchas

- `story-execution` 是开发/验证阶段状态，不替代单个 Story 的生命周期；Story 状态仍以 `story-manager` 维护的卡片为准
- LLD 必须在 story-planning 内覆盖全部目标 Story 后统一确认，开发不能绕过全量 CP5 人工确认和 `dev_gate`；特别是 `runtime` 依赖默认等上游 `verified`
- 并行 LLD 阶段不要让多个 meta-dev 同时直接问用户；应让 meta-dev 写 clarification item，由 meta-po 合并后统一提问
- `delegated_interaction.status=returned` 只表示功能 Agent 阶段交还，不等于 CP2 / CP3 人工确认已通过
- 同一 Wave 内也可能因文件冲突串行；不同 Wave 的 Story 可以提前写 LLD，但不得在全量 CP5 通过前进入开发
- fast-lane 只能减少文档厚度和人工门数量，不能跳过 CP6 / CP7、`verification-execution` 证据摘要、Agent Dispatch Evidence 或 CP8 终验摘要
- 当存在活跃 `CR-*` 时，应优先收敛变更影响，再判断是否允许推进
- “唯一 active CR”不等于“没有后续 CR 候选”；follow-up tracking 中的 candidate / spike_candidate 必须作为 backlog 显式展示
- 当 CR 影响 Story、LLD、接口契约、文件所有权、`dev_gate` 或实现设计时，必须先形成 CR 影响范围的 `lld_design_batch`，批次确认前不得进入开发
- 首次初始化时只允许从 `skills/state-router/templates/STATE-TEMPLATE.md` 复制，不允许凭空脑补字段
- 自动检查点失败时，不要发起人工确认；先把失败结果写入 `process/checks/CP*.md` 并路由给责任 agent 修复
- 不要把 `delivery/skills/*/templates/` 中的模板文件当成运行态产物；只有 `docs/`、`process/`、`process/checkpoints/`、`delivery/` 中对应产物或 CP 自动检查里的逐项 N/A / WAIVED 说明才可作为推进证据
- N/A / WAIVED 必须写明原因、影响范围和后续触发条件；空泛写“不适用”不能作为阶段推进证据
