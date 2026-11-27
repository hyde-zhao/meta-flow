# 发布说明

## 1.0.3（R0/V1 P4 维护发布）

- 版本：1.0.3（R0/V1）
- 日期：2026-11-27
- 路标：R0（P4）
- 状态：维护批次完成（版本元数据统一为 1.0.3；全局 `mf` 与项目安装已升级；
  部署证据/备份 sha256/回滚见 `docs/MAINTENANCE-1.0.3.md`；`git tag` 与 `git push`
  待用户授权后执行）。
- 范围：WP-F1 designer 角色/工作区/设计包与责任映射（SPEC-FRAMEWORK R1/R4；
  T033 A1 角色锚定先落地）；维护批次含评审返工直达 worker（MFP-0037）与
  锚点诊断序列化修复（A4）。
- designer 角色：
  - 新增 `agents/designer.md`、`CLAUDE.designer.md` 全局模板与
    `mf install designer --project-dir <contract>`（`role: designer`）。
  - 角色短名 manager/designer/worker/maintainer；别名 `mgr/dsg/wkr/mnt` 与
    `meta-*` 命名空间。
  - 工作区权限：可写 contract `architecture/`、`specs/`、P2 设计包/规格与
    `templates/DESIGN-PACKAGE.md`；子项目源码只读；禁止写需求/验收/发布。
  - 设计包模板 `templates/DESIGN-PACKAGE.md`：信息流、子项目/职责/接口、模块/功能/
    接口、REQ/MFP→SPEC→子项目/模块映射、跨子项目验证计划、预研计划、manager 设计验收。
- 责任主体与执行者（MFP-0035）：
  - 任务卡新增 `owner_role`/`executor_role`；`kind: design` 默认 designer，
    implement/fix/document/verify 默认 worker，review 由独立评审者执行。
  - 非默认主责需 manager `--owner-confirmed-by` 显式确认并写
    `task.owner.confirm` ledger；worker 不得冒充 designer，designer 只能执行 design。
  - `mf task prompt/packet` 显示 owner_role/executor_role/delivery。
- 角色锚定（T033 A1）：
  - SessionStart hook `mf hook session-start` 按宿主会话写
    `.meta-flow/session-roles/<session_id>.yaml`（按会话隔离，`/clear` 只重写本会话）；
    用户终端 `mf role --as` 写 `session-roles/user-tty.yaml`，按更新时间优先。
  - SessionStart 锚点必须绑定 `session_id`（payload 或 `CLAUDE_CODE_SESSION_ID`），
    缺失时拒绝写入；无 `session_id` 读取时不回退共享会话锚点（fail-closed）。
  - guard/CLI 使用当前会话锚点，cwd 漂移不改变 effective role；`MF_ROLE=designer/manager`
    不能由 worker/manager 会话通过环境变量提权。
  - guard 对任意形式 `mf hook session-start`（含 cd/嵌套 shell/引号）与
    `roles.session_start/write_anchor` 解释器调用 fail-closed；锚点文件工具层直接写拒绝。
  - `mf role` 显示来源（anchor/directory）、会话标识与复位建议；`mf role --as <role>
    --reason` 仅用户终端可用（非 TTY 拒绝，rc=3），写 `role.switch` ledger；
    `mf role --json` 锚点路径统一序列化为字符串（A4）。
- 评审返工直达（MFP-0037）：
  - 评审 `NEEDS_REWORK` 后实现任务自动进入 `rejected`/rework，`next_owner=实现 worker`，
    所有风险级别同样直接回流，无需 manager 裁决/退回。
  - review/review-handoff 必须包含 `rework_summary`（原因/风险/问题影响/期望结果），
    缺失时不得提交；必须整改项支持小节/表格两种写法。
  - 范围外事项用 `needs: acceptance|bug|mfp|chg` 标注，不阻塞范围内返工；
    review→rework 链路、verdict、整改项与 next_owner 写入 ledger。
  - maintainer 可删除遗留角色锚点（清理降权），仍禁止创建/改写锚点内容。
- 评审提交即回流（MFP-0038）：`rework_scope` 支持粗体/下划线/反引号；必须整改项支持
  `### R4（in-scope）` 全角/无空格小节与表格；review 提交 `NEEDS_REWORK` 即触发目标
  `rejected/rework`、`next_owner=实现 worker`，无需 manager accept；`rework_summary`
  缺失拒绝提交；`MF_LEGACY_REWORK=1` 保留回滚通道。
- 维护者复位与误伤修复（MFP-0039/REQ-0023）：新增 `mf role --reset`（仅 maintainer，
  只清理 user-tty/当前会话/遗留锚点，写 `role.reset` ledger）；guard 只检查实际执行段，
  提交消息含 anchor、`uv run meta_flow`、只读 grep 不再误拦；worker/manager 锚点
  写入仍拒绝。
- 安全卡与负向矩阵（MFP-0041 A1/A3）：新增 `SECURITY-CARD.md`、`NEGATIVE-MATRIX.md`
  standards 模板与 `mf verify security-card` 校验（信任边界/攻击者能力/可证明
  fail_closed/不可防残余/风险接受人）；负向矩阵覆盖入口×变形×shell×环境；验收规范
  补充一任务一 commit（A4）与连续两轮同类绕过暂停（A6）。
- 安全负向矩阵（R4/R5）：会话入口覆盖模块方式、subprocess 列表/拼接字符串、
  拆分锚点函数名，只读检索（grep/cat）保持豁免。
- 全局 manifest 同步：`mf dev install` 成功后更新 `~/.meta-flow/manifest.yaml` 的
  `tool_version`/`source_dir`/`updated_at`，`mf dev status` 不再显示旧版本。
- 升级安装保留工作区导入：已存在 `.meta-flow/workspace.yaml` 时，`mf install claude
  --force` 继续写 `@<项目>-contract/workspace/CLAUDE.md` 导入，不覆盖为内联模板。
- 验证：全量 pytest 268 通过、ruff 通过、`mf doctor` OK；安全负向矩阵 N1–N6 覆盖见
  tests/test_designer_role.py。部署证据与回滚见 `docs/MAINTENANCE-1.0.3.md`。
- 升级/回滚：`UV_NO_CACHE=1 mf dev install --yes` 后确认 `mf --version` 输出 1.0.3；
  项目根与子项目 `mf install ... --force` 同步模板；回滚恢复 delivery.yaml/
  RELEASE-NOTES 与全局 mf 1.0.2。

## 1.0.2（R0/V1 P4 PATCH 发布）

- 版本：1.0.2（R0/V1）
- 日期：2026-11-26
- 路标：R0（P4）
- 契约版本：meta-flow-contract R0/P4
- 状态：待发布（版本元数据已统一；release freeze、发布清单 `release/RELEASE-1.0.2.yaml`、
  `git tag v1.0.2` 与 `git push` 待 manager/用户授权后执行）
- 范围：T027 批处理（MFP-0016..0020、MFP-0024..0027、MFP-0030）、BUG-0017 与 T029 版本 bump。
- 版本元数据（T029）：`pyproject.toml`、源码 `__version__`、`delivery.yaml` 与
  `RELEASE-NOTES.md` 统一为 1.0.2。
- 五阶段与模板（MFP-0016/0017/0019）：`PHASE.md` 每阶段补齐输入/输出/任务拆解规则/验证规则/退出条件；新增
  规格-模块矩阵与决策日志模板；TASK-CARD DoR 增加“可独立验证增量”、acceptance 验证绑定与
  BUG/MFP 自动化用例要求；P4 聚类验收 + 单条 REQ 状态双轨，P5 发布固定工作清单；
  文档必要性矩阵、页数上限与热/暖/冷角色读写矩阵落地。
- 状态对账（MFP-0018）：`mf doctor` 增加 TASK.yaml+ledger 与 state 的一致性检查；新增
  `mf state show` / `mf state rebuild`（幂等、保留活动任务/lease、ledger 记录重建）。
- 追踪闭环（MFP-0020）：`mf req trace` 输出 SPEC/TASK/证据/VR/BUG/MFP/CHG/RELEASE 链路；
  `mf req trace --check` 检测孤儿并返回非零；任务卡支持 module/spec_ids/verification/evidence，
  `mf task show` 生成人读摘要；task/bug/improve list 默认活跃，`--all`/`--history` 查历史。
- 关联 BUG 读取（MFP-0024）：任务包嵌入 fixes/inputs.bugs 摘要；`mf bug show` 对活动任务关联
  BUG 开放 worker 只读并写 READ-LOG，非关联 BUG 仍拒绝。
- 读取/写入通道（MFP-0025/0027）：packet 声明的 `.meta-flow/handoffs|dev-records/<task>.md`
  可写（仅当前任务）；must_read 契约基线可 `mf context expand` 只读补读；review_scope 内
  任意大小文件可 Read/expand。
- guard 只读 expand（BUG-0017）：`mf context expand ... --reason ...` 纯只读命令不再被
  guard 误判为 Bash 写入；路径授权与 READ-LOG 由 `context.expand` 负责，非 review_scope/
  越界路径仍拒绝并记录审计。
- BLOCKED 流转（MFP-0026）：handoff 结论 BLOCKED 或 `mf task submit --blocked` 时任务转
  `blocked`、next_owner=manager，不推进独立评审；manager 裁决后 worker 重新开始。
- 提交快照（MFP-0030）：越界检查排除 gitignored 路径与 task start 前已存在的未跟踪文件；
  `*.egg-info` 等构建产物不阻塞提交；worker 可清理自身构建产物。
- 回归：全量 pytest 207 通过、ruff 通过、`mf doctor` 与 `workspace sync --check` 通过；
  guard 负向用例（shell 变量/嵌套 shell/进程替换/越界写/跨项目）保持拒绝。
- 升级/回滚：`UV_NO_CACHE=1 mf dev install --yes` 后确认 `mf --version` 输出 1.0.2；
  回滚到 1.0.1 时恢复 delivery.yaml/RELEASE-NOTES 与全局 mf。

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
