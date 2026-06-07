---
name: dag-validator
description: >-
  当需要校验工作流计划的任务依赖图（DAG）是否无环、无无效引用时使用。
  触发词包括：DAG 校验、依赖校验、循环依赖检查。
  适用场景：计划质量校验的依赖正确性维度。
argument-hint: "process/DEVELOPMENT-PLAN.yaml 路径"
user-invokable: true
status: active
---

## 目标

解析 `process/DEVELOPMENT-PLAN.yaml` 中的 Story / Task 依赖关系，检测循环依赖、无效引用和需要解释的孤立节点。

## 适用范围

- 适用阶段：CP4 Story / DAG / 并行安全预检
- 对应校验维度：维度 2 — 依赖正确性
- 严重级别：BLOCKING（循环依赖和无效引用为阻断缺陷）

## 前置条件

- [ ] `process/DEVELOPMENT-PLAN.yaml` 已生成且包含 stories / tasks 和 depends_on

## 执行约束

- 使用深度优先搜索（DFS）检测环路
- 所有 `depends_on` 中引用的 task ID 必须存在
- 同一 parallel Wave 内的任务不应互相依赖
- 若仓库提供 DAG 校验脚本，可调用脚本辅助；不存在脚本时按 YAML 结构做拓扑校验

## Gotchas

- 孤立任务不是 BLOCKING 级——它可能是有意独立的（如 cleanup 任务）。但应标记并建议确认
- 跨 Phase 的依赖是隐式的（Phase order 保证），不要误判为孤立

## 验收标准

- 输出环路列表（为空则通过）
- 输出无效引用列表
- 输出孤立任务列表
- 结论写入 CP4 自动预检摘要
