# Meta Flow

> AI 项目操作系统：三个角色、契约库与多仓交付、规格驱动。

## 状态

**v0.1.0 / R0 重构中**。当前已实现安装、工作区、MFP、规划闭环、质量闭环与控制闭环：

```text
mf bootstrap
mf install claude [--agent maintainer]
mf install worker --project-dir <sub>
mf workspace init/add-project/link/sync/status
mf req add/list/show/update/trace/validate
mf roadmap show/plan/close
mf phase enter/review/exit
mf task create/list/show/start/submit/accept/reject/prompt
mf task graph/plan/next/release/summary
mf bug add/list/show/update/close
mf knowledge add/list/show/render
mf verify record/list/show
mf release freeze/show
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
│   └── settings.json          # {"agent":"manager"}
└── .meta-flow/install.yaml
```

不创建 `contracts/` 或 `deliveries/`。

### 3. manager 初始化工作区

在项目根启动：

```bash
claude        # 默认 manager
```

manager 与用户确认项目名、contract 仓路径/远程、子项目后执行：

```bash
mf workspace init --name <项目名> --contract-dir <项目名>-contract [--contract-remote <url>]
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
    ├── .claude/settings.json  # {"agent":"worker"}
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

源码仓库地址记录在 `~/.meta-flow/manifest.yaml` 的 `repo_url`。commit 可用，push 必须用户显式授权。

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

# worker 实现
mf task show R1-P1-T001 --packet
mf task start R1-P1-T001
mf task submit R1-P1-T001 --handoff <bundle>/handoff.md

# worker2 评审（review 任务）
mf task show R1-P1-T002 --review-packet
mf task start R1-P1-T002
mf task submit R1-P1-T002

# manager 验收
mf task accept R1-P1-T002 --verdict PASS
mf task accept R1-P1-T001 --verdict PASS
```

- 低风险：manager 先 review，再验收。
- 中/高风险：worker2 独立 review，之后 manager 验收。
- 评审不通过：`review-handoff.md` 列出必须整改项，manager 退回 worker1；返工后复审。
- 每个任务状态都有 `next_owner`；`mf task prompt` 明确下一责任 agent。

## 规划闭环

```bash
# 需求基线与 DoR（标题、优先级、可验收标准）
mf req add --title "用户登录" --priority must --acceptance "登录成功"
mf req list
mf req show REQ-0001
mf req update REQ-0001 --status verified
mf req trace REQ-0001
mf req trace                      # 生成 requirements/TRACE.md

# 路标/版本
mf roadmap show
mf roadmap plan R2 --title "v2" --version-target 2.0.0 --goal "第二版"
mf roadmap close R1               # 校验 REQ/任务/BUG；归档 archive/R1

# 五阶段
mf phase enter P2
mf phase review                   # 生成阶段 REPORT.md
mf phase exit --approved-by user  # P1/P2/P4/P5 需要用户门禁
```

`roadmap close` 生成关闭报告、下一版本交接、`LESSONS-R{n}.md`，并把任务、阶段计划/报告、VR、BUG 快照移入 `archive/R{n}/`。阶段退出生成 `HANDOFF-TO-P{n}.md`。

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

# 知识
mf knowledge add --kind term --text "契约库=项目公共规范和计划"
mf knowledge add --kind lesson --text "先写验收再实现"
mf knowledge render

# 版本冻结（不等于发布）
mf release freeze
mf release show
```

- `FAIL` 验证必须关联 `--bug`。
- `PASS` 验证会关闭关联 BUG；`task accept` 会把 fix 任务关联 BUG 置为 `fixed`。
- `release freeze` 检查需求、任务、blocker/critical BUG 和版本 MAJOR，写 `release/RELEASE-<version>.yaml`；`published: false`。
- 知识条目会自动注入任务包，控制 worker 上下文。

## 控制闭环

```bash
# 依赖、wave、写冲突与下一批
mf task graph
mf task plan
mf task next
mf task summary

# lease：start 写 2 小时租约；manager 回收
mf task start R1-P1-T001
mf task release R1-P1-T001 --force

# 热区、读扩展与归档
mf context show
mf context expand requirements/REQ-0001.md --reason human_audit
mf context log
mf archive list
mf archive show R1 --reason human_audit

# 状态、审计与自检
mf status
mf log
mf doctor
```

- `state/current.json` 只存指针/计数，≤8KB；修订历史进 `ledger.ndjson`。
- 任务 start 写 lease，防止同一任务被并发占用；`task release --force` 由 manager 回收。
- `context expand` 和 `archive show` 必须带 reason，并写 `READ-LOG.ndjson`。
- `task plan` 按 wave 分组并检查同一 wave 的 `allowed_paths` 冲突。
- `mf doctor` 校验需求 DoR、追踪、任务/依赖、BUG、知识、VR、路标/阶段与 state 大小。

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
