# Meta Flow 0.5.2 部署检查

## 发布前

- [x] `pyproject.toml`、`uv.lock` 与 `meta_flow.__version__` 均为 `0.5.2`。
- [x] execution-control activation receipt v6 的 owner source set 未变化且仍为 CURRENT。
- [x] targeted：`175 passed`。
- [x] compatibility：`146 passed + 21 subtests`。
- [x] full：`2407 passed + 712 subtests`。
- [x] writer detector：`399/399` classified、`36/36` dynamic allowlisted、0 ambiguous、0 unresolved。
- [ ] Ruff、lock、delivery guardrail、双仓 `git diff --check` 最终通过。
- [ ] 从 clean source commit 构建 0.5.2 wheel/sdist。
- [ ] 生成 `ProviderArtifactReceiptV1`，且 `release_qualifying=true`。
- [ ] 在隔离环境从 wheel 安装，证明 `provider_checkout_imported=false` 且 core lifecycle canary 通过。

## 发布执行

- [ ] 提交并推送 `meta-flow` 的源码、测试、公共合同和发布资产。
- [ ] 提交并推送 `meta-flow-process` 的 writer baseline、资格说明与 release context。
- [ ] 创建并推送 annotated tag `v0.5.2`。
- [ ] 创建 GitHub Release `Meta Flow 0.5.2`，附加 wheel、sdist 和 artifact receipt。
- [ ] 核验本地 HEAD、upstream、GitHub branch/tag/release target 精确一致。
- [ ] 发布后更新过程仓 release context 的 source/process OID、tag object、artifact digest 和 URL。

## 明确不执行

- 不上传 PyPI 或其他包仓库。
- 不安装或修改 quant-lab、quant-lab-process 或其他 consumer 项目。
- 不执行 consumer recovery、Phase transition、runtime、NAS、模拟盘、实盘或交易操作。
