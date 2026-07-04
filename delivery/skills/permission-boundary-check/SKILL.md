---
name: permission-boundary-check
description: >-
  当需要检查工作流计划的操作是否超出权限边界时使用。
  触发词包括：权限检查、权限边界、越权验证、安全边界。
  适用场景：安全审计的输入层和规划层检查。
argument-hint: "process/STATE.md、process/context/*-CONTEXT.yaml、process/DEVELOPMENT-PLAN.yaml、docs/design/HLD.md 或发布上下文路径"
user-invokable: true
status: active
---

## 目标

对比 `process/STATE.md` 的人工决策 / 不授权项、阶段 Context Capsule、`process/DEVELOPMENT-PLAN.yaml`、HLD / LLD / 发布上下文中的实际操作，检测是否存在越权行为。

## 适用范围

- 适用阶段：CP4 / CP5 / CP7 / CP8 的权限边界复核
- 对应审计层：第一层（输入层）+ 第二层（规划层）

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] `process/checkpoints/CP*.md` Decision Brief 与 `process/state/GATE-LEDGER.ndjson` 与不授权项已可读取，或当前阶段明确 N/A
- [ ] `process/context/*-CONTEXT.yaml`、`process/DEVELOPMENT-PLAN.yaml`、HLD / LLD / 发布上下文至少有一个可读取的操作来源

## 执行约束

- 检查人工门禁未授权真实运行、凭据、外部写入、publish 或 live / 交易类操作时，计划是否包含对应动作
- 检查破坏性操作、生产影响、外部系统写入和高风险权限是否已有独立决策项
- 检查需要 dry-run / sandbox / 最小权限的操作是否有验证或降级路径
- 检查命令目标、文件写入范围和发布目标是否在已确认边界内

## 检查规则

| 安全边界字段 | 检查逻辑 | 违规级别 |
|------------|---------|---------|
| 不授权真实运行 / 外部写入 / publish | 计划中不得出现对应动作，除非单独决策已批准 | BLOCKING |
| destructive_operations_allowed = false | 计划中不得有破坏性配置命令 | BLOCKING |
| max_risk_level = medium | 不得有 high / critical 风险操作，除非风险接受项已确认 | BLOCKING |
| require_dry_run = true | 验证或发布上下文必须声明 dry-run / sandbox / N/A 理由 | REQUIRED |

## Gotchas

- `max_risk_level` 是整体阈值，但个别高风险操作如果有完整回滚方案并进入待人工决策清单，可判定为 conditional / pending；不得静默通过
- 网段检查需要用 CIDR 匹配，不能简单做字符串比较

## 验收标准

- 输出权限越界发现列表
- 每个发现标注违规级别和建议
- 结论写入对应 CP 检查摘要或发布就绪风险表
