---
project_id: "meta-flow"
workflow_mode: "standard"
orchestration_model: "host-orchestrated"
current_phase: "documentation"
current_agent: "host-orchestrator"
iteration: 13
blocked: false
active_change: ""
last_action: "完成 CR-018 至 CR-023：workflow eval、prompt bundle、case registry、本地 runner、CP7 集成、suite health 和 optional adapter policy 已落地并通过本地验证"
next_action: "无活跃 CR；可进入提交与 GitHub 推送"
orchestrator_session:
  kind: "host"
  role: "host-orchestrator"
  host_session_id: ""
  agent_id: ""
  agent_name: ""
  thread_id: ""
  status: "active"
  workflow_id: "meta-flow"
  active_change: ""
  pending_gate: ""
  pending_checklist_path: ""
  pending_user_decision: ""
  pending_decision_ids: []
  pending_non_authorized_items: []
  subagent_auto_dispatch: "enabled"
  resume_instruction: "用户回复人工检查点结论后，由 Host Orchestrator 主进程重新读取 STATE、checkpoint 和相关产物后继续；不得 spawn / resume 编排子 agent"
  spawned_at: ""
  last_seen_at: "2026-06-11T19:50:20+08:00"
  awaiting_since: ""
  resumed_at: ""
  closed_at: ""
  previous_agent_id: ""
  previous_thread_id: ""
  superseded_by: ""
  recovery_reason: ""
agent_lifecycle:
  orchestration_model: "host-orchestrated"
  orchestrator_singleton: false
  active_agents_scope: "functional-agents-only"
  active_agents: []
  reuse_policy: "same workflow/change/story reuses the same role thread; close after checkpoint or handoff completion"
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
      status: "pending"
      read_profile: "compact"
      generated_at: ""
      missing_or_waived_reason: ""
    cp3_design:
      path: "process/context/CP3-DESIGN-CONTEXT.yaml"
      status: "pending"
      read_profile: "compact"
      generated_at: ""
      missing_or_waived_reason: ""
    cp5_lld:
      path: "process/context/CP5-LLD-CONTEXT.yaml"
      status: "pending"
      read_profile: "compact"
      generated_at: ""
      missing_or_waived_reason: ""
    cp6_implementation:
      path: "process/context/CP6-IMPLEMENTATION-CONTEXT.yaml"
      status: "pending"
      read_profile: "minimal"
      generated_at: ""
      missing_or_waived_reason: ""
    cp7_verification:
      path: "process/context/CP7-VERIFICATION-CONTEXT.yaml"
      status: "pending"
      read_profile: "compact"
      generated_at: ""
      missing_or_waived_reason: ""
    cp8_delivery:
      path: "process/context/CP8-DELIVERY-CONTEXT.yaml"
      status: "pending"
      read_profile: "compact"
      generated_at: ""
      missing_or_waived_reason: ""
  read_expansion_log: []
workflow_health:
  status: "healthy"
  last_checked_at: "2026-06-07T10:42:25+08:00"
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
  active_signals: []
  last_escalation: ""
cr_tracking:
  index_path: "process/changes/CR-INDEX.yaml"
  consistency_check:
    last_run_at: "2026-06-11T19:59:32+08:00"
    command: "meta-flow check cr-tracking --project-root ."
    result: "PASS"
  active_crs: []
  blocked_crs: []
  follow_up_candidates: []
  spike_candidates: []
  stale_status_conflicts: []
checkpoints:
  requirement_confirmed: false
  hld_confirmed: true
  story_package_confirmed: true
  final_review_confirmed: false
parallel_waves: []
history:
  - at: "2026-06-11T19:50:20+08:00"
    actor: "host-orchestrator"
    action: "close-cr-018-to-cr-023-workflow-eval-governance"
    phase: "documentation"
    summary: "用户预授权跳过人工审批后，完成 CR-019 至 CR-023：新增 eval contracts、generated workflow fixture、本地 deterministic runner、suite health、failure backlog、CP7 eval evidence 集成和 optional adapter policy；本地 eval validate/run/suite-health 通过，外部 adapter 真实运行仍未授权。"
  - at: "2026-06-11T19:30:30+08:00"
    actor: "host-orchestrator"
    action: "create-cr-018-eval-governance-baseline"
    phase: "documentation"
    summary: "创建 CR-018：建立单主流程 + project_kind / validation_target 分流、workflow eval、prompt bundle、纯代码兼容和后续 CR 拆分台账；当前等待用户审阅，未授权后续实现或外部工具运行。"
  - at: "2026-06-11T16:50:00+08:00"
    actor: "host-orchestrator"
    action: "close-cr-017-host-orchestrated"
    phase: "documentation"
    summary: "CR-017 验证通过并关闭：active rules、state-router、STATE 模板、README / USER-MANUAL、安装器、package-builder、platform-validator 与 guardrail 已切换为 Host Orchestrator 主进程编排；Codex / Claude Code dry-run 均只安装 meta-pm/meta-se/meta-dev/meta-qa/meta-doc 功能子 agent，不安装 meta-po 或 host-orchestrator 编排 agent。"
  - at: "2026-06-11T00:00:00+08:00"
    actor: "host-orchestrator"
    action: "activate-cr-017-host-orchestrated"
    phase: "documentation"
    summary: "用户批准取消 meta-po 编排子 agent；主进程 Host Orchestrator 接管子 agent 调度、人工门禁、CR、状态推进和 LLD clarification broker，Codex / Claude Code 只安装功能子 agent。"
  - at: "2026-04-23T11:30:48+08:00"
    actor: "meta-po"
    action: "initialize-state"
    phase: "story-planning"
    summary: "初始化 STATE.md，并按用户确认结果直接装配到 story-planning"
  - at: "2026-04-23T11:30:48+08:00"
    actor: "user"
    action: "confirm-hld"
    phase: "solution-design"
    summary: "用户确认 HLD 已获批，可进入 Story 拆解"
  - at: "2026-04-23T11:30:48+08:00"
    actor: "user"
    action: "confirm-story-split"
    phase: "story-planning"
    summary: "用户确认 Story 拆分方向，可继续执行 story-planning 产物收敛"
  - at: "2026-04-23T11:33:10+08:00"
    actor: "meta-po"
    action: "check-story-planning-exit"
    phase: "story-planning"
    summary: "检测到 STORY-BACKLOG.md、DEVELOPMENT-PLAN.yaml、ARCHITECTURE-DECISION.md、PLATFORM-INSTALL-SPEC.md 尚未生成，阶段不推进"
  - at: "2026-04-23T11:34:50+08:00"
    actor: "user"
    action: "confirm-story-planning-direction"
    phase: "story-planning"
    summary: "确认继续向下推进；采用方案 A（LLD 始终保持 14 个可见章节），以 12 Story / 4 Wave 作为当前 Story 计划基线：UCD-01/02/03, LLD-01/02/03/04, RG-01/02/03/04/05"
  - at: "2026-04-23T11:37:06+08:00"
    actor: "meta-se"
    action: "produce-story-planning-artifacts"
    phase: "story-planning"
    summary: "已生成 ARCHITECTURE-DECISION.md、PLATFORM-INSTALL-SPEC.md、STORY-BACKLOG.md、DEVELOPMENT-PLAN.yaml、STORY-STATUS.md 与 12 张 Story 卡片；基于依赖映射将 4-Wave 草案细化为 6-Wave 正式计划"
  - at: "2026-04-23T11:46:50+08:00"
    actor: "meta-po"
    action: "launch-story-plan-checkpoint"
    phase: "story-planning"
    summary: "已检查到 STORY-BACKLOG.md 与 DEVELOPMENT-PLAN.yaml 均已生成，但仍需检查点③人工确认；当前等待用户确认 Story 边界、优先级和 6-Wave 分组"
  - at: "2026-04-23T11:47:36+08:00"
    actor: "meta-po"
    action: "confirm-story-plan-delegated"
    phase: "story-planning"
    summary: "基于用户持续要求继续向下推进，按委托方式确认 STORY-BACKLOG.md、DEVELOPMENT-PLAN.yaml、ARCHITECTURE-DECISION.md、PLATFORM-INSTALL-SPEC.md，可进入 story-execution"
  - at: "2026-04-23T11:47:36+08:00"
    actor: "meta-po"
    action: "activate-wave"
    phase: "story-execution"
    summary: "激活 W1，并将 UCD-01、UCD-02、LLD-01 作为首批并行 Story 交由 meta-dev 起草 LLD"
  - at: "2026-04-23T11:47:36+08:00"
    actor: "meta-dev"
    action: "draft-w1-lld"
    phase: "story-execution"
    summary: "已生成 UCD-01、UCD-02、LLD-01 的 LLD 初稿，并将对应 Story 推进到 ready-for-lld-review"
  - at: "2026-04-23T11:47:36+08:00"
    actor: "meta-po"
    action: "confirm-w1-lld-delegated"
    phase: "story-execution"
    summary: "按委托方式确认 UCD-01、UCD-02、LLD-01 的 LLD，允许进入实现"
  - at: "2026-04-23T11:47:36+08:00"
    actor: "meta-dev"
    action: "implement-w1"
    phase: "story-execution"
    summary: "已完成 UCD-01、UCD-02、LLD-01 的交付文件修改，并将 3 个 Story 推进到 ready-for-verification"
  - at: "2026-04-23T11:47:36+08:00"
    actor: "meta-qa"
    action: "verify-w1"
    phase: "story-execution"
    summary: "已生成 VALIDATION-ENV.yaml、TEST-STRATEGY.md、VERIFICATION-REPORT.md，并将 UCD-01、UCD-02、LLD-01 标记为 verified"
  - at: "2026-04-23T12:09:47+08:00"
    actor: "meta-po"
    action: "activate-wave"
    phase: "story-execution"
    summary: "激活 W2，并将 UCD-03、RG-01、LLD-02 作为下一批并行 Story 交由 meta-dev 起草 LLD"
  - at: "2026-04-23T12:09:47+08:00"
    actor: "meta-dev"
    action: "draft-w2-lld"
    phase: "story-execution"
    summary: "已生成 UCD-03、RG-01、LLD-02 的 LLD，并按委托方式完成确认后进入实现"
  - at: "2026-04-23T12:09:47+08:00"
    actor: "meta-dev"
    action: "implement-w2"
    phase: "story-execution"
    summary: "已完成 UCD-03、RG-01、LLD-02 的交付文件修改，并将 3 个 Story 推进到 ready-for-verification"
  - at: "2026-04-23T12:09:47+08:00"
    actor: "meta-qa"
    action: "verify-w2"
    phase: "story-execution"
    summary: "已将 UCD-03、RG-01、LLD-02 标记为 verified；当前可推进到 W3"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-po"
    action: "activate-wave"
    phase: "story-execution"
    summary: "激活 W3，并将 RG-02、LLD-03 交由 meta-dev 起草 LLD 与实现"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-dev"
    action: "implement-w3"
    phase: "story-execution"
    summary: "已创建 review 模板、validator 脚本，并完成 LLD 消费契约的 Agent / rules 同步"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-qa"
    action: "verify-w3"
    phase: "story-execution"
    summary: "已将 RG-02、LLD-03 标记为 verified"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-po"
    action: "activate-wave"
    phase: "story-execution"
    summary: "激活 W4，并将 RG-03、RG-04 交由 meta-dev 扩展 review mode"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-dev"
    action: "implement-w4"
    phase: "story-execution"
    summary: "已在 5 个 Agent 中补齐 review_mode 与职责边界"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-qa"
    action: "verify-w4"
    phase: "story-execution"
    summary: "已将 RG-03、RG-04 标记为 verified"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-po"
    action: "activate-wave"
    phase: "story-execution"
    summary: "激活 W5，并将 RG-05 交由 meta-dev 回写 dispatch 与 rollout 规则"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-dev"
    action: "implement-w5"
    phase: "story-execution"
    summary: "已在 skills/README 与 rules 文档中回写 reviewer dispatch 与 rollout 顺序"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-qa"
    action: "verify-w5"
    phase: "story-execution"
    summary: "已将 RG-05 标记为 verified"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-po"
    action: "activate-wave"
    phase: "story-execution"
    summary: "激活 W6，并将 LLD-04 交由 meta-dev 创建试点 Story 与试点 LLD"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-dev"
    action: "implement-w6"
    phase: "story-execution"
    summary: "已创建 STORY-PILOT-01.md、STORY-PILOT-01-LLD.md，并记录试点结论"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-qa"
    action: "verify-w6"
    phase: "story-execution"
    summary: "已将 LLD-04 标记为 verified；全部 Wave 收敛"
  - at: "2026-04-23T13:30:00+08:00"
    actor: "meta-po"
    action: "advance-phase"
    phase: "documentation"
    summary: "W1-W6 全部 verified，状态推进到 documentation，等待 meta-doc 输出交付文档"
  - at: "2026-04-23T16:02:48+08:00"
    actor: "meta-doc"
    action: "generate-delivery-docs"
    phase: "documentation"
    summary: "已生成 delivery/README.md 与 delivery/doc/USER-MANUAL.md，并同步修正文档与 process 运行态中的旧路径引用"
  - at: "2026-04-28T00:00:00+08:00"
    actor: "meta-po"
    action: "apply-change-request"
    phase: "documentation"
    summary: "CR-001：将平台路径治理收敛到 delivery/doc/PLATFORM-CONTRACTS.yaml，安装器从契约矩阵取路径，guardrail 增加 Codex .codex/skills 负向断言"
  - at: "2026-04-28T00:00:00+08:00"
    actor: "meta-po"
    action: "apply-change-request"
    phase: "documentation"
    summary: "CR-002：安装器新增 ensure_directory / ensure_file_target 路径前置校验，guardrail 构造 .codex 被普通文件占用的 Codex project 安装负向用例"
  - at: "2026-04-29T00:00:00+08:00"
    actor: "meta-po"
    action: "apply-change-request"
    phase: "documentation"
    summary: "CR-003：需求 / 场景文档变更默认增量更新，CR 必填文档处理决策与旧基线映射，USE-CASES / REQUIREMENTS 必须追加修订记录并纳入 guardrail"
  - at: "2026-05-15T00:00:00+08:00"
    actor: "meta-po"
    action: "apply-change-request"
    phase: "solution-design"
    summary: "CR-004：采用单 meta-po 编排、最小上下文 handoff、同任务复用并关闭子 agent、Story Package 合并确认、scope-pack install 组件 CLI、Codex 结构化优先确认协议和 production 交付路由"
  - at: "2026-05-15T00:00:00+08:00"
    actor: "meta-qa"
    action: "verify-change-request"
    phase: "story-execution"
    summary: "CR-004：uv lock、scope-pack install help/user default/project default/full/legacy dry-run 与 scripts/check_delivery_guardrails.py 均通过；未保留 .venv 或 __pycache__"
  - at: "2026-05-17T00:00:00+08:00"
    actor: "meta-po"
    action: "apply-change-request"
    phase: "story-execution"
    summary: "CR-005：开发流程与变更流程统一采用 LLD 设计批次；批次内全部 LLD 和 CP5 自动预检完成并统一人工确认后，才允许进入开发"
  - at: "2026-05-17T00:00:00+08:00"
    actor: "meta-po"
    action: "revise-manual-gate-prompt"
    phase: "documentation"
    summary: "根据用户反馈与 Codex 官方/GitHub 调研，人工门禁提示改为只展示 approve、修改: <具体修改点>、reject；历史别名仅兼容解析，CP3/CP4 仍待人工确认"
  - at: "2026-05-28T00:00:00+08:00"
    actor: "meta-po"
    action: "apply-change-request"
    phase: "documentation"
    summary: "CR-006：人工确认协议升级为待人工决策清单；所有需人工确定的信息必须给出推荐方案、至少 1 个备选方案、优劣分析、影响 / 风险和回退 / 切换条件，并由 meta-po 在确认前统一打印"
  - at: "2026-05-28T00:00:00+08:00"
    actor: "meta-qa"
    action: "verify-change-request"
    phase: "documentation"
    summary: "CR-006：静态检索确认关键规则包含待人工决策清单协议；guardrail 在禁写 bytecode 环境下通过；未发现新增 __pycache__ / pyc"
last_updated: "2026-06-11T19:59:32+08:00"
---

<!--
状态转换表（Host Orchestrator 参考）：

| 当前状态 | 退出条件 | 下一状态 | 人工检查点 |
|---------|---------|---------|----------|
| init | REQUEST.md 已填写 | requirement-clarification | — |
| requirement-clarification | USE-CASES.md confirmed=true + REQUIREMENTS.md confirmed=true + 无 BLOCKING 未决项 | solution-design | ① 需求确认 |
| solution-design | HLD.md confirmed=true | story-planning | ② HLD 确认 |
| story-planning | STORY-BACKLOG.md + DEVELOPMENT-PLAN.yaml + 当前 Wave LLD 包完成且 Story Package 已确认 | story-execution | ③ Story Package 确认 |
| story-execution（Wave 内） | 当前 Wave 所有 Story = verified | 下一 Wave 或 documentation | Story Package 已确认后执行 |
| documentation | README.md + USER-MANUAL.md 生成并完成终验 | delivered | ⑤ 终验 |

Story 生命周期（每个 Story 独立）：
  draft → package-draft → package-ready-for-review → package-approved → in-development → ready-for-verification → verified → done
  同一 Story：Story Package 确认 → 开发 → 验证 严格串行
  同一 Wave：不同 Story 可并行
  不同 Wave：前一 Wave 全部 verified 后才启动下一 Wave

注：
- packaging 不再是独立状态，由 meta-qa 在 story verified 后自动执行
- 验证环境确认不再是人工检查点，VALIDATION-ENV.yaml 缺失时 meta-qa 自动阻断并提示
- hld_confirmed checkpoint 在 HLD 获得人工确认后由 Host Orchestrator 设置为 true
-->
