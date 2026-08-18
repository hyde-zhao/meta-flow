---
status: candidate
version: "0.6.0"
release_artifact_profile: full
release_decision: NOT_READY
---

# 0.6.0 Migration

## 迁移结论

从 0.5.3 升级需要**工具链整体切换**，不需要批量改写 Work、CR、ledger 或热修期 V1 correction 历史。0.6.0 reader 保留 V1 历史解码；0.6.0 新 correction manifest 使用 V2 identity，0.5.3 inspector 会明确拒绝。

## 兼容矩阵

| 对象 | 变化 | 兼容/迁移 |
|---|---|---|
| State projection manifest | correction 新写 V2 schema/kind | 新 reader 读 V1/V2；旧 reader 拒绝 V2；禁止 writer 混用 |
| `cr scope-amend` | 新增 V2 objective replacement | V1 authorization/revision/receipt 保持可读；V2 需精确 `--replace-objective` |
| CR summary | 删除硬编码 decision，新增 owner-derived 字段 | summary 是可重建投影；0.5.3 对真实新 summary 隔离读取 PASS |
| provider receipt | V1 字段集不变，新增 sidecar | 旧 reader 可忽略 sidecar；新 reader 对历史缺 sidecar仅在过渡窗口告警 |
| digest policy | cache/build/generated 闭合排除 | 无业务数据迁移；旧 qualification receipt 对新 policy 失效 |
| state bootstrap | 已有 manifest 时拒绝直写 | 有意收紧；改用原生 transaction，不提供 bypass |

## 升级步骤

1. 确认没有 `PREPARED`、`APPLYING`、`PARTIAL` 或 `RECOVERED` 后继续运行的事务；
2. 保存双仓 exact OID、worktree inventory 与 runtime manifest/receipt 快照；
3. 一次性升级 CLI、writer、inspector 和 detector baseline；
4. 运行 project/work/cr/state/projection 五项只读检查；
5. 在任何 mutation 前重新 plan，旧 plan/authorization 不得跨版本复用。
