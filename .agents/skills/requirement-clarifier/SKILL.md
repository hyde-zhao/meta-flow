---
name: requirement-clarifier
description: >-
  当需要澄清需求歧义、生成结构化问题清单、或推进多轮需求确认时使用。
  触发词包括：澄清需求、需求问题、未决问题、需求歧义、需求不清晰。
  适用场景：requirement-clarification 阶段的多轮迭代。
argument-hint: "可选：指定要澄清的需求条目 ID 或关键词"
user-invokable: true
status: active
---

## 目标

识别需求中的歧义、缺口和未决项，生成结构化澄清问题列表，更新 `CLARIFICATION-LOG.md`，并判断是否已具备进入设计阶段的条件。

## 适用场景

- requirement-clarification 阶段的首次分析与多轮迭代
- 用户回答部分问题后，需要重新判断剩余阻塞项

## 前置条件

- [ ] `process/REQUEST.md` 已存在
- [ ] 已有需求草稿、用户补充说明或历史澄清记录之一

## 必须读取的输入

- `process/REQUEST.md`
- `process/REQUIREMENTS.md`（若存在）
- `process/CLARIFICATION-LOG.md`（若存在）
- 用户本轮新增回复

## 知识来源

- 用户输入与已有需求文档：唯一事实来源
- `skills/requirement-clarifier/templates/CLARIFICATION-LOG-TEMPLATE.md`：日志结构基线
- `docs/SKILL-DEVELOPMENT-STANDARD.md`：`BLOCKING / REQUIRED / OPTIONAL` 语义

## 执行步骤

1. 识别目标边界、角色、验收条件、平台约束、优先级和冲突项中的歧义。
2. 将问题按 `BLOCKING / REQUIRED / OPTIONAL` 分级。
3. 生成本轮问题列表并追加到 `CLARIFICATION-LOG.md`。
4. 统计剩余阻塞项，输出 `ready_for_design` 判断。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 澄清日志 | `process/CLARIFICATION-LOG.md` | `skills/requirement-clarifier/templates/CLARIFICATION-LOG-TEMPLATE.md` |

## 约束

- 每轮最多提出 5 个问题，按阻断级别排序
- 只追加澄清记录，不覆盖历史轮次
- `REQUEST.md` 只作为输入内容来源，不作为模板路径依赖

## 验收标准

- [ ] 澄清问题已分级并追加写入日志
- [ ] `ready_for_design` 判断与剩余阻塞项一致
- [ ] 历史记录未被覆盖

## 不适用边界

- 已确认需求完整无歧义，当前任务应转入设计阶段
- 当前任务只要求生成正式需求文档，不要求提问清单

## Gotchas

- 澄清不是“把所有想问的都问一遍”，而是先收敛阻塞设计的问题
- 对 `REQUIRED` 级别项可记录默认假设，但必须显式写出假设内容
