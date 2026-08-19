from __future__ import annotations

# ruff: noqa: I001, UP031

import json
import os

import pytest

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


def test_projection_owner_exports_frozen_public_members() -> None:
    expected = {
        "CR_LEDGER_REL", "CR_ARCHIVE_ROOT_REL", "STATE_CURRENT_REL",
        "NativeCRStatusProjectionV1", "CheckpointIndexRowV1",
        "AggregateCompletionProjector",
        "_gate_checkpoint_projection", "_checkpoint_result_projection",
        "_render_exact_section_rows", "render_status_body_projection",
        "summary_from_cr_file", "write_summary", "write_evidence_index",
        "append_ledger_event", "load_ledger_events", "project_native_cr_status",
        "_atomic_write_text", "_transaction_root", "_status_sync_writer_lock_path",
        "_acquire_status_sync_writer_lock", "_release_status_sync_writer_lock",
    }
    assert {name for name in expected if hasattr(cr_projection, name)} == expected


def test_checkpoint_result_projection_preserves_exact_ref_and_cr_subject_only(
    tmp_path: Path,
) -> None:
    projection = Mock(
        findings=(),
        heads=(
            Mock(
                checkpoint="CP0",
                subject_id="CR-069",
                decision="PASS",
                result_ref="process/checks/CP0-CR-069.result.json",
            ),
            Mock(
                checkpoint="CP0",
                subject_id="STORY-CR069-F1-S0",
                decision="PASS",
                result_ref="process/checks/CP0-STORY.result.json",
            ),
        ),
    )
    with patch.object(
        cr_projection.checkpoint_projection,
        "load_checkpoint_projection",
        return_value=projection,
    ):
        rows = cr_projection._checkpoint_result_projection(tmp_path, "CR-069")

    assert rows == {
        "CP0": cr_projection.CheckpointIndexRowV1(
            checkpoint="CP0",
            status="PASS",
            result_ref="process/checks/CP0-CR-069.result.json",
        )
    }


def test_checkpoint_result_projection_fails_closed_on_owner_findings(
    tmp_path: Path,
) -> None:
    finding = Mock(code="CURRENT_HEAD_CONFLICT", message="conflict")
    projection = Mock(findings=(finding,), heads=())
    with patch.object(
        cr_projection.checkpoint_projection,
        "load_checkpoint_projection",
        return_value=projection,
    ), pytest.raises(ValueError, match="CURRENT_HEAD_CONFLICT"):
        cr_projection._checkpoint_result_projection(tmp_path, "CR-069")


def test_checkpoint_result_projection_rejects_duplicate_or_incomplete_heads(
    tmp_path: Path,
) -> None:
    duplicate = Mock(
        checkpoint="CP0",
        subject_id="CR-069",
        decision="PASS",
        result_ref="process/checks/CP0.result.json",
    )
    projection = Mock(findings=(), heads=(duplicate, duplicate))
    with patch.object(
        cr_projection.checkpoint_projection,
        "load_checkpoint_projection",
        return_value=projection,
    ), pytest.raises(ValueError, match="duplicate canonical checkpoint head"):
        cr_projection._checkpoint_result_projection(tmp_path, "CR-069")

    projection = Mock(
        findings=(),
        heads=(Mock(checkpoint="CP1", subject_id="CR-069", decision="PASS", result_ref=""),),
    )
    with patch.object(
        cr_projection.checkpoint_projection,
        "load_checkpoint_projection",
        return_value=projection,
    ), pytest.raises(ValueError, match="missing result_ref"):
        cr_projection._checkpoint_result_projection(tmp_path, "CR-069")


def test_checkpoint_index_renderer_updates_inserts_orders_and_is_idempotent() -> None:
    text = (
        "# CR-069\n\n## Checkpoint Index\n\n"
        "| Checkpoint | Status | Ref |\n"
        "|---|---|---|\n"
        "| CP0 | stale | `process/checks/stale.json` |\n"
        "| CP2 | pending | — |\n\n"
        "## Next\n\nkeep\n"
    )
    rows = {
        "CP0": cr_projection.CheckpointIndexRowV1(
            "CP0", "PASS", "process/checks/CP0.result.json"
        ),
        "CP1": cr_projection.CheckpointIndexRowV1(
            "CP1", "PASS", "process/checks/CP1.result.json"
        ),
    }

    rendered = cr_projection.render_status_body_projection(
        text,
        lifecycle_status="active",
        readiness_status="NOT_READY",
        gate_status="implementation_in_progress",
        checkpoint_results=rows,
    )

    assert "| CP0 | PASS | `process/checks/CP0.result.json` |" in rendered
    assert "| CP1 | PASS | `process/checks/CP1.result.json` |" in rendered
    assert "| CP2 | pending | — |" in rendered
    assert "| CP6 | in-progress | — |" in rendered
    assert [
        rendered.index(f"| CP{number} |") for number in (0, 1, 2, 6)
    ] == sorted(rendered.index(f"| CP{number} |") for number in (0, 1, 2, 6))
    assert cr_projection.render_status_body_projection(
        rendered,
        lifecycle_status="active",
        readiness_status="NOT_READY",
        gate_status="implementation_in_progress",
        checkpoint_results=rows,
    ) == rendered
    assert "## Next\n\nkeep\n" in rendered


def test_checkpoint_index_renderer_supports_two_columns_and_preserves_extra_columns() -> None:
    two_column = (
        "## Checkpoint Index\n"
        "| Checkpoint | Status |\n"
        "|---|---|\n"
        "| CP0 | stale |\n"
    )
    row = cr_projection.CheckpointIndexRowV1(
        "CP0", "PASS", "process/checks/CP0.result.json"
    )
    assert cr_projection._render_checkpoint_index_rows(two_column, {"CP0": row}) == (
        "## Checkpoint Index\n"
        "| Checkpoint | Status |\n"
        "|---|---|\n"
        "| CP0 | PASS |\n"
    )

    extra_column = (
        "## Checkpoint Index\n"
        "| Checkpoint | Note | Status | Ref |\n"
        "|---|---|---|---|\n"
        "| CP0 | keep | stale | `old` |\n"
    )
    assert "| CP0 | keep | PASS | `process/checks/CP0.result.json` |" in (
        cr_projection._render_checkpoint_index_rows(extra_column, {"CP0": row})
    )

    chinese_header = (
        "## Checkpoint Index\n"
        "| CP | 状态 | 机器结果 ref |\n"
        "|---|---|---|\n"
        "| CP0 | stale | `old` |\n"
    )
    assert "| CP0 | PASS | `process/checks/CP0.result.json` |" in (
        cr_projection._render_checkpoint_index_rows(chinese_header, {"CP0": row})
    )


def test_checkpoint_index_renderer_preserves_gate_ref_and_crlf() -> None:
    text = (
        "## Checkpoint Index\r\n"
        "| Checkpoint | Status | Ref |\r\n"
        "|---|---|---|\r\n"
        "| CP6 | pending | `process/checks/pending.json` |\r\n"
    )
    rendered = cr_projection.render_status_body_projection(
        text,
        lifecycle_status="active",
        readiness_status="NOT_READY",
        gate_status="implementation_in_progress",
        checkpoint_results={},
    )
    assert "| CP6 | in-progress | `process/checks/pending.json` |\r\n" in rendered
    assert "\n" not in rendered.replace("\r\n", "")

    cp8 = cr_projection.CheckpointIndexRowV1(
        "CP8", "PASS", "process/checks/CP8.result.json"
    )
    closed = cr_projection.render_status_body_projection(
        "## Checkpoint Index\n| Checkpoint | Status | Ref |\n|---|---|---|\n",
        lifecycle_status="closed",
        readiness_status="READY",
        gate_status="closed",
        checkpoint_results={"CP8": cp8},
    )
    assert "| CP8 | approved | `process/checks/CP8.result.json` |" in closed


@pytest.mark.parametrize(
    ("text", "line_ending"),
    [
        (
            "## Checkpoint Index\n"
            "| Checkpoint | Status | Ref |\n"
            "|---|---|---|\n"
            "| CP0 | PASS | `process/checks/CP0.result.json` |",
            "\n",
        ),
        (
            "## Checkpoint Index\n"
            "| Checkpoint | Status | Ref |\n"
            "|---|---|---|",
            "\n",
        ),
        (
            "## Checkpoint Index\r\n"
            "| Checkpoint | Status | Ref |\r\n"
            "|---|---|---|\r\n"
            "| CP0 | PASS | `process/checks/CP0.result.json` |",
            "\r\n",
        ),
    ],
)
def test_checkpoint_index_renderer_preserves_eof_without_newline_and_is_idempotent(
    text: str,
    line_ending: str,
) -> None:
    rows = {
        "CP0": cr_projection.CheckpointIndexRowV1(
            "CP0", "PASS", "process/checks/CP0.result.json"
        ),
        "CP1": cr_projection.CheckpointIndexRowV1(
            "CP1", "PASS", "process/checks/CP1.result.json"
        ),
    }

    rendered = cr_projection._render_checkpoint_index_rows(text, rows)

    assert not rendered.endswith(("\n", "\r"))
    assert (
        "| CP0 | PASS | `process/checks/CP0.result.json` |"
        + line_ending
        + "| CP1 | PASS | `process/checks/CP1.result.json` |"
    ) in rendered
    assert cr_projection._render_checkpoint_index_rows(rendered, rows) == rendered


def test_lifecycle_facade_accepts_legacy_string_checkpoint_projection() -> None:
    from meta_flow.workflow.cr_lifecycle import render_status_body_projection

    text = (
        "## Checkpoint Index\n"
        "| CP | 状态 |\n"
        "|---|---|\n"
        "| CP0 | pending |\n"
    )

    rendered = render_status_body_projection(
        text,
        lifecycle_status="active",
        readiness_status="NOT_READY",
        gate_status="cp3_pending",
        checkpoint_results={"CP0": "PASS"},
    )

    assert "| CP0 | PASS |" in rendered
    assert "| CP3 | pending |" in rendered


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "## Checkpoint Index\n| Checkpoint | Status | Ref |\n|---|---|---|\n| CP0 | PASS | — |\n"
            "| CP0 | PASS | — |\n",
            "duplicate CR body table row",
        ),
        (
            "## Checkpoint Index\n| Checkpoint | Status | Ref |\n|---|---|\n",
            "separator is malformed",
        ),
        (
            "## Checkpoint Index\n| Checkpoint | Status | Evidence |\n|---|---|---|\n",
            "result ref column is missing",
        ),
        (
            "## Checkpoint Index\n| Checkpoint | Status | Ref |\n|---|---|---|\n| CP9 | PASS | — |\n",
            "invalid Checkpoint Index key",
        ),
        (
            "## Checkpoint Index\n| Checkpoint | Status | Ref |\n|---|---|---|\n| CP2 | PASS | — |\n"
            "| CP1 | PASS | — |\n",
            "not in numeric order",
        ),
    ],
)
def test_checkpoint_index_renderer_fails_closed_on_malformed_tables(
    text: str, message: str
) -> None:
    before = text.encode("utf-8")
    with pytest.raises(ValueError, match=message):
        cr_projection._render_checkpoint_index_rows(
            text,
            {"CP0": cr_projection.CheckpointIndexRowV1("CP0", "PASS", "result.json")},
        )
    assert text.encode("utf-8") == before


def test_checkpoint_index_renderer_rejects_duplicate_section_and_keeps_absent_optional() -> None:
    row = cr_projection.CheckpointIndexRowV1("CP0", "PASS", "result.json")
    absent = "# CR\n\nno checkpoint section\n"
    assert cr_projection._render_checkpoint_index_rows(absent, {"CP0": row}) == absent
    duplicate = (
        "## Checkpoint Index\n| Checkpoint | Status |\n|---|---|\n"
        "## Checkpoint Index\n| Checkpoint | Status |\n|---|---|\n"
    )
    with pytest.raises(ValueError, match="duplicate CR body section"):
        cr_projection._render_checkpoint_index_rows(duplicate, {"CP0": row})


def test_projection_kernel_value_object_shape_is_stable() -> None:
    value = cr_projection.NativeCRStatusProjectionV1(
        "CR-001", "active", "READY", "cp5_pending", "cr", "summary", "event", "PASS", ()
    )
    assert value.as_dict()["kind"] == "NativeCRStatusProjectionV1"


def test_projection_summary_ledger_and_atomic_writer_owner_behaviour(tmp_path: Path) -> None:
    cr_path = _write_cr(tmp_path)
    summary = cr_projection.summary_from_cr_file(tmp_path, cr_path)
    assert summary["id"] == "CR-101"
    assert summary["decision_status"] == "n/a"
    assert "decision" not in summary
    assert "followup_candidates" not in summary
    assert "follow_up_tracking_ref" not in summary
    assert cr_projection.write_summary(tmp_path, "CR-101", summary).is_file()
    assert cr_projection.write_evidence_index(tmp_path, "CR-101", summary).is_file()
    cr_projection.append_ledger_event(tmp_path, {"id": "CR-101", "event": "active"})
    assert cr_projection.load_ledger_events(tmp_path) == [{"event": "active", "id": "CR-101"}]
    output = tmp_path / "atomic.txt"
    cr_projection._atomic_write_text(output, "one\n")
    cr_projection._atomic_write_text(output, "two\n")
    assert output.read_text(encoding="utf-8") == "two\n"


def test_summary_projects_typed_gate_decision_and_controlled_release_dispositions(
    tmp_path: Path,
) -> None:
    cr_path = _write_cr(tmp_path)
    cr_path.write_text(
        cr_path.read_text(encoding="utf-8").replace(
            'lifecycle_status: "active"',
            'lifecycle_status: "closed"',
        ),
        encoding="utf-8",
    )
    gate_ledger = tmp_path / "process/state/GATE-LEDGER.ndjson"
    gate_ledger.parent.mkdir(parents=True)
    gate_ledger.write_text(
        json.dumps(
            {
                "event_id": "GATE-CR101-CP8-APPROVED",
                "event_type": "human_gate_approval",
                "gate": "GATE-CR101-CP8",
                "status": "approved",
                "decision": "approve",
                "cr_id": "CR-101",
                "work_id": "W-101",
                "approval_kind_version": 1,
                "approval_kind": "checkpoint_passage",
                "checkpoint": "CP8",
                "result_ref": "process/checks/CP8-CR-101.result.json",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    release_ref = "process/release/RELEASE-CONTEXT-CR101.yaml"
    release_path = tmp_path / release_ref
    release_path.parent.mkdir(parents=True)
    release_path.write_text(
        json.dumps(
            {
                "cr_id": "CR-101",
                "release_decision": "READY_WITH_RISK",
                "fact_diff": [
                    {
                        "promise_ref": "CR101-BASELINE",
                        "status": "EXECUTED_NEGATIVE_RESULT",
                        "decision_impact": "READY_WITH_RISK",
                        "risk_ref": "RISK-CR101-BASELINE",
                        "evidence_refs": ["process/evidence/baseline.json"],
                    },
                    {
                        "promise_ref": "CR101-CORRECTION",
                        "status": "DEFERRED_FOLLOW_UP",
                        "risk_ref": "RISK-CR101-CORRECTION",
                        "evidence_refs": ["process/evidence/correction.json"],
                    },
                ],
                "publication_result": {
                    "decision": "RELEASED",
                    "risk_disposition": {"waiver": False, "new_failure_count": 0},
                },
                "follow_up_summary": ["repair baseline", "authorize correction later"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = cr_projection.summary_from_cr_file(tmp_path, cr_path)

    assert summary["decision_status"] == "approved"
    assert summary["follow_up_tracking_ref"] == release_ref
    assert [item["candidate_id"] for item in summary["followup_candidates"]] == [
        "CR101-CORRECTION",
        "RISK-CR101-BASELINE",
    ]
    assert cr_projection.validate_summary_semantics(tmp_path, "CR-101", summary) == []


def test_summary_rejects_invalid_latest_typed_gate_approval(tmp_path: Path) -> None:
    cr_path = _write_cr(tmp_path)
    gate_ledger = tmp_path / "process/state/GATE-LEDGER.ndjson"
    gate_ledger.parent.mkdir(parents=True)
    valid = {
        "event_id": "GATE-CR101-CP8-APPROVED",
        "event_type": "human_gate_approval",
        "gate": "GATE-CR101-CP8",
        "status": "approved",
        "decision": "approve",
        "cr_id": "CR-101",
        "work_id": "W-101",
        "approval_kind_version": 1,
        "approval_kind": "checkpoint_passage",
        "checkpoint": "CP8",
        "result_ref": "process/checks/CP8-CR-101.result.json",
    }
    invalid_latest = {
        **valid,
        "event_id": "GATE-CR101-CP8-INVALID-LATEST",
        "work_id": "",
    }
    gate_ledger.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in (valid, invalid_latest))
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="gate decision owner approval is invalid"):
        cr_projection.summary_from_cr_file(tmp_path, cr_path)


@pytest.mark.parametrize(
    ("fact_diff", "error"),
    [
        (
            [
                {
                    "promise_ref": "CR101-CORRECTION",
                    "status": "DEFERRED_FOLLOW_UP",
                    "evidence_refs": ["../outside.json"],
                }
            ],
            "follow-up disposition evidence ref is invalid",
        ),
        (
            [
                {
                    "promise_ref": "CR101-CORRECTION",
                    "status": "DEFERRED_FOLLOW_UP",
                    "evidence_refs": ["process/evidence/one.json"],
                },
                {
                    "promise_ref": "CR101-CORRECTION",
                    "status": "DEFERRED_FOLLOW_UP",
                    "evidence_refs": ["process/evidence/two.json"],
                },
            ],
            "follow-up disposition candidate is duplicated",
        ),
        (
            [
                {
                    "promise_ref": "CR101-CORRECTION",
                    "status": "DEFERRED_FOLLOW_UP",
                    "evidence_refs": [],
                }
            ],
            "follow-up disposition evidence is missing",
        ),
    ],
)
def test_summary_rejects_untraceable_release_dispositions(
    tmp_path: Path,
    fact_diff: list[dict[str, object]],
    error: str,
) -> None:
    cr_path = _write_cr(tmp_path)
    release_path = tmp_path / "process/release/RELEASE-CONTEXT-CR101.yaml"
    release_path.parent.mkdir(parents=True)
    release_path.write_text(
        json.dumps({"cr_id": "CR-101", "fact_diff": fact_diff}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=error):
        cr_projection.summary_from_cr_file(tmp_path, cr_path)


def test_summary_semantics_rejects_forged_follow_up_candidate(tmp_path: Path) -> None:
    release_path = tmp_path / "process/release/RELEASE-CONTEXT-CR101.yaml"
    release_path.parent.mkdir(parents=True)
    release_path.write_text(
        json.dumps({"cr_id": "CR-101", "follow_up_summary": ["tracked"]}) + "\n",
        encoding="utf-8",
    )

    findings = cr_projection.validate_summary_semantics(
        tmp_path,
        "CR-101",
        {
            "id": "CR-101",
            "status": "closed",
            "follow_up_tracking_ref": "process/release/RELEASE-CONTEXT-CR101.yaml",
            "followup_candidates": [
                {
                    "candidate_id": "CR101-FORGED",
                    "disposition": "DEFERRED_FOLLOW_UP",
                    "risk_ref": None,
                    "evidence_refs": ["process/evidence/forged.json"],
                    "source_ref": "process/release/RELEASE-CONTEXT-CR101.yaml",
                }
            ],
        },
    )

    assert "followup_candidates diverge from disposition owner" in findings


def test_summary_does_not_infer_risk_acceptance_before_publication(
    tmp_path: Path,
) -> None:
    cr_path = _write_cr(tmp_path)
    release_path = tmp_path / "process/release/RELEASE-CONTEXT-CR101.yaml"
    release_path.parent.mkdir(parents=True)
    release_path.write_text(
        json.dumps(
            {
                "cr_id": "CR-101",
                "release_decision": "READY_WITH_RISK",
                "fact_diff": [
                    {
                        "promise_ref": "CR101-BASELINE",
                        "status": "EXECUTED_NEGATIVE_RESULT",
                        "decision_impact": "READY_WITH_RISK",
                        "risk_ref": "RISK-CR101-BASELINE",
                        "evidence_refs": ["process/evidence/baseline.json"],
                    }
                ],
                "publication_result": {
                    "decision": "PENDING",
                    "risk_disposition": {"new_failure_count": 0},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = cr_projection.summary_from_cr_file(tmp_path, cr_path)

    assert "followup_candidates" not in summary
    assert "follow_up_tracking_ref" not in summary


def test_summary_accepts_released_mapping_fact_diff_owner(tmp_path: Path) -> None:
    cr_path = _write_cr(tmp_path)
    release_path = tmp_path / "process/release/RELEASE-CONTEXT-CR101.yaml"
    release_path.parent.mkdir(parents=True)
    release_path.write_text(
        json.dumps(
            {
                "cr_id": "CR-101",
                "release_decision": "RELEASED",
                "fact_diff": {
                    "items": [
                        {
                            "promise_ref": "CR101-COST",
                            "status": "EXECUTED_NEGATIVE_RESULT",
                            "decision_impact": "READY_WITH_RISK",
                            "risk_ref": "RISK-CR101-COST",
                            "evidence_refs": ["process/evidence/cost.json"],
                        }
                    ]
                },
                "publication_result": {
                    "decision": "RELEASED",
                    "risk_disposition": {"waiver": False},
                },
                "follow_up_summary": ["cost calibration"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = cr_projection.summary_from_cr_file(tmp_path, cr_path)

    assert summary["followup_candidates"] == [
        {
            "candidate_id": "RISK-CR101-COST",
            "disposition": "RISK_ACCEPTED_FOR_RELEASE",
            "risk_ref": "RISK-CR101-COST",
            "evidence_refs": ["process/evidence/cost.json"],
            "source_ref": "process/release/RELEASE-CONTEXT-CR101.yaml",
        }
    ]
    assert cr_projection.validate_summary_semantics(tmp_path, "CR-101", summary) == []


def test_summary_semantics_rejects_decision_status_not_owned_by_gate(
    tmp_path: Path,
) -> None:
    _write_cr(tmp_path)

    findings = cr_projection.validate_summary_semantics(
        tmp_path,
        "CR-101",
        {
            "id": "CR-101",
            "full_ref": "process/changes/CR-101.md",
            "status": "active",
            "decision_status": "approved",
        },
    )

    assert "decision_status diverges from its gate decision owner" in findings


def test_summary_semantics_rejects_terminal_pending_and_untracked_release_follow_up(
    tmp_path: Path,
) -> None:
    release_path = tmp_path / "process/release/RELEASE-CONTEXT-CR101.yaml"
    release_path.parent.mkdir(parents=True)
    release_path.write_text(
        json.dumps(
            {
                "cr_id": "CR-101",
                "release_decision": "READY_WITH_RISK",
                "follow_up_summary": ["unowned follow-up"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    findings = cr_projection.validate_summary_semantics(
        tmp_path,
        "CR-101",
        {
            "id": "CR-101",
            "status": "closed",
            "decision_status": "pending",
        },
    )

    assert "closed CR cannot have decision_status=pending" in findings
    assert "release follow-up has no disposition or tracking ref" in findings


def test_new_reader_treats_legacy_summary_decision_as_not_applicable(tmp_path: Path) -> None:
    legacy_summary = {
        "id": "CR-101",
        "status": "closed",
        "decision": "pending",
        "followup_candidates": [],
    }

    assert (
        cr_projection.validate_summary_semantics(
            tmp_path,
            "CR-101",
            legacy_summary,
        )
        == []
    )


def test_projection_writers_skip_volatile_or_byte_identical_rewrites(tmp_path: Path) -> None:
    summary = {
        "id": "CR-101",
        "full_ref": "process/changes/CR-101.md",
        "status": "active",
        "updated_at": "2026-08-03T00:00:00+00:00",
    }
    summary_path = cr_projection.write_summary(tmp_path, "CR-101", summary)
    os.utime(summary_path, (1, 1))

    cr_projection.write_summary(
        tmp_path,
        "CR-101",
        {**summary, "updated_at": "2026-08-03T00:01:00+00:00"},
    )

    assert summary_path.stat().st_mtime_ns == 1_000_000_000
    with patch.object(
        cr_projection,
        "now_utc",
        side_effect=(
            "2026-08-03T00:00:00+00:00",
            "2026-08-03T00:01:00+00:00",
        ),
    ):
        evidence_path = cr_projection.write_evidence_index(
            tmp_path, "CR-101", summary
        )
        os.utime(evidence_path, (1, 1))
        cr_projection.write_evidence_index(tmp_path, "CR-101", summary)
    assert evidence_path.stat().st_mtime_ns == 1_000_000_000

    output = tmp_path / "same.txt"
    cr_projection._atomic_write_text(output, "same\n")
    os.utime(output, (1, 1))
    cr_projection._atomic_write_text(output, "same\n")
    assert output.stat().st_mtime_ns == 1_000_000_000


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
