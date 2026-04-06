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

分析 `REQUIREMENTS.md` 或用户原始输入中的歧义项和未决问题，生成结构化澄清问题列表，更新 `CLARIFICATION-LOG.md`，并判断需求是否已足够清晰可进入下一阶段。

## 适用范围

- 适用阶段：`requirement-clarification`
- 触发时机：每轮用户回答澄清问题后，或首次分析用户需求时
- 输出消费方：meta-po（判断是否可进入 solution-design）

## 前置条件

- [ ] `.workflow-meta/REQUEST.md` 已存在（用户原始目标）
- [ ] `.workflow-meta/CLARIFICATION-LOG.md` 已存在（首次可从模板初始化）

## 歧义识别维度

| 维度 | 检查内容 | 示例歧义 |
|------|---------|---------|
| 目标边界 | 需求范围是否明确 | "支持多个平台"——哪几个平台？ |
| 角色定义 | 是否有未定义的角色 | "用 AI 帮我做"——哪个 AI，什么能力？ |
| 验收条件 | 是否有量化的完成标准 | "好用"——如何验证好用？ |
| 平台约束 | 目标平台是否明确 | 未声明目标平台 |
| 优先级 | 多需求时是否有优先级 | 5 条需求，无优先级说明 |
| 冲突项 | 需求之间是否有矛盾 | 需求 A 要自动，需求 B 要人工确认 |

## 执行步骤

1. 读取 `REQUEST.md` 和已有 `CLARIFICATION-LOG.md`
2. 识别歧义项，按维度分类
3. 生成结构化问题列表（每条问题需包含：问题描述、所属维度、阻断等级）
4. 更新 `CLARIFICATION-LOG.md`（追加本轮问题，不覆盖历史记录）
5. 判断未决问题数量：
   - 0 个 BLOCKING 未决项 → 输出 `ready_for_design: true`
   - 存在 BLOCKING 未决项 → 输出待用户回答的问题列表

## 问题阻断等级

| 等级 | 说明 | 是否阻断推进 |
|------|------|------------|
| BLOCKING | 缺少此信息无法设计 | 是 |
| REQUIRED | 建议澄清，但有默认值可用 | 否（记录默认假设）|
| OPTIONAL | 锦上添花，可跳过 | 否 |

## 输出格式（CLARIFICATION-LOG.md 追加内容）

```markdown
## 第 N 轮澄清（{date}）

### 本轮识别的歧义项

| ID | 维度 | 问题描述 | 阻断等级 | 状态 |
|----|------|---------|---------|------|
| Q1 | 目标边界 | ... | BLOCKING | 待回答 |

### 用户回答记录

| Q-ID | 答复内容 | 记录时间 |
|------|---------|---------|
| Q1 | ... | {date} |

### 本轮结论

- 剩余 BLOCKING 未决项：N 条
- ready_for_design：true / false
```

## 执行约束

- 不允许在未决 BLOCKING 项存在时标记 `ready_for_design: true`
- 历史澄清记录只追加，不修改
- 每轮至多提出 5 个问题（避免用户疲劳），按阻断等级优先排序

## 验收标准

- [ ] `CLARIFICATION-LOG.md` 已追加本轮记录
- [ ] 每条问题标注了阻断等级
- [ ] 当 BLOCKING 项为 0 时，`ready_for_design` 正确标记为 `true`
