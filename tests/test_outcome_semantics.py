from __future__ import annotations

import copy
from pathlib import Path

import pytest

from meta_flow.semantics import outcome


def test_contract_keeps_five_families_and_overlapping_literals_typed() -> None:
    contract = outcome.semantic_contract_payload()

    assert set(contract["families"]) == {
        "authorization",
        "execution",
        "lifecycle",
        "verification",
        "release",
    }
    assert "BLOCKED" in contract["families"]["execution"]["decisions"]
    assert "BLOCKED" in contract["families"]["verification"]["cp7_decisions"]
    assert "blocked" in contract["families"]["lifecycle"]["lifecycle_statuses"]
    assert "CHECK_HARNESS_ERROR" not in contract["families"]["verification"][
        "cp7_decisions"
    ]
    assert "CHECK_HARNESS_ERROR" in contract["orthogonal_failure_classes"]


@pytest.mark.parametrize(
    ("status", "decision"),
    [
        ("APPLIED", "PASS"),
        ("RECOVERED", "PASS"),
        ("NO_CHANGE", "PASS"),
        ("BLOCKED", "BLOCKED"),
        ("PARTIAL", "PARTIAL"),
    ],
)
def test_authority_status_mapping_is_explicit(status: str, decision: str) -> None:
    assert outcome.authority_apply_decision(status) == decision


def test_unknown_authority_status_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown authority issue status"):
        outcome.authority_apply_decision("PASS")


def test_verification_decisions_have_distinct_transition_dispositions() -> None:
    assert (
        outcome.classify_verification_decision("PASS")
        is outcome.VerificationDisposition.PASS_LIKE
    )
    assert (
        outcome.classify_verification_decision("BLOCKED")
        is outcome.VerificationDisposition.FAILURE
    )
    assert (
        outcome.classify_verification_decision("N/A")
        is outcome.VerificationDisposition.NOT_APPLICABLE
    )
    assert (
        outcome.classify_verification_decision("CHECK_HARNESS_ERROR")
        is outcome.VerificationDisposition.UNKNOWN
    )


def test_transition_mapping_preserves_decision_specific_stop_reasons() -> None:
    assert outcome.transition_stop_reasons("NEEDS_REWORK", "failure") == {
        "needs_rework"
    }
    assert outcome.transition_stop_reasons("PASS", "required_human_gate") == {
        "required_human_gate",
        "authorization_required",
        "workflow_health_threshold",
    }
    assert outcome.transition_stop_reasons("UNKNOWN", "delivered") == frozenset()


def test_repository_disposes_all_66_d7_candidates_exactly_once() -> None:
    report = outcome.validate_candidate_dispositions(Path(__file__).parents[1])

    assert report["decision"] == "PASS"
    assert report["candidate_count"] == 66
    assert report["disposed_count"] == 66
    assert sum(report["disposition_counts"].values()) == 66
    assert set(report["disposition_counts"]) == outcome.OUTCOME_DISPOSITION_IDS
    assert report["source_result_digest"] == outcome.OUTCOME_CANDIDATE_SOURCE_DIGEST
    assert len(report["disposition_digest"]) == 64


def test_candidate_disposition_missing_entry_fails_closed(monkeypatch) -> None:
    original_loader = outcome.load_yaml_object

    def mutated_loader(path: Path) -> dict:
        payload = original_loader(path)
        if path.name == outcome.OUTCOME_CANDIDATE_DISPOSITIONS_REL.name:
            payload = copy.deepcopy(payload)
            payload["candidates"].pop()
        return payload

    monkeypatch.setattr(outcome, "load_yaml_object", mutated_loader)

    report = outcome.validate_candidate_dispositions(Path(__file__).parents[1])

    assert report["decision"] == "BLOCKED"
    assert any("missing disposition" in error for error in report["errors"])
