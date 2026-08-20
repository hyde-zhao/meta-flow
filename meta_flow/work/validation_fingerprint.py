"""分层验证输入的 canonical source fingerprint。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.read_contract import is_safe_read_ref

VALIDATION_LAYERS = ("targeted", "compatibility", "full")
SOURCE_ROLES = {"production", "test", "config", "lock"}
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ValidationSource:
    logical_ref: str
    role: str
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        if not is_safe_read_ref(self.logical_ref):
            raise ValueError("validation source requires one safe logical ref")
        if self.role not in SOURCE_ROLES:
            raise ValueError(f"unsupported validation source role: {self.role}")
        if not _HEX_RE.fullmatch(self.sha256):
            raise ValueError("validation source sha256 must be one lowercase digest")
        if type(self.bytes) is not int or self.bytes < 0:
            raise ValueError("validation source bytes must be a non-negative integer")

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def source_from_file(project_root: Path, logical_ref: str, *, role: str) -> ValidationSource:
    if not is_safe_read_ref(logical_ref):
        raise ValueError("validation source requires one safe logical ref")
    data = (project_root.resolve() / logical_ref).read_bytes()
    return ValidationSource(logical_ref, role, sha256(data).hexdigest(), len(data))


@dataclass(frozen=True)
class ValidationFingerprint:
    schema_version: int
    layer: str
    sources: tuple[ValidationSource, ...]
    profile_digest: str
    digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "layer": self.layer,
            "sources": [source.as_dict() for source in self.sources],
            "profile_digest": self.profile_digest,
            "digest": self.digest,
        }


def build_validation_fingerprint(
    layer: str,
    sources: Iterable[ValidationSource],
    *,
    profile_digest: str,
) -> ValidationFingerprint:
    if layer not in VALIDATION_LAYERS:
        raise ValueError(f"unsupported validation layer: {layer}")
    if not _HEX_RE.fullmatch(profile_digest):
        raise ValueError("profile_digest must be one lowercase sha256")
    ordered = tuple(sorted(sources, key=lambda source: (source.role, source.logical_ref)))
    if not ordered:
        raise ValueError("validation fingerprint requires sources")
    if len({source.logical_ref for source in ordered}) != len(ordered):
        raise ValueError("validation fingerprint contains duplicate logical refs")
    missing_roles = SOURCE_ROLES - {source.role for source in ordered}
    if missing_roles:
        raise ValueError(
            "validation fingerprint missing source roles: " + ",".join(sorted(missing_roles))
        )
    semantic = {
        "schema_version": 1,
        "layer": layer,
        "sources": [source.as_dict() for source in ordered],
        "profile_digest": profile_digest,
    }
    return ValidationFingerprint(1, layer, ordered, profile_digest, _digest(semantic))


def command_identity(argv: Iterable[str]) -> str:
    command = tuple(argv)
    if not command or not all(isinstance(item, str) and item for item in command):
        raise ValueError("command identity requires non-empty argv entries")
    return _digest({"schema_version": 1, "argv": list(command)})


def source_manifest_digest(fingerprint: ValidationFingerprint) -> str:
    """为 validation provider 投影稳定 manifest；不读取额外文件。"""

    return _digest(
        {
            "schema_version": 1,
            "sources": [source.as_dict() for source in fingerprint.sources],
        }
    )
