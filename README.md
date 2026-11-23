# Meta Flow

> AI 项目操作系统：三个角色、契约库与多仓交付、规格驱动。

## 状态

**v0.1.0 / R0.2 重构中**。当前安装与工作区流程：

```text
mf bootstrap
mf install claude [--agent maintainer]
mf install worker --project-dir <sub>
mf workspace init/add-project/link/sync/status
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
└── templates/         # 16 份规范 + 17 份制品模板 + 根配置模板
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
