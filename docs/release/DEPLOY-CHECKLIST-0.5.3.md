# Meta Flow 0.5.3 部署检查

## 发布前

- [x] CP8 已按 `READY_WITH_RISK` 批准；三个 full-suite 基线失败已被明确接受且未使用 waiver。
- [x] `pyproject.toml`、`uv.lock`、`meta_flow.__version__` 与 activation receipt v8 均为 `0.5.3`。
- [x] activation receipt v1-v7 保持不可变，v8 fixed locator 为 `CURRENT`。
- [x] targeted：`370 passed + 116 subtests`。
- [x] compatibility：`829 passed + 363 subtests`。
- [x] independent high-risk subset：`377 passed + 108 subtests`。
- [x] full：`2558 passed + 716 subtests + 3 pre-existing failures`；新失败 0、waiver=false。
- [x] Ruff、lock 与双仓 diff-check 通过；delivery guardrail 仅保留 CP8 已接受的缺失 ignored active-skill mirror，以及已声明的 detector baseline/cr_index residual，未放宽规则或使用 waiver。
- [ ] 从 clean source commit 构建 0.5.3 wheel/sdist。
- [ ] 生成 `ProviderArtifactReceiptV1`，要求 `release_qualifying=true`。
- [ ] 隔离安装 wheel，证明 `provider_checkout_imported=false` 且 core lifecycle canary 通过。

## 发布执行

- [ ] 提交并推送 `meta-flow` 与 `meta-flow-process`。
- [ ] 创建并推送 annotated tag `v0.5.3`。
- [ ] 创建 GitHub Release `Meta Flow 0.5.3`，附加 wheel、sdist 与 artifact receipt。
- [ ] 核验 source/process branch、tag target、release target 与 artifact 摘要。
- [ ] 回填 process release context 的 exact OID、tag object、URL 与 artifact digests。

## 明确不执行

- 不上传 PyPI 或其他包仓库。
- 不安装或修改 quant-lab、quant-lab-process 或其他 consumer。
- 不执行真实 correction append、effective authority cutover、reader retirement 或生产 runtime。
- 不读取凭据，不 force push，不 reset/clean，不改写历史 receipt/ledger/raw finding。
