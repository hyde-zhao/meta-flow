"""CR-075 S03：dependency/supersession 机器解析（STORY-CR075-S03）。

覆盖：闭包传递、环检测、cancelled 双后继 BLOCKED、唯一合法后继、
未知 Work typed 阻断、历史 Work 无字段兼容。
"""

from __future__ import annotations

from pathlib import Path

from meta_flow.work.dependency import (
    build_dependency_graph,
    resolve_closure,
    resolve_sole_successor,
)

_WORK_TEMPLATE = """schema_version: 1
work_id: {work_id}
status: {status}
depends_on: {depends_on}
supersedes: {supersedes}
"""


def _work(
    process: Path,
    work_id: str,
    *,
    status: str = "active",
    depends_on: list[str] | None = None,
    supersedes: list[str] | None = None,
) -> None:
    work_dir = process / "works" / work_id
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "WORK.yaml").write_text(
        _WORK_TEMPLATE.format(
            work_id=work_id,
            status=status,
            depends_on=depends_on or [],
            supersedes=supersedes or [],
        ),
        encoding="utf-8",
    )


def test_closure_is_transitive(tmp_path: Path) -> None:
    process = tmp_path
    _work(process, "W-1")
    _work(process, "W-2", depends_on=["W-1"])
    _work(process, "W-3", depends_on=["W-2"])
    graph = build_dependency_graph(process)

    result = resolve_closure(graph, "W-3")

    assert result["decision"] == "PASS"
    assert result["closure"] == ["W-1", "W-2"]


def test_cycle_is_blocked_with_cycle_chain(tmp_path: Path) -> None:
    process = tmp_path
    _work(process, "W-1", depends_on=["W-2"])
    _work(process, "W-2", depends_on=["W-1"])
    graph = build_dependency_graph(process)

    result = resolve_closure(graph, "W-1")

    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["DEPENDENCY_CYCLE_DETECTED"]
    assert set(result["cycle"]) == {"W-1", "W-2"}


def test_unknown_work_is_typed_blocked(tmp_path: Path) -> None:
    graph = build_dependency_graph(tmp_path)
    result = resolve_closure(graph, "W-GHOST")
    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["UNKNOWN_WORK"]


def test_legacy_work_without_fields_has_empty_closure(tmp_path: Path) -> None:
    process = tmp_path
    work_dir = process / "works" / "W-LEGACY"
    work_dir.mkdir(parents=True)
    (work_dir / "WORK.yaml").write_text(
        "schema_version: 1\nwork_id: W-LEGACY\nstatus: closed\n", encoding="utf-8"
    )
    graph = build_dependency_graph(process)

    result = resolve_closure(graph, "W-LEGACY")

    assert result["decision"] == "PASS"
    assert result["closure"] == []


def test_cancelled_predecessor_with_sole_successor_passes(tmp_path: Path) -> None:
    process = tmp_path
    _work(process, "W-OLD", status="cancelled")
    _work(process, "W-NEW", supersedes=["W-OLD"])
    graph = build_dependency_graph(process)

    result = resolve_sole_successor(graph, "W-OLD")

    assert result["decision"] == "PASS"
    receipt = result["receipt"]
    assert receipt["kind"] == "SupersessionReceiptV1"
    assert receipt["legal_successor_id"] == "W-NEW"
    assert receipt["declared_successors"] == ["W-NEW"]


def test_cancelled_predecessor_with_two_successors_blocks(tmp_path: Path) -> None:
    process = tmp_path
    _work(process, "W-OLD", status="cancelled")
    _work(process, "W-A", supersedes=["W-OLD"])
    _work(process, "W-B", supersedes=["W-OLD"])
    graph = build_dependency_graph(process)

    result = resolve_sole_successor(graph, "W-OLD")

    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["AMBIGUOUS_SUPERSESSION"]
    assert sorted(result["declared_successors"]) == ["W-A", "W-B"]


def test_no_declared_successor_is_needs_review(tmp_path: Path) -> None:
    process = tmp_path
    _work(process, "W-OLD", status="cancelled")
    graph = build_dependency_graph(process)

    result = resolve_sole_successor(graph, "W-OLD")

    assert result["decision"] == "NEEDS_REVIEW"
    assert result["reason_codes"] == ["NO_DECLARED_SUCCESSOR"]
