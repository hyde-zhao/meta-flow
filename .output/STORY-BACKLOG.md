---
status: confirmed
version: "2.0"
total_stories: 18
total_waves: 4
created_by: "meta-se"
created_at: "2026-04-10T02:50:00Z"
change_request: "CR-001"
confirmed_by: "user (auto-approved)"
confirmed_at: "2026-04-10T02:50:00Z"
---

# Story Backlog v2 — MFQ&PPDCS 测试用例设计工具

> 基于 CR-001（PPDCS 理论体系集成）更新。
> 产物：1 Agent（`mfq-test-designer`）+ 16 Skill + 2~3 Python 工具

---

## Story 总览

| Story ID | 标题 | 里程碑 | 需求 | Wave | 优先级 | 依赖 | v1→v2 |
|----------|------|--------|------|------|--------|------|-------|
| STORY-01 | Agent 编排器骨架 (v2: 12步状态机) | M1 | — | W1 | P0 | 无 | **修改** |
| STORY-02 | feature-parser Skill | M1 | R1 | W1 | P0 | 无 | 不变 |
| STORY-03 | scenario-discovery Skill | M1 | R2, R17 | W1 | P0 | 无 | 不变 |
| STORY-04 | m-analyzer Skill (v2: +PPDCS标注) | M1 | R3 | W2 | P0 | STORY-02 | **增强** |
| STORY-05 | Excel 批注读写工具 | M2 | R4, R7 | W1 | P0 | 无 | 不变 |
| STORY-06 | f-analyzer Skill | M2 | R4~R8 | W2 | P0 | STORY-05 | 不变 |
| STORY-07 | q-analyzer Skill | M1 | R9 | W2 | P0 | STORY-04 | 不变 |
| STORY-08 | test-point-integrator Skill | M1 | R10 | W2 | P0 | STORY-04,06,07 | 不变 |
| STORY-09 | design-planner Skill (v2: PPDCS匹配) | M1 | R11 | W2 | P0 | STORY-08 | **增强** |
| STORY-10 | combination-design Skill | M3 | R12 | W3 | P0 | STORY-09 | **重构** |
| STORY-11 | process-design Skill | M3 | R13 | W3 | P0 | STORY-09 | **重命名** |
| STORY-12 | state-design Skill | M3 | R14 | W3 | P0 | STORY-09 | **重命名** |
| STORY-13 | coverage-verifier Skill | M4 | R15 | W3 | P0 | STORY-10~12,17,18 | 不变 |
| STORY-14 | deliverable-renderer Skill | M4 | R16 | W3 | P0 | STORY-13 | 不变 |
| STORY-15 | change-impact-analyzer Skill | M6 | R19 | W4 | P1 | STORY-08,14 | 不变 |
| STORY-16 | bug-gap-analyzer Skill | M6 | R20 | W4 | P1 | STORY-13,14 | 不变 |
| STORY-17 | parameter-design Skill | M3 | R12 | W3 | P0 | STORY-09 | **新增** |
| STORY-18 | data-design Skill | M3 | R12 | W3 | P0 | STORY-09 | **新增** |

---

## v2 变更 Story 详情

### STORY-01 (v2): Agent 编排器骨架 — 12 步状态机

**变更说明**：状态机从 10 步扩展为 12 步（步骤 3 增加 PPDCS 标注，步骤 7 增加 PPDCS 匹配）。Skill 映射表从 14→16。

**新增/修改任务**：
- [ ] TASK-01-02v2: 更新状态机为 12 步（input→scenario→m-analysis(PPDCS)→f→q→integration→plan(PPDCS)→design(5方法)→coverage→delivery）
- [ ] TASK-01-04v2: 更新 Skill 触发词映射表为 16 Skill（新增 parameter-design, data-design；重命名 process-design, state-design, combination-design）

**完成准则增量**：
- [ ] 状态机包含 12 个主流程状态
- [ ] 16 个 Skill 触发词均在映射表中注册

---

### STORY-04 (v2): m-analyzer Skill — PPDCS 特征标注

**变更说明**：在原有功能点拆分和测试点生成基础上，新增 PPDCS 特征标注能力。

**新增任务**：
- [ ] TASK-04-06: 实现 PPDCS 五特征识别规则（P-Process / P-Parameter / D-Data / C-Combination / S-State）
- [ ] TASK-04-07: 实现特征区分规则嵌入（Process vs State, Parameter vs Data, Data vs Combination）
- [ ] TASK-04-08: 实现 PPDCS 标注输出格式（`mfq/m-analysis/ppdcs-annotation.md`）
- [ ] TASK-04-09: 实现混合特征处理（主特征 + 辅特征标注）

**完成准则增量**：
- [ ] 每个五级目录节点（单功能）均有 PPDCS 主特征标注
- [ ] 混合特征情况标注主特征和辅特征
- [ ] 标注包含判定依据

---

### STORY-09 (v2): design-planner Skill — PPDCS 五特征匹配

**变更说明**：方法推荐规则从 3 种（数据组合/流程图/状态图）升级为 5 种 PPDCS 特征匹配。

**新增/修改任务**：
- [ ] TASK-09-02v2: 实现 PPDCS 五特征匹配规则：
  - S-State → state-design
  - P-Process → process-design
  - P-Parameter → parameter-design
  - C-Combination → combination-design
  - D-Data → data-design
  - 混合特征 → 主方法 + 辅方法
- [ ] TASK-09-05: 实现 PPDCS 标注读取（从 `mfq/m-analysis/ppdcs-annotation.md`）
- [ ] TASK-09-06: 实现设计计划表新增 PPDCS 特征列

**完成准则增量**：
- [ ] 设计计划表含 PPDCS 特征列
- [ ] 5 种 PPDCS 方法均可推荐
- [ ] 混合特征时推荐主方法+辅方法

---

### STORY-10 (v2): combination-design Skill（原 data-combination-design 重构）

**变更说明**：原 data-combination-design 聚焦 C-Combination 特征（Pairwise/正交阵列），D-Data（等价类+边界值）和 P-Parameter（判定表/因果图）拆出为独立 Skill。

**修改任务**：
- [ ] TASK-10-01v2: 重写 SKILL.md，专注 C-Combination 特征
- [ ] TASK-10-02v2: 实现步骤 1 — 因子-状态表构建（列出因子及其状态/取值）
- [ ] TASK-10-03v2: 实现步骤 2 — Pairwise 组合生成（可选 PICT 工具 / 手动构建）
- [ ] TASK-10-04v2: 实现步骤 3 — 组合→逻辑用例
- [ ] TASK-10-05v2: 实现步骤 4 — 物理用例（含 P0~P4 + 测试类型）
- [ ] TASK-10-06v2: 实现 PICT 可用性检测和手动回退

**完成准则**：
- [ ] 因子-状态表格式符合 PPDCS C-Combination 要求
- [ ] 支持 Pairwise 生成（PICT 或手动）
- [ ] 组合爆炸时自动压缩

---

### STORY-11 (v2): process-design Skill（原 flowchart-design 重命名）

**变更说明**：重命名以对齐 PPDCS P-Process 理论命名。内部逻辑不变。

**修改任务**：
- [ ] TASK-11-01v2: Skill 目录重命名 `flowchart-design` → `process-design`
- [ ] TASK-11-02v2: 更新 SKILL.md 描述，明确对齐 P-Process 特征

---

### STORY-12 (v2): state-design Skill（原 state-diagram-design 重命名）

**变更说明**：重命名以对齐 PPDCS S-State 理论命名。增强 Process vs State 的区分规则。

**修改任务**：
- [ ] TASK-12-01v2: Skill 目录重命名 `state-diagram-design` → `state-design`
- [ ] TASK-12-02v2: 更新 SKILL.md 描述，明确对齐 S-State 特征
- [ ] TASK-12-07v2: 增加 "State vs Process 区分提示"（状态能否双向转换？）

---

### STORY-17 (v2 新增): parameter-design Skill

**里程碑**：M3 | **Wave**：W3 | **优先级**：P0 | **依赖**：STORY-09

**目标**：实现 P-Parameter 特征的判定表/因果图用例设计方法。

**输出文件**：
- `skills/parameter-design/SKILL.md`

**任务清单**：
- [ ] TASK-17-01: 编写 SKILL.md，定义 P-Parameter 四步设计流程
- [ ] TASK-17-02: 实现步骤 1 — 判定表构建（条件/动作/规则矩阵）
  - 替代方案：因果图（适用于条件间有逻辑依赖时）
  - 替代方案：决策树（适用于条件层级嵌套时）
- [ ] TASK-17-03: 实现步骤 2 — 规则提取（从判定表中提取独立规则）
- [ ] TASK-17-04: 实现步骤 3 — 规则→逻辑用例
- [ ] TASK-17-05: 实现步骤 4 — 物理用例（含 P0~P4 + 测试类型）
- [ ] TASK-17-06: 实现判定表简化（合并冗余规则、识别"无关条件"）

**完成准则**：
- [ ] 判定表格式规范（条件桩/动作桩/条件项/动作项）
- [ ] 支持因果图到判定表的转换建议
- [ ] 物理用例含优先级和测试类型
- [ ] 首版以判定表为主，因果图和决策树作为高级选项

---

### STORY-18 (v2 新增): data-design Skill

**里程碑**：M3 | **Wave**：W3 | **优先级**：P0 | **依赖**：STORY-09

**目标**：实现 D-Data 特征的等价类划分 + 边界值分析用例设计方法。

**输出文件**：
- `skills/data-design/SKILL.md`

**任务清单**：
- [ ] TASK-18-01: 编写 SKILL.md，定义 D-Data 四步设计流程
- [ ] TASK-18-02: 实现步骤 1 — 等价类划分表（数据项/有效类/无效类/选取策略/预期结果）
- [ ] TASK-18-03: 实现步骤 2 — 边界值识别（上点/离点/内点三点法）
- [ ] TASK-18-04: 实现步骤 3 — 等价类+边界值→逻辑用例
- [ ] TASK-18-05: 实现步骤 4 — 物理用例（含 P0~P4 + 测试类型）
- [ ] TASK-18-06: 实现 "Data vs Combination" 区分提示（因子独立验证够吗？）

**完成准则**：
- [ ] 等价类划分包含有效类和无效类
- [ ] 边界值使用上点/离点/内点三点法
- [ ] 物理用例含优先级和测试类型

---

## Wave 执行计划（v2）

### Wave 1（基础框架）— 不变

| Story | 任务 | 状态 |
|-------|------|------|
| STORY-01 | Agent 骨架（v2: 12步） | 需更新 |
| STORY-02 | feature-parser | 已完成 |
| STORY-03 | scenario-discovery | 已完成 |
| STORY-05 | Excel 工具 | 已完成 |

### Wave 2（分析引擎）

| Story | 任务 | 状态 |
|-------|------|------|
| STORY-04 | m-analyzer（v2: +PPDCS） | 需增强 |
| STORY-06 | f-analyzer | 已完成 |
| STORY-07 | q-analyzer | 已完成 |
| STORY-08 | test-point-integrator | 已完成 |
| STORY-09 | design-planner（v2: PPDCS匹配） | 需增强 |

### Wave 3（设计引擎 + 集成）

| Story | 任务 | 状态 |
|-------|------|------|
| STORY-10 | combination-design（重构） | 需重构 |
| STORY-11 | process-design（重命名） | 需重命名 |
| STORY-12 | state-design（重命名） | 需重命名 |
| STORY-17 | parameter-design（新增） | 需新建 |
| STORY-18 | data-design（新增） | 需新建 |
| STORY-13 | coverage-verifier | 已完成 |
| STORY-14 | deliverable-renderer | 已完成 |

### Wave 4（变更管理）— 不变

| Story | 任务 | 状态 |
|-------|------|------|
| STORY-15 | change-impact-analyzer | 已完成 |
| STORY-16 | bug-gap-analyzer | 已完成 |

---

## v2 受影响 Story 总结

| 类型 | Story | 工作量评估 |
|------|-------|-----------|
| **需更新** | STORY-01 | 小 — 状态机+映射表修改 |
| **需增强** | STORY-04 | 中 — 新增 PPDCS 标注逻辑 |
| **需增强** | STORY-09 | 中 — 新增 5 特征匹配 |
| **需重构** | STORY-10 | 中 — 剥离等价类/判定表，专注 Pairwise |
| **需重命名** | STORY-11 | 小 — 目录+描述重命名 |
| **需重命名** | STORY-12 | 小 — 目录+描述重命名 |
| **新增** | STORY-17 | 中 — 判定表/因果图全新实现 |
| **新增** | STORY-18 | 中 — 等价类+边界值全新实现 |
| 不变 | 10 个 | — |
