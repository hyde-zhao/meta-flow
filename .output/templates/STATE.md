---
project_id: ""
workflow_mode: ""
current_phase: "init"
current_agent: "meta-po"
iteration: 0
blocked: false
last_action: ""
next_action: "执行 init 阶段：创建工作目录结构，初始化 REQUEST.md，引导用户填写后唤醒 meta-pm"
checkpoints:
  requirement_confirmed: false
  solution_selected: false
  story_plan_confirmed: false
  final_package_verified: false
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
| solution-design（方案输出完成） | SOLUTION-OPTIONS.md 已输出（≥2 个方案） | — | ② 方案选择确认（用户选定后继续） |
| solution-design（方案已选定） | ARCHITECTURE-DECISION.md confirmed=true | story-planning | — |
| story-planning | STORY-BACKLOG.md + DEVELOPMENT-PLAN.yaml 输出完成 | story-execution | ③ Story 计划确认 |
| story-execution（Wave 内） | 当前 Wave 所有 Story = verified（每个 Story 经历 dev→qa 串行） | 下一 Wave 或 documentation | — |
| documentation | README.md + USER-MANUAL.md 生成 | delivered | ④ 终验 |

Story 生命周期（每个 Story 独立）：
  draft → approved → in-development(meta-dev) → ready-for-verification → verified(meta-qa)
  同一 Story：dev 和 qa 严格串行
  同一 Wave：不同 Story 可 /fleet 并行
  不同 Wave：前一 Wave 全部 verified 后才启动下一 Wave

注：
- packaging 不再是独立状态，由 meta-qa 在 story verified 后自动执行
- 验证环境确认不再是人工检查点，VALIDATION-ENV.yaml 缺失时 meta-qa 自动阻断并提示
- solution_selected checkpoint 在用户选定方案后由 meta-po 设置为 true
-->
