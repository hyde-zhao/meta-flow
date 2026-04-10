# MFQ&PPDCS 测试用例设计工具 — 用户手册

> 版本：2.0.0 | 理论基础：《海盗派测试分析: MFQ&PPDCS》 | 试点产品：华为防火墙（TGFW/NGFW）

---

## 目录

1. [安装指南](#1-安装指南)
2. [快速入门](#2-快速入门)
3. [完整使用流程](#3-完整使用流程)
4. [设计方法详解](#4-设计方法详解)
5. [变更管理](#5-变更管理)
6. [问题单分析](#6-问题单分析)
7. [工具脚本参考](#7-工具脚本参考)
8. [故障排除](#8-故障排除)
9. [常见问题](#9-常见问题)

---

## 1. 安装指南

### 1.1 前置条件

| 条件 | 最低版本 | 检查命令 |
|------|---------|---------|
| Python | 3.8+ | `python --version` |
| openpyxl | 任意 | `pip show openpyxl` |
| Copilot CLI | 1.0.21+ | 查看版本信息 |

```bash
# 安装 openpyxl（Excel 批注读写必需）
pip install openpyxl

# 安装 markitdown（文件格式转换可选）
pip install markitdown[all]
```

### 1.2 Copilot CLI 安装

1. 确保仓库根目录包含：
   - `.github/agents/ptm-tde.agent.md`
   - `agents/ptm-tde.md`
   - `skills/*/SKILL.md`（16 个 Skill）
   - `scripts/excel_coupling_tool.py`
   - `scripts/mcp_query_client.py`

2. 重启 Copilot CLI（Agent frontmatter 变更需要重启生效）

3. 使用 `@ptm-tde` 触发

### 1.3 Claude Code 安装

将以下文件复制到对应的 Claude Code 目录：
- `agents/ptm-tde.md` → `.claude/agents/ptm-tde.md`
- `skills/<name>/SKILL.md` → `.claude/skills/<name>/SKILL.md`
- `scripts/*.py` → `scripts/*.py`

### 1.4 OpenClaw 安装

将文件复制到 `.openclaw/` 目录，并创建 `manifest.yaml`：

```yaml
name: ptm-tde
version: 1.0.0
agents:
  - agents/ptm-tde.md
skills:
  - skills/*/SKILL.md
tools:
  - scripts/excel_coupling_tool.py
  - scripts/mcp_query_client.py
```

---

## 2. 快速入门

### 2.1 启动 MFQ 分析

```
@ptm-tde 我要分析"日志中心"特性的测试用例
```

### 2.2 提供输入文件

工具会提示你提供特性需求文件。支持的格式：

| 格式 | 说明 |
|------|------|
| `.md` | 直接解析 |
| `.docx` | 自动转换为 MD 后解析 |
| `.xlsx` | 自动转换为 MD 后解析 |
| `.pdf` | 自动转换为 MD 后解析 |

### 2.3 确认目录结构

工具解析需求后会展示三~五级目录：

```
日志中心（三级：特性）
├── 配置管理（四级：模块）
│   ├── 日志服务器配置（五级：子模块）
│   └── 日志过滤配置（五级：子模块）
└── 日志管理（四级：模块）
    ├── 日志查询（五级：子模块）
    └── 日志导出（五级：子模块）
```

确认或修改后继续。

### 2.4 跟随流程

工具按 10 步流程自动推进，在关键节点请求你确认。

---

## 3. 完整使用流程

### 3.1 Step 1 — 特性文件解析（feature-parser）

**输入**：特性需求文件  
**输出**：`.output/feature-input/raw-requirements.md` + `directory-structure.md`
**确认点**：目录结构

提取的需求字段：
- 编号（SR 编号）
- 所属模块
- SR 名称
- 描述

### 3.2 Step 2 — 场景分析（scenario-discovery）

**输入**：特性名称  
**输出**：`.output/scenarios/confirmed-scenarios.md`
**确认点**：场景列表

搜索策略优先级：
1. MCP 知识库（首选，需配置 MCP_ENDPOINT）
2. Web 搜索（回退）
3. 用户提供的资料

### 3.3 Step 3 — M 分析（m-analyzer）

**输入**：需求 + 目录 + 场景  
**输出**：`.output/m-analysis/test-points.md`

按五级目录逐模块分析，每个功能点生成测试点。测试点标注：
- TP-ID、模块、子模块、描述、关联需求、关联场景、来源、类型

### 3.4 Step 4 — F 分析（f-analyzer）

**输入**：M 分析结果 + 耦合矩阵 Excel  
**输出**：`.output/f-analysis/` 目录

三源耦合分析：

| 源 | 数据 | 说明 |
|----|------|------|
| 矩阵基线 | Excel 批注 | 最低基线，必须覆盖 |
| 场景耦合 | 场景推理 | 跨模块场景交互 |
| 代码依赖 | 用户输入 | 首版手动提供 |

Excel 工具使用方法：

```bash
# 读取耦合矩阵
python scripts/excel_coupling_tool.py read "耦合矩阵.xlsx" --output ".output/f-analysis/coupling-graph.json"

# 查询某特性的耦合点
python scripts/excel_coupling_tool.py query ".output/f-analysis/coupling-graph.json" --feature "日志"

# 回写新耦合点
python scripts/excel_coupling_tool.py write "耦合矩阵.xlsx" --source "new-coupling.json"
```

### 3.5 Step 5 — Q 分析（q-analyzer）

**输入**：M 分析结果 + 场景  
**输出**：`.output/q-analysis/quality-test-points.md`

HTSM 维度评估：

| 维度 | 典型防火墙相关性 |
|------|----------------|
| 可靠性 | 通常强相关（掉电恢复、主备切换） |
| 安全性 | 通常强相关（权限、审计） |
| 性能 | 视特性而定 |
| 可安装性 | 升级/回滚场景 |
| 兼容性 | 版本间兼容 |

### 3.6 Step 6 — 测试点整合（test-point-integrator）

**输入**：M + F + Q 测试点  
**输出**：`.output/integration/` 目录

核心操作：
1. 按模块归集所有测试点
2. 执行需求覆盖检查（逐条比对）
3. 合并相同测试逻辑
4. 分配测试数据

覆盖判定状态：
- **新增用例**：必须设计
- **合并**：合并到某逻辑用例（注明目标）
- **不设计用例**：应极少出现，需理由

### 3.7 Step 7 — 设计计划（design-planner）

**输入**：逻辑用例列表 + PPDCS 特征标注  
**输出**：`.output/integration/design-plan.md`
**确认点**：每个逻辑用例的 PPDCS 设计方法

PPDCS 五特征匹配规则：
- **S-State**：多状态可互转 → 状态图法（`state-design`）
- **P-Process**：多步骤有序约束 → 流程图法（`process-design`）
- **P-Parameter**：参数间有规则依赖 → 判定表法（`parameter-design`）
- **C-Combination**：多因子组合爆炸 → 组合法（`combination-design`）
- **D-Data**：数据独立有取值范围 → 等价类+边界值法（`data-design`）
- 极简场景 → 直接设计法（占比应 < 5%）

### 3.8 Step 8 — 用例设计

根据确认的 PPDCS 设计方法，对每个逻辑用例执行四步设计（详见[第 4 章](#4-设计方法详解)）。

不同逻辑用例可并行设计。

### 3.9 Step 9 — 覆盖验证（coverage-verifier）

**输出**：`.output/coverage/` 目录
**确认点**：覆盖率报告

| 检查维度 | 目标 |
|---------|------|
| 需求覆盖率 | = 100% |
| 测试点覆盖率 | ≥ 95% |

### 3.10 Step 10 — 交付（deliverable-renderer）

**输出**：`.output/delivery/` 目录

| 文档 | 内容 |
|------|------|
| `<特性名>特性测试方案.md` | 概述 + 场景 + 需求 + MFQ(PPDCS) 分析 + 整合 + 覆盖率 |
| `<特性名>特性测试用例.md` | 测试点表 + 按五级目录的完整四步设计过程 |

---

## 4. 设计方法详解（PPDCS 五方法）

### 4.1 P-Process — 流程图法（process-design）

适用于：多步骤有序约束的业务流程，流程不可回退

**四步过程**：

1. **流程图**：使用 Mermaid flowchart 语法建模
2. **路径枚举**：列出所有独立路径，标注经过的分支方向
3. **路径数据**：每条路径分配具体输入数据和预期输出
4. **物理用例**：每条路径对应一个或多个物理用例

**覆盖目标**：所有判断节点的每个分支至少覆盖一次。

### 4.2 P-Parameter — 判定表法（parameter-design）

适用于：参数间存在业务规则依赖，输入组合影响输出

**四步过程**：

1. **参数规则提取**：从需求中提取条件-结果关系
2. **判定表/因果图/决策树建模**：条件桩×动作桩矩阵
3. **逻辑用例**：判定表每条规则对应一条逻辑用例
4. **物理用例**：含优先级 + 测试类型 + 完整步骤

**建模方法选择**：参数少用判定表，逻辑复杂用因果图，有层次用决策树。

### 4.3 D-Data — 等价类+边界值法（data-design）

适用于：数据有明确取值范围，各数据项相对独立

**四步过程**：

1. **等价类划分表**

   | 数据项 | 有效等价类 | 无效等价类 |
   |--------|-----------|-----------|
   | 保存天数 | [1] 1~365 | [2] 0 [3] 负数 [4] >365 |

2. **边界值分析表**：min, min+1, 典型值, max-1, max + 无效边界

3. **逻辑用例**：有效值可组合，无效值必须隔离（一次一个无效值）
4. **物理用例**：含优先级 + 测试类型 + 完整步骤

### 4.4 C-Combination — 组合法（combination-design）

适用于：多因子多状态，全组合不可枚举

**四步过程**：

1. **因子提取**：列出因子及取值

   | 因子 | 取值列表 | 取值数 |
   |------|---------|--------|
   | 告警级别 | 紧急/主要/次要/提示 | 4 |

2. **组合压缩**：Pairwise/正交阵列（全组合 > 50 时自动建议压缩）

3. **逻辑用例**：每组数据对应一条逻辑用例
4. **物理用例**：含优先级 + 测试类型 + 完整步骤

### 4.5 S-State — 状态图法（state-design）

适用于：对象有多状态可互转（如配置的生命周期）

**四步过程**：

1. **状态图**：使用 Mermaid stateDiagram-v2 语法建模
2. **状态转换表**：列出所有合法和非法转换
3. **迁移路径**：设计覆盖所有转换的路径 + 数据
4. **物理用例**：含正面（合法转换）和负面（非法转换）测试

**覆盖目标**：所有合法转换覆盖 + 关键非法转换覆盖。

### 4.6 PPDCS 区分规则

| 疑似场景 | 区分问题 | 判定 |
|---------|---------|------|
| Process vs State | 流程能否回退？ | 不能=Process，可以=State |
| Parameter vs Data | 参数间有规则？ | 有=Parameter，无=Data |
| Data vs Combination | 独立验证够？ | 够=Data，需组合=Combination |

---

## 5. 变更管理

当特性需求发生变更时：

```
@ptm-tde 需求变更：日志服务器支持的最大数量从 8 调整为 16
```

工具会：
1. **影响分析**：识别受影响的模块/子模块
2. **增量 MFQ**：仅对受影响部分重新分析
3. **增量设计**：仅更新受影响的逻辑用例
4. **覆盖验证**：确保增量覆盖率 = 100%

**不可变保护**：未受影响的用例文件不会被修改。

---

## 6. 问题单分析

发现缺陷后：

```
@ptm-tde 分析问题单：BUG-001 日志服务器配置删除后残留过滤规则
```

工具会：
1. **覆盖回溯**：在追踪链中查找是否有用例覆盖
2. **遗漏定位**：确定在 M/F/Q/整合/设计 的哪个环节遗漏
3. **用例补充**：从遗漏环节开始补充
4. **流程优化**：输出防止同类遗漏的改进建议

---

## 7. 工具脚本参考

### 7.1 excel_coupling_tool.py

```bash
# 读取 Excel 耦合矩阵（含批注）
python scripts/excel_coupling_tool.py read <excel_path> [--output <output_path>]

# 查询某特性的耦合关系
python scripts/excel_coupling_tool.py query <graph_path> --feature <feature_name>

# 将新耦合点写回 Excel
python scripts/excel_coupling_tool.py write <excel_path> --source <source_path>
```

**支持的格式**：
- 图模型：JSON / YAML
- 输入 Excel：.xlsx（需包含批注）

**依赖**：openpyxl（首选），不可用时自动回退到 zipfile+XML

### 7.2 mcp_query_client.py

```bash
# 查询应用场景
python scripts/mcp_query_client.py --query "日志中心 应用场景" --type scenario

# 查询特性信息
python scripts/mcp_query_client.py --query "日志中心" --type feature

# 列出支持的查询类型
python scripts/mcp_query_client.py --list-types
```

**环境变量**：
- `MCP_ENDPOINT`：MCP 服务端地址（未配置时自动回退 Web 搜索）
- `MCP_API_KEY`：MCP 认证密钥

### 7.3 file_to_markdown.py

```bash
# 批量转换目录下的文件
python scripts/file_to_markdown.py <directory_path> [--recursive] [--dry-run]
```

---

## 8. 故障排除

### 8.1 Excel 工具无法读取批注

**症状**：`excel_coupling_tool.py read` 输出 0 批注

**排查**：
1. 确认 openpyxl 已安装：`pip show openpyxl`
2. 确认 Excel 文件包含批注（在 Excel 中查看）
3. 如果 openpyxl 安装失败，工具会自动回退到 zipfile+XML 解析

**解决**：
```bash
pip install openpyxl
```

### 8.2 Agent 无法触发

**症状**：输入 `@ptm-tde` 无响应

**排查**：
1. 确认 `.github/agents/ptm-tde.agent.md` 存在
2. 确认 Copilot CLI 版本 ≥ 1.0.21
3. **重启 Copilot CLI**（Agent frontmatter 变更需要重启生效）

### 8.3 MCP 查询无结果

**症状**：场景分析时提示 "MCP 未连接"

**说明**：这是正常行为。首版 MCP 客户端仅定义查询契约，实际连接待开发。  
**处理**：工具会自动回退到 Web 搜索获取场景信息。

### 8.4 覆盖率不达标

**症状**：coverage-verifier 报告未覆盖项

**排查**：
1. 检查未覆盖项列表，确认是否为真实遗漏
2. 查看覆盖报告中的 "补充建议"
3. 回到对应分析阶段补充测试点

### 8.5 `.output/` 目录异常

**症状**：分析中断后重新启动报错

**排查**：
1. 检查 `.output/STATE.yaml` 中的当前步骤
2. 工具支持从中断点恢复

**重置**：
```bash
# 完全重置（删除所有中间产物）
rm -rf .output/
```

### 8.6 文件转换失败

**症状**：非 Markdown 文件解析报错

**排查**：
1. 确认 `uvx` 可用：`uvx --version`
2. 确认 markitdown 可用：`uvx --from markitdown[all] markitdown --version`
3. 中文文件名需确保路径用引号包裹

---

## 9. 常见问题

### Q: 支持哪些产品？

首版试点华为防火墙（TGFW/NGFW），成熟后推广到其他产品。

### Q: 耦合矩阵 Excel 的格式要求？

无固定格式要求。工具读取所有 sheet 的所有批注，通过语义过滤器区分有效耦合点和审阅批注。

### Q: 可以跳过某些分析步骤吗？

不建议。MFQ 三维分析是完整方法论，跳过可能导致覆盖不全。但 Q 分析中不相关的维度会自动跳过。

### Q: 设计方法可以手动指定吗？

可以。design-planner 会基于 PPDCS 特征自动匹配推荐方法，但用户可以在确认时修改任何逻辑用例的设计方法。

### Q: 变更分析会影响已有用例吗？

不会。change-impact-analyzer 有不可变保护，只修改受影响的模块和用例。

### Q: 一次可以分析多少需求？

没有硬性限制，但建议按特性为粒度分析。大型特性（100+ 需求）建议按模块分批。

---

## 附录

### A. Skill 触发词速查

| Skill | 触发词 |
|-------|--------|
| feature-parser | 解析特性、解析需求、导入特性文件 |
| scenario-discovery | 场景分析、搜索场景、应用场景 |
| m-analyzer | M分析、功能分析、模块分析 |
| f-analyzer | F分析、耦合分析、耦合矩阵 |
| q-analyzer | Q分析、质量分析、HTSM |
| test-point-integrator | 整合测试点、逻辑用例 |
| design-planner | 设计计划、方法推荐 |
| data-combination-design | 数据组合、等价类 |
| flowchart-design | 流程图、路径分析 |
| state-diagram-design | 状态图、状态机 |
| coverage-verifier | 覆盖检查、覆盖率 |
| deliverable-renderer | 生成交付物、测试方案 |
| change-impact-analyzer | 需求变更、变更分析 |
| bug-gap-analyzer | 问题单、缺陷分析 |

### B. 文件清单

| 文件 | 说明 |
|------|------|
| `agents/ptm-tde.md` | Agent 核心提示词 |
| `skills/<name>/SKILL.md` × 14 | 14 个 Skill 定义 |
| `.github/agents/ptm-tde.agent.md` | Copilot CLI 入口 |
| `scripts/excel_coupling_tool.py` | Excel 耦合矩阵读写 |
| `scripts/mcp_query_client.py` | MCP 知识库查询 |
| `scripts/file_to_markdown.py` | 文件批量转 MD |
