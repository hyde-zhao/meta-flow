---
story_id: "PILOT-01"
story_title: "review-gated LLD 组合试点"
status: "confirmed"
tier: "S"
shared_fragments:
  - "process/HLD-review-gate.md#review-产物协议"
  - "process/HLD-lld-writing-method.md#14-章节约束"
open_items: 0
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T13:30:00+08:00"
created_at: "2026-04-23T13:30:00+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
source_story: "process/stories/STORY-PILOT-01.md"
source_hld:
  - "process/HLD-review-gate.md"
  - "process/HLD-lld-writing-method.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - PILOT-01 review-gated LLD 组合试点

## 1. Goal

证明新的 14 章节 Story LLD 能被 reviewer lane、meta-dev 和 meta-qa 共同消费。

## 2. Requirements（Functional / Non-Functional）

### 2.1 Functional

- F1：保留 14 个可见章节。
- F2：显式给出 `tier`、`shared_fragments`、`open_items`。
- F3：让 review gate 可直接从本 LLD 提取 evidence 与 anchor。

### 2.2 Non-Functional

- NF1：只做方法验证，不进入真实交付实现。
- NF2：文本必须足够清晰，供 documentation 阶段引用。

## 3. 模块拆分与职责

| 模块 / 文件组 | 职责 | 说明 |
|---|---|---|
| review gate | 提取 findings | 读取章节与 anchor |
| meta-dev | 验证可实现性 | 读取文件范围、接口、步骤 |
| meta-qa | 验证可验证性 | 读取异常、测试、回滚 |

## 4. 代码结构与文件影响范围

| 动作 | 文件路径 | 变更内容 |
|---|---|---|
| 创建 | `process/stories/STORY-PILOT-01-LLD.md` | 试点 LLD 本体 |

## 5. 数据模型与持久化设计

| 对象 / 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `tier` | enum | `S` | 试点深度 |
| `shared_fragments` | list | 非空 | 指向两份 HLD 片段 |
| `open_items` | int | `0` | 无遗留问题 |

## 6. API / Interface 设计

| 接口 / 入口 | 输入 | 输出 | 调用方 | 说明 |
|---|---|---|---|---|
| review lane | 本 LLD | findings | meta-po | 读取章节锚点 |
| meta-dev | 本 LLD | 可实现性判断 | meta-po | 读取第 4/6/11/13 节 |
| meta-qa | 本 LLD | 可验证性判断 | meta-po | 读取第 7/10/13 节 |

## 7. 核心处理流程

1. 读取共享片段。
2. 输出固定 14 章节 LLD。
3. 由 reviewer lane 提取 findings。
4. 由 meta-dev / meta-qa 读取实施与验证信息。

## 8. 技术设计细节

- 章节编号固定，便于 anchor 引用。
- 本文不写实现代码，只写消费契约。

## 9. 安全与性能设计

| 维度 | 设计措施 | 验证方式 |
|---|---|---|
| 安全 | 无命令、无脚本嵌入 | 文本检查 |
| 性能 | 单文档验证 | 文本检查 |

## 10. 测试设计

| 测试场景 | 前置条件 | 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 14 章节校验 | 文档已创建 | 逐节检查 | 14 节完整 | 人工检查 |
| review 消费校验 | 模板已存在 | 对照 findings 模板 | 字段可提取 | 人工检查 |
| 角色消费校验 | Agent 已更新 | 对照 meta-dev/meta-qa 契约 | 可直接读取对应章节 | 人工检查 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细描述 |
|---|---|---|---|
| TASK-PILOT-01-01 | 创建 | `process/stories/STORY-PILOT-01-LLD.md` | 按新方法起草试点 LLD |

## 12. 风险、难点与预研建议

| 风险 / 难点 | 影响 | 缓解措施 / 预研建议 |
|---|---|---|
| 试点过于理想化 | 证明力不足 | 明确覆盖 review / 实现 / 验证三方消费 |

## 13. 回滚与发布策略

- 发布方式：保留为 process 试点文档
- 回滚触发条件：无法支撑三方消费
- 回滚动作：补充章节或重新选择试点范围

## 14. Definition of Done

- [x] 14 个章节全部填写完成
- [x] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [x] `confirmed=false` 时不进入实现
- [x] 人工确认意见已收敛

## 人工确认区

> 已按委托方式确认并通过试点检查。
