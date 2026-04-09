---
status: confirmed
version: "1.0"
complexity: "complex"
selected_option: "A"
confirmed_by: "user (auto-approved: recommended option)"
confirmed_at: "2026-04-09T11:50:00Z"
---

# 方案设计：MFQ 测试用例设计工具

> 本文档基于 SOLUTION-OPTIONS.md 的推荐方案 A 编写，待用户在检查点②确认后生效。

## 1. 复杂度判定

**模式：`complex`**

| 判定维度 | 依据 | 结论 |
|---------|------|------|
| 需求规模 | 20 条功能/非功能需求（R1~R20） | 超出 standard 阈值 |
| 角色数量 | 3 个用户画像 × 11 个使用场景 | 多角色多场景 |
| 状态流转 | 10 步主流程 + 2 条扩展分支（变更/问题单），含 6 个用户确认点 | 多分支 |
| 平台适配 | 3 平台（Copilot CLI / Claude Code / OpenClaw），格式差异显著 | 需适配层 |
| Story 拆解 | 按 6 个里程碑（M1~M6）分批交付 | 必需 |

## 2. 产物形态

| 产物类型 | 数量 | 清单 |
|---------|------|------|
| **Agent** | 1 | `mfq-test-designer`（主编排器） |
| **Skill** | 14 | 见下方 Skill 清单 |
| **Python 工具** | 2 | `excel_coupling_tool.py`、`mcp_query_client.py` |
| **平台安装包** | 3 | Copilot CLI / Claude Code / OpenClaw |

### Skill 清单

| # | Skill 名称 | 关联需求 | 阶段 | 职责 |
|---|-----------|---------|------|------|
| 1 | `feature-parser` | R1 | 输入 | 解析特性需求文件，提取编号/模块/SR/描述，构建三级~五级目录 |
| 2 | `scenario-discovery` | R2, R17 | 输入 | MCP/Web 搜索获取应用场景，交互式确认 |
| 3 | `m-analyzer` | R3 | M 分析 | 按目录拆分功能点，生成测试点，检查需求覆盖 |
| 4 | `f-analyzer` | R4~R8 | F 分析 | 三源耦合分析（矩阵基线+场景+代码），图模型构建，候选点确认与回写 |
| 5 | `q-analyzer` | R9 | Q 分析 | HTSM 维度相关性评估，质量属性测试点生成 |
| 6 | `test-point-integrator` | R10 | 整合 | M+F+Q 测试点归集，覆盖检查，相同逻辑合并，测试数据分配 |
| 7 | `design-planner` | R11 | 整合 | 逻辑用例设计方法推荐，生成设计计划表，用户确认 |
| 8 | `data-combination-design` | R12 | 设计 | 等价类划分→数据组合→逻辑用例→物理用例（四步） |
| 9 | `flowchart-design` | R13 | 设计 | 流程图→路径枚举→路径数据→物理用例（四步） |
| 10 | `state-diagram-design` | R14 | 设计 | 状态图→转换表→迁移数据→物理用例（四步） |
| 11 | `coverage-verifier` | R15 | 验证 | 需求层+测试点层双层覆盖率检查 |
| 12 | `deliverable-renderer` | R16 | 交付 | 测试方案.md + 测试用例.md 生成 |
| 13 | `change-impact-analyzer` | R19 | 变更 | 变更需求影响分析→增量 MFQ→增量设计→增量覆盖 |
| 14 | `bug-gap-analyzer` | R20 | 变更 | 问题单覆盖盲区→遗漏定位→用例补充→流程优化建议 |

## 3. 目标平台

| 平台 | Agent 格式 | Skill 格式 | 工具声明 | 入口 |
|------|-----------|-----------|---------|------|
| Copilot CLI | `.github/agents/mfq-test-designer.agent.md` | Skill 内容嵌入 Agent 或 `.github/copilot/skills/*.md` | `tools: [shell]` | `@mfq-test-designer` |
| Claude Code | `.claude/agents/mfq-test-designer.md` | `.claude/skills/<name>/SKILL.md` | CLAUDE.md 中声明 | 对话激活 |
| OpenClaw | `.openclaw/agents/mfq-test-designer.md` | `.openclaw/skills/<name>/SKILL.md` | `manifest.yaml` | 对话激活 |

## 4. 运行时工作目录

MFQ 工具运行时使用 `.mfq-work/` 目录存储中间产物：

```
.mfq-work/
├── STATE.yaml                  # 当前分析进度（阶段、步骤、确认状态）
├── feature-input/
│   ├── raw-requirements.md     # 解析后的需求列表
│   └── directory-structure.md  # 已确认的三~五级目录
├── scenarios/
│   └── confirmed-scenarios.md  # 已确认的应用场景
├── m-analysis/
│   └── test-points.md          # M 分析产出的测试点
├── f-analysis/
│   ├── matrix-baseline.yaml    # Excel 矩阵基线（解析后）
│   ├── coupling-graph.yaml     # 内存图模型序列化
│   └── coupling-test-points.md # F 分析产出的耦合测试点
├── q-analysis/
│   └── quality-test-points.md  # Q 分析产出的测试点
├── integration/
│   ├── all-test-points.md      # M+F+Q 整合后的全量测试点
│   ├── logic-cases.md          # 逻辑用例列表
│   ├── test-data.md            # 逻辑用例对应测试数据
│   └── design-plan.md          # 设计方法推荐表（已确认）
├── design/
│   ├── <module>/<sub-module>/  # 按五级目录组织
│   │   ├── design-process.md   # 四步设计过程
│   │   └── physical-cases.md   # 物理用例
│   └── ...
├── coverage/
│   ├── requirement-coverage.md # 需求层覆盖报告
│   └── test-point-coverage.md  # 测试点层覆盖报告
└── delivery/
    ├── xx特性测试方案.md
    └── xx特性测试用例.md
```

## 5. 主要设计决策

### D1: 单 Agent 上下文管理策略

**决策**：Skill 按需激活 + 中间产物文件持久化

- Agent 提示词仅包含编排逻辑和状态机定义（~2000 tokens）
- 每个 Skill 的提示词在调用时动态加载（~500~1500 tokens/Skill）
- 所有阶段产出物写入 `.mfq-work/` 目录，后续阶段从文件读取
- 单次活跃上下文 ≤ Agent 提示词 + 1~2 个 Skill + 当前阶段数据

### D2: F 分析三源合并策略

**决策**：Excel 基线 → 场景补充 → 代码补充 → 去重合并 → 用户确认

- 第一源（Excel 矩阵）：使用 `openpyxl`（首选）或 `zipfile+XML`（回退）读取批注
- 第二源（场景耦合）：从已确认场景推理功能点间耦合
- 第三源（代码依赖）：首版为手动输入（P2 优先级）
- 合并后去重：相同功能点对的耦合关系合并，保留所有来源标注
- 图模型：内存字典结构（nodes + edges），序列化为 YAML
- 新耦合点：生成候选列表 → 用户确认 → 可选回写 Excel

### D3: 用例设计四步过程标准化

**决策**：三种设计方法统一为四步结构，输出格式一致

| 步骤 | 数据组合法 | 流程图法 | 状态图法 |
|------|-----------|---------|---------|
| 步骤 1 | 等价类划分表 | 流程图（Mermaid） | 状态图（Mermaid） |
| 步骤 2 | 数据组合分析表 | 路径枚举+分支覆盖 | 状态转换表 |
| 步骤 3 | 逻辑用例设计 | 路径数据分配 | 迁移路径数据分配 |
| 步骤 4 | 物理用例设计 | 物理用例设计 | 物理用例设计 |

物理用例统一字段：`用例编号 / 用例标题 / 测试数据 / 预置条件 / 测试步骤 / 预期结果 / 优先级(P0~P4) / 测试类型`

### D4: 覆盖率追踪链

**决策**：建立五级追踪链，支持双向查询

```
需求条目(SR) → 测试点(TP) → 逻辑用例(LC) → 测试数据(TD) → 物理用例(PC)
```

- 每个对象持有上下游引用 ID
- 覆盖检查分两层独立执行：
  - 需求层：每个 SR 的每个 TP 至少关联 1 个 LC+TD
  - 测试点层：每个 TP 至少被 1 个 PC 覆盖
- 未覆盖项自动生成补充建议

### D5: 变更与问题单的增量处理

**决策**：影响范围限定 + 增量分析 + 不可变保护

- 变更分析（R19）：从变更描述定位受影响的四/五级目录 → 仅对这些目录重新执行 MFQ → 增量合并
- 问题单分析（R20）：从复现路径定位所属目录 → 反向追踪覆盖链 → 定位遗漏环节
- 不可变保护：未受影响的 `.mfq-work/design/<module>/` 目录标记为 `frozen`，写保护

### D6: 平台适配策略

**决策**：核心 Skill 平台无关，适配层仅处理格式转换

```
packages/
├── copilot/     → .github/agents/ + .github/copilot/skills/
├── claude-code/ → .claude/agents/ + .claude/skills/
└── openclaw/    → .openclaw/agents/ + .openclaw/skills/ + manifest.yaml
```

- 核心 Skill 内容（Markdown 格式）三平台共享
- 适配差异：Agent frontmatter 格式、工具声明方式、入口触发词
- 打包脚本自动转换核心 Skill → 平台特定格式

## 6. 技术选型

| 技术栈 | 选型 | 理由 |
|--------|------|------|
| Agent 提示词 | Markdown + YAML frontmatter | 三平台通用格式 |
| Skill 提示词 | Markdown（SKILL.md） | SCOPE-Pack 标准 |
| Excel 读写 | openpyxl（首选）/ zipfile+XML（回退） | 需要读写批注；openpyxl 未安装时用 XML |
| 图模型 | Python 字典 + YAML 序列化 | 轻量级，无外部依赖 |
| 流程图/状态图 | Mermaid 语法（嵌入 Markdown） | Markdown 原生渲染 |
| MCP 查询 | Python HTTP 客户端 | 知识库查询接口（契约先行） |
| Web 搜索 | 平台内置搜索能力 | MCP 回退 |
| 文件格式转换 | markitdown（已有 Skill） | Excel/Word/PDF → Markdown |

## 7. 风险对策

| 风险 | 严重度 | 对策 |
|------|--------|------|
| 单 Agent 上下文溢出 | 中 | Skill 按需加载 + 文件持久化 + 未来可拆分为 Option B |
| Excel 批注解析失败 | 中 | openpyxl 失败时回退 zipfile+XML；不可解析批注标记人工处理 |
| MCP 知识库不可用 | 低 | Web 搜索自动回退 |
| 三平台格式不一致 | 低 | 打包脚本自动化转换 + 平台验证测试 |
| 大型特性测试点过多 | 中 | 分模块增量处理，每次只加载当前模块上下文 |
