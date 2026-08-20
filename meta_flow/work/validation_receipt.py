"""绑定 fingerprint、命令、环境和结果的验证 receipt。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.read_contract import is_safe_read_ref
from meta_flow.work.model import ValidationReuseRequestV2
from meta_flow.work.validation_fingerprint import VALIDATION_LAYERS

_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ENVIRONMENT_KEYS = {"python", "platform", "toolchain"}


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _validate_environment(summary: Mapping[str, str]) -> dict[str, str]:
    if set(summary) != ENVIRONMENT_KEYS:
        raise ValueError("environment summary must contain python/platform/toolchain")
    normalized: dict[str, str] = {}
    for key in sorted(summary):
        value = summary[key]
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 128
            or any(marker in value for marker in ("/", "\\", "\n", "\r"))
        ):
            raise ValueError(f"environment summary {key} must be one bounded non-path value")
        normalized[key] = value
    return normalized


@dataclass(frozen=True)
class ValidationReceipt:
    schema_version: int
    layer: str
    fingerprint_digest: str
    command_identity: str
    environment_summary: dict[str, str]
    decision: str
    result_digest: str
    owner: str
    receipt_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "environment_summary": self.environment_summary.copy(),
        }


@dataclass(frozen=True)
class ValidationReceiptV2:
    schema_version: int
    layer: str
    fingerprint_digest: str
    profile_digest: str
    command_identity: str
    environment_summary: dict[str, str]
    semantic_environment_digest: str
    source_manifest_digest: str
    provider_identity_digest: str
    decision: str
    partial_mutation: bool
    result_digest: str
    owner: str
    receipt_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "environment_summary": self.environment_summary.copy()}


def create_validation_receipt(
    *,
    layer: str,
    fingerprint_digest: str,
    command_identity: str,
    environment_summary: Mapping[str, str],
    decision: str,
    result_digest: str,
    owner: str,
) -> ValidationReceipt:
    if layer not in VALIDATION_LAYERS:
        raise ValueError(f"unsupported validation layer: {layer}")
    for field, value in (
        ("fingerprint_digest", fingerprint_digest),
        ("command_identity", command_identity),
        ("result_digest", result_digest),
    ):
        if not _HEX_RE.fullmatch(value):
            raise ValueError(f"{field} must be one lowercase sha256")
    if decision not in {"PASS", "FAIL"}:
        raise ValueError("validation receipt decision must be PASS or FAIL")
    if not _OWNER_RE.fullmatch(owner):
        raise ValueError("validation receipt owner must be one safe identifier")
    environment = _validate_environment(environment_summary)
    semantic = {
        "schema_version": 1,
        "layer": layer,
        "fingerprint_digest": fingerprint_digest,
        "command_identity": command_identity,
        "environment_summary": environment,
        "decision": decision,
        "result_digest": result_digest,
        "owner": owner,
    }
    return ValidationReceipt(
        1,
        layer,
        fingerprint_digest,
        command_identity,
        environment,
        decision,
        result_digest,
        owner,
        _digest(semantic),
    )


def create_validation_receipt_v2(
    *,
    layer: str,
    fingerprint_digest: str,
    profile_digest: str,
    command_identity: str,
    environment_summary: Mapping[str, str],
    source_manifest_digest: str,
    provider_identity_digest: str,
    decision: str,
    partial_mutation: bool,
    result_digest: str,
    owner: str,
) -> ValidationReceiptV2:
    if layer not in VALIDATION_LAYERS:
        raise ValueError(f"unsupported validation layer: {layer}")
    for field, value in (
        ("fingerprint_digest", fingerprint_digest),
        ("profile_digest", profile_digest),
        ("command_identity", command_identity),
        ("source_manifest_digest", source_manifest_digest),
        ("provider_identity_digest", provider_identity_digest),
        ("result_digest", result_digest),
    ):
        if not _HEX_RE.fullmatch(value):
            raise ValueError(f"{field} must be one lowercase sha256")
    if decision not in {"PASS", "FAIL"} or type(partial_mutation) is not bool:
        raise ValueError("validation receipt v2 result fields are invalid")
    if not _OWNER_RE.fullmatch(owner):
        raise ValueError("validation receipt owner must be one safe identifier")
    environment = _validate_environment(environment_summary)
    semantic_environment_digest = _digest(environment)
    semantic = {
        "schema_version": 2,
        "layer": layer,
        "fingerprint_digest": fingerprint_digest,
        "profile_digest": profile_digest,
        "command_identity": command_identity,
        "environment_summary": environment,
        "semantic_environment_digest": semantic_environment_digest,
        "source_manifest_digest": source_manifest_digest,
        "provider_identity_digest": provider_identity_digest,
        "decision": decision,
        "partial_mutation": partial_mutation,
        "result_digest": result_digest,
        "owner": owner,
    }
    return ValidationReceiptV2(
        2,
        layer,
        fingerprint_digest,
        profile_digest,
        command_identity,
        environment,
        semantic_environment_digest,
        source_manifest_digest,
        provider_identity_digest,
        decision,
        partial_mutation,
        result_digest,
        owner,
        _digest(semantic),
    )


def validation_receipt_from_payload(
    payload: Mapping[str, Any],
) -> ValidationReceipt | ValidationReceiptV2:
    if payload.get("schema_version") == 2:
        return validation_receipt_v2_from_payload(payload)
    expected = {
        "schema_version",
        "layer",
        "fingerprint_digest",
        "command_identity",
        "environment_summary",
        "decision",
        "result_digest",
        "owner",
        "receipt_digest",
    }
    if set(payload) != expected or payload.get("schema_version") != 1:
        raise ValueError("invalid validation receipt schema")
    environment = payload.get("environment_summary")
    if not isinstance(environment, Mapping):
        raise ValueError("validation receipt environment_summary must be an object")
    receipt = create_validation_receipt(
        layer=str(payload["layer"]),
        fingerprint_digest=str(payload["fingerprint_digest"]),
        command_identity=str(payload["command_identity"]),
        environment_summary={str(key): str(value) for key, value in environment.items()},
        decision=str(payload["decision"]),
        result_digest=str(payload["result_digest"]),
        owner=str(payload["owner"]),
    )
    if receipt.receipt_digest != payload.get("receipt_digest"):
        raise ValueError("validation receipt digest mismatch")
    return receipt


def validation_receipt_v2_from_payload(payload: Mapping[str, Any]) -> ValidationReceiptV2:
    expected = {
        "schema_version",
        "layer",
        "fingerprint_digest",
        "profile_digest",
        "command_identity",
        "environment_summary",
        "semantic_environment_digest",
        "source_manifest_digest",
        "provider_identity_digest",
        "decision",
        "partial_mutation",
        "result_digest",
        "owner",
        "receipt_digest",
    }
    if set(payload) != expected or payload.get("schema_version") != 2:
        raise ValueError("invalid validation receipt v2 schema")
    environment = payload.get("environment_summary")
    if not isinstance(environment, Mapping):
        raise ValueError("validation receipt environment_summary must be an object")
    partial_mutation = payload.get("partial_mutation")
    if type(partial_mutation) is not bool:
        raise ValueError("validation receipt v2 partial_mutation must be boolean")
    receipt = create_validation_receipt_v2(
        layer=str(payload["layer"]),
        fingerprint_digest=str(payload["fingerprint_digest"]),
        profile_digest=str(payload["profile_digest"]),
        command_identity=str(payload["command_identity"]),
        environment_summary={str(key): str(value) for key, value in environment.items()},
        source_manifest_digest=str(payload["source_manifest_digest"]),
        provider_identity_digest=str(payload["provider_identity_digest"]),
        decision=str(payload["decision"]),
        partial_mutation=partial_mutation,
        result_digest=str(payload["result_digest"]),
        owner=str(payload["owner"]),
    )
    if (
        receipt.semantic_environment_digest != payload.get("semantic_environment_digest")
        or receipt.receipt_digest != payload.get("receipt_digest")
    ):
        raise ValueError("validation receipt v2 digest mismatch")
    return receipt


def adapt_validation_receipt_v1(
    receipt: ValidationReceipt,
    *,
    current_fingerprint_digest: str,
    current_profile_digest: str,
    current_command_identity: str,
    current_environment: Mapping[str, str],
    current_source_manifest_digest: str,
    current_provider_identity_digest: str,
) -> ValidationReuseRequestV2:
    """V1 只读兼容：缺失的 manifest/provider/profile 保持空值，不伪造可复用。"""

    environment = _validate_environment(current_environment)
    return ValidationReuseRequestV2(
        schema_version=2,
        layer=receipt.layer,
        receipt_fingerprint_digest=receipt.fingerprint_digest,
        current_fingerprint_digest=current_fingerprint_digest,
        receipt_profile_digest="",
        current_profile_digest=current_profile_digest,
        receipt_command_identity=receipt.command_identity,
        current_command_identity=current_command_identity,
        receipt_environment=tuple(sorted(receipt.environment_summary.items())),
        current_environment=tuple(sorted(environment.items())),
        receipt_source_manifest_digest="",
        current_source_manifest_digest=current_source_manifest_digest,
        receipt_provider_identity_digest="",
        current_provider_identity_digest=current_provider_identity_digest,
        receipt_decision=receipt.decision,
        partial_mutation=False,
    )


def validation_reuse_request_from_receipt(
    receipt: ValidationReceipt | ValidationReceiptV2,
    *,
    current_fingerprint_digest: str,
    current_profile_digest: str,
    current_command_identity: str,
    current_environment: Mapping[str, str],
    current_source_manifest_digest: str,
    current_provider_identity_digest: str,
) -> ValidationReuseRequestV2:
    if isinstance(receipt, ValidationReceipt):
        return adapt_validation_receipt_v1(
            receipt,
            current_fingerprint_digest=current_fingerprint_digest,
            current_profile_digest=current_profile_digest,
            current_command_identity=current_command_identity,
            current_environment=current_environment,
            current_source_manifest_digest=current_source_manifest_digest,
            current_provider_identity_digest=current_provider_identity_digest,
        )
    environment = _validate_environment(current_environment)
    return ValidationReuseRequestV2(
        schema_version=2,
        layer=receipt.layer,
        receipt_fingerprint_digest=receipt.fingerprint_digest,
        current_fingerprint_digest=current_fingerprint_digest,
        receipt_profile_digest=receipt.profile_digest,
        current_profile_digest=current_profile_digest,
        receipt_command_identity=receipt.command_identity,
        current_command_identity=current_command_identity,
        receipt_environment=tuple(sorted(receipt.environment_summary.items())),
        current_environment=tuple(sorted(environment.items())),
        receipt_source_manifest_digest=receipt.source_manifest_digest,
        current_source_manifest_digest=current_source_manifest_digest,
        receipt_provider_identity_digest=receipt.provider_identity_digest,
        current_provider_identity_digest=current_provider_identity_digest,
        receipt_decision=receipt.decision,
        partial_mutation=receipt.partial_mutation,
    )


def load_validation_receipt(path: Path) -> ValidationReceipt | ValidationReceiptV2:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("validation receipt must be a JSON object")
    return validation_receipt_from_payload(payload)


def write_validation_receipt(
    process_root: Path,
    work_id: str,
    receipt: ValidationReceipt | ValidationReceiptV2,
) -> tuple[Path, bool]:
    work_ref = f"works/{work_id}/WORK.yaml"
    if not is_safe_read_ref(work_ref):
        raise ValueError("work_id must be safe")
    root = process_root.resolve() / "works" / work_id / "evidence" / "validation"
    root.mkdir(parents=True, exist_ok=True)
    if receipt.decision == "PASS":
        for candidate in root.glob(f"{receipt.layer}-*.receipt.json"):
            existing = load_validation_receipt(candidate)
            if (
                existing.decision == "PASS"
                and existing.fingerprint_digest == receipt.fingerprint_digest
                and existing.command_identity == receipt.command_identity
            ):
                if existing != receipt:
                    raise ValueError(
                        "exact validation PASS already has one different owner/receipt"
                    )
                return candidate, False
    name = f"{receipt.layer}-{receipt.receipt_digest[:20]}.receipt.json"
    path = root / name
    rendered = json.dumps(receipt.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8") != rendered:
            raise ValueError("validation receipt path collision")
        return path, False
    with path.open("x", encoding="utf-8") as stream:
        stream.write(rendered)
    return path, True
