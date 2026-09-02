"""CAC-05/06：release close guard 八项 checks（IF-8）+ envelope 适配（IF-9）+ R6 迁移。"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import (
    D64,
    OID40,
    import_pair,
    installation_receipt,
    publication_receipt,
    verified_observation,
    write_yaml,
)

from meta_flow.work.publication_close import (
    PUBLICATION_AUTHORIZATION_KIND,
    adapt_close_authorization_from_envelope,
    load_close_authorization_mapping,
    plan_cr076_release_close_guard,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _guard_setup(release: Path, process: Path):
    """B1→B2 导入后组装 guard 四输入；返回 (attestation_ref, attestation, 归档 result_ref)。"""
    _, r2, _, _ = import_pair(release, process)
    archive = Path(r2.archive_path).parent
    attestation = json.loads((archive / "attestation.yaml").read_bytes().decode("utf-8")) if (archive / "attestation.yaml").suffix == ".json" else _load_yaml(archive / "attestation.yaml")
    attestation_ref = f"process/evidence/CR-076/consumer-acceptance/{archive.name}/attestation.yaml"
    result_ref = f"process/evidence/CR-076/consumer-acceptance/{archive.name}/result.json"
    return attestation_ref, attestation, result_ref


def _load_yaml(path: Path):
    import yaml

    return yaml.safe_load(path.read_bytes())


def _run_guard(release, *, attestation_ref, receipts, observation, result_ref, installation=None):
    observation_ref = write_yaml(
        release.parent / "demo-process", "evidence/CR-076/observation.yaml", observation
    )
    return plan_cr076_release_close_guard(
        Path(release),
        attestation_ref=attestation_ref,
        publication_receipts=receipts,
        observation_ref=observation_ref,
        acceptance_result_ref=result_ref,
        installation_receipt=installation if installation is not None else installation_receipt(),
    )


class TestGuardPositive:
    def test_full_chain_ready(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        digest = attestation["attestation_digest"]
        report = _run_guard(
            release,
            attestation_ref=attestation_ref,
            receipts=(publication_receipt(digest),),
            observation=verified_observation(digest),
            result_ref=result_ref,
        )
        assert report.ready, (report.blockers, report.detail)
        assert report.attestation_digest == digest
        assert report.observation_receipt_digest == "f" * 64
        assert all(passed for _name, passed in report.checks)


class TestGuardNegative:
    def test_input_unreadable_short_circuits(self, routed):
        release, process = routed
        _, attestation, result_ref = _guard_setup(release, process)
        report = _run_guard(
            release,
            attestation_ref="process/evidence/CR-076/consumer-acceptance/MISSING/attestation.yaml",
            receipts=(publication_receipt(attestation["attestation_digest"]),),
            observation=verified_observation(attestation["attestation_digest"]),
            result_ref=result_ref,
        )
        assert not report.ready and report.blockers == ("GUARD-INPUT-UNREADABLE",)

    def test_schema_invalid_short_circuits(self, routed):
        release, process = routed
        _, attestation, result_ref = _guard_setup(release, process)
        broken = dict(attestation, extra_field="x")  # additionalProperties:false 必拒
        att_ref = write_yaml(process, "evidence/CR-076/broken-attestation.yaml", broken)
        report = _run_guard(
            release, attestation_ref=att_ref,
            receipts=(publication_receipt(attestation["attestation_digest"]),),
            observation=verified_observation(attestation["attestation_digest"]), result_ref=result_ref,
        )
        assert not report.ready and report.blockers == ("GUARD-SCHEMA-INVALID",)

    def test_predecessor_variant_invalid(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        # schema 合法组合（published-install × PublishedVerifiedReceiptV1 前驱），
        # 但 candidate-install 复核归 guard（LCQ-S05-03）→ 语义阻断
        wrong = installation_receipt()
        wrong["install_variant"] = "published-install"
        wrong["predecessor_kind"] = "PublishedVerifiedReceiptV1"
        report = _run_guard(
            release, attestation_ref=attestation_ref,
            receipts=(publication_receipt(attestation["attestation_digest"]),),
            observation=verified_observation(attestation["attestation_digest"]),
            result_ref=result_ref, installation=wrong,
        )
        assert "GUARD-ATTESTATION-PREDECESSOR-INVALID" in report.blockers

    def test_predecessor_digest_unbound(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        wrong = installation_receipt()
        wrong["receipt_digest"] = "7" * 64  # 与 attestation.predecessor_digest 不匹配
        report = _run_guard(
            release, attestation_ref=attestation_ref,
            receipts=(publication_receipt(attestation["attestation_digest"]),),
            observation=verified_observation(attestation["attestation_digest"]),
            result_ref=result_ref, installation=wrong,
        )
        assert "GUARD-ATTESTATION-PREDECESSOR-INVALID" in report.blockers

    def test_binding_mismatch_on_tampered_archive(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        archive = (process / "evidence" / "CR-076" / "consumer-acceptance" / "CAR-076-SCN076-07-R2")
        (archive / "result.json").write_bytes((archive / "result.json").read_bytes() + b" ")
        report = _run_guard(
            release, attestation_ref=attestation_ref,
            receipts=(publication_receipt(attestation["attestation_digest"]),),
            observation=verified_observation(attestation["attestation_digest"]), result_ref=result_ref,
        )
        assert "GUARD-ATTESTATION-BINDING-MISMATCH" in report.blockers

    def test_publication_not_succeeded(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        digest = attestation["attestation_digest"]
        failed = publication_receipt(digest)
        failed["outcome"] = "FAILED"
        report = _run_guard(
            release, attestation_ref=attestation_ref, receipts=(failed,),
            observation=verified_observation(digest), result_ref=result_ref,
        )
        assert "GUARD-PUBLICATION-NOT-SUCCEEDED" in report.blockers

    def test_empty_receipts_rejected(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        report = _run_guard(
            release, attestation_ref=attestation_ref, receipts=(),
            observation=verified_observation(attestation["attestation_digest"]), result_ref=result_ref,
        )
        assert "GUARD-PUBLICATION-NOT-SUCCEEDED" in report.blockers

    def test_predecessor_binding_broken(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        observation = verified_observation("9" * 64)  # predecessor 指向别的 attestation
        report = _run_guard(
            release, attestation_ref=attestation_ref,
            receipts=(publication_receipt(attestation["attestation_digest"]),),
            observation=observation, result_ref=result_ref,
        )
        assert "GUARD-PREDECESSOR-BROKEN" in report.blockers

    def test_digest_set_incomplete(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        observation = verified_observation(attestation["attestation_digest"])
        observation["publication_receipts"] = [  # 与传入 receipts 的三元组集合不等
            {"target_kind": "git-tag", "target_identity": "refs/tags/OTHER", "receipt_digest": "d" * 64}
        ]
        report = _run_guard(
            release, attestation_ref=attestation_ref,
            receipts=(publication_receipt(attestation["attestation_digest"]),),
            observation=observation, result_ref=result_ref,
        )
        assert "GUARD-DIGEST-SET-INCOMPLETE" in report.blockers

    def test_observation_not_verified(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        digest = attestation["attestation_digest"]
        partial = verified_observation(digest)
        partial["outcome"] = "PARTIAL"
        report = _run_guard(
            release, attestation_ref=attestation_ref, receipts=(publication_receipt(digest),),
            observation=partial, result_ref=result_ref,
        )
        assert "GUARD-OBSERVATION-NOT-VERIFIED" in report.blockers

    def test_observed_assets_diverge_from_accepted(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        digest = attestation["attestation_digest"]
        observation = verified_observation(digest)
        observation["observed_assets"] = dict(observation["observed_assets"], wheel="1" * 64)
        report = _run_guard(
            release, attestation_ref=attestation_ref, receipts=(publication_receipt(digest),),
            observation=observation, result_ref=result_ref,
        )
        assert "GUARD-OBSERVATION-NOT-VERIFIED" in report.blockers

    def test_freshness_exceeded(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        digest = attestation["attestation_digest"]
        stale = verified_observation(digest)
        stale["valid_until"] = "2020-01-01T00:00:00Z"
        report = _run_guard(
            release, attestation_ref=attestation_ref, receipts=(publication_receipt(digest),),
            observation=stale, result_ref=result_ref,
        )
        assert "GUARD-FRESHNESS-EXCEEDED" in report.blockers

    def test_asset_coverage_mismatch(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        digest = attestation["attestation_digest"]
        drifted = verified_observation(digest, assets={"wheel": "2" * 64, "sdist": D64, "build_receipt": D64, "sidecar": D64})
        report = _run_guard(
            release, attestation_ref=attestation_ref, receipts=(publication_receipt(digest),),
            observation=drifted, result_ref=result_ref,
        )
        assert "GUARD-ASSET-COVERAGE-MISMATCH" in report.blockers

    def test_result_asset_key_mapping_receipt_vs_build_receipt(self, routed):
        release, process = routed
        attestation_ref, attestation, result_ref = _guard_setup(release, process)
        digest = attestation["attestation_digest"]
        # result 侧 assets.receipt ↔ observation 侧 accepted_assets.build_receipt（键名映射）：
        # 改归档 result 的 receipt 值 → coverage 比对失败（bytes 变更同时触发 binding 复核）
        archive = process / "evidence" / "CR-076" / "consumer-acceptance" / "CAR-076-SCN076-07-R2" / "result.json"
        payload = json.loads(archive.read_bytes())
        payload["artifact"]["assets"]["receipt"] = "3" * 64
        archive.write_text(json.dumps(payload), encoding="utf-8")
        report = _run_guard(
            release, attestation_ref=attestation_ref, receipts=(publication_receipt(digest),),
            observation=verified_observation(digest), result_ref=result_ref,
        )
        assert "GUARD-ASSET-COVERAGE-MISMATCH" in report.blockers
        assert "GUARD-ATTESTATION-BINDING-MISMATCH" in report.blockers


# ---------------- IF-9：envelope 适配 + R6 deprecated 路径 ----------------

def _binding_payload():
    return {
        "schema_version": 1,
        "kind": PUBLICATION_AUTHORIZATION_KIND,
        "authorization_id": "AZ-ADAPT-0001",
        "work_id": "W-PUB",
        "plan_digest": "a" * 64,
        "target_refs": ["process/works/W-PUB/WORK.yaml"],
        "scope_digest": "b" * 64,
        "result_ref": "process/results/W-PUB/result.json",
        "handoff_ref": "process/results/W-PUB/handoff.json",
        "handoff_digest": "c" * 64,
        "publication_receipt_ref": "process/results/W-PUB/receipt.json",
        "publication_receipt_digest": "d" * 64,
        "repository_facts_digest": "e" * 64,
        "paused_oids": {"release": OID40, "process": OID40},
        "published_oids": {"release": OID40, "process": OID40},
        "expires_at": "2099-01-01T00:00:00+00:00",
        "single_use": True,
    }


def _mock_plan(payload):
    from meta_flow.work.lifecycle_transaction import WorkPublicationBindingV1

    binding = WorkPublicationBindingV1(
        payload["work_id"], payload["scope_digest"], payload["result_ref"], payload["handoff_ref"],
        payload["handoff_digest"], payload["publication_receipt_ref"], payload["publication_receipt_digest"],
        payload["repository_facts_digest"],
        tuple(payload["paused_oids"].items()), tuple(payload["published_oids"].items()),
    )
    return SimpleNamespace(
        work_id=payload["work_id"], plan_digest=payload["plan_digest"], publication_binding=binding,
        targets=[SimpleNamespace(ref=ref) for ref in payload["target_refs"]],
        operation="work.publication-close",
    )


class TestEnvelopeAdapter:
    def test_adapts_and_binds(self):
        payload = _binding_payload()
        envelope = SimpleNamespace(operation="work-publication-close", payload=dict(payload))
        authorization = adapt_close_authorization_from_envelope(envelope, _mock_plan(payload))
        assert authorization.work_id == payload["work_id"]
        assert authorization.plan_digest == payload["plan_digest"]

    def test_adapted_equals_direct_mapping(self):
        payload = _binding_payload()
        envelope = SimpleNamespace(operation="work-publication-close", payload=dict(payload))
        via_envelope = adapt_close_authorization_from_envelope(envelope, _mock_plan(payload))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            via_direct = load_close_authorization_mapping(dict(payload))
        assert via_envelope == via_direct

    def test_wrong_operation_rejected(self):
        payload = _binding_payload()
        envelope = SimpleNamespace(operation="release-publish", payload=dict(payload))
        with pytest.raises(ValueError, match="work-publication-close"):
            adapt_close_authorization_from_envelope(envelope, _mock_plan(payload))

    def test_non_mapping_payload_rejected(self):
        payload = _binding_payload()
        envelope = SimpleNamespace(operation="work-publication-close", payload=[payload])
        with pytest.raises(ValueError, match="mapping"):
            adapt_close_authorization_from_envelope(envelope, _mock_plan(payload))

    def test_unbound_plan_digest_rejected(self):
        payload = _binding_payload()
        other_plan = _mock_plan(dict(payload, plan_digest="f" * 64))
        envelope = SimpleNamespace(operation="work-publication-close", payload=dict(payload))
        with pytest.raises(ValueError, match="does not bind"):
            adapt_close_authorization_from_envelope(envelope, other_plan)


class TestDeprecatedMappingPath:
    def test_load_mapping_warns_deprecation(self):
        with pytest.warns(DeprecationWarning, match="deprecated"):
            authorization = load_close_authorization_mapping(_binding_payload())
        assert authorization.single_use is True
