"""Work dependency、supersession 与 sole legal successor 机器解析（STORY-CR075-S03）。

只读查询：收集全部 WORK.yaml → 构建 DAG → 环检测 → 闭包/successor 查询 →
typed 输出。历史 Work 无 ``depends_on``/``supersedes`` 字段时兼容为空集
（LLD §12）。

sole-successor 规则（LLD §8）：cancelled Work 的 supersede 声明集大小=1 才
legal；≥2 typed BLOCKED（不允许双后继分叉真相）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.scale import load_yaml_object

SCHEMA_VERSION = 1
BLOCKED_CYCLE = "DEPENDENCY_CYCLE_DETECTED"
BLOCKED_AMBIGUOUS_SUCCESSOR = "AMBIGUOUS_SUPERSESSION"
BLOCKED_UNKNOWN_WORK = "UNKNOWN_WORK"


@dataclass(frozen=True)
class DependencyGraphV1:
    """内存 DAG（自 WORK.yaml 集构建，不落盘）。"""

    nodes: tuple[str, ...]
    edges: Mapping[str, tuple[str, ...]]  # work_id -> depends_on ids
    supersessions: Mapping[str, tuple[str, ...]]  # work_id -> supersedes ids
    statuses: Mapping[str, str]
    sources: Mapping[str, str]
    malformed: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "DependencyGraphV1",
            "node_count": len(self.nodes),
            "edges": {key: list(value) for key, value in sorted(self.edges.items())},
            "supersessions": {
                key: list(value) for key, value in sorted(self.supersessions.items())
            },
            "statuses": dict(sorted(self.statuses.items())),
            "malformed": list(self.malformed),
        }

    def assert_healthy(self, work_id: str) -> str | None:
        """查询前置：graph 存在损坏记录时返回阻断 reason code。"""

        if self.malformed:
            return "DEPENDENCY_GRAPH_MALFORMED"
        return None


@dataclass(frozen=True)
class SupersessionReceiptV1:
    """cancelled predecessor 的唯一合法后继判定结果（入过程仓 evidence 的形态）。"""

    schema_version: int
    cancelled_work_id: str
    legal_successor_id: str
    declared_successors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "SupersessionReceiptV1",
            "cancelled_work_id": self.cancelled_work_id,
            "legal_successor_id": self.legal_successor_id,
            "declared_successors": list(self.declared_successors),
        }


def build_dependency_graph(process_root: Path) -> DependencyGraphV1:
    """收集 works/*/WORK.yaml 构建 DAG；环检测在查询时执行。"""

    works_root = process_root / "works"
    nodes: list[str] = []
    edges: dict[str, tuple[str, ...]] = {}
    supersessions: dict[str, tuple[str, ...]] = {}
    statuses: dict[str, str] = {}
    sources: dict[str, str] = {}
    malformed: list[str] = []
    malformed_ids: set[str] = set()
    if not works_root.is_dir():
        return DependencyGraphV1((), {}, {}, {}, {})
    for work_dir in sorted(works_root.iterdir()):
        work_path = work_dir / "WORK.yaml"
        if not work_dir.is_dir() or not work_path.is_file() or work_path.is_symlink():
            continue
        try:
            payload = load_yaml_object(work_path)
        except (ValueError, OSError) as exc:
            # S03 整改：损坏 envelope 显式记录（查询经 graph.malformed 阻断）。
            malformed.append(
                f"WORK_YAML_UNREADABLE:{work_dir.name}:{type(exc).__name__}"
            )
            malformed_ids.add(work_dir.name)
            continue
        work_id = str(payload.get("work_id") or "")
        if not work_id:
            continue
        if work_id in statuses:
            # S03 整改：重复 work_id 是真相分叉，必须显式记录并由查询阻断。
            malformed.append(f"DUPLICATE_WORK_ID:{work_id}")
            continue
        malformed_ids.discard(work_id)
        nodes.append(work_id)
        edges[work_id] = tuple(
            sorted({str(item) for item in (payload.get("depends_on") or ()) if str(item)})
        )
        supersessions[work_id] = tuple(
            sorted({str(item) for item in (payload.get("supersedes") or ()) if str(item)})
        )
        statuses[work_id] = str(payload.get("status") or "")
        sources[work_id] = f"works/{work_dir.name}/WORK.yaml"
    return DependencyGraphV1(
        tuple(sorted(nodes)),
        edges,
        supersessions,
        statuses,
        sources,
        tuple(sorted(set(malformed))),
    )


def detect_cycle(graph: DependencyGraphV1) -> list[str]:
    """DFS 环检测；返回参与环的节点链（空表=无环）。"""

    state: dict[str, int] = {node: 0 for node in graph.nodes}
    stack: list[str] = []
    cycles: list[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for dependency in graph.edges.get(node, ()):
            if dependency not in state:
                continue
            if state[dependency] == 1:
                cycles.extend(stack[stack.index(dependency):] + [dependency])
            elif state[dependency] == 0:
                visit(dependency)
        stack.pop()
        state[node] = 2

    for node in graph.nodes:
        if state[node] == 0:
            visit(node)
    return cycles


def resolve_closure(graph: DependencyGraphV1, work_id: str) -> dict[str, Any]:
    """传递闭包查询（含自身）；未知 Work/环 typed BLOCKED。"""

    unhealthy = graph.assert_healthy(work_id)
    if unhealthy:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "DependencyClosureV1",
            "work_id": work_id,
            "decision": "BLOCKED",
            "reason_codes": [unhealthy],
            "malformed": list(graph.malformed),
            "mutation_count": 0,
        }
    if work_id not in graph.edges:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "DependencyClosureV1",
            "work_id": work_id,
            "decision": "BLOCKED",
            "reason_codes": [BLOCKED_UNKNOWN_WORK],
            "mutation_count": 0,
        }
    unknown_dependencies = sorted(
        {
            reference
            for references in (*graph.edges.values(), *graph.supersessions.values())
            for reference in references
            if reference not in graph.edges
        }
    )
    if unknown_dependencies:
        # S03 整改：依赖指向未知 Work 时 typed BLOCKED（不静默吞掉悬边）。
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "DependencyClosureV1",
            "work_id": work_id,
            "decision": "BLOCKED",
            "reason_codes": ["UNKNOWN_DEPENDENCY"],
            "unknown_dependencies": unknown_dependencies,
            "mutation_count": 0,
        }
    cycles = detect_cycle(graph)
    if cycles:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "DependencyClosureV1",
            "work_id": work_id,
            "decision": "BLOCKED",
            "reason_codes": [BLOCKED_CYCLE],
            "cycle": cycles,
            "mutation_count": 0,
        }
    visited: set[str] = set()
    ordered: list[str] = []

    def walk(node: str) -> None:
        if node in visited:
            return
        visited.add(node)
        for dependency in sorted(graph.edges.get(node, ())):
            walk(dependency)
        ordered.append(node)

    walk(work_id)
    closure = tuple(ordered[:-1]) if len(ordered) > 1 else ()
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "DependencyClosureV1",
        "work_id": work_id,
        "decision": "PASS",
        "closure": list(closure),
        "topological_order": list(ordered),
        "mutation_count": 0,
    }


def resolve_sole_successor(
    graph: DependencyGraphV1, cancelled_work_id: str
) -> dict[str, Any]:
    """cancelled predecessor 的唯一合法后继判定（DAG receipt 形态）。"""

    if cancelled_work_id not in graph.edges:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "SupersessionQueryV1",
            "cancelled_work_id": cancelled_work_id,
            "decision": "BLOCKED",
            "reason_codes": [BLOCKED_UNKNOWN_WORK],
            "mutation_count": 0,
        }
    if graph.malformed:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "SupersessionQueryV1",
            "cancelled_work_id": cancelled_work_id,
            "decision": "BLOCKED",
            "reason_codes": ["DEPENDENCY_GRAPH_MALFORMED"],
            "malformed": list(graph.malformed),
            "mutation_count": 0,
        }
    current_status = str(graph.statuses.get(cancelled_work_id) or "")
    if current_status != "cancelled":
        # S03 整改：supersession 只对 cancelled predecessor 有定义。
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "SupersessionQueryV1",
            "cancelled_work_id": cancelled_work_id,
            "decision": "BLOCKED",
            "reason_codes": ["PREDECESSOR_NOT_CANCELLED"],
            "predecessor_status": current_status,
            "mutation_count": 0,
        }
    declared = tuple(
        successor
        for successor in sorted(graph.nodes)
        if cancelled_work_id in graph.supersessions.get(successor, ())
    )
    if len(declared) >= 2:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "SupersessionQueryV1",
            "cancelled_work_id": cancelled_work_id,
            "decision": "BLOCKED",
            "reason_codes": [BLOCKED_AMBIGUOUS_SUCCESSOR],
            "declared_successors": list(declared),
            "mutation_count": 0,
        }
    if not declared:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "SupersessionQueryV1",
            "cancelled_work_id": cancelled_work_id,
            "decision": "NEEDS_REVIEW",
            "reason_codes": ["NO_DECLARED_SUCCESSOR"],
            "mutation_count": 0,
        }
    receipt = SupersessionReceiptV1(
        SCHEMA_VERSION, cancelled_work_id, declared[0], declared
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "SupersessionQueryV1",
        "cancelled_work_id": cancelled_work_id,
        "decision": "PASS",
        "receipt": receipt.as_dict(),
        "mutation_count": 0,
    }


def dependency_query_main(argv: list[str] | None = None) -> int:
    """CLI：``meta-flow work dependency-query``（exit 0=PASS，2=BLOCKED/NEEDS_REVIEW）。"""

    import argparse
    import json as json_module

    from meta_flow.project.process_route import require_process_route

    parser = argparse.ArgumentParser(prog="meta-flow work dependency-query")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--mode", required=True, choices=("closure", "successor"))
    parser.add_argument("--format", choices=("json",), default="json")
    parsed = parser.parse_args(argv or [])
    try:
        process_root = require_process_route(parsed.project_root.resolve()).process_root
    except Exception as exc:
        print(
            json_module.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "decision": "BLOCKED",
                    "reason_codes": ["PROCESS_ROUTE_UNHEALTHY"],
                    "detail": f"{type(exc).__name__}: {exc}",
                    "mutation_count": 0,
                }
            )
        )
        return 2
    graph = build_dependency_graph(process_root)
    if parsed.mode == "closure":
        payload = resolve_closure(graph, parsed.work_id)
    else:
        payload = resolve_sole_successor(graph, parsed.work_id)
    print(json_module.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["decision"] == "PASS" else 2
