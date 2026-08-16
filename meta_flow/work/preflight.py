"""Read-only preflight adapter which consumes the validation kernel only."""

from __future__ import annotations

from dataclasses import dataclass

from meta_flow.work.validation_kernel import (
    NormalizedDecisionGraphV1,
    ValidationDecisionV1,
    capture_validation_snapshot,
    decision_from_graph,
    evaluate_work,
)


@dataclass(frozen=True)
class PreflightReportV1:
    decision: ValidationDecisionV1
    graph: NormalizedDecisionGraphV1
    mutation_count: int = 0


def run_preflight(context: dict[str, object]) -> PreflightReportV1:
    snapshot = capture_validation_snapshot("init-preflight", context)
    graph = evaluate_work(snapshot)
    return PreflightReportV1(decision_from_graph(graph), graph, mutation_count=0)


def render_preflight(report: PreflightReportV1) -> dict[str, object]:
    return {"decision": report.decision.decision.value, "graph_digest": report.graph.graph_digest, "mutation_count": 0, "codes": [item.code for item in report.graph.items]}
