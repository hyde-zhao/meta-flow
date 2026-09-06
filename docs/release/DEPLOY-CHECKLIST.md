---
status: released_remote_verified
version: "0.6.6"
release_artifact_profile: full
release_decision: RELEASED
---

# Meta Flow 0.6.6 Deploy Checklist

## 发布前硬门

- [x] 用户已批准 CR-078 功能 CP8，并独立授权真实发布 0.6.6。
- [x] 版本选择固定为 0.6.6；明确跳过 0.6.4。
- [x] G2/G3 专项、兼容回归、Ruff 与 diff check 通过。
- [x] activation receipt v11 已生成且 `CURRENT`；v1-v10 bytes 不变。
- [x] detector full baseline 与 frozen source OID 对齐，增量未解析 writer 为 0。
- [x] release/process 两仓提交并推送，source OID 固定且工作树 clean。
- [x] `uv build` 只生成一个 wheel 和一个 sdist。
- [x] `ProviderArtifactReceiptV1.json` 与 `ProviderArtifactReceiptV1.digest-policy.json` 摘要闭合。
- [x] clean-home/non-editable installed-artifact canary 通过，checkout import=false。
- [x] GitHub `v0.6.6` tag/release 指向 frozen source OID，四项远端资产摘要与已验收本地资产一致。

## 版本真相

以下位置必须全部为 0.6.6：

- `pyproject.toml`
- `uv.lock`
- `meta_flow.__version__`
- execution-control activation receipt package identity
- wheel/sdist 文件名和元数据
- release notes 与 Git tag

## 安装/升级矩阵

| 场景 | 验收 |
|---|---|
| clean-home 安装 | 从 exact wheel 安装，不从 checkout import；`meta-flow version` 为 0.6.6/READY |
| 0.6.3 → 0.6.6 | V1 G2 读取为 effective G3；历史 bytes 不变 |
| 重复安装 | 相同资产幂等，不重建或覆盖 receipt |
| 回滚 | 切回 0.6.3 exact assets；历史治理记录保留 |
| 缺失/损坏资产 | fail closed；重新下载相同摘要资产，不从源码重建 |

## 停止条件

任一测试失败、receipt STALE、detector qualification BLOCKED、源码/构建摘要漂移、canary 从 checkout import、远端摘要不一致或 tag 指向错误 OID 时，停止 publication；不得以 CP8 批准替代真实检查。
