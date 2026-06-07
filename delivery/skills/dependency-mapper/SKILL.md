---
name: dependency-mapper
description: >-
  当需要建立任务间依赖关系、构建 DAG 依赖图时使用。
  触发词包括：依赖关系、DAG、任务依赖、前置依赖。
  适用场景：工作流计划设计阶段。
argument-hint: "process/DEVELOPMENT-PLAN.yaml（已有 Story / tasks）"
user-invokable: true
status: active
---

## 目标

为 `process/DEVELOPMENT-PLAN.yaml` 中的每个 Story / Task 建立前置依赖关系（`depends_on` 字段）和依赖类型，确保执行顺序正确，并验证依赖图无环路。

## 适用范围

- 适用阶段：计划设计阶段
- 输入：已有 Story / tasks 的 `process/DEVELOPMENT-PLAN.yaml`
- 输出：更新所有 task 的 `depends_on` 字段

## 前置条件

- [ ] `process/DEVELOPMENT-PLAN.yaml` 中 phases、waves、stories / tasks 已定义
- [ ] 每个 task 有唯一 id

## 执行约束

- `depends_on` 是一个 task id 列表，表示"本任务必须在列表中所有任务完成后才能开始"
- 跨 Phase 的依赖是隐式的（Phase 按 order 串行），不需要显式声明
- 同一 Wave 内的任务（parallel=true）不应互相 depends_on
- 依赖图必须是 DAG（有向无环图），不允许循环依赖
- precheck 任务通常是其他所有任务的隐式前置（可不逐一声明，但 Phase 顺序保证即可）

## 依赖类型

| 类型 | 说明 | 示例 |
|------|------|------|
| 数据依赖 | 任务 B 需要任务 A 的输出作为输入 | 配置备份（A）→ 配置修改（B） |
| 顺序依赖 | 任务 B 必须在任务 A 之后执行 | 正向验证（A）→ 负向验证（B） |
| 资源依赖 | 任务 B 需要任务 A 释放资源 | 释放 SSH 会话（A）→ 新建连接（B） |

## DAG 校验

建立依赖关系后，使用以下规则校验：
- 遍历全部 `depends_on` 引用，确保引用的 task id 存在
- 使用拓扑排序检测环路
- 标记孤立任务（无依赖也无被依赖）——它们可能是遗漏

若仓库提供 DAG 校验脚本，可调用脚本辅助；不存在脚本时按 YAML 结构做拓扑校验。

## Gotchas

- cleanup 阶段的任务不应依赖于 positive/negative 阶段的具体任务——因为 cleanup 无论成功失败都应执行。使用 Phase 顺序保证而非 depends_on
- 避免过度声明依赖。如果 Phase 顺序已经保证了 A 在 B 之前，不需要再在 B 的 depends_on 中写 A

## 验收标准

- 所有 `depends_on` 中引用的 task id 都存在
- 依赖图无环路（可用拓扑排序验证）
- 同一 parallel Wave 内的任务无互相依赖
- 无漏网的孤立任务（除非有明确理由）
