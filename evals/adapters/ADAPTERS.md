# Optional Eval Adapter Policy

Meta Flow supports optional adapters for Promptfoo, DeepEval, Langfuse, and Garak as future extension points. These adapters are not enabled by default.

| Adapter | Default State | Allowed Without Runtime Authorization | Requires Runtime Authorization |
|---|---|---|---|
| Promptfoo | disabled | Static config generation and local dry-run planning | Running prompts against external providers |
| DeepEval | disabled | Mapping grader ids to DeepEval metric names | Model-backed scoring or network calls |
| Langfuse | disabled | Trace field mapping and masking policy review | Sending traces to a hosted backend |
| Garak | disabled | Local security suite planning | Any model/provider scan requiring credentials |

## Rules

- Adapter configuration must never contain secrets.
- Local deterministic graders remain the default CI-safe path.
- Any external service call requires a `runtime_authorization` decision item.
- Trace export must apply secret masking before data leaves the local workspace.
