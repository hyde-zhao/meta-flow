"""`process/checks` 下机器结果的 typed artifact inventory。

文件后缀只用于有界发现，不能决定 artifact identity。新产物应显式声明
``artifact_kind``；历史产物只能通过本模块内冻结的结构签名兼容分类。未知结构
保持 fail-closed，不能因为文件名包含 ``result`` 而被当成 checkpoint result。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

CHECKPOINT_RE = re.compile(r"^CP[0-8]$")


class CheckArtifactKind(StrEnum):
    """Workflow Doctor 可识别的互斥 check artifact 类型。"""

    CHECKPOINT_RESULT = "checkpoint_result"
    CANDIDATE_CHECKPOINT_RESULT = "candidate_checkpoint_result"
    C0_APPLY_RESULT = "c0_apply_result"
    CHECK_RESULT = "check_result"
    VALIDATION_RECEIPT = "validation_receipt"
    REGISTERED_LEGACY_CHECK_EVIDENCE = "registered_legacy_check_evidence"
    UNKNOWN = "unknown"


EXPLICIT_KINDS = frozenset(
    kind for kind in CheckArtifactKind if kind is not CheckArtifactKind.UNKNOWN
)


@dataclass(frozen=True)
class CheckArtifactDescriptorV1:
    """一个 check artifact 的稳定分类结果。"""

    logical_ref: str
    kind: CheckArtifactKind
    classification_mode: str
    payload: dict[str, Any]
    source_digest: str
    findings: tuple[str, ...] = ()
    schema_version: int = 1

    @property
    def checkpoint(self) -> str:
        return str(
            self.payload.get("checkpoint") or self.payload.get("checkpoint_id") or ""
        ).upper()

    @property
    def cr_id(self) -> str:
        return str(self.payload.get("cr_id") or "")


def _unknown(
    *,
    logical_ref: str,
    payload: dict[str, Any],
    source_digest: str,
    mode: str,
    finding: str,
) -> CheckArtifactDescriptorV1:
    return CheckArtifactDescriptorV1(
        logical_ref=logical_ref,
        kind=CheckArtifactKind.UNKNOWN,
        classification_mode=mode,
        payload=payload,
        source_digest=source_digest,
        findings=(finding,),
    )


def _explicit_kind(payload: dict[str, Any]) -> CheckArtifactKind | None:
    value = str(payload.get("artifact_kind") or "").strip()
    if not value:
        return None
    try:
        kind = CheckArtifactKind(value)
    except ValueError:
        return CheckArtifactKind.UNKNOWN
    return kind if kind in EXPLICIT_KINDS else CheckArtifactKind.UNKNOWN


def _legacy_candidate_signature(path: Path, payload: dict[str, Any]) -> bool:
    """只兼容有显式 candidate wire 的历史 checkpoint candidate。"""

    checkpoint = str(payload.get("checkpoint") or "").upper()
    return (
        ".candidate-" in path.name
        and bool(CHECKPOINT_RE.fullmatch(checkpoint))
        and bool(str(payload.get("cr_id") or ""))
        and bool(str(payload.get("contract_id") or ""))
        and bool(str(payload.get("cp7_event_id") or payload.get("checkpoint_event_id") or ""))
    )


def _legacy_check_result_signature(payload: dict[str, Any]) -> bool:
    if payload.get("checkpoint") or payload.get("checkpoint_id"):
        return False
    return (
        bool(str(payload.get("check_id") or ""))
        and bool(str(payload.get("decision") or ""))
        and any(
            key in payload
            for key in ("check_mode", "check_profile", "checks", "items", "nodes", "dag")
        )
    )


def classify_check_artifact(
    path: Path,
    *,
    logical_ref: str,
) -> CheckArtifactDescriptorV1:
    """读取并分类一个 regular JSON artifact；未知结构保持 fail-closed。"""

    source = path.read_bytes()
    source_digest = sha256(source).hexdigest()
    try:
        payload = json.loads(source)
    except json.JSONDecodeError as exc:
        return _unknown(
            logical_ref=logical_ref,
            payload={},
            source_digest=source_digest,
            mode="invalid-json",
            finding=f"invalid JSON: {exc}",
        )
    if not isinstance(payload, dict):
        return _unknown(
            logical_ref=logical_ref,
            payload={},
            source_digest=source_digest,
            mode="invalid-payload",
            finding="artifact payload must be an object",
        )
    if payload.get("schema_version") != 1:
        return _unknown(
            logical_ref=logical_ref,
            payload=payload,
            source_digest=source_digest,
            mode="unsupported-schema",
            finding="artifact schema_version must be 1",
        )

    explicit = _explicit_kind(payload)
    if explicit is CheckArtifactKind.UNKNOWN:
        return _unknown(
            logical_ref=logical_ref,
            payload=payload,
            source_digest=source_digest,
            mode="explicit",
            finding=f"unsupported artifact_kind: {payload.get('artifact_kind')}",
        )
    if explicit is not None:
        if explicit is CheckArtifactKind.CHECKPOINT_RESULT:
            checkpoint = str(
                payload.get("checkpoint") or payload.get("checkpoint_id") or ""
            ).upper()
            if not payload.get("cr_id") or not CHECKPOINT_RE.fullmatch(checkpoint):
                return _unknown(
                    logical_ref=logical_ref,
                    payload=payload,
                    source_digest=source_digest,
                    mode="explicit",
                    finding="checkpoint_result requires cr_id and checkpoint CP0..CP8",
                )
        return CheckArtifactDescriptorV1(
            logical_ref=logical_ref,
            kind=explicit,
            classification_mode="explicit",
            payload=payload,
            source_digest=source_digest,
        )

    if payload.get("kind") == "C0ApplyResultV1" and payload.get("checkpoint") == "C0":
        return CheckArtifactDescriptorV1(
            logical_ref=logical_ref,
            kind=CheckArtifactKind.C0_APPLY_RESULT,
            classification_mode="legacy-c0-kind",
            payload=payload,
            source_digest=source_digest,
        )
    if _legacy_candidate_signature(path, payload):
        return CheckArtifactDescriptorV1(
            logical_ref=logical_ref,
            kind=CheckArtifactKind.CANDIDATE_CHECKPOINT_RESULT,
            classification_mode="legacy-candidate-signature",
            payload=payload,
            source_digest=source_digest,
        )
    checkpoint = str(payload.get("checkpoint") or payload.get("checkpoint_id") or "").upper()
    if CHECKPOINT_RE.fullmatch(checkpoint) and payload.get("cr_id"):
        return CheckArtifactDescriptorV1(
            logical_ref=logical_ref,
            kind=CheckArtifactKind.CHECKPOINT_RESULT,
            classification_mode="legacy-checkpoint-signature",
            payload=payload,
            source_digest=source_digest,
        )
    if _legacy_check_result_signature(payload):
        return CheckArtifactDescriptorV1(
            logical_ref=logical_ref,
            kind=CheckArtifactKind.CHECK_RESULT,
            classification_mode="legacy-check-result-signature",
            payload=payload,
            source_digest=source_digest,
        )
    return _unknown(
        logical_ref=logical_ref,
        payload=payload,
        source_digest=source_digest,
        mode="unknown",
        finding="artifact kind cannot be determined",
    )


__all__ = [
    "CheckArtifactDescriptorV1",
    "CheckArtifactKind",
    "classify_check_artifact",
]
