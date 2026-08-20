from __future__ import annotations

from datetime import UTC, datetime

import pytest

from meta_flow.checks.adoption_readiness import (
    VictimAcceptanceClaimV1,
    VictimReplayAuthorizationV1,
    VictimReplayProviderFactV1,
    VictimReplayRequestV1,
    check_installed_artifact_gate,
    classify_acceptance_claim,
    plan_victim_replay,
)

HEX_A = "a" * 64
HEX_B = "b" * 64
RELEASE_OID = "c" * 40
PROCESS_OID = "d" * 40
NOW = datetime(2026, 8, 20, tzinfo=UTC)


def request() -> VictimReplayRequestV1:
    return VictimReplayRequestV1(
        target_project_id="quant-lab",
        target_project_ref_digest=HEX_A,
        candidate_provider_identity_digest=HEX_B,
        release_oid=RELEASE_OID,
        process_oid=PROCESS_OID,
        commands=("meta-flow work init-preflight --project-root .",),
        evidence_target_ref="process/evidence/CR073-SOURCE-CANDIDATE-VICTIM.json",
    )


def authorization(**overrides: object) -> VictimReplayAuthorizationV1:
    values = {
        "schema_version": 1,
        "authorization_id": "AUTH-CR073-VICTIM-001",
        "authorization_kind": "typed-external-operation",
        "operation": "source-candidate-victim-replay",
        "target_project_id": "quant-lab",
        "target_project_ref_digest": HEX_A,
        "candidate_provider_identity_digest": HEX_B,
        "release_oid": RELEASE_OID,
        "process_oid": PROCESS_OID,
        "commands": ("meta-flow work init-preflight --project-root .",),
        "evidence_target_ref": "process/evidence/CR073-SOURCE-CANDIDATE-VICTIM.json",
        "issued_at": "2026-08-19T00:00:00Z",
        "expires_at": "2026-08-21T00:00:00Z",
        "single_use": True,
        "consumed": False,
    }
    values.update(overrides)
    return VictimReplayAuthorizationV1(**values)


def provider() -> VictimReplayProviderFactV1:
    return VictimReplayProviderFactV1(
        provider_mode="source-candidate",
        provider_identity_digest=HEX_B,
    )


def evidence(
    kind: str,
    *,
    replay: str = "",
    artifact: str = "",
    installation: str = "",
) -> dict[str, str]:
    return {
        "evidence_kind": kind,
        "provider_identity_digest": HEX_B,
        "external_replay_receipt_digest": replay,
        "artifact_digest": artifact,
        "installation_receipt_digest": installation,
    }


def test_missing_authorization_is_blocked_before_any_target_io() -> None:
    plan = plan_victim_replay(request(), None, provider(), now=NOW)

    assert plan.decision == "BLOCKED"
    assert plan.finding_codes == ("EXTERNAL_AUTHORIZATION_REQUIRED",)
    assert plan.target_read_count == 0
    assert plan.target_run_count == 0
    assert plan.target_write_count == 0
    assert plan.mutation_count == 0


@pytest.mark.parametrize(
    ("auth", "code"),
    [
        (
            authorization(expires_at="2026-08-19T12:00:00Z"),
            "EXTERNAL_AUTHORIZATION_EXPIRED",
        ),
        (
            authorization(consumed=True),
            "EXTERNAL_AUTHORIZATION_NOT_FRESH_SINGLE_USE",
        ),
        (
            authorization(target_project_id="other-project"),
            "EXTERNAL_AUTHORIZATION_REQUEST_MISMATCH",
        ),
    ],
)
def test_stale_reused_or_mismatched_authorization_is_blocked(
    auth: VictimReplayAuthorizationV1,
    code: str,
) -> None:
    plan = plan_victim_replay(request(), auth, provider(), now=NOW)

    assert plan.decision == "BLOCKED"
    assert code in plan.finding_codes
    assert plan.mutation_count == 0


def test_exact_authorization_builds_plan_but_does_not_execute_target() -> None:
    plan = plan_victim_replay(request(), authorization(), provider(), now=NOW)

    assert plan.decision == "READY"
    assert plan.finding_codes == ()
    assert plan.authorization_id == "AUTH-CR073-VICTIM-001"
    assert plan.target_read_count == plan.target_run_count == plan.target_write_count == 0
    assert "quant-lab" not in str(plan.as_dict())


def test_provider_fixture_source_candidate_and_installed_claims_do_not_conflate() -> None:
    fixture_claim = classify_acceptance_claim(evidence("provider_fixture"))
    source_claim = classify_acceptance_claim(
        evidence("source_candidate_replay", replay=HEX_A)
    )
    installed_claim = classify_acceptance_claim(
        evidence(
            "installed_artifact_replay",
            replay=HEX_A,
            artifact=HEX_B,
            installation="c" * 64,
        )
    )

    assert fixture_claim is VictimAcceptanceClaimV1.PROVIDER_FIXTURE
    assert source_claim is VictimAcceptanceClaimV1.SOURCE_CANDIDATE
    assert installed_claim is VictimAcceptanceClaimV1.INSTALLED_ARTIFACT
    with pytest.raises(ValueError):
        classify_acceptance_claim(
            evidence("installed_artifact_replay", replay=HEX_A)
        )


def test_installed_artifact_is_deferred_for_cr073_and_hard_afterward() -> None:
    deferred = check_installed_artifact_gate((), current_change_id="CR-073")
    blocked = check_installed_artifact_gate(
        (VictimAcceptanceClaimV1.SOURCE_CANDIDATE,),
        current_change_id="CR-074",
    )
    ready = check_installed_artifact_gate(
        (VictimAcceptanceClaimV1.INSTALLED_ARTIFACT,),
        current_change_id="CR-074",
    )

    assert deferred.decision == "DEFERRED"
    assert blocked.decision == "BLOCKED"
    assert ready.decision == "READY"
