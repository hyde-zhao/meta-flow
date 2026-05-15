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
  reuse_policy: "same workflow/change/story reuses the same role thread; close after checkpoint or handoff completion"
checkpoints:
  requirement_confirmed: false
  hld_confirmed: false
  story_package_confirmed: false
  final_review_confirmed: false
parallel_waves: []
history: []
last_updated: ""
---

<!--
状态转换表（meta-po 参考）：

| 当前状态 | 退出条件 | 下一状态 | 人工检查点 |
|---------|---------|---------|----------|
| init | REQUEST.md 已填写 | requirement-clarification | — |
| requirement-clarification | USE-CASES.md confirmed=true + REQUIREMENTS.md confirmed=true + 无 BLOCKING 未决项 | solution-design | ① 需求确认 |
| solution-design | HLD.md confirmed=true | story-planning | ② HLD 确认 |
| story-planning | STORY-BACKLOG.md + DEVELOPMENT-PLAN.yaml + 当前 Wave LLD 包 confirmed=true | story-execution | ③ Story Package 确认 |
| story-execution（Wave 内） | 当前 Wave 所有 Story = verified | 下一 Wave 或 documentation | — |
| documentation | README.md + USER-MANUAL.md 生成并完成终验 | delivered | ⑤ 终验 |

Story 生命周期（每个 Story 独立）：
  draft → package-draft → package-ready-for-review → package-approved → in-development → ready-for-verification → verified → done
  同一 Story：LLD → 开发 → 验证 严格串行
  同一 Wave：不同 Story 可并行
  不同 Wave：前一 Wave 全部 verified 后才启动下一 Wave

注：
- packaging 不再是独立状态，由 meta-qa 在 story verified 后自动执行
- 验证环境确认不再是人工检查点，VALIDATION-ENV.yaml 缺失时 meta-qa 自动阻断并提示
- hld_confirmed checkpoint 在 HLD 获得人工确认后由 meta-po 设置为 true
-->
