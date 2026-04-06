---
name: permission-boundary-check
description: >-
  当需要检查工作流计划的操作是否超出权限边界时使用。
  触发词包括：权限检查、权限边界、越权验证、安全边界。
  适用场景：安全审计的输入层和规划层检查。
argument-hint: "input_spec.yaml 和 WORKFLOW-PLAN.yaml 路径"
user-invokable: true
status: draft
---

## 目标

对比 `input_spec.yaml` 中声明的安全边界（security_boundaries）和 `WORKFLOW-PLAN.yaml` 中的实际操作，检测是否存在越权行为。

## 适用范围

- 适用阶段：安全审计阶段（safety-review）
- 对应审计层：第一层（输入层）+ 第二层（规划层）

## 前置条件

- [ ] `input_spec.yaml` 中 `security_boundaries` 字段已填写
- [ ] `WORKFLOW-PLAN.yaml` 已生成

## 执行约束

- 检查 `production_impact_allowed` 为 false 时，是否有操作可能影响生产网
- 检查 `destructive_operations_allowed` 为 false 时，是否有破坏性操作
- 检查 `max_risk_level` 阈值，是否有超出的操作
- 检查 `require_dry_run` 为 true 时，是否设置了 dry_run_mode
- 检查命令目标网段是否在 allowed_networks 范围内

## 检查规则

| 安全边界字段 | 检查逻辑 | 违规级别 |
|------------|---------|---------|
| production_impact_allowed = false | 计划中不得有生产网操作 | BLOCKING |
| destructive_operations_allowed = false | 计划中不得有破坏性配置命令 | BLOCKING |
| max_risk_level = medium | 不得有 high/critical 风险操作 | BLOCKING |
| require_dry_run = true | global_config.dry_run_mode 必须为 true | REQUIRED |

## Gotchas

- `max_risk_level` 是整体阈值，但个别高风险操作如果有完整的回滚方案并标注了 `require_confirmation: true`，Safety Reviewer 可酌情判定为 conditional 通过
- 网段检查需要用 CIDR 匹配，不能简单做字符串比较

## 验收标准

- 输出权限越界发现列表
- 每个发现标注违规级别和建议
- 结论与 SAFETY-REPORT 对齐
