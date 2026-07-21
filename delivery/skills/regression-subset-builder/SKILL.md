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


## vNext 过程引用契约

- `process/...` 是过程仓逻辑引用，不是发布仓中的相对物理路径。
- 首次文件系统 I/O 前必须调用 `meta-flow project resolve-ref --project-root <release-root> --logical-ref <process/...> --format json`。
- 只可瞬时使用成功 JSON 中的 `resolved_path`；不得把绝对路径写入治理文件、Prompt 产物或 Git。
- 命令以退出码 2 返回 BLOCKED 时必须停止；不得自行拼 sibling、去掉 `process/`、恢复软链接或回退 legacy。
- legacy-only 操作必须交还 Host Orchestrator，并使用独立 typed authorization；本 Skill 不构造 legacy capability。

## 目标

从 ISSUE / CR / `FIXES.md` 和 `process/DEVELOPMENT-PLAN.yaml` 中反推受影响的最小 Story / 验证集合，生成 `REGRESSION-TEST-SUBSET.yaml`，用于修复后的精准回归验证。

## 适用范围

- 适用阶段：问题修复后的验证阶段
- 输入：ISSUE / CR / `docs/quality/FIXES.md`（affected_artifacts 字段）、`process/DEVELOPMENT-PLAN.yaml`
- 输出：`REGRESSION-TEST-SUBSET.yaml`

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
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
