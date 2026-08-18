---
status: candidate
version: "0.6.0"
release_artifact_profile: full
release_decision: NOT_READY
---

# 0.6.0 Rollback

## 回滚边界

回滚目标为 0.5.3。程序包回滚与过程仓状态回滚不是同一动作：0.6.0 产生的 append-only revision/receipt 不得删除或改写；旧 reader 不理解 V2 correction，因此不能在含 V2 manifest 的过程仓上直接恢复写操作。

## 触发与步骤

| 场景 | 处理 |
|---|---|
| 尚未执行任何 0.6.0 writer | 可回退程序包，随后以 0.5.3 只读检查确认；不要复用 0.6.0 plan |
| 已有 terminal 0.6.0 事务但无 V2 correction | 保留 append-only evidence；先用 0.6.0 inspect 证明 terminal，再由人工决定是否允许旧工具只读 |
| 已产生 V2 correction manifest | 禁止直接运行 0.5.3；保持 0.6.0 inspector，或从升级前双仓/runtime 精确快照恢复后再验证 |
| 非终态或恢复失败 | 停止；保留现场，使用同版本 native inspect/recover，不做手工文件回滚 |

## 回滚验证

- 双仓 OID、dirty inventory 和目标 preimage 与获批回滚计划一致；
- project/work/cr/state/projection 检查无未决事务；
- 不删除 correction receipt、scope revision、event ledger 或其他 append-only lineage；
- 不执行 `git reset --hard`、递归清理、强推或外部 consumer 写入。
