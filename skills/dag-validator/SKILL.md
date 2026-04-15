---
name: dag-validator
description: >-
  当需要校验工作流计划的任务依赖图（DAG）是否无环、无无效引用时使用。
  触发词包括：DAG 校验、依赖校验、循环依赖检查。
  适用场景：计划质量校验的依赖正确性维度。
argument-hint: "WORKFLOW-PLAN.yaml 路径"
user-invokable: true
status: draft
---

## 目标

解析 `WORKFLOW-PLAN.yaml` 中的任务依赖关系，检测循环依赖、无效引用和孤立任务。

## 适用范围

- 适用阶段：计划校验阶段（plan-check）
- 对应校验维度：维度 2 — 依赖正确性
- 严重级别：BLOCKING（循环依赖和无效引用为阻断缺陷）

## 前置条件

- [ ] `WORKFLOW-PLAN.yaml` 已生成且包含 tasks 和 depends_on

## 执行约束

- 使用深度优先搜索（DFS）检测环路
- 所有 `depends_on` 中引用的 task ID 必须存在
- 同一 parallel Wave 内的任务不应互相依赖
- 可调用辅助脚本 `scripts/validate_dag.py` 进行自动检查

## Gotchas

- 孤立任务不是 BLOCKING 级——它可能是有意独立的（如 cleanup 任务）。但应标记并建议确认
- 跨 Phase 的依赖是隐式的（Phase order 保证），不要误判为孤立

## 验收标准

- 输出环路列表（为空则通过）
- 输出无效引用列表
- 输出孤立任务列表
- 结论与 PLAN-CHECK-REPORT 的维度 2 对齐
