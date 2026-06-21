# Source of Truth Map

> This file is the human-readable summary. The machine policy source is `process/policies/SOURCE-OF-TRUTH-MAP.yaml`.

| Object | Path | Truth Role | Edit Policy | Machine Truth |
|---|---|---|---|---|
| current_runtime_state | `process/state/STATE.current.json` | machine_truth | tool-generated | true |
| human_state_summary | `process/STATE.md` | generated_summary | tool-generated | false |
| cr_lifecycle | `process/state/CR-LEDGER.ndjson` | append_only_event_log | append-only | true |
| feature_registry | `docs/design/FEATURE-REGISTRY.yaml` | machine_truth | manual-edit | true |
| feature_design | `docs/features/<feature>/DESIGN.md` | human_authored_truth | manual-edit | true |
| context_pack | `process/context/*.context.json` | generated_packet | tool-generated-versioned | false |
| story_packet | `process/context/stories/*.json` | generated_packet | tool-generated-versioned | false |
| story_return | `process/returns/*.return.json` | agent_return | tool-generated | true |
| evidence_index | `process/evidence/*.index.json` | evidence_index | tool-generated | true |
| cp_result | `process/checks/*.result.json` | machine_truth | tool-generated | true |
| cp_summary | `process/checks/*.summary.md` | generated_summary | tool-generated | false |
