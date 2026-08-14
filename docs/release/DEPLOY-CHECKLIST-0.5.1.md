# Meta Flow 0.5.1 部署检查

## 发布前

- [x] `pyproject.toml`、`uv.lock`、`meta_flow.__version__` 与 provider contract 均为 `0.5.1`。
- [x] activation receipt v1-v5 保持不可变，v6 是当前 fixed locator。
- [x] targeted：`436 passed`。
- [x] compatibility：`146 passed + 21 subtests`。
- [x] full：`2367 passed + 712 subtests`。
- [x] Ruff、lock、delivery guardrail、writer detector、public operation registry 与 governance ownership 全部通过。
- [x] Codex/Claude project full 安装 dry-run 通过。
- [x] `uv build` 成功，wheel/sdist metadata 与文件名均为 `0.5.1`。

## 发布执行

- [ ] 提交并推送 `meta-flow-process` 的治理归属、writer baseline、资格化和 release context。
- [ ] 提交并推送 `meta-flow` 的源码、测试、公共合同和发布资产。
- [ ] 创建并推送 annotated tag `v0.5.1`。
- [ ] 创建 GitHub Release `Meta Flow 0.5.1`，引用 `docs/release/RELEASE-NOTES.md` 的 0.5.1 切片。
- [ ] 核验本地 HEAD、upstream 与 GitHub 远端引用精确一致。

## 明确不执行

- 不上传 PyPI 或其他包仓库。
- 不安装或修改 quant-lab、quant-lab-process 或其他消费者项目。
- 不执行 consumer recovery、Phase transition、runtime、NAS、模拟盘、实盘或交易操作。
