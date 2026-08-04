from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_flow.project.model import Project, load_project, write_project_create_only
from meta_flow.project.process_route import IndependentProcessRoute
from meta_flow.project.read_contract import ReadContractError
from meta_flow.work.io_metrics import IOMetrics
from meta_flow.work.read_context import OperationReadContext, route_fingerprint


def write_objects(root: Path, count: int = 6) -> None:
    directory = root / "objects"
    directory.mkdir()
    for index in range(1, count + 1):
        (directory / f"{index}.json").write_text(
            json.dumps({"index": index}) + "\n",
            encoding="utf-8",
        )


def test_same_logical_ref_is_physically_read_once_and_parsed_defensively(
    tmp_path: Path,
) -> None:
    write_project_create_only(
        tmp_path,
        Project(1, "demo", "Demo", "active"),
    )
    metrics = IOMetrics("query-cache", enabled=True)
    context = OperationReadContext(
        tmp_path,
        operation_id="query-cache",
        operation_kind="query",
        allowed_reads=("PROJECT.yaml",),
        metrics=metrics,
    )

    first = load_project(tmp_path, read_context=context)
    second = load_project(tmp_path, read_context=context)

    assert first == second
    assert context.objects_read == 1
    assert context.refs == ("PROJECT.yaml",)
    totals = metrics.summary()["totals"]
    assert totals["physical_reads"] == 1
    assert totals["cache_hits"] >= 1


def test_sixth_object_is_blocked_before_open_or_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_objects(tmp_path)
    calls: list[str] = []
    original = Path.read_bytes

    def tracked(path: Path) -> bytes:
        calls.append(path.name)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    context = OperationReadContext(
        tmp_path,
        operation_id="sixth-object",
        operation_kind="query",
        allowed_reads=("objects/**",),
        max_objects=5,
    )
    for index in range(1, 6):
        context.read_json(f"objects/{index}.json")

    with pytest.raises(ReadContractError) as captured:
        context.read_json("objects/6.json")

    assert captured.value.error_code == "QUERY_OBJECT_BUDGET_EXCEEDED"
    assert captured.value.objects_read == 5
    assert captured.value.logical_ref == "objects/6.json"
    assert calls == [f"{index}.json" for index in range(1, 6)]


@pytest.mark.parametrize(
    ("allowed_reads", "requested", "error_code"),
    [
        (("objects/1.json",), "objects/2.json", "READ_SCOPE_DENIED"),
        (("objects/**",), "../outside.json", "READ_REF_INVALID"),
    ],
)
def test_invalid_ref_or_scope_is_blocked_before_physical_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    allowed_reads: tuple[str, ...],
    requested: str,
    error_code: str,
) -> None:
    write_objects(tmp_path, 2)
    calls = 0
    original = Path.read_bytes

    def tracked(path: Path) -> bytes:
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    context = OperationReadContext(
        tmp_path,
        operation_id="invalid-ref",
        operation_kind="query",
        allowed_reads=allowed_reads,
    )

    with pytest.raises(ReadContractError) as captured:
        context.read_bytes(requested)

    assert captured.value.error_code == error_code
    assert captured.value.objects_read == 0
    assert calls == 0


def test_mutation_closes_entire_context_and_cached_ref_cannot_be_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_objects(tmp_path, 1)
    calls = 0
    original = Path.read_bytes

    def tracked(path: Path) -> bytes:
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    context = OperationReadContext(
        tmp_path,
        operation_id="mutation-close",
        operation_kind="apply",
        allowed_reads=("objects/1.json",),
    )
    assert context.read_json("objects/1.json") == {"index": 1}

    context.close_after_mutation({"decision": "PASS", "mutation_count": 1})
    with pytest.raises(ReadContractError) as captured:
        context.read_json("objects/1.json")

    assert captured.value.error_code == "READ_CONTEXT_STALE"
    assert context.state == "STALE"
    assert calls == 1


def test_plan_context_cannot_be_reused_for_apply_and_snapshot_drift_stales_it(
    tmp_path: Path,
) -> None:
    context = OperationReadContext(
        tmp_path,
        operation_id="status-plan",
        operation_kind="plan",
        allowed_reads=("PROJECT.yaml",),
        route_snapshot="a" * 64,
        scope_digest="b" * 64,
    )

    with pytest.raises(ReadContractError) as wrong_kind:
        context.assert_operation("apply")
    assert wrong_kind.value.error_code == "OPERATION_CONTEXT_KIND_MISMATCH"

    with pytest.raises(ReadContractError) as drift:
        context.assert_snapshot(scope_digest="c" * 64)
    assert drift.value.error_code == "READ_CONTEXT_SNAPSHOT_DRIFT"
    assert context.state == "STALE"


def test_long_term_route_allows_only_project_roadmap_and_declared_phases(
    tmp_path: Path,
) -> None:
    refs = (
        "PROJECT.yaml",
        "ROADMAP.yaml",
        "phases/P1/PHASE.yaml",
        "phases/P2/PHASE.yaml",
    )
    for ref in (*refs, "phases/P3/PHASE.yaml"):
        path = tmp_path / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    context = OperationReadContext(
        tmp_path,
        operation_id="long-term-route",
        operation_kind="query",
        allowed_reads=(),
        query_profile="long-term-route",
        declared_phase_refs=(refs[2], refs[3]),
    )

    for ref in refs:
        context.read_json(ref)
    with pytest.raises(ReadContractError) as captured:
        context.read_json("phases/P3/PHASE.yaml")

    assert context.max_objects == 4
    assert context.objects_read == 4
    assert captured.value.error_code == "READ_SCOPE_DENIED"


def test_route_snapshot_contains_no_absolute_path(tmp_path: Path) -> None:
    route = IndependentProcessRoute(
        project_root=tmp_path / "release",
        process_root=tmp_path / "process",
        project_id="demo",
        layout_version="vnext-1",
        route_mode="sibling-binding",
        source=".meta-flow/workspace.yaml",
    )
    context = OperationReadContext.from_route(
        route,
        operation_id="route-query",
        operation_kind="query",
        allowed_reads=("PROJECT.yaml",),
    )

    payload = context.as_dict()

    assert payload["route_fingerprint"] == route_fingerprint(route)
    assert str(tmp_path) not in json.dumps(payload)


def test_frozen_route_maps_paths_without_physical_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "changes" / "CR-101.md"
    target.parent.mkdir()
    target.write_text("# CR-101\n", encoding="utf-8")
    calls = 0
    original = Path.read_bytes

    def tracked(path: Path) -> bytes:
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    context = OperationReadContext(
        tmp_path,
        operation_id="route-map",
        operation_kind="plan",
        allowed_reads=("process/**",),
    )

    assert context.repository_root == tmp_path.resolve()
    assert context.resolve_path("process/changes/CR-101.md", require_file=True) == target
    assert context.logical_ref_for(target, qualified=True) == "process/changes/CR-101.md"
    assert context.objects_read == 0
    assert calls == 0


def test_frozen_route_mapping_enforces_scope_and_repository_boundary(tmp_path: Path) -> None:
    context = OperationReadContext(
        tmp_path,
        operation_id="route-boundary",
        operation_kind="plan",
        allowed_reads=("process/changes/**",),
    )

    with pytest.raises(ReadContractError) as denied:
        context.resolve_path("process/PROJECT.yaml")
    with pytest.raises(ReadContractError) as outside:
        context.logical_ref_for(tmp_path.parent / "outside.md", qualified=True)

    assert denied.value.error_code == "READ_SCOPE_DENIED"
    assert outside.value.error_code == "READ_REF_OUTSIDE_PROCESS_ROOT"
