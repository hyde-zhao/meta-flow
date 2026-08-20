"""STATE、CURRENT 与人类摘要的可恢复文件集事务。"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, TextIO

try:  # pragma: no cover - Windows 分支由平台安装验证覆盖
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

try:  # pragma: no cover - POSIX 分支由常规测试覆盖
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None  # type: ignore[assignment]

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
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTHORIZATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LINEAGE_ENTRY_FIELDS = {
    "anchor_close_authorization_id",
    "anchor_close_digest",
    "current_digest",
}


@dataclass
class TransactionLockHandle:
    """持有平台级 advisory lock 的 writer capability。"""

    path: Path
    transaction_id: str
    stream: TextIO


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
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.state-projection.tmp")
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


def _platform_lock(stream: TextIO) -> None:
    if fcntl is not None:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if msvcrt is not None:  # pragma: no cover - Windows only
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            os.write(stream.fileno(), b"\0")
            os.fsync(stream.fileno())
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        return
    raise RuntimeError("no supported advisory file-lock implementation is available")


def _platform_unlock(stream: TextIO) -> None:
    if fcntl is not None:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return
    if msvcrt is not None:  # pragma: no cover - Windows only
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def _lock_identity(stream: TextIO) -> str:
    stream.flush()
    stream.seek(0)
    return stream.read()


def _validate_lock_handle(
    handle: TransactionLockHandle,
    *,
    expected_path: Path | None = None,
) -> None:
    path = handle.path
    if expected_path is not None and path.absolute() != expected_path.absolute():
        raise ValueError("state projection writer lock path differs from the expected lock")
    if handle.stream.closed:
        raise ValueError("state projection writer lock capability is closed")
    if path.is_symlink() or not path.is_file():
        raise ValueError("state projection writer lock ownership is unsafe")
    try:
        path_stat = path.stat()
        handle_stat = os.fstat(handle.stream.fileno())
    except OSError as exc:
        raise ValueError("state projection writer lock ownership is unsafe") from exc
    if (path_stat.st_dev, path_stat.st_ino) != (handle_stat.st_dev, handle_stat.st_ino):
        raise ValueError("state projection writer lock file identity drifted")
    if _lock_identity(handle.stream) != handle.transaction_id + "\n":
        raise ValueError("state projection writer lock identity drifted")


def _acquire_lock(lock_path: Path, transaction_id: str) -> TransactionLockHandle:
    if lock_path.is_symlink() or lock_path.exists():
        raise ValueError("state projection writer lock is already held or unsafe")
    stream: TextIO | None = None
    try:
        stream = lock_path.open("x+", encoding="utf-8")
        _platform_lock(stream)
        stream.write(transaction_id + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ValueError("state projection writer lock is already held") from exc
    except Exception:
        if stream is not None:
            stream.close()
        if lock_path.is_file() and not lock_path.is_symlink():
            lock_path.unlink()
        raise
    return TransactionLockHandle(lock_path, transaction_id, stream)


def _claim_lock(
    lock_path: Path,
    transaction_id: str,
    *,
    create_if_missing: bool,
) -> TransactionLockHandle | None:
    """接管崩溃遗留锁；仍被活进程持有或身份不符时 fail closed。"""

    if lock_path.is_symlink() or (lock_path.exists() and not lock_path.is_file()):
        raise ValueError("state projection writer lock is unsafe")
    if not lock_path.exists():
        return _acquire_lock(lock_path, transaction_id) if create_if_missing else None
    stream: TextIO | None = None
    try:
        stream = lock_path.open("r+", encoding="utf-8")
        _platform_lock(stream)
        handle = TransactionLockHandle(lock_path, transaction_id, stream)
        _validate_lock_handle(handle)
        return handle
    except (BlockingIOError, OSError) as exc:
        if stream is not None:
            stream.close()
        raise ValueError("state projection writer lock is held by an active writer") from exc
    except Exception:
        if stream is not None:
            try:
                _platform_unlock(stream)
            finally:
                stream.close()
        raise


def transaction_lock_identity(lock_path: Path) -> str | None:
    if lock_path.is_symlink() or (lock_path.exists() and not lock_path.is_file()):
        raise ValueError("state projection writer lock is unsafe")
    if not lock_path.exists():
        return None
    identity = lock_path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", identity):
        raise ValueError("state projection writer lock identity is invalid")
    return identity


def _release_lock(handle: TransactionLockHandle) -> None:
    failure: Exception | None = None
    try:
        _validate_lock_handle(handle)
        handle.path.unlink()
    except Exception as exc:  # 锁身份漂移时保留现场，但仍释放本进程的 advisory lock。
        failure = exc
    finally:
        try:
            _platform_unlock(handle.stream)
        finally:
            handle.stream.close()
    if failure is not None:
        raise failure


def state_projection_lock_path(project_root: Path) -> Path:
    _ensure_runtime_root(project_root.resolve())
    return project_root.resolve() / LOCK_REL


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
        "before_bytes_b64": None if before is None else base64.b64encode(before).decode("ascii"),
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
    if set(payload) - (
        expected | {"failure", "recovery_failures", "lineage", "correction"}
    ) or not expected.issubset(payload):
        raise ValueError("state projection transaction manifest fields mismatch")
    has_correction = "correction" in payload
    if has_correction:
        _decode_correction(payload["correction"])
    manifest_identity = (payload["schema_version"], payload["kind"])
    allowed_identities = (
        {
            (1, "StateProjectionTransactionV1"),
            (2, "StateProjectionTransactionV2"),
        }
        if has_correction
        else {(1, "StateProjectionTransactionV1")}
    )
    if manifest_identity not in allowed_identities:
        raise ValueError("state projection transaction manifest kind/version mismatch")
    if not re.fullmatch(r"[0-9a-f]{32}", str(payload["transaction_id"])):
        raise ValueError("state projection transaction id is invalid")
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
    lineage = _decode_lineage(payload.get("lineage", {}))
    if payload["state"] in TERMINAL_STATES:
        expected_field = "after_digest" if payload["state"] == "COMMITTED" else "before_digest"
        for raw in targets:
            ref = str(raw["ref"])
            entry = lineage.get(ref)
            expected_digest = str(raw[expected_field])
            if (
                entry is not None
                and expected_digest != "missing"
                and entry["current_digest"] != expected_digest
            ):
                raise ValueError("state projection transaction lineage generation mismatch")
    return path, payload


def _decode_lineage(raw_lineage: object) -> dict[str, dict[str, str]]:
    """校验 State writer 对最新 Work-close generation 的继承声明。"""

    if not isinstance(raw_lineage, Mapping):
        raise ValueError("state projection transaction lineage must be an object")
    lineage: dict[str, dict[str, str]] = {}
    for raw_ref, raw_entry in raw_lineage.items():
        ref = str(raw_ref)
        if ref not in ALLOWED_TARGET_REFS or not isinstance(raw_entry, Mapping):
            raise ValueError("state projection transaction lineage target is invalid")
        if set(raw_entry) != _LINEAGE_ENTRY_FIELDS:
            raise ValueError("state projection transaction lineage fields mismatch")
        authorization_id = str(raw_entry.get("anchor_close_authorization_id") or "")
        anchor_digest = str(raw_entry.get("anchor_close_digest") or "")
        current_digest = str(raw_entry.get("current_digest") or "")
        if (
            not _AUTHORIZATION_ID_RE.fullmatch(authorization_id)
            or not _DIGEST_RE.fullmatch(anchor_digest)
            or not _DIGEST_RE.fullmatch(current_digest)
        ):
            raise ValueError("state projection transaction lineage identity is invalid")
        lineage[ref] = {
            "anchor_close_authorization_id": authorization_id,
            "anchor_close_digest": anchor_digest,
            "current_digest": current_digest,
        }
    return lineage


def _work_close_generation_heads(project_root: Path) -> dict[str, dict[str, str]]:
    """读取当前 binding 项目的最新 Work-close generation；独立 fixture 返回空集。"""

    from meta_flow.project.process_route import require_process_route
    from meta_flow.semantics.generation_lineage import committed_generation_heads

    root = project_root.resolve()
    try:
        route = require_process_route(root)
    except (OSError, ValueError):
        if (root / ".meta-flow/workspace.yaml").exists():
            raise
        return {}
    refs = tuple(ref.removeprefix("process/") for ref in sorted(ALLOWED_TARGET_REFS))
    return committed_generation_heads(
        route.process_root / ".meta-flow-runtime/work-close/transactions",
        refs=refs,
        current_digests={
            ref.removeprefix("process/"): _digest(_read_target(_resolve_runtime_ref(root, ref)))
            for ref in ALLOWED_TARGET_REFS
        },
    )


def _build_lineage(
    project_root: Path,
    planned: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    """把直接或既有的 Work-close 锚点传播到本次 State post-image。"""

    root = project_root.resolve()
    _manifest_path, previous = _load_manifest(root)
    close_heads = _work_close_generation_heads(root)
    current_by_ref = {
        ref: _digest(_read_target(_resolve_runtime_ref(root, ref))) for ref in ALLOWED_TARGET_REFS
    }
    previous_lineage = _effective_lineage(
        previous,
        close_heads=close_heads,
        current_by_ref=current_by_ref,
    )
    planned_after = {
        ref: _digest(after) for ref, _before, after in (_decode_target(raw) for raw in planned)
    }
    lineage: dict[str, dict[str, str]] = {}
    for ref in sorted(ALLOWED_TARGET_REFS):
        close_ref = ref.removeprefix("process/")
        head = close_heads.get(close_ref)
        if head is None:
            continue
        before_digest = current_by_ref[ref]
        anchor_id = str(head["authorization_id"])
        anchor_digest = str(head["after_digest"])
        previous_entry = previous_lineage.get(ref)
        if before_digest == anchor_digest:
            pass
        elif (
            previous_entry is not None
            and previous_entry["anchor_close_authorization_id"] == anchor_id
            and previous_entry["anchor_close_digest"] == anchor_digest
            and previous_entry["current_digest"] == before_digest
        ):
            pass
        else:
            raise ValueError(f"state projection has no authorized Work-close predecessor: {ref}")
        lineage[ref] = {
            "anchor_close_authorization_id": anchor_id,
            "anchor_close_digest": anchor_digest,
            "current_digest": planned_after.get(ref, before_digest),
        }
    return lineage


def _effective_lineage(
    payload: Mapping[str, Any] | None,
    *,
    close_heads: Mapping[str, Mapping[str, str]],
    current_by_ref: Mapping[str, str],
) -> dict[str, dict[str, str]]:
    """读取显式 lineage，并对升级前的单槽 State manifest 做有界兼容。

    旧 manifest 没有 ``lineage`` 字段，但其 COMMITTED after digest 与当前 bytes
    一致时，仍可证明当前 generation 由最后一次 native State transaction 写入。
    该兼容只用于把旧 generation 迁移到首次显式锚定；一旦字段存在，即使为空，
    也不会回退到兼容推断。
    """

    if payload is None:
        return {}
    explicit = _decode_lineage(payload.get("lineage", {}))
    if "lineage" in payload or payload.get("state") != "COMMITTED":
        return explicit
    inferred = dict(explicit)
    for raw in payload.get("targets", []):
        if not isinstance(raw, Mapping):
            continue
        ref = str(raw.get("ref") or "")
        close_ref = ref.removeprefix("process/")
        head = close_heads.get(close_ref)
        after_digest = str(raw.get("after_digest") or "")
        if (
            head is not None
            and after_digest != "missing"
            and current_by_ref.get(ref) == after_digest
        ):
            inferred[ref] = {
                "anchor_close_authorization_id": str(head["authorization_id"]),
                "anchor_close_digest": str(head["after_digest"]),
                "current_digest": after_digest,
            }
    return inferred


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


def _rewind_lineage_to_preimage(payload: dict[str, Any]) -> None:
    """成功回滚后令 lineage 与恢复到的 before generation 一致。"""

    lineage = _decode_lineage(payload.get("lineage", {}))
    for raw in payload["targets"]:
        ref = str(raw["ref"])
        before_digest = str(raw["before_digest"])
        if ref in lineage and before_digest != "missing":
            lineage[ref]["current_digest"] = before_digest
    payload["lineage"] = lineage


def inspect_state_projection_transaction(
    project_root: Path,
    *,
    _ignore_lock: bool = False,
    _lock_handle: TransactionLockHandle | None = None,
) -> dict[str, Any]:
    if _ignore_lock and _lock_handle is not None:
        return {
            "decision": "BLOCKED",
            "state": "INVALID",
            "classification": "CORRUPTED",
            "findings": ["state projection lock bypass inputs are mutually exclusive"],
        }
    try:
        _path, payload = _load_manifest(project_root)
    except (OSError, ValueError) as exc:
        return {
            "decision": "BLOCKED",
            "state": "INVALID",
            "classification": "CORRUPTED",
            "findings": [str(exc)],
        }
    findings: list[str] = []
    if _lock_handle is not None:
        try:
            expected_path = project_root.resolve() / LOCK_REL
            _validate_lock_handle(_lock_handle, expected_path=expected_path)
            if transaction_lock_identity(expected_path) != _lock_handle.transaction_id:
                findings.append("STATE_PROJECTION_LOCK_IDENTITY_DRIFT")
        except (OSError, ValueError) as exc:
            findings.append(f"STATE_PROJECTION_LOCK_CAPABILITY_INVALID:{exc}")
    elif not _ignore_lock:
        try:
            if transaction_lock_identity(project_root.resolve() / LOCK_REL) is not None:
                findings.append("STATE_PROJECTION_LOCK_PRESENT")
        except (OSError, ValueError) as exc:
            findings.append(f"STATE_PROJECTION_LOCK_UNSAFE:{exc}")
    if payload is None:
        return {
            "decision": "BLOCKED" if findings else "PASS",
            "state": "NONE",
            "classification": "COMMITTED_CURRENT" if not findings else "CORRUPTED",
            "findings": findings,
        }
    expected_after = payload["state"] == "COMMITTED"
    work_close_heads: dict[str, dict[str, str]] = {}
    if payload["state"] in TERMINAL_STATES:
        try:
            work_close_heads = _work_close_generation_heads(project_root)
        except (OSError, ValueError):
            # 无 vNext binding 的独立单元 fixture 没有跨 writer lineage。
            work_close_heads = {}
    current_by_ref = {
        ref: _digest(_read_target(_resolve_runtime_ref(project_root, ref)))
        for ref in ALLOWED_TARGET_REFS
    }
    lineage = _effective_lineage(
        payload,
        close_heads=work_close_heads,
        current_by_ref=current_by_ref,
    )
    superseded_refs: set[str] = set()
    for ref in sorted(ALLOWED_TARGET_REFS):
        close_ref = ref.removeprefix("process/")
        head = work_close_heads.get(close_ref)
        if head is None:
            continue
        current_digest = current_by_ref[ref]
        entry = lineage.get(ref)
        direct_close_generation = current_digest == head["after_digest"]
        authorized_state_successor = bool(
            entry
            and entry["anchor_close_authorization_id"] == head["authorization_id"]
            and entry["anchor_close_digest"] == head["after_digest"]
            and entry["current_digest"] == current_digest
        )
        if not direct_close_generation and not authorized_state_successor:
            findings.append(f"STATE_PROJECTION_LINEAGE_UNBOUND:{ref}")
    for raw in payload["targets"]:
        ref, before, after = _decode_target(raw)
        current = _read_target(_resolve_runtime_ref(project_root, ref))
        expected = after if expected_after else before
        current_digest = _digest(current)
        work_close_ref = ref.removeprefix("process/")
        work_close_head = work_close_heads.get(work_close_ref)
        superseded_by_work_close = bool(
            work_close_head and work_close_head["after_digest"] == current_digest
        )
        if superseded_by_work_close and current_digest != _digest(expected):
            superseded_refs.add(ref)
        state_successor = bool(
            lineage.get(ref) and lineage[ref]["current_digest"] == current_digest
        )
        if (
            payload["state"] in TERMINAL_STATES
            and current_digest != _digest(expected)
            and not superseded_by_work_close
            and not state_successor
        ):
            findings.append(f"TERMINAL_GENERATION_DRIFT:{ref}")
    if payload["state"] not in TERMINAL_STATES:
        findings.append(f"UNRESOLVED_STATE_PROJECTION_TRANSACTION:{payload['state']}")
    repair_findings = [
        finding
        for finding in findings
        if finding.startswith(("TERMINAL_GENERATION_DRIFT:", "STATE_PROJECTION_LINEAGE_UNBOUND:"))
    ]
    if payload["state"] not in TERMINAL_STATES:
        classification = "PARTIAL"
    elif payload["state"] == "RECOVERED" or superseded_refs:
        classification = "SUPERSEDED"
    elif findings and len(repair_findings) == len(findings):
        classification = "COMMITTED_STALE_REPAIRABLE"
    elif findings:
        classification = "CORRUPTED"
    else:
        classification = "COMMITTED_CURRENT"
    return {
        "decision": "BLOCKED" if findings else "PASS",
        "state": payload["state"],
        "classification": classification,
        "transaction_id": payload["transaction_id"],
        "findings": findings,
    }


def state_projection_successor_head_digests(
    project_root: Path,
    *,
    close_heads: Mapping[str, Mapping[str, str]],
    _ignore_lock: bool = False,
) -> dict[str, str]:
    """返回由指定 Work-close head 合法派生出的当前 State generation。"""

    inspection = inspect_state_projection_transaction(
        project_root,
        _ignore_lock=_ignore_lock,
    )
    if inspection["decision"] != "PASS":
        return {}
    _path, payload = _load_manifest(project_root)
    if payload is None or payload["state"] != "COMMITTED":
        return {}
    lineage = _decode_lineage(payload.get("lineage", {}))
    result: dict[str, str] = {}
    for close_ref, head in close_heads.items():
        ref = "process/" + close_ref
        entry = lineage.get(ref)
        if (
            entry is not None
            and entry["anchor_close_authorization_id"] == str(head.get("authorization_id") or "")
            and entry["anchor_close_digest"] == str(head.get("after_digest") or "")
        ):
            result[close_ref] = entry["current_digest"]
    return result


def recover_state_projection_transaction(
    project_root: Path,
    *,
    lock_handle: TransactionLockHandle | None = None,
) -> dict[str, Any]:
    root = project_root.resolve()
    manifest_path, payload = _load_manifest(root)
    if payload is None:
        lock_path = root / LOCK_REL
        try:
            identity = transaction_lock_identity(lock_path)
            if identity is not None:
                handle = _claim_lock(lock_path, identity, create_if_missing=False)
                assert handle is not None
                try:
                    _manifest_path, current_payload = _load_manifest(root)
                    if current_payload is not None:
                        raise ValueError(
                            "state projection transaction appeared while recovering orphan lock"
                        )
                    return {
                        "decision": "NO_CHANGE",
                        "state": "NONE",
                        "recovered_refs": [],
                        "lock_recovered": True,
                        "findings": [],
                    }
                finally:
                    _release_lock(handle)
        except (OSError, ValueError) as exc:
            return {
                "decision": "BLOCKED",
                "state": "NONE",
                "recovered_refs": [],
                "findings": [str(exc)],
            }
        return {"decision": "NO_CHANGE", "state": "NONE", "recovered_refs": []}
    owned_lock = False
    handle = lock_handle
    lock_path = state_projection_lock_path(root)
    try:
        if handle is None:
            lock_identity = transaction_lock_identity(lock_path)
            expected_lock_identity = (
                str(payload["transaction_id"])
                if payload["state"] not in TERMINAL_STATES or lock_identity is None
                else lock_identity
            )
            handle = _claim_lock(
                lock_path,
                expected_lock_identity,
                create_if_missing=payload["state"] not in TERMINAL_STATES,
            )
            owned_lock = handle is not None
        else:
            _validate_lock_handle(handle, expected_path=lock_path)
        # 获取锁后重新读取 journal，防止 inspect/recover 间发生并发替换。
        _current_manifest_path, current_payload = _load_manifest(root)
        if (
            current_payload is None
            or current_payload["transaction_id"] != payload["transaction_id"]
        ):
            raise ValueError("state projection transaction changed while acquiring recovery lock")
        payload = current_payload
        if payload["state"] in TERMINAL_STATES:
            inspection = inspect_state_projection_transaction(root, _ignore_lock=True)
            return {
                "decision": "NO_CHANGE" if inspection["decision"] == "PASS" else "BLOCKED",
                "state": payload["state"],
                "recovered_refs": [],
                "lock_recovered": owned_lock,
                "findings": inspection["findings"],
            }
        failures = _restore_targets(root, payload)
        payload["state"] = "PARTIAL" if failures else "RECOVERED"
        if not failures:
            _rewind_lineage_to_preimage(payload)
        payload["updated_at"] = _now()
        if failures:
            payload["recovery_failures"] = failures
        _write_manifest(manifest_path, payload)
        return {
            "decision": "PARTIAL" if failures else "RECOVERED",
            "state": payload["state"],
            "recovered_refs": list(reversed(payload["attempted_refs"])) if not failures else [],
            "lock_recovered": owned_lock,
            "findings": failures,
        }
    finally:
        if owned_lock and handle is not None:
            _release_lock(handle)


CORRECTION_AUTHORIZATION_KIND = "state-projection-correct-authorization-v1"
CORRECTION_AUTHORIZATION_V2_KIND = "state-projection-correct-authorization-v2"
CORRECTION_FIELDS = {
    "corrected_transaction_id",
    "authorization_id",
    "old_manifest_digest",
    "corrected_at",
}
CORRECTION_V2_FIELDS = CORRECTION_FIELDS | {
    "authorization_schema_version",
    "writer_provenance",
}
CORRECTION_ROOT_REL = TRANSACTION_ROOT_REL / "corrections"


def _decode_writer_provenance(raw: object) -> dict[str, Any]:
    """校验 correction 当前 bytes 的来源解释；unknown 必须显式声明原因。"""

    expected = {
        "mode",
        "writer_id",
        "evidence_ref",
        "evidence_digest",
        "reason",
    }
    if not isinstance(raw, Mapping) or set(raw) != expected:
        raise ValueError("state projection correction writer provenance fields mismatch")
    mode = raw.get("mode")
    writer_id = raw.get("writer_id")
    evidence_ref = raw.get("evidence_ref")
    evidence_digest = raw.get("evidence_digest")
    reason = raw.get("reason")
    if mode == "source-writer-evidence":
        if (
            not isinstance(writer_id, str)
            or not _AUTHORIZATION_ID_RE.fullmatch(writer_id)
            or not isinstance(evidence_ref, str)
            or not evidence_ref
            or evidence_ref.startswith(("/", "./"))
            or "\\" in evidence_ref
            or ".." in Path(evidence_ref).parts
            or not isinstance(evidence_digest, str)
            or not _DIGEST_RE.fullmatch(evidence_digest)
            or reason is not None
        ):
            raise ValueError("state projection correction source writer evidence is invalid")
    elif mode == "unknown-writer":
        if (
            writer_id is not None
            or evidence_ref is not None
            or evidence_digest is not None
            or not isinstance(reason, str)
            or len(reason.strip()) < 8
        ):
            raise ValueError("state projection correction unknown writer declaration is invalid")
    else:
        raise ValueError("state projection correction writer provenance mode is invalid")
    return {
        "mode": str(mode),
        "writer_id": writer_id,
        "evidence_ref": evidence_ref,
        "evidence_digest": evidence_digest,
        "reason": reason,
    }


def _decode_correction(raw: object) -> dict[str, Any]:
    """校验 drifted-terminal correction 的溯源对象；不改动三个投影文件本身。"""

    if not isinstance(raw, Mapping):
        raise ValueError("state projection correction fields mismatch")
    raw_fields = frozenset(raw)
    if raw_fields not in {
        frozenset(CORRECTION_FIELDS),
        frozenset(CORRECTION_V2_FIELDS),
    }:
        raise ValueError("state projection correction fields mismatch")
    corrected_transaction_id = str(raw.get("corrected_transaction_id") or "")
    authorization_id = str(raw.get("authorization_id") or "")
    old_manifest_digest = str(raw.get("old_manifest_digest") or "")
    if (
        not re.fullmatch(r"[0-9a-f]{32}", corrected_transaction_id)
        or not _AUTHORIZATION_ID_RE.fullmatch(authorization_id)
        or not _DIGEST_RE.fullmatch(old_manifest_digest)
        or not isinstance(raw.get("corrected_at"), str)
    ):
        raise ValueError("state projection correction identity is invalid")
    decoded: dict[str, Any] = {
        "corrected_transaction_id": corrected_transaction_id,
        "authorization_id": authorization_id,
        "old_manifest_digest": old_manifest_digest,
        "corrected_at": str(raw["corrected_at"]),
    }
    if raw_fields == frozenset(CORRECTION_V2_FIELDS):
        if raw.get("authorization_schema_version") != 2:
            raise ValueError("state projection correction authorization version is invalid")
        decoded["authorization_schema_version"] = 2
        decoded["writer_provenance"] = _decode_writer_provenance(raw.get("writer_provenance"))
    return decoded


@dataclass(frozen=True, slots=True)
class ProjectionCorrectAuthorizationV1:
    """typed authorization：绑定被矫正事务、drift refs、preimage 与旧 manifest bytes。"""

    schema_version: int
    kind: str
    authorization_id: str
    corrected_transaction_id: str
    drift_refs: tuple[str, ...]
    preimage_digests: dict[str, str]
    old_manifest_digest: str
    expires_at: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ProjectionCorrectAuthorizationV1:
        expected = {
            "schema_version",
            "kind",
            "authorization_id",
            "corrected_transaction_id",
            "drift_refs",
            "preimage_digests",
            "old_manifest_digest",
            "expires_at",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("state projection correction authorization fields mismatch")
        refs = payload["drift_refs"]
        preimages = payload["preimage_digests"]
        if (
            payload["schema_version"] != 1
            or payload["kind"] != CORRECTION_AUTHORIZATION_KIND
            or not _AUTHORIZATION_ID_RE.fullmatch(str(payload["authorization_id"]))
            or not re.fullmatch(r"[0-9a-f]{32}", str(payload["corrected_transaction_id"]))
            or not _DIGEST_RE.fullmatch(str(payload["old_manifest_digest"]))
            or not isinstance(refs, list)
            or not all(ref in ALLOWED_TARGET_REFS for ref in refs)
            or refs != sorted(set(refs))
            or not isinstance(preimages, dict)
            or set(preimages) != set(refs)
            or not all(_DIGEST_RE.fullmatch(str(v)) for v in preimages.values())
        ):
            raise ValueError("state projection correction authorization is invalid")
        try:
            expiry = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                "state projection correction authorization expires_at is invalid"
            ) from exc
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("state projection correction authorization is expired")
        return cls(
            schema_version=1,
            kind=CORRECTION_AUTHORIZATION_KIND,
            authorization_id=str(payload["authorization_id"]),
            corrected_transaction_id=str(payload["corrected_transaction_id"]),
            drift_refs=tuple(str(ref) for ref in refs),
            preimage_digests={str(k): str(v) for k, v in preimages.items()},
            old_manifest_digest=str(payload["old_manifest_digest"]),
            expires_at=str(payload["expires_at"]),
        )


@dataclass(frozen=True, slots=True)
class ProjectionCorrectAuthorizationV2:
    """当前 correction apply 合同；在 V1 bindings 上增加 writer 来源解释。"""

    schema_version: int
    kind: str
    authorization_id: str
    corrected_transaction_id: str
    drift_refs: tuple[str, ...]
    preimage_digests: dict[str, str]
    old_manifest_digest: str
    expires_at: str
    writer_provenance: dict[str, Any]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ProjectionCorrectAuthorizationV2:
        expected = {
            "schema_version",
            "kind",
            "authorization_id",
            "corrected_transaction_id",
            "drift_refs",
            "preimage_digests",
            "old_manifest_digest",
            "expires_at",
            "writer_provenance",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("state projection correction authorization fields mismatch")
        refs = payload["drift_refs"]
        preimages = payload["preimage_digests"]
        if (
            payload["schema_version"] != 2
            or payload["kind"] != CORRECTION_AUTHORIZATION_V2_KIND
            or not _AUTHORIZATION_ID_RE.fullmatch(str(payload["authorization_id"]))
            or not re.fullmatch(r"[0-9a-f]{32}", str(payload["corrected_transaction_id"]))
            or not _DIGEST_RE.fullmatch(str(payload["old_manifest_digest"]))
            or not isinstance(refs, list)
            or not all(ref in ALLOWED_TARGET_REFS for ref in refs)
            or refs != sorted(set(refs))
            or not isinstance(preimages, dict)
            or set(preimages) != set(refs)
            or not all(_DIGEST_RE.fullmatch(str(value)) for value in preimages.values())
        ):
            raise ValueError("state projection correction authorization is invalid")
        try:
            expiry = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                "state projection correction authorization expires_at is invalid"
            ) from exc
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("state projection correction authorization is expired")
        return cls(
            schema_version=2,
            kind=CORRECTION_AUTHORIZATION_V2_KIND,
            authorization_id=str(payload["authorization_id"]),
            corrected_transaction_id=str(payload["corrected_transaction_id"]),
            drift_refs=tuple(str(ref) for ref in refs),
            preimage_digests={str(key): str(value) for key, value in preimages.items()},
            old_manifest_digest=str(payload["old_manifest_digest"]),
            expires_at=str(payload["expires_at"]),
            writer_provenance=_decode_writer_provenance(payload["writer_provenance"]),
        )


def plan_state_projection_correction(
    project_root: Path, *, ignore_lock: bool = False
) -> dict[str, Any]:
    """zero-write 输出 drifted-terminal 矫正计划与授权绑定材料。"""

    root = project_root.resolve()
    manifest_path, payload = _load_manifest(root)
    if payload is None:
        return {
            "decision": "BLOCKED",
            "kind": "StateProjectionCorrectionPlanV1",
            "blockers": ["no committed state projection transaction to correct"],
            "schema_version": 1,
        }
    inspection = inspect_state_projection_transaction(root, _ignore_lock=ignore_lock)
    drift_refs = sorted(
        finding.split(":", 1)[1]
        for finding in inspection["findings"]
        if finding.startswith("TERMINAL_GENERATION_DRIFT:")
    )
    drift_ref_set = set(drift_refs)
    blockers = [
        finding
        for finding in inspection["findings"]
        if not finding.startswith("TERMINAL_GENERATION_DRIFT:")
        and not (
            finding.startswith("STATE_PROJECTION_LINEAGE_UNBOUND:")
            and finding.split(":", 1)[1] in drift_ref_set
        )
    ]
    if payload["state"] != "COMMITTED":
        blockers.append(f"correction supports COMMITTED drift only: {payload['state']}")
    preimage_digests = {
        ref: _digest(_read_target(_resolve_runtime_ref(root, ref)))
        for ref in ALLOWED_TARGET_REFS
        if ref in drift_refs
    }
    return {
        "decision": "READY" if drift_refs and not blockers else "BLOCKED",
        "kind": "StateProjectionCorrectionPlanV1",
        "blockers": blockers
        or (["no terminal generation drift to correct"] if not drift_refs else []),
        "transaction_id": payload["transaction_id"],
        "drift_refs": drift_refs,
        "preimage_digests": preimage_digests,
        "old_manifest_digest": _digest(manifest_path.read_bytes()),
        "schema_version": 1,
    }


def correct_state_projection_transaction(
    project_root: Path,
    authorization: ProjectionCorrectAuthorizationV2,
) -> dict[str, Any]:
    """以 typed authorization 将 drifted-terminal 事务重锚到当前 bytes。

    只重写 runtime manifest（记录 correction 溯源），不触碰三个投影文件，
    不删除旧审计信息（旧 manifest bytes 由 receipt 与 correction 溯源保留 digest）。
    """

    if not isinstance(authorization, ProjectionCorrectAuthorizationV2):
        raise ValueError("state projection correction apply requires V2 authorization")
    root = project_root.resolve()
    receipt_dir = root / CORRECTION_ROOT_REL
    if receipt_dir.is_symlink() or (receipt_dir.exists() and not receipt_dir.is_dir()):
        raise ValueError("state projection correction receipt directory is unsafe")
    receipt_path = receipt_dir / f"{authorization.authorization_id}.json"
    if receipt_path.is_symlink() or receipt_path.exists():
        raise ValueError("state projection correction authorization_id was already consumed")
    plan = plan_state_projection_correction(root)
    if plan["decision"] != "READY":
        raise ValueError("state projection correction plan is not READY")
    if plan["transaction_id"] != authorization.corrected_transaction_id:
        raise ValueError("state projection correction does not bind the current transaction")
    if plan["drift_refs"] != list(authorization.drift_refs):
        raise ValueError("state projection correction drift refs mismatch")
    if plan["old_manifest_digest"] != authorization.old_manifest_digest:
        raise ValueError("state projection correction old manifest digest mismatch")
    for ref, expected_digest in authorization.preimage_digests.items():
        current = _digest(_read_target(_resolve_runtime_ref(root, ref)))
        if current != expected_digest:
            raise ValueError(f"state projection correction preimage drifted: {ref}")

    _manifest_path, old_payload = _load_manifest(root)
    assert _manifest_path is not None and old_payload is not None
    old_expected_after = {
        ref: after
        for ref, _before, after in (_decode_target(raw) for raw in old_payload["targets"])
    }
    planned: list[dict[str, Any]] = []
    for ref in sorted(ALLOWED_TARGET_REFS):
        before = old_expected_after.get(ref)
        after = _read_target(_resolve_runtime_ref(root, ref))
        planned.append(_target_record(ref, before, after))
    transaction_id = _canonical_digest(
        {
            "correction_of": old_payload["transaction_id"],
            "authorization_id": authorization.authorization_id,
            "old_manifest_digest": authorization.old_manifest_digest,
            "writer_provenance_digest": _canonical_digest(authorization.writer_provenance),
        }
    )[:32]
    _ensure_runtime_root(root)
    manifest_path = root / MANIFEST_REL
    lock_path = root / LOCK_REL
    handle = _claim_lock(lock_path, transaction_id, create_if_missing=True)
    assert handle is not None
    manifest_replaced = False
    receipt_dir_existed = receipt_dir.exists()
    old_manifest_bytes = manifest_path.read_bytes()
    try:
        locked_plan = plan_state_projection_correction(root, ignore_lock=True)
        if (
            locked_plan["decision"] != "READY"
            or locked_plan["transaction_id"] != authorization.corrected_transaction_id
            or locked_plan["drift_refs"] != list(authorization.drift_refs)
            or locked_plan["preimage_digests"] != authorization.preimage_digests
            or locked_plan["old_manifest_digest"] != authorization.old_manifest_digest
        ):
            raise ValueError("state projection correction target drifted while acquiring lock")
        now = _now()
        payload: dict[str, Any] = {
            "schema_version": 2,
            "kind": "StateProjectionTransactionV2",
            "transaction_id": transaction_id,
            "state": "COMMITTED",
            "created_at": now,
            "updated_at": now,
            "attempted_refs": [item["ref"] for item in planned],
            "applied_refs": [item["ref"] for item in planned],
            "targets": planned,
            "correction": {
                "corrected_transaction_id": old_payload["transaction_id"],
                "authorization_id": authorization.authorization_id,
                "old_manifest_digest": authorization.old_manifest_digest,
                "corrected_at": now,
                "authorization_schema_version": 2,
                "writer_provenance": authorization.writer_provenance,
            },
        }
        _load_manifest_from_payload(payload)
        _write_manifest(manifest_path, payload)
        manifest_replaced = True
        inspection = inspect_state_projection_transaction(root, _ignore_lock=True)
        if inspection["decision"] != "PASS":
            raise ValueError("state projection correction did not converge inspection")
        receipt = {
            "schema_version": 2,
            "kind": "StateProjectionCorrectionReceiptV2",
            "decision": "PASS",
            "authorization_id": authorization.authorization_id,
            "corrected_transaction_id": old_payload["transaction_id"],
            "new_transaction_id": transaction_id,
            "drift_refs": list(authorization.drift_refs),
            "old_manifest_digest": authorization.old_manifest_digest,
            "new_manifest_digest": _digest(manifest_path.read_bytes()),
            "writer_provenance": authorization.writer_provenance,
            "corrected_at": now,
        }
        receipt_dir.mkdir(parents=True, exist_ok=True)
        _replace_bytes(
            receipt_path,
            (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
        return receipt
    except Exception:
        rollback_failure: Exception | None = None
        if manifest_replaced:
            try:
                _replace_bytes(manifest_path, old_manifest_bytes)
            except Exception as rollback_exc:  # pragma: no cover - 双重 I/O 故障
                rollback_failure = rollback_exc
        if receipt_path.is_file() and not receipt_path.is_symlink():
            try:
                receipt_path.unlink()
            except OSError as rollback_exc:  # pragma: no cover - 双重 I/O 故障
                rollback_failure = rollback_failure or rollback_exc
        if not receipt_dir_existed and receipt_dir.is_dir():
            try:
                receipt_dir.rmdir()
            except OSError:
                pass
        if rollback_failure is not None:
            raise RuntimeError(
                "state projection correction failed and manifest rollback did not complete"
            ) from rollback_failure
        raise
    finally:
        _release_lock(handle)


def _load_manifest_from_payload(payload: Mapping[str, Any]) -> None:
    """写入前自校验：新 manifest 的 target/correction 必须通过严格解码路径。"""

    for raw in payload["targets"]:
        _decode_target(raw)
    _decode_correction(payload["correction"])
    if (
        payload["state"] not in TERMINAL_STATES
        or payload["schema_version"] != 2
        or payload["kind"] != "StateProjectionTransactionV2"
    ):
        raise ValueError("state projection correction manifest kind/state mismatch")
    refs = [item["ref"] for item in payload["targets"]]
    if payload["attempted_refs"] != refs or payload["applied_refs"] != refs:
        raise ValueError("state projection correction manifest accounting mismatch")


def apply_state_projection_transaction(
    project_root: Path,
    targets: Mapping[str, bytes],
    *,
    lock_handle: TransactionLockHandle | None = None,
) -> dict[str, Any]:
    root = project_root.resolve()
    if not targets or set(targets) - ALLOWED_TARGET_REFS:
        raise ValueError("state projection transaction target set is invalid")
    inspection = inspect_state_projection_transaction(
        root,
        _ignore_lock=lock_handle is not None,
    )
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
    lineage = _build_lineage(root, planned)
    plan_identity = [
        {"ref": item["ref"], "before": item["before_digest"], "after": item["after_digest"]}
        for item in planned
    ]
    transaction_id = _canonical_digest({"targets": plan_identity, "lineage": lineage})[:32]
    _ensure_runtime_root(root)
    manifest_path = root / MANIFEST_REL
    lock_path = root / LOCK_REL
    owned_lock = lock_handle is None
    handle = _acquire_lock(lock_path, transaction_id) if owned_lock else lock_handle
    assert handle is not None
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
        "lineage": lineage,
        "targets": planned,
    }
    try:
        _validate_lock_handle(handle, expected_path=lock_path)
        locked_inspection = inspect_state_projection_transaction(root, _ignore_lock=True)
        if locked_inspection["decision"] != "PASS":
            raise ValueError("unresolved state projection transaction requires recovery")
        locked_planned: list[dict[str, Any]] = []
        for ref in sorted(targets):
            before = _read_target(_resolve_runtime_ref(root, ref))
            after = bytes(targets[ref])
            if before != after:
                locked_planned.append(_target_record(ref, before, after))
        locked_identity = [
            {"ref": item["ref"], "before": item["before_digest"], "after": item["after_digest"]}
            for item in locked_planned
        ]
        locked_lineage = _build_lineage(root, locked_planned)
        if (
            _canonical_digest({"targets": locked_identity, "lineage": locked_lineage})[:32]
            != transaction_id
        ):
            raise ValueError("state projection target preimage drifted while acquiring writer lock")
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
        if not failures:
            _rewind_lineage_to_preimage(payload)
        payload["updated_at"] = _now()
        if failures:
            payload["recovery_failures"] = failures
        _write_manifest(manifest_path, payload)
        if failures:
            raise RuntimeError("state projection transaction entered PARTIAL") from exc
        raise
    finally:
        if owned_lock:
            _release_lock(handle)


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


def atomic_replace_bytes(path: Path, value: bytes) -> Path:
    """复用已资格化的单文件原子替换原语；调用方仍负责目标边界与授权。"""

    _replace_bytes(path, value)
    return path


def atomic_remove_regular_file(path: Path) -> Path:
    """删除一个已解析的普通文件，并持久化父目录变更。"""

    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"state projection target is not a regular file: {path}")
    if not path.exists():
        return path
    path.unlink()
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return path


# 公共别名只暴露已通过 writer qualification 的底层原语；调用方仍须维护独立
# transaction journal、target allowlist、preimage 与恢复状态机。
ensure_transaction_directory = _ensure_plain_directory
acquire_transaction_lock = _acquire_lock
claim_transaction_lock = _claim_lock
release_transaction_lock = _release_lock
validate_transaction_lock = _validate_lock_handle


__all__ = [
    "ALLOWED_TARGET_REFS",
    "TransactionLockHandle",
    "acquire_transaction_lock",
    "apply_state_projection_transaction",
    "atomic_remove_regular_file",
    "atomic_replace_bytes",
    "claim_transaction_lock",
    "ensure_transaction_directory",
    "inspect_state_projection_transaction",
    "replace_state_history_projection",
    "recover_state_projection_transaction",
    "release_transaction_lock",
    "state_projection_lock_path",
    "state_projection_successor_head_digests",
    "transaction_lock_identity",
    "validate_transaction_lock",
    "write_state_slim_archive",
]
