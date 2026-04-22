---
name: lld-designer
description: >-
  当某个已批准 Story 在开发前需要落地为 Low-Level Design（LLD）时使用。
  输出模块拆分、文件影响范围、数据模型、接口、流程、异常处理、测试设计、实施步骤、
  风险、发布与回滚策略，并交由人工确认后再进入实现。触发词包括：LLD、详细设计、实现设计、Story 设计。
argument-hint: "必填：Story ID；可选：功能名、目标平台或技术栈"
user-invokable: true
status: active
---

## 目标

基于已批准的 Story、已确认的 HLD 和架构约束，输出一份可直接指导编码与评审的 Story 级 LLD。

## 适用场景

- Story 已批准，准备进入实现前的详细设计
- 需要形成可评审的 Story 级实现蓝图

## 前置条件

- [ ] `process/stories/STORY-{id}.md` 已批准
- [ ] `process/HLD.md` 与 `process/ARCHITECTURE-DECISION.md` 已确认

## 必须读取的输入

- `process/stories/STORY-{id}.md`
- `process/HLD.md`
- `process/ARCHITECTURE-DECISION.md`
- 相关前置 Story 或平台约束（若存在）

## 知识来源

- `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md`
- Story 卡片中的验收标准与设计约束
- 上游 HLD / ADR 约束

## 执行步骤

1. 提炼 Story 范围、输出文件、平台目标和约束。
2. 按 14 个规定章节完成 LLD 设计。
3. 写入 `process/stories/STORY-{id}-LLD.md` 并停在人工确认前。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| Story LLD | `process/stories/STORY-{id}-LLD.md` | `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` |

## 约束

- 14 个章节必须与 `skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` 一一对应
- `confirmed=false` 时不得进入实现
- 不超出当前 Story 范围

## 验收标准

- [ ] LLD 覆盖 14 个规定章节
- [ ] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [ ] 回滚与发布策略明确

## 不适用边界

- 当前任务还处于需求或 HLD 设计阶段
- Story 尚未批准

## Gotchas

- 若模板章节与说明口径不一致，应以模板契约为准同步修正，不允许双轨并存
- 详细设计不是实现日志，必须保持“可实施”而不是“已完成”
