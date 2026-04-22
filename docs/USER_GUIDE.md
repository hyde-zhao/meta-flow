# 跨平台 Agent/Skill 元工作流系统 — 使用与安装指南

本指南说明如何把本项目作为“可安装工作流生产系统”使用。系统目标不是只生成文档，而是把需求澄清、HLD 设计、Story 规划、Story 级 LLD 设计、实现、验证和安装脚本交付整合成一个可持续运行的元工作流，并最终产出可安装到 Claude Code、Codex、Copilot、OpenClaw 的 Agent/Skill 产物。

---

## 目录

1. 系统简介
2. 环境准备
3. 多平台安装说明（含安装验证）
4. 使用说明与典型工作流
5. 常见问题

> 📖 **详细 Agent/Skill 用法参考**：见 [`AGENT-SKILL-REFERENCE.md`](./AGENT-SKILL-REFERENCE.md)

---

## 一、系统简介

本系统是一个跨平台 Agent/Skill 工作流工厂，核心能力包括：

- 需求讨论与持续澄清
- HLD 设计与人工确认
- Story 拆解与开发计划编排
- 每个 Story 在开发前先输出 LLD 并人工确认
- 基于人工提供环境配置的验证
- 面向多个平台的安装脚本生成
- 项目结束后输出 `README.md` 和 `USER-MANUAL.md` 两份交付文档

系统支持三种交付模式：

| 模式 | 适用场景 | 输出 |
|------|----------|------|
| `simple` | 简单需求，只需一个能力模块 | 单一 `SKILL.md` |
| `standard` | 需要一个稳定角色和若干能力 | 1 个 Agent + 多个 Skill |
| `complex` | 复杂协作、Story 并行、多平台安装 | 多 Agent 工作流 |

系统中的核心角色命名如下：

| 角色 | 职责 |
|------|------|
| `meta-po` | 元工作流产品负责人，负责流程编排、状态推进和人工检查点控制 |
| `meta-pm` | 元工作流产品经理，负责需求澄清与需求确认 |
| `meta-se` | 元工作流架构设计师，负责 HLD 设计、架构决策和 Story 拆解 |
| `meta-dm` | 保留的兼容占位 Agent，已废弃，职责并入 `meta-se` |
| `meta-dev` | 元工作流开发工程师，负责 Story 级 LLD、实现 Agent/Skill/脚本等产物 |
| `meta-qa` | 质量工程师，负责验证、安装脚本交付和安装可用性校验 |
| `meta-doc` | 文档工程师，负责输出 `README.md` 和 `USER-MANUAL.md` |

当前仓库的内置元工作流会交付：

- **7 个 Agent 文件**（其中 `meta-dm` 为兼容占位）
- **30 个通用 Skill**
- **3 类规则文件**（`AGENTS.md`、`CLAUDE.md`、`copilot-instructions.md`）

---

## 二、环境准备

本系统依赖 `Python >= 3.9`，并统一使用 `uv` 管理 Python 解释器与命令入口。

当前仓库尚未内置 `pyproject.toml` / `uv.lock`，因此本阶段采用“`uv` 管理解释器 + `uv run` 执行脚本”的约束，而不是裸 `python` / `pip install`。

推荐准备方式：

1. 安装 `uv`
2. 执行 `uv python install 3.11`
3. 运行仓库脚本时使用 `uv run --python 3.11 python <script>`
4. 一次性工具优先使用 `uvx`；带临时依赖的命令优先使用 `uv run --with <package>`

`delivery/scripts/install.py` 本身无需额外安装 `PyYAML`。

---

## 三、多平台安装说明

### 3.1 使用安装脚本

当前仓库通过 `delivery/scripts/install.py`、`delivery/scripts/install.ps1`、`delivery/scripts/install.sh` 直接安装产物，不再先生成平台包。安装脚本默认从根目录的 `delivery/agents/`、`delivery/skills/`、`delivery/rules/` 读取交付件。

#### 安装当前仓库内置元工作流

```bash
# 默认安装到当前项目目录
uv run --python 3.11 python scripts/install.py --platform claude-code

# 指定项目目录
uv run --python 3.11 python scripts/install.py --platform codex --project-dir /path/to/your-project

# 用户级安装，仅安装 skills
uv run --python 3.11 python scripts/install.py --platform copilot --scope user --content skills

# 仅安装规则文件
uv run --python 3.11 python scripts/install.py --platform claude-code --content rules

# DryRun
uv run --python 3.11 python scripts/install.py --platform openclaw --dry-run
```

#### 平台包装器脚本

```powershell
scripts\install.ps1 --platform codex --content agents --agent meta-po --dry-run
```

```bash
bash scripts/install.sh --platform copilot --scope user --content skills --skill state-router --dry-run
```

### 3.2 默认安装位置

| 平台 | 项目级默认目录 | 用户级默认目录 |
|------|---------------|----------------|
| Copilot CLI | `<project>/.github/` | `~/.copilot/` |
| Claude Code | `<project>/.claude/` | `~/.claude/` |
| Codex | `<project>/.codex/` | `~/.codex/` |
| OpenClaw | `<project>/.openclaw/` | `~/.openclaw/` |

### 3.3 源目录与命名规则

| 源目录 | 内容 | 规则 |
|--------|------|------|
| `delivery/agents/` | Canonical Agent 文件 | 源文件统一为 `<name>.md` |
| `delivery/skills/` | Canonical Skill 目录 | 结构固定为 `skills/<name>/SKILL.md` |
| `delivery/rules/` | 规则文件 | 如 `AGENTS.md`、`CLAUDE.md`、`copilot-instructions.md` |

安装时的命名规则：

- Copilot：Agent 目标文件名为 `<name>.agent.md`
- Claude Code / OpenClaw：Agent 目标文件名保持 `<name>.md`
- Codex：Agent 目标文件自动转换为 `<name>.yaml`

### 3.4 安装验证方法

安装完成后，可按以下方式验证：

#### ✅ Copilot CLI 验证

```bash
# 1. 在目标项目目录中启动 Copilot CLI
cd /path/to/your-project
gh copilot

# 2. 检查 Skills 是否被发现
/skills
# 期望：列出约 30 个 Skill（如 state-router、hld-designer、lld-designer、story-manager 等）

# 3. 检查主编排器可被触发
# 输入：当前工作流状态是什么？
# 期望：meta-po 响应，提示初始化 STATE.md 或读取当前状态

# 4. 验证文件结构
ls .github/agents/ | wc -l
# 期望：约 7，且后缀为 .agent.md
ls .github/copilot/skills/ | wc -l
# 期望：约 30
ls .github/copilot-instructions.md
# 期望：存在
```

#### ✅ Claude Code 验证

```bash
# 1. 检查文件结构
ls .claude/agents/   # 应有 7 个 .md 文件（含已废弃但保留的 meta-dm）
ls .claude/skills/   # 应有约 30 个 .md 文件

# 2. 启动 Claude Code 并验证 Agent 加载
# 输入：你是哪个 Agent？请说明你的职责。
# 期望：meta-po 自动接管，描述编排职责

# 3. 验证新设计能力是否可见
# 输入：请输出 HLD
# 期望：hld-designer / meta-se 路径被正确使用

# 4. DryRun 校验
uv run --python 3.11 python scripts/install.py --platform claude-code --dry-run
# 期望：输出默认安装路径和将写入的文件
```

#### ✅ Codex 验证

```bash
# 1. 检查 TOML 格式 Agent 文件
ls .codex/agents/   # 应有 7 个 .toml 文件

# 2. 验证 TOML 语法合法
uv run --python 3.11 python -c "
import pathlib, tomllib
for f in pathlib.Path('.codex/agents').glob('*.toml'):
    tomllib.loads(f.read_text())
    print(f'OK: {f.name}')
"

# 3. 检查必填字段
uv run --python 3.11 python -c "
import pathlib, tomllib
for f in pathlib.Path('.codex/agents').glob('*.toml'):
    d = tomllib.loads(f.read_text())
    assert 'developer_instructions' in d, f'{f.name} 缺少 developer_instructions'
    assert 'description' in d, f'{f.name} 缺少 description'
    assert 'name' in d, f'{f.name} 缺少 name'
print('All agents valid')
"
```

#### ✅ OpenClaw 验证

```bash
# 1. 验证 manifest.yaml 存在且结构正确
uv run --with pyyaml --python 3.11 python -c "
import yaml
m = yaml.safe_load(open('.openclaw/manifest.yaml').read())
print('agents:', len(m['agents']))   # 期望：7
print('skills:', len(m['skills']))   # 期望：约 30
"

# 2. 检查所有 manifest 引用的文件均存在
uv run --with pyyaml --python 3.11 python -c "
import yaml, pathlib
m = yaml.safe_load(open('.openclaw/manifest.yaml').read())
base = pathlib.Path('.openclaw')
for item in m.get('agents', []) + m.get('skills', []):
    p = base / item['file']
    assert p.exists(), f'缺失: {p}'
print('All manifest entries exist')
"
```

---

## 四、使用说明与典型工作流

### 4.1 标准使用顺序

推荐按下面的顺序推进：

1. 提交目标请求，启动需求讨论与澄清。
2. `meta-se` 输出 `HLD.md`，由人工确认是否进入 Story 拆解。
3. HLD 确认后，`meta-se` 输出 `STORY-BACKLOG.md` 与 `DEVELOPMENT-PLAN.yaml`。
4. `meta-dev` 为每个 Story 先输出 `STORY-{id}-LLD.md`，由人工确认后再开始实现。
5. Story 开发可并行，但同一 Story 必须按 `LLD 起草 → LLD 确认 → 实现 → 验证` 顺序推进。
6. 验证前由人工提供或确认环境配置。
7. 验证通过后再生成平台安装脚本。
8. 项目结束时由 `meta-doc` 输出 `README.md` 和 `USER-MANUAL.md`。

### 4.2 场景一：简单需求，生成单 Skill

适用于“只需要一个能力模块”的需求，例如生成一个需求澄清 Skill 或一个 Story 拆解 Skill。

```text
请启动一个新的 Agent/Skill 工作流。
目标：生成一个用于需求澄清的单一 Skill。
目标平台：Claude Code、Codex。
我希望先进行需求讨论，确认后再决定是否只做单 Skill。
```

系统会先进入澄清阶段，而不是直接写 Skill。

### 4.3 场景二：标准需求，生成单 Agent + 多 Skill

适用于“一个主角色 + 若干能力模块”的场景。

```text
请启动一个新的 Agent/Skill 工作流。
目标：生成一个可以管理 Story 开发状态的 Agent。
平台：Claude Code、Copilot。
要求：先澄清需求，再给我 HLD，确认后再拆 Story。
```

此时系统通常会输出：

- `REQUIREMENTS.md`
- `HLD.md`
- `STORY-BACKLOG.md`
- `DEVELOPMENT-PLAN.yaml`
- `stories/STORY-{id}.md`
- `stories/STORY-{id}-LLD.md`
- 对应 Agent 与 Skill 文件
- `README.md`
- `USER-MANUAL.md`

### 4.4 场景三：复杂需求，生成多 Agent 工作流

适用于存在多个阶段和多个职责边界的场景，例如：

- 需要 `meta-pm` 负责需求分析
- 需要 `meta-se` 负责 HLD 与 Story 规划
- 需要 `meta-dev` 负责 Story 级 LLD 与实现
- 需要 `meta-qa` 负责平台安装脚本交付与验证
- 需要 `meta-doc` 负责输出项目文档

```text
请启动一个新的复杂工作流项目。
目标：生成一套可安装到 Claude Code、OpenClaw、Codex、Copilot 的多 Agent 工作流。
必须包含：需求澄清、HLD 评审、Story 规划、Story 级 LLD 评审、实现、验证和开发记录。
要求：HLD 和每个 Story 的 LLD 都必须先和我确认；验证阶段默认我来提供环境配置。
```

### 4.5 Story 开发与验证约定

系统默认遵循以下约定：

| 约定 | 说明 |
|------|------|
| Story 是最小开发单元 | 每个 Story 都有自己的目标、验收标准和状态 |
| HLD 是 Story 规划前置条件 | `HLD.md` 未确认，不进入 Story 拆解 |
| LLD 是 Story 实现前置条件 | `STORY-{id}-LLD.md` 未确认，不开始实现 |
| Story 可并行 | 只有在无依赖、无文件冲突时才并行 |
| 验证默认人工提供配置 | 没有 `VALIDATION-ENV.yaml` 或人工确认，不进入验证 |
| 项目结束必须出文档 | 至少输出 `README.md` 和 `USER-MANUAL.md` |

### 4.6 验证环境配置

验证前建议由人工提供类似如下信息：

```yaml
environment_id: local-dev
provided_by: human
targets:
  - claude-code
  - openclaw
approval:
  confirmed: true
notes:
  - "本轮验证只检查安装目录、文件引用和提示词加载"
```

---

## 五、常见问题

**Q: 简单需求也一定要跑完整多 Agent 流程吗？**  
A: 不需要。系统会在设计阶段判断是否适合 `simple` 模式。简单需求可以只交付一个 Skill。

**Q: 为什么先做 HLD，再做 LLD？**
A: HLD 用来确认系统边界、架构决策和 Story 划分；LLD 用来确认某个 Story 的实现细节。把两层设计拆开，可以在真正开发前把范围和实现约束卡住。

**Q: Story 为什么要单独记录状态？**  
A: 因为一旦允许并行开发，没有 Story 状态就无法判断哪些已完成、哪些阻塞、哪些可以进入验证。

**Q: 最终交付的最小集合是什么？**  
A: 至少包括 Agent/Skill 产物、`INSTALL-MANIFEST.yaml`、`VERIFICATION-REPORT.md`、`README.md`、`USER-MANUAL.md`，以及目标平台安装脚本。
