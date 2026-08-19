---
status: frozen_candidate
version: "0.6.1"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.1 Deploy Checklist

本文固定发布顺序和阻断条件；动态结果只写入过程仓 Release Context、release-order ledger 与 CP8 result，避免 source freeze 后修改源码候选。

## 发布前输入

| 输入 | 冻结前状态 | 证据 |
|---|---|---|
| CR-072 聚合 CP7 Revision 2 | `PASS_WITH_RISK` | `process/checks/CP7-CR-072-AGGREGATE-REV2.result.json` |
| 六个 CP6 current digest | PASS | CP7 `input_artifact_hashes` |
| targeted / compatibility | PASS | 聚合验证 evidence |
| full 当前性 | PASS / reuse allowed | `process/evidence/CR-072-AGGREGATE-FULL-REUSE.json` |
| M-072-04/05/06、B-072-01/02 | RESOLVED | `CONVERGENCE.md` |
| 成本闭环 | `PASS_WITH_RISK` | `R-072-COST` open、unwaived |

## 唯一发布序列

| 顺序 | 动作 | 硬条件 | 次数上限 |
|---:|---|---|---:|
| 1 | source freeze | 双仓本地候选提交；源码仓 clean | 1 |
| 2 | typed SemVer decision | normal recommendation 如实为 next-minor；bootstrap 仅 0.6.1 | 1 |
| 3 | fingerprint | 绑定 exact source/process OID、plan/cost/compat digest | 1 |
| 4 | provider source qualification | dirty paths=0、checks 全 PASS、build count=0 | 1 |
| 5 | wheel/sdist/receipt/sidecar build | canonical asset names；qualification 不重复计数 | 1 |
| 6 | isolated consumer canary | 非 editable、checkout import=false、runtime READY | 1 |
| 7 | CP8 auto + human | 风险与不授权项显式披露 | 1 |
| 8 | tag / GitHub Release | 仅在新的远端发布授权后 | 1 |
| 9 | native close | 仅在远端发布成功并核验资产后 | 1 |

任何乱序、重复 qualification/build/canary/CP8/release、source freeze 后源码漂移或 breaking/unknown compatibility 都必须 hard fail。

## 构建与消费者验证

| 检查 | 放行条件 |
|---|---|
| 版本三真相 | `pyproject.toml`、`uv.lock`、`meta_flow.__version__` 全为 0.6.1 |
| 构建 | `uv build` 只生成一个 wheel 与一个 sdist；输出放在忽略的本地 build 目录 |
| receipt bundle | `ProviderArtifactReceiptV1-0.6.1.json` 与 `.digest-policy.json` 原子生成且摘要匹配 |
| canary | clean-home 安装 wheel，校验 sdist、receipt、sidecar、版本与 lifecycle harness |
| published assets | 远端发布获批后才核验；当前不适用 |

## CP8 自动检查

- Release Context 与 CP8 minimal context 完整；
- CP7/CP6 digest 和 full reuse decision 当前；
- release-order state 到达 `canary-passed`，qualification/build/canary count 均为 1；
- `R-072-COST` 仍公开、无 waiver；
- blocker=0、breaking/unknown compatibility=0；
- human-gate 输出与 launch message 通过机器检查。

## 不授权项

| Item ID | 操作 | 当前状态 | 独立授权要求 |
|---|---|---|---|
| NA-072-01 | push 两仓提交 | 未授权 | 用户明确授权 exact local OID push |
| NA-072-02 | 创建/推送 `v0.6.1` tag 与 GitHub Release | 未授权 | 用户明确发布授权 |
| NA-072-03 | PyPI 或其他 registry upload | 未授权 | 单独外部发布授权 |
| NA-072-04 | 外部 consumer 安装/修改、生产运行或数据写 | 未授权 | exact target typed authorization |

CP8 通过不自动授权上述操作，也不等于已经发布。
