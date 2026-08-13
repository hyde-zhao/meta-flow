# Meta Flow 0.5.0 部署检查

## 发布前

- [ ] `pyproject.toml`、`uv.lock`、`meta_flow.__version__`、provider contract/receipt 均为 `0.5.0`。
- [ ] targeted、compatibility、full、Ruff、lock、delivery guardrail 全部通过。
- [ ] `uv build` 成功，wheel/sdist 名称与 metadata 版本均为 `0.5.0`。
- [ ] Codex project full install dry-run 与 CLI reinstall dry-run 零写通过。
- [ ] `meta-flow` 与 `meta-flow-process` 两仓 staged inventory 与预期完全一致。
- [ ] 两仓 `main` 均与各自 `origin/main` 同步，无 behind。

## 发布动作

- [ ] 先提交并推送 `meta-flow-process` 资格证据。
- [ ] 再提交并推送 `meta-flow` 0.5.0 源码与发布资产。
- [ ] 在已验证的 `meta-flow` 提交创建 annotated `v0.5.0` tag 并推送。
- [ ] 创建 GitHub Release，标题为 `Meta Flow 0.5.0`，正文引用本发布说明。

## 发布后

- [ ] `git ls-remote origin refs/heads/main refs/tags/v0.5.0` 与本地对象一致。
- [ ] `gh release view v0.5.0` 显示 published，target 为已验证发布提交。
- [ ] 不安装或修改 quant-lab；其恢复由独立安装/consumer authorization 执行。
