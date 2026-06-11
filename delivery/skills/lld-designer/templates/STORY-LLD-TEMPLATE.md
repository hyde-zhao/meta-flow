---
story_id: "STORY-{id}"
title: ""
story_slug: ""
lld_version: "1.0"
tier: "S | M | L"
status: "ready-for-review"  # ready-for-review | confirmed
confirmed: false
created_by: "meta-dev"
created_at: ""
confirmed_by: ""
confirmed_at: ""
shared_fragments: []
feature_design_refs: []
lld_policy:
  required_level: "full-lld"
  trigger_reasons: []
  rationale: ""
open_items: 0
---

# LLD: STORY-{id} — {标题}

> 文件名格式：`STORY-{id}-{story_slug}-LLD.md`，其中 `story_slug` 必须复用对应 Story 卡片中的稳定 slug。
>
> 本文档只用于 `lld_policy.required_level=full-lld` 的 Story。
> `technical-note` / `waived` Story 的正式设计证据写在对应 Story 卡片中。
> 本文档需纳入全部目标 Story 的设计证据统一确认，并满足当前 Wave 的 `dev_gate` 后方可进入实现。

## 0. 上游设计依据

| 来源 | 路径 / ID | 被本 LLD 消费的内容 |
|---|---|---|
| HLD | `docs/design/HLD.md` | <架构约束> |
| ADR | `docs/design/ARCHITECTURE-DECISION.md` | <关键决策> |
| Feature Matrix | `docs/design/FEATURE-DESIGN-MATRIX.md` | <lld_policy 判定> |
| Feature DESIGN | `docs/features/<feature>/DESIGN.md` | <接口 / 数据 / 任务约束> |

## 1. Goal

> 一句话说明本 Story 要创建 / 修改 / 删除什么，以及完成后的业务或工程效果。

## 2. Requirements（Functional / Non-Functional）

### 2.1 Functional

- 

### 2.2 Non-Functional

- 

## 3. 模块拆分与职责

| 模块 / 文件组 | 职责 | 说明 |
|---|---|---|
|  |  |  |

> 若引用共享设计片段，请写成 `process/shared/{file}#{section}`，并在“说明”列标出差异化使用点。

## 4. 代码结构与文件影响范围

> 使用确定性动词（创建 / 修改 / 删除），不允许使用“可能”“也许”等模糊描述。

| 动作 | 文件路径 | 变更内容 |
|---|---|---|
| 创建 |  |  |

## 5. 数据模型与持久化设计

| 对象 / 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
|  |  |  |  |

> 若无持久化变更，请显式写明“无新增数据模型 / 持久化变更”。

## 6. API / Interface 设计

| 接口 / 入口 | 输入 | 输出 | 调用方 | 说明 |
|---|---|---|---|---|
|  |  |  |  |  |

> 本节每个接口条目，必须在 **第 10 节测试设计** 中找到至少 1 条对应测试。

## 7. 核心处理流程

1. 
2. 
3. 

> 命中以下任一条件时，必须补至少 1 张 Mermaid 图：跨 3 个以上模块、存在异步/补偿路径、异常分支无法一眼看清。

## 8. 技术设计细节

- 关键算法 / 规则：
- 依赖选择与复用点：
- 兼容性处理：
- 图示类型选择：时序图 / 流程图 / 状态图 / 结构图（按实际命中者填写）

## 9. 安全与性能设计

| 维度 | 设计措施 | 验证方式 |
|---|---|---|
| 安全 |  |  |
| 性能 |  |  |

## 10. 测试设计

| 测试场景 | 前置条件 | 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
|  |  |  |  |  |

## 11. 实施步骤

> 严格使用 TASK-ID + 确定性动词（创建 / 修改 / 删除）。

| TASK-ID | 动作 | 目标文件 | 详细描述 | 对应测试 |
|---|---|---|---|---|
| TASK-{id}-01 |  |  |  |  |

> 每个 TASK-ID 至少覆盖 1 个文件影响项；每个文件影响项至少被 1 个 TASK-ID 覆盖。

## 12. 风险、难点与预研建议

### 12.1 实现灰区与取舍记录

> 并行 LLD 阶段遇到需要用户或上游决策的实现灰区时，先写入 `STATE.md.parallel_execution.lld_clarification_queue.items[]`，由 host-orchestrator 作为 question broker 批量询问。已回答或转 OPEN / Spike 的问题必须回填到本表。

| Clarification ID | 问题 | 选项与推荐 | 决策 / 答案 | 影响面 | 证据 | 重访条件 |
|---|---|---|---|---|---|---|
| LCQ-STORY-{id}-01 |  |  |  | 接口 / 文件 owner / 测试 / 安全 / 文档 / 跨 Story 契约 |  |  |

| 风险 / 难点 | 影响 | 缓解措施 / 预研建议 |
|---|---|---|
|  |  |  |

### OPEN / Spike 跟踪

| ID | 类型（OPEN / Spike） | 问题 | 下一动作 | 责任方 |
|---|---|---|---|---|
| O-01 | OPEN |  |  |  |

## 13. 回滚与发布策略

- 发布方式：
- 回滚触发条件：
- 回滚动作：

## 14. Definition of Done

- [ ] 14 个章节全部填写完成
- [ ] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [ ] 实现灰区与取舍记录已回填所有相关 clarification item，或显式写“无”
- [ ] `confirmed=false` 时不进入实现
- [ ] 人工确认意见已收敛
- [ ] frontmatter 已填写 `tier`
- [ ] OPEN / Spike 已清点或显式写“无”

## 人工确认区

> **CP5 — Story 设计证据可实现性门**
> meta-dev 先写入 `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md` 自动预检结果。
> host-orchestrator 收齐全部目标 Story 的完整 LLD、Story 技术说明或 waived 证据、CP4 自动预检摘要和 CP5 自动预检后，再生成并提示用户审查 `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md`。
> 用户统一确认全部目标 Story 的设计证据后，仍需满足当前 Wave、依赖门控与文件所有权门控方可进入实现。

**CP5 checklist 摘要**：

| # | 检查项 | 状态 | 证据 |
|---|---|---|---|
| 1 | LLD 覆盖 AC | 待检查 | 第 2 / 10 / 14 节 |
| 2 | 与 HLD / ADR 一致 | 待检查 | 第 3 / 8 / 12 节 |
| 3 | 文件影响范围明确 | 待检查 | 第 4 / 11 节 |
| 4 | 接口契约完整 | 待检查 | 第 6 节 |
| 5 | 测试与 dev_gate 可计算 | 待检查 | 第 10 / 14 节 |
| 6 | clarification queue 已收敛 | 待检查 | 第 12.1 节 / `STATE.md.parallel_execution.lld_clarification_queue` |

**人工确认回复**：

请直接回复以下任一整行：

```text
approve
修改: <具体修改点>
reject
```

- `approve`：LLD 设计合理，允许进入实现。
- `修改: <具体修改点>`：指出具体修改点后由 meta-dev 更新重提。
- `reject`：设计方向有根本问题，需重新设计。
- Codex 历史别名 `1/通过`、`2/修改: ...`、`3/不通过` 仅作兼容解析；新提示不得把多个别名混排为主要选项。

**人工审查结果回填**：

- 结论：`approved | changes_requested | rejected`
- 审查人：
- 审查时间：
- 修改意见：
- 风险接受项：
