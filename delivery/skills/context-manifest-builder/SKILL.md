---
name: context-manifest-builder
description: >-
  当需要为阶段切换、人工门禁、实现 / 验证 / 发布准备生成最小执行上下文胶囊或最终上下文清单时使用。
  触发词包括：上下文清单、执行上下文、CONTEXT-MANIFEST、CONTEXT-CAPSULE、上下文胶囊、token budget。
  适用场景：CP2 / CP3 / CP5 / CP6 / CP7 / CP8 前后，以及交付阶段与 workflow-renderer 同步使用。
argument-hint: "DEVELOPMENT-PLAN.yaml 或交付计划路径"
user-invokable: true
status: active
---

## 目标

基于已确认或待确认的阶段产物，生成 `process/context/*-CONTEXT.yaml` 阶段上下文胶囊；交付阶段可额外生成 `CONTEXT-MANIFEST.yaml`。目标是让下游 Agent **先读最小上下文，再按需读取全文档**，降低重复读取和 token 消耗。

## 适用场景

- CP2 / CP3 / CP5 / CP6 / CP7 / CP8 前需要把本阶段真相源压缩为可审计摘要
- 子 agent 交接前需要为 `context-handoff` 提供最小上下文输入
- 人工门禁前需要形成 Decision Brief 的读取来源摘要
- 文档交付阶段，需要为后续执行 / 诊断准备上下文清单
- 需要把关键设计决策、执行约束、读取预算和观测点结构化沉淀

## 前置条件

- [ ] `process/STATE.md` 可读取，且当前阶段明确
- [ ] 当前阶段至少有一个正式真相源或 N/A / WAIVED 理由
- [ ] 若用于人工门禁，Decision Brief 或待人工决策队列已可读取

## 必须读取的输入

- `process/STATE.md`
- 当前阶段正式对象：
  - CP2：`process/REQUEST.md`、`docs/product/USE-CASES.md`、`docs/product/REQUIREMENTS.md`、`docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/product/STORY-MAP.md`、`docs/product/MVP-SCOPE.md`
  - CP3：`docs/design/BLUEPRINT.md`、`docs/design/DOMAIN-MAP.md`、`docs/design/DEPENDENCY-MAP.md`、`docs/design/HLD.md`、`docs/design/ARCHITECTURE-DECISION.md`
  - CP5：`docs/design/FEATURE-DESIGN-MATRIX.md`、`docs/features/**`、`process/stories/STORY-*.md`、`process/stories/STORY-*-LLD.md`
  - CP6：Story 卡片、实现执行证据、CP5 结果、当前 Wave 计划
  - CP7：`docs/product/TEST-MATRIX.md`、实现执行证据、验证执行证据、CP6 结果
  - CP8：`process/release/RELEASE-CONTEXT.yaml`、质量评审、发布准备和文档缺口
- 相关 Decision Brief、待人工决策项、discussion checkpoint、CR、风险接受和不授权项

## 知识来源

- `skills/context-manifest-builder/templates/CONTEXT-CAPSULE-TEMPLATE.yaml`
- `skills/context-manifest-builder/templates/CONTEXT-MANIFEST-TEMPLATE.yaml`
- 已批准的计划、设计与验证文档
- 当前交付边界与目标平台约束

## 执行步骤

1. 判定 capsule 类型：`cp2-requirement`、`cp3-design`、`cp5-lld`、`cp6-implementation`、`cp7-verification`、`cp8-delivery` 或 `final-manifest`。
2. 读取 `STATE.md.context_budget`，确认本阶段 `read_profile`、`max_source_files`、`full_doc_read_policy` 和 `full_doc_read_reason`。
3. 从正式真相源提炼当前阶段最小事实：范围、关键决策、依赖、风险、不授权项、开放问题、下游需要读取的文件列表。
4. 标记 `must_read`、`read_if_needed`、`do_not_read_by_default`，并写明全文档读取触发条件。
5. 将结果写入 `process/context/<CP>-<slug>-CONTEXT.yaml`；交付阶段如需最终清单，再写入 `delivery/doc/CONTEXT-MANIFEST.yaml` 或目标项目约定路径。
6. 回写 `STATE.md.context_budget.phase_capsules[]` 的路径、状态、生成时间和缺失 / 降级原因。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 阶段上下文胶囊 | `process/context/CP2-REQUIREMENT-CONTEXT.yaml` | `skills/context-manifest-builder/templates/CONTEXT-CAPSULE-TEMPLATE.yaml` |
| 阶段上下文胶囊 | `process/context/CP3-DESIGN-CONTEXT.yaml` | `skills/context-manifest-builder/templates/CONTEXT-CAPSULE-TEMPLATE.yaml` |
| 阶段上下文胶囊 | `process/context/CP5-LLD-CONTEXT.yaml` | `skills/context-manifest-builder/templates/CONTEXT-CAPSULE-TEMPLATE.yaml` |
| 阶段上下文胶囊 | `process/context/CP6-IMPLEMENTATION-CONTEXT.yaml` | `skills/context-manifest-builder/templates/CONTEXT-CAPSULE-TEMPLATE.yaml` |
| 阶段上下文胶囊 | `process/context/CP7-VERIFICATION-CONTEXT.yaml` | `skills/context-manifest-builder/templates/CONTEXT-CAPSULE-TEMPLATE.yaml` |
| 阶段上下文胶囊 | `process/context/CP8-DELIVERY-CONTEXT.yaml` | `skills/context-manifest-builder/templates/CONTEXT-CAPSULE-TEMPLATE.yaml` |
| 最终上下文清单 | `delivery/doc/CONTEXT-MANIFEST.yaml` 或目标项目约定路径 | `skills/context-manifest-builder/templates/CONTEXT-MANIFEST-TEMPLATE.yaml` |

## 约束

- 阶段 capsule 必须遵循 `CONTEXT-CAPSULE-TEMPLATE.yaml`
- Agent 默认先读 capsule；只有 capsule 缺失、冲突、字段不足、人工审计或深度评审触发时，才读取完整上游文档
- 读取完整文档时必须在 `full_doc_read_reason` 或 capsule `read_expansion_log` 中写明理由
- `must_read`、`key_facts`、`downstream_tasks`、`risks_and_decisions`、`token_control` 不可留空；确无内容时必须写 N/A 理由
- `do_not_read_by_default` 必须列出无关历史草稿、失败轮次、完整 transcript 和非当前 Story / Wave
- 最终清单必须遵循 `CONTEXT-MANIFEST-TEMPLATE.yaml`
- `design_decisions`、`execution_constraints`、`observability_points` 不可留空
- 若输入文档中无事实依据，不得补写虚构约束

## 验收标准

- [ ] capsule 顶级字段完整
- [ ] `read_profile` 与 `STATE.md.context_budget` 一致
- [ ] `must_read` 不超过当前阶段必要真相源；超出时有理由
- [ ] `read_if_needed` 与 `full_doc_read_policy` 有触发条件
- [ ] `do_not_read_by_default` 明确排除历史草稿、失败轮次和无关 Story
- [ ] 关键决策、开放问题、风险和不授权项已进入 `risks_and_decisions`
- [ ] 关联产物指向当前交付对象

## 不适用边界

- 当前任务只要求修正文案，且不触发阶段切换、人工门禁、实现、验证或发布准备
- 计划 / 设计对象尚未形成任何稳定事实，无法抽取 capsule；此时应记录缺失原因而不是虚构上下文

## Gotchas

- capsule 不是正式文档的替代品；它是默认读取入口和恢复索引，冲突时以正式文档为准
- 不要把上游文档正文复制进 capsule；只摘取决策、约束、文件指针和下游任务所需事实
- `must_read` 过多会抵消 token 节省，优先把非阻断材料放入 `read_if_needed`
- 观测点不是“文档目录清单”，而是用于执行诊断的检查入口
- 上下文清单需要足够精简，避免把所有上游文档全文重新复制进去

