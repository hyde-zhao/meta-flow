# Agent / Skill Context Contract

本文件是功能 Agent 与高频 Skill 的共享契约。目标是把“默认多读一点保险”改成“先读最小上下文包，按契约扩展读取，输出只写摘要和引用”。

## Input Contract

1. 必须先读取本阶段 context pack 或 Story packet：
   - 阶段入口：`process/context/CP*-*.context.json` 或 legacy `process/context/*-CONTEXT.yaml`
   - Story 入口：`process/context/stories/*.json`
2. 默认机器状态入口是 `process/state/STATE.current.json`。`process/STATE.md` 只作为人类摘要、迁移兼容或人工审计输入，不得作为子 agent 默认读取入口。
3. 只能默认读取 context / packet 中的 `allowed_reads`、`must_read` 或明确的 stage summary。以下对象必须进入 `do_not_read_by_default`：
   - `process/STATE.md`
   - `process/DEVELOPMENT-PLAN.yaml`
   - 完整 `process/changes/CR-*.md`
   - 全量 `process/stories/*-LLD.md`
   - 完整 `docs/quality/TEST-REPORT.md`、`docs/quality/REVIEW.md`、完整 diff、完整会话 transcript
4. 需要读取全文档时，必须记录 `full_doc_read_reason`，且原因只能是：
   - `capsule_missing`
   - `field_conflict`
   - `human_audit`
   - `deep_review`
   - `schema_validation_failed`
5. 全文读取日志写入 context / packet 的 `read_expansion_log`，或写入 `process/state/READ-EXPANSION-LEDGER.ndjson`。旧项目兼容时可同步到 `STATE.md.context_budget.read_expansion_log[]`。

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
5. 当前状态只保存轻量字段、refs、计数和 blocker ID；不得把 CR 长字段、Story LLD、测试日志、review 全文或 policy 全文写入 current state。
6. 不可豁免项不得通过 waiver 绕过，包括未授权 runtime access、credential / secret exposure、missing dispatch evidence、runtime-high-risk forbidden path、missing read expansion log、missing evidence 和 false runtime-ready capability claim。

## Handoff Contract

1. Handoff 只传 `context_ref`、`story_packet_ref`、`return_packet_ref`、`evidence_ref`、`result_ref` 和必要的 dispatch metadata。
2. Handoff 文件不等于目标 agent 已执行。真实调度证据必须写入 `process/state/HANDOFF-LEDGER.ndjson`、`process/state/AGENT-DISPATCH-LEDGER.ndjson` 或等价平台证据。
3. 下游 agent 完成后必须返回结构化结果；host-orchestrator 只聚合 summary、result 和 evidence index，不复制全文。
4. 交接消息不得携带完整会话历史、全部 LLD、完整 HLD、完整 TEST-MATRIX、完整 TEST-REPORT、完整 REVIEW 或完整 diff。

## Skill Contract

高频 Skill 必须遵守同一读取边界：

- `context-manifest-builder` 生成 `allowed_reads`、`read_if_needed`、`do_not_read_by_default`，并校验 token budget。
- `context-handoff` 只传 context / packet 引用和读取策略，不传长文档集合。
- `state-router` 优先读取 `STATE.current.json`、ledgers、context pack 和 CP result；`STATE.md` 仅作 human summary / legacy fallback。
- `checkpoint-manager` 优先消费 CP result JSON、evidence index、ledger 和 context refs；Markdown 只作为摘要或人工门禁入口。
- `change-impact-analysis` 优先写 CR ledger / summary / index；关闭 CR 后不得继续把全文放入 active state。
- `review-artifact-protocol`、`release-readiness` 和质量类 Skill 只输出 findings / release / evidence 摘要和引用。

## Acceptance

- 五个功能 Agent 均显式遵守 Input Contract、Output Contract 和 Handoff Contract。
- 关键 Skill 不再要求默认读取巨型 `process/STATE.md`。
- 所有默认读取集合都能表达 `allowed_reads` 和 `do_not_read_by_default`。
- 需要全文读取时必须能落到允许枚举和日志位置。
