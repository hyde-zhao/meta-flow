"""中立的有界 exact-file plan/apply/inspect/recover 事务 owner。"""

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

try:  # pragma: no cover - Windows 分支由平台验证覆盖
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

try:  # pragma: no cover - POSIX 分支由常规测试覆盖
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None  # type: ignore[assignment]

EXACT_FILE_TRANSACTION_ROOT_REL = Path(".meta-flow-runtime/exact-file")
# 使用 tracked process-route binding 作为稳定锁 inode。正式投影（含 PROJECT）会
# atomic replace，不能拿会被事务替换的 target 当锁；runtime lock 又会在 fresh
# admission 失败时制造未记账 mutation。
SHARED_WRITER_LOCK_REL = Path(".meta-flow-process.yaml")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class SharedProjectionWriterLock:
    """共享正式投影 writer 的进程级 advisory-lock capability。"""

    path: Path
    stream: TextIO


def _digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _safe_authorization_id(value: str) -> str:
    if (
        not value
        or len(value) > 128
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for character in value
        )
    ):
        raise ValueError("authorization_id is invalid")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, content: bytes) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"exact-file target is unsafe: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def _safe_path(root: Path, relative: Path, *, create_parent: bool) -> Path:
    """逐级拒绝 symlink/非目录父级，防止 exact writer 越出冻结 root。"""

    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("exact-file relative path is unsafe")
    current = root
    for part in relative.parent.parts:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise ValueError(f"exact-file parent path is unsafe: {relative.as_posix()}")
        if create_parent and not current.exists():
            current.mkdir()
    target = root / relative
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError(f"exact-file target is unsafe: {relative.as_posix()}")
    return target


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    _write_atomic(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _replace_bytes(path: Path, content: bytes) -> None:
    _write_atomic(path, content)


def acquire_shared_projection_writer_lock(
    process_root: Path,
    writer_id: str,
) -> SharedProjectionWriterLock:
    """获取所有正式投影 writer 共用的 advisory lock。"""

    _safe_authorization_id(writer_id)
    root = process_root.resolve()
    _validate_shared_projection_writer_lock_path(root)
    lock_path = root / SHARED_WRITER_LOCK_REL
    stream: TextIO | None = None
    try:
        # 锁文件必须由 project routing 预先建立；这里禁止任何 mkdir/create。
        stream = lock_path.open("r+", encoding="utf-8")
        if fcntl is not None:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt is not None:  # pragma: no cover - Windows only
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                raise ValueError("shared projection writer lock anchor is empty")
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover
            raise RuntimeError("no supported shared projection lock implementation")
        path_stat = lock_path.stat()
        handle_stat = os.fstat(stream.fileno())
        if (path_stat.st_dev, path_stat.st_ino) != (handle_stat.st_dev, handle_stat.st_ino):
            raise ValueError("shared projection writer lock identity drifted")
        return SharedProjectionWriterLock(lock_path, stream)
    except (BlockingIOError, OSError) as exc:
        if stream is not None:
            stream.close()
        raise ValueError("shared projection writer lock is already held") from exc
    except Exception:
        if stream is not None:
            stream.close()
        raise


def _validate_shared_projection_writer_lock_path(root: Path) -> None:
    """只读检查共享锁路径；admission 阶段不得顺便创建 runtime。"""

    lock_path = root / SHARED_WRITER_LOCK_REL
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ValueError("shared projection writer lock path is unsafe")


def validate_shared_projection_writer_lock(
    handle: SharedProjectionWriterLock,
    *,
    expected_path: Path | None = None,
) -> None:
    if expected_path is not None and handle.path.absolute() != expected_path.absolute():
        raise ValueError("shared projection writer lock path differs from the expected lock")
    if handle.stream.closed or handle.path.is_symlink() or not handle.path.is_file():
        raise ValueError("shared projection writer lock ownership is unsafe")
    try:
        path_stat = handle.path.stat()
        handle_stat = os.fstat(handle.stream.fileno())
    except OSError as exc:
        raise ValueError("shared projection writer lock ownership is unsafe") from exc
    if (path_stat.st_dev, path_stat.st_ino) != (handle_stat.st_dev, handle_stat.st_ino):
        raise ValueError("shared projection writer lock identity drifted")


def release_shared_projection_writer_lock(
    handle: SharedProjectionWriterLock,
    writer_id: str,
) -> None:
    _safe_authorization_id(writer_id)
    validate_shared_projection_writer_lock(handle)
    try:
        if fcntl is not None:
            fcntl.flock(handle.stream.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - Windows only
            handle.stream.seek(0)
            msvcrt.locking(handle.stream.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.stream.close()


@dataclass(frozen=True, slots=True)
class ExactFileTargetV1:
    ref: str
    before_exists: bool
    before_digest: str
    after_bytes: bytes
    after_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "before_exists": self.before_exists,
            "before_digest": self.before_digest,
            "after_bytes_b64": base64.b64encode(self.after_bytes).decode("ascii"),
            "after_digest": self.after_digest,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ExactFileTargetV1:
        expected = {
            "ref",
            "before_exists",
            "before_digest",
            "after_bytes_b64",
            "after_digest",
        }
        if set(payload) != expected or not isinstance(payload.get("before_exists"), bool):
            raise ValueError("exact-file target fields mismatch")
        try:
            after = base64.b64decode(str(payload["after_bytes_b64"]), validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("exact-file target after bytes are invalid") from exc
        target = cls(
            str(payload["ref"]),
            bool(payload["before_exists"]),
            str(payload["before_digest"]),
            after,
            str(payload["after_digest"]),
        )
        _validate_exact_target(target)
        return target


@dataclass(frozen=True, slots=True)
class ExactFilePlanV1:
    operation: str
    targets: tuple[ExactFileTargetV1, ...]
    semantic_binding_digest: str
    plan_digest: str

    @property
    def target_refs(self) -> tuple[str, ...]:
        return tuple(target.ref for target in self.targets)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "ExactFilePlanV1",
            "decision": "READY",
            "operation": self.operation,
            "targets": [target.as_dict() for target in self.targets],
            "target_refs": list(self.target_refs),
            "semantic_binding_digest": self.semantic_binding_digest,
            "plan_digest": self.plan_digest,
            "mutation_count": 0,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ExactFilePlanV1:
        expected = {
            "schema_version",
            "kind",
            "decision",
            "operation",
            "targets",
            "target_refs",
            "semantic_binding_digest",
            "plan_digest",
            "mutation_count",
        }
        if (
            set(payload) != expected
            or payload.get("schema_version") != 1
            or payload.get("kind") != "ExactFilePlanV1"
            or payload.get("decision") != "READY"
            or payload.get("mutation_count") != 0
            or not isinstance(payload.get("targets"), list)
            or not isinstance(payload.get("target_refs"), list)
        ):
            raise ValueError("exact-file plan fields mismatch")
        plan = cls(
            str(payload["operation"]),
            tuple(ExactFileTargetV1.from_mapping(item) for item in payload["targets"]),
            str(payload["semantic_binding_digest"]),
            str(payload["plan_digest"]),
        )
        _validate_exact_plan(plan)
        if list(plan.target_refs) != payload["target_refs"]:
            raise ValueError("exact-file plan target refs mismatch")
        return plan


@dataclass(frozen=True, slots=True)
class ExactFileAuthorizationV1:
    authorization_id: str
    operation: str
    plan_digest: str
    target_refs: tuple[str, ...]
    expires_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "ExactFileAuthorizationV1",
            "authorization_id": self.authorization_id,
            "operation": self.operation,
            "plan_digest": self.plan_digest,
            "target_refs": list(self.target_refs),
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ExactFileAuthorizationV1:
        expected = {
            "schema_version",
            "kind",
            "authorization_id",
            "operation",
            "plan_digest",
            "target_refs",
            "expires_at",
        }
        if (
            set(payload) != expected
            or payload.get("schema_version") != 1
            or payload.get("kind") != "ExactFileAuthorizationV1"
            or not isinstance(payload.get("target_refs"), list)
        ):
            raise ValueError("exact-file authorization fields mismatch")
        return cls(
            str(payload["authorization_id"]),
            str(payload["operation"]),
            str(payload["plan_digest"]),
            tuple(str(ref) for ref in payload["target_refs"]),
            str(payload["expires_at"]),
        )

    def validate_for(self, plan: ExactFilePlanV1) -> None:
        _safe_authorization_id(self.authorization_id)
        if (
            self.operation != plan.operation
            or self.plan_digest != plan.plan_digest
            or self.target_refs != plan.target_refs
        ):
            raise ValueError("exact-file authorization binding mismatch")
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("exact-file authorization expiry is invalid") from exc
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("exact-file authorization is expired")


def _exact_plan_digest(
    operation: str,
    targets: tuple[ExactFileTargetV1, ...],
    semantic_binding_digest: str,
) -> str:
    return _digest_bytes(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "ExactFilePlanV1",
                "operation": operation,
                "targets": [target.as_dict() for target in targets],
                "semantic_binding_digest": semantic_binding_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _validate_exact_target(target: ExactFileTargetV1) -> None:
    path = Path(target.ref)
    if (
        not target.ref
        or path.is_absolute()
        or "\\" in target.ref
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.parts[0] == ".meta-flow-runtime"
        or not _DIGEST_RE.fullmatch(target.before_digest)
        or not _DIGEST_RE.fullmatch(target.after_digest)
        or _digest_bytes(target.after_bytes) != target.after_digest
    ):
        raise ValueError("exact-file target is invalid")


def _validate_exact_plan(plan: ExactFilePlanV1) -> None:
    if (
        not plan.operation
        or len(plan.operation) > 128
        or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789.-_" for char in plan.operation)
        or not _DIGEST_RE.fullmatch(plan.semantic_binding_digest)
        or len(plan.target_refs) != len(set(plan.target_refs))
    ):
        raise ValueError("exact-file plan identity is invalid")
    for target in plan.targets:
        _validate_exact_target(target)
    if plan.plan_digest != _exact_plan_digest(
        plan.operation,
        plan.targets,
        plan.semantic_binding_digest,
    ):
        raise ValueError("exact-file plan digest mismatch")


def build_exact_file_plan(
    operation: str,
    targets: tuple[ExactFileTargetV1, ...],
    *,
    semantic_binding_digest: str,
) -> ExactFilePlanV1:
    ordered = tuple(sorted(targets, key=lambda target: target.ref))
    return ExactFilePlanV1(
        operation,
        ordered,
        semantic_binding_digest,
        _exact_plan_digest(operation, ordered, semantic_binding_digest),
    )


def _exact_manifest_path(
    root: Path,
    authorization_id: str,
    *,
    create_parent: bool = False,
) -> Path:
    return _safe_path(
        root,
        EXACT_FILE_TRANSACTION_ROOT_REL
        / _safe_authorization_id(authorization_id)
        / "manifest.json",
        create_parent=create_parent,
    )


def _validate_exact_manifest(
    payload: Mapping[str, Any],
    *,
    expected_authorization_id: str,
) -> ExactFilePlanV1:
    expected = {
        "schema_version",
        "kind",
        "authorization_id",
        "operation",
        "plan",
        "state",
        "created_at",
        "updated_at",
        "attempted_refs",
        "applied_refs",
        "before_images_b64",
        "failure",
        "recovery_failures",
    }
    if (
        set(payload) != expected
        or payload.get("schema_version") != 1
        or payload.get("kind") != "ExactFileTransactionV1"
        or payload.get("authorization_id") != expected_authorization_id
        or payload.get("state") not in {"PREPARED", "APPLYING", "COMMITTED", "RECOVERED", "PARTIAL"}
        or not isinstance(payload.get("plan"), dict)
    ):
        raise ValueError("exact-file manifest fields/identity are invalid")
    _safe_authorization_id(expected_authorization_id)
    plan = ExactFilePlanV1.from_mapping(dict(payload["plan"]))
    if payload.get("operation") != plan.operation:
        raise ValueError("exact-file manifest operation binding mismatch")
    attempted = payload.get("attempted_refs")
    applied = payload.get("applied_refs")
    before_images = payload.get("before_images_b64")
    if (
        not isinstance(attempted, list)
        or not isinstance(applied, list)
        or not isinstance(before_images, dict)
        or list(dict.fromkeys(attempted)) != attempted
        or list(dict.fromkeys(applied)) != applied
        or any(ref not in plan.target_refs for ref in attempted)
        or any(ref not in attempted for ref in applied)
        or set(before_images) != set(plan.target_refs)
        or not isinstance(payload.get("recovery_failures"), list)
    ):
        raise ValueError("exact-file manifest accounting is invalid")
    for target in plan.targets:
        try:
            before = base64.b64decode(str(before_images[target.ref]), validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("exact-file manifest before image is invalid") from exc
        if target.before_exists != bool(before) and not (
            target.before_exists and target.before_digest == _digest_bytes(b"")
        ):
            # 已存在的空文件是合法 preimage；不存在只能绑定空 bytes。
            if not (target.before_exists and before == b""):
                raise ValueError("exact-file manifest before existence mismatch")
        if _digest_bytes(before) != target.before_digest:
            raise ValueError("exact-file manifest before digest mismatch")
    return plan


def _exact_preimage(root: Path, target: ExactFileTargetV1) -> bytes:
    path = _safe_path(root, Path(target.ref), create_parent=False)
    exists = path.is_file()
    before = path.read_bytes() if exists else b""
    if exists != target.before_exists or _digest_bytes(before) != target.before_digest:
        raise ValueError(f"exact-file target preimage drift: {target.ref}")
    return before


def _rollback_exact(root: Path, manifest: dict[str, Any]) -> list[str]:
    plan = ExactFilePlanV1.from_mapping(dict(manifest["plan"]))
    by_ref = {target.ref: target for target in plan.targets}
    failures: list[str] = []
    for ref in reversed(list(manifest["attempted_refs"])):
        target = by_ref[ref]
        path = _safe_path(root, Path(ref), create_parent=False)
        try:
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ValueError("target became unsafe")
            current = path.read_bytes() if path.is_file() else b""
            current_exists = path.is_file()
            current_digest = _digest_bytes(current)
            if current_exists == target.before_exists and current_digest == target.before_digest:
                continue
            if not current_exists or current_digest != target.after_digest:
                raise ValueError("target bytes left exact transaction generations")
            before = base64.b64decode(
                str(manifest["before_images_b64"][ref]),
                validate=True,
            )
            if target.before_exists:
                _replace_bytes(path, before)
            else:
                path.unlink()
        except (OSError, ValueError) as exc:
            failures.append(f"{ref}: {exc}")
    return failures


def _blocked_exact_receipt(
    plan: ExactFilePlanV1,
    authorization: ExactFileAuthorizationV1,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "ExactFileTransactionReceiptV1",
        "decision": "BLOCKED",
        "authorization_id": authorization.authorization_id,
        "plan_digest": plan.plan_digest,
        "planned_refs": list(plan.target_refs),
        "actual_mutation_refs": [],
        "mutation_count": 0,
        "recovery_required": False,
        "reason_codes": [reason_code],
    }


def apply_exact_file_plan(
    root: Path,
    plan: ExactFilePlanV1,
    authorization: ExactFileAuthorizationV1,
) -> dict[str, Any]:
    """在一个 durable manifest 下提交任意有界 exact-file target 集。"""

    root = root.resolve()
    try:
        _validate_exact_plan(plan)
        authorization.validate_for(plan)
        manifest_path = _exact_manifest_path(root, authorization.authorization_id)
        if manifest_path.exists() or manifest_path.is_symlink():
            return _blocked_exact_receipt(
                plan,
                authorization,
                "EXACT_FILE_AUTHORIZATION_ALREADY_CONSUMED",
            )
        for target in plan.targets:
            _exact_preimage(root, target)
        _validate_shared_projection_writer_lock_path(root)
    except ValueError:
        return _blocked_exact_receipt(
            plan,
            authorization,
            "EXACT_FILE_ADMISSION_FAILED",
        )
    writer_id = "exact-file-" + _digest_bytes(authorization.authorization_id.encode())[:24]
    try:
        lock = acquire_shared_projection_writer_lock(root, writer_id)
    except ValueError:
        return _blocked_exact_receipt(
            plan,
            authorization,
            "EXACT_FILE_WRITER_LOCK_UNAVAILABLE",
        )
    try:
        try:
            manifest_path = _exact_manifest_path(root, authorization.authorization_id)
            if manifest_path.exists() or manifest_path.is_symlink():
                return _blocked_exact_receipt(
                    plan,
                    authorization,
                    "EXACT_FILE_AUTHORIZATION_ALREADY_CONSUMED",
                )
            before_images = {target.ref: _exact_preimage(root, target) for target in plan.targets}
            manifest_path = _exact_manifest_path(
                root,
                authorization.authorization_id,
                create_parent=True,
            )
        except ValueError:
            return _blocked_exact_receipt(
                plan,
                authorization,
                "EXACT_FILE_FRESH_ADMISSION_FAILED",
            )
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "kind": "ExactFileTransactionV1",
            "authorization_id": authorization.authorization_id,
            "operation": plan.operation,
            "plan": plan.as_dict(),
            "state": "PREPARED",
            "created_at": _now(),
            "updated_at": _now(),
            "attempted_refs": [],
            "applied_refs": [],
            "before_images_b64": {
                ref: base64.b64encode(content).decode("ascii")
                for ref, content in before_images.items()
            },
            "failure": "",
            "recovery_failures": [],
        }
        _validate_exact_manifest(
            manifest,
            expected_authorization_id=authorization.authorization_id,
        )
        _write_json_atomic(manifest_path, manifest)
        try:
            manifest["state"] = "APPLYING"
            manifest["updated_at"] = _now()
            _write_json_atomic(manifest_path, manifest)
            for target in plan.targets:
                _exact_preimage(root, target)
                manifest["attempted_refs"].append(target.ref)
                manifest["updated_at"] = _now()
                _write_json_atomic(manifest_path, manifest)
                _replace_bytes(
                    _safe_path(root, Path(target.ref), create_parent=True),
                    target.after_bytes,
                )
                manifest["applied_refs"].append(target.ref)
                manifest["updated_at"] = _now()
                _write_json_atomic(manifest_path, manifest)
            manifest["state"] = "COMMITTED"
            manifest["updated_at"] = _now()
            _write_json_atomic(manifest_path, manifest)
            return {
                "schema_version": 1,
                "kind": "ExactFileTransactionReceiptV1",
                "decision": "PASS",
                "authorization_id": authorization.authorization_id,
                "plan_digest": plan.plan_digest,
                "planned_refs": list(plan.target_refs),
                "actual_mutation_refs": list(manifest["applied_refs"]),
                "mutation_count": len(manifest["applied_refs"]),
                "recovery_required": False,
            }
        except Exception as exc:
            failures = _rollback_exact(root, manifest)
            manifest["state"] = "PARTIAL" if failures else "RECOVERED"
            manifest["failure"] = str(exc)
            manifest["recovery_failures"] = failures
            manifest["updated_at"] = _now()
            _write_json_atomic(manifest_path, manifest)
            return {
                "schema_version": 1,
                "kind": "ExactFileTransactionReceiptV1",
                "decision": manifest["state"],
                "authorization_id": authorization.authorization_id,
                "plan_digest": plan.plan_digest,
                "planned_refs": list(plan.target_refs),
                "actual_mutation_refs": list(manifest["applied_refs"]),
                "mutation_count": len(manifest["applied_refs"]),
                "recovery_required": bool(failures),
                "reason_codes": ["EXACT_FILE_APPLY_FAILED"],
            }
    finally:
        release_shared_projection_writer_lock(lock, writer_id)


def inspect_exact_file_transactions(
    root: Path,
    *,
    expected_operation: str = "",
) -> dict[str, Any]:
    root = root.resolve()
    runtime = root / EXACT_FILE_TRANSACTION_ROOT_REL
    findings: list[str] = []
    transactions: list[dict[str, Any]] = []
    loaded: list[tuple[Path, dict[str, Any], ExactFilePlanV1, str]] = []
    try:
        _safe_path(
            root,
            EXACT_FILE_TRANSACTION_ROOT_REL / ".inspect-sentinel",
            create_parent=False,
        )
    except ValueError:
        findings.append("EXACT_FILE_RUNTIME_UNSAFE")
    else:
        if not runtime.is_dir():
            return {
                "schema_version": 1,
                "kind": "ExactFileTransactionInspectionV1",
                "decision": "PASS",
                "transactions": [],
                "findings": [],
                "mutation_count": 0,
            }
        for path in sorted(runtime.glob("*/manifest.json")):
            try:
                if path.is_symlink() or path.parent.is_symlink():
                    raise ValueError("manifest path is unsafe")
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("manifest payload is invalid")
                plan = _validate_exact_manifest(
                    payload,
                    expected_authorization_id=path.parent.name,
                )
                state = str(payload["state"])
                if expected_operation and plan.operation != expected_operation:
                    continue
                loaded.append((path, payload, plan, state))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                findings.append(f"EXACT_FILE_MANIFEST_INVALID:{path}:{exc}")

        edges: dict[str, dict[tuple[bool, str], set[tuple[bool, str]]]] = {}
        for _path, _payload, plan, state in loaded:
            if state != "COMMITTED":
                continue
            for target in plan.targets:
                edges.setdefault(target.ref, {}).setdefault(
                    (target.before_exists, target.before_digest), set()
                ).add((True, target.after_digest))

        def reachable(
            ref: str,
            start: tuple[bool, str],
            current: tuple[bool, str],
        ) -> bool:
            pending = [start]
            seen: set[tuple[bool, str]] = set()
            while pending:
                candidate = pending.pop()
                if candidate == current:
                    return True
                if candidate in seen:
                    continue
                seen.add(candidate)
                pending.extend(edges.get(ref, {}).get(candidate, ()))
            return False

        for path, _payload, plan, state in loaded:
            classification = state
            superseded = False
            try:
                if state not in {"COMMITTED", "RECOVERED"}:
                    findings.append(f"EXACT_FILE_UNRESOLVED:{path.parent.name}:{state}")
                for target in plan.targets:
                    current_path = _safe_path(root, Path(target.ref), create_parent=False)
                    current = current_path.read_bytes() if current_path.is_file() else b""
                    current_exists = current_path.is_file()
                    expected_exists = target.before_exists if state == "RECOVERED" else True
                    expected_digest = (
                        target.before_digest if state == "RECOVERED" else target.after_digest
                    )
                    mismatched = (
                        current_exists != expected_exists
                        or _digest_bytes(current) != expected_digest
                    )
                    if mismatched and reachable(
                        target.ref,
                        (expected_exists, expected_digest),
                        (current_exists, _digest_bytes(current)),
                    ):
                        superseded = True
                    elif mismatched:
                        findings.append(
                            f"EXACT_FILE_GENERATION_DRIFT:{path.parent.name}:{target.ref}"
                        )
                if superseded:
                    classification = "SUPERSEDED"
                transactions.append(
                    {
                        "authorization_id": path.parent.name,
                        "operation": plan.operation,
                        "state": state,
                        "classification": classification,
                        "plan_digest": plan.plan_digest,
                    }
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                findings.append(f"EXACT_FILE_TARGET_INVALID:{path}:{exc}")
    return {
        "schema_version": 1,
        "kind": "ExactFileTransactionInspectionV1",
        "decision": "BLOCKED" if findings else "PASS",
        "transactions": transactions,
        "findings": findings,
        "mutation_count": 0,
    }


def recover_exact_file_transaction(
    root: Path,
    authorization_id: str,
    *,
    expected_operation: str = "",
) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = _exact_manifest_path(root, authorization_id)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("exact-file manifest is missing")
    writer_id = "exact-file-recover-" + _digest_bytes(authorization_id.encode())[:16]
    lock = acquire_shared_projection_writer_lock(root, writer_id)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("exact-file manifest is invalid")
        plan = _validate_exact_manifest(payload, expected_authorization_id=authorization_id)
        if expected_operation and plan.operation != expected_operation:
            raise ValueError("exact-file transaction operation binding mismatch")
        if payload["state"] == "COMMITTED":
            return {
                "schema_version": 1,
                "kind": "ExactFileRecoveryReceiptV1",
                "decision": "NO_CHANGE",
                "authorization_id": authorization_id,
                "plan_digest": plan.plan_digest,
                "recovery_required": False,
            }
        failures = _rollback_exact(root, payload)
        payload["state"] = "PARTIAL" if failures else "RECOVERED"
        payload["recovery_failures"] = failures
        payload["updated_at"] = _now()
        _write_json_atomic(manifest_path, payload)
        return {
            "schema_version": 1,
            "kind": "ExactFileRecoveryReceiptV1",
            "decision": payload["state"],
            "authorization_id": authorization_id,
            "plan_digest": plan.plan_digest,
            "recovery_required": bool(failures),
            "reason_codes": ["EXACT_FILE_RECOVERY_FAILED"] if failures else [],
        }
    finally:
        release_shared_projection_writer_lock(lock, writer_id)



__all__ = [
    "EXACT_FILE_TRANSACTION_ROOT_REL",
    "SHARED_WRITER_LOCK_REL",
    "ExactFileAuthorizationV1",
    "ExactFilePlanV1",
    "ExactFileTargetV1",
    "SharedProjectionWriterLock",
    "acquire_shared_projection_writer_lock",
    "apply_exact_file_plan",
    "build_exact_file_plan",
    "inspect_exact_file_transactions",
    "recover_exact_file_transaction",
    "release_shared_projection_writer_lock",
    "validate_shared_projection_writer_lock",
]
