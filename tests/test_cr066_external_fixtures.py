from __future__ import annotations

from pathlib import Path

import pytest
from cr066_external_fixture_harness import (
    FIXTURE_IDS,
    FIXTURE_RUNNERS,
    load_fixture_matrix,
)

FIXTURE_MATRIX = Path(__file__).parent / "fixtures" / "cr066" / "fixture_matrix.json"
REQUIRED_EVIDENCE = {
    "initial_state",
    "exact_command",
    "expected_result",
    "actual_result",
    "file_mutations",
    "before_digest",
    "after_digest",
    "failure_path",
    "rollback",
    "user_experience",
    "io_measurement",
}


def test_fixture_matrix_freezes_four_isolated_cases_and_evidence_contract() -> None:
    payload = load_fixture_matrix(FIXTURE_MATRIX)

    assert payload["revision"] == "C66-G2-track-mf-v1"
    assert payload["execution_boundary"] == "isolated-temporary-directories-only"
    assert payload["token_measurement"] == "unavailable"
    assert tuple(item["id"] for item in payload["fixtures"]) == FIXTURE_IDS
    assert all("<isolated-root>" in item["exact_command"] for item in payload["fixtures"])


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_external_fixture_is_auditable_and_passes(
    fixture_id: str,
    tmp_path: Path,
) -> None:
    report = FIXTURE_RUNNERS[fixture_id](tmp_path)

    assert REQUIRED_EVIDENCE <= set(report)
    assert report["fixture_id"] == fixture_id
    assert report["decision"] == "PASS", report
    assert report["actual_result"]["decision"] == "PASS", report
    assert report["rollback"]["decision"] in {"PASS", "NOOP"}, report
    assert report["rollback"]["digest_restored"] is True, report
    assert report["io_measurement"]["token"] == {
        "status": "unavailable",
        "value": None,
    }
    assert report["io_measurement"]["reads"]["status"] == "unavailable"
    assert report["io_measurement"]["writes"]["status"] == "measured-filesystem-diff"


def test_project_init_is_plan_only_and_path_escape_is_blocked(tmp_path: Path) -> None:
    report = FIXTURE_RUNNERS["project-init"](tmp_path)

    assert report["actual_result"]["actual_mutations"] == 0
    assert report["actual_result"]["plan_digest_deterministic"] is True
    assert report["actual_result"]["path_escape_blocked"] is True
    assert report["actual_result"]["process_link_created"] is False
    assert report["before_digest"] == report["after_digest"]


def test_snapshot_only_does_not_copy_history_or_mutate_source(tmp_path: Path) -> None:
    report = FIXTURE_RUNNERS["snapshot-only"](tmp_path)

    assert report["actual_result"]["historical_artifacts_copied"] == 0
    assert report["actual_result"]["source_unchanged"] is True
    assert report["actual_result"]["git_history_rewrites"] == 0
    assert report["actual_result"]["sibling_discovery"] == 0
    assert report["actual_result"]["duplicate_snapshot_payloads"] == 0


def test_install_lifecycle_is_idempotent_and_preserves_user_files(tmp_path: Path) -> None:
    report = FIXTURE_RUNNERS["installation-lifecycle"](tmp_path)

    assert report["actual_result"]["dry_run_mutations"] == 0, report
    assert report["actual_result"]["repeat_actual_mutations"] == 0, report
    assert report["actual_result"]["user_files_preserved"] is True, report
    assert report["actual_result"]["rollback_digest_restored"] is True, report


def test_partial_failure_stops_later_slice_and_requires_explicit_recovery(
    tmp_path: Path,
) -> None:
    report = FIXTURE_RUNNERS["failure-recovery"](tmp_path)

    assert report["actual_result"]["failure_state"] == "partial"
    assert report["actual_result"]["inspect_mutations"] == 0
    assert report["actual_result"]["unauthenticated_recovery_blocked"] is True
    assert report["actual_result"]["resume_pending_actions"] == ["action-2"]
    assert report["actual_result"]["rollback_actions"] == ["action-1"]
    assert report["actual_result"]["later_slice_executions"] == 0
    assert report["actual_result"]["final_state"] == "rolled_back"
