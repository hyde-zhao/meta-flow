---
name: story-manager
description: >-
  当需要拆分 Story、管理 Story 生命周期、生成 Story 卡片或更新 Story 状态时使用。
  触发词包括：拆分 Story、Story 状态、Story 卡片、Story 管理、生成 Story。
  适用场景：story-planning 和 story-execution 阶段。
argument-hint: "可选：指定 Story ID 或操作类型（create/update/status）"
user-invokable: true
status: active
---

## 目标

管理 Story 的完整生命周期：生成 Story 卡片、维护状态流转，并汇总输出 `STORY-STATUS.md`。

## 适用场景

- `story-planning` 阶段生成 Story 卡片
- `story-execution` 阶段更新 Story 状态与汇总视图

## 前置条件

- [ ] `ARCHITECTURE-DECISION.md` 或 `DEVELOPMENT-PLAN.yaml` 已存在
- [ ] Story 边界和 Wave 规划可读取

## 必须读取的输入

- `.meta-workflow/process/ARCHITECTURE-DECISION.md`
- `.meta-workflow/process/DEVELOPMENT-PLAN.yaml`
- 现有 `.meta-workflow/process/stories/STORY-*.md`（update / status 时）

## 知识来源

- `skills/story-manager/templates/STORY-TEMPLATE.md`
- `skills/story-manager/templates/STORY-STATUS-TEMPLATE.md`
- 当前 Story 生命周期规则与状态门控

## 执行步骤

1. 生成或读取 Story 卡片。
2. 按生命周期规则校验状态转换是否合法。
3. 在卡片中维护开发上下文、验证上下文与量化验收标准三件套。
4. 回写 `STORY-STATUS.md` 汇总视图。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| Story 卡片 | `.meta-workflow/process/stories/STORY-{id}.md` | `skills/story-manager/templates/STORY-TEMPLATE.md` |
| Story 状态汇总 | `.meta-workflow/process/STORY-STATUS.md` | `skills/story-manager/templates/STORY-STATUS-TEMPLATE.md` |

## 约束

- Story 状态只能按既定生命周期推进，不允许跳级
- 缺少三件套的 Story 不得进入 LLD 审核
- `STORY-STATUS.md` 必须与卡片状态保持一致

## 验收标准

- [ ] Story 生命周期包含 LLD 审核门控
- [ ] 每张 Story 卡片包含完整三件套
- [ ] 汇总视图与卡片状态一致

## 不适用边界

- 当前任务是输出 HLD 或 LLD，而不是管理 Story 生命周期
- Story 尚未形成正式边界

## Gotchas

- `verified` 是验证完成，不等于最终归档；只有收敛后才进入 `done`
- 批量更新状态时最容易漏掉 `STORY-STATUS.md`，必须同步回写

