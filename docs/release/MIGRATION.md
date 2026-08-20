---
status: release_candidate
version: "0.6.3"
base_version: "0.6.2"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.3 Migration

## 迁移结论

0.6.2 → 0.6.3 不要求数据库、凭据、外部服务或批量消费者数据迁移，也不批量改写历史 Work、Story、CR、ledger、receipt 或 registered legacy evidence。主要变化是公共治理行为的 fail-closed 强化：formal truth 使用统一分区快照，Work 状态变化使用 typed 原子事务，State/CURRENT 只接受可证明的 successor lineage。

0.6.3 当前仍是 `release_candidate / NOT_READY`。以下步骤描述发布后的升级方式，不表示 0.6.3 artifact、qualification、canary 或远端 release 已存在。

## 对象兼容性矩阵

| 对象 | 0.6.3 变化 | 兼容性 | 升级动作 |
|---|---|---|---|
| Formal CR identity | native ID 规范为 `CR-xxx`；`MF-xxx` 仅作已登记 historical alias | fail-closed strengthening | 保持 registered legacy bytes 不变；未登记 non-native contamination 先登记/处置，不手工并入 authoritative index |
| Formal truth snapshot | native、registered legacy、contamination 与 registry digest 在一次 discovery snapshot 中关闭 | compatible safety fix | 消费同一个 partition digest；禁止 consumer-local rediscovery |
| CR status-sync | discovery/index/summary/state 共用 snapshot；same tuple 为 `NO_CHANGE` | compatible safety fix | 先 plan；apply 使用 exact authorization；registry/OID/preimage drift 时重新计划 |
| State/CURRENT | `current_phase`、`active_change`、`active_story`、`pending_gate`、`next_action` 与 generation lineage 收敛 | fail-closed strengthening | 运行只读 inspect；仅对 recoverable stale lineage 使用 typed correction，不手工编辑投影 |
| projection-correct | 只追加可证明 successor receipt；拒绝 partial/corrupt/ambiguous lineage | fail-closed strengthening | 被拒绝时保留证据并修复 lineage 根因；不得强制覆盖 |
| Work lifecycle | `status-transition` 提供零写 plan、typed apply、inspect/recover | additive command + stricter mutation contract | 旧脚本改为 plan → authorization → apply；中断后 inspect/recover，不重复 apply |
| Work aliases | `start/pause/resume/block` 统一路由到 status-transition | behavior tightening | 不再假设 alias 直接写；处理 `BLOCKED`、`PARTIAL`、`RECOVERED`、`NO_CHANGE` typed result |
| HANDOFF | 由 postimage Work 与 route profile 自动判定，并作为 parent-bound child transaction | behavior tightening | routine direct G0/G1 不提交 HANDOFF；G2 functional-agent 或 legacy CP pause/block 提供匹配 postimage 的 HANDOFF |
| Post-close | typed profile 接受合法 active/completed phase 与 ready/no-issue/no-follow-up 组合 | compatible safety fix | 保持 project binding、final CP8 与 capability resolution 可追溯；缺 child report 或 alias 时 fail closed |
| Capability alias | 五个已批准 alias 登记并由 authoritative checks 消费 | compatible registry fix | 不从 release context 或本地文本推导新增 alias；未知 alias 先走独立治理 |
| Public operation registry | 增加 source declaration discovery、path contract 与 mutation reverse coverage | additive + fail-closed | 使用 `--project-root` 和 logical process refs；绝对 process path 不持久化 |
| Legacy public routes | 72 条 historical callable mutation routes 保留为显式 legacy baseline | compatible, incomplete contract coverage | 继续服从 provider admission；不要声称它们已经具备 `PublicMutationContractV3` |

## Legacy routes 迁移说明

- `LEGACY_UNCONTRACTED_CLI_BASELINE` 是可见的存量分类，不是 waiver，也不是已完成的 V3 合同。
- 这些路线按各自 admission mode（例如 apply flag、dry-run、output 或 recovery action）继续受 provider 保护；消费者不得绕过公共入口直接调用 writer。
- 当前合同化路线与 legacy baseline 必须互斥并共同覆盖 provider 识别到的 mutation routes。发现未知 route、重复 classification 或 provider/registry drift 时保持阻断。
- CR-074 不批量迁移这 72 条路线；后续 public operation convergence 必须逐条增加 owner declaration、path contract、authorization mode、L3 journey 与测试证据。

## 升级步骤

1. 等待 0.6.3 完成 qualification、build、installed-artifact canary、CP8 与远端发布；在此之前继续使用已发布 0.6.2。
2. 升级前使用 0.6.2 检查未完成的 Work lifecycle、CR status-sync 与 state projection transaction；任何 `PARTIAL` 或 `RECOVERY_REQUIRED` 均先由原版本 inspect/recover。
3. 从官方 0.6.3 release 获取 exact wheel、sdist、provider receipt 与 digest-policy sidecar，并校验 SHA-256。不得从 checkout 临时构建替代发布资产。
4. 在隔离环境安装 exact 0.6.3 wheel，确认 public version 为 0.6.3、runtime identity 为 READY、provider checkout import=false。
5. 对目标项目先执行只读 route health 与 public operation checks；所有 `process/...` 参数必须经项目 binding 解析，不能猜 sibling 或持久化绝对路径。
6. 运行 formal partition、repairable successor lineage 与 route-aware handoff 的 installed consumer journeys；quant-lab 不属于该发布前/安装时步骤。
7. 首次 mutation 重新生成 plan 与 typed authorization；不得复用 0.6.2 的 plan digest、OID、preimage、scope authorization 或 consumed receipt。
8. 观察一个完整 lifecycle；发现 drift、partial、legacy contamination 或 unexpected HANDOFF 时停止 mutation，并按 `docs/release/ROLLBACK.md` 处理。

## 脚本与自动化迁移

使用 0.6.2 直接 mutation 语义的自动化，应调整为：

1. 调用 plan，确认 `decision=READY` 或合法 `NO_CHANGE`，并保存 exact plan digest 与目标集合。
2. 由授权 owner 生成与 candidate OID、scope、preimage 绑定的 typed authorization。
3. 调用 apply；只接受与真实 mutation count 一致的 typed terminal result。
4. 出现中断或 child failure 时调用 inspect，再对指定 transaction 执行 recover；不得重放原 apply。
5. 对 routine direct G0/G1 与 G2 route profile 分别生成 HANDOFF 输入；禁止 caller boolean override。

## 不适用项

- 无数据库 schema migration、数据 backfill、凭据轮换、外部服务 cutover或生产写。
- 无自动 consumer project mutation，无自动 quant-lab replay，无自动 historical evidence rewrite。
- no-full policy 保持有效：升级准备只运行批准的 targeted、compatibility、structural 与 installed canary 层，不运行 full suite。
- 0.6.3 选择不等于风险接受；`R-074-WB-STRUCTURE` 与 scope/authz `NEEDS_REVIEW` 仍须在 CP8 可见。
