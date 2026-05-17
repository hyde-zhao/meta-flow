---
name: wave-planner
description: >-
  当需要决定哪些任务可以并行执行、哪些必须串行时使用。
  触发词包括：并行分组、Wave 划分、并行计划、任务编排。
  适用场景：工作流计划设计阶段，Phase 划分之后。
argument-hint: "DEVELOPMENT-PLAN.yaml、Story 依赖图、文件影响范围"
user-invokable: true
status: draft
---

## 目标

在每个 Phase 内部划分 Story 调度批次，决定哪些 Story 可以并行写 LLD、哪些 Story 可以并行开发、哪些必须串行。

## 适用范围

- 适用阶段：story-planning，phase-designer 和 dependency-mapper 之后
- 输入：已有 phases / Story 草案的 `DEVELOPMENT-PLAN.yaml`、Story 依赖图、文件影响范围
- 输出：更新 `DEVELOPMENT-PLAN.yaml` 中的 waves、parallel policy、dependency gates 和 file ownership

## 前置条件

- [ ] Story 列表已存在，且每个 Story 有稳定 ID、标题、初步输出文件
- [ ] `depends_on` 已由 `dependency-mapper` 生成，且 `dag-validator` 可验证无环
- [ ] Story 的文件影响范围可判定，至少区分 primary / shared / forbidden

## 执行约束

- LLD 写作并行条件：
  1. HLD / ADR 已确认
  2. Story 边界稳定，输出 LLD 文件唯一
  3. 上游依赖不会阻止设计提前展开；`runtime` 依赖必须在 LLD 中标记运行时风险
  4. 并发数不超过 `parallel_policy.max_parallel_lld`，默认 3
- 开发并行条件：
  1. Story LLD confirmed=true
  2. `contract` 依赖的上游接口已冻结
  3. `runtime` 依赖默认要求上游 `verified`
  4. `file-conflict` 依赖不得并行开发
  5. `file_ownership.primary` 不与其他 `dev_running` Story 重叠
  6. 并发数不超过 `parallel_policy.max_parallel_dev`，默认 2
- 验证并行条件：
  1. Story 进入 `ready-for-verification`
  2. 验证资源不冲突
  3. 并发数不超过 `parallel_policy.max_parallel_qa`，默认 2
- Wave 是调度分组，不是唯一门控；真正门控以 Story DAG、依赖类型和文件所有权为准

## 并行安全判定

| Story A / B 关系 | LLD 可并行 | 开发可并行 | 原因 |
|------------------|------------|------------|------|
| 无依赖，primary 文件不重叠 | 是 | 是 | 无顺序和文件冲突 |
| `contract` 依赖，接口已冻结 | 是 | 是 | 可基于冻结契约并行实现 |
| `runtime` 依赖 | 是 | 默认否 | 可提前设计，但开发需等待上游 verified |
| `file-conflict` 依赖 | 是 | 否 | LLD 可写合并策略，开发必须串行 |
| shared 文件无 `merge_owner` | 是 | 否 | 缺少合并责任人 |
| 修改同一 schema / contract | 纳入同一 LLD 设计批次确认 | 否 | 需先收敛契约 |

## 输出字段

`DEVELOPMENT-PLAN.yaml` 应包含：

```yaml
parallel_policy:
  max_parallel_lld: 3
  max_parallel_dev: 2
  max_parallel_qa: 2
waves:
  - id: W1
    parallel_lld: true
    parallel_dev: true
    stories:
      - id: STORY-001
        depends_on: []
        file_ownership:
          primary: []
          shared: []
          merge_owner: ""
          forbidden: []
        lld_gate:
          required_inputs: ["HLD", "ADR", "Story"]
        dev_gate:
          lld_confirmed: true
          dependencies_satisfied: true
          file_conflict_free: true
```

## Gotchas

- LLD 并行不是开发并行；`runtime` 依赖可以提前写 LLD，但不能默认提前开发
- 同一 Wave 内也可能因 shared 文件、schema 或 contract 冲突而必须串行开发
- 如果两个 Story 都要修改同一公共契约，优先拆出独立 contract Story，再让下游按 `contract` 依赖并行
- 并行数量是上限，不是目标；上下文过大、验证资源不足或用户要求保守时应降低并发

## 验收标准

- 每个 Story 的依赖类型可解释，且 DAG 无环
- `parallel_lld` / `parallel_dev` 的判定有依赖和文件所有权依据
- `max_parallel_lld`、`max_parallel_dev`、`max_parallel_qa` 已给出默认值或项目覆盖值
- shared 文件均有 `merge_owner` 或被判定为串行
- `runtime` 依赖默认不会进入 `dev_ready`
