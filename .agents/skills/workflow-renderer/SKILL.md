---
name: workflow-renderer
description: >-
  当需要将已批准的工作流计划渲染为人类可读的交付文档时使用。
  触发词包括：渲染工作流、生成文档、交付文档、输出工作流。
  适用场景：交付阶段。
argument-hint: "DEVELOPMENT-PLAN.yaml 或工作流计划路径"
user-invokable: true
status: active
---

## 目标

将已批准的工作流计划渲染为结构化 Markdown 交付文档，供用户或执行者阅读与执行。

## 适用场景

- 交付阶段需要把结构化计划转换为人类可读文档
- 需要按 Phase / Wave / Task 组织最终交付说明

## 前置条件

- [ ] 计划已确认
- [ ] 与执行相关的风险 / 约束结论可读取

## 必须读取的输入

- 已批准的计划文件（如 `.output/doc/DEVELOPMENT-PLAN.yaml`）
- 相关风险、验证或约束结论
- 需要出现在交付文档中的人工确认点与回滚信息

## 知识来源

- `skills/workflow-renderer/templates/OUTPUT-TEMPLATE.md`
- 当前计划内容与上游约束文档

## 执行步骤

1. 提取工作流概览、Phase / Wave 结构和 Task 明细。
2. 汇总执行约束、风险提示、禁止事项与人工确认点。
3. 按 6 个标准模块渲染为交付文档。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 交付工作流文档 | `OUTPUT/[workflow-name].md` | `skills/workflow-renderer/templates/OUTPUT-TEMPLATE.md` |

## 约束

- 输出必须遵循 `OUTPUT-TEMPLATE.md` 的 6 模块结构
- Phase / Wave / Task 顺序必须与已批准计划一致
- 渲染输出必须复用当前私有模板

## 验收标准

- [ ] 文档包含 6 个标准模块
- [ ] Phase、Wave 与 Task 均已展开
- [ ] 风险提示与回滚信息已纳入

## 不适用边界

- 当前任务只需机器可读计划，不需要渲染为阅读文档
- 计划尚未确认，仍处于设计阶段

## Gotchas

- 渲染时不要擅自替换变量占位符，应保留执行时注入的动态值
- 回滚与人工确认点最容易遗漏，必须与计划中的高风险动作一一对齐
