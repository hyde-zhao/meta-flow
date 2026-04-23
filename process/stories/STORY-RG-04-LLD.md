---
story_id: "RG-04"
story_title: "review mode 第二组扩展"
status: "confirmed"
tier: "S"
shared_fragments: []
open_items: 0
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T13:30:00+08:00"
created_at: "2026-04-23T13:30:00+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
source_story: "process/stories/STORY-RG-04.md"
source_hld:
  - "process/HLD-review-gate.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - RG-04 review mode 第二组扩展

## 1. Goal

补齐 `meta-dev` 与 `meta-doc` 的 review mode，覆盖可实现性和交付可读性两个视角。

## 2. Requirements（Functional / Non-Functional）

### 2.1 Functional

- F1：`meta-dev` review mode 明确关注接口 / 文件归属 / 平台约束。
- F2：`meta-doc` review mode 明确关注用户可读性和交付完整性。

### 2.2 Non-Functional

- NF1：与生产态执行隔离。
- NF2：统一 findings 模板。

## 3. 模块拆分与职责

| 模块 / 文件组 | 职责 | 说明 |
|---|---|---|
| `meta-dev` | 实现可行性评审 | lane-implementation |
| `meta-doc` | 文档可读性评审 | lane-docs |

## 4. 代码结构与文件影响范围

| 动作 | 文件路径 | 变更内容 |
|---|---|---|
| 修改 | `delivery/agents/meta-dev.md` | 增加 review mode 小节 |
| 修改 | `delivery/agents/meta-doc.md` | 增加 review mode 小节 |

## 5. 数据模型与持久化设计

无新增持久化；沿用 findings 模板字段。

## 6. API / Interface 设计

| 接口 / 入口 | 输入 | 输出 | 调用方 | 说明 |
|---|---|---|---|---|
| `review_mode=true` | artifact + lane | findings markdown | meta-po | 输出后停止 |

## 7. 核心处理流程

1. meta-po 为实现或文档对象分派 lane。
2. `meta-dev` / `meta-doc` 输出结构化 findings。
3. meta-po 聚合后决定是否进入下一阶段。

## 8. 技术设计细节

- `meta-dev` review mode 不创建文件。
- `meta-doc` review mode 不改正文，只提可读性问题。

## 9. 安全与性能设计

| 维度 | 设计措施 | 验证方式 |
|---|---|---|
| 安全 | 无命令执行，无文件写入 | 文本检查 |
| 性能 | 仅追加段落 | 文本检查 |

## 10. 测试设计

| 测试场景 | 前置条件 | 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| meta-dev review mode | Agent 已更新 | 阅读文档 | 存在实现可行性关注点 | 文本检查 |
| meta-doc review mode | Agent 已更新 | 阅读文档 | 存在可读性关注点 | 文本检查 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细描述 |
|---|---|---|---|
| TASK-RG-04-01 | 修改 | `delivery/agents/meta-dev.md` | 新增实现视角 review mode |
| TASK-RG-04-02 | 修改 | `delivery/agents/meta-doc.md` | 新增文档视角 review mode |

## 12. 风险、难点与预研建议

| 风险 / 难点 | 影响 | 缓解措施 / 预研建议 |
|---|---|---|
| 可读性建议过于主观 | 难以聚合 | 强制使用 evidence / impact / suggestion 字段 |

## 13. 回滚与发布策略

- 发布方式：Agent 文本原位更新
- 回滚触发条件：review mode 与生产态冲突
- 回滚动作：移除评审段落并重新设计边界

## 14. Definition of Done

- [x] 14 个章节全部填写完成
- [x] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [x] `confirmed=false` 时不进入实现
- [x] 人工确认意见已收敛

## 人工确认区

> 已按委托方式确认并进入实现。
