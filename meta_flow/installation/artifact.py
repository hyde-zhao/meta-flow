"""正式 provider artifact 与源码资格收据。"""

from __future__ import annotations

import json
import os
import re
import warnings
import zipfile
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from delivery.scripts.digest_policy import (
    build_digest_policy_sidecar,
    load_digest_policy_sidecar,
    load_known_generated_refs,
    observe_wheel_payload,
    sidecar_path_for_receipt,
)
from meta_flow.installation.identity import (
    observe_checkout_delivery_status,
    observe_checkout_source_identity,
)

ARTIFACT_RECEIPT_KIND = "ProviderArtifactReceiptV1"
ARTIFACT_RECEIPT_SCHEMA_VERSION = 1
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_FIELDS = {
    "schema_version",
    "kind",
    "distribution_name",
    "distribution_version",
    "source_commit",
    "source_dirty",
    "source_tree_digest",
    "artifact_filename",
    "artifact_sha256",
    "capability_profile_digest",
    "installed_payload_digest",
    "release_qualifying",
    "receipt_digest",
}


def _canonical_digest(payload: object) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(rendered.encode("utf-8")).hexdigest()


def _wheel_version(wheel: Path) -> tuple[str, str]:
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = sorted(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        if len(metadata_names) != 1:
            raise ValueError("provider wheel must contain exactly one METADATA file")
        name = ""
        version = ""
        for line in archive.read(metadata_names[0]).decode("utf-8").splitlines():
            if line.startswith("Name: "):
                name = line.removeprefix("Name: ").strip()
            elif line.startswith("Version: "):
                version = line.removeprefix("Version: ").strip()
        if not name or not version:
            raise ValueError("provider wheel METADATA is missing Name or Version")
        return name, version


def _wheel_payload_digest(
    wheel: Path,
    *,
    known_generated_refs: tuple[str, ...] | None = None,
) -> str:
    with zipfile.ZipFile(wheel) as archive:
        observation = observe_wheel_payload(
            archive,
            known_generated_refs=known_generated_refs,
        )
    if not observation.records:
        raise ValueError("provider wheel payload is empty")
    return observation.included_manifest_digest


def _wheel_delivery_tree_digest(
    wheel: Path,
    *,
    known_generated_refs: tuple[str, ...] | None = None,
) -> tuple[str, int]:
    with zipfile.ZipFile(wheel) as archive:
        observation = observe_wheel_payload(
            archive,
            known_generated_refs=known_generated_refs,
        )
    return observation.delivery_manifest_digest, observation.delivery_file_count


def build_provider_artifact_receipt(source_root: Path, wheel_path: Path) -> dict[str, Any]:
    """将一个现有 wheel 绑定到 exact source checkout。"""

    root = source_root.resolve()
    wheel = wheel_path.resolve()
    if not wheel.is_file() or wheel.is_symlink() or wheel.suffix != ".whl":
        raise ValueError("provider artifact must be one regular wheel file")
    source = observe_checkout_source_identity(root)
    status = observe_checkout_delivery_status(root)
    distribution_name, distribution_version = _wheel_version(wheel)
    if distribution_version != source["version"]:
        raise ValueError("provider wheel version differs from source identity")
    contract = root / "delivery" / "doc" / "PUBLIC-OPERATION-CONTRACTS.yaml"
    if not contract.is_file() or contract.is_symlink():
        raise ValueError("provider capability contract is missing")
    known_generated_refs = load_known_generated_refs(root / "delivery")
    wheel_delivery_digest, wheel_delivery_file_count = _wheel_delivery_tree_digest(
        wheel,
        known_generated_refs=known_generated_refs,
    )
    if wheel_delivery_file_count < 1:
        raise ValueError("provider wheel has no delivery payload")
    if wheel_delivery_digest != source["delivery_tree_digest"]:
        raise ValueError("provider wheel delivery payload differs from source delivery tree")
    payload: dict[str, Any] = {
        "schema_version": ARTIFACT_RECEIPT_SCHEMA_VERSION,
        "kind": ARTIFACT_RECEIPT_KIND,
        "distribution_name": distribution_name,
        "distribution_version": distribution_version,
        "source_commit": source["oid"],
        "source_dirty": not status["worktree_clean"],
        "source_tree_digest": source["delivery_tree_digest"],
        "artifact_filename": wheel.name,
        "artifact_sha256": sha256(wheel.read_bytes()).hexdigest(),
        "capability_profile_digest": sha256(contract.read_bytes()).hexdigest(),
        "installed_payload_digest": _wheel_payload_digest(
            wheel,
            known_generated_refs=known_generated_refs,
        ),
        "release_qualifying": status["worktree_clean"],
    }
    payload["receipt_digest"] = _canonical_digest(payload)
    return payload


def build_provider_artifact_bundle(
    source_root: Path,
    wheel_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """构造字段不变的 V1 receipt 与独立 DigestPolicySidecarV1。"""

    receipt = build_provider_artifact_receipt(source_root, wheel_path)
    sidecar = build_digest_policy_sidecar(source_root)
    if sidecar["included_manifest_digest"] != receipt["source_tree_digest"]:
        raise ValueError("provider receipt and digest policy sidecar source digest differ")
    return receipt, sidecar


def validate_provider_artifact_receipt(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != _FIELDS:
        raise ValueError("provider artifact receipt fields are invalid")
    normalized = dict(payload)
    if (
        normalized.get("schema_version") != ARTIFACT_RECEIPT_SCHEMA_VERSION
        or normalized.get("kind") != ARTIFACT_RECEIPT_KIND
    ):
        raise ValueError("provider artifact receipt identity is invalid")
    for key in (
        "distribution_name",
        "distribution_version",
        "artifact_filename",
    ):
        if not isinstance(normalized.get(key), str) or not normalized[key]:
            raise ValueError(f"provider artifact receipt {key} is invalid")
    if not _OID_RE.fullmatch(str(normalized.get("source_commit") or "")):
        raise ValueError("provider artifact receipt source_commit is invalid")
    for key in (
        "source_tree_digest",
        "artifact_sha256",
        "capability_profile_digest",
        "installed_payload_digest",
        "receipt_digest",
    ):
        if not _DIGEST_RE.fullmatch(str(normalized.get(key) or "")):
            raise ValueError(f"provider artifact receipt {key} is invalid")
    if not isinstance(normalized.get("source_dirty"), bool) or not isinstance(
        normalized.get("release_qualifying"), bool
    ):
        raise ValueError("provider artifact receipt booleans are invalid")
    unsigned = {key: value for key, value in normalized.items() if key != "receipt_digest"}
    if normalized["receipt_digest"] != _canonical_digest(unsigned):
        raise ValueError("provider artifact receipt digest mismatch")
    if normalized["release_qualifying"] == normalized["source_dirty"]:
        raise ValueError("provider artifact receipt release qualification is inconsistent")
    return normalized


def load_provider_artifact_receipt(path: Path) -> dict[str, Any]:
    resolved = Path(os.path.abspath(path.expanduser()))
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError("provider artifact receipt must be one regular file")
    receipt = validate_provider_artifact_receipt(
        json.loads(resolved.read_text(encoding="utf-8"))
    )
    _sidecar, sidecar_warnings = load_digest_policy_sidecar(
        resolved,
        expected_included_manifest_digest=receipt["source_tree_digest"],
        allow_missing=True,
    )
    for warning in sidecar_warnings:
        warnings.warn(warning, RuntimeWarning, stacklevel=2)
    return receipt


def artifact_receipt_conflicts(
    receipt: Mapping[str, Any],
    runtime_identity: Mapping[str, Any],
) -> tuple[str, ...]:
    conflicts: list[str] = []
    comparisons = {
        "distribution_name": runtime_identity.get("distribution_name"),
        "distribution_version": runtime_identity.get("distribution_version"),
        "capability_profile_digest": runtime_identity.get("capability_profile_digest"),
        "installed_payload_digest": runtime_identity.get("installed_payload_digest"),
    }
    # 部分 installer（包括 uv）不会保留 direct_url.json，运行时因此无法从
    # 安装目录重新取得原 wheel SHA。artifact receipt 是该字段的 owner；运行时
    # 仍必须逐字验证 distribution、capability 与 installed payload。若 installer
    # 提供了 archive hash，则把它作为额外一致性检查，绝不忽略真实漂移。
    runtime_artifact_sha256 = runtime_identity.get("artifact_sha256")
    if runtime_artifact_sha256 is not None:
        comparisons["artifact_sha256"] = runtime_artifact_sha256
    for field, actual in comparisons.items():
        if receipt.get(field) != actual:
            conflicts.append(f"PROVIDER_RECEIPT_{field.upper()}_MISMATCH")
    if receipt.get("source_dirty") is True:
        conflicts.append("PROVIDER_RECEIPT_SOURCE_DIRTY")
    if receipt.get("release_qualifying") is not True:
        conflicts.append("PROVIDER_RECEIPT_NOT_RELEASE_QUALIFYING")
    return tuple(sorted(conflicts))


__all__ = [
    "ARTIFACT_RECEIPT_KIND",
    "ARTIFACT_RECEIPT_SCHEMA_VERSION",
    "artifact_receipt_conflicts",
    "build_provider_artifact_bundle",
    "build_provider_artifact_receipt",
    "load_provider_artifact_receipt",
    "validate_provider_artifact_receipt",
    "sidecar_path_for_receipt",
]
