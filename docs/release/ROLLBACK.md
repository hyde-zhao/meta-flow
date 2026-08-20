---
status: release_candidate
version: "0.6.2"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.2 Rollback

## 回滚边界

已发布回滚目标为 0.6.1。回滚不得删除或改写 0.6.2 的 append-only ledger、receipt、Story/Work/CR 历史或 release-order evidence。

| Trigger | 动作 | 验证 |
|---|---|---|
| qualification/build/canary 失败 | 停止当前 lineage，保留失败证据，不重做已计数动作 | state 未越过失败步骤 |
| source freeze 后源码漂移 | 失效 lineage；旧 qualification/canary 不可复用 | successor fingerprint 明确阻断旧证据 |
| breaking/unknown compatibility | 阻断 0.6.2，回设计/版本决策 | compatibility gate BLOCKED |
| 本地候选未发布 | 保留候选与证据，不破坏 Git 历史 | 远端无 v0.6.2 事实 |
| 发布后出现回归 | 在独立授权下回退到 0.6.1 | 0.6.1 installed artifact READY |

禁止 `git reset --hard`、强推、删除 tag 或手工删除 ledger/receipt。非终态 native transaction 必须用同版本 inspect/recover 收敛。
