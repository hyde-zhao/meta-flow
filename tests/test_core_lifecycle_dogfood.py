from __future__ import annotations

import runpy
from pathlib import Path

FIXTURE = runpy.run_path(
    str(Path(__file__).parent / "fixtures/core_lifecycle_dogfood.py"),
    run_name="__core_lifecycle_dogfood_test__",
)
run_core_lifecycle_dogfood = FIXTURE["run_core_lifecycle_dogfood"]


def test_core_lifecycle_dogfood_is_binding_only_and_repeatable(tmp_path: Path) -> None:
    first = run_core_lifecycle_dogfood(tmp_path / "first")
    second = run_core_lifecycle_dogfood(tmp_path / "second")

    assert first == second
    assert first["decision"] == "PASS"
    assert first["route_mode"] == "sibling-binding"
    assert first["close_order"] == ["W-000", "W-001", "W-002"]
    assert first["usage_boundary"] == {
        "decision": "REVIEW",
        "stage_limit": 1,
        "projected": 1,
        "post_action": "PAUSE_AFTER_EXECUTION",
    }
    assert all(
        set(step[check_phase].values()) == {"PASS"}
        for step in first["steps"]
        for check_phase in ("after_init_checks", "after_close_checks")
    )
    assert first["unrelated_ledgers_unchanged"] is True
    assert first["cr_index_unchanged"] is True
