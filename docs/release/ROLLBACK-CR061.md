---
status: ready-for-cp8-review
version: "0.4.1"
release_artifact_profile: full
release_decision: READY_WITH_RISK
---

# CR-061 Rollback

## 回滚摘要

| 项目 | 内容 |
|---|---|
| 回滚目标 | CR-061 前的 governance projector、dispatch/admission、read-expansion、ledger 与 public operation 行为 |
| 工程范围 | CR-061 release changed leaf allowlist 与对应测试 |
| 过程历史 | checkpoint、gate、dispatch、CR 和 migration ledger 一律保留 append-only |
| 不可回滚项 | 已记录的审计事实、typed authorization consumption 和 terminal dispatch 不得删除或倒填 |
| 决策人 | 仓库维护者；真实 Git 回退需要独立 typed authorization |

## 触发条件

| Trigger ID | 条件 | 处理 |
|---|---|---|
| CR061-RB-T01 | 同一 dispatch 在不同 consumer 得到不同 terminal 结论 | 停止新 CP 投影并回滚 projector consumer |
| CR061-RB-T02 | Story admission 强制 READY 或 dependency projection 漏阻断 | 停止 CP6 admission 并恢复前一稳定 projector |
| CR061-RB-T03 | logical `process/...` 泄漏绝对路径或在 sibling-binding 下找错仓 | 停止相应公共命令并回滚 resolver consumer |
| CR061-RB-T04 | append-only migration 删除/改写历史或 replay 非幂等 | 立即停止 migration apply，保留失败 transaction evidence |
| CR061-RB-T05 | public operation 用户入口缺失但 helper 测试仍绿 | 停止 publication，恢复前一已发布命令面 |

## 回滚步骤

1. 获取单仓 Git 变更授权，并冻结新的 CP/ledger mutation。
2. 只按 CR-061 release leaf allowlist 恢复实现与测试；不得修改过程仓历史事件。
3. 重跑 terminal/dispatch、Story admission、read-expansion、ledger migration、public operation 和 paired applicability 最小回归。
4. 重跑 Ruff、隔离 pycompile、delivery guardrail、CR tracking/audit 与双仓 diff-check。
5. 生成新的回滚 result 与风险说明；如需远端 push，再申请新的 exact-OID typed authorization。

## 回滚验证

| 验证项 | 通过条件 |
|---|---|
| terminal/dispatch | 所有 consumer 同一 projector，identity crossing=0 |
| admission | forced READY=0，typed dependency blocker 正确 |
| binding | logical process ref 正确，absolute process path=0 |
| ledger | 历史保留、successor/correction 可追溯、replay 幂等 |
| public CLI | registry 中已发布操作均能由真实顶层入口发现 |

本文件只定义可执行回退边界，不授权实际回退、commit、push 或发布。
