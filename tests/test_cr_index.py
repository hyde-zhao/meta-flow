from __future__ import annotations

# ruff: noqa: I001, UP031

from meta_flow.workflow import cr_index
from meta_flow.state import current
from pathlib import Path
from unittest.mock import Mock

import pytest


def _write_cr(root: Path, cr_id: str = "CR-101") -> Path:
    path = root / "process" / "changes" / f"{cr_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nschema_version: 1\nkind: cr\ncr_id: \"%s\"\ncr_type: \"architecture\"\n"
        "title: \"example\"\nlifecycle_status: \"active\"\nreadiness_status: \"READY\"\n"
        "gate_status: \"cp5_pending\"\ngate_profile: \"standard\"\nconflict_keys: []\n"
        "impact_surface: []\nauthz_policy_refs: []\nrisk_refs: []\n---\n\n## 变更描述\n\nexample\n" % cr_id,
        encoding="utf-8",
    )
    return path


def test_index_owner_exports_frozen_nineteen_members() -> None:
    expected = {
        "CR_INDEX_REL", "INDEX_SCHEMA_VERSION", "_cr_numeric_sort_key", "_canonical_digest",
        "_dirty_path_digest", "_index_item", "_record_override", "_native_cr_minimum",
        "_validate_native_formal_cr", "build_index", "validate_index_payload", "plan_index",
        "write_index", "load_index", "_write_bootstrap_cr_file", "_update_current_active_change",
        "_write_cp0_result", "bootstrap_cr", "close_cr",
    }
    assert {name for name in expected if hasattr(cr_index, name)} == expected


def test_index_payload_validation_rejects_invalid_shape() -> None:
    assert cr_index.validate_index_payload({"schema_version": 999})


def test_terminal_predecessor_inventory_and_rebuild_projection_are_closed() -> None:
    inventory_digest = cr_index._canonical_digest(["x"])
    receipt = {"cr_id": "CR-071", "predecessor_revision_id": "R1", "terminal_status": "verified", "inventory": ["x"], "inventory_digest": inventory_digest, "revision_bytes_digest": "b" * 64}
    assert cr_index.load_terminal_predecessor_inventory([receipt], cr_id="CR-071", predecessor_revision_id="R1", expected_digest=inventory_digest, expected_revision_bytes_digest="b" * 64)["inventory"] == ["x"]
    revision = {
        "schema_version": 2,
        "cr_id": "CR-071",
        "work_id": "CR-071-R2",
        "revision_id": "R2",
        "predecessor_revision_id": "R1",
        "predecessor_revision_bytes_digest": "b" * 64,
        "scope_digest": "a" * 64,
        "previous_scope": ["old"],
        "scope": ["new", "old"],
        "invalidated_refs": [],
        "plan_digest": "c" * 64,
        "validation_graph_digest": "d" * 64,
    }
    assert cr_index.rebuild_scope_amend_index(revision) == {
        "cr_id": "CR-071",
        "work_id": "CR-071-R2",
        "revision_id": "R2",
        "scope_digest": "a" * 64,
        "plan_digest": "c" * 64,
        "validation_graph_digest": "d" * 64,
        "predecessor_revision_id": "R1",
    }


def test_index_build_validate_plan_and_write_owner_behaviour(tmp_path: Path) -> None:
    _write_cr(tmp_path)
    built = cr_index.build_index(tmp_path)
    assert built["items"][0]["id"] == "CR-101"
    assert cr_index.validate_index_payload(built) == []
    plan = cr_index.plan_index(tmp_path)
    assert plan["decision"] == "READY"
    path = cr_index.write_index(tmp_path)
    assert cr_index.load_index(tmp_path)["semantic_digest"] == built["semantic_digest"]
    assert path == tmp_path / cr_index.CR_INDEX_REL


def test_index_close_owner_uses_injected_collaborators(tmp_path: Path) -> None:
    cr_path = _write_cr(tmp_path)
    paths = {
        "process/changes/CR-101.md": cr_path,
        "process/changes/summaries/CR-101.summary.json": tmp_path / "summary.json",
        "process/archive/CR-101/evidence-index.json": tmp_path / "evidence.json",
        "process/changes/CR-INDEX.json": tmp_path / "index.json",
        "process/state/CR-LEDGER.ndjson": tmp_path / "ledger.ndjson",
    }
    result = cr_index.close_cr(
        tmp_path, "CR-101", readiness="READY", work_id="W", effective_at="now",
        expected_process_oid="", expected_plan_digest="", authorization=None,
        plan_status_sync=Mock(return_value=object()),
        apply_status_sync=Mock(return_value={"status": "PASS", "paths": paths}),
        append_ledger_event=Mock(), resolve_runtime_ref=Mock(),
        rel=lambda _root, _path: "process/changes/CR-101.md",
        current_state_updater=Mock(), discover_formal_crs_fn=Mock(return_value={"CR-101": cr_path}),
    )
    assert result["cr"] == cr_path


def test_index_bootstrap_owner_writes_expected_artifacts(tmp_path: Path) -> None:
    current.write_current_state(tmp_path, current.default_current_state(tmp_path, project_id="target-project"))
    paths = cr_index.bootstrap_cr(
        tmp_path, cr_id="CR-001", title="bootstrap", scope="scope", readiness="READY"
    )
    assert paths["cr"].is_file()
    assert paths["index"].is_file()
    assert paths["cp0_result"].is_file()


def test_index_bootstrap_can_rebuild_projection_after_new_formal_truth(tmp_path: Path) -> None:
    current.write_current_state(
        tmp_path, current.default_current_state(tmp_path, project_id="target-project")
    )
    _write_cr(tmp_path, "CR-100")
    cr_index.write_index(tmp_path)

    paths = cr_index.bootstrap_cr(
        tmp_path,
        cr_id="CR-101",
        title="bootstrap",
        scope="scope",
        readiness="READY",
        rebuild_corrupt=True,
    )

    assert paths["cr"].is_file()
    assert [item["id"] for item in cr_index.load_index(tmp_path)["items"]] == [
        "CR-100",
        "CR-101",
    ]


def test_index_bootstrap_cp0_summary_rejects_symlink_without_overwriting_target(
    tmp_path: Path,
) -> None:
    current.write_current_state(
        tmp_path,
        current.default_current_state(tmp_path, project_id="target-project"),
    )
    summary = tmp_path / "process/checks/CP0-CR-001-BOOTSTRAP.result.summary.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    victim = tmp_path / "victim.md"
    victim_bytes = b"do not overwrite\n"
    victim.write_bytes(victim_bytes)
    summary.symlink_to(victim)

    with pytest.raises(FileExistsError, match="CP0 summary target already exists"):
        cr_index.bootstrap_cr(
            tmp_path,
            cr_id="CR-001",
            title="bootstrap",
            scope="scope",
            readiness="READY",
        )

    assert summary.is_symlink()
    assert victim.read_bytes() == victim_bytes
