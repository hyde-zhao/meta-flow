# Workflow Eval CI Policy

The default CI profile is local and deterministic.

## Required Local Checks

```bash
meta-flow eval validate --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml
meta-flow eval run --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/generated-workflow-basic
meta-flow eval suite-health --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md
meta-flow eval validate --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml
meta-flow eval run --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/runtime-workflow-basic
meta-flow eval feedback sync --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/feedback/raw
meta-flow eval feedback normalize --in process/evals/feedback/raw --out process/evals/feedback/run-exec
meta-flow eval feedback triage --runs process/evals/feedback/run-exec --out process/evals/feedback/triage
meta-flow eval suite-health --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --runs process/evals/runs --triage process/evals/feedback/triage --feedback-metrics process/evals/feedback/run-exec --out docs/quality/EVAL-SUITE-HEALTH.md
meta-flow eval release-check --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --runs process/evals/runs --profile release --triage process/evals/feedback/triage --format json --json-out process/evals/release-check.json
```

## External Adapter Checks

External adapter checks are optional and disabled by default. They require explicit `runtime_authorization` because they may use credentials, network access, hosted trace backends, or model-backed graders.

## Failure Policy

- Missing schema keys: blocking.
- Missing prompt bundle hashes: blocking.
- Grader failure in required suites: blocking.
- Blocking case failure in release-check: blocking.
- Missing prompt_bundle_hashes grader or hash mismatch in release profile: blocking.
- runtime_required case without passing runtime_artifact evidence: incomplete release evidence.
- source_issue without regression_asset: incomplete release evidence.
- Open P0 GAP or blocking/high feedback ISSUE without regression asset in release-check: blocking.
- suite-health reports runtime / feedback / RUN-EXEC / ISSUE / GAP / backlog trends but does not make the final release decision.
- Optional adapter unavailable: non-blocking when adapter is disabled.
