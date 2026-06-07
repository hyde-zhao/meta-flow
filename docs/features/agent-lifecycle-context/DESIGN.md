---
status: baseline
version: "1.0"
feature_id: "FEAT-AGENT-LIFECYCLE-CONTEXT"
feature_name: "子 Agent 生命周期与上下文控制"
source_blueprint: "docs/design/BLUEPRINT.md"
source_hld: "docs/design/HLD.md"
source_adr: "docs/design/ARCHITECTURE-DECISION.md"
source_matrix: "docs/design/FEATURE-DESIGN-MATRIX.md"
related_stories: []
lld_policy_summary: "full-lld for lifecycle, dispatch, direct-ask or capsule policy changes"
confirmed_by: "meta-po"
confirmed_at: "2026-06-07"
---

# Feature Design: Agent Lifecycle Context

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-07 | meta-po | 建立子 Agent 生命周期、调度证据、用户提问权限和 Context Capsule 的 Feature 设计基线 |

## 1. 摘要

| 项目 | 内容 |
|---|---|
| Feature 目标 | 让 meta-po 能安全、可审计、低 token 地调度下游 Agent，并清楚区分真实执行、handoff 和 inline fallback |
| 推荐方案 | `STATE.md.agent_lifecycle` 保存平台能力和 active registry；handoff 记录 dispatch 区；Context Capsule 是默认交接输入 |
| 关键取舍 | 增加调度证据和 capsule 维护成本，换取状态一致性、可恢复性和 token 控制 |
| 下游 Story | 涉及子 Agent 调度、直接提问权限、context budget、handoff 或 inline fallback 的 Story |
| LLD 策略 | 生命周期 / 权限 / capsule 策略变化必须 full-lld |

## 2. 背景与问题

| 问题 ID | 背景 | 触发场景 | 影响 | 若不设计的风险 |
|---|---|---|---|---|
| P-01 | handoff 文件容易被误判为目标 Agent 已完成 | 阶段切换和 CP6 / CP7 | 虚假完成 | 没有 spawn / resume / send_input 证据 |
| P-02 | 子 Agent 读取上下文过大 | LLD / QA / release 阶段 | token 消耗高且输出不稳定 | 默认读取完整 HLD、全部 LLD、完整 diff |
| P-03 | 用户提问权限因平台不同而不稳定 | Codex / Claude 差异 | 工具不可用或问错 Agent | 没有 platform capabilities |
| P-04 | 多个同角色 Agent 并行可能冲突 | 多 Story、恢复、回修 | 重复写同一文件或状态 | active registry 缺失 |

## 3. 上游依据与输入

| 来源 | 路径 / ID | 被本设计消费的内容 |
|---|---|---|
| Blueprint | `docs/design/BLUEPRINT.md` | FEAT-AGENT-LIFECYCLE-CONTEXT 边界 |
| HLD | `docs/design/HLD.md` | capsule-first、调度证据、上下文控制 |
| ADR | ADR-002、ADR-013 至 ADR-015 | meta-po 单例、queue、dispatch evidence、capsule-first |
| Rules | `AGENTS.md`、`delivery/rules/AGENTS.md` | 子 Agent 调度证据、inline fallback、direct ask 权限 |
| Skill | context-handoff、context-manifest-builder、state-router | 交接、胶囊和状态推进 |

## 4. 目标与非目标

| 类型 | 内容 | 来源 |
|---|---|---|
| Goal | 同一工作流最多一个 active `meta-po` | ADR-002 |
| Goal | 下游 Agent 真实执行必须有调度证据 | ADR-014 |
| Goal | 下游默认读取 Context Capsule，必要时记录展开理由 | ADR-015 |
| Goal | 用户提问权限由 platform capabilities 判定 | AGENTS |
| Non-Goal | 在平台无法拉起子 Agent 时自动 inline fallback | inline fallback gate |
| Non-Goal | 把 capsule 当作正式文档替代品 | context contract |

## 5. Feature 边界与相邻对象

| 对象 | 本 Feature 负责 | 不负责 | 相邻 Feature / 模块 | 边界判定依据 |
|---|---|---|---|---|
| Agent Lifecycle | active_agents、角色复用、关闭登记 | 子 Agent 具体专业输出 | Workflow Orchestration | ADR-002 |
| Dispatch Evidence | spawn / resume / send_input / Task 证据 | 平台工具实现本身 | context-handoff | ADR-014 |
| Context Capsule | must_read、read_if_needed、do_not_read、read_expansion_log | 正式文档内容 | context-manifest-builder | ADR-015 |
| User Question Capability | direct / relay / queue / exact-text | 人工门禁业务内容 | Human Gate | AGENTS |

## 6. 推荐方案

| 设计点 | 推荐做法 | 理由 | 代价 |
|---|---|---|---|
| meta-po 单例 | `STATE.md.orchestrator_session` 记录 active meta-po | 防止重复推进 | 需要状态检查 |
| 同角色复用 | role + task + story / wave 粒度匹配 | 降低上下文重复和文件冲突 | 匹配逻辑更严格 |
| dispatch 区 | handoff frontmatter 记录 mode、agent_id、tool_name、spawned_at、completed_at | 审计真实执行 | handoff 文件更长 |
| inline fallback | 平台无法调度时阻断，用户批准后记录 fallback_reason | 防止伪造子 Agent | 需要用户额外确认 |
| capsule-first | 每阶段生成 `process/context/*-CONTEXT.yaml` | 降低 token，提升恢复 | capsule 需维护 |
| read expansion | 全文档读取必须记录原因 | 约束 token 膨胀 | 需要额外日志字段 |

## 7. 方案对比与决策记录

| Decision ID | 方案 | Pros | Cons | Impact Surface | Recommendation | When to switch |
|---|---|---|---|---|---|---|
| DQ-AL-001 | 全量 fork 上下文给子 Agent | 信息完整 | token 高、干扰大 | 所有下游 Agent | 备选 | 只有深度审计或 capsule 失效时 |
| DQ-AL-001 | capsule-first + 按需展开 | token 可控、证据清晰 | 需要维护 capsule | 默认交接 | 推荐 | capsule 缺关键字段或冲突时展开 |
| DQ-AL-002 | handoff 即完成 | 简单 | 虚假完成风险 | CP6 / CP7 | 不推荐 | 不适用 |
| DQ-AL-002 | handoff + dispatch evidence 分离 | 审计准确 | 记录成本高 | 子 Agent 生命周期 | 推荐 | 平台无法提供证据时用用户批准 inline fallback |

## 8. 数据模型与状态

| Object | Owner | 新增 / 修改字段 | 状态变化 | 兼容性 |
|---|---|---|---|---|
| agent_lifecycle.active_agents[] | meta-po | role、task_key、agent_id、thread_id、status、file_ownership、last_seen | idle -> running -> completed / closed | legacy handoff-only 需标记为 incomplete |
| platform_capabilities.user_question | meta-po | direct / relay / queue / exact-text | detected -> active | Codex / Claude 差异由状态决定 |
| Context Capsule | context-manifest-builder | must_read、read_if_needed、do_not_read_by_default、key_facts、risk_ids、decision_ids | draft -> ready -> stale | 正式文档冲突时以正式文档为准 |
| Handoff dispatch | context-handoff | mode、tool_name、agent_id、spawned_at、completed_at、fallback_reason | created -> dispatched -> completed | 缺字段时只能判定 handoff-created |

## 9. API / 接口设计

| Interface ID | 调用方 | 被调用方 | 输入契约 | 输出契约 | 错误模型 |
|---|---|---|---|---|---|
| IF-AL-01 | meta-po | platform subagent tool | role、task、context capsule、file scope | agent_id / thread_id / result | 工具不可用则 blocked 或 inline fallback gate |
| IF-AL-02 | context-manifest-builder | 下游 Agent | context yaml | 下游读取摘要和扩展日志 | 缺字段则读取正式文档并记录原因 |
| IF-AL-03 | meta-dev | meta-po question broker | clarification item | answer 回填并分发 | blocks_lld 未答则 CP5 blocked |

## 10. 关键流程

| Flow ID | 触发条件 | 主流程 | 异常流程 | 输出 / 状态变化 | 观测点 |
|---|---|---|---|---|---|
| FLOW-AL-01 | 阶段委托 | 生成 capsule -> spawn / resume Agent -> 写 dispatch evidence -> 阶段返回 | 工具不可用时请求 inline fallback 批准 | delegated_interaction updated | handoff dispatch |
| FLOW-AL-02 | 子 Agent 需要更多上下文 | 检查 capsule 缺口 -> 读取正式文档 -> 写 read_expansion_log | 与正式文档冲突时阻断 | capsule / STATE log | context_budget |
| FLOW-AL-03 | 并行 LLD 问题 | meta-dev 写 queue -> meta-po 合并提问 -> 回填答案 | blocks_lld 未答则 CP5 不发起 | lld_clarification_queue | CP5 |
| FLOW-AL-04 | 检查点完成 | meta-po 关闭或复用下游 Agent | 状态不一致时 blocked | active_agents status | STATE history |

## 11. 权限与安全

| Rule ID | 规则 | 触发条件 | 失败行为 | 测试入口 |
|---|---|---|---|---|
| SEC-AL-01 | direct ask 只允许 meta-po / 委托阶段 meta-pm / meta-se | 用户提问 | 不满足则 relay / queue | guardrail / rules review |
| SEC-AL-02 | inline fallback 必须用户批准 | 平台无法拉起子 Agent | 未批准则 blocked | handoff review |
| SEC-AL-03 | capsule 不保存凭据和敏感原文 | 上下文装配 | 脱敏或不写入 | review |

## 12. 测试与验收策略

| 验收对象 | 测试层级 | 覆盖场景 | 自动化方式 | 未自动化原因 / 手工入口 |
|---|---|---|---|---|
| Agent display / direct ask profile | static | Claude / Codex 安装 | guardrail | 平台真实调度需人工 / 集成验证 |
| Context capsule | review | must_read / read_if_needed / do_not_read | schema / review | 业务摘要准确性人工审查 |
| Dispatch evidence | checkpoint | CP6 / CP7 evidence | checkpoint-manager | 平台工具证据需实际运行 |

## 13. Story 拆分建议与 LLD 策略

| Story ID | feature_design_refs | lld_policy.required_level | 触发原因 | 必须进一步设计的问题 | 可用设计证据 |
|---|---|---|---|---|---|
| AL-DISPATCH-CHANGE | docs/features/agent-lifecycle-context/DESIGN.md | full-lld | cross-agent / state / permission | active registry、dispatch evidence、fallback | Feature DESIGN + Story LLD |
| AL-CAPSULE-WORDING | docs/features/agent-lifecycle-context/DESIGN.md | technical-note | low-risk / docs | 是否改变读取策略 | Story 技术说明 |

## 14. 下游消费契约

| 消费方 | 消费时机 | 输入契约 | 输出 / 状态要求 | 降级策略 |
|---|---|---|---|---|
| state-router | 每次推进 | active_agents、checkpoints、context_budget | 正确路由 / blocked | 状态冲突先展示 |
| context-handoff | 阶段切换 | role、task、capsule、file scope | handoff + dispatch 区 | 缺真实证据则 handoff-created |
| meta-dev / meta-qa | Story / 验证阶段 | capsule + Story scope | CP6 / CP7 evidence | 缺上下文时展开读取并记录 |

## 15. 风险与回退

| Risk ID | 风险 | 影响 | 缓解 | 回退 |
|---|---|---|---|---|
| R-AL-01 | active registry 与真实平台线程不一致 | 调度错误 | 每次推进读取 STATE 和 handoff dispatch | 阻断并要求用户选择保留线程 |
| R-AL-02 | capsule 摘要遗漏关键事实 | 下游误判 | read_if_needed 和 expansion log | 读取正式文档修正 capsule |
| R-AL-03 | inline fallback 被滥用 | 子 Agent 边界失真 | 必须用户批准并标注 meta-po 代执行 | 重新真实调度 |

## 16. Gotchas

- handoff 不是完成证据，dispatch evidence 才能证明目标 Agent 被调用。
- capsule 是上下文入口，不是正式文档替代品。
- Codex 是否可用结构化用户提问，要看当前工具面，不要硬编码假设。
