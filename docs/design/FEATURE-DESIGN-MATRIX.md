---
status: baseline
version: "1.0"
source_hld: "docs/design/HLD.md"
source_adr: "docs/design/ARCHITECTURE-DECISION.md"
confirmed_by: "meta-po"
confirmed_at: "2026-06-07"
---

# Meta Flow Feature Design Matrix

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-07 | meta-po | 建立 Feature 设计适用性矩阵，限定高风险 Feature 才补独立 DESIGN |
| 1.1 | 2026-06-11 | host-orchestrator | 新增 workflow eval governance required Feature |

## 1. 适用性判定规则

| 维度 | 需要 Feature 设计的触发条件 | 可豁免条件 |
|---|---|---|
| 状态与决策 | 修改 `STATE.md` 关键对象、人工决策队列、Agent 生命周期或 CP 语义 | 只改说明文案 |
| 文档路由 | 改变 `docs/` / `process/` / `delivery/` 输出位置或 legacy fallback | 只补单个文档的小节 |
| 权限与安全 | 涉及用户提问权限、运行授权、外部写入、publish、安全边界 | 无权限变化 |
| 跨 Agent 契约 | 多个 Agent / Skill 消费同一对象或同一状态 | 单一 Skill 内部优化 |
| 安装与平台 | 影响平台路径、安装脚本、Skill 同树资产、guardrail | 不涉及安装 |
| token 控制 | 改变默认读取策略、上下文胶囊、LLD 或 release 文档厚度 | 局部提示词措辞 |

## 2. Feature 设计矩阵

| Feature ID | Feature / Epic | 来源 | 适用性 | 判定理由 | 需要产物 | 关联 Story / CR | 建议 lld_policy | 重访条件 |
|---|---|---|---|---|---|---|---|---|
| FEAT-HUMAN-GATE-DECISION-BRIEF | 人工门禁与决策收集 | ADR-004 至 ADR-006 | required | 涉及用户确认语义、运行授权边界和状态队列 | DESIGN | CR-010、CR-012、CR-015 | full-lld | 修改 CP2 / CP3 / CP5 / CP8 语义时 |
| FEAT-AGENT-LIFECYCLE-CONTEXT | 子 Agent 生命周期与上下文控制 | ADR-002、ADR-013 至 ADR-015 | required | 涉及调度证据、上下文预算、inline fallback、direct ask 权限 | DESIGN | CR-004、CR-014、CR-016 | full-lld | 修改子 Agent 调度、提问权限或 capsule 策略时 |
| FEAT-DESIGN-DOCUMENT-LAYERING | 文档分层与交付出口路由 | ADR-020、ADR-021、ADR-027 | required | 涉及长期 / 过程 / 交付文档边界和 production 输出路由 | DESIGN | CR-010、CR-018 | full-lld | 新增正式文档类别或改变输出默认路径时 |
| FEAT-SCENARIO-DISCOVERY | 场景发现与需求结构化 | ADR-007 | technical-note | 规则已在 use-case-discovery Skill 和模板中落地，本轮不改行为 | none | CR-005 至 CR-008 | technical-note | 修改 SGQ、画像、场景确认或场景主体默认值时 |
| FEAT-SOLUTION-DESIGN | 蓝图 / HLD / ADR | ADR-008 至 ADR-010 | technical-note | 本轮补正式基线，但不改 meta-se 执行行为 | docs/design 基线 | CR-018 | technical-note | 改变 CP3 或 Architecture Gray Areas 协议时 |
| FEAT-DESIGN-EVIDENCE | LLD 分级与 Story 设计证据 | ADR-011、ADR-012 | technical-note | LLD 规则已在 lld-designer / meta-dev 中落地，本轮只记录基线 | none | CR-011、CR-013 | technical-note | 修改 full-lld / technical-note / waived 策略时 |
| FEAT-IMPLEMENTATION-VERIFICATION | 实现与验证闭环 | ADR-016、ADR-017 | technical-note | 实现 / 验证 Skill 已有模板，本轮不改执行行为 | none | CR-014、CR-015 | technical-note | 修改 CP6 / CP7 证据形态时 |
| FEAT-RELEASE-DOCUMENTATION | 发布准备与文档 | ADR-018、ADR-019 | technical-note | release profile 已落地，本轮不改发布行为 | none | CR-015 | technical-note | 修改 release_artifact_profile 或 release_decision 时 |
| FEAT-INSTALLER-GUARDRAILS | 安装契约与交付护栏 | ADR-022 至 ADR-026 | technical-note | guardrail / installer 已有实现，本轮仅保持基线 | none | CR-017 | technical-note | 新增平台、改变安装路径或资产生命周期规则时 |
| FEAT-WORKFLOW-ORCHESTRATION | 编排与 CR 跟踪 | ADR-002、ADR-004 | technical-note | 当前规则已覆盖，后续大改再补 DESIGN | none | 多个 CR | technical-note | 修改阶段图、CR 状态机或 CP 路由时 |
| FEAT-WORKFLOW-EVAL-GOVERNANCE | Workflow Eval 与 Prompt Bundle 治理 | ADR-028 至 ADR-030 | required | 涉及验证门禁、状态字段、prompt bundle、schema、runner、case lifecycle、suite health 和外部 adapter 授权边界 | DESIGN / TEST-PLAN / TASKS | CR-019 至 CR-023 | full-lld | 修改 eval schema、runner evidence、CP7 消费或外部 adapter 时 |

## 3. Story 下游消费表

| Story / 变更范围 | feature_design_refs | lld_policy.required_level | trigger_reasons | 设计证据 | CP5 审查方式 |
|---|---|---|---|---|---|
| 修改 Human Gate 协议 | `docs/features/human-gate-decision-brief/DESIGN.md` | full-lld | security、runtime_authorization、human-confirmation | Feature DESIGN + Story LLD | CP5 自动预检 + 批量人工确认 |
| 修改 Agent 调度 / 上下文 capsule | `docs/features/agent-lifecycle-context/DESIGN.md` | full-lld | cross-agent、state、token-control | Feature DESIGN + Story LLD | CP5 自动预检 + 批量人工确认 |
| 修改文档路由 / 交付出口 | `docs/features/design-document-layering/DESIGN.md` | full-lld | output-routing、delivery-boundary | Feature DESIGN + Story LLD | CP5 自动预检 + 批量人工确认 |
| 修改单个 Skill 文案或模板小节 | 相关 Skill / README | technical-note | low-risk、single-skill | Story 技术说明 | CP5 可轻量审查 |
| 纯归档 / 删除废弃资产 | CR + archive 文件 | technical-note / waived | cleanup | CR 影响分析 + guardrail | CP5 可 N/A，CP8 汇总 |
| 修改 workflow eval / prompt bundle / case registry / runner / CP7 eval evidence | `docs/features/workflow-eval-governance/DESIGN.md` | full-lld | verification-gate、prompt-bundle、schema、runner、adapter-authorization | Feature DESIGN + CR 技术说明 | CP5 批次可由用户预授权，CP7 必须验证 |

## 4. 提前确认的关键决策

| Decision ID | 决策类型 | 问题 | 推荐方案 | 备选方案 | 优劣摘要 | 影响 / 风险 | 回退 / 切换条件 | 状态 |
|---|---|---|---|---|---|---|---|---|
| DQ-FD-001 | implementation | 是否立即为所有 Feature 生成 TEST-PLAN / TASKS | 不立即全量生成，只对进入实现改造的 required Feature 增量生成 | 本轮全部生成 | 推荐方案降低 token 和维护成本；全量方案初期完整但更易过时 | 进入实现时若缺少 TEST-PLAN / TASKS 需补齐 | 某 Feature 开始实际改造时切换 | resolved |

## 5. 豁免与 N/A 说明

| Feature ID | 豁免 / N/A 原因 | 影响范围 | 风险接受 | 重访条件 | 责任方 |
|---|---|---|---|---|---|
| FEAT-SCENARIO-DISCOVERY | 本轮不改场景发现行为，只引用已落地规则 | use-case-discovery | accepted | 修改 SGQ / 场景主体默认值时 | meta-pm |
| FEAT-DESIGN-EVIDENCE | 本轮不改 LLD 生成规则，只记录分级策略 | meta-dev / lld-designer | accepted | 修改 lld_policy 时 | meta-dev |
| FEAT-RELEASE-DOCUMENTATION | 本轮不改发布产物 profile | meta-qa / meta-doc | accepted | 修改 release profile 或执行真实发布时 | meta-qa |

## 6. 自检

| 检查项 | 结果 | 证据 |
|---|---|---|
| 所有核心 Feature / Epic 均已判定 | PASS | §2 |
| required Feature 均有 DESIGN 计划 | PASS | §2 / docs/features |
| 每类 Story 有 lld_policy 建议 | PASS | §3 |
| 提前确认的关键决策已记录 | PASS | §4 |

## 7. Gotchas

- `technical-note` 不是“不设计”，而是把低风险设计证据压缩到 Story 卡片。
- required Feature 当前只生成 DESIGN；TEST-PLAN / TASKS 在进入实现改造时补齐，避免提前制造过期文档。
- 若后续改变 Human Gate、Agent Lifecycle 或文档路由，必须先更新对应 Feature DESIGN，再写 Story LLD。
