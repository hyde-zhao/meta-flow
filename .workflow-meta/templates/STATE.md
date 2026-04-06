---
project_id: ""
workflow_mode: ""
current_phase: "init"
current_agent: "meta-po"
iteration: 0
blocked: false
last_action: ""
next_action: "初始化 REQUEST.md，唤醒 meta-pm 启动需求澄清"
checkpoints:
  requirement_confirmed: false
  design_confirmed: false
  story_plan_confirmed: false
  validation_env_ready: false
  final_package_verified: false
  documentation_done: false
parallel_waves: []
history: []
last_updated: ""
---

<!--
状态转换表（meta-po 参考）：

| 当前状态 | 退出条件 | 下一状态 |
|---------|---------|---------|
| init | REQUEST.md 已填写 | requirement-clarification |
| requirement-clarification | REQUIREMENTS.md confirmed=true + 无 BLOCKING 未决项 | solution-design |
| solution-design | ARCHITECTURE-DECISION.md confirmed=true | skill-production（simple）/ story-planning（standard/complex）|
| story-planning | STORY-BACKLOG.md + DEVELOPMENT-PLAN.yaml 人工确认 | story-development |
| story-development | 当前 Wave 所有 Story = ready-for-verification | verification |
| skill-production | Skill 文件输出完成 | verification |
| verification | VERIFICATION-REPORT.md 无 BLOCKING 未通过项 | packaging |
| packaging | PACKAGE-MANIFEST.yaml + 平台包生成 | documentation |
| documentation | README.md + USER-MANUAL.md 生成 | human-final-review |
| human-final-review | 人工批准 | delivered |
-->
