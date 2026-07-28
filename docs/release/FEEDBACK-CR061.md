---
status: ready-for-cp8-review
version: "0.4.1"
release_artifact_profile: full
release_decision: READY_WITH_RISK
---

# CR-061 Feedback

## 反馈回流入口

| Feedback ID | 类型 | 观察内容 | 分流 |
|---|---|---|---|
| CR061-FB-001 | defect | 同一 dispatch 在 CP result、audit 或 handoff 中得到不同 terminal 结论 | projection convergence rework |
| CR061-FB-002 | defect | `dispatch_id` 被回退为 `event_id`，或 typed attempt 缺身份仍 PASS | dispatch identity rework |
| CR061-FB-003 | defect | virtual bootstrap/Story admission 强制 READY 或 dependency projection 漏阻断 | admission projector rework |
| CR061-FB-004 | defect | required read 与 read-expansion 登记形成死锁 | Host preregistration rework |
| CR061-FB-005 | defect | logical `process/...` 在 paired layout 下找错仓或输出绝对路径 | binding consumer rework |
| CR061-FB-006 | defect | ledger migration 重写历史、重复追加或无法幂等 replay | migration hard stop |
| CR061-FB-007 | defect | helper 测试绿但真实 CLI 不可发现或契约不同 | Public Operation Registry / L3 rework |
| CR061-FB-008 | governance | usage 总账缺阶段或 proxy 方法不可复算 | usage closure correction |

## 发布后观察计划

| Signal ID | 信号 | 触发阈值 | 动作 |
|---|---|---|---|
| CR061-OBS-001 | terminal consumer divergence | 任意 1 个可复现差异 | HIGH defect，停止新投影 |
| CR061-OBS-002 | admission false READY | 任意 1 次 | BLOCKER，停止 Story 启动 |
| CR061-OBS-003 | absolute process path | 任意 1 条设备路径 | BLOCKER，禁止 publication evidence |
| CR061-OBS-004 | append-only replay 非幂等 | 任意 1 次 mutation drift | BLOCKER，停止 apply |
| CR061-OBS-005 | registry public operation 不可达 | 任意 1 个 documented operation | HIGH defect |
| CR061-OBS-006 | 同 tuple status-sync 重复 mutation | 任意 1 次 | HIGH defect |

## 台账边界

反馈只形成事实和分流输入，不自动创建 follow-up CR，不递归启动治理实现。正式变更必须重新分类、冻结 scope 并走相应人工门。
