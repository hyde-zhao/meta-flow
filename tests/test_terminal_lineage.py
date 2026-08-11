from __future__ import annotations

import json
from hashlib import sha256

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.workflow.terminal_lineage import (
    TerminalLineageRecordV1,
    _cr_records,
    _evidence_records,
    _load_dispositions,
    project_terminal_lineage,
)


def _record(
    kind: str,
    identity: str,
    revision: int,
    ordinal: int,
    status: str,
    terminal: bool,
) -> TerminalLineageRecordV1:
    payload = {
        "kind": kind,
        "identity": identity,
        "revision": revision,
        "ordinal": ordinal,
        "status": status,
    }
    return TerminalLineageRecordV1(
        kind,
        identity,
        revision,
        ordinal,
        f"event-{ordinal}",
        status,
        terminal,
        "state/fixture.ndjson",
        canonical_digest(payload),
    )


def test_latest_revision_and_append_ordinal_define_one_current_record() -> None:
    report = project_terminal_lineage(
        (
            _record("dispatch", "D-1", 1, 1, "running", False),
            _record("dispatch", "D-1", 1, 2, "blocked", True),
            _record("dispatch", "D-1", 2, 3, "running", False),
            _record("dispatch", "D-1", 2, 4, "completed", True),
        )
    )

    assert report["decision"] == "PASS"
    assert len(report["current"]) == 1
    assert report["current"][0]["revision"] == 2
    assert report["current"][0]["event_id"] == "event-4"
    assert len(report["history"]) == 3


def test_nonterminal_latest_blocks_even_when_an_older_revision_completed() -> None:
    report = project_terminal_lineage(
        (
            _record("gate", "G-1", 1, 1, "passed", True),
            _record("gate", "G-1", 2, 2, "authorized", False),
        )
    )

    assert report["decision"] == "BLOCKED"
    assert report["findings"] == ["LATEST_NOT_TERMINAL:gate:G-1:authorized"]


def test_exact_source_bound_disposition_can_close_historical_nonterminal() -> None:
    latest = _record("dispatch", "D-LEGACY", 1, 1, "running", False)
    report = project_terminal_lineage(
        (latest,),
        dispositions={
            latest.key: {
                "source_digest": latest.source_digest,
                "terminal_status": "superseded",
                "reason": "historical dispatch superseded by terminal container",
                "evidence_refs": ["process/changes/CR-001.md"],
            }
        },
    )

    assert report["decision"] == "PASS"
    assert report["current"][0]["terminal"] is True
    assert report["current"][0]["disposition_applied"] is True


def test_disposition_rejects_nonterminal_status_for_record_kind() -> None:
    latest = _record("dispatch", "D-LEGACY", 1, 1, "running", False)

    report = project_terminal_lineage(
        (latest,),
        dispositions={
            latest.key: {
                "source_digest": latest.source_digest,
                "terminal_status": "running",
                "reason": "invalid fixture",
                "evidence_refs": ["process/changes/CR-001.md"],
            }
        },
    )

    assert report["decision"] == "BLOCKED"
    assert "DISPOSITION_STATUS_NOT_TERMINAL:dispatch:D-LEGACY:running" in report["findings"]
    assert "LATEST_NOT_TERMINAL:dispatch:D-LEGACY:running" in report["findings"]


def test_disposition_cannot_survive_source_drift_or_missing_target() -> None:
    latest = _record("work", "W-1", 1, 1, "active", False)
    report = project_terminal_lineage(
        (latest,),
        dispositions={
            latest.key: {
                "source_digest": "0" * 64,
                "terminal_status": "cancelled",
                "reason": "fixture",
                "evidence_refs": ["process/evidence.json"],
            },
            "work:W-MISSING": {
                "source_digest": "0" * 64,
                "terminal_status": "cancelled",
                "reason": "fixture",
                "evidence_refs": ["process/evidence.json"],
            },
        },
    )

    assert report["decision"] == "BLOCKED"
    assert "DISPOSITION_SOURCE_DRIFT:work:W-1" in report["findings"]
    assert "DISPOSITION_TARGET_MISSING:work:W-MISSING" in report["findings"]


def test_evidence_without_decision_is_explicitly_artifact_available_not_pass(
    tmp_path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "STORY-001.CP6.index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "story_id": "STORY-001",
                "stage": "CP6",
                "return_ref": "process/returns/STORY-001.CP6.return.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records, errors = _evidence_records(tmp_path)
    report = project_terminal_lineage(records)

    assert errors == []
    assert records[0].status == "artifact-available"
    assert records[0].status_source == "derived-artifact-presence"
    assert records[0].verification_decision == ""
    assert report["decision"] == "PASS"
    assert report["evidence_semantics"] == {
        "current_count": 1,
        "explicit_status_or_decision_count": 0,
        "derived_artifact_availability_count": 1,
        "verification_decision_counts": {},
        "terminal_does_not_imply_verification_pass": True,
    }


def test_malformed_statusless_evidence_fails_closed(tmp_path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "STORY-001.CP6.index.json").write_text("{}\n", encoding="utf-8")

    records, errors = _evidence_records(tmp_path)

    assert records == []
    assert errors
    assert "schema_version" in errors[0]


def test_formal_cr_truth_overlays_stale_ledger_and_binds_terminal_evidence(tmp_path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "changes" / "summaries").mkdir(parents=True)
    (tmp_path / "archive" / "CR-001").mkdir(parents=True)
    (tmp_path / "works").mkdir()
    (tmp_path / "state" / "CR-LEDGER.ndjson").write_text(
        json.dumps({"id": "CR-001", "status": "active", "event_id": "old"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "changes" / "CR-001.md").write_text(
        "---\nschema_version: 1\nkind: cr\ncr_id: CR-001\nlifecycle_status: closed\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "changes" / "summaries" / "CR-001.summary.json").write_text("{}\n")
    result = tmp_path / "works" / "result.json"
    result.write_text("{}\n")
    (tmp_path / "archive" / "CR-001" / "evidence-index.json").write_text(
        json.dumps(
            {
                "cr_id": "CR-001",
                "full_ref": "process/changes/CR-001.md",
                "summary_ref": "process/changes/summaries/CR-001.summary.json",
                "evidence_refs": ["process/works/result.json"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records, errors = _cr_records(tmp_path)
    report = project_terminal_lineage(records)

    assert errors == []
    assert report["decision"] == "PASS"
    assert report["current"][0]["status"] == "closed"
    assert report["current"][0]["status_source"] == "formal-cr-truth"


def test_disposition_evidence_digest_drift_fails_closed(tmp_path) -> None:
    policy = tmp_path / "policies"
    policy.mkdir()
    evidence = tmp_path / "evidence.json"
    evidence.write_text("before\n", encoding="utf-8")
    ref = "process/evidence.json"
    (policy / "TERMINAL-LINEAGE-DISPOSITIONS.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dispositions": [
                    {
                        "key": "dispatch:D-1",
                        "source_digest": "0" * 64,
                        "terminal_status": "superseded",
                        "reason": "fixture",
                        "evidence_refs": [ref],
                        "evidence_digests": {
                            ref: sha256(b"different\n").hexdigest(),
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    _dispositions, errors = _load_dispositions(tmp_path)

    assert errors == [
        "terminal lineage disposition evidence drift: dispatch:D-1:process/evidence.json"
    ]
