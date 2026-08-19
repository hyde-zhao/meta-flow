---
status: frozen_candidate
version: "0.6.1"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.1 Rollback

## 回滚边界

回滚目标是已发布的 0.6.0。程序包回退不得删除或改写 0.6.1 已产生的 append-only ledger、receipt、Story/Work/CR 历史或 release-order evidence。当前仅形成本地候选，未授权远端发布或外部 consumer mutation。

## 触发条件与动作

| Trigger | 条件 | 动作 | 验证 |
|---|---|---|---|
| RB-072-01 | qualification/build/canary 任一失败 | 停止发布序列；保留失败 evidence，不重做已计数动作 | release-order state 未越过失败步骤 |
| RB-072-02 | source freeze 后源码漂移 | 候选失效；不得复用 qualification 或 full receipt | 新 fingerprint 明确阻断旧 evidence |
| RB-072-03 | 发现 breaking/unknown compatibility | 阻断 0.6.1；调整设计或重新进入版本决策 | SemVer decision 为 BLOCKED |
| RB-072-04 | 本地候选未发布 | 不做 Git 历史破坏；保留提交并等待新指令 | 远端无 0.6.1 发布事实 |
| RB-072-05 | 未来发布后出现回归 | 由独立授权执行 0.6.0 安装/发布回滚 | 0.6.0 runtime READY，过程真相只追加不改写 |

## 安全规则

- 不使用 `git reset --hard`、强推、删除 tag 或手工删除 ledger/receipt。
- 非终态 native transaction 必须用同版本 inspect/recover 收敛。
- 0.6.1 新 CLI/schema 的消费者在回退前先确认未依赖新写入格式。
- 回滚计划不授权任何外部安装、数据写或远端操作。

动态候选 OID、artifact digest 与失败位置以 `process/release/RELEASE-CONTEXT.yaml` 为准。
