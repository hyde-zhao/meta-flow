---
name: issue-routing
description: >-
  当需要对 ISSUE 问题工单进行分类、定级和路由到正确 Agent 时使用。
  触发词包括：路由问题、分配问题、ISSUE 路由、问题分流。
  适用场景：执行反馈产生 ISSUE 后的分流决策。
argument-hint: "ISSUE 工单 ID 或问题描述"
user-invokable: true
status: draft
---

## 目标

读取 ISSUE 工单，根据问题分类（category）将其路由到正确的责任 Agent，必要时判断是否需要升级为结构性变更（CR）。

## 适用范围

- 适用阶段：交付后的问题处理阶段
- 输入：`issues/ISSUE-*.md`
- 输出：路由决策（目标 Agent + 处理建议）、必要时生成 `changes/CR-*.md`

## 前置条件

- [ ] `issues/ISSUE-*.md` 已存在且 `category` 和 `severity` 字段已填写
- [ ] `STATE.md` 可用

## 执行约束

- 只做分类和路由，不做修复
- 路由前必须确认 ISSUE 的 `status` 为 `open` 或 `triaged`
- 如果问题属于 `env-issue`，必须升级为人工接管而非路由给 Agent
- 如果判定为结构性问题（需要修改需求或安全边界），必须同时生成 CR

## 路由规则

| 问题分类 (category) | 路由目标 | 典型场景 |
|---------------------|---------|---------|
| `design-flaw` | Requirement Analyst 或 Workflow Planner | 需求、场景或计划设计有误 |
| `impl-bug` | Workflow Planner | 任务编排、命令、变量映射有误 |
| `doc-defect` | Delivery Agent | 文档表达不清、证据不足 |
| `env-issue` | 人工接管 | 环境不满足、设备版本不兼容 |

## 升级为 CR 的判定标准

| 条件 | 动作 |
|------|------|
| ISSUE 影响到 REQ-* 定义 | 生成 CR（type=modify） |
| ISSUE 需要修改安全边界 | 生成 CR（type=modify）+ 标记 high risk |
| ISSUE 影响到多个 artifact | 生成 CR + 全局影响分析 |
| ISSUE 仅影响单个任务的参数 | 不生成 CR，直接路由修复 |

## Gotchas

- `env-issue` 类问题不能路由给任何 Agent 自动修复，因为通常涉及物理设备、网络配置或权限变更，必须人工介入
- 路由前要检查是否存在相同 `symptom` 的已有 ISSUE，避免重复工单。如果存在，应关联而非新建

## 验收标准

- ISSUE 的 `status` 更新为 `triaged`
- ISSUE 的 `owner` 字段填写了路由目标
- 如果升级为 CR，`linked_changes` 字段已回填
- 路由决策包含目标 Agent 名称和处理建议
