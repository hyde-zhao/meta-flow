from __future__ import annotations

import json
from pathlib import Path

from meta_flow.checks.check_artifact import (
    CheckArtifactKind,
    classify_check_artifact,
)


def _write(tmp_path: Path, name: str, payload: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def test_explicit_checkpoint_kind_requires_checkpoint_identity(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "unknown.result.json",
        {"schema_version": 1, "artifact_kind": "checkpoint_result"},
    )

    descriptor = classify_check_artifact(path, logical_ref="process/checks/unknown.result.json")

    assert descriptor.kind is CheckArtifactKind.UNKNOWN
    assert descriptor.findings == ("checkpoint_result requires cr_id and checkpoint CP0..CP8",)


def test_c0_apply_result_keeps_distinct_identity(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "C0-CR-061.result.json",
        {
            "schema_version": 1,
            "kind": "C0ApplyResultV1",
            "checkpoint": "C0",
            "cr_id": "CR-061",
            "decision": "PASS",
        },
    )

    descriptor = classify_check_artifact(path, logical_ref="process/checks/C0-CR-061.result.json")

    assert descriptor.kind is CheckArtifactKind.C0_APPLY_RESULT
    assert descriptor.classification_mode == "legacy-c0-kind"
    assert descriptor.findings == ()


def test_legacy_candidate_is_not_a_current_checkpoint_result(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "CP7-STORY-CR069-F1-S5.candidate-v4.result.json",
        {
            "schema_version": 1,
            "checkpoint": "CP7",
            "cr_id": "CR-069",
            "story_id": "STORY-CR069-F1-S5",
            "decision": "PASS",
            "contract_id": "CR069-S5-CP7-RESULT-V1",
            "cp7_event_id": "CP7-CR069-S5-CANDIDATE-PASS-V4",
        },
    )

    descriptor = classify_check_artifact(
        path,
        logical_ref="process/checks/CP7-STORY-CR069-F1-S5.candidate-v4.result.json",
    )

    assert descriptor.kind is CheckArtifactKind.CANDIDATE_CHECKPOINT_RESULT
    assert descriptor.classification_mode == "legacy-candidate-signature"
    assert descriptor.findings == ()


def test_generic_check_result_is_not_sent_to_checkpoint_schema(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "CR-068-FILE-OWNERSHIP-DAG.result.json",
        {
            "schema_version": 1,
            "check_id": "CR-068-FILE-OWNERSHIP-DAG",
            "check_mode": "static-design-delta",
            "decision": "PASS_WITH_BASELINE_LIMITATION",
            "nodes": [],
        },
    )

    descriptor = classify_check_artifact(
        path,
        logical_ref="process/checks/CR-068-FILE-OWNERSHIP-DAG.result.json",
    )

    assert descriptor.kind is CheckArtifactKind.CHECK_RESULT
    assert descriptor.classification_mode == "legacy-check-result-signature"
    assert descriptor.findings == ()


def test_unknown_result_remains_fail_closed(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "renamed.result.json",
        {"schema_version": 1, "decision": "PASS", "arbitrary": True},
    )

    descriptor = classify_check_artifact(
        path,
        logical_ref="process/checks/renamed.result.json",
    )

    assert descriptor.kind is CheckArtifactKind.UNKNOWN
    assert descriptor.findings == ("artifact kind cannot be determined",)
