# SCOPE-Pack 元工作流 — Agent 声明

> 本项目运行 **SCOPE-Pack** 通用 Agent/Skill 工作流产物工厂。
> 主编排器为 **meta-po**，所有任务统一由 meta-po 发起并协调。

---

## 主编排器

| 字段 | 值 |
|------|----|
| 角色名称 | meta-po（元工作流产品负责人） |
| 提示词文件 | `agents/meta-po.md` |
| 触发词 | 开始、新建工作流、需求变更、推进、当前状态、继续、回退 |
| 始终激活 | 是 |

meta-po 的职责：

- **项目初始化**：创建 `process/`、`checkpoints/`、`delivery/` 工作目录及所有信息流转文件
- 初始化 `process/STATE.md` 并维护全程状态
- **先理解，后行动**：退出条件先验、上下文先行、追问优先于假设、状态一致性校验
- 发起人工检查点（共 5 类：需求确认、HLD 确认、Story 计划确认、Story LLD 确认、终验）
- 唤醒和收敛下游功能 Agent（机器可验证退出条件）
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

## 工作流阶段与 Agent 对应关系

```
init（meta-po）
 └─► requirement-clarification（meta-pm：场景发现 → 需求结构化）   [检查点①]
      └─► solution-design（meta-se：输出 HLD）                     [检查点②]
           └─► story-planning（meta-se：按 HLD 拆解 Story）        [检查点③]
                └─► story-execution（Wave 循环）
                │    Wave 内并行：STORY-A [meta-dev:LLD→确认→实现→meta-qa] ‖ STORY-B [...]
                │    同一 Story 内串行：LLD 起草 → LLD 确认 → 开发 → 验证
                └─► documentation（meta-doc）                      [检查点⑤]
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
| `skills/<skill-name>/templates/` | Skill 私有模板目录（仅单个 Skill 内部初始化 / 渲染使用） |
| `skills/<skill-name>/scripts/` | Skill 私有运行时脚本目录（需随 Skill 一起安装时使用） |
| `checkpoints/` | 人工确认稿（REQUIREMENTS/HLD/STORY-PLAN/STORY-LLD） |
| `process/stories/` | Story 卡片（STORY-*.md）与 Story 级 LLD（STORY-*-LLD.md） |
| `process/changes/` | 变更单（CR-*.md） |
| `delivery/agents/` | 交付 Agent 提示词文件（canonical 源，同时是 meta-dev 产出目录） |
| `delivery/skills/` | 交付 Skill 定义文件（canonical 源，同时是 meta-dev 产出目录） |
| `delivery/rules/` | 各平台规则文件（AGENTS.md / CLAUDE.md / copilot-instructions.md） |
| `delivery/scripts/` | 仅安装器入口（install.py / install.sh / install.ps1） |
| `scripts/` | 仓库级检查与构建脚本（不属于交付包） |
| `delivery/.github/agents/` | Copilot CLI Agent 入口文件 |
| `delivery/README.md` | 产物 README（meta-doc 产出） |
| `delivery/doc/USER-MANUAL.md` | 产物用户手册（meta-doc 产出） |
| `.agents/agents/` | 元工作流 Agent 提示词文件（meta-po/pm/se/dev/qa/doc） |
| `.agents/skills/` | 元工作流 Skill 定义文件（SCOPE-Pack 内置） |

### 输出隔离原则

> **所有由元工作流产生的文件必须按层输出到 `process/`（运行态）、`checkpoints/`（确认态）、`delivery/`（交付态）。**
> `delivery/` 是可独立推送到目标 Git 仓库的交付包，内含 `agents/`、`skills/`、`rules/`、`scripts/`、`.github/agents/`。
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

1. **先核对事实，再写方案**：平台路径、发现面、配置位置和行为约束，必须以当前仓库实现与官方文档为准；发现旧假设错误时，先修正事实判断，再扩展方案。
2. **优先最简方案**：默认选择能满足目标的最小设计，避免为“统一”额外引入新抽象层、共享运行时或重复形态；若必须保留备选方案，应说明何时切换。
3. **废弃内容要彻底删除**：已确认废弃的目录、路径变量、章节、实施步骤和验收项，不得只标注“废弃”而保留残余引用。
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
10. **修订记录完整**：每次设计迭代必须在产物头部的 `修订记录` 表追加一行，包含版本号、日期、修订人、变更要点（精确到章节号），避免靠 Git 历史反推。
11. **Story 拆解一致性**：§工作量章节中的 Story 数、Wave 数必须与 §分阶段落地章节一一对应；不一致视为设计缺陷。
12. **决策与产物形态对齐**：ADR 的结论必须反映在对应章节（架构图、模块表、流程图、落地阶段）中；孤立的 ADR 未回写到其他章节视为未落地。

## 协议约定

- **文件系统协议**：Agent 间通过 Markdown/YAML 文件交换信息，不依赖隐式推理传递
- **单写规则**：同一核心对象同一时刻只允许一个主要写入方
- **回写规则**：每一阶段结束必须回写 `STATE.md`
- **变更规则**：需求或设计变动必须先创建 `CR-*.md` 再修改正式对象
- **人工检查点**：所有人工确认统一由 meta-po 发起，通过 `ask_user` 工具触发
- **HLD 门控**：`HLD.md` 未确认前，不得进入 Story 拆解
- **LLD 门控**：`STORY-{id}-{story_slug}-LLD.md` 未确认前，不得开始对应 Story 的实现
- **Skill 模板关系维护**：创建或修改 Agent、Skill 或 Skill 私有模板时，若影响调用、适用、归属或模板交叉引用关系，必须同步更新 `skills/README.md`
- **交付脚本边界**：`delivery/scripts/` 只允许安装器入口；任何被 Skill 运行时引用的脚本必须放到 `delivery/skills/<skill>/scripts/`
- **Skill 资产同树安装**：active Skill 引用的 `templates/`、`scripts/`、`schemas/`、`examples/` 资产必须与 Skill 同树存放，并使用 Skill 相对路径或 `<skill-root>/...` 表达
- **脚本安装验证**：active Skill 一旦新增脚本资产，必须验证 Claude Code / Codex 在 project 与 user scope 下安装后可直接执行
- **缓存文件禁入库**：`__pycache__/`、`*.pyc` 及其他解释器生成缓存不是交付物，不得提交
- **护栏静态检查**：提交前必须运行 `uv run --python 3.11 python scripts/check_delivery_guardrails.py`
- **调研前置**：meta-pm 在场景发现前执行阶段零快速调研，记录至 CLARIFICATION-LOG.md
- **模式默认值**：若用户未显式声明“meta 工作流优化 / 自我开发”，工作流默认 `engagement_mode=production`
- **场景主体默认值**：若用户未显式声明 meta 优化，`USE-CASES.md` 默认 `scenario_subject_type=target-artifact`，不得把当前仓库 / 当前工作流当成默认场景主体
- **确定性语言**：meta-se 与 meta-dev 产出使用确定性动词（创建/修改/删除）和量化条件，禁止模糊表述
- **就绪检查**：meta-dev 开始实现前必须通过 Story 卡片完整性检查并确认 LLD 已获批
- **测试策略前置**：meta-qa 验收前先输出 TEST-STRATEGY.md，指导验证过程
- **方案收敛优先**：涉及方案设计、整改规划或跨平台治理时，默认优先最简方案与内联策略；除非事实或验收要求证明不足，不新增共享模板体系或多余抽象层
- **精确匹配优先**：涉及对象定位、版本对齐、规则命中或平台路径判定时，默认采用 exact 语义，不使用模糊匹配作为默认行为

## 防火墙测试工作流（现有，独立运行）

> 本项目同时保留原有防火墙测试元工作流说明，两套系统并行存在，互不干扰。
> 当前统一编排入口：`.agents/agents/meta-po.md`

## LLD 消费契约补充

- `STORY-*-LLD.md` 必须保持 **14 个可见章节**；`Tier-S` 只允许简化内容深度，不允许压缩章节数量。
- `tier`、`shared_fragments`、`open_items` 是强输入字段，meta-dev / meta-qa 不得跳过。
- meta-dev 至少消费：文件影响范围、接口设计、异常处理、测试设计、实施步骤、回滚策略。
- meta-qa 至少消费：接口设计、核心流程、测试设计、回滚策略、OPEN/Spike 状态。

## Review Gate 分派与灰度

| Lane | Agent | 主要职责 |
|------|-------|----------|
| `lane-product` | `meta-pm` | 场景、画像、指标与范围一致性 |
| `lane-architecture` | `meta-se` | 设计边界、依赖、ADR 与阶段一致性 |
| `lane-implementation` | `meta-dev` | 可实现性、文件归属、平台约束 |
| `lane-quality` | `meta-qa` | 可验证性、风险、安全、安装约束 |
| `lane-docs` | `meta-doc` | 面向用户的可读性与交付完整性 |

灰度顺序：

1. 先覆盖 `HLD.md` 与 `STORY-*-LLD.md`
2. 再覆盖 `ARCHITECTURE-DECISION.md` 与 `STORY-BACKLOG.md`
3. 最后覆盖 `README.md`、`USER-MANUAL.md` 等交付文档
