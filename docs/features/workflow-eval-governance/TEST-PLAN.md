---
feature_id: "FEAT-WORKFLOW-EVAL-GOVERNANCE"
status: "baseline"
version: "1.0"
created_at: "2026-06-11T19:41:44+08:00"
source_cr: "CR-019"
owner: "host-orchestrator"
---

# Workflow Eval Governance Test Plan

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-11 | host-orchestrator | 新增 workflow eval governance 测试计划 |

## 测试矩阵

| 测试 ID | 范围 | 方法 | 命令 / 证据 | 期望 |
|---|---|---|---|---|
| WEG-T01 | eval package schema | deterministic validation | `meta-flow eval validate --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml` | PASS |
| WEG-T02 | local runner | deterministic graders | `meta-flow eval run --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/generated-workflow-basic` | PASS |
| WEG-T03 | suite health | run evidence summary | `meta-flow eval suite-health --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md` | PASS |
| WEG-T04 | Python syntax | static compile | `python3 -m py_compile meta_flow/cli.py meta_flow/evals/runner.py` | PASS |
| WEG-T05 | delivery guardrail | static guardrail | `PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_delivery_guardrails.py` | PASS |
| WEG-T06 | CR tracking | state consistency | `meta-flow check cr-tracking --project-root .` | PASS |

## N/A

| 项 | 理由 |
|---|---|
| External Promptfoo / DeepEval / Langfuse / Garak execution | 需要网络、凭据或外部运行授权，默认不执行 |
| Production target project write | 当前变更为 meta-flow 自改进，不写入外部目标项目 |
