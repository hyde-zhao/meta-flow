---
status: ready-for-cp8-review
version: "0.4.1"
release_artifact_profile: compact
release_decision: READY_WITH_RISK
---

# CR-045 Deploy Checklist

## 发布前输入

| 输入 | 状态 | 证据 / 说明 |
|---|---|---|
| Release Context | PASS | `process/release/RELEASE-CONTEXT-CR045.yaml` |
| CP7-R6 | PASS | `process/checks/CP7-CR045-R6.result.json`；0 BLOCKER、0 未关闭实现 HIGH |
| Fact Diff | PASS | 3/3 承诺有正向执行证据，0 missing required |
| Recovery ordering | READY_WITH_RISK | CP2 / CP5 为历史 CP6 后的恢复审批，未倒填时间，需 CP8 明示接受 |
| Repository hygiene | PASS | `CR045-O-001-R4`：Host 已清理 ignored Python test caches；`PYTHONDONTWRITEBYTECODE=1 uv run --no-sync python scripts/check_delivery_guardrails.py` 返回 `OK`。 |

## 影响面验证

| 平台 / 组件 | 场景 | 适用性 | 结果 / 证据 |
|---|---|---|---|
| All / route planner | process CR route 正向、负向与 profile 组合 | 适用 | PASS；`tests/test_route_plan.py` |
| All / CP result | N/A、WAIVED、waiver ref 与 dispatch 语义 | 适用 | PASS；`tests/test_cp_result_event_ledger.py` |
| All / state transition | pass-like、失败决策、授权与 workflow-health stop reason | 适用 | PASS；`tests/test_state_transition.py` |
| Codex / Claude / Qoder installer | fresh install、upgrade、重复安装、uninstall | 不适用 | CR-045 未修改安装器、平台路径或安装 scope |
| Runtime / external systems | live、production、external write | 不适用 | 未授权且不在发布范围 |

## 发布候选检查

| Check ID | 检查项 | 状态 | 完成条件 |
|---|---|---|---|
| CR045-DEP-001 | 仅包含 CR-045 代码、测试和本 compact 文档范围 | PASS | 当前 diff summary 与 handoff 一致 |
| CR045-DEP-002 | approved-CP8 完整终态边界矩阵 | PASS | `9/9`；`process/evidence/CR045-S1.CP7-R6.index.json` |
| CR045-DEP-003 | 分层回归 17 / 113 / 329 | PASS | `process/docs/quality/TEST-REPORT-CR045-R6.md` |
| CR045-DEP-004 | delivery guardrail 无 test cache 污染 | PASS | Host 清理 ignored cache 后重跑得到 `OK`。 |
| CR045-DEP-005 | CP8 人工接受恢复审批历史 | PASS | CP8 checklist 已记录风险接受 |
| CR045-DEP-006 | 本地 commit / push 有独立授权 | AUTHORIZED | 用户于 2026-07-11 明确授权；执行结果回写 CR-045 post-close integration |
| CR045-DEP-007 | dispatch 平台 receipt | PARTIAL | session-observed；仓库不可独立验证，移交 CR-A S01 |

## 结论与授权边界

CR-045 已由 CP8 关闭为 `READY_WITH_RISK`。原 CP8 不授权 commit/push；用户随后单独授权本地 commit 和 push。该授权仍不包括 release execution、deployment、runtime、凭据读取、外部调用、生产或数据写入。准确 terminal 字段为 `next_action.stop_reason=delivered`，不是顶层 `STATE.stop_reason`。
