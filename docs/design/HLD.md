---
status: baseline
version: "1.0"
complexity: standard
selected_option: "方案B：分层正式设计基线 + capsule-first 执行"
confirmed: true
confirmed_by: "meta-po"
confirmed_at: "2026-06-07"
source_blueprint: "docs/design/BLUEPRINT.md"
source_domain_map: "docs/design/DOMAIN-MAP.md"
source_dependency_map: "docs/design/DEPENDENCY-MAP.md"
---

# Meta Flow High-Level Design

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-07 | meta-po | 建立 Meta Flow v2 总体 HLD 基线，汇总已确认规则、legacy HLD、ADR 和 CR-005 至 CR-018 |

## 1. 问题定义

### 1.1 问题陈述

Meta Flow 已具备 Agent / Skill 工厂能力，但随着场景发现、设计分层、人工门禁、子 Agent 调度、LLD 分级、实现验证和发布控制不断增强，核心设计事实散落在规则、Agent prompt、Skill README、legacy `process/` HLD、CR 和脚本中。

这带来四个问题：

1. Agent 需要读取大量规则才能理解当前设计基线，token 成本高。
2. 过程文档与长期设计文档边界不清，容易把 legacy `process/` 草案当成正式设计。
3. 子 Agent 生命周期、人工门禁、文档路由等关键机制缺少统一架构视图。
4. 后续改造难以判断哪些文档需要更新，容易只修局部 prompt。

### 1.2 核心价值

建立一套面向 Meta Flow v2 的正式设计基线，使后续 Agent 能优先读取 `docs/design/*` 理解系统边界，再按需展开 `process/`、delivery 规则和具体 Story 证据。

### 1.3 目标

| 优先级 | 目标 | 度量方式 |
|---|---|---|
| P0 | 正式设计基线覆盖蓝图、领域对象、依赖方向、总体 HLD、ADR、Feature 设计矩阵 | `docs/design/` 至少 6 份基线文件存在 |
| P0 | 明确 `docs/`、`process/`、`delivery/` 分层 | HLD / Blueprint / ADR 均说明文档路由边界 |
| P0 | 固化人工门禁、子 Agent 生命周期和 LLD 分级三类高风险机制 | `docs/features/` 中至少 3 份 Feature DESIGN |
| P1 | 降低后续理解成本 | Agent 可先读设计基线，再按 `read_expansion_log` 展开 |
| P1 | 避免低风险 Story 默认生成完整 LLD | Feature Matrix 明确 `full-lld` / `technical-note` / `waived` |

### 1.4 成功标准

- [ ] `docs/design/BLUEPRINT.md`、`DOMAIN-MAP.md`、`DEPENDENCY-MAP.md`、`HLD.md`、`ARCHITECTURE-DECISION.md`、`FEATURE-DESIGN-MATRIX.md` 均存在且有修订记录。
- [ ] 每个核心 Feature 在 Blueprint 中有 owner 和非职责边界。
- [ ] 关键领域对象在 Domain Map 中有 owner、状态和规则来源。
- [ ] Dependency Map 明确至少 6 条禁止依赖。
- [ ] Feature Matrix 对高风险能力给出 `required`，对低风险能力给出 `technical-note` 或 `waived`。
- [ ] 不迁移 `process/stories/*-LLD.md` 到 `docs/design/`。

### 1.5 约束

| 类型 | 约束内容 |
|---|---|
| 技术 | 不新增运行时依赖，不修改安装行为 |
| 治理 | 修改正式设计基线必须先建 CR |
| 文档 | 长期产品 / 设计 / 质量 / 发布文档写 `docs/`，运行态写 `process/`，交付包写 `delivery/` |
| 权限 | 本 HLD 不授权真实运行、外部写入、publish、live / 交易类操作 |
| token | 设计文档应提供索引和基线，不复制全部 prompt 或历史 CR |

### 1.6 非目标

- 不把所有 legacy `process/HLD*.md` 全量迁移到 `docs/design/`。
- 不为每个 Skill 生成 Feature DESIGN。
- 不改变当前 CP0-CP8 阶段顺序。
- 不恢复已归档 `meta-dm`。
- 不替代 Story 级 LLD、实现证据或验证证据。

## 2. 架构灰区与方案形成记录

| Gray Area | 影响面 | Option | Pros | Cons | Recommendation | When to switch |
|---|---|---|---|---|---|---|
| GA-01 设计文档是否全量迁移 legacy `process/` | token、维护成本、追溯 | A 全量迁移 | 历史材料集中 | 文档膨胀、过时风险高 | 不推荐 | 仅审计要求必须完整迁移时 |
| GA-01 | token、维护成本、追溯 | B 建立正式基线，legacy 作为来源 | 当前事实清晰，成本可控 | 需要保留来源路径 | 推荐 | 若基线缺少关键事实，再增量补充 |
| GA-02 Feature DESIGN 是否全量铺开 | token、设计覆盖 | A 每个 Feature 都写 DESIGN | 覆盖完整 | 大量低价值文档 | 不推荐 | Feature 即将实现或有高风险 |
| GA-02 | token、设计覆盖 | B 只补高风险 Feature | 聚焦门禁、状态、路由 | 部分能力只有矩阵摘要 | 推荐 | 低风险能力进入实现改造时补 |
| GA-03 HLD 是否重新发起 CP3 | 治理、效率 | A 作为新 HLD 重新 CP3 | 门禁完整 | 用户需要再次确认已确认事实 | 条件不推荐 | 如果改变阶段、Agent 权限或安装行为 |
| GA-03 | 治理、效率 | B 作为基线整理，记录 CR | 不改变行为，快速降低理解成本 | 不是新架构授权 | 推荐 | 后续基线引入新行为时走 CP3 |

本轮采用方案 B：分层正式设计基线 + capsule-first 执行。

## 3. 推荐架构

### 3.1 总体结构

```text
用户请求
  -> meta-po 统一编排
    -> meta-pm: 场景发现、需求、验证场景、产品规划
    -> meta-se: 蓝图、HLD、ADR、Feature 设计矩阵、Story 计划
    -> meta-dev: Story 设计证据、实现执行、回修
    -> meta-qa: 验证、质量评审、发布准备、安装校验
    -> meta-doc: README / USER-MANUAL / 交付说明

长期文档: docs/
过程状态: process/
交付包: delivery/
```

### 3.2 模块职责

| 模块 | 职责 | 关键输入 | 关键输出 |
|---|---|---|---|
| Orchestration | 状态、CR、阶段推进、子 Agent 调度、人工门禁 | REQUEST、STATE、CP、CR | STATE、handoff、Decision Brief |
| Product Discovery | 阶段零调研、场景发现、需求、测试矩阵、产品规划输入 | REQUEST、用户确认、CR | USE-CASES、REQUIREMENTS、SCENARIOS、TEST-MATRIX、STORY-MAP |
| Solution Design | 蓝图、领域地图、依赖地图、HLD、ADR、Feature 设计策略 | 产品规划输入、平台约束 | docs/design、docs/features、STORY-BACKLOG |
| Design Evidence | LLD / technical-note / waived 证据和 clarification queue | Story、Feature DESIGN、HLD、ADR | STORY-*-LLD、Story 技术说明、CP5 |
| Implementation | 实现对象清单、契约映射、测试 Fixture、回滚和交接 | 已确认设计证据 | IMPLEMENTATION、CP6 |
| Verification | 验证对象、追踪矩阵、契约验证、质量评审 | 实现证据、TEST-MATRIX | VERIFICATION、TEST-REPORT、REVIEW、FIXES、CP7 |
| Release & Docs | 发布上下文、部署 / 回滚 / 迁移 / 反馈、用户文档 | QA 证据、安装 dry-run、CP8 输入 | RELEASE-CONTEXT、release docs、README、USER-MANUAL |
| Installer & Guardrails | 平台契约、安装脚本、资产生命周期检查 | delivery 包、PLATFORM-CONTRACTS | install dry-run、guardrail result |

## 4. 关键流程

### 4.1 标准工作流

```text
CP0 init
  -> CP1 requirement precheck
  -> CP2 requirements / scenarios / scope human gate
  -> CP3 blueprint / HLD / ADR human gate
  -> CP4 story / DAG / feature design automatic precheck
  -> CP5 all target story design evidence human gate
  -> CP6 implementation completion
  -> CP7 verification completion
  -> CP8 delivery readiness human gate
```

### 4.2 人工门禁

1. 下游 Agent 发现需用户决策的问题，写入 `pending_human_decisions[]` 或交还给 meta-po。
2. meta-po 汇总来源，去重，生成 Decision Collection Coverage。
3. 对话发起前运行 human gate validator。
4. 用户回复 `approve` 表示接受表内推荐方案，不授权不授权项。
5. meta-po 回填 `process/checkpoints/CP*.md` 并更新 STATE。

### 4.3 子 Agent 和上下文

1. meta-po 真实调度子 Agent，handoff 只表示交接。
2. Context Capsule 是默认读取入口。
3. 下游只有在 capsule 缺字段、冲突或深度审计时读取完整文档。
4. 展开读取原因写入 `read_expansion_log`。

### 4.4 LLD 分级

| required_level | 适用 | 正式证据 |
|---|---|---|
| full-lld | 高风险、跨模块、权限 / 安全、安装器、平台适配、发布、复杂 Prompt / Skill / Workflow | `process/stories/STORY-*-LLD.md` |
| technical-note | 低风险、局部规则、文档或小范围 prompt 调整 | Story 卡片 `## 技术说明` |
| waived | 不需要实现设计或仅追溯 | Story 卡片 waived 理由、风险和重访条件 |

## 5. 非功能设计

| 维度 | 设计 |
|---|---|
| 可追溯性 | 每个阶段有正式产物、检查点、状态和 CR 链路 |
| 可恢复性 | Discussion checkpoint、Context Capsule、STATE history 支持中断恢复 |
| 安全性 | 权限、安全、运行授权、外部写入和 publish 必须独立决策 |
| 可验证性 | TEST-MATRIX、Feature TEST-PLAN、CP6 / CP7 / CP8 形成闭环 |
| 可维护性 | Agent / Skill 关系由 `delivery/skills/README.md` 维护，设计基线由 `docs/design/*` 维护 |
| token 控制 | capsule-first、Feature Matrix、LLD 分级、release profile 控制阅读和输出厚度 |

## 6. 风险

| Risk ID | 风险 | 影响 | 缓解 | 回退 |
|---|---|---|---|---|
| R-01 | 设计基线与 Agent prompt 漂移 | 下游执行按旧规则 | 修改 Agent / Skill 关系时同步更新 docs/design 或记录 CR | 以 AGENTS / delivery 规则为准并修订基线 |
| R-02 | 基线文档过厚 | token 成本反增 | 只写当前事实、索引和决策，不复制 prompt | 拆成专题 Feature DESIGN |
| R-03 | Feature DESIGN 缺 TEST-PLAN / TASKS | 进入实现时证据不足 | Feature Matrix 标记 required 时补齐 | Story 进入实现改造前创建补充 CR |
| R-04 | 用户把 baseline 当新授权 | 误以为允许真实运行 | 文档明确不授权真实运行、外部写入或 publish | CP / Decision Brief 单独授权 |

## 7. Use Case -> Architecture Traceability

| 使用场景 | 架构响应 | 证据 |
|---|---|---|
| 用户启动新工作流 | meta-po 初始化 STATE、委托 meta-pm、按 CP 推进 | Orchestration / Product Discovery |
| 用户确认场景和需求 | Human Gate 汇总 SGQ、需求、范围和决策项 | CP2 / Decision Brief |
| 用户要求设计方案 | meta-se 输出蓝图、HLD、ADR、Feature Matrix | Solution Design |
| 多个 Story 并行设计 | meta-dev 按 lld_policy 写证据，问题进入 queue | Design Evidence |
| 验证失败 | meta-qa 输出 NEEDS_REWORK，meta-po 路由回 meta-dev | Verification |
| 发布前检查 | release-readiness 生成 release context 和 profile 裁剪文档 | Release & Docs |

## 8. ADR 候选点

当前 ADR 已固化在 `docs/design/ARCHITECTURE-DECISION.md`。后续新增 ADR 的触发条件：

- 改变 Agent 职责或可提问权限。
- 改变 CP 门禁、Decision Brief 或人工确认语义。
- 改变文档输出路由。
- 改变安装路径、平台契约或交付包结构。
- 改变 LLD 分级或 Story 执行门控。

## 9. Gotchas

- 本 HLD 是 Meta Flow 当前设计基线，不是某个 production 项目的 HLD 模板。
- `docs/design/HLD.md` 不替代 `delivery/skills/hld-designer/templates/HLD-TEMPLATE.md`。
- baseline 不等于跳过 CP；新工作流仍按 CP0-CP8 执行。
- 发布阶段不得默认全文读取本 HLD，优先消费 Context Capsule 摘要。
