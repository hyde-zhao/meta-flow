# Agent / Skill Context Contract

本文件是功能 Agent 与高频 Skill 的共享契约。目标是把“默认多读一点保险”改成“先读最小上下文包，按契约扩展读取，输出只写摘要和引用”。

## Input Contract

1. 必须先读取本阶段 context pack 或 Story packet：
   - 阶段入口：`process/context/CP*-*.context.json` 或 legacy `process/context/*-CONTEXT.yaml`
   - Story 入口：`process/context/stories/*.json`
2. 默认机器状态入口是 `process/state/STATE.current.json`；默认文件系统发现入口是 `process/current/CURRENT.json`，其 status 必须能表达 `idle`、`active`、`awaiting_gate` 或 `blocked`。`process/STATE.md` 只作为人类摘要、迁移兼容或人工审计输入，不得作为子 agent 默认读取入口。
3. 只能默认读取 context / packet 中的 `allowed_reads`、`must_read` 或明确的 stage summary。以下对象必须进入 `do_not_read_by_default`：
   - `process/STATE.md`
   - `process/DEVELOPMENT-PLAN.yaml`
   - 完整 `process/changes/CR-*.md`
   - 全量 `process/stories/*-LLD.md`
   - `process/archive/**`
   - `process/discussions/**`
   - 完整 `docs/quality/TEST-REPORT.md`、`docs/quality/REVIEW.md`、完整 diff、完整会话 transcript
4. 需要读取全文档时，必须记录 `full_doc_read_reason`，且原因只能是：
   - `capsule_missing`
   - `field_conflict`
   - `human_audit`
   - `deep_review`
   - `schema_validation_failed`
5. 全文读取日志写入 context / packet 的 `read_expansion_log`，或写入 `process/state/READ-EXPANSION-LEDGER.ndjson`。旧项目兼容时可同步到 `process/state/READ-EXPANSION-LEDGER.ndjson`。

## Output Contract

1. 输出 artifact 必须写摘要、路径引用和机器可读结果，不得复制长证据正文。
2. 授权边界默认只写 `authz_policy_refs`。只有 human gate、release decision 或用户明确要求审计时，才展开 policy 全文。
3. Story 实现结果必须优先写：
   - Story Return Packet：`process/returns/*.return.json`
   - Evidence Index：`process/evidence/*.index.json`
   - Design Delta：`process/design-deltas/*.delta.json`
4. CP 检查必须优先写：
   - 机器结果：`process/checks/*.result.json`
   - 人类摘要：`process/checks/*.summary.md`
   - Ledger 事件：`process/state/CHECKPOINT-LEDGER.ndjson`
   - Failure route：`route_on_fail` 必须使用 `process/policies/FAILURE-ROUTING.json` 中的动作式枚举
   - Waiver record：`WAIVED` item 必须提供 result `waivers[]` 中可解析的 scope / expiry / approval_ref / forces_release_status，并符合 `process/policies/WAIVER-POLICY.json`
5. 同一 CR 的 CP 不以内联章节作为真相源。CR 正文只能维护 `Checkpoint Index`，记录 CP 状态摘要和 `process/checks/CP*.result.json`、`process/checkpoints/CP*.md`、context、ledger refs；不得复制 CP result、Decision Brief、review 全文或历史 checkpoint 详情。
6. 当前状态只保存轻量字段、refs、计数和 blocker ID；不得把 CR 长字段、Story LLD、测试日志、review 全文或 policy 全文写入 current state。
7. 不可豁免项不得通过 waiver 绕过，包括未授权 runtime access、credential / secret exposure、missing dispatch evidence、runtime-high-risk forbidden path、missing read expansion log、missing evidence 和 false runtime-ready capability claim。

## Current State Write Contract

`process/state/STATE.current.json` 是轻量机器状态投影，不是通用状态数据库。任何 Agent、Skill、脚本或人工修复步骤都不得直接编辑 `STATE.current.json` 的未约定字段、非 allowlist 字段或超出 field budget 的长内容；不得绕过 current-state v2 校验把完整 CR、完整 LLD、完整测试日志、review 全文、policy 全文、长决策说明、完整 diff 或运行时输出写入 current state。

合法更新入口必须是受控 writer：优先使用 `current.update_current_state()`，或使用 host-orchestrator / `meta-flow state` 提供的等价受控命令。受控入口必须执行 allowlist、field budget、`audit` / `enforce` 模式校验，并在落盘前验证候选完整状态；校验失败时不得写入或部分写入 `STATE.current.json`。

受控 patch 语义必须与 CR037-S01 / CR037-S02 保持一致：

- allowlist 外字段在 `audit` 中只能作为漂移风险暴露，在 `enforce` 中必须阻断。
- field budget 覆盖字符串长度、列表数量、列表项长度和对象总量；超预算字段不得落盘。
- dict patch 使用 deep-merge；列表、标量和 `null` 使用替换语义。
- `null` 不是删除操作；需要删除字段必须通过已定义的受控命令或后续明确契约处理。
- 任一未知字段、预算超限、secret-like 内容或候选状态校验失败时，必须 failure no-write，不得创建半更新状态。

重型状态必须进入合适的正式落点，而不是塞入 current state：

- 面向人的长摘要进入 `process/STATE.md` 人类摘要或对应检查点摘要。
- 事件事实进入 `process/state/*-LEDGER.ndjson`。
- CP 门禁事实进入 `process/checks/*.result.json` 与 `*.summary.md`。
- 阶段 / Story 执行上下文进入 `process/context/*` 或 `process/context/stories/*`。
- Story 交付证据进入 `process/returns/*.return.json` 与 `process/evidence/*.index.json`。
- 项目级长状态或可延展引用进入 `PROJECT.current` refs 或 `project_state_ref` 指向的项目状态文件。
- 非阻断后续事项进入 follow-up tracking、风险台账或 Design Delta。

## Handoff Contract

1. Handoff 只传 `context_ref`、`story_packet_ref`、`return_packet_ref`、`evidence_ref`、`result_ref` 和必要的 dispatch metadata。
2. Handoff 文件不等于目标 agent 已执行。真实调度证据必须写入 `process/state/HANDOFF-LEDGER.ndjson`、`process/state/AGENT-DISPATCH-LEDGER.ndjson` 或等价平台证据。
3. 下游 agent 完成后必须返回结构化结果；host-orchestrator 只聚合 summary、result 和 evidence index，不复制全文。
4. 交接消息不得携带完整会话历史、全部 LLD、完整 HLD、完整 TEST-MATRIX、完整 TEST-REPORT、完整 REVIEW 或完整 diff。

## Skill Contract

高频 Skill 必须遵守同一读取边界：

- `context-manifest-builder` 生成 `must_read`、`allowed_reads`、`read_if_needed`、`do_not_read_by_default`，并校验 token budget。
- `context-handoff` 只传 context / packet 引用和读取策略，不传长文档集合。
- `state-router` 优先读取 `STATE.current.json`、`process/current/CURRENT.json`、ledgers、context pack 和 CP result；`STATE.md` 仅作 human summary / legacy fallback。
- `checkpoint-manager` 优先消费 CP result JSON、evidence index、ledger 和 context refs；Markdown 只作为摘要或人工门禁入口。
- `change-impact-analysis` 优先写 CR ledger / summary / index；CR 文档只维护 Checkpoint Index、状态摘要和 ref，关闭 CR 后不得继续把全文放入 active state。
- `review-artifact-protocol`、`release-readiness` 和质量类 Skill 只输出 findings / release / evidence 摘要和引用。

## Acceptance

- 五个功能 Agent 均显式遵守 Input Contract、Output Contract 和 Handoff Contract。
- 关键 Skill 不再要求默认读取巨型 `process/STATE.md`。
- 所有默认读取集合都能表达 `allowed_reads` 和 `do_not_read_by_default`。
- `process/current/CURRENT.json` 能在 active 和 idle 状态下指向 current context / checkpoint / story / release / handoff 入口，并只把 `CR-INDEX.json` 作为新流程 CR index；`CR-INDEX.yaml` 仅是 legacy read-only fallback。
- CR 模板包含 `Checkpoint Index`，并声明自动 CP 真相源是 `process/checks/CP*.result.json`、人工门禁真相源是 `process/checkpoints/CP*.md`。
- 需要全文读取时必须能落到允许枚举和日志位置。
