"""Validation receipt 的语义身份对象；不读取文件、不拥有 planner 状态。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.\d+)?(?:[-+._A-Za-z0-9]*)?$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_LAYERS = frozenset({"targeted", "compatibility", "full"})
_SEMANTIC_FIELDS = {
    "python",
    "python_implementation",
    "python_version",
    "platform",
    "platform_system",
    "architecture",
    "platform_machine",
    "toolchain",
    "toolchains",
    "uv",
}
_INCIDENTAL_FIELDS = {
    "cache",
    "cache_dir",
    "cwd",
    "home",
    "hostname",
    "temp",
    "timestamp",
    "username",
}


def _digest(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(rendered.encode("utf-8")).hexdigest()


def _major_minor(value: str, *, code: str) -> str:
    match = _VERSION_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(code)
    return f"{match.group(1)}.{match.group(2)}"


@dataclass(frozen=True)
class SemanticEnvironmentV1:
    python_implementation: str
    python_major_minor: str
    platform_system: str
    platform_machine: str
    toolchains: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if (
            not _SAFE_NAME_RE.fullmatch(self.python_implementation)
            or not re.fullmatch(r"\d+\.\d+", self.python_major_minor)
            or not _SAFE_NAME_RE.fullmatch(self.platform_system)
            or not _SAFE_NAME_RE.fullmatch(self.platform_machine)
            or tuple(sorted(set(self.toolchains))) != self.toolchains
            or not self.toolchains
            or any(
                not _SAFE_NAME_RE.fullmatch(name)
                or not re.fullmatch(r"\d+\.\d+", version)
                for name, version in self.toolchains
            )
        ):
            raise ValueError("SEMANTIC_ENVIRONMENT_INVALID")

    def as_dict(self) -> dict[str, object]:
        return {
            "python_implementation": self.python_implementation,
            "python_major_minor": self.python_major_minor,
            "platform_system": self.platform_system,
            "platform_machine": self.platform_machine,
            "toolchains": [
                {"name": name, "major_minor": version}
                for name, version in self.toolchains
            ],
        }

    @property
    def digest(self) -> str:
        return _digest(self.as_dict())


def normalize_semantic_environment(raw: Mapping[str, Any]) -> SemanticEnvironmentV1:
    """丢弃显式 incidental 字段；未知字段和缺失安全字段保守拒绝。"""

    unknown = set(raw) - _SEMANTIC_FIELDS - _INCIDENTAL_FIELDS
    if unknown:
        raise ValueError("SEMANTIC_ENVIRONMENT_UNKNOWN_FIELD")
    python_implementation = str(raw.get("python_implementation") or "")
    python_version = str(raw.get("python_version") or "")
    combined_python = str(raw.get("python") or "").split()
    if not python_implementation and len(combined_python) == 2:
        python_implementation, python_version = combined_python
    platform_system = str(raw.get("platform_system") or raw.get("platform") or "")
    platform_machine = str(raw.get("platform_machine") or raw.get("architecture") or "")
    raw_toolchains = raw.get("toolchains", raw.get("toolchain"))
    if raw_toolchains is None and raw.get("uv") is not None:
        raw_toolchains = {"uv": raw["uv"]}
    if not isinstance(raw_toolchains, Mapping):
        raise ValueError("SEMANTIC_ENVIRONMENT_TOOLCHAIN_INVALID")
    toolchains = tuple(
        sorted(
            (
                str(name),
                _major_minor(
                    str(version), code="SEMANTIC_ENVIRONMENT_TOOLCHAIN_VERSION_INVALID"
                ),
            )
            for name, version in raw_toolchains.items()
        )
    )
    return SemanticEnvironmentV1(
        python_implementation,
        _major_minor(
            python_version, code="SEMANTIC_ENVIRONMENT_PYTHON_VERSION_INVALID"
        ),
        platform_system,
        platform_machine,
        toolchains,
    )


@dataclass(frozen=True, order=True)
class SourceManifestEntryV1:
    logical_ref: str
    sha256: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.logical_ref)
        if (
            not self.logical_ref
            or path.is_absolute()
            or path.as_posix() != self.logical_ref
            or any(part in {"", ".", ".."} for part in path.parts)
            or not _DIGEST_RE.fullmatch(self.sha256)
        ):
            raise ValueError("SOURCE_MANIFEST_ENTRY_INVALID")

    def as_dict(self) -> dict[str, str]:
        return {"logical_ref": self.logical_ref, "sha256": self.sha256}


@dataclass(frozen=True)
class SourceManifestV1:
    entries: tuple[SourceManifestEntryV1, ...]

    def __post_init__(self) -> None:
        if not self.entries or tuple(sorted(set(self.entries))) != self.entries:
            raise ValueError("SOURCE_MANIFEST_INVALID")
        if len({entry.logical_ref for entry in self.entries}) != len(self.entries):
            raise ValueError("SOURCE_MANIFEST_DUPLICATE_REF")

    def as_dict(self) -> dict[str, object]:
        return {"entries": [entry.as_dict() for entry in self.entries]}

    @property
    def digest(self) -> str:
        return _digest(self.as_dict())


def build_source_manifest(
    entries: Mapping[str, str] | Sequence[tuple[str, str]],
) -> SourceManifestV1:
    values = entries.items() if isinstance(entries, Mapping) else entries
    normalized = tuple(
        sorted(SourceManifestEntryV1(str(ref), str(digest)) for ref, digest in values)
    )
    return SourceManifestV1(normalized)


@dataclass(frozen=True)
class ReceiptIdentityV2:
    layer: str
    source_fingerprint_digest: str
    profile_digest: str
    command_identity: str
    environment: SemanticEnvironmentV1
    source_manifest: SourceManifestV1
    provider_identity_digest: str
    outcome: str
    partial_mutation: bool = False

    def __post_init__(self) -> None:
        if (
            self.layer not in _LAYERS
            or any(
                not _DIGEST_RE.fullmatch(value)
                for value in (
                    self.source_fingerprint_digest,
                    self.profile_digest,
                    self.provider_identity_digest,
                )
            )
            or not self.command_identity.strip()
            or self.outcome not in {"PASS", "FAIL", "BLOCKED"}
            or type(self.partial_mutation) is not bool
        ):
            raise ValueError("RECEIPT_IDENTITY_V2_INVALID")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": "ReceiptIdentityV2",
            "layer": self.layer,
            "source_fingerprint_digest": self.source_fingerprint_digest,
            "profile_digest": self.profile_digest,
            "command_identity": self.command_identity,
            "environment": self.environment.as_dict(),
            "environment_digest": self.environment.digest,
            "source_manifest": self.source_manifest.as_dict(),
            "source_manifest_digest": self.source_manifest.digest,
            "provider_identity_digest": self.provider_identity_digest,
            "outcome": self.outcome,
            "partial_mutation": self.partial_mutation,
        }

    @property
    def digest(self) -> str:
        return _digest(self.as_dict())


def build_receipt_identity_v2(
    *,
    layer: str,
    source_fingerprint_digest: str,
    profile_digest: str,
    command_identity: str,
    environment: SemanticEnvironmentV1 | Mapping[str, Any],
    source_manifest: SourceManifestV1 | Mapping[str, str],
    provider_identity_digest: str,
    outcome: str,
    partial_mutation: bool = False,
) -> ReceiptIdentityV2:
    return ReceiptIdentityV2(
        layer,
        source_fingerprint_digest,
        profile_digest,
        command_identity,
        environment
        if isinstance(environment, SemanticEnvironmentV1)
        else normalize_semantic_environment(environment),
        source_manifest
        if isinstance(source_manifest, SourceManifestV1)
        else build_source_manifest(source_manifest),
        provider_identity_digest,
        outcome,
        partial_mutation,
    )
