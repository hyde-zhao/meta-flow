---
status: release_candidate
version: "0.6.2"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.2 Deploy Checklist

## 发布前输入

| 输入 | 状态 | 证据 |
|---|---|---|
| CR-073 聚合 CP7 | `PASS_WITH_RISK` | `process/checks/CP7-CR-073-AGGREGATE-REV2.result.json` |
| 七个 current CP6 绑定 | PASS | CP7 `input_artifact_hashes` |
| affected regression / detector | PASS | `CR073-CP7-INCREMENTAL-REGRESSION` / `DETECTOR-QUALIFICATION` |
| 最终 full 及 no-drift | 可复用，禁止重跑 | `CR073-CP7-FINAL-FRESH-FULL` / `FINAL-SOURCE-FINGERPRINT` |
| quant-lab source-candidate replay | PASS | `process/evidence/CR073-SOURCE-CANDIDATE-VICTIM.json` |
| 0.6.2 typed selection | `PASS_WITH_RISK` | `CR-073-SEMVER-SELECTION-0.6.2.json` |

## 唯一发布序列

| 顺序 | 动作 | 硬条件 | 次数上限 |
|---:|---|---|---:|
| 1 | version metadata | `pyproject.toml` / `uv.lock` / `meta_flow.__version__` / provider package version 归一到 0.6.2 | 1 |
| 2 | source freeze | 双仓 candidate 提交且 release 仓 clean | 1 |
| 3 | typed version selection | 保留 machine BLOCKED/0.7.0 事实，消费一次性 0.6.2 selection | 1 |
| 4 | fingerprint | 绑定 exact release/process OID、source/plan/cost/compat digest | 1 |
| 5 | provider source qualification | dirty paths=0、checks PASS、build count=0 | 1 |
| 6 | wheel/sdist/receipt/sidecar build | canonical names；qualification 不重复计数 | 1 |
| 7 | isolated installed-artifact canary | non-editable、checkout import=false、runtime READY、quant-lab journeys | 1 |
| 8 | CP8 auto + human | 风险与不授权项显式披露 | 1 |
| 9 | tag / GitHub Release | 仅在 CP8 后新的 typed publication authorization | 1 |
| 10 | native close | 仅在远端发布成功且资产核验后 | 1 |

任何乱序、重复 qualification/build/canary/CP8/release、freeze 后源码漂移、breaking/unknown compatibility 或 installed-artifact claim 缺失都必须 hard fail。

## 构建与消费者验证

| 检查 | 放行条件 |
|---|---|
| 版本真相 | `pyproject.toml`、`uv.lock`、`meta_flow.__version__`、provider package version 全为 0.6.2 |
| 构建 | `uv build` 只生成一个 wheel 与一个 sdist |
| receipt bundle | `ProviderArtifactReceiptV1.json` 与 `ProviderArtifactReceiptV1.digest-policy.json` 原子生成且摘要匹配 |
| canary | clean-home 安装 exact wheel，校验 sdist/receipt/sidecar/version，并获得 installed-artifact victim claim |
| 回归 | 只跑 version/provider/release 受影响集，不重跑 full |

## 当前不授权项

| Item ID | 操作 | 状态 | 独立授权 |
|---|---|---|---|
| NA-073-01 | 双仓 Git commit/push | 未授权 | exact candidate 本地提交/推送授权 |
| NA-073-02 | 创建/推送 `v0.6.2` tag 与 GitHub Release | 未授权 | CP8 后 typed publication authorization |
| NA-073-03 | PyPI/registry upload | 未授权 | 单独外部发布授权 |
| NA-073-04 | quant-lab mutation、生产写或凭据读取 | 未授权 | exact target typed authorization |

CP8 通过不自动授权任何 Git 或远端操作。
