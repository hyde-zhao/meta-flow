from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cr074.formal_truth.test_status_sync_partition import _enable_registered_legacy
from test_cr_status_sync import write_termination_fixture
from test_route_aware_handoff import _work
from test_work_lifecycle_transaction import _close_phase_work, _governance_fixture

from meta_flow.checks import cr_tracking
from meta_flow.project.governance_projection import GOVERNANCE_PROJECTION_REL
from meta_flow.work.lifecycle_transaction import (
    SharedProjectionRepairAuthorizationV1,
    apply_shared_projection_repair,
    inspect_shared_projection_repair,
    plan_shared_projection_repair,
)
from meta_flow.workflow import cr_analysis, cr_index, cr_status_sync
from meta_flow.workflow.legacy_evidence_registry import load_formal_cr_partition

VICTIM_REPLAY_STATUS = "PENDING_AUTHORIZATION"
FIXTURE_EVIDENCE_SCOPE = "META_FLOW_SHARED_FIXTURE_ONLY"


@dataclass(frozen=True, slots=True)
class JourneyFixtureContractV1:
    contract_id: str
    journey: str
    scenario: str
    evidence_test: str
    expected_decision: str


@dataclass(frozen=True, slots=True)
class RoundJourneyCoverageRowV1:
    round_id: str
    journey: str
    scenario: str
    evidence_test: str
    expected_decision: str
    fixture_contract_id: str
    evidence_scope: str = FIXTURE_EVIDENCE_SCOPE
    victim_replay_status: str = VICTIM_REPLAY_STATUS


JOURNEY_FIXTURE_CONTRACTS = {
    contract.journey: contract
    for contract in (
        JourneyFixtureContractV1(
            contract_id="CR074-J1-PARTITION-V1",
            journey="J1",
            scenario="registered-legacy-and-native-consumers-share-partition",
            evidence_test="test_j1_registered_legacy_and_native_consumers_share_partition",
            expected_decision="PASS",
        ),
        JourneyFixtureContractV1(
            contract_id="CR074-J2-SUCCESSOR-REPAIR-V1",
            journey="J2",
            scenario="repairable-stale-lineage-accepts-typed-successor",
            evidence_test="test_j2_only_repairable_stale_lineage_accepts_typed_successor",
            expected_decision="PASS",
        ),
        JourneyFixtureContractV1(
            contract_id="CR074-J3-ROUTE-AWARE-HANDOFF-V1",
            journey="J3",
            scenario="route-profile-selects-handoff-policy",
            evidence_test="test_j3_route_profile_selects_handoff_policy",
            expected_decision="NOT_REQUIRED+REQUIRED",
        ),
    )
}


def _coverage_row(round_id: str, journey: str) -> RoundJourneyCoverageRowV1:
    """六轮只引用三个共享 fixture 合同，不复制事故 fixture。"""

    contract = JOURNEY_FIXTURE_CONTRACTS[journey]
    return RoundJourneyCoverageRowV1(
        round_id=round_id,
        journey=journey,
        scenario=contract.scenario,
        evidence_test=contract.evidence_test,
        expected_decision=contract.expected_decision,
        fixture_contract_id=contract.contract_id,
    )


SIX_ROUND_TO_JOURNEYS = (
    _coverage_row("R1", "J1"),
    _coverage_row("R1_recovery", "J1"),
    _coverage_row("R1_recovery", "J2"),
    _coverage_row("R2_admission", "J1"),
    _coverage_row("R2_admission", "J2"),
    _coverage_row("R2_failure", "J2"),
    _coverage_row("W1", "J3"),
    _coverage_row("R3", "J1"),
    _coverage_row("R3", "J2"),
    _coverage_row("R3", "J3"),
)


def test_j1_registered_legacy_and_native_consumers_share_partition(
    tmp_path: Path,
) -> None:
    release, process, _cr_path, _scope = write_termination_fixture(tmp_path)
    paths = _enable_registered_legacy(release, process)
    protected = {key: paths[key].read_bytes() for key in ("legacy", "registry", "follow_ups")}

    _registry, snapshot, partition = load_formal_cr_partition(
        release,
        consumer_id="cr074-j1",
    )
    tracking = cr_tracking.build_cr_tracking_report(partition)
    lifecycle = cr_analysis.build_cr_lifecycle_check_report(
        release,
        partition_snapshot=snapshot,
        partition_report=partition,
    )
    index = cr_index.build_index(release, discovery_snapshot=snapshot)
    status_plan = cr_status_sync.plan_status_sync(
        release,
        "CR-101",
        status="closed",
        readiness="READY_WITH_RISK",
        gate_status="cp8_closed",
        work_id="WORK-101",
        effective_at="2026-08-20T09:00:00+00:00",
    )

    assert partition.decision == "PASS"
    assert tracking.partition_snapshot_digest == lifecycle.partition_snapshot_digest
    assert status_plan.admission is not None
    assert status_plan.admission.snapshot_digest == snapshot.snapshot_digest
    assert status_plan.as_dict()["mutation_count"] == 0
    assert [item["id"] for item in index["items"]] == ["CR-101"]
    assert tracking.registered_legacy_ids == ("CR-174",)
    assert tracking.native_cr_ids == ("CR-101",)
    assert {
        key: paths[key].read_bytes() for key in ("legacy", "registry", "follow_ups")
    } == protected


def test_j2_only_repairable_stale_lineage_accepts_typed_successor(
    tmp_path: Path,
) -> None:
    release, process, phase = _governance_fixture(tmp_path)
    _close_phase_work(release, process, phase, "W-001")
    project_path = process / "PROJECT.yaml"
    project_path.write_bytes(project_path.read_bytes() + b"\n")
    protected = {
        ref: (process / ref).read_bytes()
        for ref in (
            "PROJECT.yaml",
            phase.phase_ref,
            GOVERNANCE_PROJECTION_REL.as_posix(),
        )
    }

    plan = plan_shared_projection_repair(process)
    before = inspect_shared_projection_repair(process)
    authorization = SharedProjectionRepairAuthorizationV1(
        authorization_id="AUTH-CR074-J2",
        plan_digest=plan.plan_digest,
        target_refs=tuple(target.ref for target in plan.targets),
        expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )

    receipt = apply_shared_projection_repair(process, plan, authorization)
    after = inspect_shared_projection_repair(process)

    assert before["classification"] == "COMMITTED_STALE_REPAIRABLE"
    assert before["mutation_count"] == 0
    assert receipt.decision == "PASS"
    assert receipt.mutation_count == 1
    assert after["classification"] == "COMMITTED_CURRENT"
    assert after["decision"] == "PASS"
    assert {ref: (process / ref).read_bytes() for ref in protected} == protected


def test_j3_route_profile_selects_handoff_policy() -> None:
    from meta_flow.work.handoff import decide_handoff_policy
    from meta_flow.work.route_profile import RouteProfile

    routine = decide_handoff_policy(_work("G1"), "paused")
    functional = decide_handoff_policy(
        _work("G2", route_profile=RouteProfile(dispatch_mode="functional-agent")),
        "paused",
    )

    assert routine.decision == "NOT_REQUIRED"
    assert functional.decision == "REQUIRED"


@pytest.mark.parametrize(
    "row",
    SIX_ROUND_TO_JOURNEYS,
    ids=lambda row: f"{row.round_id}-{row.journey}",
)
def test_six_round_coverage_row_binds_shared_fixture_contract(
    row: RoundJourneyCoverageRowV1,
) -> None:
    contract = JOURNEY_FIXTURE_CONTRACTS[row.journey]

    assert row.fixture_contract_id == contract.contract_id
    assert row.scenario == contract.scenario
    assert row.evidence_test == contract.evidence_test
    assert row.expected_decision == contract.expected_decision
    assert callable(globals()[row.evidence_test])
    # 本矩阵只证明共享 Meta Flow fixture；quant-lab 受害者重放仍需独立授权。
    assert row.evidence_scope == FIXTURE_EVIDENCE_SCOPE
    assert row.victim_replay_status == "PENDING_AUTHORIZATION"


def test_six_round_matrix_has_no_orphan_and_does_not_claim_victim_replay() -> None:
    assert {row.round_id for row in SIX_ROUND_TO_JOURNEYS} == {
        "R1",
        "R1_recovery",
        "R2_admission",
        "R2_failure",
        "W1",
        "R3",
    }
    assert {row.journey for row in SIX_ROUND_TO_JOURNEYS} == {"J1", "J2", "J3"}
    assert all(row.victim_replay_status == VICTIM_REPLAY_STATUS for row in SIX_ROUND_TO_JOURNEYS)
    assert all(row.evidence_scope != "VICTIM_REPLAY" for row in SIX_ROUND_TO_JOURNEYS)
