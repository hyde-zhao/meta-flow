# SCOPE-Pack 元工作流

> 通用 Agent/Skill 工作流产物工厂 — 从需求到交付的全流程编排。

## 目录结构

| 目录 | 用途 |
|------|------|
| `agents/` | **交付 Agent 源目录**（安装脚本默认从此读取，文件名为 `<name>.md`） |
| `skills/` | **交付 Skill 源目录**（安装脚本默认从此读取，结构为 `skills/<name>/SKILL.md`；如有模板，位于 `skills/<name>/templates/`） |
| `rules/` | **交付规则源目录**（如 `AGENTS.md`、`CLAUDE.md`、`copilot-instructions.md`） |
| `.agents/agents/` | 元工作流内部 Agent 定义（保留） |
| `.agents/skills/` | 元工作流内部 Skill 定义（保留） |
| `.github/agents/` | Copilot CLI 入口（元工作流 Agent） |
| `.input/` | 只读输入目录（用户提供的原始材料） |
| `process/` · `checkpoints/` · `delivery/` | **工作流三层输出目录** — 运行态 / 确认态 / 交付态 |
| `docs/` | 参考文档和源材料 |
| `scripts/` | 元工作流工具脚本与安装脚本 |

## 输出隔离原则

所有由元工作流产生的运行时文档、人工确认稿与最终交付物统一按层输出：

```
├── process/                     # 运行时文档（默认建议 gitignore）
│   ├── STATE.md
│   ├── REQUEST.md
│   ├── INPUT-INDEX.md
│   ├── CLARIFICATION-LOG.md
│   ├── USE-CASES.md
│   ├── REQUIREMENTS.md
│   ├── HLD.md
│   ├── ARCHITECTURE-DECISION.md
│   ├── STORY-BACKLOG.md
│   ├── DEVELOPMENT-PLAN.yaml
│   ├── TEST-STRATEGY.md
│   ├── changes/
│   └── stories/
├── checkpoints/                 # 人工确认稿（默认建议 gitignore）
│   ├── CHECKPOINT-REQUIREMENTS.md
│   ├── CHECKPOINT-HLD.md
│   ├── CHECKPOINT-STORY-PLAN.md
│   └── CHECKPOINT-STORY-LLD-<story-id>.md
└── delivery/                    # 最终交付物（默认入库）
    ├── README.md
    ├── doc/
    ├── agents/
    ├── skills/
    ├── rules/
    └── scripts/
```

测试时可在 `delivery/` 目录中独立启动 Agent 加载产物文件：

```bash
cd delivery && copilot @ptm-tde
```

## Python 环境规范（uv）

当前仓库对 Python 运行环境采用 `uv` 作为统一工具链，但仓库当前**尚未**内置 `pyproject.toml` / `uv.lock`。因此本阶段的执行约束是：

1. 使用 `uv` 安装和选择 Python 解释器，不以系统 Python 作为默认入口。
2. 运行仓库内 Python 脚本时，优先使用 `uv run --python <version> python <script>`。
3. 一次性工具与临时依赖优先使用 `uvx` 或 `uv run --with <package>`，不把裸 `pip install` 作为日常流程。
4. 安装到目标项目的 uv 规范统一通过 `rules/AGENTS.md`、`rules/CLAUDE.md`、`rules/copilot-instructions.md` 传播。

示例：

```bash
uv python install 3.11
uv run --python 3.11 python scripts/install.py --platform claude-code --dry-run
```

## 开发节奏

1. `meta-pm` 输出需求与场景
2. `meta-se` 输出并提交 `HLD.md`
3. 用户确认 HLD 后，`meta-se` 拆解 Story 与开发计划
4. `meta-dev` 对每个 Story 先输出 `STORY-{id}-LLD.md`，确认后再实现
5. `meta-qa` 验证并生成安装脚本，`meta-doc` 输出交付文档

## 交付目录约定

安装脚本默认从仓库根目录的以下目录读取交付件：

- `agents/`
- `skills/`
- `rules/`

其中：

- Skill 私有模板随 `skills/<skill-name>/templates/` 一并安装

命名规则：

- Copilot 安装目标中的 Agent 文件后缀必须为 `.agent.md`
- Claude Code / OpenClaw 的 Agent 文件后缀保持为 `.md`
- Codex 目标会自动转换为 `.toml`

## 快速开始

```
@meta-po 开始
```

详细使用说明见 `delivery/README.md`（产物文档）和 `delivery/doc/USER-MANUAL.md`。
