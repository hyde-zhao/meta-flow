# Workflow Eval CI Policy

The default CI profile is local and deterministic.

## Required Local Checks

```bash
meta-flow eval validate --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml
meta-flow eval run --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/generated-workflow-basic
meta-flow eval suite-health --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md
```

## External Adapter Checks

External adapter checks are optional and disabled by default. They require explicit `runtime_authorization` because they may use credentials, network access, hosted trace backends, or model-backed graders.

## Failure Policy

- Missing schema keys: blocking.
- Missing prompt bundle hashes: blocking.
- Grader failure in required suites: blocking.
- Optional adapter unavailable: non-blocking when adapter is disabled.
