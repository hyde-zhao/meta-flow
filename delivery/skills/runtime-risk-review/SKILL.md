---
name: runtime-risk-review
description: >-
  当需要复核工作流的运行时风险（DryRun、隔离、权限最小化）时使用。
  触发词包括：运行时风险、DryRun、执行环境、隔离检查。
  适用场景：安全审计的运行时层检查。
argument-hint: "process/DEVELOPMENT-PLAN.yaml、process/context/*-CONTEXT.yaml 或 process/release/RELEASE-CONTEXT.yaml 路径"
user-invokable: true
status: active
---

## 目标

复核工作流计划的运行时安全特性，包括 DryRun 模式支持、执行隔离配置、权限最小化水平。

## 适用范围

- 适用阶段：CP4 / CP7 / CP8 的运行时风险复核
- 对应审计层：第四层（运行时层安全检查）
- 本层为建议性检查，不直接阻断

## 前置条件

- [ ] `process/DEVELOPMENT-PLAN.yaml`、验证上下文或发布上下文已生成

## 执行约束

- 检查 dry-run / fixture / sandbox / manual-review / waived 的验证方式是否存在和合理
- 检查是否有沙箱/隔离环境的建议
- 检查执行权限是否满足最小化原则
- 本层检查结果为建议级别，不直接产生 BLOCKING 判定

## 检查清单

| 检查项 | 合格标准 | 级别 |
|--------|---------|------|
| DryRun / Fixture 模式 | 验证或发布上下文声明 dry-run、fixture、sandbox、manual-review 或 N/A 理由 | RECOMMENDED |
| 执行隔离 | 建议在隔离环境执行高风险任务 | RECOMMENDED |
| 权限最小化 | 执行中使用的权限不超过必要范围 | RECOMMENDED |
| 超时保护 | 所有 task 有 timeout_seconds | REQUIRED |
| 失败保护 | 所有 task 有 on_failure 策略 | REQUIRED |

## Gotchas

- DryRun 模式对于只包含 `display` 类只读操作的计划不是必须的——只有包含配置修改操作时才应强烈建议
- 运行时层是元工作流智能力的边界——实际的隔离和权限控制由外部执行器负责，这里只做声明性检查

## 验收标准

- 输出运行时风险检查清单（含每项的通过/不通过状态）
- 有配置修改操作时明确建议 DryRun
- 结论写入对应 CP 检查摘要或发布就绪风险表
