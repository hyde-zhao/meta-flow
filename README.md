# SCOPE-Pack 元工作流

> 通用 Agent/Skill 工作流产物工厂 — 从需求到交付的全流程编排。

## 目录结构

| 目录 | 用途 |
|------|------|
| `delivery/` | **可独立交付的包**（可推送为独立 Git 仓库） |
| `delivery/agents/` | 交付 Agent 定义（安装脚本从此读取，`<name>.md`） |
| `delivery/skills/` | 交付 Skill 定义（结构为 `<name>/SKILL.md`；模板位于 `<name>/templates/`） |
| `delivery/rules/` | 平台规则文件（`AGENTS.md`、`CLAUDE.md`、`copilot-instructions.md`） |
| `delivery/scripts/` | 安装脚本入口（`install.py` / `install.sh` / `install.ps1`）；需随 Skill 一起安装的私有脚本应放在对应 `delivery/skills/<skill>/scripts/` 下 |
| `delivery/.github/agents/` | Copilot CLI Agent 入口文件 |
| `scripts/` | 仓库级检查/构建脚本（不随 `delivery/` 一起安装到目标平台） |
| `.agents/agents/` | 元工作流引擎 Agent 定义（不参与安装） |
| `.agents/skills/` | 元工作流引擎 Skill 定义（不参与安装） |
| `.github/` | 本仓库的 Copilot 平台配置 |
| `.input/` | 只读输入目录（用户提供的原始材料） |
| `.meta-workflow/` | 安装器状态目录（仅保存安装 manifest，不作为当前元工作流运行态输出目录） |
| `process/` | 运行时文档（gitignored，STATE.md / HLD.md / stories 等） |
| `checkpoints/` | 人工确认稿（gitignored） |
| `docs/` | 参考文档和设计历史 |

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

## `.meta-workflow` 目录说明

`.meta-workflow/` 当前不承载 SCOPE-Pack 的运行态文档，也不是 `process/`、`checkpoints/`、`delivery/` 的替代目录。当前规则要求元工作流产物仍按输出隔离原则写入仓库根目录下的 `process/`、`checkpoints/` 和 `delivery/`。

当前实现中，`delivery/scripts/install.py` 会把安装状态写入 `<WORKSPACE_ROOT>/.meta-workflow/delivery/doc/INSTALL-MANIFEST.yaml`。该 manifest 记录已安装的平台、scope、安装时间、canonical commit、目标路径和卸载所需的 remove path。安装器执行 `--uninstall` 时依赖这个文件精确卸载。

因此：

1. 若仍需要通过安装器执行精确卸载，应保留 `.meta-workflow/`。
2. 若确认不再需要历史安装记录或安装器卸载能力，可以删除 `.meta-workflow/`，但会丢失既有安装记录。
3. 当前仓库中的 `.meta-workflow/` 未被 Git 跟踪，也未在 `.gitignore` 中显式忽略；如团队决定长期把它作为本地状态目录，应补充 ignore 规则。

## Python 环境规范（uv）

当前仓库对 Python 运行环境采用 `uv` 作为统一工具链，但仓库当前**尚未**内置 `pyproject.toml` / `uv.lock`。因此本阶段的执行约束是：

1. 使用 `uv` 安装和选择 Python 解释器，不以系统 Python 作为默认入口。
2. 运行仓库内 Python 脚本时，优先使用 `uv run --python <version> python <script>`。
3. 一次性工具与临时依赖优先使用 `uvx` 或 `uv run --with <package>`，不把裸 `pip install` 作为日常流程。
4. 安装到目标项目的 uv 规范统一通过 `delivery/rules/AGENTS.md`、`delivery/rules/CLAUDE.md`、`delivery/rules/copilot-instructions.md` 传播。

示例：

```bash
uv python install 3.11
# 从项目根运行
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code --dry-run
# 或从 delivery/ 目录运行（delivery 作为独立仓库时）
cd delivery && python scripts/install.py --platform claude-code --dry-run
```

## 开发节奏

1. `meta-pm` 输出需求与场景
2. `meta-se` 输出并提交 `HLD.md`
3. 用户确认 HLD 后，`meta-se` 拆解 Story 与开发计划
4. `meta-dev` 对每个 Story 先输出 `STORY-{id}-{story_slug}-LLD.md`，确认后再实现
5. `meta-qa` 验证并生成安装脚本，`meta-doc` 输出交付文档

## 交付目录约定

安装脚本从 `delivery/` 内读取交付件，支持两种运行方式：

```bash
# 方式一：从项目根目录运行
python delivery/scripts/install.py --platform claude-code

# 方式二：以 delivery/ 为根（独立 Git 仓库）运行
cd delivery
python scripts/install.py --platform claude-code
```

交付目录结构：
- `delivery/agents/` — canonical Agent 定义
- `delivery/skills/` — canonical Skill 定义（含 `<skill>/templates/`、`<skill>/scripts/` 等私有运行时资产）
- `delivery/rules/` — 平台规则文件

## 交付护栏

1. `delivery/scripts/` **只允许**安装器入口：`install.py`、`install.sh`、`install.ps1`。
2. 任何被 active Skill 运行时使用的模板、脚本、schema、示例，都必须放在 `delivery/skills/<skill>/` 私有子目录下。
3. active Skill 的 `SKILL.md` 不得引用 `delivery/scripts/*.py`，也不得使用依赖当前工作目录的 `python scripts/...` 写法。
4. Python 缓存/编译产物（`__pycache__/`、`*.pyc`）不得入库。

仓库级静态检查命令：

```bash
uv run --python 3.11 python scripts/check_delivery_guardrails.py
```

命名规则：

- Copilot 安装目标中的 Agent 文件后缀必须为 `.agent.md`
- Claude Code / OpenClaw 的 Agent 文件后缀保持为 `.md`
- Codex 目标会自动转换为 `.toml`

## 快速使用 meta-flow

首次启动一个正式交付工作流时，建议直接给出目标、平台和约束：

```text
@meta-po 开始
目标：为 <agent / skill / workflow 名称> 产出正式方案
平台：Claude Code、Codex
要求：先澄清需求，再给我 HLD，确认后再拆 Story
```

常用控制语句：

```text
@meta-po 当前状态
@meta-po 继续
```

如果当前是在优化 meta-flow 本身，而不是为目标产物交付方案，请显式声明：

```text
当前是在做 meta 工作流优化，请进入 meta-self-dev 模式。
```

详细使用说明见 [delivery/README.md](delivery/README.md) 和 [delivery/doc/USER-MANUAL.md](delivery/doc/USER-MANUAL.md)。
