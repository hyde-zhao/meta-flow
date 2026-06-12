---
status: baseline
version: "1.0"
confirmed_by: "meta-po"
confirmed_at: "2026-06-07"
source_hld: "docs/design/HLD.md"
---

# Meta Flow Architecture Decisions

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-07 | meta-po | 汇总当前仍有效的 Meta Flow v2 架构决策，吸收 CR-005 至 CR-018 |
| 1.1 | 2026-06-11 | host-orchestrator | 吸收 CR-019 至 CR-023：修正 Host Orchestrator 编排基线，新增 workflow eval / prompt bundle 治理决策 |

## ADR 列表

| ADR | 决策 | 状态 | 理由 | 影响面 |
|---|---|---|---|---|
| ADR-001 | canonical functional role 保持 `meta-pm` / `meta-se` / `meta-dev` / `meta-qa` / `meta-doc` 五类；主编排由 Host Orchestrator 主进程承担 | accepted | `meta-dm` 已归档，`meta-po` 编排子 agent 已由 CR-017 取消；功能角色覆盖端到端流程 | Agent lifecycle、安装、rules |
| ADR-002 | Host Orchestrator 是唯一主编排器，Codex / Claude Code 只安装功能子 agent | accepted | 避免状态竞争和多线程重复推进；主进程统一维护 STATE、CR、人工门禁和调度证据 | STATE、handoff、dispatch evidence |
| ADR-003 | 阶段内允许委托 `meta-pm` / `meta-se` 直接与用户讨论，但正式 CP2 / CP3 由 Host Orchestrator 发起 | accepted | 保留阶段专业交互，同时保证人工门禁一致 | delegated_interaction、Human Gate |
| ADR-004 | CP2 / CP3 / CP5 / CP8 是关键人工门禁，CP4 只做自动预检并汇入 CP5 | accepted | 减少不必要确认，同时保留关键决策点 | checkpoint-manager、state-router |
| ADR-005 | 人工门禁必须生成 Decision Brief 和 Decision Collection Coverage | accepted | 解决用户确认时问题收集不完整的问题 | pending_human_decisions、validator |
| ADR-006 | 用户回复 `approve` 只表示接受待决策表推荐方案，不授权真实运行、外部写入、publish 或 live 操作 | accepted | 避免设计确认被误读为运行授权 | Human Gate、release-readiness |
| ADR-007 | 场景发现必须在标准模式下产生用户可见 SGQ 证据 | accepted | 防止静默生成场景和误判用户意图 | use-case-discovery、CP2 |
| ADR-008 | HLD 前必须处理 Architecture Gray Areas，并优先使用 advisor table-first | accepted | 关键问题越早确认越能减少返工 | hld-designer、CP3 |
| ADR-009 | 蓝图 / 领域 / 依赖地图在跨 Feature / Epic、数据归属或依赖方向问题上是 HLD 前置输入 | accepted | 先定义产品能力和数据归属，再决定架构形态 | blueprint-design、HLD |
| ADR-010 | CP3 后、CP4 前必须生成 `FEATURE-DESIGN-MATRIX.md` | accepted | 控制哪些 Feature 需要详细设计，避免 LLD 全量膨胀 | implementation-design、story-manager |
| ADR-011 | LLD 采用 `full-lld` / `technical-note` / `waived` 分级 | accepted | 减少低风险 Story 的设计 token，同时保留高风险设计证据 | lld-designer、CP5 |
| ADR-012 | 全部目标 Story 的设计证据统一确认后才能进入实现 | accepted | 防止边开发边发现跨 Story 设计冲突 | CP5、story-execution |
| ADR-013 | 并行 LLD 阶段 `meta-dev` 不直接问用户，只写 clarification queue | accepted | 避免多个子 Agent 同时打断用户并漏收问题 | lld_clarification_queue |
| ADR-014 | 子 Agent 调度必须有真实平台证据；handoff 不等于执行完成 | accepted | 防止“创建交接文件”被误判为目标 Agent 已完成 | CP6 / CP7 |
| ADR-015 | Context Capsule 是下游默认读取入口，全文档读取必须记录原因 | accepted | 控制 token 消耗并保留审计原因 | context_budget、read_expansion_log |
| ADR-016 | Story 实现开始后必须使用 implementation-execution 输出实现证据，低风险 Story 可写摘要但 CP6 必须记录 N/A 理由 | accepted | 让实现从“改文件”变成可验证执行证据 | CP6、implementation-execution |
| ADR-017 | 验证使用 verification-execution / quality-review，并支持 `NEEDS_REWORK` / `NEEDS_DESIGN_CLARIFICATION` 路由 | accepted | 失败不应被标记为 verified | CP7、quality-review |
| ADR-018 | 发布准备采用 capsule-first 和 `release_artifact_profile=minimal|compact|full` | accepted | 控制发布阶段 token 和文档厚度 | release-readiness、CP8 |
| ADR-019 | release_decision 使用 `READY` / `READY_WITH_RISK` / `NOT_READY` / `RELEASED` / `FAILED`，其中 `RELEASED` / `FAILED` 需独立真实发布授权 | accepted | 区分发布准备和真实发布执行 | release-readiness |
| ADR-020 | 文档分层为 `docs/` 长期文档、`process/` 运行态和确认态、`delivery/` 可安装交付包 | accepted | 避免过程状态和交付文档混写 | docs/process/delivery |
| ADR-021 | production 项目必须先读取目标 README/docs 交付约定，无约定时询问用户 | accepted | 避免默认把目标项目产物写到 meta-flow 自身 delivery | output routing |
| ADR-022 | 平台路径以 `delivery/doc/PLATFORM-CONTRACTS.yaml` 为单一真相源 | accepted | 避免按同平台目录类比推断导致安装错误 | installer、platform-validator |
| ADR-023 | active Skill 的模板 / scripts / schemas / examples 必须与 Skill 同树安装 | accepted | 保证 Skill 安装后资产可用 | delivery/skills、guardrail |
| ADR-024 | `delivery/scripts/` 只允许安装入口，Skill 运行时脚本放到 Skill 自己目录 | accepted | 避免共享脚本路径在安装后失效 | delivery guardrail |
| ADR-025 | `meta-dm` 归档，仅保留 `process/archive/meta-dm.md` | accepted | Story 拆解职责已由 `meta-se` 承担 | Agent lifecycle、installer |
| ADR-026 | guardrail 必须覆盖交付资产生命周期、安装路径、direct ask 权限、human gate 协议和 Python cache | accepted | 防止已修复结构性问题回流 | `scripts/check_delivery_guardrails.py` |
| ADR-027 | 正式设计基线写入 `docs/design/`，legacy `process/HLD*.md` 仅作为来源材料 | accepted | 降低后续理解成本，避免旧草案混入执行 | docs/design |
| ADR-028 | 使用单主流程 + `target_project_profile.project_kind` / `validation_target.sut_type` 分流 code / workflow / prompt / mixed 验证 | accepted | 避免拆出两套主流程，同时保证纯代码项目不被强制 workflow eval | STATE、Story template、CP7 |
| ADR-029 | workflow eval、prompt bundle 和 case registry 是 generated workflow / prompt-skill / mixed 产物的一等验证契约 | accepted | 生成工作流需要结构、hash、trace、case、权限和回归证据；纯代码项目默认 N/A | evals/contracts、meta-qa、verification-execution |
| ADR-030 | 本地 deterministic runner 是默认 eval producer；Promptfoo / DeepEval / Langfuse / Garak 只能作为可选 adapter | accepted | 保持无凭据、无网络、可审计的默认验证路径；外部工具必须单独 runtime_authorization | meta-flow eval、evals/adapters、CI policy |

## 决策与产物对齐

| ADR | 已落地产物 |
|---|---|
| ADR-001 / ADR-025 | `delivery/agents/` 六个 active Agent；`process/archive/meta-dm.md` |
| ADR-004 / ADR-005 / ADR-006 | checkpoint-manager、human gate validator、AGENTS rules |
| ADR-009 / ADR-027 | `docs/design/BLUEPRINT.md`、`DOMAIN-MAP.md`、`DEPENDENCY-MAP.md`、`HLD.md` |
| ADR-010 / ADR-011 | `docs/design/FEATURE-DESIGN-MATRIX.md` |
| ADR-015 | context-manifest-builder、`process/context/*-CONTEXT.yaml` 约定 |
| ADR-018 / ADR-019 | release-readiness Skill、release templates、meta-qa / meta-po rules |
| ADR-020 / ADR-021 | AGENTS 输出路由、README、USER-MANUAL |
| ADR-022 / ADR-023 / ADR-024 / ADR-026 | install.py、PLATFORM-CONTRACTS、guardrail |
| ADR-028 / ADR-029 / ADR-030 | `evals/contracts/*`、`meta_flow/evals/runner.py`、`docs/features/workflow-eval-governance/*`、`docs/quality/EVAL-SUITE-HEALTH.md` |

## 待重访决策

| ID | 触发条件 | 当前默认 | 重访动作 |
|---|---|---|---|
| RV-001 | 某 Feature 进入实际实现改造且矩阵标记 required | 先只有 DESIGN | 补 `TEST-PLAN.md` 和 `TASKS.md` |
| RV-002 | 目标平台新增或路径契约变化 | 以 PLATFORM-CONTRACTS 为准 | 更新契约、installer、platform-validator 和 ADR |
| RV-003 | Codex / Claude 平台提供新的结构化用户提问工具 | Codex exact text，Claude direct ask 受 tools 限制 | 更新 platform capabilities 和人工门禁协议 |
| RV-004 | 发布阶段需要执行真实发布 | 默认只做发布准备 | 生成独立 runtime_authorization 决策项 |
| RV-005 | 需要真实外部 eval adapter、LLM judge 或 trace backend | 默认本地 deterministic runner | 创建独立 runtime_authorization CR 或 Spike |

## Gotchas

- ADR 是当前仍有效的架构决策，不是完整历史年表；完整历史仍看 CR。
- 若 ADR 与 `delivery/doc/PLATFORM-CONTRACTS.yaml` 冲突，平台路径以契约为准，并修订 ADR。
- 任何改变用户确认语义、运行授权或交付出口的修改都必须新增 ADR。
