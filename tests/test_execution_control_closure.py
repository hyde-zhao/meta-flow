from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType, SimpleNamespace

import pytest

import meta_flow.execution_control.closure as closure_module
from meta_flow.checks import cp_result
from meta_flow.execution_control.closure import (
    INVENTORY_KINDS,
    ClosureCohortV1,
    ClosureOwnerCensusV1,
    _audit_closure,
    audit_closure,
    project_cr_consistency_inventory,
    project_dispatch_closure_inventory,
)
from meta_flow.execution_control.contract import canonical_digest
from meta_flow.project.scale import dump_yaml
from meta_flow.work.budget import BudgetLimit
from meta_flow.work.model import Work
from meta_flow.work.route_profile import SAFE_ROUTE_PROFILE
from meta_flow.work.scope import WorkScope
from meta_flow.work.validation_receipt import create_validation_receipt
from meta_flow.workflow.cr_projection import NativeCRStatusProjectionV1

STORY_ID = "STORY-CRTEST-F1-S3"
CR_ID = "CR-901"


@dataclass(frozen=True)
class ClosureFixture:
    release: Path
    process: Path
    result_ref: str
    return_ref: str
    evidence_ref: str
    receipt_ref: str
    return_path: Path
    receipt_path: Path


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(*roots: Path) -> dict[str, bytes]:
    return {
        f"{root.name}/{path.relative_to(root).as_posix()}": path.read_bytes()
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _healthy_projection() -> NativeCRStatusProjectionV1:
    return NativeCRStatusProjectionV1(
        cr_id=CR_ID,
        lifecycle_status="active",
        readiness_status="NOT_READY",
        gate_status="implementation_in_progress",
        formal_cr_ref=f"process/changes/{CR_ID}.md",
        summary_ref=f"process/changes/summaries/{CR_ID}.summary.json",
        ledger_event_id="CR-901-STATUS-1",
        decision="PASS",
        findings=(),
    )


@pytest.fixture
def closure_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ClosureFixture:
    release = tmp_path / "release"
    process = tmp_path / "process"
    release.mkdir()
    process.mkdir()
    subprocess.run(["git", "init", "-q", str(release)], check=True)
    subprocess.run(["git", "init", "-q", str(process)], check=True)
    (release / ".meta-flow").mkdir()
    (release / ".meta-flow/workspace.yaml").write_text(
        "\n".join(
            (
                "schema_version: 1",
                "layout_version: independent-process-repo-v1",
                "workflow_model: vnext",
                "project_id: fixture",
                "repo_role: release",
                "route_mode: sibling-binding",
                "process_repo:",
                "  anchor: workspace_parent",
                "  relative_path: process",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        "\n".join(
            (
                "schema_version: 1",
                "layout_version: independent-process-repo-v1",
                "workflow_model: vnext",
                "project_id: fixture",
                "repo_role: process",
                "route_mode: sibling-binding",
                "release_repo:",
                "  anchor: workspace_parent",
                "  relative_path: release",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\nproject_id: fixture\nname: Fixture\nstatus: active\n",
        encoding="utf-8",
    )
    work_path = process / "works" / CR_ID / "WORK.yaml"
    work_path.parent.mkdir(parents=True)
    work_scope = WorkScope(
        version=1,
        allowed_reads=("works/CR-901/WORK.yaml",),
        allowed_writes=("works/CR-901/**",),
        required_checks=("closure",),
    )
    work = Work(
        schema_version=1,
        work_id=CR_ID,
        project_id="fixture",
        kind="cr",
        objective="fixture closure",
        status="active",
        request_ref="works/CR-901/REQUEST.md",
        request_confirmed=True,
        phase_ref="",
        risk_profile="G1",
        risk_reason_codes=("TEST_FIXTURE",),
        required_gates=(),
        route_profile=SAFE_ROUTE_PROFILE,
        scope=work_scope,
        budget=BudgetLimit(8, 8, 3, 32000),
        usage_ref="works/CR-901/USAGE.json",
        release_base_oid="a" * 40,
        process_base_oid="b" * 40,
    )
    work_path.write_text(dump_yaml(work.as_dict()) + "\n", encoding="utf-8")

    receipt = create_validation_receipt(
        layer="targeted",
        fingerprint_digest=hashlib.sha256(b"profile").hexdigest(),
        command_identity=hashlib.sha256(b"command").hexdigest(),
        environment_summary={"python": "3.11", "platform": "linux", "toolchain": "uv"},
        decision="PASS",
        result_digest=hashlib.sha256(b"result").hexdigest(),
        owner="fixture",
    )
    receipt_ref = f"process/works/{CR_ID}/evidence/validation/targeted.receipt.json"
    receipt_path = process / receipt_ref.removeprefix("process/")
    _write_json(receipt_path, receipt.as_dict())
    return_ref = f"process/returns/{STORY_ID}.CP6.return.json"
    return_path = process / return_ref.removeprefix("process/")
    _write_json(
        return_path,
        {
            "schema_version": 1,
            "cr_id": CR_ID,
            "story_id": STORY_ID,
            "touched_files": [{"path": "meta_flow/example.py", "change_type": "modified"}],
        },
    )
    evidence_ref = f"process/evidence/{STORY_ID}.CP6.index.json"
    evidence_path = process / evidence_ref.removeprefix("process/")
    _write_json(
        evidence_path,
        {
            "schema_version": 1,
            "cr_id": CR_ID,
            "story_id": STORY_ID,
            "return_ref": return_ref,
            "commands": [{"command": "pytest", "result": "PASS"}],
            "tests": ["closure"],
        },
    )
    result_ref = f"process/checks/CP6-{STORY_ID}.result.json"
    result_path = process / result_ref.removeprefix("process/")
    _write_json(
        result_path,
        {
            "schema_version": 1,
            "checkpoint": "CP6",
            "event_id": "CP6-CRTEST-S3-PASS-V1",
            "check_attempt": 1,
            "cr_id": CR_ID,
            "story_id": STORY_ID,
            "decision": "PASS",
            "evidence_ref": evidence_ref,
            "dispatch_refs": ["DISPATCH-CRTEST-S3-V1"],
            "items": [],
            "input_artifact_hashes": {
                return_ref: f"sha256:{_sha256(return_path)}",
                evidence_ref: f"sha256:{_sha256(evidence_path)}",
                receipt_ref: f"sha256:{_sha256(receipt_path)}",
            },
            "checker_provenance": {"profile": "strict"},
        },
    )
    checkpoint_ledger = process / "state/CHECKPOINT-LEDGER.ndjson"
    checkpoint_ledger.parent.mkdir(parents=True)
    checkpoint_ledger.write_text(
        json.dumps(
            {
                "event_id": "CP6-CRTEST-S3-PASS-V1",
                "event_type": "checkpoint_result",
                "checkpoint": "CP6",
                "cr_id": CR_ID,
                "story_id": STORY_ID,
                "decision": "PASS",
                "result_ref": result_ref,
                "revision": 1,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    dispatch_ledger = process / "state/AGENT-DISPATCH-LEDGER.ndjson"
    dispatch_ledger.write_text(
        json.dumps(
            {
                "event_id": "DISPATCH-CRTEST-S3-V1",
                "event_type": "dispatch",
                "dispatch_id": "DISPATCH-CRTEST-S3-V1",
                "attempt_id": "ATTEMPT-1",
                "story_id": STORY_ID,
                "canonical_role": "meta-dev",
                "checkpoint": "CP6",
                "dispatch_mode": "direct",
                "status": "completed",
                "terminal_result": "PASS",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (process / "changes").mkdir()
    formal_ref = f"process/changes/{CR_ID}.md"
    summary_ref = f"process/changes/summaries/{CR_ID}.summary.json"
    (process / f"changes/{CR_ID}.md").write_text(
        "\n".join(
            (
                "---",
                "schema_version: 1",
                f'cr_id: "{CR_ID}"',
                'cr_type: "architecture"',
                'title: "Fixture CR"',
                'lifecycle_status: "active"',
                'readiness_status: "NOT_READY"',
                'gate_status: "implementation_in_progress"',
                'gate_profile: "architecture-major"',
                "---",
                "",
                "# Fixture CR",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (process / "changes/summaries").mkdir()
    _write_json(
        process / f"changes/summaries/{CR_ID}.summary.json",
        {
            "id": CR_ID,
            "full_ref": formal_ref,
            "status": "active",
            "readiness": "NOT_READY",
            "gate_status": "implementation_in_progress",
        },
    )
    _write_json(
        process / "changes/CR-INDEX.json",
        {
            "items": [
                {
                    "id": CR_ID,
                    "full_ref": formal_ref,
                    "summary_ref": summary_ref,
                    "lifecycle_status": "active",
                    "readiness_status": "NOT_READY",
                    "gate_status": "implementation_in_progress",
                }
            ]
        },
    )
    (process / "state/CR-LEDGER.ndjson").write_text(
        json.dumps(
            {
                "event_id": "CR-901-STATUS-1",
                "event_type": "cr_status",
                "id": CR_ID,
                "cr_id": CR_ID,
                "status": "active",
                "readiness": "NOT_READY",
                "gate_status": "implementation_in_progress",
                "full_ref": formal_ref,
                "summary_ref": summary_ref,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(cp_result, "validate_cp_result", lambda *args, **kwargs: ([], []))
    return ClosureFixture(
        release=release,
        process=process,
        result_ref=result_ref,
        return_ref=return_ref,
        evidence_ref=evidence_ref,
        receipt_ref=receipt_ref,
        return_path=return_path,
        receipt_path=receipt_path,
    )


def test_public_api_is_deny_default_and_has_only_three_inputs() -> None:
    signature = inspect.signature(audit_closure)
    assert tuple(signature.parameters) == (
        "project_root",
        "story_id",
        "expected_cohort_revision",
    )
    with pytest.raises(TypeError):
        audit_closure(  # type: ignore[call-arg]
            Path("."),
            story_id=STORY_ID,
            expected_cohort_revision=1,
            expected_manifest={},
        )


def test_native_authority_and_all_six_projectors_pass_without_writes(
    closure_fixture: ClosureFixture,
) -> None:
    before = _snapshot(closure_fixture.release, closure_fixture.process)

    result = audit_closure(
        closure_fixture.release,
        story_id=STORY_ID,
        expected_cohort_revision=1,
    )

    assert result.cohort_decision == result.strict_project_decision == "PASS", result.reason_codes
    assert result.reason_codes == ()
    assert result.authority_decision == "PASS"
    assert len(result.projector_provenance) == 6
    assert {item.kind for item in result.projector_provenance} == set(INVENTORY_KINDS)
    assert all(item.executed and item.decision == "PASS" for item in result.projector_provenance)
    assert all(item.expected_callable_ref == item.actual_callable_ref for item in result.projector_provenance)
    assert result.mutation_count == 0
    assert _snapshot(closure_fixture.release, closure_fixture.process) == before


def test_result_is_deterministic_for_the_same_native_preimage(
    closure_fixture: ClosureFixture,
) -> None:
    first = audit_closure(
        closure_fixture.release, story_id=STORY_ID, expected_cohort_revision=1
    )
    second = audit_closure(
        closure_fixture.release, story_id=STORY_ID, expected_cohort_revision=1
    )
    assert first == second
    assert first.result_digest == canonical_digest(first.as_dict(include_result_digest=False))


def test_return_or_evidence_drift_blocks_before_any_projector(
    closure_fixture: ClosureFixture,
) -> None:
    closure_fixture.return_path.write_text('{"forged":true}\n', encoding="utf-8")
    result = audit_closure(
        closure_fixture.release, story_id=STORY_ID, expected_cohort_revision=1
    )
    assert result.cohort_decision == "BLOCKED"
    assert result.authority_decision == "BLOCKED"
    assert result.projector_provenance == ()
    assert "CLOSURE_AUTHORITY_INVALID" in result.reason_codes
    assert any(code.startswith("CLOSURE_INPUT_HASH_DRIFT") for code in result.reason_codes)
    assert result.mutation_count == 0


def test_wrong_cohort_revision_blocks_at_native_authority(
    closure_fixture: ClosureFixture,
) -> None:
    result = audit_closure(
        closure_fixture.release, story_id=STORY_ID, expected_cohort_revision=2
    )
    assert result.authority_decision == "BLOCKED"
    assert "CLOSURE_CP6_STRICT_CORRELATION_FAILED" in result.reason_codes
    assert result.projector_provenance == ()


def test_caller_resigned_side_artifacts_cannot_change_expected_authority(
    closure_fixture: ClosureFixture,
) -> None:
    baseline = audit_closure(
        closure_fixture.release, story_id=STORY_ID, expected_cohort_revision=1
    )
    _write_json(
        closure_fixture.process / "evidence/caller-authority.json",
        {
            "manifest": [],
            "owner": "caller",
            "decision": "PASS",
            "digest": hashlib.sha256(b"self-signed").hexdigest(),
        },
    )
    replay = audit_closure(
        closure_fixture.release, story_id=STORY_ID, expected_cohort_revision=1
    )
    assert baseline.cohort_decision == replay.cohort_decision == "PASS", baseline.reason_codes
    assert baseline.authority_provenance_digest == replay.authority_provenance_digest
    assert baseline.result_digest == replay.result_digest


@pytest.mark.parametrize("kind", INVENTORY_KINDS)
def test_each_canonical_projector_bypass_is_typed_blocked(
    closure_fixture: ClosureFixture, kind: str
) -> None:
    result = _audit_closure(
        closure_fixture.release,
        story_id=STORY_ID,
        expected_cohort_revision=1,
        projector_overrides={kind: None},
    )
    provenance = next(item for item in result.projector_provenance if item.kind == kind)
    assert result.cohort_decision == "BLOCKED"
    assert provenance.executed is False
    assert "CANONICAL_PROJECTOR_BYPASSED" in provenance.reason_codes
    assert result.mutation_count == 0


@pytest.mark.parametrize("kind", INVENTORY_KINDS)
def test_substituted_callable_with_self_consistent_output_is_blocked(
    closure_fixture: ClosureFixture, kind: str
) -> None:
    def substitute(project_root: Path, authority: object, cohort: ClosureCohortV1) -> ClosureOwnerCensusV1:
        del project_root, authority
        return ClosureOwnerCensusV1(
            kind=kind,
            items=(),
            source_refs=("meta_flow/execution_control/closure.py",),
        )

    result = _audit_closure(
        closure_fixture.release,
        story_id=STORY_ID,
        expected_cohort_revision=1,
        projector_overrides={kind: substitute},
    )
    provenance = next(item for item in result.projector_provenance if item.kind == kind)
    assert result.cohort_decision == "BLOCKED"
    assert provenance.actual_callable_ref.endswith(".substitute")
    assert provenance.actual_callable_contract_digest != provenance.expected_callable_contract_digest
    assert "CANONICAL_PROJECTOR_CALLABLE_MISMATCH" in provenance.reason_codes
    assert provenance.executed is False


@pytest.mark.parametrize("kind", INVENTORY_KINDS)
def test_distinct_projector_object_with_identical_contract_is_blocked(
    closure_fixture: ClosureFixture, kind: str
) -> None:
    canonical = closure_module._CLOSED_PROJECTOR_REGISTRY[kind].projector
    substitute = FunctionType(
        canonical.__code__,
        canonical.__globals__,
        canonical.__name__,
        canonical.__defaults__,
        canonical.__closure__,
    )
    substitute.__module__ = canonical.__module__
    substitute.__qualname__ = canonical.__qualname__
    substitute.__annotations__ = canonical.__annotations__.copy()
    substitute.__kwdefaults__ = dict(canonical.__kwdefaults__ or {})

    assert substitute is not canonical
    assert closure_module._callable_ref(substitute) == closure_module._callable_ref(canonical)
    assert closure_module._callable_contract_digest(
        substitute
    ) == closure_module._callable_contract_digest(canonical)

    result = _audit_closure(
        closure_fixture.release,
        story_id=STORY_ID,
        expected_cohort_revision=1,
        projector_overrides={kind: substitute},
    )
    provenance = next(item for item in result.projector_provenance if item.kind == kind)
    assert result.cohort_decision == "BLOCKED"
    assert provenance.callable_object_match is False
    assert "CANONICAL_PROJECTOR_OBJECT_MISMATCH" in provenance.reason_codes
    assert provenance.executed is False


@pytest.mark.parametrize(
    ("kind", "module_name", "attribute"),
    (
        ("container", "meta_flow.work.model", "load_work"),
        ("dispatch", "meta_flow.state.event_ledger", "project_dispatch_attempt"),
        ("result", "meta_flow.checks.cp_result", "project_cp_evidence_inventory"),
        ("evidence", "meta_flow.checks.cp_result", "project_cp_evidence_inventory"),
        ("projection", "meta_flow.workflow.cr_lifecycle", "project_native_cr_status"),
        ("receipt", "meta_flow.execution_control.closure", "load_validation_receipt"),
    ),
)
def test_nested_canonical_owner_callable_substitution_is_blocked(
    closure_fixture: ClosureFixture,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    module_name: str,
    attribute: str,
) -> None:
    module = importlib.import_module(module_name)

    def forged_owner(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return SimpleNamespace(decision="PASS", findings=(), work_id=CR_ID)

    monkeypatch.setattr(module, attribute, forged_owner)
    result = audit_closure(
        closure_fixture.release, story_id=STORY_ID, expected_cohort_revision=1
    )
    provenance = next(item for item in result.projector_provenance if item.kind == kind)
    assert result.cohort_decision == "BLOCKED"
    assert "CANONICAL_OWNER_CALLABLE_MISMATCH" in provenance.reason_codes
    assert provenance.actual_owner_callable_ref.endswith(".forged_owner")
    assert provenance.executed is False


@pytest.mark.parametrize(
    ("kind", "module_name", "attribute"),
    (
        ("container", "meta_flow.work.model", "load_work"),
        ("dispatch", "meta_flow.state.event_ledger", "project_dispatch_attempt"),
        ("result", "meta_flow.checks.cp_result", "project_cp_evidence_inventory"),
        ("evidence", "meta_flow.checks.cp_result", "project_cp_evidence_inventory"),
        ("projection", "meta_flow.workflow.cr_lifecycle", "project_native_cr_status"),
        ("receipt", "meta_flow.execution_control.closure", "load_validation_receipt"),
    ),
)
def test_distinct_owner_object_with_identical_contract_is_blocked(
    closure_fixture: ClosureFixture,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    module_name: str,
    attribute: str,
) -> None:
    module = importlib.import_module(module_name)
    canonical = getattr(module, attribute)
    substitute = FunctionType(
        canonical.__code__,
        canonical.__globals__,
        canonical.__name__,
        canonical.__defaults__,
        canonical.__closure__,
    )
    substitute.__module__ = canonical.__module__
    substitute.__qualname__ = canonical.__qualname__
    substitute.__annotations__ = canonical.__annotations__.copy()
    substitute.__kwdefaults__ = dict(canonical.__kwdefaults__ or {})
    monkeypatch.setattr(module, attribute, substitute)

    assert substitute is not canonical
    assert closure_module._callable_ref(substitute) == closure_module._callable_ref(canonical)
    assert closure_module._runtime_owner_callable_digest(
        substitute
    ) == closure_module._runtime_owner_callable_digest(canonical)

    result = audit_closure(
        closure_fixture.release, story_id=STORY_ID, expected_cohort_revision=1
    )
    provenance = next(item for item in result.projector_provenance if item.kind == kind)
    assert result.cohort_decision == "BLOCKED"
    assert provenance.owner_callable_object_match is False
    assert "CANONICAL_OWNER_CALLABLE_OBJECT_MISMATCH" in provenance.reason_codes
    assert provenance.executed is False


def test_corrupted_native_receipt_is_counted_by_receipt_owner(
    closure_fixture: ClosureFixture,
) -> None:
    payload = json.loads(closure_fixture.receipt_path.read_text(encoding="utf-8"))
    payload["receipt_digest"] = hashlib.sha256(b"forged").hexdigest()
    _write_json(closure_fixture.receipt_path, payload)
    result = audit_closure(
        closure_fixture.release, story_id=STORY_ID, expected_cohort_revision=1
    )
    # receipt 同时属于 CP6 input hashes，必须在 authority 层先 fail closed。
    assert result.authority_decision == "BLOCKED"
    assert any(code.startswith("CLOSURE_INPUT_HASH_DRIFT") for code in result.reason_codes)


def test_dispatch_adapter_consumes_canonical_event_projector() -> None:
    cohort = ClosureCohortV1("CR-TEST", "execution-control", "closure", 1)
    events = (
        {
            "event_id": "dispatch-1",
            "event_type": "dispatch",
            "dispatch_id": "dispatch-1",
            "attempt_id": "attempt-1",
            "story_id": STORY_ID,
            "canonical_role": "meta-dev",
            "checkpoint": "CP6",
            "dispatch_mode": "direct",
            "status": "completed",
            "terminal_result": "PASS",
        },
    )
    items = project_dispatch_closure_inventory(
        cohort=cohort,
        events=events,
        dispatch_ids=("dispatch-1", "dispatch-missing"),
    )
    assert [(item.ref, item.dangling) for item in items] == [
        ("dispatch-1", False),
        ("dispatch-missing", True),
    ]


def test_cr_adapter_rejects_duck_type_and_missing_identity() -> None:
    cohort = ClosureCohortV1("CR-TEST", "execution-control", "closure", 1)
    fake = SimpleNamespace(
        cr_id=CR_ID,
        decision="PASS",
        findings=(),
        formal_cr_ref=f"process/changes/{CR_ID}.md",
    )
    assert project_cr_consistency_inventory(cohort=cohort, projection=fake)[0].dangling
    healthy = _healthy_projection()
    missing = NativeCRStatusProjectionV1(
        cr_id=healthy.cr_id,
        lifecycle_status=healthy.lifecycle_status,
        readiness_status=healthy.readiness_status,
        gate_status=healthy.gate_status,
        formal_cr_ref="",
        summary_ref=healthy.summary_ref,
        ledger_event_id=healthy.ledger_event_id,
        decision="PASS",
        findings=(),
    )
    assert not project_cr_consistency_inventory(cohort=cohort, projection=healthy)[0].dangling
    assert project_cr_consistency_inventory(cohort=cohort, projection=missing)[0].dangling


def test_cp_evidence_adapter_rechecks_declared_evidence_digest(
    closure_fixture: ClosureFixture,
) -> None:
    cohort = ClosureCohortV1(CR_ID, "execution-control", "closure", 1)
    projected = cp_result.project_cp_evidence_inventory(
        closure_fixture.release,
        cohort=cohort,
        result_refs=(closure_fixture.result_ref,),
    )
    assert projected.mutation_count == 0
    assert projected.findings == ()
    assert not projected.result_items[0].dangling
    assert all(not item.dangling for item in projected.evidence_items)


def test_malformed_public_input_returns_typed_blocked() -> None:
    result = audit_closure(Path("."), story_id="bad/id", expected_cohort_revision=0)
    assert result.cohort_decision == result.strict_project_decision == "BLOCKED"
    assert result.authority_decision == "BLOCKED"
    assert result.mutation_count == 0


def test_missing_process_route_returns_typed_blocked(tmp_path: Path) -> None:
    result = audit_closure(tmp_path, story_id=STORY_ID, expected_cohort_revision=1)
    assert result.authority_decision == "BLOCKED"
    assert result.projector_provenance == ()
    assert "CLOSURE_CP6_LEDGER_IDENTITY_UNAVAILABLE" in result.reason_codes
    assert result.mutation_count == 0
