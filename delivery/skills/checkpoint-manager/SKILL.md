---
name: checkpoint-manager
description: >-
  当需要创建、执行、记录或审查 meta-flow 的 CP0-CP8 检查点时使用。
  每个检查点都必须包含 Entry Criteria、Checklist、Exit Criteria、Deliverables；
  自动检查点必须写检查结果，人工检查点必须生成可填写的人工审查稿。
argument-hint: "checkpoint_id、目标阶段、Story ID 或检查对象路径"
user-invokable: true
status: active
---

# checkpoint-manager

## 目标

为 meta-flow 提供统一检查点契约，覆盖：

- 自动检查点：执行检查并写入检查结果。
- 自动预检 + 人工检查点：先写自动预检结果，再生成供用户审查的 checklist 文件。
- Story 级滚动检查点：按 Story 独立记录 LLD、编码完成和验证完成结果。
- 关键决策门控：CP2 / CP3 / CP5 / CP8 生成人工审查稿和 Decision Brief；CP4 只生成自动预检并汇入 CP5。
- 上下文门控：CP2 / CP3 / CP5 / CP6 / CP7 / CP8 必须检查对应 `process/context/*-CONTEXT.yaml`，或记录 `N/A` / `WAIVED` / `BLOCKED` 原因。

本 Skill 必须遵守 `delivery/rules/AGENT-SKILL-CONTRACT.md`：CP 机器真相源优先使用 result JSON、evidence index、ledger 和 context refs；Markdown 只作为人类摘要或人工门禁入口。

所有检查点必须采用 IPD 风格的四段结构：

1. Entry Criteria
2. Checklist
3. Exit Criteria
4. Deliverables

## 文件路径约定

| 类型 | 路径 | 说明 |
|---|---|---|
| 机器检查结果 | `process/checks/CP{n}-{slug}.result.json` | CP 检查机器真相源，必须符合 `schemas/CP-RESULT.schema.json`，可用 `meta-flow cp result-check` 校验 |
| 人类检查摘要 | `process/checks/CP{n}-{slug}.summary.md` | 由 result JSON 渲染的人类摘要，可用 `meta-flow cp render-summary` 生成 |
| 自动检查结果 | `process/checks/CP{n}-{slug}.md` | 由 agent 填写，必须包含逐项 PASS / FAIL / N/A / WAIVED |
| 讨论日志 | `process/discussions/CP{n}-*-DISCUSSION-LOG.md` | CP2 / CP3 人类审计与恢复日志；不替代正式产物 |
| 讨论恢复点 | `process/checks/CP{n}-DISCUSSION-CHECKPOINT.json` | CP2 / CP3 中断恢复状态；缺失时自动检查必须说明 N/A 或 blocked 原因 |
| 人工审查稿 | `process/checkpoints/CP{n}-{slug}.md` | 由 host-orchestrator 发起，必须包含 checklist、自动预检摘要、人工审查结果区 |
| Story 设计证据人工审查稿 | `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` | 全部目标 Story 的完整 LLD / 技术说明 / waived 证据统一确认 |
| Story 编码完成结果 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` | meta-dev 自检结果，必须包含 Agent Dispatch Evidence |
| Story 验证完成结果 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` | meta-qa 验证结果，必须包含 Agent Dispatch Evidence |
| 阶段上下文胶囊 | `process/context/CP*-*-CONTEXT.yaml` | 默认读取入口；checkpoint 记录其状态和读取扩展理由 |
| Story Context Contract | `process/context/stories/*.json` | Story 级 CP6 / CP7 默认读取入口 |
| Evidence Index | `process/evidence/*.index.json` | CP6 / CP7 默认证据入口，避免复制完整日志和实现正文 |
| Story Return Packet | `process/returns/*.return.json` | Story 实现 / 验证返回结果，供 CP result 消费 |
| Checkpoint Ledger | `process/state/CHECKPOINT-LEDGER.ndjson` | 每个 CP result 追加一行 `checkpoint_result` 事件 |
| Handoff Ledger | `process/state/HANDOFF-LEDGER.ndjson` | 每次阶段 / Story 交接追加一行 handoff 事件 |
| Agent Dispatch Ledger | `process/state/AGENT-DISPATCH-LEDGER.ndjson` | 每次真实子 agent 调度追加一行 dispatch 事件 |
| Failure Routing Policy | `process/policies/FAILURE-ROUTING.json` | `route_on_fail` 的机器枚举、creates / updates / invalidates / next_allowed_stage |
| Waiver Policy | `process/policies/WAIVER-POLICY.json` | waiver 的 scope / expiry / approval_ref / non-waivable 规则 |

`process/checks/` 属于运行态检查证据；`process/checkpoints/` 属于人工确认态文件。人工审查时，host-orchestrator 必须在用户提示中给出具体 `process/checkpoints/...` 路径。CP4 不再生成独立人工审查稿；其自动预检摘要必须写入 CP5 人工审查稿。

所有 `process/*` 检查点路径都必须先经过 process 路由健康检查。外置模式下，CP0 前必须存在 `<project-root>/process -> <artifact-root>/process/<project-name>` 软链接、`process/.meta-flow-process.yaml` 和与之匹配的 `STATE.md.artifact_routing`；路由记录必须使用锚点 + 相对路径，不得写入设备相关绝对路径：`artifact_root` 相对 `project_root`，`project_process_root` 相对 `artifact_root`，`link_path` 相对 `project_root`。缺失、断链、项目名不匹配或路由冲突时，检查点结论只能是 `BLOCKED`。

## 结果状态

检查项状态只允许使用：

| 状态 | 含义 |
|---|---|
| `PASS` | 检查通过，证据充分 |
| `FAIL` | 检查失败，必须说明阻断原因 |
| `N/A` | 当前对象不适用，必须说明理由 |
| `WAIVED` | 已知未完全满足，但经人工接受风险，必须写明接受人和原因 |

检查点结论只允许使用：

| 结论 | 含义 |
|---|---|
| `PASS` | 满足出口条件，可推进 |
| `FAIL` | 不满足出口条件，不可推进 |
| `BLOCKED` | 缺少输入或存在阻断，需回退或补充 |
| `WAIVED` | 人工接受风险后放行 |

自动检查点存在任一 `FAIL` 且未被 `WAIVED` 时，结论必须为 `FAIL` 或 `BLOCKED`，不得进入人工确认。

失败项不能只写自然语言处理意见。`BLOCKER` / `HIGH` 且状态为 `FAIL` / `BLOCKED` 的检查项必须设置 `route_on_fail`，且只能使用：

```text
rework_same_story
reopen_cp5_design
require_user_decision
create_followup_candidate
escalate_runtime_high_risk
block_release
waive_with_risk_acceptance
```

每个 route 的副作用由 `process/policies/FAILURE-ROUTING.json` 定义，至少包含 `creates`、`updates`、`invalidates` 和 `next_allowed_stage`。检查命令为：

```bash
meta-flow failure policy-check --project-root .
meta-flow failure route-check --result process/checks/CP7-STORY.result.json --project-root .
meta-flow check failure-routing --result process/checks/CP7-STORY.result.json --project-root .
```

`WAIVED` 不是万能通过。每个 `WAIVED` item 必须有 `waiver_ref`，并在 result `waivers[]` 中提供包含 `waiver_id`、`applies_to`、`scope`、`expires_at`、`approval_ref` 和 `forces_release_status` 的 waiver record。以下事项不可豁免：未授权 runtime access、credential / secret exposure、缺少真实 dispatch evidence、runtime-high-risk forbidden path、缺少 runtime-high-risk human gate、缺少 deny-default read expansion log、证据路径不存在、高风险 forbidden path、未授权或 fixture-only 能力被写成 runtime-ready / implemented。检查命令为：

```bash
meta-flow waiver policy-check --project-root .
meta-flow waiver check --result process/checks/CP8-DELIVERY.result.json --project-root .
meta-flow check waiver-policy --result process/checks/CP8-DELIVERY.result.json --project-root .
```

CP7 是验证完成滚动门，允许使用更细的路由结论：`PASS`、`PASS_WITH_RISK`、`WAIVED`、`NEEDS_REWORK`、`NEEDS_DESIGN_CLARIFICATION`、`BLOCKED`。其中 `PASS_WITH_RISK` 可推进但必须汇入 CP8 风险接受输入；`NEEDS_REWORK` 路由回 meta-dev；`NEEDS_DESIGN_CLARIFICATION` 路由回 meta-se / host-orchestrator；`BLOCKED` 停止推进。

## CP Result Schema

CP 检查应优先产出机器可读 `*.result.json`，Markdown 只作为摘要或人工审查入口。`*.result.json` 至少包含：

```json
{
  "schema_version": 1,
  "checkpoint": "CP6",
  "checkpoint_id": "CP6-STORY-CR123-S01",
  "story_id": "STORY-CR123-S01",
  "cr_id": "CR-123",
  "context_ref": "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
  "dispatch_refs": ["ADE-0001"],
  "evidence_ref": "process/evidence/STORY-CR123-S01.CP6.index.json",
  "items": [
    {
      "id": "CP6-01",
      "category": "implementation",
      "name": "Implementation matches Story Context Contract",
      "status": "PASS",
      "severity": "BLOCKER",
      "evidence_refs": ["process/evidence/STORY-CR123-S01.CP6.index.json#changed_files"],
      "owner": "meta-dev",
      "route_on_fail": "rework_same_story",
      "waiver_ref": null,
      "notes": ""
    }
  ],
  "blockers": [],
  "waivers": [],
  "read_expansion_refs": [],
  "decision": "PASS",
  "next_route": "CP7"
}
```

检查命令：

```bash
meta-flow cp result-check --result process/checks/CP6-STORY-CR123-S01.result.json --project-root .
meta-flow cp render-summary --result process/checks/CP6-STORY-CR123-S01.result.json
meta-flow cp ledger-append --result process/checks/CP6-STORY-CR123-S01.result.json --project-root .
meta-flow event check --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint
meta-flow failure route-check --result process/checks/CP6-STORY-CR123-S01.result.json --project-root .
meta-flow waiver check --result process/checks/CP6-STORY-CR123-S01.result.json --project-root .
```

CP6 / CP7 的 result JSON 必须包含 `story_id`、`context_ref`、`dispatch_refs` 和 `evidence_ref`。存在 blocker 或未豁免的高严重度失败时，`decision` 不得为 `PASS` / `PASS_WITH_RISK`。

CP6 / CP7 不得默认把完整 Story LLD、完整 IMPLEMENTATION、完整 TEST-REPORT、完整 REVIEW、完整 diff 或完整 agent transcript 复制进 Markdown 检查文件；只写 `context_ref`、`return_packet_ref`、`evidence_ref`、`dispatch_refs`、检查项结论和必要的一句话摘要。需要审计全文时，记录 `full_doc_read_reason`。

## 通用检查结果模板

自动检查结果文件必须使用以下结构：

```markdown
---
checkpoint_id: "CP{n}"
checkpoint_name: ""
type: "auto | auto_precheck | rolling_auto | batch_auto_then_manual"
status: "PASS | FAIL | BLOCKED | WAIVED"
owner: ""
created_at: ""
checked_at: ""
target:
  phase: ""
  story_id: ""
  artifacts: []
manual_checkpoint: ""
---

# CP{n} {检查点名称} 检查结果

## Entry Criteria

| 条目 | 状态 | 证据 | 说明 |
|---|---|---|---|
|  | PASS |  |  |

## Checklist

| # | 检查项 | 状态 | 证据 | 处理意见 |
|---|---|---|---|---|
| 1 |  | PASS |  |  |

## Exit Criteria

| 条目 | 状态 | 证据 | 说明 |
|---|---|---|---|
|  | PASS |  |  |

## Deliverables

| 交付物 | 路径 | 状态 | 说明 |
|---|---|---|---|
|  |  | PASS |  |

## 结论

- 结论：`PASS | FAIL | BLOCKED | WAIVED`（CP7 可使用 `PASS | PASS_WITH_RISK | WAIVED | NEEDS_REWORK | NEEDS_DESIGN_CLARIFICATION | BLOCKED`）
- 阻断项：
- 豁免项：
- 下一步：
```

## 通用人工审查稿模板

人工检查点必须使用以下结构：

```markdown
---
checkpoint_id: "CP{n}"
checkpoint_name: ""
type: "manual | auto_then_manual | rolling_auto_then_manual | batch_auto_then_manual"
status: "pending | approved | changes_requested | rejected"
owner: "host-orchestrator"
created_at: ""
reviewed_by: ""
reviewed_at: ""
auto_check_result: ""
target:
  phase: ""
  story_id: ""
  artifacts: []
---

# CP{n} {检查点名称} 人工审查

## 自动预检摘要

| 预检文件 | 结论 | 阻断项 | 说明 |
|---|---|---|---|
| `process/checks/...` | PASS | 0 |  |

## Decision Brief

### 审批者摘要

| 字段 | 内容 |
|---|---|
| 本次确认服务的整体目标 | `<用一句话说明本检查点 / CR / 批次服务的用户目标>` |
| 推荐动作 | `approve / 修改 / reject` 及推荐理由 |
| approve 后会发生什么 | `<进入下一阶段、启动哪些实现、关闭哪些范围或接受哪些风险>` |
| approve 不授权什么 | `<真实运行 / 凭据 / 外部写入 / publish / live / production write 等必须单独授权>` |
| 不确认会阻塞什么 | `<阻塞阶段、CR、Story、发布或后续验证>` |

### Context Capsule Summary

| 字段 | 内容 |
|---|---|
| capsule 路径 | `process/context/CP*-*-CONTEXT.yaml` |
| capsule 状态 | `ready / blocked / waived / missing` |
| read_profile | `minimal / compact / full` |
| 默认读取策略 | 先读 capsule；仅在缺失、冲突、字段不足、人工审计或深度评审时读取完整文档 |
| 全文档读取扩展 | `<0/N 次；逐项说明 reason>` |
| 缺失 / waived 理由 | `<若无 capsule，必须说明>` |

### Decision Collection Coverage

| 来源 | 路径 / 对象 | 扫描状态 | 候选问题数 | 纳入待决策数 | 分类 / N/A 原因 |
|---|---|---:|---:|---:|---|
| STATE pending queue | `STATE.md.human_gate_decisions.pending_human_decisions[]` | scanned / missing / n/a | 0 | 0 |  |
| 委托 Agent 交还摘要 | `process/handoffs/*RETURN-SUMMARY.md` | scanned / missing / n/a | 0 | 0 |  |
| 自动预检结果 | `process/checks/CP*.md` | scanned / missing / n/a | 0 | 0 |  |
| discussion log / checkpoint | `process/discussions/*` / `process/checks/*DISCUSSION-CHECKPOINT.json` | scanned / missing / n/a | 0 | 0 |  |
| 下游正式产物 | `HLD.md` / `LLD` / `REVIEW.md` / `FIXES.md` / release docs | scanned / missing / n/a | 0 | 0 |  |
| 用户显式选择题 | 当前对话 / REQUEST / CR | scanned / missing / n/a | 0 | 0 |  |

> 发起人工确认前必须证明所有适用来源已扫描。若某来源缺失或 N/A，必须写明原因；不得让用户再打开长文档自行查找未收集的问题。

### 决策分层

| 分类 | 数量 | 处理方式 |
|---|---:|---|
| 必须用户决策 | 0 | 进入下方待人工决策清单 |
| 高风险策略确认 | 0 | 涉及 runtime、凭据、外部写入、publish、live、production write 时必须显式展示 |
| agent 默认处理 | 0 | 低风险、可逆、局部实现细节由 agent 采用推荐默认并留审计摘要 |
| 仅审计记录 | 0 | 已按项目规则处理且不需要用户拍板，只保留证据路径 |

### 待人工决策清单

| 决策 ID | 决策类型 | 待确认问题 | 推荐方案 | 备选方案 | 优劣分析 | 影响 / 风险 | 回退 / 切换条件 |
|---|---|---|---|---|---|---|---|
| CP{n}-DQ-01 | `scope / architecture / security / implementation / runtime_authorization / risk_acceptance / follow_up_tracking` | `<说明需要用户决定什么、背景、触发条件和影响范围>` | `<1 个推荐方案；用户回复 approve 时默认接受>` | `<至少 1 个可执行备选方案，优先 2 个；不得写“无备选”>` | `<分别说明推荐和备选的优势、代价、适用条件>` | `<用户价值 / 复杂度 / 可验证性 / 维护 / 平台 / 安全权限 / 交付影响>` | `<回退阶段、Story 状态或切换条件>` |

| 字段 | 内容 |
|---|---|
| 推荐决策 | `approve / 修改: <具体修改点> / reject` 及理由 |
| 备选方案 | 至少 1 个可执行备选，优先 2 个；不得写“无备选”，治理备选可为暂缓确认 / 保持当前基线 / 回退上游 / 转 Spike |
| 影响维度 | 用户价值、实现复杂度、可验证性、维护成本、平台兼容、安全 / 权限、交付影响 |
| 优劣分析 | 各候选方案的优势、代价、适用条件 |
| 风险与回退 | 风险等级、接受条件、回退阶段或 Story 状态 |
| 用户需决策事项 | 本轮必须由用户决定的事项；必须逐项引用上方决策 ID |

### CP2 / CP3 / CP5 / CP8 追加 Decision Brief 字段

| 检查点 | 必须追加内容 |
|---|---|
| CP2 | 用户真实意图、场景覆盖、认知盲区补充、Scenario Gray Areas 处理结果、Deferred Ideas、用户选择影响、回退方式、discussion log / checkpoint 路径或 N/A 原因 |
| CP3 | 候选架构适用条件、优化项、牺牲项、影响面、切换条件、Use Case → Architecture Traceability、关键场景模拟结果、未决风险、discussion log / checkpoint 路径或 N/A 原因 |
| CP5 | 设计证据类型分布、LLD clarification queue 收敛状态、已回答问题、转 OPEN / Spike 的问题、未回答阻断项为 0 的证据、跨 Story 契约、文件 owner、merge order |
| CP8 | 交付范围、安装验证、文档缺口、遗留风险、风险接受项、推荐处理方案、至少 1 个备选处理方案、回退方式 |

### CP8 后续跟踪分流表

| 分流类别 | 项目 ID | 状态 | 处理方式 | 台账 / CR 路径 | 说明 |
|---|---|---|---|---|---|
| 关闭范围 | CLOSE-01 | closed | 本轮交付内关闭 | `process/checkpoints/CP8-...md` |  |
| 不授权范围 | NA-01 | not-authorized | 不进入本轮执行授权 | `process/checkpoints/CP8-...md` | 真实运行、凭据、publish、live 等必须独立列出 |
| 风险接受项 | RA-01 | accepted-risk | 用户接受风险后放行 | `process/checkpoints/CP8-...md` | 必须有回退条件 |
| 后续 CR 候选项 | CR-020 | candidate | 保留在 follow-up tracking 台账，暂不创建正式 CR 文件 | `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md` | 启动时再转 active |
| 取消 / deferred 项 | DEF-01 | cancelled/deferred | 不进入当前范围 | `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md` | 不删除，保留追溯 |

## Entry Criteria

| 条目 | 状态 | 证据 | 审查意见 |
|---|---|---|---|
|  | 待审查 |  |  |

## Checklist

| # | 检查项 | 审查结果 | 证据 | 审查意见 |
|---|---|---|---|---|
| 1 |  | 待审查 |  |  |

## Exit Criteria

| 条目 | 审查结果 | 证据 | 审查意见 |
|---|---|---|---|
|  | 待审查 |  |  |

## Deliverables

| 交付物 | 路径 | 审查结果 | 审查意见 |
|---|---|---|---|
|  |  | 待审查 |  |

## 人工审查结果

- 结论：`approved | changes_requested | rejected`
- 审查人：
- 审查时间：
- 修改意见：
- 风险接受项：
```

host-orchestrator 发起人工检查时必须提示：

```text
请审查：process/checkpoints/CP{n}-{slug}.md
自动预检结论：PASS / WAIVED
上下文胶囊：process/context/CP{n}-*-CONTEXT.yaml（read_profile=<minimal|compact|full>，完整来源见 checklist）
审批者摘要：
- 本次确认服务的整体目标：...
- 推荐动作：approve / 修改 / reject
- approve 后会发生什么：...
- approve 不授权什么：...
- 不确认会阻塞什么：...
本轮待人工决策项：N
决策收集覆盖：已扫描 <S> 个来源，发现候选问题 <C> 个，纳入待决策 <D> 个；N/A / 缺失来源 <M> 个，原因见 checklist 的 Decision Collection Coverage。
决策分层：
- 必须用户决策：N
- 高风险策略确认：M
- agent 默认处理：K
- 仅审计记录：A
如果你回复 approve，表示你接受以下 N 项推荐方案，不表示授权以下 M 项禁止操作。
待人工决策清单：
| 决策 ID | 决策类型 | 待确认问题 | 推荐方案 | 备选方案 | 优劣摘要 | 影响 / 风险 |
|---|---|---|---|---|---|---|
| CP{n}-DQ-01 | scope | ... | ... | ... | ... | ... |

不授权项：
- ...

该文件包含本检查点的 Entry Criteria、Checklist、Exit Criteria、Deliverables、自动预检摘要、Decision Brief、待人工决策清单和人工审查结果区。
回复 `approve` 表示接受上表全部推荐方案；如需调整，请用 `修改: <具体修改点>` 指明决策 ID 和修改内容。
审查后请在“人工审查结果”中填写结论，也可以直接回复以下任一整行：
approve
修改: <具体修改点>
reject
```

### Decision Brief 压缩策略

checkpoint 文件中的 Decision Brief 必须完整；对话发起消息可以按 `STATE.md.human_gate_decisions.decision_brief_profile` 压缩，以减少 token 消耗。

允许值：full|compact|summary。

| profile | 对话输出 | 文件要求 | 适用条件 |
|---|---|---|---|
| `full` | 打印完整待决策表 | checkpoint 保持完整 | 决策项少、用户要求全文或高风险审计 |
| `compact` | 打印 checklist 路径、自动预检、capsule 摘要、决策项总数、blocking / high-risk 决策表、不授权项、三个 exact 回复 | checkpoint 保持完整 | 默认模式 |
| `summary` | 按决策类型分组汇总，只打印高风险 / 阻断项和完整表路径 | checkpoint 保持完整 | 决策项数量超过 `summary_threshold` |

压缩不得省略：

- checklist 文件路径
- 自动预检结论
- Context Capsule Summary
- Decision Collection Coverage 摘要
- 待决策项总数
- blocking / high-risk 决策项
- approve 不代表授权的不授权项
- `approve`、`修改: <具体修改点>`、`reject` 三个 exact 回复

## Human Gate Launch Protocol

CP2 / CP3 / CP5 / CP8 的人工门禁发起动作必须同时满足文件合规和对话合规：

1. 发起前必须从 `STATE.md.human_gate_decisions.pending_human_decisions[]`、委托 Agent 交还摘要、review summary、自动预检结果、discussion log / checkpoint、LLD clarification queue、OPEN / Spike 项、inline fallback 授权、预授权终验条件、用户显式提出的选择题和当前 gate 相关正式产物中聚合本轮 DQ。
2. Decision Brief 必须包含 `### Decision Collection Coverage`，逐项列出适用来源、扫描状态、候选问题数、纳入待决策数和分类 / N/A 原因；缺少覆盖报告时不得发起人工确认。
3. 若下游产物中存在 `Q-*`、`OPEN`、`LCQ-*`、`O-*`、权限 / 安全边界、风险接受、运行授权、外部接口、数据写入、publish、live / 交易类事项，必须先分类为 `resolved-by-user`、`decision-item`、`non-blocking-open`、`converted-to-spike` 或 `n/a-with-reason`。
4. `decision-item` 必须写入待人工决策清单；每项必须有 `decision_type`，取值为 `scope`、`architecture`、`security`、`implementation`、`runtime_authorization`、`risk_acceptance`、`follow_up_tracking`。
5. 发起前必须运行 `meta-flow check human-gate` 校验 checkpoint 文件；如果存在待发送消息草稿，必须同时用 `--launch-message-file` 校验对话内容包含 checklist 路径、自动预检结论、决策收集覆盖摘要、待决策项数量、待决策表格和三个 exact 回复。
6. 若待决策项数量大于 0 但发起消息未打印表格，检查点视为发起失败；若待决策项为 0，消息必须打印 `本轮待人工决策项：0` 并说明原因。
7. 用户对关键语义做出修订后，必须更新 DQ、重新生成 Decision Brief 和 Decision Collection Coverage，并重新发起确认，不得仅在后续文档静默修正。

## CP0 原始请求受理门

- 类型：自动
- 结果文件：`process/checks/CP0-REQUEST-INTAKE.md`
- 责任方：host-orchestrator
- 阶段：`init -> requirement-clarification`

### Entry Criteria

| 条目 | 说明 |
|---|---|
| 原始请求存在 | 用户已有明确任务、变更请求或 `.input/` 输入 |
| process 路由可用 | `meta-flow workspace check` 通过；首次初始化时已先用 `meta-flow workspace link --artifact-root <artifact_root> --project-name <project_name>` 或等价动作创建外置目录和软链接 |
| 工作目录可写 | `docs/`、`process/checks/`、`process/checkpoints/` 可创建；不得因缺少路由而直接创建本地 `process/` |
| 编排器单例可判定 | Codex 下未发现多个活动 host-orchestrator |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 请求已记录 | `process/REQUEST.md` 包含原始用户目标和约束 |
| 2 | 目标对象明确 | 区分新工作流、修改 meta-flow 本身、外部 production 交付 |
| 3 | engagement mode 明确 | `production` 或 `meta-self-dev` 已设置 |
| 4 | 输出位置明确 | 运行态、确认态、交付态路径可判定 |
| 5 | process 软链接契约明确 | 外置模式下 `process/.meta-flow-process.yaml` 与 `STATE.md.artifact_routing` 的 `artifact_root`、`project_process_root`、`link_path`、`project_name` 一致，且路径以锚点 + 相对路径记录；首次初始化前缺 artifact 目录时先向用户索取 |
| 6 | 干系人或决策人明确 | 至少能判定谁负责人工确认 |
| 7 | 初始优先级明确 | Must / Should / Could 或等价优先级已记录 |
| 8 | 明显冲突已暴露 | 与现有规则冲突的内容已登记为开放问题 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 初始化完成 | `STATE.md`、`REQUEST.md`、`INPUT-INDEX.md` 已就绪，且 `process` 路由健康 |
| 无阻断开放问题 | 不存在阻止进入场景发现的 BLOCKING 项 |

### Deliverables

- `process/REQUEST.md`
- `process/STATE.md`
- `process/INPUT-INDEX.md`
- `process/checks/CP0-REQUEST-INTAKE.md`

## CP1 用户场景完备门

- 类型：自动
- 结果文件：`process/checks/CP1-USE-CASE-COMPLETENESS.md`
- 责任方：meta-pm
- 阶段：`requirement-clarification`

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP0 通过 | 原始请求已结构化 |
| 场景主体明确 | `scenario_subject_type` 与 `scenario_subject_id` 已判定或有待确认状态 |
| 初步范围明确 | Scope / Out of Scope 有初稿 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 用户角色完整 | 覆盖主要使用者、维护者、审批者或调用方 |
| 2 | 正向场景完整 | Happy Path 从触发到结束闭环 |
| 3 | 异常场景覆盖 | 错误输入、依赖失败、权限不足、超时、回退 |
| 4 | 边界场景覆盖 | 空数据、重复执行、并发、历史兼容、部分失败 |
| 5 | 场景可验证 | 每个关键场景可转为验收标准或测试用例 |
| 6 | 非功能场景存在 | 性能、安全、可靠性、可维护性、可观测性 |
| 7 | 场景优先级明确 | P0/P1/P2 或 MoSCoW 已记录 |
| 8 | 原始需求可追溯 | 场景能追溯到原始请求或变更来源 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| P0 场景无缺失 | 关键用户旅程和异常路径已覆盖 |
| 开放问题有状态 | OPEN / RESOLVED / DEFERRED 均有 owner 或处理计划 |

### Deliverables

- `docs/product/USE-CASES.md`
- `process/CLARIFICATION-LOG.md`
- `process/checks/CP1-USE-CASE-COMPLETENESS.md`

## CP2 需求 / 场景 / 范围基线门

- 类型：自动预检 + 人工
- 自动结果文件：`process/checks/CP2-REQUIREMENTS-BASELINE.md`
- 人工审查稿：`process/checkpoints/CP2-REQUIREMENTS-BASELINE.md`
- 责任方：meta-pm / host-orchestrator

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP1 通过 | 用户场景已形成可追溯基线 |
| 需求草案存在 | `docs/product/REQUIREMENTS.md` 已生成 |
| 工程验证场景存在或说明 N/A | `SCENARIOS.yaml` 与 `TEST-MATRIX.md` 已生成，或自动检查写明不适用 / waived 原因 |
| 产品规划输入存在或说明 N/A | `STORY-MAP.md` 与 `MVP-SCOPE.md` 已生成，或自动检查写明不适用 / waived 原因 |
| 非功能需求有初稿 | 性能、安全、可靠性、兼容性等已列出 |
| 场景讨论证据存在或说明 N/A | `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md` 与 `process/checks/CP2-DISCUSSION-CHECKPOINT.json` 可读，或自动检查写明不适用原因 |
| 用户可见场景确认证据存在 | 标准模式下至少 1 条 `SGQ-*` 场景确认问题、用户回答和复述确认已写入 discussion log / checkpoint；fast-lane N/A 必须说明原因 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 功能需求完整 | P0/P1 场景均有对应需求 |
| 2 | 非功能需求量化 | NFR 有可检验目标值或明确不适用理由 |
| 3 | 范围清晰 | Scope / Out of Scope 明确 |
| 4 | 验收标准明确 | 每条 P0/P1 需求有 AC |
| 5 | 约束条件记录 | 技术、合规、资源、平台、兼容性约束已记录 |
| 6 | 依赖和风险识别 | 外部依赖、未知技术点、交付风险已登记 |
| 7 | 需求无冲突 | 冲突已解决或有决策记录 |
| 8 | 变更机制明确 | 基线后修改必须走 CR |
| 9 | 追溯矩阵建立 | 原始请求 -> 场景 -> 需求 可追溯 |
| 10 | Scenario Gray Areas 已处理 | 3-4 个关键灰区、用户选择的 1-3 个重点、未选项和 canonical refs 已记录 |
| 11 | Deferred Ideas 已隔离 | 超出当前 scope 的想法、风险和扩展场景已进入 deferred，不污染需求基线 |
| 12 | 用户可见场景确认已完成 | 至少 1 条 `SGQ-*` 场景确认交互已记录问题、候选选项或 freeform、用户回答、复述确认和影响面；缺失时 CP2 只能 `FAIL` / `BLOCKED` |
| 13 | 8 维扫描后台化 | 仅将影响设计 / 测试 / 交付 / 门控的缺口暴露给用户，其余覆盖状态已记录 |
| 14 | 工程验证场景可追踪 | `SCENARIOS.yaml` 覆盖正向、负向、边界、权限、失败恢复或写明 N/A；`TEST-MATRIX.md` 可追踪 Scenario / Requirement / Story / 测试状态 |
| 15 | MVP 范围可确认 | `STORY-MAP.md`、`MVP-SCOPE.md`、`RELEASE-SLICES.md`、`BACKLOG.md` 存在或有 N/A / waived 原因，且 In Scope / Out of Scope / Deferred 可人工确认 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| P0/P1 需求通过 | 致命问题 = 0，阻塞问题 = 0 |
| 人工确认完成 | `process/checkpoints/CP2-REQUIREMENTS-BASELINE.md` 结论为 approved |

### Deliverables

- `docs/product/REQUIREMENTS.md`
- `docs/product/SCENARIOS.yaml`
- `docs/product/TEST-MATRIX.md`
- `docs/product/STORY-MAP.md`
- `docs/product/MVP-SCOPE.md`
- `docs/product/RELEASE-SLICES.md`
- `docs/product/BACKLOG.md`
- `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md`（或 N/A 说明）
- `process/checks/CP2-DISCUSSION-CHECKPOINT.json`（或 N/A 说明）
- `process/checks/CP2-REQUIREMENTS-BASELINE.md`
- `process/checkpoints/CP2-REQUIREMENTS-BASELINE.md`

## CP3 蓝图 / HLD 架构评审门

- 类型：自动预检 + 人工
- 自动结果文件：`process/checks/CP3-HLD-CONSISTENCY.md`
- 人工审查稿：`process/checkpoints/CP3-HLD-REVIEW.md`
- 责任方：meta-se / host-orchestrator

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP2 通过 | 需求 / 场景 / 范围基线已确认 |
| 蓝图适用性已判定 | `docs/design/BLUEPRINT.md` / `docs/design/DOMAIN-MAP.md` / `docs/design/DEPENDENCY-MAP.md` 已生成，或 CP3 自动检查写明 N/A / waived 原因 |
| HLD 草案存在 | `docs/design/HLD.md` 已生成 |
| ADR 草案可读 | `docs/design/ARCHITECTURE-DECISION.md` 已生成草案；关键决策点越早确认越好，CP3 只提交影响架构 / 安全 / 权限 / 外部接口 / 运行授权的核心 ADR |
| 架构讨论证据存在或说明 N/A | `process/discussions/CP3-HLD-DISCUSSION-LOG.md` 与 `process/checks/CP3-DISCUSSION-CHECKPOINT.json` 可读，或自动检查写明不适用 / blocked 原因 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 需求覆盖 | 所有 P0/P1 需求在架构中有对应设计 |
| 2 | 模块边界清晰 | 职责高内聚、低耦合 |
| 3 | 接口方向明确 | 调用方向、输入输出、错误处理清晰 |
| 4 | 数据流清晰 | 核心数据流、状态流、持久化策略清楚 |
| 5 | 核心 ADR 可决策 | CP3 需确认的关键 ADR 有推荐方案、至少 1 个备选方案、优劣分析、影响 / 风险和回退 / 切换条件 |
| 6 | 风险有缓解 | 技术、依赖、性能风险有应对方案 |
| 7 | NFR 已落地 | 性能、安全、可靠性、可观测性有设计承载 |
| 8 | 失败路径明确 | 超时、失败、回滚、降级、重试策略明确 |
| 9 | 可测试性明确 | 架构支持单测、集成测试、回归测试 |
| 10 | 内部一致 | HLD、ADR、Risk Matrix、NFR 不自相矛盾 |
| 11 | Architecture Gray Areas 已前置 | HLD 前已识别关键架构灰区，且 advisor table 影响候选方案和推荐方案 |
| 12 | 适用性矩阵完整 | 用户目标、项目成熟度、认知负担、验证条件和回退成本均已评估 |
| 13 | 场景映射完整 | Use Case → Architecture Traceability 覆盖关键 UC、模块、异常路径和验证方式 |
| 14 | 场景模拟通过 | 至少 2-3 个关键 UC 已走通推荐架构；失败项不存在或已阻断 |
| 15 | 切换条件明确 | 推荐方案的优化项、牺牲项和 When to switch 条件已记录 |
| 16 | 蓝图承接明确 | `docs/design/BLUEPRINT.md` / `docs/design/DOMAIN-MAP.md` / `docs/design/DEPENDENCY-MAP.md` 已被 HLD 消费，或自动检查逐项写明 N/A / waived 原因、影响和后续触发条件 |
| 17 | Feature 级实现设计触发条件明确 | HLD 已列出哪些 Feature 需要 `implementation-design`，以及 `docs/design/FEATURE-DESIGN-MATRIX.md` / `docs/features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md` 的生成条件 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 自动预检通过 | 无未豁免 FAIL |
| 人工确认完成 | HLD 可作为 Story 拆解输入 |

### Deliverables

- `docs/design/HLD.md`
- `docs/design/BLUEPRINT.md`（或 CP3 N/A / waived 说明）
- `docs/design/DOMAIN-MAP.md`（或 CP3 N/A / waived 说明）
- `docs/design/DEPENDENCY-MAP.md`（或 CP3 N/A / waived 说明）
- `docs/design/ARCHITECTURE-DECISION.md`（CP3 前为草案，CP3 后回写核心 ADR 确认结论）
- `process/discussions/CP3-HLD-DISCUSSION-LOG.md`（或 N/A 说明）
- `process/checks/CP3-DISCUSSION-CHECKPOINT.json`（或 N/A 说明）
- `process/checks/CP3-HLD-CONSISTENCY.md`
- `process/checkpoints/CP3-HLD-REVIEW.md`

## CP4 Story 拆解与并行安全门

- 类型：自动预检（汇入 CP5）
- 自动结果文件：`process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md`
- 责任方：meta-se / host-orchestrator

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP3 通过 | HLD 已确认 |
| Feature 设计矩阵存在 | `docs/design/FEATURE-DESIGN-MATRIX.md` 已生成，覆盖 Feature / Epic 适用性、required / waived / n/a 理由和 Story lld_policy 建议 |
| 必要 Feature 设计已处理 | 矩阵中 `required` 的 Feature 已生成 `docs/features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md`，或写明 waived 决策和重访条件 |
| Story 计划存在 | `STORY-BACKLOG.md`、`DEVELOPMENT-PLAN.yaml` 和 Story 卡片已生成 |
| 依赖信息存在 | `depends_on`、依赖类型和文件所有权已填写 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | Story 覆盖需求 | 每条 P0/P1 需求有 Story 覆盖 |
| 2 | Story 粒度合理 | 单 Story 可独立开发、验证，并可纳入 LLD 设计批次统一确认 |
| 3 | AC 明确 | 每个 Story 有可验证验收标准 |
| 4 | INVEST 基本满足 | 独立、可协商、有价值、可估算、小、可测试 |
| 5 | 依赖关系完整 | `depends_on` 标清上游 Story |
| 6 | 依赖类型明确 | `contract` / `runtime` / `file-conflict` |
| 7 | DAG 无环 | 依赖图不能出现循环 |
| 8 | 关键路径识别 | 长链路依赖和阻塞点已标记 |
| 9 | 文件所有权明确 | `primary`、`shared`、`merge_owner`、`forbidden` |
| 10 | 并行计划合理 | `lld_ready` / `dev_ready` 可解释 |
| 11 | Wave 不是硬门 | Wave 只作为调度分组，实际以 DAG 和 gate 为准 |
| 12 | QA 策略同步 | Story 如何验证、哪些可并行验证已说明 |
| 13 | Feature 设计矩阵完整 | 所有 Feature / Epic 均有 `required` / `waived` / `n/a` 判定和理由 |
| 14 | required Feature 设计就绪 | `required` Feature 的 DESIGN / TEST-PLAN / TASKS 已生成，或 waived 决策已进入人工决策项 |
| 15 | Story 设计引用完整 | 每个 Story 均有 `feature_design_refs`，指向 Feature 设计或 waived 证据 |
| 16 | LLD 策略明确 | 每个 Story 均有 `lld_policy.required_level=full-lld|technical-note|waived`、触发原因和重访条件 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| DAG 校验通过 | 无循环依赖 |
| 文件冲突可控 | 未处理冲突 = 0 |
| 首批队列可计算 | `lld_ready` 可解释 |
| CP5 汇总就绪 | Feature 设计矩阵、Story 边界、`lld_policy`、依赖、文件所有权和并行计划风险可汇入 CP5 Decision Brief |

### Deliverables

- `docs/design/FEATURE-DESIGN-MATRIX.md`
- `docs/features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md`（仅矩阵中 required 的 Feature；waived / n/a 写明原因）
- `process/STORY-BACKLOG.md`
- `process/DEVELOPMENT-PLAN.yaml`
- `process/stories/STORY-*.md`
- `process/stories/STORY-STATUS.md`
- `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md`

## CP5 Story 设计证据可实现性门

- 类型：全量自动预检 + 全量人工
- 自动结果文件：`process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`
- 人工审查稿：`process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md`
- 责任方：meta-dev / host-orchestrator

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP4 自动预检通过 | Story 拆解、依赖 DAG、文件所有权和并行计划已通过自动检查 |
| 全部目标 Story 处于设计审查态 | 状态均为 `lld-ready-for-review` 或全量 `lld-batch-ready-for-review` |
| 全部目标 Story 设计证据已生成 | `full-lld` 有 `STORY-{id}-{story_slug}-LLD.md`；`technical-note` 有 Story `## 技术说明`；`waived` 有豁免理由、风险接受和重访条件 |
| LLD clarification 队列可读 | `STATE.md.parallel_execution.lld_clarification_queue` 已初始化，且无未回答阻断项；若有 OPEN / Spike，已标注非阻断和重访条件 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 设计证据覆盖 AC | 每条验收标准有实现设计或明确 waived 理由 |
| 2 | 与 HLD 一致 | 不违背 HLD / ADR |
| 3 | 文件影响范围明确 | 新增、修改、删除文件写清楚 |
| 4 | 接口契约完整 | 输入、输出、错误码、超时、兼容性 |
| 5 | 数据结构明确 | schema、字段、状态、迁移、默认值 |
| 6 | 控制流明确 | 主流程、异常流程、回退流程 |
| 7 | 依赖输入明确 | 上游 contract/runtime 依赖满足条件清楚 |
| 8 | 并发和一致性考虑 | 竞态、重复执行、事务、幂等已说明 |
| 9 | 安全设计明确 | 权限、输入校验、敏感信息、审计 |
| 10 | 可测试性明确 | 单测点、集成点、Mock 点、验证命令 |
| 11 | dev_gate 可计算 | `lld_confirmed`、`dependencies_satisfied`、`file_conflict_free` 可判定 |
| 12 | 偏差记录机制明确 | 实现偏离 LLD 时必须记录原因和影响 |
| 13 | CP4 摘要已纳入 | Story 边界、DAG、并行安全、文件所有权和 OPEN 项已写入 Decision Brief |
| 14 | clarification 队列已收敛 | 已回答项、转 OPEN / Spike 项、阻断项为 0、跨 Story 契约和 merge order 均已写入 Decision Brief |
| 15 | lld_policy 分级合理 | `full-lld` / `technical-note` / `waived` 与触发原因一致，高风险 Story 未被降级 |
| 16 | Feature 设计输入被消费 | Story 的 `feature_design_refs` 已在 LLD / 技术说明 / waived 证据中引用 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 自动预检通过 | 全部目标 Story 的设计证据可实现性检查无阻断项 |
| clarification 队列收敛 | `blocks_lld=true` 的未回答项为 0；非阻断 OPEN / Spike 已有 owner 和重访条件 |
| 人工确认完成 | 全部目标 Story 的完整 LLD / 技术说明 / waived 证据被统一批准 |
| dev_gate 可更新 | 全部目标 Story 可进入 `lld-approved`，当前 Wave 满足时进入 `dev_ready` |

### Deliverables

- `process/stories/STORY-{id}-{story_slug}-LLD.md`（仅 `full-lld`）
- `process/stories/STORY-{id}-{story_slug}.md` 的 `## 技术说明` 或 waived 证据（仅 `technical-note` / `waived`）
- `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`
- `process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md`
- 更新后的 `process/stories/STORY-STATUS.md`

## CP6 Story 编码完成门

- 类型：滚动自动
- 结果文件：`process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md`
- 责任方：meta-dev

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP5 通过 | 全部目标 Story 的设计证据已确认 |
| dev_gate 满足 | 依赖和文件所有权允许开发 |
| 实现完成 | Story 任务清单已执行完 |
| 实现执行证据存在 | Story 必需的 `IMPLEMENTATION.md`、Story 实现摘要或 `DEV-LOG.md` 已生成；复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / Guardrail / 平台适配必须有完整 IMPLEMENTATION |
| meta-dev 调度证据存在 | `STATE.md.agent_lifecycle` 与 handoff `dispatch` 证明 meta-dev 已由子 agent 执行，或存在用户批准的 inline fallback |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | AC 全部实现 | Story 验收标准无遗漏 |
| 2 | 与 LLD 一致 | 偏离 LLD 的地方有记录和理由 |
| 3 | 文件边界合规 | 未越过 `file_ownership.forbidden`，未抢占其他 Story primary 文件 |
| 4 | 实现对象清单完整 | 代码、Prompt / Skill、模板 / Schema、安装器、guardrail、测试、文档等适用对象均已列出，N/A 有理由 |
| 5 | 设计契约映射完整 | 每个 must / should / must-not、输入输出字段、状态变化、权限变化、平台分支均映射到实现位置或 N/A |
| 6 | 单元测试 / Fixture 计划已执行 | 按实现对象选择 pytest、fixture、结构检查、契约测试、dry-run 或人工检查；未运行项有原因 |
| 7 | 最小实现切片已验证 | 每个 Slice 有输出文件、局部验证和状态；失败项未被忽略 |
| 8 | 平台差异检查完成 | Claude / Codex / OpenClaw 的工具权限、schema、安装路径、降级策略已检查或 N/A |
| 9 | 代码规范通过 | lint、format、类型检查或项目等价命令通过，或 N/A 有理由 |
| 10 | 静态检查通过 | guardrail、安全扫描、结构检查按适用范围通过 |
| 11 | 自测完成 | 正向和主要异常场景已验证 |
| 12 | 文档同步 | README、USER-MANUAL、接口文档、配置说明、变更说明必要时更新 |
| 13 | 实现交接摘要完整 | 完成内容、行为变化、受影响文件、验证、未运行检查、剩余风险、QA / Review / Doc 关注点已记录 |
| 14 | 设计缺口反馈 | Feature / HLD / LLD / TEST-MATRIX / 决策队列缺口已反馈，不被实现阶段静默吞掉 |
| 15 | 状态回写 | Story 状态、任务清单、偏差记录、implementation evidence 路径已更新 |
| 16 | 无缓存产物 | `__pycache__`、构建缓存等不进入交付物 |
| 17 | Agent Dispatch Evidence | 存在 meta-dev 的 `canonical_role`、`codex_agent_name`、`reasoning_profile`、`dispatch_trigger`、`agent_id` / `thread_id`、`tool_name`、`spawned_at` 或 `resumed_at`、`completed_at`；或存在用户批准的 `dispatch.mode=inline-fallback` |
| 18 | Story Return Packet | `process/returns/STORY-*.CP6.return.json` 存在，并通过 `meta-flow story return-check`；touched files 未越过 Story Work Packet 的 `allowed_write_paths` / `forbidden_write_paths` |
| 19 | Evidence Index | `process/evidence/STORY-*.CP6.index.json` 存在，并通过 `meta-flow story evidence-check`；CP6 Markdown 只引用索引，不复制完整证据正文 |
| 20 | Design Delta | 若 `design_delta_required=true`，`process/design-deltas/STORY-*.delta.json` 存在，并通过 `meta-flow design delta-check` |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 必要命令通过 | 验证命令有证据或 N/A 理由 |
| 实现契约闭环 | 实现对象、设计契约、测试 / fixture、切片验证和交接摘要均可追溯 |
| 无阻塞自查问题 | Story 可进入 `ready-for-verification` |
| 调度证据通过 | meta-dev 执行证据有效；仅 handoff-created 不可放行 |

### Deliverables

- 代码变更
- `process/stories/STORY-{id}-{story_slug}-IMPLEMENTATION.md`（强制场景）或 Story 实现摘要 / `DEV-LOG.md`（普通场景）
- `DEV-LOG.md`
- `process/returns/STORY-{id}.CP6.return.json`
- `process/evidence/STORY-{id}.CP6.index.json`
- `process/design-deltas/STORY-{id}.delta.json`（仅设计 delta 存在时）
- `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md`
- 更新后的 Story 状态
- 对应 meta-dev handoff 的 `dispatch` 记录

## CP7 Story 验证完成门

- 类型：滚动自动
- 结果文件：`process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md`
- 责任方：meta-qa

### Entry Criteria

| 条目 | 说明 |
|---|---|
| CP6 通过 | Story 处于 `ready-for-verification` |
| 测试上下文可用 | 验证环境或等价验证方式可用 |
| 测试策略存在 | `TEST-STRATEGY.md` 已生成或明确 N/A |
| 覆盖矩阵可用 | `TEST-MATRIX.md` 可读，或 CP7 自动检查写明 N/A / waived 原因 |
| 验证执行证据可生成 | `verification-execution` 可输出验证范围、对象清单、追踪矩阵、设计契约验证、分层验证计划和阶段决策，或检查结果写明轻量 N/A 原因 |
| 质量评审产物可生成 | `quality-review` 可输出 `docs/quality/TEST-REPORT.md` / `docs/quality/REVIEW.md` / `docs/quality/FIXES.md`，或检查结果写明不适用原因 |
| meta-qa 调度证据存在 | `STATE.md.agent_lifecycle` 与 handoff `dispatch` 证明 meta-qa 已由子 agent 执行，或存在用户批准的 inline fallback |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 功能测试通过 | Story AC 对应测试均通过 |
| 2 | 异常测试通过 | 失败、超时、权限、边界条件覆盖 |
| 3 | 回归影响评估 | 相关旧功能没有明显退化 |
| 4 | 集成验证完成 | contract/runtime 依赖相关集成点通过 |
| 5 | 非功能验证完成 | 性能、安全、可靠性按 Story 适用范围验证 |
| 6 | 缺陷闭环 | P0/P1 缺陷为 0，P2 有处理计划 |
| 7 | 测试证据完整 | 命令、日志、报告、截图或等价证据记录 |
| 8 | 追溯完整 | 需求、Story、LLD、代码、测试结果可串联 |
| 9 | TEST-MATRIX 回链完整 | `docs/product/TEST-MATRIX.md` 的适用场景均回链到 `docs/quality/TEST-REPORT.md` / `docs/quality/REVIEW.md` 结论，未执行项有风险或 N/A / waived 理由 |
| 10 | 质量发现闭环 | `REVIEW.md` findings 已按严重度处理，`FIXES.md` 记录修复、豁免或回修 owner |
| 11 | 验证对象清单完整 | 代码、Prompt / Skill、模板 / Schema、安装器、guardrail、文档、状态和发布产物按适用范围列出，N/A 有原因 |
| 12 | 验证追踪矩阵完整 | Scenario / Requirement / Story / Design Contract / Implementation / Test / Risk 可追溯，缺口已记录 |
| 13 | 设计契约验证完成 | HLD / ADR / LLD / Feature DESIGN / IMPLEMENTATION / PLATFORM-CONTRACTS 中的 must / should / must-not 有验证方式和结果 |
| 14 | 分层验证计划执行 | 静态、单元、Prompt / Skill fixture、契约、集成、dry-run、回归、人工审查均按适用性执行或 N/A |
| 15 | Prompt / Skill fixture 记录 | 复杂 Prompt / Skill / Workflow 改造有 fixture 或人工样例验证；低风险 N/A 有理由 |
| 16 | 人工 / 语义质量审查 | 需求一致性、场景覆盖、Prompt 边界、文档可用性、错误信息和 happy path 偏差已审查 |
| 17 | 问题与剩余风险分级 | `BLOCKER` / `HIGH` / `MEDIUM` / `LOW` / `INFO` 已记录 owner、状态和下一步 |
| 18 | 阶段决策合法 | CP7 结论只使用 `PASS` / `PASS_WITH_RISK` / `BLOCKED` / `NEEDS_REWORK` / `NEEDS_DESIGN_CLARIFICATION` / `WAIVED`，并带路由 |
| 19 | Agent Dispatch Evidence | 存在 meta-qa 的 `canonical_role`、`codex_agent_name`、`reasoning_profile`、`dispatch_trigger`、`agent_id` / `thread_id`、`tool_name`、`spawned_at` 或 `resumed_at`、`completed_at`；或存在用户批准的 `dispatch.mode=inline-fallback` |
| 20 | Story Return Packet | `process/returns/STORY-*.CP7.return.json` 存在，并通过 `meta-flow story return-check` |
| 21 | Evidence Index | `process/evidence/STORY-*.CP7.index.json` 存在，并通过 `meta-flow story evidence-check`；CP7 Markdown 只引用索引，不复制完整证据正文 |
| 22 | Design Delta 回写 | 需要 Feature DESIGN / ADR / HLD 回写的 design delta 在 CP8 前必须通过 `meta-flow design delta-check --require-merged`，否则路由到 `NEEDS_DESIGN_CLARIFICATION` 或 CP8 BLOCKED |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 阻塞缺陷为 0 | P0/P1 缺陷 = 0 |
| 验证结论可路由 | `PASS` / `PASS_WITH_RISK` / `WAIVED` 可进入下一阶段；`NEEDS_REWORK` 回 meta-dev；`NEEDS_DESIGN_CLARIFICATION` 回 meta-se / host-orchestrator；`BLOCKED` 停止推进 |
| 调度证据通过 | meta-qa 执行证据有效；仅 handoff-created 不可放行 |

### Deliverables

- `docs/quality/VERIFICATION-REPORT.md` 或 Feature scoped 等价文件
- `docs/quality/TEST-REPORT.md`（或 Story / Feature scoped 等价文件）
- `docs/quality/REVIEW.md`（或 Story / Feature scoped 等价文件）
- `docs/quality/FIXES.md`（若存在 findings；无 findings 时写 N/A 理由）
- `process/returns/STORY-{id}.CP7.return.json`
- `process/evidence/STORY-{id}.CP7.index.json`
- `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md`
- 缺陷记录或风险接受记录
- 更新后的 `STORY-STATUS.md`
- 对应 meta-qa handoff 的 `dispatch` 记录

## CP8 交付就绪门

- 类型：自动预检 + 人工
- 自动结果文件：`process/checks/CP8-DELIVERY-READINESS.md`
- 人工审查稿：`process/checkpoints/CP8-DELIVERY-READINESS.md`
- 责任方：meta-qa / meta-doc / host-orchestrator

### Entry Criteria

| 条目 | 说明 |
|---|---|
| 目标 Story 已验证 | 所有目标 Story 处于 `verified` |
| 文档已生成 | README、USER-MANUAL 或等价文档完成 |
| 安装验证完成 | 适用平台的安装或 dry-run 已执行 |
| 发布上下文胶囊存在 | `process/release/RELEASE-CONTEXT.yaml` 已生成，且只包含摘要、计数、风险 ID、决策 ID 和证据路径 |
| 发布 profile 已判定 | `release_artifact_profile=minimal|compact|full` 已写入 capsule、发布产物和 CP8 自动预检 |
| 发布就绪产物存在 | `docs/release/RELEASE-NOTES.md`、`docs/release/DEPLOY-CHECKLIST.md`、`docs/release/ROLLBACK.md`、`docs/release/MIGRATION.md`、`docs/release/FEEDBACK.md` 已生成，或 CP8 自动预检写明逐项 N/A / waived 原因 |

### Checklist

| # | 检查项 | 说明 |
|---|---|---|
| 1 | 需求闭环 | P0/P1 需求均有实现和验证证据 |
| 2 | Story 闭环 | 目标 Story 均 verified |
| 3 | 文档齐套 | README、USER-MANUAL、必要规则说明完成 |
| 4 | 安装验证通过 | Codex / Claude、project / user scope 按适用范围验证 |
| 5 | 平台规则一致 | AGENTS.md / CLAUDE.md 与实际交付内容一致 |
| 6 | 交付目录合规 | `delivery/agents`、`delivery/skills`、`delivery/rules`、`delivery/scripts` 边界正确 |
| 7 | 缓存和临时文件清理 | 无 `__pycache__`、临时构建产物 |
| 8 | guardrail 通过 | 当前仓库存在 guardrail 时必须通过 |
| 9 | 风险和遗留问题明确 | 遗留问题有状态、owner、后续计划 |
| 10 | Release Context Capsule 完整 | 发布范围、版本号决策、质量摘要、影响面、安装验证摘要、发布文档状态、不授权项和后续事项均已汇总；不得复制长日志、全文 diff 或上游全文 |
| 11 | 发布 profile 合法 | `minimal` / `compact` / `full` 判定有理由；fast-lane 可 minimal，standard 默认 compact，高风险 / 真实发布 / 迁移 / 权限 / 安装路径变更必须 full |
| 12 | 发布结论合法 | `release_decision` 只使用 `READY` / `READY_WITH_RISK` / `NOT_READY` / `RELEASED` / `FAILED`；CP8 默认只允许 `READY` / `READY_WITH_RISK` / `NOT_READY` |
| 13 | 发布就绪产物完整 | 发布说明、部署检查、回滚、迁移和反馈计划按 profile 可读；不适用项有原因、影响和后续触发条件 |
| 14 | 版本号决策完成 | SemVer / alpha / beta / rc 判断已写入 `RELEASE-NOTES.md` 和 CP8 Decision Brief |
| 15 | 安装升级矩阵完成 | 受影响平台 / 组件 / scope 的全新安装、升级、重复安装幂等、dry-run、卸载 / 回滚已执行或 N/A |
| 16 | 迁移兼容性判断完成 | 状态 schema、模板字段、配置、安装路径、Agent frontmatter、Skill 输出格式、命令参数和数据结构已判断 |
| 17 | 发布后观察计划完成 | `FEEDBACK.md` 含观察信号、触发阈值和反馈分流；默认不要求独立 `POST-RELEASE-OBSERVATION.md` |
| 18 | 用户终验确认 | 用户明确 approve / 修改 / reject；approve 仅接受 READY / READY_WITH_RISK，不授权真实发布动作 |

### Exit Criteria

| 条目 | 说明 |
|---|---|
| 自动预检通过 | 无未豁免 FAIL |
| 发布就绪可判定 | `release_decision=READY` 或 `READY_WITH_RISK` 可发起人工终验；`NOT_READY` 不得发起人工终验；`RELEASED` / `FAILED` 只能在独立真实发布授权后写入 |
| 人工终验通过 | 用户确认 delivered |

### Deliverables

- `delivery/README.md`
- `delivery/doc/USER-MANUAL.md`
- `delivery/agents/*`
- `delivery/skills/*`
- `delivery/rules/*`
- `delivery/scripts/*`
- `process/release/RELEASE-CONTEXT.yaml`
- `docs/release/RELEASE-NOTES.md`（或 CP8 N/A / waived 说明）
- `docs/release/DEPLOY-CHECKLIST.md`（或 CP8 N/A / waived 说明）
- `docs/release/ROLLBACK.md`（或 CP8 N/A / waived 说明）
- `docs/release/MIGRATION.md`（或 CP8 N/A / waived 说明）
- `docs/release/FEEDBACK.md`（或 CP8 N/A / waived 说明）
- `process/checks/CP8-DELIVERY-READINESS.md`
- `process/checkpoints/CP8-DELIVERY-READINESS.md`

## 执行规则

1. 所有 CP 文件创建或更新后，必须回写 `process/STATE.md.checkpoints` 中的路径和结论。
1. 写入任何 CP 文件前必须确认 `process` 路由健康。首次初始化只允许在已建立外置过程目录和软链接后写入 `STATE.md` / `REQUEST.md` / `INPUT-INDEX.md`；若 artifact 目录未知、软链接断裂或路由冲突，先写 `BLOCKED` 结论或中断并要求用户提供目录，不得静默创建新的本地 `process/`。
2. 人工检查点的自动预检未 `PASS` 或 `WAIVED` 前，host-orchestrator 不得发起人工确认。
3. 人工确认通过后，host-orchestrator 必须把人工结论写回对应 `process/checkpoints/CP*.md` 的“人工审查结果”，并同步更新 `STATE.md`。
4. 如果用户直接在对话中回复 `approve`，host-orchestrator 也必须补写人工审查结果文件，不能只改状态。`1/通过` 可作为历史兼容别名解析，但新提示不得再把多个等价别名混排给用户。
5. `changes_requested` 必须路由给对应 agent 修订，并在重提时保留旧检查结果作为历史证据。
6. `rejected` 必须回退到检查点定义的目标阶段或 Story 状态。
7. CP6 / CP7 必须包含 `## Agent Dispatch Evidence` 小节；若缺少真实子 agent 证据且没有用户批准的 `inline-fallback`，结论只能是 `FAIL` 或 `BLOCKED`。CP6 / CP7 还必须引用 Story Return Packet 与 Evidence Index；Markdown 检查文件不得替代结构化 return / evidence 真相源。
8. CP4 自动预检失败时不得进入 CP5；CP4 通过时不得单独要求人工确认，必须把摘要并入 CP5。
9. CP2 / CP3 人工检查点发起前必须校验 discussion log / checkpoint 存在；若缺失且没有 N/A 理由，结论只能是 `BLOCKED`。
10. CP5 人工检查点发起前必须校验 `STATE.md.parallel_execution.lld_clarification_queue`。存在未回答 `blocks_lld=true` item 时，CP5 结论只能是 `BLOCKED`；用户明确接受转 OPEN / Spike 的 item 必须写入 Decision Brief、LLD 第 12.1 节或 Story 技术说明，以及 DEV-LOG。

CP6 / CP7 的 `Agent Dispatch Evidence` 小节必须使用以下结构：

```markdown
## Agent Dispatch Evidence

| 检查项 | 状态 | 证据 | 说明 |
|---|---|---|---|
| 子 agent 调度模式 | PASS/FAIL/WAIVED | `process/handoffs/...` | `subagent` / `inline-fallback` / `handoff-only` |
| canonical role | PASS/FAIL/WAIVED | `dispatch.canonical_role` / `active_agents[].role` | `meta-dev` / `meta-qa`，不得写动态 profile 名称 |
| Codex custom agent | PASS/FAIL/WAIVED | `dispatch.codex_agent_name` / `active_agents[].codex_agent_name` | `meta-dev` / `meta-dev-debugger` / `meta-qa` / `meta-qa-critical` |
| reasoning profile | PASS/FAIL/WAIVED | `dispatch.reasoning_profile` / `active_agents[].reasoning_profile` | `default` / `debugger` / `critical` |
| dispatch trigger | PASS/FAIL/WAIVED | `dispatch.dispatch_trigger` / `active_agents[].dispatch_trigger` | `phase-default` / `repeated-failure` / `critical-checkpoint` / `risk-review` 等可审计原因 |
| agent 标识 | PASS/FAIL/WAIVED | `STATE.md.agent_lifecycle` | `agent_id` 或 `thread_id` |
| 平台工具证据 | PASS/FAIL/WAIVED | `tool_name` | `spawn_agent` / `resume_agent` / `send_input` / platform task |
| 完成时间 | PASS/FAIL/WAIVED | `completed_at` | 子 agent 返回完成结果的时间 |
| inline fallback 授权 | N/A/WAIVED/FAIL | `approved_by`、`approved_at` | 仅 fallback 时允许 WAIVED |
```

## 验收标准

- [ ] CP0-CP8 均有 Entry Criteria、Checklist、Exit Criteria、Deliverables
- [ ] 自动检查点均生成 `process/checks/CP*.md` 结果文件
- [ ] CP2 / CP3 / CP5 / CP8 人工检查点均生成 `process/checkpoints/CP*.md` 审查稿
- [ ] 人工检查稿包含 Decision Brief
- [ ] host-orchestrator 发起关键人工确认时明确提示 checklist 文件路径、自动预检结论、待决策项数量、待决策表格和三个 exact 回复
- [ ] 发起消息已复述 `approve` 接受哪些 DQ，且不授权项已独立列出
- [ ] `meta-flow check human-gate` 校验 checkpoint 文件和发起消息通过
- [ ] 人工审查后对应 `process/checkpoints/CP*.md` 已填入结论
- [ ] `STATE.md.checkpoints` 与检查文件状态一致

## Gotchas

- 自动预检 `PASS` 或 `WAIVED` 不等于人工门已通过；CP2 / CP3 / CP5 / CP8 缺少用户结论和“人工审查结果”回填时，不得推进状态。
- CP4 只生成自动预检并汇入 CP5；不得为 CP4 单独生成用户确认稿，也不得用 CP4 通过替代全量 CP5 设计证据确认。
- Decision Brief 里的人工决策项必须有可执行备选方案和回退 / 切换条件；治理类备选可以是暂缓确认、保持当前基线、回退上游或转 Spike，但不能写“无备选”。
- `approve` 只表示接受待人工决策清单内的推荐方案，不授权真实运行、凭据、安全、外部接口、数据写入、publish 或 live / 交易类操作。
- 模板文件存在不等于检查通过；每个检查项必须有路径、状态和证据，缺证据时应写 `FAIL`、`BLOCKED`、`N/A` 或 `WAIVED` 及原因。
