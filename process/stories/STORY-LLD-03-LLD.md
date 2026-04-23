---
story_id: "LLD-03"
story_title: "LLD 生产/消费契约对齐"
status: "confirmed"
tier: "M"
shared_fragments: []
open_items: 0
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T13:30:00+08:00"
created_at: "2026-04-23T13:30:00+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
source_story: "process/stories/STORY-LLD-03.md"
source_hld:
  - "process/HLD-lld-writing-method.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - LLD-03 LLD 生产/消费契约对齐

## 1. Goal

把 `meta-dev`、`meta-qa` 与平台 rules 的 LLD 消费语义统一为同一套可执行口径。

## 2. Requirements（Functional / Non-Functional）

### 2.1 Functional

- F1：`meta-dev` 明确读取 Story、HLD、ADR、平台规则。
- F2：`meta-qa` 明确读取接口、异常、测试、回滚章节。
- F3：3 份 rules 文档同步 14 章节与消费契约。

### 2.2 Non-Functional

- NF1：不把 review gate 逻辑写回 LLD 方法正文。
- NF2：平台口径保持一致。

## 3. 模块拆分与职责

| 模块 / 文件组 | 职责 | 说明 |
|---|---|---|
| `delivery/agents/meta-dev.md` | 实现输入合同 | Ready Check 与实现边界 |
| `delivery/agents/meta-qa.md` | 验证输入合同 | 验证入口与失败条件 |
| `delivery/rules/*` | 平台统一规则 | 固化 14 章节与消费口径 |

## 4. 代码结构与文件影响范围

| 动作 | 文件路径 | 变更内容 |
|---|---|---|
| 修改 | `delivery/agents/meta-dev.md` | 新增 LLD 消费契约 |
| 修改 | `delivery/agents/meta-qa.md` | 新增 LLD 消费契约 |
| 修改 | `delivery/rules/AGENTS.md` | 增补 14 章节与消费规则 |
| 修改 | `delivery/rules/CLAUDE.md` | 同步规则口径 |
| 修改 | `delivery/rules/copilot-instructions.md` | 同步规则口径 |

## 5. 数据模型与持久化设计

| 对象 / 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `tier` | enum | S/M/L | 深度控制，不影响章节数 |
| `shared_fragments` | list | 可空 | 复用片段来源 |
| `open_items` | int | `>=0` | OPEN / Spike 计数 |

## 6. API / Interface 设计

| 接口 / 入口 | 输入 | 输出 | 调用方 | 说明 |
|---|---|---|---|---|
| `meta-dev` Ready Check | Story + LLD + ADR + rules | 实现入口 | meta-dev | 缺一不可 |
| `meta-qa` verification input | LLD sections 6/7/10/13 | 验证范围 | meta-qa | 不允许脑补 |
| rules sync | 统一文本约束 | 平台指令 | 各平台运行时 | 保持跨平台一致 |

## 7. 核心处理流程

1. 先在 agent 文本中固化消费职责。
2. 再在 rules 文档中同步强约束。
3. 由后续 Story 与 pilot 消费新契约。

## 8. 技术设计细节

- 14 章节固定属于硬规则。
- `Tier-S` 只减深度，不减章节数。
- agent 与 rules 采用相同名词，避免语义漂移。

## 9. 安全与性能设计

| 维度 | 设计措施 | 验证方式 |
|---|---|---|
| 安全 | 不新增执行能力 | 文本检查 |
| 性能 | 文档规则同步 | 文本检查 |

## 10. 测试设计

| 测试场景 | 前置条件 | 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| meta-dev 输入检查 | Agent 已更新 | 阅读文档 | 明确读取 Story/HLD/ADR/rules | 文本检查 |
| meta-qa 输入检查 | Agent 已更新 | 阅读文档 | 明确读取接口/异常/测试/回滚 | 文本检查 |
| rules 口径一致 | 3 份规则已更新 | 对比文案 | 14 章节与 rollout 一致 | 文本检查 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细描述 |
|---|---|---|---|
| TASK-LLD-03-01 | 修改 | `delivery/agents/meta-dev.md` | 补消费契约与 Ready Check |
| TASK-LLD-03-02 | 修改 | `delivery/agents/meta-qa.md` | 补消费契约与验证入口 |
| TASK-LLD-03-03 | 修改 | `delivery/rules/AGENTS.md` | 补 14 章节硬约束 |
| TASK-LLD-03-04 | 修改 | `delivery/rules/CLAUDE.md`、`delivery/rules/copilot-instructions.md` | 同步平台口径 |

## 12. 风险、难点与预研建议

| 风险 / 难点 | 影响 | 缓解措施 / 预研建议 |
|---|---|---|
| 平台口径不一致 | 下游行为漂移 | rules 同步更新并纳入验证 |

## 13. 回滚与发布策略

- 发布方式：原位更新 Agent / rules
- 回滚触发条件：新契约与已有 LLD 方法冲突
- 回滚动作：回退本 Story 修改并重新对齐术语

## 14. Definition of Done

- [x] 14 个章节全部填写完成
- [x] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [x] `confirmed=false` 时不进入实现
- [x] 人工确认意见已收敛

## 人工确认区

> 已按委托方式确认并进入实现。
