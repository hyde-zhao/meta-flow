# Meta Flow 0.5.1 发布后反馈

## 观察信号

- `work publication-close` 在单 Work 与批量跨 Work 发布中的 READY/BLOCKED 原因。
- repair authorization 的过期、重复消费、scope/OID/blocker 漂移拒绝是否稳定。
- usage hard-stop 事件是否精确追加一次，executor 是否保持 fail-closed。
- `project.phase-metadata` 后 project/governance/state/close-inspect/phase-transition 是否持续一致。
- 安装后的 `worktree_clean`、`exact_commit_delivery` 和公共操作登记是否一致。

## 触发阈值

- 任一 PARTIAL 无法由 native recover 收敛：立即停止 consumer 推进并报告 provider defect。
- native writer 成功后出现治理投影或 shared lineage 不一致：按跨模块一致性缺陷处理。
- authorization 未漂移却错误 BLOCKED，或发生 scope 外 mutation：按安全/契约缺陷处理。

## 分流

- 回归或事务一致性失败：缺陷修复。
- 新 lifecycle/object 需求：后续 backlog，不扩入 0.5.1 热修。
- 消费者项目内容缺失：由消费者 adoption Work 处理，不回写 Meta Flow provider 历史。
