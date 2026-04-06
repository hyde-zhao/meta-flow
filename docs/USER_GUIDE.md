# 跨平台 Agent/Skill 元工作流系统 — 使用与安装指南

本指南说明如何把本项目作为“可安装工作流生产系统”使用。系统目标不是只生成文档，而是把需求澄清、方案设计、Story 开发、验证和打包整合成一个可持续运行的元工作流，并最终产出可安装到 Claude Code、Codex、Copilot、OpenClaw 的 Agent/Skill 包。

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
- 方案设计与人工确认
- Story 拆解与并行开发
- 基于人工提供环境配置的验证
- 面向多个平台的安装包生成
- 项目结束后输出 `README.md` 和 `USER-MANUAL.md` 两份文档

系统支持三种交付模式：

| 模式 | 适用场景 | 输出 |
|------|----------|------|
| `simple` | 简单需求，只需一个能力模块 | 单一 `SKILL.md` |
| `standard` | 需要一个稳定角色和若干能力 | 1 个 Agent + 多个 Skill |
| `complex` | 复杂协作、Story 并行、多平台打包 | 多 Agent 工作流包 |

系统中的核心角色命名如下：

| 角色 | 职责 |
|------|------|
| `meta-po` | 元流产品负责人，负责流程编排和检查点控制 |
| `meta-pm` | 元流产品经理，负责需求澄清与需求确认 |
| `meta-se` | 元流架构设计师，负责方案设计和架构决策 |
| `meta-dm` | 元流开发经理，负责 Story 拆解和并行规划 |
| `meta-dev` | 元流开发工程师，负责实现 Agent、Skill 与模板 |
| `meta-qa` | 质量工程师，负责验证、打包和安装可用性校验 |
| `meta-doc` | 文档工程师，负责输出 `README.md` 和 `USER-MANUAL.md` |

---

## 二、环境准备

本系统依赖 `Python >= 3.9` 和 `pyyaml`，打包脚本通过 `python` 或 `uv` 执行。

```bash
pip install pyyaml        # 必须
pip install uv            # 可选，加速依赖管理
```

---

## 三、多平台安装说明

使用打包脚本 `scripts/package_builder.py` 将 `.agents/` 下的产物构建为各平台安装包，再手动复制到目标项目目录。

### 3.1 构建安装包

```bash
# 模拟构建（不写文件，仅验证）
python scripts/package_builder.py --dry-run

# 构建全部平台包
python scripts/package_builder.py

# 只构建指定平台
python scripts/package_builder.py --targets copilot,claude-code
```

构建产物输出到 `packages/` 目录：

| 平台 | 构建产物目录 | 核心入口文件 |
|------|-------------|-------------|
| Copilot CLI | `packages/copilot/.github/copilot/` | `copilot-instructions.md` |
| Claude Code | `packages/claude-code/.claude/` | `CLAUDE.md` |
| Codex | `packages/codex/.codex/` | — (仅 agents + skills) |
| OpenClaw | `packages/openclaw/.openclaw/` | `manifest.yaml` |

### 3.2 安装到目标项目

将对应平台的构建产物目录复制到目标项目根目录下：

```bash
# Copilot CLI
cp -r packages/copilot/.github  /path/to/your-project/

# Claude Code
cp -r packages/claude-code/.claude  /path/to/your-project/

# Codex
cp -r packages/codex/.codex  /path/to/your-project/

# OpenClaw
cp -r packages/openclaw/.openclaw  /path/to/your-project/
```

### 3.3 安装验证方法

安装完成后，使用以下方法验证各平台安装是否成功：

#### ✅ Copilot CLI 验证

```bash
# 1. 在目标项目目录中启动 Copilot CLI
cd /path/to/your-project
gh copilot  # 或 copilot-cli

# 2. 检查 Skills 是否被发现
/skills
# 期望：列出 25 个 Skill 名称（如 state-router、story-manager 等）

# 3. 检查 Agent 是否就绪
# 输入：当前工作流状态是什么？
# 期望：meta-po 响应，提示初始化 STATE.md 或读取当前状态

# 4. 验证文件结构
ls .github/copilot/skills/ | wc -l   # 应为 25
ls .github/copilot/copilot-instructions.md  # 应存在
```

#### ✅ Claude Code 验证

```bash
# 1. 检查文件结构
ls .claude/agents/   # 应有 7 个 .md 文件（meta-po/pm/se/dm/dev/qa/doc）
ls .claude/skills/   # 应有 25 个 .md 文件

# 2. 启动 Claude Code 并验证 Agent 加载
# 输入：你是哪个 Agent？请说明你的职责。
# 期望：meta-po 自动接管，描述编排职责

# 3. 验证 Skill 触发
# 输入：帮我提取需求
# 期望：requirement-extraction Skill 自动触发

# 4. SHA256 完整性校验
sha256sum -c packages/INSTALL-CHECKSUMS.sha256 2>&1 | grep -v OK
# 期望：无输出（全部通过）
```

#### ✅ Codex 验证

```bash
# 1. 检查 YAML 格式 Agent 文件
ls .codex/agents/   # 应有 7 个 .yaml 文件

# 2. 验证 YAML 语法合法
python -c "
import yaml, pathlib
for f in pathlib.Path('.codex/agents').glob('*.yaml'):
    yaml.safe_load(f.read_text())
    print(f'OK: {f.name}')
"
# 期望：7 行 OK 输出

# 3. 检查必填字段
python -c "
import yaml, pathlib
for f in pathlib.Path('.codex/agents').glob('*.yaml'):
    d = yaml.safe_load(f.read_text())
    assert 'instructions' in d, f'{f.name} 缺少 instructions'
    assert 'description' in d, f'{f.name} 缺少 description'
print('All agents valid')
"
```

#### ✅ OpenClaw 验证

```bash
# 1. 验证 manifest.yaml 存在且结构正确
python -c "
import yaml
m = yaml.safe_load(open('.openclaw/manifest.yaml').read())
print('agents:', len(m['agents']))   # 期望：7
print('skills:', len(m['skills']))   # 期望：25
"

# 2. 检查所有 manifest 引用的文件均存在
python -c "
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

无论最终是单 Skill 还是多 Agent 工作流，推荐都按下面的顺序推进：

1. 提交目标请求，启动需求讨论与澄清。
2. 在设计阶段确认采用 simple、standard 或 complex 模式。
3. 如果进入开发，先拆解 Story 和开发计划。
4. Story 开发可并行，但要持续记录状态。
5. 验证前由人工提供或确认验证环境配置。
6. 验证通过后再生成平台安装包。
7. 项目结束时由 `meta-doc` 输出 `README.md` 和 `USER-MANUAL.md`。

### 4.2 场景一：简单需求，生成单 Skill

适用于“只需要一个能力模块”的需求，例如生成一个需求澄清 Skill 或一个 Story 拆解 Skill。

建议这样发起：

```text
请启动一个新的 Agent/Skill 工作流。
目标：生成一个用于需求澄清的单一 Skill。
目标平台：Claude Code、Codex。
我希望先进行需求讨论，确认后再决定是否只做单 Skill。
```

系统会先进入澄清阶段，而不是直接写 Skill。

### 4.3 场景二：标准需求，生成单 Agent + 多 Skill

适用于“一个主角色 + 若干能力模块”的场景。

建议这样发起：

```text
请启动一个新的 Agent/Skill 工作流。
目标：生成一个可以管理 Story 开发状态的 Agent。
平台：Claude Code、Copilot。
要求：先澄清需求，再给我方案设计，确认后再拆 Story。
```

此时系统通常会输出：

- `REQUIREMENTS.md`
- `SOLUTION-DESIGN.md`
- `STORY-BACKLOG.md`
- 对应 Agent 与 Skill 文件
- `README.md`
- `USER-MANUAL.md`

### 4.4 场景三：复杂需求，生成多 Agent 工作流包

适用于存在多个阶段和多个职责边界的场景，例如：

- 需要 `meta-pm` 负责需求分析
- 需要 `meta-se` 负责方案设计
- 需要 `meta-dm` 和 `meta-dev` 负责 Story 规划与开发
- 需要 `meta-qa` 负责平台打包与验证
- 需要 `meta-doc` 负责输出项目文档

建议这样发起：

```text
请启动一个新的复杂工作流项目。
目标：生成一套可安装到 Claude Code、OpenClaw、Codex、Copilot 的多 Agent 工作流。
必须包含：需求讨论澄清、方案设计、开发计划和 Story 拆解、Story 开发、Story 验证、开发记录。
要求：设计阶段先和我确认；验证阶段默认我来提供环境配置。
```

### 4.5 Story 开发与验证约定

系统默认遵循以下约定：

| 约定 | 说明 |
|------|------|
| Story 是最小开发单元 | 每个 Story 都有自己的目标、验收标准和状态 |
| Story 可并行 | 只有在无依赖、无文件冲突时才并行 |
| 验证默认人工提供配置 | 没有 `VALIDATION-ENV.yaml` 或人工确认，不进入验证 |
| Story 状态必须记录 | 至少回写到 `STORY-STATUS.md` 和 `DEV-LOG.md` |
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

**Q: 为什么验证前一定要人工提供环境配置？**  
A: 因为安装和验证通常依赖本地目录、权限、运行时和目标平台上下文，这些不是 AI 可以默认假设的。把它对象化可以避免“看起来完成，实际上无法验证”。

**Q: Story 为什么要单独记录状态？**  
A: 因为一旦允许并行开发，没有 Story 状态就无法判断哪些已完成、哪些阻塞、哪些可以进入验证。

**Q: 最终交付的最小集合是什么？**  
A: 至少包括 Agent/Skill 产物、`PACKAGE-MANIFEST.yaml`、`VERIFICATION-REPORT.md`、`README.md`、`USER-MANUAL.md`，以及目标平台安装目录结构。
