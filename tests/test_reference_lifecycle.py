from __future__ import annotations

from pathlib import Path

import pytest

from meta_flow.project.reference_lifecycle import (
    ReferenceCandidateV1,
    _load_candidates,
    build_reference_index,
    classify_reference_candidate,
)
from meta_flow.work.model import normalize_legacy_work_payload
from meta_flow.workflow.story_evidence import _slug_status


def test_legacy_terminal_work_completed_at_is_read_only_compatible() -> None:
    payload = {
        "schema_version": 1,
        "status": "completed",
        "completed_at": "2026-08-03",
    }

    normalized, reasons = normalize_legacy_work_payload(payload)

    assert payload["completed_at"] == "2026-08-03"
    assert "completed_at" not in normalized
    assert normalized["updated_at"] == "2026-08-03"
    assert "LEGACY_COMPLETED_AT_READ_COMPATIBILITY" in reasons


def test_legacy_completed_at_never_legalizes_nonterminal_work() -> None:
    with pytest.raises(ValueError, match="terminal Work"):
        normalize_legacy_work_payload(
            {
                "schema_version": 1,
                "status": "active",
                "completed_at": "2026-08-03",
            }
        )


def test_legacy_story_completed_aliases_are_canonicalized_to_done() -> None:
    assert _slug_status("completed") == "done"
    assert _slug_status("completed-direct") == "done"
    assert _slug_status("ready_for_verification") == "ready-for-verification"


def _candidate(ref: str, disposition: str, *, rebuildable: bool = False):
    return ReferenceCandidateV1(
        ref=ref,
        requested_disposition=disposition,
        lifecycle_status="completed",
        rebuildable=rebuildable,
        evidence_refs=("process/evidence.json",),
    )


def test_archive_requires_orphan_or_explicit_redirect_proof(tmp_path: Path) -> None:
    (tmp_path / "history").mkdir()
    (tmp_path / "history/result.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "evidence.json").write_text("{}\n", encoding="utf-8")

    blocked = classify_reference_candidate(
        tmp_path,
        _candidate("history/result.json", "archive"),
        inbound_index={"history/result.json": ("phases/P1/PHASE.yaml",)},
    )
    allowed = classify_reference_candidate(
        tmp_path,
        ReferenceCandidateV1(
            ref="history/result.json",
            requested_disposition="archive",
            lifecycle_status="completed",
            rebuildable=False,
            evidence_refs=("process/evidence.json",),
            redirect_proven=True,
        ),
        inbound_index={"history/result.json": ("phases/P1/PHASE.yaml",)},
    )

    assert blocked["decision"] == "BLOCKED"
    assert "REFERENCE_ARCHIVE_NOT_ELIGIBLE" in blocked["blockers"]
    assert allowed["decision"] == "PASS"
    assert allowed["archive_eligible"] is True
    assert allowed["delete_eligible"] is False


def test_delete_requires_orphan_and_explicit_rebuildability(tmp_path: Path) -> None:
    (tmp_path / "derived").mkdir()
    (tmp_path / "derived/index.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "evidence.json").write_text("{}\n", encoding="utf-8")

    blocked = classify_reference_candidate(
        tmp_path,
        _candidate("derived/index.json", "delete"),
        inbound_index={},
    )
    allowed = classify_reference_candidate(
        tmp_path,
        _candidate("derived/index.json", "delete", rebuildable=True),
        inbound_index={},
    )

    assert blocked["decision"] == "BLOCKED"
    assert "REFERENCE_DELETE_NOT_ELIGIBLE" in blocked["blockers"]
    assert allowed["decision"] == "PASS"
    assert allowed["orphan"] is True
    assert allowed["delete_eligible"] is True


def test_canonical_truth_never_becomes_archive_or_delete_eligible(tmp_path: Path) -> None:
    (tmp_path / "PROJECT.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    (tmp_path / "evidence.json").write_text("{}\n", encoding="utf-8")

    result = classify_reference_candidate(
        tmp_path,
        _candidate("PROJECT.yaml", "archive"),
        inbound_index={},
    )

    assert result["decision"] == "BLOCKED"
    assert result["canonical_protected"] is True
    assert result["executable"] is False
    assert result["archive_eligible"] is False


def test_malformed_canonical_source_is_reported_instead_of_silently_skipped(
    tmp_path: Path,
) -> None:
    (tmp_path / "PROJECT.yaml").write_text("invalid\n", encoding="utf-8")
    findings: list[str] = []

    index = build_reference_index(tmp_path, findings=findings)

    assert index == {}
    assert findings == ["REFERENCE_SOURCE_PARSE_FAILED:PROJECT.yaml:ValueError"]


def test_missing_structured_reference_remains_visible_in_index(tmp_path: Path) -> None:
    (tmp_path / "PROJECT.yaml").write_text(
        "schema_version: 1\nroadmap_ref: ROADMAP.yaml\n",
        encoding="utf-8",
    )

    index = build_reference_index(tmp_path)

    assert index["ROADMAP.yaml"] == ("PROJECT.yaml",)


def test_candidate_rebuildable_requires_native_json_boolean(tmp_path: Path) -> None:
    policy = tmp_path / "policies"
    policy.mkdir()
    (policy / "REFERENCE-LIFECYCLE-CANDIDATES.json").write_text(
        '{"schema_version":1,"kind":"ReferenceLifecycleCandidatesV1",'
        '"candidates":[{"ref":"derived.json","requested_disposition":"delete",'
        '"lifecycle_status":"completed","rebuildable":"false",'
        '"evidence_refs":["process/evidence.json"]}]}\n',
        encoding="utf-8",
    )

    candidates, errors = _load_candidates(tmp_path)

    assert candidates == ()
    assert errors == ["reference candidate rebuildable must be a boolean"]
