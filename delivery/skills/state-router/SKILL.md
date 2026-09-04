---
name: state-router
description: >-
  当需要推进工作流状态、回退到上一阶段、查询当前进度、或判断下一步应调用哪个 Agent 时使用。
  触发词包括：推进、下一步、当前状态、回退、状态查询、继续、阶段目标、长期路线、Roadmap。
  适用场景：元工作流全流程的状态管理。
argument-hint: "可选：指定目标阶段、查询字段或回退原因"
user-invokable: true
status: active
---


## vNext 过程引用契约

- `process/...` 是过程仓逻辑引用，不是发布仓中的相对物理路径。
- 首次文件系统 I/O 前必须调用 `meta-flow project resolve-ref --project-root <release-root> --logical-ref <process/...> --format json`。
- 只可瞬时使用成功 JSON 中的 `resolved_path`；不得把绝对路径写入治理文件、Prompt 产物或 Git。
- 命令以退出码 2 返回 BLOCKED 时必须停止；不得自行拼 sibling、去掉 `process/`、恢复软链接或回退 legacy。
- legacy-only 操作必须交还 Host Orchestrator，并使用独立 typed authorization；本 Skill 不构造 legacy capability。

## 目标

读取并更新轻量运行态、ledger 和 legacy 状态摘要，根据当前阶段的退出条件判断是否可推进、是否需要回退、下一步应唤醒哪个 Agent，并保持状态机与 `skills/state-router/templates/STATE-TEMPLATE.md`、`delivery/rules/AGENT-SKILL-CONTRACT.md` 及唯一机器 owner `delivery/rules/DELIVERY-RUNTIME-CONTRACT.json` 一致。

默认机器状态入口是 `process/state/STATE.current.json`。`STATE.md 是人类摘要` 和 legacy fallback；新项目不得把巨型 `process/STATE.md` 作为子 agent 默认读取入口。

## 适用场景

- 元工作流阶段推进、阶段回退、状态查询
- `host-orchestrator` 在每个阶段完成后进行退出条件判定
- Story 执行阶段内的 LLD 设计批次、开发队列、验证队列和依赖门控判断
- `requirement-clarification` / `solution-design` 阶段内的用户交互权委托状态判断
- 并行 LLD 写作期间的 `lld_clarification_queue` 收敛检查
- CP2 / CP3 / CP5 / CP8 前的 Decision Brief、`GATE-LEDGER.ndjson` 和当前 gate scalar/ref 维护
- CP2 / CP3 / CP5 / CP6 / CP7 / CP8 前后的 `context_budget`、`process/context/*-CONTEXT.yaml` 和全文档读取理由维护
- `workflow_health` 循环 / 卡顿 / 反复回修信号维护
- CP0-CP8 检查点状态、自动检查结果路径和人工审查结果路径维护
- CR 跟踪状态查询：汇总 active / blocked 正式 CR、follow-up candidate、spike_candidate 和状态冲突
- 长期治理与阶段查询：沿 Project/Roadmap/declared Phase 真相链回答阶段目标、下一阶段、长期路线和重叠关系
- `standard` / `fast-lane` 工作流模式、关键决策门控和同工作流自动子 agent 调度状态维护

## 前置条件

- [ ] 已通过唯一 logical-ref resolver 检查 `process` 路由；binding-only 默认不得创建 `process` 软链接，只有独立 typed authorization 明确选择 `relative-symlink` 才允许 legacy 兼容链接
- [ ] `process/state/STATE.current.json` 已存在；仅 legacy payload 缺少 state v2 时才读取 `process/STATE.md`，且不得把人类摘要提升为机器真相
- [ ] 当前阶段相关产物的存在性和确认状态可被检查

## 必须读取的输入

- `process/state/STATE.current.json`（默认机器状态入口，若已存在）
- `process/state/CR-LEDGER.ndjson`、`STORY-LEDGER.ndjson`、`GATE-LEDGER.ndjson`、`RUN-LEDGER.ndjson`、`CHECKPOINT-LEDGER.ndjson`、`HANDOFF-LEDGER.ndjson`、`AGENT-DISPATCH-LEDGER.ndjson`（按当前查询范围读取）
- `process/STATE.md`（仅 legacy fallback、人类摘要、迁移兼容或 state v2 缺失时读取）
- `skills/state-router/templates/STATE-TEMPLATE.md`
- `skills/checkpoint-manager/SKILL.md`
- `meta-flow check cr-tracking`（若存在）：CR 台账、正式 CR 和 `STATE.current.json.active_change` 一致性预检
- 长期治理查询按需读取：`process/PROJECT.yaml`、其 `roadmap_ref`、Roadmap 中全部 `phase_refs`，以及 active Phase `result_refs` 中声明的实施计划
- `process/context/*-CONTEXT.yaml` / `process/context/*.context.json` / `process/context/stories/*.json`：当前阶段上下文胶囊；默认优先读取
- `process/checks/CP0-*.result.json` 中的 `route_plan`，或正式 CR frontmatter / summary 中的 `cr_type`、`cr_trait_*`、`gate_profile`：用于判定当前 CR 的实际 CP 路径
- `meta-flow route plan`：当 CP0 result 尚未固化 route_plan，但已有 CR type / trait / gate profile 时，用可执行策略预览或重建 route_plan
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
- Story 执行阶段默认读取 Story ledger、Story packet、return packet、evidence index 和 CP result；`process/stories/STORY-*.md`、`process/stories/STORY-*-LLD.md`、`process/stories/STORY-*-IMPLEMENTATION.md` 与 `process/STORY-STATUS.md` 仅在 context `allowed_reads` 指明、字段冲突、人工审计或 legacy fallback 时读取。

## 知识来源

- `skills/state-router/templates/STATE-TEMPLATE.md`：状态对象结构与阶段机基线
- `AGENTS.md` / `rules/AGENTS.md`：阶段定义、人工检查点与角色职责
- 各阶段产物 frontmatter 与文件存在性：退出条件的事实来源
- `process/changes/CR-INDEX.json` 与 `process/changes/CR-*-FOLLOW-UP-TRACKING-*.md`：CR 跟踪索引和后续候选台账；`CR-INDEX.yaml` 仅作 legacy read-only fallback
- `process/PROJECT.yaml`、其 `roadmap_ref` 与 Roadmap 的 `phase_refs`：长期治理和 Phase 状态的机器真相链；project memory 只作线索
- `context-manifest-builder`：阶段上下文胶囊和最终上下文清单契约；capsule 是默认读取入口，不替代正式产物
- `scenario-expansion` / `story-planning` / `blueprint-design` / `implementation-design` / `implementation-execution` / `verification-execution` / `quality-review` / `release-readiness`：软件开发工作流新增产物契约；模板存在不代表运行态产物已完成

## 执行步骤

### 1. 初始化或读取状态

0. 首次 I/O 前必须用唯一 resolver 解析需要的 `process/...` logical ref；退出码 2、binding 冲突或元数据不一致时立即 BLOCKED。binding-only 默认不得创建 `process` 软链接，也不得把 logical ref 改写成 sibling 物理路径。
0.1 新项目和已迁移项目必须读取 `process/state/STATE.current.json`，并使用 ledgers 作为 CR、Story、Gate、Run、Handoff 和 Dispatch 的机器真相源；`process/STATE.md` 只用于受控的人类摘要渲染、人工审计和显式 legacy 迁移。
1. 首次初始化走 native project/state 初始化入口，由 resolver 返回的过程仓根创建 state v2、current discovery 与必要子目录；Skill 不自行构造 artifact root、project process root 或 link path。
2. 默认 route 必须是 `sibling-binding`。只有 Host Orchestrator 持有独立 typed authorization 且明确选择 `relative-symlink` 时，才可调用 legacy 兼容入口；本 Skill 不创建、恢复或猜测软链接。
3. 受控 writer 写入 `STATE.current.json` 后，由 native renderer 生成 `process/STATE.md` 人类摘要并刷新 CURRENT；任何失败都不得用手写 Markdown 代替。
4. 若 legacy 摘要需要迁移，必须先导入 native owner，再从 owner 重建摘要，不能把旧布尔值直接当作新检查点通过。
5. 读取 `workflow_mode`、`fast_lane_reason`、`current_phase`、`current_agent`、`blocked`、`active_change`、`pending_gate`、`pending_checklist_path`、`active_delegation_ref`、`active_question_batch_ref`、`agent_dispatch_ref`、`checkpoint_ledger_ref`、`gate_decisions_ref`、`cr_tracking_ref`、`cr_ledger_ref`、`workflow_health_ref`、`decision_briefs` 和 `discussion_checkpoints`。
6. 若 `blocked=true`，先返回阻塞原因，不允许静默推进。
7. 若旧 `STATE.md` 的 `checkpoints` 仍是“需求/HLD/Story/终验”旧布尔结构，必须先迁移为 CP0-CP8 结构；迁移动作写入 `history`，不得把旧布尔值当作新检查点已通过。
8. 若 `platform_capabilities_ref` 或 `agent_dispatch_ref` 缺失，必须写入轻量 ref 并把能力探测结果追加到 `process/state/AGENT-DISPATCH-LEDGER.ndjson` 或平台能力摘要；能力未探测前，不得把需要功能 Agent 的任务标记为 `completed`。
9. 若发现 legacy `orchestrator_session`，必须迁移为当前 scalar 字段和 dispatch / handoff ledger ref；迁移动作只表示状态结构升级，不表示允许重复启动 `host-orchestrator`。
10. 若用户启动正式工作流且未显式禁用自动调度，`subagent_auto_dispatch` 默认为 `enabled`；该授权只覆盖真实子 agent 调度，不覆盖 inline fallback。
11. 若 `discussion_checkpoints` 缺失，必须按模板补齐 CP2 / CP3 discussion log 和 checkpoint 路径；补齐路径不代表讨论已完成。
12. 若 `delegated_interaction` 缺失，必须按模板补齐，默认 `status=none`；补齐不代表已经委托成功。
13. 若 LLD clarification queue ref 缺失，必须写入 `active_question_batch_ref` 或 `process/state/QUESTION-LEDGER.ndjson` ref；补齐不代表问题已收敛。
14. 若 gate 决策 ref 缺失，必须写入 `gate_decisions_ref=process/state/GATE-LEDGER.ndjson`；补齐不代表当前没有待决策项，发起人工门禁前仍必须从正式产物重新聚合 Decision Brief。
15. 若 CR tracking ref 缺失，必须写入 `cr_tracking_ref=process/changes/CR-INDEX.json` 和 `cr_ledger_ref=process/state/CR-LEDGER.ndjson`；补齐不代表当前没有后续候选 CR，状态查询前仍必须读取台账和正式 CR 文件。`CR-INDEX.yaml` 只能在 legacy 迁移场景只读参考。
16. 若 `context_budget` 缺失，必须按模板补齐，默认 `require_capsule_first=true`；补齐不代表 capsule 已生成。CP2 / CP3 / CP5 / CP6 / CP7 / CP8 前必须检查对应 `process/context/*-CONTEXT.yaml` 的存在性、状态和 `read_profile`。
17. 若 `workflow_health` 缺失，必须按模板补齐，默认 `status=healthy` 和计数器为 0；每次推进、回退、重试、用户问题重复、CP 失败或 Story 回修时刷新对应计数器。

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
| LLD clarification 队列过大 | `lld_clarification_items` | 8 | 暂停 LLD 并由 host-orchestrator 合并问题批量询问 |
| 同一 CP 重试失败 | `cp_retry_count` | 2 | 路由到责任 Agent 或人工仲裁 |
| 同一 Story 回修次数过多 | `story_rework_count` | 2 | 升级为设计澄清或 CR |
| 产物 hash 连续不变但仍重写 | `unchanged_artifact_hash_rounds` | 2 | 停止重写，要求明确新事实或决策 |
| 阶段轮次过长 | `phase_elapsed_rounds` | 6 | 输出卡顿摘要和下一步决策 |

任一计数器超过阈值时，`workflow_health.status` 必须变为 `stalled`、`blocked` 或 `requires-human-arbitration`，并把下一步写成决策项；不得继续静默重试消耗 token。

### 2.0 CR 产品基线重整优先路由

CR 路由必须由可执行 `route_plan` 驱动，而不是固定全量 CP0-CP8 模板。state-router 读取顺序为：

1. 优先读取 CP0 result JSON 中已固化的 `route_plan`。
2. 若正式 CR 写有 `route_plan_ref`，优先读取该 JSON artifact，例如 `process/checks/CP0-CR045.route-plan.json`。
3. 若 CP0 result / route_plan_ref 未固化 route_plan，则从正式 CR frontmatter / summary 读取 `cr_type`、`cr_trait_*`、`gate_profile`，调用或等价执行 `meta-flow route plan --from-cr <CR.md>` 生成草稿 route_plan。
4. 若 CR 尚未创建，CP0 intake 先由 host-orchestrator 评估草稿 `cr_type`、`cr_trait`、`gate_profile`，再生成草稿 route_plan；CP0 PASS 后回填正式 CR frontmatter。

route_plan 的优先级：

- `gate_profile` 表达治理强度和默认最大路径。
- `route_plan.stages[]` 是本 CR 的实际执行路径，按 CP0..CP8 顺序推进。
- `route_plan.checkpoint_applicability[CPx]` 是 CP 是否需要 result/checkpoint 的机器判断。
- `cr_trait_*` 扁平 frontmatter 字段必须通过统一桥接逻辑转成 `derive_route_plan()` 消费的 `cr_trait` dict；不得让各模块自行解析。
- `CPx-lite` 不得作为 CP result 的 `checkpoint` 值；`-lite` 只表示 `mode: "lite"`，checkpoint ID 仍为标准 `CP0`..`CP8`。
- `decision=N/A` 的 CP 不适用于当前 CR，state-router 不得为该 CP 构造 result path、不得因缺少 CP result 而 BLOCKED；后续聚合校验可从 route_plan 或 aggregate applicability JSON 重建决策链。
- `decision=WAIVED` 表示 CP 适用但被显式豁免，必须有 waiver reason/ref，不能当作 N/A 使用。
- route_plan 可以因产品基线或 trait 添加 gate_profile 默认 stages 之外的 CP，但不得静默降级治理强度。CP2 / CP3 / CP5 / CP8 在 profile 外新增时必须保留标准 human gate 语义；若当前 profile 不能承载该硬门禁，route_plan 必须写入 `profile_upgrade_required[]` 并 BLOCKED。
- 典型升级规则：`requires_architecture_review=true` 至少升级到 `architecture-major`；`requires_story_decomposition=true` 至少升级到能保留 CP5 设计确认的代码 profile；`docs-lite + has_new_implementation=true` 必须升级到 `standard-code`；`micro + has_new_design=true` 必须 BLOCKED 并要求升级。

state-router 仍维护阶段机，但阶段序列必须从 `route_plan.stages[]` 推导，不得按全量阶段固定推进。推导规则为：

| CP | phase |
|---|---|
| CP0 | `init` |
| CP1 / CP2 | `requirement-clarification` |
| CP3 | `solution-design` |
| CP4 / CP5 | `story-planning` |
| CP6 / CP7 | `story-execution` |
| CP8 | `documentation` |

`route_plan.phase_sequence` 是该映射去重后的结果；若 artifact 未包含该字段，state-router 必须按上表即时推导。某阶段全部 CP 均为 `N/A` 时，该阶段不进入推进序列；某阶段有任一 CP 适用或 waived，则该阶段保留并只检查适用 CP。

CP 适用性由 `cr_trait` 决定：

| cr_trait 字段 | 为 false / 空时影响 | 为 true 时影响 |
|---|---|---|
| `uses_existing_evidence_only` | 不触发特殊裁剪 | CP3 / CP4 / CP5 / CP6 / CP7 全部 `N/A`；CP2 仍按 scope / authz 风险决定是否人工确认 |
| `has_new_design` | CP3 / CP4 / CP5 默认 `N/A` | CP3 / CP4 / CP5 必须适用，除非更细字段裁剪 |
| `requires_architecture_review` | CP3 可 `lite` 或 `N/A` | CP3 必须 `mode=standard` 且 `human_gate=required` |
| `requires_story_decomposition` | CP4 / CP5 默认 `N/A` | CP4 / CP5 必须适用，CP3 至少 `lite` |
| `has_new_implementation` | CP6 默认 `N/A` | CP6 必须适用，并自动推导 CP7，除非存在显式 verification waiver |
| `has_new_verification` | 无新实现时 CP7 默认 `N/A` | CP7 必须适用 |
| `requires_subagent_dispatch` | dispatch 可以记录为 not-required / inline-fallback | 必须存在真实子 agent 调度证据，或有批准的 inline-fallback |

CP1 不由 `cr_trait` 直接控制，而由 gate profile 与产品基线规则控制：`architecture-major`、`runtime-high-risk` 或 `product_baseline_refresh_required=true` 时 CP1 required；其他 profile 默认 CP1 N/A。

CP2 的 `human_gate` 使用三级语义：

| human_gate | 含义 |
|---|---|
| `required` | 必须人工确认，缺失则 BLOCKED |
| `optional` | 自动预检可通过；存在 scope / authz / product-baseline 灰区时升级为 required |
| `none` | 无人工门禁，仅限明确低风险 profile |

CP2 升级为 required 的触发条件包括：`cr_type` 为 `product-scope` / `architecture` / `runtime`，`product_baseline_refresh_required=true`，`impact_surface` 包含 use-cases / requirements / scope / product-baseline，存在未关闭 scope/authz OPEN/LCQ，或授权边界发生变化。

`human_gate=optional` 只有同时满足以下条件时可自动推进并记录 `approval_source=auto-clean-gate`：自动预检 `PASS` 或 `WAIVED`、Decision Brief 无待人工决策项、`meta-flow check human-gate` 无 ERROR、context check 无 ERROR、无 blocking/high-risk open item、无 scope/authz/product-baseline 灰区、用户未要求显式审查。任一条件不满足时必须升级为 `required` 并等待用户确认；自动推进后若用户在后续 24h 内要求回看，必须允许回退到该 CP 重新审阅。

按阶段推进前，state-router 必须先读取 active CR 的 summary / CR-INDEX。若任一 active CR 命中以下条件，不得进入 Story 拆解、LLD 设计批次、story-planning 或 story-execution：

- `product_baseline_refresh_required=true`
- `required_gate=CP2`
- `gate_status=cp2_pending`
- `impact_surface` 包含 `use-cases` / `requirements` / `scope` / `product` / `product-baseline`
- `affected_product_docs` 包含 `USE-CASES.md`、`REQUIREMENTS.md`、`SCENARIOS.yaml`、`TEST-MATRIX.md`、`STORY-MAP.md`、`MVP-SCOPE.md`

命中后下一步固定为：

- `current_phase=requirement-clarification`
- `current_agent=meta-pm`
- `next_action.type=delegate_product_baseline_refresh`
- `next_action.text` 必须说明基于哪个 CR / Change Package 执行增量场景发现、需求澄清和 CP2
- `block_story_decomposition_until=CP2-approved`

大块集中需求默认归类为目标包，而不是 CR 列表。同一目标、同一 persona / user journey、共享 HLD、同一 release value 或需要多个 Story 才能交付的需求集合，必须先创建 / 复用 parent CR 或 Change Package 作为审计外壳，再委托 `meta-pm` 完整执行用户场景发现、需求澄清、SCENARIOS / TEST-MATRIX / STORY-MAP / MVP-SCOPE，并在 CP2 通过后进入 `solution-design`。只有目标、审批人、风险授权、交付节奏、回滚策略或审计边界不同，才允许拆出子 CR；普通开发工作拆 Story，不逐条拆 CR。

### 2. 按阶段检查退出条件

下表是标准全量路径的阶段基线。存在 active CR route_plan 时，以 `route_plan.stages[]` 作为实际推进路径；表中不适用的 CP 必须由 `route_plan.checkpoint_applicability` 标记为 `N/A`，不得为跳过的 CP 生成仪式性 result JSON。

| 当前阶段 | 退出条件 | 下一阶段 | 默认唤醒 Agent |
|---|---|---|---|
| `init` | `process/checks/CP0-REQUEST-INTAKE.md` 结论为 `PASS` 或 `WAIVED` | `requirement-clarification` | `meta-pm` |
| `requirement-clarification` | 阶段委托已交还，CP1 自动检查通过，CP2 自动预检通过且 `process/checkpoints/CP2-REQUIREMENTS-BASELINE.md` 人工结论为 `approved`；`docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/product/STORY-MAP.md`、`docs/product/MVP-SCOPE.md` 存在，或 CP2 自动检查逐项写明 `N/A` / `WAIVED` 原因 | `solution-design` | `meta-se` |
| `solution-design` | 阶段委托已交还，CP3 自动预检通过且 `process/checkpoints/CP3-HLD-REVIEW.md` 人工结论为 `approved`；`docs/design/BLUEPRINT.md`、`docs/design/DOMAIN-MAP.md`、`docs/design/DEPENDENCY-MAP.md` 已生成并被 HLD 消费，`docs/design/ARCHITECTURE-DECISION.md` 的核心 ADR 已确认，或 CP3 自动检查逐项写明 `N/A` / `WAIVED` 原因 | `story-planning` | `meta-se` |
| `story-planning` | `docs/design/FEATURE-DESIGN-MATRIX.md` 已生成，required Feature 设计已生成或 waived，CP4 自动预检通过，`lld_clarification_queue` 无未回答阻断项，全部目标 Story 的独立 LLD / Batch LLD Story 锚点 / 技术说明 / waived 证据通过 CP5 自动预检且 `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` 人工结论为 `approved` | `story-execution` | `meta-dev` |
| `story-execution` | 全部目标 Story 均通过 CP6、CP7，并到达 `verified` 或 `verified-with-risk`，且 CP6 包含实现执行证据路径 / N/A 原因，CP6/CP7 包含 Agent Dispatch Evidence；CP7 通过 `verification-execution` 产出 `docs/quality/VERIFICATION-REPORT.md` 或等价摘要，包含验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划和合法阶段决策；`TEST-MATRIX.md` 可追溯到 `VERIFICATION-REPORT.md` / `TEST-REPORT.md` / `REVIEW.md`，或 CP7 写明 `N/A` / `WAIVED` 原因 | `documentation` | `meta-dev` / `meta-qa` / `meta-doc` |
| `documentation` | CP8 自动预检通过且 `process/checkpoints/CP8-DELIVERY-READINESS.md` 人工结论为 `approved`；`process/release/RELEASE-CONTEXT.yaml` 已生成且 `release_artifact_profile=minimal|compact|full`、`release_decision=READY|READY_WITH_RISK`；`NOT_READY` 不得发起人工终验；`RELEASED` / `FAILED` 只能在独立真实发布授权后写入；`docs/release/RELEASE-NOTES.md`、`docs/release/DEPLOY-CHECKLIST.md`、`docs/release/ROLLBACK.md`、`docs/release/MIGRATION.md`、`docs/release/FEEDBACK.md` 已按 profile 生成或 CP8 写明 `N/A` / `WAIVED` 原因；CP8 后续事项已按关闭范围 / 不授权范围 / 风险接受项 / 后续 CR 候选项 / 取消或 deferred 项分流，必要时 `follow_up_tracking_path` 可读 | `delivered` | `host-orchestrator` |
| `delivered` | 只读归档 | — | — |

推进时只允许读取检查点结果文件和 `process/checks/CP*.result.json` 与 `process/state/CHECKPOINT-LEDGER.ndjson` 的同步状态；若两者冲突，以检查点结果文件为准，并把冲突写入 `history`。

### 2.1 阶段委托交互检查

`delegated_interaction` 只描述阶段内谁直接与用户沟通，不改变正式门控归属。

| 阶段 | 合法委托 | 推进要求 |
|---|---|---|
| `requirement-clarification` | `agent_role=meta-pm` | CP2 人工确认前，若 `status=delegated|active|awaiting-user`，不得由 host-orchestrator 代写需求或发起 CP2；必须把用户输入转交给该 meta-pm。只有 `status=returned` 且 `return_summary_path` 可读，才允许生成 CP2 Decision Brief。 |
| `solution-design` | `agent_role=meta-se` | CP3 人工确认前，若 `status=delegated|active|awaiting-user`，不得由 host-orchestrator 代写 HLD 或发起 CP3；必须把用户输入转交给该 meta-se。只有 `status=returned` 且 `return_summary_path` 可读，才允许生成 CP3 Decision Brief。 |
| 其他阶段 | 空或 `status=none|returned|closed` | 不得保留活跃阶段委托；若仍为 active，先收敛或标记 blocked。 |

若用户在 `host-orchestrator` 线程中发送内容，而 `delegated_interaction.status` 表示活跃委托，state-router 必须返回“转交委托 Agent”的下一步建议，而不是推进阶段。

### 2.2 当前状态 / CR 盘点查询

当用户询问“当前状态”“还有哪些 CR 需要推进”“建议如何推进”“待跟踪 CR”等问题时，state-router 不得只返回 `STATE.current.json.active_change` 或唯一 `status=active` 的正式 CR；必须生成 CR 盘点视图：

1. 读取 `process/state/STATE.current.json.active_change`、`process/changes/CR-INDEX.json` 与 `process/state/CR-LEDGER.ndjson`、全部 `process/changes/CR-*.md` 正式 CR 和全部 `process/changes/CR-*-FOLLOW-UP-TRACKING-*.md` 台账；native index 必须先通过 schema、数值 CR 顺序和 semantic digest 校验。`process/changes/CR-INDEX.yaml` 若存在，只能作为 legacy read-only fallback 并应列为迁移警告。
2. 若存在 `meta-flow check cr-tracking`，运行或要求运行该脚本检查 `--project-root .`；若无法运行，必须在回答中说明跳过原因。
3. 输出必须固定分为五类：`active formal CR`、`blocked formal CR`、`follow-up candidate`、`spike_candidate`、`stale_status_conflicts`。
4. `candidate` / `spike_candidate` 是 backlog，不占执行锁，但必须在“还有哪些 CR 需要推进”回答中列出标题、优先级、阻塞前置、下一步和不授权边界。
5. 若 `STATE.current.json.active_change` 指向已关闭 CR，或与正式 `status=active` 的 CR 不一致，必须先列为 `stale_status_conflicts`；不得因为状态冲突而隐藏 follow-up 台账候选项。
6. 若存在独立 active CR（例如未占用 follow-up 候选编号的临时 CR），必须要求其在台账或 `CR-INDEX.json` 中建立 `related_active_cr`、`blocked_by`、`superseded_by` 或等价关系，否则列为同步缺口。
7. 推进建议必须先收敛 active / blocked 正式 CR，再说明哪些 candidate 可启动、哪些必须等待前置 CR、哪些只适合 Spike。

### 2.3 长期治理 / 阶段目标查询

当用户询问“阶段目标”“长期治理”“长期路线”“Roadmap”“下一阶段”“后续如何规划”或“与现有阶段是否重叠”时，state-router 必须使用以下独立查询路径；不得用 CR 盘点、当前 Work、最近对话或 memory 代替：

1. 通过 resolver 读取 `process/PROJECT.yaml`，校验项目身份并取得唯一 `roadmap_ref`。
2. 只读取该 `roadmap_ref`，按声明顺序取得 `phase_refs`。
3. 通过 resolver 读取全部 declared `phase_refs`；禁止 sibling discovery、目录扫描、文件名推导或未声明 Phase 扩读。
4. 核对每个 Phase 的 `status`、`objective`、`work_refs`、`result_refs`，并检查引用缺失、重复 active、项目身份和 schema 冲突。任何冲突返回 `BLOCKED`，不得猜测修复。
5. 普通阶段查询到第 4 步停止。只有用户需要 active Phase 的详细路线时，才从该 Phase 的 `result_refs` 中读取已声明实施计划，并记录扩读原因；只有边界、重定基或历史决策问题才继续读取治理基线/ADR。
6. 默认 5 对象查询预算不变；长期路线允许 `PROJECT + ROADMAP + 全部 declared phase_refs` 的有界例外。该例外不授权全部 Work/CR、legacy 或历史对象扩读。
7. 回答固定分为：
   - `机器事实`：路径、Phase 顺序、状态、目标和声明引用；
   - `解释/推断`：当前问题由哪个 Phase/工作流承载；
   - `建议`：下一 Work、工作流或 Phase 调整，以及不授权边界。
8. 提议新 Phase 前输出重叠矩阵，至少比较目标结果、进入条件、退出条件、非目标和时间跨度。若候选目标可作为 active/planned Phase 的 Work 或工作流完成，默认复用现有 Phase。
9. project memory 只用于发现可能的历史线索；memory 不可用不阻塞，memory 与仓库冲突时采用仓库机器事实并报告漂移。

此查询是只读操作，不更新 `STATE.current.json`，不创建 Work/CR/Phase，也不构成实现、Git 或发布授权。

### 3. 处理回退

1. 记录回退原因与目标阶段。
2. 将回退动作写入 `history`。
3. 只回退到最近仍可恢复的稳定阶段，不跨越未收敛变更单。

### 3.1 后续 CR 启动与冲突预检

当用户请求从 follow-up tracking 台账启动候选 CR 时，state-router 必须先做冲突预检，再允许 `change-impact-analysis` 创建正式 CR：

1. 读取台账路径、候选编号、`STATE.current.json.active_change`、`process/changes/CR-INDEX.json` 与 `process/state/CR-LEDGER.ndjson` 和所有未关闭 `process/changes/CR-*.md`；`CR-INDEX.yaml` 若存在，只能作为 legacy read-only fallback。
2. `candidate` / `spike_candidate` 不占执行锁；`active` / `blocked` 的正式 CR 视为未完成。
3. 比较受影响正式文档、Story / LLD 批次、文件 owner、外部接口、权限 / 安全边界、运行授权、风险接受项和来源决策 ID。
4. 若无重叠，允许创建正式 CR；台账状态单独改为 `active`，native index 只能通过 `meta-flow cr index`/`status-sync` 从 formal CR 重建，禁止直接编辑 index item。
5. 若存在重叠，返回 `blocked` 下一步，不得静默并行推进；host-orchestrator 必须发起人工决策，选项包括合并到现有 CR、保持候选等待、标记 `blocked`、拆分无冲突子集或 `superseded`。

### 4. 回写状态

1. 更新 `current_phase`、`current_agent`、`last_action`、`next_action`、`last_updated`。
2. 推进或回退时追加 `history` 记录。
3. 同步 `checkpoints.<cp_id>.status`、`last_result`、`auto_result`、`manual_review` 或滚动 `results[]`。
4. 查询状态时不改变业务内容，但允许刷新 `next_action`。

native CR 的 lifecycle/readiness/gate tuple 变化不得逐文件手写。state-router 必须先调用 `meta-flow cr status-sync` 生成零 mutation 计划；只有 plan=READY、expected process OID、Work scope digest 和所有 target before digest 未漂移且存在本轮 apply 授权，才可执行 apply。异常后先 inspect，再显式 resume/rollback；`RECOVERED`、`PARTIAL` 和 `BLOCKED` 都停止后续阶段。

### 4.1 检查点结果同步

每次推进前必须按 `checkpoint-manager` 契约读取检查点结果。若 active CR 有 route_plan，则本表只适用于 `checkpoint_applicability[CPx].applies=true` 的 CP；`decision=N/A` 的 CP 不读取必读文件、不调用 `meta-flow cp result-check`、不因文件不存在阻断推进。若存在历史 N/A result JSON，可以校验其 `not_applicable_reason` / `route_plan_ref`，但不得要求 CP6 / CP7 的 story dispatch 字段。

| 检查点 | 必读文件 | 通过条件 |
|---|---|---|
| CP0 | `process/checks/CP0-REQUEST-INTAKE.md` | 结论为 `PASS` 或 `WAIVED` |
| CP1 | `process/checks/CP1-USE-CASE-COMPLETENESS.md` | 结论为 `PASS` 或 `WAIVED` |
| CP2 | `process/checks/CP2-REQUIREMENTS-BASELINE.md` + `process/checkpoints/CP2-REQUIREMENTS-BASELINE.md` | 自动预检通过且人工结论 `approved`；`docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/product/STORY-MAP.md`、`docs/product/MVP-SCOPE.md` 存在或自动检查逐项写明 `N/A` / `WAIVED` |
| CP3 | `process/checks/CP3-HLD-CONSISTENCY.md` + `process/checkpoints/CP3-HLD-REVIEW.md` | 自动预检通过且人工结论 `approved`；蓝图适用性已判定，`docs/design/BLUEPRINT.md`、`docs/design/DOMAIN-MAP.md`、`docs/design/DEPENDENCY-MAP.md` 已被 HLD 消费或自动检查逐项写明 `N/A` / `WAIVED`；`docs/design/ARCHITECTURE-DECISION.md` 的核心 ADR 已用推荐 / 备选 / 优劣 / 影响风险 / 回退条件确认 |
| CP4 | `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md` | 自动预检通过；`docs/design/FEATURE-DESIGN-MATRIX.md`、required Feature 设计、Story `feature_design_refs` / `lld_policy`、结果、风险和开放项汇入 CP5 Decision Brief |
| CP5 | 全部目标 Story 的 `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md` + `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` | 全部目标 Story 的独立 LLD / Batch LLD Story 锚点 / 技术说明 / waived 证据自动预检通过且全量人工结论 `approved` |
| CP6 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` | 当前 Story 结论为 `PASS` 或 `WAIVED`，meta-dev 调度证据通过，且实现执行证据完整：复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / 护栏 / 平台适配 / 发布相关 Story 必须有 `process/stories/STORY-{id}-{story_slug}-IMPLEMENTATION.md` 或 `docs/features/<feature>/IMPLEMENTATION.md`；低风险 Story 至少在 Story 卡片或 DEV-LOG 中记录实现对象清单、设计契约映射、测试 / Fixture 计划、最小实现切片、本地验证与 N/A 理由 |
| CP7 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` | 当前 Story 结论为 `PASS`、`PASS_WITH_RISK` 或 `WAIVED` 时可进入已验证状态；`NEEDS_REWORK` 必须回 meta-dev；`NEEDS_DESIGN_CLARIFICATION` 必须回 meta-se / host-orchestrator；`BLOCKED` 停止推进；meta-qa 调度证据通过；`verification-execution` 已输出 `docs/quality/VERIFICATION-REPORT.md` 或 Feature scoped 等价证据；验证对象清单、验证追踪矩阵、设计契约验证和分层验证计划完整；`TEST-MATRIX.md` 覆盖项已回链到 `VERIFICATION-REPORT.md` / `TEST-REPORT.md` / `REVIEW.md` 或检查结果写明 `N/A` / `WAIVED` |
| CP8 | `process/checks/CP8-DELIVERY-READINESS.md` + `process/checkpoints/CP8-DELIVERY-READINESS.md` | 自动预检通过且人工结论 `approved`；`process/release/RELEASE-CONTEXT.yaml` 可读，且 `release_artifact_profile=minimal|compact|full`、`release_decision=READY|READY_WITH_RISK`；`READY_WITH_RISK` 的风险已进入 Decision Brief / risk acceptance；`docs/release/RELEASE-NOTES.md`、`docs/release/DEPLOY-CHECKLIST.md`、`docs/release/ROLLBACK.md`、`docs/release/MIGRATION.md`、`docs/release/FEEDBACK.md` 已按 profile 生成或自动检查写明 `N/A` / `WAIVED`；若存在 CP8 后续事项，follow-up tracking 台账可读且无未分类项 |

CP2 / CP3 / CP5 / CP8 人工检查点文件缺失、未填“人工审查结果”或结论不是 `approved` 时，不得推进。CP4 不再要求独立人工审查稿。

CP2 推进前必须确认 `discussion_checkpoints.cp2_scenario_discussion` 指向的 log / checkpoint 已存在，或 CP2 自动检查明确写明 N/A / blocked 原因；同时确认 `SCENARIOS.yaml`、`TEST-MATRIX.md`、`STORY-MAP.md`、`MVP-SCOPE.md` 的存在性或逐项 N/A / WAIVED 证据。CP3 推进前同理检查 `discussion_checkpoints.cp3_hld_discussion`，并确认蓝图适用性判定、`BLUEPRINT.md` / `DOMAIN-MAP.md` / `DEPENDENCY-MAP.md` 的存在性或逐项 N/A / WAIVED 证据；核心 ADR 必须在 CP3 Decision Brief 中以关键决策项形式确认，包含推荐、备选、优劣、影响 / 风险和回退 / 切换条件；不得只看 `HLD.md confirmed=true`。

CP2 / CP3 / CP5 / CP8 发起前必须额外确认 Decision Brief 与 gate ledger：

- 所有 `Q-*`、`OPEN`、`LCQ-*`、`O-*`、权限 / 安全边界、风险接受、运行授权、外部接口、数据写入、publish、live / 交易类事项已分类为 `resolved-by-user`、`decision-item`、`non-blocking-open`、`converted-to-spike` 或 `n/a-with-reason`。
- `decision-item` 均已写入本轮 checkpoint Decision Brief，并通过 `GATE-LEDGER.ndjson` 或 gate launch event 记录 `id/gate/decision_type/question/recommendation/alternatives/pros_cons/impact_risk/rollback_switch/status/source`。
- `decision_collection_coverage[]` 已记录本轮 gate 的来源扫描覆盖，包含每个适用来源的 `source_type/source_path/scan_status/candidate_count/included_decision_count/classification_or_na_reason`。
- 本轮发起消息、`pending_decision_ids` 与 `process/checkpoints/CP*.md` 的 Decision Brief 决策表一致；若不一致，不得把当前 gate 状态置为 `awaiting-user`。
- 门禁消息必须通过 `meta-flow ask-user human-gate --checkpoint <process/checkpoints/CP*.md> --output <launch-message> --check-output` 生成并自检，并通过 `meta-flow check human-gate --checkpoint <process/checkpoints/CP*.md> --launch-message-file <launch-message> --require-launch-message` 校验后，才能发起人工确认。
- 若用户修订了范围、安全、运行授权或风险接受含义，必须把相关 DQ 退回 `open`，重新生成 Decision Brief 和发起消息。

### 5. Story 并行调度队列

story-planning 和 story-execution 阶段必须维护并行执行上下文或 queue ref。标准开发时，`lld_design_batch` 必须覆盖全部目标 Story，但每个 Story 的设计证据按 `lld_policy.required_level` 分为 `full-lld`、`technical-note`、`waived`，并可在 `standard-lite` / `allows_batch_lld=true` 下用 `design_evidence_type=batch-lld` 打包多个低中风险 Story 的独立设计小节；CR 触发时，`lld_design_batch` 默认等于 CR 影响范围内全部受影响 Story。Wave 只用于进入 story-execution 后的开发/验证调度。

1. `lld_design_batch`：本轮必须先完成设计证据的 Story 集合；标准开发使用 `batch_id=all-stories`、`source=all-stories` 并列出全部目标 Story，CR 使用 `source=change` 并列出全部受影响 Story；每项必须含 `story_id`、`design_evidence_type=full-lld|batch-lld|technical-note|waived`、`evidence_path`、`lld_policy_required_level`；`batch-lld` 的 `evidence_path` 必须指向 `process/stories/BATCH-*-LLD.md#story-story-{id}`。
2. `lld_ready`：全量设计证据批次内 Story 边界稳定、HLD/ADR/FEATURE-DESIGN-MATRIX 已确认、Feature 设计输入满足且没有 design_evidence_confirmed=true。
3. `lld_running`：正在写 LLD 的 Story，数量不得超过 `max_parallel_lld`。
4. `lld_review`：完整 LLD / Batch LLD Story anchor / 技术说明 / waived 证据已输出，等待全部目标 Story 完成设计证据与 CP5 自动预检；不得因单个 Story 或单个 Wave 已就绪就进入开发。
5. `lld_batch_review`：全部目标 Story 均已输出设计证据和 CP5 自动预检，等待 `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` 人工确认。
6. `lld_clarification_queue`：并行 LLD 期间由 meta-dev 写入的实现灰区队列。字段至少包含 `status`、`active_question_batch`、`items[]`；每个 item 至少包含 `id`、`story_id`、`owner_agent`、`question`、`options`、`recommendation`、`impact_surface`、`blocks_lld`、`answer`、`status`。
7. `dev_ready`：进入 story-execution 后，全量 CP5 人工确认 approved，当前 Story 所在 Wave 可执行，当前 Story design_evidence_confirmed=true，`dev_gate` 满足，且 `file_ownership.primary` 不与 `dev_running` 冲突。
8. `dev_running`：正在实现的 Story，数量不得超过 `max_parallel_dev`。
9. `verify_ready`：开发完成并进入 `ready-for-verification` 的 Story；CP6 已记录实现执行证据路径、证据类型、实现对象清单、设计契约映射、测试 / Fixture 计划、切片验证结果和平台差异检查结论，或写明低风险 N/A 理由。
10. `verify_running`：正在验证的 Story，数量不得超过 `max_parallel_qa`。
11. `verified_with_risk`：CP7 结论为 `PASS_WITH_RISK` 的 Story；可进入后续阶段，但剩余风险必须汇入 CP8 Decision Brief / risk acceptance 输入。
12. `needs_rework`：CP7 结论为 `NEEDS_REWORK` 的 Story；必须路由回 meta-dev，复修后重新 CP6 / CP7。
13. `needs_design_clarification`：CP7 结论为 `NEEDS_DESIGN_CLARIFICATION` 的 Story；必须路由回 meta-se / host-orchestrator，必要时重开 CP5 或 CR。
14. `blocked_by_dependency`：依赖类型、上游状态、批次边界或文件所有权阻塞的 Story，必须写明 `blocked_by`、`dependency_type`、`required_status` 或 `conflict_files`。

CP5 发起前必须额外检查 `lld_clarification_queue`：

- `status=awaiting-user|batching|blocked` 时不得发起 CP5。
- 任一 item 满足 `blocks_lld=true` 且 `status` 不是 `answered|resolved|converted-to-spike|waived` 时，不得发起 CP5。
- 非阻断 OPEN / Spike 可进入 CP5，但必须在 `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` 的 Decision Brief 中暴露其影响、owner、重访条件和是否影响跨 Story 契约。
- 用户回答后，host-orchestrator 必须把答案写回 item 的 `answer/status`，再通过 `resume_agent` 或 `send_input` 分发给对应 `owner_agent`。
- CP5 context 必须通过 `meta-flow story cp5-context-check --context <process/context/CP5-*-CONTEXT.yaml> --project-root .`；默认读取集合不得包含完整 HLD / ADR / TEST-MATRIX / TEST-REPORT / REVIEW，除非 capsule 写明 `full_doc_read_reason` 或 `read_expansion_log`。
- 每份 Story 设计证据必须通过 `meta-flow story lld-check --lld <evidence> --evidence-type full-lld|batch-lld|technical-note|waived`；`full-lld` 必须覆盖 14 段语义要点，`batch-lld` 必须标注 batch scope / homogeneous pattern / risk level / shared contract，且不得用于 runtime / security / credential / production-write 等高风险 Story。

依赖门控规则：

| 依赖类型 | LLD 队列规则 | 开发队列规则 |
|---|---|---|
| `contract` | 上游接口在 Story 或 LLD 中声明即可进入 LLD | 上游接口冻结且当前 LLD confirmed=true |
| `runtime` | 可进入 LLD，但必须记录运行时风险 | 默认要求上游 `verified` |
| `file-conflict` | 可进入 LLD，但必须记录合并顺序 | 不得与冲突 Story 并行开发 |

### 6. Agent 生命周期登记

Codex 多 agent 模式下，state-router 必须维护 `AGENT-DISPATCH-LEDGER.ndjson` 和 handoff dispatch 证据。active agent 视图只登记功能子 agent，不登记 Host Orchestrator 主进程：

1. 新 agent 启动前，按 `role + workflow_id + change_id + story_id + wave_id` 精确查找可复用线程；批次级确认按 `role + workflow_id + change_id + batch_id` 追踪。
2. 命中可复用线程时返回 resume / send_input 建议，不允许重复 spawn。
3. 关键人工检查点通过、Story LLD 确认完成、实现交接验证、验证报告交付或文档终验完成后，标记对应功能子 agent 线程 `status=closing` 并提示 Host Orchestrator close。
4. active agent 视图中不得出现 `host-orchestrator`；发现时必须标记为 legacy/stale 并迁出到 archive 或 dispatch ledger，不得继续当作可调度功能 agent。
5. active agent 失活或用户手动关闭时，必须在 dispatch ledger 记录重建原因，不能静默生成新线程。
6. 若旧 `STATE.md` 存在 `agent_lifecycle`，必须迁移为 `AGENT-DISPATCH-LEDGER.ndjson` 与 `platform_capabilities_ref`；迁移本身不代表允许新建编排子 agent。
7. Codex 工具面暴露 `spawn_agent` / `resume_agent` / `send_input` 时，必须通过受控 writer 将 `platform_capabilities.subagent_dispatch.available=true`、`method=codex-tools` 写入 `STATE.current.json` 的合法字段；若工具面不可用，写 `available=false`、`method=unavailable`、`limitation` 并阻断需要功能 Agent 的任务。不得直接编辑生成的 `STATE.md`。
8. `subagent_auto_dispatch=enabled` 且 `subagent_dispatch.available=true` 时，创建 `mode=subagent` handoff 后必须立即调用真实子 agent 工具；不得只写 handoff 后继续由 Host Orchestrator 代做。
9. Codex 动态思考 profile 只能改变实际 `codex_agent_name`，不能改变 canonical `role`；dispatch event 的 `role` 仍写 `meta-dev` / `meta-se` / `meta-qa`。
10. ``process/state/AGENT-DISPATCH-LEDGER.ndjson` platform capability event.required_tools` 必须列出 `spawn_agent` / `resume_agent` / `send_input`；`process/state/AGENT-DISPATCH-LEDGER.ndjson codex_reasoning_profiles event` 必须保存 `meta-dev-debugger`、`meta-se-critical`、`meta-qa-critical` 的默认 / 升级映射。

### 6.0 Codex 动态思考 Profile 调度

Codex 下按下表选择实际 custom agent；Claude Code / OpenClaw 暂不应用该表。

| canonical role | 默认 `codex_agent_name` / 模型 | 默认 profile | 升级条件 | 升级 `codex_agent_name` / 模型 | 升级 profile |
|---|---|---|---|---|---|
| `meta-dev` | `meta-dev` / `gpt-5.6-terra` | `default` | 实现失败超过 2 轮、CP7 回修反复、跨模块 bug、状态机异常、PIT / 数据泄漏 / 数据一致性风险、复杂 flaky test | `meta-dev-debugger` / `gpt-5.6-sol` | `debugger` |
| `meta-se` | `meta-se` / `gpt-5.6-terra` | `default` | 架构冻结、公共 contract、跨模块边界、安全权限、外部接口、长期维护成本或重大 ADR 决策 | `meta-se-critical` / `gpt-5.6-sol` | `critical` |
| `meta-qa` | `meta-qa` / `gpt-5.6-terra` | `default` | CP5 全量设计证据确认、CP7 最终验证、CP8 交付就绪、发布前、安全 / 安装 / 平台路径 / workflow harness 高风险验证 | `meta-qa-critical` / `gpt-5.6-sol` | `critical` |

调度记录必须同时写入 `process/state/AGENT-DISPATCH-LEDGER.ndjson` dispatch events 与 handoff `dispatch`：

- `role` / `canonical_role`：状态机角色，不随 profile 改名
- `codex_agent_name`：实际调用的 Codex custom agent
- `reasoning_profile`：`default|debugger|critical`
- `dispatch_trigger`：命中升级条件或默认阶段原因
- `tool_name`：`spawn_agent` / `resume_agent` / `send_input`

若升级条件命中但对应 profile agent 不存在，或当前 Codex 会话的 `spawn_agent.agent_type` 发现面尚未暴露该 profile，必须阻断并提示重新安装 / 重载 Codex agents；不得静默回退到默认 agent。

### 6.1 Orchestrator Session 登记

Host Orchestrator 主进程会话只保留当前 scalar/ref，不得写入 active agent dispatch 视图。

| 字段 | 说明 |
|---|---|
| `kind` | 固定为 `host` |
| `role` | 固定为 `host-orchestrator` |
| `host_session_id` | 当前主进程会话标识；平台无独立 ID 时可为空，但必须写 `status` 与时间戳 |
| `agent_id` / `thread_id` | legacy 字段，仅用于迁移旧 `host-orchestrator` 子 agent；host 模式默认留空 |
| `status` | `active`、`awaiting-user`、`blocked`、`closed`、`superseded`、`unavailable` |
| `workflow_id` / `active_change` | 当前工作流与活跃变更键 |
| `pending_gate` | 等待人工确认的检查点，例如 `CP8` |
| `pending_checklist_path` | 已提示给用户的人工审查稿路径 |
| `pending_user_decision` | 允许的用户输入与当前等待事项，例如 `approve`、`修改: ...`、`reject`；`1/通过`、`2/修改: ...`、`3/不通过` 仅作历史兼容别名 |
| `next_exact_prompt` | 阶段任务、检查点、Story 实现 / 验证或 CR 收敛完成后给用户的可复制下一步准确提示词；不得只写“同意”“继续”“可以”等模糊词 |
| `pending_decision_ids` | 本轮发起消息中实际展示给用户的 DQ ID；必须与 Decision Brief 和 `GATE-LEDGER.ndjson` gate event 一致 |
| `pending_non_authorized_items` | 本轮 approve 不代表授权的事项，尤其是真实运行、凭据、外部接口、数据写入、publish、live / 交易类操作 |
| `resume_instruction` | 用户回复后由同一主进程继续读取 `STATE.current.json`、回填 checkpoint 并推进；不得 spawn 编排子 agent |
| `subagent_auto_dispatch` | `enabled` / `disabled`；同工作流真实子 agent 调度授权状态 |
| `spawned_at` / `last_seen_at` / `awaiting_since` / `resumed_at` / `closed_at` | 编排器生命周期时间 |
| `previous_agent_id` / `previous_thread_id` | legacy 迁移字段，记录被废弃的旧 `host-orchestrator` 编排子 agent 标识 |
| `superseded_by` | legacy 迁移字段，记录替代旧编排子 agent 的 host session |
| `recovery_reason` | 仅当从旧 `host-orchestrator` 子 agent 或损坏状态恢复时填写 |

规则：

1. 发起 CP2 / CP3 / CP5 / CP8 关键人工检查点时，必须将 `status=awaiting-user`，并写入 `pending_gate`、`pending_checklist_path`、`pending_user_decision`、`next_exact_prompt`、`pending_decision_ids`、`pending_non_authorized_items`、`resume_instruction` 和 `awaiting_since`。Codex 可用 `meta-flow ask-user human-gate --checkpoint <process/checkpoints/CP*.md> --format codex-json` 生成 `request_user_input` 负载；不可用时发送 exact-text fallback。
2. 用户确认、修改或拒绝后，Host Orchestrator 必须在当前主进程中重新读取 `STATE.current.json` 和相关检查点，回填人工结果并继续；不得使用 `spawn_agent` / `resume_agent` / `send_input` 启动或恢复编排子 agent。
3. 回填 `approve` 或自动 CP `PASS` / `WAIVED` 后必须执行 post-approval transition loop：读取 active CR 的 `route_plan`，连续执行后续所有 `human_gate=none` 且未被阻塞的 CP / 阶段准备，直到到达下一个 `human_gate=required` 的 CP2 / CP3 / CP5 / CP8、`delivered`、`FAIL` / `BLOCKED` / `NEEDS_REWORK` / `NEEDS_DESIGN_CLARIFICATION`、授权边界或 workflow health 阈值。停下时必须在 `STATE.current.json.next_action.stop_reason` 或等价状态中写入 `required_human_gate`、`blocked`、`needs_rework`、`needs_design_clarification`、`authorization_required`、`workflow_health_threshold`、`delivered` 或 `no_remaining_route`；只写 approval ledger 不算完成。
4. CP4 是 `human_gate=none` 的自动 CP；当 route plan 中 CP4 `decision=PASS` 且后续 CP5 `human_gate=required` 时，当前状态不得停在“等待用户继续 / 推进 CP5”，必须已打开 CP5 gate，或写明合法 `stop_reason`。该规则用 `meta-flow check state-transition --route-plan <route-plan.json> --result <CP4-result.json> --project-root .` 回归验证。
5. CP2 / CP3 / CP5 / CP8 人工门禁 approve 后，必须用 `meta-flow check state-transition --route-plan <route-plan.json> --approved-gate CP{n} --project-root .` 验证已经推进到下一个 required gate、`delivered` 或合法 `stop_reason`。
6. CP result 通过、人工门禁 approve、关闭 CR、推进阶段或推进 `delivered` 后，必须运行 `meta-flow cp result-check --result <process/checks/CP*.result.json> --check-consistency --project-root .` 和 `meta-flow cr status-sync --id <CR> --status <status> --project-root .`，确保 CR frontmatter、summary、index、`STATE.current.json` 和 lifecycle ledger 同步。
7. 回填人工结果、关闭 CR、推进阶段或推进 `delivered` 前，必须重新读取 `STATE.current.json`、对应 `process/checks/CP*.result.json`、`process/checkpoints/CP*.md`、活跃 formal CR 和下游引用；事件写入 native ledger，由 renderer 更新人类摘要。
8. 若发现旧 `host-orchestrator` 编排子 agent 状态，必须迁移为 host scalar/ref，将旧 agent 标识写入 archive 或 dispatch ledger，并记录迁移原因。
9. 若同时发现多个活跃的 legacy 编排子 agent 记录，必须阻断推进，要求人工选择保留的状态来源并关闭 / 标记其余记录为 `superseded`。
10. 若 CR 模板的自动终验授权字段有效，且 CP8 自动预检 `PASS`、无 `BLOCKING` / `REQUIRED`，允许将人工结果写为 `approved` 并标注 `approval_source=user-preauthorized`；否则仍按默认人工确认处理。

dispatch ledger 或 handoff `dispatch` 中每条记录必须使用以下字段。平台没有提供的字段可以为空，但 `completed` 状态必须满足证据规则。

| 字段 | 说明 |
|---|---|
| `role` | 目标功能 Agent，例如 `meta-dev`、`meta-qa` |
| `codex_agent_name` | Codex 实际 custom agent 名称，例如 `meta-dev-debugger`；非 Codex 平台可为空 |
| `reasoning_profile` | `default`、`debugger` 或 `critical`；非 Codex 平台可为空 |
| `dispatch_trigger` | 选择该 agent/profile 的可枚举触发条件 |
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
4. CP6 / CP7 推进前必须交叉检查 `process/state/AGENT-DISPATCH-LEDGER.ndjson` dispatch events 与对应 handoff frontmatter；任一方缺失证据时，检查点必须失败。

## 输出文件 / 输出模板

| 对象 | 路径 | 用途 |
|---|---|---|
| 运行时状态 | `process/state/STATE.current.json` | 当前状态机机器真相 |
| 状态模板 | `skills/state-router/templates/STATE-TEMPLATE.md` | 初始化与结构基线 |
| CR 跟踪索引 | `process/changes/CR-INDEX.json` | active / blocked / candidate / spike_candidate / conflict 的机器可查询索引 |
| 自动检查结果 | `process/checks/CP*.result.json` | 自动检查点和自动预检机器证据；`*.summary.md` 仅为人类摘要 |
| 人工审查稿 | `process/checkpoints/CP*.md` | 人工检查点 checklist 与审查结果 |

## 约束

- 只负责状态判断、推进决策与状态回写，不生成需求/设计/实现内容
- 推进前必须验证当前阶段退出条件，不能用“默认通过”代替检查
- 推进前必须验证对应 CP 结果文件；不能只看文档 frontmatter 的 `confirmed=true`
- CP4 只作为自动预检门；不得要求 `process/checkpoints/CP4-STORY-PLAN-REVIEW.md` 才推进
- `approve` 回填和自动 CP 通过不是本轮终点；除非遇到 required human gate、delivery 或合法 `stop_reason`，不得把状态停在等待用户“继续”
- 回退必须记录原因、发起方和目标阶段
- Agent 复用必须使用 exact key，不得用模糊角色名匹配替代
- 并行队列必须由 Story DAG、依赖类型和文件所有权计算，不得只按 Wave 名称粗略并行
- 仅使用当前 `process/state/STATE.current.json`、`delivery/rules/DELIVERY-RUNTIME-CONTRACT.json` 与 native renderer 契约；模板只服务人类摘要兼容

## CR-058 merged gate 与恢复路由

1. CP3 与 CP5 可由同一个 `interaction_id` 发起，但必须分别检查 subgate evidence、result 和 receipt；任一 subgate 非 pass-like 都停止传播。
2. facts、scope、authz 或 revision 变化时，必须创建新的 Decision Bundle revision，只装配 delta、capsule ref 与 `read_expansion_log`，不得复用旧 approval。
3. approval 回填后连续执行所有 `human_gate=none` 节点，直到 required gate、授权边界、失败或稳定 stop reason。native CR 状态必须通过一次 batch status-sync 投影 formal、正文状态表、Checkpoint Index、summary、ledger 与 formal-only index。
4. 失败先分类为 `CHECK_HARNESS_ERROR`、`DETERMINISTIC_SCHEMA_REPAIR`、`REAL_CONTENT_FAILURE` 或 `PARTIAL_MUTATION`。G0 / G1 / G2 单检查恢复上限为 `1 / 2 / 2`；drift、真实内容失败、部分 mutation 和未知失败不得自动恢复。
5. G0 / G1 只路由 affected-check targeted revalidation；G2/G3 同一 finding 最多 2 次独立 re-QA，第 3 次路由 `NEEDS_DESIGN_CLARIFICATION`。GovernanceRiskProfile V2：G2=scope-goal-note；G3=原 G2 完整流程（等价 V1 G2）；只有用户显式选择 G3。

## 验收标准

- [ ] `STATE.current.json` 的阶段与下一步动作与实际产物状态一致，且 generated `STATE.md` 通过 exact render 检查
- [ ] 初始化前已完成 logical-ref 路由健康检查；默认 sibling-binding 下不存在 `process` 软链接，legacy `relative-symlink` 仅在独立授权下验证
- [ ] 初始化时机器状态通过 native schema，route metadata 与 reciprocal binding 一致
- [ ] `process/checks/CP*.result.json` 与 `process/state/CHECKPOINT-LEDGER.ndjson` 与 `process/checks/CP*.md`、`process/checkpoints/CP*.md` 的结论一致
- [ ] `approve` 或自动 CP `PASS` 后已通过 `meta-flow check state-transition`，证明状态推进到下一个 required gate、`delivered` 或合法 `stop_reason`
- [ ] CP result / CR 状态变更后已运行 `meta-flow cp result-check --check-consistency` 和 `meta-flow cr status-sync --id <CR>`
- [ ] 推进 / 回退操作均追加 `history`
- [ ] 同一任务同角色不会重复登记活动 agent，检查点完成后有关闭动作
- [ ] `lld_ready` / `dev_ready` / `verify_ready` 的每个 Story 均能解释依赖和文件所有权依据
- [ ] 活跃阶段委托不会被 host-orchestrator 越权代写或越权发起 CP2 / CP3
- [ ] CP2 推进前会检查 `SCENARIOS.yaml`、`TEST-MATRIX.md`、`STORY-MAP.md`、`MVP-SCOPE.md` 的存在性或 CP2 N/A / WAIVED 证据
- [ ] CP3 推进前会检查 `BLUEPRINT.md`、`DOMAIN-MAP.md`、`DEPENDENCY-MAP.md` 的存在性、HLD 消费关系或 CP3 N/A / WAIVED 证据
- [ ] CP7 推进前会检查 `verification-execution` 证据、`docs/quality/VERIFICATION-REPORT.md` 或等价摘要，以及 `TEST-MATRIX.md` 到 `VERIFICATION-REPORT.md` / `TEST-REPORT.md` / `REVIEW.md` 的追溯，或 CP7 N/A / WAIVED 证据
- [ ] CP8 推进前会检查 `process/release/RELEASE-CONTEXT.yaml`、`release_artifact_profile`、`release_decision`、`RELEASE-NOTES.md`、`DEPLOY-CHECKLIST.md`、`ROLLBACK.md`、`MIGRATION.md`、`FEEDBACK.md`，或 CP8 N/A / WAIVED 证据
- [ ] `lld_clarification_queue` 无未回答阻断项时才允许进入 CP5
- [ ] CP5 发起前已通过 `meta-flow story cp5-context-check` 和每份设计证据的 `meta-flow story lld-check`
- [ ] 阻塞状态下返回明确阻塞原因
- [ ] 状态查询必须列出 active formal CR、blocked formal CR、follow-up candidate、spike_candidate 和 stale_status_conflicts
- [ ] `meta-flow check cr-tracking` 能识别 `STATE.current.json.active_change` 指向已关闭 CR、多个 active CR、台账候选与正式 CR 文件不同步等问题
- [ ] 长期路线查询已读取 PROJECT、其 roadmap_ref 和全部 declared phase_refs，并明确显示读取闭包
- [ ] active Phase 详细计划只从其 result_refs 读取；未执行 sibling discovery 或全历史扩读
- [ ] 新 Phase 建议包含重叠矩阵；可归入现有 Phase 的目标已路由为 Work/工作流
- [ ] 长期路线回答已区分机器事实、解释/推断和建议，且未以 memory 覆盖仓库真相

## 不适用边界

- 任务要求生成需求、设计、代码或文档本体
- 当前请求仅需要查看某个单独文件内容，不涉及状态推进

## Gotchas

- `story-execution` 是开发/验证阶段状态，不替代单个 Story 的生命周期；Story 状态仍以 `story-manager` 维护的卡片为准
- LLD 必须在 story-planning 内覆盖全部目标 Story 后统一确认，开发不能绕过全量 CP5 人工确认和 `dev_gate`；特别是 `runtime` 依赖默认等上游 `verified`
- 并行 LLD 阶段不要让多个 meta-dev 同时直接问用户；应让 meta-dev 写 clarification item，由 host-orchestrator 合并后统一提问
- `delegated_interaction.status=returned` 只表示功能 Agent 阶段交还，不等于 CP2 / CP3 人工确认已通过
- 同一 Wave 内也可能因文件冲突串行；不同 Wave 的 Story 可以提前写 LLD，但不得在全量 CP5 通过前进入开发
- fast-lane 只能减少文档厚度和人工门数量，不能跳过 CP6 / CP7、`verification-execution` 证据摘要、Agent Dispatch Evidence 或 CP8 终验摘要
- 当存在活跃 `CR-*` 时，应优先收敛变更影响，再判断是否允许推进
- 当 active CR 命中产品基线重整条件时，必须优先路由到 `requirement-clarification` / `meta-pm` / CP2；CP2 approved 前不得进入 Story 拆解、LLD 设计批次或实现
- “唯一 active CR”不等于“没有后续 CR 候选”；follow-up tracking 中的 candidate / spike_candidate 必须作为 backlog 显式展示
- “没有 active Work”不等于“没有 active Phase 或长期路线”；阶段问题必须沿 PROJECT→ROADMAP→全部 declared phase_refs 查询
- 不要因为 5 对象默认预算而漏掉 Roadmap 声明的第 4 个 Phase；使用声明闭包的有界例外，同时禁止 sibling discovery
- 不要把实施步骤、Wave 或短期 CR 直接升格为长期 Phase；先做重叠矩阵，优先归入现有 Phase 的 Work/工作流
- 不要让 project memory、旧 HLD 或最近一次会话摘要替代当前 Project/Roadmap/Phase 机器事实
- 当 CR 影响 Story、LLD、接口契约、文件所有权、`dev_gate` 或实现设计时，必须先形成 CR 影响范围的 `lld_design_batch`，批次确认前不得进入开发
- 首次初始化时只允许从 `skills/state-router/templates/STATE-TEMPLATE.md` 复制，不允许凭空脑补字段
- 首次初始化时不要直接 `mkdir process` 或手写 `STATE.md`；应使用 binding-aware native 初始化入口创建机器 state，再由 renderer 生成摘要。
- 自动检查点失败时，不要发起人工确认；先把失败结果写入 `process/checks/CP*.result.json` 和 checkpoint ledger，并路由给责任 agent 修复
- 不要把 `delivery/skills/*/templates/` 中的模板文件当成运行态产物；只有 `docs/`、`process/`、`process/checkpoints/`、`delivery/` 中对应产物或 CP 自动检查里的逐项 N/A / WAIVED 说明才可作为推进证据
- N/A / WAIVED 必须写明原因、影响范围和后续触发条件；空泛写“不适用”不能作为阶段推进证据
