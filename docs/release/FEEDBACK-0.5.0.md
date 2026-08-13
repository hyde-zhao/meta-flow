# Meta Flow 0.5.0 发布后反馈

## 观察信号

| 信号 | 预期 | 需要行动的阈值 |
|---|---|---|
| Work-init plan | lineage/governance 可预见问题零写 `BLOCKED` | 任一 plan `READY` 后因相同 preimage 报 legacy-tail ambiguous |
| Work-init apply | `PASS` 或 exact `RECOVERED` | 无 manifest 的 `PARTIAL_MUTATION` |
| init-inspect | terminal transaction 为 `PASS`；旧 partial 可给出绑定计划 | 无法绑定 Work ID、OID 或 exact digest |
| close-inspect | 接受合法后继，拒绝外部 drift | 合法多 Work 顺序被误判，或外部 drift 被接受 |
| projection | State/CURRENT/governance 成功后同时 current | Work-init `PASS` 后任一 projection stale |

## 反馈分流

- 可重复的 lineage/transaction 一致性错误：缺陷。
- 新对象或新 lifecycle 的需求：backlog，不扩入 0.5.0 热修。
- 外部项目 OID、dirty path 或权限问题：环境/consumer admission，不伪装为 provider 缺陷。
- 凭据、生产运行或真实安装问题：必须先取得独立授权再诊断。
