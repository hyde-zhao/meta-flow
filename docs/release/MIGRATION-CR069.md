---
project_id: meta-flow
cr_id: CR-069
release_artifact_profile: full
release_decision: NOT_READY
migration_required: true
migration_execution: not-authorized
updated_at: '2026-08-10'
---

# CR-069 迁移说明

这是公共治理契约的向前迁移：新 producer 与 writer 统一进入 execution-control kernel，固定 provider receipt 只允许 package-owned materializer 创建，consumer scanner 负责验证闭合关系。它不要求改写 Git 历史或复制 legacy evidence。

1. 当前 provider receipt 为 `CURRENT` 时，策略仍是 `enforce-new`；receipt 只提高 assurance/readiness，不解锁旁路 writer。
2. receipt missing 或 stale 不恢复 caller-supplied policy，也不启用 legacy mutation。
3. relative-symlink/legacy 只保留明确的只读或显式 postcondition 边界；sibling-binding 是 canonical route。
4. 既有 ledger 不批量重写；需要纠正时使用 append-only native event。

Meta Flow 源码消费者从下一次获准安装/升级后获得该能力。外部项目必须在各自仓库中单独安装并执行 consumer acceptance；本 CR 没有修改或安装任何外部项目。当前不执行 package version bump、安装、升级、外部 consumer apply、legacy history copy、tag 或正式 release。
