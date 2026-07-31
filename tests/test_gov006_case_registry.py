from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

REGISTRY_PATH = Path(__file__).parent / "fixtures" / "gov006" / "CASE-REGISTRY.json"
EXPECTED_CATEGORY_COUNTS = {
    "LIF": (9, 18),
    "MAN": (8, 8),
    "OWN": (8, 8),
    "RUL": (7, 14),
    "FIX": (2, 6),
}
ITEM_FIELDS = {
    "category",
    "kind",
    "id",
    "contract_refs",
    "polarity",
    "entry",
    "expected_result",
    "owner_story",
}
BINDING_FIELDS = {"semantic_id", "execution_id", "embedded_ids"}


def _load_registry() -> dict[str, object]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _assert_registry(registry: dict[str, object]) -> None:
    assert set(registry) == {
        "schema_version",
        "expected_counts",
        "required_contract_refs",
        "semantics",
        "executions",
        "idempotency_assertions",
        "isolated_fixture_ids",
        "local_test_crosswalk",
    }
    assert registry["schema_version"] == 1
    expected_counts = registry["expected_counts"]
    assert expected_counts == {
        "semantic": 34,
        "execution": 54,
        "idempotency": 12,
        "isolated_fixture": 6,
    }

    semantics = registry["semantics"]
    executions = registry["executions"]
    idempotency = registry["idempotency_assertions"]
    isolated = registry["isolated_fixture_ids"]
    crosswalk = registry["local_test_crosswalk"]
    assert isinstance(semantics, list)
    assert isinstance(executions, list)
    assert isinstance(idempotency, list)
    assert isinstance(isolated, list)
    assert isinstance(crosswalk, list)
    assert (len(semantics), len(executions), len(idempotency), len(isolated)) == (
        34,
        54,
        12,
        6,
    )

    semantic_ids = {item["id"] for item in semantics}
    execution_ids = {item["id"] for item in executions}
    embedded_ids = {item["id"] for item in idempotency}
    assert len(semantic_ids) == 34
    assert len(execution_ids) == 54
    assert len(embedded_ids) == 12
    assert not (semantic_ids & execution_ids)
    assert not (semantic_ids & embedded_ids)
    assert not (execution_ids & embedded_ids)

    for item in semantics:
        assert set(item) == ITEM_FIELDS
        assert item["kind"] == "semantic"
        assert item["polarity"] in {"positive", "failure", "mixed"}
        assert item["contract_refs"]
        assert item["entry"] and item["expected_result"] and item["owner_story"]
    for item in executions:
        assert set(item) == ITEM_FIELDS | {"semantic_id"}
        assert item["kind"] == "execution"
        assert item["semantic_id"] in semantic_ids
        assert item["category"] == item["semantic_id"].split("-", 1)[0]
        assert item["polarity"] in {"positive", "failure", "mixed"}
        assert item["contract_refs"]
    for item in idempotency:
        assert set(item) == ITEM_FIELDS | {"semantic_id", "execution_id"}
        assert item["kind"] == "idempotency"
        assert item["semantic_id"] in semantic_ids
        assert item["execution_id"] in execution_ids
        parent = next(
            execution
            for execution in executions
            if execution["id"] == item["execution_id"]
        )
        assert parent["semantic_id"] == item["semantic_id"]

    for category, (semantic_count, execution_count) in EXPECTED_CATEGORY_COUNTS.items():
        assert sum(item["category"] == category for item in semantics) == semantic_count
        assert sum(item["category"] == category for item in executions) == execution_count
    assert set(isolated) <= execution_ids
    assert all(item.startswith("FIX-") for item in isolated)

    local_refs = [row["local_test_ref"] for row in crosswalk]
    assert len(local_refs) == len(set(local_refs))
    flattened_executions: list[str] = []
    flattened_embedded: list[str] = []
    for row in crosswalk:
        assert set(row) == {"local_test_ref", "bindings"}
        assert row["local_test_ref"]
        assert row["bindings"]
        for binding in row["bindings"]:
            assert set(binding) == BINDING_FIELDS
            assert binding["semantic_id"] in semantic_ids
            assert binding["execution_id"] in execution_ids
            assert isinstance(binding["embedded_ids"], list)
            execution = next(
                item for item in executions if item["id"] == binding["execution_id"]
            )
            assert execution["semantic_id"] == binding["semantic_id"]
            flattened_executions.append(binding["execution_id"])
            flattened_embedded.extend(binding["embedded_ids"])
    assert len(flattened_executions) == len(set(flattened_executions)) == 54
    assert set(flattened_executions) == execution_ids
    assert len(flattened_embedded) == len(set(flattened_embedded)) == 12
    assert set(flattened_embedded) == embedded_ids

    required_refs = set(registry["required_contract_refs"])
    positive_refs = {
        ref
        for item in executions
        if item["polarity"] in {"positive", "mixed"}
        for ref in item["contract_refs"]
    }
    failure_refs = {
        ref
        for item in executions
        if item["polarity"] in {"failure", "mixed"}
        for ref in item["contract_refs"]
    }
    assert required_refs <= positive_refs
    assert required_refs <= failure_refs

    forbidden_ids = {
        case_id
        for case_id in semantic_ids | execution_ids | embedded_ids
        if any(token in case_id for token in ("WINDOWS", "QODER", "OPENCLAW", "F1-F4"))
    }
    assert forbidden_ids == set()


def test_case_registry_exact_counts_and_crosswalk() -> None:
    _assert_registry(_load_registry())


@pytest.mark.parametrize(
    ("section", "index"),
    [
        ("semantics", 0),
        ("executions", 0),
        ("idempotency_assertions", 0),
    ],
)
def test_duplicate_ids_fail(section: str, index: int) -> None:
    registry = _load_registry()
    duplicate = deepcopy(registry[section][index])
    registry[section].append(duplicate)

    with pytest.raises(AssertionError):
        _assert_registry(registry)


def test_unregistered_crosswalk_reference_fails() -> None:
    registry = _load_registry()
    registry["local_test_crosswalk"][0]["bindings"][0]["execution_id"] = "LIF-99-A"

    with pytest.raises(AssertionError):
        _assert_registry(registry)


def test_multi_owner_and_orphan_execution_fail() -> None:
    registry = _load_registry()
    binding = deepcopy(registry["local_test_crosswalk"][0]["bindings"][0])
    registry["local_test_crosswalk"][1]["bindings"].append(binding)

    with pytest.raises(AssertionError):
        _assert_registry(registry)


def test_required_contract_needs_positive_and_failure_trace() -> None:
    registry = _load_registry()
    for execution in registry["executions"]:
        if execution["polarity"] in {"failure", "mixed"}:
            execution["contract_refs"] = [
                ref
                for ref in execution["contract_refs"]
                if ref != "FEAT-G06-07"
            ]

    with pytest.raises(AssertionError):
        _assert_registry(registry)
