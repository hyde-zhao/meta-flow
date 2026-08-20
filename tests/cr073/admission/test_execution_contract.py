from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow.contracts.typed_ref import RepositoryRole
from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.project.process_route_adapter import resolve_typed_repository_ref
from meta_flow.work.assurance import render_validation_provider_decision
from meta_flow.work.directory_envelope import normalize_successor_repository_refs
from meta_flow.work.init_transaction import (
    ExecutionContractAdmissionError,
    build_execution_contract_admission_validator,
    load_and_validate_execution_contract,
)
from meta_flow.work.model import (
    GovernanceProviderIdentityV1,
    SuccessorContractV1,
    TypedRepositoryRefV2,
    ValidationReuseDecisionV2,
    ValidationReuseRequestV2,
    admit_governance_provider,
)
from meta_flow.work.preflight import run_lifecycle_preflight
from meta_flow.work.validation_planner import build_validation_execution_plan
from meta_flow.work.validation_receipt import (
    adapt_validation_receipt_v1,
    create_validation_receipt,
    create_validation_receipt_v2,
    validation_receipt_from_payload,
    validation_reuse_request_from_receipt,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _route_fixture(tmp_path: Path) -> tuple[Path, Path]:
    release = tmp_path / "meta-flow"
    process = tmp_path / "meta-flow-process"
    (release / ".meta-flow").mkdir(parents=True)
    process.mkdir()
    for repository in (release, process):
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    (release / ".meta-flow" / "workspace.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture\n"
        "repo_role: release\n"
        "route_mode: sibling-binding\n"
        "process_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow-process\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture\n"
        "repo_role: process\n"
        "route_mode: sibling-binding\n"
        "release_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\nproject_id: fixture\nname: Fixture\nstatus: active\n",
        encoding="utf-8",
    )
    return release, process


def _contract() -> SuccessorContractV1:
    return SuccessorContractV1.build(
        contract_revision=1,
        root_concept="root",
        slice_id="slice-1",
        unit_id="W-001",
    )


def _unit(contract: SuccessorContractV1 | None = None) -> ExecutionUnitV1:
    value = contract or _contract()
    return ExecutionUnitV1(
        unit_id="W-001",
        root_concept="root",
        slice_id="slice-1",
        container_role="primary",
        revision=1,
        supersedes_unit_id="",
        contract_ref="process/contracts/W-001.json",
        contract_digest=value.payload_digest,
    )


def test_contract_is_loaded_and_semantically_validated_before_mutation(tmp_path: Path) -> None:
    release, process = _route_fixture(tmp_path)
    contract = _contract()
    target = process / "contracts" / "W-001.json"
    target.parent.mkdir()
    target.write_text(json.dumps(contract.as_dict()), encoding="utf-8")

    result = load_and_validate_execution_contract(
        release,
        ref=TypedRepositoryRefV2(
            2,
            RepositoryRole.PROCESS,
            "process/contracts/W-001.json",
        ),
        unit=_unit(contract),
        transaction_identity={
            "contract_revision": 1,
            "root_concept": "root",
            "slice_id": "slice-1",
            "unit_id": "W-001",
        },
    )
    assert result.contract == contract
    assert result.mutation_count == 0
    assert len(result.file_sha256) == 64
    owner, validator = build_execution_contract_admission_validator(
        release,
        ref="process/contracts/W-001.json",
        unit=_unit(contract),
    )
    report = run_lifecycle_preflight(
        {"work_id": "W-001"},
        {},
        validators=((owner, validator),),  # type: ignore[arg-type]
    )
    assert report.decision.decision.value == "READY"
    assert {item.code for item in report.decision.items} == {"EXECUTION_CONTRACT_READY"}


@pytest.mark.parametrize(
    ("contract", "unit", "code"),
    [
        (
            SuccessorContractV1.build(
                contract_revision=2,
                root_concept="root",
                slice_id="slice-1",
                unit_id="W-001",
            ),
            _unit(),
            "EXECUTION_CONTRACT_TUPLE_MISMATCH:contract_revision",
        ),
        (
            SuccessorContractV1.build(
                contract_revision=1,
                root_concept="other",
                slice_id="slice-1",
                unit_id="W-001",
            ),
            _unit(),
            "EXECUTION_CONTRACT_TUPLE_MISMATCH:root_concept",
        ),
        (
            _contract(),
            replace(_unit(), contract_digest=DIGEST_A),
            "EXECUTION_CONTRACT_CALLER_DIGEST_MISMATCH",
        ),
    ],
)
def test_revision_tuple_and_caller_digest_mismatch_fail_closed(
    tmp_path: Path,
    contract: SuccessorContractV1,
    unit: ExecutionUnitV1,
    code: str,
) -> None:
    release, process = _route_fixture(tmp_path)
    target = process / "contracts" / "W-001.json"
    target.parent.mkdir()
    target.write_text(json.dumps(contract.as_dict()), encoding="utf-8")
    with pytest.raises(ExecutionContractAdmissionError, match=code):
        load_and_validate_execution_contract(
            release,
            ref="process/contracts/W-001.json",
            unit=unit,
        )


def test_legacy_missing_prefix_and_typed_role_prefix_conflict_are_rejected(tmp_path: Path) -> None:
    release, _process = _route_fixture(tmp_path)
    with pytest.raises(ExecutionContractAdmissionError, match="EXECUTION_CONTRACT_REF_INVALID"):
        load_and_validate_execution_contract(
            release,
            ref="contracts/W-001.json",
            unit=_unit(),
        )
    with pytest.raises(ValueError, match="MIXED_PREFIX"):
        TypedRepositoryRefV2(2, RepositoryRole.PROCESS, "contracts/W-001.json")


def test_typed_ref_resolver_rejects_symlink(tmp_path: Path) -> None:
    release, process = _route_fixture(tmp_path)
    actual = process / "actual.json"
    actual.write_text("{}\n", encoding="utf-8")
    link = process / "link.json"
    try:
        link.symlink_to(actual)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(ValueError, match="typed repository ref must target a regular file"):
        resolve_typed_repository_ref(
            release,
            TypedRepositoryRefV2(2, RepositoryRole.PROCESS, "process/link.json"),
        )


def _provider(**updates: str) -> GovernanceProviderIdentityV1:
    values = {
        "package_name": "meta-flow",
        "package_version": "0.6.1",
        "source_kind": "candidate",
        "release_oid": "a" * 40,
        "process_oid": "b" * 40,
        "route_digest": DIGEST_C,
    }
    values.update(updates)
    return GovernanceProviderIdentityV1(**values)


def test_stale_or_global_provider_cannot_admit_governance_write() -> None:
    expected = _provider()
    stale = admit_governance_provider(_provider(release_oid="d" * 40), expected)
    unknown = admit_governance_provider(_provider(source_kind="global-unknown"), expected)
    assert stale.decision == "BLOCKED"
    assert stale.reason_codes == ("PROVIDER_RELEASE_OID_MISMATCH",)
    assert unknown.decision == "BLOCKED"
    assert "GLOBAL_PROVIDER_UNKNOWN" in unknown.reason_codes
    assert admit_governance_provider(expected, expected).decision == "READY"


class _FakeProvider:
    def __init__(self, decision: str) -> None:
        self.decision = decision
        self.calls: list[ValidationReuseRequestV2] = []

    def evaluate_reuse(self, request: ValidationReuseRequestV2) -> ValidationReuseDecisionV2:
        self.calls.append(request)
        return ValidationReuseDecisionV2(
            self.decision,
            () if self.decision == "REUSE" else ("FRESH_RUN_REQUIRED",),
            request.current_provider_identity_digest,
        )


def _receipt_and_request() -> tuple[object, ValidationReuseRequestV2]:
    receipt = create_validation_receipt_v2(
        layer="targeted",
        fingerprint_digest=DIGEST_A,
        profile_digest=DIGEST_B,
        command_identity=DIGEST_C,
        environment_summary={"python": "3.11", "platform": "linux", "toolchain": "uv"},
        source_manifest_digest="d" * 64,
        provider_identity_digest="e" * 64,
        decision="PASS",
        partial_mutation=False,
        result_digest="f" * 64,
        owner="fixture",
    )
    request = validation_reuse_request_from_receipt(
        receipt,
        current_fingerprint_digest=DIGEST_A,
        current_profile_digest=DIGEST_B,
        current_command_identity=DIGEST_C,
        current_environment={"python": "3.11", "platform": "linux", "toolchain": "uv"},
        current_source_manifest_digest="d" * 64,
        current_provider_identity_digest="e" * 64,
    )
    return receipt, request


def test_planner_is_a_thin_fake_provider_adapter() -> None:
    receipt, request = _receipt_and_request()
    provider = _FakeProvider("REUSE")
    plan = build_validation_execution_plan(
        fingerprints={"targeted": DIGEST_A},
        command_identities={"targeted": DIGEST_C},
        receipts=(receipt,),  # type: ignore[arg-type]
        layers=("targeted",),
        policy_provider=provider,
        provider_requests={"targeted": request},
    )
    assert len(provider.calls) == 1
    assert plan.decision == "REUSED_ALL"
    assert plan.steps[0].action == "REUSED_UNCHANGED"
    assert render_validation_provider_decision(
        provider.evaluate_reuse(request)
    )["decision"] == "REUSE"


def test_v1_receipt_is_readable_but_missing_semantics_are_not_fabricated() -> None:
    legacy = create_validation_receipt(
        layer="targeted",
        fingerprint_digest=DIGEST_A,
        command_identity=DIGEST_B,
        environment_summary={"python": "3.11", "platform": "linux", "toolchain": "uv"},
        decision="PASS",
        result_digest=DIGEST_C,
        owner="fixture",
    )
    roundtrip = validation_receipt_from_payload(legacy.as_dict())
    request = adapt_validation_receipt_v1(
        roundtrip,  # type: ignore[arg-type]
        current_fingerprint_digest=DIGEST_A,
        current_profile_digest="d" * 64,
        current_command_identity=DIGEST_B,
        current_environment={"python": "3.11", "platform": "linux", "toolchain": "uv"},
        current_source_manifest_digest="e" * 64,
        current_provider_identity_digest="f" * 64,
    )
    assert request.receipt_profile_digest == ""
    assert request.receipt_source_manifest_digest == ""
    assert request.receipt_provider_identity_digest == ""


def test_successor_ref_normalization_writes_only_v2() -> None:
    result = normalize_successor_repository_refs(
        (
            "process/contracts/W-001.json",
            TypedRepositoryRefV2(2, RepositoryRole.RELEASE, "pyproject.toml"),
        )
    )
    assert [ref.schema_version for ref in result.refs] == [2, 2]
    assert len(result.digest) == 64
