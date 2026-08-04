"""单 operation 读取上下文的最小跨层契约。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Protocol, runtime_checkable


class ReadContractError(ValueError):
    """在物理读取前可稳定识别的读取阻断。"""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        logical_ref: str = "",
        objects_read: int = 0,
        refs: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.logical_ref = logical_ref
        self.objects_read = objects_read
        self.refs = refs

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "blocked_ref": self.logical_ref,
            "objects_read": self.objects_read,
            "refs": list(self.refs),
            "target_bytes": 0,
        }


def normalize_read_ref(value: str) -> str:
    """规范化过程仓内逻辑引用；拒绝绝对路径和路径逃逸。"""

    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ReadContractError(
            "READ_REF_INVALID",
            "logical ref must be one non-empty relative POSIX path",
            logical_ref=value if isinstance(value, str) else "",
        )
    windows = PureWindowsPath(value)
    parts = value.split("/")
    ref = PurePosixPath(value)
    if (
        windows.drive
        or windows.root
        or ref.is_absolute()
        or ref.parts != tuple(parts)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ReadContractError(
            "READ_REF_INVALID",
            "logical ref must be canonical and remain inside the process repository",
            logical_ref=value,
        )
    return ref.as_posix()


def is_safe_read_ref(value: str) -> bool:
    """判断值是否为可供读取契约使用的规范逻辑引用。"""

    try:
        normalize_read_ref(value)
    except ReadContractError:
        return False
    return True


@runtime_checkable
class RouteSnapshotProtocol(Protocol):
    """读取上下文建立时所需的最小 workspace route 快照。"""

    process_root: Path
    project_id: str
    layout_version: int
    route_mode: str
    source: str


@runtime_checkable
class ReadContextProtocol(Protocol):
    """Loader 只依赖此 Protocol，不依赖具体缓存实现。"""

    operation_id: str
    operation_kind: str

    @property
    def objects_read(self) -> int: ...

    @property
    def refs(self) -> tuple[str, ...]: ...

    @property
    def repository_root(self) -> Path: ...

    def assert_operation(self, expected_kind: str) -> None: ...

    def resolve_path(self, logical_ref: str, *, require_file: bool = False) -> Path: ...

    def logical_ref_for(self, path: Path, *, qualified: bool = False) -> str: ...

    def read_bytes(self, logical_ref: str, *, category: str | None = None) -> bytes: ...

    def read_text(self, logical_ref: str, *, category: str | None = None) -> str: ...

    def read_json(self, logical_ref: str, *, category: str | None = None) -> Any: ...

    def read_yaml_object(
        self,
        logical_ref: str,
        *,
        category: str | None = None,
        loader: Callable[[Path], dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...

    def byte_size(self, logical_ref: str) -> int: ...

    def assert_snapshot(
        self,
        *,
        route_fingerprint: str | None = None,
        scope_digest: str | None = None,
        profile_digest: str | None = None,
        authorization_digest: str | None = None,
    ) -> None: ...

    def close(self) -> None: ...

    def close_after_mutation(self, receipt: Mapping[str, Any]) -> None: ...


def process_relative_ref(process_root: Path, path: Path) -> str:
    """把已知过程仓路径转换为 Protocol 使用的相对逻辑引用。"""

    try:
        relative = path.resolve(strict=False).relative_to(process_root.resolve(strict=False))
    except ValueError as exc:
        raise ReadContractError(
            "READ_REF_OUTSIDE_PROCESS_ROOT",
            "read path is outside the process repository",
        ) from exc
    return normalize_read_ref(relative.as_posix())


__all__ = [
    "ReadContextProtocol",
    "ReadContractError",
    "RouteSnapshotProtocol",
    "is_safe_read_ref",
    "normalize_read_ref",
    "process_relative_ref",
]
