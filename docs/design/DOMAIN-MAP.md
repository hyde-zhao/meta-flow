---
status: baseline
version: "1.0"
confirmed_by: "meta-po"
confirmed_at: "2026-06-07"
---

# Meta Flow Domain Map

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-07 | meta-po | 建立 Meta Flow v2 核心领域对象、状态机和业务规则基线 |
| 1.1 | 2026-06-11 | host-orchestrator | 新增 project kind、validation target、workflow eval、prompt bundle、case registry 和 suite health 对象 |

## 1. 术语表

| Term | 定义 | 来源 | 备注 |
|---|---|---|---|
| Workflow | 一次由 Host Orchestrator 主进程编排的端到端工作流实例 | `STATE.md` | 默认 `workflow_mode=standard` |
| Phase | 工作流阶段，如 requirement-clarification、solution-design、story-planning | AGENTS | 阶段推进必须回写状态 |
| Checkpoint | CP0-CP8 检查点，分自动检查和人工确认 | checkpoint-manager | 自动写 `process/checks`，人工写 `process/checkpoints` |
| Human Gate | CP2 / CP3 / CP5 / CP8 的正式人工确认门 | AGENTS | 由 `meta-po` 发起 |
| Decision Brief | 人工确认前给用户的决策摘要 | checkpoint-manager | 必须含推荐、备选、优劣、风险和回退 |
| Pending Human Decision | 结构化待人工决策项 | `STATE.md.human_gate_decisions` | 不得只留在对话或下游 Markdown |
| Context Capsule | 阶段上下文胶囊 | context-manifest-builder | 下游默认先读，必要时展开正式文档 |
| Story | 可执行的工作单元 | story-manager | 包含 owner、依赖、file ownership、lld_policy |
| LLD Evidence | Story 设计证据 | lld-designer | 可为 full-lld、technical-note 或 waived |
| Implementation Evidence | Story 实现证据 | implementation-execution | CP6 消费 |
| Verification Evidence | Story 验证证据 | verification-execution | CP7 / CP8 消费 |
| Change Request | 变更单 | change-impact-analysis | 修改正式对象前必须创建 |
| Follow-up Candidate | CP8 后续候选项 | change-impact-analysis | 只进台账，不自动创建正式 CR |
| Archived Agent | 已归档 Agent | CR-017 | `meta-dm` 已归档，不可安装 / 唤醒 |
| Project Kind | 目标项目类型画像 | CR-018 / CR-019 | code-project / workflow-product / agentic-code-product / mixed / unknown |
| Validation Target | Story 或交付对象的验证目标 | CR-018 / CR-021 | 决定 code / workflow / prompt / mixed 验证层 |
| Prompt Bundle | 版本化 prompt / rules / agent / skill 契约 | CR-019 | 默认保存引用、hash、兼容范围和 rollback |
| Workflow Eval Suite | 工作流评估套件 | CR-019 / CR-020 | 本地 deterministic runner 的输入 |

## 2. 领域对象

| Object ID | 对象 | Owner Feature | 关键字段 / 属性 | 状态 | 规则来源 |
|---|---|---|---|---|---|
| OBJ-01 | Workflow State | FEAT-WORKFLOW-ORCHESTRATION | current_phase、workflow_mode、active_change、checkpoints、history | active / blocked / delivered | state-router |
| OBJ-02 | Human Decision Queue | FEAT-HUMAN-GATE-DECISION-BRIEF | pending_human_decisions[]、decision_collection_coverage、non_authorized_items | empty / pending / resolved | AGENTS / checkpoint-manager |
| OBJ-03 | Checkpoint Result | FEAT-HUMAN-GATE-DECISION-BRIEF | cp_id、entry criteria、checklist、exit criteria、deliverables、result | PASS / FAIL / BLOCKED / WAIVED | checkpoint-manager |
| OBJ-04 | Agent Lifecycle Registry | FEAT-AGENT-LIFECYCLE-CONTEXT | active_agents、platform_capabilities、dispatch evidence、thread_id | idle / delegated / running / completed / blocked | AGENTS |
| OBJ-05 | Context Capsule | FEAT-AGENT-LIFECYCLE-CONTEXT | must_read、read_if_needed、do_not_read_by_default、key_facts、read_expansion_log | draft / ready / stale | context-manifest-builder |
| OBJ-06 | Product Artifact | FEAT-SCENARIO-DISCOVERY | USE-CASES、REQUIREMENTS、SCENARIOS、TEST-MATRIX、STORY-MAP、MVP-SCOPE | draft / confirmed / superseded | meta-pm |
| OBJ-07 | Design Artifact | FEAT-SOLUTION-DESIGN | BLUEPRINT、DOMAIN-MAP、DEPENDENCY-MAP、HLD、ADR、FEATURE-DESIGN-MATRIX | draft / baseline / confirmed / superseded | meta-se |
| OBJ-08 | Story Card | FEAT-DESIGN-EVIDENCE | story_id、status、depends_on、file_ownership、feature_design_refs、lld_policy | draft / lld-ready / dev-ready / verified | story-manager |
| OBJ-09 | LLD Clarification Item | FEAT-DESIGN-EVIDENCE | id、story_id、question、options、recommendation、blocks_lld、answer、status | open / answered / converted-to-spike / closed | meta-dev / meta-po |
| OBJ-10 | Implementation Evidence | FEAT-IMPLEMENTATION-VERIFICATION | implementation objects、contract mapping、fixtures、rollback、handoff | draft / ready-for-verification / rework | implementation-execution |
| OBJ-11 | Verification Evidence | FEAT-IMPLEMENTATION-VERIFICATION | validation objects、trace matrix、contract checks、decision | PASS / PASS_WITH_RISK / BLOCKED / NEEDS_REWORK / WAIVED | verification-execution |
| OBJ-12 | Release Context | FEAT-RELEASE-DOCUMENTATION | release_artifact_profile、release_decision、quality_summary、risk summary | minimal / compact / full; READY / NOT_READY | release-readiness |
| OBJ-13 | Platform Contract | FEAT-INSTALLER-GUARDRAILS | platform scopes、forbidden paths、rules / agents / skills dirs | active / invalid | `delivery/doc/PLATFORM-CONTRACTS.yaml` |
| OBJ-14 | Delivery Asset | FEAT-INSTALLER-GUARDRAILS | agents、skills、rules、scripts、status | active / archived | install.py / guardrail |
| OBJ-15 | Target Project Profile | FEAT-WORKFLOW-EVAL-GOVERNANCE | project_kind、confidence、source、delivery_routing_ref、validation_defaults | unknown / classified | state-router |
| OBJ-16 | Validation Target | FEAT-IMPLEMENTATION-VERIFICATION | sut_type、native_test_required、workflow_eval_required、prompt_bundle_required、eval_suite_refs | pending / ready / n/a | story-manager / verification-execution |
| OBJ-17 | Workflow Eval Suite | FEAT-WORKFLOW-EVAL-GOVERNANCE | suite_id、sut、prompt_bundle、case_registry、trace_policy、graders | draft / valid / failed | `meta-flow eval validate` |
| OBJ-18 | Prompt Bundle | FEAT-WORKFLOW-EVAL-GOVERNANCE | bundle_id、version、components、sha256、compatibility、rollback | valid / drifted / failed | prompt bundle grader |
| OBJ-19 | Eval Case Registry | FEAT-WORKFLOW-EVAL-GOVERNANCE | registry_id、cases、category、grader refs、expected_result | draft / active / quarantined / archived | case registry links |
| OBJ-20 | Eval Run Evidence | FEAT-WORKFLOW-EVAL-GOVERNANCE | run_id、suite_id、status、grader_results、issues | PASS / FAIL | `process/evals/runs/*` |
| OBJ-21 | Eval Suite Health | FEAT-WORKFLOW-EVAL-GOVERNANCE | total_runs、passed、failed、open_blocking_failures | healthy / degraded / failing | `docs/quality/EVAL-SUITE-HEALTH.md` |

## 3. 状态机

| State Machine ID | 对象 | 状态 | 合法转换 | 非法转换处理 |
|---|---|---|---|---|
| SM-01 | Workflow Phase | init -> requirement-clarification -> solution-design -> story-planning -> story-execution -> documentation -> delivered | CP exit criteria 通过后推进 | 缺少 CP 或人工门禁未通过时阻断 |
| SM-02 | Human Gate | not-started -> brief-ready -> awaiting-user -> approved / changes-requested / rejected | Decision Brief 校验通过后进入 awaiting-user | 决策项缺失、未打印表格或无 checklist 路径时发起失败 |
| SM-03 | Story | draft -> lld-ready -> lld-ready-for-review -> dev-ready -> implementing -> ready-for-verification -> verified | CP5 通过后才能进入 dev-ready | CP5 前实现 Story 视为门禁违规 |
| SM-04 | Verification | ready-for-verification -> PASS / PASS_WITH_RISK / BLOCKED / NEEDS_REWORK / NEEDS_DESIGN_CLARIFICATION / WAIVED | CP7 产出阶段决策 | `NEEDS_REWORK` 不得标记 verified |
| SM-05 | LLD Clarification | open -> answered -> distributed -> closed | meta-po 批量询问并回填答案 | `blocks_lld=true` 未回答时不得发起 CP5 |
| SM-06 | Agent Lifecycle | idle -> spawned / resumed -> running -> completed / blocked / closed | 有真实调度证据或批准的 inline fallback | handoff-only 不得视为 completed |
| SM-07 | CR | candidate -> active -> closed / cancelled / superseded / blocked | 用户启动正式 CR 后 active | follow-up candidate 不占执行锁 |
| SM-08 | Delivery Asset | active -> archived | 通过 CR 明确废弃并移出 delivery | archived 资产回到 delivery 时 guardrail 失败 |
| SM-09 | Eval Case | draft -> active -> quarantined / deprecated / archived | case registry 变更经 CR 或 suite health 分流 | candidate case 不得作为 required gate |
| SM-10 | Eval Run | not-started -> running -> PASS / FAIL | runner 生成 run evidence | FAIL 不得被 CP7 静默忽略 |

## 4. 业务规则

| Rule ID | 规则 | Owner | 影响场景 | 验证入口 |
|---|---|---|---|---|
| RULE-01 | 标准模式 CP2 前必须产生至少 1 条用户可见 SGQ 场景确认交互 | FEAT-SCENARIO-DISCOVERY | 场景发现 | CP2 自动检查 |
| RULE-02 | CP2 / CP3 / CP5 / CP8 人工门禁必须打印待决策表；`approve` 只接受推荐方案，不授权真实运行 | FEAT-HUMAN-GATE-DECISION-BRIEF | 人工确认 | human gate validator |
| RULE-03 | `meta-po` 是正式人工门禁和运行授权问题唯一发起者 | FEAT-HUMAN-GATE-DECISION-BRIEF | CP2 / CP3 / CP5 / CP8 | AGENTS / guardrail |
| RULE-04 | `meta-dev` 在并行 LLD 阶段只写 clarification queue，不直接问用户 | FEAT-DESIGN-EVIDENCE | LLD 写作 | CP5 |
| RULE-05 | Story 开发必须等全部目标 Story 设计证据统一确认 | FEAT-DESIGN-EVIDENCE | Story execution | CP5 |
| RULE-06 | CP6 / CP7 必须有 Agent Dispatch Evidence；handoff 不等于执行完成 | FEAT-AGENT-LIFECYCLE-CONTEXT | 实现 / 验证 | CP6 / CP7 |
| RULE-07 | production 项目先读目标 README/docs 约定，不能默认写当前仓库 `delivery/` | FEAT-DESIGN-DOCUMENT-LAYERING | 交付出口 | CP0 / CP8 |
| RULE-08 | 长期设计文档写 `docs/design`，执行态 Story / LLD 证据写 `process/stories` | FEAT-DESIGN-DOCUMENT-LAYERING | 文档路由 | guardrail / review |
| RULE-09 | 平台路径以 `delivery/doc/PLATFORM-CONTRACTS.yaml` 为单一真相源 | FEAT-INSTALLER-GUARDRAILS | 安装 / 平台校验 | guardrail |
| RULE-10 | 已归档 `meta-dm` 不得安装、唤醒或重新出现在 `delivery/agents` | FEAT-INSTALLER-GUARDRAILS | Agent 生命周期 | guardrail |
| RULE-11 | 发布阶段默认 capsule-first，按 `release_artifact_profile` 控制文档厚度 | FEAT-RELEASE-DOCUMENTATION | CP8 | release-readiness |
| RULE-12 | 权限、安全、运行授权、外部写入和 live / 交易类事项必须进入独立决策项 | FEAT-HUMAN-GATE-DECISION-BRIEF | 设计 / 发布 | Decision Brief |
| RULE-13 | `project_kind=code-project` 时 workflow eval 默认 N/A，除非 Story 显式要求 | FEAT-WORKFLOW-EVAL-GOVERNANCE | 纯代码项目验证 | CP7 |
| RULE-14 | `sut_type=generated-workflow|prompt-skill-workflow|agentic-code-product|mixed` 时必须消费 eval evidence 或写明 WAIVED / BLOCKED | FEAT-WORKFLOW-EVAL-GOVERNANCE | workflow / prompt 验证 | CP7 |
| RULE-15 | Promptfoo / DeepEval / Langfuse / Garak 默认 disabled；网络、凭据和 trace 上传必须有 runtime_authorization | FEAT-WORKFLOW-EVAL-GOVERNANCE | 外部 adapter | CP7 / CP8 |

## 5. Gotchas

- `status=baseline` 表示当前正式基线，不等于一次新 CP3 已发起并通过。
- `process/HLD*.md` 是历史专题设计来源，不是当前总体 HLD 的默认消费入口。
- Story LLD 保留在 `process/stories/`，不要迁移到 `docs/design/`。
- `Decision Brief` 是人工确认入口，不是把所有讨论复制给用户的长文档。
