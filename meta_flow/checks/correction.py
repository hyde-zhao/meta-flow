"""Append-only post-close correction contracts.

This module is deliberately a validator/replay layer.  It never mutates the
historical target; the only writable object is a separately supplied
correction ledger after a caller has checked its prefix hash.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

REQUIRED_CORRECTION_FIELDS = (
    "schema_version", "event_id", "target_ref", "patch", "author", "reason", "evidence_refs", "created_at",
)
ALLOWED_PATCH_PREFIXES = ("/annotations/", "/evidence_refs", "/provenance/")


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}" if path.is_file() else ""


def _valid_target(value: Any) -> bool:
    return isinstance(value, dict) and all(value.get(key) for key in ("namespace", "id", "source_sha256"))


def validate_correction_event(event: dict[str, Any], *, chain: list[dict[str, Any]] | None = None) -> list[str]:
    errors = [f"missing correction field: {field}" for field in REQUIRED_CORRECTION_FIELDS if not event.get(field)]
    if event.get("schema_version") not in {"meta-flow.correction/v1", 1}:
        errors.append("schema_version must be meta-flow.correction/v1")
    if event.get("historical_mutation") is True:
        errors.append("historical_mutation must be false; corrections are append-only")
    if not _valid_target(event.get("target_ref")):
        errors.append("target_ref must contain namespace, id, and source_sha256")
    if not isinstance(event.get("evidence_refs"), list) or not event.get("evidence_refs"):
        errors.append("evidence_refs must be a non-empty list")
    patch = event.get("patch")
    if not isinstance(patch, list) or not patch:
        errors.append("patch must be a non-empty list")
    else:
        for index, operation in enumerate(patch):
            if not isinstance(operation, dict):
                errors.append(f"patch[{index}] must be an object")
                continue
            if operation.get("op") not in {"add", "replace"}:
                errors.append(f"patch[{index}] operation must be add or replace")
            path = str(operation.get("path") or "")
            if not any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in ALLOWED_PATCH_PREFIXES):
                errors.append(f"patch[{index}] path is outside correction allowlist: {path or '-'}")
    if chain:
        ids = {str(item.get("event_id") or "") for item in chain}
        supersedes = event.get("supersedes")
        if supersedes and supersedes not in ids:
            errors.append("supersedes references a missing correction event")
        if any(str(item.get("event_id") or "") == str(event.get("event_id") or "") for item in chain):
            errors.append("event_id already exists in correction chain")
        if supersedes:
            by_id = {str(item.get("event_id") or ""): item for item in chain}
            seen = {str(event.get("event_id") or "")}
            cursor = str(supersedes)
            while cursor:
                if cursor in seen:
                    errors.append("supersedes chain contains a cycle")
                    break
                seen.add(cursor)
                cursor = str((by_id.get(cursor) or {}).get("supersedes") or "")
    return errors


def append_correction(path: Path, event: dict[str, Any], *, expected_prefix_hash: str, chain: list[dict[str, Any]] | None = None) -> dict[str, str]:
    errors = validate_correction_event(event, chain=chain)
    if errors:
        raise ValueError("invalid correction event: " + "; ".join(errors))
    actual = _sha256(path) if path.exists() else f"sha256:{hashlib.sha256(b'').hexdigest()}"
    if actual != expected_prefix_hash:
        raise ValueError("correction ledger prefix hash changed; append refused")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if not path.read_text(encoding="utf-8").endswith(payload):
        raise OSError("correction append tail verification failed")
    return {"event_id": str(event["event_id"]), "prefix_sha256": actual, "new_prefix_sha256": _sha256(path)}


def replay_corrections(original: dict[str, Any], chain: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply accepted correction annotations to a derived copy only."""

    derived = deepcopy(original)
    for event in sorted(chain, key=lambda item: (str(item.get("created_at") or ""), str(item.get("event_id") or ""))):
        if validate_correction_event(event, chain=[item for item in chain if item is not event]):
            continue
        for operation in event["patch"]:
            parts = [part for part in str(operation["path"]).split("/") if part]
            target: dict[str, Any] = derived
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = operation.get("value")
    return derived
