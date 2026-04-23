---
story_id: "RG-02"
story_title: "review 产物协议与静态前置检查"
status: "confirmed"
tier: "S"
shared_fragments: []
open_items: 0
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T13:30:00+08:00"
created_at: "2026-04-23T13:30:00+08:00"
updated_at: "2026-04-23T13:30:00+08:00"
source_story: "process/stories/STORY-RG-02.md"
source_hld:
  - "process/HLD-review-gate.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - RG-02 review 产物协议与静态前置检查

## 1. Goal

为 review gate 固化 findings / summary 模板，并提供仅做机械校验的静态检查脚本。

## 2. Requirements（Functional / Non-Functional）

### 2.1 Functional

- F1：新增 findings 模板，覆盖 reviewer、lane、artifact、severity、rule_ref、evidence。
- F2：新增 summary 模板，覆盖聚合结论、计数和下一步决策。
- F3：新增脚本，校验 frontmatter、章节和锚点。
- F4：在 `meta-po` 中声明模板与脚本入口。

### 2.2 Non-Functional

- NF1：脚本只做结构校验，不做语义判断。
- NF2：实现不引入外部依赖。

## 3. 模块拆分与职责

| 模块 / 文件组 | 职责 | 说明 |
|---|---|---|
| `delivery/skills/review-artifact-protocol/` | 持有评审共享资产 | 供各 reviewer lane 共用 |
| `delivery/skills/review-artifact-protocol/scripts/validate_review_artifact.py` | 结构检查 | 面向 findings / summary |
| `delivery/agents/meta-po.md` | 路由与聚合说明 | 引用模板与脚本 |

## 4. 代码结构与文件影响范围

| 动作 | 文件路径 | 变更内容 |
|---|---|---|
| 创建 | `delivery/skills/review-artifact-protocol/templates/REVIEW-FINDINGS-TEMPLATE.md` | 定义 findings 结构 |
| 创建 | `delivery/skills/review-artifact-protocol/templates/REVIEW-SUMMARY-TEMPLATE.md` | 定义 summary 结构 |
| 创建 | `delivery/skills/review-artifact-protocol/scripts/validate_review_artifact.py` | 静态校验脚本 |
| 修改 | `delivery/agents/meta-po.md` | 暴露模板与脚本路径 |

## 5. 数据模型与持久化设计

| 对象 / 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `reviewer` | string | 非空 | 评审执行体 |
| `lane` | string | 非空 | reviewer lane |
| `artifact` | path | 非空 | 被评审对象 |
| `decision` | enum | `proceed/revise/escalate` | summary 聚合动作 |

## 6. API / Interface 设计

| 接口 / 入口 | 输入 | 输出 | 调用方 | 说明 |
|---|---|---|---|---|
| review template | 路由信息 | markdown 模板 | reviewer lane | 结构化 findings / summary |
| validator script | markdown path + kind | 退出码 + `OK/ERROR` | meta-po / 人工 | 机械性检查 |

## 7. 核心处理流程

1. reviewer lane 基于 findings 模板输出问题。
2. meta-po 用 summary 模板聚合多 lane 结论。
3. validator 脚本在提交前检查模板结构是否完整。

## 8. 技术设计细节

- frontmatter 采用轻量 yaml-like 解析。
- kind 支持 `auto/findings/summary`。
- 缺字段、缺章节、缺锚点均返回非零退出码。

## 9. 安全与性能设计

| 维度 | 设计措施 | 验证方式 |
|---|---|---|
| 安全 | 不执行外部命令，不联网 | 脚本阅读 + 运行 |
| 性能 | 单文件字符串扫描 | dry-run |

## 10. 测试设计

| 测试场景 | 前置条件 | 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| findings 模板校验 | 模板已创建 | 运行 `--kind findings` | 返回 `OK` | dry-run |
| summary 模板校验 | 模板已创建 | 运行 `--kind summary` | 返回 `OK` | dry-run |
| 缺字段 | 构造坏样例 | 删除 frontmatter 字段 | 返回 `ERROR` | 逻辑检查 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细描述 |
|---|---|---|---|
| TASK-RG-02-01 | 创建 | `delivery/skills/review-artifact-protocol/templates/REVIEW-FINDINGS-TEMPLATE.md` | 固化 findings 结构 |
| TASK-RG-02-02 | 创建 | `delivery/skills/review-artifact-protocol/templates/REVIEW-SUMMARY-TEMPLATE.md` | 固化 summary 结构 |
| TASK-RG-02-03 | 创建 | `delivery/skills/review-artifact-protocol/scripts/validate_review_artifact.py` | 实现结构校验 |
| TASK-RG-02-04 | 修改 | `delivery/agents/meta-po.md` | 增加模板 / 脚本入口说明 |

## 12. 风险、难点与预研建议

| 风险 / 难点 | 影响 | 缓解措施 / 预研建议 |
|---|---|---|
| 模板字段漂移 | lane 输出不兼容 | 使用统一模板和脚本约束 |

## 13. 回滚与发布策略

- 发布方式：直接进入 `delivery/`
- 回滚触发条件：模板结构不满足聚合需求
- 回滚动作：回退模板与脚本，并恢复人工校验

## 14. Definition of Done

- [x] 14 个章节全部填写完成
- [x] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [x] `confirmed=false` 时不进入实现
- [x] 人工确认意见已收敛

## 人工确认区

> 已按委托方式确认并进入实现。
