---
project_id: ""
workflow_mode: "standard"
fast_lane_reason: ""
fast_lane_risk_classification: ""
current_phase: "init"
current_agent: "host-orchestrator"
iteration: 0
blocked: false
active_change: ""
last_action: ""
next_action: "执行 init 阶段：创建工作目录结构，初始化 REQUEST.md，引导用户填写后唤醒 meta-pm"
delivery_routing:
  engagement_mode: "production"
  target_project_root: ""
  readme_contract_found: false
  output_root: ""
  requires_user_confirmation: false
  route_validation:
    status: "unchecked|pass|requires-user-confirmation|blocked"
    checked_at: ""
    scanned_sources: []
    production_delivery_allowed_roots: []
    forbidden_roots_when_production:
      - "delivery/agents"
      - "delivery/skills"
      - "delivery/rules"
      - ".agents"
    user_confirmed_output_route: false
    confirmation_source: ""
    validation_errors: []
target_project_profile:
  project_kind: "unknown" # code-project | workflow-product | agentic-code-product | mixed | unknown
  confidence: "low" # high | medium | low
  source: "" # user | readme-scan | cr | inferred
  delivery_routing_ref: "process/STATE.md.delivery_routing"
  validation_defaults:
    native_test_required: true
    workflow_eval_required: false
    prompt_bundle_required: false
  eval_contracts:
    workflow_eval_schema: "evals/contracts/WORKFLOW-EVAL.schema.yaml"
    prompt_bundle_schema: "evals/contracts/PROMPT-BUNDLE.schema.yaml"
    case_registry_schema: "evals/contracts/CASE-REGISTRY.schema.yaml"
  notes: []
context_budget:
  default_read_profile: "compact"
  full_doc_read_policy: "only-on-missing-conflict-audit-or-deep-review"
  max_source_files_per_handoff: 8
  max_summary_items_per_capsule: 20
  require_capsule_first: true
  full_doc_read_reason_required: true
  context_root: "process/context"
  phase_capsules:
    cp2_requirement:
      path: "process/context/CP2-REQUIREMENT-CONTEXT.yaml"
      status: "pending|ready|blocked|waived"
      read_profile: "compact"
      generated_at: ""
      missing_or_waived_reason: ""
    cp3_design:
      path: "process/context/CP3-DESIGN-CONTEXT.yaml"
      status: "pending|ready|blocked|waived"
      read_profile: "compact"
      generated_at: ""
      missing_or_waived_reason: ""
    cp5_lld:
      path: "process/context/CP5-LLD-CONTEXT.yaml"
      status: "pending|ready|blocked|waived"
      read_profile: "compact"
      generated_at: ""
      missing_or_waived_reason: ""
    cp6_implementation:
      path: "process/context/CP6-IMPLEMENTATION-CONTEXT.yaml"
      status: "pending|ready|blocked|waived"
      read_profile: "minimal"
      generated_at: ""
      missing_or_waived_reason: ""
    cp7_verification:
      path: "process/context/CP7-VERIFICATION-CONTEXT.yaml"
      status: "pending|ready|blocked|waived"
      read_profile: "compact"
      generated_at: ""
      missing_or_waived_reason: ""
    cp8_delivery:
      path: "process/context/CP8-DELIVERY-CONTEXT.yaml"
      status: "pending|ready|blocked|waived"
      read_profile: "compact"
      generated_at: ""
      missing_or_waived_reason: ""
  read_expansion_log: []
  read_expansion_schema:
    - "at"
    - "actor"
    - "phase"
    - "capsule_path"
    - "expanded_to"
    - "reason"
workflow_health:
  status: "healthy|watch|stalled|blocked|requires-human-arbitration"
  last_checked_at: ""
  thresholds:
    same_question_rounds_max: 2
    hld_revision_rounds_max: 3
    lld_clarification_items_max: 8
    cp_retry_count_max: 2
    story_rework_count_max: 2
    unchanged_artifact_hash_rounds_max: 2
    phase_elapsed_rounds_max: 6
  counters:
    same_question_rounds: 0
    hld_revision_rounds: 0
    lld_clarification_items: 0
    cp_retry_count: 0
    story_rework_count: 0
    unchanged_artifact_hash_rounds: 0
    phase_elapsed_rounds: 0
  escalation_policy: "任一计数器超过阈值时，host-orchestrator 必须停止继续消耗轮次，生成决策项或人工仲裁请求；不得继续静默重试。"
  active_signals: []
  last_escalation: ""
artifacts:
  requirements:
    request: "process/REQUEST.md"
    use_cases: "docs/product/USE-CASES.md"
    requirements: "docs/product/REQUIREMENTS.md"
    scenarios: "docs/product/SCENARIOS.yaml"
    test_matrix: "docs/product/TEST-MATRIX.md"
    story_map: "docs/product/STORY-MAP.md"
    mvp_scope: "docs/product/MVP-SCOPE.md"
    release_slices: "docs/product/RELEASE-SLICES.md"
    backlog: "docs/product/BACKLOG.md"
    status: "pending|complete|n/a|waived|blocked"
    evidence: []
  blueprint:
    blueprint: "docs/design/BLUEPRINT.md"
    domain_map: "docs/design/DOMAIN-MAP.md"
    dependency_map: "docs/design/DEPENDENCY-MAP.md"
    architecture_decision: "docs/design/ARCHITECTURE-DECISION.md"
    feature_design_matrix: "docs/design/FEATURE-DESIGN-MATRIX.md"
    applicability: "pending|required|not-applicable|waived"
    hld_consumed: false
    evidence: []
  feature_design:
    matrix: "docs/design/FEATURE-DESIGN-MATRIX.md"
    root: "docs/features"
    required_when: "HLD 或 BLUEPRINT 标记 Feature 存在跨模块契约、数据模型、权限、安全、外部接口、迁移、并发或多 Story 共享实现边界"
    lld_policy_values:
      - "full-lld"
      - "technical-note"
      - "waived"
    items: []
    item_schema:
      - "feature_id"
      - "feature_name"
      - "applicability"
      - "required_reason"
      - "design"
      - "test_plan"
      - "tasks"
      - "story_ids"
      - "lld_policy"
      - "status"
      - "owner_agent"
      - "evidence"
  implementation:
    story_evidence_pattern: "process/stories/STORY-{id}-{story_slug}-IMPLEMENTATION.md"
    feature_evidence_pattern: "docs/features/<feature>/IMPLEMENTATION.md"
    required_for:
      - "prompt-skill-workflow"
      - "installer"
      - "guardrail"
      - "platform-adapter"
      - "high-risk-full-lld"
      - "release-related"
    evidence_type_values:
      - "implementation-md"
      - "story-summary"
      - "dev-log"
      - "n/a"
    item_schema:
      - "story_id"
      - "implementation_type"
      - "evidence_path"
      - "implementation_objects"
      - "contract_mapping_status"
      - "test_fixture_plan_status"
      - "slice_validation_status"
      - "platform_diff_check_status"
      - "handoff_summary_status"
      - "status"
  quality:
    test_strategy: "docs/quality/TEST-STRATEGY.md"
    verification_report: "docs/quality/VERIFICATION-REPORT.md"
    test_report: "docs/quality/TEST-REPORT.md"
    review: "docs/quality/REVIEW.md"
    fixes: "docs/quality/FIXES.md"
    validation_mode_values:
      - "runtime"
      - "static-only"
      - "dry-run-only"
      - "review-only"
      - "mixed"
    cp7_result_values:
      - "PASS"
      - "PASS_WITH_RISK"
      - "BLOCKED"
      - "NEEDS_REWORK"
      - "NEEDS_DESIGN_CLARIFICATION"
      - "WAIVED"
    matrix_trace_status: "pending|complete|n/a|waived|blocked"
    verification_evidence_schema:
      - "story_id"
      - "validation_mode"
      - "verification_report_path"
      - "validation_object_inventory_status"
      - "traceability_matrix_status"
      - "design_contract_verification_status"
      - "layered_validation_plan_status"
      - "fixture_validation_status"
      - "platform_dry_run_status"
      - "manual_semantic_review_status"
      - "issue_risk_status"
      - "cp7_result"
      - "route_to"
      - "risk_acceptance_required"
    evidence: []
    workflow_eval:
      required_for_sut_types:
        - "generated-workflow"
        - "prompt-skill-workflow"
        - "meta-flow-core-code"
        - "agentic-code-product"
        - "mixed"
      optional_for_sut_types:
        - "code-project"
      run_root: "process/evals/runs"
      suite_health: "docs/quality/EVAL-SUITE-HEALTH.md"
      failure_backlog: "docs/quality/FAILURE-BACKLOG.md"
      external_adapters_default: "disabled"
      runtime_authorization_required_for:
        - "external-service"
        - "credentials"
        - "trace-upload"
        - "network"
  release:
    release_context: "process/release/RELEASE-CONTEXT.yaml"
    release_notes: "docs/release/RELEASE-NOTES.md"
    deploy_checklist: "docs/release/DEPLOY-CHECKLIST.md"
    rollback: "docs/release/ROLLBACK.md"
    migration: "docs/release/MIGRATION.md"
    feedback: "docs/release/FEEDBACK.md"
    release_artifact_profile_values:
      - "minimal"
      - "compact"
      - "full"
    release_decision_values:
      - "READY"
      - "READY_WITH_RISK"
      - "NOT_READY"
      - "RELEASED"
      - "FAILED"
    release_execution_requires_independent_authorization: true
    readiness_status: "pending|complete|n/a|waived|blocked"
    evidence: []
confirmation_adapter:
  platform: ""
  preferred_mode: "structured-select"
  fallback_mode: "exact-text"
orchestrator_session:
  kind: "host"
  role: "host-orchestrator"
  host_session_id: ""
  agent_id: ""
  agent_name: ""
  thread_id: ""
  status: "active"
  workflow_id: ""
  active_change: ""
  pending_gate: ""
  pending_checklist_path: ""
  pending_user_decision: ""
  pending_decision_ids: []
  pending_non_authorized_items: []
  subagent_auto_dispatch: "enabled"
  resume_instruction: "用户回复人工检查点结论后，由 Host Orchestrator 主进程重新读取 STATE、checkpoint 和相关产物后继续；不得 spawn / resume 编排子 agent"
  spawned_at: ""
  last_seen_at: ""
  awaiting_since: ""
  resumed_at: ""
  closed_at: ""
  previous_agent_id: ""
  previous_thread_id: ""
  superseded_by: ""
  recovery_reason: ""
delegated_interaction:
  phase: ""
  agent_role: ""
  agent_id: ""
  agent_name: ""
  thread_id: ""
  handoff_path: ""
  status: "none|delegated|active|awaiting-user|returned|blocked|closed"
  started_at: ""
  returned_at: ""
  return_summary_path: ""
  pending_user_input: ""
  routing_note: "requirement-clarification 委托 meta-pm、solution-design 委托 meta-se；正式人工检查点仍由 host-orchestrator 发起"
agent_lifecycle:
  orchestration_model: "host-orchestrated"
  orchestrator_singleton: false
  active_agents_scope: "functional-agents-only"
  platform_capabilities:
    subagent_dispatch:
      available: false
      checked_at: ""
      method: "unverified"
      limitation: "未完成平台子 agent 调度能力探测前，不得把下游任务标记为 completed"
    user_question:
      available: false
      checked_at: ""
      method: "unverified|conversation|request_user_input|platform-task|relay-only"
      structured_choice_available: false
      question_broker: "host-orchestrator"
      allowed_direct_roles:
        - "host-orchestrator"
        - "meta-pm"
        - "meta-se"
      limitation: "ask_user 是语义动作；未确认平台用户提问能力前，子 agent 不得假设可直接向用户提问。Codex 仅在当前工具面明确提供 request_user_input 时允许结构化选择，否则使用 exact-text 或经 host-orchestrator relay。"
  active_agents: []
  singleton_violation: false
  singleton_resolution: ""
  dispatch_evidence_required: true
  allowed_statuses:
    - "handoff-created"
    - "spawn-requested"
    - "running"
    - "completed"
    - "failed"
    - "unavailable"
    - "blocked"
    - "closing"
    - "closed"
  reuse_policy: "same workflow/change/story reuses the same role thread; close after checkpoint or verified agent completion"
  evidence_policy: "Agent Dispatch Evidence required: handoff files are not execution evidence; completed subagent work requires agent_id/thread_id plus tool evidence, unless user-approved inline-fallback is recorded"
parallel_execution:
  max_parallel_lld: 3
  max_parallel_dev: 2
  max_parallel_qa: 2
  lld_design_batch:
    batch_id: ""
    source: "all-stories|change|manual"
    stories: []
    story_schema:
      - "story_id"
      - "story_slug"
      - "design_evidence_type"
      - "lld_policy_required_level"
      - "feature_design_refs"
      - "evidence_path"
      - "status"
      - "owner_agent"
    status: "not-started|designing|ready-for-review|approved|blocked"
    manual_review: ""
    basis: "覆盖全部目标 Story；每项设计证据可为 full-lld、technical-note 或 waived，但均需进入 CP5 统一确认"
  lld_ready: []
  lld_running: []
  lld_review: []
  lld_batch_review: []
  lld_clarification_queue:
    status: "idle|collecting|batching|awaiting-user|answered|blocked|closed"
    active_question_batch: ""
    items: []
    item_schema:
      - "id"
      - "story_id"
      - "owner_agent"
      - "question"
      - "options"
      - "recommendation"
      - "impact_surface"
      - "blocks_lld"
      - "answer"
      - "status"
  dev_ready: []
  dev_running: []
  implementation_review: []
  verify_ready: []
  verify_running: []
  blocked_by_dependency: []
checkpoints:
  profile: "default-cp0-cp8"
  result_root: "process/checks"
  manual_root: "process/checkpoints"
  cp0_request_intake:
    type: "auto"
    status: "pending"
    auto_result: "process/checks/CP0-REQUEST-INTAKE.md"
    manual_review: ""
    last_result: ""
  cp1_use_case_completeness:
    type: "auto"
    status: "pending"
    auto_result: "process/checks/CP1-USE-CASE-COMPLETENESS.md"
    manual_review: ""
    last_result: ""
  cp2_requirements_baseline:
    type: "auto_then_manual"
    status: "pending"
    auto_result: "process/checks/CP2-REQUIREMENTS-BASELINE.md"
    manual_review: "process/checkpoints/CP2-REQUIREMENTS-BASELINE.md"
    last_result: ""
  cp3_hld_review:
    type: "auto_then_manual"
    status: "pending"
    auto_result: "process/checks/CP3-HLD-CONSISTENCY.md"
    manual_review: "process/checkpoints/CP3-HLD-REVIEW.md"
    last_result: ""
  cp4_story_plan_review:
    type: "auto_precheck"
    status: "pending"
    auto_result: "process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md"
    manual_review: ""
    last_result: ""
  cp5_story_lld_review:
    type: "all_stories_auto_then_manual"
    status: "per_workflow"
    auto_result_pattern: "process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md"
    manual_review_pattern: "process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md"
    results: []
  cp6_coding_done:
    type: "rolling_auto"
    status: "per_story"
    auto_result_pattern: "process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md"
    results: []
  cp7_verification_done:
    type: "rolling_auto"
    status: "per_story"
    auto_result_pattern: "process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md"
    result_values:
      - "PASS"
      - "PASS_WITH_RISK"
      - "BLOCKED"
      - "NEEDS_REWORK"
      - "NEEDS_DESIGN_CLARIFICATION"
      - "WAIVED"
    route_by_result:
      PASS: "verified"
      PASS_WITH_RISK: "verified-with-risk"
      WAIVED: "verified"
      NEEDS_REWORK: "meta-dev"
      NEEDS_DESIGN_CLARIFICATION: "meta-se|host-orchestrator"
      BLOCKED: "blocked"
    results: []
  cp8_delivery_readiness:
    type: "auto_then_manual"
    status: "pending"
    auto_result: "process/checks/CP8-DELIVERY-READINESS.md"
    manual_review: "process/checkpoints/CP8-DELIVERY-READINESS.md"
    release_context: "process/release/RELEASE-CONTEXT.yaml"
    allowed_readiness_decisions:
      - "READY"
      - "READY_WITH_RISK"
      - "NOT_READY"
    execution_decisions_require_independent_authorization:
      - "RELEASED"
      - "FAILED"
    last_result: ""
decision_briefs:
  cp2_requirements_baseline: ""
  cp3_hld_review: ""
  cp5_story_lld_review: ""
  cp8_delivery_readiness: ""
discussion_checkpoints:
  cp2_scenario_discussion:
    log: "process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md"
    checkpoint: "process/checks/CP2-DISCUSSION-CHECKPOINT.json"
    status: "pending"
  cp3_hld_discussion:
    log: "process/discussions/CP3-HLD-DISCUSSION-LOG.md"
    checkpoint: "process/checks/CP3-DISCUSSION-CHECKPOINT.json"
    status: "pending"
human_gate_decisions:
  status: "idle|collecting|ready-for-gate|awaiting-user|answered|blocked|closed"
  active_gate: ""
  active_checkpoint: ""
  active_launch_message: ""
  decision_collection_coverage: []
  pending_human_decisions: []
  accepted_decision_ids: []
  non_authorized_items: []
  follow_up_tracking_path: ""
  decision_brief_profile: "compact"
  decision_brief_profile_values:
    - "full"
    - "compact"
    - "summary"
  chat_print_policy: "checkpoint 文件中的 Decision Brief 必须完整；对话中可按 profile 压缩，但必须打印 checklist 路径、自动预检结论、决策项总数、blocking/high-risk 摘要、不授权项和三个 exact 回复。"
  compact_threshold: 6
  summary_threshold: 12
  item_schema:
    - "id"
    - "gate"
    - "decision_type"
    - "question"
    - "recommendation"
    - "alternatives"
    - "pros_cons"
    - "impact_risk"
    - "rollback_switch"
    - "status"
    - "source"
    - "owner_agent"
    - "updated_at"
    - "answer"
  coverage_schema:
    - "gate"
    - "source_type"
    - "source_path"
    - "scan_status"
    - "candidate_count"
    - "included_decision_count"
    - "classification_or_na_reason"
  allowed_decision_types:
    - "scope"
    - "architecture"
    - "security"
    - "implementation"
    - "runtime_authorization"
    - "risk_acceptance"
    - "follow_up_tracking"
  allowed_statuses:
    - "open"
    - "ready-for-gate"
    - "awaiting-user"
    - "accepted"
    - "changes-requested"
    - "rejected"
    - "resolved-by-user"
    - "non-blocking-open"
    - "converted-to-spike"
    - "n/a-with-reason"
  classification_policy: "CP2/CP3/CP5/CP8 前，所有 Q-*、OPEN、LCQ-*、O-*、权限/安全/运行授权/风险接受/外部接口/数据写入/publish/live/交易类问题必须分类；decision-item 写入 pending_human_decisions"
  launch_protocol: "发起人工门禁消息必须包含 checklist 路径、自动预检结论、待决策项数量、待决策表格、三个 exact 回复，以及 approve 不代表授权禁止操作的复述"
  follow_up_statuses:
    - "candidate"
    - "active"
    - "blocked"
    - "spike_candidate"
    - "converted-to-spike"
    - "closed"
    - "cancelled"
    - "superseded"
cr_tracking:
  status: "not-indexed|indexed|needs-sync|conflict|blocked"
  index_path: "process/changes/CR-INDEX.yaml"
  last_consistency_check: ""
  active_crs: []
  blocked_crs: []
  follow_up_candidates: []
  spike_candidates: []
  stale_status_conflicts: []
  item_schema:
    - "id"
    - "title"
    - "status"
    - "source_tracking"
    - "formal_cr_path"
    - "priority"
    - "blocked_by"
    - "impact_surface"
    - "conflict_keys"
    - "next_gate"
    - "next_action"
    - "last_checked_at"
  reporting_policy: "状态查询必须同时输出 active CR、blocked CR、follow-up candidate、spike_candidate 和 stale_status_conflicts；candidate/spike_candidate 不占执行锁"
  consistency_check: "存在 meta-flow check cr-tracking 时，当前状态查询、候选 CR 启动、CR 关闭和 CP8 follow-up 分流后必须运行或记录跳过原因"
parallel_waves: []
history: []
last_updated: ""
---

<!--
状态转换表（host-orchestrator 参考）：

| 当前状态 | 退出条件 | 下一状态 | 检查点 |
|---------|---------|---------|----------|
| init | CP0 自动检查通过 | requirement-clarification | CP0 原始请求受理门 |
| requirement-clarification | CP1 自动检查通过 + CP2 人工确认通过，且 SCENARIOS / STORY-MAP / MVP-SCOPE 存在或有 N/A / WAIVED 原因 | solution-design | CP1 用户场景完备门；CP2 需求 / 场景 / 范围基线门 |
| solution-design | CP3 人工确认通过，且 BLUEPRINT / DOMAIN-MAP / DEPENDENCY-MAP 已生成并被 HLD 消费，或有 N/A / WAIVED 原因 | story-planning | CP3 蓝图 / HLD 架构评审门 |
| story-planning | CP4 自动预检通过，Story DAG 与并行计划可校验，全部目标 Story 的完整 LLD / 技术说明 / waived 证据通过全量 CP5 | story-execution | CP4 Story 拆解与并行安全自动门；CP5 全量设计证据确认 |
| story-execution | 全部目标 Story 通过 CP6、CP7 并到达 verified / verified-with-risk | documentation | CP6 编码完成、CP7 验证完成检查 |
| documentation | CP8 自动预检与人工终验通过 | delivered | CP8 交付就绪门 |

Story 生命周期（每个 Story 独立）：
  draft → lld-ready → lld-in-progress → lld-ready-for-review → lld-batch-ready-for-review → lld-approved → dev-ready → in-development → ready-for-verification → verified / verified-with-risk → done
  兼容旧状态：package-draft≈lld-ready，package-ready-for-review≈lld-ready-for-review，package-approved≈dev-ready
  同一 Story：全量设计证据确认 → 开发 → 验证 严格串行
  LLD 写作必须在 story-planning 内覆盖全部目标 Story 且可跨 Story 并行；开发必须满足 dev_gate、依赖类型、文件所有权和全量 CP5 确认
  Wave 只用于进入 story-execution 后的开发/验证调度；CR 触发时，CR 影响范围是 LLD 设计批次；真正门控以 Story DAG 为准

注：
- packaging 不再是独立状态，由 meta-qa 在 story verified 后自动执行
- 验证环境确认不再是人工检查点；`validation_mode=runtime` 或 `mixed` 且需要真实运行时，`VALIDATION-ENV.yaml` 缺失才由 meta-qa 阻断；`static-only` / `dry-run-only` / `review-only` 必须记录等价验证证据、N/A 理由和剩余风险
- 所有自动检查结果写入 process/checks/CP*.md；所有人工审查稿写入 process/checkpoints/CP*.md
- CP2 / CP3 / CP5 / CP8 人工检查点发起时必须提示用户 checklist 文件路径，人工审查后必须回填对应 process/checkpoints/CP*.md 的“人工审查结果”；CP4 只写自动预检并汇入 CP5 Decision Brief
- subagent_auto_dispatch=enabled 表示同工作流内允许 host-orchestrator 自动拉起真实子 agent；inline fallback 仍需用户单独批准
- user_question.available=false 或 method=relay-only 时，子 agent 不得直接向用户提问；meta-pm/meta-se 的阶段委托问题经 host-orchestrator relay，meta-dev 的实现灰区写入 lld_clarification_queue
- delegated_interaction 仅记录阶段内用户交互权委托；不得代表 CP2 / CP3 已确认
- lld_clarification_queue 存在 blocks_lld=true 且未回答的 item 时，不得发起 CP5 全量人工确认
- human_gate_decisions.pending_human_decisions 是 CP2 / CP3 / CP5 / CP8 待人工决策清单的状态机对象；checkpoint 文件和对话发起消息必须从该队列聚合并保持一致
- pending_non_authorized_items 用于记录本轮 approve 不代表授权的事项，尤其是真实运行、凭据、安全、外部接口、数据写入、publish、live / 交易类操作
-->
