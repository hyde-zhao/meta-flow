# Agent / Skill Context Contract

本文件是功能 Agent 与高频 Skill 的共享契约。目标是把“默认多读一点保险”改成“先读最小上下文包，按契约扩展读取，输出只写摘要和引用”。

运行时 delivery 语义的唯一机器 owner 是 `delivery/rules/DELIVERY-RUNTIME-CONTRACT.json`；本文件是人类规范 facade。route、STATE/CURRENT、checkpoint 真相路径、source/mirror 与平台 renderer 不得在下游另立冲突枚举。

## vNext Work-first Contract

### Binding-only 逻辑引用门

需要过程仓的 vNext `project/work/retrospective/evolution` Python 命令通过 `.meta-flow/workspace.yaml` 的统一 resolver 定位；`repository` 命令继续要求显式单仓 `--repo-root`。Agent/Skill 中的 `process/...` 是逻辑引用，不是发布仓相对物理路径。首次文件系统 I/O 前必须调用 `meta-flow project resolve-ref --project-root <release-root> --logical-ref <process/...> --format json`，只瞬时使用成功 JSON 的 `resolved_path`。退出码 2 时必须 BLOCKED；不得猜测 sibling、去掉前缀、复刻 resolver、恢复软链接或回退 legacy，也不得把绝对路径写回任何产物。legacy-only 顶层操作必须交还 Host Orchestrator 获取独立 typed authorization。

### Binding-only 路径兼容门

- route-aware prompt 必须把 `process/...` 明确标为逻辑引用，并在首次文件 I/O 前调用唯一 resolver。
- resolver 返回退出码 2、binding 冲突或元数据不一致时，任何调用前必须 BLOCKED；不得改拼 sibling、恢复软链接或自动 fallback。
- 只渲染逻辑引用的模板不执行 resolver；真正消费文件的 Agent/Skill 承担解析责任。
- legacy 顶层操作的 typed capability 由 Host Orchestrator 提供，功能 Agent/Skill 不得自行构造。

当独立过程库根存在 `PROJECT.yaml` 且当前对象为 `works/<work-id>/WORK.yaml` 时，本节优先于下方 legacy CP/context-pack 规则：

1. 默认入口只读 `PROJECT.yaml`、当前 `WORK.yaml`、当前 `REQUEST.md` 和用户问题直接需要的 Phase/证据引用；总对象数、读写、检查和 token 不得超过 Work 的 G profile 与 scope。
2. `allowed_reads` 是最大允许集合，不是必读集合；禁止为了“保险”读取完整 HLD、全部历史 CR/Story、完整测试报告、全量 diff 或 transcript。
3. G0 不创建独立评审/CP/context pack；G1 最多一次 Work 范围轻量评审；G2/G3 或正式 CR 才使用下方 CP0-CP8 与独立 QA 契约。GovernanceRiskProfile V2：G2=scope-goal-note；G3=原 G2 完整流程（等价 V1 G2）；只有用户显式选择 G3。
4. 输出优先写回当前 Work 目录的最小 REQUEST、WORK、USAGE、HANDOFF、RESULT 或 evidence ref；不得复制已有长证据正文。
5. 每次读/写/检查前分别校验 risk、scope、budget。任一条件不满足时停止并返回重分类、缩小范围或拆 Work 建议；不得用剩余 token 绕过 scope，也不得用 scope 绕过风险门。
6. 项目查询最多读取 5 个直接引用对象；跨项目汇总、全历史审计和敏感证据必须升级并批准。
7. 复盘报告、建议决策、进化包、实现启动和 publication 是不同对象；任何 Agent/Skill 都不得把上一步的 approve 扩张为下一步授权。
8. native CR 的真相顺序是 PROJECT/WORK/formal CR → summary/ledger/CR-INDEX。任何 Agent/Skill 都不得从 CR-INDEX 反向修改 lifecycle，也不得让旧 index、summary 正文、ledger 或 legacy 仓参与 native index rebuild；损坏/缺失 index 必须走显式 dry-run/rebuild。
9. 一个 Decision Bundle revision 可以合并一次用户确认，但每个 subgate 仍必须独立校验、独立 evidence、独立结果和停止传播。facts/scope/authz 漂移时必须新建 revision，不能复用旧确认。
10. 冻结写 scope 前必须按 Git index facts 做八分类；tracked symlink、missing 与 ignored generated output 只能进入 validation，submodule/outside_repo/duplicate 必须 BLOCKED。commit 子门按仓库分别检查 staged symmetric difference，不得 `git add -f`。

下方契约继续服务 legacy 项目和 G2 profile，不得作为 G0/G1 默认开销。

## Input Contract

1. 必须先读取本阶段 context pack 或 Story packet：
   - 阶段入口：`process/context/CP*-*.context.json` 或 legacy `process/context/*-CONTEXT.yaml`
   - Story 入口：`process/context/stories/*.json`
2. 默认机器状态入口是 `process/state/STATE.current.json`；默认文件系统发现入口是 `process/current/CURRENT.json`，其 status 必须能表达 `idle`、`active`、`awaiting_gate`、`awaiting_authorization` 或 `blocked`。`process/STATE.md` 只作为人类摘要、迁移兼容或人工审计输入，不得作为子 agent 默认读取入口。`next_session_handoff_ref` 字段存在且为显式 `null` 时表示 owner 已确认无 handoff，不得扫描历史文件回退；只有 legacy payload 缺少该字段时才允许发现回退。
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
   - `schema_validation_failed`
   - `human_audit`
   - `summary_insufficient`
5. 每个理由必须在读取目标正文前提供 `reason_evidence`：`capsule_missing` 提供 `capsule_ref`；`field_conflict` 提供 `conflict_field` 与两个含 `ref/digest` 的来源；`schema_validation_failed` 提供 `schema_id/error_code/target_ref`；`human_audit` 提供 `authorization_ref`；`summary_insufficient` 提供非空 `missing_slots`。理由或证据不符合契约时必须 `BLOCKED`，并保持 `target bytes=0`、`mutation=0`。
6. 全文读取日志写入 context / packet 的 `read_expansion_log`，或写入 `process/state/READ-EXPANSION-LEDGER.ndjson`。旧 schema 事件只允许历史只读解析，不得作为新扩读授权或新事件模板。

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
- `change-impact-analysis` 与 `state-router` 对 native CR 状态变化必须先调用 `meta-flow cr status-sync` dry-run，并且只在 exact OID/Work scope 授权下 apply；不得分别手写 formal CR、summary、ledger、STATE 或 index。
- Host Orchestrator 合并人工确认时必须创建 revision-aware Decision Bundle；功能 Agent 只能回写自身 subgate result/evidence，不能把 bundle approval 解释为 commit/push/runtime 授权。
- `review-artifact-protocol`、`release-readiness` 和质量类 Skill 只输出 findings / release / evidence 摘要和引用。

## Governance Execution Closure

1. failure route 只接受 `CHECK_HARNESS_ERROR`、`DETERMINISTIC_SCHEMA_REPAIR`、`REAL_CONTENT_FAILURE`、`PARTIAL_MUTATION` 四类。G0 / G1 / G2 每个检查的自动恢复次数上限是 `1 / 2 / 2`；facts / scope / OID / authz / profile 漂移、真实内容失败、部分写入和未知失败不得自动重试。
2. 只有 G2 能进入 independent QA；同一 finding fingerprint 最多 2 次 re-QA，第 3 次返回 `NEEDS_DESIGN_CLARIFICATION`。G0 / G1 只能执行 affected-check targeted revalidation。
3. usage event 无论是否越界都必须先幂等追加。80% 为 `WARNING`；100% 及以上或 token `unavailable` 阻断后续 mutation。changed-path 机器真相只读取 `git status --porcelain=v1 -z -uall` 的 leaf paths；collapsed count 仅供 UI。
4. CP6 / CP8 的 cost closure 必须证明 stage coverage=100%、token proxy 在批准上限内、去重 gate interaction 不超过批准上限且 unknown leaf paths=0。合法结论仅为 `PASS_WITH_BASELINE_LIMITATION|FAIL`，`FAIL` 必须停止推进。CR-057 的 `1,752,000` 只能标记为 `authorized_proxy_ceiling`。
5. facts / scope / authz 变化时，Decision Bundle 必须创建新 revision，并只携带 delta、capsule ref 和 `read_expansion_log`；不得复制完整上轮 brief。合并一次 CP3 + CP5 用户交互不合并两个 subgate 的 evidence、result 或 receipt。
6. status-sync 必须以一个可恢复事务投影 formal frontmatter、CR 正文状态摘要、Checkpoint Index、summary、evidence index、ledger 和 formal-only index。follow-up candidate 不进入 formal-only index；dangling formal ref 仍阻断。
7. CP8、native close、测试或 cost closure 均不构成 repository publication authorization。`git commit`、`git push`、publish、live、production write 和 credential access 必须另有 exact target、facts/OID 与时效绑定的 typed authorization。

## Acceptance

- 五个功能 Agent 均显式遵守 Input Contract、Output Contract 和 Handoff Contract。
- 关键 Skill 不再要求默认读取巨型 `process/STATE.md`。
- 所有默认读取集合都能表达 `allowed_reads` 和 `do_not_read_by_default`。
- `process/current/CURRENT.json` 能在 active 和 idle 状态下指向 current context / checkpoint / story / release / handoff 入口，并只把 `CR-INDEX.json` 作为新流程 CR index；`CR-INDEX.yaml` 仅是 legacy read-only fallback。
- CR 模板包含 `Checkpoint Index`，并声明自动 CP 真相源是 `process/checks/CP*.result.json`、人工门禁真相源是 `process/checkpoints/CP*.md`。
- 需要全文读取时必须能落到允许枚举和日志位置。
