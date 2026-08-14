# Meta Flow 0.5.1 迁移说明

## 适用范围

从 `0.5.0` 升级到 `0.5.1`。本版本没有 State schema 批量迁移，也不要求重写历史 Work、HANDOFF、usage event、base OID、Phase 或 close manifest。

## 升级步骤

1. 确认没有 `PREPARED`、`APPLYING` 或 `PARTIAL` 的 Work-init、publication-close 或 Phase metadata 事务。
2. 若存在非终态事务，先使用当前版本的 native inspect/recover 收敛；`RECOVERED` 后停止并重新 plan。
3. 安装 exact 0.5.1 provider，并核验 `meta-flow version --format json` 中 `worktree_clean=true`、`exact_commit_delivery=true`。
4. 重新执行项目 `project check`、`governance check`、`state check`、`work close-inspect` 与 `cr-tracking`。

## 行为变化

- `work publication-close` 支持 V2 exact path coverage 和 recovery Work pending scope。
- repair Work 默认仍不可达；必须提供 single-use typed repair authorization。
- hard-stop usage event 在合法 admission 下按 append-first 记录，然后阻断 executor。
- 新增 `project.phase-metadata plan/apply/inspect/recover`，只拥有 Phase `result_refs` 的有界追加。
- activation receipt fixed locator 从 v5 轮换为 v6，v1-v5 保持 legacy 可验证。

## 兼容边界

- 直接手工编辑 shared Phase/Project/State 仍会被 lineage 检查拒绝。
- 0.5.0 不认识 Phase metadata transaction；存在非终态 metadata transaction 时不得降级。
- 本版本不自动运行 consumer mutation，也不自动创建 repair authorization 或 publication authorization。
