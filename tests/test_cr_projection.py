from __future__ import annotations

# ruff: noqa: I001, UP031

import json

from meta_flow.workflow import cr_projection
from unittest.mock import Mock, patch
from pathlib import Path


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


def _write_converged_native_projection_fixture(root: Path) -> dict[str, object]:
    cr_path = _write_cr(root)
    text = cr_path.read_text(encoding="utf-8")
    cr_path.write_text(
        text.replace(
            'lifecycle_status: "active"\nreadiness_status: "READY"\n'
            'gate_status: "cp5_pending"',
            'lifecycle_status: "closed"\n'
            'readiness_status: "READY_WITH_RISK"\n'
            'gate_status: "cp8_closed"',
        ),
        encoding="utf-8",
    )
    summary = cr_projection.summary_from_cr_file(root, cr_path)
    cr_projection.write_summary(root, "CR-101", summary)
    cr_projection.append_ledger_event(
        root,
        {
            "event": "status_sync",
            "event_id": "CR-101-CLOSED",
            "id": "CR-101",
            "status": "closed",
            "readiness": "READY_WITH_RISK",
            "gate_status": "cp8_closed",
            "full_ref": "process/changes/CR-101.md",
            "summary_ref": "process/changes/summaries/CR-101.summary.json",
        },
    )
    return {
        "items": [
            {
                "id": "CR-101",
                "lifecycle_status": "closed",
                "readiness_status": "READY_WITH_RISK",
                "gate_status": "cp8_closed",
                "full_ref": "process/changes/CR-101.md",
                "summary_ref": "process/changes/summaries/CR-101.summary.json",
            }
        ]
    }


def test_projection_owner_exports_frozen_twenty_members() -> None:
    expected = {
        "CR_LEDGER_REL", "CR_ARCHIVE_ROOT_REL", "STATE_CURRENT_REL",
        "NativeCRStatusProjectionV1", "AggregateCompletionProjector",
        "_gate_checkpoint_projection", "_checkpoint_result_projection",
        "_render_exact_section_rows", "render_status_body_projection",
        "summary_from_cr_file", "write_summary", "write_evidence_index",
        "append_ledger_event", "load_ledger_events", "project_native_cr_status",
        "_atomic_write_text", "_transaction_root", "_status_sync_writer_lock_path",
        "_acquire_status_sync_writer_lock", "_release_status_sync_writer_lock",
    }
    assert {name for name in expected if hasattr(cr_projection, name)} == expected


def test_projection_kernel_value_object_shape_is_stable() -> None:
    value = cr_projection.NativeCRStatusProjectionV1(
        "CR-001", "active", "READY", "cp5_pending", "cr", "summary", "event", "PASS", ()
    )
    assert value.as_dict()["kind"] == "NativeCRStatusProjectionV1"


def test_projection_summary_ledger_and_atomic_writer_owner_behaviour(tmp_path: Path) -> None:
    cr_path = _write_cr(tmp_path)
    summary = cr_projection.summary_from_cr_file(tmp_path, cr_path)
    assert summary["id"] == "CR-101"
    assert cr_projection.write_summary(tmp_path, "CR-101", summary).is_file()
    assert cr_projection.write_evidence_index(tmp_path, "CR-101", summary).is_file()
    cr_projection.append_ledger_event(tmp_path, {"id": "CR-101", "event": "active"})
    assert cr_projection.load_ledger_events(tmp_path) == [{"event": "active", "id": "CR-101"}]
    output = tmp_path / "atomic.txt"
    cr_projection._atomic_write_text(output, "one\n")
    cr_projection._atomic_write_text(output, "two\n")
    assert output.read_text(encoding="utf-8") == "two\n"


def test_projection_writer_lock_owner_behaviour(tmp_path: Path) -> None:
    (tmp_path / "process").mkdir()
    owner = cr_projection._acquire_status_sync_writer_lock(
        tmp_path, transaction_id="TX-1", purpose="test"
    )
    assert owner is not None
    assert cr_projection._acquire_status_sync_writer_lock(
        tmp_path, transaction_id="TX-2", purpose="test"
    ) is None
    assert cr_projection._release_status_sync_writer_lock(tmp_path, owner) is True


def test_native_status_owner_handles_missing_formal_cr_directly(tmp_path: Path) -> None:
    projection = cr_projection.project_native_cr_status(
        tmp_path, cr_id="CR-404", resolve_runtime_ref=lambda root, ref: root / ref,
        rel=lambda _root, path: path.as_posix(), load_index=lambda _root: {},
    )
    assert projection.decision == "BLOCKED"
    assert projection.findings == ("FORMAL_CR_MISSING",)


def test_native_cr_status_projection_requires_four_source_convergence(tmp_path: Path) -> None:
    index = _write_converged_native_projection_fixture(tmp_path)
    resolve_runtime_ref = Mock(side_effect=lambda root, logical_ref: root / logical_ref)
    rel = Mock(side_effect=lambda root, path: path.relative_to(root).as_posix())
    load_index = Mock(return_value=index)

    projection = cr_projection.project_native_cr_status(
        tmp_path,
        cr_id="CR-101",
        resolve_runtime_ref=resolve_runtime_ref,
        rel=rel,
        load_index=load_index,
    )

    assert projection.decision == "PASS"
    assert projection.findings == ()
    assert projection.as_dict() == {
        "cr_id": "CR-101",
        "lifecycle_status": "closed",
        "readiness_status": "ready_with_risk",
        "gate_status": "cp8_closed",
        "formal_cr_ref": "process/changes/CR-101.md",
        "summary_ref": "process/changes/summaries/CR-101.summary.json",
        "ledger_event_id": "CR-101-CLOSED",
        "decision": "PASS",
        "findings": [],
        "kind": "NativeCRStatusProjectionV1",
        "schema_version": 1,
    }
    assert {
        call.args[1] for call in resolve_runtime_ref.call_args_list
    } == {
        "process/changes",
        "process/changes/summaries/CR-101.summary.json",
        "process/state/CR-LEDGER.ndjson",
    }
    rel.assert_called_once_with(tmp_path, tmp_path / "process/changes/CR-101.md")
    load_index.assert_called_once_with(tmp_path)


def test_native_cr_status_projection_blocks_derived_status_drift(tmp_path: Path) -> None:
    index = _write_converged_native_projection_fixture(tmp_path)
    index["items"][0]["lifecycle_status"] = "active"  # type: ignore[index]
    summary_path = tmp_path / "process/changes/summaries/CR-101.summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["status"] = "active"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    cr_projection.append_ledger_event(
        tmp_path,
        {
            "event": "status_sync",
            "event_id": "CR-101-DRIFT",
            "id": "CR-101",
            "status": "active",
            "readiness": "NOT_READY",
            "gate_status": "cp8_pending",
            "full_ref": "process/changes/CR-101.md",
            "summary_ref": "process/changes/summaries/CR-101.summary.json",
        },
    )

    projection = cr_projection.project_native_cr_status(
        tmp_path,
        cr_id="CR-101",
        resolve_runtime_ref=lambda root, logical_ref: root / logical_ref,
        rel=lambda root, path: path.relative_to(root).as_posix(),
        load_index=lambda _root: index,
    )

    assert projection.decision == "BLOCKED"
    assert projection.findings == (
        "CR_INDEX_STATUS_DIVERGED",
        "CR_SUMMARY_STATUS_DIVERGED",
        "CR_LEDGER_STATUS_DIVERGED",
    )


def test_aggregate_completion_projector_is_direct_owner_type() -> None:
    projector = cr_projection.AggregateCompletionProjector(
        project_root=Path("."), expected_state_updated_at="2026-01-01T00:00:00+00:00"
    )
    assert isinstance(projector, cr_projection.AggregateCompletionProjector)


def test_aggregate_completion_projector_uses_injected_owner_collaborators(
    tmp_path: Path,
) -> None:
    append_ledger_event = Mock(return_value=tmp_path / "process/state/CR-LEDGER.ndjson")
    rel = Mock(return_value="process/state/CR-LEDGER.ndjson")
    projector = cr_projection.AggregateCompletionProjector(
        project_root=tmp_path,
        expected_state_updated_at="2026-01-01T00:00:00+00:00",
        append_ledger_event_fn=append_ledger_event,
        rel_fn=rel,
    )
    result = Mock(
        cr_id="CR-101",
        aggregate_id="AGG-1",
        overall="PASS",
        terminal=True,
        projection_decision="ELIGIBLE",
        payload_digest="digest",
    )
    receipt = Mock(
        aggregate_id="AGG-1",
        aggregate_ref="process/aggregates/AGG-1.json",
        readback_valid=True,
        current_selected=True,
    )

    with patch.object(
        cr_projection.current,
        "project_aggregate_completion",
        return_value={"status": "projected"},
    ):
        projected = projector.project_aggregate(result=result, receipt=receipt)

    assert projected["status"] == "complete"
    assert projected["writer_receipts"]["cr_ledger"] == {
        "status": "projected",
        "ledger_ref": "process/state/CR-LEDGER.ndjson",
    }
    append_ledger_event.assert_called_once()
    rel.assert_called_once_with(
        tmp_path.resolve(), tmp_path / "process/state/CR-LEDGER.ndjson"
    )
