# Eval Run eval-20260612T005129Z

- suite_id: `generated-workflow-basic-suite`
- status: `PASS`
- created_at: `2026-06-12T00:51:29+00:00`
- eval_path: `evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml`

## Grader Results

| Grader | Type | Status | Evidence |
|---|---|---|---|
| `manifest-required-fields` | `required_fields` | `PASS` | WORKFLOW-MANIFEST.yaml contains required fields: artifacts, checkpoints, entrypoints, schema_version, workflow_id, workflow_type |
| `prompt-bundle-required-fields` | `required_fields` | `PASS` | PROMPT-BUNDLE.yaml contains required fields: bundle_id, compatibility, components, rollback, schema_version, version |
| `artifact-paths-exist` | `path_exists` | `PASS` | all paths exist: agents/workflow-orchestrator.md, skills/sample-skill/SKILL.md, prompts/rules.md, CASE-REGISTRY.yaml |
| `prompt-bundle-hashes` | `prompt_bundle_hashes` | `PASS` | prompts/rules.md sha256 OK; agents/workflow-orchestrator.md sha256 OK; skills/sample-skill/SKILL.md sha256 OK |
| `case-registry-links` | `case_registry_links` | `PASS` | 3 case(s) reference existing graders |
| `no-live-or-secret-actions` | `forbidden_patterns` | `PASS` | no forbidden patterns matched in agents/*.md, skills/*/SKILL.md, prompts/*.md |

## Issues

| Severity | Code | Path | Message |
|---|---|---|---|
| INFO | none |  | No package-level issues |
