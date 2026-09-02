"""CR-076 S05 测试共享装配：tmp sibling-binding project + 冻结 schema 复制 + fixture 构造。

装配模式 = tests/test_vnext_process_routing.py（plan_project_init/apply_project_init）；
fixture 构造口径 = process/docs/design/CR-076/schemas/fixtures/run-fixtures.py（J24 双层
覆盖矩阵、az() 十二字段、base()/installed_doc() 双 variant），程序化构造不回写冻结目录。
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from meta_flow.ingestion.consumer_acceptance_validator import (
    INSTALLED_ARTIFACT,
    SOURCE_CANDIDATE,
    ProvenanceBundle,
    ProviderFrozenIdentityV1,
    compute_result_digest,
)
from meta_flow.project.onboarding import (
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)

D64 = "a" * 64
OID40 = "0123456789abcdef0123456789abcdef01234567"
TS = "2026-08-28T01:52:35Z"
SCHEMA_NAMES = (
    "consumer-acceptance-result-v1.schema.json",
    "release-bundle-identity-v1.schema.json",
)

# 24 行 = 双层覆盖矩阵（rev3）：W3-W10 × J1/J2/J3（24 格）+ round 1..6 轮转（18 格）
J24 = [
    {"journey": w, "round": (wi % 6) + 1, "case": c, "outcome": "PASS"}
    for wi, w in enumerate(("W3", "W4", "W5", "W6", "W7", "W8", "W9", "W10"))
    for c in ("J1", "J2", "J3")
]


def canonical_digest(document):
    blob = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()


def _authorize(plan) -> OnboardingAuthorization:
    payload = plan.as_dict()
    return OnboardingAuthorization(
        schema_version=1,
        authorization_id=f"auth-{plan.plan_digest[:12]}",
        authorization_source=AUTHORIZATION_SOURCE,
        authorization_kind=AUTHORIZATION_KIND,
        operation=payload["operation"],
        decision_ref=payload["decision_ref"],
        project_id=payload["project_id"],
        plan_digest=payload["plan_digest"],
        expected_oids=payload["base_oids"],
        expires_at="2099-01-01T00:00:00+00:00",
    )


@pytest.fixture()
def routed(tmp_path: Path) -> tuple[Path, Path]:
    """tmp sibling-binding（release, process）+ 冻结 schema 已复制进 tmp process。"""
    release = tmp_path / "demo"
    release.mkdir()
    _git(release, "init", "-b", "main")
    (release / "README.md").write_text("demo\n", encoding="utf-8")
    _git(release, "add", "README.md")
    _git(release, "-c", "user.name=Meta Flow Test", "-c", "user.email=t@example.invalid", "commit", "-m", "initial")
    plan = plan_project_init(ProjectInitRequest(release, "demo", "Demo"))
    apply_project_init(plan, _authorize(plan))
    process = tmp_path / "demo-process"
    schema_dir = process / "docs" / "design" / "CR-076" / "schemas"
    schema_dir.mkdir(parents=True)
    # 冻结 schema 只读消费：源 = sibling 真实 process 仓（tests/cr076 → tests → release → 上级）
    source = Path(__file__).resolve().parents[2].parent / "meta-flow-process" / "docs" / "design" / "CR-076" / "schemas"
    for name in SCHEMA_NAMES:
        (schema_dir / name).write_bytes((source / name).read_bytes())
    return release, process


class FakeLedger:
    """O-03 窄协议内存 fake（is_consumed/consume）。"""

    def __init__(self, consumed=None):
        self.consumed = set(consumed or ())

    def is_consumed(self, authorization_id: str) -> bool:
        return authorization_id in self.consumed

    def consume(self, authorization_id: str, *, attempt_id: str, preimage_digest: str) -> None:
        self.consumed.add(authorization_id)


def authorization_block(result_id: str) -> dict:
    return {
        "authorization_ref": f"process/authorizations/AZ-{result_id}.json",
        "authorization_id": f"AZ-{result_id}",
        "authorization_digest": "sha256:" + D64,
        "scope": ["consumer-replay-execute"],
        "target": ["SCN-076-07"],
        "validity": {"not_before": "2026-08-27T00:00:00Z", "not_after": "2026-09-30T00:00:00Z"},
        "single_use": {"consumed": True, "consumed_at": TS, "consumed_by": "SCN-076-07"},
        "authorization_inherited": False,
        "principal": "user-hyde",
        "authorized_at": "2026-08-27T10:00:00Z",
    }


def result_document(result_id: str, variant: str) -> dict:
    document = {
        "schema_version": 1,
        "kind": "ConsumerAcceptanceResultV1",
        "result_id": result_id,
        "variant": variant,
        "created_at": TS,
        "authorization": authorization_block(result_id),
        "artifact": {
            "variant": variant,
            "source_release_oid": OID40,
            "source_process_oid": OID40,
            "source_tree_digest": D64,
            "provider_identity": "provider-authoritative-dev",
        },
        "execution": {
            "consumer_project_uid": "consumer-project-uid-1",
            "quant_lab_release_oid": OID40,
            "quant_lab_process_oid": OID40,
            "command_identity": "meta-flow replay execute --scenario SCN-076-07",
            "profile_fingerprint": D64,
            "environment_fingerprint": D64,
            "provider_fingerprint": D64,
            "started_at": TS,
            "finished_at": TS,
            "exit_digest": D64,
            "result_digest": D64,
            "mutation_inventory": [
                {"path": "meta-flow/.meta-flow-runtime/replay/SCN-076-07/", "mutation_kind": "REPLAY-OUTPUT-WRITE"}
            ],
            "zero_modification_proofs": {"cr_174_preimage_digest": D64, "cr_175_preimage_digest": D64},
            "journeys": copy.deepcopy(J24),
            "overall": "PASS",
        },
    }
    if variant == INSTALLED_ARTIFACT:
        document["artifact"] = {
            "variant": variant,
            "bundle_manifest_digest": D64,
            "semver": "1.2.3",
            "assets": {"wheel": D64, "sdist": D64, "receipt": D64, "sidecar": D64},
            "source_release_oid": OID40,
            "source_process_oid": OID40,
            "provider_identity": "provider-authoritative-dev",
            "provider_fingerprint": D64,
        }
    return document


def finalize(document: dict) -> tuple[dict, dict]:
    """注入 operation/consumer_project_uid → 重算 authorization_digest 与 result_digest。"""
    evidence = copy.deepcopy(document["authorization"])
    evidence["operation"] = "consumer-replay-execute"
    evidence["consumer_project_uid"] = document["execution"]["consumer_project_uid"]
    document["authorization"]["authorization_digest"] = canonical_digest(evidence)
    document["execution"]["result_digest"] = compute_result_digest(document)
    return document, evidence


def registry_row(document: dict, evidence: dict) -> dict:
    """issuance registry / execution ledger 行：digest=对 evidence 的权威 canonical digest。"""
    row = dict(evidence)
    row["authorization_digest"] = document["authorization"]["authorization_digest"]
    return row


def frozen_identity(variant: str) -> ProviderFrozenIdentityV1:
    fields = {
        "variant": variant,
        "source_release_oid": OID40,
        "source_process_oid": OID40,
        "provider_identity": "provider-authoritative-dev",
        "consumer_project_uid": "consumer-project-uid-1",
        "quant_lab_release_oid": OID40,
        "quant_lab_process_oid": OID40,
        "command_identity": "meta-flow replay execute --scenario SCN-076-07",
        "profile_fingerprint": D64,
        "environment_fingerprint": D64,
        "provider_fingerprint": D64,
    }
    if variant == SOURCE_CANDIDATE:
        fields["source_tree_digest"] = D64
    if variant == INSTALLED_ARTIFACT:
        fields.update(
            bundle_manifest_digest=D64,
            semver="1.2.3",
            wheel_digest=D64,
            sdist_digest=D64,
            bundle_receipt_digest=D64,
            sidecar_digest=D64,
            artifact_provider_fingerprint=D64,
        )
    return ProviderFrozenIdentityV1(**fields)


def installation_receipt() -> dict:
    return {
        "schema_version": 1,
        "kind": "InstallationReceiptV1",
        "receipt_digest": "b" * 64,
        "predecessor_digest": "c" * 64,
        "predecessor_kind": "TransportReceiptV1",
        "install_variant": "candidate-install",
        "consumer_project_uid": "consumer-project-uid-1",
        "installed_at": TS,
        "outcome": "INSTALLED",
    }


def provenance(document: dict, evidence: dict, *, issuance=None, ledger_rows=None) -> ProvenanceBundle:
    row = registry_row(document, evidence)
    return ProvenanceBundle(
        issuance_rows=(row,) if issuance is None else issuance,
        execution_ledger_rows=(row,) if ledger_rows is None else ledger_rows,
    )


def stage_result(process: Path, name: str, document: dict) -> str:
    inbox = process / "evidence" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"{name}.json").write_text(json.dumps(document), encoding="utf-8")
    return f"process/evidence/inbox/{name}.json"


def import_pair(release: Path, process: Path):
    """B1→B2 顺序导入并返回（b1 产物, b2 产物, evidence dict 对, result 文档对）。"""
    from meta_flow.ingestion.consumer_acceptance_import import import_consumer_acceptance

    b1_doc, b1_ev = finalize(result_document("CAR-076-SCN076-07-R1", SOURCE_CANDIDATE))
    b2_doc, b2_ev = finalize(result_document("CAR-076-SCN076-07-R2", INSTALLED_ARTIFACT))
    b1_ref = stage_result(process, "CAR-B1", b1_doc)
    b2_ref = stage_result(process, "CAR-B2", b2_doc)
    ledger = FakeLedger()
    r1 = import_consumer_acceptance(
        release, result_ref=b1_ref, frozen=frozen_identity(SOURCE_CANDIDATE),
        authorization_evidence=b1_ev, provenance=provenance(b1_doc, b1_ev),
        ledger=ledger, authorization_id="AZ-CAR-076-SCN076-07-R1",
    )
    r2 = import_consumer_acceptance(
        release, result_ref=b2_ref, frozen=frozen_identity(INSTALLED_ARTIFACT),
        authorization_evidence=b2_ev, provenance=provenance(b2_doc, b2_ev),
        ledger=ledger, authorization_id="AZ-CAR-076-SCN076-07-R2",
        installation_predecessor=installation_receipt(),
    )
    return r1, r2, (b1_doc, b1_ev), (b2_doc, b2_ev)


def publication_receipt(attestation_digest: str) -> dict:
    return {
        "schema_version": 1,
        "kind": "PublicationReceiptV1",
        "receipt_digest": "d" * 64,
        "predecessor_digest": attestation_digest,
        "predecessor_kind": "ConsumerAcceptanceAttestationV1",
        "target": {"target_kind": "git-tag", "target_identity": "refs/tags/v1.2.3"},
        "attempt_id": "PUB-1",
        "authorization_digest": "sha256:" + "e" * 64,
        "outcome": "SUCCEEDED",
        "recorded_at": TS,
    }


def verified_observation(attestation_digest: str, assets=None) -> dict:
    now = datetime.now(UTC)
    digest_set = {"wheel": D64, "sdist": D64, "build_receipt": D64, "sidecar": D64}
    return {
        "schema_version": 1,
        "kind": "PublishedVerifiedReceiptV1",
        "receipt_digest": "f" * 64,
        "predecessor_digest": attestation_digest,
        "predecessor_kind": "ConsumerAcceptanceAttestationV1",
        "accepted_bundle_digest": D64,
        "publication_receipts": [
            {"target_kind": "git-tag", "target_identity": "refs/tags/v1.2.3", "receipt_digest": "d" * 64}
        ],
        "accepted_assets": dict(digest_set if assets is None else assets),
        "observed_assets": dict(digest_set),
        "observed_at": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_until": (now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "observation_authorization_digest": "sha256:" + "9" * 64,
        "outcome": "VERIFIED",
    }


def write_yaml(process: Path, relative: str, document: dict) -> str:
    path = process / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=True, allow_unicode=True), encoding="utf-8")
    return f"process/{relative}"


__all__ = [
    "D64",
    "FakeLedger",
    "J24",
    "OID40",
    "TS",
    "canonical_digest",
    "finalize",
    "frozen_identity",
    "import_pair",
    "installation_receipt",
    "publication_receipt",
    "provenance",
    "registry_row",
    "result_document",
    "routed",
    "stage_result",
    "verified_observation",
    "write_yaml",
]
