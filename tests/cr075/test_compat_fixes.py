"""CR-075 P0 兼容债：MF-BUG-11（超集 schema）与 MF-BUG-14（canonical result ref）。"""

from __future__ import annotations

import warnings
from pathlib import Path

from meta_flow.work import lifecycle_transaction as lt


def _write_result(process: Path, work_id: str, extra: dict[str, object] | None = None) -> str:
    payload: dict[str, object] = {
        "schema_version": 1,
        "work_id": work_id,
        "decision": "PASS",
    }
    if extra:
        payload.update(extra)
    from meta_flow.project.scale import dump_yaml

    path = process / "works" / work_id / "RESULT.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(payload), encoding="utf-8")
    return f"works/{work_id}/RESULT.yaml"


def _fixture_process(tmp_path: Path) -> Path:
    process = tmp_path / "proc"
    process.mkdir()
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture\n"
        "repo_role: process\n"
        "release_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: release\n",
        encoding="utf-8",
    )
    return process


def test_mf_bug_11_superset_fields_are_tolerated(tmp_path: Path) -> None:
    """Work result 新增实现证据字段（超集）被容忍；必填缺失仍 fail closed。"""

    process = _fixture_process(tmp_path)
    ref = _write_result(
        process,
        "WORK-075-001",
        extra={"summary": "P0 done", "evidence_ref": "archive/CR-075/evidence.json"},
    )

    # 不抛异常即通过（必填齐备 + 超集字段）。
    lt._validate_result(process, "WORK-075-001", "completed", ref)


def test_mf_bug_11_missing_required_field_fails_closed(tmp_path: Path) -> None:
    process = _fixture_process(tmp_path)
    ref = _write_result(process, "WORK-075-002")
    # 抹掉 decision 字段模拟缺必填。
    path = process / ref
    path.write_text("schema_version: 1\nwork_id: WORK-075-002\n", encoding="utf-8")

    try:
        lt._validate_result(process, "WORK-075-002", "completed", ref)
    except ValueError as exc:
        assert "exact matching PASS result" in str(exc)
    else:  # pragma: no cover - 防回归守卫
        raise AssertionError("missing decision must fail closed")


def test_mf_bug_14_canonical_process_ref_accepted_without_warning(tmp_path: Path) -> None:
    process = _fixture_process(tmp_path)
    _write_result(process, "WORK-075-003")

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        canonical = lt._canonical_result_ref("process/works/WORK-075-003/RESULT.yaml")

    assert canonical == "works/WORK-075-003/RESULT.yaml"


def test_mf_bug_14_legacy_process_relative_ref_warns(tmp_path: Path) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        canonical = lt._canonical_result_ref("works/WORK-075-004/RESULT.yaml")

    assert canonical == "works/WORK-075-004/RESULT.yaml"
    assert any(
        isinstance(item.message, DeprecationWarning) and "legacy" in str(item.message)
        for item in caught
    ), "process-relative result_ref must emit DeprecationWarning"


def test_mf_bug_14_unsafe_refs_rejected() -> None:
    for bad in ("/etc/passwd", "../escape.yaml", "process/../x", ""):
        try:
            lt._canonical_result_ref(bad)
        except ValueError:
            continue
        raise AssertionError(f"unsafe ref accepted: {bad!r}")
