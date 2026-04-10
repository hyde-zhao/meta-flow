# 平台安装规范（PLATFORM-INSTALL-SPEC）— MFQ 测试用例设计工具

> 由 meta-se 在方案设计阶段输出，meta-qa 在打包阶段严格遵守。
> 产物名称：`mfq-test-designer` | 版本：1.0.0 | 产物形态：1 Agent + 14 Skill + 2 Python 工具

---

## 平台总览

| 维度 | GitHub Copilot CLI | Claude Code | OpenClaw |
|------|-------------------|-------------|---------|
| 安装根目录 | `.github/` | `.claude/` | `.openclaw/` |
| Agent 路径 | `agents/mfq-test-designer.agent.md` | `agents/mfq-test-designer.md` | `agents/mfq-test-designer.md` |
| Skill 路径 | 嵌入 Agent 或 `copilot/skills/` | `skills/<name>/SKILL.md` | `skills/<name>/SKILL.md` |
| 工具声明 | `tools: [shell]` | CLAUDE.md 权限声明 | `manifest.yaml` tools 节 |
| 入口 | `@mfq-test-designer` | 对话激活 | 对话激活 |
| Python 工具 | `scripts/*.py`（shell 调用） | `scripts/*.py` | `scripts/*.py` |

---

## 1. GitHub Copilot CLI（v1.0.21+）

### 目录结构

```
<project-root>/
├── .github/
│   ├── copilot-instructions.md          # 全局指令（含 MFQ Skill 触发词表）
│   └── agents/
│       └── mfq-test-designer.agent.md   # 主 Agent 入口（含 14 Skill 描述）
├── scripts/
│   ├── excel_coupling_tool.py           # Excel 批注读写工具
│   └── mcp_query_client.py             # MCP 查询客户端
└── .workflow-meta/mfq/                           # 运行时工作目录（Agent 自动创建）
```

### 主入口文件

- **路径**：`.github/agents/mfq-test-designer.agent.md`
- **格式**：Markdown + YAML frontmatter
- **工具声明**：`tools: [shell]`（v1.0.21 仅支持 shell 工具类型）

### frontmatter 规范

```yaml
---
name: mfq-test-designer
description: "MFQ 测试用例设计工具 — 从特性需求到测试用例的完整分析流程"
tools:
  - shell
---
```

### Skill 嵌入策略

Copilot CLI 当前不支持独立 Skill 文件动态加载，因此 14 个 Skill 的**触发词和职责摘要**嵌入 Agent 正文，完整 Skill 逻辑由 Agent 按阶段内联引用。

### 已知限制

| 限制 | 影响 | 缓解措施 |
|------|------|---------|
| 工具类型仅支持 `shell` | 所有 Python 工具需通过 shell 调用 | `python scripts/excel_coupling_tool.py <args>` |
| 无原生 sub-agent 协议 | 不能自动切换 Agent | Skill 内容嵌入主 Agent |
| frontmatter 变更需重启 | 开发期调试不便 | 提示词正文中内联核心逻辑 |
| 单 Agent 提示词尺寸限制 | 14 Skill 全部嵌入可能超限 | Skill 分为"摘要嵌入"+"按需展开" |

### 验证清单

- [ ] `.github/agents/mfq-test-designer.agent.md` 存在且 frontmatter 合法
- [ ] `.github/copilot-instructions.md` 包含 MFQ 触发词声明
- [ ] `scripts/excel_coupling_tool.py` 可通过 `python scripts/excel_coupling_tool.py --help` 执行
- [ ] 在 Copilot CLI 中输入 `@mfq-test-designer` 可激活 Agent

---

## 2. Claude Code

### 目录结构

```
<project-root>/
├── .claude/
│   ├── CLAUDE.md                        # 全局配置（含工具权限 + Skill 路径）
│   ├── agents/
│   │   └── mfq-test-designer.md         # 主 Agent 入口
│   └── skills/
│       ├── feature-parser/SKILL.md
│       ├── scenario-discovery/SKILL.md
│       ├── m-analyzer/SKILL.md
│       ├── f-analyzer/SKILL.md
│       ├── q-analyzer/SKILL.md
│       ├── test-point-integrator/SKILL.md
│       ├── design-planner/SKILL.md
│       ├── data-combination-design/SKILL.md
│       ├── flowchart-design/SKILL.md
│       ├── state-diagram-design/SKILL.md
│       ├── coverage-verifier/SKILL.md
│       ├── deliverable-renderer/SKILL.md
│       ├── change-impact-analyzer/SKILL.md
│       └── bug-gap-analyzer/SKILL.md
├── scripts/
│   ├── excel_coupling_tool.py
│   └── mcp_query_client.py
└── .workflow-meta/mfq/
```

### 主入口文件

- **路径**：`.claude/agents/mfq-test-designer.md`
- **格式**：Markdown（无强制 frontmatter）
- **工具声明**：在 CLAUDE.md 中通过全局配置

### CLAUDE.md 关键配置

```markdown
## MFQ Test Designer 工具配置

### 工具权限
- shell: 允许（执行 Python 脚本）
- file_read/file_write: 允许（需求文件读取 + 中间产物 + 交付物输出）

### Skill 路径
Skill 定义文件位于 `.claude/skills/<skill-name>/SKILL.md`，共 14 个。
```

### 已知限制

| 限制 | 影响 | 缓解措施 |
|------|------|---------|
| Skill 路径需在 CLAUDE.md 声明 | 新增 Skill 需同步更新 | 打包脚本自动生成声明 |
| 无原生 MCP 集成（取决于版本） | MCP 查询需 Python 脚本兜底 | `scripts/mcp_query_client.py` |

### 验证清单

- [ ] `.claude/CLAUDE.md` 存在且包含工具权限声明
- [ ] `.claude/agents/mfq-test-designer.md` 存在
- [ ] `.claude/skills/*/SKILL.md` 共 14 个文件
- [ ] 重启 Claude Code 后 Agent 可激活

---

## 3. OpenClaw

### 目录结构

```
<project-root>/
├── .openclaw/
│   ├── manifest.yaml                    # 清单文件（Agent/Skill/Tool 全注册）
│   ├── agents/
│   │   └── mfq-test-designer.md
│   └── skills/
│       ├── feature-parser/SKILL.md
│       ├── ... (同 Claude Code 14 个 Skill)
│       └── bug-gap-analyzer/SKILL.md
├── scripts/
│   ├── excel_coupling_tool.py
│   └── mcp_query_client.py
└── .workflow-meta/mfq/
```

### manifest.yaml 规范

```yaml
name: mfq-test-designer
version: "1.0.0"
description: "MFQ 测试用例设计工具 — 从特性需求到测试用例的完整分析流程"

agents:
  - name: mfq-test-designer
    path: agents/mfq-test-designer.md
    entry: true

skills:
  - { name: feature-parser, path: skills/feature-parser/SKILL.md }
  - { name: scenario-discovery, path: skills/scenario-discovery/SKILL.md }
  - { name: m-analyzer, path: skills/m-analyzer/SKILL.md }
  - { name: f-analyzer, path: skills/f-analyzer/SKILL.md }
  - { name: q-analyzer, path: skills/q-analyzer/SKILL.md }
  - { name: test-point-integrator, path: skills/test-point-integrator/SKILL.md }
  - { name: design-planner, path: skills/design-planner/SKILL.md }
  - { name: data-combination-design, path: skills/data-combination-design/SKILL.md }
  - { name: flowchart-design, path: skills/flowchart-design/SKILL.md }
  - { name: state-diagram-design, path: skills/state-diagram-design/SKILL.md }
  - { name: coverage-verifier, path: skills/coverage-verifier/SKILL.md }
  - { name: deliverable-renderer, path: skills/deliverable-renderer/SKILL.md }
  - { name: change-impact-analyzer, path: skills/change-impact-analyzer/SKILL.md }
  - { name: bug-gap-analyzer, path: skills/bug-gap-analyzer/SKILL.md }

tools:
  - { name: excel-coupling-tool, type: python, path: scripts/excel_coupling_tool.py }
  - { name: mcp-query-client, type: python, path: scripts/mcp_query_client.py }
```

### 已知限制

| 限制 | 影响 | 缓解措施 |
|------|------|---------|
| manifest 格式可能随版本变化 | 需跟踪 OpenClaw 版本 | 打包脚本硬编码当前格式 |
| Skill 发现依赖 manifest 注册 | 新增 Skill 需同步更新 | 打包脚本自动扫描生成 |

### 验证清单

- [ ] `.openclaw/manifest.yaml` YAML 语法合法
- [ ] manifest 中声明的所有 path 对应文件存在
- [ ] Agent + Skill 数量与 manifest 声明一致（1 + 14）

---

## 跨平台共享内容

| 文件 | 内容 | 三平台共享 |
|------|------|-----------|
| `scripts/excel_coupling_tool.py` | Excel 批注读写（openpyxl / zipfile+XML） | ✅ 完全相同 |
| `scripts/mcp_query_client.py` | MCP 知识库查询客户端 | ✅ 完全相同 |
| 14 个 SKILL.md | 核心 MFQ 分析/设计逻辑 | ✅ 内容相同，安装路径不同 |
| Agent 提示词正文 | 编排逻辑 + 状态机 | ⚠️ 基本相同，frontmatter 格式不同 |
| `.workflow-meta/mfq/` | 运行时工作目录 | ✅ 结构相同 |

## 打包流程

```
.agents/skills/<name>/SKILL.md    ──┬──→ packages/copilot/   (嵌入 Agent)
.agents/agents/mfq-test-designer.md ├──→ packages/claude-code/ (.claude/skills/)
scripts/*.py                        └──→ packages/openclaw/   (.openclaw/skills/)
                                     ↑
                           scripts/build_packages.py（打包脚本）
```

## 通用约定

| 约定 | 内容 |
|------|------|
| 命名规范 | 文件名 kebab-case：`^[a-z][a-z0-9-]+\.(md\|yaml)$` |
| 必填 Frontmatter | Agent/Skill 文件必须包含 `name`、`description` |
| 版本锁定 | `INSTALL-CHECKSUMS.sha256` 记录每个产物文件的 SHA256 |
| 单一职责 | 每个 Skill 文件只描述一个能力 |
| 禁止自执行脚本 | 安装包中不得包含自动执行的 shell 脚本 |
