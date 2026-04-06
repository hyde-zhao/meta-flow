---
name: coverage-checker
description: >-
  当需要检查测试场景是否被工作流计划完全覆盖时使用。
  触发词包括：覆盖率检查、场景覆盖、未覆盖场景。
  适用场景：计划质量校验的完整性维度。
argument-hint: "SCENARIOS.yaml 和 WORKFLOW-PLAN.yaml 路径"
user-invokable: true
status: draft
---

## 目标

交叉比对 `SCENARIOS.yaml` 中的场景清单和 `WORKFLOW-PLAN.yaml` 中的任务引用，计算覆盖率并列出未覆盖的场景。

## 适用范围

- 适用阶段：计划校验阶段（plan-check）
- 对应校验维度：维度 1 — 完整性
- 严重级别：BLOCKING（未覆盖场景视为阻断缺陷）

## 前置条件

- [ ] `SCENARIOS.yaml` 已生成
- [ ] `WORKFLOW-PLAN.yaml` 已生成

## 执行约束

- 每个 TC-* 必须被至少一个 task 的 `linked_scenario` 引用
- 覆盖率 = 已覆盖场景数 / 总场景数
- 100% 覆盖时通过，否则为 BLOCKING
- 可调用辅助脚本 `scripts/check_coverage.py` 进行自动检查

## Gotchas

- precheck 类场景（type=precheck）通常由 precheck 阶段的固定任务覆盖，不会有显式的 `linked_scenario`。需要特殊处理或标记为"隐式覆盖"
- 一个 task 可以覆盖多个场景（`linked_scenario` 只支持单值），如果计划模板升级为列表需同步调整检查逻辑

## 验收标准

- 输出覆盖率百分比
- 列出所有未覆盖场景的 TC-ID
- 结论与 PLAN-CHECK-REPORT 的维度 1 对齐
