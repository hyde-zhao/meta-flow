---
project_id: "meta-flow"
release_scope: "workflow-eval-governance"
created_at: "2026-06-11T19:50:20+08:00"
---

# Deploy Checklist

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-11 | host-orchestrator | 新增 workflow eval governance 部署检查 |

## 检查项

| 项 | 命令 / 证据 | 状态 |
|---|---|---|
| Python compile | `python3 -m py_compile meta_flow/cli.py meta_flow/evals/runner.py` | PASS |
| Eval validate | `python3 -m meta_flow.cli eval validate --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml` | PASS |
| Eval run | `python3 -m meta_flow.cli eval run --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/generated-workflow-basic` | PASS |
| Suite health | `python3 -m meta_flow.cli eval suite-health --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md` | PASS |
| External adapters | `evals/adapters/ADAPTERS.md` | DISABLED_BY_DEFAULT |

## 不授权项

- 不执行外部 Promptfoo / DeepEval / Langfuse / Garak。
- 不读取凭据。
- 不上传 trace。
- 不执行 publish / live / production 写入。
