"""STATE、CURRENT 与人类摘要的可恢复文件集事务。"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.process_route import _resolve_runtime_ref

TRANSACTION_ROOT_REL = Path(".meta-flow-runtime/state-projection")
MANIFEST_REL = TRANSACTION_ROOT_REL / "transaction.json"
LOCK_REL = TRANSACTION_ROOT_REL / "writer.lock"
ALLOWED_TARGET_REFS = frozenset(
    {
        "process/state/STATE.current.json",
        "process/STATE.md",
        "process/current/CURRENT.json",
    }
)
TERMINAL_STATES = frozenset({"COMMITTED", "RECOVERED"})


def _digest(value: bytes | None) -> str:
    return "missing" if value is None else sha256(value).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _ensure_runtime_root(project_root: Path) -> Path:
    root = project_root.resolve()
    runtime = root / TRANSACTION_ROOT_REL
    cursor = root
    for part in TRANSACTION_ROOT_REL.parts:
        cursor = cursor / part
        if cursor.is_symlink() or (cursor.exists() and not cursor.is_dir()):
            raise ValueError(f"state projection runtime path is unsafe: {cursor}")
        cursor.mkdir(exist_ok=True)
    return runtime


def _ensure_plain_directory(path: Path, *, require_new: bool = False) -> None:
    """逐级建立目录，并拒绝任一现存 symlink/非目录祖先。"""

    chain = [path, *path.parents]
    for directory in reversed(chain[:-1]):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ValueError(f"state projection directory path is unsafe: {directory}")
        if directory == path and require_new and directory.exists():
            raise FileExistsError(f"state projection directory already exists: {directory}")
        if not directory.exists():
            directory.mkdir()


def _read_target(path: Path) -> bytes | None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"state projection target is not a regular file: {path}")
    return path.read_bytes() if path.is_file() else None


def _replace_bytes(path: Path, value: bytes) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"state projection target is not a regular file: {path}")
    _ensure_plain_directory(path.parent)
    temporary = path.with_name(
        f".{path.name}.{secrets.token_hex(8)}.state-projection.tmp"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def _acquire_lock(lock_path: Path, transaction_id: str) -> None:
    if lock_path.is_symlink() or lock_path.exists():
        raise ValueError("state projection writer lock is already held or unsafe")
    try:
        with lock_path.open("x", encoding="utf-8") as handle:
            handle.write(transaction_id + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ValueError("state projection writer lock is already held") from exc


def _release_lock(lock_path: Path, transaction_id: str) -> None:
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ValueError("state projection writer lock ownership is unsafe")
    if lock_path.read_text(encoding="utf-8") != transaction_id + "\n":
        raise ValueError("state projection writer lock identity drifted")
    lock_path.unlink()


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    rendered = (
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _replace_bytes(path, rendered)


def _target_record(ref: str, before: bytes | None, after: bytes) -> dict[str, Any]:
    return {
        "ref": ref,
        "before_digest": _digest(before),
        "after_digest": _digest(after),
        "before_bytes_b64": None
        if before is None
        else base64.b64encode(before).decode("ascii"),
        "after_bytes_b64": base64.b64encode(after).decode("ascii"),
    }


def _decode_target(raw: Mapping[str, Any]) -> tuple[str, bytes | None, bytes]:
    expected = {
        "ref",
        "before_digest",
        "after_digest",
        "before_bytes_b64",
        "after_bytes_b64",
    }
    if set(raw) != expected:
        raise ValueError("state projection transaction target fields mismatch")
    ref = str(raw["ref"])
    if ref not in ALLOWED_TARGET_REFS:
        raise ValueError(f"state projection transaction target is not allowed: {ref}")
    before_raw = raw["before_bytes_b64"]
    try:
        before = None if before_raw is None else base64.b64decode(str(before_raw), validate=True)
        after = base64.b64decode(str(raw["after_bytes_b64"]), validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("state projection transaction target bytes are invalid") from exc
    if _digest(before) != raw["before_digest"] or _digest(after) != raw["after_digest"]:
        raise ValueError("state projection transaction target digest mismatch")
    return ref, before, after


def _load_manifest(project_root: Path) -> tuple[Path, dict[str, Any] | None]:
    path = project_root.resolve() / MANIFEST_REL
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("state projection transaction manifest is unsafe")
    if not path.is_file():
        return path, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("state projection transaction manifest is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("state projection transaction manifest must be an object")
    expected = {
        "schema_version",
        "kind",
        "transaction_id",
        "state",
        "created_at",
        "updated_at",
        "attempted_refs",
        "applied_refs",
        "targets",
    }
    if set(payload) - (expected | {"failure", "recovery_failures"}) or not expected.issubset(
        payload
    ):
        raise ValueError("state projection transaction manifest fields mismatch")
    if payload["schema_version"] != 1 or payload["kind"] != "StateProjectionTransactionV1":
        raise ValueError("state projection transaction manifest kind/version mismatch")
    if payload["state"] not in {"PREPARED", "APPLYING", "PARTIAL", *TERMINAL_STATES}:
        raise ValueError("state projection transaction state is invalid")
    targets = payload["targets"]
    if not isinstance(targets, list) or not targets:
        raise ValueError("state projection transaction targets must be non-empty")
    decoded = [_decode_target(item) for item in targets if isinstance(item, dict)]
    if len(decoded) != len(targets) or len({item[0] for item in decoded}) != len(decoded):
        raise ValueError("state projection transaction targets are invalid or duplicated")
    refs = [item[0] for item in decoded]
    for field in ("attempted_refs", "applied_refs"):
        value = payload[field]
        if not isinstance(value, list) or len(value) != len(set(value)):
            raise ValueError(f"state projection transaction {field} is invalid")
        if value != refs[: len(value)]:
            raise ValueError(f"state projection transaction {field} is not an ordered prefix")
    if len(payload["applied_refs"]) > len(payload["attempted_refs"]):
        raise ValueError("state projection transaction accounting is invalid")
    return path, payload


def _restore_targets(project_root: Path, payload: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    decoded = [_decode_target(item) for item in payload["targets"]]
    attempted = set(payload["attempted_refs"])
    for ref, before, after in reversed(decoded):
        if ref not in attempted:
            continue
        path = _resolve_runtime_ref(project_root, ref)
        try:
            current = _read_target(path)
            if _digest(current) == _digest(before):
                continue
            if _digest(current) != _digest(after):
                failures.append(f"GENERATION_DRIFT:{ref}")
                continue
            if before is None:
                path.unlink(missing_ok=True)
            else:
                _replace_bytes(path, before)
        except (OSError, ValueError) as exc:
            failures.append(f"RESTORE_FAILED:{ref}:{type(exc).__name__}")
    return failures


def inspect_state_projection_transaction(project_root: Path) -> dict[str, Any]:
    try:
        _path, payload = _load_manifest(project_root)
    except (OSError, ValueError) as exc:
        return {"decision": "BLOCKED", "state": "INVALID", "findings": [str(exc)]}
    if payload is None:
        return {"decision": "PASS", "state": "NONE", "findings": []}
    findings: list[str] = []
    expected_after = payload["state"] == "COMMITTED"
    for raw in payload["targets"]:
        ref, before, after = _decode_target(raw)
        current = _read_target(_resolve_runtime_ref(project_root, ref))
        expected = after if expected_after else before
        if payload["state"] in TERMINAL_STATES and _digest(current) != _digest(expected):
            findings.append(f"TERMINAL_GENERATION_DRIFT:{ref}")
    if payload["state"] not in TERMINAL_STATES:
        findings.append(f"UNRESOLVED_STATE_PROJECTION_TRANSACTION:{payload['state']}")
    return {
        "decision": "BLOCKED" if findings else "PASS",
        "state": payload["state"],
        "transaction_id": payload["transaction_id"],
        "findings": findings,
    }


def recover_state_projection_transaction(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    manifest_path, payload = _load_manifest(root)
    if payload is None:
        return {"decision": "NO_CHANGE", "state": "NONE", "recovered_refs": []}
    if payload["state"] in TERMINAL_STATES:
        inspection = inspect_state_projection_transaction(root)
        return {
            "decision": "NO_CHANGE" if inspection["decision"] == "PASS" else "BLOCKED",
            "state": payload["state"],
            "recovered_refs": [],
            "findings": inspection["findings"],
        }
    failures = _restore_targets(root, payload)
    payload["state"] = "PARTIAL" if failures else "RECOVERED"
    payload["updated_at"] = _now()
    if failures:
        payload["recovery_failures"] = failures
    _write_manifest(manifest_path, payload)
    return {
        "decision": "PARTIAL" if failures else "RECOVERED",
        "state": payload["state"],
        "recovered_refs": list(reversed(payload["attempted_refs"])) if not failures else [],
        "findings": failures,
    }


def apply_state_projection_transaction(
    project_root: Path,
    targets: Mapping[str, bytes],
) -> dict[str, Any]:
    root = project_root.resolve()
    if not targets or set(targets) - ALLOWED_TARGET_REFS:
        raise ValueError("state projection transaction target set is invalid")
    inspection = inspect_state_projection_transaction(root)
    if inspection["decision"] != "PASS":
        raise ValueError("unresolved state projection transaction requires recovery")
    planned: list[dict[str, Any]] = []
    for ref in sorted(targets):
        path = _resolve_runtime_ref(root, ref)
        before = _read_target(path)
        after = bytes(targets[ref])
        if before != after:
            planned.append(_target_record(ref, before, after))
    if not planned:
        return {"decision": "NO_CHANGE", "mutation_count": 0, "applied_refs": []}
    plan_identity = [
        {"ref": item["ref"], "before": item["before_digest"], "after": item["after_digest"]}
        for item in planned
    ]
    transaction_id = _canonical_digest(plan_identity)[:32]
    _ensure_runtime_root(root)
    manifest_path = root / MANIFEST_REL
    lock_path = root / LOCK_REL
    _acquire_lock(lock_path, transaction_id)
    created_at = _now()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": "StateProjectionTransactionV1",
        "transaction_id": transaction_id,
        "state": "PREPARED",
        "created_at": created_at,
        "updated_at": created_at,
        "attempted_refs": [],
        "applied_refs": [],
        "targets": planned,
    }
    try:
        _write_manifest(manifest_path, payload)
        payload["state"] = "APPLYING"
        payload["updated_at"] = _now()
        _write_manifest(manifest_path, payload)
        for raw in planned:
            ref, _before, after = _decode_target(raw)
            payload["attempted_refs"].append(ref)
            payload["updated_at"] = _now()
            _write_manifest(manifest_path, payload)
            _replace_bytes(_resolve_runtime_ref(root, ref), after)
            payload["applied_refs"].append(ref)
            payload["updated_at"] = _now()
            _write_manifest(manifest_path, payload)
        payload["state"] = "COMMITTED"
        payload["updated_at"] = _now()
        _write_manifest(manifest_path, payload)
        return {
            "decision": "PASS",
            "transaction_id": transaction_id,
            "mutation_count": len(planned),
            "applied_refs": list(payload["applied_refs"]),
        }
    except Exception as exc:
        payload["failure"] = f"{type(exc).__name__}:{exc}"
        failures = _restore_targets(root, payload)
        payload["state"] = "PARTIAL" if failures else "RECOVERED"
        payload["updated_at"] = _now()
        if failures:
            payload["recovery_failures"] = failures
        _write_manifest(manifest_path, payload)
        if failures:
            raise RuntimeError("state projection transaction entered PARTIAL") from exc
        raise
    finally:
        _release_lock(lock_path, transaction_id)


def replace_state_history_projection(project_root: Path, value: bytes) -> Path:
    """原子刷新固定的单文件 HISTORY 投影，不扩大三对象事务 target 集。"""

    path = _resolve_runtime_ref(project_root.resolve(), "process/state/HISTORY.md")
    _replace_bytes(path, value)
    return path


def write_state_slim_archive(
    project_root: Path,
    *,
    timestamp: str,
    archive_bytes: bytes,
    report_bytes: bytes,
) -> Path:
    """在固定 archive root 下 create-only 写入一组 state slim 证据。"""

    if not re.fullmatch(r"\d{8}-\d{6}Z\d{4}", timestamp):
        raise ValueError("state slim archive timestamp is invalid")
    archive_root = _resolve_runtime_ref(
        project_root.resolve(),
        "process/archive/state",
    )
    archive_dir = archive_root / timestamp
    _ensure_plain_directory(archive_dir, require_new=True)
    _replace_bytes(archive_dir / "archived-fields.json", archive_bytes)
    _replace_bytes(archive_dir / "slim-report.json", report_bytes)
    return archive_dir


__all__ = [
    "ALLOWED_TARGET_REFS",
    "apply_state_projection_transaction",
    "inspect_state_projection_transaction",
    "replace_state_history_projection",
    "recover_state_projection_transaction",
    "write_state_slim_archive",
]
