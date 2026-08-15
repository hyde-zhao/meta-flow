# Meta Flow 0.5.2 发布后反馈

## 观察信号

- `meta-flow version --format json` 的 distribution、module path、source commit/dirty、editable、artifact 和 installed payload 身份是否一致。
- 外部 consumer mutation 是否只在 exact clean provider 下放行，诊断性只读操作是否保持可用。
- clean artifact canary 是否始终从隔离 venv 导入，且 `provider_checkout_imported=false`。
- Project-level legacy registry 在连续 Phase transition 后是否持续分类同一 immutable CR。
- Phase transition 写前 post-state validator 是否对 registry 丢失、digest drift、formal CR contamination 和 index 冲突稳定 fail closed。
- Phase metadata 提升 Project owner 后，Project/governance/State/CURRENT/close lineage 是否保持一致。

## 触发阈值

- 同一 distribution version 对应不同 source/artifact digest 且正式 mutation 被放行：立即按供应链高风险缺陷处理。
- artifact receipt 与 wheel 或 installed payload digest 不一致：禁止安装/继续 mutation。
- Phase transition COMMITTED 后 mandatory post-state check 失败：按事务一致性高风险缺陷处理。
- registered legacy evidence 在跨 Phase 后消失或进入 native CR index：冻结 consumer lifecycle 并回到 provider 修复。
- 任一 PARTIAL 无法由 native recover 收敛：停止 consumer 推进，不允许手工修治理文件。

## 分流

- provenance、installer、artifact receipt 或 mutation gate 回归：provider 缺陷修复。
- registry owner、transition continuity 或 formal CR truth 回归：治理合同缺陷修复。
- consumer 缺少 registry 声明或 identity 文件：consumer adoption Work，不回写 Meta Flow 历史。
- Release/Run/Incident/Epoch 等新对象需求：后续 backlog，不扩入 0.5.2 热修。
