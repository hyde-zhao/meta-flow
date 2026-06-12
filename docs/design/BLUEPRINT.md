---
status: baseline
version: "1.0"
source_story_map: "process/STORY-BACKLOG.md"
source_mvp_scope: "AGENTS.md"
confirmed_by: "meta-po"
confirmed_at: "2026-06-07"
---

# Meta Flow Blueprint

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-07 | meta-po | 基于 AGENTS、delivery 规则、legacy HLD、ADR 和 CR-005 至 CR-018 建立正式设计基线 |
| 1.1 | 2026-06-11 | host-orchestrator | 新增 workflow eval governance 能力域，修正 Host Orchestrator 编排表述 |

## 1. 蓝图定位

本蓝图定义 Meta Flow v2 的长期工程能力边界。它不是单个 Story 的实现设计，也不替代 `process/STATE.md`、CP 检查点或运行日志。

正式消费顺序：

1. `docs/design/BLUEPRINT.md` 定义能力边界和数据归属。
2. `docs/design/DOMAIN-MAP.md` 定义领域对象、状态和规则。
3. `docs/design/DEPENDENCY-MAP.md` 定义允许依赖和禁止依赖。
4. `docs/design/HLD.md` 定义总体架构和关键流程。
5. `docs/design/ARCHITECTURE-DECISION.md` 记录当前仍有效的 ADR。
6. `docs/design/FEATURE-DESIGN-MATRIX.md` 判定 Feature 级设计和 LLD 深度。

## 2. 能力地图

| Capability ID | 能力域 | 用户价值 | 覆盖对象 | Owner Feature |
|---|---|---|---|---|
| CAP-01 | 工作流编排与状态推进 | 用户只需在主进程 Host Orchestrator 中推进复杂工作流，阶段、门禁和回退可追溯 | `STATE.md`、CP0-CP8、handoff、CR | FEAT-WORKFLOW-ORCHESTRATION |
| CAP-02 | 场景发现与需求结构化 | 标准模式下先发现真实使用场景，再提取需求和验证场景 | `USE-CASES`、`REQUIREMENTS`、`SCENARIOS`、`TEST-MATRIX` | FEAT-SCENARIO-DISCOVERY |
| CAP-03 | 蓝图、HLD 与 ADR 设计 | 在 Story 拆解前明确能力边界、架构方案、关键决策和切换条件 | `BLUEPRINT`、`DOMAIN-MAP`、`DEPENDENCY-MAP`、`HLD`、`ADR` | FEAT-SOLUTION-DESIGN |
| CAP-04 | Feature 设计与 LLD 分级 | 只为高风险能力生成必要设计，低风险 Story 用技术说明或 waived 证据控制 token | `FEATURE-DESIGN-MATRIX`、`docs/features/*`、`STORY-*-LLD` | FEAT-DESIGN-EVIDENCE |
| CAP-05 | 人工门禁与决策收集 | CP2 / CP3 / CP5 / CP8 前统一收集用户必须决策的问题，避免漏问和误授权 | Decision Brief、`pending_human_decisions[]`、`process/checkpoints` | FEAT-HUMAN-GATE-DECISION-BRIEF |
| CAP-06 | 子 Agent 生命周期与上下文控制 | 子 Agent 按阶段自动调度，复用 / 关闭 / 证据记录可审计，默认 capsule-first 降低 token | `agent_lifecycle`、`process/context/*-CONTEXT.yaml`、handoff | FEAT-AGENT-LIFECYCLE-CONTEXT |
| CAP-07 | 实现、验证与回修闭环 | Story 实现前消费设计证据，CP6 / CP7 记录实现和验证证据，失败后路由回修 | `IMPLEMENTATION`、`VERIFICATION`、`TEST-REPORT`、`FIXES` | FEAT-IMPLEMENTATION-VERIFICATION |
| CAP-08 | 发布准备与交付文档 | 发布前按 profile 生成必要文档和风险分流，不默认执行真实发布 | `RELEASE-CONTEXT`、release docs、README、USER-MANUAL | FEAT-RELEASE-DOCUMENTATION |
| CAP-09 | 安装契约与交付护栏 | 保证 delivery 包可安装、路径正确、废弃资产不回流 | `PLATFORM-CONTRACTS`、install scripts、guardrail | FEAT-INSTALLER-GUARDRAILS |
| CAP-10 | 文档分层与交付出口路由 | 区分长期文档、过程文档、确认态和交付包，避免 production 项目被写入 meta-flow 自身交付面 | `docs/`、`process/`、`delivery/` | FEAT-DESIGN-DOCUMENT-LAYERING |
| CAP-11 | Workflow Eval 与 Prompt Bundle 治理 | 生成工作流、Prompt / Skill 与 mixed 产物可通过 schema、case、hash、runner evidence 和 suite health 验证 | `evals/contracts/*`、`PROMPT-BUNDLE.yaml`、`CASE-REGISTRY.yaml`、`process/evals/runs/*`、`docs/quality/EVAL-SUITE-HEALTH.md` | FEAT-WORKFLOW-EVAL-GOVERNANCE |

## 3. Feature / Epic 边界

| Feature ID | 名称 | 负责事项 | 不负责事项 | 拥有数据 | 只读数据 | 禁止依赖 |
|---|---|---|---|---|---|---|
| FEAT-WORKFLOW-ORCHESTRATION | 工作流编排 | 状态推进、阶段切换、CR 跟踪、检查点路由 | 直接替下游 Agent 完成阶段内专业产物 | `process/STATE.md`、`process/changes/*` | docs/design、docs/product、CP 文件 | 不得绕过 CP 门禁直接进入后续阶段 |
| FEAT-SCENARIO-DISCOVERY | 场景发现 | 阶段零调研、SGQ 用户可见确认、场景 / 需求 / 测试矩阵输入 | HLD、LLD、实现设计 | `docs/product/*` | `process/REQUEST.md`、CR | 不得用工程测试场景替代用户场景发现 |
| FEAT-SOLUTION-DESIGN | 蓝图与架构 | 蓝图、领域地图、依赖地图、HLD、ADR、Story Planning 输入 | Story 实现、验证执行 | `docs/design/BLUEPRINT.md`、`DOMAIN-MAP.md`、`DEPENDENCY-MAP.md`、`HLD.md`、`ARCHITECTURE-DECISION.md` | `docs/product/*`、discussion log | 不得在 CP3 前拆 Story |
| FEAT-DESIGN-EVIDENCE | 设计证据分级 | Feature 设计矩阵、Feature DESIGN、Story LLD / technical-note / waived 策略 | 代码修改和验证执行 | `docs/design/FEATURE-DESIGN-MATRIX.md`、`docs/features/*`、`process/stories/*-LLD.md` | HLD、ADR、Story | 不得为所有 Story 默认生成完整 LLD |
| FEAT-HUMAN-GATE-DECISION-BRIEF | 人工门禁 | Decision Brief、决策收集覆盖、统一确认消息、不授权项 | 阶段内自由讨论产物 | `process/checkpoints/*`、`STATE.md.human_gate_decisions` | CP 自动检查、下游开放问题 | 不得把 `approve` 解释为真实运行授权 |
| FEAT-AGENT-LIFECYCLE-CONTEXT | Agent 生命周期与上下文 | 子 Agent 调度证据、active registry、context capsule、inline fallback 门禁 | 具体业务产物内容 | `STATE.md.agent_lifecycle`、`process/context/*`、`process/handoffs/*` | docs/design、Story、CP 文件 | 不得把 handoff 当作下游 Agent 已执行 |
| FEAT-IMPLEMENTATION-VERIFICATION | 实现与验证 | 实现证据、验证证据、质量报告、回修闭环 | 架构重设计和范围变更 | `process/stories/*-IMPLEMENTATION.md`、`docs/quality/*` | LLD、Feature DESIGN、TEST-MATRIX | 不得在 CP5 前实现 Story |
| FEAT-RELEASE-DOCUMENTATION | 发布与文档 | Release Context、发布文档、README、USER-MANUAL、后续跟踪分流 | 未授权真实发布 | `docs/release/*`、`delivery/README.md`、`delivery/doc/USER-MANUAL.md` | QA 报告、CP8 | 不得默认生成 full profile 或执行 publish |
| FEAT-INSTALLER-GUARDRAILS | 安装与护栏 | 平台契约、安装脚本、资产生命周期、静态检查 | 目标项目业务测试 | `delivery/doc/PLATFORM-CONTRACTS.yaml`、`delivery/scripts/*`、`scripts/check_delivery_guardrails.py` | delivery agents / skills / rules | 不得按平台目录类比推断路径 |
| FEAT-DESIGN-DOCUMENT-LAYERING | 文档分层 | docs/process/delivery 路由、legacy fallback 边界、production 交付出口 | 具体 HLD 内容本身 | 本设计基线、规则说明 | 目标 README/docs | 不得把过程态文档当长期交付物 |
| FEAT-WORKFLOW-EVAL-GOVERNANCE | Workflow Eval 与 Prompt Bundle 治理 | eval schema、prompt bundle、case registry、本地 runner evidence、suite health、failure backlog、adapter 授权边界 | 目标项目业务逻辑、外部 SaaS 真实运行、CP7 最终放行裁决 | `evals/contracts/*`、`evals/fixtures/*`、`meta_flow/evals/*`、`docs/quality/EVAL-SUITE-HEALTH.md` | Story、verification-execution、meta-qa、目标项目测试结果 | 不得把 eval run PASS 直接等同 CP7 PASS |

## 4. 跨 Feature 流程

| Flow ID | 触发 | 参与 Feature | 数据写入 Owner | 失败路径 | 验证入口 |
|---|---|---|---|---|---|
| FLOW-01 | 新建标准工作流 | ORCHESTRATION -> SCENARIO -> SOLUTION -> DESIGN-EVIDENCE -> IMPLEMENTATION -> RELEASE | 各阶段 owner 单写 | CP 自动检查失败或人工 reject 回退到对应阶段 | CP0-CP8 |
| FLOW-02 | CP2 / CP3 / CP5 / CP8 人工确认 | HUMAN-GATE 读取阶段产物和自动检查 | HUMAN-GATE | Decision Brief 缺失或决策表未打印时阻断 | `meta-flow check human-gate` |
| FLOW-03 | 并行 LLD 写作 | DESIGN-EVIDENCE -> AGENT-LIFECYCLE -> HUMAN-GATE | DESIGN-EVIDENCE / STATE queue | `blocks_lld=true` 未回答时不得发起 CP5 | CP5 |
| FLOW-04 | CP7 验证失败 | IMPLEMENTATION-VERIFICATION -> ORCHESTRATION -> meta-dev 回修 | IMPLEMENTATION-VERIFICATION | 不得标记 verified，回修后重跑 CP6 / CP7 | CP6 / CP7 |
| FLOW-05 | 交付安装验证 | INSTALLER-GUARDRAILS -> RELEASE-DOCUMENTATION | INSTALLER-GUARDRAILS | guardrail / dry-run 失败时 CP8 不得 READY | guardrail、install dry-run |
| FLOW-06 | 文档路由 | DESIGN-DOCUMENT-LAYERING -> 所有 Feature | 对应文档 owner | production 项目缺少输出约定时先询问用户 | README/docs 扫描、CP8 |
| FLOW-07 | Workflow / Prompt 产物验证 | WORKFLOW-EVAL-GOVERNANCE -> IMPLEMENTATION-VERIFICATION -> RELEASE-DOCUMENTATION | WORKFLOW-EVAL-GOVERNANCE / docs/quality | eval suite FAIL 时不得把 CP7 标记 PASS；外部 adapter 缺授权时 N/A | `meta-flow eval validate/run/suite-health`、CP7 |

## 5. 共享能力

| Shared ID | 名称 | 使用方 | Owner | 调用方向 | 降级策略 |
|---|---|---|---|---|---|
| SH-01 | Context Capsule | meta-po、meta-se、meta-dev、meta-qa、meta-doc | FEAT-AGENT-LIFECYCLE-CONTEXT | 阶段 owner 生成，下游默认先读 | 缺字段时读取正式文档并记录 `read_expansion_log` |
| SH-02 | Decision Brief | meta-po、checkpoint-manager、各阶段 Agent | FEAT-HUMAN-GATE-DECISION-BRIEF | 下游写候选问题，meta-po 统一发起 | 缺失时人工门禁失败 |
| SH-03 | Platform Contracts | installer、platform-validator、guardrail、HLD / LLD | FEAT-INSTALLER-GUARDRAILS | 所有平台路径断言从该契约读取 | 契约缺失时不得类比推断 |
| SH-04 | Review Artifact Protocol | meta-po、meta-se、meta-dev、meta-qa、meta-doc | FEAT-WORKFLOW-ORCHESTRATION | reviewer lane 使用共享 findings / summary | 无法拉起 reviewer 时记录 N/A / inline fallback 门禁 |
| SH-05 | CR Tracking | meta-po、state-router、change-impact-analysis | FEAT-WORKFLOW-ORCHESTRATION | 变更先建 CR，再改正式对象 | 状态冲突时先展示冲突再推进 |
| SH-06 | Workflow Eval Evidence | meta-qa、verification-execution、quality-review、release-readiness | FEAT-WORKFLOW-EVAL-GOVERNANCE | runner 生成 evidence，CP7 / CP8 消费摘要 | suite FAIL 时写 failure backlog；外部 adapter 缺授权时 N/A |

## 6. 待确认边界

| Decision ID | 决策类型 | 问题 | 推荐方案 | 备选方案 | 推荐 / 备选优劣 | 影响 / 风险 | 回退 / 切换条件 |
|---|---|---|---|---|---|---|---|
| DQ-BP-001 | implementation | 是否为所有 Feature 立刻补 TEST-PLAN / TASKS | 暂不全量补，只为后续实际变更 Feature 增量生成 | 全量补齐 | 推荐方案节省 token 并降低维护成本；全量补齐初期完整但容易过时 | 若后续 Feature 进入实现改造，必须补齐对应 TEST-PLAN / TASKS | 某 Feature 出现代码改造、权限 / 安全 / 发布风险时切换为 required |

## 7. 自检

| 检查项 | 结果 | 证据 |
|---|---|---|
| 每个核心能力有 owner Feature | PASS | §2 / §3 |
| Feature 职责和非职责已区分 | PASS | §3 |
| 共享能力有单一 owner | PASS | §5 |
| 不新增未确认 Agent / Skill | PASS | 本蓝图只整理当前 v2 基线 |
