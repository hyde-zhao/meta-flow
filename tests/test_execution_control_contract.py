from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from meta_flow.execution_control import (
    ActivationDecisionV1,
    AdmissionFactsV1,
    AdmissionPlanV1,
    ClosureAuditV1,
    ContainerBudgetV1,
    ExecutionUnitV1,
    FailureRouteV1,
    FindingIdentityV1,
    canonical_digest,
)

SHA = "a" * 64
OID = "b" * 40
FINGERPRINTS = {
    key: SHA
    for key in (
        "facts",
        "scope",
        "authorization",
        "contract",
        "consumer",
        "ownership",
        "slice",
        "test",
        "source",
        "profile",
    )
}


def _payloads() -> list[tuple[type[object], dict[str, object]]]:
    return [
        (
            ExecutionUnitV1,
            {
                "unit_id": "W-001",
                "root_concept": "execution-control",
                "slice_id": "S1",
                "container_role": "primary",
                "revision": 1,
                "supersedes_unit_id": "",
                "contract_ref": "process/contracts/execution-control-v1.json",
                "contract_digest": SHA,
            },
        ),
        (
            ContainerBudgetV1,
            {
                "primary_max": 1,
                "auxiliary_max": 0,
                "repair_max": 0,
                "concurrent_write_max": 1,
            },
        ),
        (
            FindingIdentityV1,
            {
                "root_concept": "execution-control",
                "slice_id": "S1",
                "check_group_id": "targeted",
                "canonical_finding_code": "CONTENT_FAILURE",
                "contract_revision": 1,
                "target_scope_digest": SHA,
            },
        ),
        (
            FailureRouteV1,
            {
                "classification_digest": SHA,
                "slice_route_digest": SHA,
                "attempt_plan_digest": SHA,
                "execution_action": "REWORK_CURRENT_SLICE",
                "occurrence": 1,
            },
        ),
        (
            ClosureAuditV1,
            {
                "audit_scope": "typed-cohort",
                "cohort_revision": 1,
                "dangling_container_count": 0,
                "dangling_dispatch_count": 0,
                "dangling_result_count": 0,
                "dangling_evidence_count": 0,
                "dangling_projection_count": 0,
                "dangling_receipt_count": 0,
                "grandfathered_legacy_count": 0,
                "grandfathered_legacy_refs": [],
                "fingerprints": FINGERPRINTS,
            },
        ),
        (
            AdmissionFactsV1,
            {
                "release_oid": OID,
                "process_oid": OID,
                "dirty_path_digest": SHA,
                "scope_digest": SHA,
                "authorization_digest": SHA,
                "profile_digest": SHA,
                "inventory_digest": SHA,
                "target_preimage_digest": SHA,
                "project_active_owner_digest": SHA,
            },
        ),
        (
            AdmissionPlanV1,
            {
                "decision": "READY",
                "facts_digest": SHA,
                "scope_digest": SHA,
                "candidate_digest": SHA,
                "conflicts": [],
                "planned_domain_mutation_count": 0,
                "coordination_required": True,
            },
        ),
        (
            ActivationDecisionV1,
            {
                "policy_revision": 1,
                "mode": "canonical",
                "cohort_revision": 1,
                "decision": "READY",
                "enforced": True,
                "grandfathered": False,
                "reason_codes": [],
                "invalidated_layers": [],
            },
        ),
    ]


@pytest.mark.parametrize(("contract_type", "payload"), _payloads())
def test_closed_contract_round_trip(
    contract_type: type[object],
    payload: dict[str, object],
) -> None:
    value = contract_type.from_mapping(payload)  # type: ignore[attr-defined]

    assert value.as_dict() == payload  # type: ignore[attr-defined]
    assert contract_type.from_mapping(value.as_dict()) == value  # type: ignore[attr-defined]
    with pytest.raises(FrozenInstanceError):
        setattr(value, next(iter(payload)), None)


@pytest.mark.parametrize(("contract_type", "payload"), _payloads())
def test_closed_contract_rejects_missing_and_extra_fields(
    contract_type: type[object],
    payload: dict[str, object],
) -> None:
    missing = dict(payload)
    missing.pop(next(iter(missing)))
    extra = {**payload, "unknown": True}

    with pytest.raises(ValueError, match="fields mismatch"):
        contract_type.from_mapping(missing)  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="fields mismatch"):
        contract_type.from_mapping(extra)  # type: ignore[attr-defined]


def test_execution_unit_enforces_work_identity_revision_and_safe_refs() -> None:
    payload = _payloads()[0][1]
    unit = ExecutionUnitV1.from_mapping(payload, work_id="W-001")
    assert unit.unit_id == "W-001"

    with pytest.raises(ValueError, match="unit_id must equal work_id"):
        ExecutionUnitV1.from_mapping(payload, work_id="W-002")
    with pytest.raises(ValueError, match="revision 1"):
        ExecutionUnitV1.from_mapping({**payload, "supersedes_unit_id": "W-000"})
    with pytest.raises(ValueError, match="supersedes_unit_id"):
        ExecutionUnitV1.from_mapping({**payload, "revision": 2})
    with pytest.raises(ValueError, match="safe relative ref"):
        ExecutionUnitV1.from_mapping({**payload, "contract_ref": "../escape.json"})


def test_policy_v1_budget_is_exact_and_negative_or_boolean_is_rejected() -> None:
    assert ContainerBudgetV1.policy_v1().as_dict() == {
        "primary_max": 1,
        "auxiliary_max": 0,
        "repair_max": 0,
        "concurrent_write_max": 1,
    }
    for field in ContainerBudgetV1.FIELDS:
        with pytest.raises(ValueError, match="non-negative integer"):
            ContainerBudgetV1.from_mapping(
                {**ContainerBudgetV1.policy_v1().as_dict(), field: -1}
            )
    with pytest.raises(ValueError, match="non-negative integer"):
        ContainerBudgetV1.from_mapping(
            {**ContainerBudgetV1.policy_v1().as_dict(), "primary_max": True}
        )


def test_finding_identity_excludes_caller_reset_fields_and_validates_digest() -> None:
    payload = _payloads()[2][1]
    identity = FindingIdentityV1.from_mapping(payload)

    assert "work_id" not in identity.as_dict()
    assert "thread_id" not in identity.as_dict()
    assert "root_cause_id" not in identity.as_dict()
    with pytest.raises(ValueError, match="fields mismatch"):
        FindingIdentityV1.from_mapping({**payload, "root_cause_id": "renamed"})
    with pytest.raises(ValueError, match="SHA-256"):
        FindingIdentityV1.from_mapping({**payload, "target_scope_digest": "bad"})


def test_failure_route_binds_digests_without_copying_canonical_outcomes() -> None:
    payload = _payloads()[3][1]
    assert FailureRouteV1.from_mapping(payload).occurrence == 1
    with pytest.raises(ValueError, match="third occurrence"):
        FailureRouteV1.from_mapping({**payload, "occurrence": 3})
    clarified = FailureRouteV1.from_mapping(
        {**payload, "occurrence": 3, "execution_action": "REQUIRE_DESIGN_CLARIFICATION"}
    )
    assert clarified.occurrence == 3


def test_closure_audit_separates_typed_cohort_from_legacy_limitations() -> None:
    payload = _payloads()[4][1]
    audit = ClosureAuditV1.from_mapping(payload)
    assert audit.cohort_pass
    assert audit.strict_project_pass

    dangling = ClosureAuditV1.from_mapping({**payload, "dangling_receipt_count": 1})
    assert not dangling.cohort_pass
    legacy = ClosureAuditV1.from_mapping(
        {
            **payload,
            "grandfathered_legacy_count": 1,
            "grandfathered_legacy_refs": ["process/archive/legacy.json"],
        }
    )
    assert legacy.cohort_pass
    assert not legacy.strict_project_pass
    with pytest.raises(ValueError, match="exact canonical fingerprint keys"):
        ClosureAuditV1.from_mapping({**payload, "fingerprints": {"source": SHA}})


def test_admission_plan_is_pure_zero_write_and_has_closed_conflict_truth_table() -> None:
    ready = _payloads()[6][1]
    assert not AdmissionPlanV1.from_mapping(ready).blocked
    blocked = AdmissionPlanV1.from_mapping(
        {**ready, "decision": "BLOCKED", "conflicts": ["DUPLICATE_ACTIVE_SLICE_OWNER"]}
    )
    assert blocked.blocked
    with pytest.raises(ValueError, match="zero planned domain mutations"):
        AdmissionPlanV1.from_mapping({**ready, "planned_domain_mutation_count": 1})
    with pytest.raises(ValueError, match="READY admission"):
        AdmissionPlanV1.from_mapping({**ready, "conflicts": ["CONFLICT"]})
    with pytest.raises(ValueError, match="BLOCKED admission"):
        AdmissionPlanV1.from_mapping({**ready, "decision": "BLOCKED"})


def test_activation_decision_prevents_canonical_or_mode_downgrade_contradictions() -> None:
    payload = _payloads()[7][1]
    assert ActivationDecisionV1.from_mapping(payload).mode == "canonical"
    with pytest.raises(ValueError, match="canonical activation"):
        ActivationDecisionV1.from_mapping({**payload, "enforced": False})
    with pytest.raises(ValueError, match="shadow activation"):
        ActivationDecisionV1.from_mapping({**payload, "mode": "shadow"})
    enforce_new = ActivationDecisionV1.from_mapping(
        {
            **payload,
            "mode": "enforce-new",
            "invalidated_layers": ["full", "targeted"],
            "reason_codes": ["RECEIPT_STALE"],
        }
    )
    assert enforce_new.invalidated_layers == ("full", "targeted")


def test_canonical_digest_is_key_order_independent_and_rejects_unknown_types() -> None:
    first = {"outer": {"b": 2, "a": 1}, "flag": True}
    second = {"flag": True, "outer": {"a": 1, "b": 2}}
    assert canonical_digest(first) == canonical_digest(second)
    assert len(canonical_digest(ContainerBudgetV1.policy_v1())) == 64
    for _ in range(1000):
        assert canonical_digest(first) == canonical_digest(second)
    with pytest.raises(ValueError, match="unsupported canonical value type"):
        canonical_digest({"bad": object()})


def test_contract_source_has_no_io_or_canonical_failure_status_literal_copy() -> None:
    source_path = Path("meta_flow/execution_control/contract.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert imported_roots.isdisjoint({"os", "subprocess", "socket", "urllib", "requests"})
    assert "CHECK_HARNESS_ERROR" not in source
    assert "DETERMINISTIC_SCHEMA_REPAIR" not in source
    assert "TERMINAL_SUCCESS_STATUSES" not in source
    assert "FAILURE_CLASSES" not in source
