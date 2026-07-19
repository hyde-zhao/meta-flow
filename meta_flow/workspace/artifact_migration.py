"""显式单项目、零 mutation 的 artifact migration 预检。

该模块只读取调用方显式给出的 source/target roots，并返回不可变的
``MigrationManifest``。它不会创建迁移脚本、修改文件或软链接，也不会调用
Git/worktree/ref/remote/helper/scheduler 能力。
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import stat
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath
from statistics import median
from typing import BinaryIO, Literal

from meta_flow.workspace.project_artifact_routing import RouteDecision
from meta_flow.workspace.project_worktree import UnknownValue, WorktreeHealth

ReadinessDecision = Literal["READY", "BLOCKED", "MANUAL_REVIEW"]

REQUIRED_MANIFEST_SECTIONS = (
    "identity",
    "scope",
    "mapping",
    "summary",
    "link_plan",
    "worktree_ref_readiness",
    "readiness",
    "validation",
    "rollback",
    "ops_follow_up",
    "evidence",
)


@dataclass(frozen=True)
class PortablePathRef:
    anchor: str
    relative_path: str


@dataclass(frozen=True)
class MigrationRoot:
    """一个显式 allowlisted source→target root；runtime path 不进入 manifest。"""

    source_anchor: str
    source_relative: str
    source_runtime_root: Path
    target_anchor: str
    target_relative: str
    target_runtime_root: Path


@dataclass(frozen=True)
class ExplicitMigrationProject:
    manifest_id: str
    project_id: str
    route_mode: str
    source_repository_id: str
    target_repository_id: str
    observed_at: str
    roots: tuple[MigrationRoot, ...]
    denied_paths: tuple[str, ...]
    input_refs: tuple[str, ...]


@dataclass(frozen=True)
class WeeklySyncCount:
    week_start: str
    sync_count: int


@dataclass(frozen=True)
class ManualSyncMetricsSummary:
    project_id: str
    weekly_sync_counts: tuple[WeeklySyncCount, ...]
    durations_seconds: tuple[float, ...]
    avoidable_scheduling_blockers: int
    total_scheduling_attempts: int
    window_complete: bool
    blocker_classification_complete: bool


@dataclass(frozen=True)
class ManifestIdentity:
    schema_version: str
    manifest_id: str
    project_id: str
    route_mode: str
    source_repository_id: str
    target_repository_id: str
    observed_at: str


@dataclass(frozen=True)
class ManifestScopeRoot:
    source: PortablePathRef
    target: PortablePathRef


@dataclass(frozen=True)
class ManifestScope:
    explicit_roots: tuple[ManifestScopeRoot, ...]
    allowed_read_paths: tuple[PortablePathRef, ...]
    denied_paths: tuple[str, ...]
    symlink_policy: str
    enumeration_complete: bool


@dataclass(frozen=True)
class MigrationMapping:
    source: PortablePathRef
    target: PortablePathRef
    object_type: str
    size_bytes: int
    content_hash: str | None
    link_target: str | None
    link_target_class: str | None
    target_state: str
    conflict: str | None
    readable: bool


@dataclass(frozen=True)
class MigrationSummary:
    file_count: int
    link_count: int
    directory_count: int
    total_bytes: int
    hash_algorithm: str
    missing_count: int
    unreadable_count: int
    conflicting_count: int


@dataclass(frozen=True)
class ManualPlanStep:
    step_id: str
    object_kind: str
    path: PortablePathRef
    proposed_action: str
    preconditions: tuple[str, ...]
    manual_authorization: str
    expected_post_state: str
    executed: bool = False


@dataclass(frozen=True)
class LinkPlan:
    steps: tuple[ManualPlanStep, ...]
    executed: bool = False


@dataclass(frozen=True)
class WorktreeRefReadiness:
    decision: str
    project_id: str
    proposed_integration_ref: str | None
    expected_oid: str | None
    worktree_role: str | None
    observation_digest: str | None
    fresh_health_required: bool
    executed: bool = False


@dataclass(frozen=True)
class ManifestReadiness:
    decision: ReadinessDecision
    reason_codes: tuple[str, ...]
    authorization_status: str


@dataclass(frozen=True)
class ValidationHandoff:
    checks: tuple[str, ...]
    owner: str
    executed: bool = False


@dataclass(frozen=True)
class RollbackHandoff:
    backup_requirements: tuple[str, ...]
    restore_triggers: tuple[str, ...]
    restore_checks: tuple[str, ...]
    owner: str
    executed: bool = False


@dataclass(frozen=True)
class ThresholdResult:
    threshold_id: str
    met: bool | None
    observed_value: str
    condition: str


@dataclass(frozen=True)
class FollowUpCandidate:
    candidate_id: str
    project_id: str
    reason_codes: tuple[str, ...]
    required_decisions: tuple[str, ...]
    executable: bool = False
    helper_enabled: bool = False
    scheduler_registered: bool = False
    remote_write_count: int = 0


@dataclass(frozen=True)
class OpsFollowUp:
    decision: Literal["none", "follow-up-candidate", "insufficient-data"]
    metrics_window_complete: bool
    blocker_classification_complete: bool
    thresholds: tuple[ThresholdResult, ...]
    candidate: FollowUpCandidate | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ReadError:
    code: str
    path: PortablePathRef
    operation: str


@dataclass(frozen=True)
class ManifestEvidence:
    input_refs: tuple[str, ...]
    read_errors: tuple[ReadError, ...]
    read_operation_count: int
    mutation_count: int
    command_count: int
    generated_at: str
    content_digest: str


@dataclass(frozen=True)
class MigrationManifest:
    identity: ManifestIdentity
    scope: ManifestScope
    mapping: tuple[MigrationMapping, ...]
    summary: MigrationSummary
    link_plan: LinkPlan
    worktree_ref_readiness: WorktreeRefReadiness
    readiness: ManifestReadiness
    validation: ValidationHandoff
    rollback: RollbackHandoff
    ops_follow_up: OpsFollowUp
    evidence: ManifestEvidence


@dataclass
class _ReadState:
    read_operations: int = 0
    read_errors: list[ReadError] | None = None
    reason_codes: list[str] | None = None

    def __post_init__(self) -> None:
        if self.read_errors is None:
            self.read_errors = []
        if self.reason_codes is None:
            self.reason_codes = []


def _lstat(path: Path) -> os.stat_result:
    """测试可观测的 allowlisted lstat 端口。"""

    return path.lstat()


def _scandir(path: Path) -> AbstractContextManager[os.ScandirIterator[str]]:
    """测试可观测的 allowlisted enumeration 端口。"""

    return os.scandir(path)


def _open_binary(path: Path) -> BinaryIO:
    """以 fail-closed no-follow 方式打开并确认普通文件。"""

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("no-follow file open is unsupported on this platform")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise OSError("opened object is not a regular file")
        return os.fdopen(descriptor, "rb", closefd=True)
    except BaseException:
        os.close(descriptor)
        raise


def _readlink(path: Path) -> str:
    """读取 link 文本但不跟随 link。"""

    return os.readlink(path)


def _plain(value: object) -> object:
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def migration_manifest_to_dict(manifest: MigrationManifest) -> dict[str, object]:
    """按固定 11 分区顺序输出 canonical、无 runtime path 的 payload。"""

    raw = {name: _plain(getattr(manifest, name)) for name in REQUIRED_MANIFEST_SECTIONS}
    return raw


def _canonical_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _portable_path(anchor: str, relative_path: str) -> PortablePathRef | None:
    if not anchor or not relative_path or "\x00" in relative_path or "\\" in relative_path:
        return None
    posix = PurePosixPath(relative_path)
    windows = PureWindowsPath(relative_path)
    parts = relative_path.split("/")
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or any(part in {"", ".", ".."} for part in parts)
        or str(posix) != relative_path
    ):
        return None
    return PortablePathRef(anchor=anchor, relative_path=relative_path)


def _join_relative(prefix: str, suffix: str) -> str:
    return prefix if not suffix else f"{prefix}/{suffix}"


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _contains(root: Path, candidate: Path) -> bool:
    root_text = os.fspath(_absolute_lexical(root))
    candidate_text = os.fspath(_absolute_lexical(candidate))
    try:
        return os.path.commonpath((root_text, candidate_text)) == root_text
    except ValueError:
        return False


def _roots_overlap(left: Path, right: Path) -> bool:
    return _contains(left, right) or _contains(right, left)


def _record_error(
    state: _ReadState,
    *,
    code: str,
    path: PortablePathRef,
    operation: str,
    reason: str,
) -> None:
    assert state.read_errors is not None
    assert state.reason_codes is not None
    state.read_errors.append(ReadError(code=code, path=path, operation=operation))
    state.reason_codes.append(reason)


def _safe_lstat(
    runtime_path: Path,
    portable_path: PortablePathRef,
    state: _ReadState,
) -> os.stat_result | None:
    state.read_operations += 1
    try:
        return _lstat(runtime_path)
    except FileNotFoundError:
        return None
    except PermissionError:
        _record_error(
            state,
            code="read-permission-denied",
            path=portable_path,
            operation="lstat",
            reason="unreadable-object",
        )
    except OSError:
        _record_error(
            state,
            code="lstat-failed",
            path=portable_path,
            operation="lstat",
            reason="unreadable-object",
        )
    return None


def _hash_file(
    runtime_path: Path,
    portable_path: PortablePathRef,
    state: _ReadState,
) -> str | None:
    state.read_operations += 1
    try:
        digest = hashlib.sha256()
        with _open_binary(runtime_path) as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    except PermissionError:
        _record_error(
            state,
            code="read-permission-denied",
            path=portable_path,
            operation="hash",
            reason="unreadable-object",
        )
    except OSError:
        _record_error(
            state,
            code="content-read-failed",
            path=portable_path,
            operation="hash",
            reason="unreadable-object",
        )
    return None


def _link_info(
    *,
    runtime_path: Path,
    root_runtime: Path,
    relative_path: str,
    portable_path: PortablePathRef,
    mapped_portable_path: PortablePathRef,
    denied_paths: tuple[str, ...],
    state: _ReadState,
) -> tuple[str | None, str, bool]:
    state.read_operations += 1
    try:
        target_text = _readlink(runtime_path)
    except PermissionError:
        _record_error(
            state,
            code="read-permission-denied",
            path=portable_path,
            operation="readlink",
            reason="unreadable-object",
        )
        return None, "unreadable", False
    except OSError:
        _record_error(
            state,
            code="readlink-failed",
            path=portable_path,
            operation="readlink",
            reason="unreadable-object",
        )
        return None, "unreadable", False

    assert state.reason_codes is not None
    windows = PureWindowsPath(target_text)
    if os.path.isabs(target_text) or windows.is_absolute() or bool(windows.drive):
        state.reason_codes.append("out-of-scope-symlink")
        return None, "absolute-out-of-scope", True
    if "\x00" in target_text or "\\" in target_text:
        state.reason_codes.append("out-of-scope-symlink")
        return None, "nonportable-out-of-scope", True
    parent = posixpath.dirname(relative_path)
    normalized = posixpath.normpath(posixpath.join(parent, target_text))
    if normalized == ".." or normalized.startswith("../"):
        state.reason_codes.append("out-of-scope-symlink")
        return target_text, "relative-out-of-scope", True

    target_runtime = root_runtime / Path(normalized)
    target_portable = PortablePathRef(
        anchor=portable_path.anchor,
        relative_path=_join_relative(
            portable_path.relative_path.removesuffix(relative_path).rstrip("/"),
            normalized,
        ),
    )
    mapped_target_portable = PortablePathRef(
        anchor=mapped_portable_path.anchor,
        relative_path=_join_relative(
            mapped_portable_path.relative_path.removesuffix(relative_path).rstrip("/"),
            normalized,
        ),
    )
    if any(
        _matches_denied_path(path.relative_path, denied_paths)
        for path in (target_portable, mapped_target_portable)
    ):
        state.reason_codes.extend(("denied-descendant", "denied-symlink-target"))
        return None, "relative-denied", True
    target_stat = _safe_lstat(target_runtime, target_portable, state)
    if target_stat is None:
        state.reason_codes.append("broken-symlink")
        return target_text, "relative-broken", True
    return target_text, "relative-in-scope", False


def _target_state(
    *,
    root: MigrationRoot,
    relative_path: str,
    object_type: str,
    content_hash: str | None,
    link_target: str | None,
    state: _ReadState,
) -> tuple[str, str | None]:
    runtime_path = root.target_runtime_root / Path(relative_path)
    portable_path = PortablePathRef(
        root.target_anchor,
        _join_relative(root.target_relative, relative_path),
    )
    target_stat = _safe_lstat(runtime_path, portable_path, state)
    if target_stat is None:
        if any(error.path == portable_path for error in state.read_errors or ()):
            return "unreadable", "target-unreadable"
        return "missing", None

    if object_type == "file" and stat.S_ISREG(target_stat.st_mode):
        target_hash = _hash_file(runtime_path, portable_path, state)
        if target_hash is None:
            return "unreadable", "target-unreadable"
        return (
            ("matching", None) if target_hash == content_hash else ("conflict", "content-mismatch")
        )
    if object_type == "directory" and stat.S_ISDIR(target_stat.st_mode):
        return "matching", None
    if object_type == "symlink" and stat.S_ISLNK(target_stat.st_mode):
        state.read_operations += 1
        try:
            target_link = _readlink(runtime_path)
        except OSError:
            _record_error(
                state,
                code="readlink-failed",
                path=portable_path,
                operation="readlink",
                reason="unreadable-object",
            )
            return "unreadable", "target-unreadable"
        if link_target is None:
            return "matching", None
        return (
            ("matching", None)
            if target_link == link_target
            else ("conflict", "link-target-mismatch")
        )
    return "conflict", "object-type-mismatch"


def _enumerate_root(
    root: MigrationRoot,
    denied_paths: tuple[str, ...],
    state: _ReadState,
) -> list[MigrationMapping]:
    mappings: list[MigrationMapping] = []

    def walk(current: Path, parent_relative: str) -> None:
        state.read_operations += 1
        try:
            with _scandir(current) as entries:
                names = sorted(entry.name for entry in entries)
        except PermissionError:
            _record_error(
                state,
                code="read-permission-denied",
                path=PortablePathRef(
                    root.source_anchor,
                    _join_relative(root.source_relative, parent_relative),
                ),
                operation="enumerate",
                reason="enumeration-incomplete",
            )
            return
        except OSError:
            _record_error(
                state,
                code="enumeration-failed",
                path=PortablePathRef(
                    root.source_anchor,
                    _join_relative(root.source_relative, parent_relative),
                ),
                operation="enumerate",
                reason="enumeration-incomplete",
            )
            return

        for name in names:
            runtime_path = current / name
            relative_path = name if not parent_relative else f"{parent_relative}/{name}"
            source_path = PortablePathRef(
                root.source_anchor,
                _join_relative(root.source_relative, relative_path),
            )
            target_path = PortablePathRef(
                root.target_anchor,
                _join_relative(root.target_relative, relative_path),
            )
            if _deny_descendant(source_path, target_path, denied_paths, state):
                continue
            source_stat = _safe_lstat(runtime_path, source_path, state)
            if source_stat is None:
                mappings.append(
                    MigrationMapping(
                        source=source_path,
                        target=target_path,
                        object_type="unknown",
                        size_bytes=0,
                        content_hash=None,
                        link_target=None,
                        link_target_class=None,
                        target_state="unknown",
                        conflict="source-unreadable",
                        readable=False,
                    )
                )
                continue

            if stat.S_ISDIR(source_stat.st_mode):
                object_type = "directory"
                content_hash = None
                link_target = None
                link_class = None
                readable = True
            elif stat.S_ISREG(source_stat.st_mode):
                object_type = "file"
                content_hash = _hash_file(runtime_path, source_path, state)
                link_target = None
                link_class = None
                readable = content_hash is not None
            elif stat.S_ISLNK(source_stat.st_mode):
                object_type = "symlink"
                link_target, link_class, ambiguous = _link_info(
                    runtime_path=runtime_path,
                    root_runtime=root.source_runtime_root,
                    relative_path=relative_path,
                    portable_path=source_path,
                    mapped_portable_path=target_path,
                    denied_paths=denied_paths,
                    state=state,
                )
                content_hash = None
                readable = link_class != "unreadable"
                if ambiguous:
                    assert state.reason_codes is not None
                    state.reason_codes.append("symlink-manual-review")
            else:
                object_type = "unsupported"
                content_hash = None
                link_target = None
                link_class = "unsupported-object"
                readable = False
                assert state.reason_codes is not None
                state.reason_codes.append("unsupported-object")

            target_state, conflict = _target_state(
                root=root,
                relative_path=relative_path,
                object_type=object_type,
                content_hash=content_hash,
                link_target=link_target,
                state=state,
            )
            mappings.append(
                MigrationMapping(
                    source=source_path,
                    target=target_path,
                    object_type=object_type,
                    size_bytes=source_stat.st_size if object_type == "file" else 0,
                    content_hash=content_hash,
                    link_target=link_target,
                    link_target_class=link_class,
                    target_state=target_state,
                    conflict=conflict,
                    readable=readable,
                )
            )
            if object_type == "directory":
                walk(runtime_path, relative_path)

    walk(root.source_runtime_root, "")
    return mappings


def _parse_week_start(value: str) -> date | None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.weekday() == 0 else None


def evaluate_manual_sync_follow_up(metrics: ManualSyncMetricsSummary) -> OpsFollowUp:
    """纯函数计算 O-AW-03；任何命中最多返回一个不可执行 candidate。"""

    sufficient = bool(
        metrics.window_complete
        and metrics.blocker_classification_complete
        and metrics.durations_seconds
        and metrics.total_scheduling_attempts > 0
        and metrics.avoidable_scheduling_blockers >= 0
        and metrics.avoidable_scheduling_blockers <= metrics.total_scheduling_attempts
        and all(item.sync_count >= 0 for item in metrics.weekly_sync_counts)
        and all(value >= 0 for value in metrics.durations_seconds)
    )
    if not sufficient:
        thresholds = tuple(
            ThresholdResult(identifier, None, "unavailable", condition)
            for identifier, condition in (
                ("O-AW-03-T1", ">=3 weekly syncs for 4 consecutive weeks"),
                ("O-AW-03-T2", "median duration >600 seconds"),
                ("O-AW-03-T3", "avoidable scheduling blocker rate >5%"),
            )
        )
        return OpsFollowUp(
            decision="insufficient-data",
            metrics_window_complete=metrics.window_complete,
            blocker_classification_complete=metrics.blocker_classification_complete,
            thresholds=thresholds,
            candidate=None,
            reason_codes=("metrics-insufficient-data",),
        )

    ordered_weeks = sorted(
        (
            parsed,
            item.sync_count,
        )
        for item in metrics.weekly_sync_counts
        if (parsed := _parse_week_start(item.week_start)) is not None
    )
    longest = 0
    current = 0
    previous: date | None = None
    for week_start, sync_count in ordered_weeks:
        consecutive = previous is not None and (week_start - previous).days == 7
        if sync_count >= 3:
            current = current + 1 if consecutive else 1
            longest = max(longest, current)
        else:
            current = 0
        previous = week_start
    t1 = longest >= 4
    duration_median = float(median(metrics.durations_seconds))
    t2 = duration_median > 600.0
    block_rate = metrics.avoidable_scheduling_blockers / metrics.total_scheduling_attempts
    t3 = block_rate > 0.05
    thresholds = (
        ThresholdResult(
            "O-AW-03-T1",
            t1,
            f"longest-consecutive-weeks={longest}",
            ">=3 weekly syncs for 4 consecutive weeks",
        ),
        ThresholdResult(
            "O-AW-03-T2",
            t2,
            f"median-seconds={duration_median:.6f}",
            "median duration >600 seconds",
        ),
        ThresholdResult(
            "O-AW-03-T3",
            t3,
            f"avoidable-rate={block_rate:.6f}",
            "avoidable scheduling blocker rate >5%",
        ),
    )
    reasons = tuple(item.threshold_id for item in thresholds if item.met)
    candidate = (
        FollowUpCandidate(
            candidate_id=f"conditional-sync-helper:{metrics.project_id}",
            project_id=metrics.project_id,
            reason_codes=reasons,
            required_decisions=(
                "scope",
                "security",
                "runtime_authorization",
                "rollback",
                "scheduler_policy",
            ),
        )
        if reasons
        else None
    )
    return OpsFollowUp(
        decision="follow-up-candidate" if candidate else "none",
        metrics_window_complete=True,
        blocker_classification_complete=True,
        thresholds=thresholds,
        candidate=candidate,
        reason_codes=reasons,
    )


def _identity_reasons(
    project: ExplicitMigrationProject,
    route: RouteDecision,
    health: WorktreeHealth,
    metrics: ManualSyncMetricsSummary,
) -> list[str]:
    reasons: list[str] = []
    if route.decision != "PASS":
        reasons.append("route-not-pass")
    if route.project_id != project.project_id:
        reasons.append("route-project-mismatch")
    if route.layout_version != project.route_mode:
        reasons.append("route-mode-mismatch")
    if health.project_id != project.project_id:
        reasons.append("worktree-project-mismatch")
    if health.decision != "HEALTHY":
        reasons.append("worktree-health-not-fresh")
    if health.active_operation_id is not None:
        reasons.append("worktree-operation-active")
    observation = health.observation
    if observation is None:
        reasons.append("worktree-observation-missing")
    elif (
        observation.identity.project_id != project.project_id
        or observation.route_config_digest != route.config_digest
    ):
        reasons.append("worktree-observation-mismatch")
    if metrics.project_id != project.project_id:
        reasons.append("metrics-project-mismatch")
    if not project.roots:
        reasons.append("scope-empty")
    if route.decision == "PASS":
        for root in project.roots:
            source_owned = any(
                target.canonical_ref.anchor == root.source_anchor
                and target.canonical_ref.relative_path == root.source_relative
                and _absolute_lexical(target.runtime_path)
                == _absolute_lexical(root.source_runtime_root)
                for target in route.read_targets
            )
            target_owned = any(
                target.canonical_ref.anchor == root.target_anchor
                and target.canonical_ref.relative_path == root.target_relative
                and _absolute_lexical(target.runtime_path)
                == _absolute_lexical(root.target_runtime_root)
                for target in route.read_targets
            )
            if not source_owned:
                reasons.append("route-source-scope-mismatch")
            if not target_owned:
                reasons.append("route-target-scope-mismatch")
    return reasons


def _portable_scope(
    project: ExplicitMigrationProject,
) -> tuple[tuple[ManifestScopeRoot, ...], list[str]]:
    scope_roots: list[ManifestScopeRoot] = []
    reasons: list[str] = []
    seen: set[tuple[str, str, str, str]] = set()
    for root in project.roots:
        source = _portable_path(root.source_anchor, root.source_relative)
        target = _portable_path(root.target_anchor, root.target_relative)
        if source is None or target is None:
            reasons.append("nonportable-scope")
            continue
        if any(
            _matches_denied_path(path.relative_path, project.denied_paths)
            for path in (source, target)
        ):
            reasons.append("denied-scope")
        key = (source.anchor, source.relative_path, target.anchor, target.relative_path)
        if key in seen:
            reasons.append("duplicate-scope")
            continue
        seen.add(key)
        if not root.source_runtime_root.is_absolute() or not root.target_runtime_root.is_absolute():
            reasons.append("runtime-root-not-absolute")
        if _roots_overlap(root.source_runtime_root, root.target_runtime_root):
            reasons.append("runtime-root-overlap")
        scope_roots.append(ManifestScopeRoot(source=source, target=target))
    return tuple(scope_roots), reasons


def _matches_denied_path(relative_path: str, patterns: tuple[str, ...]) -> bool:
    path = PurePosixPath(relative_path)
    for pattern in patterns:
        normalized = pattern.removesuffix("/**").removesuffix("/*").rstrip("/")
        if relative_path == normalized or relative_path.startswith(f"{normalized}/"):
            return True
        if path.match(pattern):
            return True
    return False


def _deny_descendant(
    source_path: PortablePathRef,
    target_path: PortablePathRef,
    denied_paths: tuple[str, ...],
    state: _ReadState,
) -> bool:
    """在任何 descendant filesystem probe 或 mapping 前应用 deny policy。"""

    source_denied = _matches_denied_path(source_path.relative_path, denied_paths)
    target_denied = _matches_denied_path(target_path.relative_path, denied_paths)
    if not source_denied and not target_denied:
        return False
    assert state.reason_codes is not None
    state.reason_codes.append("denied-descendant")
    if source_denied:
        state.reason_codes.append("denied-source-descendant")
    if target_denied:
        state.reason_codes.append("denied-target-descendant")
    return True


def _worktree_section(health: WorktreeHealth) -> WorktreeRefReadiness:
    observation = health.observation
    if observation is None:
        return WorktreeRefReadiness(
            decision=health.decision,
            project_id=health.project_id,
            proposed_integration_ref=None,
            expected_oid=None,
            worktree_role=None,
            observation_digest=health.observation_digest,
            fresh_health_required=True,
        )
    integration_ref = observation.identity.integration_ref
    integration_oid = observation.integration_oid
    role = observation.role
    return WorktreeRefReadiness(
        decision=health.decision,
        project_id=health.project_id,
        proposed_integration_ref=integration_ref,
        expected_oid=integration_oid if isinstance(integration_oid, str) else None,
        worktree_role=role
        if isinstance(role, str) and not isinstance(role, UnknownValue)
        else None,
        observation_digest=health.observation_digest,
        fresh_health_required=True,
    )


def _empty_manifest(
    project: ExplicitMigrationProject,
    health: WorktreeHealth,
    ops: OpsFollowUp,
    scope_roots: tuple[ManifestScopeRoot, ...],
    reasons: tuple[str, ...],
    state: _ReadState,
) -> MigrationManifest:
    return _assemble_manifest(
        project=project,
        health=health,
        ops=ops,
        scope_roots=scope_roots,
        mappings=(),
        reasons=reasons,
        state=state,
        decision="BLOCKED",
    )


def _assemble_manifest(
    *,
    project: ExplicitMigrationProject,
    health: WorktreeHealth,
    ops: OpsFollowUp,
    scope_roots: tuple[ManifestScopeRoot, ...],
    mappings: tuple[MigrationMapping, ...],
    reasons: tuple[str, ...],
    state: _ReadState,
    decision: ReadinessDecision,
) -> MigrationManifest:
    unreadable = sum(not item.readable or item.target_state == "unreadable" for item in mappings)
    summary = MigrationSummary(
        file_count=sum(item.object_type == "file" for item in mappings),
        link_count=sum(item.object_type == "symlink" for item in mappings),
        directory_count=sum(item.object_type == "directory" for item in mappings),
        total_bytes=sum(item.size_bytes for item in mappings if item.object_type == "file"),
        hash_algorithm="sha256",
        missing_count=sum(item.target_state == "missing" for item in mappings),
        unreadable_count=unreadable,
        conflicting_count=sum(item.target_state == "conflict" for item in mappings),
    )
    allowed_paths = tuple(item for root in scope_roots for item in (root.source, root.target))
    link_steps = tuple(
        ManualPlanStep(
            step_id=f"manual-link-{index + 1}",
            object_kind="symlink",
            path=root.source,
            proposed_action=f"link to {root.target.anchor}:{root.target.relative_path}",
            preconditions=(
                "fresh route/worktree health",
                "validated backup",
                "explicit runtime authorization",
            ),
            manual_authorization="REQUIRED_NOT_GRANTED",
            expected_post_state="source link resolves to project-owned target",
        )
        for index, root in enumerate(scope_roots)
    )
    identity = ManifestIdentity(
        schema_version="1",
        manifest_id=project.manifest_id,
        project_id=project.project_id,
        route_mode=project.route_mode,
        source_repository_id=project.source_repository_id,
        target_repository_id=project.target_repository_id,
        observed_at=project.observed_at,
    )
    manifest = MigrationManifest(
        identity=identity,
        scope=ManifestScope(
            explicit_roots=scope_roots,
            allowed_read_paths=allowed_paths,
            denied_paths=tuple(sorted(dict.fromkeys(project.denied_paths))),
            symlink_policy="lstat-no-follow-outside-explicit-root",
            enumeration_complete=not bool(state.read_errors)
            and not any(
                reason
                in {
                    "enumeration-incomplete",
                    "unreadable-object",
                    "broken-symlink",
                    "out-of-scope-symlink",
                    "unsupported-object",
                    "denied-descendant",
                }
                for reason in reasons
            ),
        ),
        mapping=mappings,
        summary=summary,
        link_plan=LinkPlan(steps=link_steps),
        worktree_ref_readiness=_worktree_section(health),
        readiness=ManifestReadiness(
            decision=decision,
            reason_codes=reasons,
            authorization_status="NOT_AUTHORIZED",
        ),
        validation=ValidationHandoff(
            checks=(
                "compare source/target canonical hash and count",
                "verify link text without following out-of-scope links",
                "re-read route and worktree health",
                "verify local and remote refs by exact OID under separate authorization",
                "append execution evidence to the gate ledger",
            ),
            owner="future-project-migration-operator",
        ),
        rollback=RollbackHandoff(
            backup_requirements=(
                "capture pre-migration file/link snapshot",
                "record exact route/worktree/ref observations",
            ),
            restore_triggers=(
                "hash/count mismatch",
                "link target mismatch",
                "route/worktree/ref verification failure",
            ),
            restore_checks=(
                "restore recorded file/link snapshot",
                "verify route/worktree identity and exact OIDs",
            ),
            owner="future-project-migration-operator",
        ),
        ops_follow_up=ops,
        evidence=ManifestEvidence(
            input_refs=tuple(sorted(dict.fromkeys(project.input_refs))),
            read_errors=tuple(state.read_errors or ()),
            read_operation_count=state.read_operations,
            mutation_count=0,
            command_count=0,
            generated_at=project.observed_at,
            content_digest="",
        ),
    )
    digest = _canonical_digest(migration_manifest_to_dict(manifest))
    return replace(manifest, evidence=replace(manifest.evidence, content_digest=digest))


def build_migration_manifest(
    explicit_project: ExplicitMigrationProject,
    route_decision: RouteDecision,
    worktree_health: WorktreeHealth,
    metrics_summary: ManualSyncMetricsSummary,
) -> MigrationManifest:
    """构建 11 分区只读 manifest；任何不确定性 fail closed。

    调用方必须传入一个显式项目和 fresh route/worktree value objects。本函数不会
    发现 sibling 项目，也不会调用 lifecycle、Git、helper、scheduler 或 remote。
    """

    state = _ReadState()
    ops = evaluate_manual_sync_follow_up(metrics_summary)
    scope_roots, scope_reasons = _portable_scope(explicit_project)
    reasons = _identity_reasons(
        explicit_project,
        route_decision,
        worktree_health,
        metrics_summary,
    )
    reasons.extend(scope_reasons)
    if reasons:
        return _empty_manifest(
            explicit_project,
            worktree_health,
            ops,
            scope_roots,
            tuple(dict.fromkeys(reasons)),
            state,
        )

    root_reasons: list[str] = []
    for root, portable in zip(explicit_project.roots, scope_roots, strict=True):
        source_stat = _safe_lstat(root.source_runtime_root, portable.source, state)
        target_stat = _safe_lstat(root.target_runtime_root, portable.target, state)
        if source_stat is None:
            root_reasons.append("source-root-missing")
        elif not stat.S_ISDIR(source_stat.st_mode):
            root_reasons.append("source-root-not-directory")
        if target_stat is None:
            root_reasons.append("target-root-missing")
        elif not stat.S_ISDIR(target_stat.st_mode):
            root_reasons.append("target-root-not-directory")
    if root_reasons or state.read_errors:
        root_reasons.extend(state.reason_codes or ())
        return _empty_manifest(
            explicit_project,
            worktree_health,
            ops,
            scope_roots,
            tuple(dict.fromkeys(root_reasons)),
            state,
        )

    mappings = tuple(
        sorted(
            (
                item
                for root in explicit_project.roots
                for item in _enumerate_root(root, explicit_project.denied_paths, state)
            ),
            key=lambda item: (
                item.source.anchor,
                item.source.relative_path,
                item.target.anchor,
                item.target.relative_path,
            ),
        )
    )
    post_reasons = list(state.reason_codes or ())
    if any(item.target_state == "missing" for item in mappings):
        post_reasons.extend(("missing-target", "manual-migration-required"))
    if any(item.target_state == "conflict" for item in mappings):
        post_reasons.append("mapping-conflict")
    if any(not item.readable or item.target_state == "unreadable" for item in mappings):
        post_reasons.append("unreadable-object")
    post_reasons = list(dict.fromkeys(post_reasons))
    decision: ReadinessDecision = "MANUAL_REVIEW" if post_reasons else "READY"
    return _assemble_manifest(
        project=explicit_project,
        health=worktree_health,
        ops=ops,
        scope_roots=scope_roots,
        mappings=mappings,
        reasons=tuple(post_reasons),
        state=state,
        decision=decision,
    )
