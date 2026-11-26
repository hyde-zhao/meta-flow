# Meta Flow

> AI 项目操作系统：三个角色、契约库与多仓交付、规格驱动。

## 状态

**v1.0.2 / R0 1.0.x 试运行**。当前已实现安装、工作区、MFP、规划闭环、质量闭环与控制闭环：

```text
mf bootstrap
mf install claude [--agent maintainer]
mf install worker --project-dir <sub>
mf workspace init/attach/add-project/link/sync/status
mf req add/list/show/update/trace/validate
mf roadmap show/plan/close
mf phase enter/review/exit
mf task create/list/show/start/submit/accept/reject/prompt
mf task graph/plan/next/release/summary
mf bug add/list/show/update/close
mf knowledge add/list/show/render
mf verify record/list/show
mf release freeze/check/show
mf context show/expand/log/policy
mf archive list/show
mf status / mf log / mf doctor
mf uninstall claude
mf dev clone/update/install/status
mf role/status/doctor
```

## 安装

### 1. 全局模板库

```bash
uv tool install git+ssh://git@github.com/hyde-zhao/meta-flow@main
mf bootstrap
```

生成 `~/.meta-flow/`：

```text
~/.meta-flow/
├── manifest.yaml      # tool/template 版本、repo_url、source_dir
├── agents/            # manager / maintainer / worker
└── templates/         # 16 份规范 + 18 份制品模板 + 根配置模板
```

### 2. 项目安装

```bash
cd <项目根>
mf install claude                       # 只装 manager
mf install claude --agent maintainer    # 装 maintainer + manager
```

写入：

```text
<项目根>/
├── CLAUDE.md
├── README.md
├── .claude/
│   ├── agents/manager.md
│   ├── agents/maintainer.md   # 可选
│   └── settings.json          # {"agent":"manager","hooks":{...}}
└── .meta-flow/install.yaml
```

不创建 `contracts/` 或 `deliveries/`。

### 更新与升级

```bash
mf bootstrap --force                         # 只刷新 ~/.meta-flow 全局模板库
mf upgrade --project-dir <项目根> --force
mf upgrade --project-dir <子项目> --force
```

`--force` 只覆盖安装镜像（`.claude/agents`、`CLAUDE.md` 受管块、settings hook），
旧文件保留 `.bak`；contract 骨架只补缺失文件，不覆盖项目自定义的 standards/
templates/policies/README 与 phase plans（BUG-0015）。contract 内容变更走
manager 的评审/变更流程。

### 3. manager 初始化工作区

在项目根启动：

```bash
claude        # 默认 manager
```

manager 与用户确认项目名、contract 仓路径/远程、子项目后执行：

```bash
# 新项目
mf workspace init --name <项目名> --contract-dir <项目名>-contract [--contract-remote <url>] \
  [--roadmap R0 --phase P1 --version 1.0.0]
# 已有 contract：接入并导入路标/阶段/版本/workspace 注册，不覆盖既有内容
mf workspace attach --name <项目名> --contract-dir <项目名>-contract [--contract-remote <url>]
mf workspace add-project --name frontend --path frontend [--remote <url>]
mf workspace link
mf doctor
```

生成：

```text
<项目根>/
├── CLAUDE.md                  # @<项目名>-contract/workspace/CLAUDE.md
├── README.md                  # 软链或生成副本
├── mf.workspace.yaml
├── <项目名>-contract/          # git 仓库：契约库
│   ├── workspace/{CLAUDE.md,README.md,mf.workspace.yaml}
│   ├── project/ roadmap/ requirements/ architecture/ specs/
│   ├── standards/ templates/ tasks/ dev-records/ verification/
│   ├── handoffs/ reviews/ bugs/ knowledge/ policies/ state/ archive/
│   └── .meta-flow/role.yaml
└── frontend/                  # git 仓库：子项目
    ├── CLAUDE.md
    ├── .claude/agents/worker.md
    ├── .claude/settings.json  # {"agent":"worker","hooks":{...}}
    ├── .meta-flow/install.yaml
    ├── delivery.yaml
    └── src/ tests/ release/
```

### 4. 启动角色

```bash
cd <项目根> && claude                 # manager
claude --agent maintainer             # maintainer
cd frontend && claude                 # worker（独立会话）
```

子项目必须单独启动 Claude Code，才能读取它自己的 `.claude/settings.json`。

## PreToolUse 守卫

安装时会写入：

```json
{
  "agent": "manager",
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read|Write|Edit|MultiEdit|NotebookEdit|Grep|Glob|Bash",
        "hooks": [{"type": "command", "command": "mf hook pretool"}]
      }
    ]
  }
}
```

`mf hook pretool` 根据 cwd / `MF_ROLE` 推导角色，并在工具层拦截：

- manager 直接读 `archive/**`；直接读/写交付库 `src/**`、`tests/**`。
- worker 读完整契约、其他任务 bundle、其他交付库。
- worker 写非当前任务 bundle、`allowed_paths` 之外的交付源码。
- 直接改 `state/**`、写 `archive/**`、maintainer 改项目契约。
- Bash 命令同样经过路径策略与审计：worker 不能借 shell 读契约基线/其他交付库或绕过读预算；写操作受 `allowed_paths` 约束（BUG-0014）。`$HOME`/环境变量会展开，`sh -c`/`bash -c` 会递归解析；`eval`、`source`/`.`、进程替换 `<(...)`/`>(...)` 与转义变量 `\$HOME` 同样纳入解析或保守拒绝；无法安全解析且涉及路径时 deny。
- guard allow/deny 持久化到 READ-LOG（role/task/path/reason/tool），可用 `mf context log` 查询；拒绝信息包含当前任务/lease/allowed_paths 与合法通道。
- 提交后不可直接编辑；返工需 manager reject 后 `mf task start`。本地 `.meta-flow/improvements/MFP-*.yaml` 是受控写入白名单（或 `mf improve new --local`），其他越界写仍拒绝。
- bundle 匹配使用完整任务 ID/contract 相对路径；跨 roadmap/phase 的同尾号任务不会互相放行。

`--force` 只影响 CLI 技术校验；hook 对直接 Read/Write 的边界仍然生效。`mf uninstall` 会移除该 hook，保留其他自定义 hook。

## 维护者

`maintainer` 负责 meta-flow 自身与项目安装更新：

```bash
mf dev status
mf dev clone            # 克隆到 ~/.meta-flow/source
mf dev update           # git pull --ff-only
mf dev install --yes    # 从本地源码更新全局 mf
mf install claude --project-dir <root> --force
mf install worker --project-dir <sub> --force
mf uninstall claude --project-dir <path>
```

源码仓库地址记录在 `~/.meta-flow/manifest.yaml` 的 `repo_url`。commit 可用，push 必须用户显式授权。`mf dev status` 在 `source_dir` 缺失或不是 git 仓库时会显式报错，并提示 `mf dev clone` 或 `--source`。

MFP-0029：uv 在 `pyproject.toml` 版本号不变时会复用缓存构建，`mf dev install`
可能静默安装旧代码。CLI 已默认注入 `UV_NO_CACHE=1` 强制重建；同版本源码迭代后
请用 `UV_NO_CACHE=1 mf dev install --yes` 并检查 `mf --version`，或在安装后运行
`mf task --help` 等确认新命令存在。完整修复（`uv tool install --reinstall` 与
安装后自检）见 MFP-0029。

## MFP 改进包

manager 在 contract 仓创建工具改进包，提交到全局 inbox；worker 创建本地包，由 manager 导入；maintainer 读取并导入源码仓。

```bash
# manager
mf improve new --title "补充 task 命令"
# 填写上下文与验收标准后
mf improve validate MFP-0001
mf improve submit MFP-0001

# worker
mf improve new --local --title "worker 被工具缺口阻塞"

# maintainer
mf improve list --inbox
mf dev improve import <project>/MFP-0001 --kind requirement
mf dev improve import <project>/MFP-0001 --kind bug --already-implemented --version 0.1.1 --commit abc123
mf dev improve list --scope open
mf dev improve update MFP-0001 --status verified --version 0.1.2 --commit def456
```

已实现的 MFP 记录为 `BUG/REQ/CHG` 并关闭；未实现的完整包进入源码 `improvements/open/`，由 meta-flow 源码会话实施。

## 任务与评审

```bash
# manager 创建任务；中高风险会自动生成 review 任务
mf task create --title "实现 X" --risk high --acceptance "命令 mf X 成功"

# 查看下一步责任 agent（worker 或 manager）
mf task prompt R1-P1-T001

# worker 实现（在子项目目录启动）
mf task show R1-P1-T001 --packet
mf task start R1-P1-T001 --owner worker-1
mf task submit R1-P1-T001 --handoff <bundle>/handoff.md

# worker2 评审（review 任务，独立身份；只写 review.md + review-handoff.md）
mf task show R1-P1-T002 --review-packet
mf task start R1-P1-T002 --owner reviewer-2
mf task submit R1-P1-T002

# manager 验收（在项目根启动）
mf task accept R1-P1-T002 --verdict PASS
mf task accept R1-P1-T001 --verdict PASS
# critical 任务必须追加：
# mf task accept <task> --verdict PASS --user-approved-by <用户/记录>
```

- 低风险：manager 先 review，再验收。
- 中/高风险：worker2 独立 review，之后 manager 验收；高风险不能降级为 manager 自审或 `--no-review`。
- 评审结论从 `review-handoff.md` / `review.md` 读取；manager 不能用 `--verdict` 覆盖相反结论。
- 评审不通过：`review-handoff.md` 列出必须整改项，manager 退回 worker1；返工后复审。
- critical 任务必须记录用户验收 `--user-approved-by`。
- 每个任务状态都有 `next_owner`；`mf task prompt` 明确下一责任 agent。
- 角色守卫：manager 不能 `task start/submit`；worker 不能 `req/roadmap/phase/bug/verify/release/task accept`。
- 任务包按 effort（XS/S/M/L/XL）分配预算，并预置 allowed_paths 前缀的代码入口清单；
  超预算用 `mf context expand <path> --reason packet_missing` 或拆分任务。worker 可用
  `mf context show/expand` 受控查看活动任务 bundle、评审目标或 allowed_paths，并写
  READ-LOG。
- 评审包（`--review-packet`）按 `reviews` 目标嵌入被评审任务的 dev-record、handoff 与
  diff；证据缺失时显式报错，不再静默显示 missing。
- review 任务提交只需 `review.md` + `review-handoff.md`；handoff/dev-record 要求仅适用于
  implement/fix 任务（MFP-0013）。返工任务可读自己评审任务的 review 输出。
- handoff/dev-record/evidence 由 packet 的 process paths 显式授权，独立于
  `allowed_paths`/`forbidden`；`mf task submit` 支持 `.meta-flow/dev-records|handoffs`
  本地副本（仅当前任务，guard 放行并审计）。packet 的必须读取项（TASK.yaml/REQ/SPEC/
  标准/BUG/MFP）可用 `mf context expand --reason packet_missing` 只读补读（READ-LOG）。
- BLOCKED 流转（MFP-0026）：handoff 结论写 `BLOCKED` 或 `mf task submit --blocked`
  时任务转 `blocked`、next_owner=manager，关联 review 保持 draft/ready 不推进；
  manager 改卡/扩 allowed_paths 后 worker 用 `mf task start/rework` 重新开始。
- 任务卡按机器需要最小化：支持 `module`、`spec_ids`、`verification`/`evidence`；
  `mf task show` 输出人读摘要。`mf task list` 默认活跃，`--all` 含 accepted/cancelled。
- review 任务可读取 review_scope 内任意大小文件（Read 或 `mf context expand`），
  guard 不把 expand 误判为写入；review_scope 外仍拒绝。
- 并行任务：提交时按任务活动窗口隔离其他并行任务的 diff；单任务越界仍拒绝，
  非活动/非重叠改动不被静默计入；diff.patch 包含未跟踪新增文件。
- worker 无交付根绑定时任务命令要求 `--project-dir <交付库>`，否则 rc=3；guard
  同规则。

## 规划闭环

```bash
# 需求基线与 DoR（标题、来源、优先级、可验收标准）
mf req add --title "用户登录" --priority must --acceptance "登录成功" --non-goal "不做第三方登录"
mf req list
mf req show REQ-0001
mf req update REQ-0001 --status verified
mf req trace REQ-0001
mf req trace                      # 生成 requirements/TRACE.md（当前路标，排除 archive）
mf req trace --archive            # 审计历史：显式包含 archive
mf req trace --check              # 孤儿/未闭环检查（REQ/SPEC/TASK/证据/VR/BUG/MFP/CHG/RELEASE），有孤儿返回 1

# 路标/版本
mf roadmap show
mf roadmap plan R2 --title "v2" --version-target 2.0.0 --goal "第二版"

# 五阶段：exit 记录门禁，enter 推进；不能跳级
mf phase exit --approved-by user  # P1 退出（用户确认）
mf phase enter P2
mf phase review                   # 生成阶段 REPORT.md
mf phase exit --approved-by user  # P2 退出；P3 不需要用户门禁
mf phase enter P3
# P3 exit -> enter P4 -> exit --approved-by user -> enter P5
# P5 exit --approved-by user

mf release freeze                 # 阶段策略：P3 结束后可发；P4/P5 修复随时可发；P1/P2 禁止
mf roadmap close R1               # 需要 P5 退出 + 用户批准 + 已冻结
```

`roadmap close` 生成关闭报告、下一版本交接、`LESSONS-R{n}.md`，并把任务、阶段计划/报告、VR、BUG、release 清单迁入 `archive/R{n}/`。阶段退出生成 `HANDOFF-TO-P{n}.md`。`--force` 只能绕过技术校验，不能绕过用户门禁。

## 质量闭环

```bash
# L1/L2/L3 验证
mf verify record --layer implementation --scope "登录" --result PASS \
  --task R1-P1-T001 --requirement REQ-0001
mf verify list --layer implementation

# 缺陷
mf bug add --title "登录报错" --severity major --requirement REQ-0001
mf bug update BUG-0001 --status fixed --fix-task R1-P1-T001
mf bug close BUG-0001 --verification "回归通过"

# 知识（可限定交付库）
mf knowledge add --kind term --text "契约库=项目公共规范和计划"
mf knowledge add --kind lesson --text "先写验收再实现"
mf knowledge add --kind convention --text "前端统一用 pnpm" --delivery frontend
mf knowledge render

# 版本冻结与发布一致性（不等于发布）
mf release freeze
mf release check --source-dir ../meta-flow
mf release show
```

- `FAIL` 验证必须关联 `--bug`。
- `PASS` 验证把关联 BUG 置为 `verifying`，最终关闭仍由 manager 执行 `mf bug close`。
- `task accept` 会把 fix 任务关联 BUG 置为 `fixed`；manager 验证后再关闭。
- `release freeze` 按阶段策略检查：P1/P2 禁止冻结/发布；P3 active 仅允许
  alpha/预发布；P3 阶段结束（exited/done）后允许正式发布；P4/P5 的修复/补丁
  可随时冻结，不要求阶段结束或 P5 退出。同时检查需求、任务、blocker/critical
  BUG 与版本策略，写 `release/RELEASE-<version>.yaml`；`published: false`。
  阶段门属用户门禁，`--force` 不能绕过；版本/技术校验仍可用 `--force`。
- 版本一致性（MFP-0028）：冻结前校验交付库版本单源——`pyproject.toml`、
  源码 `__version__`、`delivery.yaml`、`RELEASE-NOTES.md`、git tag 与发布清单
  `release/RELEASE-<version>.yaml` 必须一致，任一处不一致时失败（不得静默沿用
  旧版本号）。交付源码目录默认探测当前目录与契约同级交付库，也可显式
  `--source-dir`。`mf release check [--require-tag] [--json]` 做发布前/后审计：
  一致返回 0，不一致返回 1 并列出失败字段；`--require-tag` 要求 `v<version>`
  tag 存在，且 tag 指向的 `pyproject.toml`/源码版本必须与目标版本一致。
  版本一致性属技术校验，`--force` 不可绕过。
- 版本策略：优先读取 ROADMAP 的 `version_major`/`version_range` 声明映射（支持
  R0/V1 1.0.x）；未声明的 MAJOR 不一致默认拒绝。`--force` 必须带
  `--reason` 与 `--approved-by`，并写入发布清单 `override` 与 ledger。
- 知识条目按交付库/项目/路标与任务相关性过滤后注入任务包，不跨项目匹配同名任务 ID。
- 测试已隔离 cwd/MF_ROLE，工作区内与 `/tmp` 运行全量 pytest 结果一致。

## 控制闭环

```bash
# 依赖、wave、写冲突与下一批（manager）
mf task graph
mf task plan
mf task next
mf task summary

# lease：start 写 2 小时租约；manager 回收
# worker 在子项目运行：
mf task start R1-P1-T001 --owner worker-1
# manager 在项目根回收：
mf task release R1-P1-T001 --force

# 热区、读扩展与归档（manager）
mf context show
mf context expand requirements/REQ-0001.md --reason human_audit
mf context log
mf archive list
mf archive show R1 --reason human_audit

# 状态、审计与自检
mf status
mf state show                     # 对账 TASK.yaml+ledger 与 state 派生快照
mf state rebuild                  # 从 TASK.yaml/ledger 重建 state（幂等、保留 lease、审计）
mf log
mf doctor
```

- `state/current.json` 只存指针/计数，≤8KB；TASK.yaml + ledger 是任务真相，state 是派生快照。
  手工漂移由 `mf doctor` 对账报警，用 `mf state rebuild` 重建（幂等、保留活动任务/lease、写审计）；
  截断时写 `state.truncate`，完整列表用 `mf task summary`。
- 缺失或损坏时从 ROADMAP/tasks/handoff 重建；修订历史进 `ledger.ndjson`。
- 任务 start 写 lease，并检查依赖、同 wave 写冲突和 `owner`；`task release --force` 由 manager 回收。
- `task submit` 用 git diff + 工作树快照校验 `allowed_paths`/`forbidden`，越界拒绝；
  gitignored 构建产物与 task start 前已存在的未跟踪文件不阻塞提交（MFP-0030）。
- `context expand` 和 `archive show` 必须带 reason；archive 只允许 manager，并写 `READ-LOG.ndjson`。
- `context show` 显示热区文件大小、总量和 manager 8KB/128KB 预算；超出预算的整文件读取被拒绝。
- worker 只能通过 `task show --packet` 获取上下文；任务包声明 read policy、预算和 `packet_digest`。
- `task plan` 按 wave 分组并检查同一 wave 的 `allowed_paths` 冲突；`task start` 会拒绝未满足依赖或冲突任务。
- `mf req list` / `mf req trace` / `mf bug list` / `mf verify list` 默认只读当前路标；用 `--all` 查看历史。
- `mf knowledge render` 生成热区 `KNOWLEDGE.md`（≤8KB）和冷区 `LESSONS.md`；任务包只注入热区知识。
- `mf log` / `mf context log` 从文件尾部读取，避免全量载入 ledger/READ-LOG。
- `mf doctor` 校验需求 DoR、追踪、任务/依赖、BUG、知识、VR、路标/阶段、策略文件、归档引用和 state 大小。

### 热区 / 温区 / 冷区

| 层 | 内容 | 读取方式 |
|---|---|---|
| 热 | `state/current.json`、ROADMAP、当前 R/阶段 PLAN、需求/架构 INDEX、`KNOWLEDGE.md`、上一阶段 handoff | manager 会话；`mf context show` 统计大小 |
| 温 | 当前路标 REQ 详情、DESIGN/SPEC、当前阶段任务 bundle、当前版本 VR/BUG | 按 ID/任务包读取；默认列表当前路标 |
| 冷 | `archive/R{n}/`（任务、阶段报告、VR、BUG、release、需求快照）、旧 lessons | 只能 `mf archive show --reason`；直接 Read 被 hook 拒绝 |

版本关闭时，`roadmap close` 会把该版本的任务、阶段文档、VR、BUG、release 清单和需求快照迁入 `archive/R{n}/`。

## 卸载

```bash
mf uninstall claude --project-dir <root>
mf uninstall claude --project-dir <sub>
```

按 `.meta-flow/install.yaml` 记录删除管理的 agent、CLAUDE.md managed block、settings 中的 `agent` 字段和安装记录；默认保留 contract 仓与子项目源码。`--purge` 额外移除 workspace 元数据。

## 开发

```bash
uv sync
uv run pytest
uv run ruff check src tests
```

## License

MIT。见 [LICENSE](LICENSE)。
