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


## vNext 过程引用契约

- `process/...` 是过程仓逻辑引用，不是发布仓中的相对物理路径。
- 首次文件系统 I/O 前必须调用 `meta-flow project resolve-ref --project-root <release-root> --logical-ref <process/...> --format json`。
- 只可瞬时使用成功 JSON 中的 `resolved_path`；不得把绝对路径写入治理文件、Prompt 产物或 Git。
- 命令以退出码 2 返回 BLOCKED 时必须停止；不得自行拼 sibling、去掉 `process/`、恢复软链接或回退 legacy。
- legacy-only 操作必须交还 Host Orchestrator，并使用独立 typed authorization；本 Skill 不构造 legacy capability。

## 目标

管理 Story 的完整生命周期：以 `process/DEVELOPMENT-PLAN.yaml` 作为 Story 管理机器真相源，生成 Story 卡片、维护状态流转、回写 `feature_design_refs` / `lld_policy` / `implementation_gate` / `verification_gate`，并按需派生 `STORY-STATUS.md` / `STORY-BACKLOG.md` 等 legacy 兼容视图。

## 适用场景

- `story-planning` 阶段生成 `DEVELOPMENT-PLAN.yaml` 与 Story 卡片
- `story-execution` 阶段更新 `DEVELOPMENT-PLAN.yaml` 中的 Story 状态，并按需刷新 legacy 汇总视图

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] `ARCHITECTURE-DECISION.md` 或 `DEVELOPMENT-PLAN.yaml` 已存在
- [ ] `docs/design/FEATURE-DESIGN-MATRIX.md` 已存在，或当前操作只是在 CP3 前创建初始 Story 草稿
- [ ] Story 边界和 Wave 规划可读取

## 必须读取的输入

- `docs/design/ARCHITECTURE-DECISION.md`
- `docs/design/FEATURE-DESIGN-MATRIX.md`
- `process/DEVELOPMENT-PLAN.yaml`（Story 管理机器真相源）
- 现有 `process/stories/STORY-*.md`（update / status 时）

## 知识来源

- `skills/story-manager/templates/STORY-TEMPLATE.md`
- `skills/story-manager/templates/STORY-STATUS-TEMPLATE.md`（legacy / generated view）
- 当前 Story 生命周期规则与状态门控
- `meta-flow story plan-check`：校验 `DEVELOPMENT-PLAN.yaml` 与 legacy 视图是否漂移

## 执行步骤

1. 生成或读取 Story 卡片，并基于 Story 标题生成或复用 `story_slug`。
2. 按生命周期规则校验状态转换是否合法。
3. 在卡片中维护开发上下文、验证上下文与量化验收标准三件套。
4. 根据 `FEATURE-DESIGN-MATRIX.md` 和 Feature DESIGN 回写 `feature_design_refs` 与 `lld_policy.required_level=full-lld|technical-note|waived`；若 `standard-lite` / `allows_batch_lld=true` 使用 Batch LLD，保持 `required_level` 的风险分级语义，并将 `lld_gate.design_evidence_type=batch-lld` 与锚点证据路径写入 Story。
5. 对 `technical-note` 或 `waived` Story，维护 Story 内 `## 技术说明` 或豁免证据，供 CP5 审查。
6. 对进入实现阶段的 Story，维护 `implementation_gate` 与 `## 实现执行上下文`，记录 implementation evidence 路径、实现对象清单、测试计划引用和局部验证结果。
7. 对进入验证阶段的 Story，维护 `verification_gate` 与 `## 验证上下文`，记录 validation_mode、VERIFICATION / TEST-REPORT / REVIEW 路径、CP7 结论、剩余风险和路由。
8. 回写 `DEVELOPMENT-PLAN.yaml` 的 Story 状态、Wave、任务、门禁与文件所有权字段。
9. 若需要人类汇总视图，基于 `DEVELOPMENT-PLAN.yaml` 派生 `STORY-STATUS.md` / `STORY-BACKLOG.md`，不得独立维护不同状态。
10. 运行或要求运行 `meta-flow story plan-check --project-root .`，确认 legacy 视图未与计划冲突。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| Story 卡片 | `process/stories/STORY-{id}-{story_slug}.md` | `skills/story-manager/templates/STORY-TEMPLATE.md` |
| Story 管理真相源 | `process/DEVELOPMENT-PLAN.yaml` | `story_management_truth_source: process/DEVELOPMENT-PLAN.yaml` |
| Story 卡片 | `process/stories/STORY-{id}-{story_slug}.md` | `skills/story-manager/templates/STORY-TEMPLATE.md` |
| Story 状态汇总（legacy / generated） | `process/STORY-STATUS.md` | `skills/story-manager/templates/STORY-STATUS-TEMPLATE.md` |

## 约束

- Story 状态只能按既定生命周期推进，不允许跳级
- 缺少三件套的 Story 不得进入 LLD 审核
- 缺少 `feature_design_refs` 或 `lld_policy` 的 Story 不得通过 CP4
- `technical-note` / `waived` 只能用于低风险 Story；命中数据、安全、外部接口、并发、迁移或跨 Story 契约时必须升级 `full-lld`；`batch-lld` 只能用于 `standard-lite` / `allows_batch_lld=true` 的低中风险 Story，且必须有可被 CP5 独立引用的 Story 锚点
- 进入 CP6 前，`implementation_gate.status` 必须为 `ready-for-cp6` 或写明 N/A 原因
- 进入 verified / verified-with-risk 前，`verification_gate.cp7_result` 必须为合法结论；`PASS_WITH_RISK` 必须记录剩余风险和 CP8 输入，`NEEDS_REWORK` / `NEEDS_DESIGN_CLARIFICATION` 必须记录路由
- `DEVELOPMENT-PLAN.yaml` 是 Story 状态、Wave、任务、依赖和文件所有权的机器真相源；`STORY-STATUS.md` / `STORY-BACKLOG.md` 不得独立维护不同状态
- `STORY-STATUS.md` 若存在，必须与 `DEVELOPMENT-PLAN.yaml` 和卡片状态保持一致；冲突时以 `DEVELOPMENT-PLAN.yaml` 为准并运行 `meta-flow story plan-check`
- `story_slug` 必须由 Story 标题生成 kebab-case 稳定片段；已有卡片时必须复用原值，不得静默改名

## 验收标准

- [ ] Story 生命周期包含 LLD 审核门控
- [ ] 每张 Story 卡片包含完整三件套
- [ ] 每张 Story 卡片包含 `feature_design_refs` 和 `lld_policy`
- [ ] `full-lld` / `batch-lld` / `technical-note` / `waived` Story 含可被 CP5 审查的设计证据
- [ ] 实现阶段 Story 包含 `implementation_gate` 和实现执行上下文
- [ ] 验证阶段 Story 包含 `verification_gate` 和验证上下文
- [ ] `DEVELOPMENT-PLAN.yaml` 包含 `story_management_truth_source: process/DEVELOPMENT-PLAN.yaml`
- [ ] 汇总视图与 `DEVELOPMENT-PLAN.yaml` / 卡片状态一致
- [ ] `meta-flow story plan-check --project-root .` 返回 PASS，或已记录 legacy drift 风险
- [ ] Story 卡片文件名同时包含 Story 编号与名称 slug

## 不适用边界

- 当前任务是输出 HLD 或 LLD，而不是管理 Story 生命周期
- Story 尚未形成正式边界

## Gotchas

- `verified` 是验证完成，不等于最终归档；`verified-with-risk` 可继续推进但必须保留风险接受输入；只有收敛后才进入 `done`
- 批量更新状态时最容易漏掉 legacy 视图；先改 `DEVELOPMENT-PLAN.yaml`，再派生 / 刷新 `STORY-STATUS.md`，不得反向手工改状态
- `story_slug` 来自标题但一旦落盘即成为稳定标识；标题文案微调不能自动触发文件重命名
- 不要把 `lld_policy=technical-note` 当作“无需设计”；它仍需要 Story 卡片中的正式技术说明，并纳入 CP5 批量确认
- 不要把 `DEV-LOG.md` 当作默认万能交接；复杂 / 高风险 / Prompt-Skill / Guardrail / 安装器 / 平台适配 Story 仍必须有完整 IMPLEMENTATION
