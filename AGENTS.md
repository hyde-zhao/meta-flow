# SCOPE-Pack 元工作流 — Agent 声明

> 本项目运行 **SCOPE-Pack** 通用 Agent/Skill 工作流产物工厂。
> 主编排器为 **meta-po**，所有任务统一由 meta-po 发起并协调。

---

## 主编排器

| 字段 | 值 |
|------|----|
| 角色名称 | meta-po（元工作流产品负责人） |
| 提示词文件 | `.agents/agents/meta-po.md` |
| 触发词 | 开始、新建工作流、需求变更、推进、当前状态、继续、回退 |
| 始终激活 | 是 |

meta-po 的职责：
- **项目初始化**：创建 `.output/` 工作目录及所有信息流转文件
- 初始化 `.output/STATE.md` 并维护全程状态
- **先理解，后行动**：退出条件先验、上下文先行、追问优先于假设、状态一致性校验
- 发起人工检查点（共 4 个：需求确认、方案选择确认、Story 计划确认、终验）
- 唤醒和收敛下游功能 Agent（机器可验证退出条件）
- 受理变更请求，创建 `changes/CR-*.md`，执行五维度影响分析
- **失败模式识别**：识别需求循环、方案僵局、开发卡顿等常见失败信号

## 功能 Agent（按需唤醒，由 meta-po 调度）

| Agent | 提示词文件 | 职责 | 唤醒条件 |
|-------|-----------|------|---------|
| **meta-pm** | `.agents/agents/meta-pm.md` | 快速调研（阶段零）+ 场景发现（USE-CASES.md，含画像/指标）+ 需求结构化（REQUIREMENTS.md，含风险/里程碑）+ 完整性自检 | 新请求进入、需求模糊、需求变更后重整 |
| **meta-se** | `.agents/agents/meta-se.md` | 多方案设计（≥2 方案 + 5 层架构 Mermaid 图 + 技术选型理由）+ Story 拆解（含文件布局 + TASK-ID 任务清单）+ 开发计划（含完成准则） | REQUIREMENTS.md 已确认（solution-design 和 story-planning 两阶段均由 meta-se 执行） |
| ~~**meta-dm**~~ | ~~`.agents/agents/meta-dm.md`~~ | ~~Story 拆解与并行计划~~ | ⚠️ **已废弃**，职责合并至 meta-se |
| **meta-dev** | `.agents/agents/meta-dev.md` | 就绪检查 + Agent/Skill 文件实现 + TASK-ID 增量追踪 + 偏差记录 | 存在已批准且可执行的 Story |
| **meta-qa** | `.agents/agents/meta-qa.md` | TEST-STRATEGY.md 输出（ISTQB/ISO 25010）+ 8 维度验收 + 质量门控 + 平台打包 | Story 进入 ready-for-verification + VALIDATION-ENV.yaml 已就绪 |
| **meta-doc** | `.agents/agents/meta-doc.md` | README（含架构概览 + 用户旅程）+ USER-MANUAL（含故障排除）+ 严重度分级文档缺口 | 核心产物已验证且包清单稳定 |

## 工作流阶段与 Agent 对应关系

```
init（meta-po）
 └─► requirement-clarification（meta-pm：场景发现 → 需求结构化）  [检查点①]
      └─► solution-design（meta-se：输出≥2个备选方案）            [检查点②]
           └─► story-planning（meta-se：按选定方案拆解 Story）     [检查点③]
                └─► story-execution（Wave 循环）
                │    Wave 内并行：STORY-A [meta-dev→meta-qa] ‖ STORY-B [meta-dev→meta-qa]
                │    同一 Story 内串行：meta-dev 完成后 meta-qa 才介入
                └─► documentation（meta-doc）                      [检查点④]
                     └─► delivered
```

## 工作目录约定

| 目录 / 文件 | 用途 |
|------------|------|
| **`.output/`** | **产物输出 + 工作流运行时状态（统一输出目录）** |
| `.output/STATE.md` | 工作流运行时状态（meta-po 维护） |
| `.output/REQUEST.md` | 用户原始请求 |
| `.output/USE-CASES.md` | 场景文档（meta-pm 产出） |
| `.output/REQUIREMENTS.md` | 结构化需求（meta-pm 产出） |
| `.output/SOLUTION-OPTIONS.md` | 多方案对比（meta-se 产出） |
| `.output/SOLUTION-DESIGN.md` | 选定方案描述（meta-se 产出） |
| `.output/ARCHITECTURE-DECISION.md` | 架构决策（meta-se 产出） |
| `.output/STORY-BACKLOG.md` | Story 列表（meta-se 产出） |
| `.output/DEVELOPMENT-PLAN.yaml` | Wave 执行计划（meta-se 产出，含完成准则） |
| `.output/TEST-STRATEGY.md` | 测试策略（meta-qa 产出，ISTQB/ISO 25010） |
| `.output/templates/` | 所有对象的标准模板 |
| `.output/stories/` | Story 卡片（STORY-*.md） |
| `.output/changes/` | 变更单（CR-*.md） |
| `.output/packages/` | 各平台安装包输出 |
| `.output/agents/` | **产物 Agent 提示词文件**（meta-dev 产出） |
| `.output/skills/` | **产物 Skill 定义文件**（meta-dev 产出） |
| `.output/scripts/` | **产物工具脚本**（meta-dev 产出） |
| `.output/.github/agents/` | **产物 Copilot CLI 入口**（meta-dev 产出） |
| `.output/README.md` | 产物 README（meta-doc 产出） |
| `.output/USER-MANUAL.md` | 产物用户手册（meta-doc 产出） |
| `.agents/agents/` | 元工作流 Agent 提示词文件（meta-po/pm/se/dev/qa/doc） |
| `.agents/skills/` | 元工作流 Skill 定义文件（SCOPE-Pack 内置） |

### 输出隔离原则

> **所有由元工作流产生的产物必须输出到 `.output/` 目录。**
> `.agents/` 和 `.github/` 仅存放元工作流自身的定义文件，不得被产物污染。
> 测试时可在 `.output/` 目录中独立启动 Agent 加载产物文件验证。

## 协议约定

- **文件系统协议**：Agent 间通过 Markdown/YAML 文件交换信息，不依赖隐式推理传递
- **单写规则**：同一核心对象同一时刻只允许一个主要写入方
- **回写规则**：每一阶段结束必须回写 `STATE.md`
- **变更规则**：需求或方案变动必须先创建 `CR-*.md` 再修改正式对象
- **人工检查点**：所有人工确认统一由 meta-po 发起，通过 `ask_user` 工具触发
- **上下文预算**：meta-po 持有的上下文不超过总窗口的 30%
- **调研前置**：meta-pm 在场景发现前执行阶段零快速调研，记录至 CLARIFICATION-LOG.md
- **确定性语言**：meta-se 产出使用确定性动词（创建/修改/删除）和量化条件，禁止模糊表述
- **就绪检查**：meta-dev 开始实现前必须通过 Story 卡片完整性检查
- **测试策略前置**：meta-qa 验收前先输出 TEST-STRATEGY.md，指导验证过程

## 防火墙测试工作流（现有，独立运行）

> 本项目同时保留原有防火墙测试元工作流（`.fw-meta/`），两套系统并行存在，互不干扰。
> 防火墙测试工作流入口：`.agents/agents/meta-orchestrator.md`
