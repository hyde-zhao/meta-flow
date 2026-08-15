# Meta Flow 0.5.2 回滚方案

## 回滚目标

回滚到已发布的 `v0.5.1` 源码与交付资产。

## 前置检查

1. 使用 0.5.2 inspect 检查 Work-init、publication-close、Phase metadata 和 Phase transition transaction。
2. 任一事务处于 `PREPARED`、`APPLYING` 或 `PARTIAL` 时禁止降级；先用 0.5.2 recover 收敛。
3. 查询 `PROJECT.yaml` 是否使用 `legacy_evidence_registry_ref`；若 active Phase 未同时保留等价 registry ref，降级到 0.5.1 会丢失 legacy classification，必须先停止并制定 consumer 迁移。
4. 保留 GitHub Release 中的 0.5.2 artifact receipt、source commit 和 tag 作为审计证据。

## 回滚动作

1. 从 GitHub 获取 `v0.5.1` exact artifact 和 tag commit。
2. 重新安装 0.5.1，并核验 distribution version、source OID 和 delivery digest。
3. 重跑 `project check`、`governance check`、`state check`、`work close-inspect` 与 `check cr-tracking`。
4. 只有 CR tracking 仍保持已登记 legacy evidence 且所有 native transaction terminal，才允许继续 consumer lifecycle。

## 不可破坏的历史

- 不删除 terminal transaction manifest、successor receipt、artifact receipt 或 usage event。
- 不改写旧 HANDOFF、base OID、scope、budget、result 或 legacy CR 原文。
- 不通过手工 PROJECT/PHASE/STATE 修改模拟 native migration 或 recovery。
