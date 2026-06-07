---
status: draft
version: "1.0"
source_story_map: "docs/product/STORY-MAP.md"
source_mvp_scope: "docs/product/MVP-SCOPE.md"
confirmed_by: ""
confirmed_at: ""
---

# Blueprint

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | <date> | meta-se | 初始蓝图 |

## 能力地图

| Capability ID | 能力域 | 用户价值 | 覆盖 Story | Owner Feature |
|---|---|---|---|---|
| CAP-01 | <能力域> | <用户价值> | ST-001 | FEAT-01 |

## Feature / Epic 边界

| Feature ID | 名称 | 负责事项 | 不负责事项 | 拥有数据 | 只读数据 | 禁止依赖 |
|---|---|---|---|---|---|---|
| FEAT-01 | <名称> | <职责> | <非职责> | <data owner> | <read-only data> | <forbidden dependency> |

## 跨 Feature 流程

| Flow ID | 触发 | 参与 Feature | 数据写入 Owner | 失败路径 | 验证入口 |
|---|---|---|---|---|---|
| FLOW-01 | <触发> | FEAT-01 -> FEAT-02 | FEAT-01 | <失败处理> | TEST-MATRIX |

## 共享能力

| Shared ID | 名称 | 使用方 | Owner | 调用方向 | 降级策略 |
|---|---|---|---|---|---|
| SH-01 | <共享能力> | <使用方> | <owner> | <direction> | <fallback> |

## 待确认边界

决策类型只能使用：`scope`、`architecture`、`security`、`implementation`、`runtime_authorization`、`risk_acceptance`、`follow_up_tracking`。

| Decision ID | 决策类型 | 问题 | 推荐方案 | 备选方案 | 推荐 / 备选优劣 | 影响 / 风险 | 回退 / 切换条件 |
|---|---|---|---|---|---|---|---|
| DQ-BP-001 | architecture | <问题> | <推荐> | <备选> | <优劣> | <影响> | <条件> |
