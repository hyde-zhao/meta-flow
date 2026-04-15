---
name: workflow-renderer
description: >-
  当需要将已批准的工作流计划渲染为人类可读的交付文档时使用。
  触发词包括：渲染工作流、生成文档、交付文档、输出工作流。
  适用场景：交付阶段。
argument-hint: "WORKFLOW-PLAN.yaml 路径"
user-invokable: true
status: draft
---

## 目标

将已批准的 `WORKFLOW-PLAN.yaml` 转换为结构化的 Markdown 交付文档，包含 6 个标准模块。

## 适用范围

- 适用阶段：交付阶段（delivery）
- 输入：已批准的 WORKFLOW-PLAN.yaml + 校验结论 + 安全结论
- 输出：`OUTPUT/[workflow-name].md`

## 前置条件

- [ ] WORKFLOW-PLAN.yaml 已通过 Plan Checker 校验
- [ ] WORKFLOW-PLAN.yaml 已通过 Safety Reviewer 审计
- [ ] `VENDOR-CONSTRAINTS.yaml` 可用（风险提示参考）

## 执行约束

- 输出格式遵循 `.fw-meta/templates/OUTPUT-TEMPLATE.md` 的 6 模块结构
- Phase → Wave → Task 按计划顺序展开为表格
- 禁止事项来源：SAFETY-REPORT 中的 BLOCKING 发现 + VENDOR-CONSTRAINTS 中的 forbidden_commands
- 需人工批准的操作根据 task 的 `require_confirmation: true` 标记
- 不遗漏 SAFETY-REPORT 的任何 HIGH 及以上级别发现

## Gotchas

- 渲染时命令中的变量占位符应保留（如 `{interface_name}`），不替换为实际值——实际值由执行时注入
- 回滚策略模块容易被敷衍处理（只写"手动恢复"），应从 task 的 rollback_action 字段提取具体的回滚命令

## 验收标准

- 文档包含全部 6 个模块
- 所有 Phase 和 Task 均已展开
- 风险提示完整覆盖安全审计发现
- 禁止事项清单不为空
