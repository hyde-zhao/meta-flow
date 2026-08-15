# Meta Flow 0.5.2 迁移说明

## 适用范围

从 `0.5.1` 升级到 `0.5.2`。本版本没有 State schema 批量迁移，也不要求改写历史 Work、CR、HANDOFF、usage event、base OID、close manifest 或 immutable legacy evidence。

## 升级步骤

1. 确认 Work-init、publication-close、Phase metadata 和 Phase transition 没有 `PREPARED`、`APPLYING` 或 `PARTIAL` 事务。
2. 若存在非终态事务，先用当前版本 native inspect/recover 收敛；`RECOVERED` 后停止并重新 plan。
3. 安装 GitHub Release 的 exact 0.5.2 artifact，并核验随附 `ProviderArtifactReceiptV1`。
4. 运行 `meta-flow version --format json`，要求 distribution/source/artifact/installed-payload 身份与安装收据一致，正式 mutation 还要求 `release_ready=true`。
5. 重跑项目 `project check`、`governance check`、`state check`、`work close-inspect` 与 `check cr-tracking`。
6. 若 adoption doctor 报 active-Phase-only legacy registry warning，通过原生 `project phase-metadata` 事务将现有精确 registry ref 提升为 Project owner；不得直接编辑 PROJECT/PHASE/STATE。

## 行为变化

- 外部 consumer mutation 默认拒绝 dirty/non-exact provider；只读命令仍可用于诊断。
- `meta-flow --version` 输出简短版本，`meta-flow version --format json` 输出完整 provider provenance。
- installer manifest 增加完整 source OID、source/delivery/capability/installed-payload digest 和 artifact receipt 身份。
- Project schema 新增可选 `legacy_evidence_registry_ref`；旧 active Phase 声明仍作为兼容 fallback。
- Phase metadata 对 legacy registry append 扩展为六目标原子事务，并验证 registry 输入与 Project identity。
- Phase transition 在 mutation 前验证 registry continuity、immutable digest、formal CR truth/index 和 CR tracking。

## 兼容边界

- 未声明 legacy evidence 的项目不需要迁移。
- 项目级 registry 不扫描目录、不接受 wildcard，也不会修改 legacy CR 原文或把 legacy CR 写入 native index。
- 0.5.1 不认识 Project-level legacy owner；依赖该 owner 才能保持跨 Phase CR tracking 的项目不得直接降级。
- execution-control activation receipt v6 没有轮换；它继续约束未变化的 owner source set，0.5.2 整包身份由 artifact receipt 独立证明。
