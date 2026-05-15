# Meta Flow 元工作流

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
| `~/.meta-flow/` | 安装器状态目录（仅保存安装 manifest，不作为当前元工作流运行态输出目录） |
| `process/` | 运行时文档（gitignored，STATE.md / HLD.md / stories 等） |
| `process/checks/` | 自动检查点结果（gitignored，CP0-CP8 自检证据） |
| `checkpoints/` | 人工检查点审查稿（gitignored，CP2/CP3/CP4/CP5/CP8 checklist 与审查结果） |
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
│   ├── checks/
│   ├── changes/
│   └── stories/
├── checkpoints/                 # 人工检查点审查稿（默认建议 gitignore）
│   ├── CP2-REQUIREMENTS-BASELINE.md
│   ├── CP3-HLD-REVIEW.md
│   ├── CP4-STORY-PLAN-REVIEW.md
│   ├── CP5-STORY-001-example-LLD.md
│   └── CP8-DELIVERY-READINESS.md
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
meta-flow install --platform codex --scope project --component agent --dry-run
uv run --python 3.11 python delivery/scripts/install.py --platform codex --dry-run
```

## `~/.meta-flow` 目录说明

`~/.meta-flow/` 当前不承载 Meta Flow 的运行态文档，也不是 `process/`、`process/checks/`、`checkpoints/` 或交付出口的替代目录。当前规则要求元工作流运行态仍写入仓库根目录下的 `process/`、自动检查结果写入 `process/checks/`、人工审查稿写入 `checkpoints/`；交付态按 engagement mode 路由，meta-flow 自身改进写当前仓库 `delivery/`，外部 production 项目按目标项目约定或用户确认输出。

当前实现中，`delivery/scripts/install.py` 会把安装状态写入 `~/.meta-flow/delivery/doc/INSTALL-MANIFEST.yaml`。该 manifest 记录已安装的平台、scope、安装时间、canonical commit、目标路径和卸载所需的 remove path。安装器执行 `--uninstall` 时依赖这个文件精确卸载。

因此：

1. 若仍需要通过安装器执行精确卸载，应保留 `~/.meta-flow/`。
2. 若确认不再需要历史安装记录或安装器卸载能力，可以删除 `~/.meta-flow/`，但会丢失既有安装记录。
3. `~/.meta-flow/` 位于用户主目录，不属于当前仓库跟踪范围；不应作为项目运行态文档或交付出口使用。

## Python 环境规范（uv）

当前仓库对 Python 运行环境采用 `uv` 作为统一工具链，并已提供 `pyproject.toml` / `uv.lock` 与 `meta-flow` console script。因此本阶段的执行约束是：

1. 使用 `uv` 安装和选择 Python 解释器，不以系统 Python 作为默认入口。
2. 运行仓库内 Python 脚本时，优先使用 `uv run --python <version> python <script>`；安装入口优先使用 `meta-flow install`。
3. 一次性工具与临时依赖优先使用 `uvx` 或 `uv run --with <package>`，不把裸 `pip install` 作为日常流程。
4. 安装到目标项目的 uv 规范统一通过 `delivery/rules/AGENTS.md`、`delivery/rules/CLAUDE.md` 传播。

示例：

```bash
uv python install 3.11
uv tool install --editable .
meta-flow install --platform codex --scope user --component rules
meta-flow install --platform codex --scope project --component agent --project-dir /path/to/project
# 从项目根运行
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code --dry-run
# 或从 delivery/ 目录运行（delivery 作为独立仓库时）
cd delivery && uv run --python 3.11 python scripts/install.py --platform claude-code --dry-run
```

## 开发节奏

1. `meta-po` 初始化请求并写入 CP0 自动检查结果。
2. `meta-pm` 输出场景与需求，写入 CP1 / CP2 自动检查结果；CP2 通过人工审查后进入设计。
3. `meta-se` 输出 `HLD.md` 和 CP3 自动预检；CP3 通过人工审查后拆解 Story、开发计划、依赖类型与文件所有权。
4. `meta-se` 写入 CP4 自动预检；CP4 通过人工审查后，`meta-po` 按 Story DAG 计算 `lld_ready` / `dev_ready` 队列。
5. `meta-dev` 并行输出 Story LLD 和 CP5 自动预检，`meta-po` 发起单 Story 或小批次滚动确认。
6. Story CP5 确认且 `dev_gate` 满足后，`meta-po` 必须通过平台子 agent 能力调度 `meta-dev` 并记录证据；`meta-dev` 并行实现并写入 CP6 编码完成结果。
7. Story 进入验证时，`meta-po` 必须通过平台子 agent 能力调度 `meta-qa` 并记录证据；`meta-qa` 验证并写入 CP7 验证完成结果。
8. 所有目标 Story 验证后，`meta-qa` / `meta-doc` 完成交付材料并写入 CP8 自动预检；CP8 人工终验通过后进入 delivered。

## 检查点

Meta Flow 默认采用 CP0-CP8 检查点。所有检查点都包含 Entry Criteria、Checklist、Exit Criteria、Deliverables。

| CP | 名称 | 类型 | 文件 |
|----|------|------|------|
| CP0 | 原始请求受理门 | 自动 | `process/checks/CP0-REQUEST-INTAKE.md` |
| CP1 | 用户场景完备门 | 自动 | `process/checks/CP1-USE-CASE-COMPLETENESS.md` |
| CP2 | 需求基线门 | 自动预检 + 人工 | `process/checks/CP2-REQUIREMENTS-BASELINE.md`；`checkpoints/CP2-REQUIREMENTS-BASELINE.md` |
| CP3 | HLD 架构评审门 | 自动预检 + 人工 | `process/checks/CP3-HLD-CONSISTENCY.md`；`checkpoints/CP3-HLD-REVIEW.md` |
| CP4 | Story 拆解与并行安全门 | 自动预检 + 人工 | `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md`；`checkpoints/CP4-STORY-PLAN-REVIEW.md` |
| CP5 | Story LLD 可实现性门 | 滚动自动预检 + 人工 | `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`；`checkpoints/CP5-{story_id}-{story_slug}-LLD.md` |
| CP6 | Story 编码完成门 | 滚动自动 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md` |
| CP7 | Story 验证完成门 | 滚动自动 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md` |
| CP8 | 交付就绪门 | 自动预检 + 人工 | `process/checks/CP8-DELIVERY-READINESS.md`；`checkpoints/CP8-DELIVERY-READINESS.md` |

人工检查点由 `meta-po` 发起。发起时会提示 `checkpoints/CP*.md` 路径；用户审查后可以在文件的“人工审查结果”中填写结论，也可以在对话中回复 `1/approve/通过`、`2/修改: <具体修改点>`、`3/reject/不通过`，由 `meta-po` 回填结果文件。

CP6 / CP7 还必须包含 `Agent Dispatch Evidence` 小节。`process/handoffs/*.md` 只表示交接，不表示子 agent 已执行；Story 编码或验证完成必须有 `spawn_agent` / `resume_agent` / `send_input`、平台 Task/Subagent 返回标识，并在 `STATE.md.agent_lifecycle` 或 handoff `dispatch` 中记录 `agent_id` 或 `thread_id`，或用户明确批准的 `inline-fallback`。缺少调度证据时，CP6 / CP7 只能判定为 `FAIL` 或 `BLOCKED`。

## 交付目录约定

安装脚本从 `delivery/` 内读取交付件，推荐使用 `meta-flow install`：

```bash
# user scope 默认只安装 rules
meta-flow install --platform codex --scope user

# project scope 默认安装 agent 组件（agents + skills）
meta-flow install --platform codex --scope project --project-dir /path/to/project

# 未指定 --project-dir 时，交互式终端会提示确认当前目录或输入其他目录
meta-flow install --platform codex --scope project

# 显式安装完整组件
meta-flow install --platform codex --scope project --component full --project-dir /path/to/project
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
