from __future__ import annotations

import json
from pathlib import Path

from meta_flow.semantics import ownership


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    owner_path = root / "meta_flow/semantics/ownership.py"
    owner_path.parent.mkdir(parents=True)
    owner_path.write_text("\"\"\"fixture owner\"\"\"\n", encoding="utf-8")
    (root / "meta_flow/semantics/__init__.py").write_text(
        "SEMANTIC_OWNER_MANIFEST = "
        "{'governance-ownership-v1': 'meta_flow.semantics.ownership'}\n",
        encoding="utf-8",
    )
    guardrail_path = root / "scripts/check_delivery_guardrails.py"
    guardrail_path.parent.mkdir(parents=True)
    guardrail_path.write_text(
        "from meta_flow.semantics.ownership import validate_ownership\n"
        "ROOT = None\n"
        "def collect_governance_ownership_errors():\n"
        "    return validate_ownership(ROOT)\n",
        encoding="utf-8",
    )
    cli_path = root / "meta_flow/cli.py"
    cli_path.write_text(
        "def route(validator, forwarded):\n"
        "    if validator == \"governance-ownership\":\n"
        "        from meta_flow.semantics import ownership\n"
        "        return ownership.main(forwarded)\n",
        encoding="utf-8",
    )
    concept_payload = {
        "schema_version": 2,
        "kind": "GovernanceConceptOwnersV2",
        "universe": {
            "freeze_id": "fixture-r5-v1",
            "canonical_concept_ids": ["governance-ownership"],
            "expansion_policy": "explicit-revision-only",
        },
        "detector_profile": {
            "profile_id": "fixture-source-bounded-v1",
            "qualification": "product-full-baseline-plus-incremental-hard-gate-v2",
            "source_types": list(ownership.DETECTOR_SOURCE_TYPES),
            "ast_roots": ["meta_flow"],
            "known_blind_spots": ["dynamic imports are outside this fixture"],
        },
        "concept_owners": {
            "governance-ownership": {
                "owner": "meta_flow.semantics.ownership",
                "source_of_truth_boundary": (
                    "process/policies/SOURCE-OF-TRUTH-MAP.yaml"
                    "#objects.governance_ownership"
                ),
                "conformance_checker": "meta-flow check governance-ownership",
                "conflict_keys": ["concept-owner"],
                "legacy_aliases": [],
                "forbidden_aliases": [],
            }
        },
        "consumer_mappings": [
            {
                "consumer_id": "registry:CAP-FIXTURE-OWNERSHIP",
                "kind": "registry",
                "ref": (
                    "process/docs/design/CAPABILITY-REGISTRY.yaml"
                    "#capabilities[CAP-FIXTURE-OWNERSHIP]"
                ),
                "concept_id": "governance-ownership",
                "conformance_check": "capability-concept-ref",
            },
            {
                "consumer_id": "ast-import-call:meta_flow/cli.py",
                "kind": "ast-import-call",
                "ref": "meta_flow/cli.py",
                "concept_id": "governance-ownership",
                "conformance_check": "static-owner-import",
            },
            {
                "consumer_id": (
                    "cli-public-operation:meta-flow-check-governance-ownership"
                ),
                "kind": "cli-public-operation",
                "ref": "meta-flow check governance-ownership",
                "concept_id": "governance-ownership",
                "conformance_check": "cli-route-contract",
            },
            {
                "consumer_id": "explicit-boundary-ref:governance_ownership",
                "kind": "explicit-boundary-ref",
                "ref": (
                    "process/policies/SOURCE-OF-TRUTH-MAP.yaml"
                    "#objects.governance_ownership"
                ),
                "concept_id": "governance-ownership",
                "conformance_check": "source-boundary-owner-match",
            },
        ],
    }
    _write_json(root / ownership.CONCEPT_OWNERS_REL, concept_payload)
    _write_json(
        root / ownership.SOURCE_OF_TRUTH_REL,
        {
            "schema_version": 2,
            "objects": {
                "governance_ownership": {
                    "path": "process/docs/design/CONCEPT-OWNERS.yaml",
                    "truth_role": "machine_truth",
                    "edit_policy": "manual-edit",
                    "machine_truth": True,
                    "canonical_concept_id": "governance-ownership",
                    "owner": "meta_flow.semantics.ownership",
                }
            },
        },
    )
    _write_json(
        root / ownership.FEATURE_REGISTRY_REL,
        {
            "schema_version": 1,
            "features": [{"feature_id": "FEAT-FIXTURE-OWNERSHIP"}],
        },
    )
    _write_json(
        root / ownership.CAPABILITY_REGISTRY_REL,
        {
            "schema_version": 1,
            "capabilities": [
                {
                    "id": "CAP-FIXTURE-OWNERSHIP",
                    "feature_refs": ["FEAT-FIXTURE-OWNERSHIP"],
                    "concept_refs": ["governance-ownership"],
                }
            ],
        },
    )
    return root


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_valid_profile_recomputes_exact_owner_and_consumer_coverage(
    tmp_path: Path,
) -> None:
    root = _fixture(tmp_path)

    report = ownership.validate_ownership(root)

    assert report["decision"] == "PASS"
    assert report["concept_coverage"] == {
        "discovered": 1,
        "owned": 1,
        "multi_owner": 0,
        "unowned": 0,
        "unknown": 0,
        "percent": 100.0,
    }
    assert report["consumer_coverage"]["discovered"] == 4
    assert report["consumer_coverage"]["mapped"] == 4
    assert report["consumer_coverage"]["percent"] == 100.0
    assert len(report["source_fingerprint"]) == 64


def test_unmapped_ast_consumer_fails_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    rogue = root / "meta_flow/rogue.py"
    rogue.write_text(
        "from meta_flow.semantics import ownership\n",
        encoding="utf-8",
    )

    report = ownership.validate_ownership(root)

    assert report["decision"] == "BLOCKED"
    assert any("ast-import-call:meta_flow/rogue.py" in error for error in report["errors"])
    assert any("owner import is not consumed" in error for error in report["errors"])


def test_unknown_registry_concept_fails_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    path = root / ownership.CAPABILITY_REGISTRY_REL
    payload = _load(path)
    payload["capabilities"][0]["concept_refs"] = ["unknown-concept"]
    _write_json(path, payload)

    report = ownership.validate_ownership(root)

    assert report["decision"] == "BLOCKED"
    assert any("concept_refs contain unknown IDs" in error for error in report["errors"])
    assert any("consumer mapping concept mismatch" in error for error in report["errors"])
    assert report["concept_coverage"]["unknown"] == 1
    assert report["consumer_coverage"]["unknown"] == [
        "registry:CAP-FIXTURE-OWNERSHIP"
    ]


def test_source_boundary_owner_drift_fails_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    path = root / ownership.SOURCE_OF_TRUTH_REL
    payload = _load(path)
    payload["objects"]["governance_ownership"]["owner"] = "meta_flow.rogue"
    _write_json(path, payload)

    report = ownership.validate_ownership(root)

    assert report["decision"] == "BLOCKED"
    assert any("source-of-truth boundary owner mismatch" in error for error in report["errors"])


def test_source_fingerprint_binds_every_registered_owner_module(
    tmp_path: Path,
) -> None:
    root = _fixture(tmp_path)
    second_owner = root / "meta_flow/semantics/preregistration.py"
    second_owner.write_text('"""second fixture owner"""\n', encoding="utf-8")
    consumer = root / "meta_flow/consumer.py"
    consumer.write_text(
        "from meta_flow.semantics import preregistration\n"
        "CONTRACT = preregistration.semantic_contract_payload()\n",
        encoding="utf-8",
    )
    concept_path = root / ownership.CONCEPT_OWNERS_REL
    concepts = _load(concept_path)
    concepts["universe"]["canonical_concept_ids"].append(
        "preregistration-semantics"
    )
    concepts["concept_owners"]["preregistration-semantics"] = {
        "owner": "meta_flow.semantics.preregistration",
        "source_of_truth_boundary": (
            "process/policies/SOURCE-OF-TRUTH-MAP.yaml"
            "#objects.preregistration_semantics"
        ),
        "conformance_checker": "meta-flow check governance-ownership",
        "conflict_keys": ["consumer-requirement"],
        "legacy_aliases": [],
        "forbidden_aliases": [],
    }
    concepts["consumer_mappings"].extend(
        [
            {
                "consumer_id": "registry:CAP-FIXTURE-PREREGISTRATION",
                "kind": "registry",
                "ref": (
                    "process/docs/design/CAPABILITY-REGISTRY.yaml"
                    "#capabilities[CAP-FIXTURE-PREREGISTRATION]"
                ),
                "concept_id": "preregistration-semantics",
                "conformance_check": "capability-concept-ref",
            },
            {
                "consumer_id": "ast-import-call:meta_flow/consumer.py",
                "kind": "ast-import-call",
                "ref": "meta_flow/consumer.py",
                "concept_id": "preregistration-semantics",
                "conformance_check": "static-owner-import",
            },
            {
                "consumer_id": (
                    "explicit-boundary-ref:preregistration_semantics"
                ),
                "kind": "explicit-boundary-ref",
                "ref": (
                    "process/policies/SOURCE-OF-TRUTH-MAP.yaml"
                    "#objects.preregistration_semantics"
                ),
                "concept_id": "preregistration-semantics",
                "conformance_check": "source-boundary-owner-match",
            },
        ]
    )
    _write_json(concept_path, concepts)
    truth_path = root / ownership.SOURCE_OF_TRUTH_REL
    truth = _load(truth_path)
    truth["objects"]["preregistration_semantics"] = {
        "path": "meta_flow/semantics/preregistration.py",
        "truth_role": "machine_truth",
        "edit_policy": "manual-edit",
        "machine_truth": True,
        "canonical_concept_id": "preregistration-semantics",
        "owner": "meta_flow.semantics.preregistration",
    }
    _write_json(truth_path, truth)
    capability_path = root / ownership.CAPABILITY_REGISTRY_REL
    capabilities = _load(capability_path)
    capabilities["capabilities"].append(
        {
            "id": "CAP-FIXTURE-PREREGISTRATION",
            "feature_refs": ["FEAT-FIXTURE-OWNERSHIP"],
            "concept_refs": ["preregistration-semantics"],
        }
    )
    _write_json(capability_path, capabilities)
    before = ownership.validate_ownership(root)

    second_owner.write_text('"""mutated second fixture owner"""\n', encoding="utf-8")
    after = ownership.validate_ownership(root)

    assert before["decision"] == "PASS"
    assert after["decision"] == "PASS"
    assert before["source_fingerprint"] != after["source_fingerprint"]


def test_duplicate_consumer_mapping_fails_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    path = root / ownership.CONCEPT_OWNERS_REL
    payload = _load(path)
    payload["consumer_mappings"].append(dict(payload["consumer_mappings"][0]))
    _write_json(path, payload)

    report = ownership.validate_ownership(root)

    assert report["decision"] == "BLOCKED"
    assert any("duplicate IDs" in error for error in report["errors"])


def test_repository_profile_is_the_r5_source_bounded_gate() -> None:
    root = Path(__file__).parents[1]

    report = ownership.validate_ownership(root)

    assert report["decision"] == "PASS"
    assert report["concept_coverage"]["discovered"] == 9
    assert report["consumer_coverage"]["discovered"] == 49
    assert report["outcome_candidate_dispositions"]["candidate_count"] == 66
    assert report["outcome_candidate_dispositions"]["disposed_count"] == 66
    assert report["detector"]["source_types"] == list(
        ownership.DETECTOR_SOURCE_TYPES
    )
