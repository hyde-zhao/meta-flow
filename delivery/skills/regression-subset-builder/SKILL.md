---
name: regression-subset-builder
description: >-
  当问题修复后需要确定最小回归验证范围时使用。
  触发词包括：回归测试、最小回归集、修复验证、回归范围。
  适用场景：问题修复后的验证阶段。
argument-hint: "ISSUE ID 或修复涉及的 artifact 列表"
user-invokable: true
status: active
---

## 目标

从 ISSUE / CR / `FIXES.md` 和 `process/DEVELOPMENT-PLAN.yaml` 中反推受影响的最小 Story / 验证集合，生成 `REGRESSION-TEST-SUBSET.yaml`，用于修复后的精准回归验证。

## 适用范围

- 适用阶段：问题修复后的验证阶段
- 输入：ISSUE / CR / `docs/quality/FIXES.md`（affected_artifacts 字段）、`process/DEVELOPMENT-PLAN.yaml`
- 输出：`REGRESSION-TEST-SUBSET.yaml`

## 前置条件

- [ ] ISSUE 工单已创建且 `affected_artifacts` 字段已填写
- [ ] `process/DEVELOPMENT-PLAN.yaml` 存在且 Story / tasks 中有依赖关系

## 执行约束

- 回归范围策略：
  - `affected-only`：仅包含直接受影响的任务
  - `affected-and-downstream`：包含直接受影响 + 依赖链下游任务（推荐）
  - `full`：全量回归（仅在重大变更时使用）
- 默认使用 `affected-and-downstream` 策略
- 每个回归任务必须标注 `reason`（directly-affected / downstream-dependency / safety-critical）
- 安全关键任务（涉及安全约束验证的）应始终包含在回归集中

## 反推逻辑

1. 从 ISSUE 的 `affected_artifacts` 找到受影响的文件
2. 从 `process/DEVELOPMENT-PLAN.yaml` 找到引用这些文件的 Story / task
3. 找到这些 task 的下游依赖（被 depends_on 引用的任务链）
4. 检查是否有安全关键任务需要额外加入
5. 输出最小任务集合

辅助脚本：`scripts/build_regression_subset.py`（Phase 3 开发）

## Gotchas

- `affected-only` 策略看起来省事，但可能遗漏因依赖传递而实际受影响的下游任务。推荐默认使用 `affected-and-downstream`
- cleanup 阶段的任务通常不需要回归——除非修复本身涉及清理逻辑

## 验收标准

- 输出的 `REGRESSION-TEST-SUBSET.yaml` 格式正确
- `regression_tasks` 列表非空
- 每个任务的 `reason` 字段已填写
- 策略选择有明确理由
- 关联的 ISSUE 和 CR 编号正确
