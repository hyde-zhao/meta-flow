---
name: phase-designer
description: >-
  当需要将需求和场景组织为执行阶段时使用。
  触发词包括：阶段划分、设计阶段、Phase 设计、执行顺序。
  适用场景：工作流计划设计的第一步。
argument-hint: "REQUIREMENTS.md 和 SCENARIOS.yaml 路径"
user-invokable: true
status: draft
---

## 目标

根据需求和场景的类型、风险级别和依赖关系，将测试活动组织为有序的执行阶段（Phase），每个阶段有明确的目标和进入/退出条件。

## 适用范围

- 适用阶段：计划设计阶段（plan-design）
- 输入：`REQUIREMENTS.md`、`SCENARIOS.yaml`
- 输出：`WORKFLOW-PLAN.yaml` 中的 phases 结构

## 前置条件

- [ ] `REQUIREMENTS.md` 状态为 confirmed
- [ ] `SCENARIOS.yaml` 已生成
- [ ] `VENDOR-CONSTRAINTS.yaml` 已生成

## 执行约束

- 标准阶段模板按以下顺序排列：precheck → positive → negative → edge → cleanup
- 可根据实际需求裁剪（如无边界场景则省略 edge 阶段）
- 每个阶段必须有至少一个 Wave
- cleanup 阶段是强制的——即使测试成功也必须清理
- 阶段之间是串行关系，阶段内的 Wave 可以并行

## 阶段设计决策指南

| 决策点 | 规则 |
|--------|------|
| 前置检查放在哪里 | 永远是第一个阶段，任何检查失败则整体终止 |
| 正向和负向是否分阶段 | 推荐分开——先正向验证功能正常，再负向验证阻断正确，避免污染会话状态 |
| 修改配置的任务放在哪里 | 如果需要临时修改配置进行验证，应在 positive/negative 中处理，但配置恢复放在 cleanup |
| 高风险任务放在哪里 | 放在独立 Wave 中，不与其他任务并行 |

## Gotchas

- 不要把 cleanup 放在 positive 或 negative 阶段之间——如果中间阶段失败跳转到 cleanup，可能会跳过后续必要的验证
- precheck 阶段不应包含任何配置修改操作，它只做"看"不做"改"

## 验收标准

- 每个阶段有明确的 id、name、description 和 order
- 阶段顺序合理（precheck 最先，cleanup 最后）
- cleanup 阶段存在
- 每个场景至少被分配到一个阶段的任务中
