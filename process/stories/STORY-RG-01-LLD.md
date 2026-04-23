---
story_id: "RG-01"
story_title: "meta-po 评审协调核心"
status: "confirmed"
tier: "M"
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T12:09:47+08:00"
created_at: "2026-04-23T12:09:47+08:00"
updated_at: "2026-04-23T12:09:47+08:00"
source_story: "process/stories/STORY-RG-01.md"
source_hld:
  - "process/HLD-review-gate.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - RG-01 meta-po 评审协调核心

## 1. Goal

为 `meta-po` 增加阶段出口文档评审协调能力，负责治理模式分流、review findings 聚合、升级仲裁和阶段交接边界判断。

## 2. Requirements（Functional / Non-Functional）

### 2.1 Functional

- F1：支持 `direct / review-gated / conditional` 三种治理分流。
- F2：支持 `严重 / 一般 / 轻微` findings 聚合与放行规则。
- F3：往返轮次达到 3 次时自动升级人工仲裁。
- F4：明确 story-planning / story-execution 交接边界。

### 2.2 Non-Functional

- NF1：meta-po 不得自评目标文档。
- NF2：只做协调，不直接改被评审文档。

## 3. 模块拆分与职责

| 模块 / 文件组 | 职责 | 说明 |
|---|---|---|
| `delivery/agents/meta-po.md` | 编排规则主载体 | 维护 review coordinator 语义 |

## 4. 代码结构与文件影响范围

| 动作 | 文件路径 | 变更内容 |
|---|---|---|
| 修改 | `delivery/agents/meta-po.md` | 增加治理分流、聚合规则、升级仲裁和交接边界 |

## 5. 数据模型与持久化设计

无新增持久化对象；逻辑上引入以下聚合模型：

| 对象 / 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `governance_mode` | enum | direct / review-gated / conditional | 决定是否触发评审 |
| `finding_severity` | enum | 严重 / 一般 / 轻微 | 决定阻断等级 |
| `round_trip_count` | int | `>= 3` 升级人工仲裁 | 防止死循环 |

## 6. API / Interface 设计

| 接口 / 入口 | 输入 | 输出 | 调用方 | 说明 |
|---|---|---|---|---|
| phase exit doc -> meta-po | 待评审文档 + 治理字段 | 是否进入 review gate | meta-se/meta-dev | 分流入口 |
| reviewer lanes -> meta-po | findings 列表 | 聚合结论 | reviewer agents | meta-po 负责聚合 |
| meta-po -> 检查点 | 聚合后的放行决定 | 是否进入人工确认 | user checkpoint | 不直接改文档 |

## 7. 核心处理流程

1. 读取出口文档的治理模式。
2. 判定是否进入 review gate。
3. 收集多 reviewer findings 并按严重级别聚合。
4. 若往返次数超限，升级人工仲裁。
5. 仅在评审通过后进入人工确认或下一阶段。

## 8. 技术设计细节

- `direct` 不触发 review gate。
- `conditional` 命中高风险对象时才触发。
- 聚合规则采用严重优先，避免“轻微问题稀释严重问题”。

## 9. 安全与性能设计

| 维度 | 设计措施 | 验证方式 |
|---|---|---|
| 安全 | 禁止 meta-po 自评或直接篡改目标文档 | 文本检查 |
| 性能 | 仅增加协调规则，无运行时代码 | 文本检查 |

## 10. 测试设计

| 测试场景 | 前置条件 | 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| direct 分流 | `governance_mode=direct` | 阅读规则 | 不触发 review gate | 文本检查 |
| review-gated 分流 | `governance_mode=review-gated` | 阅读规则 | 必触发结构化评审 | 文本检查 |
| 严重 findings 聚合 | 存在严重问题 | 阅读规则 | 阻断放行 | 文本检查 |
| 往返超限 | round_trip_count>=3 | 阅读规则 | 升级人工仲裁 | 文本检查 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细描述 |
|---|---|---|---|
| TASK-RG-01-01 | 修改 | `delivery/agents/meta-po.md` | 增加 review coordinator 段落 |
| TASK-RG-01-02 | 修改 | `delivery/agents/meta-po.md` | 固化 findings 聚合与升级规则 |
| TASK-RG-01-03 | 修改 | `delivery/agents/meta-po.md` | 写清 governance_mode 分流逻辑 |
| TASK-RG-01-04 | 修改 | `delivery/agents/meta-po.md` | 写清 story-planning / story-execution 边界 |

## 12. 风险、难点与预研建议

| 风险 / 难点 | 影响 | 缓解措施 / 预研建议 |
|---|---|---|
| 规则与功能 Agent 提示词不一致 | 后续执行漂移 | 在 RG-03 / RG-04 继续同步 reviewer lanes |

## 13. 回滚与发布策略

- 发布方式：更新 `meta-po.md`
- 回滚触发条件：规则与 HLD-review-gate 不一致
- 回滚动作：回退该段并以 HLD-review-gate 为准重写

## 14. Definition of Done

- [x] 14 个章节全部填写完成
- [x] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [x] `confirmed=false` 时不进入实现
- [x] 人工确认意见已收敛

## 人工确认区

> 已按委托方式确认并进入实现。

