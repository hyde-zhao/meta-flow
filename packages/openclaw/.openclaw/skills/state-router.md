---
name: state-router
description: >-
  当需要推进工作流状态、回退到上一阶段、查询当前进度、或判断下一步应调用哪个 Agent 时使用。
  触发词包括：推进、下一步、当前状态、回退、状态查询、继续。
  适用场景：元工作流全流程的状态管理。
argument-hint: "可选：指定目标状态或要查询的字段"
user-invokable: true
status: draft
---

## 目标

读取 `STATE.md`，根据当前阶段的退出条件判断是否可以推进，输出下一步应调用的 Agent 和需要加载的上下文，并更新 `STATE.md`。

## 适用范围

- 适用阶段：元工作流全部 9 个状态阶段
- 接入方式：读写 `.fw-meta/STATE.md`（运行时）或参考 `.fw-meta/templates/STATE.md`（模板）
- 触发时机：每次阶段切换、用户主动查询、异常恢复

## 前置条件

- [ ] `.fw-meta/STATE.md` 已存在（首次使用时从模板初始化）
- [ ] 当前阶段的主要产物文件已确认存在或不存在

## 执行约束

- 只做状态判断和推进决策，不做任何内容生成
- 推进前必须检查当前阶段的退出条件是否全部满足
- 回退时必须在 `history` 中记录回退原因
- 每次操作都必须回写 `STATE.md` 并更新 `last_updated`
- 当 `blocked=true` 时，拒绝推进并说明阻塞原因

## 状态转换判断规则

根据 `current_phase` 值，检查以下退出条件：

| 当前阶段 | 退出条件 | 下一阶段 | 需通知 Agent |
|----------|----------|----------|-------------|
| init | STATE.md 已初始化、input_spec.yaml 已录入 | requirement 或 vendor | Requirement Analyst 或 Vendor Adapter |
| requirement | REQUIREMENTS.md + SCENARIOS.yaml 已生成且 requirement_confirmed=true | plan-design | Workflow Planner |
| vendor | VENDOR-CONSTRAINTS.yaml 已生成 | plan-design | Workflow Planner |
| plan-design | WORKFLOW-PLAN.yaml 已生成 | plan-check | Plan Checker |
| plan-check | PLAN-CHECK-REPORT.md 结论为 pass | safety-review | Safety Reviewer |
| plan-check (failed) | PLAN-CHECK-REPORT.md 结论为 fail | plan-design | Workflow Planner（quality_check 轮次 +1） |
| safety-review | SAFETY-REPORT.md verdict 为 approved | delivery | Delivery Agent |
| safety-review (failed) | SAFETY-REPORT.md verdict 为 blocked | plan-design | Workflow Planner（safety_check 轮次 +1） |
| delivery | OUTPUT/*.md + CONTEXT-MANIFEST.yaml 已生成 | human-review | 人工评审者 |
| human-review | 用户批准 | delivered | 流程结束 |

## Gotchas

- 回退到 plan-design 时，必须检查 quality_check 或 safety_check 轮次是否已达上限（3 轮 / 2 轮），达到上限时应升级为 L3 人工接管而非继续回退
- requirement 和 vendor 可以并行推进（两者无强依赖），但 plan-design 需要两者都完成
- 首次初始化时 STATE.md 可能不存在，需要从模板复制并填充 project_id

## 验收标准

- 推进后 `STATE.md` 的 `current_phase` 和 `current_agent` 正确更新
- `history` 数组新增一条记录且 timestamp 为当前时间
- 回退操时 `round` 计数正确递增
- 阻塞状态下调用时返回阻塞原因而非静默忽略
