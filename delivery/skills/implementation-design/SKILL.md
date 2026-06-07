---
name: implementation-design
description: >-
  当 CP3 已确认，需要先判定 Feature / Epic 是否需要实现设计，并按 FEATURE-DESIGN-MATRIX
  输出必要的 DESIGN、TEST-PLAN、TASKS 与 Story 下游消费契约时使用。触发词包括：Feature 设计、
  实现设计、技术设计、FEATURE-DESIGN-MATRIX、TEST-PLAN、TASKS。
  适用场景：CP3 后、CP4 前，为 Story LLD 分级和开发计划提供输入。
argument-hint: "Feature ID、BLUEPRINT.md、HLD.md、ARCHITECTURE-DECISION.md 和相关 Story"
user-invokable: true
status: active
---

## 目标

先输出 `docs/design/FEATURE-DESIGN-MATRIX.md`，判定哪些 Feature / Epic 需要独立实现设计；对命中触发条件的 Feature 输出可实现但不过度细碎的 `docs/features/<feature>/DESIGN.md`、`TEST-PLAN.md` 和 `TASKS.md`，并为每个 Story 写清 `feature_design_refs` 与 `lld_policy`。

## 适用场景

- CP3 已确认 HLD 与核心 ADR，需要在 Story 拆解前判断哪些 Feature 必须设计、哪些可以豁免。
- Feature 涉及数据模型、权限、安全、跨模块调用、外部系统、并发、性能或迁移。
- 多个 Story 共用同一 Feature 边界，需要在 Story LLD 前先冻结接口与数据归属。
- 简单 Story 不需要完整 LLD，但仍需要 Feature 级实现计划或 Story 内 `## 技术说明`。

## 前置条件

- [ ] `docs/design/BLUEPRINT.md` 已生成或 HLD 中已明确 Feature / Epic 边界。
- [ ] `docs/design/HLD.md` 与 `docs/design/ARCHITECTURE-DECISION.md` 已通过 CP3，或 CP3 文件写明 ADR N/A / waived 原因。
- [ ] 相关 Story、MVP 范围和非目标可读取。
- [ ] 涉及平台路径时，`delivery/doc/PLATFORM-CONTRACTS.yaml` 可读取。

## 必须读取的输入

- `docs/design/BLUEPRINT.md`（若存在）
- `docs/design/HLD.md`（若存在）
- `docs/design/ARCHITECTURE-DECISION.md`（若存在）
- `docs/design/FEATURE-DESIGN-MATRIX.md`（若已存在，增量更新；若不存在，先创建）
- `docs/product/STORY-MAP.md`
- `docs/product/MVP-SCOPE.md`
- 相关 Story 卡片或 Story 列表
- 目标代码库结构摘要

## 知识来源

- `skills/implementation-design/templates/FEATURE-DESIGN-MATRIX-TEMPLATE.md`
- `skills/implementation-design/templates/FEATURE-DESIGN-TEMPLATE.md`
- `skills/implementation-design/templates/TEST-PLAN-TEMPLATE.md`
- `skills/implementation-design/templates/TASKS-TEMPLATE.md`

## 执行步骤

1. 基于 HLD、ADR、蓝图、Story Map 和 MVP 范围建立 `FEATURE-DESIGN-MATRIX.md`，逐个 Feature 判定 `required` / `waived` / `n/a`。
2. 对每个 `required` Feature 写明触发原因、关联 Story、需要冻结的接口 / 数据 / 权限 / 失败路径，以及下游 Story 的 `lld_policy` 建议。
3. 仅对 `required` Feature 生成 `docs/features/<feature>/DESIGN.md`、`TEST-PLAN.md`、`TASKS.md`；对 `waived` 必须写明豁免理由、风险、重访条件和影响 Story。
4. 读取现有代码位置，列出模块变更、接口、数据、权限、错误处理和兼容性；关键决策若需要提前确认，写入人工决策项，包含推荐方案、备选方案、优劣分析、影响 / 风险和回退 / 切换条件。
5. 为测试代理输出测试计划，覆盖测试层级、风险、手工验收和未自动化原因。
6. 将实现拆成 TASK-ID，确保每个任务有输入、输出、文件范围和验证入口。
7. 回写 Story 卡片或交还给 `story-manager`：每个 Story 必须有 `feature_design_refs` 与 `lld_policy.required_level=full-lld|technical-note|waived`。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| Feature 设计矩阵 | `docs/design/FEATURE-DESIGN-MATRIX.md` | `skills/implementation-design/templates/FEATURE-DESIGN-MATRIX-TEMPLATE.md` |
| Feature 技术设计 | `docs/features/<feature>/DESIGN.md` | `skills/implementation-design/templates/FEATURE-DESIGN-TEMPLATE.md` |
| Feature 测试计划 | `docs/features/<feature>/TEST-PLAN.md` | `skills/implementation-design/templates/TEST-PLAN-TEMPLATE.md` |
| Feature 任务清单 | `docs/features/<feature>/TASKS.md` | `skills/implementation-design/templates/TASKS-TEMPLATE.md` |

## 约束

- 不重新定义全局 Feature 边界；如发现边界错误，回到 `blueprint-design` 或 CR。
- 不私自扩展 MVP 范围；新能力必须进入 Backlog 或人工决策项。
- 不把实现日志写成设计；设计必须能在编码前审查。
- 对不可逆迁移、权限、安全和外部接口必须显式列出失败路径和回退策略。
- 不为所有 Story 默认生成完整 LLD；必须按 `lld_policy` 分级，减少不必要的设计 token 消耗。
- `technical-note` 只适用于低风险 Story，必须写入 Story 卡片 `## 技术说明`，不能隐藏关键接口、数据、安全或运行授权风险。

## 验收标准

- [ ] 每个设计项能回链到 Feature、Story 或场景。
- [ ] `FEATURE-DESIGN-MATRIX.md` 覆盖所有 Feature / Epic，并说明 required / waived / n/a 的理由。
- [ ] 接口、错误路径和权限规则有对应测试计划。
- [ ] TASK-ID 覆盖实现顺序、文件范围和验证入口。
- [ ] 每个 Story 均有 `feature_design_refs` 与 `lld_policy`，高风险 Story 的 `full-lld` 触发条件已明确。
- [ ] 需要提前人工确认的关键决策已进入待人工决策清单，并包含推荐、备选、优劣、影响 / 风险和回退 / 切换条件。

## 不适用边界

- 还没有 Feature / Epic 边界。
- 只有单行文档或配置改动，不需要 Feature 级设计。
- 当前已经进入实现阶段，且设计已获批。

## Gotchas

- Feature `DESIGN.md` 不是 Story LLD 的替代品；高风险 Story 仍要 `full-lld`。
- `FEATURE-DESIGN-MATRIX.md` 是 CP4 的门禁输入，不是讨论日志；不要只在对话里说明哪个 Feature 需要设计。
- 低风险 Story 的 `technical-note` 必须能被 CP5 审查，不能只写“无需 LLD”。
- 写任务清单时最容易漏掉验证入口，导致 CP6 / CP7 只能证明“改了文件”。
- 权限、安全和迁移不能只写在风险表里，必须落到接口、流程和测试计划。
