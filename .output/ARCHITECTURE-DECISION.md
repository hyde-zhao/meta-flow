---
status: confirmed
version: "2.0"
confirmed: true
change_request: "CR-001"
confirmed_by: "user (auto-approved: recommended option A)"
confirmed_at: "2026-04-10T02:45:00Z"
---

# 架构决策记录 v2：MFQ&PPDCS 测试用例设计工具

> 本文档记录所有关键架构决策。v2 基于 MFQ&PPDCS 理论体系更新。

---

## ADR-1: Agent 架构模式（v2 确认）

**决策**：采用方案 A — 单编排 Agent + 16 Skill + 2~3 Python 工具

**背景**：
- 需求复杂度为 complex（20 条需求，3 角色，12 步主流程 + 2 扩展分支）
- PPDCS 集成使 Skill 数量从 14 增加到 16（设计 Skill 从 3→5）
- 首版聚焦华为防火墙试点，三平台均原生支持"1 Agent + N Skill"

**v1→v2 变化**：Skill 数量 14→16，主流程步骤 10→12

**后果**：
- ✅ 用户单一入口，三平台无缝兼容
- ✅ PPDCS 五特征完整覆盖
- ⚠️ 16 Skill 上下文压力略增（通过按需加载缓解）

**状态**：✅ 已确认

---

## ADR-2: F 分析数据底座（v1 不变）

**决策**：Excel 直读 + 内存图模型（首版不引入 Neo4j）

**背景**：
- 耦合矩阵当前以 Excel 形式维护（4 sheets，522 条批注）
- 引入 Neo4j 增加部署复杂度和学习成本

**方案细节**：
- 读取：`openpyxl` 解析 Excel 批注（首选），`zipfile + comments.xml` 解析（回退）
- 存储：Python 字典结构 `{nodes: [...], edges: [...]}`，YAML 序列化
- 查询：支持按功能点查询直接/间接耦合点
- 回写：`openpyxl` 写入新批注到 Excel

**状态**：✅ 已确认

---

## ADR-3: PPDCS 五特征建模框架（v2 新增 ⭐）

**决策**：M 分析阶段为每个单功能标注 PPDCS 主特征，设计计划阶段基于特征匹配选择方法

**背景**：
- 《海盗派测试分析》明确提出：选择测试设计技术应基于被测对象内在逻辑特征与技术特征的匹配
- v1 仅有 3 种设计方法（数据组合/流程图/状态图），将 P-Parameter/D-Data/C-Combination 混为一体
- PPDCS 是 MFQ 方法论中 M 维度的核心建模指导

**方案细节**：

1. **PPDCS 特征标注**（m-analyzer 输出）：
   - 为每个五级目录节点（单功能）标注 PPDCS 主特征和辅特征
   - 标注格式：`{ feature_id, ppdcs_primary: "P-Process|P-Parameter|D-Data|C-Combination|S-State", ppdcs_secondary: "...|null", rationale: "..." }`
   - 输出到 `mfq/m-analysis/ppdcs-annotation.md`

2. **特征匹配**（design-planner 输出）：
   - 读取 PPDCS 标注，为每个逻辑用例推荐设计 Skill
   - 优先级：S-State > P-Process > P-Parameter > C-Combination > D-Data
   - 混合特征：主特征决定主方法，辅特征生成补充用例

3. **五种设计 Skill 对齐**：
   | PPDCS | Skill | 建模输出 | 建模工具 |
   |-------|-------|---------|---------|
   | P-Process | process-design | 流程图 + 路径覆盖 | Mermaid flowchart |
   | P-Parameter | parameter-design | 判定表 + 规则列表 | Markdown 表格 |
   | D-Data | data-design | 等价类表 + 边界值 | Markdown 表格 |
   | C-Combination | combination-design | 因子表 + Pairwise | PICT/手动 |
   | S-State | state-design | 状态图 + 转换表 | Mermaid stateDiagram |

**关键区分规则**（嵌入 design-planner 提示词）：
- Process vs State → 流程能否回退？不能=Process，能=State
- Parameter vs Data → 参数间有业务规则？有=Parameter，无=Data
- Data vs Combination → 因子独立验证够？够=Data，需组合=Combination

**后果**：
- ✅ 测试设计技术选择有理论依据，从"经验驱动"升级为"特征匹配驱动"
- ✅ 覆盖 MFQ 理论的完整 PPDCS 维度
- ⚠️ PPDCS 特征识别依赖 LLM 语义理解，混合特征需人工辅助
- ⚠️ P-Parameter（判定表/因果图）建模是 5 种中最复杂的

**状态**：✅ 已确认

---

## ADR-4: 用例设计统一四步过程（v2 扩展为 5 种方法）

**决策**：五种设计方法统一为四步结构，每个逻辑用例按五级目录独立输出设计过程

**v1→v2 变化**：从 3 种方法扩展为 5 种，增加 P-Parameter 和 D-Data

**方案细节**：

| 步骤 | P-Process | P-Parameter | D-Data | C-Combination | S-State |
|------|-----------|-------------|--------|---------------|---------|
| 1-建模 | 流程图(Mermaid) | 判定表/因果图 | 等价类划分表 | 因子-状态表 | 状态图(Mermaid) |
| 2-推导 | 路径枚举 | 规则提取 | 边界值识别 | Pairwise 生成 | 转换表 |
| 3-逻辑用例 | 路径→LC | 规则→LC | 等价类→LC | 组合→LC | 转换→LC |
| 4-物理用例 | LC→PC(P0~P4) | LC→PC | LC→PC | LC→PC | LC→PC |

**后果**：
- ✅ 5 种方法输出格式统一，简化覆盖检查
- ✅ 设计过程可追溯、可审计
- ⚠️ P-Parameter 的步骤1（判定表构建）对 LLM 推理要求较高

**状态**：✅ 已确认

---

## ADR-5: 运行时工作目录结构（v2 增加 PPDCS 文件）

**决策**：使用 `mfq/` 目录，v2 增加 `ppdcs-annotation.md` 和 `ppdcs-profile.md`

**v1→v2 变化**：
- `m-analysis/` 新增 `ppdcs-annotation.md`（PPDCS 特征标注）
- `design/<module>/<sub-module>/` 新增 `ppdcs-profile.md`（子模块特征详情）
- `integration/design-plan.md` 增加 PPDCS 特征列

**状态**：✅ 已确认

---

## ADR-6: 平台适配策略（v1 不变）

**决策**：核心 Skill 平台无关，打包脚本自动转换为平台特定格式

**状态**：✅ 已确认

---

## ADR-7: 覆盖率追踪链（v1 不变）

**决策**：五级追踪链 `SR → TP → LC → TD → PC`，双向查询

**状态**：✅ 已确认

---

## 人工确认清单

| # | 决策 | 确认项 | 确认状态 |
|---|------|-------|---------|
| 1 | ADR-1 | 单 Agent + 16 Skill（v2）？ | ✅ 已确认 |
| 2 | ADR-2 | F 分析 Excel 直读 + 内存图模型？ | ✅ 已确认 |
| 3 | ADR-3 | **PPDCS 五特征建模框架？** | ✅ 已确认 |
| 4 | ADR-4 | 五种设计方法统一四步结构？ | ✅ 已确认 |
| 5 | ADR-5 | 运行时工作目录（含 PPDCS 文件）？ | ✅ 已确认 |
| 6 | ADR-6 | 平台适配策略？ | ✅ 已确认 |
| 7 | ADR-7 | 覆盖率追踪链？ | ✅ 已确认 |
