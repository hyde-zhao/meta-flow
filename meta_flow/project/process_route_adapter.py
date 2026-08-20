"""为 binding-only consumer 投影 canonical 过程仓路由。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from meta_flow.contracts.typed_ref import RepositoryRole
from meta_flow.project.process_route import (
    IndependentProcessRoute,
    ProcessRouteError,
    require_process_route,
)
from meta_flow.semantics.route import RouteConsumerClass, route_consumer_policy
from meta_flow.work.model import TypedRepositoryRefV2

_CONSUMER_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
_EXPECTED_MODE = "sibling-binding"
_PROVIDER_CODES = frozenset(
    {
        "logical_ref_escape",
        "logical_ref_invalid",
        "process_repo_missing",
        "route_conflict",
        "route_invalid",
        "route_not_initialized",
        "route_project_mismatch",
        "route_provider_unavailable",
    }
)


@dataclass(frozen=True)
class RouteConsumerView:
    """供 read consumer 使用的不可变 canonical route 投影。"""

    consumer_id: str
    project_id: str
    project_root: Path
    process_root: Path
    route_mode: str
    source: str
    classification: str
    status: str = "healthy"
    error_code: str = ""
    message: str = ""
    blocking: bool = False


class RouteConsumerError(ValueError):
    """adapter 暴露的稳定、阻断式 route consumer 失败。"""

    def __init__(self, code: str, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.error_code = code
        self.cause = cause
        self.blocking = True


def _raise_consumer_error(code: str, message: str, *, cause: BaseException | None = None) -> NoReturn:
    raise RouteConsumerError(code, message, cause=cause)


def _validate_consumer_id(consumer_id: str) -> None:
    if not isinstance(consumer_id, str) or not _CONSUMER_ID_RE.fullmatch(consumer_id):
        _raise_consumer_error(
            "route_consumer_invalid",
            "consumer_id must be a non-empty lowercase identifier",
        )


def _normalize_provider_error(error: ProcessRouteError) -> NoReturn:
    """保留已冻结 provider code；未知 code 一律按 provider 不可用阻断。"""

    if error.error_code in _PROVIDER_CODES:
        _raise_consumer_error(error.error_code, str(error), cause=error)
    _raise_consumer_error(
        "route_provider_unavailable",
        f"canonical route provider returned unknown error code: {error.error_code}",
        cause=error,
    )


def _project_route(
    route: IndependentProcessRoute,
    consumer_id: str,
    classification: RouteConsumerClass,
) -> RouteConsumerView:
    return RouteConsumerView(
        consumer_id=consumer_id,
        project_id=route.project_id,
        project_root=route.project_root,
        process_root=route.process_root,
        route_mode=route.route_mode,
        source=route.source,
        classification=classification.value,
    )


def resolve_consumer_route(
    project_root: Path,
    *,
    consumer_id: str,
    expected_mode: str = _EXPECTED_MODE,
) -> RouteConsumerView:
    """解析唯一 canonical route；不执行 legacy fallback 或二次 discovery。"""

    _validate_consumer_id(consumer_id)
    try:
        policy = route_consumer_policy(consumer_id)
    except ValueError as error:
        _raise_consumer_error("route_consumer_invalid", str(error), cause=error)
    if not policy.vnext_read:
        _raise_consumer_error(
            "route_consumer_not_vnext_read",
            f"consumer {consumer_id!r} is not a vNext read consumer",
        )
    if expected_mode != _EXPECTED_MODE:
        _raise_consumer_error(
            "route_mode_unexpected",
            f"unsupported expected route mode: {expected_mode!r}",
        )

    try:
        route = require_process_route(project_root)
    except ProcessRouteError as error:
        _normalize_provider_error(error)
    except Exception as error:
        _raise_consumer_error(
            "route_provider_unavailable",
            "canonical route provider is unavailable",
            cause=error,
        )

    if route.route_mode != expected_mode:
        _raise_consumer_error(
            "route_mode_unexpected",
            f"resolved route mode {route.route_mode!r} does not match {expected_mode!r}",
        )
    return _project_route(route, consumer_id, policy.classification)


def resolve_configured_consumer_route(
    project_root: Path,
    *,
    consumer_id: str,
) -> RouteConsumerView | None:
    """存在 tracked vNext binding 时解析；否则显式交还 legacy consumer。"""

    root = project_root.resolve(strict=False)
    if not (root / ".meta-flow" / "workspace.yaml").is_file():
        return None
    return resolve_consumer_route(root, consumer_id=consumer_id)


def resolve_typed_repository_ref(
    project_root: Path,
    ref: TypedRepositoryRefV2,
) -> Path:
    """只按 repo role + logical path 解析 regular file，不猜 sibling 或前缀。"""

    root = project_root.resolve(strict=True)
    if ref.repo_role is RepositoryRole.PROCESS:
        route = require_process_route(root)
        suffix = Path(*ref.logical_path.split("/")[1:])
        raw_target = route.process_root / suffix
        boundary = route.process_root.resolve(strict=True)
    else:
        raw_target = root / ref.logical_path
        boundary = root
    if raw_target.is_symlink():
        raise RouteConsumerError("typed_ref_symlink", "typed repository ref must target a regular file")
    try:
        target = raw_target.resolve(strict=True)
    except OSError as exc:
        raise RouteConsumerError("typed_ref_missing", "typed repository ref target is missing", cause=exc) from exc
    if not target.is_relative_to(boundary) or not target.is_file():
        raise RouteConsumerError(
            "typed_ref_not_regular",
            "typed repository ref must resolve to one contained regular file",
        )
    return target


__all__ = [
    "RouteConsumerError",
    "RouteConsumerView",
    "resolve_configured_consumer_route",
    "resolve_consumer_route",
    "resolve_typed_repository_ref",
]
