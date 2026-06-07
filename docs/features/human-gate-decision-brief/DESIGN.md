---
status: baseline
version: "1.0"
feature_id: "FEAT-HUMAN-GATE-DECISION-BRIEF"
feature_name: "人工门禁与决策收集"
source_blueprint: "docs/design/BLUEPRINT.md"
source_hld: "docs/design/HLD.md"
source_adr: "docs/design/ARCHITECTURE-DECISION.md"
source_matrix: "docs/design/FEATURE-DESIGN-MATRIX.md"
related_stories: []
lld_policy_summary: "full-lld for protocol changes; technical-note for wording-only updates"
confirmed_by: "meta-po"
confirmed_at: "2026-06-07"
---

# Feature Design: Human Gate Decision Brief

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-07 | meta-po | 建立人工门禁、Decision Brief、决策收集覆盖和不授权项的 Feature 设计基线 |

## 1. 摘要

| 项目 | 内容 |
|---|---|
| Feature 目标 | 在 CP2 / CP3 / CP5 / CP8 前完整收集、去重、展示用户必须决策的问题，并防止设计确认被误解为运行授权 |
| 推荐方案 | `meta-po` 统一发起正式人工门禁；下游写结构化决策项；Human Gate validator 校验 checkpoint 和发起消息 |
| 关键取舍 | 增加少量 checkpoint / STATE 维护成本，换取确认完整性和安全边界清晰 |
| 下游 Story | 后续涉及 CP 语义、确认消息、运行授权或决策队列的 Story |
| LLD 策略 | 协议变化必须 full-lld；仅修改措辞可 technical-note |

## 2. 背景与问题

| 问题 ID | 背景 | 触发场景 | 影响 | 若不设计的风险 |
|---|---|---|---|---|
| P-01 | 用户确认时经常看不到所有需确认问题 | CP2 / CP3 / CP5 / CP8 发起前 | 用户决策不完整，后续返工 | 问题只留在下游文档或对话中，meta-po 未汇总 |
| P-02 | `approve` 容易被误解为授权真实运行 | 发布、外部写入、live / 交易类事项 | 安全和权限边界失真 | 设计通过被当成执行授权 |
| P-03 | 下游 Agent 可发现问题但不应都直接问用户 | 并行 LLD、QA / Doc 发现开放项 | 用户被多线程打断 | 决策项分散、答案无法回填 |
| P-04 | 人工门禁消息可能漏 checklist 路径、预检结论或决策表 | 对话发起阶段 | 用户无法审计或恢复 | 门禁形式通过但内容不完整 |

## 3. 上游依据与输入

| 来源 | 路径 / ID | 被本设计消费的内容 |
|---|---|---|
| Blueprint | `docs/design/BLUEPRINT.md` | FEAT-HUMAN-GATE-DECISION-BRIEF 边界 |
| HLD | `docs/design/HLD.md` | 人工门禁总体流程 |
| ADR | ADR-004 至 ADR-006、ADR-012、ADR-013 | CP 门禁、approve 语义、LLD queue |
| Feature Matrix | `docs/design/FEATURE-DESIGN-MATRIX.md` | required / full-lld 判定 |
| Rules | `AGENTS.md`、`delivery/rules/AGENTS.md` | 人工检查点、Human Gate Launch Protocol、用户视角复述 |

## 4. 目标与非目标

| 类型 | 内容 | 来源 |
|---|---|---|
| Goal | 所有人工决策项在发起确认前进入结构化队列 | ADR-005 |
| Goal | 用户看到 checklist 路径、自动预检、决策收集覆盖、待决策表和不授权项 | AGENTS |
| Goal | 用户回复 `approve` 的含义可审计、可回填 | ADR-006 |
| Non-Goal | 代替阶段内 meta-pm / meta-se 与用户的草案讨论 | delegated_interaction |
| Non-Goal | 授权真实运行、外部写入、publish 或 live 操作 | 安全边界 |

## 5. Feature 边界与相邻对象

| 对象 | 本 Feature 负责 | 不负责 | 相邻 Feature / 模块 | 边界判定依据 |
|---|---|---|---|---|
| Human Gate | CP2 / CP3 / CP5 / CP8 正式发起与回填 | 阶段内自由讨论 | Workflow Orchestration | ADR-004 |
| Pending Decision | 结构化字段、去重、展示、状态更新 | 生成业务问题内容本身 | meta-pm / meta-se / meta-dev / meta-qa | ADR-005 |
| Not Authorized Items | 明确 approve 不包含的操作 | 执行真实发布或写入 | Release Readiness | ADR-006 |
| Validator | 校验 checkpoint 和发起消息完整性 | 判断业务方案对错 | `meta-flow check human-gate` | Human Gate Protocol |

## 6. 推荐方案

| 设计点 | 推荐做法 | 理由 | 代价 |
|---|---|---|---|
| 发起者 | 仅 `meta-po` 发起正式人工门禁 | 统一用户确认口径 | 阶段 Agent 需交还摘要 |
| 数据模型 | `STATE.md.human_gate_decisions.pending_human_decisions[]` 为状态机对象 | 支持恢复、去重、回填 | 写入字段更多 |
| 来源覆盖 | Decision Brief 必须含 `Decision Collection Coverage` | 防止漏扫下游 OPEN / Q / LCQ | 需要记录扫描来源 |
| 展示格式 | 对话打印待决策表和三个 exact 回复 | 降低用户理解成本 | 消息较长 |
| 不授权项 | 独立列出真实运行 / 凭据 / 外部写入 / publish / live | 防止误授权 | 需分类判断 |
| 校验 | 发起前运行 validator | 把协议问题前置暴露 | 需要维护脚本 |

## 7. 方案对比与决策记录

| Decision ID | 方案 | Pros | Cons | Impact Surface | Recommendation | When to switch |
|---|---|---|---|---|---|---|
| DQ-HG-001 | 下游 Agent 各自问用户 | 简单直接 | 多线程打断、答案分散 | 用户体验、状态一致性 | 备选 | 只适用于 meta-pm / meta-se 委托阶段内草案讨论 |
| DQ-HG-001 | meta-po 统一 broker | 决策完整、可回填、可审计 | meta-po 负担更高 | CP2 / CP3 / CP5 / CP8 | 推荐 | 若平台提供更强结构化协作工具，可保留 broker 语义但换展示方式 |

## 8. 数据模型与状态

| Object | Owner | 新增 / 修改字段 | 状态变化 | 兼容性 |
|---|---|---|---|---|
| pending_human_decisions[] | meta-po | id、decision_type、question、recommendation、alternatives、pros_cons、impact_risk、rollback、status | pending -> resolved / n/a / converted-to-spike | 旧 Markdown 开放项必须迁入或分类 |
| decision_collection_coverage | meta-po | scanned_sources、candidate_count、included_count、n/a_reasons、missing_sources | draft -> ready | 缺失时 Human Gate FAIL |
| non_authorized_items[] | meta-po | item、reason、requires_separate_authorization | active | 设计确认不授权运行 |
| CP checkpoint | meta-po | Decision Brief、Checklist、人工审查结果 | draft -> awaiting-user -> filled | 用户对话确认后仍回填 |

## 9. API / 接口设计

| Interface ID | 调用方 | 被调用方 | 输入契约 | 输出契约 | 错误模型 |
|---|---|---|---|---|---|
| IF-HG-01 | 下游 Agent | STATE / meta-po | 决策项或 clarification item，字段完整 | 队列新增或交还摘要 | 字段缺失则 meta-po 标为 incomplete |
| IF-HG-02 | meta-po | validator | checkpoint path，可选 launch message | PASS / FAIL 和缺失项 | FAIL 时不得发起门禁 |
| IF-HG-03 | 用户 | meta-po | `approve` / `修改: <具体修改点>` / `reject` | 人工结果回填、状态推进或回退 | 修改 / reject 触发重算 Decision Brief |

## 10. 关键流程

| Flow ID | 触发条件 | 主流程 | 异常流程 | 输出 / 状态变化 | 观测点 |
|---|---|---|---|---|---|
| FLOW-HG-01 | CP2 / CP3 / CP5 / CP8 前 | 扫描来源 -> 分类问题 -> 生成 Decision Brief -> validator -> 对话发起 | 缺待决策表 / checklist / 覆盖摘要时阻断 | awaiting-user | checkpoint、validator 输出 |
| FLOW-HG-02 | 用户 `approve` | 接受推荐方案 -> 回填 checkpoint -> 清空 / 标记 resolved -> 推进阶段 | 有不授权项时保持不授权 | phase advance | STATE history |
| FLOW-HG-03 | 用户 `修改:` | 定位决策 ID -> 更新方案 / 影响面 -> 重发 Decision Brief | 不能定位时要求用户补充具体修改点 | awaiting-user | revised checkpoint |
| FLOW-HG-04 | 用户 `reject` | 标记 rejected -> 回退到对应阶段或阻断 | 无回退目标时询问 | changes-requested / blocked | STATE history |

## 11. 人机协作与确认点

| 确认点 | 触发条件 | 需要谁确认 | 推荐方案 | 备选方案 | 不授权项 |
|---|---|---|---|---|---|
| CP2 | 需求 / 场景 / 范围基线 | 用户 | approve 推荐方案 | 修改 / reject | 不授权实现、外部写入 |
| CP3 | 蓝图 / HLD / ADR | 用户 | approve 推荐架构 | 修改 / reject | 不授权真实部署 / 运行 |
| CP5 | 全量 Story 设计证据 | 用户 | approve 设计证据批次 | 修改单个 Story / reject | 不授权实现外部操作 |
| CP8 | 交付就绪 | 用户 | approve 交付状态和风险接受 | 修改 / reject | 不授权 publish / live，除非单独列出 |

## 12. 异常、失败与降级策略

| Failure ID | 失败条件 | 系统行为 | 用户可见影响 | 恢复 / 回退 | 测试入口 |
|---|---|---|---|---|---|
| F-HG-01 | Decision Brief 缺失 | 不发起人工门禁 | 提示缺失来源 | 重新生成 Brief | validator |
| F-HG-02 | 待决策项 > 0 但对话未打印表格 | 门禁发起失败 | 用户不会看到 approve 入口 | 补发完整消息 | validator |
| F-HG-03 | 用户修改范围 / 安全 / 授权含义 | 重算影响面 | 需要重新确认 | 重新发布 Decision Brief | CP checkpoint |
| F-HG-04 | 下游只在 Markdown 留 OPEN | 分类为缺失来源或导入队列 | 阶段阻断或 N/A 说明 | 扫描并分类 | CP precheck |

## 13. 权限与安全

| Rule ID | 规则 | 触发条件 | 失败行为 | 测试入口 |
|---|---|---|---|---|
| SEC-HG-01 | `approve` 不授权真实运行 | 所有人工门禁 | 若消息未说明则门禁失败 | validator |
| SEC-HG-02 | runtime_authorization 必须单独决策 | 外部写入、publish、live | 阻断执行 | Decision Brief |
| SEC-HG-03 | 凭据 / secret 不进入 memory 或文档 | 用户提供敏感信息 | 要求脱敏或忽略 | review |

## 14. 测试与验收策略

| 验收对象 | 测试层级 | 覆盖场景 | 自动化方式 | 未自动化原因 / 手工入口 |
|---|---|---|---|---|
| Human Gate checkpoint | static | Brief 结构完整 | `meta-flow check human-gate` | 人工审查业务合理性 |
| Launch message | static | 三个 exact 回复、待决策表、不授权项 | validator `--launch-message-file` | 用户理解仍需人工确认 |
| STATE queue | review | 决策项字段完整 | CP precheck | 状态语义人工审查 |

## 15. Story 拆分建议与 LLD 策略

| Story ID | feature_design_refs | lld_policy.required_level | 触发原因 | 必须进一步设计的问题 | 可用设计证据 |
|---|---|---|---|---|---|
| HG-PROTOCOL-CHANGE | docs/features/human-gate-decision-brief/DESIGN.md | full-lld | security / runtime_authorization / human-confirmation | 字段迁移、validator、回填策略 | Feature DESIGN + Story LLD |
| HG-WORDING-ONLY | docs/features/human-gate-decision-brief/DESIGN.md | technical-note | low-risk | 文案是否改变确认语义 | Story 技术说明 |

## 16. 下游消费契约

| 消费方 | 消费时机 | 输入契约 | 输出 / 状态要求 | 降级策略 |
|---|---|---|---|---|
| checkpoint-manager | 生成 CP2 / CP3 / CP5 / CP8 | 决策队列、覆盖摘要、不授权项 | checkpoint 含 Decision Brief | 缺字段则 FAIL |
| state-router | 状态推进 | 人工结果和 resolved 决策项 | 推进或回退 | 不一致则 blocked |
| meta-po | 对话发起 | 完整 checklist 路径、预检结论、决策表 | awaiting-user | validator fail 时不发起 |

## 17. 风险与回退

| Risk ID | 风险 | 影响 | 缓解 | 回退 |
|---|---|---|---|---|
| R-HG-01 | 决策表过长 | 用户阅读成本高 | 只展示关键决策，非阻断项分类 N/A / follow-up | 拆分为后续 CR |
| R-HG-02 | 下游问题未结构化 | 决策漏收 | Human Gate 前扫描 Q / OPEN / LCQ | 回退下游补字段 |
| R-HG-03 | 文案修改改变授权语义 | 安全风险 | wording-only 也需检查不授权项 | 重发 Brief |

## 18. Gotchas

- 不要把阶段内草案讨论和正式人工门禁混在一起。
- 不要把“用户通过设计”解释成“用户授权执行”。
- 决策项为 0 时也必须说明扫描来源和原因。
