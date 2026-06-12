# Generated Workflow Basic Eval Coverage Matrix

| Case ID | Category | Target | Graders | Covered Risk |
|---|---|---|---|---|
| CASE-001 | smoke | `WORKFLOW-MANIFEST.yaml` | manifest-required-fields, artifact-paths-exist | Missing entrypoint, checkpoints, or artifact routing |
| CASE-002 | regression | `PROMPT-BUNDLE.yaml` | prompt-bundle-required-fields, prompt-bundle-hashes | Prompt drift or untracked prompt changes |
| CASE-003 | security | generated prompts | no-live-or-secret-actions, case-registry-links | Live action, credential, or external write leakage |
