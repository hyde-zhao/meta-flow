---
status: confirmed
version: "1.0"
total_stories: 16
total_waves: 4
created_by: "meta-se"
created_at: "2026-04-09T11:50:00Z"
confirmed_by: "user"
confirmed_at: "2026-04-09T12:09:51Z"
---

# Story Backlog — MFQ 测试用例设计工具

> 按里程碑（M1~M6）拆解，每个 Story 含明确的输入/输出/完成准则。
> 产物：1 Agent（`mfq-test-designer`）+ 14 Skill + 2 Python 工具

---

## Story 总览

| Story ID | 标题 | 里程碑 | 需求 | Wave | 优先级 | 依赖 |
|----------|------|--------|------|------|--------|------|
| STORY-01 | Agent 编排器骨架 | M1 | — | W1 | P0 | 无 |
| STORY-02 | feature-parser Skill | M1 | R1 | W1 | P0 | 无 |
| STORY-03 | scenario-discovery Skill | M1 | R2, R17 | W1 | P0 | 无 |
| STORY-04 | m-analyzer Skill | M1 | R3 | W2 | P0 | STORY-02 |
| STORY-05 | Excel 批注读写工具 | M2 | R4, R7 | W1 | P0 | 无 |
| STORY-06 | f-analyzer Skill | M2 | R4~R8 | W2 | P0 | STORY-05 |
| STORY-07 | q-analyzer Skill | M1 | R9 | W2 | P0 | STORY-04 |
| STORY-08 | test-point-integrator Skill | M1 | R10 | W2 | P0 | STORY-04, STORY-06, STORY-07 |
| STORY-09 | design-planner Skill | M1 | R11 | W2 | P0 | STORY-08 |
| STORY-10 | data-combination-design Skill | M3 | R12 | W3 | P0 | STORY-09 |
| STORY-11 | flowchart-design Skill | M3 | R13 | W3 | P0 | STORY-09 |
| STORY-12 | state-diagram-design Skill | M3 | R14 | W3 | P0 | STORY-09 |
| STORY-13 | coverage-verifier Skill | M4 | R15 | W3 | P0 | STORY-10, STORY-11, STORY-12 |
| STORY-14 | deliverable-renderer Skill | M4 | R16 | W3 | P0 | STORY-13 |
| STORY-15 | change-impact-analyzer Skill | M6 | R19 | W4 | P1 | STORY-08, STORY-14 |
| STORY-16 | bug-gap-analyzer Skill | M6 | R20 | W4 | P1 | STORY-13, STORY-14 |

> **说明**：R6（代码依赖分析）为 P2 优先级，首版由 f-analyzer 内置手动输入接口，不单独拆 Story。R17（MCP 查询）首版由 scenario-discovery 内置 Web 搜索回退，MCP 客户端在 STORY-03 中预留接口。R18（跨平台安装包）由 meta-qa 在 verification 阶段统一执行，不单独拆 Story。

---

## Story 详情

### STORY-01: Agent 编排器骨架

**里程碑**：M1 | **Wave**：W1 | **优先级**：P0

**目标**：创建 `mfq-test-designer` Agent 的主提示词文件，包含状态机定义、Skill 触发词表、用户交互协议和运行时目录初始化逻辑。

**输入**：
- SOLUTION-DESIGN.md（架构决策、状态机流程）
- PLATFORM-INSTALL-SPEC.md（各平台 Agent 格式要求）

**输出文件**：
- `.agents/agents/mfq-test-designer.md`（核心 Agent 提示词）
- 三平台适配版本的 Agent 入口文件（后续 STORY 填充 Skill 内容时同步更新）

**任务清单**：
- [ ] TASK-01-01: 编写 Agent frontmatter（name, description, tools）
- [ ] TASK-01-02: 编写 10 步状态机定义（input→scenario→M→F→Q→integration→plan→design→coverage→delivery）
- [ ] TASK-01-03: 编写变更/问题单扩展分支定义
- [ ] TASK-01-04: 编写 14 Skill 触发词映射表
- [ ] TASK-01-05: 编写 `.mfq-work/` 运行时目录初始化逻辑
- [ ] TASK-01-06: 编写用户确认点协议（场景确认、目录确认、方法确认、覆盖确认）

**完成准则**：
- [ ] Agent 提示词文件语法正确（YAML frontmatter + Markdown 正文）
- [ ] 状态机包含 10 个主流程状态 + 2 个扩展分支
- [ ] 14 个 Skill 触发词均在映射表中注册
- [ ] `.mfq-work/` 初始化逻辑可被 Agent 调用

---

### STORY-02: feature-parser Skill

**里程碑**：M1 | **Wave**：W1 | **优先级**：P0

**目标**：实现特性需求文件解析能力，从多种格式的输入文件中提取结构化需求条目，构建三~五级目录结构。

**输入**：
- 特性需求文件（Markdown/Word/Excel/PDF）
- file-to-markdown Skill（已有，用于格式转换）

**输出文件**：
- `.agents/skills/feature-parser/SKILL.md`

**任务清单**：
- [ ] TASK-02-01: 编写 SKILL.md frontmatter 和执行约束
- [ ] TASK-02-02: 实现需求字段提取逻辑（编号/所属模块/SR名称/描述）
- [ ] TASK-02-03: 实现三级→四级→五级目录结构构建规则
- [ ] TASK-02-04: 实现与用户交互确认目录结构的提示词
- [ ] TASK-02-05: 定义输出格式（`.mfq-work/feature-input/`）

**完成准则**：
- [ ] 能解析参考文档中的测试点分析表格式
- [ ] 输出的目录结构包含三级（特性）、四级（模块）、五级（子模块）
- [ ] 用户确认步骤已定义

---

### STORY-03: scenario-discovery Skill

**里程碑**：M1 | **Wave**：W1 | **优先级**：P0

**目标**：实现特性应用场景分析能力，通过搜索获取典型场景，与用户交互式对齐。

**输入**：
- 特性名称和基本描述
- MCP 查询接口契约（预留）

**输出文件**：
- `.agents/skills/scenario-discovery/SKILL.md`
- `scripts/mcp_query_client.py`（接口框架）

**任务清单**：
- [ ] TASK-03-01: 编写 SKILL.md，定义场景发现流程
- [ ] TASK-03-02: 实现 Web 搜索回退逻辑
- [ ] TASK-03-03: 实现交互式场景确认提示词
- [ ] TASK-03-04: 编写 `mcp_query_client.py` 接口框架（首版仅定义查询契约）
- [ ] TASK-03-05: 定义输出格式（`.mfq-work/scenarios/confirmed-scenarios.md`）

**完成准则**：
- [ ] 能通过 Web 搜索获取华为防火墙特性的典型场景
- [ ] 场景包含触发条件、处理逻辑、异常路径
- [ ] MCP 查询接口已预留

---

### STORY-04: m-analyzer Skill

**里程碑**：M1 | **Wave**：W2 | **优先级**：P0 | **依赖**：STORY-02

**目标**：实现 M 分析（模块/功能点分析），按目录拆分功能点并生成测试点。

**输出文件**：
- `.agents/skills/m-analyzer/SKILL.md`

**任务清单**：
- [ ] TASK-04-01: 编写 SKILL.md，定义 M 分析流程
- [ ] TASK-04-02: 实现按四/五级目录逐模块分析功能点的提示词
- [ ] TASK-04-03: 实现测试点生成规则（覆盖需求 + 场景）
- [ ] TASK-04-04: 实现测试点标注（模块、关联需求 ID、来源）
- [ ] TASK-04-05: 定义输出格式（`.mfq-work/m-analysis/test-points.md`）

**完成准则**：
- [ ] 每个功能点下至少生成 1 个测试点
- [ ] 测试点标注完整（模块/需求 ID/来源）
- [ ] 需求覆盖率检查逻辑已定义

---

### STORY-05: Excel 批注读写工具

**里程碑**：M2 | **Wave**：W1 | **优先级**：P0

**目标**：实现耦合矩阵 Excel 文件的批注（comments）读取和写入能力。

**输出文件**：
- `scripts/excel_coupling_tool.py`

**任务清单**：
- [ ] TASK-05-01: 实现 openpyxl 读取批注（首选路径）
- [ ] TASK-05-02: 实现 zipfile + comments.xml 读取批注（回退路径）
- [ ] TASK-05-03: 实现批注语义过滤器（区分耦合描述 vs 审批备注/元数据）
- [ ] TASK-05-04: 实现批注写入（新增耦合点回写）
- [ ] TASK-05-05: 实现 CLI 接口（`--read`、`--write`、`--filter`）
- [ ] TASK-05-06: 测试覆盖：用参考矩阵（522 条批注）验证读取准确性

**完成准则**：
- [ ] 能正确读取参考矩阵中的有效耦合批注
- [ ] 语义过滤器误判率 < 10%
- [ ] 回写后 Excel 文件可用 Excel 正常打开

---

### STORY-06: f-analyzer Skill

**里程碑**：M2 | **Wave**：W2 | **优先级**：P0 | **依赖**：STORY-05

**目标**：实现 F 分析（耦合分析），三源合并 + 内存图模型 + 候选点确认。

**输出文件**：
- `.agents/skills/f-analyzer/SKILL.md`

**任务清单**：
- [ ] TASK-06-01: 编写 SKILL.md，定义 F 分析三阶段流程
- [ ] TASK-06-02: 实现矩阵基线读取逻辑（调用 excel_coupling_tool.py）
- [ ] TASK-06-03: 实现场景耦合推理逻辑
- [ ] TASK-06-04: 实现代码依赖手动输入接口（R6 的 P2 简化版）
- [ ] TASK-06-05: 实现内存图模型构建（nodes + edges + YAML 序列化）
- [ ] TASK-06-06: 实现候选耦合点生成与用户确认交互
- [ ] TASK-06-07: 实现确认后回写 Excel 逻辑

**完成准则**：
- [ ] 三源数据可独立或组合输入
- [ ] 图模型支持按功能点查询直接耦合点
- [ ] 候选耦合点呈现给用户确认后纳入分析结果

---

### STORY-07: q-analyzer Skill

**里程碑**：M1 | **Wave**：W2 | **优先级**：P0 | **依赖**：STORY-04

**目标**：实现 Q 分析（质量属性分析），参考 HTSM 维度评估相关性并生成测试点。

**输出文件**：
- `.agents/skills/q-analyzer/SKILL.md`

**任务清单**：
- [ ] TASK-07-01: 编写 SKILL.md，定义 Q 分析流程
- [ ] TASK-07-02: 实现 HTSM 维度列表（功能性/安全性/可靠性/性能/可安装性/兼容性/可维护性等）
- [ ] TASK-07-03: 实现相关性评估规则（仅相关维度展开分析）
- [ ] TASK-07-04: 实现质量属性测试点生成
- [ ] TASK-07-05: 定义输出格式（`.mfq-work/q-analysis/quality-test-points.md`）

**完成准则**：
- [ ] HTSM 维度覆盖参考文档的分析表
- [ ] 非相关维度不生成测试点
- [ ] 每个相关维度至少 1 个测试点

---

### STORY-08: test-point-integrator Skill

**里程碑**：M1 | **Wave**：W2 | **优先级**：P0 | **依赖**：STORY-04, STORY-06, STORY-07

**目标**：实现 M+F+Q 测试点归集、覆盖检查和逻辑用例合并。

**输出文件**：
- `.agents/skills/test-point-integrator/SKILL.md`

**任务清单**：
- [ ] TASK-08-01: 编写 SKILL.md，定义整合流程
- [ ] TASK-08-02: 实现按模块归集 M+F+Q 测试点
- [ ] TASK-08-03: 实现需求覆盖完整性检查
- [ ] TASK-08-04: 实现相同测试逻辑识别与合并规则
- [ ] TASK-08-05: 实现测试数据分配逻辑
- [ ] TASK-08-06: 定义输出格式（逻辑用例列表 + 测试数据）

**完成准则**：
- [ ] 所有需求描述的功能被至少 1 个测试点覆盖
- [ ] 合并后的逻辑用例无重复测试逻辑
- [ ] 每个逻辑用例关联明确的测试数据集

---

### STORY-09: design-planner Skill

**里程碑**：M1 | **Wave**：W2 | **优先级**：P0 | **依赖**：STORY-08

**目标**：实现设计方法推荐和设计计划生成。

**输出文件**：
- `.agents/skills/design-planner/SKILL.md`

**任务清单**：
- [ ] TASK-09-01: 编写 SKILL.md，定义设计计划生成流程
- [ ] TASK-09-02: 实现方法推荐规则（CF-04: I/O→数据组合, 分支→流程图, 状态→状态图）
- [ ] TASK-09-03: 实现设计计划表格式（逻辑用例 ID / 推荐方法 / 理由）
- [ ] TASK-09-04: 实现与用户交互确认的提示词

**完成准则**：
- [ ] 每条逻辑用例标注推荐方法
- [ ] 方法选择符合 CF-04 规则
- [ ] 用户可修改推荐方法

---

### STORY-10: data-combination-design Skill

**里程碑**：M3 | **Wave**：W3 | **优先级**：P0 | **依赖**：STORY-09

**目标**：实现数据组合法的四步用例设计过程。

**输出文件**：
- `.agents/skills/data-combination-design/SKILL.md`

**任务清单**：
- [ ] TASK-10-01: 编写 SKILL.md，定义四步设计流程
- [ ] TASK-10-02: 实现步骤 1 — 等价类划分表（测试数据/有效类/无效类/选取策略/选取结果）
- [ ] TASK-10-03: 实现步骤 2 — 数据组合分析表（数据/取值/组合分析/约束/策略/结果）
- [ ] TASK-10-04: 实现步骤 3 — 逻辑用例设计
- [ ] TASK-10-05: 实现步骤 4 — 物理用例设计（含优先级 P0~P4 + 测试类型）
- [ ] TASK-10-06: 实现组合爆炸检测和 pairwise 压缩策略

**完成准则**：
- [ ] 四步产出物格式符合参考文档
- [ ] 物理用例包含优先级和测试类型字段
- [ ] 组合数过大时自动建议压缩策略

---

### STORY-11: flowchart-design Skill

**里程碑**：M3 | **Wave**：W3 | **优先级**：P0 | **依赖**：STORY-09

**目标**：实现流程图法的四步用例设计过程。

**输出文件**：
- `.agents/skills/flowchart-design/SKILL.md`

**任务清单**：
- [ ] TASK-11-01: 编写 SKILL.md，定义四步设计流程
- [ ] TASK-11-02: 实现步骤 1 — 流程图建模（Mermaid flowchart 语法）
- [ ] TASK-11-03: 实现步骤 2 — 路径枚举与分支覆盖表
- [ ] TASK-11-04: 实现步骤 3 — 路径数据分配
- [ ] TASK-11-05: 实现步骤 4 — 物理用例设计
- [ ] TASK-11-06: 实现流程过于复杂时的子流程拆分建议

**完成准则**：
- [ ] 流程图使用 Mermaid flowchart 语法，可渲染
- [ ] 路径枚举覆盖所有判断分支
- [ ] 物理用例包含优先级和测试类型字段

---

### STORY-12: state-diagram-design Skill

**里程碑**：M3 | **Wave**：W3 | **优先级**：P0 | **依赖**：STORY-09

**目标**：实现状态图法的四步用例设计过程。

**输出文件**：
- `.agents/skills/state-diagram-design/SKILL.md`

**任务清单**：
- [ ] TASK-12-01: 编写 SKILL.md，定义四步设计流程
- [ ] TASK-12-02: 实现步骤 1 — 状态图建模（Mermaid stateDiagram 语法）
- [ ] TASK-12-03: 实现步骤 2 — 状态转换表（当前状态/事件/目标/守卫条件）
- [ ] TASK-12-04: 实现步骤 3 — 迁移路径数据分配
- [ ] TASK-12-05: 实现步骤 4 — 物理用例设计
- [ ] TASK-12-06: 实现非法状态转换的负面测试路径生成

**完成准则**：
- [ ] 状态图使用 Mermaid stateDiagram 语法，可渲染
- [ ] 状态转换表覆盖所有合法迁移
- [ ] 包含非法转换的负面测试用例

---

### STORY-13: coverage-verifier Skill

**里程碑**：M4 | **Wave**：W3 | **优先级**：P0 | **依赖**：STORY-10, STORY-11, STORY-12

**目标**：实现双层覆盖率检查。

**输出文件**：
- `.agents/skills/coverage-verifier/SKILL.md`

**任务清单**：
- [ ] TASK-13-01: 编写 SKILL.md，定义覆盖检查流程
- [ ] TASK-13-02: 实现需求层覆盖检查（SR→TP→LC+TD 逐条验证）
- [ ] TASK-13-03: 实现测试点层覆盖检查（TP→PC 逐条验证）
- [ ] TASK-13-04: 实现覆盖率报告生成
- [ ] TASK-13-05: 实现未覆盖项补充建议生成

**完成准则**：
- [ ] 双层检查完整执行
- [ ] 覆盖率报告格式清晰，标注每个未覆盖项
- [ ] 未覆盖项自动建议补充方向

---

### STORY-14: deliverable-renderer Skill

**里程碑**：M4 | **Wave**：W3 | **优先级**：P0 | **依赖**：STORY-13

**目标**：实现测试方案和测试用例 Markdown 文件生成。

**输出文件**：
- `.agents/skills/deliverable-renderer/SKILL.md`

**任务清单**：
- [ ] TASK-14-01: 编写 SKILL.md，定义交付物生成流程
- [ ] TASK-14-02: 实现 `xx特性测试方案.md` 模板渲染（特性概述/场景/需求/MFQ/整合）
- [ ] TASK-14-03: 实现 `xx特性测试用例.md` 模板渲染（测试点表 + 按五级目录组织的设计过程）
- [ ] TASK-14-04: 实现五级目录结构到 Markdown heading 的映射

**完成准则**：
- [ ] 输出的两个 Markdown 文件结构与参考文档一致
- [ ] 包含完整的四步设计过程
- [ ] 物理用例含优先级和测试类型字段

---

### STORY-15: change-impact-analyzer Skill

**里程碑**：M6 | **Wave**：W4 | **优先级**：P1 | **依赖**：STORY-08, STORY-14

**目标**：实现需求变更影响分析与用例增量更新。

**输出文件**：
- `.agents/skills/change-impact-analyzer/SKILL.md`

**任务清单**：
- [ ] TASK-15-01: 编写 SKILL.md，定义变更分析流程
- [ ] TASK-15-02: 实现变更需求解析与受影响模块识别
- [ ] TASK-15-03: 实现增量 MFQ 分析（仅受影响部分）
- [ ] TASK-15-04: 实现增量用例设计触发
- [ ] TASK-15-05: 实现不可变保护（不修改未受影响用例）
- [ ] TASK-15-06: 实现增量覆盖验证

**完成准则**：
- [ ] 受影响模块清单与变更描述一致
- [ ] 未受影响的用例文件未被修改
- [ ] 增量覆盖率 = 100%

---

### STORY-16: bug-gap-analyzer Skill

**里程碑**：M6 | **Wave**：W4 | **优先级**：P1 | **依赖**：STORY-13, STORY-14

**目标**：实现问题单覆盖盲区分析与用例补充。

**输出文件**：
- `.agents/skills/bug-gap-analyzer/SKILL.md`

**任务清单**：
- [ ] TASK-16-01: 编写 SKILL.md，定义问题单分析流程
- [ ] TASK-16-02: 实现问题单→模块定位逻辑
- [ ] TASK-16-03: 实现覆盖盲区检测（反向追踪 PC→LC→TP→SR）
- [ ] TASK-16-04: 实现遗漏环节定位（M/F/Q/整合/设计 哪个阶段遗漏）
- [ ] TASK-16-05: 实现用例补充逻辑
- [ ] TASK-16-06: 实现流程优化建议生成

**完成准则**：
- [ ] 每条问题单标注覆盖状态和遗漏环节
- [ ] 补充的用例仅涉及缺失部分
- [ ] 流程优化建议可操作
