---
status: release_candidate
version: "0.6.3"
base_version: "0.6.2"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.3 Deploy Checklist

## 当前发布状态

| 输入 | 当前状态 | 放行要求 |
|---|---|---|
| 已发布基线 | 0.6.2 | 回滚与兼容性比较均以 0.6.2 为准 |
| CR-074 聚合 CP7 | `PASS_WITH_RISK` | 保留两项 MEDIUM 风险与 legacy route 风险，不改写为全绿 |
| `R-074-WB-STRUCTURE` | open-owned | CP8 对 0.6.3 显式风险接受；P6 convergence owner 保持有效 |
| scope/authz | `NEEDS_REVIEW` | CP8 显式审查 `R-074-SCOPE-AUTHZ-EVIDENCE-KIND` |
| full suite | `NOT_RUN` | 遵守 no-full policy；不为候选或发布补跑 full |
| quant-lab CR-175 replay | deferred-after-release-independent | 不进入 0.6.3 发布硬门；发布后另行授权与留证 |
| release qualification / build / canary / CP8 | 未执行或未确认 | 逐步完成后才可改变 `NOT_READY` |

## 发布序列

以下步骤必须按同一 frozen candidate lineage 顺序执行。只有已有机器证据的步骤可以勾选；不得把计划项表述成已完成证据。

- [x] 1. 将 `pyproject.toml`、`uv.lock` 与 `meta_flow.__version__` 等版本真相统一到 0.6.3，并运行仅针对版本与受影响面的检查。
- [ ] 2. 生成 0.6.3 provider targeted/compatibility/closure 证据，并以 fingerprint currentness 复用历史 full 基线；`candidate_full` 必须写成复用证明，禁止执行 full。
- [ ] 3. 生成独立 dispatch、scanner qualification 与 final consumer manifest，全部零计数和 cross-link 闭合。
- [ ] 4. 取得固定 v10 create-only typed authorization，执行 activation-receipt-v10 plan/apply exactly once；v1–v9 bytes 必须不变。
- [ ] 5. 运行 v10 loader/package/currentness 定向检查，确认 fixed locator 为 `CURRENT`，且源码 receipt materialization count=1。
- [ ] 6. 在独立 Git 授权下建立 0.6.3 双仓 source freeze；文档修改、CP7 PASS 或 v10 materialization 不等于 commit 授权。
- [ ] 7. 在 frozen lineage 上绑定 0.6.3 typed SemVer selection、exact release/process OID、CR-074 CP7 successor、scope 与 source fingerprint；确认无未登记 dirty path。
- [ ] 8. 复核 no-full policy：full 保持 `NOT_RUN`；以 fingerprint 影响面机器证据证明已有 targeted/compatibility/structural 证据仍 current；若超出批准切片则停止并重新计划，不静默扩展测试。
- [ ] 9. 审查 `R-074-WB-STRUCTURE`、`R-074-SCOPE-AUTHZ-EVIDENCE-KIND` 和 `R-074-LEGACY-PUBLIC-ROUTES`，确认仍无 blocker。
- [ ] 10. 对 frozen source 执行一次 provider source qualification；要求 authoritative、dirty paths 为 0、build count 为 0。
- [ ] 11. 执行一次 0.6.3 wheel/sdist 构建，并原子生成 canonical `ProviderArtifactReceiptV1.json` 与 `ProviderArtifactReceiptV1.digest-policy.json`；artifact bundle materialization count=1，禁止重复。
- [ ] 12. 在 clean home、non-editable 环境对 exact wheel 执行一次 isolated installed-artifact canary；禁止从 provider checkout fallback import。
- [ ] 13. 运行 0.6.3 CP8 auto result 与人工 gate；fact diff 必须保留风险、`NEEDS_REVIEW`、no-full 与 deferred quant-lab acceptance。
- [ ] 14. 仅在 CP8 后取得新的 typed Git/publication authorization，再执行 push、`v0.6.3` tag、GitHub Release 或 registry 操作。
- [ ] 15. 核验远端 tag、release asset count 与 SHA-256 后，才可将状态推进为 `RELEASED` 并执行 native close。

任何乱序、重复 activation-receipt materialization/qualification/build/artifact-bundle materialization/canary/CP8、freeze 后源码漂移、缺少 risk acceptance、installed-artifact claim 缺失或未经授权的 Git/外部写入都必须 hard fail，保持 `NOT_READY`。

## 影响面验证矩阵

| 影响面 | 发布前检查 | 当前状态 |
|---|---|---|
| Formal truth partition | native 与 registered legacy 共用一个 deterministic snapshot；unregistered contamination 与 ID overlap 阻断 | source CP7 PASS；installed 0.6.3 待 canary |
| CR status-sync | discovery/index/summary/state 共用 partition digest；same tuple 为 `NO_CHANGE`；registry/OID/preimage drift 零写阻断 | source CP7 PASS；qualification 待执行 |
| State/CURRENT | 五字段投影、pending gate 与 generation lineage 一致；不可修复 lineage fail closed | source CP7 PASS_WITH_RISK；installed 0.6.3 待 canary |
| Work status-transition | plan 零写；typed apply 精确目标；PARTIAL/RECOVERED 可 inspect/recover；replay 为 `NO_CHANGE` | source CP7 PASS_WITH_RISK；installed 0.6.3 待 canary |
| Route-aware HANDOFF | G0/G1 routine direct 不要求；G2 functional-agent / legacy CP 在 pause/block 时要求；active 不要求 | source CP7 PASS；installed 0.6.3 待 canary |
| Post-close / capability | typed profile、authoritative child reports、五个 approved aliases 与空批准范围不扩张 | source CP7 PASS_WITH_RISK；scope/authz 待 CP8 review |
| Public operation inventory | 当前 contracts、contracted mutation routes 与 provider admission reverse coverage 对账 | source 定向检查 PASS；72 条 legacy route 明确保留为未合同化基线 |

## Qualification、构建与 canary 放行条件

| 阶段 | 必须证明 | 不得声称 |
|---|---|---|
| qualification | frozen source、exact OID/fingerprint、0.6.3 版本一致、授权与 dirty-path 预检通过 | 不能用现有 CP7 或本地 pytest 代替 |
| build | 一个 wheel、一个 sdist、`ProviderArtifactReceiptV1.json` 与 `ProviderArtifactReceiptV1.digest-policy.json`，名称与摘要一致 | 当前未构建；不能引用 0.6.2 资产作为 0.6.3 资产 |
| canary | clean-home 安装 exact wheel；public version 为 0.6.3/READY；checkout import=false；J1/J2/J3 installed journeys 通过 | 当前未执行；source fixture 不能冒充 installed claim |
| CP8 | fact diff、风险接受、不授权项、no-full 与 quant-lab deferred follow-up 全部可见 | 当前 pending；CP7 `PASS_WITH_RISK` 不等于 CP8 完成 |

canary 的 J1/J2/J3 只验证 Meta Flow 自有 fixture：formal partition、repairable successor lineage 与 route-aware handoff。quant-lab CR-175 replay 不属于 pre-release canary，必须留到 0.6.3 发布后独立执行。

`activation-receipt-v10.json` 是 source-freeze 前由 package-owned create-only writer 生成的源码 receipt；`ProviderArtifactReceiptV1.json` 与 sidecar 是 build 后的 artifact bundle。两类 materialization 使用不同计数和授权，不得合并、互相替代或复用 0.6.2 证据。

## No-full policy

- 0.6.3 当前采用 targeted → compatibility → structural 的有界验证链；full suite 必须保持 `NOT_RUN`。
- 不得因准备 release notes、版本元数据或 artifact 而自动触发 full。
- 候选 fingerprint 不变时复用 current CP7 source evidence；命令、环境、scope 或 source 漂移时只重跑失效的批准层。
- 若 impact analysis 判定 targeted/compatibility/structural 已不足，发布状态保持 `NOT_READY`，由用户重新决定验证范围；不得自行补跑 full。

## 风险与人工决策

| 风险 | CP8 必须确认的内容 | 未确认时 |
|---|---|---|
| `R-074-WB-STRUCTURE` | 大型历史 transaction modules 的结构风险由 P6 convergence 持有，CR-075 S01-S03 前禁止新增第五个 kernel | `NOT_READY` |
| `R-074-SCOPE-AUTHZ-EVIDENCE-KIND` | `scope_authz_consistency=NEEDS_REVIEW` 是独立风险，不是 post-close finding，也不扩大 runtime/外部授权 | `NOT_READY` |
| `R-074-LEGACY-PUBLIC-ROUTES` | 72 条存量 route 仍为 `LEGACY_UNCONTRACTED_CLI_BASELINE`，仅有 admission 保护，不宣称 V3 合同完成 | `NOT_READY` |
| quant-lab acceptance | 明确为发布后独立 follow-up，不作为当前 release fact，也不由 CP8 授权 | 不阻断 0.6.3；不得提前执行 |

## 当前不授权项

| Item ID | 操作 | 当前状态 | 所需边界 |
|---|---|---|---|
| NA-074-01 | Git commit/push、branch mutation | 未授权 / 未执行 | exact candidate 的独立 Git authorization |
| NA-074-02 | 创建或推送 `v0.6.3` tag、GitHub Release | 未授权 / 未执行 | CP8 后 typed publication authorization |
| NA-074-03 | PyPI/registry upload | 未授权 / 未执行 | 独立外部发布授权 |
| NA-074-04 | quant-lab 读取、运行、安装或写入 | deferred / 未执行 | 发布后 exact target、scope 与 capability authorization |
| NA-074-05 | runtime、SaaS、production、trading 或凭据读取 | 未授权 / 未执行 | 独立高风险授权；不由本发布隐式授予 |

CP8 approve 只决定 release readiness；它不自动授权 Git、tag、远端发布、registry、外部项目、生产或凭据操作。
