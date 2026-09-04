---
status: release_candidate
version: "0.6.5"
base_version: "0.6.3"
---

# Meta Flow 0.6.5 Migration

## 迁移结论

0.6.3 → 0.6.5 不需要数据库、凭据、外部服务或历史治理对象的批量迁移。0.6.4 没有公开发布，因此不存在 0.6.4 升级路径。

## 治理等级兼容

| 持久化值 | schema version | 0.6.5 effective profile | 动作 |
|---|---:|---|---|
| G0/G1 | 1 或缺失 | G0/G1 | 无迁移 |
| G2 | 1 或缺失 | G3 | 保留原 bytes，继续完整设计语义 |
| G2 | 2 | G2 | 使用 scope-goal-note 轻量设计 |
| G3 | 2 | G3 | 使用原 G2 完整设计路径 |

外部消费者不得只凭字符串 `G2` 判断设计深度，必须同时读取 `risk_profile_schema_version` 或 provider 给出的 `effective_profile`。

## 升级步骤

1. 下载 v0.6.5 的 wheel、sdist、ProviderArtifactReceiptV1 与 sidecar。
2. 按 GitHub Release 公布的 SHA-256 校验四项资产。
3. 在隔离环境安装 exact wheel，不使用 editable checkout。
4. 运行 `meta-flow version --format json`，确认 package version=0.6.5、provider readiness=READY。
5. 对仍在执行的历史 V1 G2 CR 做只读 route 检查，确认 effective profile=G3；不得批量改写历史文件。

## 行为变化

- 高风险默认从旧完整 G2 改为新轻量 G2。
- 只有用户显式选择才进入 G3。
- 架构 delta 恢复 CP3 人工复核，但不自动构成 G3 同意。
- consent trigger 只会阻断并请求决定，不会代表用户已授权完整 LLD 或真实运行。
