---
name: solution-designer
description: >-
  历史兼容入口，已废弃并重定向到 hld-designer，用于兼容“方案设计、架构设计、
  复杂度判定、设计方案、simple/standard/complex 判断”等旧触发词。
argument-hint: "请改用 hld-designer；可附带目标平台或约束条件"
user-invokable: true
status: deprecated
---

## 状态

本 Skill 已废弃，保留文件仅用于兼容历史触发词和旧文档入口。

## 重定向

1. 正式能力统一收敛到 `hld-designer`。
2. 正式输出仍为 `.meta-workflow/process/HLD.md`。
3. 模板、输入、约束、验收标准全部以 `hld-designer` 为准。

## 兼容规则

1. 新增规则、文档和实现不得再把 `solution-designer` 作为 canonical Skill。
2. 不再维护独立模板或第二套 HLD 章节口径。
3. 用户若使用历史触发词，应解释为调用 `hld-designer`。

## 不适用边界

- 任何新的 HLD 设计、规则编写或文档引用场景。

## Gotchas

- 若发现 `solution-designer` 与 `hld-designer` 重新分叉，优先收敛到 `hld-designer`，不要恢复双轨维护。

