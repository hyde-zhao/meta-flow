---
feature_id: "FEAT-WORKFLOW-EVAL-GOVERNANCE"
status: "baseline"
version: "1.0"
created_at: "2026-06-11T19:41:44+08:00"
source_cr: "CR-019"
owner: "host-orchestrator"
---

# Workflow Eval Governance Design

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-11 | host-orchestrator | 新增 workflow eval / prompt bundle / case lifecycle / runner / CP7 integration / optional adapter 治理设计 |

## 1. 问题定义

Meta Flow 既能开发纯代码，也能生产 Agent / Skill / workflow 产物。旧验证方式主要覆盖 meta-flow 自身与代码改动，缺少对“生成工作流是否可运行、可追踪、可回归、可审计”的稳定验证面。

本 Feature 引入一组本地优先、可追踪、可逐步接 CI 的评估契约：

- `WORKFLOW-EVAL.yaml`：评估套件和 grader 契约。
- `PROMPT-BUNDLE.yaml`：规则、Agent、Skill、模板、rubric、human gate 文案和 context policy 的版本与 hash 契约。
- `CASE-REGISTRY.yaml`：case 生命周期、覆盖分类、grader 引用和期望证据。
- `process/evals/runs/<run-id>/`：本地执行证据。
- `docs/quality/EVAL-SUITE-HEALTH.md` / `FAILURE-BACKLOG.md`：长期质量状态。

## 2. 项目类型分流

| 字段 | Owner | 作用 |
|---|---|---|
| `target_project_profile.project_kind` | `STATE.md` / state-router | 判断目标项目是 `code-project`、`workflow-product`、`agentic-code-product`、`mixed` 或 `unknown` |
| `validation_target.sut_type` | Story / verification gate | 判断当前 Story 或交付对象应执行 code、workflow、prompt 或 mixed 验证 |

纯代码项目默认只要求目标项目原生测试、构建、静态检查和质量评审。workflow / prompt-skill / mixed / agentic-code 项目才要求 workflow eval 和 prompt bundle 证据。

## 3. 架构决策

| 决策 | 推荐方案 | 备选方案 | 选择理由 |
|---|---|---|---|
| Eval 真相源 | 本地 canonical schema + deterministic runner | 直接采用 Promptfoo / DeepEval 作为主路径 | 本地 schema 更稳定，可无凭据、无网络、可审计；外部工具作为 adapter |
| Prompt 管理 | prompt bundle 保存引用、hash、版本、兼容性和 rollback | 复制完整 prompt 文本 | 避免 token 膨胀和敏感信息扩散 |
| CP7 集成 | eval evidence 作为 verification-execution 的输入证据 | eval run PASS 直接等于 CP7 PASS | CP7 仍需验证对象清单、追踪矩阵、设计契约和风险判断 |
| CI 策略 | 默认本地 deterministic suite | 默认执行外部 LLM judge / trace backend | 避免不稳定、凭据和网络风险 |

## 4. 契约边界

| 对象 | 输入 | 输出 | 不负责 |
|---|---|---|---|
| eval schema | suite / bundle / case registry 文档 | 可验证结构契约 | 不执行测试 |
| local runner | WORKFLOW-EVAL、PROMPT-BUNDLE、CASE-REGISTRY、fixture | run evidence、grader results、suite health 输入 | 不替代 CP7、不调用外部服务 |
| CP7 integration | run evidence、实现证据、设计证据 | VERIFICATION-REPORT / TEST-REPORT / REVIEW | 不修改实现 |
| adapters | canonical case / result / trace mapping | 可选外部工具映射 | 默认不上传 trace、不使用凭据 |

## 5. 运行证据结构

```text
process/evals/runs/<run-id>/
├── run-summary.json
└── run-summary.md
```

后续需要更完整 trace 时扩展为：

```text
RUN-EVIDENCE.yaml
TRACE.jsonl
RESULTS.json
SUMMARY.md
```

## 6. 失败路径

| 失败 | 处理 |
|---|---|
| schema 缺少必填字段 | CR-019 / CR-020 阻断 |
| prompt bundle hash drift | 阻断，除非 CR 明确接受变更 |
| case 引用不存在的 grader | 阻断 |
| runner 失败 | CP7 不得直接 PASS；写入 verification report |
| 外部 adapter 需要网络或凭据 | 转 runtime_authorization，默认不执行 |

## 7. Gotchas

- workflow eval 是验证层，不是新主流程。
- prompt bundle 是引用与 hash 契约，不是把提示词复制成大文件。
- deterministic grader 是默认路径，LLM judge 只能作为可选 adapter。
- generated workflow 的 eval assets 应写入目标项目约定目录；production 模式不得默认污染 meta-flow 自身 `delivery/`。
