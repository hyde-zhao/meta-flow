---
status: release_candidate
version: "0.6.3"
base_version: "0.6.2"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.3 Rollback

## 回滚目标与原则

0.6.3 的发布后回滚目标固定为已发布 0.6.2。当前 0.6.3 尚未 qualification、build、canary、CP8 或发布，因此现在只有“停止候选 lineage”，不存在可声称已执行的远端回滚。

回滚只切换可执行包和入口，不删除或改写 append-only ledger、authorization、transaction manifest、receipt、Work/Story/CR 历史、release evidence 或 quant-lab follow-up 记录。禁止使用 `git reset --hard`、强推、删除已发布 tag、手工改状态投影或手工清理 transaction 文件作为回滚方法。

## 触发条件

| Trigger | 决策 | 立即动作 |
|---|---|---|
| qualification、build、canary 或 CP8 失败 | 候选失败，尚未发布 | 停止当前 0.6.3 lineage，保留失败证据与计数，不重复已计数步骤 |
| source freeze 后 OID、fingerprint、scope 或 preimage 漂移 | 旧 lineage 失效 | 阻断旧 qualification/canary 复用；重新计划，不补跑 full |
| `R-074-WB-STRUCTURE` 或 scope/authz review 未被 CP8 接受 | `NOT_READY` | 不进入 publication；回到风险决策或当前切片修正 |
| installed canary 出现 partition、lineage、transaction 或 HANDOFF 回归 | `NOT_READY` | 保留 exact artifact 与 canary 证据，停止发布 |
| 0.6.3 发布后出现高严重度回归 | 需要真实回滚 | 在独立授权下切回官方 0.6.2 artifact，并启动问题分流 |
| 仅 quant-lab post-release acceptance 失败 | 外部 follow-up 失败 | 不自动回滚 Meta Flow；按影响判定 ISSUE/CR 或风险接受，除非证明 0.6.3 通用能力回归 |

## 发布前停止流程

1. 停止 0.6.3 release sequence；不得继续 qualification、build、canary、CP8、tag 或 publication。
2. 记录失败所在步骤、exact OID/fingerprint、artifact digest（若已生成）、mutation count 与 terminal decision。
3. 对 `PARTIAL`、`RECOVERY_REQUIRED` 或非终态 transaction 使用同一候选版本的 inspect/recover；不得以再次 apply 覆盖原失败。
4. 使该 lineage 的后续 receipt 失效，并为 successor candidate 生成新的 plan、authorization 与 fingerprint。
5. 继续维持 0.6.2 为唯一已发布基线；没有远端 mutation 时不创建虚假的 rollback receipt。

## 发布后回滚流程

真实回滚需要独立 typed authorization，并由 release operator 执行：

1. 冻结新的 0.6.3 mutation，收集受影响命令、项目、transaction ID 与 installed artifact digest。
2. 在仍可运行 0.6.3 时先检查 unresolved Work status-transition、CR status-sync、state projection 和 child transaction；对非终态记录按 0.6.3 的 inspect/recover 协议收敛。
3. 从官方 0.6.2 release 获取 exact wheel、sdist、receipt 与 sidecar，校验发布时记录的 SHA-256；不得从工作树临时重建“等价 0.6.2”。
4. 在隔离环境安装 exact 0.6.2 artifact，确认 public version 为 0.6.2 且 runtime identity 为 READY。
5. 对受影响项目执行只读 route health、formal truth、CURRENT/state、未完成 transaction 与 public operation 检查；发现 0.6.3-only 非终态 manifest 时保持阻断，交回 0.6.3 recovery 工具处理。
6. 仅在验证通过后切换消费者入口；保留 0.6.3 tag、release、artifact 与全部失败证据，不强推或删 tag。
7. 创建独立 incident/ISSUE 或 CR 候选，记录是否需要修复版；`FEEDBACK.md` 本身不创建正式工单。

## 回滚验证

| 检查 | 放行条件 |
|---|---|
| 版本与 artifact | 使用官方 0.6.2 exact artifact；版本、receipt 与 sidecar 摘要匹配 |
| Formal truth | native CR 与 registered legacy 分区无新增污染；0.6.3 产生的 evidence 仍可保留读取，不被 0.6.2 重写 |
| State/CURRENT | 无手工 projection mutation；active phase/change/gate 与 canonical truth 一致 |
| Transaction | 无 unresolved `PARTIAL` / `RECOVERY_REQUIRED`；同一 authorization 未被重复消费 |
| Consumer | 受影响项目使用 0.6.2 时基础 read-only checks 通过；失败时继续隔离而不是带风险切换 |
| 外部边界 | quant-lab follow-up、production、trading、SaaS 与凭据均未因回滚隐式执行 |

## 数据与兼容性边界

- 0.6.2 → 0.6.3 无数据库或消费者数据迁移，通常不需要数据回滚。
- 0.6.3 新增的 transaction manifest、successor receipt、partition digest 与 HANDOFF child evidence 是治理历史，必须保留；0.6.2 不得尝试删除或反向改写。
- 已提交的 0.6.3 状态变化不能仅靠降级包撤销。必须先由拥有该 mutation 的版本 inspect/recover，再决定是否需要新的 typed successor。
- 72 条 legacy callable mutation routes 的合同化状态不会因二进制回滚改变；其 provider admission 与风险分类仍需独立核对。
- quant-lab CR-175 acceptance 是发布后独立 follow-up，不属于 0.6.3 artifact 回滚对象。

## 责任边界

| 事项 | Owner |
|---|---|
| 候选停止、证据封存、release decision | Host Orchestrator / release owner |
| exact artifact 安装与消费者切换 | 取得独立授权的 release operator |
| transaction inspect/recover | 对应 native operation owner |
| `R-074-WB-STRUCTURE` 后续 | P6 Transaction Primitive Convergence |
| quant-lab acceptance 或失败分流 | 独立 quant-lab follow-up owner |
