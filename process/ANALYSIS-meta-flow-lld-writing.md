---
generated_by: meta-se / awesome-copilot-analysis
generated_at: 2026-04-23T09:11:09+08:00
project: meta-flow
source_repo: https://github.com/github/awesome-copilot
requirements_version: draft（当前仓库缺少已确认的 REQUIREMENTS.md / USE-CASES.md，本报告基于 README.md、process/HLD.md 与当前用户主题）
status: partial
analysis_topic: lld-writing
---

# ANALYSIS：Awesome-Copilot 资源借鉴分析报告（主题：LLD 写作）

## 项目特征摘要

- **技术栈**：Markdown 驱动的 Agent / Skill 工作流产物工厂；运行态文件位于 `process/`；Story 级设计对象为 `process/stories/STORY-*-LLD.md`
- **领域关键词**：agentic workflow、分阶段门禁、HLD→Story→LLD→实现、文件化契约、AI 可执行文档
- **质量目标**：确定性语言、可追踪、可验证、先设计后实现、人工检查点与验证门禁
- **集成需求**：LLD 需要同时服务 `meta-dev` 的实现准备、`meta-qa` 的验证设计、`meta-po` 的门禁控制
- **输入完整性**：`.input/` 已就绪；`process/REQUIREMENTS.md`、`process/USE-CASES.md`、`process/REQUEST.md` 当前缺失，因此本报告按 **LLD 写作专题** 输出，不做需求匹配排序

---

## 一、结论摘要

**awesome-copilot 里没有单一的 “LLD Writer”，LLD 能力是由 5 类资源组合出来的：**

1. **Specification**：把约束、接口、验收条件写清楚
2. **Workflow Blueprint**：把入口、服务层、数据流、错误路径写成实现级流程
3. **Implementation Plan**：把设计进一步拆成原子 phase/task/validation
4. **ADR**：把关键设计决策与取舍留痕
5. **Technical Spike**：把无法确定的技术问题从 LLD 主体中剥离，先研究再实现

**对本项目最有价值的，不是整包照搬某个 agent/skill，而是组合借鉴以下骨架：**

- `create-specification` 的 **契约写法**
- `project-workflow-analysis-blueprint-generator` 的 **实现级流程写法**
- `create-implementation-plan` 的 **原子任务与验证写法**
- `create-architectural-decision-record` 的 **决策留痕写法**
- `create-technical-spike` 的 **未决问题升级路径**

---

## 二、Agents 分析

### 2.1 需适配后借鉴

| Agent | 本地路径 | GitHub 链接 | 核心功能 | 优点 | 缺点/局限 | 借鉴判断 | 借鉴内容 |
|---|---|---|---|---|---|---|---|
| `implementation-plan.agent.md` | `.input/agents/implementation-plan.agent.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/agents/implementation-plan.agent.md) | 生成确定性的 implementation plan | 强调 phase 原子化、任务可并行、要求精确到文件与函数 | 更像“实施计划”而不是“详细设计”；缺少接口契约、异常路径、数据模型章节 | **需适配** | 迁移其 `REQ-/TASK-/GOAL-` 编码、阶段完成准则、验证条目到 `STORY-*-LLD.md` 的“实施步骤”部分 |
| `specification.agent.md` | `.input/agents/specification.agent.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/agents/specification.agent.md) | 生成 AI-ready specification | 对需求、约束、接口、验收条件表达清晰，适合机器消费 | 偏 specification，不包含足够的任务拆解与文件影响范围 | **需适配** | 迁移其 `Interfaces & Data Contracts`、`Acceptance Criteria`、`Validation Criteria` 结构到 LLD 主体 |
| `adr-generator.agent.md` | `.input/agents/adr-generator.agent.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/agents/adr-generator.agent.md) | 生成 ADR | 决策、替代方案、正负后果、实施注意事项完整 | ADR 是决策对象，不是完整 LLD；若单独使用会导致实现细节缺失 | **需适配** | 用作 LLD 中“关键决策/取舍/影响”子章节模板 |
| `project-architecture-planner.agent.md` | `.input/agents/project-architecture-planner.agent.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/agents/project-architecture-planner.agent.md) | 做整体架构与扩展路线规划 | 擅长候选方案对比、架构风格与扩展路线 | 偏 HLD/架构规划，不适合直接生成 Story 级 LLD | **仅参考** | 仅借鉴“至少比较两个方案并给出 trade-off”的写法 |

### 2.2 不适用（跳过原因）

- `plan.agent.md`、`planner.agent.md`：偏通用“先思考后规划”的对话模式，缺少 LLD 所需的接口、数据、异常、验证等硬结构。
- 其他 architecture/planning 泛化 Agent：大多停留在 HLD、路线图或 planning 层，无法直接覆盖 Story 级详细设计。

---

## 三、Skills 分析

### 3.1 可直接借鉴

| Skill | 本地路径 | GitHub 链接 | 核心功能 | 优点 | 缺点/局限 | 借鉴内容 |
|---|---|---|---|---|---|---|
| `project-workflow-analysis-blueprint-generator` | `.input/skills/project-workflow-analysis-blueprint-generator/SKILL.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/skills/project-workflow-analysis-blueprint-generator/SKILL.md) | 输出 implementation-ready 的端到端工作流文档 | 直接覆盖 **入口点、服务层、数据映射、数据访问、响应构造、错误处理、异步处理、测试模式**，非常接近 Story 级 LLD 的“主流程 + 异常流程”写法 | 更适合“基于现有代码反推实现模板”，对纯前置设计需要补足目标变更说明 | **主流程章节模板** |
| `create-technical-spike` | `.input/skills/create-technical-spike/SKILL.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/skills/create-technical-spike/SKILL.md) | 为阻塞实现的技术问题创建 time-boxed spike | 能把“当前还无法定稿”的问题从 LLD 主文档中拆出去，避免假定式设计 | 不是 LLD 主体，而是配套研究机制 | **未决问题升级路径** |

### 3.2 需适配后借鉴

| Skill | 本地路径 | GitHub 链接 | 核心功能 | 适配说明 |
|---|---|---|---|---|
| `create-implementation-plan` | `.input/skills/create-implementation-plan/SKILL.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/skills/create-implementation-plan/SKILL.md) | 生成确定性实施计划 | 保留其 phase/task/validation 结构，但不要把 LLD 降成纯任务清单；需补充模块职责、接口契约、异常处理、回滚策略 |
| `update-implementation-plan` | `.input/skills/update-implementation-plan/SKILL.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/skills/update-implementation-plan/SKILL.md) | 基于新约束更新实施计划 | 适合映射到 LLD 变更单场景；需要接入本项目 `CR-*.md` 变更流程，而不是直接改计划文件 |
| `create-specification` | `.input/skills/create-specification/SKILL.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/skills/create-specification/SKILL.md) | 生成 AI-ready specification | 很适合作为 LLD 上半部分；需补充文件影响范围、实施步骤、发布/回滚、任务分解 |
| `breakdown-feature-implementation` | `.input/skills/breakdown-feature-implementation/SKILL.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/skills/breakdown-feature-implementation/SKILL.md) | 生成详细 feature implementation plan | 内容最接近传统 LLD，覆盖架构图、数据库、API、前端、性能/安全；但强绑定 Epoch monorepo、tRPC、Stack Auth、shadcn/ui 等 SaaS/Web 前提，需要抽象成通用模板 |
| `architecture-blueprint-generator` | `.input/skills/architecture-blueprint-generator/SKILL.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/skills/architecture-blueprint-generator/SKILL.md) | 生成项目架构蓝图 | 更适合 HLD→LLD 的桥接层，可借鉴“Implementation Patterns”“Testing Architecture”小节；不适合作为 Story 级详细设计全文 |
| `create-architectural-decision-record` | `.input/skills/create-architectural-decision-record/SKILL.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/skills/create-architectural-decision-record/SKILL.md) | 生成 ADR 文档 | 适合作为 LLD 的决策附录；需要与 `STORY-*-LLD.md` 合并或双向引用，避免决策与实现说明分离 |

### 3.3 关键判断

**如果只选一个最像 LLD 的资源，首选 `breakdown-feature-implementation`；如果要给本项目落一套可持续的 LLD 方法，最佳组合是：**

`create-specification` + `project-workflow-analysis-blueprint-generator` + `create-implementation-plan` + `create-architectural-decision-record` + `create-technical-spike`

原因：

1. `create-specification` 负责 **写清楚**
2. `workflow-analysis-blueprint` 负责 **写完整主/异常流程**
3. `create-implementation-plan` 负责 **写成可执行任务**
4. `ADR` 负责 **写清楚为什么这样设计**
5. `technical-spike` 负责 **处理当前还不能定稿的问题**

---

## 四、Instructions 分析

### 4.1 可直接借鉴

| Instruction | 本地路径 | GitHub 链接 | 适用技术栈 | 借鉴判断 | 借鉴内容 |
|---|---|---|---|---|---|
| `spec-driven-workflow-v1.instructions.md` | `.input/instructions/spec-driven-workflow-v1.instructions.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/instructions/spec-driven-workflow-v1.instructions.md) | 通用 | **直接借鉴** | 核心是 `requirements.md → design.md → tasks.md` 三件套，以及“未完成 design/plan 不得进入 implement”的强约束。这与本项目的 `REQUIREMENTS/HLD/STORY-LLD` 门禁思想高度一致。 |

### 4.2 需适配后借鉴

| Instruction | 本地路径 | GitHub 链接 | 适配说明 |
|---|---|---|---|
| `task-implementation.instructions.md` | `.input/instructions/task-implementation.instructions.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/instructions/task-implementation.instructions.md) | 适合作为 **LLD 执行期** 的落地约束：实现前先读 plan/details，任务完成后更新变更记录。需要改造成符合本项目 `STORY-*-LLD.md`、Story 卡片与 `TASK-ID` 的协议。 |

### 4.3 不适用（跳过原因）

- 其他 instructions 多为语言/框架专项最佳实践，对“LLD 文档怎么写”帮助有限。

---

## 五、Plugins / Workflows / Hooks 分析

### 5.1 Plugins

| Plugin | 本地路径 | GitHub 链接 | 包含资源 | 借鉴判断 | 借鉴内容/适配说明 |
|---|---|---|---|---|---|
| `project-planning` | `.input/plugins/project-planning/README.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/plugins/project-planning/README.md) | PRD、Epic 架构、Implementation Plan、Technical Spike、Issue 生成相关命令与 Agent/Skill 组合 | **需适配** | 它证明了 community 的成熟模式不是“单文档 LLD”，而是 **PRD → Arch → Implementation Plan → Issue/Task → Spike** 的资源链。可借鉴为本项目的 HLD / Story / LLD / TASK-ID 串联方式。 |

### 5.2 Workflows

**未发现与 LLD 写作直接相关的 workflow 资源。**

`.input/workflows/` 当前主要是 OSPO / relevance / 报告型工作流，不是详细设计写作模板。

### 5.3 Hooks

**未发现与 LLD 写作直接相关的 hook 资源。**

现有 hooks 更偏治理、日志、工具边界保护，对“如何写 LLD”没有直接模板价值。

---

## 六、实现原理分析（LLD 写作视角）

### 6.1 awesome-copilot 的共同写法

从本次高相关资源看，awesome-copilot 的 LLD 相关内容有 5 个稳定模式：

1. **把“设计”和“任务”拆开写**
   - `create-specification` 负责契约
   - `create-implementation-plan` 负责实施
   - 说明社区默认认为“详细设计 ≠ 任务清单”，两者应分层

2. **接口与数据契约必须显式**
   - `create-specification` 明确要求 `Interfaces & Data Contracts`
   - `workflow-analysis-blueprint` 明确要求 DTO、response model、repository 接口、事务模式

3. **主流程与异常流程必须成对出现**
   - `workflow-analysis-blueprint` 把 error handling、async path、compensating actions 单列
   - 这比只写 happy path 的设计文更适合 AI/自动化执行

4. **决策与实施注意事项分离**
   - `ADR` 把决策、替代方案、后果独立出来
   - 避免设计文把“是什么/怎么做/为什么”混写成一个模糊段落

5. **未决问题先升级为 spike，不在设计中偷设默认值**
   - `create-technical-spike` 的价值在于：允许设计文显式承认“当前还不知道”

### 6.2 对本项目的直接启发

本项目当前已经要求：

- HLD 与 LLD 分离
- LLD 先确认、再实现
- 使用确定性语言
- Story 级产物需要服务开发与验证

因此最合适的借鉴方式不是引入新的通用 planner，而是把 awesome-copilot 的 LLD 能力折叠进 `STORY-*-LLD.md` 的固定骨架中。

---

## 七、综合借鉴建议

### 7.1 直接引入清单（meta-dev / meta-qa 可直接使用）

| 资源路径 | 类型 | 引入方式 | 目标消费方 |
|---|---|---|---|
| `.input/instructions/spec-driven-workflow-v1.instructions.md` | instruction | 作为 `LLD 未完成不得实现` 的方法论来源，在 Story LLD 模板和 meta-dev 准入规则中直接引用 | meta-dev / meta-po |
| `.input/skills/project-workflow-analysis-blueprint-generator/SKILL.md` | skill | 作为 `STORY-*-LLD.md` 中“核心流程 / 异常路径 / 数据访问 / 测试入口”章节的直接参考模板 | meta-dev / meta-qa |
| `.input/skills/create-technical-spike/SKILL.md` | skill | 当 LLD 中存在未决技术问题时，直接作为升级路径引用，而不是在 LLD 内模糊保留 | meta-dev / meta-se |

### 7.2 适配引入清单

| 资源路径 | 类型 | 适配要点 | 目标消费方 |
|---|---|---|---|
| `.input/skills/create-specification/SKILL.md` | skill | 把 `Purpose/Scope`、`Requirements`、`Interfaces & Data Contracts`、`Acceptance Criteria` 收编为 Story LLD 主体前半部分 | meta-dev |
| `.input/skills/create-implementation-plan/SKILL.md` | skill | 把 `Implementation Phase / Task / Validation` 收编为 Story LLD 后半部分与 TASK-ID 清单 | meta-dev |
| `.input/skills/update-implementation-plan/SKILL.md` | skill | 结合 `CR-*.md` 做 LLD 变更维护，而不是直接改文档无留痕 | meta-po / meta-dev |
| `.input/skills/breakdown-feature-implementation/SKILL.md` | skill | 提炼其“架构图/数据库/API/前端/安全性能”栏目，去除 Epoch 与 Web/SaaS 强绑定假设 | meta-dev |
| `.input/skills/create-architectural-decision-record/SKILL.md` | skill | 把 ADR 的 `Decision / Consequences / Alternatives / Implementation Notes` 压缩为 LLD 的决策附录 | meta-se / meta-dev |
| `.input/instructions/task-implementation.instructions.md` | instruction | 把 `.copilot-tracking` 机制映射到 Story 卡片、`TASK-ID` 与变更记录，形成执行闭环 | meta-dev / meta-qa |
| `.input/plugins/project-planning/README.md` | plugin | 借鉴“PRD→Architecture→Implementation Plan→Issues→Spike”的资源链，不直接照搬插件目录形态 | meta-se / meta-dev |

### 7.3 推荐的 Story LLD 章节骨架

> 推荐把本项目的 `process/stories/STORY-*-LLD.md` 收敛为下列固定结构。

1. **目标与范围**：本 Story 要解决什么，不解决什么  
2. **输入约束**：来源于 HLD / Story 卡片 / CR 的要求与限制  
3. **模块与文件影响范围**：新增/修改/删除哪些文件与对象  
4. **接口与数据契约**：输入、输出、状态、持久化结构、外部依赖  
5. **核心流程与异常流程**：入口 → 服务 → 数据 → 返回；列出失败路径  
6. **关键决策与备选方案**：引用 ADR-lite 结构  
7. **实施步骤与 TASK-ID**：按 phase/task 原子化拆解  
8. **验证设计**：单测/集成/回归/错误路径/边界值  
9. **发布与回滚**：迁移、兼容、开关、回退条件  
10. **遗留问题 / Spike 升级项**：当前不能拍板的问题与后续动作

### 7.4 HLD 可直接引用的模式 / 规则

- **设计前置规则**：`spec-driven-workflow-v1.instructions.md` → 未完成 design/plan 不进入 implement
- **实现级流程模板**：`project-workflow-analysis-blueprint-generator` → 主流程、异常路径、数据映射、测试入口必须显式
- **决策留痕模式**：`create-architectural-decision-record` / `adr-generator.agent.md` → 每个重要设计点都要有 alternatives 与 consequences
- **风险隔离模式**：`create-technical-spike` → 未决问题不要伪装成已决设计

### 7.5 对 `ARCHITECTURE-DECISION.md` 的影响

| 决策点 | 来源资源 | 推荐决策 | 理由 |
|---|---|---|---|
| LLD 是否只写任务，不写契约 | `create-specification` + `create-implementation-plan` | **否**，LLD 必须同时覆盖契约与任务 | awesome-copilot 将 spec 与 plan 分开，说明只写 task 会丢失接口/约束/验收语义 |
| LLD 是否必须包含异常路径 | `project-workflow-analysis-blueprint-generator` | **是** | 该资源把 error handling、retry、compensating actions 作为实现级文档的固定部分 |
| 未决技术问题如何处理 | `create-technical-spike` | **升级为 Spike，不在 LLD 中模糊默认** | 可避免“伪确定性”设计进入实现阶段 |
| 设计取舍是否需要独立记录 | `create-architectural-decision-record` / `adr-generator.agent.md` | **需要**，至少保留 ADR-lite 小节 | 便于后续 Story 变更、验证与回溯 |

---

## 八、遗留问题

| 问题 | 影响 | 建议操作 |
|---|---|---|
| 当前仓库缺少 `process/REQUIREMENTS.md`、`process/USE-CASES.md`、`process/REQUEST.md` | 无法按 skill 规范做“项目特征→相关性排序”的严格筛选 | 后续若补齐正式输入，可再产出一版“结合已确认需求”的 LLD 专题分析 |
| 本次分析聚焦 LLD 写作，不覆盖实际模板落地 | 报告可指导设计，但不会自动改变 `STORY-*-LLD.md` 结构 | 若进入实现阶段，下一步应把第 7.3 节固化为 Story LLD 模板 |
