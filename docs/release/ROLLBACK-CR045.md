---
status: ready-for-cp8-review
version: "0.4.1"
release_artifact_profile: compact
release_decision: READY_WITH_RISK
---

# CR-045 Rollback

## 回滚摘要

| 项目 | 内容 |
|---|---|
| 回滚目标 | CR-045 变更前的 `0.4.0` 路由、CP result 与 state-transition 实现 |
| 范围 | `meta_flow/policies/route_plan.py`、`meta_flow/checks/cp_result.py`、`meta_flow/checks/state_transition.py` 及对应 CR-045 测试 |
| 数据恢复 | 不涉及；CR-045 不修改持久化数据或 schema |
| 不可回滚项 | 无工程不可回滚项；CP2 / CP5 的恢复审批审计历史不得删除或倒填 |
| 决策人 | 发布 / 仓库维护责任人 |

## 触发条件

| Trigger ID | 条件 | 证据 |
|---|---|---|
| CR045-RB-T01 | process CR 生成错误 checkpoint route 或错误 required gate | route check、用户报告或回归失败 |
| CR045-RB-T02 | N/A 被错误处理为 waiver，或 waiver / dispatch 校验出现兼容性回归 | CP result check 或 ledger test |
| CR045-RB-T03 | pass-like 结果保留 stale failure reason，或失败决策丢失真实 stop cause | state-transition check 或 workflow doctor |

## 回滚步骤

1. 获得独立的仓库变更 / 发布授权，并冻结新的 CR route 生成。
2. 以版本控制恢复上述三个实现模块及对应测试到 CR-045 前的已知良好版本；不得修改 checkpoint、gate、CR 或 dispatch 历史台账。
3. 运行 route-plan、CP result / event ledger、state-transition 聚焦测试与全量回归。
4. 对受影响的活动 CR 只读重算 route plan 并比较差异；如需写回状态或 route artifact，另行走 CR 和人工门禁。
5. 将回滚结果和剩余影响写入新的检查证据；真实 push / publish 仍需独立授权。

## 回滚验证

| 验证项 | 方法 | 通过条件 |
|---|---|---|
| 路由恢复 | route-plan test 与 route check | 目标基线全部通过 |
| CP 语义恢复 | CP result / ledger tests | 无 N/A / WAIVED 或 dispatch 漂移 |
| 状态恢复 | state-transition matrix | 合法 stop reason 接受、stale reason 拒绝 |
| 全量健康 | 全量 pytest 与 delivery guardrail | 0 test failure；guardrail 无阻断 |

回滚文档本身不授权执行版本控制写入、push 或 publish。
