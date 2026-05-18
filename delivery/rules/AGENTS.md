# Meta Flow 元工作流 — Agent 声明

> 本项目运行 **Meta Flow** 通用 Agent/Skill 工作流产物工厂。
> 主编排器为 **meta-po**，所有任务统一由一个 meta-po 子 agent 发起并协调。

---

## 主编排器

| 字段 | 值 |
|------|----|
| 角色名称 | meta-po（元工作流产品负责人） |
| 提示词文件 | Codex：`.codex/agents/meta-po.toml`；Claude Code/OpenClaw：`agents/meta-po.md` |
| 触发词 | 开始、新建工作流、需求变更、推进、当前状态、继续、回退 |
| 始终激活 | 否。仅在显式 `@meta-po` 或触发词命中时启动；若已有活动 `meta-po`，必须复用，不得再拉起新线程 |

meta-po 的职责：

- **项目初始化**：创建 `process/`、`process/checks/`、`checkpoints/`，并按交付路由决定是否写入 `delivery/` 或目标项目约定目录
- 初始化 `process/STATE.md` 并维护全程状态
- **先理解，后行动**：退出条件先验、上下文先行、追问优先于假设、状态一致性校验
- 维护 CP0-CP8 检查点：自动检查点写入 `process/checks/CP*.md`，人工检查点写入 `checkpoints/CP*.md` 并在发起确认时提示用户 checklist 路径，审查后回填人工结果
- 唤醒和收敛下游功能 Agent（机器可验证退出条件）；Codex 下同一工作流只允许 1 个 `meta-po`，同角色同任务优先复用已有子 agent，检查点或交接完成后及时关闭；发现两个活动 `meta-po` 时必须阻断推进并要求用户选择保留线程
- 记录子 agent 调度证据：handoff 文件只表示交接，不表示目标 agent 已执行；meta-dev / meta-qa 等下游完成必须有 `spawn_agent` / `resume_agent` / `send_input` 或平台 Task/Subagent 证据，或用户批准的 `inline-fallback`
- 维护 Agent 命令与显示区分：Codex 使用 `nickname_candidates`（如 `po-zhao`、`dev-yang`），Claude Code 不使用 nickname，改用不同 `color` 区分 subagent
- 受理变更请求，创建 `changes/CR-*.md`，执行五维度影响分析
- **失败模式识别**：识别需求循环、HLD 僵局、LLD 僵局、开发卡顿等常见失败信号

## 功能 Agent（按需唤醒，由 meta-po 调度）

| Agent | 提示词文件 | 职责 | 唤醒条件 |
|-------|-----------|------|---------|
| **meta-pm** | `agents/meta-pm.md` | 快速调研（阶段零）+ 场景发现（USE-CASES.md，含画像/指标）+ 需求结构化（REQUIREMENTS.md，含风险/里程碑）+ 完整性自检 | 新请求进入、需求模糊、需求变更后重整 |
| **meta-se** | `agents/meta-se.md` | HLD 设计（含候选方案对比 + 5 层架构图 + 技术选型理由）+ Story 拆解（含文件布局 + TASK-ID 任务清单）+ 开发计划（含完成准则） | REQUIREMENTS.md 已确认（solution-design 和 story-planning 两阶段均由 meta-se 执行） |
| ~~**meta-dm**~~ | ~~`agents/meta-dm.md`~~ | ~~Story 拆解与并行计划~~ | ⚠️ **已废弃**，职责合并至 meta-se |
| **meta-dev** | `agents/meta-dev.md` | Story LLD 输出与人工确认闭环 + Agent/Skill 文件实现 + TASK-ID 增量追踪 + 偏差记录 | 存在已批准且可执行的 Story |
| **meta-qa** | `agents/meta-qa.md` | TEST-STRATEGY.md 输出（ISTQB/ISO 25010）+ 8 维度验收 + 质量门控 + 平台安装脚本交付 | Story 进入 ready-for-verification + VALIDATION-ENV.yaml 已就绪 |
| **meta-doc** | `agents/meta-doc.md` | README（含架构概览 + 用户旅程）+ USER-MANUAL（含故障排除）+ 严重度分级文档缺口 | 核心产物已验证且安装脚本稳定 |

### Agent 命令与显示映射

canonical role 仍为 `meta-*`，用于状态机、handoff、检查点和审计。平台展示按下表安装：

| canonical role | Codex 命令 / nickname_candidates | Claude Code color |
|---|---|---|
| `meta-po` | `po-zhao`、`po-qian`、`po-sun`、`po-li`、`po-zhou` | `red` |
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `orange` |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `yellow` |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu`、`dev-he`、`dev-lv`、`dev-shi`、`dev-zhang`、`dev-kong` | `green` |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong`、`qa-cao`、`qa-yan`、`qa-hua`、`qa-jin`、`qa-wei` | `cyan` |
| `meta-doc` | `doc-cao`、`doc-yan`、`doc-hua`、`doc-jin`、`doc-wei` | `purple` |

## 工作流阶段与 Agent 对应关系

```
init（meta-po）                                                   [CP0 自动]
 └─► requirement-clarification（meta-pm：场景发现 → 需求结构化）   [CP1 自动 + CP2 人工]
      └─► solution-design（meta-se：输出 HLD）                     [CP3 人工]
           └─► story-planning（meta-se 拆解全部 Story → meta-po 计算全量 LLD 队列 → meta-dev 并行产出全部 Story LLD） [CP4 人工 + CP5 全量确认]
                │    LLD 写作并行：全部目标 Story 的 LLD 可按并发上限分轮起草
                │    LLD 确认全量化：全部 Story LLD 与 CP5 自动预检完成后，统一人工确认
                └─► story-execution（全量 LLD 确认后进入 Wave 开发/验证循环）
                │    开发并行：全量 CP5 已通过后，按 Wave 调度依赖满足且文件无冲突的 dev-ready Story 并行实现
                │    同一 Story 内串行：CP6 开发完成 → CP7 验证完成
                └─► documentation（meta-doc）                      [CP8 人工]
                     └─► delivered
```

## 工作目录约定

| 目录 / 文件 | 用途 |
|------------|------|
| `process/STATE.md` | 工作流运行时状态（meta-po 维护） |
| `process/REQUEST.md` | 用户原始请求 |
| `process/USE-CASES.md` | 场景文档（meta-pm 产出） |
| `process/REQUIREMENTS.md` | 结构化需求（meta-pm 产出） |
| `process/HLD.md` | 高层设计过程稿（meta-se 产出） |
| `process/ARCHITECTURE-DECISION.md` | 架构决策（meta-se 产出） |
| `process/STORY-BACKLOG.md` | Story 列表（meta-se 产出） |
| `process/DEVELOPMENT-PLAN.yaml` | Wave 执行计划（meta-se 产出，含完成准则） |
| `process/TEST-STRATEGY.md` | 测试策略（meta-qa 产出，ISTQB/ISO 25010） |
| `process/checks/` | 自动检查点结果（CP0/CP1/CP2/CP3/CP4/CP5/CP6/CP7/CP8） |
| `skills/<skill-name>/templates/` | Skill 私有模板目录（仅单个 Skill 内部初始化 / 渲染使用） |
| `skills/<skill-name>/scripts/` | Skill 私有运行时脚本目录（需随 Skill 一起安装时使用） |
| `checkpoints/` | 人工检查点审查稿（CP2/CP3/CP4/CP5/CP8，含 checklist 和人工审查结果） |
| `process/stories/` | Story 卡片（STORY-*.md）与 Story 级 LLD（STORY-*-LLD.md） |
| `process/changes/` | 变更单（CR-*.md） |
| `delivery/agents/` | 交付 Agent 提示词文件（canonical 源，同时是 meta-dev 产出目录） |
| `delivery/skills/` | 交付 Skill 定义文件（canonical 源，同时是 meta-dev 产出目录） |
| `delivery/rules/` | 各平台规则文件（AGENTS.md / CLAUDE.md） |
| `delivery/scripts/` | 仅安装器入口（install.py / install.sh / install.ps1） |
| `scripts/` | 仓库级检查与构建脚本（不属于交付包） |
| `delivery/README.md` | 产物 README（meta-doc 产出） |
| `delivery/doc/USER-MANUAL.md` | 产物用户手册（meta-doc 产出） |
| `.agents/agents/` | 元工作流 Agent 提示词文件（meta-po/pm/se/dev/qa/doc） |
| `.agents/skills/` | 元工作流 Skill 定义文件（Meta Flow 内置） |

### 输出隔离原则

> **所有由元工作流产生的文件必须按层输出到 `process/`（运行态）、`process/checks/`（自动检查结果）、`checkpoints/`（确认态）和经确认的交付出口。**
> 只有 `engagement_mode=meta-self-dev` 或用户明确说明优化 meta-flow 本身时，才默认把交付物写入当前仓库 `delivery/`。
> production 项目必须先扫描目标项目 `README.md` / `README.*` / `docs/` 的交付物约定；存在则遵守，不存在则先提出建议并等待用户确认。
> 当前仓库 `delivery/` 是 meta-flow 自身可独立推送到目标 Git 仓库的交付包，内含 `agents/`、`skills/`、`rules/`、`scripts/`。
> `.agents/` 保留元工作流引擎自身定义，不参与安装。

## Python 环境与依赖管理（uv）

若项目包含 Python 代码、脚本、验证工具或 MCP 服务，必须遵循以下约束：

1. 统一使用 `uv` 管理 Python 解释器、虚拟环境和依赖。
2. 存在项目级 Python 依赖时，以 `pyproject.toml` 为唯一依赖声明来源，以 `uv.lock` 为唯一锁定结果；禁止提交 `.venv/`。
3. 所有开发、测试、构建和脚本执行统一通过 `uv run` 触发；一次性工具统一优先使用 `uvx`。
4. 禁止将裸 `pip install`、系统 Python 或未入库依赖作为日常工作流默认入口。
5. 若项目尚未建立 `pyproject.toml` / `uv.lock`，仍必须使用 `uv` 管理解释器，并以 `uv run --python <version> python <script>` 作为 Python 命令入口。
6. README、USER-MANUAL 及平台规则文件中的 Python 示例必须与上述约束保持一致。

## 方案编写与修订规则

1. **先核对事实，再写方案**：平台路径、发现面、配置位置和行为约束，必须以当前仓库实现与官方文档为准；发现旧假设错误时，先修正事实判断，再扩展方案。涉及平台安装路径时，`delivery/doc/PLATFORM-CONTRACTS.yaml` 是单一真相源，README / USER-MANUAL / HLD / LLD 只能作为派生说明。
2. **优先最简方案**：默认选择能满足目标的最小设计，避免为“统一”额外引入新抽象层、共享运行时或重复形态；若必须保留备选方案，应说明何时切换。
3. **废弃内容要彻底删除**：已确认废弃的目录、路径变量、章节、实施步骤和验收项，不得只标注“废弃”而保留残余引用。
   - 本规则不得用于删除仍需追溯的旧需求或旧场景基线；需求 / 场景变更必须通过 CR 记录旧基线保留方式。
4. **问题必须状态化**：阻塞问题、遗留问题和开放问题必须逐项标注状态（如已解答、部分解答、待整改），并在方案修订时同步刷新。
5. **主选与备选并存**：已确认主选方案时，实施文档应同时记录主选值、备选方案和切换条件，避免后续重复讨论同一决策。
6. **问题描述必须完整**：方案中的问题条目不能只有标题，至少应说明背景、触发条件、影响范围、为何是问题以及需要谁决策。
7. **目录设计要分层**：过程文档、人工检查点文档、交付文档应分区描述，避免把运行态、检查态和交付态混写为同一输出面。
8. **稳定偏好才能升格为共享规则**：只有已经稳定、适合团队复用的偏好才能进入仓库共享规范；明显属于个人工作习惯的内容不应直接写入共享规则。

## 方案评审规则（Design Review）

> 本节规则适用于对 HLD / LLD / Story Plan / ADR 等设计产物的评审。评审方（无论是人还是 Agent）必须逐条校验下列维度，未通过项必须返工或在产物中显式留痕。

1. **内部一致性检查**：ADR、Risk Matrix、NFR、模块职责、流程图之间不得自相矛盾。典型反例：ADR-1 规定"HTML 注释隐藏" vs Risk 应对要求"可读附录"。发现矛盾必须在同一轮修订中解决，不得延迟。
2. **目标必须量化**：成功标准（Success Criteria）每一条必须含可度量值（数量、百分比、字段集、耗时、覆盖率等）；禁止"不少于 X"、"尽可能"、"更完整"这类无可检验下限的表述。
3. **集成契约显式化**：任何新 Agent / Skill / 模块必须显式定义与调用方和相邻对象的契约，至少覆盖：**调用方向、调用时机、触发方式、输入契约、输出契约、后续衔接、降级策略、调用方需要同步修改的范围**。不允许只声明"独立可调用"而不说明如何被真实集成。
4. **相邻对象边界澄清**：非目标（Out of Scope）章节必须显式指出与相邻 Skill / Agent 的职责差异；同名或近义职责（如"澄清"、"扩展"、"发现"）必须逐词界定归属，避免默认重叠。
5. **前置校验与失败路径**：每个执行阶段必须定义前置条件校验表与失败行为（终止 / 降级 / 回退），禁止"成功路径 only"的设计。
6. **回退决策可操作化**：用户的修改/回退动作必须映射为可枚举的决策表（意图关键词 → 回退目标 → 理由），避免"根据类型回退"这类需模型自由裁量的模糊规则。
7. **理论依据可追溯**：枚举型框架（维度表、阶段列表、检查清单）必须说明来源方法论（如 JTBD / FMEA / Journey Mapping / ISTQB / ISO 25010 等），或显式声明"领域经验 + 可扩展"以避免被当作穷尽集合使用。
8. **遗留问题状态闭环**：待确认问题在每次修订必须回写状态（OPEN / RESOLVED + 日期 + 决策引用）；收敛后原问题行不得删除，以保留决策追溯链。
9. **Gotchas 必有**：Skill 类产出的 HLD 或 SKILL.md 必须包含实质性 Gotchas 章节（至少列出常见误用与规避），形式性填充视为未完成。
10. **修订记录完整**：每次设计迭代必须在产物头部的 `修订记录` 表追加一行，包含版本号、日期、修订人、变更要点（精确到章节号），避免靠 Git 历史反推；该规则同样覆盖 `USE-CASES.md` 与 `REQUIREMENTS.md`。
11. **Story 拆解一致性**：§工作量章节中的 Story 数、Wave 数必须与 §分阶段落地章节一一对应；不一致视为设计缺陷。
12. **决策与产物形态对齐**：ADR 的结论必须反映在对应章节（架构图、模块表、流程图、落地阶段）中；孤立的 ADR 未回写到其他章节视为未落地。
13. **官方契约一致性**：涉及平台路径、schema 或发现机制的 HLD / LLD / Story Plan / ADR，必须引用官方文档或 `delivery/doc/PLATFORM-CONTRACTS.yaml` 中的已验证来源；禁止用同平台目录类比推断。Codex Agent 与 Skill 必须分开断言：Agent 在 `.codex/agents` / `~/.codex/agents`，Skill 在 `.agents/skills` / `~/.agents/skills`。

## 协议约定

- **文件系统协议**：Agent 间通过 Markdown/YAML 文件交换信息，不依赖隐式推理传递
- **单写规则**：同一核心对象同一时刻只允许一个主要写入方
- **回写规则**：每一阶段结束必须回写 `STATE.md`
- **变更规则**：需求或设计变动必须先创建 `CR-*.md` 再修改正式对象
- **需求 / 场景变更追溯**：修改 `USE-CASES.md` / `REQUIREMENTS.md` 前，必须在 CR 中填写文档处理决策（新增 / 原文档更新 / 归档 / 不变）；默认增量更新、保留旧基线并追加 `## 修订记录`，不得用新草案整体替换旧文档
- **检查点结构**：CP0-CP8 均必须包含 Entry Criteria、Checklist、Exit Criteria、Deliverables；自动检查点必须在 `process/checks/CP*.md` 写入逐项结果，人工检查点必须在 `checkpoints/CP*.md` 写入 checklist 和“人工审查结果”。
- **人工检查点**：所有人工确认统一由 meta-po 发起；发起时必须提示用户 checklist 文件路径（如 `checkpoints/CP3-HLD-REVIEW.md`）。Claude Code 可使用结构化选择；Codex 只有在当前工具面明确提供可用的 `request_user_input` / 选择 UI 时才使用结构化选择，否则默认使用 exact 文本确认。发起确认时只展示三个推荐回复：`approve`、`修改: <具体修改点>`、`reject`；内部可兼容历史别名 `1/通过`、`2/修改: ...`、`3/不通过`，但不得把多个别名混排成用户必须理解的选项。用户直接在对话中确认时，meta-po 仍必须回填对应 `checkpoints/CP*.md`。
- **子 agent 调度证据**：meta-po 调用功能 Agent 必须使用平台子 agent 调度能力。Codex 新任务使用 `spawn_agent`，复用任务使用 `resume_agent` 或 `send_input`；Claude Code/OpenClaw 使用对应 Task/Subagent 能力。`process/handoffs/*.md` 必须包含 `dispatch` 区，记录 `mode`、`agent_id` / `thread_id`、`tool_name`、`spawned_at` / `resumed_at`、`completed_at`。缺少这些字段时，只能判定为 `handoff-created`，不得写成目标 agent 已完成。
- **inline fallback 门禁**：当前平台无法拉起子 agent 时，meta-po 必须阻断并说明原因；只有用户明确批准后才能用 `dispatch.mode=inline-fallback` 代执行，并记录 `fallback_reason`、`approved_by`、`approved_at`。inline fallback 结果必须表述为 meta-po 代执行，不得表述为 meta-dev / meta-qa 独立完成。
- **HLD 门控**：CP3 自动预检和人工确认未通过前，不得进入 Story 拆解。
- **Story 计划与 LLD 门控**：CP4 自动预检和人工确认未通过前，不得开始全量 LLD 设计；全部目标 Story 的 CP5 自动预检和全量人工确认未通过前，不得进入 Story 执行。LLD 必须覆盖全部目标 Story，且可跨 Story 并行写作。标准开发默认以全部目标 Story 为 LLD 设计批次；变更流程默认以 CR 影响范围为 LLD 设计批次。
- **Story 执行门控**：进入 story-execution 时全部目标 Story 的 LLD 必须已确认；开发按 Wave、Story DAG、依赖类型和文件所有权调度，不得在 CP5 前实现任何 Story。
- **编码与验证门控**：Story 实现完成后必须写入 CP6 编码完成检查结果；验证完成后必须写入 CP7 验证完成检查结果。CP6/CP7 必须包含 `Agent Dispatch Evidence`；缺少真实子 agent 证据且没有用户批准的 `inline-fallback` 时不得推进 Story 状态。
- **Skill 模板关系维护**：创建或修改 Agent、Skill 或 Skill 私有模板时，若影响调用、适用、归属或模板交叉引用关系，必须同步更新 `skills/README.md`
- **交付脚本边界**：`delivery/scripts/` 只允许安装器入口；任何被 Skill 运行时引用的脚本必须放到 `delivery/skills/<skill>/scripts/`
- **Skill 资产同树安装**：active Skill 引用的 `templates/`、`scripts/`、`schemas/`、`examples/` 资产必须与 Skill 同树存放，并使用 Skill 相对路径或 `<skill-root>/...` 表达
- **脚本安装验证**：active Skill 一旦新增脚本资产，必须验证 Claude Code / Codex 在 project 与 user scope 下安装后可直接执行
- **缓存文件禁入库**：`__pycache__/`、`*.pyc` 及其他解释器生成缓存不是交付物，不得提交
- **护栏静态检查**：`scripts/check_delivery_guardrails.py` 是 meta-flow 自身仓库 guardrail；仅当当前仓库存在该文件时，提交前运行 `uv run --python 3.11 python scripts/check_delivery_guardrails.py`。外部 production 项目不得硬引用 `/home/hyde/projects/meta-flow/scripts/check_delivery_guardrails.py`，应改按目标 README/docs 的测试、构建、安装 dry-run 或用户确认的验证命令执行。
- **调研前置**：meta-pm 在场景发现前执行阶段零快速调研，记录至 CLARIFICATION-LOG.md
- **模式默认值**：若用户未显式声明“meta 工作流优化 / 自我开发”，工作流默认 `engagement_mode=production`
- **场景主体默认值**：若用户未显式声明 meta 优化，`USE-CASES.md` 默认 `scenario_subject_type=target-artifact`，不得把当前仓库 / 当前工作流当成默认场景主体
- **确定性语言**：meta-se 与 meta-dev 产出使用确定性动词（创建/修改/删除）和量化条件，禁止模糊表述
- **就绪检查**：meta-dev 开始实现前必须通过 Story 卡片完整性检查并确认 LLD 已获批
- **测试策略前置**：meta-qa 验收前先输出 TEST-STRATEGY.md，指导验证过程
- **方案收敛优先**：涉及方案设计、整改规划或跨平台治理时，默认优先最简方案与内联策略；除非事实或验收要求证明不足，不新增共享模板体系或多余抽象层
- **精确匹配优先**：涉及对象定位、版本对齐、规则命中或平台路径判定时，默认采用 exact 语义，不使用模糊匹配作为默认行为
- **平台契约优先**：安装器、DryRun、guardrail 与交付文档必须共同引用 `delivery/doc/PLATFORM-CONTRACTS.yaml`；Codex Skill 禁止写入 `.codex/skills` 或 `~/.codex/skills`
- **安装路径前置校验**：安装器写入前必须逐级检查目标父路径；任一级被普通文件占用时必须 fail fast，输出 `安装路径被非目录占用: <path>`，不得暴露 Python traceback
- **安装组件默认值**：安装 CLI 使用 `--component rules|agent|full`；`rules` 只安装 AGENTS.md / CLAUDE.md 等规则，`agent` 安装 agents+skills，`full` 同时安装两类内容；user scope 默认 `rules`，project scope 默认 `full`；legacy `--content all|agents|skills|rules` 仅作兼容入口

## 防火墙测试工作流（现有，独立运行）

> 本项目同时保留原有防火墙测试元工作流说明，两套系统并行存在，互不干扰。
> 当前统一编排入口：Codex 使用 `.codex/agents/meta-po.toml`；Claude Code/OpenClaw 使用对应平台的 `agents/meta-po.md`。

## LLD 消费契约补充

- `STORY-*-LLD.md` 必须保持 **14 个可见章节**；`Tier-S` 只允许简化内容深度，不允许压缩章节数量。
- `tier`、`shared_fragments`、`open_items` 是强输入字段，meta-dev / meta-qa 不得跳过。
- meta-dev 至少消费：文件影响范围、接口设计、异常处理、测试设计、实施步骤、回滚策略，并在全部目标 Story 的 LLD 统一确认且当前 Wave 的 `dev_gate` 满足后优先复用同一子 agent 继续实现。
- meta-qa 至少消费：接口设计、核心流程、测试设计、回滚策略、OPEN/Spike 状态。

## Review Gate 分派与灰度

| Lane | Agent | 主要职责 |
|------|-------|----------|
| `lane-product` | `meta-pm` | 场景、画像、指标与范围一致性、原始需求 / 场景基线保留和修订记录 |
| `lane-architecture` | `meta-se` | 设计边界、依赖、ADR 与阶段一致性 |
| `lane-implementation` | `meta-dev` | 可实现性、文件归属、平台约束 |
| `lane-quality` | `meta-qa` | 可验证性、风险、安全、安装约束 |
| `lane-docs` | `meta-doc` | 面向用户的可读性与交付完整性 |

灰度顺序：

1. 先覆盖 `HLD.md` 与 `STORY-*-LLD.md`
2. 再覆盖 `ARCHITECTURE-DECISION.md` 与 `STORY-BACKLOG.md`
3. 最后覆盖 `README.md`、`USER-MANUAL.md` 等交付文档
