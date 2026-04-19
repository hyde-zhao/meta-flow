---
name: context-manifest-builder
description: >-
  当需要为交付的工作流生成执行上下文清单时使用。
  触发词包括：上下文清单、执行上下文、CONTEXT-MANIFEST。
  适用场景：交付阶段，与 workflow-renderer 同步使用。
argument-hint: "DEVELOPMENT-PLAN.yaml 或交付计划路径"
user-invokable: true
status: active
---

## 目标

基于已批准的计划、设计与验证结论，生成 `CONTEXT-MANIFEST.yaml`，为执行者和诊断者提供完整但最小化的上下文清单。

## 适用场景

- 文档交付阶段，需要为后续执行 / 诊断准备上下文清单
- 需要把关键设计决策、执行约束和观测点结构化沉淀

## 前置条件

- [ ] 计划与关键设计对象已确认
- [ ] 验证或审计结论已可读取

## 必须读取的输入

- `.output/doc/DEVELOPMENT-PLAN.yaml`
- `.output/doc/HLD.md`
- `.output/doc/ARCHITECTURE-DECISION.md`
- `.output/doc/VERIFICATION-REPORT.md`（若存在）
- 相关安全 / 约束结论（若存在）

## 知识来源

- `skills/context-manifest-builder/templates/CONTEXT-MANIFEST-TEMPLATE.yaml`
- 已批准的计划、设计与验证文档
- 当前交付边界与目标平台约束

## 执行步骤

1. 提炼关键设计决策及其理由。
2. 汇总执行所需工具、权限、网络与环境限制。
3. 归纳主要观测点、检查信号和定位入口。
4. 将结果写入 `CONTEXT-MANIFEST.yaml`。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 上下文清单 | `.output/doc/CONTEXT-MANIFEST.yaml` | `skills/context-manifest-builder/templates/CONTEXT-MANIFEST-TEMPLATE.yaml` |

## 约束

- 输出必须遵循 `CONTEXT-MANIFEST-TEMPLATE.yaml`
- `design_decisions`、`execution_constraints`、`observability_points` 不可留空
- 若输入文档中无事实依据，不得补写虚构约束

## 验收标准

- [ ] 顶级字段完整
- [ ] 设计决策、执行约束与观测点均有实际内容
- [ ] 关联产物指向当前交付对象

## 不适用边界

- 当前任务只要求渲染用户文档，不需要执行上下文清单
- 计划 / 设计对象尚未确认，无法抽取稳定上下文

## Gotchas

- 观测点不是“文档目录清单”，而是用于执行诊断的检查入口
- 上下文清单需要足够精简，避免把所有上游文档全文重新复制进去
