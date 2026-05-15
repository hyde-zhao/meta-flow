# SCOPE-Pack 元工作流

> 通用 Agent/Skill 工作流产物工厂 — 从需求到交付的全流程编排。

## 目录结构

| 目录 | 用途 |
|------|------|
| `delivery/` | **meta-flow 自身可独立交付的包**（可推送为独立 Git 仓库）；外部 production 项目的交付出口需按目标 README/docs 或用户确认路由 |
| `delivery/agents/` | 交付 Agent 定义（安装脚本从此读取，`<name>.md`） |
| `delivery/skills/` | 交付 Skill 定义（结构为 `<name>/SKILL.md`；模板位于 `<name>/templates/`） |
| `delivery/rules/` | 平台规则文件（`AGENTS.md`、`CLAUDE.md`） |
| `delivery/scripts/` | 安装脚本入口（`install.py` / `install.sh` / `install.ps1`）；需随 Skill 一起安装的私有脚本应放在对应 `delivery/skills/<skill>/scripts/` 下 |
| `scripts/` | 仓库级检查/构建脚本（不随 `delivery/` 一起安装到目标平台） |
| `.agents/agents/` | 元工作流引擎 Agent 定义（不参与安装） |
| `.agents/skills/` | 元工作流引擎 Skill 定义（不参与安装） |
| `.input/` | 只读输入目录（用户提供的原始材料） |
| `.meta-workflow/` | 安装器状态目录（仅保存安装 manifest，不作为当前元工作流运行态输出目录） |
| `process/` | 运行时文档（gitignored，STATE.md / HLD.md / stories 等） |
| `checkpoints/` | 人工确认稿（gitignored） |
| `docs/` | 参考文档和设计历史 |

## 输出隔离原则

所有由元工作流产生的运行时文档、人工确认稿与最终交付物统一按层输出。meta-flow 自身改进使用当前仓库 `delivery/`；外部 production 项目必须先读取目标 `README.md` / `README.*` / `docs/` 的交付约定，若无约定则先给出建议并等待用户确认。

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
│   ├── CHECKPOINT-STORY-PACKAGE.md
│   └── CHECKPOINT-FINAL.md
└── delivery/                    # meta-flow 自身最终交付物（production 项目不默认使用）
    ├── README.md
    ├── doc/
    ├── agents/
    ├── skills/
    ├── rules/
    └── scripts/
```

安装测试优先使用全局命令或 `uv run`：

```bash
scope-pack install --platform codex --scope project --component agent --dry-run
uv run --python 3.11 python delivery/scripts/install.py --platform codex --dry-run
```

## `.meta-workflow` 目录说明

`.meta-workflow/` 当前不承载 SCOPE-Pack 的运行态文档，也不是 `process/`、`checkpoints/` 或交付出口的替代目录。当前规则要求元工作流运行态仍写入仓库根目录下的 `process/`、`checkpoints/`；交付态按 engagement mode 路由，meta-flow 自身改进写当前仓库 `delivery/`，外部 production 项目按目标项目约定或用户确认输出。

当前实现中，`delivery/scripts/install.py` 会把安装状态写入 `<WORKSPACE_ROOT>/.meta-workflow/delivery/doc/INSTALL-MANIFEST.yaml`。该 manifest 记录已安装的平台、scope、安装时间、canonical commit、目标路径和卸载所需的 remove path。安装器执行 `--uninstall` 时依赖这个文件精确卸载。

因此：

1. 若仍需要通过安装器执行精确卸载，应保留 `.meta-workflow/`。
2. 若确认不再需要历史安装记录或安装器卸载能力，可以删除 `.meta-workflow/`，但会丢失既有安装记录。
3. 当前仓库中的 `.meta-workflow/` 未被 Git 跟踪，也未在 `.gitignore` 中显式忽略；如团队决定长期把它作为本地状态目录，应补充 ignore 规则。

## Python 环境规范（uv）

当前仓库对 Python 运行环境采用 `uv` 作为统一工具链，并已提供 `pyproject.toml` / `uv.lock` 与 `scope-pack` console script。因此本阶段的执行约束是：

1. 使用 `uv` 安装和选择 Python 解释器，不以系统 Python 作为默认入口。
2. 运行仓库内 Python 脚本时，优先使用 `uv run --python <version> python <script>`；安装入口优先使用 `scope-pack install`。
3. 一次性工具与临时依赖优先使用 `uvx` 或 `uv run --with <package>`，不把裸 `pip install` 作为日常流程。
4. 安装到目标项目的 uv 规范统一通过 `delivery/rules/AGENTS.md`、`delivery/rules/CLAUDE.md` 传播。

示例：

```bash
uv python install 3.11
uv tool install --editable .
scope-pack install --platform codex --scope user --component rules
scope-pack install --platform codex --scope project --component agent --project-dir /path/to/project
# 从项目根运行
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code --dry-run
# 或从 delivery/ 目录运行（delivery 作为独立仓库时）
cd delivery && uv run --python 3.11 python scripts/install.py --platform claude-code --dry-run
```

## 开发节奏

1. `meta-pm` 输出需求与场景
2. `meta-se` 输出并提交 `HLD.md`
3. 用户确认 HLD 后，`meta-se` 拆解 Story、开发计划与当前 Wave 的 Story Package 草案
4. `meta-po` 组织 `meta-dev` 为当前 Wave 输出 LLD 包，并发起 Story Package 合并确认
5. Story Package 确认通过后，`meta-dev` 复用同一子 agent 实现，`meta-qa` 验证并生成安装脚本，`meta-doc` 输出交付文档

## 交付目录约定

安装脚本从 `delivery/` 内读取交付件，推荐使用 `scope-pack install`：

```bash
# user scope 默认只安装 rules
scope-pack install --platform codex --scope user

# project scope 默认安装 agent 组件（agents + skills）
scope-pack install --platform codex --scope project --project-dir /path/to/project

# 显式安装完整组件
scope-pack install --platform codex --scope project --component full --project-dir /path/to/project
```

兼容运行方式：

```bash
# 从项目根目录运行
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code

# 以 delivery/ 为根（独立 Git 仓库）运行
cd delivery
uv run --python 3.11 python scripts/install.py --platform claude-code
```

交付目录结构：
- `delivery/agents/` — canonical Agent 定义
- `delivery/skills/` — canonical Skill 定义（含 `<skill>/templates/`、`<skill>/scripts/` 等私有运行时资产）
- `delivery/rules/` — 平台规则文件
- `delivery/doc/PLATFORM-CONTRACTS.yaml` — 平台安装路径单一真相源，安装器、DryRun 与 guardrail 共同读取

组件语义：

- `rules`：只安装平台规则入口（如 `AGENTS.md` / `CLAUDE.md`）
- `agent`：安装 agents + skills
- `full`：同时安装 rules 与 agent 组件
- legacy `--content all|agents|skills|rules` 仅保留兼容，新文档优先使用 `--component`

## 交付护栏

1. `delivery/scripts/` **只允许**安装器入口：`install.py`、`install.sh`、`install.ps1`。
2. 任何被 active Skill 运行时使用的模板、脚本、schema、示例，都必须放在 `delivery/skills/<skill>/` 私有子目录下。
3. active Skill 的 `SKILL.md` 不得引用 `delivery/scripts/*.py`，也不得使用依赖当前工作目录的 `python scripts/...` 写法。
4. Python 缓存/编译产物（`__pycache__/`、`*.pyc`）不得入库。
5. Codex Skill 禁止安装到 `.codex/skills` 或 `~/.codex/skills`；项目级使用 `.agents/skills`，用户级使用 `~/.agents/skills`。
6. 安装器必须在写入前检查路径组件冲突；例如目标 `.codex` 已是普通文件时，应明确报错 `安装路径被非目录占用`，不得输出 Python traceback。

meta-flow 自身仓库级静态检查命令：

```bash
uv run --python 3.11 python scripts/check_delivery_guardrails.py
```

该脚本不属于外部 production 项目的默认交付物。仅当当前仓库存在 `scripts/check_delivery_guardrails.py` 时才运行上述命令。若在其他项目使用 meta-flow 生成或安装工作流，而目标项目没有该脚本，外部 production 项目不得硬引用 `/home/hyde/projects/meta-flow/scripts/check_delivery_guardrails.py`；应按目标项目 README/docs 中的测试、构建、安装 dry-run 或用户确认的验证命令执行。

命名规则：

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
