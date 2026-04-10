---
status: confirmed
version: "2.0"
complexity: "complex"
selected_option: "A"
change_request: "CR-001"
confirmed_by: "user (auto-approved: recommended option A)"
confirmed_at: "2026-04-10T02:45:00Z"
theoretical_basis: "《海盗派测试分析: MFQ&PPDCS》邰晓梅著, ISBN 978-7-115-44415-8"
---

# 方案设计 v2：MFQ&PPDCS 测试用例设计工具

> 本文档基于 SOLUTION-OPTIONS.md v2 的方案 A 编写。
> 理论基础：MFQ&PPDCS 框架（邰晓梅《海盗派测试分析》）

---

## 1. 复杂度判定

**模式：`complex`**（与 v1 一致，PPDCS 集成增加了设计层复杂度）

| 判定维度 | 依据 | 结论 |
|---------|------|------|
| 需求规模 | 20 条功能/非功能需求（R1~R20），PPDCS 增加 2 条隐式需求 | 超出 standard |
| 角色数量 | 3 个用户画像 × 11 个使用场景 | 多角色多场景 |
| 状态流转 | 12 步主流程（v1 为 10 步）+ 2 扩展分支，含 6 个用户确认点 | 多分支 |
| 平台适配 | 3 平台，格式差异显著 | 需适配层 |
| Story 拆解 | 按 6 个里程碑分批交付 | 必需 |

## 2. 理论框架对齐

### 2.1 MFQ&PPDCS 完整框架（来源：书籍第三章~第五章）

```
完整框架：KYM → TCO → MFQ(PPDCS) → TD → TE

KYM (Know Your Mission)     — 了解测试任务（用户提供需求文件 + 场景对齐）
TCO (Testing Coverage Outline) — 测试覆盖大纲（三~五级目录 + 测试点清单）
MFQ — 三维度测试分析：
  M (MD: Model-based Discrete Function) — 单功能测试分析（使用 PPDCS 建模）
  F (FI: Function Interaction)          — 功能交互/耦合分析
  Q (QC: Quality Characteristics)       — 质量属性分析
PPDCS — M 分析中的 5 种建模特征：
  P-Process     流程：多步骤有前后约束     → 流程图/活动图建模
  P-Parameter   参数：参与业务规则处理     → 判定表/因果图/决策树建模
  D-Data        数据：有取值范围，独立验证  → 等价类划分 + 边界值分析
  C-Combination 组合：多因子多状态组合爆炸  → Pairwise/正交阵列
  S-State       状态：对象多状态可互转     → 状态图/状态转换表

关键区分：
  P-Process vs S-State：Process 单向不可逆流程；State 允许双向状态转换
  P-Parameter vs D-Data：Parameter 关注规则处理是否正确；Data 关注取值是否正确
  C-Combination：当 Data/Parameter 的因子过多时，用 Pairwise 压缩组合空间
```

### 2.2 工具实现映射

| 框架阶段 | 工具阶段 | 实现 Skill |
|---------|---------|-----------|
| KYM | input + scenario | feature-parser + scenario-discovery |
| TCO | m-analysis (目录+测试点) | m-analyzer |
| M (PPDCS) | m-analysis (特征标注) | m-analyzer（PPDCS 特征标注） |
| F | f-analysis | f-analyzer |
| Q | q-analysis | q-analyzer |
| TD | design (5种方法) | design-planner + 5 个 PPDCS 设计 Skill |
| TE | — | 工具不涉及执行阶段 |

## 3. 产物形态

| 产物类型 | 数量 | 清单 | v1→v2 变化 |
|---------|------|------|-----------|
| **Agent** | 1 | `mfq-test-designer`（主编排器） | 12步状态机（+2步） |
| **Skill** | 16 | 见下方 Skill 清单 | +2（parameter-design, data-design） |
| **Python 工具** | 2~3 | `excel_coupling_tool.py`、`mcp_query_client.py`、`pict_wrapper.py`(可选) | +1可选 |
| **平台安装包** | 3 | Copilot CLI / Claude Code / OpenClaw | 不变 |

### Skill 清单（v2）

| # | Skill 名称 | 关联需求 | PPDCS 对齐 | 阶段 | 职责 | v1→v2 |
|---|-----------|---------|-----------|------|------|-------|
| 1 | `feature-parser` | R1 | KYM | 输入 | 解析特性需求文件，提取编号/模块/SR/描述，构建三级~五级目录 | 不变 |
| 2 | `scenario-discovery` | R2, R17 | KYM | 输入 | MCP/Web 搜索获取应用场景，交互式确认 | 不变 |
| 3 | `m-analyzer` | R3 | M+TCO | M 分析 | 单功能拆分 + **PPDCS 特征标注** + 测试点生成 | **增强** |
| 4 | `f-analyzer` | R4~R8 | F | F 分析 | 三源耦合分析，图模型构建，候选点确认与回写 | 不变 |
| 5 | `q-analyzer` | R9 | Q | Q 分析 | HTSM 维度相关性评估，质量属性测试点 | 不变 |
| 6 | `test-point-integrator` | R10 | — | 整合 | M+F+Q 测试点归集，覆盖检查，逻辑合并 | 不变 |
| 7 | `design-planner` | R11 | PPDCS | 整合 | **PPDCS 五特征匹配推荐** + 用户确认 | **增强** |
| 8 | `process-design` | R13 | P-Process | 设计 | 流程图建模→路径枚举→路径数据→物理用例 | **重命名**(原flowchart-design) |
| 9 | `parameter-design` | R12 | P-Parameter | 设计 | 判定表/因果图建模→规则提取→逻辑用例→物理用例 | **新增** |
| 10 | `data-design` | R12 | D-Data | 设计 | 等价类划分→边界值识别→逻辑用例→物理用例 | **新增**(从data-combination拆出) |
| 11 | `combination-design` | R12 | C-Combination | 设计 | 因子-状态表→Pairwise/正交生成→逻辑用例→物理用例 | **重构**(原data-combination) |
| 12 | `state-design` | R14 | S-State | 设计 | 状态图→转换表→迁移路径→物理用例 | **重命名**(原state-diagram-design) |
| 13 | `coverage-verifier` | R15 | — | 验证 | 需求层+测试点层双层覆盖率检查 | 不变 |
| 14 | `deliverable-renderer` | R16 | — | 交付 | 测试方案.md + 测试用例.md 生成 | 不变 |
| 15 | `change-impact-analyzer` | R19 | — | 变更 | 变更需求影响分析→增量 MFQ→增量设计 | 不变 |
| 16 | `bug-gap-analyzer` | R20 | — | 变更 | 问题单覆盖盲区→用例补充→流程优化 | 不变 |

### v1 → v2 变更明细

| v1 组件 | v2 组件 | 变更类型 | 说明 |
|---------|---------|---------|------|
| m-analyzer | m-analyzer | **增强** | 新增 PPDCS 特征标注输出 |
| design-planner | design-planner | **增强** | 匹配逻辑从 3 种方法→5 种 PPDCS 特征 |
| data-combination-design | parameter-design + data-design + combination-design | **拆分** | 对齐 P-Parameter / D-Data / C-Combination |
| flowchart-design | process-design | **重命名** | 对齐 P-Process 理论命名 |
| state-diagram-design | state-design | **重命名** | 对齐 S-State 理论命名 |

## 4. 目标平台

（与 v1 一致）

| 平台 | Agent 格式 | Skill 格式 | 工具声明 | 入口 |
|------|-----------|-----------|---------|------|
| Copilot CLI | `.github/agents/mfq-test-designer.agent.md` | Skill 内容嵌入 Agent | `tools: [shell]` | `@mfq-test-designer` |
| Claude Code | `.claude/agents/mfq-test-designer.md` | `.claude/skills/<name>/SKILL.md` | CLAUDE.md 中声明 | 对话激活 |
| OpenClaw | `.openclaw/agents/mfq-test-designer.md` | `.openclaw/skills/<name>/SKILL.md` | `manifest.yaml` | 对话激活 |

## 5. 运行时工作目录（v2 更新）

```
.workflow-meta/mfq/
├── STATE.yaml                   # 当前分析进度
├── feature-input/
│   ├── raw-requirements.md      # 解析后的需求列表
│   └── directory-structure.md   # 已确认的三~五级目录
├── scenarios/
│   └── confirmed-scenarios.md   # 已确认的应用场景
├── m-analysis/
│   ├── test-points.md           # M 分析产出的测试点
│   └── ppdcs-annotation.md      # **[v2新增] PPDCS 特征标注表**
├── f-analysis/
│   ├── matrix-baseline.yaml
│   ├── coupling-graph.yaml
│   └── coupling-test-points.md
├── q-analysis/
│   └── quality-test-points.md
├── integration/
│   ├── all-test-points.md
│   ├── logic-cases.md
│   ├── test-data.md
│   └── design-plan.md          # **[v2更新] 含 PPDCS 特征列**
├── design/
│   ├── <module>/<sub-module>/
│   │   ├── ppdcs-profile.md    # **[v2新增] 该子模块的 PPDCS 特征**
│   │   ├── design-process.md   # 四步设计过程
│   │   └── physical-cases.md
│   └── ...
├── coverage/
│   ├── requirement-coverage.md
│   └── test-point-coverage.md
└── delivery/
    ├── xx特性测试方案.md
    └── xx特性测试用例.md
```

## 6. 主要设计决策

### D1: 单 Agent + PPDCS 五特征匹配（v2 新增核心决策）

**决策**：在 M 分析阶段为每个单功能标注 PPDCS 主特征，设计计划阶段基于特征匹配选择设计方法。

**理论依据**（《海盗派》P183）：
> 选择测试设计技术应基于被测对象内在逻辑的「特征」与测试设计技术的「特征」的匹配，
> 当二者对齐时，该技术最为有效。

**PPDCS 特征匹配规则**：

| 识别条件 | PPDCS 特征 | 推荐设计 Skill | 建模输出 |
|---------|-----------|---------------|---------|
| 需求有业务流程含义，多步骤有序约束，可能涉及多角色 | P-Process | process-design | 流程图/活动图 |
| 参数参与业务规则判定，输入组合影响输出结果 | P-Parameter | parameter-design | 判定表/因果图 |
| 数据有明确取值范围，各数据项相对独立 | D-Data | data-design | 等价类表 + 边界值 |
| 多因子多状态，全组合不可枚举 | C-Combination | combination-design | 因子表 + Pairwise |
| 对象有多状态可互转，存在状态生命周期 | S-State | state-design | 状态图/转换表 |
| 混合特征（≥2 个特征同时存在） | 主特征优先 | 主方法 + 辅方法补充 | 两种模型组合 |

**特征区分规则**：
- P-Process vs S-State：问"流程能否回到前面的步骤？" → 不能回退 = Process，可以回退 = State
- P-Parameter vs D-Data：问"参数间有业务规则关系吗？" → 有规则 = Parameter，无规则/独立 = Data
- D-Data vs C-Combination：问"因子独立验证够吗？" → 够 = Data，因子间有交互需组合 = Combination

### D2: 上下文管理策略（不变）

Skill 按需激活 + 中间产物文件持久化。

### D3: F 分析三源合并策略（不变）

Excel 基线 → 场景补充 → 代码补充 → 去重合并 → 用户确认。

### D4: 五种 PPDCS 设计方法的统一四步过程（v2 扩展）

**决策**：5 种设计方法统一为四步结构，输出格式一致。

| 步骤 | P-Process | P-Parameter | D-Data | C-Combination | S-State |
|------|-----------|-------------|--------|---------------|---------|
| 1-建模 | 流程图(Mermaid) | 判定表/因果图 | 等价类划分表 | 因子-状态表 | 状态图(Mermaid) |
| 2-推导 | 路径枚举 | 规则提取 | 边界值识别 | Pairwise 生成 | 转换表 |
| 3-逻辑用例 | 路径→LC | 规则→LC | 等价类→LC | 组合→LC | 转换→LC |
| 4-物理用例 | LC→PC | LC→PC | LC→PC | LC→PC | LC→PC |

物理用例统一字段：`用例编号 / 用例标题 / 测试数据 / 预置条件 / 测试步骤 / 预期结果 / 优先级(P0~P4) / 测试类型`

### D5: 覆盖率追踪链（不变）

五级追踪链：`SR → TP → LC → TD → PC`，双向查询。

### D6: 变更与问题单的增量处理（不变）

影响范围限定 + 增量 MFQ(PPDCS) + 不可变保护。

### D7: 平台适配策略（不变）

核心 Skill 平台无关，打包脚本自动转换。

## 7. 12 步主流程（v2）

```
 1. input        特性文件解析 + 三~五级目录确认              [feature-parser]      (KYM)
 2. scenario     应用场景分析 + 用户确认                      [scenario-discovery]   (KYM)
 3. m-analysis   单功能拆分 + PPDCS特征标注 + 测试点生成     [m-analyzer]           (M+TCO)
 4. f-analysis   耦合关系分析（三源合并）                     [f-analyzer]           (F)
 5. q-analysis   质量属性分析（HTSM）                         [q-analyzer]           (Q)
 6. integration  M+F+Q测试点归集 + 覆盖检查 + 逻辑合并        [test-point-integrator]
 7. plan         PPDCS五特征匹配推荐 + 用户确认               [design-planner]       (PPDCS)
 8. design       并行用例设计（5种PPDCS方法选择性执行）        [5 design Skills]      (TD)
 9. coverage     双层覆盖率验证                                [coverage-verifier]
10. delivery     交付物生成（测试方案.md + 测试用例.md）       [deliverable-renderer]
```

扩展分支（不变）：
- 变更分支：需求变更 → 影响定位 → 增量 MFQ(PPDCS) → 增量设计
- 问题单分支：问题单 → 覆盖盲区 → 遗漏定位 → 用例补充 → 流程优化

## 8. 技术选型

| 技术栈 | 选型 | 理由 | v1→v2 变化 |
|--------|------|------|-----------|
| Agent 提示词 | Markdown + YAML frontmatter | 三平台通用 | 不变 |
| Skill 提示词 | Markdown（SKILL.md） | SCOPE-Pack 标准 | 不变 |
| Excel 读写 | openpyxl / zipfile+XML 回退 | 批注读写 | 不变 |
| 图模型 | Python 字典 + YAML | 轻量级 | 不变 |
| 流程/状态图 | Mermaid 语法 | Markdown 渲染 | 不变 |
| 判定表/因果图 | Markdown 表格 + Mermaid | **[v2新增]** P-Parameter 建模 | **新增** |
| Pairwise | PICT(可选) / 手动建模 | **[v2新增]** C-Combination | **新增** |
| MCP 查询 | Python HTTP 客户端 | 知识库接口 | 不变 |
| 文件格式转换 | markitdown | Excel/Word/PDF→MD | 不变 |

## 9. 风险对策

| 风险 | 严重度 | 对策 | v1→v2 变化 |
|------|--------|------|-----------|
| 单 Agent 上下文溢出 | 中 | Skill 按需加载 + 文件持久化 | 不变 |
| **PPDCS 特征识别不准** | **中** | **提供明确区分规则 + 用户确认** | **v2 新增** |
| **P-Parameter 建模复杂** | **中** | **首版简化为判定表，因果图作为高级选项** | **v2 新增** |
| Excel 批注解析失败 | 中 | openpyxl→zipfile+XML 双重回退 | 不变 |
| MCP 知识库不可用 | 低 | Web 搜索自动回退 | 不变 |
| **PICT 工具不可用** | **低** | **手动 pairwise 建模回退** | **v2 新增** |
| 大型特性测试点过多 | 中 | 分模块增量处理 | 不变 |
