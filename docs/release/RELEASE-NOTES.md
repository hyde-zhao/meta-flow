---
status: frozen_candidate
version: "0.6.1"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.1 发布说明

## 摘要

0.6.1 是 CR-072 的单一聚合发布候选，同时交付消费者完整性稳定化、治理 Plan Compiler、依赖闭包、成本度量以及机器化 SemVer / 发布顺序门。本文随源码候选冻结；qualification、构建、canary 与 CP8 的运行时事实以 `process/release/RELEASE-CONTEXT.yaml` 和 CP8 result 为准。

| 项目 | 内容 |
|---|---|
| 当前版本 | 0.6.0 |
| 目标版本 | 0.6.1 |
| 发布切片 | Work A + Work B，一次聚合发布 |
| 当前结论 | `NOT_READY`，等待冻结后的单次发布序列与 CP8 |
| 中间版本 | 无；不发布 0.7.0 或 0.6.1-stabilization |

## 版本号决策

正常机器规则会因新增公共 CLI 与 schema 推荐下一个 MINOR（0.7.0）。本发布按用户明确决策选择 0.6.1，并使用仅对 0.6.1 有效、不可复用的 typed bootstrap decision；分类器不得把变更伪装为普通 PATCH。bootstrap 不覆盖破坏性兼容变更：发现 breaking 或 compatibility unknown 时仍须阻断。

## 新增能力

| Change ID | 内容 | 主要入口 |
|---|---|---|
| REL-072-01 | canonical Plan IR、Plan Compiler 与 package completeness | `meta-flow package compile` |
| REL-072-02 | affected-only closure-build 与失效传播 | `meta-flow package closure-build` |
| REL-072-03 | production-path Story contract 与 helper-only 拒绝 | Story contract / CP6 admission |
| REL-072-04 | canonical projection、append-only ledger 与 receipt 三真相归一化 | package state / receipt |
| REL-072-05 | measure-only 成本报告与 Workflow Health 接入 | `meta-flow package cost-report` |
| REL-072-06 | typed SemVer 决策和 release-order 状态机 | `semver-decide`、`release-check`、`release-advance` |

## 稳定化修复

| Change ID | 内容 |
|---|---|
| STAB-072-01 | receipt/sidecar 下载、资产命名与安装合同一致 |
| STAB-072-02 | clean-home 安装态 canary 覆盖 READY、missing、mismatch、symlink fail-closed |
| STAB-072-03 | usage admission 统一接受 routine `clarification` 阶段及既有 requirement aliases |
| STAB-072-04 | CR/Work/Phase/State 投影与已知 baseline/checker hygiene 收敛 |

## 兼容与迁移

- 新 CLI 和 schema 是向后兼容新增；旧命令入口继续保留。
- handwritten plan 不再是 canonical authority；现有消费者可继续只读，但新写入必须经 compiler/typed contract。
- 不批量改写历史 Work、Story、ledger 或 receipt；详见 `docs/release/MIGRATION.md`。
- 0.6.1 的 SemVer bootstrap 是一次性初始化事实，不成为后续版本的 waiver 或 precedent。

## 治理生命周期

- Governance Truth Map 明确区分机器真相、append-only 事件和可重建摘要；派生状态不能覆盖有效的失败停止事实。
- Retention Policy 继续约束关闭 CR 的默认上下文和历史证据保留，`cr_type` 与 `conflict_keys` 用于变更分类及冲突预检。

## Context sufficiency / read expansion governance

- 默认上下文继续采用 capsule-first 和 deny-default；必要全文扩读写入 `READ-EXPANSION-LEDGER`。
- Story return、CP summary、Decision Brief 和 Feature 设计摘要继续受 output profile budgets 约束，避免恢复与发布阶段重复复制长证据。

## Failure routing / waiver governance

- 高严重度失败按 `FAILURE-ROUTING.json` 路由，waiver 必须符合 `WAIVER-POLICY.json` 并携带 scope、expiry 和 approval ref。
- 未授权运行、凭据、缺失证据、缺少真实 dispatch、错误的 runtime-ready 声明和 canary terminal receipt 缺失均为不可豁免事项，不能被风险接受替代 PASS。

## 验证与发布证据

| 层 | 冻结前结论 | 权威后续证据 |
|---|---|---|
| targeted | PASS：41 tests + 334 subtests | CP7 Revision 2 |
| compatibility | PASS：247 tests + 397 subtests | CP7 Revision 2 |
| full | PASS：2752 tests + 725 subtests；机器影响面允许复用 | `CR-072-AGGREGATE-FULL-REUSE.json` |
| qualification/build/canary | 冻结后执行且各一次 | Release Context / release-order ledger |
| CP8 | 尚未批准 | CP8 result 与人工门 ledger |

## 已知风险

`R-072-COST` 保持 open、unwaived：结构预算通过，但当前过程/产品文件比为 3.05，且缺少可信 token telemetry。该风险必须由 CP8 显式处置，不能改写成成本目标已达成。

## 授权边界

当前仅授权发布仓与过程仓的本地提交。未授权 push、远端 tag、GitHub Release、PyPI、外部 consumer 安装/修改、生产运行、数据写入或凭据访问；因此本轮最多形成经 CP8 审查的本地发布候选，不会记录为 `RELEASED`，也不会关闭 Work、CR 或 P5。

## 回滚与反馈

- 部署与证据检查：`docs/release/DEPLOY-CHECKLIST.md`
- 迁移：`docs/release/MIGRATION.md`
- 回滚：`docs/release/ROLLBACK.md`
- 反馈：`docs/release/FEEDBACK.md`
- 动态发布真相：`process/release/RELEASE-CONTEXT.yaml`
