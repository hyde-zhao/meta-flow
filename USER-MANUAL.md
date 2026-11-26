# 用户手册

## 适用对象

本手册面向使用 meta-flow 的项目 manager、worker 与 maintainer。版本按
`x.y.z = V.R.patch` 管理：当前 V1/R0 = 1.0.x（工具版本 1.0.2），R1 =
V1/R1 = 1.1.x。命令以 `mf` 1.0.2 为准；绑定声明见 contract 的
`roadmap/ROADMAP.yaml`（`version_major`/`version_range`）。
版本单一来源：`pyproject.toml`、源码 `__version__`、`delivery.yaml`、
`RELEASE-NOTES.md` 与发布清单必须一致，发布前用 `mf release check` 校验。

## 安装与部署

1. 安装工具（源码安装）：

   ```bash
   git clone git@github.com:hyde-zhao/meta-flow.git
   cd meta-flow
   UV_NO_CACHE=1 uv tool install --force .
   mf --version
   ```

   同版本号源码迭代时，uv 可能复用缓存构建（MFP-0029），必须带
   `UV_NO_CACHE=1` 或 `uv tool install --force --reinstall .`；安装后确认
   `mf --version` 输出源码版本（当前 1.0.2）。

2. 初始化全局模板库：

   ```bash
   mf bootstrap
   mf doctor --global
   ```

3. 在项目根安装 manager（可选同时安装 maintainer）：

   ```bash
   mf install claude --project-dir <项目根>
   # 或
   mf install claude --project-dir <项目根> --agent maintainer
   ```

   安装会生成 `.claude/`、`CLAUDE.md`、`.meta-flow/install.yaml`，并在 git 仓库
   维护安装镜像忽略块；非 git 目录跳过 `.gitignore`。安装镜像不入库。

4. 更新与升级：

   ```bash
   mf bootstrap --force            # 刷新 ~/.meta-flow 全局模板库
   mf upgrade --project-dir <项目根> --force
   mf upgrade --project-dir <子项目> --force
   mf doctor --path <项目根>
   ```

   `--force` 只覆盖项目安装镜像（`.claude/agents`、`CLAUDE.md` 受管块、
   `.claude/settings.json` hook），旧文件保留 `.bak` 备份；contract 的
   standards/templates/policies/improvements README 与 R1 phase plans 等只在
   缺失时补建，**不会覆盖项目自定义内容**（BUG-0015）。`mf bootstrap --force`
   同样只刷新 `~/.meta-flow` 全局模板，不触碰 contract。contract 内容变更走
   manager 的评审/变更流程（`mf task`、`CHG-*`），不能用安装升级强制覆盖。

## 快速开始 1：全新项目

目标：从空目录完成安装、工作区、manager 规划、worker 第一个任务与验收。

### 1. 初始化工作区（manager）

```bash
cd <项目根>
mf workspace init --name "示例项目" --contract-dir 示例项目-contract \
  --roadmap R0 --phase P1 --version 1.0.0
mf workspace add-project --name backend --path backend \
  --remote git@github.com:you/backend.git
mf workspace link
mf doctor --path .
```

检查点：

- `<项目根>/CLAUDE.md` 只含 `@示例项目-contract/workspace/CLAUDE.md` 导入行；
- `<项目根>/README.md` 指向 contract 的 workspace README；
- contract 内 `roadmap/ROADMAP.yaml` 含 `version_major`、`version_target`；
- `mf doctor` 输出 `mf doctor: OK`。

### 2. manager 规划（需求 / 路标 / 阶段 / 任务）

```bash
mf req add --title "用户可登录" --priority must --acceptance "登录成功"
mf roadmap show
mf phase enter P1
mf task create --title "实现登录接口" --kind implement --risk high \
  --allowed-path "src/**" --allowed-path "tests/**" \
  --acceptance "接口返回 200" --acceptance "失败用例覆盖"
mf task prompt R0-P1-T001
```

说明：高风险任务会自动生成独立 review 任务（如 `R0-P1-T002`）。先运行
`mf task prompt` 确认 `responsible_agent` 与下一责任，再交给 worker。

### 3. worker 开发（子项目）

```bash
cd backend
mf task prompt R0-P1-T001
mf task show R0-P1-T001 --packet
mf task start R0-P1-T001
```

任务包给出 allowed_paths、验收、预算、代码入口、process paths（handoff /
dev-record / evidence）。worker 只改 allowed_paths 内文件；完成后写：

```text
<contract>/roadmap/R0/phases/P1/tasks/T001/dev-record.md
<contract>/roadmap/R0/phases/P1/tasks/T001/handoff.md
```

（也可写交付库 `.meta-flow/dev-records/R0-P1-T001.md` 与
`.meta-flow/handoffs/R0-P1-T001.md`，提交时会回退读取。）

自验并提交：

```bash
pytest -q && ruff check .
mf task submit R0-P1-T001 \
  --handoff ../示例项目-contract/roadmap/R0/phases/P1/tasks/T001/handoff.md
mf task prompt R0-P1-T001
```

超过读预算的单文件（>64KB）不要用 `cat` 硬读：用
`mf context show` 查看活动任务 bundle，或
`mf context expand <path> --reason packet_missing` 受控补读（写 READ-LOG）。
hook 同时覆盖 Bash，worker 不能借 shell 读取契约基线、其他交付库或绕过读预算。

### 4. 独立评审与验收（manager）

```bash
mf task prompt R0-P1-T002
mf task show R0-P1-T002 --review-packet
# reviewer 写 review.md / review-handoff.md，结论 PASS|PASS_WITH_RISK|
# NEEDS_REWORK|BLOCKED；review 任务只写这两个文件，无需 handoff.md
mf task submit R0-P1-T002
mf task accept R0-P1-T002 --verdict PASS
mf task accept R0-P1-T001 --verdict PASS
mf verify record --layer implementation --scope "登录接口" \
  --result PASS --requirement REQ-0001
```

检查点：实现者不自验收；PASS_WITH_RISK 必须写风险与接受人；每任务后
`mf task prompt` 明确 next_owner。

## 快速开始 2：迁移项目

目标：把已有项目接入 meta-flow，保留原项目内容与历史，不丢源码/文档/任务。

### 1. 盘点与环境

```text
- 原项目源码、测试、构建脚本、发布文档；
- 已有需求/设计/任务/缺陷记录（Markdown、Excel、issue 列表均需导出摘要）；
- 已有 contract 仓（若存在）及其远程地址；
- 交付库清单、分支、版本号（旧版本标注 V0 cold）。
```

```bash
cd <原项目根>
mf bootstrap
mf install claude --project-dir .
```

### 2. 重建或接入 contract

新 contract（无历史 contract）：

```bash
mf workspace init --name "迁移项目" --contract-dir 迁移项目-contract \
  --roadmap R0 --phase P1 --version 1.0.0
```

已有 contract：先 clone 到项目根下，再接入（保留原 contract 内容）：

```bash
git clone <contract-remote> 迁移项目-contract
mf workspace attach --name "迁移项目" --contract-dir 迁移项目-contract \
  --contract-remote <contract-remote>
mf workspace link
mf doctor --path .
```

`workspace attach` 只导入 roadmap/phase/version/workspace 注册与子项目登记，
不覆盖已有 contract；已注册项目 id/名称冲突时直接报错。不导入源码或实现。

### 3. 迁移文档与任务

1. 需求：按原需求逐条 `mf req add`，保留原编号到 `source`/描述，补验收标准。
2. 路标/阶段：在 ROADMAP.yaml 声明 `version_major`（旧 0.x 记为 V0 cold）；
   当前工作放到 R0 的对应阶段。
3. 设计/规范：把跨库真相放进 contract；交付库文档（delivery.yaml、
   RELEASE-NOTES、USER-MANUAL、DESIGN、README）留在交付库并入库。
4. 任务：历史任务不伪造完成证据；未完成工作用 `mf task create` 重建，
   `inputs` 引用原需求，allowed_paths 只列本次要改的路径。
5. 子项目：

   ```bash
   mf workspace add-project --name backend --path backend
   mf workspace add-project --name frontend --path frontend
   mf workspace link
   mf doctor --path .
   ```

检查点：`mf doctor` OK、`mf workspace sync --check` OK；交付仓 git status 只含
交付文档与源码，不出现 CLAUDE.md/.claude/.meta-flow；contract 原内容未被覆盖。

### 4. 首个任务与验收

```bash
mf task plan
mf task create --title "迁移后回归基线" --risk medium \
  --allowed-path "tests/**" --acceptance "全量测试通过"
mf task prompt R0-P1-T001
cd backend
mf task show R0-P1-T001 --packet
mf task start R0-P1-T001
# 实现 + 测试 + dev-record + handoff
mf task submit R0-P1-T001
cd ..
mf task accept R0-P1-T001 --verdict PASS
```

## 功能说明

### 工作区

| 命令 | 说明 |
|---|---|
| `mf workspace init` | 新建 contract 与工作区注册，可声明 roadmap/phase/version |
| `mf workspace attach` | 接入已有 contract；不覆盖 contract，不导入源码 |
| `mf workspace add-project` | 安装 worker 子项目并登记 |
| `mf workspace link` | 重建根 CLAUDE/README 链接并刷新安装 digest |
| `mf workspace sync [--check]` | 校验/刷新根生成文件 |
| `mf workspace status` | 查看 contract/子项目 git 与版本 |
| `mf doctor --path <p>` / `--global` | 校验安装、工作区、契约、规划数据 |

### 任务与评审

- `mf task create/start/submit/prompt/show --packet/--review-packet`。
- 评审包按 `reviews` 目标嵌入被评审任务的 dev-record/handoff/diff；证据缺失显式报错。
- review 任务提交只需 `review.md` + `review-handoff.md`；implement/fix 仍要求
  handoff/dev-record。
- 返工任务可读自己评审任务的 review 输出，只整改必须项。
- 任务包按 effort（XS/S/M/L/XL）选择预算档位；超出用
  `mf context expand <path> --reason packet_missing` 分段读取或拆分任务。worker 可
  受控 show/expand 活动任务 bundle、评审目标、allowed_paths 与任务包 must_read
  契约基线（TASK.yaml/REQ/SPEC/标准/BUG/MFP，写 READ-LOG）；非 must_read 仍拒绝。
- worker 可写任务包声明的本地副本 `.meta-flow/handoffs/<task>.md`、
  `.meta-flow/dev-records/<task>.md`（仅当前任务）与 `.meta-flow/improvements/MFP-*.yaml`；
  其他 `.meta-flow/**` 仍拒绝。
- 提交后不可直接编辑；返工先由 manager reject，再 `mf task start <id>`。本地 MFP 写
  `.meta-flow/improvements/MFP-*.yaml` 或 `mf improve new --local` 均受审计，其他
  越界写仍拒绝。
- `mf task submit --blocked`（或 handoff 结论写 `BLOCKED`）转 manager 裁决：任务状态为
  `blocked`、next_owner=manager，关联 review 任务保持 draft/ready、不派给评审者；
  manager 改卡/扩 allowed_paths 后 worker 用 `mf task start/rework` 重新开始。
- `mf task show` 输出人读摘要（模块/规格/验收/责任），不再需要手工维护第二份状态；
  任务卡支持 `module`、`spec_ids`、`verification`/`evidence` 机器字段。
- `mf task list` 默认只列活跃任务（draft/ready/in_progress/submitted/blocked/rework/rejected），
  `--all` 才含 accepted/cancelled；`mf bug list`/`mf improve list` 同理（`--history`/`--all`）。
- `mf task submit` 只校验本任务变更：并行任务按活动窗口隔离；单任务越界仍拒绝；
  evidence/diff.patch 包含未跟踪新增文件。task start 前的未跟踪文件与 gitignored
  构建产物（如 `*.egg-info/`）不阻塞提交；worker 可用 `git clean`/`rm` 清理自身构建产物。
- 评审任务可读取 review_scope 内任意大小文件（Read 或 `mf context expand`），不受
  64KB 预算限制；review_scope 外仍拒绝。
- guard 覆盖 Bash：`$HOME`/环境变量会展开，`sh -c`/`bash -c` 会递归解析，
  `eval`/`source`/`.`/进程替换 `<(...)`/`>(...)` 与转义变量 `\$HOME` 同样受策略约束；
  无法安全解析且涉及路径时保守拒绝。allow/deny（role/task/path/reason/tool）持久化到
  READ-LOG，可用 `mf context log` 查询；deny 会给出当前任务/lease/allowed_paths 与
  合法通道。
- 任务 bundle 匹配使用完整任务 ID；跨 roadmap/phase 的同尾号任务不会互相放行。
- worker 无交付根绑定时，在 workspace 根执行任务命令必须带 `--project-dir
  <交付库>`，否则 rc=3；从交付库目录运行或设置显式交付绑定后自动限定作用域。
- 评审结论仅 PASS / PASS_WITH_RISK / NEEDS_REWORK / BLOCKED；高风险任务由未参与
  实现的 reviewer 评审，实现者不得自验收。

### 需求与版本

- `mf req add/list/update/trace/validate`。`mf req trace` 默认只追踪当前路标，
  排除 archive、BUG 按 id 去重、SPEC 只匹配 `SPEC-*.md`；审计历史用
  `mf req trace --archive`。
- `mf req trace --check`（MFP-0020）：输出 REQ→SPEC→TASK→证据→VR→BUG/MFP/CHG→RELEASE
  链路并检测孤儿：无 SPEC/TASK/证据/VR 的 REQ、无 REQ/SPEC 的 TASK、accepted 但
  BUG 未关闭、未关闭且无修复任务的 BUG、MFP 无验收/实施证据、CHG 未闭环；有孤儿
  返回 1。阶段门/发布门用 `--all --check` 做一次全量对账。
- `mf state show/rebuild`（MFP-0018）：TASK.yaml + ledger 是任务真相，`state/current.json`
  是派生快照。`mf doctor` 会做状态对账（counts/ready/submitted/lease/next_owner/
  source_digest/ledger 最近事件）；不一致时运行 `mf state rebuild` 安全重建（保留活动
  任务与 lease、幂等、ledger 记录 `state.rebuild`）。禁止手工编辑 state。
- `mf release freeze` 阶段策略：P1/P2 禁止冻结/发布；P3 active 仅允许
  alpha/预发布，P3 阶段结束（exited/done）后允许正式发布；P4/P5 的修复/补丁
  可随时冻结，不要求阶段结束或 P5 退出。阶段门属用户门禁，`--force` 不能绕过。
- `mf release freeze`：优先使用 ROADMAP 声明的 `version_major`/`version_range`
  （支持 R0/V1 1.0.x）；未声明的 MAJOR 不一致默认拒绝；`--force` 必须带
  `--reason` 与 `--approved-by`，并写入发布清单 `override` 与 ledger。
- `mf release check`（MFP-0028）：发布一致性校验——发布清单、`pyproject.toml`、
  源码 `__version__`、`delivery.yaml`、`RELEASE-NOTES.md` 与 git tag 必须与目标
  版本一致；不一致返回 1 并列出失败字段。`--source-dir` 指定交付源码目录（默认
  探测当前目录与契约同级交付库）；`--require-tag` 要求 `v<version>` tag 存在且其
  指向的版本文件一致。`mf release freeze` 冻结前也会执行交付库版本校验，不一致
  时失败；版本一致性属技术校验，`--force` 不可绕过。

### 维护者

- `mf dev status`：source_dir 缺失/非 git 时显式报错，引导 `mf dev clone` 或
  `--source`。
- `mf dev clone/update/install --yes`；`mf dev improve import/list/update`。
- MFP-0029：`mf dev install` 已默认注入 `UV_NO_CACHE=1`，避免同版本号复用旧
  构建；安装后务必用 `mf --version` 与关键命令（如 `mf task --help`）确认全局
  工具与源码 HEAD 一致。完整 `--reinstall` 与安装自检待 MFP-0029 实施。
- `mf install/uninstall/upgrade`；push 与远程创建需用户授权。

## 故障排查

| 现象 | 处理 |
|---|---|
| `角色: unbound` | 在 workspace 根/contract/子项目运行，或显式 `MF_ROLE`；首次 init/attach 由安装角色 bootstrap |
| worker 任务命令 rc=3 | 无交付根绑定：加 `--project-dir <交付库>` 或进入交付库目录 |
| 根 CLAUDE.md 被判 modified | 运行 `mf workspace link` 刷新 install digest；再 `mf doctor` |
| `mf dev status` 报源码不存在 | 运行 `mf dev clone` 或 `--source <有效源码目录>` |
| release freeze 拒绝 MAJOR | 在 ROADMAP 声明 `version_major`/`version_range`；例外用 `--force --reason --approved-by` |
| release freeze 阶段被拒 | P1/P2 禁止发布；P3 active 仅 alpha/预发布，先 `mf phase exit` 再正式冻结；P4/P5 修复可直接冻结（阶段门不可 `--force` 绕过） |
| release freeze/check 报版本不一致 | 同步 `pyproject.toml`、源码 `__version__`、`delivery.yaml`、`RELEASE-NOTES.md` 与发布清单；tag 指向旧版本时重打 `v<version>`（MFP-0028） |
| `mf --version` 仍是旧版本 | 源码 `__version__` 未更新，或全局工具未重装：`UV_NO_CACHE=1 mf dev install --yes`（MFP-0028/0029） |
| 追踪矩阵出现旧任务/重复 BUG | 使用默认当前路标追踪；仅在审计时 `--archive` |
| 工作区内 pytest 角色门失败 | 0.1.1 起测试已隔离 cwd/MF_ROLE；仍失败时检查是否自定义 fixture 设置了角色 |
| worker 读到 >64KB 文件被拒 | 用 `mf context expand <path> --reason packet_missing`；常规 Read/cat 受预算限制 |
| 评审包显示证据缺失 | 目标任务未提交或未固化 dev-record/handoff/diff；先完成目标任务 submit 再生成 |
| review 任务 submit 提示缺少 handoff | 0.1.1 起 review 只需 review.md + review-handoff.md；若仍报错请升级 `mf` |
| Bash 被 guard 拒绝 | 检查路径是否在契约基线/其他交付库/allowed_paths 之外；worker 用任务 bundle 与合法 CLI；变量/嵌套 shell/eval/source/进程替换无法安全解析时会被保守拒绝 |
| 提交后需要修改文件 | 不能直接编辑；由 manager reject 后 `mf task start <id>`；本地 MFP 例外（`.meta-flow/improvements/MFP-*.yaml`） |
| 看不到 guard 拦截原因/审计 | deny 信息含角色/任务/lease/allowed_paths；manager 用 `mf context log` 查询 allow/deny |
| 任务提交提示越界但文件属于并行任务 | 确认两个任务都处于重叠活动窗口且 allowed_paths 不相交；非活动改动仍会被拒绝 |
| 提交仍报 egg-info/构建产物越界 | 1.0.2 起提交快照排除 gitignored 与 start 前未跟踪文件；若仍报错，确认 `.gitignore` 规则并运行 `git status --ignored` 核对 |
| `mf doctor` 报“状态对账” | state 派生快照过期：运行 `mf state rebuild`；不要手工编辑 `state/current.json` |
| worker `mf bug show` 被拒 | 1.0.2 起只允许读取活动任务 `fixes`/`inputs.bugs` 关联的 BUG；非关联 BUG 由 manager 读取 |
| `mf req trace --check` 返回 1 | 按输出逐项补 SPEC/TASK/证据/VR，关闭 BUG/MFP/CHG 或登记原因；仅审计历史时用 `--archive` |
| 写 `.meta-flow/handoffs|dev-records/<task>.md` 被拒 | 1.0.2 起仅当前 in_progress 任务的本地副本可写；提交后需 manager 重开 |
| 安装镜像被 git 跟踪 | 确认 `.gitignore` 含 `# >>> meta-flow install mirror >>>` 块；运行 `mf install/upgrade` 修复 |
