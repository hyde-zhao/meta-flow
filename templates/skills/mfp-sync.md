---
name: mfp-sync
roles: [maintainer]
trigger: 生产项目升级 mf 后同步 MFP resolution
inputs: [meta-flow 归档 index.json, 生产项目 .meta-flow/improvements/]
outputs: [生产项目 state.json（resolved/rejected/accepted-not-resolved/deferred）]
read: ["源码 improvements/archive/index.json"]
write: ["生产项目 .meta-flow/improvements/state.json"]
budget: 按 maintainer 预算
---

# SKILL mfp-sync

> 适用角色: meta-flow maintainer
> 触发: `mf upgrade` 后/MFP resolution 变化
> 输出: 生产项目只读状态

## 步骤

1. 确认来源项目与归档索引（`mf dev improve index --source <源码目录>`）。
2. 在生产项目根执行 `mf improve sync --project-dir <根> --source <源码目录>`。
3. 检查 `state.json`：resolved（版本/commit/tests）、rejected（理由）、accepted-not-resolved（目标/阶段）、deferred（原因/触发）。
4. 生产项目只读自己的 MFP；通知来源项目。

## 门禁

- 只有 maintainer 可同步；生产项目 manager/worker/designer 拒绝。
- 不篡改 ID、不写其他项目 MFP。

## 失败/升级

- 无网络 → 使用本地归档/快照，保持上次状态并提示。
- 下一责任: 来源项目（确认关闭）/ manager（评估）。

## 证据

- state.json、ledger `mfp.synced`。

## 反模式

- 生产项目角色自行同步；把其他项目 MFP 写进本地状态。
