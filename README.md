# Meta Flow

> AI 项目操作系统：三个角色、契约库与交付库、规格驱动交付。

## 状态

**R0 骨架进行中**（v0.1.0）。当前已具备：

- `mf` CLI 骨架：`init`、`role`、`status`、`doctor`
- 工作区两仓初始化：`contracts/` + `deliveries/`
- 目录级角色推导：根目录 = maintainer，`contracts/` = manager，`deliveries/**` = worker
- 11 份默认规范模板
- `PROJECT-PLAN` 模板：过程、过程交付件、最终交付件能力
- 三个角色定义：`agents/meta-maintainer.md`、`meta-manager.md`、`meta-worker.md`
- 工作区结构、PROJECT-PLAN 与版本策略校验（`same-major` / `exact` / `independent`）

完整设计见 [DESIGN.md](DESIGN.md)。

## 安装

用户从 GitHub 安装，不发布 PyPI：

```bash
# R0 开发期先用 main；正式版本发布后改用 tag
uv tool install git+https://github.com/hyde-zhao/meta-flow@main
mf --version
```

用户不需要 clone 源码。维护者从源码安装：

```bash
git clone https://github.com/hyde-zhao/meta-flow
cd meta-flow
uv sync
uv run mf --version
```

## 平台支持

| 平台 | R1 | R2 |
|---|---|---|
| Claude Code | ✓ | ✓ |
| DeepSeek Harness (DSH) | - | ✓ |
| Codex | - | ✓ |

## 本地开发快速开始

```bash
uv sync
uv run mf --help

# 初始化一个工作区
uv run mf init --path /tmp/demo --name demo --delivery app --no-git

# 查看角色与状态
uv run mf role --path /tmp/demo/contracts
uv run mf status --path /tmp/demo
uv run mf doctor --path /tmp/demo
```

## 核心模型

```text
workspace/
├── contracts/     # 契约库：规范、需求、路标、计划、状态、验证、架构与端到端契约
└── deliveries/    # 交付库集合：源码、发布件、发布说明、用户手册
```

- 契约库是唯一公共真相源和跨库集成点。
- 交付库是完整交付单元，交付库之间不直接引用。
- manager 在契约库管理项目；worker 在交付库执行任务卡；maintainer 维护工作区和工具。
- 版本双轨：路标 `R{n}` ↔ 项目版本 `n.x.y`，交付物使用 SemVer。

## 角色

| 角色 | 目录 | 职责 |
|---|---|---|
| `meta-maintainer` | 工作区根目录 / 工具源码仓 | 建仓、安装、跨仓健康、工具维护 |
| `meta-manager` | `contracts/` | 需求、路标、五阶段、规范、任务卡、验收 |
| `meta-worker` | `deliveries/**` | 执行任务包、自验、交接、提交 |

设计工作使用 `kind: design` 任务，由 worker 执行，manager 验收；暂不新增角色。

## 开发

```bash
uv sync
uv run pytest
uv run ruff check src tests
```

## License

MIT。见 [LICENSE](LICENSE)。
