---
name: story-manager
description: >-
  当需要拆分 Story、管理 Story 生命周期、生成 Story 卡片或更新 Story 状态时使用。
  触发词包括：拆分 Story、Story 状态、Story 卡片、Story 管理、生成 Story。
  适用场景：story-planning 和 story-execution 阶段。
argument-hint: "可选：指定 Story ID、Story 名称或操作类型（create/update/status）"
user-invokable: true
status: active
---

## 目标

管理 Story 的完整生命周期：生成 Story 卡片、维护状态流转、回写 `feature_design_refs` / `lld_policy` / `implementation_gate` / `verification_gate`，并汇总输出 `STORY-STATUS.md`。

## 适用场景

- `story-planning` 阶段生成 Story 卡片
- `story-execution` 阶段更新 Story 状态与汇总视图

## 前置条件

- [ ] `ARCHITECTURE-DECISION.md` 或 `DEVELOPMENT-PLAN.yaml` 已存在
- [ ] `docs/design/FEATURE-DESIGN-MATRIX.md` 已存在，或当前操作只是在 CP3 前创建初始 Story 草稿
- [ ] Story 边界和 Wave 规划可读取

## 必须读取的输入

- `docs/design/ARCHITECTURE-DECISION.md`
- `docs/design/FEATURE-DESIGN-MATRIX.md`
- `process/DEVELOPMENT-PLAN.yaml`
- 现有 `process/stories/STORY-*.md`（update / status 时）

## 知识来源

- `skills/story-manager/templates/STORY-TEMPLATE.md`
- `skills/story-manager/templates/STORY-STATUS-TEMPLATE.md`
- 当前 Story 生命周期规则与状态门控

## 执行步骤

1. 生成或读取 Story 卡片，并基于 Story 标题生成或复用 `story_slug`。
2. 按生命周期规则校验状态转换是否合法。
3. 在卡片中维护开发上下文、验证上下文与量化验收标准三件套。
4. 根据 `FEATURE-DESIGN-MATRIX.md` 和 Feature DESIGN 回写 `feature_design_refs` 与 `lld_policy.required_level=full-lld|technical-note|waived`。
5. 对 `technical-note` 或 `waived` Story，维护 Story 内 `## 技术说明` 或豁免证据，供 CP5 审查。
6. 对进入实现阶段的 Story，维护 `implementation_gate` 与 `## 实现执行上下文`，记录 implementation evidence 路径、实现对象清单、测试计划引用和局部验证结果。
7. 对进入验证阶段的 Story，维护 `verification_gate` 与 `## 验证上下文`，记录 validation_mode、VERIFICATION / TEST-REPORT / REVIEW 路径、CP7 结论、剩余风险和路由。
8. 回写 `STORY-STATUS.md` 汇总视图。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| Story 卡片 | `process/stories/STORY-{id}-{story_slug}.md` | `skills/story-manager/templates/STORY-TEMPLATE.md` |
| Story 状态汇总 | `process/STORY-STATUS.md` | `skills/story-manager/templates/STORY-STATUS-TEMPLATE.md` |

## 约束

- Story 状态只能按既定生命周期推进，不允许跳级
- 缺少三件套的 Story 不得进入 LLD 审核
- 缺少 `feature_design_refs` 或 `lld_policy` 的 Story 不得通过 CP4
- `technical-note` / `waived` 只能用于低风险 Story；命中数据、安全、外部接口、并发、迁移或跨 Story 契约时必须升级 `full-lld`
- 进入 CP6 前，`implementation_gate.status` 必须为 `ready-for-cp6` 或写明 N/A 原因
- 进入 verified / verified-with-risk 前，`verification_gate.cp7_result` 必须为合法结论；`PASS_WITH_RISK` 必须记录剩余风险和 CP8 输入，`NEEDS_REWORK` / `NEEDS_DESIGN_CLARIFICATION` 必须记录路由
- `STORY-STATUS.md` 必须与卡片状态保持一致
- `story_slug` 必须由 Story 标题生成 kebab-case 稳定片段；已有卡片时必须复用原值，不得静默改名

## 验收标准

- [ ] Story 生命周期包含 LLD 审核门控
- [ ] 每张 Story 卡片包含完整三件套
- [ ] 每张 Story 卡片包含 `feature_design_refs` 和 `lld_policy`
- [ ] `technical-note` / `waived` Story 含可被 CP5 审查的设计证据
- [ ] 实现阶段 Story 包含 `implementation_gate` 和实现执行上下文
- [ ] 验证阶段 Story 包含 `verification_gate` 和验证上下文
- [ ] 汇总视图与卡片状态一致
- [ ] Story 卡片文件名同时包含 Story 编号与名称 slug

## 不适用边界

- 当前任务是输出 HLD 或 LLD，而不是管理 Story 生命周期
- Story 尚未形成正式边界

## Gotchas

- `verified` 是验证完成，不等于最终归档；`verified-with-risk` 可继续推进但必须保留风险接受输入；只有收敛后才进入 `done`
- 批量更新状态时最容易漏掉 `STORY-STATUS.md`，必须同步回写
- `story_slug` 来自标题但一旦落盘即成为稳定标识；标题文案微调不能自动触发文件重命名
- 不要把 `lld_policy=technical-note` 当作“无需设计”；它仍需要 Story 卡片中的正式技术说明，并纳入 CP5 批量确认
- 不要把 `DEV-LOG.md` 当作默认万能交接；复杂 / 高风险 / Prompt-Skill / Guardrail / 安装器 / 平台适配 Story 仍必须有完整 IMPLEMENTATION
