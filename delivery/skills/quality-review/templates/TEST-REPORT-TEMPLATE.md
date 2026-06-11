---
status: draft
version: "1.0"
scope: ""
created_at: ""
validation_mode: "runtime|static-only|dry-run-only|review-only|mixed"
verification_result: "PASS|PASS_WITH_RISK|BLOCKED|NEEDS_REWORK|NEEDS_DESIGN_CLARIFICATION|WAIVED"
---

# Test Report

## 验证范围

| 项 | 内容 |
|---|---|
| Feature / Story | <name / id> |
| 验证范围 | <scope> |
| 非范围 | <out of scope> |
| 上游设计 | <HLD / ADR / DESIGN / LLD> |
| 实现证据 | <IMPLEMENTATION / DEV-LOG / Story implementation_context> |
| validation_mode | runtime / static-only / dry-run-only / review-only / mixed |

## 验证对象清单

| 对象 | 类型 | 验证方式 | 是否阻塞 | 证据 |
|---|---|---|---|---|
| `<path>` | code / prompt-skill / template-schema / installer-platform / guardrail-validator / docs / state-process / release | static / unit / fixture / contract / integration / dry-run / regression / manual | yes / no | <evidence> |

## 验证追踪矩阵

| Scenario | Requirement | Story | Design Contract | Implementation | Test / Check | Status | Risk |
|---|---|---|---|---|---|---|---|
| SCN-001 | REQ-001 | ST-001 | <contract> | <path / item> | <command / fixture / review> | PASS / GAP / WAIVED / RISK | <risk / N/A> |

## 设计契约验证

| 契约 | 来源 | 验证方式 | 是否阻塞 | 结果 | 证据 |
|---|---|---|---|---|---|
| <must / should / must-not> | HLD / ADR / LLD / DESIGN / IMPLEMENTATION / PLATFORM-CONTRACTS | guardrail / dry-run / fixture / review / test | yes / no | PASS / FAIL / N/A / WAIVED | <evidence> |

## 分层验证计划

| 验证层 | 方法 | 目标 | 必跑 | 结果 | 未覆盖风险 |
|---|---|---|---|---|---|
| 静态检查 | `git diff --check` | 格式 / schema / frontmatter | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| 单元测试 | `pytest ...` | 核心逻辑 | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| Prompt / Skill Fixture | fixture / 人工样例 | Prompt 行为和边界 | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| 契约测试 | schema / validator | 上下游兼容 | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| 集成测试 | integration | 多模块协作 | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| 平台 dry-run | install dry-run | 平台渲染和路径 | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| 回归测试 | historical fixture | 防止旧行为破坏 | yes / conditional / no | PASS / FAIL / N/A | <risk> |
| 人工审查 | checklist / review | 语义质量和风险 | yes / conditional / no | PASS / FAIL / N/A | <risk> |

## 测试环境

| 字段 | 值 |
|---|---|
| Runtime | <python/node/os/etc> |
| Commit / Diff | <ref> |
| Validation Env | <path or N/A> |

## 测试命令

| Command ID | 命令 | 结果 | 证据 |
|---|---|---|---|
| CMD-01 | `<command>` | PASS / FAIL / SKIPPED | <log / output> |

## Prompt / Skill Fixture 验证

| Fixture ID | 输入 / 场景 | 期望 | 结果 | 证据 |
|---|---|---|---|---|
| FX-001 | minimal-input / conflicting-rules / platform-codex / forbidden-scope | <expected> | PASS / FAIL / N/A | <path / note> |

## 平台适配验证

| 平台 | 检查项 | 预期 | 结果 | 证据 |
|---|---|---|---|---|
| Claude Code | direct ask agent 有 `AskUserQuestion` | yes / n/a | PASS / FAIL / N/A | <evidence> |
| Codex | 不渲染 Claude-only schema | yes / n/a | PASS / FAIL / N/A | <evidence> |
| install | project / user scope dry-run 可执行 | yes / n/a | PASS / FAIL / N/A | <evidence> |

## 覆盖结果

| Scenario ID | Story ID | 测试类型 | 覆盖状态 | 证据 | 缺口 / 原因 |
|---|---|---|---|---|---|
| SCN-001 | ST-001 | unit / integration / regression / manual | covered / gap / waived | <file / command> | <reason> |

## 失败与缺口

| Finding ID | 严重度 | 问题 | 影响 | 下一动作 | 责任方 |
|---|---|---|---|---|---|
| TST-001 | BLOCKING / REQUIRED / OPTIONAL | <问题> | <影响> | <动作> | meta-dev / meta-qa / human |

## 剩余风险

| Risk ID | 风险 | 等级 | 是否接受 | 接受人 / 条件 | 后续处理 |
|---|---|---|---|---|---|
| R-001 | <risk> | HIGH / MEDIUM / LOW | yes / no | <human / CP8 / condition> | <follow-up / N/A> |

## 结论

`PASS | PASS_WITH_RISK | BLOCKED | NEEDS_REWORK | NEEDS_DESIGN_CLARIFICATION | WAIVED`

## 阶段决策

| 结论 | 路由 | 条件 / 说明 |
|---|---|---|
| PASS / PASS_WITH_RISK / BLOCKED / NEEDS_REWORK / NEEDS_DESIGN_CLARIFICATION / WAIVED | none / meta-dev / meta-se / host-orchestrator / human | <下一步> |
