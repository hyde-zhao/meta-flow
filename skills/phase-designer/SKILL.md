---
name: phase-designer
description: >-
  当需要将需求和场景组织为执行阶段时使用。
  触发词包括：阶段划分、设计阶段、Phase 设计、执行顺序。
  适用场景：工作流计划设计的第一步。
argument-hint: "REQUIREMENTS.md 和 SCENARIOS.yaml 路径"
user-invokable: true
status: active
---

## 目标

根据需求、场景、风险和依赖关系，将执行活动组织为有序阶段（Phase），供后续 Wave 规划消费。

## 适用场景

- Story / 工作流计划设计的第一步
- 需要决定阶段边界、顺序与进入 / 退出条件

## 前置条件

- [ ] `REQUIREMENTS.md` 已确认
- [ ] `SCENARIOS.yaml` 已生成

## 必须读取的输入

- `.meta-workflow/process/REQUIREMENTS.md`
- `.meta-workflow/process/SCENARIOS.yaml`
- 相关约束或平台限制（若存在）

## 知识来源

- 需求优先级、场景类型与依赖关系
- 现有阶段设计规则：前置检查优先、清理阶段兜底

## 执行步骤

1. 按目标、风险和依赖关系划分阶段。
2. 为每个阶段定义目标、顺序和进入 / 退出条件。
3. 将阶段结构写入计划对象，供 Wave 设计继续细化。

## 输出文件 / 输出模板

输出为 `.meta-workflow/process/DEVELOPMENT-PLAN.yaml` 中的阶段结构；不直接依赖模板文件。

## 约束

- 阶段间串行，阶段内任务可交给后续 Wave 规划决定
- 清理 / 收尾阶段不得省略
- 依赖需求与场景内容契约，而非模板可用性

## 验收标准

- [ ] 每个阶段有明确目标与顺序
- [ ] 阶段边界合理，清理阶段存在
- [ ] 全部场景被纳入至少一个阶段

## 不适用边界

- 当前任务只需生成测试场景，不需要阶段设计
- 需求与场景尚未收敛

## Gotchas

- 阶段设计过细会导致后续 Wave 规划碎片化
- 把高风险任务和普通任务混在同一阶段会削弱隔离效果


