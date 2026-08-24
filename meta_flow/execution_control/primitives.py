"""execution_control 原语唯一 owner facade。

digest/now/authorization-id 校验、原子写、通用事务 manifest 路径、runtime 链、
writer lock 与共享正式投影锁的唯一实现。消费方（lifecycle_transaction /
status_transition / transaction_child / handoff / state.current /
state.projection_transaction / exact_file_transaction）只允许从这里导入原语，
不得互相导入 ``_`` 前缀符号；本模块不得反向导入任何消费方（SCC=0）。

旧私有名（``_digest_bytes`` 等）由各消费模块内保留 thin alias 一个版本周期，
之后删除。
"""

from __future__ import annotations

import json
import os
import re
import secrets
from collections.abc import Mapping, Sequence
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

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.project.scale import dump_yaml

DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
# 使用 tracked process-route binding 作为稳定锁 inode。正式投影（含 PROJECT）会
# atomic replace，不能拿会被事务替换的 target 当锁；runtime lock 又会在 fresh
# admission 失败时制造未记账 mutation。
SHARED_WRITER_LOCK_REL = Path(".meta-flow-process.yaml")


def digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def safe_authorization_id(value: str) -> str:
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


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_atomic(path: Path, content: bytes) -> None:
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
        fsync_directory(path.parent)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def safe_path(root: Path, relative: Path, *, create_parent: bool) -> Path:
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


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    write_atomic(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def replace_bytes(path: Path, content: bytes) -> None:
    write_atomic(path, content)


def render_yaml_bytes(payload: Mapping[str, Any]) -> bytes:
    return (dump_yaml(dict(payload)) + "\n").encode("utf-8")


def plan_digest(plan_fields: Mapping[str, Any]) -> str:
    return canonical_digest(dict(plan_fields))


def manifest_path(
    root: Path,
    authorization_id: str,
    *,
    transaction_root_rel: Path,
) -> Path:
    """通用事务 manifest 路径：``<transaction_root>/<auth_id>/manifest.json``。"""

    return root / transaction_root_rel / safe_authorization_id(authorization_id) / "manifest.json"


def ensure_runtime_chain(root: Path, parts: Sequence[Path], *, create: bool) -> None:
    """逐级校验（可选创建）runtime 目录链，拒绝 symlink 与非目录占用。"""

    current = root.resolve()
    for part in parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise ValueError(f"transaction runtime path is not a plain directory: {current}")
        elif create:
            current.mkdir()
        else:
            raise ValueError("transaction runtime path is missing")


def acquire_writer_lock(
    root: Path,
    authorization_id: str,
    *,
    lock_rel: Path,
    runtime_parts: Sequence[Path],
) -> Path:
    """独占文件 writer lock：锁文件内容绑定 authorization_id，排他创建。"""

    ensure_runtime_chain(root, runtime_parts, create=True)
    path = root / lock_rel
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(safe_authorization_id(authorization_id) + "\n")
    except FileExistsError as exc:
        raise ValueError("writer lock is already held") from exc
    return path


def release_writer_lock(path: Path, authorization_id: str) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.read_text(encoding="utf-8").strip() != authorization_id
    ):
        raise ValueError("writer lock ownership changed")
    path.unlink()


@dataclass
class SharedProjectionWriterLock:
    """共享正式投影 writer 的进程级 advisory-lock capability。"""

    path: Path
    stream: TextIO


def acquire_shared_projection_writer_lock(
    process_root: Path,
    writer_id: str,
) -> SharedProjectionWriterLock:
    """获取所有正式投影 writer 共用的 advisory lock。"""

    safe_authorization_id(writer_id)
    root = process_root.resolve()
    validate_shared_projection_writer_lock_path(root)
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


def validate_shared_projection_writer_lock_path(root: Path) -> None:
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
    safe_authorization_id(writer_id)
    validate_shared_projection_writer_lock(handle)
    try:
        if fcntl is not None:
            fcntl.flock(handle.stream.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - Windows only
            handle.stream.seek(0)
            msvcrt.locking(handle.stream.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.stream.close()
