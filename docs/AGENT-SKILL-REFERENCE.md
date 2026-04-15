# SCOPE-Pack Agent/Skill 使用参考手册

本文档是 SCOPE-Pack 元工作流系统中 Agent 与 Skill 的当前参考说明。

> 📖 安装方法见 [`USER_GUIDE.md`](./USER_GUIDE.md)

---

## 目录

1. Agent 使用参考
2. Skill 使用参考
3. 典型流程与检查点
4. 运行时文件与状态

---

## 一、Agent 使用参考

当前仓库中有 **7 个 Agent 文件**，其中 `meta-dm` 已废弃，仅作为兼容占位保留。实际主流程由 `meta-po / meta-pm / meta-se / meta-dev / meta-qa / meta-doc` 协作完成。

### `meta-po` — 主编排器

| 项目 | 说明 |
|------|------|
| 职责 | 初始化 `.output/`、推进阶段、触发人工检查点、路由变更 |
| 触发方式 | `@meta-po`、开始、新建工作流、推进、当前状态、继续、回退、需求变更 |
| 不负责 | 直接写需求、HLD、LLD、代码或文档 |

### `meta-pm` — 需求澄清专家

| 项目 | 说明 |
|------|------|
| 职责 | 场景发现、需求澄清、输出 `USE-CASES.md` 与 `REQUIREMENTS.md` |
| 触发阶段 | `requirement-clarification` |
| 不负责 | 设计决策、状态推进 |

### `meta-se` — 架构设计师

| 项目 | 说明 |
|------|------|
| 职责 | 输出 `HLD.md`、等待人工确认、再拆解 Story 与开发计划 |
| 触发阶段 | `solution-design`、`story-planning` |
| 关键约束 | `HLD.md` 未确认前不得拆解 Story |

### `meta-dm` — 兼容占位 Agent（已废弃）

| 项目 | 说明 |
|------|------|
| 状态 | 已废弃 |
| 现状 | 职责已合并进 `meta-se` |
| 说明 | 平台包中可能仍保留该文件用于兼容旧安装结构 |

### `meta-dev` — 开发工程师

| 项目 | 说明 |
|------|------|
| 职责 | 为每个 Story 先输出 `STORY-{id}-LLD.md`，经人工确认后再实现产物 |
| 触发阶段 | `story-execution` |
| 关键约束 | LLD 未确认前不得开始实现 |

### `meta-qa` — 质量工程师

| 项目 | 说明 |
|------|------|
| 职责 | 输出测试策略、执行验证、生成包清单与安装包 |
| 触发条件 | Story 进入 `ready-for-verification` 且验证环境可用 |
| 输出 | `TEST-STRATEGY.md`、`VERIFICATION-REPORT.md`、`PACKAGE-MANIFEST.yaml` |

### `meta-doc` — 文档工程师

| 项目 | 说明 |
|------|------|
| 职责 | 在验证通过后整理 README 与用户手册 |
| 触发阶段 | `documentation` |
| 输出 | `.output/README.md`、`.output/USER-MANUAL.md` |

---

## 二、Skill 使用参考

当前仓库内共有 **30 个通用 Skill**。它们统一位于 `.agents/skills/<skill-name>/SKILL.md`，由触发词自动激活。

### 1. 需求分析类

| Skill | 触发词 | 用途 |
|------|--------|------|
| `requirement-extraction` | 提取需求、整理需求、结构化需求、需求分析 | 将自然语言需求转成结构化需求 |
| `requirement-clarifier` | 澄清需求、需求问题、未决问题、需求歧义 | 通过多轮问题消除需求歧义 |
| `scenario-expansion` | 展开场景、生成场景、测试场景、场景扩展 | 把需求展开成场景 |
| `scope-normalization` | 归一化需求、去重、合并需求、范围整理 | 合并、去重和清理需求边界 |

### 2. 设计与规划类

| Skill | 触发词 | 用途 |
|------|--------|------|
| `solution-designer` | 方案设计、架构设计、复杂度判定、设计方案 | 历史兼容入口，现统一落到 HLD 方案比较 |
| `hld-designer` | HLD、高层设计、架构评审、架构方案 | 生成可评审的 `HLD.md` |
| `lld-designer` | LLD、详细设计、实现设计、Story 设计 | 为单个 Story 生成 `STORY-{id}-LLD.md` |
| `phase-designer` | 阶段划分、设计阶段、Phase 设计、执行顺序 | 划分执行阶段 |
| `dependency-mapper` | 依赖关系、DAG、任务依赖、前置依赖 | 建立任务依赖关系 |
| `wave-planner` | 并行分组、Wave 划分、并行计划、任务编排 | 规划并行 Wave |
| `story-manager` | 拆分 Story、Story 状态、Story 卡片、Story 管理 | 生成和维护 Story 生命周期 |
| `dag-validator` | DAG 校验、依赖校验、循环依赖检查 | 检查开发计划无环 |

### 3. 交付与文档类

| Skill | 触发词 | 用途 |
|------|--------|------|
| `claude-agent-writer` | 写 Claude Agent、创建 Claude 子代理 | 输出 Claude Agent 规范 |
| `copilot-agent-writer` | 写 Copilot Agent、创建自定义 Agent | 输出 Copilot Agent 规范 |
| `file-to-markdown` | 转换文件、转为MD、文件转换 | 将外部文件转成 Markdown |
| `package-builder` | 打包、生成安装包、平台打包 | 生成平台安装包 |
| `platform-validator` | 校验安装包、平台验证、结构校验 | 检查安装包目录结构 |
| `workflow-renderer` | 渲染工作流、生成文档、交付文档 | 将工作流产物渲染为文档 |
| `context-handoff` | 上下文交接、装配上下文、阶段切换 | 为下游 Agent 准备最小上下文 |
| `context-manifest-builder` | 上下文清单、执行上下文、CONTEXT-MANIFEST | 生成上下文清单 |

### 4. 质量与安全类

| Skill | 触发词 | 用途 |
|------|--------|------|
| `coverage-checker` | 覆盖率检查、场景覆盖、未覆盖场景 | 检查场景覆盖度 |
| `dangerous-command-scan` | 危险命令、命令扫描、安全扫描 | 扫描高风险命令 |
| `permission-boundary-check` | 权限检查、权限边界、越权验证 | 检查越权风险 |
| `runtime-risk-review` | 运行时风险、DryRun、执行环境 | 审查运行时风险 |
| `regression-subset-builder` | 回归测试、最小回归集、回归范围 | 生成最小回归验证范围 |
| `run-feedback-parser` | 执行反馈、提交反馈、记录执行结果 | 固化执行反馈 |

### 5. 变更与问题管理类

| Skill | 触发词 | 用途 |
|------|--------|------|
| `change-impact-analysis` | 需求变更、修改需求、变更影响、发起变更 | 生成 CR 并分析影响 |
| `issue-drafter` | 起草问题、创建 ISSUE、问题工单 | 起草问题单 |
| `issue-routing` | 路由问题、分配问题、ISSUE 路由 | 对问题单分类与路由 |
| `state-router` | 推进、下一步、当前状态、回退、状态查询 | 查询状态并给出下一步 |

---

## 三、典型流程与检查点

### 标准主流程

```text
init
  → requirement-clarification
  → solution-design（输出 HLD）
  → HLD 人工确认
  → story-planning
  → story-execution（逐 Story：LLD 起草 → LLD 确认 → 实现 → 验证）
  → documentation
  → delivered
```

### 5 类人工检查点

| 检查点 | 触发时机 | 用户需要确认 |
|--------|---------|-------------|
| 需求确认 | `REQUIREMENTS.md` 完成后 | 需求是否完整、无歧义 |
| HLD 确认 | `HLD.md` 完成后 | 高层设计是否允许进入 Story 规划 |
| Story 计划确认 | `STORY-BACKLOG.md` 完成后 | Story 边界、优先级、Wave 分组 |
| Story LLD 确认 | `STORY-{id}-LLD.md` 完成后 | 当前 Story 是否允许进入实现 |
| 终验 | 文档与平台包齐备后 | 交付范围是否完整 |

### Story 生命周期

```text
draft → approved → ready-for-lld-review → lld-approved → in-development → ready-for-verification → verified → done
```

### 直接对话示例

```text
用户：请启动一个新的复杂工作流项目，先澄清需求，再输出 HLD，确认后拆 Story。

meta-po：初始化 .output/，唤醒 meta-pm。
meta-pm：完成 USE-CASES.md / REQUIREMENTS.md。
meta-po：[检查点1] 请确认需求。
用户：确认。
meta-se：输出 HLD.md。
meta-po：[检查点2] 请确认 HLD。
用户：确认。
meta-se：输出 STORY-BACKLOG.md / DEVELOPMENT-PLAN.yaml / STORY-*.md。
meta-po：[检查点3] 请确认 Story 计划。
用户：确认。
meta-dev：先输出 STORY-001-LLD.md。
meta-po：[检查点4] 请确认 STORY-001 的 LLD。
用户：确认。
meta-dev：开始实现 STORY-001。
meta-qa：验证通过。
meta-doc：整理 README.md 和 USER-MANUAL.md。
meta-po：[检查点5] 请终验。
```

---

## 四、运行时文件与状态

### 运行时目录

```text
.output/
├── STATE.md
├── REQUEST.md
├── USE-CASES.md
├── REQUIREMENTS.md
├── HLD.md
├── ARCHITECTURE-DECISION.md
├── STORY-BACKLOG.md
├── DEVELOPMENT-PLAN.yaml
├── TEST-STRATEGY.md
├── VERIFICATION-REPORT.md
├── PACKAGE-MANIFEST.yaml
├── stories/
│   ├── STORY-001.md
│   ├── STORY-001-LLD.md
│   └── ...
├── changes/
└── packages/
```

### 关键文件说明

| 文件 | 创建方 | 作用 | 是否人工确认 |
|------|--------|------|-------------|
| `REQUEST.md` | meta-po | 记录用户原始请求 | 否 |
| `USE-CASES.md` | meta-pm | 场景文档 | 否 |
| `REQUIREMENTS.md` | meta-pm | 结构化需求 | 是 |
| `HLD.md` | meta-se | 高层设计文档 | 是 |
| `ARCHITECTURE-DECISION.md` | meta-se | 架构决策与约束 | 否 |
| `STORY-BACKLOG.md` | meta-se | Story 列表 | 是 |
| `DEVELOPMENT-PLAN.yaml` | meta-se | Wave 与依赖计划 | 否 |
| `stories/STORY-*.md` | meta-se | Story 卡片 | 否 |
| `stories/STORY-*-LLD.md` | meta-dev | Story 级 LLD | 是 |
| `TEST-STRATEGY.md` | meta-qa | 测试策略 | 否 |
| `VERIFICATION-REPORT.md` | meta-qa | 验证报告 | 否 |
| `PACKAGE-MANIFEST.yaml` | meta-qa | 打包清单 | 否 |

### `STATE.md` 中最重要的字段

| 字段 | 含义 |
|------|------|
| `current_phase` | 当前阶段 |
| `current_agent` | 当前负责 Agent |
| `blocked` | 是否阻塞 |
| `history` | 历史状态变更 |

### 状态推进原则

1. `REQUIREMENTS.md` 未确认，不进入设计阶段
2. `HLD.md` 未确认，不进入 Story 拆解
3. `STORY-{id}-LLD.md` 未确认，不进入该 Story 的实现
4. 验证环境未准备好，meta-qa 不开始验证
5. 验证和打包未完成，meta-doc 不输出最终交付文档
