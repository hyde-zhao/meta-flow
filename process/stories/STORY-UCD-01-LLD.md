---
story_id: "UCD-01"
story_title: "use-case-discovery 核心增强"
status: "confirmed"
tier: "S"
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T11:47:36+08:00"
created_at: "2026-04-23T11:47:36+08:00"
updated_at: "2026-04-23T11:47:36+08:00"
source_story: "process/stories/STORY-UCD-01.md"
source_hld:
  - "process/HLD.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - UCD-01 use-case-discovery 核心增强

## 1. Goal

将 `use-case-discovery` Skill 升级为可显式处理产物类型感知、治理字段输出、`mixed` 判定和草稿恢复的正式发现入口，同时不把 review gate 逻辑写回 Skill 本体。

## 2. Requirements

### Functional

- F1：Skill 必须显式包含 Phase 0/1A/1B/2/3 五阶段结构。
- F2：Skill 必须定义 tool / skill / agent / workflow / mixed 的判定与追问重点。
- F3：Skill 必须保留并解释 `target_artifact_type`、`governance_mode`、`review_policy`。
- F4：Skill 必须描述 `draft/confirmed` 恢复路径与失败行为。

### Non-Functional

- NF1：保持中文默认输出风格。
- NF2：不得新增 review gate 执行逻辑。
- NF3：分类规则必须可机读、可检查，避免模糊措辞。

## 3. 模块拆分与职责

| 模块 | 职责 | 输入 | 输出 |
|---|---|---|---|
| Intent Intake | 接收用户意图、识别发现入口 | 原始请求 | discovery 启动条件 |
| Artifact Classifier | 判定目标产物类型和 `mixed` | 请求文本、追问结果 | `target_artifact_type` |
| Discovery Pipeline | 组织 Phase 0/1A/1B/2/3 步骤 | 分类结果、已有草稿 | 分阶段执行说明 |
| Governance Writer | 输出治理字段语义与边界 | discovery 结果 | `governance_mode`、`review_policy` |
| Recovery Handler | 处理 draft/confirmed 恢复、失败回退 | 历史草稿、用户上下文 | 恢复/阻塞路径 |

## 4. 代码结构与文件影响范围

| 动作 | 文件 | 说明 |
|---|---|---|
| 修改 | `delivery/skills/use-case-discovery/SKILL.md` | 扩展主流程、分类矩阵、治理字段、恢复/失败路径 |

## 5. 数据模型与持久化设计

本 Story 不新增独立持久化对象；需要在 Skill 规范中固化以下结构化输出字段：

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `target_artifact_type` | enum | tool/skill/agent/workflow/mixed | 发现阶段主分类结果 |
| `governance_mode` | enum | direct/review-gated/conditional | 决定后续门禁方式 |
| `review_policy` | enum | none/light/strict | 决定是否进入 review gate |

## 6. API / Interface 设计

| 接口 | 输入 | 输出 | 错误/异常 |
|---|---|---|---|
| 用户 -> Skill | 自然语言目标、上下文、已有草稿 | 发现问题、治理字段、产物类型判断 | 目标不清、目标冲突 |
| Skill -> meta-pm | 已确认场景与治理字段 | `USE-CASES.md` 编写约束 | 若类型不清则不得向下游输出稳定治理字段 |

## 7. 核心处理流程

1. Phase 0：识别当前请求是否进入 use-case discovery。
2. Phase 1A：收集原始目标与候选产物类型。
3. Phase 1B：按矩阵追问并收敛为单类或 `mixed`。
4. Phase 2：组织场景发现与治理字段。
5. Phase 3：输出可交接的发现结果与恢复指引。

### 异常流程

- 若目标同时命中多个产物，且无法靠追问收敛，则输出 `mixed` 并写明拆分建议。
- 若用户要求恢复历史草稿但状态不明，则进入恢复澄清，不得默认覆盖。
- 若请求本质是 review gate 或 LLD 方法设计，则显式路由到相邻 Skill，不在本 Skill 内处理。

## 8. 技术设计细节

- 使用显式阶段标题组织正文，避免把 Phase 逻辑写成长段落说明。
- `mixed` 规则采用“多目标并存 / 触发方式不同 / 交付路径不同”三条硬规则。
- 恢复逻辑采用先识别草稿状态、后决定继续/重建的顺序，不允许静默跳过。

## 9. 安全与性能设计

- 不执行任何命令，不读取非必要外部目录。
- 对模糊目标只输出澄清问题，不做强行分类。
- 维持单轮文本处理，无额外性能风险。

## 10. 测试设计

| 测试点 | 输入场景 | 期望结果 |
|---|---|---|
| T-01 | 单一 skill 诉求 | 正确输出 `target_artifact_type=skill` |
| T-02 | 同时涉及 agent + skill | 触发 `mixed` 或拆分建议 |
| T-03 | 已有 draft 继续完善 | 命中恢复路径，不重新初始化 |
| T-04 | 错把 review gate 请求送入本 Skill | 正确拒绝并路由 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细步骤 | 验证对应 |
|---|---|---|---|---|
| T1 | 修改 | `delivery/skills/use-case-discovery/SKILL.md` | 写入 Phase 0/1A/1B/2/3 主流程 | T-01 |
| T2 | 修改 | `delivery/skills/use-case-discovery/SKILL.md` | 写入产物类型矩阵与 `mixed` 三条硬规则 | T-01,T-02 |
| T3 | 修改 | `delivery/skills/use-case-discovery/SKILL.md` | 增加 draft/confirmed 恢复和失败路径 | T-03 |
| T4 | 修改 | `delivery/skills/use-case-discovery/SKILL.md` | 增加治理字段语义与 Gotchas | T-04 |

## 12. 风险、难点与预研建议

| 风险 | 影响 | 应对 |
|---|---|---|
| Phase 段落过多导致冗长 | 可读性下降 | 用固定小节和表格收敛 |
| `mixed` 规则过宽 | 下游大量误判 | 保持三条硬规则，不做模糊兜底 |
| 恢复语义与 meta-pm 不一致 | 交接漂移 | 在 UCD-03 同步上下游契约 |

## 13. 回滚与发布策略

- 若改造后读者无法快速定位主流程，可回滚到旧版 `SKILL.md` 并保留治理字段定义。
- 发布采用单文件变更，无额外脚本或安装结构影响。
- 若发现与 review gate 职责混写，立即回退相关段落并在后续 Story 处理。

## 14. Definition of Done + 确认区

### Definition of Done

- [x] `SKILL.md` 包含 Phase 0/1A/1B/2/3
- [x] 明确 tool / skill / agent / workflow / mixed 的判定
- [x] 包含治理字段与恢复路径
- [x] 不含 review gate 执行逻辑

### 确认区

- `confirmed`: true
- 待确认事项：
  1. 治理字段语义是否需要单独章节承载
  2. `mixed` 规则示例数量是否需要固定为 3 例
