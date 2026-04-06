---
name: issue-drafter
description: >-
  当执行反馈中发现问题，需要起草 ISSUE 工单时使用。
  触发词包括：起草问题、创建 ISSUE、问题工单、报告问题。
  适用场景：执行反馈产生问题时。
argument-hint: "RUN-EXEC 记录路径或问题描述"
user-invokable: true
status: draft
---

## 目标

从 RUN-EXEC 记录或用户描述中提取问题，起草标准化的 ISSUE 工单。

## 适用范围

- 适用阶段：执行反馈的问题处理
- 输入：`runs/RUN-EXEC-*.md`（failed_tasks 部分）或用户直接描述
- 输出：`issues/ISSUE-NNN.md`

## 前置条件

- [ ] 问题现象已明确（有 RUN-EXEC 记录或用户描述）
- [ ] `.fw-meta/templates/ISSUE-TEMPLATE.md` 可用

## 执行约束

- ISSUE 编号格式：`ISSUE-NNN`，递增不复用
- 必须填写 category（design-flaw / impl-bug / env-issue / doc-defect）
- 必须填写 severity（BLOCKING / HIGH / MEDIUM / LOW）
- affected_artifacts 字段必须指向受影响的具体文件
- 初步根因分析至少提供假设和支撑证据

## 分类判定指南

| 现象 | 建议 category |
|------|-------------|
| 需求遗漏或理解错误 | design-flaw |
| 命令语法错误或参数错误 | impl-bug |
| 设备不可达或版本不兼容 | env-issue |
| 文档表述不清或证据不足 | doc-defect |

## Gotchas

- 一次执行可能产生多个独立问题，应为每个独立原因创建单独的 ISSUE，不要合并不同原因的问题到一个工单
- ISSUE 创建后不直接路由——提交给 Orchestrator 通过 issue-routing skill 做分类路由

## 验收标准

- ISSUE 文件 frontmatter 全部字段完整
- category 和 severity 判定合理
- affected_artifacts 不为空
- 初步根因分析包含假设和证据
