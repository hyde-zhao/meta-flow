"""CAC-03/04：import 七步编排（IF-7）——B1/B2 分工、attestation 产出、防重三道、mutation=0。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from conftest import (
    FakeLedger,
    finalize,
    frozen_identity,
    import_pair,
    installation_receipt,
    provenance,
    result_document,
    stage_result,
)
from jsonschema import Draft7Validator

from meta_flow.ingestion.consumer_acceptance_import import (
    ATTESTATION_PREDECESSOR_MISSING,
    ATTESTATION_VARIANT_FORBIDDEN,
    AUTHORIZATION_CONSUMED,
    B1_NOT_IMPORTED,
    INGESTION_RECEIPT_KIND,
    JOURNAL_NAME,
    NATURAL_LANGUAGE_UNSUPPORTED,
    PREIMAGE_DRIFT,
    RESULT_ID_DUPLICATED,
    import_consumer_acceptance,
)
from meta_flow.ingestion.consumer_acceptance_schema import (
    ConsumerAcceptanceBlocked,
    load_bundle_identity_schema,
)
from meta_flow.ingestion.consumer_acceptance_validator import (
    INSTALLED_ARTIFACT,
    SOURCE_CANDIDATE,
    ProvenanceBundle,
)

HEX64 = re.compile(r"^[a-f0-9]{64}$")
EVIDENCE_REF = "process/evidence/CR-076/consumer-acceptance"


class CountingLedger(FakeLedger):
    """恢复断言用 fake：记录 consume 调用次数（恢复期必须为 0，不得二次消费）。"""

    def __init__(self, consumed=None):
        super().__init__(consumed)
        self.consume_calls = 0

    def consume(self, authorization_id, *, attempt_id, preimage_digest):
        self.consume_calls += 1
        super().consume(authorization_id, attempt_id=attempt_id, preimage_digest=preimage_digest)


class TestB1Import:
    def test_b1_happy_no_attestation_receipt_written(self, routed):
        release, process = routed
        r1, r2, _, _ = import_pair(release, process)
        assert r1.attestation is None
        archive = process / "evidence" / "CR-076" / "consumer-acceptance" / "CAR-076-SCN076-07-R1"
        assert (archive / "result.json").is_file() and (archive / "ingestion-receipt.yaml").is_file()
        assert not (archive / "attestation.yaml").exists()
        receipt = yaml.safe_load((archive / "ingestion-receipt.yaml").read_bytes())
        assert receipt["kind"] == INGESTION_RECEIPT_KIND
        assert receipt["decision"] == "IMPORTED"
        assert receipt["consumption_source"] == "execution-ledger"
        assert HEX64.match(receipt["result_digest"])
        assert receipt["receipt_digest"].startswith("sha256:")
        assert r1.digest == receipt["receipt_digest"]

    def test_b2_attestation_fields_frozen_schema(self, routed):
        release, process = routed
        _, r2, _, b2 = import_pair(release, process)
        b2_doc, _ = b2
        attestation = r2.attestation
        assert set(attestation) == {
            "schema_version", "kind", "attestation_digest", "predecessor_digest",
            "predecessor_kind", "consumer_result_digest", "result_ref", "accepted_at",
        }
        assert attestation["predecessor_kind"] == "InstallationReceiptV1"
        assert attestation["predecessor_digest"] == "b" * 64  # installation_receipt().receipt_digest
        # consumer_result_digest = 归档 result canonical bytes sha256（裸 hex64）
        assert HEX64.match(attestation["consumer_result_digest"])
        # attestation_digest 槽位置零口径：对置零文档可复算
        core = dict(attestation, attestation_digest="0" * 64)
        recomputed = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        import hashlib
        assert attestation["attestation_digest"] == hashlib.sha256(recomputed.encode("utf-8")).hexdigest()
        # 落盘副本过冻结 bundle identity schema
        loaded = load_bundle_identity_schema(Path(release))
        assert not list(Draft7Validator(loaded.document).iter_errors(attestation))
        assert (Path(r2.archive_path).parent / "attestation.yaml").is_file()

    def test_ledger_consumed_after_import(self, routed):
        release, process = routed
        b1_doc, b1_ev = finalize(result_document("CAR-LEDGER", SOURCE_CANDIDATE))
        ref = stage_result(process, "CAR-LEDGER", b1_doc)
        ledger = FakeLedger()
        import_consumer_acceptance(
            release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
            authorization_evidence=b1_ev, provenance=provenance(b1_doc, b1_ev),
            ledger=ledger, authorization_id="AZ-LEDGER",
        )
        assert ledger.is_consumed("AZ-LEDGER")


class TestDedup:
    def test_result_id_duplicated(self, routed):
        release, process = routed
        _, _, _, b2 = import_pair(release, process)
        b2_doc, b2_ev = b2
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            import_consumer_acceptance(
                release, result_ref="process/evidence/inbox/CAR-B2.json",
                frozen=frozen_identity(INSTALLED_ARTIFACT), authorization_evidence=b2_ev,
                provenance=provenance(b2_doc, b2_ev), ledger=FakeLedger(), authorization_id="AZ-X",
                installation_predecessor=installation_receipt(),
            )
        assert excinfo.value.code == RESULT_ID_DUPLICATED

    def test_authorization_consumed(self, routed):
        release, process = routed
        b3_doc, b3_ev = finalize(result_document("CAR-076-SCN076-07-R3", SOURCE_CANDIDATE))
        stage_result(process, "CAR-B3", b3_doc)
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            import_consumer_acceptance(
                release, result_ref="process/evidence/inbox/CAR-B3.json",
                frozen=frozen_identity(SOURCE_CANDIDATE), authorization_evidence=b3_ev,
                provenance=provenance(b3_doc, b3_ev),
                ledger=FakeLedger(consumed={"AZ-C"}), authorization_id="AZ-C",
            )
        assert excinfo.value.code == AUTHORIZATION_CONSUMED
        # mutation=0：失败不落盘
        assert not (process / "evidence" / "CR-076" / "consumer-acceptance" / "CAR-076-SCN076-07-R3").exists()

    def test_preimage_drift_blocks(self, routed, monkeypatch):
        release, process = routed
        b1_doc, b1_ev = finalize(result_document("CAR-TOCTOU", SOURCE_CANDIDATE))
        ref = stage_result(process, "CAR-TOCTOU", b1_doc)
        from meta_flow.ingestion import consumer_acceptance_import as cai
        calls = {"n": 0}
        real = cai._read_result_bytes

        def flipping(root, result_ref):
            calls["n"] += 1
            if calls["n"] >= 2:  # 落库前重验返回不同 bytes → TOCTOU
                return real(root, result_ref) + b" "
            return real(root, result_ref)

        monkeypatch.setattr(cai, "_read_result_bytes", flipping)
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            import_consumer_acceptance(
                release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
                authorization_evidence=b1_ev, provenance=provenance(b1_doc, b1_ev),
                ledger=FakeLedger(), authorization_id="AZ-T",
            )
        assert excinfo.value.code == "PREIMAGE-DRIFT"


class TestAttestationGating:
    def _b2_call(self, release, process, *, predecessor, prior_b1=True):
        doc, evidence = finalize(result_document("CAR-GATE", INSTALLED_ARTIFACT))
        ref = stage_result(process, "CAR-GATE", doc)
        if prior_b1:
            b1_doc, b1_ev = finalize(result_document("CAR-GATE-B1", SOURCE_CANDIDATE))
            b1_ref = stage_result(process, "CAR-GATE-B1", b1_doc)
            import_consumer_acceptance(
                release, result_ref=b1_ref, frozen=frozen_identity(SOURCE_CANDIDATE),
                authorization_evidence=b1_ev, provenance=provenance(b1_doc, b1_ev),
                ledger=FakeLedger(), authorization_id="AZ-GATE-B1",
            )
        return import_consumer_acceptance(
            release, result_ref=ref, frozen=frozen_identity(INSTALLED_ARTIFACT),
            authorization_evidence=evidence, provenance=provenance(doc, evidence),
            ledger=FakeLedger(), authorization_id="AZ-GATE",
            installation_predecessor=predecessor,
        )

    def test_b1_with_predecessor_forbidden(self, routed):
        release, process = routed
        b1_doc, b1_ev = finalize(result_document("CAR-FORBID", SOURCE_CANDIDATE))
        ref = stage_result(process, "CAR-FORBID", b1_doc)
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            import_consumer_acceptance(
                release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
                authorization_evidence=b1_ev, provenance=provenance(b1_doc, b1_ev),
                ledger=FakeLedger(), authorization_id="AZ-F",
                installation_predecessor=installation_receipt(),
            )
        assert excinfo.value.code == ATTESTATION_VARIANT_FORBIDDEN

    def test_b2_without_predecessor_blocks(self, routed):
        release, process = routed
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            self._b2_call(release, process, predecessor=None)
        assert excinfo.value.code == ATTESTATION_PREDECESSOR_MISSING

    def test_b2_non_candidate_install_predecessor_blocks(self, routed):
        release, process = routed
        wrong = installation_receipt()
        wrong["install_variant"] = "published-install"
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            self._b2_call(release, process, predecessor=wrong)
        assert excinfo.value.code == ATTESTATION_PREDECESSOR_MISSING

    def test_b2_before_b1_blocks(self, routed):
        release, process = routed
        doc, evidence = finalize(result_document("CAR-ORPHAN", INSTALLED_ARTIFACT))
        ref = stage_result(process, "CAR-ORPHAN", doc)
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            import_consumer_acceptance(
                release, result_ref=ref, frozen=frozen_identity(INSTALLED_ARTIFACT),
                authorization_evidence=evidence, provenance=provenance(doc, evidence),
                ledger=FakeLedger(), authorization_id="AZ-O",
                installation_predecessor=installation_receipt(),
            )
        assert excinfo.value.code == B1_NOT_IMPORTED


class TestChannelAndEarlyGates:
    def test_non_process_channel_blocks(self, routed):
        release, process = routed
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            import_consumer_acceptance(
                release, result_ref="docs/notes/CAR-B1.json", frozen=frozen_identity(SOURCE_CANDIDATE),
                authorization_evidence={}, provenance=ProvenanceBundle(issuance_rows=()),
                ledger=FakeLedger(), authorization_id="AZ-N",
            )
        assert excinfo.value.code == NATURAL_LANGUAGE_UNSUPPORTED

    def test_schema_failure_leaves_no_archive_and_ledger_intact(self, routed):
        release, process = routed
        doc, evidence = finalize(result_document("CAR-BAD", SOURCE_CANDIDATE))
        del doc["execution"]  # schema 必拒
        ref = stage_result(process, "CAR-BAD", doc)
        ledger = FakeLedger()
        with pytest.raises(ConsumerAcceptanceBlocked):
            import_consumer_acceptance(
                release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
                authorization_evidence=evidence, provenance=provenance(doc, evidence),
                ledger=ledger, authorization_id="AZ-BAD",
            )
        assert not ledger.is_consumed("AZ-BAD")
        assert not (process / "evidence" / "CR-076" / "consumer-acceptance" / "CAR-BAD").exists()

    def test_identity_drift_blocks_before_consume(self, routed):
        release, process = routed
        doc, evidence = finalize(result_document("CAR-DRIFT", SOURCE_CANDIDATE))
        ref = stage_result(process, "CAR-DRIFT", doc)
        frozen = frozen_identity(SOURCE_CANDIDATE)
        object.__setattr__(frozen, "source_release_oid", "9" * 40)
        ledger = FakeLedger()
        with pytest.raises(ConsumerAcceptanceBlocked):
            import_consumer_acceptance(
                release, result_ref=ref, frozen=frozen,
                authorization_evidence=evidence, provenance=provenance(doc, evidence),
                ledger=ledger, authorization_id="AZ-D",
            )
        assert not ledger.is_consumed("AZ-D")


class TestStagedJournalRecovery:
    """R5 fault-injection：consume 后 staged journal 半成品的幂等续跑与漂移阻断。"""

    @staticmethod
    def _archive(process, result_id):
        return process / "evidence" / "CR-076" / "consumer-acceptance" / result_id

    @staticmethod
    def _journal(process, result_id):
        return TestStagedJournalRecovery._archive(process, result_id) / JOURNAL_NAME

    @staticmethod
    def _fail_first_write(monkeypatch, filename):
        """注入断点：指定文件名的首次 _atomic_write 抛 OSError（journal 写不受影响）。"""
        from meta_flow.ingestion import consumer_acceptance_import as cai

        real = cai._atomic_write
        state = {"failed": False}

        def failing(path, data):
            if Path(path).name == filename and not state["failed"]:
                state["failed"] = True
                raise OSError(f"injected failure writing {filename}")
            return real(path, data)

        monkeypatch.setattr(cai, "_atomic_write", failing)

    @staticmethod
    def _read_journal(process, result_id):
        return yaml.safe_load(TestStagedJournalRecovery._journal(process, result_id).read_bytes())

    def _stage_b1(self, process, result_id):
        doc, ev = finalize(result_document(result_id, SOURCE_CANDIDATE))
        ref = stage_result(process, result_id, doc)
        return ref, doc, ev

    def test_breakpoint1_consume_done_result_write_failed_recovers(self, routed, monkeypatch):
        """断点 1：consume 后、result.json 首写前崩溃 → journal consumed-only，可恢复。"""
        release, process = routed
        ref, doc, ev = self._stage_b1(process, "CAR-FI1")
        from meta_flow.ingestion import consumer_acceptance_import as cai

        self._fail_first_write(monkeypatch, "result.json")
        first = CountingLedger()
        with pytest.raises(OSError):
            cai.import_consumer_acceptance(
                release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
                authorization_evidence=ev, provenance=provenance(doc, ev),
                ledger=first, authorization_id="AZ-FI1",
            )
        assert first.consume_calls == 1  # 授权确实已消费（持久状态）
        journal = self._read_journal(process, "CAR-FI1")
        assert journal["steps"] == {"consumed": True, "archived": False, "receipted": False, "attested": False}
        assert journal["done"] is False
        # 半成品不得被误判为完整 PASS：result/receipt 均缺失、journal 未 done
        archive = self._archive(process, "CAR-FI1")
        assert not (archive / "result.json").exists()
        assert not (archive / "ingestion-receipt.yaml").exists()
        monkeypatch.undo()
        # 新进程语义：全新 ledger 实例，预置已消费（模拟持久账本中的已消费状态）
        second = CountingLedger(consumed={"AZ-FI1"})
        receipt = cai.import_consumer_acceptance(
            release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
            authorization_evidence=ev, provenance=provenance(doc, ev),
            ledger=second, authorization_id="AZ-FI1",
        )
        assert second.consume_calls == 0  # 恢复全程不新增消费
        assert (archive / "result.json").is_file()
        assert (archive / "ingestion-receipt.yaml").is_file()
        assert self._read_journal(process, "CAR-FI1")["done"] is True
        landed = yaml.safe_load((archive / "ingestion-receipt.yaml").read_bytes())
        assert landed["receipt_digest"] == receipt.digest

    def test_breakpoint2_result_written_receipt_missing_recovers(self, routed, monkeypatch):
        """断点 2：result.json 写后崩溃 → journal archived=true，恢复补 receipt。"""
        release, process = routed
        ref, doc, ev = self._stage_b1(process, "CAR-FI2")
        from meta_flow.ingestion import consumer_acceptance_import as cai

        self._fail_first_write(monkeypatch, "ingestion-receipt.yaml")
        with pytest.raises(OSError):
            cai.import_consumer_acceptance(
                release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
                authorization_evidence=ev, provenance=provenance(doc, ev),
                ledger=CountingLedger(), authorization_id="AZ-FI2",
            )
        journal = self._read_journal(process, "CAR-FI2")
        assert journal["steps"]["consumed"] is True
        assert journal["steps"]["archived"] is True
        assert journal["steps"]["receipted"] is False
        assert journal["done"] is False
        archive = self._archive(process, "CAR-FI2")
        assert (archive / "result.json").is_file()
        assert not (archive / "ingestion-receipt.yaml").exists()
        monkeypatch.undo()
        second = CountingLedger(consumed={"AZ-FI2"})
        receipt = cai.import_consumer_acceptance(
            release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
            authorization_evidence=ev, provenance=provenance(doc, ev),
            ledger=second, authorization_id="AZ-FI2",
        )
        assert second.consume_calls == 0
        landed = yaml.safe_load((archive / "ingestion-receipt.yaml").read_bytes())
        assert landed["receipt_digest"] == receipt.digest
        assert self._read_journal(process, "CAR-FI2")["done"] is True

    def test_breakpoint3_b2_receipt_written_attestation_missing_recovers(self, routed, monkeypatch):
        """断点 3（B2）：receipt 写后、attestation 写前崩溃 → 恢复补 attestation。"""
        release, process = routed
        b1_doc, b1_ev = finalize(result_document("CAR-FI3-B1", SOURCE_CANDIDATE))
        b1_ref = stage_result(process, "CAR-FI3-B1", b1_doc)
        from meta_flow.ingestion import consumer_acceptance_import as cai

        cai.import_consumer_acceptance(
            release, result_ref=b1_ref, frozen=frozen_identity(SOURCE_CANDIDATE),
            authorization_evidence=b1_ev, provenance=provenance(b1_doc, b1_ev),
            ledger=FakeLedger(), authorization_id="AZ-FI3-B1",
        )
        b2_doc, b2_ev = finalize(result_document("CAR-FI3", INSTALLED_ARTIFACT))
        b2_ref = stage_result(process, "CAR-FI3", b2_doc)
        self._fail_first_write(monkeypatch, "attestation.yaml")
        with pytest.raises(OSError):
            cai.import_consumer_acceptance(
                release, result_ref=b2_ref, frozen=frozen_identity(INSTALLED_ARTIFACT),
                authorization_evidence=b2_ev, provenance=provenance(b2_doc, b2_ev),
                ledger=CountingLedger(), authorization_id="AZ-FI3",
                installation_predecessor=installation_receipt(),
            )
        journal = self._read_journal(process, "CAR-FI3")
        assert journal["steps"]["receipted"] is True
        assert journal["steps"]["attested"] is False
        assert journal["done"] is False
        archive = self._archive(process, "CAR-FI3")
        assert (archive / "result.json").is_file() and (archive / "ingestion-receipt.yaml").is_file()
        assert not (archive / "attestation.yaml").exists()
        monkeypatch.undo()
        second = CountingLedger(consumed={"AZ-FI3"})
        receipt = cai.import_consumer_acceptance(
            release, result_ref=b2_ref, frozen=frozen_identity(INSTALLED_ARTIFACT),
            authorization_evidence=b2_ev, provenance=provenance(b2_doc, b2_ev),
            ledger=second, authorization_id="AZ-FI3",
            installation_predecessor=installation_receipt(),
        )
        assert second.consume_calls == 0
        assert (archive / "attestation.yaml").is_file()
        landed = yaml.safe_load((archive / "attestation.yaml").read_bytes())
        assert landed["attestation_digest"] == receipt.attestation["attestation_digest"]
        assert self._read_journal(process, "CAR-FI3")["done"] is True

    def test_breakpoint4_tampered_result_bytes_block_recovery(self, routed, monkeypatch):
        """断点 4：journal 半成品 + result bytes 被篡改 → PREIMAGE-DRIFT，不产生新归档。"""
        release, process = routed
        ref, doc, ev = self._stage_b1(process, "CAR-FI4")
        from meta_flow.ingestion import consumer_acceptance_import as cai

        self._fail_first_write(monkeypatch, "ingestion-receipt.yaml")
        with pytest.raises(OSError):
            cai.import_consumer_acceptance(
                release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
                authorization_evidence=ev, provenance=provenance(doc, ev),
                ledger=CountingLedger(), authorization_id="AZ-FI4",
            )
        monkeypatch.undo()
        # 篡改 inbox 源 bytes（追加换行：JSON 仍可解析、schema 仍有效，但 digest 漂移）
        inbox = process / "evidence" / "inbox" / "CAR-FI4.json"
        inbox.write_bytes(inbox.read_bytes() + b"\n")
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            cai.import_consumer_acceptance(
                release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
                authorization_evidence=ev, provenance=provenance(doc, ev),
                ledger=CountingLedger(consumed={"AZ-FI4"}), authorization_id="AZ-FI4",
            )
        assert excinfo.value.code == PREIMAGE_DRIFT
        archive = self._archive(process, "CAR-FI4")
        # 不产生新归档产物：receipt 仍缺失，journal 仍未 done
        assert not (archive / "ingestion-receipt.yaml").exists()
        assert self._read_journal(process, "CAR-FI4")["done"] is False

    def test_done_journal_reports_result_id_duplicated(self, routed):
        """journal done=true → 现状 RESULT-ID-DUPLICATED 语义（journal 优先于目录存在判断）。"""
        release, process = routed
        ref, doc, ev = self._stage_b1(process, "CAR-FI5")
        from meta_flow.ingestion import consumer_acceptance_import as cai

        cai.import_consumer_acceptance(
            release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
            authorization_evidence=ev, provenance=provenance(doc, ev),
            ledger=FakeLedger(), authorization_id="AZ-FI5",
        )
        assert self._read_journal(process, "CAR-FI5")["done"] is True
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            cai.import_consumer_acceptance(
                release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
                authorization_evidence=ev, provenance=provenance(doc, ev),
                ledger=FakeLedger(), authorization_id="AZ-FI5",
            )
        assert excinfo.value.code == RESULT_ID_DUPLICATED

    def test_archive_without_journal_reports_result_id_duplicated(self, routed):
        """target_root 存在但无 journal（历史遗留/外部构造）→ 维持 RESULT-ID-DUPLICATED。"""
        release, process = routed
        archive = self._archive(process, "CAR-EXTERNAL")
        archive.mkdir(parents=True)
        (archive / "result.json").write_text("{}", encoding="utf-8")
        ref, doc, ev = self._stage_b1(process, "CAR-EXTERNAL")
        from meta_flow.ingestion import consumer_acceptance_import as cai

        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            cai.import_consumer_acceptance(
                release, result_ref=ref, frozen=frozen_identity(SOURCE_CANDIDATE),
                authorization_evidence=ev, provenance=provenance(doc, ev),
                ledger=FakeLedger(), authorization_id="AZ-EXT",
            )
        assert excinfo.value.code == RESULT_ID_DUPLICATED
