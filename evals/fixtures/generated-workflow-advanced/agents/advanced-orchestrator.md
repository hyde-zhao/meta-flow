# Advanced Workflow Orchestrator

artifact_id: advanced-workflow
trace_id: TRACE-ADV-001
source_decision_id: CR-028

## States

### requirement-clarification

Collect structured requirements before design. Transition: requirement-clarification -> solution-design.

### solution-design

Produce the design package. Transition: solution-design -> story-execution.

### story-execution

Execute implementation and verification waves after design approval.

## GATE-1 Requirement Review

HARD-STOP manual gate. The user must reply approve or reject before the workflow can leave requirement review.

| Decision ID | Type | Recommended | Alternative | Rollback |
|---|---|---|---|---|
| DQ-ADV-001 | scope | Approve requirement baseline | Request changes | Return to requirement-clarification |

Entry Criteria: requirements are structured.
Checklist: review scope, risks, and acceptance criteria.
Exit Criteria: decision is approve or reject.
Deliverables: requirement baseline and decision record.

### GATE-2 Design Readiness

Entry Criteria: HLD is present.
Checklist: verify dependency direction and artifact trace.
Exit Criteria: design package is internally consistent.
Deliverables: HLD, task plan, and handoff capsule.

## Skill Chain

requirement-clarification uses requirement-extraction then scenario-expansion.

solution-design uses blueprint-design then hld-designer.
