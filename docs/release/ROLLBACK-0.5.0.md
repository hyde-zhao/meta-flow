# Meta Flow 0.5.0 回滚方案

## 回滚目标

回到发布前 `meta-flow` 与 `meta-flow-process` 的已知远端提交；保留 `v0.5.0` 标签和 GitHub Release 审计记录，必要时将 Release 标记为不推荐使用，不改写公开历史。

## 前置检查

1. 运行 `meta-flow work init-inspect --project-root <release-root>`。
2. 若存在 `PREPARED`、`APPLYING` 或 `PARTIAL` Work-init transaction，先使用 0.5.0 native recovery 收敛；未收敛前不得降级。
3. 确认没有消费者正在执行 Work-init、Work-close 或 Phase transition。

## 回滚动作

1. 基于发布前提交建立修复分支或 revert 提交，不使用 force push。
2. 配对恢复 provider 源码和过程仓 writer qualification/baseline。
3. 重新运行目标版本的 targeted、compatibility、full 与安装 dry-run。
4. 推送普通修复提交，并在 GitHub Release 中记录降级原因。

## 不可自动回滚项

- 已由 0.5.0 写入的 terminal Work-init transaction manifest 属于审计证据，不删除。
- 已完成的 consumer native recovery 不反向重建原 `PARTIAL_MUTATION`。
- quant-lab 或其他消费者的安装/恢复需要独立授权，本发布不自动触发。
