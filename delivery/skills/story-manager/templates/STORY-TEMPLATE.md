---
story_id: "STORY-{id}"
title: ""
story_slug: ""
status: "draft"
priority: "P0"
wave: "W1"
depends_on: []
dependency_contracts: []
feature_design_refs: []
lld_policy:
  required_level: "full-lld" # full-lld | technical-note | waived
  trigger_reasons: []
  rationale: ""
  waiver_reason: ""
  revisit_condition: ""
  evidence_path: ""
file_ownership:
  primary: []
  shared: []
  merge_owner: ""
  forbidden: []
lld_gate:
  required_inputs: ["HLD", "ADR", "FEATURE-DESIGN-MATRIX", "Story"]
  design_evidence_type: "full-lld" # full-lld | technical-note | waived
  design_evidence_path: ""
  status: "not-started"
implementation_gate:
  evidence_required: false
  evidence_path: ""
  evidence_type: "implementation-md|story-summary|dev-log|n/a"
  implementation_objects: []
  test_plan_refs: []
  local_validation_results: []
  status: "not-started"
verification_gate:
  validation_mode: "runtime|static-only|dry-run-only|review-only|mixed"
  validation_target:
    sut_type: "code-project|generated-workflow|prompt-skill-workflow|meta-flow-core-code|agentic-code-product|mixed|unknown"
    native_test_required: true
    workflow_eval_required: false
    prompt_bundle_required: false
    eval_suite_refs: []
    prompt_bundle_refs: []
    runtime_authorization_required: []
  workflow_eval:
    run_id: ""
    run_summary_path: ""
    suite_health_path: ""
    prompt_bundle_hash_status: "pending|pass|fail|n/a"
    eval_trace_coverage_status: "pending|complete|partial|n/a"
    eval_suite_health_status: "pending|pass|fail|n/a"
  verification_report_path: ""
  test_report_path: ""
  review_path: ""
  cp7_result: "PASS|PASS_WITH_RISK|BLOCKED|NEEDS_REWORK|NEEDS_DESIGN_CLARIFICATION|WAIVED|not-started"
  validation_object_inventory_status: "pending|complete|n/a"
  traceability_matrix_status: "pending|complete|n/a"
  design_contract_verification_status: "pending|complete|n/a"
  layered_validation_plan_status: "pending|complete|n/a"
  remaining_risks: []
  route_to: ""
  status: "not-started"
dev_gate:
  design_evidence_confirmed: false
  lld_confirmed: false # legacy alias；以 design_evidence_confirmed 为准
  dependencies_satisfied: false
  file_conflict_free: false
task_count: 0
created_at: ""
updated_at: ""
---

## 目标

[一句话描述本 Story 要实现什么]

## 开发上下文（dev_context）

- **输入文件**：
- **输出文件**：
- **设计约束**：
- **Feature 设计引用**：`feature_design_refs` 必须列出本 Story 消费的 `docs/features/<feature>/DESIGN.md`、`TEST-PLAN.md`、`TASKS.md` 或 `waived` 证据。
- **LLD 策略**：`lld_policy.required_level` 取值为 `full-lld`、`technical-note`、`waived`；命中数据、安全、外部接口、并发、迁移或跨 Story 契约时默认 `full-lld`。
- **命名规范**：Story 卡片文件名必须为 `STORY-{id}-{story_slug}.md`，其中 `story_slug` 是 `title` 的 kebab-case 稳定片段
- **平台目标**：

### 依赖与并行门控

> `depends_on` 必须声明依赖类型，供 host-orchestrator 计算 `lld_ready` 与 `dev_ready`。

| 上游 Story | 类型（contract/runtime/file-conflict） | LLD 门控 | 开发门控 | 说明 |
|------------|-----------------------------------------|----------|----------|------|
| STORY-XXX | contract | upstream_lld_or_story_contract_declared | upstream_contract_frozen | |

### 文件所有权

| 类型 | 文件 | Owner / 合并规则 |
|------|------|------------------|
| primary | | 当前 Story 独占写入 |
| shared | | 必须指定 merge_owner |
| forbidden | | 当前 Story 禁止修改 |

### 文件系统布局

> 预期创建/修改的文件列表（含完整路径）。

```
<root>/
├── .agents/skills/<skill-name>/
│   └── SKILL.md           ← 新建
├── .agents/agents/
│   └── <agent-name>.md    ← 新建 / 修改
└── ...
```

### 关键 Frontmatter 字段

| 文件 | 字段 | 类型 | 必填 | 说明 / 取值范围 |
|------|------|------|------|----------------|
| SKILL.md | title | string | ✅ | Skill 显示名称 |
| SKILL.md | version | string | ✅ | 语义化版本号 |
| SKILL.md | description | string | ✅ | 一句话描述 |

### AI 可执行任务清单

> 使用 TASK-ID 前缀 + 确定性动词（创建/修改/删除）的原子任务。

| TASK-ID | 动作 | 目标文件 | 描述 |
|---------|------|---------|------|
| T1 | 创建 | `.agents/skills/<name>/SKILL.md` | |
| T2 | 修改 | | |

## 实现执行上下文（implementation_context）

> CP6 前必须维护本节。复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / Guardrail / 平台适配 Story 必须生成完整 IMPLEMENTATION；普通 Story 可用本节和 DEV-LOG 覆盖。

| 项目 | 内容 |
|---|---|
| 实现证据类型 | implementation-md / story-summary / dev-log / n/a |
| 实现证据路径 | `process/stories/STORY-{id}-{story_slug}-IMPLEMENTATION.md` / `DEV-LOG.md` |
| 实现对象清单 | code / prompt-skill / template-schema / installer-platform / guardrail-test / docs-handoff |
| 设计契约映射状态 | pending / complete / n/a |
| 单元测试 / Fixture 计划 | `<test refs>` |
| 最小实现切片 | `<slice ids>` |
| 局部验证结果 | `<commands / checks>` |
| 平台差异检查 | PASS / FAIL / N/A |
| 未覆盖项 | `<items or none>` |
| QA / Review / Doc 关注点 | `<handoff notes>` |

## 技术说明

> 当 `lld_policy.required_level=technical-note` 或 `waived` 时，本节是 CP5 正式设计证据。`full-lld` Story 可在此引用 LLD 文件，不重复展开。

| 项目 | 内容 |
|---|---|
| 设计证据类型 | full-lld / technical-note / waived |
| 设计依据 | HLD / ADR / FEATURE-DESIGN-MATRIX / Feature DESIGN |
| 文件影响 | <create / modify / delete 文件列表> |
| 接口 / 数据 / 权限变化 | <无新增 / 具体变化> |
| 异常、失败与回退 | <失败路径和回退策略> |
| 测试入口 | <命令 / TEST-PLAN / 手工验收> |
| 风险与重访条件 | <risk / revisit_condition> |
| 偏离记录 | <实现偏离设计时记录原因和影响> |

## 验证上下文（validation_context）

> CP7 前后维护本节。复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / Guardrail / 平台适配 Story 必须引用完整 `VERIFICATION-REPORT.md`；低风险 Story 可在本节保留验证摘要。

| 项目 | 内容 |
|---|---|
| validation_mode | runtime / static-only / dry-run-only / review-only / mixed |
| validation_target.sut_type | code-project / generated-workflow / prompt-skill-workflow / meta-flow-core-code / agentic-code-product / mixed |
| workflow eval | code-project 默认 N/A；workflow / prompt / mixed 默认要求 eval suite 与 prompt bundle 证据 |
| 验证报告路径 | `docs/quality/VERIFICATION-REPORT.md` / Feature scoped / N/A |
| 测试报告路径 | `docs/quality/TEST-REPORT.md` / N/A |
| Review 路径 | `docs/quality/REVIEW.md` / N/A |
| 验证对象清单状态 | pending / complete / n/a |
| 验证追踪矩阵状态 | pending / complete / n/a |
| 设计契约验证状态 | pending / complete / n/a |
| 分层验证计划状态 | pending / complete / n/a |
| Prompt / Skill fixture | PASS / FAIL / N/A |
| Workflow eval evidence | PASS / FAIL / N/A；引用 `process/evals/runs/<run-id>/run-summary.json` 和 `docs/quality/EVAL-SUITE-HEALTH.md` |
| 平台 dry-run | PASS / FAIL / N/A |
| 人工 / 语义审查 | PASS / RISK / FAIL / N/A |
| CP7 结论 | PASS / PASS_WITH_RISK / BLOCKED / NEEDS_REWORK / NEEDS_DESIGN_CLARIFICATION / WAIVED |
| 剩余风险 | `<risk ids or none>` |
| 路由 | none / meta-dev / meta-se / host-orchestrator / human |

## 量化验收标准（acceptance_criteria）

- [ ] **完整性**：产物文件数量 >= N（期望输出数：N）
- [ ] **平台适配**：至少 1 个平台安装目录符合 PLATFORM-INSTALL-SPEC.md 规范
- [ ] **验收标准覆盖**：verified_criteria == total_criteria
- [ ] **安全合规**：dangerous-command-scan 返回 0 个风险项
- [ ] **命名规范**：文件名符合 `^[a-z][a-z0-9-]+\.md$`
- [ ] **Frontmatter 完整**：title、version、description 字段均非空
- [ ] **可安装性**：目录树结构比对通过（DryRun 或结构校验）
- [ ] **文档覆盖**（OPTIONAL）：功能在 USER-MANUAL.md 中有对应说明

## 阻塞说明（如有）

（无）
