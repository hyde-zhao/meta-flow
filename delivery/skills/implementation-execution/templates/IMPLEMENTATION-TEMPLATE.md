---
status: draft
version: "1.0"
story_id: ""
story_slug: ""
feature_id: ""
implementation_type: "story|feature|prompt-skill|guardrail|installer|platform|docs|mixed"
source_story: "process/stories/STORY-{id}-{story_slug}.md"
source_design_evidence: ""
created_by: "meta-dev"
created_at: ""
updated_at: ""
---

# Implementation: <Story / Feature / Change>

## 1. 实现摘要

| 项目 | 内容 |
|---|---|
| 实现目标 | <本次实现要落成什么工程资产> |
| 行为变化 | <用户可见 / agent 可见 / 平台可见变化> |
| 范围边界 | <本次不做什么> |
| CP6 证据 | `process/checks/CP6-...md` |

## 2. 上游设计引用

| 来源 | 路径 / ID | 本次消费内容 |
|---|---|---|
| Story | `process/stories/STORY-...md` | 范围、AC、文件所有权 |
| Story 设计证据 | `process/stories/STORY-...-LLD.md` / `## 技术说明` / waived | 实现约束 |
| HLD / ADR | `docs/design/HLD.md` / `docs/design/ARCHITECTURE-DECISION.md` | 架构边界 |
| Feature 设计 | `docs/features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md` | Feature 契约 |
| Feature Matrix | `docs/design/FEATURE-DESIGN-MATRIX.md` | `feature_design_refs` / `lld_policy` |

## 3. 实现前置检查

| 检查项 | 结果 | 证据 / 说明 |
|---|---|---|
| 上游 Feature 设计存在或 N/A | PASS / FAIL / N/A |  |
| Story 范围明确 | PASS / FAIL |  |
| 待确认问题已关闭 | PASS / FAIL |  |
| 影响范围可定位 | PASS / FAIL |  |
| 验证方式明确 | PASS / FAIL |  |
| 当前 Wave / dev_gate 满足 | PASS / FAIL |  |
| 文件所有权无冲突 | PASS / FAIL |  |

## 4. 实现对象清单

| 对象 | 类型 | 目标 | 是否必须 | 验证方式 |
|---|---|---|---|---|
| `<path>` | code / prompt-skill / template-schema / installer-platform / guardrail-test / docs-handoff | <目标> | yes / no | pytest / fixture / structure-check / guardrail / dry-run / diff-check / manual |

## 5. 设计契约映射

| 设计要求 | 来源 | 实现位置 | 实现动作 | 验证 |
|---|---|---|---|---|
| <must / should / must-not> | LLD / DESIGN / ADR / Story | `<path>` | create / modify / delete | <command / check> |

## 6. 单元测试 / Fixture 计划

| 测试对象 | 测试类型 | 输入 / Fixture | 期望 | 覆盖风险 | 状态 |
|---|---|---|---|---|---|
| `<object>` | unit / fixture / structure-check / contract / dry-run / manual | <input> | <expected> | <risk> | planned / passed / failed / n/a |

## 7. 最小实现切片

| Slice ID | 对应设计契约 | 改动对象 | 输出文件 | 局部验证 | 状态 |
|---|---|---|---|---|---|
| IMPL-S1 | <contract> | <object> | `<path>` | <command / check> | pending / done / blocked |

## 8. 变更说明

### 8.1 代码变更

| 文件 | 动作 | 说明 |
|---|---|---|
| `<path>` | create / modify / delete |  |

### 8.2 Prompt / Skill 变更

| 文件 | 动作 | 说明 |
|---|---|---|
| `<path>` | create / modify / delete |  |

### 8.3 模板 / Schema 变更

| 文件 | 动作 | 说明 |
|---|---|---|
| `<path>` | create / modify / delete |  |

### 8.4 Guardrail / 测试变更

| 文件 / 命令 | 动作 | 说明 |
|---|---|---|
| `<path>` | create / modify / run |  |

### 8.5 文档变更

| 文件 | 动作 | 说明 |
|---|---|---|
| `<path>` | create / modify / delete |  |

## 9. 平台差异处理

| 平台 | 检查项 | 预期 | 结果 |
|---|---|---|---|
| Claude Code | direct ask agent 有 `AskUserQuestion` | yes / n/a | PASS / FAIL / N/A |
| Claude Code | non-direct agent 不声明 `AskUserQuestion` | yes / n/a | PASS / FAIL / N/A |
| Codex | 不写 Claude-only `tools` schema | yes / n/a | PASS / FAIL / N/A |
| Codex | 无 `request_user_input` 时可降级 | yes / n/a | PASS / FAIL / N/A |
| install | dry-run 可执行 | yes / n/a | PASS / FAIL / N/A |

## 10. 验证结果

| 命令 / 检查 | 结果 | 证据 |
|---|---|---|
| `git diff --check` | PASS / FAIL / N/A |  |
| `uv run --python 3.11 pytest <tests>` | PASS / FAIL / N/A |  |
| `uv run --python 3.11 python scripts/check_delivery_guardrails.py` | PASS / FAIL / N/A |  |
| `uv run --python 3.11 meta-flow install --platform <platform> --scope project --component agent --project-dir <path> --dry-run` | PASS / FAIL / N/A |  |

## 11. 未覆盖项

| 未覆盖内容 | 原因 | 后续处理 |
|---|---|---|
| <item> | <reason> | <owner / revisit condition> |

## 12. 风险与回滚

| Risk ID | 风险 | 影响 | 缓解 | 回滚 / 切换条件 |
|---|---|---|---|---|
| R-01 | <risk> | <impact> | <mitigation> | <rollback> |

## 13. 设计缺口反馈

| Gap ID | 发现阶段 | 问题 | 应反馈到 | 是否阻塞 | 推荐处理 |
|---|---|---|---|---|---|
| GAP-01 | implementation | <issue> | BLUEPRINT / HLD / FEATURE-DESIGN / LLD / TEST-MATRIX / decision queue | yes / no | <action> |

## 14. QA / Review / Doc 后续交接

### QA 关注点

- <验证重点>

### Review 关注点

- <评审重点>

### Doc 关注点

- <文档重点>
