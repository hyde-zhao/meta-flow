# Meta Flow 0.5.0 迁移说明

## 适用版本

从 `0.4.1` 升级到 `0.5.0`。

## 行为变化

- Work-init plan 会在写入前校验 shared generation lineage 与 governance baseline currentness。
- 相同 ref、相同 `after_digest` 的多个无-lineage legacy close manifest 被视为一个可审计 generation 等价集；不同 digest 的 fork 仍阻断。
- Work-init apply 使用持久 transaction manifest；成功前必须同步并验证 State、CURRENT 和 governance projection。
- 新增 `meta-flow work init-inspect` 和 `meta-flow work init-recover`。

## 0.4.1 部分写入恢复

先运行：

```bash
meta-flow work init-inspect --project-root <release-root> --work-id <work-id>
```

只有计划为 `READY` 时，使用同一输出中的 plan digest：

```bash
meta-flow work init-recover --project-root <release-root> --work-id <work-id> \
  --plan-digest <exact-plan-digest> --apply
```

结果为 `RECOVERED` 后必须停止并重新执行 Work-init plan；不得在同一轮直接启动 Work。

## 无需迁移

- 不批量重写历史 close manifest。
- 不删除历史 successor 或 transaction receipt。
- 不要求修改 Project、Roadmap、Phase、State schema 或安装路径。
