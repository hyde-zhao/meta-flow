"""跨 writer 共享投影的只读 generation lineage 查询。"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path, PurePosixPath

_AUTHORIZATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_FIELDS = {
    "schema_version",
    "kind",
    "authorization_id",
    "work_id",
    "plan_digest",
    "state",
    "created_at",
    "updated_at",
    "attempted_refs",
    "applied_refs",
    "targets",
}
_MANIFEST_OPTIONAL_FIELDS = {"failure", "recovery_failures", "lineage"}
_TARGET_FIELDS = {
    "ref",
    "before_digest",
    "after_digest",
    "before_bytes_b64",
    "after_bytes_b64",
}


def _safe_relative_ref(value: object) -> str:
    ref = str(value or "")
    path = PurePosixPath(ref)
    if not ref or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("generation lineage target ref is unsafe")
    return ref


def _validated_manifest(path: Path) -> dict[str, object]:
    if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError("generation lineage manifest path is unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("generation lineage manifest is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("generation lineage manifest must be an object")
    fields = set(payload)
    if not _MANIFEST_FIELDS <= fields or fields - _MANIFEST_FIELDS - _MANIFEST_OPTIONAL_FIELDS:
        raise ValueError("generation lineage manifest fields mismatch")
    authorization_id = str(payload.get("authorization_id") or "")
    work_id = str(payload.get("work_id") or "")
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "work-close-transaction-v1"
        or not _AUTHORIZATION_ID_RE.fullmatch(authorization_id)
        or authorization_id != path.parent.name
        or not _AUTHORIZATION_ID_RE.fullmatch(work_id)
        or not _DIGEST_RE.fullmatch(str(payload.get("plan_digest") or ""))
    ):
        raise ValueError("generation lineage manifest identity is invalid")
    state = str(payload.get("state") or "")
    if state not in {"COMMITTED", "RECOVERED"}:
        raise ValueError(
            f"unresolved Work close transaction requires recovery: {authorization_id}:{state}"
        )
    raw_targets = payload.get("targets")
    lineage = payload.get("lineage", {})
    attempted_refs = payload.get("attempted_refs")
    applied_refs = payload.get("applied_refs")
    if (
        not isinstance(raw_targets, list)
        or len(raw_targets) > 7
        or not isinstance(lineage, Mapping)
        or not isinstance(attempted_refs, list)
        or not isinstance(applied_refs, list)
    ):
        raise ValueError("generation lineage manifest structure is invalid")
    target_refs: list[str] = []
    targets: list[dict[str, str]] = []
    for raw in raw_targets:
        if not isinstance(raw, Mapping) or set(raw) != _TARGET_FIELDS:
            raise ValueError("generation lineage target structure is invalid")
        ref = _safe_relative_ref(raw.get("ref"))
        before_digest = str(raw.get("before_digest") or "")
        after_digest = str(raw.get("after_digest") or "")
        if not _DIGEST_RE.fullmatch(before_digest) or not _DIGEST_RE.fullmatch(after_digest):
            raise ValueError("generation lineage target digest is invalid")
        try:
            before = base64.b64decode(str(raw.get("before_bytes_b64") or ""), validate=True)
            after = base64.b64decode(str(raw.get("after_bytes_b64") or ""), validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("generation lineage target bytes are invalid") from exc
        if sha256(before).hexdigest() != before_digest or sha256(after).hexdigest() != after_digest:
            raise ValueError("generation lineage target bytes/digest mismatch")
        target_refs.append(ref)
        targets.append(
            {
                "ref": ref,
                "before_digest": before_digest,
                "after_digest": after_digest,
            }
        )
    if len(target_refs) != len(set(target_refs)):
        raise ValueError("generation lineage target refs are duplicated")
    for field, refs in (("attempted_refs", attempted_refs), ("applied_refs", applied_refs)):
        if (
            any(not isinstance(ref, str) for ref in refs)
            or len(refs) != len(set(refs))
            or refs != target_refs[: len(refs)]
        ):
            raise ValueError(f"generation lineage {field} is invalid")
    if applied_refs != attempted_refs[: len(applied_refs)]:
        raise ValueError("generation lineage applied_refs exceed attempted_refs")
    normalized_lineage: dict[str, str] = {}
    for raw_ref, raw_predecessor in lineage.items():
        ref = _safe_relative_ref(raw_ref)
        predecessor = str(raw_predecessor or "")
        if (
            ref not in target_refs
            or not _AUTHORIZATION_ID_RE.fullmatch(predecessor)
            or predecessor == authorization_id
        ):
            raise ValueError("generation lineage predecessor binding is invalid")
        normalized_lineage[ref] = predecessor
    return {
        "authorization_id": authorization_id,
        "state": state,
        "created_at": str(payload.get("created_at") or ""),
        "updated_at": str(payload.get("updated_at") or ""),
        "targets": targets,
        "lineage": normalized_lineage,
        "lineage_declared": "lineage" in payload,
    }


def committed_generation_heads(
    transaction_root: Path,
    *,
    refs: tuple[str, ...],
    current_digests: Mapping[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    """返回 Work close 对指定共享 ref 的唯一 COMMITTED head。"""

    if transaction_root.is_symlink():
        raise ValueError("generation lineage transaction root is unsafe")
    root = transaction_root.resolve()
    if root.exists() and not root.is_dir():
        raise ValueError("generation lineage transaction root is unsafe")
    if not root.is_dir():
        return {}
    manifests = [
        _validated_manifest(path)
        for path in sorted(root.glob("*/manifest.json"))
    ]
    by_id = {
        str(manifest["authorization_id"]): manifest
        for manifest in manifests
    }
    for manifest in manifests:
        for ref, predecessor in dict(manifest["lineage"]).items():
            previous = by_id.get(predecessor)
            if (
                previous is None
                or previous["state"] != "COMMITTED"
                or not any(target["ref"] == ref for target in previous["targets"])
            ):
                raise ValueError(
                    f"generation lineage predecessor is invalid: {ref}:{predecessor}"
                )

    heads: dict[str, dict[str, str]] = {}
    for ref in refs:
        candidates = [
            manifest
            for manifest in manifests
            if manifest["state"] == "COMMITTED"
            and any(target["ref"] == ref for target in manifest["targets"])
        ]
        if not candidates:
            continue
        successors: dict[str, str] = {}
        legacy = sorted(
            [manifest for manifest in candidates if not manifest["lineage_declared"]],
            key=lambda manifest: (
                str(manifest["updated_at"]),
                str(manifest["created_at"]),
                str(manifest["authorization_id"]),
            ),
        )
        explicit_legacy_tails = {
            str(dict(manifest["lineage"]).get(ref) or "")
            for manifest in candidates
            if dict(manifest["lineage"]).get(ref)
        } & {str(manifest["authorization_id"]) for manifest in legacy}
        if len(explicit_legacy_tails) > 1:
            raise ValueError(f"generation lineage legacy tail is ambiguous: {ref}")
        if not explicit_legacy_tails and current_digests and current_digests.get(ref):
            matching_legacy_tails = {
                str(manifest["authorization_id"])
                for manifest in legacy
                for target in manifest["targets"]
                if target["ref"] == ref
                and target["after_digest"] == current_digests[ref]
            }
            if len(matching_legacy_tails) > 1:
                raise ValueError(f"generation lineage legacy tail is ambiguous: {ref}")
            explicit_legacy_tails = matching_legacy_tails
        if explicit_legacy_tails:
            tail_id = next(iter(explicit_legacy_tails))
            legacy = [
                manifest
                for manifest in legacy
                if str(manifest["authorization_id"]) != tail_id
            ] + [
                manifest
                for manifest in legacy
                if str(manifest["authorization_id"]) == tail_id
            ]
        for previous, successor in zip(legacy, legacy[1:], strict=False):
            successors[str(previous["authorization_id"])] = str(
                successor["authorization_id"]
            )
        for manifest in candidates:
            predecessor = dict(manifest["lineage"]).get(ref)
            if predecessor is None:
                continue
            successor = str(manifest["authorization_id"])
            existing = successors.get(predecessor)
            if existing is not None and existing != successor:
                raise ValueError(
                    f"generation lineage has multiple successors: {ref}:{predecessor}"
                )
            successors[predecessor] = successor
        head_candidates = [
            manifest
            for manifest in candidates
            if str(manifest["authorization_id"]) not in successors
        ]
        if len(head_candidates) != 1:
            raise ValueError(f"generation lineage head is ambiguous: {ref}")
        head = head_candidates[0]
        target = next(target for target in head["targets"] if target["ref"] == ref)
        heads[ref] = {
            "authorization_id": str(head["authorization_id"]),
            "after_digest": target["after_digest"],
        }
    return heads


def committed_generation_head_digests(
    transaction_root: Path,
    *,
    refs: tuple[str, ...],
    current_digests: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """返回 Work close 对指定共享 ref 的唯一 COMMITTED head 摘要。"""

    return {
        ref: head["after_digest"]
        for ref, head in committed_generation_heads(
            transaction_root,
            refs=refs,
            current_digests=current_digests,
        ).items()
    }


__all__ = ["committed_generation_head_digests", "committed_generation_heads"]
