from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from meta_flow.checks.frozen_cp6_evidence import (
    FrozenCp6EvidenceError,
    FrozenCp6EvidenceV2,
    build_cp6_evidence_v2,
    compare_frozen_evidence,
    freeze_cp6_evidence,
    project_story_admission,
)
from meta_flow.semantics import receipt
from meta_flow.workflow import story_evidence


def _root() -> Path:
    return Path(__file__).parents[1]


def _build_v2() -> FrozenCp6EvidenceV2:
    return build_cp6_evidence_v2(
        _root(),
        story_id="STORY-R8-S01",
        release_oid="1" * 40,
        process_oid="2" * 40,
        scope_digest="3" * 64,
        implementation_digest="4" * 64,
        dependency_digests={"STORY-R7-S01:contract": "5" * 64},
        cp6_result_ref="process/checks/CP6-STORY-R8-S01.result.json",
    )


def test_compiler_is_deterministic_and_validator_recomputes_current_source() -> None:
    first = receipt.compile_semantic_contract(_root())
    second = receipt.compile_semantic_contract(_root())

    assert first.as_dict() == second.as_dict()
    assert first.contract_digest == second.contract_digest
    assert receipt.validate_semantic_contract_digest(
        _root(), first.contract_digest
    ) == {
        "decision": "READY",
        "reason_codes": ["SEMANTIC_CONTRACT_DIGEST_RECONFIRMED"],
        "current_contract_digest": first.contract_digest,
    }


def test_contract_digest_invalidates_owner_preregistration_and_outcome_mutants() -> None:
    current = receipt.compile_semantic_contract(_root())
    components = current.as_dict()
    mutants: list[dict] = []

    owner_mutant = copy.deepcopy(components)
    owner_mutant["ownership"]["source_fingerprint"] = "0" * 64
    mutants.append(owner_mutant)

    preregistration_mutant = copy.deepcopy(components)
    preregistration_mutant["preregistration"][
        "full_lld_required_trigger"
    ] = "changed_trigger"
    mutants.append(preregistration_mutant)

    outcome_mutant = copy.deepcopy(components)
    outcome_mutant["outcome"]["mappings"][
        "authority_apply_status_to_execution_decision"
    ]["BLOCKED"] = "PASS"
    mutants.append(outcome_mutant)

    receipt_mutant = copy.deepcopy(components)
    receipt_mutant["receipt_binding"]["validator"] = "trust-caller-digest"
    mutants.append(receipt_mutant)

    for mutant in mutants:
        compiled = receipt.compile_contract_from_components(
            ownership_contract=mutant["ownership"],
            preregistration_contract=mutant["preregistration"],
            outcome_contract=mutant["outcome"],
            receipt_binding_contract=mutant["receipt_binding"],
        )
        assert compiled.contract_digest != current.contract_digest


def test_v2_is_closed_and_ready_only_after_validator_recomputation() -> None:
    frozen = _build_v2()
    reparsed = freeze_cp6_evidence(**frozen.as_dict())

    assert isinstance(reparsed, FrozenCp6EvidenceV2)
    assert reparsed.evidence_digest == frozen.evidence_digest
    assert project_story_admission(
        reparsed,
        expected_dependency_digests={"STORY-R7-S01:contract": "5" * 64},
        project_root=_root(),
    )["decision"] == "READY"
    without_recompute = project_story_admission(
        reparsed,
        expected_dependency_digests={"STORY-R7-S01:contract": "5" * 64},
    )
    assert without_recompute["decision"] == "BLOCKED"
    assert without_recompute["reason_codes"] == [
        "SEMANTIC_CONTRACT_RECOMPUTE_REQUIRED"
    ]


def test_stale_v2_propagates_revalidation_through_validator_and_compare() -> None:
    current = _build_v2()
    stale_payload = current.as_dict()
    stale_payload["contract_digest"] = "0" * 64
    stale = freeze_cp6_evidence(**stale_payload)

    admission = project_story_admission(
        stale,
        expected_dependency_digests={"STORY-R7-S01:contract": "5" * 64},
        project_root=_root(),
    )
    assert admission["decision"] == "revalidation-required"
    assert admission["reason_codes"] == ["SEMANTIC_CONTRACT_DIGEST_CHANGED"]
    comparison = compare_frozen_evidence(stale, current)
    assert comparison["decision"] == "revalidation-required"
    assert comparison["contract_changed"] is True
    assert comparison["reason_codes"] == ["SEMANTIC_CONTRACT_DIGEST_CHANGED"]


def test_v2_rejects_unknown_fields_bad_digest_and_unknown_schema() -> None:
    payload = _build_v2().as_dict()
    with pytest.raises(FrozenCp6EvidenceError, match="fields mismatch"):
        freeze_cp6_evidence(**(payload | {"unknown": True}))
    with pytest.raises(FrozenCp6EvidenceError, match="contract_digest"):
        freeze_cp6_evidence(**(payload | {"contract_digest": "bad"}))
    with pytest.raises(FrozenCp6EvidenceError, match="unknown FrozenCp6Evidence"):
        freeze_cp6_evidence(**(payload | {"schema_version": 3}))
    with pytest.raises(FrozenCp6EvidenceError, match="field types"):
        freeze_cp6_evidence(**(payload | {"story_id": 7}))
    with pytest.raises(FrozenCp6EvidenceError, match="process logical ref"):
        freeze_cp6_evidence(
            **(payload | {"cp6_result_ref": "process/checks/../escape.json"})
        )


def test_validator_rejects_malformed_digest_before_source_comparison() -> None:
    assert receipt.validate_semantic_contract_digest(_root(), "g" * 64) == {
        "decision": "BLOCKED",
        "reason_codes": ["SEMANTIC_CONTRACT_DIGEST_INVALID"],
        "current_contract_digest": "",
    }


def test_v1_is_read_only_compatibility_and_never_returns_ready() -> None:
    v1 = {
        "schema_version": 1,
        "story_id": "STORY-LEGACY",
        "release_oid": "1" * 40,
        "process_oid": "2" * 40,
        "scope_digest": "3" * 64,
        "implementation_digest": "4" * 64,
        "dependency_digests": {"upstream": "5" * 64},
        "cp6_result_ref": "process/checks/CP6-STORY-LEGACY.result.json",
    }

    admission = project_story_admission(
        v1,
        expected_dependency_digests={"upstream": "5" * 64},
        project_root=_root(),
    )
    comparison = compare_frozen_evidence(v1, v1)

    assert admission["decision"] == "revalidation-required"
    assert admission["reason_codes"] == ["SEMANTIC_CONTRACT_BINDING_MISSING"]
    assert comparison["decision"] == "revalidation-required"
    assert comparison["reason_codes"] == ["SEMANTIC_CONTRACT_BINDING_MISSING"]


def test_production_builder_derives_identity_from_recorded_cp6_pass() -> None:
    frozen = story_evidence.build_cp6_semantic_evidence_v2(
        _root(),
        result_path=Path(
            "process/checks/CP6-STORY-CR061-S02.result.json"
        ),
        release_oid="1" * 40,
        process_oid="2" * 40,
        scope_digest="3" * 64,
        implementation_digest="4" * 64,
        dependency_digests={"upstream": "5" * 64},
    )

    assert frozen.story_id == "STORY-CR061-S02"
    assert frozen.cp6_result_ref == (
        "process/checks/CP6-STORY-CR061-S02.result.json"
    )
    assert frozen.contract_digest == receipt.compile_semantic_contract(
        _root()
    ).contract_digest


def test_project_cp6_public_operation_can_emit_contract_bound_v2(capsys) -> None:
    exit_code = story_evidence.main(
        [
            "project-cp6",
            "--project-root",
            str(_root()),
            "--result",
            "process/checks/CP6-STORY-CR061-S02.result.json",
            "--freeze-semantic-evidence",
            "--release-oid",
            "1" * 40,
            "--process-oid",
            "2" * 40,
            "--scope-digest",
            "3" * 64,
            "--implementation-digest",
            "4" * 64,
            "--dependency-digest",
            "upstream=" + "5" * 64,
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["frozen_evidence"]["schema_version"] == 2
    assert output["frozen_evidence"]["story_id"] == "STORY-CR061-S02"
    assert output["projection_plan"]["operation"] == "story.project-cp6"
