---
status: ready-for-cp8-review
version: "0.4.1"
release_artifact_profile: full
release_decision: READY_WITH_RISK
---

# CR-061 Deploy Checklist

## 发布前输入

| 输入 | 状态 | 证据 / 说明 |
|---|---|---|
| Route / applicability | PASS | `process/checks/CP0-CR-061.route-plan.json`、`process/checks/CP8-CR-061.applicability.json` |
| C0 cutover | PASS | 3/3 replay、11/11 consumer、bootstrap/legacy consumer=0 |
| CP7 aggregate | PASS | `process/checks/CP7-CR-061-AGGREGATE-REVALIDATION-02.result.json` |
| Public Operation Registry | PASS | documented=6、undocumented=0、unknown=0、L3=4 |
| Native governance | PASS | CR tracking/audit、checkpoint/gate/dispatch ledger PASS |
| Usage closure | READY_WITH_RISK | 后半程没有完整可比总账；不得声明原 hard cap 合规 |

## 影响面验证

| 组件 | 场景 | 适用性 | 结果 / 证据 |
|---|---|---|---|
| terminal-success / dispatch | real、inline typed attempt、terminal projection | 适用 | PASS；S01 与 C0/CP7 |
| Story admission | CP5→CP6、dependency projection、bootstrap cutover | 适用 | PASS；S02/C0 |
| read-expansion / ledger migration | Host 预登记、successor/correction、幂等 replay | 适用 | PASS；S03/S04 |
| public CLI | 6 个 registry operation、4 条 L3 journey | 适用 | PASS；S05 |
| CP8 applicability | paired logical route plan 与 aggregate | 适用 | PASS；attempt-7 |
| installer / runtime / external project | 安装、迁移 apply、生产写 | 不适用 | 未授权且不在 CR-061 范围 |

## 发布候选检查

| Check ID | 检查项 | 状态 | 完成条件 |
|---|---|---|---|
| CR061-DEP-001 | 5 个 Story CP6/CP7 与 aggregate | PASS | 最终 versioned result strict consistency |
| CR061-DEP-002 | C0 cutover 后 legacy/bootstrap consumer | PASS | 0/0 |
| CR061-DEP-003 | 独立 QA 与公共入口 | PASS | attempt-7 PASS；L3 4/4 |
| CR061-DEP-004 | logical process ref 与绝对路径边界 | PASS | applicability/status-sync paired dogfood；absolute process path=0 |
| CR061-DEP-005 | full-profile 发布与回滚文档 | PASS | CR-061 五份 release artifacts |
| CR061-DEP-006 | CP8 人工批准 | PENDING | 用户明确 approve 或修改后的逐项决定 |
| CR061-DEP-007 | native close | PENDING | CP8 approved 后单独执行 |
| CR061-DEP-008 | release/process commit 与 push | NOT_AUTHORIZED | 各仓分别申请 exact-OID typed authorization |

## 授权边界

本清单不授权真实安装、ledger migration apply、native close、Git、tag 或发布。任何 publication 必须先完成 CP8 人工批准和 native close，再分别生成 release/process 单仓 typed authorization。
