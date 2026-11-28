---
name: mfp-archive
roles: [maintainer]
trigger: 生产项目记录 MFP，需要归档到 meta-flow
inputs: [全局 inbox MFP, meta-flow 源码目录]
outputs: [improvements/archive/MFP-*.yaml + index.json]
read: ["~/.meta-flow/improvements/inbox/", "源码 improvements/"]
write: ["meta-flow 源码 improvements/archive/"]
budget: 按 maintainer 预算
---

# SKILL mfp-archive

> 适用角色: meta-flow maintainer（唯一归档者）
> 触发: 归档 MFP
> 输出: 归档文件与索引

## 步骤

1. `mf improve list --inbox` 查看待归档；确认来源项目与 ID（`MFP-<project>-<seq>`）。
2. `mf dev improve archive <project>/<MFP> --source <源码目录>`。
3. 检查 `improvements/archive/<id>.yaml` 与 `archive/index.json`（id/source_project/status/decision/target/resolution）。
4. 归档不等于评估：交 meta-flow manager `mfp-triage`。

## 门禁

- 只有 maintainer 可归档；生产项目 manager/designer/worker 与生产 maintainer 一律拒绝。
- 不改验收标准；不自动 push（需用户授权）。

## 失败/升级

- MFP 不完整 → 退回记录者补充，不静默归档。
- 下一责任: manager（评估）或 maintainer（同步）。

## 证据

- 归档文件、index.json、ledger。

## 反模式

- 生产项目角色代归档；改写 MFP 验收；归档后不通知 manager。
