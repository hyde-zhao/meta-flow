---
name: issue-drafter
description: >-
  当执行反馈中发现问题，需要起草 ISSUE 工单时使用。
  触发词包括：起草问题、创建 ISSUE、问题工单、报告问题。
  适用场景：执行反馈产生问题时。
argument-hint: "RUN-EXEC 记录路径或问题描述"
user-invokable: true
status: active
---

## 目标

从 RUN-EXEC 记录或用户问题描述中提取事实，起草标准化 ISSUE 工单。

## 适用场景

- 执行反馈中暴露了独立问题，需要进入 ISSUE 流转
- 用户描述了可归档的问题现象，需要形成结构化工单

## 前置条件

- [ ] 问题现象已明确（有 RUN-EXEC 记录或用户描述）

## 必须读取的输入

- RUN-EXEC 记录（若存在）
- 用户问题描述
- 与问题直接相关的日志、命令输出或证据

## 知识来源

- `skills/issue-drafter/templates/ISSUE-TEMPLATE.md`
- 运行反馈与证据文件
- 当前交付对象的实际行为

## 执行步骤

1. 提炼现象、影响范围、复现条件与期望结果。
2. 判定 `category` 与 `severity`。
3. 整理证据、初步根因假设与受影响产物。
4. 按模板生成 ISSUE 草稿。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| ISSUE 草稿 | `issues/ISSUE-{id}.md` | `skills/issue-drafter/templates/ISSUE-TEMPLATE.md` |

## 约束

- ISSUE 编号递增，不复用
- `category`、`severity`、`affected_artifacts` 必填
- ISSUE 草稿必须复用当前私有模板

## 验收标准

- [ ] ISSUE frontmatter 完整
- [ ] 分类、严重度与影响对象明确
- [ ] 证据与初步根因分析已填写

## 不适用边界

- 当前请求只是问题分流，不需要新建 ISSUE
- 现象尚不明确，无法形成最小问题单元

## Gotchas

- 一次执行可能暴露多个独立问题，应拆成多个 ISSUE，而不是强行合并
- 证据不足时要写明“待补证据”，不能把猜测包装成事实
