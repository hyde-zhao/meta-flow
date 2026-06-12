---
name: workflow-orchestrator
description: "Sample generated workflow orchestrator used by local eval fixtures."
---

# Workflow Orchestrator

Read `WORKFLOW-MANIFEST.yaml`, route the task through intake, plan, execute, verify, and done states, and stop when verification reports a blocking issue.

The orchestrator treats `approve` as acceptance of listed recommendations only. It does not authorize external writes or real release execution.
