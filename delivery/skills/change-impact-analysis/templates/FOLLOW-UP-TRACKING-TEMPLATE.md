---
source_cr: "CR-{id}"
status: "open"
created_at: ""
created_by: "host-orchestrator"
updated_at: ""
checkpoint_source: "CP8"
cr_index_path: "process/changes/CR-INDEX.json"
---

# CR-{id} 后续事项跟踪台账

## 目的

本台账只记录 CP8 或 CR 收敛后需要后续跟踪的候选事项。候选项未启动前不得预创建正式 CR 文件；只有用户决定推进某一项时，才在 `process/changes/` 下创建对应正式 CR，并把本台账中的状态改为 `active`。

本台账不是唯一状态索引。每次新增、启动、关闭、取消或替代候选项后，必须同步 `process/changes/CR-INDEX.json` 与 `process/state/CR-LEDGER.ndjson`，并运行或记录跳过 `meta-flow check cr-tracking` 的原因。`CR-INDEX.yaml` 仅作 legacy read-only fallback。

## 状态字段约定

机器真相源优先使用 `lifecycle_status`、`readiness_status` 和 `gate_status`；`状态` 表格列只作为 legacy / 人读摘要。

| 字段 | 允许值 | 含义 |
|---|---|---|
| `lifecycle_status` | `candidate` / `active` / `blocked` / `closed` / `cancelled` / `superseded` | 候选或正式 CR 的生命周期 |
| `readiness_status` | `ready` / `ready_with_risk` / `not_ready` / `n/a` | 当前交付或验证就绪程度 |
| `gate_status` | `not_started` / `cp2_pending` / `cp3_pending` / `cp5_pending` / `cp7_pending` / `cp8_pending` / `closed` | 当前门禁位置 |

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

## 结构化候选项

> 本 fenced YAML 是台账局部结构，不是 CR 索引真相源；机器 CR 索引优先使用 `process/changes/CR-INDEX.json`，下面的 Markdown 表格只做人读摘要。候选编号未来默认使用 `FU-CR{id}-001`、`SP-CR{id}-001`、`RA-CR{id}-001`，历史 `CR-020` 类编号写入 `legacy_ids`。

```yaml
follow_up_items:
  - id: "FU-CR{id}-001"
    legacy_ids: []
    title: "<候选标题>"
    kind: "implementation-gate"
    lifecycle_status: "candidate"
    readiness_status: "n/a"
    gate_status: "not_started"
    gate_profile: "standard"
    source_cr: "CR-{id}"
    source_decision_id: "CP8-DQ-xx"
    priority: 1
    formal_cr_path: ""
    blocked_by: []
    superseded_by: []
    impact_surface:
      - "<文档 / Story / 文件 owner / 外部接口 / 安全或运行授权>"
    conflict_keys:
      documents: []
      stories: []
      files: []
      external_interfaces: []
      security_runtime: []
      risk_acceptance: []
      source_decisions: []
    authorization_required:
      runtime: false
      credential_read: false
      nas_access: false
      trading_write: false
    next_action: "等待用户选择是否推进"
```

## 分流总览

| 类别 | 数量 | 阻断当前交付 | 说明 |
|---|---:|---|---|
| 关闭范围 | 0 | 否 | 本轮已完成并关闭 |
| 不授权范围 | 0 | 否 | 设计通过不代表授权执行的事项 |
| 风险接受项 | 0 | 否 / 是 | 用户接受风险后放行，必须有回退条件 |
| 后续 CR 候选项 | 0 | 否 | 只维护候选状态，不创建正式 CR |
| 取消 / deferred 项 | 0 | 否 | 保留追溯，不删除 |

## 后续 CR / Spike 候选索引

| 候选编号 | 标题 | 状态 | 类型 | 优先级 | 影响面 / 冲突键 | 正式 CR 路径 | 相关 active CR / blocked_by / superseded_by | 当前门控 | 阻塞原因 | 下一步 | 来源 |
|---|---|---|---|---:|---|---|---|---|---|---|---|
| FU-CR{id}-001 | `<候选标题>` | candidate | CR / Spike | 1 | `<文档 / Story / 文件 owner / 外部接口 / 安全或运行授权>` |  |  | 未启动 |  | 等待用户选择是否推进 | CP8-DQ-xx |

## 启动候选 CR 流程

用户决定推进某一候选项时，在当前主进程会话中说明“启动后续 CR”，并给出台账路径、候选编号和目标摘要。host-orchestrator 必须先读取本台账、`STATE.current.json.active_change`、`process/changes/CR-INDEX.json`、`process/state/CR-LEDGER.ndjson` 和活跃正式 CR，完成冲突预检后，才能创建正式 CR 文件并把状态改为 `active`。`CR-INDEX.yaml` 若存在，只能作为 legacy read-only fallback。

## CR 冲突预检

| 检查项 | 结果 | 证据 | 处理结论 |
|---|---|---|---|
| 是否已有 `STATE.current.json.active_change` | PASS / BLOCKED | `process/STATE.md` |  |
| 是否存在未关闭正式 CR | PASS / BLOCKED | `process/changes/CR-*.md` |  |
| 正式文档影响面是否重叠 | PASS / BLOCKED | 文档处理决策 |  |
| Story / LLD 批次是否重叠 | PASS / BLOCKED | Story / CR 影响分析 |  |
| 文件 owner 是否冲突 | PASS / BLOCKED | Story file_ownership / CR 影响分析 |  |
| 外部接口 / 安全 / 运行授权是否重叠 | PASS / BLOCKED | Decision Brief / CR |  |
| `STATE.current.json.active_change` 是否指向已关闭 CR | PASS / BLOCKED | `meta-flow check cr-tracking` |  |
| 台账候选与正式 CR 文件是否同步 | PASS / BLOCKED | `meta-flow check cr-tracking` |  |

若存在重叠，默认不得并行推进；必须在以下处理方式中选择并记录：合并到现有 CR、保持候选等待、标记 `blocked`、拆分无冲突子集、或标记 `superseded` 并链接替代 CR。

## 状态索引同步

| 对象 | 路径 | 同步要求 | 当前状态 |
|---|---|---|---|
| 运行时状态 | `process/changes/CR-INDEX.json` 与 `process/state/CR-LEDGER.ndjson` | 记录 active、blocked、candidate、spike_candidate、stale_status_conflicts | pending |
| CR 索引 | `process/changes/CR-INDEX.json` | 记录每个候选项的状态、正式 CR 路径、影响面、blocked_by 和下一步 | pending |
| 一致性检查 | `meta-flow check cr-tracking --project-root .` | 新增台账、启动候选、关闭 CR 或状态冲突修复后执行 | pending |

## 不授权范围

| 项目 ID | 范围 | 原因 | 需要未来授权时的动作 | 来源 |
|---|---|---|---|---|
| NA-01 | `<真实运行 / 凭据 / publish / live / 外部写入等>` | `<为什么本轮不授权>` | `<创建正式 CR 或重新发起人工门禁>` | CP8-DQ-xx |

## 风险接受项

| 项目 ID | 风险 | 接受条件 | 回退 / 切换条件 | 来源 |
|---|---|---|---|---|
| RA-01 | `<风险描述>` | `<用户接受条件>` | `<回退条件>` | CP8-DQ-xx |

## 关闭范围

| 项目 ID | 已关闭内容 | 关闭证据 | 来源 |
|---|---|---|---|
| CLOSE-01 | `<已完成内容>` | `<CP8 / 验证 / 文档路径>` | CP8 |

## 取消 / Deferred 项

| 项目 ID | 内容 | 状态 | 原因 | 可重启条件 | 来源 |
|---|---|---|---|---|---|
| DEF-01 | `<取消或延后内容>` | cancelled / deferred | `<原因>` | `<条件>` | CP8-DQ-xx |
