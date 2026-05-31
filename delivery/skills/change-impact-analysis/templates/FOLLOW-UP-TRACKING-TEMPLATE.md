---
source_cr: "CR-{id}"
status: "open"
created_at: ""
created_by: "meta-po"
updated_at: ""
checkpoint_source: "CP8"
---

# CR-{id} 后续事项跟踪台账

## 目的

本台账只记录 CP8 或 CR 收敛后需要后续跟踪的候选事项。候选项未启动前不得预创建正式 CR 文件；只有用户决定推进某一项时，才在 `process/changes/` 下创建对应正式 CR，并把本台账中的状态改为 `active`。

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
| 关闭范围 | 0 | 否 | 本轮已完成并关闭 |
| 不授权范围 | 0 | 否 | 设计通过不代表授权执行的事项 |
| 风险接受项 | 0 | 否 / 是 | 用户接受风险后放行，必须有回退条件 |
| 后续 CR 候选项 | 0 | 否 | 只维护候选状态，不创建正式 CR |
| 取消 / deferred 项 | 0 | 否 | 保留追溯，不删除 |

## 后续 CR / Spike 候选索引

| 候选编号 | 标题 | 状态 | 类型 | 影响面 / 冲突键 | 正式 CR 路径 | 当前门控 | 阻塞原因 | 下一步 | 来源 |
|---|---|---|---|---|---|---|---|---|---|
| CR-020 | `<候选标题>` | candidate | CR / Spike | `<文档 / Story / 文件 owner / 外部接口 / 安全或运行授权>` |  | 未启动 |  | 等待用户选择是否推进 | CP8-DQ-xx |

## 启动候选 CR 流程

用户决定推进某一候选项时，使用 `@meta-po 启动后续 CR`，并给出台账路径、候选编号和目标摘要。meta-po 必须先读取本台账、`STATE.md.active_change` 和活跃正式 CR，完成冲突预检后，才能创建正式 CR 文件并把状态改为 `active`。

## CR 冲突预检

| 检查项 | 结果 | 证据 | 处理结论 |
|---|---|---|---|
| 是否已有 `STATE.md.active_change` | PASS / BLOCKED | `process/STATE.md` |  |
| 是否存在未关闭正式 CR | PASS / BLOCKED | `process/changes/CR-*.md` |  |
| 正式文档影响面是否重叠 | PASS / BLOCKED | 文档处理决策 |  |
| Story / LLD 批次是否重叠 | PASS / BLOCKED | Story / CR 影响分析 |  |
| 文件 owner 是否冲突 | PASS / BLOCKED | Story file_ownership / CR 影响分析 |  |
| 外部接口 / 安全 / 运行授权是否重叠 | PASS / BLOCKED | Decision Brief / CR |  |

若存在重叠，默认不得并行推进；必须在以下处理方式中选择并记录：合并到现有 CR、保持候选等待、标记 `blocked`、拆分无冲突子集、或标记 `superseded` 并链接替代 CR。

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
