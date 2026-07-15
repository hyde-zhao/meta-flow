from __future__ import annotations

import json
from pathlib import Path

from meta_flow.checks import quality_governance, token_budget


def _row(rel_path: str) -> token_budget.FileBudgetInfo:
    return token_budget.FileBudgetInfo(
        path=Path(rel_path),
        rel_path=rel_path,
        byte_count=9000,
        estimated_tokens=2250,
        default_read_status="DENY_DEFAULT",
        artifact_kind="cp_check_lite",
        budget_bytes=8192,
    )


def _state(root: Path, active_change: str) -> None:
    path = root / "process" / "state" / "STATE.current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"active_change": active_change}), encoding="utf-8")


def test_active_over_budget_object_is_blocking(tmp_path: Path) -> None:
    _state(tmp_path, "CR-047")

    disposition = token_budget.classify_over_budget(
        tmp_path, _row("process/checks/CP6-CR047-ST-WT-001.result.json")
    )

    assert disposition.blocking
    assert disposition.lifecycle_class == "active"
    assert disposition.read_class == "default-required"


def test_closed_over_budget_object_is_reference_only_warning(tmp_path: Path) -> None:
    _state(tmp_path, "CR-047")
    archive = tmp_path / "process" / "archive" / "CR-037" / "evidence-index.json"
    archive.parent.mkdir(parents=True)
    archive.write_text("{}\n", encoding="utf-8")

    disposition = token_budget.classify_over_budget(
        tmp_path, _row("process/checks/CP7-CR037-S01-VERIFICATION-DONE.result.json")
    )

    assert not disposition.blocking
    assert disposition.severity == "WARN"
    assert disposition.read_class == "reference-only"
    assert disposition.remediation_ref == "process/archive/CR-037/evidence-index.json"


def test_unknown_over_budget_object_remains_fail_closed(tmp_path: Path) -> None:
    _state(tmp_path, "CR-047")

    disposition = token_budget.classify_over_budget(
        tmp_path, _row("process/checks/UNOWNED.result.json")
    )

    assert disposition.blocking
    assert disposition.lifecycle_class == "unclassified"


def test_append_only_correction_only_downgrades_targeted_legacy_result(tmp_path: Path) -> None:
    correction = tmp_path / quality_governance.READ_EXPANSION_CORRECTION_REL
    correction.parent.mkdir(parents=True)
    correction.write_text(
        json.dumps(
            {
                "schema_version": "meta-flow.correction/v1",
                "event_id": "C1",
                "target_ref": {
                    "namespace": "cp-result",
                    "id": "process/checks/CP0-CR-037.result.json",
                    "source_sha256": "sha256:fixture",
                },
                "patch": [
                    {
                        "op": "add",
                        "path": "/annotations/read_expansion_provenance",
                        "value": {"status": "legacy/unavailable", "does_not_assert_pass": True},
                    }
                ],
                "author": "auditor",
                "reason": "legacy provenance unavailable",
                "evidence_refs": ["process/changes/CR-047.md"],
                "created_at": "2026-07-15T00:00:00Z",
                "historical_mutation": False,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    targets, errors = quality_governance._load_read_expansion_corrections(tmp_path)

    assert errors == []
    assert targets == {"process/checks/CP0-CR-037.result.json": "C1"}
