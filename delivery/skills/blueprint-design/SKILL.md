---
name: blueprint-design
description: >-
  当 Story Map 与 MVP 范围已确认，需要定义 Feature / Epic 边界、能力地图、领域对象、
  数据归属和依赖方向时使用。触发词包括：蓝图设计、Feature 边界、能力地图、领域建模、依赖地图。
  适用场景：产品规划完成后、系统架构或 Feature 详细设计前。
argument-hint: "STORY-MAP.md、MVP-SCOPE.md 和现有系统结构"
user-invokable: true
status: active
---

## 目标

把产品规划产物转化为跨 Feature / Epic 的工程蓝图，输出 `BLUEPRINT.md`、`DOMAIN-MAP.md` 和 `DEPENDENCY-MAP.md`，为后续架构设计与 Feature 实现设计提供边界。

## 适用场景

- 多个 Feature / Epic 之间存在能力边界、数据归属或依赖方向问题。
- 需要先定义领域对象和共享能力，再写系统架构或 Feature 设计。
- 当前需求容易被实现代理拆成文件任务，缺少产品能力层边界。

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] `docs/product/STORY-MAP.md` 已生成。
- [ ] `docs/product/MVP-SCOPE.md` 已生成，且关键范围决策已分类。
- [ ] 目标项目现有结构或交付出口已确认。

## 必须读取的输入

- `docs/product/STORY-MAP.md`
- `docs/product/MVP-SCOPE.md`
- `docs/product/RELEASE-SLICES.md`（若存在）
- 目标项目 README / docs / 现有代码结构摘要（若适用）
- 活跃 `process/changes/CR-*.md`（若本轮由变更触发）

## 知识来源

- `skills/blueprint-design/templates/BLUEPRINT-TEMPLATE.md`
- `skills/blueprint-design/templates/DOMAIN-MAP-TEMPLATE.md`
- `skills/blueprint-design/templates/DEPENDENCY-MAP-TEMPLATE.md`

## 执行步骤

1. 从 Story Map 中聚合产品能力域和候选 Feature / Epic。
2. 为每个 Feature 定义职责、非职责、拥有数据、只读数据和禁止依赖。
3. 抽取领域对象、状态、规则和术语，输出 `DOMAIN-MAP.md`。
4. 建立 Feature、模块、服务或交付物之间的依赖图，标注允许方向和禁止方向。
5. 对需要用户确认的边界、数据归属、安全或共享能力问题，写入人工决策项。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 产品工程蓝图 | `docs/design/BLUEPRINT.md` | `skills/blueprint-design/templates/BLUEPRINT-TEMPLATE.md` |
| 领域地图 | `docs/design/DOMAIN-MAP.md` | `skills/blueprint-design/templates/DOMAIN-MAP-TEMPLATE.md` |
| 依赖地图 | `docs/design/DEPENDENCY-MAP.md` | `skills/blueprint-design/templates/DEPENDENCY-MAP-TEMPLATE.md` |

## 约束

- 不深入函数级实现，不替代 `implementation-design` 或 Story LLD。
- 不重新定义产品范围；范围变化必须回到 `MVP-SCOPE.md` 或 CR。
- 数据归属必须唯一；共享数据必须说明 owner 与写入规则。
- 禁止依赖必须显式写出原因和违反后的风险。

## 验收标准

- [ ] 每个 Feature / Epic 有职责、非职责和数据归属。
- [ ] 领域对象、状态和关键业务规则可追溯到 Story 或场景。
- [ ] 依赖图无明显循环，且标注允许 / 禁止方向。
- [ ] 待确认边界进入人工决策清单。

## 不适用边界

- 单一小改动，不存在跨 Feature 边界或数据归属问题。
- 当前阶段仍在澄清用户场景。
- 当前任务只需要写单个 Story LLD。

## Gotchas

- 蓝图不是架构图；它先回答产品能力和数据归属，再让架构设计决定技术结构。
- 多个 Feature 同时拥有同一数据是后续耦合和测试失真的高风险信号。
- 共享能力必须说明调用方向和写权限，否则容易被实现阶段扩成隐式平台层。
