# Meta Flow Delivery Package

本目录是可独立交付的 Meta Flow 产物包，包含：

- `agents/`：交付 Agent 定义
- `skills/`：交付 Skill 定义及其私有运行时资产
- `rules/`：平台规则文件
- `scripts/`：安装器入口
- `doc/PLATFORM-CONTRACTS.yaml`：平台安装路径契约；安装器和校验脚本以此为路径真相源

## 输出分层

生产项目中的默认输出分为三层：

- `docs/`：长期可交付文档。产品与范围写 `docs/product/`，蓝图 / HLD / ADR / Feature 设计矩阵写 `docs/design/`，Feature 级设计写 `docs/features/<feature>/`，质量报告写 `docs/quality/`，发布资料写 `docs/release/`。
- `process/`：运行过程文档。`STATE.md`、`REQUEST.md`、执行计划、Story 卡片、CR、discussion、handoff 和自动检查结果都留在这里。
- `process/context/`：阶段上下文胶囊 / context pack。CP2 / CP3 / CP5 / CP6 / CP7 / CP8 的子 agent、人工门禁、验证和发布准备默认先读取这里，只消费 `allowed_reads`，减少重复读取全文档。
- `process/checkpoints/`：人工确认态。CP2 / CP3 / CP5 / CP8 的 Decision Brief、checklist 和人工审查结果写入这里。

旧项目里的 `process/USE-CASES.md`、`process/HLD.md`、根目录 `checkpoints/CP*.md` 等路径只作为 legacy fallback 读取；新工作流在无目标项目约定时默认生成到 `docs/...` 与 `process/checkpoints/...`。如果目标项目已有交付目录或 README/docs 已定义自己的文档目录，production 模式必须优先遵守目标约定；无约定时由 host-orchestrator 提出路由建议并等待用户确认。

外置 process / docs 路由必须使用锚点 + 相对路径，不能把 `/home/...`、盘符或设备专属根目录写入 `STATE.current.json.artifact_routing_ref` 与 `process/.meta-flow-process.yaml`、`process/.meta-flow-process.yaml` 或发布 / 迁移文档。默认记录方式为：`artifact_root` 相对 `project_root`，`project_process_root` 相对 `artifact_root`，`link_path` 相对 `project_root`。例如源码仓库旁边放置 artifact 仓库时，记录 `artifact_root=../meta-flow-artifacts`、`project_process_root=process/<project-name>`、`link_path=process`。

## CP2 / CP3 讨论增强

标准模式下，Meta Flow 会在两个关键人工门前加强讨论，但不新增 CP 编号或独立人工门：

- CP2 前，`meta-pm` 先识别 3-4 个 `Scenario Gray Areas`，让用户选择 1-3 个重点讨论；未选但有价值的想法进入 `Deferred Ideas`，不污染当前 scope。
- CP3 前，`meta-se` 先识别 `Architecture Gray Areas` 并在阶段委托内直接与用户完成 advisor table-first 讨论；需要额外 reviewer lane 时由 `host-orchestrator` 汇总。advisor lane 优先使用 `Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch` 表格。
- HLD 必须记录适用性矩阵、Use Case → Architecture Traceability、关键场景模拟、优化 / 牺牲 / 切换条件和自审结果。

讨论日志写入 `process/discussions/`，恢复点写入 `process/checks/`：

| 阶段 | Discussion Log | Discussion Checkpoint |
|---|---|---|
| CP2 | `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md` | `process/checks/CP2-DISCUSSION-CHECKPOINT.json` |
| CP3 | `process/discussions/CP3-HLD-DISCUSSION-LOG.md` | `process/checks/CP3-DISCUSSION-CHECKPOINT.json` |

Discussion Log 用于审计和恢复，不替代正式产物。下游 Agent 默认先读取 `process/context/*-CONTEXT.yaml` 或 `process/context/*.context.json`；必要时再展开读取正式的 `USE-CASES.md`、`REQUIREMENTS.md`、`SCENARIOS.yaml`、`TEST-MATRIX.md`、`HLD.md`、`ARCHITECTURE-DECISION.md`、`FEATURE-DESIGN-MATRIX.md` 或 Decision Brief。展开全文前必须记录 `full_doc_read_reason`，且原因必须属于 context pack / `READ-POLICY.json` 的允许枚举。

复杂项目的异步 power mode（如 `process/discussions/CP2-QUESTIONS.json/html`、`CP3-QUESTIONS.json/html`）保留为后续可选增强，本交付包不默认生成这些文件，也不把它们作为验收前置。

## 阶段委托与 LLD 问题队列

Meta Flow 的交互路径分两类：

- `requirement-clarification`：host-orchestrator 启动或复用 `meta-pm` 后，将阶段内用户交互权委托给 `meta-pm`。用户可直接与 `meta-pm` 多轮讨论 Scenario Gray Areas、场景和需求草案；草案确认“可提交给 host-orchestrator 汇总”后，`meta-pm` 写交还摘要，host-orchestrator 回收并发起 CP2。
- `solution-design`：host-orchestrator 启动或复用 `meta-se` 后，将阶段内用户交互权委托给 `meta-se`。用户可直接与 `meta-se` 讨论 Architecture Gray Areas、advisor table 和 HLD 草案；草案确认“可提交给 host-orchestrator 发起 CP3”后，`meta-se` 写交还摘要，host-orchestrator 回收并发起 CP3。
- `story-planning` 的并行 LLD：多个 `meta-dev` 不直接并发问用户。实现灰区写入 `process/state/QUESTION-LEDGER.ndjson` 或 CP5 context queue ref，由 host-orchestrator 作为 question broker 合并、排序、批量询问用户、回填答案并分发给对应 `meta-dev`。

阶段委托状态写入 `handoff/context delegated_interaction ref or STATE.current.json.active_delegation_ref`。这只代表阶段内交互权委托，不代表 CP2 / CP3 已通过。LLD clarification 队列存在未回答 `blocks_lld=true` 项时，host-orchestrator 不得发起 CP5；转 OPEN / Spike 的项必须在 CP5 Decision Brief、完整 LLD 或 Story 技术说明、DEV-LOG 中暴露。

## 工作流检查点

安装后的 Meta Flow 使用 CP0-CP8 检查点。自动检查结果写入目标项目的 `process/checks/CP*.md`；阶段上下文胶囊写入 `process/context/*-CONTEXT.yaml`；关键人工审查稿写入 `process/checkpoints/CP*.md`。CP2 / CP3 / CP5 / CP8 由 `host-orchestrator` 发起人工确认，发起前必须生成 Context Capsule、Decision Brief 和待人工决策清单，并提示具体 checklist 文件路径。Decision Brief 必须包含审批者摘要和决策分层：审批者摘要说明本次确认服务的整体目标、推荐动作、`approve` 后会发生什么、`approve` 不授权什么、不确认会阻塞什么；决策分层区分必须用户决策、高风险策略确认、agent 默认处理和仅审计记录。待人工决策清单的状态机对象是 `process/checkpoints/CP*.md` Decision Brief 与 `process/state/GATE-LEDGER.ndjson`，逐项列出决策 ID、决策类型、待确认问题、推荐方案、至少 1 个备选方案（优先 2 个）、优劣分析、影响 / 风险和回退 / 切换条件；用户回复 `approve` 表示接受清单内全部推荐方案。审查后必须回填“人工审查结果”。CP4 只生成自动预检并汇入 CP5。

人工门禁发起消息必须同时合规：包含 checklist 路径、自动预检结论、Context Capsule 摘要、审批者摘要、决策分层、决策收集覆盖摘要、待决策项数量、待决策表格或压缩后的 blocking / high-risk 决策摘要和三个 exact 回复。checkpoint 文件中的 Decision Brief 必须完整；对话可按 `decision_brief_profile=full|compact|summary` 压缩，但不能省略整体目标、`approve` 后果、不授权边界和阻塞影响。低风险、可回退、实现细节类事项默认归入 agent 默认处理或仅审计记录，不进入用户主确认表。真实运行、凭据、安全、外部接口、数据写入、publish、live / 交易类事项必须作为不授权项单独列出；`approve` 不代表授权这些操作。CP8 必须输出 follow-up tracking 分流：关闭范围、不授权范围、风险接受项、后续 CR 候选项、取消 / deferred 项。后续 CR 候选只进入 `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md` 台账，用户决定推进某项时才创建正式 CR。

阶段任务、检查点、Story 实现 / 验证或 CR 收敛完成后，Host Orchestrator 必须给出可直接复制的“下一步准确提示词”，例如 `approve`、`修改: <具体修改点>`、`reject`、`执行下一步: <具体动作>` 或 `处理阻塞: <具体处理方式>`；不得只提示用户回复“同意”“继续”“可以”。`meta-flow next` 遵守同一输出规则。

Codex 平台没有 Claude Code frontmatter `tools: AskUserQuestion` 的同构 agent 字段。Host Orchestrator 在当前 Codex 工具面明确提供 `request_user_input` 时，可用 `meta-flow ask-user human-gate --checkpoint <process/checkpoints/CP*.md> --format codex-json` 生成结构化提问负载；不可用时发送命令输出中的 exact-text fallback。生成或维护发起消息后，仍必须用 `meta-flow check human-gate --checkpoint <path> --launch-message-file <message>` 校验。

启动台账中的后续 CR 时，在当前主进程会话中说明“启动后续 CR”并给出台账路径、候选编号和目标摘要。host-orchestrator 必须先读取台账、`STATE.current.json.active_change`、`process/changes/CR-INDEX.json`、`process/state/CR-LEDGER.ndjson` 和活跃 `process/changes/CR-*.md`，做 CR 冲突预检；`CR-INDEX.yaml` 若存在，只能作为 legacy read-only fallback。`candidate` / `spike_candidate` 不占执行锁；候选项转正式 CR 后才把台账状态、`CR-INDEX.json` 和 `CR-LEDGER.ndjson` 改为 `active`，写入正式 CR 路径。若已有未完成 CR 且影响面重叠，默认不得并行推进，必须让用户在合并到现有 CR、保持候选等待、标记 `blocked`、拆分无冲突子集或 `superseded` 中选择。

状态查询必须列出 `active formal CR`、`blocked formal CR`、`follow-up candidate`、`spike_candidate` 和 `stale_status_conflicts`，不能只返回唯一 active CR。若目标项目存在 `meta-flow check cr-tracking`，host-orchestrator 在状态盘点、候选 CR 启动、CR 关闭和 CP8 follow-up 分流后运行或记录跳过原因；该脚本会检查 `STATE.current.json.active_change`、正式 CR、follow-up 台账和 `CR-INDEX.json` 的一致性，并默认阻断 legacy YAML。

CR lifecycle 的机器入口是 `process/changes/CR-INDEX.json`、`process/changes/summaries/CR-*.summary.json`、`process/state/CR-LEDGER.ndjson` 和 `process/state/CHECKPOINT-LEDGER.ndjson`。完整 `process/changes/CR-*.md` 只在人工审计、冲突排查、深度评审或用户明确要求时展开。常用命令：

```bash
meta-flow cr summary --id CR-101 --project-root .
meta-flow cr index --project-root .
meta-flow cr brief --id CR-101 --project-root .
meta-flow cr brief --id CR-101 --mode enforce --project-root .
meta-flow cr impact-report --project-root .
meta-flow cr impact-report --mode enforce --project-root .
meta-flow cr check --project-root .
meta-flow cr conflicts --id CR-101 --project-root .
```

新 CR 应优先写结构化影响面字段：`impact_capability_refs`、`impact_feature_refs`、`impact_module_paths`、`impact_policy_refs`、`impact_process_refs`、`impact_runtime_refs`、`impact_data_refs`。旧 `impact_surface` 兼容读取，但迁移报告必须暴露无法分类的 `uncategorized_legacy`，并把需要人工分类的条目变成 follow-up candidate 或显式风险。项目可用 `process/project/IMPACT-SURFACE-RULES.yaml` 配置 legacy impact 分类规则；配置修改后必须重新运行 impact report、CR lifecycle check 和相关测试。

上下文预算检查使用 `meta-flow doctor tokens --project-root .`、`meta-flow doctor context --project-root .` 和 `meta-flow doctor artifacts --project-root .`。第一阶段采用零依赖估算 `ceil(char_count / 4)`，用于发现默认读取集合中的大文件、检查 `STATE.md` / summary / LLD / CP check 等 artifact 是否超出 `process/policies/ARTIFACT-BUDGETS.json` 或内置默认预算。`doctor context` 会读取 `process/state/READ-EXPANSION-LEDGER.ndjson`，统计 `frequently_expanded_files`、`frequently_expanded_features`、`missing_context_slots`、`expansion_reason_distribution`、`estimated_extra_tokens` 和 `summary_update_recommendations`，用高频全文读取反推 Feature summary 或 Story packet 缺口。

Context pack 使用 `meta-flow context build --stage <CP2|CP3|CP5|CP6|CP7|CP8> --profile <profile> --cr <CR-ID> --project-root .` 生成，并用 `meta-flow context check --context <path> --project-root .` 校验。context pack 必须包含 `STATE.current.json`、CR index / CR summary、read policy、预算信息、deny-default 集合和全文读取理由枚举；`allowed_reads` 不得包含 `process/STATE.md`、`process/DEVELOPMENT-PLAN.yaml`、完整 `process/changes/CR-*.md` 或全量 Story LLD / IMPLEMENTATION。`process/policies/READ-POLICY.json` 是默认读取策略的机器真相源；缺失时 `context build` 会写入内置默认策略。

Story Context Contract 使用 `process/context/stories/*.json` 作为 Story 级最小上下文契约。`meta-flow context build-story-packet --story <process/stories/STORY-*.md> --stage BASE|CP6|CP7 --project-root .` 会生成 base context、CP6 work packet 或 CP7 verify packet；`meta-flow context check-story-packet --packet <path> --project-root .` 会校验预算、deny-default、Story/CR/state/read-policy refs、`feature_refs`、`feature_design_refs`、`lld_policy`、`allowed_write_paths`、`forbidden_write_paths`、acceptance 和 verification plan。`meta-flow context sufficiency-check --packet <path>` 会额外检查上下文足够性，确认 packet 是否包含最低充分上下文：`objective.summary`、Feature context 摘要或 summary ref、`cr_delta.summary`、`dependency_inputs`、读写边界、acceptance、verification plan、authz policy refs 和 expected return packet；`architecture-major`、`product-redesign`、`runtime-high-risk` 缺关键槽位时失败，普通 profile 默认给出 warning。Story agent 默认只消费 packet 的 `allowed_reads` 和写入边界；full LLD 只进入 `read_if_needed`，不得默认塞入 `allowed_reads`。CP6 packet 必须声明 `expected_return_packet`，CP7 packet 必须声明 `implementation_return_ref` 和 `expected_return_packet`。

Read Expansion Governance 使用 `process/state/READ-EXPANSION-LEDGER.ndjson` 记录所有 deny-default 全文读取。需要展开读取 `process/STATE.md`、`process/DEVELOPMENT-PLAN.yaml`、完整 CR、全量 Story LLD / IMPLEMENTATION 或其他 deny-default 文件时，优先通过 `meta-flow context read-log --path <path> --reason <allowed-reason> --stage <CP> --agent <role> --context-ref <context-ref> --project-root .` 写入事件，再用 `meta-flow context read-log-check --project-root .` 校验。`reason` 必须属于 `READ-POLICY.json.full_doc_read_allowed_when`；CP result 若直接引用 deny-default 文件，必须提供 `read_expansion_refs`，并且 refs 要覆盖 `READ-EXPANSION-LEDGER` 中的对应路径。

Agent / Skill Contract 使用 `delivery/rules/AGENT-SKILL-CONTRACT.md` 作为共享瘦身契约，目录与分区 contract 使用 `delivery/rules/DIRECTORY-CONTRACT.md` / `.yaml`。五个功能 Agent 必须先读阶段 context pack 或 Story packet，默认机器状态入口是 `process/state/STATE.current.json`，默认文件系统发现入口是 `process/current/CURRENT.json`，并且只读取 `allowed_reads` / `must_read`；`process/STATE.md`、`process/DEVELOPMENT-PLAN.yaml`、完整 CR、全量 Story LLD、`process/archive/**`、完整 TEST-REPORT / REVIEW / diff 都属于 `do_not_read_by_default`。需要全文读取时必须写入 `full_doc_read_reason`，且原因只能是 `capsule_missing`、`field_conflict`、`human_audit`、`deep_review` 或 `schema_validation_failed`。Handoff 只传 `context_ref` / `story_packet_ref` / `evidence_ref` / `result_ref`，真实执行证据写入 handoff / dispatch / checkpoint ledgers。

Story Return / Evidence / Design Delta 使用结构化产物闭合 Story 交接。`process/returns/STORY-*.return.json` 记录 agent 实际 touched files、contract changes、boundary check、verification commands、risk 和 next route；`meta-flow story return-check --packet <work-or-verify-packet> --return <return-packet> --project-root .` 校验 story/stage 匹配、写入路径是否落在 `allowed_write_paths`、是否触碰 `forbidden_write_paths`、是否有 unexpected imports、成功状态是否提供验证证据，以及 `design_delta_required=true` 时是否声明 `design_delta_ref`。`meta-flow story evidence-index --return <return-packet> --project-root .` 生成 `process/evidence/STORY-*.index.json`，`meta-flow story evidence-check --index <index> --project-root .` 校验证据索引。Story 修改长期设计时写 `process/design-deltas/STORY-*.delta.json`，用 `meta-flow design delta-check --delta <delta> --project-root .` 校验结构；CP8 前使用 `--require-merged` 强制所有需要回写 Feature DESIGN / ADR / HLD 的 delta 已合并。CP6 return 可以用 `meta-flow story verify-packet --from-return <CP6-return> --story <story-card> --project-root .` 生成 CP7 verify packet。

CP Result / Event Ledger 使用机器可读结果和事件台账降低 CP 文档膨胀。`process/checks/CP*.result.json` 是 CP 自动检查机器真相源，`process/checks/CP*.summary.md` 是可渲染人类摘要；`meta-flow cp result-check --result <result> --project-root .` 校验 schema、状态枚举、blocker 与 decision 一致性，CP6 / CP7 还要求 `story_id`、`context_ref`、`dispatch_refs` 和 `evidence_ref`。`meta-flow cp render-summary --result <result>` 生成摘要，`meta-flow cp ledger-append --result <result> --project-root .` 追加 `process/state/CHECKPOINT-LEDGER.ndjson`。`meta-flow event check --ledger <ledger> --type checkpoint|handoff|dispatch|run|gate` 校验 NDJSON 事件台账；`HANDOFF-LEDGER` 记录交接事件，`AGENT-DISPATCH-LEDGER` 记录真实子 agent 调度证据，`RUN-LEDGER` 记录命令运行证据。Markdown 检查文件可保留审计摘要，但不得替代 result JSON、evidence index 和 ledger。

CP8 result 可包含 `fact_diff`，用于把 CP2 承诺、CP7 evidence alignment、剩余风险和 release decision 放在同一张机器可读差异表里。`release-readiness` 先生成 `process/release/RELEASE-CONTEXT.yaml`，再按 `release_artifact_profile=minimal|compact|full` 裁剪 release notes、deploy、rollback、migration 和 feedback 文档；默认不把完整 evidence 正文复制进 release docs。`cp result-check --check-consistency` 会检查 result JSON 与 summary、CR index、STATE 和 checkpoint ledger 的派生状态是否一致。

同一 CR 的 CP 不以内联章节作为真相源。`process/changes/CR-*.md` 只维护 `Checkpoint Index`、状态摘要和 ref；自动 CP 真相源是 `process/checks/CP*.result.json`，人工门禁真相源是 `process/checkpoints/CP*.md`，事件真相源是 `CHECKPOINT-LEDGER.ndjson` / `GATE-LEDGER.ndjson`。不得把 CP result、Decision Brief、review 全文或历史 checkpoint 详情复制进 CR 正文；关闭 CR 后只保留 status + ref 指针。

Story 管理以 `process/DEVELOPMENT-PLAN.yaml` 作为 Story / Wave / status / task 机器真相源。`process/STORY-BACKLOG.md`、`process/STORY-STATUS.md` 和 Feature `TASKS.md` 只能作为 optional legacy / generated views；修改 Story 管理对象后运行 `meta-flow story plan-check --project-root .`，检查 Story 卡、Feature trace 和旧视图是否与 DEVELOPMENT-PLAN drift。

Failure Routing / Waiver Governance 使用 `process/policies/FAILURE-ROUTING.json` 和 `process/policies/WAIVER-POLICY.json` 收敛失败处理与豁免。`meta-flow failure policy-check --project-root .` 校验 route policy，`meta-flow failure route-check --result <CP-result> --project-root .` 校验 `route_on_fail`，兼容入口为 `meta-flow check failure-routing --result <CP-result> --project-root .`。`BLOCKER` / `HIGH` 的 `FAIL` / `BLOCKED` item 必须声明动作式 route：`rework_same_story`、`reopen_cp5_design`、`require_user_decision`、`create_followup_candidate`、`escalate_runtime_high_risk`、`block_release` 或 `waive_with_risk_acceptance`；每个 route 必须定义 `creates`、`updates`、`invalidates` 和 `next_allowed_stage`。`meta-flow waiver policy-check --project-root .` 与 `meta-flow waiver check --result <CP-result> --project-root .` 校验 waiver 的 `scope`、`expires_at`、`approval_ref`、`forces_release_status` 和适用范围。未授权 runtime access、credential / secret exposure、missing dispatch evidence、runtime-high-risk forbidden path、missing human gate、missing read expansion log、missing evidence、false runtime-ready capability claim 等 non-waivable / 不可豁免；需要风险接受的 waiver 不能静默 PASS，必须推动 `PASS_WITH_RISK` 或 CP8 `READY_WITH_RISK`。

Checkpoint route 由 CR type、route traits 与 gate profile 确定；未适用的 CP 必须记录为 `N/A`，只有具备 scope、expiry、approval ref 与 release-status 影响的明确豁免才能记录为 `WAIVED`。人工批准或自动 CP 得到 pass-like 结果后，Host Orchestrator 必须继续消费 route plan，直到下一个 `human_gate=required`、delivered 或明确的 failure / authorization / workflow-health stop reason；`meta-flow check state-transition --route-plan <route-plan> --result <CP-result> --project-root .` 用于校验该推进契约。

真实数据验证可使用 `meta-flow validation run --cr <CR-ID> --profile real-lake-readonly --reruns 2 --project-root .` 生成 validation task、run ledger、evidence index、rerun comparison、admission summary 和 forbidden operation counter 摘要。默认不执行外部命令；只有传入 `--execute --command '<validation command>'` 并具备对应 runtime authorization 时，才会运行真实验证命令。该 wrapper 用于固化 CP7 证据，不授权 lake write、trading、broker、publish 或 credential 操作。

Context-budgeted 端到端回归 fixture 位于 `evals/fixtures/context-budgeted-meta-flow/`，用于验证 `STATE.current.json -> CR summary -> context pack -> Story packet -> Story return -> evidence index -> CP result -> checkpoint ledger` 这条链。对应测试为 `tests/test_context_budgeted_flow_e2e.py`，会证明默认 `allowed_reads` 不包含 `process/STATE.md`、`process/DEVELOPMENT-PLAN.yaml`、完整 CR 或全量 Story LLD。

Governance Truth Map 使用 `process/policies/SOURCE-OF-TRUTH-MAP.yaml` 作为机器可读策略入口，`docs/design/SOURCE-OF-TRUTH-MAP.md` 只是人类说明。`meta-flow governance init --project-root .` 可生成默认 truth map 与 `process/policies/RETENTION-POLICY.json`；`meta-flow governance truth-map-check --project-root .` 校验 `STATE.md`、CP summary、context pack、Story packet、Evidence index、CP result、ledger 等对象的 truth role、edit policy、append-only 和 generated-from 关系；`meta-flow governance retention-check --project-root .` 校验 closed CR summary-only、旧 Story packet deny-default、CP audit appendix high-risk-only 和 ledger latest-window / index 默认上下文策略。兼容检查入口为 `meta-flow check truth-map --project-root .` 与 `meta-flow check retention-policy --project-root .`。

Feature Registry 使用 `docs/design/FEATURE-REGISTRY.yaml` 作为 Feature / bounded context 长期设计所有权入口。`meta-flow feature build --project-root .` 可从 `docs/features/*` 生成初始 registry；`meta-flow feature check --project-root .` 校验每个 Feature 的 `feature_id`、`owner_context`、`status`、`risk_profile`、`module_paths`、`design_doc_policy` 和 `design_doc`；`architecture-major`、`product-redesign`、`runtime-high-risk` 等 profile 必须声明 `product_domain` 和 `capability`，避免 Feature Registry 退化为平面清单。`meta-flow feature trace --project-root .` 校验 Story 是否声明 `feature_refs`、`feature_design_refs` 与 `lld_policy`，且引用的 Feature 必须存在。高风险 Feature / Story 必须使用 `lld_policy=full-lld`。兼容检查入口为 `meta-flow check design-ownership --project-root .` 和 `meta-flow check story-to-feature-trace --project-root .`。长期设计真相源应是 Feature DESIGN / ADR / HLD，Story 只承载本次实现切片的 LLD / technical note / evidence。

Module Boundary 使用 `docs/design/MODULE-BOUNDARIES.yaml` 作为模块 owner、包前缀、路径、允许依赖和禁止依赖的机器入口。`meta-flow module init --project-root .` 可生成初始边界；`meta-flow check module-boundaries --project-root .` 校验配置完整性；`meta-flow check imports --project-root .` 使用 Python `ast` 扫描源码 import，发现 core / data / research 等模块越界依赖；`meta-flow check architecture-fitness --project-root .` 聚合边界、import 和高风险隔离检查；`meta-flow check risk-rings --changed-files <files...> --project-root .` 会结合 changed files / impact terms 与 `GATE-PROFILES` 分类，确保触碰 runtime-high-risk ring 的变更不能被降级。模块边界检查只解析 Python import；非 Python 语言或动态 import 需要后续扩展专用解析器或在 CP 人工审查中补充。

Capability Status 使用 `docs/design/CAPABILITY-STATUS.yaml` 区分 `implemented`、`offline-fixture-only`、`experimental`、`deferred`、`not-authorized`、`future-slot` 等能力状态。`meta-flow capability check --artifact <doc> --project-root .` 或 `meta-flow check capability-claims --artifact <doc> --project-root .` 会检查 README / HLD / 测试说明是否把未实现、未授权或仅 fixture 的能力误写成 implemented / runtime-ready / production-ready。运行授权必须由 `runtime_authorized=true` 和授权门禁共同表达，不能由 README 文案暗示。

Concept Owners 使用 `docs/design/CONCEPT-OWNERS.yaml` 固化概念 canonical owner、conflict key aliases、legacy alias 和 forbidden alias。`meta-flow concept check --changed-files <files...> --project-root .` 或 `meta-flow check concept-overlap --changed-files <files...> --project-root .` 会发现新增或修改文件是否落在 legacy / forbidden alias 上，避免 contracts、manifest、quality、source_registry、runtime 等概念在多个 bounded context 中重复生长。触碰 legacy alias 默认给 warning，触碰 forbidden alias 默认 fail；`conflict_keys` 在 Concept Owners 内统一注册，不单独新增 Conflict Keys registry。

Package Identity 使用 `docs/design/PACKAGE-IDENTITY.yaml` 统一 product name、repo name、Python import、CLI name、legacy alias、package mode 和 public API files。`meta-flow identity check --project-root .` 或 `meta-flow check package-identity --project-root .` 会对照 `pyproject.toml`、包目录、public API 文件和 README，发现 repo / package / import / CLI 漂移。`meta-flow identity scan --project-root .` 额外输出只读 delivery routing 建议，扫描 README / docs 中已有交付约定，并列出 production 项目默认禁止写入的 meta-flow 交付根。对 quant-lab 这类项目，应先明确 `product_name=quant-lab`、`python_import=quant_lab`、`cli_name=qlab`、legacy alias 和 package mode，再推进 README、测试和交付包迁移。

Gate profile 使用 `process/policies/GATE-PROFILES.json` 分级。`meta-flow gate classify --changed-files <files...>` 或 `meta-flow gate classify --impact <terms...>` 会把 docs-only 归入 `docs-lite`，process ledger / checker / context / state 类治理改动归入 `process-lite`，`manifest_schema` / `public_contract` 等架构关键词升级到 `architecture-major`，`credential` / `NAS` / `QMT` / `MiniQMT` / `XtQuant` / `gateway` / `trading` / `publish` 等关键词强制升级到 `runtime-high-risk`。`meta-flow gate plan --profile <profile>` 输出该 profile 的阶段、人工门和 context 预算；`meta-flow gate check` 校验 profile 注册表。

授权边界使用 `process/policies/AUTHZ-POLICY.json` 注册。普通 artifact 只写 `authz_policy_refs`，不得复制 policy 全文；只有人工门禁和 release 决策可用 `meta-flow policy expand <POLICY-ID...>` 展开。`meta-flow policy check --artifact <path>` 会检查高风险词是否缺少对应 policy ref，并发现普通 artifact 中复制 `expanded_text` 的情况。`approve` 仍只表示接受本轮推荐决策，不表示授权 `requires=explicit_*` 的操作。

轻量运行态使用 `process/state/STATE.current.json` 作为机器默认入口，`process/STATE.md` 作为 `meta-flow state render` 生成的人类摘要。新项目可运行 `meta-flow state init --project-root . --project-id <project-name>` 初始化 state v2 和基础 ledgers；完整 adoption 建议优先使用 `meta-flow workspace bootstrap --artifact-root <relative-artifact-root> --project-name <project-name> --project-root .`。迁移和检查命令为 `meta-flow state migrate-v2 --project-root .`、`meta-flow state render --project-root .`、`meta-flow state check --project-root .`。`STATE.current.json` 不得保存 closed CR 长字段、历史正文、检查点全集或授权 policy 全文；这些信息必须以 ledger、summary、policy ref 或 evidence ref 形式引用。

CR 生命周期治理使用 `process/state/CR-LEDGER.ndjson`、`process/changes/CR-INDEX.json` 和 `process/changes/summaries/CR-*.summary.json`；legacy `process/changes/CR-INDEX.yaml` 仅作迁移期只读 fallback。正式 CR 必须声明 `cr_type=product-scope|architecture|feature|refactor|bugfix|docs|process|runtime|release|experiment`；旧 `cr_kind` 会被兼容映射到 `cr_type`。目标项目首次启动可运行 `meta-flow cr bootstrap --id CR-001 --title "<title>" --scope "<scope>" --project-root .`，创建 active bootstrap CR、CR summary/index/ledger、CP0 result/summary 和 CP0 context。关闭 CR 时运行 `meta-flow cr close --id <CR-ID> --readiness <READY|READY_WITH_RISK|NOT_READY>`，必须生成 summary、evidence index、ledger event 并重建 CR index。默认上下文只读取 CR summary / index；完整 `process/changes/CR-*.md` 仅在冲突排查、人工审计、深度评审或用户明确要求时展开。检查入口为 `meta-flow cr check --project-root .` 和 `meta-flow cr conflicts --id <CR-ID> --project-root .`。

## Target Project Adoption Readiness

在目标项目安装 Meta Flow 后，建议先执行只读 readiness，再创建 bootstrap CR：

```bash
meta-flow workspace bootstrap --artifact-root <relative-artifact-root> --project-name <project-name> --project-root .
meta-flow identity scan --project-root .
meta-flow quality init --project-root .
meta-flow doctor adoption --project-root .
meta-flow cr bootstrap --id CR-001 --title "<project> adoption bootstrap" --scope "Initialize Meta Flow adoption readiness." --project-root .
meta-flow context check --context process/context/CP0-CR001.context.json --project-root .
meta-flow check cp-result --result process/checks/CP0-CR-001-BOOTSTRAP.result.json --project-root .
```

`doctor adoption` 不写文件，只聚合 workspace route、state v2、CR tracking、package identity、quality governance、workflow ledgers 和 human gate readiness。它不授权 credentials、runtime、SaaS、production write、trading、publish 或 CR-033 runtime follow-up。

CP6 / CP7 必须包含 `Agent Dispatch Evidence`。handoff 文件只表示交接，不表示目标 agent 已执行；编码和验证完成必须有真实子 agent 调度证据，或用户明确批准的 `inline-fallback`。CP6 还必须记录实现执行证据：复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / 护栏 / 平台适配 / 发布相关 Story 输出完整 `IMPLEMENTATION.md`；低风险 Story 可写 Story 摘要或 DEV-LOG，但必须说明 N/A 理由。CP7 必须记录验证执行证据：验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题和剩余风险、阶段决策。

| CP | 名称 | 类型 |
|----|------|------|
| CP0 | 原始请求受理门 | 自动 |
| CP1 | 用户场景完备门 | 自动 |
| CP2 | 需求基线门 | 自动预检 + 人工 |
| CP3 | 蓝图 / HLD 架构评审门 | 自动预检 + 人工 |
| CP4 | Story 拆解与并行安全门 | 自动预检（汇入 CP5） |
| CP5 | Story 设计证据可实现性门 | 全量 / 批次自动预检 + 人工；含 full-lld / batch-lld / technical-note / waived 证据和 clarification queue 收敛检查 |
| CP6 | Story 编码完成门 | 滚动自动；检查实现执行证据 |
| CP7 | Story 验证完成门 | 滚动自动；检查验证执行证据和结论分级 |
| CP8 | 交付就绪门 | 自动预检 + 人工 |

## 软件开发工作流产物

Meta Flow 的软件开发工作流在 CP2 / CP3 / CP7 / CP8 增加工程化产物，但不新增人工门编号：

| 阶段 | 关键产物 | 边界 |
|---|---|---|
| CP2 前 | `docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/product/STORY-MAP.md`、`docs/product/MVP-SCOPE.md`、`docs/product/RELEASE-SLICES.md` | 用于把用户场景转成工程验证覆盖、产品范围和发布切片；不包含底层实现步骤 |
| CP3 前 | `docs/design/BLUEPRINT.md`、`docs/design/DOMAIN-MAP.md`、`docs/design/DEPENDENCY-MAP.md`、`docs/design/HLD.md` | 蓝图定义 Feature / Epic 边界、领域对象、数据归属和依赖方向；HLD 消费这些边界并给出系统架构 |
| CP6 前 | `process/stories/STORY-*-IMPLEMENTATION.md`、`docs/features/<feature>/IMPLEMENTATION.md`，或 Story 卡片 / DEV-LOG 实现摘要 | 将设计证据转成实现对象、契约映射、测试 / Fixture、最小切片、平台差异、本地验证和交接摘要；复杂 / 高风险等场景强制完整文档，低风险可轻量化 |
| CP7 | `docs/quality/VERIFICATION-REPORT.md`、`docs/quality/TEST-REPORT.md`、`docs/quality/REVIEW.md`、`docs/quality/FIXES.md` | 记录验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、验证命令、覆盖缺口、独立 review findings、回修 / 设计澄清输入和阶段决策；`PASS_WITH_RISK` 风险进入 CP8 |
| CP8 | `process/release/RELEASE-CONTEXT.yaml`、`docs/release/RELEASE-NOTES.md`、`docs/release/DEPLOY-CHECKLIST.md`、`docs/release/ROLLBACK.md`、`docs/release/MIGRATION.md`、`docs/release/FEEDBACK.md` | 发布准备先生成 capsule 摘要，再按 `release_artifact_profile=minimal|compact|full` 裁剪发布产物；`release_decision=READY|READY_WITH_RISK` 可进入终验，`NOT_READY` 阻断，`RELEASED|FAILED` 需要独立真实发布授权；`FEEDBACK.md` 不替代 follow-up tracking 台账 |

## Workflow Eval 与 Prompt Bundle

Meta Flow 通过 `project_kind` 和 `validation_target.sut_type` 在同一主流程内区分纯代码、workflow、prompt-skill、agentic-code 和 mixed 项目。纯代码项目默认使用目标项目原生测试、构建、静态检查和质量评审；workflow / prompt / mixed 对象增加 workflow eval 和 prompt bundle 证据。

本地 eval 命令：

```bash
meta-flow eval validate --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml
meta-flow eval run --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/generated-workflow-basic
meta-flow eval suite-health --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md
meta-flow eval run --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/runtime-workflow-basic
meta-flow eval runtime-run --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --sample RT-GENERIC-FULL-20260617 --platform codex --workspace evals/fixtures/runtime-workflow-basic/runtime/workspace-basic --mode collect --out process/evals/runtime-run
meta-flow eval suite-health --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md
meta-flow eval feedback sync --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/feedback/raw
meta-flow eval feedback normalize --in process/evals/feedback/raw --out process/evals/feedback/run-exec
meta-flow eval feedback triage --runs process/evals/feedback/run-exec --out process/evals/feedback/triage
meta-flow eval release-check --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --runs process/evals/runs --profile release --triage process/evals/feedback/triage --format json --json-out process/evals/release-check.json
```

`WORKFLOW-EVAL.yaml`、`PROMPT-BUNDLE.yaml` 和 `CASE-REGISTRY.yaml` 是 generated workflow / prompt-skill 产物的验证契约。`process/evals/runs/<run-id>/run-summary.json` 是 CP7 的输入证据之一，但 eval run PASS 不等于 CP7 PASS；`verification-execution` 仍必须输出验证对象清单、追踪矩阵、设计契约验证、分层验证计划、问题和风险。

通用 eval 能力包括 `runtime_artifact`、`runtime-run`、`install_mapping`、`feedback sync/normalize/triage/analyze`、`mutate`、`backlog list/check/close`、`suite-health` 和 `release-check`。`runtime_artifact` 只读取已有运行工作区，支持 `RUNTIME-SAMPLE-REGISTRY.yaml`、`sample_ids`、`profile=partial|full|regression`、expected BLOCKED 样本、阶段顺序、内容密度、空文件 / 模板残留、trace chain、Gate、delivery、coverage 和表格检查；`runtime-run` 只负责 dry-run / manual-handoff / collect 证据，生成 RUN-EXEC 与 runtime artifact manifest，不启动 Agent、不判分。真实执行 Agent、git 拉取、外部模型、网络或写远端都必须按授权边界单独处理。feedback 必须先标准化为 RUN-EXEC，再 triage 为 `ISSUE_DRAFT`、`GAP`、`BACKLOG`、`ENVIRONMENT`、`USAGE`、`DUPLICATE` 或 `NO_ACTION`，不能把所有现场反馈自动升级为 ISSUE。`suite-health` 是趋势报告，`release-check` 才是发布门禁，输出 `PASS|PASS_WITH_RISK|BLOCKED` 和机器可读 JSON。

Promptfoo / DeepEval / Langfuse / Garak 默认 disabled。任何网络、凭据、trace 上传、外部模型调用、publish、live 或 production 写入都必须单独形成 `runtime_authorization` 决策项。

## Quality Governance

Meta Flow 提供轻量质量治理 policy，用来把质量模型、eval 矩阵和最小 workflow metrics 固化为可检查契约。初始化命令：

```bash
meta-flow quality init --project-root .
meta-flow quality model-check --project-root .
meta-flow quality eval-check --project-root .
meta-flow doctor quality --project-root .
meta-flow doctor workflow --project-root .
```

`quality init` 会写入：

- `process/policies/QUALITY-MODEL.yaml`
- `process/policies/EVAL-MATRIX.yaml`

这两个文件定义质量维度、eval 映射和派生指标来源。workflow metrics 只从已有 `process/checks/*.result.json`、`process/state/*-LEDGER.ndjson` 和 `process/state/READ-EXPANSION-LEDGER.ndjson` 派生；不要创建或手工维护独立 `WORKFLOW-METRICS` 真相源。默认模板随 `context-manifest-builder` skill 安装，路径是：

- `skills/context-manifest-builder/templates/QUALITY-MODEL-TEMPLATE.yaml`
- `skills/context-manifest-builder/templates/EVAL-MATRIX-TEMPLATE.yaml`

## 子 Agent 调度证据

`host-orchestrator` 调用 `meta-dev`、`meta-qa` 等功能 Agent 时，必须记录平台调度证据：

- Codex：新任务记录 `spawn_agent`，复用任务记录 `resume_agent` 或 `send_input`
- Claude Code / OpenClaw：记录平台 Task/Subagent 标识
- `process/handoffs/*.md` 必须包含 `dispatch` 区，记录 `mode`、`canonical_role`、`codex_agent_name`、`reasoning_profile`、`dispatch_trigger`、`agent_id` / `thread_id`、`tool_name`、`spawned_at` / `resumed_at`、`completed_at`

若当前运行模式不能拉起子 agent，默认阻断。只有用户明确批准时，才允许 `dispatch.mode=inline-fallback`，并必须写明 fallback 原因和批准信息。

用户启动正式工作流后，同工作流内默认允许 `host-orchestrator` 自动拉起所需功能 Agent；该授权只覆盖真实子 agent 调度，不覆盖 inline fallback。

CP6 / CP7 的 `Agent Dispatch Evidence` 中若缺少真实工具调用、`codex_agent_name` / `reasoning_profile` / `dispatch_trigger` 或用户批准的 fallback，Story 不得推进到完成态。

## fast-lane 快速模式

`fast-lane` 用于低风险轻量实现、小型规则 / Skill / Agent 修改和文档更新。它可以减少需求、HLD、LLD、IMPLEMENTATION、VERIFICATION 和 release 文档厚度，发布阶段默认使用 `release_artifact_profile=minimal`，但不能跳过 CP6 / CP7、Agent Dispatch Evidence、实现执行证据摘要、验证执行证据摘要、`RELEASE-CONTEXT.yaml` 或 CP8 终验摘要。命中架构、权限、安全、平台安装、外部接口、文件所有权冲突或多 Story 依赖时，必须升级到 `standard`。

CP2 / CP3 的讨论增强不会强行升级所有小修改；fast-lane 下若 discussion log / checkpoint 不适用，自动检查必须记录 N/A 原因。

## 安装

推荐作为全局命令安装（本地开发建议 editable，便于读取当前 checkout 的 `delivery/` 资产）：

```bash
uv tool install --editable .
meta-flow install codex --scope user
meta-flow install codex --scope project --project-dir /path/to/project
meta-flow uninstall codex --scope project --project-dir /path/to/project
meta-flow install codex --help
meta-flow uninstall codex --help
```

项目级安装未提供 `--project-dir` 时，交互式终端会提示确认当前目录或输入其他目录；非交互环境必须显式传入 `--project-dir`。

从仓库根目录运行：

```bash
uv run --python 3.11 python delivery/scripts/install.py claude
```

或把 `delivery/` 作为独立仓库根目录运行：

```bash
cd delivery
uv run --python 3.11 python scripts/install.py claude
```

支持的平台：

- `claude`
- `codex`
- `openclaw`
- `qoder`

常用示例：

```bash
meta-flow install codex --scope user --component rules
meta-flow install codex --scope project --component full --project-dir /path/to/project
meta-flow uninstall codex --scope project --component rules --project-dir /path/to/project
uv run --python 3.11 python delivery/scripts/install.py claude --dry-run
meta-flow install qoder --scope project --project-dir /path/to/project
```

> **注意**：Qoder 与 Codex 在 project scope 共享 `AGENTS.md`。安装器使用 platform-tagged managed block（`<!-- myflow:managed:begin platform=qoder -->`）隔离各平台内容，卸载一个平台不影响另一个平台的已安装内容。

legacy 兼容示例：

```bash
uv run --python 3.11 python delivery/scripts/install.py codex --scope user --content rules
```

组件参数：

- `rules`：只安装平台规则入口（如 AGENTS.md / CLAUDE.md）。
- `agent`：安装 agents + skills。
- `full`：同时安装 rules 与 agent 组件。

默认值：

- `--scope user` 默认 `--component rules`。
- `--scope project` 默认 `--component full`。
- `meta-flow uninstall <platform>` 未指定 `--component` 时默认卸载 `full`；可用 `--component rules|agent|full` 精确卸载组件。
- legacy `--content all|agents|skills|rules` 保留兼容，但新命令优先使用 `--component`。

## Agent 命令与显示区分

| canonical role | Codex 命令 / nickname_candidates | Codex 模型 | Codex `model_reasoning_effort` | Claude Code color |
|---|---|---|---|---|
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `gpt-5.6-terra` | `medium` | `orange` |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `gpt-5.6-terra` | `high` | `yellow` |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu`、`dev-he`、`dev-lv`、`dev-shi`、`dev-zhang`、`dev-kong` | `gpt-5.6-terra` | `medium` | `green` |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong`、`qa-cao`、`qa-yan`、`qa-hua`、`qa-jin`、`qa-wei` | `gpt-5.6-terra` | `high` | `cyan` |
| `meta-doc` | `doc-cao`、`doc-yan`、`doc-hua`、`doc-jin`、`doc-wei` | `gpt-5.6-luna` | `low` | `purple` |

canonical role 只覆盖功能子 agent，用于状态机、handoff 与检查点审计；Host Orchestrator 是主进程职责，不安装 Codex / Claude Code agent 文件。Codex 使用 `nickname_candidates` 作为命令别名，并从 Codex-only 路由显式写入 `model` 和 `model_reasoning_effort`；Claude Code 文件型 subagent 不使用 nickname，安装器写入 `color` 区分不同子 agent。主进程建议父会话在标准 / 复杂工作流中使用 `model_reasoning_effort="high"`，fast-lane 或小范围机械修改可使用 `medium`。

Codex 还会安装动态思考 profile，但 canonical role 不变：`meta-dev-debugger`、`meta-se-critical` 与 `meta-qa-critical` 使用 `gpt-5.6-sol`，推理等级分别为 `high`、`xhigh`、`xhigh`。Host Orchestrator 调度时必须在 `AGENT-DISPATCH-LEDGER.ndjson` 或 handoff `dispatch` 记录 `canonical_role`、`codex_agent_name`、`reasoning_profile` 和 `dispatch_trigger`。

Codex 主进程启动正式工作流后默认授权真实子 agent 调度；若当前工具面有 `spawn_agent` / `resume_agent` / `send_input`，创建 `mode=subagent` handoff 后必须调用对应工具。只创建 handoff 不能算子 agent 已执行；工具不可用时必须阻断并记录 `subagent_dispatch.available=false`，除非用户明确批准 `inline-fallback`。

## 目录约束

1. `scripts/` 只放安装器入口：`install.py`、`install.sh`、`install.ps1`
2. Skill 私有模板、脚本、示例必须放在 `skills/<skill>/` 目录内
3. Python 缓存文件（`__pycache__/`、`*.pyc`）不得进入交付包
4. Codex Agent 与 Skill 路径分开治理：Agent 在 `.codex/agents` / `~/.codex/agents`，Skill 在 `.agents/skills` / `~/.agents/skills`
5. 安装器写入前会检查路径组件冲突；目标目录任一级被普通文件占用时会 fail fast 并提示修复

## 交付出口路由

当前仓库 `delivery/` 只作为 meta-flow 自身交付包。若工作流服务外部 production 项目，host-orchestrator 必须先扫描目标项目已有交付目录，以及 `README.md` / `README.*` / `docs/` 的交付物或发布约定；存在约定时按目标项目执行，不存在时先提出建议并等待用户确认，不能默认写当前仓库 `delivery/`。

更多使用方式见 `doc/USER-MANUAL.md`。
