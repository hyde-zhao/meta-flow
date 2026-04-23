---
story_id: "RG-03"
story_title: "review mode 第一组扩展"
status: "confirmed"
tier: "S"
shared_fragments: []
open_items: 0
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T13:30:00+08:00"
created_at: "2026-04-23T13:30:00+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
source_story: "process/stories/STORY-RG-03.md"
source_hld:
  - "process/HLD-review-gate.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - RG-03 review mode 第一组扩展

## 1. Goal

为 `meta-pm`、`meta-se`、`meta-qa` 增加 `review_mode=true` 的结构化评审入口。

## 2. Requirements（Functional / Non-Functional）

### 2.1 Functional

- F1：3 个 Agent 都必须暴露 review mode 入口。
- F2：输出均引用统一 findings 模板。
- F3：review mode 与生产态边界清晰。

### 2.2 Non-Functional

- NF1：不得自评。
- NF2：不与正常执行步骤混写。

## 3. 模块拆分与职责

| 模块 / 文件组 | 职责 | 说明 |
|---|---|---|
| `meta-pm` | 产品 / 场景审查 | lane-product |
| `meta-se` | 架构审查 | lane-architecture |
| `meta-qa` | 质量审查 | lane-quality |

## 4. 代码结构与文件影响范围

| 动作 | 文件路径 | 变更内容 |
|---|---|---|
| 修改 | `delivery/agents/meta-pm.md` | 增加产品视角 review mode |
| 修改 | `delivery/agents/meta-se.md` | 增加架构视角 review mode |
| 修改 | `delivery/agents/meta-qa.md` | 增加质量视角 review mode |

## 5. 数据模型与持久化设计

无新增持久化；统一复用 `REVIEW-FINDINGS-TEMPLATE.md`。

## 6. API / Interface 设计

| 接口 / 入口 | 输入 | 输出 | 调用方 | 说明 |
|---|---|---|---|---|
| `review_mode=true` | target artifact + lane | findings markdown | meta-po | 只输出 findings |

## 7. 核心处理流程

1. meta-po 分派 lane。
2. 对应 Agent 在 review mode 下输出 findings。
3. 输出后停止，等待聚合。

## 8. 技术设计细节

- 文案显式写明“不进入生产态”。
- 每个 Agent 各自声明关注点。

## 9. 安全与性能设计

| 维度 | 设计措施 | 验证方式 |
|---|---|---|
| 安全 | 不执行目标文档修改 | 文本检查 |
| 性能 | 仅增加文档段落 | 文本检查 |

## 10. 测试设计

| 测试场景 | 前置条件 | 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| meta-pm review mode | Agent 已更新 | 阅读文档 | 包含场景审查入口 | 文本检查 |
| meta-se review mode | Agent 已更新 | 阅读文档 | 包含架构审查入口 | 文本检查 |
| meta-qa review mode | Agent 已更新 | 阅读文档 | 包含质量审查入口 | 文本检查 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细描述 |
|---|---|---|---|
| TASK-RG-03-01 | 修改 | `delivery/agents/meta-pm.md` | 写入 lane-product 审查入口 |
| TASK-RG-03-02 | 修改 | `delivery/agents/meta-se.md` | 写入 lane-architecture 审查入口 |
| TASK-RG-03-03 | 修改 | `delivery/agents/meta-qa.md` | 写入 lane-quality 审查入口 |

## 12. 风险、难点与预研建议

| 风险 / 难点 | 影响 | 缓解措施 / 预研建议 |
|---|---|---|
| 生产态和评审态混淆 | 误触发实现流程 | 在文案中显式停止条件 |

## 13. 回滚与发布策略

- 发布方式：Agent 文本原位更新
- 回滚触发条件：review mode 描述影响原有生产态
- 回滚动作：删除附加段落并重新隔离

## 14. Definition of Done

- [x] 14 个章节全部填写完成
- [x] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [x] `confirmed=false` 时不进入实现
- [x] 人工确认意见已收敛

## 人工确认区

> 已按委托方式确认并进入实现。
