# meta-flow 1.0.3 维护批次证据摘要

- 日期：2026-11-27
- 范围：不建任务卡；maintainer 直接改工具源码/模板并临时部署（用户授权）。
- 结论：MFP-0038、MFP-0039/REQ-0023、MFP-0041（A1/A3/A4/A6）、MFP-0040
  部署门完成；MFP-0037 复核为 verified。未 push、未创建远程。
- `next_owner=manager`：等待 manager 验收并更新契约侧 MFP/REQ resolution。

## 一、按 MFP 分项

| 项 | 修改 | commit | 验证 |
|---|---|---|---|
| MFP-0038 | `task.py`：`rework_scope` 支持粗体/下划线/反引号；必须整改项支持 `### R4（in-scope）` 全角/无空格小节与表格；review submit `NEEDS_REWORK` 即触发目标 `rejected/rework`、`next_owner=实现 worker`；`rework_summary` 提交强制；模板同步；`MF_LEGACY_REWORK=1` 回滚 | `0ca9f4a` | `tests/test_task.py` 52 passed；高/中/低风险、范围外、缺 summary、legacy 回滚用例 |
| MFP-0039 / REQ-0023 | `roles.py`/`cli.py`：`mf role --reset`（仅 maintainer，只清理 user-tty/当前会话/遗留锚点，写 `role.reset` ledger）；`guard.py` 按实际执行段识别会话入口/锚点 API，跳过提交消息与只读 grep；文档更新 maintainer 模板、workspace manager 提示、USER-MANUAL | `5359662` | `tests/test_designer_role.py`、`tests/test_cli.py`；reset 正负例、误伤三例、真实入口 deny |
| MFP-0041 A1/A3/A4/A6 | `templates.py`：新增 `SECURITY-CARD.md`、`NEGATIVE-MATRIX.md`；`verify.py`/`cli.py`：`mf verify security-card` 校验信任边界/攻击者能力/可证明 fail_closed/不可防残余/风险接受人；验收规范补一任务一 commit 与连续两轮绕过暂停 | `52abe4e` | `tests/test_security_card.py`、`tests/test_designer_role.py` A3 矩阵；模板注册断言 |
| MFP-0040 | 版本 1.0.3；全局备份与 sha256；临时部署；真实 hook 回归；ruff format 策略；回滚步骤 | `70c882c`、`4fa95e8` + 本文档 | 见第三节 |
| MFP-0037 | 复核返工链路/锚点清理；resolution 更新为 1.0.3 | `f87f264` + 本批 | `tests/test_task.py`、`tests/test_designer_role.py` |

本批附属修复（MFP-0040 安装/升级范围）：

- `4fa95e8`：`mf dev install` 同步 `~/.meta-flow/manifest.yaml` 的
  `tool_version`/`source_dir`；`mf install claude --force` 在已有工作区保留根
  `CLAUDE.md` 的 contract 导入，不再覆盖为内联模板。回归：
  `tests/test_release.py::test_dev_install_syncs_global_manifest_tool_version`、
  `tests/test_workspace.py::test_reinstall_preserves_workspace_claude_import`。

## 二、MFP-0041 A5：工具缺口 resolution / 降级

| MFP | 状态 | 证据 | 处理 |
|---|---|---|---|
| MFP-0011 并行任务快照污染 | 1.0.2 已实现 | `task.py` `_partition_changes`/`ownership.json`；`tests/test_submit_snapshot.py`；RELEASE-NOTES 1.0.2 第 160 行 | resolution：已在 1.0.2 交付；本批复核通过 |
| MFP-0012 显式 MF_ROLE 交付作用域 | 1.0.2 已实现 | `cli.py` `_ensure_worker_scope`；`tests/test_boundaries.py::test_worker_delivery_scope_preserved_with_mf_role`；`tests/test_cli.py` E1 | resolution：已在 1.0.2 交付；本批复核通过 |
| MFP-0013 review 提交不要求 handoff.md | 1.0.2 已实现 | `task.py` 提交分支仅校验 review.md + review-handoff.md；`tests/test_task.py` | resolution：已在 1.0.2 交付；本批复核通过 |
| MFP-0014 guard 诊断/审计/本地 MFP/完整任务 ID | 1.0.2 已实现 | `guard.py` deny 诊断与 READ-LOG 审计、本地 MFP 白名单、完整任务 ID 匹配；`tests/test_guard.py` | resolution：已在 1.0.2 交付；本批复核通过 |
| MFP-0038/0039/0040/0041 | 本批实现 | 本文档与对应 commit | 待 manager 验收后更新契约侧 resolution |

降级/残余：

- MFP-0041 A2（不可伪造宿主凭据/OS 隔离/威胁模型定稿）不在本批，归 R1。
- REQ-0022（非 CLI BUG 关闭渠道）归 R1。
- maintainer 跨生产项目/OS 级权限模型归 R1。
- MFP-0038 的 `MF_LEGACY_REWORK=1` 仅临时回滚通道，下一版本评估移除。

## 三、1.0.3 版本/部署证据

- 版本：`mf --version` → `mf 1.0.3`；`pyproject.toml`/`src/meta_flow/__init__.py`/
  `delivery.yaml`/`RELEASE-NOTES.md`/`uv.lock` 一致。
- `~/.meta-flow/manifest.yaml`：`tool_version: 1.0.3`，`updated_at:
  2026-11-27T09:38:14Z`。
- 安装记录：项目根与子项目 `.meta-flow/install.yaml` 均为 `tool_version: 1.0.3`。
- 全局模板：`mf bootstrap --force` 后含 `agents/designer.md`、
  `templates/CLAUDE.designer.md`、`templates/standards/SECURITY-CARD.md`、
  `NEGATIVE-MATRIX.md`。
- `mf doctor --global`、`mf doctor --path <root>`、`mf doctor --path <sub>` 全部 OK。
- 备份：
  - `~/.local/share/uv/tools/meta-flow.bak-1.0.2-20261127`（1.0.2）
  - `~/.local/share/uv/tools/meta-flow.bak-1.0.3-20261127-pre-batch`（本批部署前 1.0.3）
  - 两者入口均 sha256 `9399a1259489a0106030369456b14023cb93c5bf98709bd4635a6621665555b4`。
- 源码与安装包：`diff -r --exclude=__pycache__ src/meta_flow <site-packages>/meta_flow`
  无差异；`task.py` sha256 `6b8da22c...1315f4`、`guard.py` sha256 `cecb342b...91db4`
  源码与安装包一致（python3.14 site-packages）。
- 真实 hook：`.claude/settings.json` 含 `mf hook pretool` 与 `mf hook session-start`；
  实际调用 `mf hook pretool`：
  - `mf hook session-start` payload → deny（SessionStart/锚点 API 只能宿主/用户终端）。
  - `git commit -m "fix(anchor): note uv run meta_flow"` → 无 deny。
  - `grep "mf hook session-start" README.md` → 无 deny。
- T035/T036 回归：`tests/test_designer_role.py`、
  `tests/test_task.py`、`tests/test_guard.py` 通过；全量 `pytest -q` → 268 passed,
  1 xfailed；`ruff check .` → clean。
- `ruff format` 策略：R0/P4 明确豁免（当前 24 文件会被重排，避免混入维护批次
  diff）；`ruff check` 为强制门，后续独立格式化批次统一处理。
- `mf role --json`：maintainer（source=anchor）；`/clear` 由宿主 SessionStart
  重写本会话锚点（代码与单测覆盖，未在真实会话中断验证）。

## 四、回滚步骤

1. 恢复全局工具：`rm -rf ~/.local/share/uv/tools/meta-flow` 后
   `cp -a ~/.local/share/uv/tools/meta-flow.bak-1.0.2-20261127 ~/.local/share/uv/tools/meta-flow`
   （或恢复 pre-batch 1.0.3 备份）。
2. 恢复源码：`git checkout <上一版本 commit>`（不 push 时不涉及远程）。
3. 恢复全局元数据：`~/.meta-flow/manifest.yaml` 的 `tool_version` 改为对应版本。
4. 重装项目安装：`mf install claude --project-dir <root> --force`、
   `mf install worker --project-dir <sub> --force`；确认 `mf doctor`。
5. 回滚 MFP-0038 自动回流：设置 `MF_LEGACY_REWORK=1` 并走 manager accept 旧路径；
   下一版本移除前仅作应急。

## 五、边界与下一责任

- 未 `git push`、未创建远程、未改 T035/T036 已验收结论、未启动 T033/T038。
- 不改契约内容；contract 侧模板/验收规范更新由 manager 按流程同步。
- `next_owner=manager`：验收本摘要与各 commit，更新 MFP/REQ resolution；发布
  tag/push 需用户显式授权。
