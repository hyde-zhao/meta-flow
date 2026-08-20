"""S5 T1：canonical runtime context 与 active inventory 的最小契约测试。"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

import pytest

from meta_flow.execution_control.admission import execution_inventory_digest
from meta_flow.execution_control.contract import ExecutionUnitV1, canonical_digest
from meta_flow.execution_control.migration import (
    FIXED_RECEIPT_REF,
    GENERATOR_IDENTITY,
    LEGACY_RECEIPT_REFS,
    MATERIALIZATION_AUTHORIZATION_REF,
    PACKAGE_NAME,
    PACKAGE_VERSION,
    FreshMaterializationProofV1,
    NativeMaterializationAuthorityV1,
    ProviderActivationReceiptV1,
    ProviderReceiptLoadV1,
    UnknownProviderContractError,
    _load_native_materialization_authority,
    _MaterializationSnapshotV1,
    _materialize_provider_activation_receipt_create_only,
    _mint_materialization_capability,
    _path_preimage_digest,
    _perform_receipt_create_only,
    _policy_for_receipt,
    _register_fresh_materialization_proof,
    apply_provider_receipt_materialization,
    build_provider_qualification_evidence,
    current_execution_control_policy,
    load_provider_activation_receipt,
    materialize_provider_activation_receipt,
    plan_provider_receipt_materialization,
)
from meta_flow.execution_control.runtime_context import (
    ActiveExecutionInventoryV1,
    RequestMaterializationCandidateV1,
    _repository_facts,
    build_execution_control_context,
    project_active_execution_inventory,
)
from meta_flow.project.model import Project
from meta_flow.state.event_ledger import append_event

SHA = "a" * 64
OID = "b" * 40
FROZEN_REQUIRED_SOURCE_OWNERS = frozenset({
    "meta_flow/execution_control/runtime_context.py", "meta_flow/execution_control/migration.py",
    "meta_flow/execution_control/consumer_scan.py", "meta_flow/execution_control/contract.py",
    "meta_flow/execution_control/admission.py", "meta_flow/execution_control/repair_admission.py",
    "meta_flow/work/store.py",
    "meta_flow/work/assurance.py", "meta_flow/work/cli.py",
    "meta_flow/work/usage.py", "meta_flow/work/usage_admission.py",
    "meta_flow/evolution.py",
    "meta_flow/evolution_cli.py",
})


def _evidence_digests() -> dict[str, str]:
    return {
        f"{layer}.{part}": SHA
        for layer in (
            "candidate_targeted",
            "candidate_compatibility",
            "candidate_full",
            "candidate_closure",
        )
        for part in ("profile", "command", "result", "receipt")
    }


def _write_package_sources(root: Path) -> None:
    for ref in FROZEN_REQUIRED_SOURCE_OWNERS:
        source = root.joinpath(*Path(ref).parts[1:])
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(ref.encode("utf-8"))


def _receipt_locator(package_root: Path) -> Path:
    return package_root.joinpath(*PurePosixPath(FIXED_RECEIPT_REF).parts[1:])


def _receipt_payload(package_root: Path | None = None) -> dict[str, object]:
    manifest = []
    for ref in sorted(FROZEN_REQUIRED_SOURCE_OWNERS):
        raw = (
            package_root.joinpath(*Path(ref).parts[1:]).read_bytes()
            if package_root is not None
            else b"x"
        )
        manifest.append(
            {"ref": ref, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        )
    evidence = {
        key: value for key, value in _evidence_digests().items()
    }
    payload: dict[str, object] = {
        "schema_version": 1,
        "package_name": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "policy_revision": 1,
        "cohort_revision": 1,
        "context_revision": 1,
        "qualified_source_manifest": manifest,
        "qualified_source_set_digest": canonical_digest(manifest),
        "evidence_digests": evidence,
        "generator_identity": GENERATOR_IDENTITY,
        "qualified_source_exclusions": [FIXED_RECEIPT_REF],
    }
    payload["receipt_digest"] = ProviderActivationReceiptV1.digest_payload(payload)
    return payload


def test_packaged_receipt_rotation_preserves_v1_through_v8_and_selects_v9() -> None:
    release_root = Path(__file__).parents[1]
    package_root = release_root / "meta_flow"
    qualification_evidence_path = (
        release_root / "docs/release/PROVIDER-QUALIFICATION-0.6.1.json"
    )
    assert LEGACY_RECEIPT_REFS == (
        "meta_flow/execution_control/provider/activation-receipt-v1.json",
        "meta_flow/execution_control/provider/activation-receipt-v2.json",
        "meta_flow/execution_control/provider/activation-receipt-v3.json",
        "meta_flow/execution_control/provider/activation-receipt-v4.json",
        "meta_flow/execution_control/provider/activation-receipt-v5.json",
        "meta_flow/execution_control/provider/activation-receipt-v6.json",
        "meta_flow/execution_control/provider/activation-receipt-v7.json",
        "meta_flow/execution_control/provider/activation-receipt-v8.json",
    )
    legacy_v1 = package_root.joinpath(*PurePosixPath(LEGACY_RECEIPT_REFS[0]).parts[1:])
    legacy_v2 = package_root.joinpath(*PurePosixPath(LEGACY_RECEIPT_REFS[1]).parts[1:])
    legacy_v3 = package_root.joinpath(*PurePosixPath(LEGACY_RECEIPT_REFS[2]).parts[1:])
    legacy_v4 = package_root.joinpath(*PurePosixPath(LEGACY_RECEIPT_REFS[3]).parts[1:])
    legacy_v5 = package_root.joinpath(*PurePosixPath(LEGACY_RECEIPT_REFS[4]).parts[1:])
    legacy_v6 = package_root.joinpath(*PurePosixPath(LEGACY_RECEIPT_REFS[5]).parts[1:])
    legacy_v7 = package_root.joinpath(*PurePosixPath(LEGACY_RECEIPT_REFS[6]).parts[1:])
    legacy_v8 = package_root.joinpath(*PurePosixPath(LEGACY_RECEIPT_REFS[7]).parts[1:])
    current = _receipt_locator(package_root)

    assert hashlib.sha256(legacy_v1.read_bytes()).hexdigest() == (
        "37f1a9c7f3d28c8b4c0bacd2f6817c8cd900bdab71180321b437d335c0b1263a"
    )
    assert hashlib.sha256(legacy_v2.read_bytes()).hexdigest() == (
        "63ea571d3f28e794d054f43c6be9f12f36a65f920ef45aa9597b2a4226aa2130"
    )
    assert hashlib.sha256(legacy_v3.read_bytes()).hexdigest() == (
        "7423d0bb1c1605e6800641b71b90bda40f82076b790846112e6b580ab8bfdebd"
    )
    assert hashlib.sha256(legacy_v4.read_bytes()).hexdigest() == (
        "372d3a49c1997ec58c1e1d2108e07d95059a5355131f7d771517efb7f8da7fff"
    )
    assert hashlib.sha256(legacy_v5.read_bytes()).hexdigest() == (
        "fd62739690c958465faaa1308c98cf13341becb49922cb536406cd5d23b40c55"
    )
    assert hashlib.sha256(legacy_v6.read_bytes()).hexdigest() == (
        "f40190109d7c75ea3a9b87522fade3a0550a9e811c627d7f866fc1c5eb31a975"
    )
    assert hashlib.sha256(legacy_v7.read_bytes()).hexdigest() == (
        "4bf68682229b94de4597a11ae28c4e8e8feee37774acd242da2a1595ea709ea9"
    )
    assert hashlib.sha256(legacy_v8.read_bytes()).hexdigest() == (
        "26ac1314bf96ee75a3040e68860b6c59cbb66a55fb843979a4d3f87870370530"
    )
    assert current.name == "activation-receipt-v9.json"
    assert load_provider_activation_receipt().status == "CURRENT"

    current_payload = json.loads(current.read_text(encoding="utf-8"))
    assert current_payload["package_version"] == PACKAGE_VERSION
    assert current_payload["qualified_source_exclusions"] == [FIXED_RECEIPT_REF]
    assert current_payload["generator_identity"] == GENERATOR_IDENTITY

    qualification_evidence = json.loads(
        qualification_evidence_path.read_text(encoding="utf-8")
    )
    assert qualification_evidence["package_name"] == PACKAGE_NAME
    # revision 9 的 provider evidence 源于已发布 0.6.1 资格档案；
    # 当前包版本由 receipt 自身的 PACKAGE_VERSION 独立表达。
    assert qualification_evidence["package_version"] == "0.6.1"
    for layer_name, layer_payload in qualification_evidence["layers"].items():
        for evidence_part in ("profile", "command", "result", "receipt"):
            assert current_payload["evidence_digests"][
                f"{layer_name}.{evidence_part}"
            ] == canonical_digest(layer_payload[evidence_part])


def test_receipt_is_closed_fixed_locator_and_policy_never_changes_writer_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "meta_flow"
    _write_package_sources(root)
    locator = _receipt_locator(root)
    monkeypatch.setattr("meta_flow.execution_control.migration._package_root", lambda: root)
    monkeypatch.setattr("meta_flow.execution_control.migration._receipt_path", lambda: locator)
    missing = load_provider_activation_receipt()
    assert missing.status == "MISSING"
    locator.parent.mkdir(parents=True)
    locator.write_text(json.dumps(_receipt_payload(root)), encoding="utf-8")
    current = load_provider_activation_receipt()
    assert current.status == "CURRENT"
    scanner_source = root / "execution_control/consumer_scan.py"
    scanner_source.write_text("scanner drift", encoding="utf-8")
    assert load_provider_activation_receipt().status == "STALE"

    comparable = []
    for status in ("MISSING", "STALE", "CURRENT"):
        policy = _policy_for_receipt(ProviderReceiptLoadV1(status, (), None))
        comparable.append(
            (
                policy.effective_writer_mode,
                policy.budget.as_dict(),
                policy.reason_codes,
                policy.mutation_count,
            )
        )
        assert policy.candidate_receipt_status == status
    assert len(set(map(repr, comparable))) == 1
    assert comparable[0][0] == "enforce-new"
    assert _policy_for_receipt(ProviderReceiptLoadV1("BLOCKED", (), None)).effective_writer_mode == "blocked"

    monkeypatch.setattr(
        "meta_flow.execution_control.migration.load_provider_activation_receipt",
        lambda: missing,
    )
    assert current_execution_control_policy().budget.as_dict() == {
        "primary_max": 1,
        "auxiliary_max": 0,
        "repair_max": 0,
        "concurrent_write_max": 1,
    }


def test_receipt_schema_mutants_and_legacy_materializer_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "meta_flow"
    _write_package_sources(root)
    locator = _receipt_locator(root)
    monkeypatch.setattr("meta_flow.execution_control.migration._package_root", lambda: root)
    monkeypatch.setattr("meta_flow.execution_control.migration._receipt_path", lambda: locator)
    payload = _receipt_payload(root)
    receipt = ProviderActivationReceiptV1.from_mapping(payload)
    assert receipt.as_dict() == payload
    with pytest.raises(ValueError, match="fields mismatch"):
        ProviderActivationReceiptV1.from_mapping({**payload, "caller_path": "bad"})

    for field, value in (
        ("package_name", "not-meta-flow"),
        ("package_version", "9.9.9"),
        ("generator_identity", "caller-generator"),
        ("policy_revision", 2),
        ("context_revision", 2),
        ("cohort_revision", 2),
    ):
        mutated = {**payload, field: value}
        mutated["receipt_digest"] = ProviderActivationReceiptV1.digest_payload(mutated)
        with pytest.raises(UnknownProviderContractError):
            ProviderActivationReceiptV1.from_mapping(mutated)

    evidence_mutants = []
    missing = dict(payload["evidence_digests"])
    missing.pop(next(iter(missing)))
    evidence_mutants.append(missing)
    extra = dict(payload["evidence_digests"])
    extra["candidate_targeted.extra"] = SHA
    evidence_mutants.append(extra)
    bad_hex = dict(payload["evidence_digests"])
    bad_hex[next(iter(bad_hex))] = "G" * 64
    evidence_mutants.append(bad_hex)
    for evidence_mutant in evidence_mutants:
        mutated = {**payload, "evidence_digests": evidence_mutant}
        mutated["receipt_digest"] = ProviderActivationReceiptV1.digest_payload(mutated)
        with pytest.raises(ValueError, match="evidence digests invalid"):
            ProviderActivationReceiptV1.from_mapping(mutated)

    unsafe_manifest = [dict(item) for item in payload["qualified_source_manifest"]]
    unsafe_manifest[0]["ref"] = ""
    mutated = {**payload, "qualified_source_manifest": unsafe_manifest}
    mutated["qualified_source_set_digest"] = canonical_digest(unsafe_manifest)
    mutated["receipt_digest"] = ProviderActivationReceiptV1.digest_payload(mutated)
    with pytest.raises(ValueError, match="manifest ref"):
        ProviderActivationReceiptV1.from_mapping(mutated)

    evidence = build_provider_qualification_evidence(
        {
            "cohort_revision": 1,
            "context_revision": 1,
            "evidence_digests": _evidence_digests(),
        }
    )
    assert tuple(inspect.signature(load_provider_activation_receipt).parameters) == ()
    assert tuple(inspect.signature(materialize_provider_activation_receipt).parameters) == (
        "evidence",
    )
    assert materialize_provider_activation_receipt(receipt).decision == "BLOCKED"
    blocked = materialize_provider_activation_receipt(evidence)
    assert blocked.decision == "BLOCKED"
    assert blocked.reason_codes == ("MATERIALIZATION_APPLY_REQUIRED",)
    assert blocked.mutation_count == 0 and not locator.exists()


def _authority() -> NativeMaterializationAuthorityV1:
    evidence = build_provider_qualification_evidence(
        {
            "cohort_revision": 1,
            "context_revision": 1,
            "evidence_digests": _evidence_digests(),
        }
    )
    return NativeMaterializationAuthorityV1(
        release_oid=OID,
        process_oid=OID,
        scope_digest=SHA,
        freeze_payload_digest=(
            "acb49951388d83249acd5474db32fe33a1568943785ba38500333bdddb74a084"
        ),
        cp7_event_id="CP7-CR069-S5-CANDIDATE-PASS-V1",
        cp7_result_digest=SHA,
        checkpoint_event_digest=SHA,
        return_digest=SHA,
        evidence_digest=SHA,
        dispatch_digest=SHA,
        scanner_receipt_digest=SHA,
        final_manifest_receipt_digest=SHA,
        provider_evidence=evidence,
        authorization_digest=SHA,
    )


def _snapshot(release_root: Path, locator: Path, *, release_oid: str = OID) -> _MaterializationSnapshotV1:
    return _MaterializationSnapshotV1(
        release_root=release_root,
        release_identity_digest=SHA,
        process_identity_digest="c" * 64,
        release_oid=release_oid,
        process_oid=OID,
        dirty_digest="d" * 64,
        route_digest="e" * 64,
        target_preimage_digest=_path_preimage_digest(locator),
        authority=_authority(),
    )


def _write_native_authority(
    process_root: Path,
    *,
    cp7_decision: str = "PASS",
    mutant: str = "",
) -> Path:
    event_id = "CP7-CR069-S5-CANDIDATE-PASS-V1"
    refs = {
        "cp7_result": "checks/CP7-S5.result.json",
        "checkpoint_ledger": "state/CHECKPOINT-LEDGER.ndjson",
        "return": "returns/STORY-CR069-F1-S5.CP7.return.json",
        "evidence": "evidence/STORY-CR069-F1-S5.CP7.index.json",
        "dispatch": "checks/CR-069-S5-CP7-DISPATCH.json",
        "scanner_receipt": "checks/CR-069-S5-SCANNER-QUALIFICATION-CURRENT.receipt.json",
        "final_manifest_receipt": "checks/CR-069-S5-FINAL-CONSUMER-MANIFEST-CURRENT.receipt.json",
    }
    common = {
        "schema_version": 1,
        "project_id": "meta-flow",
        "cr_id": "CR-069",
        "story_id": "STORY-OTHER" if mutant == "cross-unit" else "STORY-CR069-F1-S5",
        "revision": 9,
        "release_oid": OID,
        "process_oid": OID,
        "scope_digest": SHA,
        "cp7_event_id": event_id,
    }
    payloads: dict[str, dict[str, object]] = {}

    def store(name: str, payload: dict[str, object], digest_field: str) -> tuple[str, str]:
        payload[digest_field] = canonical_digest(payload)
        path = process_root / refs[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        payloads[name] = payload
        return hashlib.sha256(path.read_bytes()).hexdigest(), str(payload[digest_field])

    dispatch_sha, dispatch_digest = store(
        "dispatch",
        {
            **common,
            "contract_id": "CR069-S5-META-QA-CRITICAL-DISPATCH-V1",
            "decision": "COMPLETED",
            "agent_id": "agent-qa-critical",
            "thread_id": "thread-qa-critical",
            "tool_name": "send_message" if mutant == "wrong-tool" else "spawn_agent",
            "codex_agent_name": "meta-qa" if mutant == "wrong-role" else "meta-qa-critical",
            "reasoning_profile": "meta-qa-critical",
            "dispatch_trigger": "cp7-candidate-independent-qa",
            "completed_at": "2026-08-09T00:00:00Z",
        },
        "dispatch_digest",
    )
    scanner_sha, scanner_digest = store(
        "scanner_receipt",
        {
            **common,
            "contract_id": "CR069-S5-SCANNER-QUALIFICATION-RECEIPT-V1",
            "status": "current",
            "decision": "PASS",
            "dispatch_ref": f"process/{refs['dispatch']}",
            "dispatch_sha256": dispatch_sha,
            "dispatch_digest": dispatch_digest,
            "scanner_callable_ref": (
                "caller.scanner" if mutant == "wrong-scanner" else
                "meta_flow.execution_control.consumer_scan.scan_execution_control_consumers"
            ),
            "scanner_source_ref": "meta_flow/execution_control/consumer_scan.py",
            "scanner_source_digest": SHA,
            "scanner_contract_digest": SHA,
            "parser_identity": "cpython-ast-python-3.11",
            "profile_digest": SHA,
            "command_identity_digest": SHA,
            "source_set_digest": SHA,
            "subject_set_digest": SHA,
            "edge_set_digest": SHA,
            "classification_digest": SHA,
            "source_count": 262,
            "subject_count": 82,
            "edge_count": 147,
            "classification_count": 16,
            "static_exit_counters": {
                "syntax_error_count": 0,
                "unclassified_consumer_count": 0,
                "unclassified_legacy_writer_call_count": 0,
                "unfingerprinted_scanned_or_excluded_path_count": 0,
                "unresolved_exclusion_count": 0,
                "unresolved_path_count": 0,
                "security_call_edge_count": 0,
                "explicit_dispatch_error_count": 0,
            },
        },
        "receipt_digest",
    )
    final_sha, final_digest = store(
        "final_manifest_receipt",
        {
            **common,
            "contract_id": "CR069-S5-FINAL-CONSUMER-MANIFEST-RECEIPT-V1",
            "status": "current",
            "decision": "PASS",
            "dispatch_ref": f"process/{refs['dispatch']}",
            "dispatch_sha256": dispatch_sha,
            "dispatch_digest": dispatch_digest,
            "scanner_receipt_ref": f"process/{refs['scanner_receipt']}",
            "scanner_receipt_sha256": scanner_sha,
            "scanner_receipt_digest": scanner_digest,
            "validation_receipts": _evidence_digests(),
            "dynamic_exit_counters": {
                "impacted_consumer_failure_count": 0,
                "unresolved_fixture_capability_count": 0,
                "unresolved_consumer_closure_count": 0,
            },
        },
        "receipt_digest",
    )
    evidence_sha, evidence_digest = store(
        "evidence",
        {
            **common,
            "contract_id": "CR069-S5-CP7-EVIDENCE-INDEX-V1",
            "decision": "PASS",
            "dispatch_ref": f"process/{refs['dispatch']}",
            "dispatch_sha256": dispatch_sha,
            "dispatch_digest": dispatch_digest,
            "scanner_receipt_ref": f"process/{refs['scanner_receipt']}",
            "scanner_receipt_sha256": scanner_sha,
            "scanner_receipt_digest": scanner_digest,
            "final_manifest_receipt_ref": f"process/{refs['final_manifest_receipt']}",
            "final_manifest_receipt_sha256": final_sha,
            "final_manifest_receipt_digest": final_digest,
            "provider_evidence_digests": _evidence_digests(),
        },
        "evidence_digest",
    )
    return_sha, return_digest = store(
        "return",
        {
            **common,
            "contract_id": "CR069-S5-CP7-RETURN-V1",
            "checkpoint": "CP7",
            "decision": "PASS",
            "evidence_ref": f"process/{refs['evidence']}",
            "evidence_sha256": evidence_sha,
            "evidence_digest": evidence_digest,
            "dispatch_ref": f"process/{refs['dispatch']}",
            "dispatch_sha256": dispatch_sha,
            "dispatch_digest": dispatch_digest,
            "scanner_receipt_ref": f"process/{refs['scanner_receipt']}",
            "scanner_receipt_sha256": scanner_sha,
            "scanner_receipt_digest": scanner_digest,
            "final_manifest_receipt_ref": f"process/{refs['final_manifest_receipt']}",
            "final_manifest_receipt_sha256": final_sha,
            "final_manifest_receipt_digest": final_digest,
        },
        "return_digest",
    )
    cp7_sha, cp7_digest = store(
        "cp7_result",
        {
            **common,
            "contract_id": "CR069-S5-CP7-RESULT-V1",
            "checkpoint": "CP7",
            "decision": cp7_decision,
            "return_ref": f"process/{refs['return']}",
            "return_sha256": return_sha,
            "return_digest": return_digest,
            "evidence_ref": f"process/{refs['evidence']}",
            "evidence_sha256": evidence_sha,
            "evidence_digest": evidence_digest,
            "dispatch_ref": f"process/{refs['dispatch']}",
            "dispatch_sha256": dispatch_sha,
            "dispatch_digest": dispatch_digest,
            "scanner_receipt_ref": f"process/{refs['scanner_receipt']}",
            "scanner_receipt_sha256": scanner_sha,
            "scanner_receipt_digest": scanner_digest,
            "final_manifest_receipt_ref": f"process/{refs['final_manifest_receipt']}",
            "final_manifest_receipt_sha256": final_sha,
            "final_manifest_receipt_digest": final_digest,
        },
        "result_digest",
    )
    ledger = {
        **common,
        "contract_id": "CR069-S5-CHECKPOINT-LEDGER-EVENT-V1",
        "event_id": event_id if mutant != "wrong-event-id" else f"{event_id}-OTHER",
        "event_type": (
            "cr069_s5_candidate_authority"
            if mutant != "wrong-event-type"
            else "checkpoint_result"
        ),
        "checkpoint": "CP7",
        "decision": "PASS",
        "result_ref": (
            f"process/{refs['cp7_result']}"
            if mutant != "wrong-result-ref"
            else "process/checks/OTHER.result.json"
        ),
        "cp7_result_ref": f"process/{refs['cp7_result']}",
        "cp7_result_sha256": cp7_sha,
        "cp7_result_digest": cp7_digest,
        "previous_event_digest": "",
    }
    ledger["event_digest"] = canonical_digest(ledger)
    ledger_path = process_root / refs["checkpoint_ledger"]
    append_event(ledger_path, ledger)
    if mutant == "non-head":
        non_head = {
            **ledger,
            "decision": "BLOCKED",
            "previous_event_digest": ledger["event_digest"],
        }
        non_head["event_digest"] = canonical_digest(
            {key: value for key, value in non_head.items() if key != "event_digest"}
        )
        append_event(ledger_path, non_head)
    ledger_sha = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    ledger_digest = str(ledger["event_digest"])
    raw_digests = {
        "cp7_result": cp7_sha,
        "checkpoint_ledger": ledger_sha,
        "return": return_sha,
        "evidence": evidence_sha,
        "dispatch": dispatch_sha,
        "scanner_receipt": scanner_sha,
        "final_manifest_receipt": final_sha,
    }
    native_chain_digest = canonical_digest(
        {
            "release_oid": OID,
            "process_oid": OID,
            "scope_digest": SHA,
            "cp7_event_id": event_id,
            "raw_preimages": raw_digests,
            "typed_digests": {
                "dispatch": dispatch_digest,
                "scanner_receipt": scanner_digest,
                "final_manifest_receipt": final_digest,
                "evidence": evidence_digest,
                "return": return_digest,
                "cp7_result": cp7_digest,
                "checkpoint_head": ledger_digest,
            },
        }
    )
    authority: dict[str, object] = {
        **common,
        "contract_id": "CR069-S5-MATERIALIZATION-AUTHORITY-V1",
        "decision": "APPROVED",
        "operation": "provider-receipt-create-only",
        "target_ref": FIXED_RECEIPT_REF,
        "freeze_payload_digest": "acb49951388d83249acd5474db32fe33a1568943785ba38500333bdddb74a084",
        "provider_evidence_digests": _evidence_digests(),
        "native_chain_digest": native_chain_digest,
        "checkpoint_event_digest": ledger_digest,
        "scanner_qualification_receipt_digest": scanner_digest,
        "final_manifest_receipt_digest": final_digest,
        "cp7_result_digest": cp7_digest,
        "return_digest": return_digest,
        "evidence_digest": evidence_digest,
        "dispatch_digest": dispatch_digest,
    }
    for name, digest in raw_digests.items():
        authority[f"{name}_ref"] = f"process/{refs[name]}"
        authority[f"{name}_sha256"] = digest
    if mutant == "closed-field":
        authority["caller_pass"] = True
    authority["authorization_digest"] = canonical_digest(
        {
            "contract_id": "CR069-S5-MATERIALIZATION-AUTHORITY-V1",
            "operation": "provider-receipt-create-only",
            "target_ref": authority["target_ref"],
            "cr_id": "CR-069",
            "story_id": "STORY-CR069-F1-S5",
            "revision": 9,
            "release_oid": OID,
            "process_oid": OID,
            "scope_digest": SHA,
            "native_chain_digest": native_chain_digest,
        }
    )
    path = process_root / MATERIALIZATION_AUTHORIZATION_REF
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(authority, sort_keys=True), encoding="utf-8")
    return path


def test_native_materialization_authority_requires_exact_cp7_and_ledger(
    tmp_path: Path,
) -> None:
    process_root = tmp_path / "process"
    authorization_path = _write_native_authority(process_root)
    authority = _load_native_materialization_authority(process_root)
    assert authority.freeze_payload_digest.startswith("acb499")
    assert authority.provider_evidence.evidence_digests

    _write_native_authority(process_root, cp7_decision="BLOCKED")
    with pytest.raises(ValueError, match="CP7_RESULT_NOT_CURRENT_PASS"):
        _load_native_materialization_authority(process_root)

    _write_native_authority(process_root)
    payload = json.loads(authorization_path.read_text(encoding="utf-8"))
    payload["caller_pass"] = True
    payload["authorization_digest"] = canonical_digest(
        {key: value for key, value in payload.items() if key != "authorization_digest"}
    )
    authorization_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="FIELDS_MISMATCH"):
        _load_native_materialization_authority(process_root)

    _write_native_authority(process_root)
    payload = json.loads(authorization_path.read_text(encoding="utf-8"))
    payload["authorization_digest"] = canonical_digest(
        {key: value for key, value in payload.items() if key != "authorization_digest"}
    )
    authorization_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="AUTHORITY_DIGEST_DRIFT"):
        _load_native_materialization_authority(process_root)


@pytest.mark.parametrize(
    "mutant, expected",
    (
        ("wrong-role", "DISPATCH_SEMANTICS_INVALID"),
        ("wrong-tool", "DISPATCH_SEMANTICS_INVALID"),
        ("wrong-scanner", "SCANNER_RECEIPT_SEMANTICS_INVALID"),
        ("cross-unit", "NATIVE_IDENTITY_INVALID"),
        ("non-head", "CHECKPOINT_LEDGER_HEAD_INVALID"),
        ("wrong-event-id", "CHECKPOINT_LEDGER_HEAD_INVALID"),
        ("wrong-event-type", "CHECKPOINT_LEDGER_HEAD_INVALID"),
        ("wrong-result-ref", "CHECKPOINT_LEDGER_HEAD_INVALID"),
        ("closed-field", "AUTHORITY_FIELDS_MISMATCH"),
    ),
)
def test_native_authority_mutants_are_typed_blocked_before_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutant: str,
    expected: str,
) -> None:
    writes: list[Path] = []
    monkeypatch.setattr(
        "meta_flow.execution_control.migration._write_receipt_exclusive",
        lambda path, _raw: writes.append(path),
    )
    process_root = tmp_path / mutant
    _write_native_authority(process_root, mutant=mutant)
    with pytest.raises(ValueError, match=expected):
        _load_native_materialization_authority(process_root)
    assert writes == []


def test_native_authority_rejects_missing_and_minimal_current_receipt_before_writer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    writes: list[Path] = []
    monkeypatch.setattr(
        "meta_flow.execution_control.migration._write_receipt_exclusive",
        lambda path, _raw: writes.append(path),
    )
    process_root = tmp_path / "minimal"
    authority_path = _write_native_authority(process_root)
    dispatch = process_root / "checks/CR-069-S5-CP7-DISPATCH.json"
    dispatch.unlink()
    with pytest.raises(ValueError, match="AUTHORITY_REF_DRIFT"):
        _load_native_materialization_authority(process_root)

    _write_native_authority(process_root)
    scanner = process_root / "checks/CR-069-S5-SCANNER-QUALIFICATION-CURRENT.receipt.json"
    scanner.write_text('{"decision":"PASS","status":"current"}\n', encoding="utf-8")
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    authority["scanner_receipt_sha256"] = hashlib.sha256(scanner.read_bytes()).hexdigest()
    authority_path.write_text(json.dumps(authority, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="SCANNER_RECEIPT_FIELDS_MISMATCH"):
        _load_native_materialization_authority(process_root)
    assert writes == []


def test_direct_mint_low_writer_and_forged_proof_are_zero_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package_root = tmp_path / "meta_flow"
    _write_package_sources(package_root)
    locator = _receipt_locator(package_root)
    monkeypatch.setattr("meta_flow.execution_control.migration._package_root", lambda: package_root)
    monkeypatch.setattr("meta_flow.execution_control.migration._receipt_path", lambda: locator)
    receipt = ProviderActivationReceiptV1.from_mapping(_receipt_payload(package_root))

    assert _mint_materialization_capability(object()) is None
    forged = object.__new__(FreshMaterializationProofV1)
    assert _mint_materialization_capability(forged) is None
    direct = _perform_receipt_create_only(object(), receipt)
    assert direct.decision == "BLOCKED" and direct.mutation_count == 0
    assert not locator.exists()


def test_materialization_requires_fresh_plan_private_single_use_capability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package_root = tmp_path / "meta_flow"
    _write_package_sources(package_root)
    locator = _receipt_locator(package_root)
    monkeypatch.setattr("meta_flow.execution_control.migration._package_root", lambda: package_root)
    monkeypatch.setattr("meta_flow.execution_control.migration._receipt_path", lambda: locator)
    monkeypatch.setattr(
        "meta_flow.execution_control.migration._snapshot_materialization_inputs",
        lambda _root: _snapshot(tmp_path, locator),
    )

    direct = _materialize_provider_activation_receipt_create_only(object())
    assert direct.decision == "BLOCKED" and direct.mutation_count == 0
    assert not locator.exists()

    plan = plan_provider_receipt_materialization(tmp_path)
    assert plan.decision == "READY" and plan.mutation_count == 0
    assert "capability" not in plan.as_dict()
    materialized = apply_provider_receipt_materialization(plan)
    assert materialized.decision == "PASS" and locator.is_file()
    assert materialized.mutation_count == 2
    assert materialized.durable_refs == (
        "meta_flow/execution_control/provider",
        FIXED_RECEIPT_REF,
    )
    replay_plan = apply_provider_receipt_materialization(plan)
    assert replay_plan.decision == "BLOCKED" and replay_plan.mutation_count == 0


def test_capability_target_drift_and_replay_block_before_writer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package_root = tmp_path / "meta_flow"
    _write_package_sources(package_root)
    locator = _receipt_locator(package_root)
    monkeypatch.setattr("meta_flow.execution_control.migration._package_root", lambda: package_root)
    monkeypatch.setattr("meta_flow.execution_control.migration._receipt_path", lambda: locator)
    snapshot = _snapshot(tmp_path, locator)
    monkeypatch.setattr(
        "meta_flow.execution_control.migration._snapshot_materialization_inputs",
        lambda _root: snapshot,
    )
    plan = plan_provider_receipt_materialization(tmp_path)
    proof = _register_fresh_materialization_proof(snapshot, plan)
    assert proof is not None
    capability = _mint_materialization_capability(proof)
    assert capability is not None
    assert _mint_materialization_capability(proof) is None
    locator.parent.mkdir(parents=True)
    locator.write_text("drift", encoding="utf-8")
    receipt = ProviderActivationReceiptV1.from_mapping(_receipt_payload(package_root))
    drift = _perform_receipt_create_only(capability, receipt)
    assert drift.decision == "BLOCKED" and drift.mutation_count == 0
    assert locator.read_text(encoding="utf-8") == "drift"
    replay = _materialize_provider_activation_receipt_create_only(capability)
    assert replay.decision == "BLOCKED" and replay.mutation_count == 0

    wrong_plan = replace(plan, release_oid="f" * 40)
    assert _register_fresh_materialization_proof(snapshot, wrong_plan) is None


def test_apply_fresh_authority_drift_blocks_before_capability_and_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package_root = tmp_path / "meta_flow"
    _write_package_sources(package_root)
    locator = _receipt_locator(package_root)
    monkeypatch.setattr("meta_flow.execution_control.migration._package_root", lambda: package_root)
    monkeypatch.setattr("meta_flow.execution_control.migration._receipt_path", lambda: locator)
    snapshots = iter(
        (
            _snapshot(tmp_path, locator),
            _snapshot(tmp_path, locator, release_oid="f" * 40),
        )
    )
    monkeypatch.setattr(
        "meta_flow.execution_control.migration._snapshot_materialization_inputs",
        lambda _root: next(snapshots),
    )
    plan = plan_provider_receipt_materialization(tmp_path)
    blocked = apply_provider_receipt_materialization(plan)
    assert blocked.decision == "BLOCKED"
    assert blocked.reason_codes == ("MATERIALIZATION_FRESH_PREIMAGE_DRIFT",)
    assert blocked.mutation_count == 0 and not locator.exists()


def test_apply_rejects_cross_clone_runtime_root_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root_a = tmp_path / "clone-a"
    root_b = tmp_path / "clone-b"
    package_root = root_a / "meta_flow"
    _write_package_sources(package_root)
    locator = _receipt_locator(package_root)
    monkeypatch.setattr("meta_flow.execution_control.migration._package_root", lambda: package_root)
    monkeypatch.setattr("meta_flow.execution_control.migration._receipt_path", lambda: locator)
    first = replace(
        _snapshot(root_a, locator),
        release_identity_digest="1" * 64,
        process_identity_digest="2" * 64,
    )
    second = replace(
        _snapshot(root_b, locator),
        release_identity_digest="3" * 64,
        process_identity_digest="4" * 64,
    )
    monkeypatch.setattr(
        "meta_flow.execution_control.migration._snapshot_materialization_inputs",
        lambda root: first if root == root_a else second,
    )
    plan = plan_provider_receipt_materialization(root_a)
    forged_runtime_root = replace(plan, _release_root=root_b)
    blocked = apply_provider_receipt_materialization(forged_runtime_root)
    assert blocked.decision == "BLOCKED"
    assert blocked.reason_codes == ("MATERIALIZATION_FRESH_PREIMAGE_DRIFT",)
    assert not locator.exists()


def test_gated_materializer_accounts_partial_write_exactly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "meta_flow"
    _write_package_sources(root)
    locator = _receipt_locator(root)
    monkeypatch.setattr("meta_flow.execution_control.migration._package_root", lambda: root)
    monkeypatch.setattr("meta_flow.execution_control.migration._receipt_path", lambda: locator)
    snapshot = _snapshot(tmp_path, locator)
    monkeypatch.setattr(
        "meta_flow.execution_control.migration._snapshot_materialization_inputs",
        lambda _root: snapshot,
    )

    def partial_write(path: Path, _rendered: bytes) -> None:
        path.write_bytes(b"partial")
        raise OSError("injected write failure")

    monkeypatch.setattr(
        "meta_flow.execution_control.migration._write_receipt_exclusive", partial_write
    )
    partial = apply_provider_receipt_materialization(
        plan_provider_receipt_materialization(tmp_path)
    )
    assert partial.decision == "PARTIAL_MUTATION"
    assert partial.mutation_count == 2
    assert partial.durable_refs[-1] == FIXED_RECEIPT_REF


def _unit(name: str) -> ExecutionUnitV1:
    return ExecutionUnitV1(
        unit_id=name,
        root_concept="execution-control",
        slice_id="S5",
        container_role="primary",
        revision=1,
        supersedes_unit_id="",
        contract_ref="process/contracts/execution-control-v1.json",
        contract_digest=SHA,
    )


@dataclass(frozen=True)
class _Scope:
    digest: str = SHA


@dataclass(frozen=True)
class _Budget:
    reads: int = 5


@dataclass(frozen=True)
class _Work:
    work_id: str = "W-NEW"
    project_id: str = "demo"
    work_ref: str = "works/W-NEW/WORK.yaml"
    scope: _Scope = _Scope()
    budget: _Budget = _Budget()
    risk_profile: str = "G2"
    status: str = "planned"
    execution_unit: ExecutionUnitV1 | None = None


def _project(refs: tuple[str, ...]) -> Project:
    return Project(1, "demo", "demo", "active", active_work_refs=refs)


def test_active_inventory_consumes_exact_declared_refs_only_and_detects_all_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "works/W-1/WORK.yaml": _Work("W-1", "demo", "works/W-1/WORK.yaml", execution_unit=_unit("W-1")),
        "works/W-2/WORK.yaml": _Work("W-2", "demo", "works/W-2/WORK.yaml", execution_unit=_unit("W-2")),
        "works/LEGACY/WORK.yaml": _Work("LEGACY", "demo", "works/LEGACY/WORK.yaml"),
    }
    monkeypatch.setattr(
        "meta_flow.execution_control.runtime_context.load_work",
        lambda _root, work_id: values[f"works/{work_id}/WORK.yaml"],
    )
    assert project_active_execution_inventory(Path("/process"), _project(())).decision == "READY"
    one = project_active_execution_inventory(Path("/process"), _project(("works/W-1/WORK.yaml",)))
    assert one.decision == "READY" and one.object_count == 1
    many = project_active_execution_inventory(
        Path("/process"), _project(("works/W-1/WORK.yaml", "works/W-2/WORK.yaml")), max_objects=2
    )
    assert many.decision == "READY" and many.object_count == 2
    legacy = project_active_execution_inventory(Path("/process"), _project(("works/LEGACY/WORK.yaml",)))
    assert legacy.decision == "READY"
    assert legacy.legacy_refs == ("works/LEGACY/WORK.yaml",) and legacy.objects_read == 1
    duplicate = project_active_execution_inventory(
        Path("/process"), _project(("works/W-1/WORK.yaml", "works/W-1/WORK.yaml"))
    )
    assert duplicate.decision == "BLOCKED" and "ACTIVE_INVENTORY_DUPLICATE_REF" in duplicate.reason_codes
    dangling = project_active_execution_inventory(Path("/process"), _project(("works/MISSING/WORK.yaml",)))
    assert dangling.decision == "BLOCKED" and "ACTIVE_INVENTORY_DANGLING_REF" in dangling.reason_codes
    for unsafe_ref in (
        "works/../W-1/WORK.yaml",
        "not-works/W-1/WORK.yaml",
        "works/../WORK.yaml",
        "works/not safe/WORK.yaml",
    ):
        unsafe = project_active_execution_inventory(Path("/process"), _project((unsafe_ref,)))
        assert unsafe.decision == "BLOCKED"
        assert unsafe.reason_codes == ("ACTIVE_INVENTORY_UNSAFE_REF",)
        assert unsafe.objects_read == 0
    over = project_active_execution_inventory(
        Path("/process"), _project(("works/W-1/WORK.yaml", "works/W-2/WORK.yaml")), max_objects=1
    )
    assert over.decision == "BLOCKED" and over.reason_codes == ("ACTIVE_INVENTORY_BUDGET_EXCEEDED",)


def test_context_is_release_root_only_and_plan_apply_are_distinct(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process_root = tmp_path / "process-repo"
    missing_receipt = tmp_path / "missing-provider-receipt.json"
    project = _project(())
    monkeypatch.setattr(
        "meta_flow.execution_control.migration._receipt_path",
        lambda: missing_receipt,
    )
    monkeypatch.setattr(
        "meta_flow.execution_control.runtime_context.require_project_process_route",
        lambda root, project_id: type("Route", (), {"project_root": root, "process_root": process_root, "project_id": project_id, "route_mode": "sibling-binding"})(),
    )
    monkeypatch.setattr("meta_flow.execution_control.runtime_context.load_project", lambda _root: project)
    monkeypatch.setattr(
        "meta_flow.execution_control.runtime_context._repository_facts",
        lambda _release, _process: (OID, OID, SHA, SHA),
    )
    work = _Work(execution_unit=_unit("W-NEW"))
    plan = build_execution_control_context(tmp_path, work, operation="plan")
    apply = build_execution_control_context(tmp_path, work, operation="apply")
    assert plan.decision == apply.decision == "READY"
    assert plan is not apply
    assert plan.operation == "plan" and apply.operation == "apply"
    assert plan.release_root_identity and plan.process_root_identity
    assert plan.release_root_identity != plan.process_root_identity
    assert plan.provider_receipt_status == "MISSING"
    assert plan.context_digest != apply.context_digest


def test_context_root_identities_change_with_canonical_release_or_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release_a, release_b = tmp_path / "release-a", tmp_path / "release-b"
    process_a, process_b = tmp_path / "process-a", tmp_path / "process-b"
    routes = {release_a.resolve(): process_a, release_b.resolve(): process_b}
    monkeypatch.setattr(
        "meta_flow.execution_control.runtime_context.require_project_process_route",
        lambda root, project_id: type("Route", (), {"project_root": root, "process_root": routes[root], "project_id": project_id, "route_mode": "sibling-binding"})(),
    )
    monkeypatch.setattr("meta_flow.execution_control.runtime_context.load_project", lambda _root: _project(()))
    monkeypatch.setattr(
        "meta_flow.execution_control.runtime_context._repository_facts", lambda *_: (OID, OID, SHA, SHA)
    )
    work = _Work(execution_unit=_unit("W-NEW"))
    first = build_execution_control_context(release_a, work, operation="plan")
    second = build_execution_control_context(release_b, work, operation="plan")
    assert first.release_root_identity != second.release_root_identity
    assert first.process_root_identity != second.process_root_identity


def test_repository_facts_use_frozen_porcelain_v2_untracked_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(_root: Path, *args: str) -> str:
        calls.append(args)
        return OID + "\n" if args[:2] == ("rev-parse", "HEAD") else ""

    monkeypatch.setattr("meta_flow.execution_control.runtime_context._git_value", fake_git)
    _repository_facts(tmp_path / "release", tmp_path / "process")
    assert calls.count(("status", "--porcelain=v2", "-z", "--untracked-files=all")) == 2


def test_context_binds_route_oid_dirty_scope_authorization_profile_target_and_active_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process_root = tmp_path / "process-repo"
    work = _Work(execution_unit=_unit("W-NEW"))
    monkeypatch.setattr(
        "meta_flow.execution_control.runtime_context.require_project_process_route",
        lambda root, project_id: type("Route", (), {"project_root": root, "process_root": process_root, "project_id": project_id, "route_mode": "sibling-binding"})(),
    )
    monkeypatch.setattr("meta_flow.execution_control.runtime_context.load_project", lambda _root: _project(()))
    monkeypatch.setattr(
        "meta_flow.execution_control.runtime_context._repository_facts",
        lambda _release, _process: (OID, OID, SHA, SHA),
    )
    context = build_execution_control_context(tmp_path, work, operation="plan")
    for field in (
        "route_digest", "release_oid", "process_oid", "dirty_path_digest", "scope_digest",
        "authorization_digest", "profile_digest", "target_preimage_digest", "project_active_owner_digest",
    ):
        assert getattr(context, field)
    assert context.target_preimage_digest != SHA  # missing target is a real bound fact, not caller input
    assert isinstance(context.inventory, ActiveExecutionInventoryV1)
    assert context.admission_facts().inventory_digest == execution_inventory_digest(
        context.inventory.units
    )


def test_request_candidate_is_closed_digest_bound_and_not_authorization() -> None:
    content = "# REQUEST\n\n确定性请求。\n".encode()
    candidate = RequestMaterializationCandidateV1.build(
        request_ref="works/W-NEW/REQUEST.md",
        content_bytes=content,
        source_kind="evolution-package",
        source_ref="evolution/EV-1.yaml",
        source_digest=SHA,
        before_preimage_digest="b" * 64,
    )
    payload = {
        "schema_version": candidate.schema_version,
        "request_ref": candidate.request_ref,
        "content_bytes": candidate.content_bytes,
        "content_digest": candidate.content_digest,
        "source_kind": candidate.source_kind,
        "source_ref": candidate.source_ref,
        "source_digest": candidate.source_digest,
        "before_preimage_digest": candidate.before_preimage_digest,
        "candidate_digest": candidate.candidate_digest,
    }
    assert RequestMaterializationCandidateV1.from_mapping(payload) == candidate
    with pytest.raises(ValueError, match="fields mismatch"):
        RequestMaterializationCandidateV1.from_mapping(
            {**payload, "authorization_digest": SHA}
        )
    with pytest.raises(ValueError, match="content digest drift"):
        RequestMaterializationCandidateV1.from_mapping(
            {**payload, "content_bytes": b"different"}
        )
    with pytest.raises(ValueError, match="candidate digest drift"):
        RequestMaterializationCandidateV1.from_mapping(
            {**payload, "source_digest": "d" * 64}
        )
