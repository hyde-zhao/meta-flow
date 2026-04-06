---
name: context-manifest-builder
description: >-
  当需要为交付的工作流生成执行上下文清单时使用。
  触发词包括：上下文清单、执行上下文、CONTEXT-MANIFEST。
  适用场景：交付阶段，与 workflow-renderer 同步使用。
argument-hint: "WORKFLOW-PLAN.yaml 路径"
user-invokable: true
status: draft
---

## 目标

基于已批准的计划和审计结论，生成 `CONTEXT-MANIFEST.yaml`，为执行者和诊断者提供设计决策、约束和观测点的完整上下文。

## 适用范围

- 适用阶段：交付阶段（delivery），与 workflow-renderer 同时输出
- 输入：WORKFLOW-PLAN.yaml + PLAN-CHECK-REPORT + SAFETY-REPORT
- 输出：`CONTEXT-MANIFEST.yaml`

## 前置条件

- [ ] WORKFLOW-PLAN.yaml 已批准
- [ ] PLAN-CHECK-REPORT.md 已生成
- [ ] SAFETY-REPORT.md 已生成
- [ ] `.fw-meta/templates/CONTEXT-MANIFEST.yaml` 可用

## 执行约束

- 输出格式遵循 `.fw-meta/templates/CONTEXT-MANIFEST.yaml`
- 必须填写 design_decisions（阶段设计理由、Wave 分组理由、回退策略）
- 必须填写 execution_constraints（需要的工具、权限、网络）
- 必须填写 observability_points（检查点、指标、日志位置）
- version 必须与交付文档版本一致

## Gotchas

- design_decisions 容易被敷衍填写——应从 Planner 的设计过程中提取关键决策，如"为什么先正向后负向"，而不是写"按计划执行"
- observability_points 应包含足够细粒度的检查点，让诊断者在执行失败时能快速定位问题阶段

## 验收标准

- CONTEXT-MANIFEST.yaml 所有顶级字段已填写
- design_decisions 非空且有实际内容
- observability_points 覆盖关键 Phase 的进入和退出
- version 与交付文档一致
