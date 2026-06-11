---
status: draft
version: "1.0"
story_id: ""
story_slug: ""
feature_id: ""
validation_mode: "runtime|static-only|dry-run-only|review-only|mixed"
verification_result: "PASS|PASS_WITH_RISK|BLOCKED|NEEDS_REWORK|NEEDS_DESIGN_CLARIFICATION|WAIVED"
source_story: "process/stories/STORY-{id}-{story_slug}.md"
source_implementation: ""
created_by: "meta-qa"
created_at: ""
updated_at: ""
---

# Verification: <Story / Feature / Change>

## 1. 结论

| 项目 | 内容 |
|---|---|
| 阶段决策 | PASS / PASS_WITH_RISK / BLOCKED / NEEDS_REWORK / NEEDS_DESIGN_CLARIFICATION / WAIVED |
| validation_mode | runtime / static-only / dry-run-only / review-only / mixed |
| 是否可进入下一阶段 | yes / no |
| 需要路由 | none / meta-dev / meta-se / host-orchestrator / human |
| CP7 证据 | `process/checks/CP7-...md` |

## 2. 验证范围

| 项 | 内容 |
|---|---|
| Feature / Story | <名称> |
| 验证范围 | <本轮验证覆盖什么> |
| 非范围 | <本轮不覆盖什么> |
| 上游设计 | <文档链接> |
| 实现摘要 | <IMPLEMENTATION / DEV-LOG / Story implementation_context> |
| 已接受风险 | <风险 ID / N/A> |
| 阻塞条件 | <条件 / N/A> |

## 3. 验证对象清单

| 对象 | 类型 | 来源 / 变更原因 | 验证方式 | 是否阻塞 | 证据 |
|---|---|---|---|---|---|
| `<path>` | code / prompt-skill / template-schema / installer-platform / guardrail-validator / docs / state-process / release | <diff / implementation / CR> | static / unit / fixture / contract / integration / dry-run / regression / manual | yes / no | <command / report / N/A> |

## 4. 验证追踪矩阵

| Scenario | Requirement | Story | Design Contract | Implementation | Test / Check | Status | Risk |
|---|---|---|---|---|---|---|---|
| SCN-001 | REQ-001 | ST-001 | <contract> | <path / impl item> | <command / fixture / review> | PASS / GAP / WAIVED / RISK | <risk / N/A> |

## 5. 设计契约验证清单

| 契约 | 来源 | 验证方式 | 是否阻塞 | 结果 | 证据 |
|---|---|---|---|---|---|
| <must / should / must-not> | HLD / ADR / LLD / DESIGN / IMPLEMENTATION / PLATFORM-CONTRACTS | guardrail / dry-run / fixture / review / test | yes / no | PASS / FAIL / N/A / WAIVED | <evidence> |

## 6. 分层验证计划

| 验证层 | 方法 | 目标 | 触发条件 | 必跑 | 结果 | 未覆盖风险 |
|---|---|---|---|---|---|---|
| 静态检查 | `git diff --check` | 格式 / whitespace | 非 trivial 改动 | yes | PASS / FAIL / N/A | <risk> |
| 单元测试 | `pytest ...` | 核心逻辑 | code / parser / state / installer / guardrail | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| Prompt / Skill Fixture | fixture / 人工样例 | Prompt 行为和边界 | prompt-skill / workflow | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| 契约测试 | schema / matrix / validator | 上下游兼容 | 模板 / 状态 / quality-review | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| 集成测试 | end-to-end / module integration | 多模块协作 | shared contracts | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| 平台 dry-run | install dry-run | 平台渲染和路径 | platform / installer | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| 回归测试 | 历史样例 / 最小回归集 | 防止旧行为破坏 | 修复 / shared behavior | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| 人工审查 | checklist / review | 语义质量和风险 | prompt / docs / design boundary | yes / conditional / no | PASS / FAIL / N/A | <risk> |

## 7. 自动化验证结果

| Command ID | 命令 / 检查 | 结果 | 证据 | 说明 |
|---|---|---|---|---|
| CMD-01 | `<command>` | PASS / FAIL / SKIPPED / N/A | <output / path> | <说明> |

## 8. Prompt / Skill Fixture 验证

| Fixture ID | 输入 / 场景 | 期望 | 实际 | 结果 | 证据 |
|---|---|---|---|---|---|
| FX-001 | minimal-input / conflicting-rules / platform-codex / forbidden-scope | <expected> | <actual summary> | PASS / FAIL / N/A | <path / note> |

## 9. 平台适配验证

| 平台 | 检查项 | 预期 | 结果 | 证据 |
|---|---|---|---|---|
| Claude Code | direct ask agent 有 `AskUserQuestion` | yes / n/a | PASS / FAIL / N/A | <evidence> |
| Claude Code | non-direct agent 不声明 `AskUserQuestion` | yes / n/a | PASS / FAIL / N/A | <evidence> |
| Codex | 不渲染 Claude-only schema | yes / n/a | PASS / FAIL / N/A | <evidence> |
| Codex | 无 `request_user_input` 时使用 exact-text / relay | yes / n/a | PASS / FAIL / N/A | <evidence> |
| install | project / user scope dry-run 可执行 | yes / n/a | PASS / FAIL / N/A | <evidence> |

## 10. 人工 / 语义质量审查

| 检查项 | 结果 | 是否阻塞 | 说明 |
|---|---|---|---|
| 需求一致性 | PASS / RISK / FAIL / N/A | yes / no |  |
| 场景覆盖 | PASS / RISK / FAIL / N/A | yes / no |  |
| Prompt / Agent 边界 | PASS / RISK / FAIL / N/A | yes / no |  |
| 文档可用性 | PASS / RISK / FAIL / N/A | yes / no |  |
| 错误信息可行动 | PASS / RISK / FAIL / N/A | yes / no |  |
| 是否只覆盖 happy path | PASS / RISK / FAIL / N/A | yes / no |  |

## 11. 问题清单

| ID | 等级 | 问题 | 影响 | 建议处理 | Owner | 状态 |
|---|---|---|---|---|---|---|
| Q-001 | BLOCKER / HIGH / MEDIUM / LOW / INFO | <问题> | <影响> | <建议> | meta-dev / meta-qa / meta-se / host-orchestrator / human | OPEN / RESOLVED / WAIVED |

## 12. 剩余风险

| Risk ID | 风险 | 等级 | 是否接受 | 接受人 / 条件 | 后续处理 |
|---|---|---|---|---|---|
| R-001 | <risk> | HIGH / MEDIUM / LOW | yes / no | <human / CP8 / condition> | <follow-up / N/A> |

## 13. 质量评审与修复输入

| 产物 | 路径 | 结论 |
|---|---|---|
| TEST-REPORT | `docs/quality/TEST-REPORT.md` | PASS / FAIL / N/A |
| REVIEW | `docs/quality/REVIEW.md` | approve / request-changes / block / N/A |
| FIXES | `docs/quality/FIXES.md` | none / pending / done / N/A |

## 14. 阶段决策

| 结论 | 路由 | 条件 / 说明 |
|---|---|---|
| PASS / PASS_WITH_RISK / BLOCKED / NEEDS_REWORK / NEEDS_DESIGN_CLARIFICATION / WAIVED | none / meta-dev / meta-se / host-orchestrator / human | <下一步> |

## 15. CP8 输入

| 输入项 | 内容 |
|---|---|
| 风险接受候选 | <risk IDs / N/A> |
| 后续 CR 候选 | <candidate / N/A> |
| 不授权项 | <runtime / credential / external write / publish / live / N/A> |
| 发布准备关注点 | <release-readiness input / N/A> |
