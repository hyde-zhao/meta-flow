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

- **项目初始化**：创建 `.meta-workflow/` 工作目录及所有信息流转文件
- 初始化 `.meta-workflow/process/STATE.md` 并维护全程状态
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
| **`.meta-workflow/`** | **工作流运行根目录（process/checkpoints/delivery）** |
| `.meta-workflow/process/STATE.md` | 工作流运行时状态（meta-po 维护） |
| `.meta-workflow/process/REQUEST.md` | 用户原始请求 |
| `.meta-workflow/process/USE-CASES.md` | 场景文档（meta-pm 产出） |
| `.meta-workflow/process/REQUIREMENTS.md` | 结构化需求（meta-pm 产出） |
| `.meta-workflow/process/HLD.md` | 高层设计过程稿（meta-se 产出） |
| `.meta-workflow/process/ARCHITECTURE-DECISION.md` | 架构决策（meta-se 产出） |
| `.meta-workflow/process/STORY-BACKLOG.md` | Story 列表（meta-se 产出） |
| `.meta-workflow/process/DEVELOPMENT-PLAN.yaml` | Wave 执行计划（meta-se 产出，含完成准则） |
| `.meta-workflow/process/TEST-STRATEGY.md` | 测试策略（meta-qa 产出，ISTQB/ISO 25010） |
| `skills/<skill-name>/templates/` | Skill 私有模板目录（仅单个 Skill 内部初始化 / 渲染使用） |
| `.meta-workflow/checkpoints/` | 人工确认稿（REQUIREMENTS/HLD/STORY-PLAN/STORY-LLD） |
| `.meta-workflow/process/stories/` | Story 卡片（STORY-*.md）与 Story 级 LLD（STORY-*-LLD.md） |
| `.meta-workflow/process/changes/` | 变更单（CR-*.md） |
| `.meta-workflow/delivery/scripts/install.*` | 各平台安装脚本输出 |
| `.meta-workflow/delivery/rules/` | 各平台规则文件输出 |
| `.meta-workflow/delivery/agents/` | **产物 Agent 提示词文件**（meta-dev 产出） |
| `.meta-workflow/delivery/skills/` | **产物 Skill 定义文件**（meta-dev 产出） |
| `agents/` | 根目录交付 Agent 源目录 |
| `skills/` | 根目录交付 Skill 源目录 |
| `rules/` | 根目录交付规则源目录 |
| `.meta-workflow/delivery/scripts/*.py` | **产物工具脚本**（meta-dev 产出） |
| `.meta-workflow/delivery/.github/agents/` | **产物 Copilot CLI 入口**（meta-dev 产出） |
| `.meta-workflow/delivery/README.md` | 产物 README（meta-doc 产出） |
| `.meta-workflow/delivery/doc/USER-MANUAL.md` | 产物用户手册（meta-doc 产出） |
| `.agents/agents/` | 元工作流 Agent 提示词文件（meta-po/pm/se/dev/qa/doc） |
| `.agents/skills/` | 元工作流 Skill 定义文件（SCOPE-Pack 内置） |

### 输出隔离原则

> **所有由元工作流产生的文件必须输出到 `.meta-workflow/`，并按 process/checkpoints/delivery 分层。**
> 根目录 `agents/`、`skills/`、`rules/` 为交付源目录；`.agents/` 和 `.github/` 仍保留元工作流自身定义。
> 测试时可在 `.meta-workflow/delivery/` 目录中独立启动 Agent 加载产物文件验证。

## 方案编写与修订规则

1. **先核对事实，再写方案**：平台路径、发现面、配置位置和行为约束，必须以当前仓库实现与官方文档为准；发现旧假设错误时，先修正事实判断，再扩展方案。
2. **优先最简方案**：默认选择能满足目标的最小设计，避免为“统一”额外引入新抽象层、共享运行时或重复形态；若必须保留备选方案，应说明何时切换。
3. **废弃内容要彻底删除**：已确认废弃的目录、路径变量、章节、实施步骤和验收项，不得只标注“废弃”而保留残余引用。
4. **问题必须状态化**：阻塞问题、遗留问题和开放问题必须逐项标注状态（如已解答、部分解答、待整改），并在方案修订时同步刷新。
5. **主选与备选并存**：已确认主选方案时，实施文档应同时记录主选值、备选方案和切换条件，避免后续重复讨论同一决策。
6. **问题描述必须完整**：方案中的问题条目不能只有标题，至少应说明背景、触发条件、影响范围、为何是问题以及需要谁决策。
7. **目录设计要分层**：过程文档、人工检查点文档、交付文档应分区描述，避免把运行态、检查态和交付态混写为同一输出面。
8. **稳定偏好才能升格为共享规则**：只有已经稳定、适合团队复用的偏好才能进入仓库共享规范；明显属于个人工作习惯的内容不应直接写入共享规则。

## 协议约定

- **文件系统协议**：Agent 间通过 Markdown/YAML 文件交换信息，不依赖隐式推理传递
- **单写规则**：同一核心对象同一时刻只允许一个主要写入方
- **回写规则**：每一阶段结束必须回写 `STATE.md`
- **变更规则**：需求或设计变动必须先创建 `CR-*.md` 再修改正式对象
- **人工检查点**：所有人工确认统一由 meta-po 发起，通过 `ask_user` 工具触发
- **HLD 门控**：`HLD.md` 未确认前，不得进入 Story 拆解
- **LLD 门控**：`STORY-{id}-LLD.md` 未确认前，不得开始对应 Story 的实现
- **Skill 模板关系维护**：创建或修改 Agent、Skill 或 Skill 私有模板时，若影响调用、适用、归属或模板交叉引用关系，必须同步更新 `skills/README.md`
- **调研前置**：meta-pm 在场景发现前执行阶段零快速调研，记录至 CLARIFICATION-LOG.md
- **确定性语言**：meta-se 与 meta-dev 产出使用确定性动词（创建/修改/删除）和量化条件，禁止模糊表述
- **就绪检查**：meta-dev 开始实现前必须通过 Story 卡片完整性检查并确认 LLD 已获批
- **测试策略前置**：meta-qa 验收前先输出 TEST-STRATEGY.md，指导验证过程
- **方案收敛优先**：涉及方案设计、整改规划或跨平台治理时，默认优先最简方案与内联策略；除非事实或验收要求证明不足，不新增共享模板体系或多余抽象层
- **精确匹配优先**：涉及对象定位、版本对齐、规则命中或平台路径判定时，默认采用 exact 语义，不使用模糊匹配作为默认行为

## 防火墙测试工作流（现有，独立运行）

> 本项目同时保留原有防火墙测试元工作流说明，两套系统并行存在，互不干扰。
> 当前统一编排入口：`.agents/agents/meta-po.md`

