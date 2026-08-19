"""基于 authoritative Package Plan 的 zero-write affected closure。"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from meta_flow.workflow.package_compiler import admit_compiled_plan
from meta_flow.workflow.package_plan import (
    PackagePlanIRV1,
    canonical_digest,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_NODE_KINDS = {"story", "feature", "module", "test", "asset", "operation"}
_EDGE_TYPES = {"contract", "runtime", "verification", "release"}


def _closed(value: object, fields: set[str], *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(code)
    return value


def _text(value: object, *, code: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or value != value.strip() or (not value and not allow_empty):
        raise ValueError(code)
    return value


def _strings(value: object, *, code: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item or item != item.strip() for item in value
    ):
        raise ValueError(code)
    return tuple(sorted(set(value)))


@dataclass(frozen=True)
class ClosureGraphNodeV1:
    node_id: str
    kind: str
    story_id: str
    roots: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: object) -> ClosureGraphNodeV1:
        item = _closed(
            value, {"node_id", "kind", "story_id", "roots"}, code="CLOSURE_NODE_FIELDS_MISMATCH"
        )
        kind = _text(item["kind"], code="CLOSURE_NODE_KIND_INVALID")
        if kind not in _NODE_KINDS:
            raise ValueError("CLOSURE_NODE_KIND_INVALID")
        story_id = _text(item["story_id"], code="CLOSURE_STORY_ID_INVALID", allow_empty=True)
        return cls(
            node_id=_text(item["node_id"], code="CLOSURE_NODE_ID_INVALID"),
            kind=kind,
            story_id=story_id,
            roots=_strings(item["roots"], code="CLOSURE_ROOTS_INVALID"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "story_id": self.story_id,
            "roots": list(self.roots),
        }


@dataclass(frozen=True)
class ClosureGraphEdgeV1:
    upstream: str
    downstream: str
    edge_type: str

    @classmethod
    def from_mapping(cls, value: object) -> ClosureGraphEdgeV1:
        item = _closed(
            value,
            {"upstream", "downstream", "edge_type"},
            code="CLOSURE_EDGE_FIELDS_MISMATCH",
        )
        edge_type = _text(item["edge_type"], code="CLOSURE_EDGE_TYPE_INVALID")
        if edge_type not in _EDGE_TYPES:
            raise ValueError("CLOSURE_EDGE_TYPE_INVALID")
        return cls(
            upstream=_text(item["upstream"], code="CLOSURE_EDGE_ENDPOINT_INVALID"),
            downstream=_text(item["downstream"], code="CLOSURE_EDGE_ENDPOINT_INVALID"),
            edge_type=edge_type,
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "upstream": self.upstream,
            "downstream": self.downstream,
            "edge_type": self.edge_type,
        }


@dataclass(frozen=True)
class ClosureRequestV1:
    schema_version: int
    package_plan_digest: str
    base_sha: str
    head_sha: str
    changed_roots: tuple[str, ...]
    graph_nodes: tuple[ClosureGraphNodeV1, ...]
    graph_edges: tuple[ClosureGraphEdgeV1, ...]
    prior_fingerprint: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ClosureRequestV1:
        fields = {
            "schema_version",
            "package_plan_digest",
            "base_sha",
            "head_sha",
            "changed_roots",
            "graph_nodes",
            "graph_edges",
            "prior_fingerprint",
        }
        item = _closed(value, fields, code="CLOSURE_REQUEST_FIELDS_MISMATCH")
        if item["schema_version"] != 1:
            raise ValueError("CLOSURE_REQUEST_SCHEMA_INVALID")
        if not isinstance(item["graph_nodes"], (list, tuple)) or not isinstance(
            item["graph_edges"], (list, tuple)
        ):
            raise ValueError("CLOSURE_GRAPH_INVALID")
        return cls(
            schema_version=1,
            package_plan_digest=_text(
                item["package_plan_digest"], code="CLOSURE_PLAN_DIGEST_INVALID"
            ),
            base_sha=_text(item["base_sha"], code="INVALID_LITERAL_SHA", allow_empty=True),
            head_sha=_text(item["head_sha"], code="INVALID_LITERAL_SHA", allow_empty=True),
            changed_roots=_strings(item["changed_roots"], code="CLOSURE_CHANGED_ROOT_INVALID"),
            graph_nodes=tuple(
                sorted(
                    (ClosureGraphNodeV1.from_mapping(entry) for entry in item["graph_nodes"]),
                    key=lambda entry: entry.node_id,
                )
            ),
            graph_edges=tuple(
                sorted(
                    (ClosureGraphEdgeV1.from_mapping(entry) for entry in item["graph_edges"]),
                    key=lambda entry: (entry.upstream, entry.downstream, entry.edge_type),
                )
            ),
            prior_fingerprint=_text(
                item["prior_fingerprint"], code="CLOSURE_PRIOR_FINGERPRINT_INVALID", allow_empty=True
            ),
        )


@dataclass(frozen=True)
class ClosureDiagnosticV1:
    code: str
    subject: str
    message: str
    recovery_action: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": "BLOCKER",
            "code": self.code,
            "subject": self.subject,
            "message": self.message,
            "recovery_action": self.recovery_action,
        }


@dataclass(frozen=True)
class ClosureResultV1:
    schema_version: int
    package_plan_digest: str
    direct_nodes: tuple[str, ...]
    transitive_nodes: tuple[str, ...]
    affected_stories: tuple[str, ...]
    affected_features: tuple[str, ...]
    affected_modules: tuple[str, ...]
    affected_tests: tuple[str, ...]
    affected_assets: tuple[str, ...]
    affected_operations: tuple[str, ...]
    build_set: tuple[str, ...]
    graph_digest: str
    source_fingerprint: str
    semantic_digest: str
    semantic_noop: bool
    diagnostics: tuple[ClosureDiagnosticV1, ...]
    decision: str
    mutation_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "ClosureResultV1",
            "package_plan_digest": self.package_plan_digest,
            "direct_nodes": list(self.direct_nodes),
            "transitive_nodes": list(self.transitive_nodes),
            "affected_stories": list(self.affected_stories),
            "affected_features": list(self.affected_features),
            "affected_modules": list(self.affected_modules),
            "affected_tests": list(self.affected_tests),
            "affected_assets": list(self.affected_assets),
            "affected_operations": list(self.affected_operations),
            "build_set": list(self.build_set),
            "graph_digest": self.graph_digest,
            "source_fingerprint": self.source_fingerprint,
            "semantic_digest": self.semantic_digest,
            "semantic_noop": self.semantic_noop,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "decision": self.decision,
            "mutation_count": self.mutation_count,
        }


def graph_from_package_plan(plan: PackagePlanIRV1) -> tuple[tuple[ClosureGraphNodeV1, ...], tuple[ClosureGraphEdgeV1, ...]]:
    """从当前 Plan 派生 stable Story/path/Feature/operation graph。"""

    nodes: dict[str, ClosureGraphNodeV1] = {}
    edges: set[ClosureGraphEdgeV1] = set()
    for story in plan.stories:
        story_node = f"story:{story.story_id}"
        nodes[story_node] = ClosureGraphNodeV1(story_node, "story", story.story_id, ())
        for path in (*story.primary_paths, *story.shared_paths):
            if path.startswith("tests/"):
                kind = "test"
            elif path == "README.md" or path.startswith(("docs/", "delivery/doc/")):
                kind = "asset"
            else:
                kind = "module"
            node_id = f"path:{path}"
            existing = nodes.get(node_id)
            if existing is None:
                nodes[node_id] = ClosureGraphNodeV1(node_id, kind, story.story_id, (path,))
            if kind in {"test", "asset"}:
                edges.add(ClosureGraphEdgeV1(story_node, node_id, "verification"))
            else:
                edges.add(ClosureGraphEdgeV1(node_id, story_node, "runtime"))
        for feature_ref in story.feature_refs:
            node_id = f"feature:{feature_ref}"
            nodes.setdefault(
                node_id,
                ClosureGraphNodeV1(
                    node_id,
                    "feature",
                    story.story_id,
                    (f"process/docs/features/{feature_ref}/DESIGN.md",),
                ),
            )
            edges.add(ClosureGraphEdgeV1(story_node, node_id, "contract"))
        for operation_id in story.public_operation_ids:
            node_id = f"operation:{operation_id}"
            nodes.setdefault(
                node_id,
                ClosureGraphNodeV1(node_id, "operation", story.story_id, ()),
            )
            edges.add(ClosureGraphEdgeV1(story_node, node_id, "release"))
    for upstream, downstream, edge_type in plan.dependency_edges:
        edges.add(
            ClosureGraphEdgeV1(
                f"story:{upstream}", f"story:{downstream}", edge_type
            )
        )
    return tuple(sorted(nodes.values(), key=lambda item: item.node_id)), tuple(
        sorted(edges, key=lambda item: (item.upstream, item.downstream, item.edge_type))
    )


def _graph_topology(
    nodes: Mapping[str, ClosureGraphNodeV1], edges: Sequence[ClosureGraphEdgeV1]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    indegree = {node_id: 0 for node_id in nodes}
    downstream: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.downstream not in downstream[edge.upstream]:
            downstream[edge.upstream].add(edge.downstream)
            indegree[edge.downstream] += 1
    ready = sorted(node_id for node_id, count in indegree.items() if count == 0)
    ordered: list[str] = []
    while ready:
        node_id = ready.pop(0)
        ordered.append(node_id)
        for child in sorted(downstream.get(node_id, set())):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    cycle = tuple(sorted(node_id for node_id, count in indegree.items() if count > 0))
    return tuple(ordered), cycle


def build_affected_closure(
    request: ClosureRequestV1, plan: PackagePlanIRV1
) -> ClosureResultV1:
    diagnostics: list[ClosureDiagnosticV1] = []
    for name, value in (("base_sha", request.base_sha), ("head_sha", request.head_sha)):
        if not _SHA_RE.fullmatch(value):
            diagnostics.append(
                ClosureDiagnosticV1(
                    "INVALID_LITERAL_SHA",
                    name,
                    "SHA must be an explicit 40-character lowercase hexadecimal literal",
                    "pass the exact immutable commit OID in argv",
                )
            )
    authority_errors = admit_compiled_plan(plan, expected_fingerprint=plan.source_fingerprint)
    if authority_errors or request.package_plan_digest != plan.semantic_digest:
        diagnostics.append(
            ClosureDiagnosticV1(
                "PACKAGE_PLAN_NON_AUTHORITATIVE",
                plan.package_id,
                ",".join(authority_errors) or "package plan digest mismatch",
                "recompile canonical sources in the current process",
            )
        )
    node_groups: dict[str, list[ClosureGraphNodeV1]] = defaultdict(list)
    for node in request.graph_nodes:
        node_groups[node.node_id].append(node)
    nodes = {node_id: group[0] for node_id, group in node_groups.items()}
    if any(len(group) != 1 for group in node_groups.values()):
        diagnostics.append(
            ClosureDiagnosticV1(
                "CLOSURE_GRAPH_INVALID",
                "graph",
                "duplicate node identity",
                "deduplicate graph nodes at the compiler boundary",
            )
        )
    edge_pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
    valid_edges: list[ClosureGraphEdgeV1] = []
    for edge in request.graph_edges:
        if edge.upstream not in nodes or edge.downstream not in nodes or edge.upstream == edge.downstream:
            diagnostics.append(
                ClosureDiagnosticV1(
                    "CLOSURE_GRAPH_NODE_MISSING",
                    f"{edge.upstream}->{edge.downstream}",
                    "edge endpoint is missing or self-referential",
                    "recompile the complete package graph",
                )
            )
            continue
        edge_pairs[(edge.upstream, edge.downstream)].add(edge.edge_type)
        valid_edges.append(edge)
    if any(len(types) > 1 for types in edge_pairs.values()):
        diagnostics.append(
            ClosureDiagnosticV1(
                "CLOSURE_GRAPH_INVALID",
                "graph",
                "one endpoint pair has conflicting edge types",
                "declare one typed dependency per endpoint pair",
            )
        )
    topology, cycle = _graph_topology(nodes, valid_edges)
    if cycle:
        diagnostics.append(
            ClosureDiagnosticV1(
                "CLOSURE_GRAPH_CYCLE",
                ",".join(cycle),
                "graph contains a deterministic cycle",
                "remove the cycle in canonical Plan inputs",
            )
        )

    root_to_nodes: dict[str, set[str]] = defaultdict(set)
    for node in nodes.values():
        for root in node.roots:
            root_to_nodes[root].add(node.node_id)
    direct: set[str] = set()
    for changed_root in request.changed_roots:
        matches = root_to_nodes.get(changed_root, set())
        if not matches:
            diagnostics.append(
                ClosureDiagnosticV1(
                    "CLOSURE_CHANGED_ROOT_UNREGISTERED",
                    changed_root,
                    "changed root is not present in the compiled graph",
                    "register the root or correct the changed-root input",
                )
            )
        direct.update(matches)
    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in valid_edges:
        outgoing[edge.upstream].add(edge.downstream)
    affected = set(direct)
    queue = deque(sorted(direct))
    while queue:
        node_id = queue.popleft()
        for child in sorted(outgoing.get(node_id, set())):
            if child not in affected:
                affected.add(child)
                queue.append(child)
    transitive = affected - direct
    graph_digest = canonical_digest(
        {
            "nodes": [item.as_dict() for item in request.graph_nodes],
            "edges": [item.as_dict() for item in request.graph_edges],
        }
    )
    source_fingerprint = canonical_digest(
        {
            "plan_source_fingerprint": plan.source_fingerprint,
            "plan_digest": request.package_plan_digest,
            "base_sha": request.base_sha,
            "head_sha": request.head_sha,
            "graph_digest": graph_digest,
        }
    )
    affected_by_kind = {
        kind: tuple(sorted(node_id for node_id in affected if nodes[node_id].kind == kind))
        for kind in _NODE_KINDS
    }
    semantic_input = {
        "package_plan_digest": request.package_plan_digest,
        "changed_roots": list(request.changed_roots),
        "direct_nodes": sorted(direct),
        "transitive_nodes": sorted(transitive),
        "build_set": [node_id for node_id in topology if node_id in affected],
        "graph_digest": graph_digest,
        "source_fingerprint": source_fingerprint,
        "diagnostics": [item.as_dict() for item in sorted(diagnostics, key=lambda item: (item.code, item.subject))],
    }
    semantic_digest = canonical_digest(semantic_input)
    ordered_diagnostics = tuple(sorted(diagnostics, key=lambda item: (item.code, item.subject, item.message)))
    return ClosureResultV1(
        schema_version=1,
        package_plan_digest=request.package_plan_digest,
        direct_nodes=tuple(sorted(direct)),
        transitive_nodes=tuple(sorted(transitive)),
        affected_stories=affected_by_kind["story"],
        affected_features=affected_by_kind["feature"],
        affected_modules=affected_by_kind["module"],
        affected_tests=affected_by_kind["test"],
        affected_assets=affected_by_kind["asset"],
        affected_operations=affected_by_kind["operation"],
        build_set=tuple(node_id for node_id in topology if node_id in affected),
        graph_digest=graph_digest,
        source_fingerprint=source_fingerprint,
        semantic_digest=semantic_digest,
        semantic_noop=request.prior_fingerprint == semantic_digest,
        diagnostics=ordered_diagnostics,
        decision="BLOCKED" if ordered_diagnostics else "PASS",
        mutation_count=0,
    )


@dataclass(frozen=True)
class CanonicalOperationRecordV1:
    event_id: str
    operation_id: str
    input_digest: str
    source_fingerprint: str
    plan_digest: str
    decision: str
    record_digest: str

    @classmethod
    def build(
        cls,
        *,
        event_id: str,
        operation_id: str,
        input_digest: str,
        source_fingerprint: str,
        plan_digest: str,
        decision: str,
    ) -> CanonicalOperationRecordV1:
        payload = {
            "schema_version": 1,
            "event_id": event_id,
            "operation_id": operation_id,
            "input_digest": input_digest,
            "source_fingerprint": source_fingerprint,
            "plan_digest": plan_digest,
            "decision": decision,
        }
        return cls(
            event_id=event_id,
            operation_id=operation_id,
            input_digest=input_digest,
            source_fingerprint=source_fingerprint,
            plan_digest=plan_digest,
            decision=decision,
            record_digest=canonical_digest(payload),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "CanonicalOperationRecordV1",
            "event_id": self.event_id,
            "operation_id": self.operation_id,
            "input_digest": self.input_digest,
            "source_fingerprint": self.source_fingerprint,
            "plan_digest": self.plan_digest,
            "decision": self.decision,
            "record_digest": self.record_digest,
        }


def plan_operation_record_append(
    existing: Sequence[Mapping[str, Any]], record: CanonicalOperationRecordV1
) -> dict[str, Any]:
    matches = [item for item in existing if item.get("event_id") == record.event_id]
    if not matches:
        decision, planned = "APPEND", 1
    elif len(matches) == 1 and matches[0].get("record_digest") == record.record_digest:
        decision, planned = "NO_CHANGE", 0
    else:
        decision, planned = "CONFLICT", 0
    return {
        "schema_version": 1,
        "kind": "CanonicalOperationAppendPlanV1",
        "decision": decision,
        "event_id": record.event_id,
        "record_digest": record.record_digest,
        "planned_mutation_count": planned,
        "mutation_count": 0,
        "plan_digest": canonical_digest(
            {
                "decision": decision,
                "event_id": record.event_id,
                "record_digest": record.record_digest,
                "planned_mutation_count": planned,
            }
        ),
    }


def build_operation_receipt(
    record: CanonicalOperationRecordV1,
    *,
    ledger_preimage_digest: str,
    ledger_postimage_digest: str,
    projection_targets: Sequence[str],
    transaction_id: str,
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "kind": "OperationReceiptV1",
        "event_id": record.event_id,
        "record_digest": record.record_digest,
        "ledger_preimage_digest": ledger_preimage_digest,
        "ledger_postimage_digest": ledger_postimage_digest,
        "projection_targets": sorted(set(projection_targets)),
        "transaction_id": transaction_id,
    }
    payload["receipt_digest"] = canonical_digest(payload)
    return payload


__all__ = [
    "CanonicalOperationRecordV1",
    "ClosureGraphEdgeV1",
    "ClosureGraphNodeV1",
    "ClosureRequestV1",
    "ClosureResultV1",
    "build_affected_closure",
    "build_operation_receipt",
    "graph_from_package_plan",
    "plan_operation_record_append",
]
