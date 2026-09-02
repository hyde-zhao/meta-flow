"""R3/R4 返修测试：release CLI 成功路径（IF-13）+ S02 持久授权跨调用 single-use。

B1/B2 happy 走真实 consumer_acceptance_import_main（argv 全参数），断言 exit 0、
stdout 可解析机器 JSON、decision=IMPORTED、归档产物在盘且 receipt_digest 一致；
BLOCKED 回归（schema 漂移 / identity 漂移）exit 2 + 零 traceback。
持久授权：每次 CLI 调用新建 PersistentAuthorizationLedger（进程内零共享内存），
single-use 状态只存在于 root/.meta-flow-runtime/authorization/ 双 ndjson。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml
from conftest import (
    finalize,
    frozen_identity,
    installation_receipt,
    registry_row,
    result_document,
    stage_result,
)

from meta_flow.ingestion.consumer_acceptance_validator import (
    INSTALLED_ARTIFACT,
    SOURCE_CANDIDATE,
)
from meta_flow.release import cli as release_cli

HEX64 = re.compile(r"^[a-f0-9]{64}$")
REPO_ROOT = Path(__file__).resolve().parents[2]


def _archive_dir(process: Path, result_id: str) -> Path:
    return process / "evidence" / "CR-076" / "consumer-acceptance" / result_id


def _envelope(authorization_id: str, target_refs: tuple[str, ...]):
    """合法 S02 envelope（operation=consumer-acceptance-import；issuance 登记用）。"""
    from meta_flow.execution_control.authorization import AuthorizationEnvelopeV1

    return AuthorizationEnvelopeV1(
        schema_version=1,
        kind="authorization-envelope",
        authorization_id=authorization_id,
        operation="consumer-acceptance-import",
        target_refs=tuple(target_refs),
        plan_digest="f" * 64,
        issued_at="2026-08-28T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        single_use=True,
        authorization_source="typed-user-confirmation",
        payload={},
    )


def _register_issuance(release: Path, envelope) -> None:
    from meta_flow.execution_control.authorization import AuthorizationLedger

    AuthorizationLedger(root=release).register_issuance(envelope)


def _run_import(
    release: Path,
    *,
    result_ref: str,
    variant: str,
    evidence: dict,
    rows: list,
    authorization_id: str,
    frozen_override: dict | None = None,
    predecessor: dict | None = None,
) -> int:
    """进程内 CLI 调用（每次 main 全新装配 = 零共享内存）。"""
    frozen = frozen_override if frozen_override is not None else asdict(frozen_identity(variant))
    argv = [
        "consumer-acceptance-import",
        "--project-root", str(release),
        "--result-ref", result_ref,
        "--variant", variant,
        "--frozen-identity", json.dumps(frozen),
        "--authorization-evidence", json.dumps(evidence),
        "--provenance", json.dumps({"issuance_rows": rows, "execution_ledger_rows": rows}),
        "--authorization-id", authorization_id,
    ]
    if predecessor is not None:
        argv += ["--installation-predecessor", json.dumps(predecessor)]
    return release_cli.main(argv)


class TestCliHappyPath:
    def test_b1_happy_exit_zero_machine_json(self, routed, capsys):
        release, process = routed
        doc, ev = finalize(result_document("CAR-CLI-B1", SOURCE_CANDIDATE))
        ref = stage_result(process, "CAR-CLI-B1", doc)
        _register_issuance(release, _envelope("AZ-CLI-B1", (ref,)))
        rc = _run_import(
            release, result_ref=ref, variant=SOURCE_CANDIDATE, evidence=ev,
            rows=[registry_row(doc, ev)], authorization_id="AZ-CLI-B1",
        )
        assert rc == 0
        out = capsys.readouterr()
        assert "Traceback" not in out.out + out.err
        payload = json.loads(out.out)
        assert payload["decision"] == "IMPORTED"
        assert payload["result_id"] == "CAR-CLI-B1"
        assert HEX64.match(payload["result_digest"])
        assert payload["attestation"] is None
        archive = _archive_dir(process, "CAR-CLI-B1")
        assert (archive / "result.json").is_file()
        assert (archive / "ingestion-receipt.yaml").is_file()
        receipt = yaml.safe_load((archive / "ingestion-receipt.yaml").read_bytes())
        assert receipt["receipt_digest"] == payload["receipt_digest"]
        assert payload["archive_path"].endswith("result.json")
        assert payload["receipt_path"].endswith("ingestion-receipt.yaml")

    def test_b2_happy_attestation_written(self, routed, capsys):
        release, process = routed
        b1_doc, b1_ev = finalize(result_document("CAR-CLI-B2-B1", SOURCE_CANDIDATE))
        b1_ref = stage_result(process, "CAR-CLI-B2-B1", b1_doc)
        _register_issuance(release, _envelope("AZ-CLI-B2-B1", (b1_ref,)))
        rc = _run_import(
            release, result_ref=b1_ref, variant=SOURCE_CANDIDATE, evidence=b1_ev,
            rows=[registry_row(b1_doc, b1_ev)], authorization_id="AZ-CLI-B2-B1",
        )
        assert rc == 0
        capsys.readouterr()
        b2_doc, b2_ev = finalize(result_document("CAR-CLI-B2", INSTALLED_ARTIFACT))
        b2_ref = stage_result(process, "CAR-CLI-B2", b2_doc)
        _register_issuance(release, _envelope("AZ-CLI-B2", (b2_ref,)))
        rc = _run_import(
            release, result_ref=b2_ref, variant=INSTALLED_ARTIFACT, evidence=b2_ev,
            rows=[registry_row(b2_doc, b2_ev)], authorization_id="AZ-CLI-B2",
            predecessor=installation_receipt(),
        )
        assert rc == 0
        out = capsys.readouterr()
        assert "Traceback" not in out.out + out.err
        payload = json.loads(out.out)
        assert payload["decision"] == "IMPORTED"
        assert payload["attestation"] and payload["attestation"]["kind"] == "ConsumerAcceptanceAttestationV1"
        archive = _archive_dir(process, "CAR-CLI-B2")
        assert (archive / "attestation.yaml").is_file()

    def test_schema_drift_blocks_exit_two_machine_json(self, routed, capsys):
        release, process = routed
        doc, ev = finalize(result_document("CAR-CLI-BAD", SOURCE_CANDIDATE))
        del doc["execution"]  # schema 必拒
        ref = stage_result(process, "CAR-CLI-BAD", doc)
        _register_issuance(release, _envelope("AZ-CLI-BAD", (ref,)))
        rc = _run_import(
            release, result_ref=ref, variant=SOURCE_CANDIDATE, evidence=ev,
            rows=[registry_row(doc, ev)], authorization_id="AZ-CLI-BAD",
        )
        assert rc == 2
        out = capsys.readouterr()
        assert "Traceback" not in out.out + out.err
        payload = json.loads(out.out)
        assert payload["decision"] == "BLOCKED"
        assert payload["error"]

    def test_identity_drift_blocks_exit_two_machine_json(self, routed, capsys):
        release, process = routed
        doc, ev = finalize(result_document("CAR-CLI-DRIFT", SOURCE_CANDIDATE))
        ref = stage_result(process, "CAR-CLI-DRIFT", doc)
        _register_issuance(release, _envelope("AZ-CLI-DRIFT", (ref,)))
        frozen = asdict(frozen_identity(SOURCE_CANDIDATE))
        frozen["source_release_oid"] = "9" * 40  # identity 漂移
        rc = _run_import(
            release, result_ref=ref, variant=SOURCE_CANDIDATE, evidence=ev,
            rows=[registry_row(doc, ev)], authorization_id="AZ-CLI-DRIFT",
            frozen_override=frozen,
        )
        assert rc == 2
        out = capsys.readouterr()
        assert "Traceback" not in out.out + out.err
        payload = json.loads(out.out)
        assert payload["decision"] == "BLOCKED"
        assert payload["error"]


class TestPersistentAuthorizationSingleUse:
    def test_second_independent_call_blocked_authorization_consumed(self, routed, capsys):
        release, process = routed
        d1, e1 = finalize(result_document("CAR-P1", SOURCE_CANDIDATE))
        r1 = stage_result(process, "CAR-P1", d1)
        d2, e2 = finalize(result_document("CAR-P2", SOURCE_CANDIDATE))
        r2 = stage_result(process, "CAR-P2", d2)
        _register_issuance(release, _envelope("AZ-SHARED", (r1, r2)))
        rc1 = _run_import(
            release, result_ref=r1, variant=SOURCE_CANDIDATE, evidence=e1,
            rows=[registry_row(d1, e1)], authorization_id="AZ-SHARED",
        )
        assert rc1 == 0
        capsys.readouterr()
        # 持久化证据：双账本落盘（跨进程可验证的唯一真相源）
        auth_dir = release / ".meta-flow-runtime" / "authorization"
        assert (auth_dir / "issuance-registry.ndjson").is_file()
        assert (auth_dir / "consumption-ledger.ndjson").is_file()
        # 第二次独立调用（新进程语义：全新 adapter，零共享内存，仅共享磁盘账本）
        rc2 = _run_import(
            release, result_ref=r2, variant=SOURCE_CANDIDATE, evidence=e2,
            rows=[registry_row(d2, e2)], authorization_id="AZ-SHARED",
        )
        assert rc2 == 2
        out = capsys.readouterr()
        assert "Traceback" not in out.out + out.err
        payload = json.loads(out.out)
        assert "AUTHORIZATION-CONSUMED" in payload["error"]
        # 第二个 result 未被导入（授权 single-use 阻断）
        assert not _archive_dir(process, "CAR-P2").exists()

    def test_issuance_missing_blocks(self, routed, capsys):
        release, process = routed
        doc, ev = finalize(result_document("CAR-UNREG", SOURCE_CANDIDATE))
        ref = stage_result(process, "CAR-UNREG", doc)
        # 未 register_issuance → issuance registry 无此授权
        rc = _run_import(
            release, result_ref=ref, variant=SOURCE_CANDIDATE, evidence=ev,
            rows=[registry_row(doc, ev)], authorization_id="AZ-UNREG",
        )
        assert rc == 2
        out = capsys.readouterr()
        assert "Traceback" not in out.out + out.err
        payload = json.loads(out.out)
        assert "AUTHORIZATION-ISSUANCE-MISSING" in payload["error"]
        assert not _archive_dir(process, "CAR-UNREG").exists()

    def test_cross_process_subprocess_smoke(self, routed):
        uv = shutil.which("uv")
        if uv is None:
            pytest.skip("uv 不可用：跳过跨进程冒烟")
        probe = subprocess.run(
            [uv, "run", "python", "-c", "import meta_flow"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=180,
        )
        if probe.returncode != 0:
            pytest.skip("uv 环境不可用（meta-flow 无法导入）：跳过跨进程冒烟")
        release, process = routed
        d1, e1 = finalize(result_document("CAR-SUB1", SOURCE_CANDIDATE))
        r1 = stage_result(process, "CAR-SUB1", d1)
        d2, e2 = finalize(result_document("CAR-SUB2", SOURCE_CANDIDATE))
        r2 = stage_result(process, "CAR-SUB2", d2)
        _register_issuance(release, _envelope("AZ-SUB", (r1, r2)))
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

        def spawn(result_ref: str, doc: dict, ev: dict) -> subprocess.CompletedProcess:
            return subprocess.run(
                [
                    uv, "run", "meta-flow", "release", "consumer-acceptance-import",
                    "--project-root", str(release),
                    "--result-ref", result_ref,
                    "--variant", SOURCE_CANDIDATE,
                    "--frozen-identity", json.dumps(asdict(frozen_identity(SOURCE_CANDIDATE))),
                    "--authorization-evidence", json.dumps(ev),
                    "--provenance", json.dumps(
                        {"issuance_rows": [registry_row(doc, ev)],
                         "execution_ledger_rows": [registry_row(doc, ev)]}
                    ),
                    "--authorization-id", "AZ-SUB",
                ],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=180, env=env,
            )

        first = spawn(r1, d1, e1)
        assert first.returncode == 0, first.stderr
        assert "Traceback" not in first.stdout + first.stderr
        second = spawn(r2, d2, e2)
        assert second.returncode == 2, second.stderr
        assert "AUTHORIZATION-CONSUMED" in second.stdout
        assert "Traceback" not in second.stdout + second.stderr
