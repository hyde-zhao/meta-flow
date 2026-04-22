---
generated_by: meta-se / awesome-copilot-analysis
generated_at: 2026-04-22T15:44:00+08:00
project: use-case-discovery-skill
source_repo: https://github.com/github/awesome-copilot
requirements_version: draft（基于用户直接请求，无正式 REQUIREMENTS.md）
status: ready
---

# Awesome-Copilot 资源借鉴分析报告

> 针对目标产物：`use-case-discovery` Skill（产品经理与用户讨论用户场景的结构化 Skill）

## 项目特征摘要

- **技术栈**：Markdown Skill（SKILL.md 指令）+ 私有模板，无代码运行时
- **领域关键词**：use-case discovery、product requirements、user story、scenario、PM、interview、brainstorming
- **质量目标**：场景覆盖完整性、输出格式与 meta-pm 兼容、可重复执行
- **集成需求**：与 meta-pm.md / requirement-extraction / requirement-clarifier 集成
- **Agent/Skill 需求**：对话驱动、多轮确认、结构化输出、维度扫描框架

---

## 一、Agents 分析

### 可直接借鉴

| Agent | 本地路径 | GitHub 链接 | 核心功能 | 优点 | 缺点/局限 | 借鉴内容 |
|-------|---------|-----------|---------|------|----------|---------|
| `prd.agent.md` | `.input/agents/prd.agent.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/agents/prd.agent.md) | 多轮澄清 + PRD 生成，Ask 3-5 clarifying questions before writing | 明确"先问后写"原则；user stories 覆盖 primary / alternative / edge cases；Final Checklist 模式 | 面向 PRD 而非 USE-CASES；澄清问题无分级（BLOCKING/REQUIRED）| **先问后写框架**（3-5 问）；**edge case 覆盖原则**；**Final Checklist** 确认机制 |
| `se-product-manager-advisor.agent.md` | `.input/agents/se-product-manager-advisor.agent.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/agents/se-product-manager-advisor.agent.md) | PM 三问框架（Who / What problem / How to measure） | 三问框架极度精炼可操作；成功指标问法"What's the target? (50% faster, 90% of users)" 量化具体；Hypothesis-Driven Development 作为探索补充 | 面向 GitHub Issues 创建，不输出 USE-CASES 格式 | **PM 三问框架**（谁用 / 什么问题 / 如何量化）完整融入 Phase 1 开场；量化成功指标问法 |

### 需适配后借鉴

| Agent | 本地路径 | 核心功能 | 适配说明 |
|-------|---------|---------|---------|
| `specification.agent.md` | `.input/agents/specification.agent.md` | 生成 AI-ready 规范文档（Given-When-Then AC、自包含、机器可读）| 其 AC 格式（Given/When/Then）可直接移植为 Phase 3 USE-CASES.md 验收条件字段的写法规范 |
| `blueprint-mode.agent.md` | `.input/agents/blueprint-mode.agent.md` | 置信度驱动的执行策略（>90% 继续 / <90% 追问一问）| 可借鉴"置信度 <90 时停下来追问"机制，作为 Phase 2 维度扫描中"是否需要追问"的判定逻辑 |

### 不适用（跳过原因）

> `context-architect.agent.md`：面向代码变更的文件依赖分析，与场景发现无关。
> `prd.agent.md`（部分）：GitHub Issues 创建部分与本 Skill 场景无关，只借鉴对话框架。

---

## 二、Skills 分析

### 可直接借鉴

| Skill 目录 | 本地路径 | GitHub 链接 | 核心功能 | 优点 | 缺点/局限 | 借鉴内容 |
|-----------|---------|-----------|---------|------|----------|---------|
| `prd` | `.input/skills/prd/SKILL.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/skills/prd/SKILL.md) | 三阶段 PRD 工作流：Discovery（Interview）→ Analysis & Scoping → Technical Drafting | "Discovery = Interview" 明确定义；"never skip 2 clarifying questions"；Quality Standards 强调可量化而非模糊 | Phase 3 输出面向 PRD 而非 USE-CASES | **三阶段框架命名和分工**（发现 → 分析 → 输出）；**"never skip Discovery"** 规则作为 Gotcha；可量化验收标准的写法 |
| `breakdown-epic-pm` | `.input/skills/breakdown-epic-pm/SKILL.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/skills/breakdown-epic-pm/SKILL.md) | Epic PRD：用户画像 + 高层用户旅程 + 成功指标 + Out of Scope | User Journeys 章节按"用户旅程 + 工作流"描述，兼顾了用户时间维度的场景 | 面向 Epic 级别，颗粒度偏粗 | **"High-Level User Journeys"** 章节结构可作为时间维度（D4）发现问题的模板；**Business Value 评级**（H/M/L）可作为可选成功指标 |
| `breakdown-feature-prd` | `.input/skills/breakdown-feature-prd/SKILL.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/skills/breakdown-feature-prd/SKILL.md) | Feature PRD：User Stories (As a / I want / So that) + Given/When/Then AC + Out of Scope | User Story 格式标准、可追溯；Given/When/Then 与 meta-pm.md 验收条件格式高度一致 | 无多维度覆盖扫描 | **User Story 格式**（As a / I want / So that）作为 Phase 3 场景描述补充；**Given/When/Then** 作为"前置条件-触发-输出"的规范化写法 |

### 需适配后借鉴

| Skill 目录 | 本地路径 | 适配说明 |
|-----------|---------|---------|
| `dataverse-python-usecase-builder` | `.input/skills/dataverse-python-usecase-builder/SKILL.md` | 其 "Phase 1: Requirement Analysis" 六问（What operations / How much data / Frequency / Performance / Error tolerance / Audit）是**领域特定**的维度扫描示例；可作为 D8 集成维度的追问参考模式，但不直接移植 |

---

## 三、Workflows 分析

| Workflow | 本地路径 | 核心功能 | 借鉴判断 | 借鉴内容/适配说明 |
|---------|---------|---------|---------|----------------|
| `relevance-check.md` | `.input/workflows/relevance-check.md` | 内容相关性判断工作流 | 不适用 | 面向内容分类，与场景发现无关 |
| 其余 6 个 | `.input/workflows/` | OSPO 治理类工作流 | 不适用 | 面向组织管理，与本 Skill 无关 |

---

## 四、Hooks 分析

| Hook | 借鉴判断 | 说明 |
|------|---------|------|
| `secrets-scanner` | 不适用 | 纯文本对话 Skill，无代码产出，无密钥风险 |
| `dependency-license-checker` | 不适用 | 无外部依赖 |
| `session-logger` | 仅参考 | 多轮会话记录思路可作为 CLARIFICATION-LOG.md 追加机制的参考 |

---

## 五、Instructions 分析

| Instruction 文件 | 本地路径 | 相关性 | 借鉴判断 | 借鉴内容 |
|----------------|---------|-------|---------|---------|
| `agent-skills.instructions.md` | `.input/instructions/agent-skills.instructions.md` | **高** | **直接借鉴** | 见下方详述 |
| `spec-driven-workflow-v1.instructions.md` | `.input/instructions/spec-driven-workflow-v1.instructions.md` | **高** | 需适配借鉴 | EARS 需求格式；置信度打分机制 |
| `context-engineering.instructions.md` | `.input/instructions/context-engineering.instructions.md` | 中 | 仅参考 | SKILL.md 描述字段设计的上下文管理原则 |
| `agents.instructions.md` | `.input/instructions/agents.instructions.md` | 中 | 仅参考 | Agent frontmatter 规范（与本项目已有 SKILL 规范对比） |

### `agent-skills.instructions.md` 关键发现（高相关，直接影响 HLD）

这是本次分析最重要的资源，对 `use-case-discovery` Skill 的设计有**结构性影响**：

**① description 字段是唯一自动激活机制**
> "Copilot reads ONLY the `name` and `description` to decide whether to load a skill."
> "If your description is vague, the skill will never be activated."

→ 影响：SKILL.md 的 `description` 字段必须同时包含 WHAT + WHEN + KEYWORDS，不能写"进行场景发现"这类模糊描述。

**② 500 行硬性上限 + 5 步以上流程须拆 `references/`**
> "SKILL.md body under 500 lines (consider splitting into `references/` at ~200 lines; 500 is the hard maximum)"
> "Large workflows (>5 steps) split into `references/` folder"

→ 影响：8 维度扫描框架（8 个维度 × 追问示例）篇幅超过 5 步，**必须拆入 `references/8-dimensions-framework.md`**，而不是内嵌在 SKILL.md。这**直接改变了 HLD 中的产物形态**。

**③ 渐进式加载三层架构**
> Level 1: description（总是加载）→ Level 2: SKILL.md body（匹配后加载）→ Level 3: references/scripts/templates（引用时才加载）

→ 影响：SKILL.md 主体保持精简（描述三阶段框架 + 核心规则），8 维框架和 USE-CASES 模板放 Level 3，需要时才消耗 context。

**④ Gotchas 是最高价值内容**
> "The `## Gotchas` section is consistently the most valuable part of any skill"

→ 影响：Skill 设计必须包含实质性 Gotchas，而不是形式性填充。

---

## 六、Plugins 分析

| Plugin 目录 | 相关性 | 说明 |
|-----------|-------|------|
| `context-engineering` | 低 | 面向 IDE 上下文工程，不直接适用 |
| 其余 | 低/不适用 | 面向前端开发、云服务、DevOps，与本 Skill 无关 |

---

## 七、综合借鉴建议

### 7.1 直接引入清单（meta-dev 在实现 Skill 时直接使用）

| 资源路径 | 类型 | 引入方式 | 目标消费方 |
|---------|------|---------|---------|
| `.input/agents/se-product-manager-advisor.agent.md` § Step 1 | Agent 片段 | 将 PM 三问框架（Who / What problem / How to measure）内嵌为 Phase 1 开场追问模板 | meta-dev（实现 SKILL.md Phase 1）|
| `.input/skills/prd/SKILL.md` § Phase 1 Discovery | Skill 章节 | "Discovery = Interview，先问后写，3个核心问题" 作为 Phase 1 的指导原则 | meta-dev（实现 SKILL.md）|
| `.input/instructions/agent-skills.instructions.md` § 全文 | Instruction | 约束 SKILL.md 的 description 写法、行数上限（500）、references/ 拆分规则 | meta-dev（实现所有 SKILL.md 章节）|
| `.input/skills/breakdown-feature-prd/SKILL.md` § User Stories + AC | Skill 章节 | Given/When/Then 格式作为 Phase 3 输出模板中"前置条件-触发-结果"字段的规范化写法 | meta-dev（实现 USE-CASES-TEMPLATE.md）|

### 7.2 适配引入清单

| 资源路径 | 类型 | 适配要点 | 目标消费方 |
|---------|------|---------|---------|
| `.input/instructions/spec-driven-workflow-v1.instructions.md` § EARS Notation | Instruction 片段 | EARS 格式 `WHEN [condition] THE SYSTEM SHALL [behavior]` 适配为 USE-CASES.md 中"处理逻辑"字段的推荐写法（非强制）| meta-dev（实现 USE-CASES-TEMPLATE.md）|
| `.input/agents/blueprint-mode.agent.md` § Persistence / Confidence | Agent 片段 | 置信度机制简化为：Phase 2 维度扫描中"用户连续 3 次回答无遗漏"时跳出 → 隐式置信度判定 | meta-dev（实现 SKILL.md Phase 2 退出逻辑）|
| `.input/skills/breakdown-epic-pm/SKILL.md` § High-Level User Journeys | Skill 章节 | "旅程维度"（首次/日常/偶发/停用）适配为 8 维框架的 D4 时间维度的具体问法 | meta-dev（实现 `references/8-dimensions-framework.md`）|

### 7.3 HLD 直接引用的架构模式 / 技术约束

- **架构模式**：`prd/SKILL.md` → 三阶段管道（Discovery → Analysis → Output）命名与分工可直接对应 Phase 1/2/3
- **Skill 形态约束**：`agent-skills.instructions.md` → SKILL.md 主体 ≤ 500 行；5 步以上流程拆 `references/`；描述字段 WHAT+WHEN+KEYWORDS
- **对话框架**：`se-product-manager-advisor.agent.md` → PM 三问作为 Phase 1 的标准化开场
- **输出格式**：`breakdown-feature-prd/SKILL.md` → Given/When/Then 格式对齐 meta-pm.md 验收条件规范

### 7.4 对 ARCHITECTURE-DECISION.md 的影响

| 决策点 | 来源资源 | 推荐决策 | 理由 |
|-------|---------|---------|------|
| 8 维度框架放在 SKILL.md 内嵌还是 `references/` | `agent-skills.instructions.md` §500-line limit | **必须放 `references/8-dimensions-framework.md`**（原 HLD ADR-2 结论需要修改）| 8 维框架 × 追问示例 + 案例约 150 行，加上 SKILL.md 主体易超 500 行上限；且框架是"按需引用"资源，符合 Level 3 加载场景 |
| USE-CASES-TEMPLATE.md 是否需要 | `breakdown-feature-prd/SKILL.md` | 保留，且明确模板包含 Given/When/Then 的处理逻辑字段规范化写法 | 模板是 Level 3 资源（templates/），与 SKILL.md 主体解耦 |
| description 字段写法 | `agent-skills.instructions.md` §description best practices | 使用 WHAT+WHEN+KEYWORDS 三段式，包含"场景发现、使用场景讨论、use-case-workshop"等触发词 | description 是唯一自动激活机制，模糊描述导致 Skill 永远不被加载 |

---

## 八、遗留问题

| 问题 | 影响 | 建议操作 |
|------|------|---------|
| `.input/skills/copilot-instructions-blueprint-generator/SKILL.md` 超 36KB 未完整读取 | 低（该 Skill 面向 copilot-instructions 生成，与本 Skill 关联度中） | 可在 LLD 阶段按需补充读取 |
| awesome-copilot 中无直接对应"多维场景发现"或"USE-CASES 生成"的 Skill | 中（验证了本 Skill 的创新价值，无直接参考实现）| 从 PRD/Specification 类资源中间接借鉴，本 Skill 是该领域填补空白 |

---

## 九、设计评审补充发现（2026-04-22）

> 以下发现不是对 awesome-copilot 资源本身的新分析，而是将本报告与**当前仓库真实契约**对照后的补充结论，用于校正 HLD 假设。

| 发现 | 当前仓库事实 | 对 HLD / 落地计划的影响 |
|------|-------------|------------------------|
| `requirement-extraction` 当前**未**声明 `USE-CASES.md` 为兼容输入 | `skills/requirement-extraction/SKILL.md` 的必须读取输入仅包含自然语言需求、`REQUEST.md`、`input_spec.yaml` 与目标平台/约束线索 | HLD 不能假设下游已天然兼容 `USE-CASES.md`；必须把 `requirement-extraction` 契约改造纳入落地范围，确保场景 → 需求链路通过正式工件交接 |
| meta-pm 当前默认读取 `INPUT-INDEX.md` 与已有 `USE-CASES.md` | `agents/meta-pm.md` 默认加载内容包含 `process/INPUT-INDEX.md` 与 `process/USE-CASES.md` | HLD 的输入契约需要显式纳入这两个工件，否则导入模式与草稿恢复路径只停留在概念层，不符合现有 Agent 行为 |
| 触发词 / 描述存在与相邻 Skill 冲突的现实风险 | `scenario-expansion` 已占用"展开场景 / 测试场景 / 场景扩展"，`requirement-clarifier` 已占用"澄清需求 / 需求歧义"语义 | `use-case-discovery` 的 `description` 与 README 边界说明必须显式排除上述语义，避免自动激活命中错误 Skill |
