"""Project-first artifact routing with portable, fail-closed metadata.

该模块只解析路由并生成不可变值对象；它不会创建目录、修改软链接或调用 Git。
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

ArtifactKind = Literal["docs", "process"]
RouteIntent = Literal["read", "write"]

SCHEMA_VERSION = 1
PROJECT_FIRST_LAYOUT = "project-first-worktree-v1"
LEGACY_LAYOUT = "legacy-shared-v1"
SUPPORTED_LAYOUTS = (LEGACY_LAYOUT, PROJECT_FIRST_LAYOUT)
ALLOWED_ANCHORS = (
    "project_root",
    "artifact_control_root",
    "sibling_root",
    "project_worktree",
)
STABLE_ERROR_CODES = (
    "config_missing",
    "schema_unsupported",
    "layout_unsupported",
    "project_mismatch",
    "anchor_unknown",
    "anchor_parent_invalid",
    "anchor_cycle",
    "absolute_canonical_path",
    "path_escape",
    "control_nested_worktree",
    "write_target_ambiguous",
    "target_not_owned",
    "route_conflict",
)

_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PATH_PARENT = {
    "artifact_control_root": "project_root",
    "sibling_root": "project_root",
    "project_worktree": "sibling_root",
    "docs_relative": "project_worktree",
    "process_relative": "project_worktree",
    "legacy_docs": "artifact_control_root",
    "legacy_process": "artifact_control_root",
}
_ANCHOR_NODE_FIELDS = ("artifact_control_root", "sibling_root", "project_worktree")


@dataclass(frozen=True)
class PathRef:
    anchor: str
    relative_path: str


@dataclass(frozen=True)
class ProjectArtifactConfig:
    schema_version: int
    project_id: str
    layout_version: str
    artifact_control_root: PathRef
    sibling_root: PathRef | None = None
    project_worktree: PathRef | None = None
    docs_relative: PathRef | None = None
    process_relative: PathRef | None = None
    legacy_docs: PathRef | None = None
    legacy_process: PathRef | None = None
    branch_namespace: str = ""
    owned_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteTarget:
    kind: ArtifactKind
    role: Literal["primary", "compatibility"]
    canonical_ref: PathRef
    runtime_path: Path
    read_only: bool


@dataclass(frozen=True)
class RoutingError:
    code: str
    field: str
    message: str
    logical_candidates: tuple[str, ...]
    repair_route: str
    declared_anchor: str = ""
    expected_anchor: str = ""


@dataclass(frozen=True)
class RouteDecision:
    schema_version: int
    project_id: str
    layout_version: str
    target_kind: str
    intent: str
    decision: Literal["PASS", "BLOCKED"]
    read_targets: tuple[RouteTarget, ...]
    write_target: RouteTarget | None
    conflicts: tuple[str, ...]
    error: RoutingError | None
    config_digest: str
    decision_digest: str
    observed_at: str


@dataclass(frozen=True)
class OwnedTargetProof:
    project_id: str
    target_kind: ArtifactKind
    candidate_relative: str
    write_target_digest: str
    config_digest: str
    decision_digest: str


class RoutingValidationError(ValueError):
    """面向调用方的结构化路由校验错误。"""

    def __init__(
        self,
        code: str,
        *,
        field: str,
        message: str,
        logical_candidates: Sequence[str] = (),
        repair_route: str,
        declared_anchor: str = "",
        expected_anchor: str = "",
    ) -> None:
        if code not in STABLE_ERROR_CODES:
            raise ValueError(f"unknown routing error code: {code}")
        safe_message = str(message).replace("\x00", "").replace("\n", " ")[:500]
        self.error = RoutingError(
            code=code,
            field=field,
            message=safe_message,
            logical_candidates=tuple(str(item)[:500] for item in logical_candidates),
            repair_route=repair_route[:500],
            declared_anchor=declared_anchor[:100],
            expected_anchor=expected_anchor[:100],
        )
        self.code = self.error.code
        self.field = self.error.field
        self.logical_candidates = self.error.logical_candidates
        self.repair_route = self.error.repair_route
        self.declared_anchor = self.error.declared_anchor
        self.expected_anchor = self.error.expected_anchor
        super().__init__(f"{code}: {field}: {safe_message}; repair: {self.repair_route}")


def _raise_validation(
    code: str,
    *,
    field: str,
    message: str,
    logical_candidates: Sequence[str] = (),
    repair_route: str,
    declared_anchor: str = "",
    expected_anchor: str = "",
) -> None:
    raise RoutingValidationError(
        code,
        field=field,
        message=message,
        logical_candidates=logical_candidates,
        repair_route=repair_route,
        declared_anchor=declared_anchor,
        expected_anchor=expected_anchor,
    )


def _validate_project_id(project_id: object, *, field: str) -> str:
    if not isinstance(project_id, str) or not _PROJECT_ID_PATTERN.fullmatch(project_id):
        _raise_validation(
            "project_mismatch",
            field=field,
            message="project identity must be a non-option safe token",
            logical_candidates=(str(project_id),),
            repair_route="provide a project id matching ^[A-Za-z0-9][A-Za-z0-9._-]*$",
        )
    return project_id


def _parse_scalar(value: str, *, line_number: int) -> object:
    value = value.strip()
    if not value:
        return ""
    if value[0] in {'"', "'"}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            _raise_validation(
                "route_conflict",
                field=f"metadata.line.{line_number}",
                message="invalid quoted scalar",
                repair_route="fix the selected metadata file; no fallback file will be scanned",
            )
        if not isinstance(parsed, str):
            _raise_validation(
                "route_conflict",
                field=f"metadata.line.{line_number}",
                message="quoted metadata scalar must be a string",
                repair_route="use a quoted string scalar",
            )
        return parsed
    if value.startswith("["):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            _raise_validation(
                "route_conflict",
                field=f"metadata.line.{line_number}",
                message="invalid inline list",
                repair_route="use a scalar list with one item per line",
            )
        if not isinstance(parsed, list):
            _raise_validation(
                "route_conflict",
                field=f"metadata.line.{line_number}",
                message="inline collection must be a list",
                repair_route="use a scalar list",
            )
        return parsed
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    return value


def _parse_simple_yaml(text: str) -> dict[str, object]:
    lines: list[tuple[int, str, int]] = []
    for number, raw_line in enumerate(text.splitlines(), start=1):
        if "\t" in raw_line:
            _raise_validation(
                "route_conflict",
                field=f"metadata.line.{number}",
                message="tabs are not allowed in portable route metadata",
                repair_route="replace tabs with spaces",
            )
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped in {"---", "..."}:
            continue
        lines.append((len(raw_line) - len(raw_line.lstrip(" ")), stripped, number))

    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object] | list[object]]] = [(-1, root)]
    for index, (indent, stripped, line_number) in enumerate(lines):
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            _raise_validation(
                "route_conflict",
                field=f"metadata.line.{line_number}",
                message="invalid indentation",
                repair_route="use a root mapping with consistently indented children",
            )
        parent = stack[-1][1]
        if stripped.startswith("- "):
            if not isinstance(parent, list):
                _raise_validation(
                    "route_conflict",
                    field=f"metadata.line.{line_number}",
                    message="list item appears outside a list field",
                    repair_route="place list items below a list-valued key",
                )
            parent.append(_parse_scalar(stripped[2:], line_number=line_number))
            continue
        if not isinstance(parent, dict) or ":" not in stripped:
            _raise_validation(
                "route_conflict",
                field=f"metadata.line.{line_number}",
                message="metadata entry must be key: value",
                repair_route="fix the selected metadata mapping",
            )
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        if not key or key in parent:
            _raise_validation(
                "route_conflict",
                field=f"metadata.line.{line_number}",
                message="metadata keys must be non-empty and unique",
                logical_candidates=(key,),
                repair_route="remove duplicate or empty keys",
            )
        if raw_value.strip():
            parent[key] = _parse_scalar(raw_value, line_number=line_number)
            continue
        next_is_list = index + 1 < len(lines) and lines[index + 1][0] > indent and lines[index + 1][1].startswith("- ")
        child: dict[str, object] | list[object] = [] if next_is_list else {}
        parent[key] = child
        stack.append((indent, child))
    return root


def _parse_metadata(raw: bytes) -> dict[str, object]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _raise_validation(
            "route_conflict",
            field="metadata",
            message="metadata must be UTF-8",
            repair_route="rewrite the selected metadata file as UTF-8",
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = _parse_simple_yaml(text)
    if not isinstance(payload, dict):
        _raise_validation(
            "route_conflict",
            field="metadata",
            message="metadata root must be an object",
            repair_route="use a mapping at the metadata root",
        )
    return payload


def _raw_path_ref(payload: Mapping[str, object], field: str, *, required: bool) -> PathRef | None:
    value = payload.get(field)
    if value is None:
        if required:
            _raise_validation(
                "route_conflict",
                field=field,
                message="required path reference is missing",
                repair_route=f"add {field}.anchor and {field}.relative_path",
            )
        return None
    if not isinstance(value, Mapping):
        _raise_validation(
            "route_conflict",
            field=field,
            message="path reference must be an object",
            repair_route=f"replace {field} with anchor/relative_path fields",
        )
    anchor = value.get("anchor")
    relative_path = value.get("relative_path")
    if not isinstance(anchor, str):
        anchor = "" if anchor is None else str(anchor)
    if not isinstance(relative_path, str):
        _raise_validation(
            "route_conflict",
            field=f"{field}.relative_path",
            message="relative_path must be a string",
            repair_route="provide a portable POSIX relative path",
        )
    return PathRef(anchor=anchor, relative_path=relative_path)


def _validate_anchor_graph(refs: Mapping[str, PathRef | None]) -> None:
    for field, ref in refs.items():
        if ref is None:
            continue
        if ref.anchor not in ALLOWED_ANCHORS:
            _raise_validation(
                "anchor_unknown",
                field=f"{field}.anchor",
                message="path reference uses an unknown logical anchor",
                logical_candidates=(ref.anchor,),
                repair_route=f"choose the required anchor {_PATH_PARENT[field]}",
                declared_anchor=ref.anchor,
                expected_anchor=_PATH_PARENT[field],
            )

    edges = {
        field: ref.anchor
        for field in _ANCHOR_NODE_FIELDS
        if (ref := refs.get(field)) is not None and ref.anchor != "project_root"
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, trail: tuple[str, ...]) -> None:
        if node in visiting:
            cycle = (*trail, node)
            _raise_validation(
                "anchor_cycle",
                field=f"{node}.anchor",
                message="anchor graph contains a cycle",
                logical_candidates=cycle,
                repair_route="restore the fixed project_root→sibling_root→project_worktree DAG",
                declared_anchor=edges.get(node, ""),
                expected_anchor=_PATH_PARENT[node],
            )
        if node in visited:
            return
        visiting.add(node)
        parent = edges.get(node)
        if parent in _ANCHOR_NODE_FIELDS:
            visit(parent, (*trail, node))
        visiting.remove(node)
        visited.add(node)

    for field in _ANCHOR_NODE_FIELDS:
        if refs.get(field) is not None:
            visit(field, ())

    for field, ref in refs.items():
        if ref is None:
            continue
        expected = _PATH_PARENT[field]
        if ref.anchor != expected:
            _raise_validation(
                "anchor_parent_invalid",
                field=f"{field}.anchor",
                message="path reference uses the wrong parent anchor",
                logical_candidates=(ref.anchor, expected),
                repair_route=f"set {field}.anchor to {expected}",
                declared_anchor=ref.anchor,
                expected_anchor=expected,
            )


def _normalize_relative_path(value: str, *, field: str) -> str:
    if not value:
        _raise_validation(
            "path_escape",
            field=field,
            message="canonical relative path must be non-empty",
            repair_route="provide a normalized non-empty POSIX relative path",
        )
    if "\x00" in value or "\n" in value or "\r" in value or "\\" in value:
        _raise_validation(
            "path_escape",
            field=field,
            message="canonical relative path contains a forbidden character",
            repair_route="use POSIX segments without NUL, newline, or backslash",
        )
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if posix_path.is_absolute() or windows_path.is_absolute() or bool(windows_path.drive):
        _raise_validation(
            "absolute_canonical_path",
            field=field,
            message="canonical metadata cannot contain an absolute device path",
            logical_candidates=(value,),
            repair_route="replace the value with an anchor-relative path",
        )
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts) or str(posix_path) != value:
        _raise_validation(
            "path_escape",
            field=field,
            message="canonical path contains empty, dot, traversal, or non-normalized segments",
            logical_candidates=(value,),
            repair_route="normalize the path and remove dot/traversal segments",
        )
    return value


def _normalize_owned_path_items(value: object, *, required: bool) -> list[str]:
    if not isinstance(value, (list, tuple)) or (required and not value):
        _raise_validation(
            "route_conflict",
            field="owned_paths",
            message=(
                "project-first layout requires a non-empty owned_paths list"
                if required
                else "owned_paths must be a list or tuple when provided"
            ),
            repair_route="declare the current project's docs and process owned paths",
        )
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            _raise_validation(
                "route_conflict",
                field=f"owned_paths.{index}",
                message="owned path must be a string",
                repair_route="use normalized POSIX relative paths",
            )
        normalized.append(_normalize_relative_path(item, field=f"owned_paths.{index}"))
    return normalized


def _normalize_owned_paths(value: object) -> tuple[str, ...]:
    normalized = _normalize_owned_path_items(value, required=True)
    if len(set(normalized)) != len(normalized):
        _raise_validation(
            "route_conflict",
            field="owned_paths",
            message="owned paths must be unique",
            repair_route="remove duplicate owned path declarations",
        )
    ordered = sorted(normalized)
    for index, left in enumerate(ordered):
        left_path = PurePosixPath(left)
        for right in ordered[index + 1 :]:
            right_path = PurePosixPath(right)
            if left_path == right_path or left_path in right_path.parents or right_path in left_path.parents:
                _raise_validation(
                    "route_conflict",
                    field="owned_paths",
                    message="owned paths must not overlap",
                    logical_candidates=(left, right),
                    repair_route="declare disjoint owned path roots",
                )
    return tuple(ordered)


def _normalized_ref(ref: PathRef | None, field: str) -> PathRef | None:
    if ref is None:
        return None
    return PathRef(
        anchor=ref.anchor,
        relative_path=_normalize_relative_path(ref.relative_path, field=f"{field}.relative_path"),
    )


def _required_config_ref(config: ProjectArtifactConfig, field: str) -> PathRef:
    ref = getattr(config, field)
    if ref is None:
        _raise_validation(
            "route_conflict",
            field=field,
            message="layout requires this path reference",
            repair_route=f"add {field} using anchor {_PATH_PARENT[field]}",
        )
    return ref


def _path_contains(parent: PurePosixPath, child: PurePosixPath) -> bool:
    return parent == child or parent in child.parents


def _validate_leaf_contract(config: ProjectArtifactConfig) -> None:
    if config.layout_version == PROJECT_FIRST_LAYOUT:
        docs = _required_config_ref(config, "docs_relative")
        process = _required_config_ref(config, "process_relative")
        _required_config_ref(config, "sibling_root")
        worktree = _required_config_ref(config, "project_worktree")
        if PurePosixPath(worktree.relative_path).name != config.project_id:
            _raise_validation(
                "project_mismatch",
                field="project_worktree.relative_path",
                message="project worktree terminal identity differs from project_id",
                logical_candidates=(worktree.relative_path, config.project_id),
                repair_route="make the project_worktree terminal segment equal project_id",
            )
        expected_namespace = f"projects/{config.project_id}"
        if config.branch_namespace != expected_namespace:
            _raise_validation(
                "project_mismatch",
                field="branch_namespace",
                message="branch namespace differs from project identity",
                logical_candidates=(config.branch_namespace, expected_namespace),
                repair_route=f"set branch_namespace to {expected_namespace}",
            )
        docs_path = PurePosixPath(docs.relative_path)
        process_path = PurePosixPath(process.relative_path)
        if _path_contains(docs_path, process_path) or _path_contains(process_path, docs_path):
            _raise_validation(
                "route_conflict",
                field="docs_relative/process_relative",
                message="docs and process targets must not overlap",
                logical_candidates=(docs.relative_path, process.relative_path),
                repair_route="use disjoint docs and process paths",
            )
        for field, leaf in (("docs_relative", docs_path), ("process_relative", process_path)):
            if not any(
                _path_contains(PurePosixPath(owned), leaf) for owned in config.owned_paths
            ):
                _raise_validation(
                    "target_not_owned",
                    field=field,
                    message="project target is not covered by owned_paths",
                    logical_candidates=(str(leaf), *config.owned_paths),
                    repair_route="add a non-overlapping owned path covering the target",
                )
    else:
        legacy_docs = _required_config_ref(config, "legacy_docs")
        legacy_process = _required_config_ref(config, "legacy_process")
        docs_path = PurePosixPath(legacy_docs.relative_path)
        process_path = PurePosixPath(legacy_process.relative_path)
        if _path_contains(docs_path, process_path) or _path_contains(process_path, docs_path):
            _raise_validation(
                "route_conflict",
                field="legacy_docs/legacy_process",
                message="legacy docs and process targets must not overlap",
                logical_candidates=(legacy_docs.relative_path, legacy_process.relative_path),
                repair_route="use disjoint legacy docs and process paths",
            )


def _normalize_config(config: ProjectArtifactConfig) -> ProjectArtifactConfig:
    _validate_project_id(config.project_id, field="project_id")
    if config.schema_version != SCHEMA_VERSION:
        _raise_validation(
            "schema_unsupported",
            field="schema_version",
            message="unsupported project artifact schema version",
            logical_candidates=(str(config.schema_version), str(SCHEMA_VERSION)),
            repair_route=f"use schema_version {SCHEMA_VERSION}",
        )
    if config.layout_version not in SUPPORTED_LAYOUTS:
        _raise_validation(
            "layout_unsupported",
            field="layout_version",
            message="layout version is missing or unsupported",
            logical_candidates=SUPPORTED_LAYOUTS,
            repair_route="select one explicit supported layout; do not infer it from path existence",
        )
    refs = {field: getattr(config, field) for field in _PATH_PARENT}
    _validate_anchor_graph(refs)
    owned_paths = (
        _normalize_owned_paths(config.owned_paths)
        if config.layout_version == PROJECT_FIRST_LAYOUT
        else tuple(sorted(_normalize_owned_path_items(config.owned_paths, required=False)))
    )
    normalized = ProjectArtifactConfig(
        schema_version=config.schema_version,
        project_id=config.project_id,
        layout_version=config.layout_version,
        artifact_control_root=_normalized_ref(config.artifact_control_root, "artifact_control_root"),  # type: ignore[arg-type]
        sibling_root=_normalized_ref(config.sibling_root, "sibling_root"),
        project_worktree=_normalized_ref(config.project_worktree, "project_worktree"),
        docs_relative=_normalized_ref(config.docs_relative, "docs_relative"),
        process_relative=_normalized_ref(config.process_relative, "process_relative"),
        legacy_docs=_normalized_ref(config.legacy_docs, "legacy_docs"),
        legacy_process=_normalized_ref(config.legacy_process, "legacy_process"),
        branch_namespace=config.branch_namespace,
        owned_paths=owned_paths,
    )
    _validate_leaf_contract(normalized)
    return normalized


def _resolve_under(parent: Path, ref: PathRef, *, field: str) -> Path:
    parent = parent.resolve(strict=False)
    candidate = (parent / ref.relative_path).resolve(strict=False)
    try:
        candidate.relative_to(parent)
    except ValueError:
        _raise_validation(
            "path_escape",
            field=f"{field}.relative_path",
            message="resolved path escapes its declared runtime anchor",
            logical_candidates=(f"{ref.anchor}:{ref.relative_path}",),
            repair_route="choose an anchor-relative path contained by its declared parent",
            declared_anchor=ref.anchor,
            expected_anchor=_PATH_PARENT[field],
        )
    return candidate


def _runtime_anchors(config: ProjectArtifactConfig, project_root: Path) -> dict[str, Path]:
    root = project_root.resolve(strict=False)
    control = _resolve_under(root, config.artifact_control_root, field="artifact_control_root")
    anchors = {"project_root": root, "artifact_control_root": control}
    if config.sibling_root is not None:
        sibling = _resolve_under(root, config.sibling_root, field="sibling_root")
        if _runtime_contains(control, sibling) or _runtime_contains(sibling, control):
            _raise_validation(
                "control_nested_worktree",
                field="artifact_control_root/sibling_root",
                message="artifact control root and sibling root must not contain one another",
                logical_candidates=(
                    f"project_root:{config.artifact_control_root.relative_path}",
                    f"project_root:{config.sibling_root.relative_path}",
                ),
                repair_route="configure disjoint control and sibling roots",
            )
        anchors["sibling_root"] = sibling
    if config.project_worktree is not None:
        sibling = anchors.get("sibling_root")
        if sibling is None:
            _raise_validation(
                "route_conflict",
                field="project_worktree",
                message="project worktree has no resolved sibling_root",
                repair_route="add a valid sibling_root",
            )
        worktree = _resolve_under(sibling, config.project_worktree, field="project_worktree")
        if _runtime_contains(control, worktree):
            _raise_validation(
                "control_nested_worktree",
                field="project_worktree",
                message="project worktree resolves inside artifact control root",
                logical_candidates=(f"sibling_root:{config.project_worktree.relative_path}",),
                repair_route="move the logical worktree route outside the control root",
            )
        anchors["project_worktree"] = worktree
    return anchors


def _runtime_contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def load_project_artifact_config(
    *,
    project_root: Path,
    requested_project_id: str,
    metadata_path: Path | None = None,
) -> ProjectArtifactConfig:
    """读取且只读取一个显式或默认 metadata 文件，并返回已验证配置。"""

    requested_project_id = _validate_project_id(requested_project_id, field="requested_project_id")
    project_root = project_root.resolve(strict=False)
    selected_path = metadata_path or project_root / "process" / ".meta-flow-process.yaml"
    if not selected_path.is_absolute():
        selected_path = project_root / selected_path
    selected_path = selected_path.resolve(strict=False)
    if not selected_path.is_file():
        _raise_validation(
            "config_missing",
            field="metadata_path",
            message="the selected route metadata file does not exist",
            logical_candidates=(str(metadata_path) if metadata_path is not None else "process/.meta-flow-process.yaml",),
            repair_route="provide one explicit metadata file or create the canonical project metadata",
        )
    try:
        payload = _parse_metadata(selected_path.read_bytes())
    except OSError as exc:
        _raise_validation(
            "route_conflict",
            field="metadata_path",
            message=f"selected route metadata cannot be read: {exc.__class__.__name__}",
            repair_route="restore read permission for the selected metadata file",
        )

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version != SCHEMA_VERSION:
        _raise_validation(
            "schema_unsupported",
            field="schema_version",
            message="schema_version is missing or unsupported",
            logical_candidates=(str(schema_version), str(SCHEMA_VERSION)),
            repair_route=f"set schema_version to {SCHEMA_VERSION}",
        )
    project_id = _validate_project_id(payload.get("project_id"), field="project_id")
    if project_id != requested_project_id:
        _raise_validation(
            "project_mismatch",
            field="project_id",
            message="metadata project identity differs from the requested project",
            logical_candidates=(project_id, requested_project_id),
            repair_route="select metadata owned by the requested project",
        )
    layout = payload.get("layout_version")
    if not isinstance(layout, str) or layout not in SUPPORTED_LAYOUTS:
        _raise_validation(
            "layout_unsupported",
            field="layout_version",
            message="layout_version is missing or unsupported",
            logical_candidates=SUPPORTED_LAYOUTS,
            repair_route="set one authoritative supported layout; never infer it from existing paths",
        )

    refs = {
        field: _raw_path_ref(
            payload,
            field,
            required=field == "artifact_control_root"
            or (layout == PROJECT_FIRST_LAYOUT and field in {"sibling_root", "project_worktree", "docs_relative", "process_relative"})
            or (layout == LEGACY_LAYOUT and field in {"legacy_docs", "legacy_process"}),
        )
        for field in _PATH_PARENT
    }
    _validate_anchor_graph(refs)
    config = ProjectArtifactConfig(
        schema_version=schema_version,
        project_id=project_id,
        layout_version=layout,
        artifact_control_root=refs["artifact_control_root"],  # type: ignore[arg-type]
        sibling_root=refs["sibling_root"],
        project_worktree=refs["project_worktree"],
        docs_relative=refs["docs_relative"],
        process_relative=refs["process_relative"],
        legacy_docs=refs["legacy_docs"],
        legacy_process=refs["legacy_process"],
        branch_namespace=str(payload.get("branch_namespace", "")),
        owned_paths=tuple(payload.get("owned_paths", ())) if isinstance(payload.get("owned_paths", ()), (list, tuple)) else (),
    )
    config = _normalize_config(config)
    _runtime_anchors(config, project_root)
    return config


def _path_ref_to_dict(ref: PathRef | None) -> dict[str, str] | None:
    if ref is None:
        return None
    return {"anchor": ref.anchor, "relative_path": ref.relative_path}


def project_artifact_config_to_dict(config: ProjectArtifactConfig) -> dict[str, object]:
    normalized = _normalize_config(config)
    return {
        "schema_version": normalized.schema_version,
        "project_id": normalized.project_id,
        "layout_version": normalized.layout_version,
        "artifact_control_root": _path_ref_to_dict(normalized.artifact_control_root),
        "sibling_root": _path_ref_to_dict(normalized.sibling_root),
        "project_worktree": _path_ref_to_dict(normalized.project_worktree),
        "docs_relative": _path_ref_to_dict(normalized.docs_relative),
        "process_relative": _path_ref_to_dict(normalized.process_relative),
        "legacy_docs": _path_ref_to_dict(normalized.legacy_docs),
        "legacy_process": _path_ref_to_dict(normalized.legacy_process),
        "branch_namespace": normalized.branch_namespace,
        "owned_paths": list(normalized.owned_paths),
    }


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_artifact_config_digest(config: ProjectArtifactConfig) -> str:
    return _canonical_digest(project_artifact_config_to_dict(config))


def _logical_target(target: RouteTarget) -> dict[str, object]:
    return {
        "kind": target.kind,
        "role": target.role,
        "canonical_ref": _path_ref_to_dict(target.canonical_ref),
        "read_only": target.read_only,
    }


def _decision_digest_payload(
    *,
    config_digest: str,
    project_id: str,
    layout_version: str,
    target_kind: str,
    intent: str,
    decision: str,
    read_targets: Sequence[RouteTarget],
    write_target: RouteTarget | None,
    error: RoutingError | None,
) -> dict[str, object]:
    return {
        "config_digest": config_digest,
        "project_id": project_id,
        "layout_version": layout_version,
        "target_kind": target_kind,
        "intent": intent,
        "decision": decision,
        "read_targets": [_logical_target(target) for target in read_targets],
        "write_target": _logical_target(write_target) if write_target else None,
        "error_code": error.code if error else None,
    }


def _blocked_decision(
    config: ProjectArtifactConfig,
    *,
    target_kind: str,
    intent: str,
    error: RoutingError,
    observed_at: str | None,
) -> RouteDecision:
    try:
        config_digest = project_artifact_config_digest(config)
    except RoutingValidationError:
        config_digest = _canonical_digest(
            {
                "schema_version": config.schema_version,
                "project_id": config.project_id,
                "layout_version": config.layout_version,
            }
        )
    digest_payload = _decision_digest_payload(
        config_digest=config_digest,
        project_id=config.project_id,
        layout_version=config.layout_version,
        target_kind=target_kind,
        intent=intent,
        decision="BLOCKED",
        read_targets=(),
        write_target=None,
        error=error,
    )
    return RouteDecision(
        schema_version=config.schema_version,
        project_id=config.project_id,
        layout_version=config.layout_version,
        target_kind=target_kind,
        intent=intent,
        decision="BLOCKED",
        read_targets=(),
        write_target=None,
        conflicts=error.logical_candidates,
        error=error,
        config_digest=config_digest,
        decision_digest=_canonical_digest(digest_payload),
        observed_at=observed_at or datetime.now(UTC).isoformat(timespec="seconds"),
    )


def resolve_project_artifact_route(
    config: ProjectArtifactConfig,
    *,
    project_root: Path,
    target_kind: ArtifactKind,
    intent: RouteIntent,
    observed_at: str | None = None,
) -> RouteDecision:
    """纯解析一个 artifact kind；预期冲突返回 BLOCKED value object。"""

    try:
        config = _normalize_config(config)
        if target_kind not in {"docs", "process"}:
            _raise_validation(
                "route_conflict",
                field="target_kind",
                message="target_kind must be docs or process",
                logical_candidates=(str(target_kind),),
                repair_route="select one supported artifact kind",
            )
        if intent not in {"read", "write"}:
            _raise_validation(
                "route_conflict",
                field="intent",
                message="route intent must be read or write",
                logical_candidates=(str(intent),),
                repair_route="select read or write explicitly",
            )
        anchors = _runtime_anchors(config, project_root)
        if config.layout_version == PROJECT_FIRST_LAYOUT:
            primary_ref = _required_config_ref(config, f"{target_kind}_relative")
            primary_parent = anchors["project_worktree"]
            primary = RouteTarget(
                kind=target_kind,
                role="primary",
                canonical_ref=primary_ref,
                runtime_path=_resolve_under(primary_parent, primary_ref, field=f"{target_kind}_relative"),
                read_only=False,
            )
            compatibility_ref = getattr(config, f"legacy_{target_kind}")
            read_targets: list[RouteTarget] = [primary]
            if compatibility_ref is not None:
                read_targets.append(
                    RouteTarget(
                        kind=target_kind,
                        role="compatibility",
                        canonical_ref=compatibility_ref,
                        runtime_path=_resolve_under(
                            anchors["artifact_control_root"],
                            compatibility_ref,
                            field=f"legacy_{target_kind}",
                        ),
                        read_only=True,
                    )
                )
            write_candidates = [primary]
        else:
            primary_ref = _required_config_ref(config, f"legacy_{target_kind}")
            primary = RouteTarget(
                kind=target_kind,
                role="primary",
                canonical_ref=primary_ref,
                runtime_path=_resolve_under(
                    anchors["artifact_control_root"],
                    primary_ref,
                    field=f"legacy_{target_kind}",
                ),
                read_only=False,
            )
            read_targets = [primary]
            write_candidates = [primary]
        if len(write_candidates) != 1:
            _raise_validation(
                "write_target_ambiguous",
                field="write_target",
                message="route did not produce exactly one authoritative write target",
                logical_candidates=tuple(
                    f"{target.canonical_ref.anchor}:{target.canonical_ref.relative_path}"
                    for target in write_candidates
                ),
                repair_route="select one explicit layout and remove ambiguous writable candidates",
            )
    except RoutingValidationError as exc:
        return _blocked_decision(
            config,
            target_kind=str(target_kind),
            intent=str(intent),
            error=exc.error,
            observed_at=observed_at,
        )

    config_digest = project_artifact_config_digest(config)
    write_target = write_candidates[0] if intent == "write" else None
    digest_payload = _decision_digest_payload(
        config_digest=config_digest,
        project_id=config.project_id,
        layout_version=config.layout_version,
        target_kind=target_kind,
        intent=intent,
        decision="PASS",
        read_targets=read_targets,
        write_target=write_target,
        error=None,
    )
    return RouteDecision(
        schema_version=config.schema_version,
        project_id=config.project_id,
        layout_version=config.layout_version,
        target_kind=target_kind,
        intent=intent,
        decision="PASS",
        read_targets=tuple(read_targets),
        write_target=write_target,
        conflicts=(),
        error=None,
        config_digest=config_digest,
        decision_digest=_canonical_digest(digest_payload),
        observed_at=observed_at or datetime.now(UTC).isoformat(timespec="seconds"),
    )


def assert_owned_target(
    decision: RouteDecision,
    *,
    candidate: Path,
    target_kind: ArtifactKind,
) -> OwnedTargetProof:
    """证明候选路径属于当前 decision 的唯一 owned write target。"""

    write_target = decision.write_target
    if (
        decision.decision != "PASS"
        or write_target is None
        or decision.target_kind != target_kind
        or write_target.kind != target_kind
        or not candidate.is_absolute()
    ):
        _raise_validation(
            "target_not_owned",
            field="candidate",
            message="candidate cannot be proved against a matching PASS write decision",
            logical_candidates=(str(candidate), str(decision.target_kind), str(target_kind)),
            repair_route="resolve a fresh write decision for the same project and artifact kind",
        )
    root = write_target.runtime_path.resolve(strict=False)
    resolved_candidate = candidate.resolve(strict=False)
    try:
        relative = resolved_candidate.relative_to(root)
    except ValueError:
        _raise_validation(
            "target_not_owned",
            field="candidate",
            message="candidate is outside the unique owned write target",
            logical_candidates=(
                str(candidate),
                f"{write_target.canonical_ref.anchor}:{write_target.canonical_ref.relative_path}",
            ),
            repair_route="use a candidate contained by the current project's authoritative write target",
        )
    target_digest = _canonical_digest(_logical_target(write_target))
    return OwnedTargetProof(
        project_id=decision.project_id,
        target_kind=target_kind,
        candidate_relative=relative.as_posix(),
        write_target_digest=target_digest,
        config_digest=decision.config_digest,
        decision_digest=decision.decision_digest,
    )


def _error_to_dict(error: RoutingError | None) -> dict[str, object] | None:
    if error is None:
        return None
    return {
        "code": error.code,
        "field": error.field,
        "message": error.message,
        "logical_candidates": list(error.logical_candidates),
        "repair_route": error.repair_route,
        "declared_anchor": error.declared_anchor,
        "expected_anchor": error.expected_anchor,
    }


def _target_to_dict(target: RouteTarget, *, include_runtime_paths: bool) -> dict[str, object]:
    payload = _logical_target(target)
    if include_runtime_paths:
        payload["runtime_path"] = str(target.runtime_path)
        payload["runtime_path_class"] = "noncanonical-observation"
    return payload


def route_decision_to_dict(
    decision: RouteDecision,
    *,
    include_runtime_paths: bool = False,
) -> dict[str, object]:
    """序列化 decision；默认仅输出跨设备可移植的 canonical 字段。"""

    return {
        "schema_version": decision.schema_version,
        "project_id": decision.project_id,
        "layout_version": decision.layout_version,
        "target_kind": decision.target_kind,
        "intent": decision.intent,
        "decision": decision.decision,
        "read_targets": [
            _target_to_dict(target, include_runtime_paths=include_runtime_paths)
            for target in decision.read_targets
        ],
        "write_target": (
            _target_to_dict(decision.write_target, include_runtime_paths=include_runtime_paths)
            if decision.write_target
            else None
        ),
        "conflicts": list(decision.conflicts),
        "error": _error_to_dict(decision.error),
        "config_digest": decision.config_digest,
        "decision_digest": decision.decision_digest,
    }
