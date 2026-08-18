"""Provider source/artifact digest 的唯一排除与路径规范化实现。"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

EXCLUSION_POLICY_ID = "source-digest-exclusion-v1"
KNOWN_GENERATED_MANIFEST_REF = (
    "delivery/doc/SOURCE-DIGEST-GENERATED-MANIFEST.json"
)
DIGEST_POLICY_SIDECAR_SCHEMA_VERSION = 1
DIGEST_POLICY_SIDECAR_SUFFIX = ".digest-policy.json"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_EXCLUSION_REASONS = (
    "__pycache__",
    "pyc",
    "build",
    "dist",
    "known_generated",
)
_GENERATED_MANIFEST_FIELDS = {
    "schema_version",
    "kind",
    "generated_refs",
}
_SIDECAR_FIELDS = {
    "manifest_schema_version",
    "exclusion_policy_id",
    "exclusion_policy_digest",
    "included_manifest_digest",
    "included_file_count",
    "excluded_counts_by_reason",
    "tracked_generated_violation_count",
}


class DigestPolicyViolation(ValueError):
    """表示 digest 输入树含不可被排除策略掩盖的结构性错误。"""

    def __init__(self, findings: Iterable[str]) -> None:
        self.findings = tuple(sorted(set(findings)))
        super().__init__("; ".join(self.findings))


@dataclass(frozen=True)
class DeliveryDigestObservation:
    """delivery tree 的 canonical manifest 与排除统计。"""

    included_manifest_digest: str
    included_file_count: int
    excluded_counts_by_reason: dict[str, int]
    exclusion_policy_digest: str
    records: dict[str, str]
    tracked_generated_violation_count: int = 0


@dataclass(frozen=True)
class WheelPayloadObservation:
    """wheel 全 payload 及其中 delivery 子树的 canonical digest。"""

    included_manifest_digest: str
    included_file_count: int
    delivery_manifest_digest: str
    delivery_file_count: int
    excluded_counts_by_reason: dict[str, int]
    records: dict[str, str]


def canonical_digest(payload: object) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(rendered).hexdigest()


def _safe_logical_ref(value: str, *, prefix: str = "delivery") -> bool:
    if not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.parts[:1] == (prefix,)
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _delivery_root(root: Path) -> Path:
    resolved = root.expanduser().resolve()
    delivery = resolved / "delivery" if (resolved / "delivery").is_dir() else resolved
    if not delivery.is_dir() or delivery.is_symlink():
        raise DigestPolicyViolation(("DELIVERY_ROOT_UNSAFE",))
    return delivery


def load_known_generated_refs(
    delivery_root: Path,
    *,
    require_manifest: bool = False,
) -> tuple[str, ...]:
    delivery = _delivery_root(delivery_root)
    manifest = delivery / "doc" / "SOURCE-DIGEST-GENERATED-MANIFEST.json"
    if not manifest.exists():
        if require_manifest:
            raise DigestPolicyViolation(("KNOWN_GENERATED_MANIFEST_MISSING",))
        return ()
    if manifest.is_symlink() or not manifest.is_file():
        raise DigestPolicyViolation(("KNOWN_GENERATED_MANIFEST_UNSAFE",))
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DigestPolicyViolation(("KNOWN_GENERATED_MANIFEST_INVALID",)) from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != _GENERATED_MANIFEST_FIELDS
        or payload.get("schema_version") != 1
        or payload.get("kind") != "SourceDigestGeneratedManifestV1"
        or not isinstance(payload.get("generated_refs"), list)
    ):
        raise DigestPolicyViolation(("KNOWN_GENERATED_MANIFEST_INVALID",))
    refs = tuple(payload["generated_refs"])
    if (
        any(not isinstance(ref, str) or not _safe_logical_ref(ref) for ref in refs)
        or tuple(sorted(set(refs))) != refs
        or KNOWN_GENERATED_MANIFEST_REF in refs
    ):
        raise DigestPolicyViolation(("KNOWN_GENERATED_MANIFEST_REFS_INVALID",))
    return refs


def exclusion_policy_payload(known_generated_refs: Iterable[str] = ()) -> dict[str, Any]:
    refs = tuple(sorted(set(known_generated_refs)))
    return {
        "schema_version": 1,
        "exclusion_policy_id": EXCLUSION_POLICY_ID,
        "exclude": [
            {"kind": "exact_dir", "path": "__pycache__", "scope": "any"},
            {"kind": "exact_suffix", "suffix": ".pyc", "scope": "any"},
            {"kind": "exact_dir", "path": "build", "scope": "delivery-root"},
            {"kind": "exact_dir", "path": "dist", "scope": "delivery-root"},
            {
                "kind": "known_generated",
                "manifest_ref": KNOWN_GENERATED_MANIFEST_REF,
                "refs": list(refs),
            },
        ],
        "block": [
            "symlink",
            "submodule",
            "outside_root",
            "duplicate_logical_owner",
        ],
        "tracked_generated": ["__pycache__", "pyc", "build", "dist"],
    }


def exclusion_policy_digest(known_generated_refs: Iterable[str] = ()) -> str:
    return canonical_digest(exclusion_policy_payload(known_generated_refs))


def _exclusion_reason(
    logical_ref: str,
    *,
    known_generated_refs: frozenset[str],
) -> str | None:
    path = PurePosixPath(logical_ref)
    if "__pycache__" in path.parts:
        return "__pycache__"
    if path.suffix == ".pyc":
        return "pyc"
    # build/dist 只属于 delivery 根一级排除项。wheel/install 的全 payload
    # 若出现顶层 build/ 或 dist/，必须继续参与 artifact digest，不能被静默隐藏。
    if path.parts[:1] == ("delivery",):
        relative_parts = path.parts[1:]
        if relative_parts[:1] == ("build",):
            return "build"
        if relative_parts[:1] == ("dist",):
            return "dist"
    if logical_ref in known_generated_refs:
        return "known_generated"
    return None


def _git_delivery_inventory(delivery: Path) -> tuple[frozenset[str], tuple[str, ...]]:
    root_result = subprocess.run(
        ["git", "-C", str(delivery), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if root_result.returncode != 0:
        return frozenset(), ()
    git_root = Path(root_result.stdout.strip()).resolve()
    try:
        delivery_relative = delivery.relative_to(git_root)
    except ValueError:
        return frozenset(), ("DELIVERY_OUTSIDE_GIT_ROOT",)
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(git_root),
            "ls-files",
            "--stage",
            "-z",
            "--",
            delivery_relative.as_posix(),
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        return frozenset(), ("GIT_INVENTORY_UNAVAILABLE",)
    tracked: set[str] = set()
    findings: list[str] = []
    prefix = delivery_relative.parts
    for entry in completed.stdout.split(b"\0"):
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            mode = metadata.split(b" ", 1)[0].decode("ascii")
            repo_ref = PurePosixPath(raw_path.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            findings.append("GIT_INVENTORY_INVALID")
            continue
        if tuple(repo_ref.parts[: len(prefix)]) != prefix:
            findings.append("GIT_INVENTORY_OUTSIDE_DELIVERY")
            continue
        relative = PurePosixPath(*repo_ref.parts[len(prefix) :])
        logical_ref = PurePosixPath("delivery", relative).as_posix()
        tracked.add(logical_ref)
        if mode == "160000":
            findings.append(f"SUBMODULE:{logical_ref}")
    return frozenset(tracked), tuple(findings)


def observe_delivery_tree(
    root: Path,
    *,
    require_generated_manifest: bool = False,
) -> DeliveryDigestObservation:
    delivery = _delivery_root(root)
    known_refs = load_known_generated_refs(
        delivery,
        require_manifest=require_generated_manifest,
    )
    known_set = frozenset(known_refs)
    tracked_refs, inventory_findings = _git_delivery_inventory(delivery)
    findings = list(inventory_findings)
    records: dict[str, str] = {}
    excluded = {reason: 0 for reason in _EXCLUSION_REASONS}
    tracked_generated: list[str] = []
    delivery_resolved = delivery.resolve()
    seen: set[str] = set()
    for path in sorted(delivery.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(delivery)
        # standalone delivery repo 的根级 .git 是版本控制容器，不是 delivery owner。
        if relative.parts[:1] == (".git",):
            continue
        logical_ref = (PurePosixPath("delivery") / PurePosixPath(relative.as_posix())).as_posix()
        if logical_ref in seen:
            findings.append(f"DUPLICATE_LOGICAL_OWNER:{logical_ref}")
            continue
        seen.add(logical_ref)
        if path.is_symlink():
            findings.append(f"SYMLINK:{logical_ref}")
            continue
        if path.name == ".git":
            findings.append(f"SUBMODULE_MARKER:{logical_ref}")
            continue
        try:
            path.resolve(strict=False).relative_to(delivery_resolved)
        except ValueError:
            findings.append(f"OUTSIDE_ROOT:{logical_ref}")
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            findings.append(f"UNSUPPORTED_FILE_TYPE:{logical_ref}")
            continue
        reason = _exclusion_reason(logical_ref, known_generated_refs=known_set)
        if reason is not None:
            excluded[reason] += 1
            if reason != "known_generated" and logical_ref in tracked_refs:
                tracked_generated.append(logical_ref)
            continue
        records[logical_ref] = sha256(path.read_bytes()).hexdigest()
    findings.extend(f"TRACKED_GENERATED:{ref}" for ref in tracked_generated)
    if findings:
        raise DigestPolicyViolation(findings)
    return DeliveryDigestObservation(
        included_manifest_digest=canonical_digest(records),
        included_file_count=len(records),
        excluded_counts_by_reason=excluded,
        exclusion_policy_digest=exclusion_policy_digest(known_refs),
        records=records,
        tracked_generated_violation_count=0,
    )


def _safe_archive_ref(value: str) -> str | None:
    if not value or "\\" in value or value.startswith("/"):
        return None
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def _is_distribution_generated(relative: PurePosixPath) -> bool:
    rendered = relative.as_posix()
    if ".dist-info/" not in rendered:
        return False
    return relative.name in {
        "INSTALLER",
        "RECORD",
        "REQUESTED",
        "direct_url.json",
        "uv_cache.json",
    }


def payload_exclusion_reason(
    logical_ref: str,
    *,
    known_generated_refs: Iterable[str] = (),
) -> str | None:
    """返回 source/wheel/install payload 共用的精确排除原因。"""

    normalized = _safe_archive_ref(logical_ref)
    if normalized is None:
        raise DigestPolicyViolation((f"ARCHIVE_PATH_UNSAFE:{logical_ref}",))
    reason = _exclusion_reason(
        normalized,
        known_generated_refs=frozenset(known_generated_refs),
    )
    if reason is not None:
        return reason
    if _is_distribution_generated(PurePosixPath(normalized)):
        return "distribution_metadata"
    return None


def observe_wheel_payload(
    archive: Any,
    *,
    known_generated_refs: Iterable[str] | None = None,
) -> WheelPayloadObservation:
    refs = (
        tuple(known_generated_refs)
        if known_generated_refs is not None
        else load_known_generated_refs(Path(__file__).resolve().parents[1])
    )
    known_set = frozenset(refs)
    records: dict[str, str] = {}
    delivery_records: dict[str, str] = {}
    excluded = {**{reason: 0 for reason in _EXCLUSION_REASONS}, "distribution_metadata": 0}
    findings: list[str] = []
    seen: set[str] = set()
    for info in archive.infolist():
        logical_ref = _safe_archive_ref(info.filename.rstrip("/"))
        if logical_ref is None:
            raw_parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            code = (
                "OUTSIDE_ROOT"
                if info.filename.startswith("/") or ".." in raw_parts
                else "ARCHIVE_PATH_UNSAFE"
            )
            findings.append(f"{code}:{info.filename}")
            continue
        if info.is_dir():
            continue
        if logical_ref in seen:
            findings.append(f"DUPLICATE_LOGICAL_OWNER:{logical_ref}")
            continue
        seen.add(logical_ref)
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            findings.append(f"SYMLINK:{logical_ref}")
            continue
        reason = payload_exclusion_reason(
            logical_ref,
            known_generated_refs=known_set,
        )
        if reason is not None:
            excluded[reason] += 1
            continue
        digest = sha256(archive.read(info)).hexdigest()
        records[logical_ref] = digest
        if PurePosixPath(logical_ref).parts[:1] == ("delivery",):
            delivery_records[logical_ref] = digest
    if findings:
        raise DigestPolicyViolation(findings)
    return WheelPayloadObservation(
        included_manifest_digest=canonical_digest(records),
        included_file_count=len(records),
        delivery_manifest_digest=canonical_digest(delivery_records),
        delivery_file_count=len(delivery_records),
        excluded_counts_by_reason=excluded,
        records=records,
    )


def build_digest_policy_sidecar(source_root: Path) -> dict[str, Any]:
    observation = observe_delivery_tree(source_root, require_generated_manifest=True)
    payload = {
        "manifest_schema_version": DIGEST_POLICY_SIDECAR_SCHEMA_VERSION,
        "exclusion_policy_id": EXCLUSION_POLICY_ID,
        "exclusion_policy_digest": observation.exclusion_policy_digest,
        "included_manifest_digest": observation.included_manifest_digest,
        "included_file_count": observation.included_file_count,
        "excluded_counts_by_reason": observation.excluded_counts_by_reason,
        "tracked_generated_violation_count": (
            observation.tracked_generated_violation_count
        ),
    }
    return validate_digest_policy_sidecar(payload)


def validate_digest_policy_sidecar(
    payload: object,
    *,
    expected_included_manifest_digest: str | None = None,
    expected_policy_digest: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != _SIDECAR_FIELDS:
        raise ValueError("digest policy sidecar fields are invalid")
    normalized = dict(payload)
    counts = normalized.get("excluded_counts_by_reason")
    if (
        normalized.get("manifest_schema_version")
        != DIGEST_POLICY_SIDECAR_SCHEMA_VERSION
        or normalized.get("exclusion_policy_id") != EXCLUSION_POLICY_ID
        or not _DIGEST_RE.fullmatch(str(normalized.get("exclusion_policy_digest") or ""))
        or not _DIGEST_RE.fullmatch(str(normalized.get("included_manifest_digest") or ""))
        or not isinstance(normalized.get("included_file_count"), int)
        or isinstance(normalized.get("included_file_count"), bool)
        or normalized["included_file_count"] < 1
        or not isinstance(counts, Mapping)
        or set(counts) != set(_EXCLUSION_REASONS)
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in counts.values()
        )
        or normalized.get("tracked_generated_violation_count") != 0
    ):
        raise ValueError("digest policy sidecar values are invalid")
    if (
        expected_included_manifest_digest is not None
        and normalized["included_manifest_digest"]
        != expected_included_manifest_digest
    ):
        raise ValueError("digest policy sidecar included manifest digest mismatch")
    if (
        expected_policy_digest is not None
        and normalized["exclusion_policy_digest"] != expected_policy_digest
    ):
        raise ValueError("digest policy sidecar policy digest mismatch")
    normalized["excluded_counts_by_reason"] = dict(counts)
    return normalized


def sidecar_path_for_receipt(receipt_path: Path) -> Path:
    # 不调用 resolve()：必须保留最终 leaf 的 symlink 身份，交给 reader/writer
    # fail closed，而不是跟随链接后误判为普通文件。
    target = Path(os.path.abspath(receipt_path.expanduser()))
    return target.with_name(target.stem + DIGEST_POLICY_SIDECAR_SUFFIX)


def load_digest_policy_sidecar(
    receipt_path: Path,
    *,
    expected_included_manifest_digest: str,
    allow_missing: bool = True,
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    sidecar_path = sidecar_path_for_receipt(receipt_path)
    if not sidecar_path.exists():
        if allow_missing:
            return None, ("DIGEST_POLICY_SIDECAR_MISSING_LEGACY",)
        raise ValueError("digest policy sidecar is missing")
    if sidecar_path.is_symlink() or not sidecar_path.is_file():
        raise ValueError("digest policy sidecar path is unsafe")
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("digest policy sidecar is unreadable") from exc
    current_refs = load_known_generated_refs(Path(__file__).resolve().parents[1])
    return (
        validate_digest_policy_sidecar(
            payload,
            expected_included_manifest_digest=expected_included_manifest_digest,
            expected_policy_digest=exclusion_policy_digest(current_refs),
        ),
        (),
    )


__all__ = [
    "DIGEST_POLICY_SIDECAR_SUFFIX",
    "DigestPolicyViolation",
    "EXCLUSION_POLICY_ID",
    "KNOWN_GENERATED_MANIFEST_REF",
    "build_digest_policy_sidecar",
    "canonical_digest",
    "exclusion_policy_digest",
    "load_digest_policy_sidecar",
    "load_known_generated_refs",
    "observe_delivery_tree",
    "observe_wheel_payload",
    "payload_exclusion_reason",
    "sidecar_path_for_receipt",
    "validate_digest_policy_sidecar",
]
