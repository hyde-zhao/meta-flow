---
source_cr: "CR-018"
status: "closed"
created_at: "2026-06-11T19:30:30+08:00"
created_by: "host-orchestrator"
updated_at: "2026-06-11T19:59:32+08:00"
checkpoint_source: "CR-018"
cr_index_path: "process/changes/CR-INDEX.yaml"
---

# CR-018 后续事项跟踪台账

## 目的

本台账记录 CR-018 之后需要分步落地的候选事项。候选项未启动前不得预创建正式 CR 文件；只有用户决定推进某一项时，才在 `process/changes/` 下创建对应正式 CR，并把本台账和 `CR-INDEX.yaml` 中的状态改为 `active`。

本台账不是唯一状态索引。每次新增、启动、关闭、取消或替代候选项后，必须同步 `process/STATE.md.cr_tracking` 与 `process/changes/CR-INDEX.yaml`，并运行或记录跳过 `meta-flow check cr-tracking --project-root .` 的原因。

## 状态字段约定

| 状态 | 含义 | 处理规则 |
|---|---|---|
| `candidate` | 候选，还没启动正式 CR | 保留摘要、触发条件和下一步，不创建正式 CR |
| `active` | 已创建正式 CR，正在推进 | 填写正式 CR 路径、当前门控、阻塞原因和下一步 |
| `blocked` | 已启动但被外部条件阻塞 | 保留正式 CR 路径和阻塞条件 |
| `spike_candidate` | 候选 Spike，还没启动 | 不创建正式 Spike CR，等待用户选择 |
| `converted-to-spike` | 已转为正式 Spike CR | 链接正式 Spike CR 文件 |
| `closed` | 对应正式 CR 已关闭 | 填写关闭证据，例如 CP8 approved 时间 |
| `cancelled` | 明确取消，不再推进 | 保留取消理由，不删除 |
| `superseded` | 被另一个 CR 替代 | 填写替代 CR 路径 |

## 分流总览

| 类别 | 数量 | 阻断当前交付 | 说明 |
|---|---:|---|---|
| 关闭范围 | 6 | 否 | CR-018 基线与 CR-019 至 CR-023 均已预授权实施并关闭 |
| 不授权范围 | 2 | 否 | CR-018 批准不代表授权外部工具、真实凭据、publish、live、生产写入或目标项目写入 |
| 风险接受项 | 0 | 否 | 当前没有要求用户接受风险后放行的事项 |
| 后续 CR 候选项 | 0 | 否 | 候选项已转正式 CR 并关闭 |
| 取消 / deferred 项 | 0 | 否 | 暂无取消项 |

## 后续 CR / Spike 候选索引

| 候选编号 | 标题 | 状态 | 类型 | 优先级 | 影响面 / 冲突键 | 正式 CR 路径 | 相关 active CR / blocked_by / superseded_by | 当前门控 | 阻塞原因 | 下一步 | 来源 |
|---|---|---|---|---:|---|---|---|---|---|---|---|
| CR-019 | workflow eval / prompt bundle schema 与样例工作流基线 | closed | CR | 1 | `evals/contracts/*`; `WORKFLOW-EVAL.yaml`; `PROMPT-BUNDLE.yaml`; generated workflow fixture; docs/design | `process/changes/CR-019.md` | related: `CR-018` | closed | 无 | 已完成 schema、fixture 和 Feature 设计基线 | CR-018 |
| CR-020 | 本地 eval runner 与确定性 grader | closed | CR | 2 | `meta_flow/evals`; run evidence; deterministic fixtures; safety checks | `process/changes/CR-020.md` | related: `CR-019` | closed | 无 | 已完成 `meta-flow eval validate/run/suite-health` | CR-018 |
| CR-021 | CP7 / meta-qa / verification-execution 集成 | closed | CR | 3 | `delivery/agents/meta-qa.md`; `verification-execution`; `docs/quality/*`; `process/evals/runs/*` | `process/changes/CR-021.md` | related: `CR-019`, `CR-020` | closed | 无 | 已完成 eval evidence 消费规则和质量证据 | CR-018 |
| CR-022 | case lifecycle、coverage matrix、failure backlog 与 suite health | closed | CR | 4 | `CASE-REGISTRY.yaml`; `EVAL-COVERAGE-MATRIX.md`; `FAILURE-BACKLOG.md`; suite health summary; regression policy | `process/changes/CR-022.md` | related: `CR-019` | closed | 无 | 已完成 suite health 和 failure backlog | CR-018 |
| CR-023 | CI 策略与 Promptfoo / DeepEval / Langfuse / Garak 可选适配 | closed | CR / Spike | 5 | CI policy; external adapters; trace backend; credential boundary; network authorization | `process/changes/CR-023.md` | related: `CR-020`, `CR-021` | closed | 无 | 已完成本地 CI policy 和 adapter policy；真实外部运行仍未授权 | CR-018 |

## 启动候选 CR 流程

用户决定推进某一候选项时，在当前主进程会话中说明“启动后续 CR”，并给出台账路径、候选编号和目标摘要。host-orchestrator 必须先读取本台账、`STATE.md.active_change`、`STATE.md.cr_tracking`、`process/changes/CR-INDEX.yaml` 和活跃正式 CR，完成冲突预检后，才能创建正式 CR 文件并把状态改为 `active`。

## CR 冲突预检

| 检查项 | 结果 | 证据 | 处理结论 |
|---|---|---|---|
| 是否已有 `STATE.md.active_change` | BLOCKED | `process/STATE.md` 当前指向 `CR-018` | CR-018 未关闭前不得启动 CR-019+ |
| 是否存在未关闭正式 CR | BLOCKED | `process/changes/CR-018.md` status=`open` | 后续候选等待 CR-018 审批 / 关闭或显式并行授权 |
| 正式文档影响面是否重叠 | BLOCKED | CR-018 文档处理决策覆盖规则、状态、QA、验证和 eval 契约 | 默认不得并行推进重叠候选 |
| Story / LLD 批次是否重叠 | BLOCKED | CR-018 设计批次 `CR-018-BASELINE-DESIGN-BATCH` | 后续实现 CR 必须消费该设计批次 |
| 文件 owner 是否冲突 | PASS_WITH_RISK | 当前未创建实现 diff | 启动候选 CR 时按 Story file owner 重新检查 |
| 外部接口 / 安全 / 运行授权是否重叠 | BLOCKED | NA-01 / NA-02 | 外部工具和目标项目写入必须单独授权 |
| `STATE.md.active_change` 是否指向已关闭 CR | PASS | 当前 CR-018 为 open | 无 stale active_change |
| 台账候选与正式 CR 文件是否同步 | PASS_WITH_RISK | 候选项仅在本台账和 CR-INDEX 中登记 | 一致性检查后刷新结果 |

若存在重叠，默认不得并行推进；必须在以下处理方式中选择并记录：合并到现有 CR、保持候选等待、标记 `blocked`、拆分无冲突子集、或标记 `superseded` 并链接替代 CR。

## 状态索引同步

| 对象 | 路径 | 同步要求 | 当前状态 |
|---|---|---|---|
| 运行时状态 | `process/STATE.md.cr_tracking` | 记录 active、blocked、candidate、spike_candidate、stale_status_conflicts | synced |
| CR 索引 | `process/changes/CR-INDEX.yaml` | 记录每个候选项的状态、正式 CR 路径、影响面、blocked_by 和下一步 | synced |
| 一致性检查 | `meta-flow check cr-tracking --project-root .` | 新增台账、启动候选、关闭 CR 或状态冲突修复后执行 | PASS at 2026-06-11T19:59:32+08:00 |

## 不授权范围

| 项目 ID | 范围 | 原因 | 需要未来授权时的动作 | 来源 |
|---|---|---|---|---|
| NA-01 | 外部服务、真实凭据、网络 trace backend、Promptfoo / DeepEval / Langfuse / Garak 真实运行、publish、live、生产写入 | 用户当前只要求完成 CR 写作；CR-018 是治理基线，不是运行授权 | 创建正式 CR / Spike，并在人工门禁中列出 runtime_authorization 决策项 | CR-018 |
| NA-02 | 在任意 production 目标项目中写入 eval assets、修改项目目录、改变发布路径 | production 项目必须先扫描目标项目 README / docs / 交付约定并写入 `STATE.md.delivery_routing` | 在目标项目上下文中创建正式 CR，确认 delivery_routing 和 project_kind 后再写入 | CR-018 |

## 风险接受项

| 项目 ID | 风险 | 接受条件 | 回退 / 切换条件 | 来源 |
|---|---|---|---|---|
| N/A | 当前没有要求用户接受风险后放行的事项 | N/A | N/A | CR-018 |

## 关闭范围

| 项目 ID | 已关闭内容 | 关闭证据 | 来源 |
|---|---|---|---|
| CLOSE-01 | CR-018 治理基线 | `process/changes/CR-018.md` | CR-018 |
| CLOSE-02 | CR-019 schema 与 fixture 基线 | `process/changes/CR-019.md` | CR-018 |
| CLOSE-03 | CR-020 local runner | `process/changes/CR-020.md` | CR-018 |
| CLOSE-04 | CR-021 CP7 eval integration | `process/changes/CR-021.md` | CR-018 |
| CLOSE-05 | CR-022 suite health / failure backlog | `process/changes/CR-022.md` | CR-018 |
| CLOSE-06 | CR-023 CI / optional adapter policy | `process/changes/CR-023.md` | CR-018 |

## 取消 / Deferred 项

| 项目 ID | 内容 | 状态 | 原因 | 可重启条件 | 来源 |
|---|---|---|---|---|---|
| N/A | 当前没有取消或 deferred 项 | N/A | N/A | N/A | CR-018 |
