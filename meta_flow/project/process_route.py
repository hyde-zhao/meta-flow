"""vNext 独立过程仓路由与逻辑引用解析。"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from meta_flow.project.onboarding import (
    LAYOUT_VERSION,
    WORKSPACE_BINDING_REL,
    check_independent_process_route,
)


class ProcessRouteError(ValueError):
    """可预期的 vNext 路由或逻辑引用阻断。"""

    def __init__(self, error_code: str, message: str, logical_ref: str = "") -> None:
        super().__init__(message)
        self.error_code = error_code
        self.logical_ref = logical_ref

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": False,
            "error_code": self.error_code,
            "message": str(self),
            "logical_ref": self.logical_ref,
        }


@dataclass(frozen=True)
class IndependentProcessRoute:
    """一次健康检查生成的不可变 vNext 过程仓路由。"""

    project_root: Path
    process_root: Path
    project_id: str
    layout_version: str
    route_mode: str
    source: str

    def resolve_ref(self, logical_ref: str) -> Path:
        """把 ``process/<relative>`` 映射到过程仓，拒绝歧义和路径逃逸。"""

        return _resolve_injected_process_ref(self.process_root, logical_ref)

    def format_ref(self, path: Path) -> str:
        """把 release/process 物理路径格式化为唯一 canonical 引用。"""

        return _format_injected_runtime_ref(self.project_root, self.process_root, path)

    def success_payload(self, logical_ref: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": True,
            "project_id": self.project_id,
            "layout_version": self.layout_version,
            "route_mode": self.route_mode,
            "logical_ref": logical_ref,
            "resolved_path": str(self.resolve_ref(logical_ref)),
        }


def _validate_logical_ref(logical_ref: str) -> PurePosixPath:
    if not isinstance(logical_ref, str):
        raise ProcessRouteError("logical_ref_invalid", "logical ref must be one UTF-8 string", "")
    if (
        not logical_ref
        or "\x00" in logical_ref
        or "\\" in logical_ref
        or ":" in logical_ref
        or logical_ref.startswith("/")
        or logical_ref.startswith("//")
    ):
        raise ProcessRouteError(
            "logical_ref_invalid",
            "logical ref must be a relative POSIX process/<relative> path",
            logical_ref,
        )
    windows_ref = PureWindowsPath(logical_ref)
    if windows_ref.drive or windows_ref.root:
        raise ProcessRouteError(
            "logical_ref_invalid",
            "Windows drive, rooted, and UNC logical refs are forbidden",
            logical_ref,
        )
    raw_parts = logical_ref.split("/")
    if len(raw_parts) < 2 or raw_parts[0] != "process" or any(
        part in {"", ".", ".."} for part in raw_parts
    ):
        raise ProcessRouteError(
            "logical_ref_invalid",
            "logical ref must start with process/ and contain only non-empty safe segments",
            logical_ref,
        )
    ref = PurePosixPath(logical_ref)
    if ref.is_absolute() or ref.parts != tuple(raw_parts):
        raise ProcessRouteError("logical_ref_invalid", "logical ref is not canonical POSIX text", logical_ref)
    return ref


def _resolve_injected_process_ref(process_root: Path, logical_ref: str) -> Path:
    """在调用方已验证过程根后映射 logical ref，不执行 route discovery。"""

    ref = _validate_logical_ref(logical_ref)
    trusted_root = process_root.resolve(strict=False)
    candidate = trusted_root.joinpath(*ref.parts[1:]).resolve(strict=False)
    if not candidate.is_relative_to(trusted_root):
        raise ProcessRouteError(
            "logical_ref_escape",
            "logical ref resolves outside the injected process repository",
            logical_ref,
        )
    return candidate


def _format_injected_runtime_ref(
    project_root: Path,
    process_root: Path,
    path: Path,
) -> str:
    """使用已验证的双仓根格式化物理路径，不执行 route discovery。"""

    root = project_root.resolve(strict=False)
    routed_root = process_root.resolve(strict=False)
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve(strict=False)

    if resolved in {root, routed_root}:
        raise ProcessRouteError(
            "logical_ref_invalid",
            "repository roots are not artifact references",
        )

    try:
        process_relative = resolved.relative_to(routed_root)
    except ValueError:
        process_relative = None
    if process_relative is not None:
        return (PurePosixPath("process") / PurePosixPath(process_relative.as_posix())).as_posix()

    try:
        release_relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ProcessRouteError(
            "logical_ref_escape",
            "runtime path is outside the release and bound process repositories",
        ) from exc
    if release_relative.parts[:1] == ("process",):
        raise ProcessRouteError(
            "route_conflict",
            "release-local process path conflicts with the bound process repository",
        )
    return PurePosixPath(release_relative.as_posix()).as_posix()


def require_process_route(project_root: Path) -> IndependentProcessRoute:
    """解析唯一 binding 路由；任何不健康状态均 fail closed。"""

    root = project_root.resolve()
    health = check_independent_process_route(root)
    if not health.ok or health.process_repo_root is None:
        if health.status == "not_initialized":
            code = "route_not_initialized"
        elif health.status == "binding_invalid" or any(
            message.startswith("workspace binding")
            or message.startswith("process_repo.")
            for message in health.errors
        ):
            code = "route_invalid"
        else:
            code = "route_conflict"
        detail = "; ".join(health.errors) or health.status
        raise ProcessRouteError(
            code,
            f"independent process route is not healthy: {detail}; run meta-flow project check --project-root .",
        )
    return IndependentProcessRoute(
        project_root=root,
        process_root=health.process_repo_root,
        project_id=health.project_id,
        layout_version=LAYOUT_VERSION,
        route_mode=health.route_mode,
        source=WORKSPACE_BINDING_REL.as_posix(),
    )


def require_project_process_route(
    project_root: Path,
    *,
    project_id: str,
) -> IndependentProcessRoute:
    """返回与显式 project_id 一致的健康路由，供 mutation planner 使用。"""

    route = require_process_route(project_root)
    if route.project_id != project_id:
        raise ProcessRouteError(
            "route_project_mismatch",
            "independent process route belongs to a different project_id",
        )
    return route


def resolve_process_ref(project_root: Path, logical_ref: str) -> Path:
    """供 Python 顶层入口使用的单次 route + ref 解析捷径。"""

    return require_process_route(project_root).resolve_ref(logical_ref)


def format_runtime_ref(project_root: Path, path: Path) -> str:
    """把运行时物理路径还原为 release-relative 或 ``process/...`` 引用。"""

    root = project_root.resolve(strict=False)
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve(strict=False)
    try:
        release_relative = resolved.relative_to(root)
    except ValueError:
        release_relative = None
    if release_relative is not None and (
        release_relative.parts[:1] != ("process",)
        or not (root / ".meta-flow" / "workspace.yaml").is_file()
    ):
        if not release_relative.parts:
            raise ProcessRouteError(
                "logical_ref_invalid",
                "repository roots are not artifact references",
            )
        return PurePosixPath(release_relative.as_posix()).as_posix()

    process_marker = _resolve_runtime_ref(root, "process/.meta-flow-process.yaml")
    return _format_injected_runtime_ref(root, process_marker.parent, resolved)


def _resolve_runtime_ref(project_root: Path, logical_ref: str) -> Path:
    """为非 Git 单元 fixture 保留低层路径；真实仓库始终要求 vNext binding。"""

    root = project_root.resolve()
    binding_path = root / ".meta-flow" / "workspace.yaml"
    if binding_path.exists() or binding_path.is_symlink():
        return resolve_process_ref(root, logical_ref)
    if (root / ".git").exists():
        # 真实 Git 项目不得把既有 legacy process 软链接当作 vNext 自动 fallback。
        return resolve_process_ref(root, logical_ref)
    ref = _validate_logical_ref(logical_ref)
    legacy_link = root / "process"  # guardrail: legacy-non-git-fixture-only
    if legacy_link.is_symlink():
        legacy_root = legacy_link.resolve(strict=False)
        if not (legacy_root / ".meta-flow-process.yaml").is_file():
            raise ProcessRouteError(
                "legacy_policy_denied",
                "legacy process link lacks route metadata",
                logical_ref,
            )
        candidate = legacy_root.joinpath(*ref.parts[1:]).resolve(strict=False)
        if not candidate.is_relative_to(legacy_root):
            raise ProcessRouteError(
                "logical_ref_escape", "legacy logical ref escapes its route", logical_ref
            )
        return candidate
    candidate = root.joinpath(*ref.parts).resolve(strict=False)
    if not candidate.is_relative_to(root):
        raise ProcessRouteError("logical_ref_escape", "fixture logical ref escapes its root", logical_ref)
    return candidate


def _resolve_runtime_path(project_root: Path, path: str | Path) -> Path:
    """解析可能是 process logical ref 的低层路径参数。"""

    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    logical = candidate.as_posix()
    if logical.startswith("process/"):
        return _resolve_runtime_ref(project_root, logical)
    return (project_root.resolve() / candidate).resolve(strict=False)


def resolve_ref_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project resolve-ref")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--logical-ref", required=True)
    parser.add_argument("--format", choices=("json",), default="json")
    parsed = parser.parse_args(argv or [])
    try:
        route = require_process_route(parsed.project_root)
        payload = route.success_payload(parsed.logical_ref)
    except ProcessRouteError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:  # pragma: no cover - 未知故障不得伪装为契约型 BLOCKED
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": False,
                    "error_code": "internal_error",
                    "message": str(exc),
                    "logical_ref": parsed.logical_ref,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


__all__ = [
    "IndependentProcessRoute",
    "ProcessRouteError",
    "format_runtime_ref",
    "require_project_process_route",
    "require_process_route",
    "resolve_process_ref",
    "resolve_ref_main",
]
