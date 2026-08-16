# Meta Flow 0.5.3 迁移说明

## 适用范围

从 `0.5.2` 升级到 `0.5.3`。本版本不要求批量改写历史 Work、CR、ledger、raw findings 或 terminal transaction。activation receipt v1-v7 保持不可变，新版本使用 create-only v8。

## 升级步骤

1. 确认 Work-init、scope-amend、projection/correction 事务没有 `PREPARED`、`APPLYING`、`PARTIAL` 或 `RECOVERED` 未处理状态。
2. 下载 GitHub Release 的 exact 0.5.3 wheel 和 `ProviderArtifactReceiptV1.json`，核验页面公布的 SHA-256。
3. 安装 wheel 后设置同一版本 receipt，运行 `meta-flow version --format json`，要求 release readiness 与 exact artifact identity 为 PASS。
4. 对目标项目运行只读 route/project/state/CR/Work 检查；任何 OID、dirty inventory、preimage 或 schema 漂移都先重新 plan。
5. 需要 scope amendment 时只使用原生 `meta-flow cr scope-amend` plan/apply；不得手改 WORK、successor revision、receipt 或 invalidation。

## 行为变化

- Work-init 新增 production validation snapshot，preflight 与 apply 共享唯一 graph；apply fresh recapture 必须与批准 graph digest 一致。
- scope amendment 创建 append-only successor revision，并通过原子事务更新 canonical projection/receipt/invalidation。
- validation reuse 只有在七维 taxonomy、evidence digest、comparison basis 与单权威 graph 全部一致时才允许 `REUSED_UNCHANGED`。
- compatibility observation 使用持久 CAS/hash-chain truth；retirement 只产生 proposal，不能自动退役 reader。
- missing-evidence recovery 只恢复对应 blocker，不覆盖 human-gate pending、PARTIAL/RECOVERED、other/unknown 或更高优先级 blocker。

## 独立授权边界

真实 correction append、effective authority cutover、reader retirement、consumer 安装/升级及生产运行都需要各自新的 typed authorization；0.5.3 发布授权不包含这些动作。
