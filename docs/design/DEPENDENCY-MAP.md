---
status: baseline
version: "1.0"
confirmed_by: "meta-po"
confirmed_at: "2026-06-07"
---

# Meta Flow Dependency Map

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-07 | meta-po | 建立阶段、Agent、Skill、文档和交付资产依赖基线 |
| 1.1 | 2026-06-11 | host-orchestrator | 新增 workflow eval governance 依赖，修正 Host Orchestrator 编排依赖 |

## 1. 阶段依赖

| From | To | 依赖类型 | 允许方向 | 原因 | 验证 / 监控 |
|---|---|---|---|---|---|
| init | requirement-clarification | phase-order | allowed | 初始化状态、请求和输出路由后才能澄清需求 | CP0 |
| requirement-clarification | solution-design | phase-order | allowed | CP2 确认需求 / 场景 / 范围基线后才能设计 HLD | CP2 |
| solution-design | story-planning | phase-order | allowed | CP3 确认 HLD / ADR 后才能拆 Story | CP3 |
| story-planning | story-execution | phase-order | allowed | CP4 / CP5 通过后才能实现 | CP4 / CP5 |
| story-execution | documentation | phase-order | allowed | 实现和验证稳定后再写最终文档 | CP6 / CP7 |
| documentation | delivered | phase-order | allowed | CP8 交付就绪后进入 delivered | CP8 |

## 2. 正式工件依赖

| From | To | 依赖类型 | 允许方向 | 原因 | 验证 / 监控 |
|---|---|---|---|---|---|
| `REQUEST.md` | `USE-CASES.md` | input | allowed | 原始请求是场景发现输入 | CP1 |
| `USE-CASES.md` | `REQUIREMENTS.md` | derive | allowed | 需求必须从已确认场景提取 | CP1 / CP2 |
| `USE-CASES.md` / `REQUIREMENTS.md` | `SCENARIOS.yaml` / `TEST-MATRIX.md` | derive | allowed | 工程验证场景由产品场景和需求展开 | CP2 |
| `SCENARIOS.yaml` / `TEST-MATRIX.md` | `STORY-MAP.md` / `MVP-SCOPE.md` | planning | allowed | Story Map 和范围切片需要覆盖验证输入 | CP2 |
| `STORY-MAP.md` / `MVP-SCOPE.md` | `BLUEPRINT.md` / `DOMAIN-MAP.md` / `DEPENDENCY-MAP.md` | design | allowed | 蓝图从产品规划聚合 Feature / Epic 边界 | CP3 |
| `BLUEPRINT.md` / `DOMAIN-MAP.md` / `DEPENDENCY-MAP.md` | `HLD.md` / `ARCHITECTURE-DECISION.md` | design | allowed | HLD 消费边界、对象和依赖方向 | CP3 |
| `HLD.md` / `ARCHITECTURE-DECISION.md` | `FEATURE-DESIGN-MATRIX.md` | design | allowed | Feature 设计矩阵按架构风险判定设计深度 | CP4 |
| `FEATURE-DESIGN-MATRIX.md` | `docs/features/<feature>/DESIGN.md` | design | allowed | required Feature 需要冻结边界和契约 | CP4 |
| `FEATURE-DESIGN-MATRIX.md` / `docs/features/*` | `STORY-*-LLD.md` / Story 技术说明 / waived 证据 | design | allowed | Story 设计证据消费 Feature 设计策略 | CP5 |
| Story 设计证据 | Story 实现证据 | runtime | allowed | 实现必须消费已确认设计 | CP6 |
| Story 实现证据 | Story 验证证据 / `TEST-REPORT.md` | runtime | allowed | 验证必须知道改动对象和契约 | CP7 |
| 验证 / 质量证据 | Release Context / release docs | release | allowed | 发布就绪需要质量和风险摘要 | CP8 |
| `WORKFLOW-EVAL.yaml` / `PROMPT-BUNDLE.yaml` / `CASE-REGISTRY.yaml` | Eval Run Evidence | validation | allowed | runner 需要稳定契约和 case / grader 引用 | `meta-flow eval run` |
| Eval Run Evidence / Suite Health | `VERIFICATION-REPORT.md` / `TEST-REPORT.md` / `REVIEW.md` | validation | allowed | CP7 消费 eval evidence，但不被 eval run 替代 | CP7 |

## 3. Agent / Skill 依赖

| From | To | 依赖类型 | 允许方向 | 原因 | 验证 / 监控 |
|---|---|---|---|---|---|
| host-orchestrator | meta-pm / meta-se / meta-dev / meta-qa / meta-doc | dispatch | allowed | Host Orchestrator 主进程是统一编排器 | dispatch evidence |
| meta-pm | use-case-discovery / requirement-extraction / scenario-expansion / story-planning | skill-use | allowed | 需求阶段产出产品和验证输入 | CP1 / CP2 |
| meta-se | blueprint-design / hld-designer / implementation-design / story-manager | skill-use | allowed | 设计阶段产出蓝图、HLD、Story 计划 | CP3 / CP4 |
| meta-dev | lld-designer / implementation-execution | skill-use | allowed | 设计证据和实现执行 | CP5 / CP6 |
| meta-qa | verification-execution / quality-review / release-readiness | skill-use | allowed | 验证、质量和发布准备 | CP7 / CP8 |
| meta-doc | workflow-renderer | skill-use | allowed | 已验证产物转用户文档 | CP8 |
| meta-dev | 用户 | direct-question | forbidden | 并行 LLD 阶段必须通过 queue 由 meta-po 汇总 | LLD clarification queue |
| meta-qa / meta-doc | 用户 | direct-gate | forbidden | 运行授权和正式人工门禁必须由 meta-po 发起 | Human Gate |

## 4. 上下文依赖

| From | To | 依赖类型 | 允许方向 | 原因 | 验证 / 监控 |
|---|---|---|---|---|---|
| `process/context/*-CONTEXT.yaml` | 下游 Agent | context | allowed | 默认 capsule-first 降低 token | read_profile / read_expansion_log |
| 正式文档 | Context Capsule | source | allowed | capsule 是摘要，不替代正式文档 | 冲突时以正式文档为准 |
| Discussion Log | 正式文档 | audit-only | restricted | discussion 用于审计和恢复，不作为唯一输入 | CP2 / CP3 检查 |
| Handoff | Dispatch Evidence | evidence | forbidden | handoff 只说明交接，不说明已执行 | CP6 / CP7 |
| Eval Run PASS | CP7 PASS | gate-substitution | forbidden | eval evidence 是输入证据，不是 CP7 最终裁决 | verification-execution |

## 5. 禁止依赖

| Forbidden ID | From | To | 禁止原因 | 替代路径 | 违反风险 |
|---|---|---|---|---|---|
| FD-01 | story-execution | CP5 前 Story 设计证据 | CP5 未通过前实现会绕过设计确认 | 先完成 LLD / technical-note / waived 批量确认 | 代码与架构不一致、回修成本高 |
| FD-02 | `docs/design/*` | `process/discussions/*` 作为唯一输入 | 讨论日志不可替代正式产物 | 消费正式文档或 Context Capsule | 丢失决策追溯 |
| FD-03 | production project | 当前仓库 `delivery/` 默认输出 | production 应遵守目标 README/docs | 先扫描目标项目约定并询问 | 污染 meta-flow 自身交付包 |
| FD-04 | installer / LLD | 平台路径类比推断 | 平台路径必须以契约为准 | 读取 `delivery/doc/PLATFORM-CONTRACTS.yaml` | 安装失败或写错目录 |
| FD-05 | meta-po 状态推进 | handoff-only | handoff 不是执行完成证据 | 使用真实子 agent 调度证据或批准 inline fallback | 虚假完成 |
| FD-06 | archived assets | delivery active surface | 归档资产不可安装 / 唤醒 | 保留在 `process/archive` | 废弃角色回流 |
| FD-07 | release-readiness | 全量 HLD / LLD / diff 默认读取 | 发布阶段默认 capsule-first 控制 token | 只读取摘要、计数、风险 ID、证据路径 | 发布阶段 token 膨胀 |
| FD-08 | low-risk Story | full-lld 默认生成 | LLD 深度需按风险分级 | technical-note / waived | 设计文档膨胀 |
| FD-09 | external eval adapter | default CP7 execution | 外部工具可能需要网络、凭据或 trace 上传 | 先走 local deterministic runner；外部执行需 runtime_authorization | 凭据泄漏、不可复现、误授权 |
| FD-10 | code-project | workflow eval 强制执行 | 纯代码项目不应被 workflow 验证层污染 | 原生测试 / 构建 / 静态检查，workflow eval N/A | 验证成本膨胀、错误阻断 |

## 6. 循环风险

| Cycle ID | 涉及对象 | 风险 | 当前处理 |
|---|---|---|---|
| CYCLE-01 | CP5 问题收敛 -> 用户确认 -> LLD 重写 -> 新问题 | LLD 僵局和反复打断用户 | 统一 clarification queue，meta-po 批量提问，blocks_lld 项未答不得进 CP5 |
| CYCLE-02 | 验证失败 -> 设计澄清 -> 实现回修 -> 再验证失败 | 开发卡顿 | `workflow_health` 记录回修计数，必要时路由回设计澄清 |
| CYCLE-03 | 文档路由规则 -> 产物写错目录 -> 再修正规则 | 交付目录污染 | `docs/` / `process/` / `delivery/` 分层规则和 guardrail |
| CYCLE-04 | 子 Agent 上下文过大 -> 输出不稳定 -> 再读更多上下文 | token 消耗失控 | Context Capsule + read expansion reason |

## 7. Gotchas

- 依赖图中 `allowed` 不代表任何阶段都可以读取全文档；读取仍受 context budget 控制。
- `forbidden` 依赖并不是永远不能改变，但必须通过 CR 和人工决策重开。
- `docs/design/DEPENDENCY-MAP.md` 是长期基线，具体 Story 的文件冲突仍以 Story 卡片和 CP4 / CP5 为准。
