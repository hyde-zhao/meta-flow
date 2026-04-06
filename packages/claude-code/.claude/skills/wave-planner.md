---
name: wave-planner
description: >-
  当需要决定哪些任务可以并行执行、哪些必须串行时使用。
  触发词包括：并行分组、Wave 划分、并行计划、任务编排。
  适用场景：工作流计划设计阶段，Phase 划分之后。
argument-hint: "WORKFLOW-PLAN.yaml（已有 phases）和 VENDOR-CONSTRAINTS.yaml"
user-invokable: true
status: draft
---

## 目标

在每个 Phase 内部划分 Wave 并行组，决定哪些任务可以安全地同时执行，哪些必须串行。

## 适用范围

- 适用阶段：计划设计阶段，phase-designer 之后
- 输入：已有 phases 的 `WORKFLOW-PLAN.yaml`、`VENDOR-CONSTRAINTS.yaml`
- 输出：更新 `WORKFLOW-PLAN.yaml` 中的 waves 结构

## 前置条件

- [ ] `WORKFLOW-PLAN.yaml` 中已有 phases 定义
- [ ] `VENDOR-CONSTRAINTS.yaml` 中 `resource_limits` 已填写

## 执行约束

- 同一 Wave 内的任务标记为 `parallel: true` 时必须满足以下所有条件：
  1. 任务之间无数据依赖（不互相 depends_on）
  2. 不同时修改同一设备配置
  3. 高风险任务不与同网段其他任务并行
  4. 并发数不超过厂商 `resource_limits.max_ssh_sessions`
- 不同 Wave 之间是串行的（Wave 1 全部完成后才执行 Wave 2）
- precheck 和 cleanup 阶段内通常只有一个 Wave（串行执行）

## 并行安全判定

| 任务 A 属性 | 任务 B 属性 | 可并行？ | 原因 |
|------------|------------|---------|------|
| 只读（display） | 只读（display） | ✅ | 无冲突 |
| 只读（display） | 修改配置 | ❌ | 读取结果可能不一致 |
| 修改配置 | 修改配置 | ❌ | 配置冲突 |
| 低风险 | 低风险 | ✅ | 风险可控 |
| 高风险 | 任何 | ❌ | 高风险任务必须独占 |

## Gotchas

- SSH 并发数是硬限制——华为路由器默认最多 5 个 SSH 会话，超过会导致连接被拒绝
- 即使两个 display 命令理论上可以并行，如果它们的输出都超过一屏且使用了 `screen-length 0 temporary`，并行执行可能导致输出交错

## 验收标准

- 每个 Wave 内的并行任务确实满足无冲突条件
- 并发任务数不超过设备 SSH 会话限制
- 高风险任务在独立 Wave 中
- Wave 之间的顺序逻辑正确
