from __future__ import annotations

import json
from pathlib import Path

from meta_flow.state import current


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _formal_fixture(root: Path) -> None:
    _write_json(
        root / "process/PROJECT.yaml",
        {
            "schema_version": 1,
            "project_id": "fixture",
            "status": "active",
            "roadmap_ref": "ROADMAP.yaml",
        },
    )
    _write_json(
        root / "process/ROADMAP.yaml",
        {
            "schema_version": 1,
            "project_id": "fixture",
            "status": "active",
            "phase_refs": ["phases/P1/PHASE.yaml"],
        },
    )
    _write_json(
        root / "process/phases/P1/PHASE.yaml",
        {
            "schema_version": 1,
            "project_id": "fixture",
            "phase_id": "P1",
            "status": "active",
            "work_refs": [],
            "result_refs": [],
        },
    )
    (root / "process/changes").mkdir(parents=True, exist_ok=True)
    current.write_current_state(root, current.default_current_state(root, project_id="fixture"))
    current.render_state_file(root, force=True)


def test_enforce_rejects_state_that_is_internally_consistent_but_formally_stale(
    tmp_path: Path,
) -> None:
    _formal_fixture(tmp_path)

    errors, _warnings = current.check_current_state(tmp_path, mode="enforce")

    assert any("formal_truth_projection_stale" in error for error in errors)
    assert any("formal_truth_field_stale: current_phase" in error for error in errors)
    assert any("formal_truth_field_stale: next_action" in error for error in errors)


def test_projection_refresh_is_zero_write_then_transactionally_converges(
    tmp_path: Path,
) -> None:
    _formal_fixture(tmp_path)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    plan = current.plan_formal_truth_refresh(tmp_path)

    after_plan = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert before == after_plan
    assert plan["decision"] == "READY"
    assert plan["mutation_count"] == 0
    assert plan["planned_mutation_count"] == 3

    state = current.refresh_formal_truth_projection(tmp_path)
    errors, warnings = current.check_current_state(tmp_path, mode="enforce")

    assert errors == []
    assert warnings == []
    assert state["current_phase"] == "P1"
    assert state["next_action"]["type"] == "continue_active_phase"
    projected = json.loads((tmp_path / "process/current/CURRENT.json").read_text(encoding="utf-8"))
    assert projected["phase"] == "P1"
    assert projected["updated_at"] == state["updated_at"]
    assert "Phase: P1" in (tmp_path / "process/STATE.md").read_text(encoding="utf-8")


def test_formal_cr_truth_overrides_stale_active_ledger_event(tmp_path: Path) -> None:
    _formal_fixture(tmp_path)
    formal_ref = "process/changes/CR-064-closed.md"
    ledger_path = tmp_path / "process/state/CR-LEDGER.ndjson"
    ledger_path.write_text(
        json.dumps({"id": "CR-064", "status": "active", "full_ref": formal_ref})
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / formal_ref).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / formal_ref).write_text(
        "---\nkind: cr\ncr_id: CR-064\nlifecycle_status: closed\nstatus: closed\n---\n",
        encoding="utf-8",
    )

    state = current.refresh_formal_truth_projection(tmp_path)

    assert state["active_change"] is None
    assert state["formal_truth_projection"]["active_cr_ids"] == []
    assert formal_ref in state["formal_truth_projection"]["source_refs"]


def test_formal_cr_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    _formal_fixture(tmp_path)
    formal_ref = "process/changes/CR-064-closed.md"
    ledger_path = tmp_path / "process/state/CR-LEDGER.ndjson"
    ledger_path.write_text(
        json.dumps({"id": "CR-064", "status": "active", "full_ref": formal_ref})
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / formal_ref).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / formal_ref).write_text(
        "---\nkind: cr\ncr_id: CR-OTHER\nlifecycle_status: closed\n---\n",
        encoding="utf-8",
    )

    try:
        current.plan_formal_truth_refresh(tmp_path)
    except ValueError as exc:
        assert "truth missing" in str(exc)
    else:
        raise AssertionError("mismatched formal CR identity must fail closed")
