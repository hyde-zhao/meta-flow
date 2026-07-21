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


## vNext 过程引用契约

- `process/...` 是过程仓逻辑引用，不是发布仓中的相对物理路径。
- 首次文件系统 I/O 前必须调用 `meta-flow project resolve-ref --project-root <release-root> --logical-ref <process/...> --format json`。
- 只可瞬时使用成功 JSON 中的 `resolved_path`；不得把绝对路径写入治理文件、Prompt 产物或 Git。
- 命令以退出码 2 返回 BLOCKED 时必须停止；不得自行拼 sibling、去掉 `process/`、恢复软链接或回退 legacy。
- legacy-only 操作必须交还 Host Orchestrator，并使用独立 typed authorization；本 Skill 不构造 legacy capability。

## 目标

解析 `process/DEVELOPMENT-PLAN.yaml` 中的 Story / Task 依赖关系，检测循环依赖、无效引用和需要解释的孤立节点。

## 适用范围

- 适用阶段：CP4 Story / DAG / 并行安全预检
- 对应校验维度：维度 2 — 依赖正确性
- 严重级别：BLOCKING（循环依赖和无效引用为阻断缺陷）

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
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
