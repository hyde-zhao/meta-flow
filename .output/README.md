# MFQ&PPDCS 测试用例设计工具（mfq-test-designer）

> 基于《海盗派测试分析: MFQ&PPDCS》方法论，从特性需求到测试用例的系统化设计工具。  
> 支持 Copilot CLI / Claude Code / OpenClaw 三平台安装使用。

---

## 概述

MFQ&PPDCS 测试用例设计工具帮助测试架构师和测试工程师，通过 **M 分析**（基于 PPDCS 模型的单功能分析）→ **F 分析**（耦合关系）→ **Q 分析**（质量属性）的系统化流程，从特性需求出发输出完整的测试方案和测试用例。

**理论基础**：《海盗派测试分析: MFQ&PPDCS》（邰晓梅著）  
**首版试点**：华为防火墙设备（TGFW/NGFW）

## 核心特性

| 特性 | 说明 |
|------|------|
| 📋 **MFQ&PPDCS 分析链** | M(PPDCS) → F → Q 三维测试点分析 + PPDCS 特征标注 |
| 🔗 **耦合矩阵引擎** | 直读 Excel 批注（含 openpyxl + zipfile 双路径），内存图模型 |
| 🧪 **五种 PPDCS 设计方法** | 流程图法(P)、判定表法(P)、等价类+边界值法(D)、组合法(C)、状态图法(S) |
| ✅ **双层覆盖验证** | 需求层（SR→TP→LC）+ 测试点层（TP→PC）自动检查 |
| 🔄 **变更增量分析** | 需求变更仅影响相关模块，不改动无关用例 |
| 🐛 **问题单回溯** | 定位覆盖盲区、遗漏环节，输出流程优化建议 |

## PPDCS 五特征

| 特征 | 含义 | 识别条件 | 设计方法 |
|------|------|---------|---------|
| **P-Process** | 流程 | 多步骤有序约束，不可回退 | 流程图/活动图 |
| **P-Parameter** | 参数 | 参数间有业务规则依赖 | 判定表/因果图 |
| **D-Data** | 数据 | 数据有取值范围，各项独立 | 等价类+边界值 |
| **C-Combination** | 组合 | 多因子组合爆炸 | Pairwise/正交 |
| **S-State** | 状态 | 多状态可互转，有生命周期 | 状态图/转换表 |

**关键区分**：
- Process vs State → 流程能否回退？不能=Process，可以=State
- Parameter vs Data → 参数间有规则？有=Parameter，无=Data
- Data vs Combination → 独立验证够？够=Data，需组合=Combination

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│              mfq-test-designer Agent                     │
│           (12 步状态机 + 2 扩展分支)                      │
├─────────┬──────────┬──────────┬──────────┬──────────────┤
│  input  │ scenario │ M/F/Q    │ PPDCS    │  delivery    │
│         │          │ analysis │ design   │              │
├─────────┴──────────┴──────────┴──────────┴──────────────┤
│                     16 Skills                            │
│  feature-parser · scenario-discovery · m-analyzer        │
│  f-analyzer · q-analyzer · test-point-integrator         │
│  design-planner · process-design · parameter-design      │
│  data-design · combination-design · state-design         │
│  coverage-verifier · deliverable-renderer                │
│  change-impact-analyzer · bug-gap-analyzer               │
├─────────────────────────────────────────────────────────┤
│                   2 Python 工具                          │
│  excel_coupling_tool.py    mcp_query_client.py           │
└─────────────────────────────────────────────────────────┘
```

## 12 步主流程

```
 1. input        特性文件解析 + 三~五级目录确认           (KYM)
 2. scenario     应用场景分析 + 用户确认                   (KYM)
 3. m-analysis   单功能拆分 + PPDCS特征标注 + 测试点      (M+TCO)
 4. f-analysis   耦合关系分析（Excel矩阵 + 场景 + 代码） (F)
 5. q-analysis   质量属性分析（HTSM 维度评估）            (Q)
 6. integration  M+F+Q测试点归集 + 覆盖检查 + 逻辑合并
 7. plan         PPDCS五特征匹配推荐 + 用户确认            (PPDCS)
 8. design       并行用例设计（5种PPDCS方法选择执行）      (TD)
 9. coverage     双层覆盖率验证
10. delivery     交付物生成（测试方案.md + 测试用例.md）
```

### 扩展分支

- **需求变更**：变更需求 → 影响分析 → 增量 MFQ(PPDCS) → 增量设计 → 覆盖验证
- **问题单分析**：问题单 → 覆盖回溯 → 遗漏定位 → 用例补充 → 流程优化

## 快速开始

### Copilot CLI 安装

确保项目根目录包含以下文件（已随仓库提供）：

```
.github/agents/mfq-test-designer.agent.md    # Agent 入口
agents/mfq-test-designer.md           # Agent 完整提示词
skills/*/SKILL.md                     # 16 个 Skill
scripts/excel_coupling_tool.py                # Excel 工具
scripts/mcp_query_client.py                   # MCP 客户端
```

在 Copilot CLI 中输入 `@mfq-test-designer` 即可启动。

### Claude Code 安装

```
.claude/agents/mfq-test-designer.md
.claude/skills/<name>/SKILL.md
scripts/*.py
```

### OpenClaw 安装

```
.openclaw/agents/mfq-test-designer.md
.openclaw/skills/<name>/SKILL.md
.openclaw/manifest.yaml
scripts/*.py
```

## 使用流程

### 1. 启动分析

```
@mfq-test-designer 分析特性 "日志中心"
```

提供特性需求文件（支持 Markdown/Word/Excel/PDF），工具会：
1. 解析需求文件，提取结构化需求
2. 构建三~五级目录结构
3. 请求你确认目录结构

### 2. 场景对齐

工具通过 MCP 或 Web 搜索获取典型应用场景，以交互方式与你确认。

### 3. MFQ(PPDCS) 分析

自动执行 M(PPDCS 标注) → F → Q 三维分析。M 分析会为每个子模块标注 PPDCS 主特征。F 分析需要提供耦合矩阵 Excel 文件。

### 4. 用例设计

工具基于 PPDCS 特征匹配推荐设计方法后需你确认。确认后并行执行五种设计方法：

| PPDCS | 方法 | 适用场景 | 四步产出 |
|-------|------|---------|---------|
| P-Process | 流程图法 | 多步骤业务流程 | 流程图 → 路径表 → 路径数据 → 物理用例 |
| P-Parameter | 判定表法 | 参数有规则依赖 | 规则提取 → 判定表 → 逻辑用例 → 物理用例 |
| D-Data | 等价类+边界值 | 独立数据验证 | 等价类表 → 边界值表 → 逻辑用例 → 物理用例 |
| C-Combination | 组合法 | 多因子组合爆炸 | 因子表 → Pairwise → 逻辑用例 → 物理用例 |
| S-State | 状态图法 | 状态生命周期 | 状态图 → 转换表 → 迁移数据 → 物理用例 |

### 5. 交付

输出两个 Markdown 文档：
- **`<特性名>特性测试方案.md`**：特性概述 + 场景分析 + MFQ(PPDCS) 分析 + 整合
- **`<特性名>特性测试用例.md`**：测试点表 + 按五级目录组织的设计过程

## 用户确认点

| 步骤 | 确认内容 |
|------|---------|
| input 完成 | 三~五级目录结构 |
| scenario 完成 | 应用场景列表 |
| m-analysis 完成 | PPDCS 特征标注 |
| plan 完成 | 每个逻辑用例的 PPDCS 设计方法 |
| coverage 完成 | 覆盖率报告 |

## 运行时目录

工具运行时在 `mfq/` 目录存储中间产物：

```
mfq/
├── STATE.yaml              # 分析进度
├── feature-input/           # 需求 + 目录结构
├── scenarios/               # 应用场景
├── m-analysis/
│   ├── test-points.md       # M 分析测试点
│   └── ppdcs-annotation.md  # PPDCS 特征标注表
├── f-analysis/              # 耦合图模型 + 耦合测试点
├── q-analysis/              # 质量属性测试点
├── integration/             # 整合后的逻辑用例 + 测试数据 + PPDCS 设计计划
├── design/<module>/<sub>/
│   ├── ppdcs-profile.md     # PPDCS 特征详情
│   ├── design-process.md    # 四步设计过程
│   └── physical-cases.md    # 物理用例
├── coverage/                # 覆盖率报告
└── delivery/                # 最终交付物
```

## 前置依赖

| 依赖 | 说明 | 安装方式 |
|------|------|---------|
| Python 3.8+ | 运行 Python 工具脚本 | 系统自带或手动安装 |
| openpyxl | Excel 批注读写（首选） | `pip install openpyxl` |
| markitdown | 文件格式转换（可选） | `pip install markitdown[all]` |
| uv/uvx | markitdown 的推荐运行方式 | 参见 [uv 文档](https://github.com/astral-sh/uv) |

## 五级追踪链

```
SR（系统需求）→ TP（测试点）→ LC（逻辑用例）→ TD（测试数据）→ PC（物理用例）
```

支持正向追踪（需求→用例）和反向回溯（用例→需求），用于覆盖检查和问题单分析。

## 物理用例字段

| 字段 | 必填 | 说明 |
|------|------|------|
| 用例编号 | ✅ | `PC-<模块>-<子模块>-NNN` |
| 用例标题 | ✅ | 简明测试目的 |
| 测试数据 | ✅ | 具体数据值 |
| 预置条件 | ✅ | 执行前环境要求 |
| 测试步骤 | ✅ | 编号步骤列表 |
| 预期结果 | ✅ | 对应步骤的预期 |
| 优先级 | ✅ | P0（冒烟）~ P4（生僻） |
| 测试类型 | ✅ | 功能/性能/安全/可靠性等 |

## 优先级定义

| 优先级 | 含义 | 建议占比 |
|--------|------|---------|
| P0 | 冒烟测试 | ~5% |
| P1 | 基本功能 | ~25% |
| P2 | 重要功能 | ~40% |
| P3 | 一般功能 | ~25% |
| P4 | 生僻场景 | ~5% |

## 项目结构

```
myflow/
├── .agents/
│   ├── agents/
│   │   └── mfq-test-designer.md        # Agent 核心提示词
│   └── skills/
│       ├── feature-parser/SKILL.md
│       ├── scenario-discovery/SKILL.md
│       ├── m-analyzer/SKILL.md
│       ├── f-analyzer/SKILL.md
│       ├── q-analyzer/SKILL.md
│       ├── test-point-integrator/SKILL.md
│       ├── design-planner/SKILL.md
│       ├── process-design/SKILL.md        # P-Process
│       ├── parameter-design/SKILL.md      # P-Parameter
│       ├── data-design/SKILL.md           # D-Data
│       ├── combination-design/SKILL.md    # C-Combination
│       ├── state-design/SKILL.md          # S-State
│       ├── coverage-verifier/SKILL.md
│       ├── deliverable-renderer/SKILL.md
│       ├── change-impact-analyzer/SKILL.md
│       └── bug-gap-analyzer/SKILL.md
├── .github/agents/
│   └── mfq-test-designer.agent.md      # Copilot CLI 入口
├── scripts/
│   ├── excel_coupling_tool.py           # Excel 耦合矩阵工具
│   ├── mcp_query_client.py              # MCP 查询客户端
│   └── file_to_markdown.py              # 文件转 MD 工具
└── .input/                          # 参考文档
```

## 版本信息

| 字段 | 值 |
|------|------|
| 版本 | 2.0.0 |
| 理论基础 | MFQ&PPDCS（《海盗派测试分析》） |
| 架构 | 1 Agent + 16 Skills + 2 Python 工具 |
| 试点产品 | 华为防火墙（TGFW/NGFW） |
| 目标平台 | Copilot CLI / Claude Code / OpenClaw |

## License

内部工具，仅限项目组使用。
