"""七步合同编排（IF-7）：受授权 typed mutation 导入 + 防重三道 + B1/B2 条件性 attestation。

唯一 mutation 入口：任一步失败 = BLOCKED（typed reason code，mutation=0）；
登记先于副作用（ADR-076-07）；TOCTOU 落库前重验 bytes；receipt 与归档同窗口原子落位。
R5 返修：consume 后落 staged journal（归档目录内 .journal.yaml），多文件产物按
journal steps 幂等续跑；半成品 + result bytes 漂移 → PREIMAGE-DRIFT。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

from meta_flow.ingestion.consumer_acceptance_schema import (
    CONSUMER_RESULT_SCHEMA_NAME,
    NATURAL_LANGUAGE_UNSUPPORTED,
    RESULT_UNREADABLE,
    ConsumerAcceptanceBlocked,
    check_journey_coverage,
    check_journey_unique_keys,
    ensure_result_within_size,
    load_design_schema,
    parse_result_document,
    validate_consumer_result,
)
from meta_flow.ingestion.consumer_acceptance_validator import (
    INSTALLED_ARTIFACT,
    SOURCE_CANDIDATE,
    ProvenanceBundle,
    ProviderFrozenIdentityV1,
    validate_identity,
    verify_replay_execution_authorization,
)
from meta_flow.project.process_route import require_process_route, resolve_process_ref

INGESTION_RECEIPT_KIND = "ConsumerAcceptanceIngestionReceiptV1"
ATTESTATION_KIND = "ConsumerAcceptanceAttestationV1"
DECISION_IMPORTED = "IMPORTED"
RESULT_ID_DUPLICATED = "RESULT-ID-DUPLICATED"
AUTHORIZATION_CONSUMED = "AUTHORIZATION-CONSUMED"
PREIMAGE_DRIFT = "PREIMAGE-DRIFT"
ATTESTATION_VARIANT_FORBIDDEN = "ATTESTATION-VARIANT-FORBIDDEN"
ATTESTATION_PREDECESSOR_MISSING = "ATTESTATION-PREDECESSOR-MISSING"
B1_NOT_IMPORTED = "B1-NOT-IMPORTED"
INSTALL_RECEIPT_KIND = "InstallationReceiptV1"
CANDIDATE_INSTALL = "candidate-install"
AUTHORIZATION_ISSUANCE_MISSING = "AUTHORIZATION-ISSUANCE-MISSING"
JOURNAL_NAME = ".journal.yaml"
JOURNAL_CORRUPT = "JOURNAL-CORRUPT"


def _plain_digest(document: Mapping[str, Any]) -> str:
    """裸 hex64 canonical digest（bundle schema 家族口径；attestation_digest 同法）。"""
    blob = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class AuthorizationLedger(Protocol):
    """O-03 窄协议：provider import 授权 single-use 账本（S02 注入或内存 fake）。"""

    def is_consumed(self, authorization_id: str) -> bool: ...

    def consume(self, authorization_id: str, *, attempt_id: str, preimage_digest: str) -> None: ...


@dataclass(frozen=True, slots=True)
class IngestionReceipt:
    """导入产物（receipt 一对一；B2 另含 attestation）。"""

    document: Mapping[str, Any]
    digest: str
    attestation: Mapping[str, Any] | None
    archive_path: Path
    receipt_path: Path


def _canonical_digest(document: Mapping[str, Any]) -> str:
    blob = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _read_result_bytes(root: Path, result_ref: str) -> bytes:
    if not result_ref.startswith("process/"):
        raise ConsumerAcceptanceBlocked(
            NATURAL_LANGUAGE_UNSUPPORTED, f"non-canonical channel has no import entry: {result_ref!r}"
        )
    try:
        path = resolve_process_ref(root, result_ref)
    except Exception as exc:
        raise ConsumerAcceptanceBlocked(RESULT_UNREADABLE, f"result ref unresolvable: {exc}") from exc
    if not path.is_file():
        raise ConsumerAcceptanceBlocked(RESULT_UNREADABLE, f"result ref missing: {result_ref}")
    return path.read_bytes()


def _resolve_evidence_root(root: Path, override: Path | None) -> Path:
    if override is not None:
        return Path(override)
    return require_process_route(root).process_root / "evidence" / "CR-076" / "consumer-acceptance"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, staged = tempfile.mkstemp(dir=str(path.parent), prefix=".staged-", suffix=path.name)
    try:
        with os.fdopen(handle_fd, "wb") as handle:
            handle.write(data)
        os.replace(staged, path)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise


def _write_yaml(path: Path, document: Mapping[str, Any]) -> None:
    _atomic_write(path, yaml.safe_dump(dict(document), sort_keys=True, allow_unicode=True).encode("utf-8"))


def _yaml_bytes(document: Mapping[str, Any]) -> bytes:
    """与 _write_yaml 完全一致的期望 bytes（恢复期先验一致性用）。"""
    return yaml.safe_dump(dict(document), sort_keys=True, allow_unicode=True).encode("utf-8")


def _journal_path(target_root: Path) -> Path:
    """staged journal 落在归档目录内部（自包含；见模块 docstring 的位置决策）。"""
    return target_root / JOURNAL_NAME


def _load_staged_journal(journal_path: Path, result_id: str) -> dict[str, Any]:
    """读 staged journal；形态损坏（外部篡改/半写）→ JOURNAL-CORRUPT 确定性阻断。"""
    try:
        document = yaml.safe_load(journal_path.read_bytes())
    except (OSError, yaml.YAMLError) as exc:
        raise ConsumerAcceptanceBlocked(JOURNAL_CORRUPT, f"staged journal unreadable: {exc}") from exc
    steps = document.get("steps") if isinstance(document, dict) else None
    shape_ok = (
        isinstance(document, dict)
        and document.get("result_id") == result_id
        and isinstance(document.get("done"), bool)
        and isinstance(document.get("result_digest"), str)
        and bool(document.get("result_digest"))
        and isinstance(document.get("receipt"), Mapping)
        and isinstance(steps, Mapping)
    )
    if not shape_ok:
        raise ConsumerAcceptanceBlocked(JOURNAL_CORRUPT, f"staged journal shape invalid: {journal_path}")
    return document


def _ensure_artifact(path: Path, expected: bytes, *, label: str) -> None:
    """R5 恢复语义：缺失则补写；已存在则先验 bytes 一致，漂移 → PREIMAGE-DRIFT。"""
    if path.is_file():
        if path.read_bytes() != expected:
            raise ConsumerAcceptanceBlocked(
                PREIMAGE_DRIFT, f"archived {label} drifted from staged journal: {path}"
            )
        return
    _atomic_write(path, expected)


def _resume_staged_import(
    *,
    journal: dict[str, Any],
    journal_path: Path,
    target_root: Path,
    raw: bytes,
) -> IngestionReceipt:
    """R5 幂等续跑：authorization 已消费（不得二次消费，跳过 ledger.consume 与防重三道）。

    产物按 journal 快照补齐：缺失补写、已存在先验 bytes 一致则跳过重写；
    任一已落盘产物与 journal 不一致 → PREIMAGE-DRIFT（mutation 停止）。
    """
    steps = dict(journal["steps"])
    receipt = dict(journal["receipt"])
    attestation = journal.get("attestation")
    attestation = dict(attestation) if isinstance(attestation, Mapping) else None
    result_path = target_root / "result.json"
    receipt_path = target_root / "ingestion-receipt.yaml"

    def _mark(**progress: bool) -> None:
        steps.update(progress)
        _write_yaml(journal_path, dict(journal, steps=dict(steps)))

    _ensure_artifact(result_path, raw, label="result.json")
    _mark(archived=True)
    _ensure_artifact(receipt_path, _yaml_bytes(receipt), label="ingestion-receipt.yaml")
    _mark(receipted=True)
    if attestation is not None:
        _ensure_artifact(target_root / "attestation.yaml", _yaml_bytes(attestation), label="attestation.yaml")
        _mark(attested=True)
    _write_yaml(journal_path, dict(journal, steps=dict(steps), done=True))
    return IngestionReceipt(
        document=receipt,
        digest=str(receipt.get("receipt_digest") or ""),
        attestation=attestation,
        archive_path=result_path,
        receipt_path=receipt_path,
    )


def _b1_already_imported(evidence_base: Path, result_id: str, release_oid: str, process_oid: str) -> bool:
    for archived in sorted(evidence_base.glob("*/result.json")):
        if archived.parent.name == result_id:
            continue
        try:
            document = json.loads(archived.read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            continue
        artifact = document.get("artifact") or {}
        if (
            document.get("variant") == SOURCE_CANDIDATE
            and artifact.get("source_release_oid") == release_oid
            and artifact.get("source_process_oid") == process_oid
        ):
            return True
    return False


def _build_attestation(
    *,
    payload: Mapping[str, Any],
    variant: str,
    predecessor: Mapping[str, Any] | None,
    evidence_base: Path,
    result_digest: str,
    result_id: str,
    result_ref: str,
    imported_at: str,
) -> Mapping[str, Any] | None:
    """R9 分工：B1 只产 receipt；B2 须 exact candidate-install 前驱 + B1 先行导入。"""
    if variant == SOURCE_CANDIDATE:
        if predecessor is not None:
            raise ConsumerAcceptanceBlocked(
                ATTESTATION_VARIANT_FORBIDDEN, "B1 (source-candidate-replay) never produces an attestation"
            )
        return None
    if variant != INSTALLED_ARTIFACT:
        raise ConsumerAcceptanceBlocked(ATTESTATION_PREDECESSOR_MISSING, f"unknown variant: {variant!r}")
    if not isinstance(predecessor, Mapping) or any(
        predecessor.get(field) != expected
        for field, expected in (
            ("kind", INSTALL_RECEIPT_KIND),
            ("install_variant", CANDIDATE_INSTALL),
        )
    ) or not str(predecessor.get("receipt_digest") or ""):
        raise ConsumerAcceptanceBlocked(
            ATTESTATION_PREDECESSOR_MISSING,
            "B2 requires an exact candidate-install InstallationReceiptV1 predecessor",
        )
    artifact = payload.get("artifact") or {}
    if not _b1_already_imported(
        evidence_base, result_id, str(artifact.get("source_release_oid") or ""), str(artifact.get("source_process_oid") or "")
    ):
        raise ConsumerAcceptanceBlocked(B1_NOT_IMPORTED, "B2 import requires B1 to be imported first")
    # 冻结 schema 字段（release-bundle-identity-v1 $defs.ConsumerAcceptanceAttestationV1）：
    # 平铺 predecessor_digest/predecessor_kind；attestation_digest=槽位置零后规范化 SHA-256（非自引用）。
    core: dict[str, Any] = {
        "schema_version": 1,
        "kind": ATTESTATION_KIND,
        "attestation_digest": "0" * 64,
        "predecessor_digest": str(predecessor.get("receipt_digest") or ""),
        "predecessor_kind": INSTALL_RECEIPT_KIND,
        "consumer_result_digest": result_digest,
        "result_ref": result_ref,
        "accepted_at": imported_at,
    }
    core["attestation_digest"] = _plain_digest(core)
    return core


def import_consumer_acceptance(
    project_root: Path,
    *,
    result_ref: str,
    frozen: ProviderFrozenIdentityV1,
    authorization_evidence: Mapping[str, Any] | None,
    provenance: ProvenanceBundle,
    ledger: AuthorizationLedger,
    authorization_id: str,
    writer: str = "host-orchestrator",
    scope: tuple[str, ...] = ("consumer-acceptance-import",),
    installation_predecessor: Mapping[str, Any] | None = None,
    evidence_root: Path | None = None,
    imported_at: str | None = None,
) -> IngestionReceipt:
    """IF-7：七步编排（唯一 mutation 入口；任一步失败 mutation=0）。"""
    root = Path(project_root).resolve()
    raw = _read_result_bytes(root, result_ref)
    ensure_result_within_size(raw)
    first_digest = hashlib.sha256(raw).hexdigest()
    payload = parse_result_document(raw)
    schema = load_design_schema(root, CONSUMER_RESULT_SCHEMA_NAME)
    findings = validate_consumer_result(payload, schema)
    if not findings.ok:
        raise ConsumerAcceptanceBlocked(findings.code, "; ".join(findings.errors[:3]))
    check_journey_unique_keys(payload)
    check_journey_coverage(payload)
    drift = validate_identity(payload, frozen)
    if not drift.ok:
        raise ConsumerAcceptanceBlocked(drift.codes[0], "; ".join(drift.drifts[:3]))
    evidence_report = verify_replay_execution_authorization(
        result_payload=payload, authorization_evidence=authorization_evidence, provenance=provenance
    )
    if not evidence_report.ok:
        raise ConsumerAcceptanceBlocked(evidence_report.codes[0], "; ".join(evidence_report.notes[:3]))
    result_id = str(payload.get("result_id") or "")
    evidence_base = _resolve_evidence_root(root, evidence_root)
    target_root = evidence_base / result_id
    journal_path = _journal_path(target_root)
    # -- R5 staged journal 恢复入口（先于防重三道） ----------------------------
    # a) done=true → 现状 RESULT-ID-DUPLICATED 语义；
    # b) 半成品 → 重读 bytes 对账 journal.result_digest（漂移=PREIMAGE-DRIFT），
    #    一致则幂等续跑（跳过 ledger.consume：authorization 已消费，不得二次消费）；
    # c) 无 journal → 落入下方现有三道防重（含 target 存在但无 journal 的历史遗留）。
    if journal_path.is_file():
        journal = _load_staged_journal(journal_path, result_id)
        if journal.get("done") is True:
            raise ConsumerAcceptanceBlocked(RESULT_ID_DUPLICATED, f"result already imported: {result_id}")
        if first_digest != str(journal.get("result_digest") or ""):
            raise ConsumerAcceptanceBlocked(
                PREIMAGE_DRIFT, "result bytes drifted from staged journal (recovery)"
            )
        return _resume_staged_import(
            journal=journal, journal_path=journal_path, target_root=target_root, raw=raw
        )
    if target_root.exists():
        raise ConsumerAcceptanceBlocked(RESULT_ID_DUPLICATED, f"result already imported: {result_id}")
    if ledger.is_consumed(authorization_id):
        raise ConsumerAcceptanceBlocked(AUTHORIZATION_CONSUMED, f"authorization already consumed: {authorization_id}")
    if hashlib.sha256(_read_result_bytes(root, result_ref)).hexdigest() != first_digest:
        raise ConsumerAcceptanceBlocked(PREIMAGE_DRIFT, "result bytes changed during import (TOCTOU)")
    stamp = imported_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    attestation = _build_attestation(
        payload=payload,
        variant=str(payload.get("variant") or ""),
        predecessor=installation_predecessor,
        evidence_base=evidence_base,
        result_digest=first_digest,
        result_id=result_id,
        result_ref=result_ref,
        imported_at=stamp,
    )
    ledger.consume(authorization_id, attempt_id=f"import-{result_id}", preimage_digest=first_digest)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "kind": INGESTION_RECEIPT_KIND,
        "result_id": result_id,
        "result_digest": first_digest,
        "result_ref": result_ref,
        "authorization_id": authorization_id,
        "authorization_digest": str((payload.get("authorization") or {}).get("authorization_digest") or ""),
        "writer": writer,
        "scope": list(scope),
        "decision": DECISION_IMPORTED,
        "schema_digest": schema.digest,
        "journey_coverage": {"journeys": len(payload.get("execution", {}).get("journeys") or []), "cells": "18+24"},
        "imported_at": stamp,
        "consumption_source": evidence_report.consumption_source,
    }
    receipt["receipt_digest"] = _canonical_digest(receipt)
    # -- R5 mutation 顺序：consume → journal(consumed) → result.json → receipt → attestation → done
    journal: dict[str, Any] = {
        "result_id": result_id,
        "authorization_id": authorization_id,
        "attempt_id": f"import-{result_id}",
        "result_digest": first_digest,
        "result_ref": result_ref,
        "variant": str(payload.get("variant") or ""),
        "steps": {"consumed": True, "archived": False, "receipted": False, "attested": False},
        "done": False,
        "receipt": dict(receipt),
        "attestation": dict(attestation) if attestation is not None else None,
    }
    _write_yaml(journal_path, journal)
    _atomic_write(target_root / "result.json", raw)
    journal["steps"]["archived"] = True
    _write_yaml(journal_path, journal)
    _write_yaml(target_root / "ingestion-receipt.yaml", receipt)
    journal["steps"]["receipted"] = True
    _write_yaml(journal_path, journal)
    if attestation is not None:
        _write_yaml(target_root / "attestation.yaml", attestation)
        journal["steps"]["attested"] = True
        _write_yaml(journal_path, journal)
    journal["done"] = True
    _write_yaml(journal_path, journal)
    return IngestionReceipt(
        document=receipt,
        digest=str(receipt["receipt_digest"]),
        attestation=attestation,
        archive_path=target_root / "result.json",
        receipt_path=target_root / "ingestion-receipt.yaml",
    )


__all__ = [
    "ATTESTATION_KIND",
    "ATTESTATION_PREDECESSOR_MISSING",
    "ATTESTATION_VARIANT_FORBIDDEN",
    "AUTHORIZATION_ISSUANCE_MISSING",
    "AuthorizationLedger",
    "B1_NOT_IMPORTED",
    "CANDIDATE_INSTALL",
    "DECISION_IMPORTED",
    "IngestionReceipt",
    "INGESTION_RECEIPT_KIND",
    "INSTALL_RECEIPT_KIND",
    "JOURNAL_CORRUPT",
    "JOURNAL_NAME",
    "PREIMAGE_DRIFT",
    "RESULT_ID_DUPLICATED",
    "import_consumer_acceptance",
]
