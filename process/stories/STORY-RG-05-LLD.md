---
story_id: "RG-05"
story_title: "分派表与灰度落地"
status: "confirmed"
tier: "S"
shared_fragments: []
open_items: 0
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T13:30:00+08:00"
created_at: "2026-04-23T13:30:00+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
source_story: "process/stories/STORY-RG-05.md"
source_hld:
  - "process/HLD-review-gate.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - RG-05 分派表与灰度落地

## 1. Goal

将 reviewer 分派表与 HLD/LLD 优先试点的 rollout 顺序写入正式 README / rules。

## 2. Requirements（Functional / Non-Functional）

### 2.1 Functional

- F1：`delivery/skills/README.md` 增加 reviewer dispatch 表。
- F2：3 份 rules 文档都写明 rollout 顺序。
- F3：dispatch 与已实现的 review mode 一一对应。

### 2.2 Non-Functional

- NF1：先试点 HLD / LLD，再扩到其他文档。
- NF2：跨平台口径一致。

## 3. 模块拆分与职责

| 模块 / 文件组 | 职责 | 说明 |
|---|---|---|
| `delivery/skills/README.md` | 人类可读分派表 | 记录 lane 与 agent 对应 |
| `delivery/rules/*` | 平台 rollout 规则 | 固化灰度顺序 |

## 4. 代码结构与文件影响范围

| 动作 | 文件路径 | 变更内容 |
|---|---|---|
| 修改 | `delivery/skills/README.md` | 增加 reviewer dispatch 与 rollout |
| 修改 | `delivery/rules/AGENTS.md` | 增加 review gate rollout |
| 修改 | `delivery/rules/CLAUDE.md` | 同步 rollout |
| 修改 | `delivery/rules/copilot-instructions.md` | 同步 rollout |

## 5. 数据模型与持久化设计

无新增持久化；仅新增表格化关系。

## 6. API / Interface 设计

| 接口 / 入口 | 输入 | 输出 | 调用方 | 说明 |
|---|---|---|---|---|
| reviewer dispatch | lane + agent | 可读映射表 | 维护者 / meta-po | 分派依据 |
| rollout rule | artifact class | rollout phase | 各平台 | 先后顺序控制 |

## 7. 核心处理流程

1. 以已实现的 review mode 为事实源。
2. 在 README 记录 lane 映射。
3. 在 rules 记录 rollout 顺序。

## 8. 技术设计细节

- README 负责“谁做什么”。
- rules 负责“先在哪些对象上启用”。

## 9. 安全与性能设计

| 维度 | 设计措施 | 验证方式 |
|---|---|---|
| 安全 | 无执行能力新增 | 文本检查 |
| 性能 | 仅文档更新 | 文本检查 |

## 10. 测试设计

| 测试场景 | 前置条件 | 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| README dispatch | README 已更新 | 阅读文档 | lane 与 agent 一一对应 | 文本检查 |
| rules rollout | rules 已更新 | 对比文案 | 先 HLD/LLD、后其他文档 | 文本检查 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细描述 |
|---|---|---|---|
| TASK-RG-05-01 | 修改 | `delivery/skills/README.md` | 新增 reviewer dispatch 表 |
| TASK-RG-05-02 | 修改 | `delivery/rules/AGENTS.md` | 新增 rollout 顺序 |
| TASK-RG-05-03 | 修改 | `delivery/rules/CLAUDE.md`、`delivery/rules/copilot-instructions.md` | 同步平台口径 |

## 12. 风险、难点与预研建议

| 风险 / 难点 | 影响 | 缓解措施 / 预研建议 |
|---|---|---|
| dispatch 与真实能力不一致 | review gate 路由错误 | 以已实现 Agent 为准回写 README |

## 13. 回滚与发布策略

- 发布方式：README / rules 原位更新
- 回滚触发条件：review mode 分工变化
- 回滚动作：同步刷新 dispatch 与 rollout 文案

## 14. Definition of Done

- [x] 14 个章节全部填写完成
- [x] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [x] `confirmed=false` 时不进入实现
- [x] 人工确认意见已收敛

## 人工确认区

> 已按委托方式确认并进入实现。
