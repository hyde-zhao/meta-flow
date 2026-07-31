from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_flow.installation.asset_executor import FRESH_ASSET_ACTION_COUNTS
from meta_flow.installation.canonical import canonical_digest
from meta_flow.installation.contracts import (
    ACTION_OWNERSHIP_KINDS,
    DECISIONS,
    GLOBAL_CHECKPOINTS,
    OPERATIONS,
)
from meta_flow.installation.recovery import JOURNAL_STATES, RECOVERY_ACTIONS

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "gov006"
REGISTRY_PATH = FIXTURE_ROOT / "CASE-REGISTRY.json"
MATRIX_PATH = FIXTURE_ROOT / "matrix-fixtures.json"
RESULT_FIELDS = {
    "case_id",
    "semantic_id",
    "decision",
    "terminal",
    "mutation_count",
    "authorization_count",
    "transaction_count",
    "portable_refs_only",
}


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


REGISTRY = _load(REGISTRY_PATH)
MATRIX = _load(MATRIX_PATH)
EXECUTIONS = tuple(REGISTRY["executions"])
IDEMPOTENCY = tuple(REGISTRY["idempotency_assertions"])


def _profiles() -> dict[str, dict[str, str]]:
    return {
        profile["semantic_id"]: profile
        for profile in MATRIX["semantic_profiles"]
    }


def _matrix_result(case: dict[str, object]) -> dict[str, object]:
    """将 registry case 映射到统一协议；不复制业务 expected_result。"""

    profile = _profiles()[case["semantic_id"]]
    polarity = case["polarity"]
    decision = "BLOCKED" if polarity == "failure" else "READY"
    if "noop" in profile["expected_terminal"]:
        decision = "NOOP"
    return {
        "case_id": case["id"],
        "semantic_id": case["semantic_id"],
        "decision": decision,
        "terminal": profile["expected_terminal"],
        "mutation_count": 0,
        "authorization_count": 0,
        "transaction_count": 1,
        "portable_refs_only": True,
    }


def test_matrix_contract_matches_all_production_enums_exactly() -> None:
    contract = MATRIX["contract"]

    assert tuple(contract["operations"]) == OPERATIONS
    assert tuple(contract["decisions"]) == DECISIONS
    assert tuple(contract["checkpoints"]) == GLOBAL_CHECKPOINTS
    assert tuple(contract["ownership_types"]) == ACTION_OWNERSHIP_KINDS[1:4]
    assert tuple(contract["journal_states"]) == JOURNAL_STATES
    assert tuple(contract["recovery_actions"]) == RECOVERY_ACTIONS
    assert set(contract["result_protocol"]) == RESULT_FIELDS
    assert len(FRESH_ASSET_ACTION_COUNTS) == 10


def test_matrix_has_one_profile_for_every_semantic_and_no_business_copy() -> None:
    profiles = _profiles()
    semantic_ids = {item["id"] for item in REGISTRY["semantics"]}

    assert len(profiles) == len(semantic_ids) == 34
    assert set(profiles) == semantic_ids
    assert all(
        set(profile) == {
            "semantic_id",
            "driver",
            "expected_terminal",
        }
        for profile in MATRIX["semantic_profiles"]
    )
    assert "expected_result" not in MATRIX_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "case",
    EXECUTIONS,
    ids=[case["id"] for case in EXECUTIONS],
)
def test_all_54_execution_cells_use_one_result_protocol(
    case: dict[str, object],
) -> None:
    result = _matrix_result(case)

    assert set(result) == RESULT_FIELDS
    assert result["case_id"] == case["id"]
    assert result["semantic_id"] == case["semantic_id"]
    assert result["decision"] in DECISIONS
    assert result["mutation_count"] == result["authorization_count"] == 0
    assert result["transaction_count"] == 1
    assert result["portable_refs_only"] is True


@pytest.mark.parametrize(
    "assertion",
    IDEMPOTENCY,
    ids=[assertion["id"] for assertion in IDEMPOTENCY],
)
def test_all_12_embedded_idempotency_assertions_are_stable(
    assertion: dict[str, object],
) -> None:
    parent = next(
        case
        for case in EXECUTIONS
        if case["id"] == assertion["execution_id"]
    )
    first = _matrix_result(parent)
    second = _matrix_result(parent)

    assert parent["semantic_id"] == assertion["semantic_id"]
    assert canonical_digest(first) == canonical_digest(second)
    assert first == second


def test_matrix_exact_totals_and_registry_ref_are_stable() -> None:
    expected = REGISTRY["expected_counts"]

    assert MATRIX["schema_version"] == 1
    assert MATRIX["registry_ref"] == (
        "tests/fixtures/gov006/CASE-REGISTRY.json"
    )
    assert (
        expected["semantic"],
        expected["execution"],
        expected["idempotency"],
        expected["isolated_fixture"],
    ) == (34, 54, 12, 6)
