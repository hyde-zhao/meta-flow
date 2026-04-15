---
name: context-handoff
description: >-
  当阶段切换时需要为下一个 Agent 装配最小必要上下文时使用。
  触发词包括：上下文交接、装配上下文、阶段切换、交接给。
  适用场景：Orchestrator 将控制权移交给下一个功能 Agent。
argument-hint: "目标 Agent 名称"
user-invokable: false
status: draft
---

## 目标

根据目标 Agent 的上下文隔离规则，从当前工作区中筛选出该 Agent 需要加载的最小文件集合，并明确列出不应加载的内容，确保 Agent 在最小上下文下工作。

## 适用范围

- 适用阶段：所有阶段切换时
- 调用者：仅 Meta-Orchestrator 内部使用
- 输出：上下文加载清单

## 前置条件

- [ ] 目标 Agent 已确定
- [ ] `.fw-meta/` 目录下的相关文件就绪

## 执行约束

- 严格遵循上下文隔离表，不多加载也不少加载
- Orchestrator 自身上下文不超过总 token 的 30%
- 不加载其他 Agent 的历史推理过程和中间草稿
- 不加载已归档的历史版本（除非明确需要对比）

## 上下文隔离表

| 目标 Agent | 必须加载 | 明确不加载 |
|-----------|---------|-----------|
| Requirement Analyst | `input_spec.yaml`、项目背景描述 | 其他 Agent 的历史推理过程 |
| Vendor Adapter | `input_spec.yaml`（厂商和设备字段）、`vendor-profiles/` 下对应画像 | 与厂商无关的评审结论 |
| Workflow Planner | `REQUIREMENTS.md`、`SCENARIOS.yaml`、`VENDOR-CONSTRAINTS.yaml` | Requirement Analyst 的中间草稿 |
| Plan Checker | `WORKFLOW-PLAN.yaml`、`SCENARIOS.yaml`、`VENDOR-CONSTRAINTS.yaml` | 设计 Agent 的隐式思考过程 |
| Safety Reviewer | `WORKFLOW-PLAN.yaml`、`input_spec.yaml`（安全边界字段）、厂商安全约束 | 非必要历史版本 |
| Delivery Agent | 已批准的 `WORKFLOW-PLAN.yaml`、`PLAN-CHECK-REPORT.md`、`SAFETY-REPORT.md` | 早期草稿和失败轮次细节 |

## Gotchas

- Vendor Adapter 只需要 input_spec.yaml 中的厂商相关字段（target_vendor, target_platform, target_version），不需要整个 input_spec 的测试目标和约束部分
- 当存在活跃的 CR 时，切换到任何 Agent 都需要额外加载对应的 CR 文件，让 Agent 知道变更上下文
- Plan Checker 和 Safety Reviewer 不应看到 Workflow Planner 的失败修订历史，只看最新版本

## 验收标准

- 输出的文件清单与隔离表一致
- 不包含隔离表中"不加载"列的任何内容
- 当存在活跃 CR/ISSUE 时，相关文件已包含在清单中
