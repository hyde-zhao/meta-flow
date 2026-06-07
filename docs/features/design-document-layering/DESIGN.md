---
status: baseline
version: "1.0"
feature_id: "FEAT-DESIGN-DOCUMENT-LAYERING"
feature_name: "文档分层与交付出口路由"
source_blueprint: "docs/design/BLUEPRINT.md"
source_hld: "docs/design/HLD.md"
source_adr: "docs/design/ARCHITECTURE-DECISION.md"
source_matrix: "docs/design/FEATURE-DESIGN-MATRIX.md"
related_stories: []
lld_policy_summary: "full-lld for routing/default-path changes; technical-note for adding a single baseline doc"
confirmed_by: "meta-po"
confirmed_at: "2026-06-07"
---

# Feature Design: Design Document Layering

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-07 | meta-po | 建立 `docs/`、`process/`、`delivery/` 分层和 production / meta-self-dev 交付出口路由设计基线 |

## 1. 摘要

| 项目 | 内容 |
|---|---|
| Feature 目标 | 让长期文档、运行态、人工确认态和可安装交付包有稳定边界，避免过程文档或 meta-flow 自身交付面污染 production 项目 |
| 推荐方案 | `docs/` 承载长期产品 / 设计 / 质量 / 发布文档，`process/` 承载运行态和确认态，`delivery/` 只承载 meta-flow 可安装交付包 |
| 关键取舍 | 需要维护 legacy fallback 说明，但新生成默认路径清晰 |
| 下游 Story | 涉及输出目录、文档类型、安装包结构、production 交付出口的 Story |
| LLD 策略 | 改默认路由必须 full-lld；新增单个基线文档可 technical-note |

## 2. 背景与问题

| 问题 ID | 背景 | 触发场景 | 影响 | 若不设计的风险 |
|---|---|---|---|---|
| P-01 | 旧设计文档集中在 `process/`，与运行态混在一起 | 新 Agent 读取设计事实 | 容易误读草案或过期文档 | 长期设计缺少正式入口 |
| P-02 | 用户使用 Meta Flow 生产项目时，交付物不应默认写当前仓库 `delivery/` | production mode | 输出污染 meta-flow 自身交付包 | 目标项目文档路由错误 |
| P-03 | `checkpoints/` 根目录旧路径和 `process/checkpoints/` 新路径并存 | 人工确认 | checklist 路径混乱 | 用户审查错文件 |
| P-04 | 技术文档、状态、计划、检查点、交付包边界不清 | 新增文档或模板 | 后续维护成本高 | Agent 不知道该写哪里 |

## 3. 上游依据与输入

| 来源 | 路径 / ID | 被本设计消费的内容 |
|---|---|---|
| Blueprint | `docs/design/BLUEPRINT.md` | FEAT-DESIGN-DOCUMENT-LAYERING 边界 |
| HLD | `docs/design/HLD.md` | 文档分层总体设计 |
| ADR | ADR-020、ADR-021、ADR-027 | 输出路由、production、正式基线 |
| Rules | `AGENTS.md`、`delivery/rules/AGENTS.md` | 工作目录约定和输出隔离原则 |
| User Manual | `delivery/doc/USER-MANUAL.md` | 用户视角路径说明 |

## 4. 目标与非目标

| 类型 | 内容 | 来源 |
|---|---|---|
| Goal | 将长期产品 / 设计 / 质量 / 发布文档默认写入 `docs/` | ADR-020 |
| Goal | 将运行态、计划、handoff、CR、自动检查和人工检查点写入 `process/` | ADR-020 |
| Goal | 将 meta-flow 可安装 Agent / Skill / rules / install scripts 写入 `delivery/` | ADR-020 |
| Goal | production 项目优先遵守目标 README/docs 约定 | ADR-021 |
| Non-Goal | 删除所有 legacy `process/HLD*.md` | 追溯需要 |
| Non-Goal | 将 Story LLD 迁移到 `docs/design/` | Story 执行态证据 |

## 5. Feature 边界与相邻对象

| 对象 | 本 Feature 负责 | 不负责 | 相邻 Feature / 模块 | 边界判定依据 |
|---|---|---|---|---|
| `docs/` | 长期产品、设计、质量、发布文档 | 运行时状态 | meta-doc / meta-se / meta-qa | ADR-020 |
| `process/` | STATE、REQUEST、计划、Story 执行态、CR、checks、checkpoints、context、handoff | 可安装交付包 | state-router / checkpoint-manager | AGENTS |
| `delivery/` | canonical Agent / Skill / rules / installer | production 项目的业务文档 | installer / guardrail | ADR-021 |
| legacy fallback | 旧路径只读兼容说明 | 新生成默认路径 | CLI / README | ADR-027 |

## 6. 推荐方案

| 设计点 | 推荐做法 | 理由 | 代价 |
|---|---|---|---|
| 长期设计 | 写 `docs/design/*` | Agent 可优先读取正式基线 | 需要维护基线 |
| Story 级证据 | 留在 `process/stories/*` | 属于执行态和 CP5 / CP6 / CP7 证据 | 不在 docs 中集中展示 |
| 人工确认 | 写 `process/checkpoints/*` | 确认态与长期文档分离 | 用户需知道路径 |
| 自动检查 | 写 `process/checks/*` | 自动结果可重复生成 | 不作为长期文档 |
| delivery 包 | 只放安装相关 canonical 源 | 避免 production 输出污染 | meta-self-dev 需显式说明 |
| legacy fallback | 只读，不作为新生成默认路径 | 支持旧项目恢复 | 需 guardrail / 文档说明 |

## 7. 目录契约

| 目录 | 默认内容 | Owner | 新生成默认 | Legacy fallback |
|---|---|---|---|---|
| `docs/product/` | USE-CASES、REQUIREMENTS、SCENARIOS、TEST-MATRIX、STORY-MAP、MVP-SCOPE、RELEASE-SLICES、BACKLOG | meta-pm | 是 | `process/USE-CASES.md` |
| `docs/design/` | BLUEPRINT、DOMAIN-MAP、DEPENDENCY-MAP、HLD、ADR、FEATURE-DESIGN-MATRIX | meta-se | 是 | `process/HLD*.md`、`process/ARCHITECTURE-DECISION.md` |
| `docs/features/` | Feature DESIGN、TEST-PLAN、TASKS、IMPLEMENTATION、VERIFICATION | meta-se / meta-dev / meta-qa | 按矩阵 required | 无 |
| `docs/quality/` | TEST-STRATEGY、VERIFICATION-REPORT、TEST-REPORT、REVIEW、FIXES | meta-qa | 是 | `process/TEST-STRATEGY.md` |
| `docs/release/` | RELEASE-NOTES、DEPLOY-CHECKLIST、ROLLBACK、MIGRATION、FEEDBACK | meta-qa | 是 | 无 |
| `process/` | STATE、REQUEST、DEVELOPMENT-PLAN、STORY-BACKLOG、CR、handoff、context、checks、checkpoints、stories | meta-po / stage owner | 是 | 旧根 `checkpoints/` 只读 |
| `delivery/` | agents、skills、rules、scripts、README、USER-MANUAL | meta-flow self-dev | 仅 meta-self-dev | production 不默认写 |

## 8. 方案对比与决策记录

| Decision ID | 方案 | Pros | Cons | Impact Surface | Recommendation | When to switch |
|---|---|---|---|---|---|---|
| DQ-DL-001 | 所有文档继续写 `process/` | 简单、兼容旧习惯 | 长期设计和运行态混乱 | 全流程 | 不推荐 | 仅读取 legacy 项目时 |
| DQ-DL-001 | `docs/` / `process/` / `delivery/` 分层 | 边界清晰、可交付 | 需要迁移说明 | 全流程 | 推荐 | 不适用 |
| DQ-DL-002 | production 默认写当前仓库 `delivery/` | meta-flow self-dev 简单 | 污染目标项目和交付包 | 交付出口 | 不推荐 | 仅用户明确 meta-self-dev |
| DQ-DL-002 | production 先读目标 README/docs | 遵守目标项目约定 | 需要前置扫描 | production | 推荐 | 目标无约定时询问用户 |

## 9. API / 接口设计

| Interface ID | 调用方 | 被调用方 | 输入契约 | 输出契约 | 错误模型 |
|---|---|---|---|---|---|
| IF-DL-01 | stage Agent | file system | artifact_type、engagement_mode、target README/docs | 目标路径 | 无约定且 production 时必须询问 |
| IF-DL-02 | CLI / meta-flow next | STATE pending checklist | pending_checklist_path | `process/checkpoints/CP*.md` fallback | 旧根路径不得作为默认 |
| IF-DL-03 | guardrail | delivery tree | active / archived assets、allowed dirs | PASS / FAIL | 不允许废弃资产回流 |

## 10. 关键流程

| Flow ID | 触发条件 | 主流程 | 异常流程 | 输出 / 状态变化 | 观测点 |
|---|---|---|---|---|---|
| FLOW-DL-01 | 新工作流初始化 | 判定 engagement_mode -> 扫描目标 README/docs -> 确定输出路由 | production 无约定时询问用户 | STATE artifacts 路由 | CP0 |
| FLOW-DL-02 | 生成设计文档 | 写入 `docs/design` 或 `docs/features` | legacy 文档只读引用 | docs baseline | review |
| FLOW-DL-03 | 发起人工确认 | 写入 `process/checkpoints` 并提示路径 | 缺路径时门禁失败 | awaiting-user | validator |
| FLOW-DL-04 | 归档废弃资产 | 创建 CR -> 移出 `delivery` -> 保留 `process/archive` | guardrail 发现回流则 fail | archive | guardrail |

## 11. 异常、失败与降级策略

| Failure ID | 失败条件 | 系统行为 | 用户可见影响 | 恢复 / 回退 | 测试入口 |
|---|---|---|---|---|---|
| F-DL-01 | production 项目无文档约定 | 先提出建议并等待确认 | 用户决定 docs 路由 | 写入 STATE | CP0 |
| F-DL-02 | 新文档写入 legacy `process/*.md` 技术路径 | 标记路由违规 | 需要迁移或解释 N/A | 创建 CR 修正 | review / guardrail |
| F-DL-03 | `delivery/` 出现废弃 Agent | guardrail FAIL | 无法通过交付检查 | 移到 archive | guardrail |
| F-DL-04 | root `checkpoints/` 被新生成 | 标记 legacy path 违规 | 用户审查路径混乱 | 迁移到 `process/checkpoints` | review |

## 12. 测试与验收策略

| 验收对象 | 测试层级 | 覆盖场景 | 自动化方式 | 未自动化原因 / 手工入口 |
|---|---|---|---|---|
| delivery tree | static | allowed dirs、archived assets | `scripts/check_delivery_guardrails.py` | 目标项目 README/docs 需人工判断 |
| CLI fallback | static | pending checklist path | guardrail / rg | 用户审查仍需人工 |
| docs baseline | review | 六份设计基线存在 | file presence / review | 内容质量人工评审 |

## 13. Story 拆分建议与 LLD 策略

| Story ID | feature_design_refs | lld_policy.required_level | 触发原因 | 必须进一步设计的问题 | 可用设计证据 |
|---|---|---|---|---|---|
| DL-ROUTING-CHANGE | docs/features/design-document-layering/DESIGN.md | full-lld | output-routing / delivery-boundary | 新路径、legacy fallback、guardrail | Feature DESIGN + Story LLD |
| DL-BASELINE-DOC-ADD | docs/features/design-document-layering/DESIGN.md | technical-note | docs-only | 是否改变默认路由 | Story 技术说明 |

## 14. 下游消费契约

| 消费方 | 消费时机 | 输入契约 | 输出 / 状态要求 | 降级策略 |
|---|---|---|---|---|
| meta-pm / meta-se / meta-qa | 生成长期文档 | artifact type + route table | 写 `docs/*` | 目标项目有约定时遵守目标约定 |
| meta-po | 初始化 / CP | engagement_mode、target docs convention | STATE artifacts route | 无约定时询问 |
| installer / guardrail | 交付前 | delivery tree | installable package | 违规则 FAIL |

## 15. 风险与回退

| Risk ID | 风险 | 影响 | 缓解 | 回退 |
|---|---|---|---|---|
| R-DL-01 | 正式基线与 legacy process 文档冲突 | Agent 不知道信谁 | 以最新 docs/design 和 AGENTS 为准，修订或标注 legacy | 创建 CR |
| R-DL-02 | 过度文档化 | token 增加 | Feature Matrix 控制 required | 改为 technical-note |
| R-DL-03 | production 路由误判 | 写错目标路径 | 扫描 README/docs 并询问用户 | 迁移文档并记录 CR |

## 16. Gotchas

- `docs/design` 是长期基线，不是每轮运行的临时草稿区。
- `process/checkpoints` 是人工确认态，不应放到根目录 `checkpoints/`。
- `delivery/` 只有在 meta-flow 自身改造或用户明确要求时才作为输出面。
