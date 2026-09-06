---
status: ready_for_publication
version: "0.6.6"
base_version: "0.6.5"
release_artifact_profile: full
release_decision: READY_WITH_RISK
---

# Meta Flow 0.6.6 发布说明

## 摘要

0.6.6 是 CR-078 的 P0 热修版本：修复 `work scope-amend` 重写 `works/*/WORK.yaml` 后不登记共享投影后继、导致该 Work 后续一切 close 族转换（resume / status-transition / close / close-inspect）永久 BLOCKED 的缺陷，并交付存量楔死仓库的原生修复出口。同时修复 consumer 报告的附录缺口与 0.6.5 治理工具自身的四个潜在缺陷。

## 用户可见变化

- `work scope-amend`（G1 / G2 current CR / legacy CR 三条 lane）在 apply 后于共享写锁内登记 successor receipt；PASS 输出 `shared_projection_successor_id`。plan preview 新增 `lineage_preflight`（close 锚点冻结，进入 plan_digest）。
- 新增 `meta-flow work shared-projection-repair`：零写 plan/inspect（COMMITTED_CURRENT / COMMITTED_STALE_REPAIRABLE / SUPERSEDED / PARTIAL / CORRUPTED 五态）+ typed apply（幂等、单次消费、绑定 inspect snapshot）；修复对象扩展到 `works/*/WORK.yaml`。
- 新增 `meta-flow work authorization-template`：从零写 plan 自动生成 typed authorization 模板（机械字段填充 + `<fill:...>` 人工占位 + field_bindings 绑定说明）。
- `cr query` 支持 `--format json`；查询 native CR 时返回 `native_cr_requires_formal_truth_query` + native 视图，不再误报 `legacy_evidence_not_registered`。
- G2 `authorized_add_writes` 通配符（含尾部 `/**`）给出显式 blocker `G2_CURRENT_CR_SCOPE_AMEND_WILDCARD_UNSUPPORTED`；G1 delta 尾通配语义不变。
- `work resume-check` 缺 HANDOFF.yaml 时返回 typed `HANDOFF_NOT_INITIALIZED`。
- `work scope-amend-inspect` 输出 `lineage_states`（每个 COMMITTED 事务的 WORK.yaml 锚定/对齐状态）。
- scope-amend 后继登记失败返回 PARTIAL（`SCOPE_AMEND_SHARED_SUCCESSOR_RECORD_FAILED`）并指向 repair 命令；最坏失败态与 0.6.5 存量楔死态同构。

## 修复的 0.6.5 治理工具缺陷

- delivered 休息态无法激活新 CR（status-sync 激活 patch 不重置 current_phase）。
- CR close 在投影 ref 干净的工作区必然失败（投影子事务先于锁内 admission 校验写入）。
- `check post-close` 的 readiness 大小写常量与 canonical 小写不匹配导致终态误报。
- post-close 不支持无 Work 的 release CR（新增 `work_binding_policy: not_required` 显式声明）。

## 兼容性与迁移

- 无数据迁移；0.6.5 存量楔死仓库升级后执行 `work shared-projection-repair` 即可解锁。
- **前向不兼容**：0.6.6 写出的 `work.scope-amend` successor receipt 被 0.6.5 读取时 fail-closed；升级后不支持降级。
- close 族事务语义与家族不变量零变化（receipt 是既有「close 之间外部 writer」机制的扩展注册）。

## 验证摘要

- CR-078 targeted：45 passed（successor 全链 / repair CLI e2e / 附录 / delivered 再入 / clean-tree close）。
- affected compatibility：288 passed，64 subtests passed。
- 冻结候选全量（排除 2 个后置门）：3609 passed，2 deselected，729 subtests passed。
- 冻结后最终无排除全量：见 qualification evidence `final_revalidation`。
- closure：detector 446 writers 0 unresolved、delivery guardrails OK、Ruff、`uv lock --check`、`git diff --check` 全部 PASS。

## 已知边界

- 0.6.6 不上传 PyPI；官方资产以 GitHub Release 的 wheel、sdist、receipt 和 sidecar 为准。
- authorization-template 的 scope-amend 分支不预跑 plan（该 plan 校验授权信封本体），机械面直接从 delta + Work/仓状态推导。

## 安装

```bash
uvx --from meta-flow==0.6.6 meta-flow --version
# 或从 GitHub Release 安装 wheel
```
