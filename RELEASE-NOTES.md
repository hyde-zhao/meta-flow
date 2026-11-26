# 发布说明

## 1.0.1（R0/V1 P4 修复发布）

- 版本：1.0.1（R0/V1）
- 日期：2026-11-26
- 路标：R0（P4）
- 契约版本：meta-flow-contract R0/P4
- 状态：已发布（用户批准 P4 修复发布；发布清单 `release/RELEASE-1.0.1.yaml`）
- 变更：
  - T017/T019/T021：P4 工具闭环、NEEDS_REWORK 自动重开、`mf task rework`、BUG-0015 部署覆盖修复；
  - T023/BUG-0016：release freeze 阶段策略修正（P1/P2 禁发、P3 结束后可发、P4/P5 修复随时可发；`--force` 不绕过阶段门）；
  - T014：L1/L3 验证通过；VR-0001..0003；L2 SPEC/规范复核仍待 M02/M03；
  - 版本元数据修正（MFP-0028/T025）：`pyproject.toml`、源码 `__version__`、
    `mf --version`、`delivery.yaml` 与发布清单统一为 1.0.1；新增
    `mf release check` 与 `release freeze` 版本一致性校验（pyproject/源码/
    RELEASE-NOTES/清单/tag，不一致失败，不得静默 0.1.1）。修复前
    `mf --version` 实际仍输出 0.1.1（源码版本常量未同步）。
  - 发布清单新增 `stage`。
- 已知问题/未完成：
  - T015 ptm-team 手动部署与 ptm-tde 验证；
  - M02/M03：14/16 规范待复核、SPEC-001..005 未编写、`mf req trace specs=0`；L2 VR PASS_WITH_RISK；
  - R5：upgrade 补建缺失 phase plan；
  - MFP-0021..0027 工具缺口（maintainer）；
  - MFP-0029：uv 在同版本号源码迭代时复用缓存，`mf dev install` 可能静默装旧代码；
    CLI 已默认 `UV_NO_CACHE=1` 缓解，完整 `--reinstall` 与安装后自检待实施；
  - v1.0.1 tag 指向的提交仍含旧版本元数据（pyproject/源码 0.1.1）；
    T026 评审通过后由 manager 重打 tag 或按下一 patch 记录（MFP-0028）。
  - 1.0.1 为 P4 修复发布，不替代 P4 退出/P5 门禁。
- 升级/回滚：全局 mf 使用 1.0.1 代码：`UV_NO_CACHE=1 mf dev install --yes`
  后确认 `mf --version` 输出 1.0.1，再执行项目/子项目 `mf upgrade`；回滚
  1.0.0 时恢复 delivery.yaml/RELEASE-NOTES 与全局 mf。

## 1.0.0（R0/V1 冻结候选，历史）

- 版本：1.0.0（R0/V1）
- 日期：2026-11-25（R0 试运行基线）
- 路标：R0（P4 收口）
- 契约版本：meta-flow-contract R0/P4
- 状态：历史冻结候选；1.0.1 为当前修复发布；原发布阶段策略已在 1.0.1 修正

## 范围

meta-flow V1/R0 1.0.x 试运行版本，覆盖安装/工作区/契约接入、任务与评审闭环、
上下文与角色守卫、需求追踪与版本冻结、交付文档与自托管布局。

## 变更

- 工作区：新增 `mf workspace attach`，可接入已有 contract，只导入路标/阶段/版本/
  workspace 注册等状态元数据，不覆盖 contract、不导入源码（BUG-0006）。
- 安装一致性：`mf workspace link/init/attach` 后刷新 install.yaml 的 CLAUDE.md
  digest（BUG-0007）；`mf dev status` 在 source_dir 缺失/无效时显式报错并引导
  `mf dev clone`/`--source`（BUG-0005）；模板统一使用 `mf doctor --path/--global`
  （BUG-0008）。
- 版本策略：`mf release freeze` 读取 ROADMAP 的 `version_major`/`version_range`
  声明映射（支持 R0/V1 1.0.x）；未声明的 MAJOR 不一致默认拒绝，`--force` 必须记录
  `--reason`、`--approved-by` 与版本（BUG-0011/MFP-0006）。
- 发布阶段策略（1.0.1 修复，BUG-0016；见上）：1.0.0 原流程要求 P5 退出；1.0.1 已按用户策略修正。
- 需求追踪：`mf req trace` 默认只追踪当前路标，排除 archive；BUG 按 id 去重；
  SPEC 只匹配 `SPEC-*.md`；新增 `--archive` 供审计（BUG-0012）。
- 任务与评审：任务包按 effort 提供预算档位、代码入口清单与 `mf context expand`
  提示；handoff/dev-record/evidence 作为独立 process paths 授权；`mf task submit`
  支持交付库 `.meta-flow/dev-records|handoffs` 本地副本（MFP-0007）。
- 并行任务：提交时按任务活动窗口隔离其他并行任务的 diff；单任务越界仍拒绝，
  非活动/非重叠改动不被静默计入（MFP-0011）。
- 角色边界：worker 无交付根绑定时任务命令要求 `--project-dir`，否则 rc=3；guard
  同规则（MFP-0012/F3）。
- 知识注入：按项目/交付库/路标和任务相关性过滤，阻止跨项目同名任务 ID 误匹配。
- 测试隔离：pytest 统一切换临时 cwd 并清理 MF_ROLE，工作区内与 /tmp 运行一致
  （BUG-0010）。
- 交付文档：delivery.yaml 补充文档索引与版本策略；USER-MANUAL 增加新项目与迁移
  项目两个快速开始；清理 .gitignore 过期自定义规则（BUG-0004/REQ-0009/0016）。
- 返工（T018 R1–R7）：worker 可受控 `mf context show/expand`（活动任务 bundle、
  评审目标、allowed_paths；带 reason 写 READ-LOG）；review packet 按 reviews 目标
  嵌入 dev-record/handoff/diff，缺失显式报错；guard 放行评审目标 bundle 与返工评审
  输出；diff.patch 纳入未跟踪新增文件；补 MFP-0011 E3 非活动改动回归；review 任务
  提交只需 review.md + review-handoff.md（MFP-0013）；guard hook 覆盖 Bash 路径策略
  与 READ-LOG 审计（BUG-0014）。
- 返工第二轮（CHG-0002）：Bash 路径策略展开 `$HOME`/环境变量并递归解析
  `sh -c`/`bash -c`，无法安全解析的涉及路径读写保守拒绝（R8/F8）；guard deny 输出
  角色/当前任务/lease/allowed_paths 与合法通道，返工 prompt 含 `mf task start`
  （R9）；本地 `.meta-flow/improvements/MFP-*.yaml` 受控写入并审计（R10）；guard
  allow/deny 持久化 READ-LOG（role/task/path/reason/tool，命令脱敏），可用
  `mf context log` 查询（R11）；bundle 匹配使用完整任务 ID，跨 roadmap/phase 同名
  尾号不误放行（R12）。
- 返工第三轮（R13/F12）：Bash 路径策略将 `eval`、`source`/`.`、进程替换
  `<(...)`/`>(...)` 纳入递归解析或保守拒绝；转义变量 `\$HOME` 不得绕过；自有
  bundle/allowed 在可安全解析时仍允许；审计记录原始命令/parsed_paths/unsafe。
- 安装升级边界（BUG-0015）：`mf upgrade --force` 只覆盖安装镜像（agent 文件、
  `CLAUDE.md` 受管块、settings hook），不再把 `--force` 传给 contract 骨架同步；
  contract 的 standards/templates/policies/improvements README 与 R1 phase plans
  等自定义内容保持不变，仅补建缺失文件。`mf bootstrap --force` 仍只刷新
  `~/.meta-flow` 全局模板库。

## 已知问题

- 本版本为 R0 试运行基线；T014/T015 验证与用户 P4 门禁完成前不得标记发布。
- `mf release freeze` 仍未自动维护交付库 delivery.yaml 版本；由 manager 在发布前
  按 ROADMAP 版本策略核对。
- ptm-team/ptm-tde 外部验证由 T015 承接，证据不在本交付仓。

## 升级与回滚

- 升级：在源码目录运行 `mf dev update`、`mf dev install --yes`，随后
  `mf upgrade --project-dir <root>` 与子项目 `mf upgrade --project-dir <sub>`，
  最后运行 `mf doctor --path <root>` 与 `mf workspace sync --check`。
- 回滚：使用 `uv tool install --force` 安装上一版本源码标签；项目侧可回退
  `.meta-flow/install.yaml` 与全局模板快照，contract 仓按 git 历史回退。
- 安装镜像（CLAUDE.md/.claude/.meta-flow）不入库；delivery.yaml、RELEASE-NOTES.md、
  USER-MANUAL.md、DESIGN.md、README.md 入交付仓。
