"""CAC-02：validator 漂移矩阵（IF-6，18 checks）+ IF-14 授权证据核验矩阵。

漂移注入只改单一字段，断言 typed code 精确命中（唯一/预期集）；
IF-14 覆盖语义授权、七要素 registry、时间不变量、三源 consumption。
"""

from __future__ import annotations

import copy

import pytest
from conftest import (
    D64,
    finalize,
    frozen_identity,
    provenance,
    result_document,
)
from conftest import (
    canonical_digest as canonical_digest_of,
)

from meta_flow.ingestion.consumer_acceptance_validator import (
    AUTHORIZATION_CONSUMPTION_UNPROVEN,
    AUTHORIZATION_DIGEST_MISMATCH,
    AUTHORIZATION_EVIDENCE_MISSING,
    AUTHORIZATION_EXECUTION_OUT_OF_WINDOW,
    AUTHORIZATION_EXPIRED,
    AUTHORIZATION_INHERITED,
    AUTHORIZATION_OBJECT_CONFUSED,
    AUTHORIZATION_OPERATION_MISMATCH,
    AUTHORIZATION_PROVENANCE_UNTRUSTED,
    AUTHORIZATION_TIME_INVARIANT_VIOLATED,
    COMMAND_IDENTITY_MISMATCH,
    DIGEST_MISMATCH_BUNDLE_MANIFEST,
    DIGEST_MISMATCH_RECEIPT,
    DIGEST_MISMATCH_RESULT,
    DIGEST_MISMATCH_SDIST,
    DIGEST_MISMATCH_SIDECAR,
    DIGEST_MISMATCH_SOURCE_TREE,
    DIGEST_MISMATCH_WHEEL,
    FINGERPRINT_MISMATCH_ENVIRONMENT,
    FINGERPRINT_MISMATCH_PROFILE,
    FINGERPRINT_MISMATCH_PROVIDER,
    INSTALLED_ARTIFACT,
    OID_MISMATCH_PROCESS,
    OID_MISMATCH_QUANT_LAB_PROCESS,
    OID_MISMATCH_QUANT_LAB_RELEASE,
    OID_MISMATCH_RELEASE,
    PROVIDER_IDENTITY_MISMATCH,
    SEMVER_MISMATCH,
    SOURCE_CANDIDATE,
    ProvenanceBundle,
    compute_result_digest,
    validate_identity,
    verify_replay_execution_authorization,
)

# (漂移说明, mutate(payload), frozen 改键, frozen 改值, 预期 code)
DRIFT_CASES = [
    ("result_digest", lambda d: d["execution"].__setitem__("result_digest", "f" * 64), None, None, DIGEST_MISMATCH_RESULT),
    ("source_tree(B1)", None, "source_tree_digest", "b" * 64, DIGEST_MISMATCH_SOURCE_TREE),
    ("bundle_manifest", None, "bundle_manifest_digest", "b" * 64, DIGEST_MISMATCH_BUNDLE_MANIFEST),
    ("wheel", lambda d: d["artifact"]["assets"].__setitem__("wheel", "b" * 64), None, None, DIGEST_MISMATCH_WHEEL),
    ("sdist", lambda d: d["artifact"]["assets"].__setitem__("sdist", "b" * 64), None, None, DIGEST_MISMATCH_SDIST),
    ("receipt", lambda d: d["artifact"]["assets"].__setitem__("receipt", "b" * 64), None, None, DIGEST_MISMATCH_RECEIPT),
    ("sidecar", lambda d: d["artifact"]["assets"].__setitem__("sidecar", "b" * 64), None, None, DIGEST_MISMATCH_SIDECAR),
    ("source_release_oid", lambda d: d["artifact"].__setitem__("source_release_oid", "1" * 40), None, None, OID_MISMATCH_RELEASE),
    ("source_process_oid", lambda d: d["artifact"].__setitem__("source_process_oid", "1" * 40), None, None, OID_MISMATCH_PROCESS),
    ("quant_lab_release", lambda d: d["execution"].__setitem__("quant_lab_release_oid", "1" * 40), None, None, OID_MISMATCH_QUANT_LAB_RELEASE),
    ("quant_lab_process", lambda d: d["execution"].__setitem__("quant_lab_process_oid", "1" * 40), None, None, OID_MISMATCH_QUANT_LAB_PROCESS),
    ("profile_fp", lambda d: d["execution"].__setitem__("profile_fingerprint", "b" * 64), None, None, FINGERPRINT_MISMATCH_PROFILE),
    ("env_fp", lambda d: d["execution"].__setitem__("environment_fingerprint", "b" * 64), None, None, FINGERPRINT_MISMATCH_ENVIRONMENT),
    ("provider_fp", lambda d: d["execution"].__setitem__("provider_fingerprint", "b" * 64), None, None, FINGERPRINT_MISMATCH_PROVIDER),
    ("command_identity", lambda d: d["execution"].__setitem__("command_identity", "other-cmd"), None, None, COMMAND_IDENTITY_MISMATCH),
    ("semver", lambda d: d["artifact"].__setitem__("semver", "9.9.9"), None, None, SEMVER_MISMATCH),
    ("provider_identity", lambda d: d["artifact"].__setitem__("provider_identity", "other-host"), None, None, PROVIDER_IDENTITY_MISMATCH),
]


def _b2_pair():
    return finalize(result_document("R-DRIFT", INSTALLED_ARTIFACT))


def _b1_pair():
    return finalize(result_document("R-DRIFT1", SOURCE_CANDIDATE))


class TestIdentityDriftMatrix:
    @pytest.mark.parametrize(
        ("label", "mutate", "frozen_key", "frozen_value", "expected"),
        [(c[0], c[1], c[2], c[3], c[4]) for c in DRIFT_CASES if not c[0].startswith("source_tree")],
    )
    def test_installed_drift_hits_single_code(self, label, mutate, frozen_key, frozen_value, expected):
        document, _ = _b2_pair()
        if mutate:
            mutate(document)
        frozen = frozen_identity(INSTALLED_ARTIFACT)
        if frozen_key:
            object.__setattr__(frozen, frozen_key, frozen_value)
        report = validate_identity(document, frozen)
        assert not report.ok and expected in report.codes, (label, report.codes)

    def test_b1_source_tree_drift(self):
        document, _ = _b1_pair()
        frozen = frozen_identity(SOURCE_CANDIDATE)
        object.__setattr__(frozen, "source_tree_digest", "b" * 64)
        report = validate_identity(document, frozen)
        assert not report.ok and DIGEST_MISMATCH_SOURCE_TREE in report.codes

    def test_happy_b1_b2_no_drift(self):
        for variant in (SOURCE_CANDIDATE, INSTALLED_ARTIFACT):
            document, _ = finalize(result_document(f"R-{variant[:4]}", variant))
            report = validate_identity(document, frozen_identity(variant))
            assert report.ok, (variant, report.codes, report.drifts)


class TestResultDigestSlot:
    def test_slot_zeroed_not_self_referential(self):
        document, _ = _b2_pair()
        d1 = compute_result_digest(document)
        document["execution"]["result_digest"] = D64  # 槽位变化不影响 digest
        assert compute_result_digest(document) == d1


def _happy_report():
    document, evidence = _b2_pair()
    return verify_replay_execution_authorization(
        result_payload=document,
        authorization_evidence=evidence,
        provenance=provenance(document, evidence),
    ), document, evidence


class TestAuthorizationEvidence:
    def test_happy_ok_execution_ledger_source(self):
        report, _, _ = _happy_report()
        assert report.ok, report.notes
        assert report.consumption_source == "execution-ledger"

    def test_missing_evidence_blocks(self):
        document, _ = _b2_pair()
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=None,
            provenance=provenance(document, {}),
        )
        assert not report.ok and AUTHORIZATION_EVIDENCE_MISSING in report.codes

    def test_inherited_authorization_blocks(self):
        document, evidence = _b2_pair()
        document["authorization"]["authorization_inherited"] = True
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence, provenance=provenance(document, evidence)
        )
        assert not report.ok and AUTHORIZATION_INHERITED in report.codes

    def test_digest_mismatch_blocks(self):
        document, evidence = _b2_pair()
        evidence["principal"] = "someone-else"
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence, provenance=provenance(document, evidence)
        )
        assert not report.ok and AUTHORIZATION_DIGEST_MISMATCH in report.codes

    def test_non_replay_operation_blocks(self):
        document, evidence = _b2_pair()
        evidence["operation"] = "release-publish"
        document["authorization"]["authorization_digest"] = "sha256:" + D64
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence,
            provenance=ProvenanceBundle(issuance_rows=(dict(evidence, authorization_digest=document["authorization"]["authorization_digest"]),)),
        )
        assert not report.ok and AUTHORIZATION_OBJECT_CONFUSED in report.codes

    def test_unbound_scope_blocks(self):
        document, evidence = _b2_pair()
        # scope 双侧同步改并保持 digest 链一致 → 精确触达 scope 绑定检查
        evidence["scope"] = ["release-publish"]  # 授权用途偏移：evidence 侧 scope 与 result 声明不一致
        document["authorization"]["authorization_digest"] = canonical_digest_of(evidence)
        row = dict(evidence)
        row["authorization_digest"] = document["authorization"]["authorization_digest"]
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence,
            provenance=ProvenanceBundle(issuance_rows=(row,), execution_ledger_rows=(row,)),
        )
        assert not report.ok and AUTHORIZATION_OPERATION_MISMATCH in report.codes

    def test_unbound_consumer_project_blocks(self):
        document, evidence = _b2_pair()
        evidence["consumer_project_uid"] = "other-project"
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence, provenance=provenance(document, evidence)
        )
        assert not report.ok and AUTHORIZATION_OPERATION_MISMATCH in report.codes

    def test_registry_unreachable_blocks(self):
        document, evidence = _b2_pair()
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence,
            provenance=ProvenanceBundle(issuance_rows=None, execution_ledger_rows=provenance(document, evidence).execution_ledger_rows),
        )
        assert not report.ok and AUTHORIZATION_PROVENANCE_UNTRUSTED in report.codes

    def test_registry_seven_element_miss_blocks(self):
        document, evidence = _b2_pair()
        row = dict(evidence)
        row["authorization_digest"] = "sha256:" + "0" * 64  # 行 digest 与声明不符
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence,
            provenance=ProvenanceBundle(issuance_rows=(row,)),
        )
        assert not report.ok and AUTHORIZATION_PROVENANCE_UNTRUSTED in report.codes

    def test_inverted_validity_blocks_expired(self):
        document, evidence = _b2_pair()
        evidence["validity"] = {"not_before": "2026-09-30T00:00:00Z", "not_after": "2026-08-27T00:00:00Z"}
        document["authorization"]["authorization_digest"] = "sha256:" + D64
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence, provenance=ProvenanceBundle(issuance_rows=()),
        )
        assert not report.ok and AUTHORIZATION_EXPIRED in report.codes

    def test_execution_out_of_window_blocks(self):
        document, evidence = _b2_pair()
        document["execution"]["started_at"] = "2026-08-20T00:00:00Z"  # 早于 not_before(08-27)
        evidence = copy.deepcopy(evidence)
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence, provenance=provenance(document, evidence)
        )
        assert not report.ok and AUTHORIZATION_EXECUTION_OUT_OF_WINDOW in report.codes

    def test_time_chain_inversion_blocks(self):
        document, evidence = _b2_pair()
        document["authorization"]["authorized_at"] = "2026-08-29T00:00:00Z"  # 晚于 started(08-28)
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=dict(evidence, authorized_at="2026-08-29T00:00:00Z"),
            provenance=provenance(document, dict(evidence, authorized_at="2026-08-29T00:00:00Z")),
        )
        assert not report.ok and AUTHORIZATION_TIME_INVARIANT_VIOLATED in report.codes

    def test_unparseable_timeline_blocks(self):
        document, evidence = _b2_pair()
        evidence["validity"] = {"not_before": "not-a-time", "not_after": "2026-09-30T00:00:00Z"}
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence, provenance=provenance(document, evidence)
        )
        assert not report.ok and AUTHORIZATION_TIME_INVARIANT_VIOLATED in report.codes

    def test_no_consumption_source_blocks(self):
        document, evidence = _b2_pair()
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence,
            provenance=ProvenanceBundle(issuance_rows=provenance(document, evidence).issuance_rows),  # ledger 空
        )
        assert not report.ok and AUTHORIZATION_CONSUMPTION_UNPROVEN in report.codes

    def test_signature_source_accepted(self):
        document, evidence = _b2_pair()
        evidence = copy.deepcopy(document["authorization"])
        evidence["operation"] = "consumer-replay-execute"
        evidence["consumer_project_uid"] = document["execution"]["consumer_project_uid"]
        evidence["signature"] = "sig-by-issuer"
        document["authorization"]["authorization_digest"] = "sha256:" + D64
        evidence["authorization_digest"] = document["authorization"]["authorization_digest"]
        row = dict(evidence)
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence,
            provenance=ProvenanceBundle(issuance_rows=(row,), frozen_public_key="sha256:" + D64),
        )
        assert report.consumption_source == "signature", report.codes

    def test_challenge_source_accepted(self):
        document, evidence = _b2_pair()
        evidence = dict(evidence)
        evidence["challenge_token"] = "CH-1"
        report = verify_replay_execution_authorization(
            result_payload=document, authorization_evidence=evidence,
            provenance=ProvenanceBundle(issuance_rows=provenance(document, dict(evidence)).issuance_rows, preregistered_challenges=("CH-1",)),
        )
        assert report.consumption_source == "challenge", report.codes
