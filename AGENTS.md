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
- **项目初始化**：创建 `.workflow-meta/` 目录及所有信息流转文件（STATE.md、REQUEST.md 等）
- 初始化 `.workflow-meta/STATE.md` 并维护全程状态
- 发起人工检查点（共 4 个：需求确认、方案选择确认、Story 计划确认、终验）
- 唤醒和收敛下游功能 Agent
- 受理变更请求，创建 `changes/CR-*.md`

## 功能 Agent（按需唤醒，由 meta-po 调度）

| Agent | 提示词文件 | 职责 | 唤醒条件 |
|-------|-----------|------|---------|
| **meta-pm** | `.agents/agents/meta-pm.md` | 场景发现（USE-CASES.md）+ 需求澄清与结构化（REQUIREMENTS.md） | 新请求进入、需求模糊、需求变更后重整 |
| **meta-se** | `.agents/agents/meta-se.md` | 多方案设计（≥2 个方案 + Mermaid 流程图）+ Story 拆解与并行计划 | REQUIREMENTS.md 已确认（solution-design 和 story-planning 两个阶段均由 meta-se 执行） |
| ~~**meta-dm**~~ | ~~`.agents/agents/meta-dm.md`~~ | ~~Story 拆解与并行计划~~ | ⚠️ **已废弃**，职责合并至 meta-se |
| **meta-dev** | `.agents/agents/meta-dev.md` | Agent/Skill 文件实现 | 存在已批准且可执行的 Story |
| **meta-qa** | `.agents/agents/meta-qa.md` | Story 验证与平台打包 | Story 进入 ready-for-verification + VALIDATION-ENV.yaml 已就绪 |
| **meta-doc** | `.agents/agents/meta-doc.md` | README 与 USER-MANUAL 输出 | 核心产物已验证且包清单稳定 |

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
| `.workflow-meta/` | 运行时对象文件 |
| `.workflow-meta/STATE.md` | 工作流运行时状态（meta-po 维护） |
| `.workflow-meta/REQUEST.md` | 用户原始请求 |
| `.workflow-meta/USE-CASES.md` | 场景文档（meta-pm 产出） |
| `.workflow-meta/REQUIREMENTS.md` | 结构化需求（meta-pm 产出） |
| `.workflow-meta/SOLUTION-OPTIONS.md` | 多方案对比（meta-se 产出） |
| `.workflow-meta/SOLUTION-DESIGN.md` | 选定方案描述（meta-se 产出） |
| `.workflow-meta/ARCHITECTURE-DECISION.md` | 架构决策（meta-se 产出） |
| `.workflow-meta/STORY-BACKLOG.md` | Story 列表（meta-se 产出） |
| `.workflow-meta/DEVELOPMENT-PLAN.yaml` | Wave 执行计划（meta-se 产出） |
| `.workflow-meta/templates/` | 所有对象的标准模板 |
| `.workflow-meta/stories/` | Story 卡片（STORY-*.md） |
| `.workflow-meta/changes/` | 变更单（CR-*.md） |
| `.workflow-meta/packages/` | 各平台安装包输出 |
| `.agents/agents/` | Agent 提示词文件 |
| `.agents/skills/` | Skill 定义文件 |

## 协议约定

- **文件系统协议**：Agent 间通过 Markdown/YAML 文件交换信息，不依赖隐式推理传递
- **单写规则**：同一核心对象同一时刻只允许一个主要写入方
- **回写规则**：每一阶段结束必须回写 `STATE.md`
- **变更规则**：需求或方案变动必须先创建 `CR-*.md` 再修改正式对象
- **人工检查点**：所有人工确认统一由 meta-po 发起，通过 `ask_user` 工具触发
- **上下文预算**：meta-po 持有的上下文不超过总窗口的 30%

## 防火墙测试工作流（现有，独立运行）

> 本项目同时保留原有防火墙测试元工作流（`.fw-meta/`），两套系统并行存在，互不干扰。
> 防火墙测试工作流入口：`.agents/agents/meta-orchestrator.md`
