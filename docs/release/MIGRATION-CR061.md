---
status: ready-for-cp8-review
version: "0.4.1"
release_artifact_profile: full
release_decision: READY_WITH_RISK
---

# CR-061 Migration

## 迁移结论

CR-061 不执行批量历史重写。新 projector 和公共命令从当前事实推导；旧 dispatch/read-expansion 事件需要规范化时，只允许追加 typed successor/correction。无法唯一关联的历史记录保持 warning 或 BLOCKED，不编造 identity、timestamp、attempt 或 receipt。

| 对象 | 变化 | 迁移策略 | 兼容性 |
|---|---|---|---|
| terminal-success projection | 是 | 新 consumer 统一读取 native projector；不改旧 terminal 行 | compatible with explicit unavailable |
| dispatch identity | 是 | 新事件必须 typed；旧行由 append-only correction 覆盖 | compatible with audit warning |
| Story CP6 evidence | 是 | bootstrap evidence 通过 frozen evidence replay；cutover 后用新 projector 重验 | compatible |
| read-expansion ledger | 是 | 原生 dry-run、apply、幂等 replay；Host 预登记 | append-only |
| CP result / checkpoint ledger | 是 | 新结果严格 correlation；旧结果保持 immutable | append-only |
| `STATE.current.json` | 否 | 合法缺失时不创建、不迁移 | N/A |
| 安装路径、依赖、外部数据 | 否 | 无迁移动作 | N/A |

## Apply 边界

- 本 CR 的 CP8 不执行 migration apply。
- 任何未来 apply 必须绑定 exact process OID、canonical plan digest、preimage、mutation allowlist 和一次性 typed authorization。
- partial mutation 必须保留 transaction/rollback evidence，不得宣称成功。
- 真实 replay 必须从公共顶层入口执行，不得只调用内部 helper。
