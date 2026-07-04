---
status: draft
version: "1.0"
feature_id: ""
feature_name: ""
source_blueprint: "docs/design/BLUEPRINT.md"
source_hld: "docs/design/HLD.md"
source_adr: "docs/design/ARCHITECTURE-DECISION.md"
source_matrix: "docs/design/FEATURE-DESIGN-MATRIX.md"
related_stories: []
lld_policy_summary: ""
confirmed_by: ""
confirmed_at: ""
---

# Feature Design: <feature>

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | <date> | meta-dev | 初始 Feature 设计 |

## 摘要

| 项目 | 内容 |
|---|---|
| Feature 目标 | <一句话说明本 Feature 解决什么问题> |
| 推荐方案 | <推荐技术方向> |
| 关键取舍 | <本设计牺牲 / 优化了什么> |
| 下游 Story | STORY-001, STORY-002 |
| LLD 策略 | full-lld / technical-note / waived 的分布摘要 |

## 背景与问题

| 问题 ID | 背景 | 触发场景 | 影响 | 若不设计的风险 |
|---|---|---|---|---|
| P-01 | <context> | UC- / SCN- / REQ- | <impact> | <risk> |

## 上游依据与输入

| 来源 | 路径 / ID | 被本设计消费的内容 |
|---|---|---|
| Blueprint | `docs/design/BLUEPRINT.md` | <Feature 边界 / 数据归属> |
| HLD | `docs/design/HLD.md` | <架构约束> |
| ADR | `docs/design/ARCHITECTURE-DECISION.md` | <关键决策> |
| Feature Matrix | `docs/design/FEATURE-DESIGN-MATRIX.md` | <required / lld_policy 判定> |
| Scenario / Requirement | UC- / SCN- / REQ- | <用户价值与验收依据> |

## 目标与非目标

| 类型 | 内容 | 来源 |
|---|---|---|
| Goal | <目标> | ST- / REQ- / BP- |
| Non-Goal | <非目标> | MVP-SCOPE |

## Feature 边界与相邻对象

| 对象 | 本 Feature 负责 | 不负责 | 相邻 Feature / 模块 | 边界判定依据 |
|---|---|---|---|---|
| <object> | <in-scope> | <out-of-scope> | <neighbor> | BP- / HLD- / ADR- |

## 现有代码位置

| 区域 | 路径 | 当前职责 | 变更方式 |
|---|---|---|---|
| <模块> | <path> | <职责> | create / modify / delete |

## 现状分析

| 维度 | 当前状态 | 缺口 | 约束 |
|---|---|---|---|
| 数据 | <current> | <gap> | <constraint> |
| 接口 | <current> | <gap> | <constraint> |
| 测试 | <current> | <gap> | <constraint> |
| 运维 / 发布 | <current> | <gap> | <constraint> |

## 推荐方案

| 设计点 | 推荐做法 | 理由 | 代价 |
|---|---|---|---|
| <point> | <approach> | <why> | <cost> |

## 方案对比与决策记录

| Decision ID | 方案 | Pros | Cons | Impact Surface | Recommendation | When to switch |
|---|---|---|---|---|---|---|
| DQ-FD-001 | Option A | <pros> | <cons> | <impact> | 推荐 / 备选 | <condition> |
| DQ-FD-001 | Option B | <pros> | <cons> | <impact> | 推荐 / 备选 | <condition> |

## 模块变更

| Module | 变更 | 输入 | 输出 | 失败路径 |
|---|---|---|---|---|
| <module> | <change> | <input> | <output> | <failure> |

## 数据模型与状态

| Object | Owner | 新增 / 修改字段 | 状态变化 | 兼容性 |
|---|---|---|---|---|
| <object> | <owner> | <fields> | <state> | <compat> |

## API / 接口设计

| Interface ID | 调用方 | 被调用方 | 输入契约 | 输出契约 | 错误模型 |
|---|---|---|---|---|---|
| IF-01 | <caller> | <callee> | <input> | <output> | <errors> |

## 关键流程

| Flow ID | 触发条件 | 主流程 | 异常流程 | 输出 / 状态变化 | 观测点 |
|---|---|---|---|---|---|
| FLOW-01 | <trigger> | <happy-path> | <failure-path> | <output> | <log / metric / trace> |

## 人机协作与确认点

| 确认点 | 触发条件 | 需要谁确认 | 推荐方案 | 备选方案 | 不授权项 |
|---|---|---|---|---|---|
| DQ-FD-001 | <condition> | 用户 / PO / SE | <recommendation> | <alternative> | <not-authorized> |

## 异常、失败与降级策略

| Failure ID | 失败条件 | 系统行为 | 用户可见影响 | 恢复 / 回退 | 测试入口 |
|---|---|---|---|---|---|
| F-01 | <condition> | <behavior> | <impact> | <rollback> | TEST-PLAN |

## 权限与安全

| Rule ID | 规则 | 触发条件 | 失败行为 | 测试入口 |
|---|---|---|---|---|
| SEC-01 | <rule> | <condition> | <failure> | TEST-PLAN |

## 测试与验收策略

| 验收对象 | 测试层级 | 覆盖场景 | 自动化方式 | 未自动化原因 / 手工入口 |
|---|---|---|---|---|
| <object> | unit / integration / e2e / manual | SCN-001 | <command> | <reason> |

## 实现顺序

| Step | 内容 | 前置条件 | 输出 | 验证入口 |
|---|---|---|---|---|
| 1 | <step> | <precondition> | <output> | TEST-PLAN |

## Story 拆分建议与 LLD 策略

| Story ID | feature_design_refs | lld_policy.required_level | 触发原因 | 必须进一步设计的问题 | 可用设计证据 |
|---|---|---|---|---|---|
| STORY-001 | docs/features/<feature>/DESIGN.md | full-lld / technical-note / waived | data / security / cross-module / external / concurrency / migration / low-risk | <问题> | LLD / Batch LLD Story 锚点 / Story 技术说明 / waived reason |

## 下游消费契约

| 消费方 | 消费时机 | 输入契约 | 输出 / 状态要求 | 降级策略 |
|---|---|---|---|---|
| story-manager | CP4 前 | Story 拆分建议、`lld_policy` | Story 卡片含 `feature_design_refs` / `lld_policy` | 缺失则 CP4 FAIL |
| lld-designer | CP5 前 | Story + Feature DESIGN / TEST-PLAN / TASKS | full-lld 或 technical-note / waived 证据 | 缺失 required 设计则 blocked |
| meta-qa | CP7 / CP8 | TEST-PLAN、验收策略 | TEST-REPORT / REVIEW 追溯 | 缺失则补测试计划或记录 WAIVED |

## 风险与回退

| Risk ID | 风险 | 影响 | 缓解 | 回退 |
|---|---|---|---|---|
| R-01 | <risk> | <impact> | <mitigation> | <rollback> |
