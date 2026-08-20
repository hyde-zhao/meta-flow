---
status: release_candidate
version: "0.6.3"
base_version: "0.6.2"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.3 发布说明

## 摘要

0.6.3 是基于已发布 0.6.2 的 CR-074 补丁候选，主题为 Formal Truth Partition & Atomic Lifecycle Recovery。它统一 native 与已登记 legacy formal CR 的真相分区，并把 Work 状态变化收敛为零写计划、typed apply、可检查和可恢复的原子事务。

当前文档只描述 release candidate，不表示 0.6.3 已发布。CR-074 聚合 CP7 为 `PASS_WITH_RISK`；版本元数据已经统一到 0.6.3，并通过版本/资产命名定向检查，但 source freeze、source qualification、构建、installed-artifact canary、CP8、Git commit/tag 和远端发布均未执行或确认，因此当前 `release_decision=NOT_READY`。

| 项目 | 内容 |
|---|---|
| 已发布基线 | 0.6.2 |
| 目标版本 | 0.6.3 |
| 发布范围 | CR-074，Work A / Work B，共五个 Story |
| 已有质量结论 | CP7 `PASS_WITH_RISK`；无当前功能 blocker |
| 当前发布结论 | `NOT_READY` |
| full policy | `NOT_RUN`；本切片采用 no-full policy，不运行 full suite |
| 发布后跟进 | quant-lab CR-175 / installed 0.6.3 acceptance，独立授权、独立证据、非发布阻断 |

## 版本号决策

SemVer 分类器因新增公共 CLI 与 schema，真实建议为 `next-minor / 0.7.0`，并对所选 0.6.3 返回 `REQUESTED_VERSION_SEMVER_MISMATCH`。用户已明确选择从已发布 0.6.2 升级到 0.6.3；该选择是单次、不可复用、非 precedent 的 `PASS_WITH_RISK` 决策，不能改写机器分类，也不豁免 breaking/unknown compatibility。该版本用于承载 CR-074 的 formal truth、状态投影和 Work lifecycle 修复；它不声明数据库、凭据、外部服务或消费者数据迁移。公共 CLI 和 contract 有新增及 fail-closed 强化，最终兼容性仍须由 0.6.3 qualification 与 isolated installed-artifact canary 证明，不能由 CP7 source evidence 代替。

## 用户可见变化

| Change ID | 用户可见变化 | 行为边界 |
|---|---|---|
| REL-074-01 | native `CR-xxx` 与已登记 historical legacy alias 使用同一个 deterministic formal-truth partition snapshot | 已登记 legacy bytes 保持不可变；未登记 non-native contamination 或 native/legacy ID 重叠会 fail closed |
| REL-074-02 | `cr status-sync` 的 discovery、index、summary 与 state consumer 共享同一 partition digest | 相同 tuple 收敛为 `NO_CHANGE`；registry/OID/preimage 漂移在写入前阻断 |
| REL-074-03 | `STATE.current.json` 与 CURRENT 的 generation lineage、formal projection 和五个精简字段统一收敛 | `current_phase`、`active_change`、`active_story`、`pending_gate`、`next_action` 漂移不再被静默保留 |
| REL-074-04 | `state projection-correct` 只接受可证明可修复的 stale lineage | `PARTIAL`、损坏或歧义 lineage 继续阻断；成功修复只追加 successor receipt，重复 apply 为 `NO_CHANGE` |
| REL-074-05 | 新增 `work status-transition` 的 plan/apply/inspect/recover 公共链路 | plan 零写；apply 需要绑定 plan digest、OID、preimage 与目标集合的 typed authorization；非零 mutation 不会伪装成 `BLOCKED/0` |
| REL-074-06 | `work start/pause/resume/block` 成为安全 status-transition alias | alias 默认遵循相同零写计划与 typed apply 契约，不再绕过事务 coordinator |
| REL-074-07 | HANDOFF 由 canonical route profile 自动判定并绑定父事务 | routine direct G0/G1 不要求 HANDOFF；G2 functional-agent 或 legacy CP compatible Work 在 pause/block 时要求 HANDOFF；direct handoff writer 不再是状态变更入口 |
| REL-074-08 | post-close 使用 typed profile 处理 active/completed phase、无 ISSUE / 无 follow-up 与 capability resolution | 缺失或未解析的 required capability 继续阻断，不再由本地推断扩张批准范围 |
| REL-074-09 | 五个已批准 capability alias 完成登记并进入 authoritative checks | capability 证据为 `5/5`；不得把未批准 alias 或 release context 内容当作新增授权 |
| REL-074-10 | public operation inventory 增加 reverse coverage 与 provider mutation admission 对账 | 当前合同、contracted mutation 与 provider admission 已定向验证；legacy 存量不被伪装成已合同化 |

## Legacy routes 兼容边界

CR-074 保留 72 条 historical callable mutation routes，分类为 `LEGACY_UNCONTRACTED_CLI_BASELINE`。这些路线仍由 provider admission 判定 mutation mode，但尚未成为 `PublicMutationContractV3`；0.6.3 不宣称公共 mutation contract 已覆盖全部 legacy routes。其后续收敛属于 public operation convergence，不得在本发布中隐式扩大。

Formal CR 的规范身份仍是 `CR-xxx`；`MF-xxx` 仅可作为已登记 historical alias 使用。升级不会批量改写 legacy 记录，也不会把未登记 legacy CR 自动提升为 authoritative truth。

## Governance Truth Map / Retention Policy

- Governance Truth Map 继续区分 canonical machine truth、append-only event 与可重建 summary；CR-074 的 `cr_type=process`、`conflict_keys=[bootstrap, adoption-readiness]` 不会因发布文档而改变。
- Retention Policy 继续保护历史 CR、Work、transaction manifest、receipt、legacy evidence 与 release evidence；迁移、修复和回滚都不得删除或覆盖有效失败事实。

## Context sufficiency / read expansion governance

- 发布准备继续使用 capsule-first、deny-default 与最多五对象的有界读取；需要全文扩读时写入 `READ-EXPANSION-LEDGER`，并保留合法 reason 与证据。
- Story Return、CP summary、Decision Brief 与 release context 继续服从 output profile budgets；full profile 只增加发布影响面的完整性，不复制完整上游报告或日志。

## Failure routing / waiver governance

- 失败继续按 `FAILURE-ROUTING.json` 路由，waiver 继续受 `WAIVER-POLICY.json` 约束；风险接受不能伪装成测试通过。
- 未授权操作、凭据读取、缺失必需证据、错误 mutation count、不可恢复 lineage、未完成 qualification/build/canary/CP8 与缺少 publication authorization 均为不可豁免项，当前只能维持 `NOT_READY`。

## 验证摘要与 no-full policy

- Work A 的 S01-S03 和 Work B 的 S04-S05 均有 current CP6 `PASS` 证据；聚合 CP7 successor 为 `PASS_WITH_RISK`。
- R1 shared projection/state lineage 为 `PASS`；R2 legacy/capability registry 为 `PASS`，capability `5/5` 且 legacy bytes mutation 为 0；R3 post-close/formal truth 为 `PASS_WITH_RISK`，authoritative post-close 为 `PASS`、finding count 为 0。
- 验证使用 targeted、compatibility 与 structural evidence；full suite 明确为 `NOT_RUN`。当前 no-full policy 禁止为了发布文档或候选收敛补跑 full；若候选 fingerprint 或影响面超出批准切片，应停止并重新决策，而不是静默执行 full。
- 0.6.3 版本真相与 README/release asset pattern 已通过定向检查；source qualification、wheel/sdist build、receipt/sidecar qualification 与 isolated installed-artifact canary 尚未执行或确认。source 测试不能冒充 installed-artifact claim。

## 已知风险与待决事项

| Risk ID | 当前状态 | 发布影响 |
|---|---|---|
| `R-074-WB-STRUCTURE` | MEDIUM，open-owned | transaction primitives 仍分散在大型历史模块；CP8 必须显式接受，且 CR-075 S01-S03 前须完成 P6 convergence；禁止新增第五个 kernel |
| `R-074-SCOPE-AUTHZ-EVIDENCE-KIND` | MEDIUM，`scope_authz_consistency=NEEDS_REVIEW` | 与 authoritative post-close PASS 分开记录；CP8 前不得消音或改写成全绿 |
| `R-074-LEGACY-PUBLIC-ROUTES` | LOW，open | 72 条 legacy callable mutation routes 尚未合同化；当前只有显式分类与 provider admission 保护 |
| `CR074-QUANT-LAB-CR175-REPLAY` | deferred-after-release-independent | 0.6.3 发布后再做独立 acceptance；不阻断 0.6.3，但当前也不得声称已执行或已通过 |

## 破坏性变化、迁移与回滚

- 无数据库、凭据、外部服务或批量历史数据迁移。
- mutating lifecycle 的操作方式被 fail-closed 强化：先 plan，再以 typed authorization apply；中断后使用 inspect/recover，不能直接修文件或重复执行。
- HANDOFF 的创建由 status-transition 与 route policy 所有；直接 handoff writer 不再承担状态转换。
- 详细升级兼容性见 `docs/release/MIGRATION.md`；发布后回滚目标固定为已发布 0.6.2，见 `docs/release/ROLLBACK.md`。

## 授权边界

本候选不授权或证明以下动作：Git commit/push/tag、GitHub Release、PyPI/registry upload、真实发布、安装到外部项目、quant-lab 读取/运行/写入、runtime/SaaS/production write、交易、凭据或 secret 读取。qualification、build、canary 与 CP8 也仍需按发布序列和独立授权执行。

## 关联文档

- 部署检查：`docs/release/DEPLOY-CHECKLIST.md`
- 迁移：`docs/release/MIGRATION.md`
- 回滚：`docs/release/ROLLBACK.md`
- 反馈与发布后 quant-lab acceptance：`docs/release/FEEDBACK.md`
- 动态发布真相：`process/release/RELEASE-CONTEXT.yaml`（当前已切换为 CR-074 / 0.6.3 release candidate，仍保持 `NOT_READY`）
