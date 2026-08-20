---
status: release_candidate
version: "0.6.2"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.2 发布说明

## 摘要

0.6.2 交付 CR-073 的 Work admission、失败恢复、验证真相与受害者确认收敛。它解决 quant-lab 六轮事故暴露的关键问题：建单前无法预检、native writer 产物与业务 scope 混同、execution contract 语义错误晚爆、失败无法留证、环境漂移后 receipt 静默复用、以及未登记失败被投影成健康。

| 项目 | 内容 |
|---|---|
| 已发布基线 | 0.6.1 |
| 目标版本 | 0.6.2 |
| 发布切片 | CR-073 / RS-073-02，单一 cutover |
| 当前结论 | `NOT_READY`，等待 qualification、build、installed-artifact canary 与 CP8 |
| 中间版本 | 无 |

## 版本号决策

truthful SemVer classifier 因新增公共 CLI 与 schema 推荐 `next-minor / 0.7.0`，并对 `0.6.2` 返回 `REQUESTED_VERSION_SEMVER_MISMATCH`。用户于 2026-08-20 明确选择 `0.6.2`；该 typed selection 不可复用、不是 precedent，且必须在 CP8 以 `R-073-SEMVER-0.6.2-EXPLICIT-SELECTION` 显式披露。这不改写机器分类，也不豁免 breaking/unknown compatibility 阻断。

## 新增能力

| Change ID | 内容 | 主要入口 |
|---|---|---|
| REL-073-01 | 零写模拟 success/failure/no-op 全生命周期 | `meta-flow work init-preflight` |
| REL-073-02 | init 时强制校验 contract revision、typed ref、root concept、slice 与 digest | Work admission |
| REL-073-03 | native writer 有界 system namespace，与业务 scope 分离 | Work scope contract |
| REL-073-04 | paused/blocked G0/G1 Work 可执行只增不减、可恢复的 scope amendment | `work scope-amend*` |
| REL-073-05 | ValidationPolicyV2 将 environment/source manifest 纳入 receipt 复用判定 | validation planner |
| REL-073-06 | FAIL receipt 与 observation 缺口投影为 warning/block，不再假健康 | formal state projection |
| REL-073-07 | CR-071 historical reframe 与 quant-lab 六轮→J1/J2/J3 受害者验收 | post-close / adoption checks |

## 验证摘要

- 七个 Story 的 current CP6 result / Return / Evidence Index 均绑定精确 digest。
- affected regression：179 passed；detector：412/412 classified，0 unresolved unallowlisted。
- 最终 full 已执行且指纹前后一致：2869 passed、1 个预期 v9 STALE 残余、725 subtests、3 warnings。按用户指令不再重跑 full；版本元数据收敛后只跑 targeted/受影响回归。
- quant-lab source-candidate J1/J2/J3 回放 PASS；目标写入 0、Git mutation 0、安装 0、网络 0。
- installed-artifact victim replay 必须由本发布的隔离 canary 补齐，source-candidate claim 不能冒充安装态 claim。

## Governance Truth Map / Retention Policy

- Governance Truth Map 继续区分 canonical machine truth、append-only event 和可重建 summary；派生状态不得覆盖有效失败或 typed transition stop。
- Retention Policy 继续约束已关闭 CR 与历史证据；`cr_type` 和 `conflict_keys` 仍是变更分类与冲突预检的必要输入。

## Context sufficiency / read expansion governance

- 默认继续 capsule-first 与 deny-default；必要全文扩读写入 `READ-EXPANSION-LEDGER`。
- Story Return、CP summary、Decision Brief 和 Feature 摘要继续受 output profile budgets 约束，不因发布 cutover 复制长证据或新增解释性 Work。

## Failure routing / waiver governance

- 高严重度失败继续按 `FAILURE-ROUTING.json` 路由；waiver 必须符合 `WAIVER-POLICY.json`。
- 未授权操作、凭据读取、缺失证据、breaking/unknown compatibility、未完成 installed-artifact canary 和缺少 publication authorization 都是不可豁免项，不能用普通风险接受伪装成 PASS。

## 授权边界

当前仅授权本地 version metadata、source freeze、fingerprint、qualification×1、build×1 和 isolated canary×1。未授权 Git commit/push/tag、GitHub Release、PyPI、外部项目 mutation、生产写或凭据读取。

## 关联文档

- 部署检查：`docs/release/DEPLOY-CHECKLIST.md`
- 迁移：`docs/release/MIGRATION.md`
- 回滚：`docs/release/ROLLBACK.md`
- 反馈：`docs/release/FEEDBACK.md`
- 动态真相：`process/release/RELEASE-CONTEXT.yaml`
