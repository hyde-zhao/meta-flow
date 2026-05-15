---
project_id: ""
workflow_mode: ""
current_phase: "init"
current_agent: "meta-po"
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
confirmation_adapter:
  platform: ""
  preferred_mode: "structured-select"
  fallback_mode: "exact-text"
agent_lifecycle:
  orchestrator_singleton: true
  active_agents: []
  singleton_violation: false
  singleton_resolution: ""
  reuse_policy: "same workflow/change/story reuses the same role thread; close after checkpoint or handoff completion"
parallel_execution:
  max_parallel_lld: 3
  max_parallel_dev: 2
  max_parallel_qa: 2
  lld_ready: []
  lld_running: []
  lld_review: []
  dev_ready: []
  dev_running: []
  verify_ready: []
  verify_running: []
  blocked_by_dependency: []
checkpoints:
  profile: "default-cp0-cp8"
  result_root: "process/checks"
  manual_root: "checkpoints"
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
    manual_review: "checkpoints/CP2-REQUIREMENTS-BASELINE.md"
    last_result: ""
  cp3_hld_review:
    type: "auto_then_manual"
    status: "pending"
    auto_result: "process/checks/CP3-HLD-CONSISTENCY.md"
    manual_review: "checkpoints/CP3-HLD-REVIEW.md"
    last_result: ""
  cp4_story_plan_review:
    type: "auto_then_manual"
    status: "pending"
    auto_result: "process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md"
    manual_review: "checkpoints/CP4-STORY-PLAN-REVIEW.md"
    last_result: ""
  cp5_story_lld_review:
    type: "rolling_auto_then_manual"
    status: "per_story"
    auto_result_pattern: "process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md"
    manual_review_pattern: "checkpoints/CP5-{story_id}-{story_slug}-LLD.md"
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
    results: []
  cp8_delivery_readiness:
    type: "auto_then_manual"
    status: "pending"
    auto_result: "process/checks/CP8-DELIVERY-READINESS.md"
    manual_review: "checkpoints/CP8-DELIVERY-READINESS.md"
    last_result: ""
parallel_waves: []
history: []
last_updated: ""
---

<!--
状态转换表（meta-po 参考）：

| 当前状态 | 退出条件 | 下一状态 | 检查点 |
|---------|---------|---------|----------|
| init | CP0 自动检查通过 | requirement-clarification | CP0 原始请求受理门 |
| requirement-clarification | CP1 自动检查通过 + CP2 人工确认通过 | solution-design | CP1 用户场景完备门；CP2 需求基线门 |
| solution-design | CP3 人工确认通过 | story-planning | CP3 HLD 架构评审门 |
| story-planning | CP4 人工确认通过，Story DAG 与并行计划可校验 | story-execution | CP4 Story 拆解与并行安全门 |
| story-execution | 每个目标 Story 通过 CP5/CP6/CP7 并到达 verified | 下一调度批次或 documentation | CP5 LLD、CP6 编码完成、CP7 验证完成滚动检查 |
| documentation | CP8 自动预检与人工终验通过 | delivered | CP8 交付就绪门 |

Story 生命周期（每个 Story 独立）：
  draft → lld-ready → lld-in-progress → lld-ready-for-review → lld-approved → dev-ready → in-development → ready-for-verification → verified → done
  兼容旧状态：package-draft≈lld-ready，package-ready-for-review≈lld-ready-for-review，package-approved≈dev-ready
  同一 Story：LLD 确认 → 开发 → 验证 严格串行
  LLD 写作可跨 Story 并行；开发必须满足 dev_gate、依赖类型、文件所有权和 CP5 确认
  Wave 是调度分组，不是唯一门控；真正门控以 Story DAG 为准

注：
- packaging 不再是独立状态，由 meta-qa 在 story verified 后自动执行
- 验证环境确认不再是人工检查点，VALIDATION-ENV.yaml 缺失时 meta-qa 自动阻断并提示
- 所有自动检查结果写入 process/checks/CP*.md；所有人工审查稿写入 checkpoints/CP*.md
- 人工检查点发起时必须提示用户 checklist 文件路径，人工审查后必须回填对应 checkpoints/CP*.md 的“人工审查结果”
-->
