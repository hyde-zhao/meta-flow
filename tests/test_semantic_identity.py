from __future__ import annotations

from hashlib import sha256

import pytest

from meta_flow.evidence.semantic_identity import (
    APPROVED_CANONICALIZER_SET_DIGEST,
    APPROVED_DIMENSIONS,
    APPROVED_TABLE_DIGEST,
    ConcreteEquivalenceTableV1,
    DimensionClassificationV1,
    EquivalenceDimensionV1,
    approved_table_bytes,
    build_semantic_identity,
    canonicalize_dimension,
    dimension_from_name,
    load_concrete_equivalence_table,
    load_embedded_concrete_equivalence_table,
)


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _value(dimension: str, salt: str = "a") -> dict[str, object]:
    d = _digest(salt)
    fields = {
        "source": {
            "repo_role": "release",
            "logical_refs_posix_byte_sorted": ["a", "b"],
            "content_digests": [d],
            "generated_input_lineage_digest": _digest("lineage"),
        },
        "profile": {
            "profile_schema_revision": "1",
            "required_layers_ordered": ["targeted", "full"],
            "risk_class": "high",
            "scope_digest": d,
            "policy_revision": "1",
        },
        "command": {
            "executable_identity_version": "uv-1",
            "subcommand": f"pytest-{salt}",
            "normalized_flags": ["-q", "--x"],
            "explicit_defaults": ["x=1"],
            "cwd_logical_role_scope": "release",
            "stdin_contract": "none",
        },
        "environment": {
            "platform": "linux",
            "architecture": "x64",
            "runtime_version": "3.11",
            "locale_timezone_semantics": "C/UTC",
            "declared_env_allowlist_value_digests": [d],
            "capability_digest": _digest("cap"),
            "isolation_permission_network_policy_digest": _digest("policy"),
        },
        "runner": {
            "runner_checker_canonical_id": "pytest",
            "implementation_digest": d,
            "invocation_schema": "v1",
            "selected_assertions": ["a", "b"],
            "failure_threshold": "0",
            "orchestration_policy_digest": _digest("policy"),
        },
        "evidence": {
            "required_evidence_schema": "v1",
            "validation_layers_ordered": ["targeted", "full"],
            "artifact_result_receipt_semantic_digests": [d],
            "scenario_fixture_coverage": "100",
            "sufficiency_decision": "sufficient",
        },
        "provenance": {
            "producer_revision_lineage": "v1",
            "resolution_graph_digest": d,
            "fixture_data_lineage": "fixture",
            "external_contract_digest": _digest("contract"),
        },
    }
    return fields[dimension]


@pytest.mark.parametrize("dimension", APPROVED_DIMENSIONS)
def test_each_approved_dimension_has_two_equivalent_directed_samples(
    dimension: str,
) -> None:
    first = canonicalize_dimension(dimension, _value(dimension))
    second = canonicalize_dimension(dimension, _value(dimension))
    assert first.classification is DimensionClassificationV1.EQUIVALENT
    assert first.digest == second.digest


@pytest.mark.parametrize("dimension", APPROVED_DIMENSIONS)
def test_each_dimension_counterexample_is_non_equivalent(dimension: str) -> None:
    assert canonicalize_dimension(dimension, _value(dimension)).digest != canonicalize_dimension(
        dimension, _value(dimension, "changed")
    ).digest


@pytest.mark.parametrize("dimension", APPROVED_DIMENSIONS)
def test_unknown_missing_or_extra_input_fails_closed(dimension: str) -> None:
    assert (
        canonicalize_dimension(dimension, {"unsupported": True}).classification
        is DimensionClassificationV1.UNKNOWN
    )
    assert (
        canonicalize_dimension(dimension, {}).classification
        is DimensionClassificationV1.UNKNOWN
    )
    extra = {**_value(dimension), "undeclared_environment": "secret"}
    assert (
        canonicalize_dimension(dimension, extra).classification
        is DimensionClassificationV1.UNKNOWN
    )


@pytest.mark.parametrize("name", ("check", "dependency", "runtime", "CHECK", "other"))
def test_rejected_dimensions_and_aliases_have_no_mapping(name: str) -> None:
    assert dimension_from_name(name) is None


def test_exact_table_literal_and_canonicalizer_set_are_the_only_loader_path() -> None:
    table = load_concrete_equivalence_table(
        table_ref="bundle-c/table",
        table_bytes=approved_table_bytes(),
        canonicalizer_set_digest=APPROVED_CANONICALIZER_SET_DIGEST,
    )
    assert table is not None and table.is_approved()
    assert table.table_digest == APPROVED_TABLE_DIGEST
    assert tuple(item.value for item in EquivalenceDimensionV1) == APPROVED_DIMENSIONS
    assert (
        load_concrete_equivalence_table(
            table_ref="bundle-c/table",
            table_bytes=approved_table_bytes() + b" ",
            canonicalizer_set_digest=APPROVED_CANONICALIZER_SET_DIGEST,
        )
        is None
    )
    assert (
        load_concrete_equivalence_table(
            table_ref="bundle-c/table",
            table_bytes=approved_table_bytes(),
            canonicalizer_set_digest=_digest("alternate"),
        )
        is None
    )


def test_direct_table_construction_cannot_bypass_verified_loader() -> None:
    with pytest.raises(TypeError, match="verified loader"):
        ConcreteEquivalenceTableV1(
            "forged", APPROVED_TABLE_DIGEST, APPROVED_CANONICALIZER_SET_DIGEST
        )


def test_safe_order_drift_and_oid_audit_only_relations() -> None:
    table = load_embedded_concrete_equivalence_table()
    values = {dimension: _value(dimension) for dimension in APPROVED_DIMENSIONS}
    values["source"]["logical_refs_posix_byte_sorted"] = ["b", "a"]
    graph = _digest("graph")
    evidence = _digest("evidence")
    first = build_semantic_identity(
        table=table,
        values=values,
        receipt_evidence_digest=evidence,
        decision_graph_digest=graph,
        oid="old",
    )
    values["source"]["logical_refs_posix_byte_sorted"] = ["a", "b"]
    second = build_semantic_identity(
        table=table,
        values=values,
        receipt_evidence_digest=evidence,
        decision_graph_digest=graph,
        oid="new",
    )
    assert first.complete and second.complete
    assert first.dimensions[0].digest == second.dimensions[0].digest
    assert first.oid != second.oid
