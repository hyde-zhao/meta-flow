"""只读、精确绑定的 legacy evidence 与 formal CR 分区 owner。

本模块只负责加载项目声明的 registry、构造不可变发现快照并解释分区结果。
它不写 registry/evidence，也不决定任何 lifecycle mutation；下游 consumer 必须
消费同一份快照，不能各自重新发现或重新解释 legacy 边界。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

from meta_flow.policies.gate_profiles import default_gate_profiles
from meta_flow.project.process_route import (
    ProcessRouteError,
    require_process_route,
)
from meta_flow.project.scale import load_yaml_object
from meta_flow.semantics.cr_status import validate_native_status_tuple
from meta_flow.workflow.cr_model import parse_frontmatter

SUPPORTED_SCHEMA_VERSION: Final = 1
EVIDENCE_KIND: Final = "legacy_closed_cr_evidence"
ALLOWED_OPERATIONS: Final = frozenset({"inspect_evidence", "list_follow_ups", "get_follow_up"})
SUPPORTED_LEGACY_OUTCOMES: Final = frozenset(
    {
        ("closed", "PASS_WITH_RISK"),
        ("closed-pass-with-risk", "PASS_WITH_RISK"),
    }
)
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_OUTCOME_FIELD_RE: Final = re.compile(
    r"(?mi)^\s*(?P<key>status|lifecycle|decision|outcome|lifecycle_status|readiness_status)"
    r"\s*:\s*(?P<value>[^#\r\n]+?)\s*$"
)
_FIELD_RE: Final = re.compile(
    r"(?m)^\s*(?P<key>id|status|relationship)\s*:\s*(?P<value>[^#\r\n]+?)\s*$"
)
_FOLLOW_UP_ID_RE: Final = re.compile(
    r"(?m)^\s*(?:-\s*)?id\s*:\s*(?P<id>[A-Za-z0-9][A-Za-z0-9._:-]*)\s*$"
)


class LegacyEvidenceError(ValueError):
    """携带稳定 failure taxonomy 的 fail-closed 错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class LegacyEvidenceRegistration:
    """调用方显式注入的一条 exact-bound registration。"""

    schema_version: int
    registration_id: str
    project_id: str
    consumer_id: str
    evidence_kind: str
    evidence_logical_ref: str
    evidence_sha256: str
    follow_up_logical_ref: str
    follow_up_sha256: str
    expected_lifecycle: str
    expected_decision: str
    expected_follow_up_count: int
    expected_follow_up_ids: tuple[str, ...]
    expected_follow_up_statuses: tuple[tuple[str, str], ...]
    allowed_operations: frozenset[str]


@dataclass(frozen=True)
class LegacyFollowUpView:
    """已作为完整 evidence 验证的一部分读取的单个 follow-up。"""

    follow_up_id: str
    status: str
    relationship: str
    source_logical_ref: str
    source_anchor: str


@dataclass(frozen=True)
class LegacyEvidenceView:
    """不可变、明确非 formal 的 verified sidecar view。"""

    source_kind: str
    compatibility_kind: str
    registration_id: str
    project_id: str
    consumer_id: str
    evidence_kind: str
    evidence_logical_ref: str
    evidence_sha256: str
    follow_up_logical_ref: str
    follow_up_sha256: str
    legacy_lifecycle: str
    legacy_decision: str
    lifecycle_view: str
    readiness_view: str
    gate_view: str
    follow_up_ids: tuple[str, ...]
    follow_ups: tuple[LegacyFollowUpView, ...]


@dataclass(frozen=True)
class DeclaredLegacyEvidenceRegistry:
    """由 Project 持久声明或兼容 Phase result_ref 显式声明的 registry。"""

    registry_logical_ref: str
    registry_sha256: str
    registrations: tuple[LegacyEvidenceRegistration, ...]
    evidence_paths: tuple[Path, ...]
    ownership_scope: str = "none"
    declaration_phase_ref: str = ""


@dataclass(frozen=True)
class LegacyRegistryEntryV1:
    """一个 canonical CR ID 到 exact legacy evidence ref 的冻结映射。"""

    cr_id: str
    evidence_logical_ref: str
    evidence_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "cr_id": self.cr_id,
            "evidence_logical_ref": self.evidence_logical_ref,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True)
class LegacyRegistrySnapshotV1:
    """不含物理路径的 registry identity；可安全绑定到 operation plan。"""

    registry_logical_ref: str
    registry_payload_digest: str
    entries: tuple[LegacyRegistryEntryV1, ...]
    registered_legacy_ids_digest: str
    excluded_paths_digest: str

    @property
    def registered_legacy_ids(self) -> tuple[str, ...]:
        return tuple(entry.cr_id for entry in self.entries)

    @property
    def excluded_legacy_refs(self) -> tuple[str, ...]:
        return tuple(entry.evidence_logical_ref for entry in self.entries)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "LegacyRegistrySnapshotV1",
            "registry_logical_ref": self.registry_logical_ref,
            "registry_payload_digest": self.registry_payload_digest,
            "entries": [entry.as_dict() for entry in self.entries],
            "registered_legacy_ids": list(self.registered_legacy_ids),
            "registered_legacy_ids_digest": self.registered_legacy_ids_digest,
            "excluded_legacy_refs": list(self.excluded_legacy_refs),
            "excluded_paths_digest": self.excluded_paths_digest,
        }


@dataclass(frozen=True)
class FormalCRDiscoverySnapshotV1:
    """一次有界扫描得到的 native/legacy/contamination 唯一分区。"""

    registry_logical_ref: str
    registry_payload_digest: str
    registered_legacy_ids: tuple[str, ...]
    registered_legacy_ids_digest: str
    excluded_legacy_refs: tuple[str, ...]
    excluded_paths_digest: str
    process_tree_manifest_digest: str
    native_formal_cr_refs: tuple[str, ...]
    registered_legacy_refs: tuple[str, ...]
    unregistered_contamination_refs: tuple[str, ...]
    overlap_conflicts: tuple[str, ...]
    snapshot_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "FormalCRDiscoverySnapshotV1",
            "registry_logical_ref": self.registry_logical_ref,
            "registry_payload_digest": self.registry_payload_digest,
            "registered_legacy_ids": list(self.registered_legacy_ids),
            "registered_legacy_ids_digest": self.registered_legacy_ids_digest,
            "excluded_legacy_refs": list(self.excluded_legacy_refs),
            "excluded_paths_digest": self.excluded_paths_digest,
            "process_tree_manifest_digest": self.process_tree_manifest_digest,
            "native_formal_cr_refs": list(self.native_formal_cr_refs),
            "registered_legacy_refs": list(self.registered_legacy_refs),
            "unregistered_contamination_refs": list(self.unregistered_contamination_refs),
            "overlap_conflicts": list(self.overlap_conflicts),
            "snapshot_digest": self.snapshot_digest,
        }


@dataclass(frozen=True)
class FormalCRPartitionReportV1:
    """只解释一份 snapshot 的 typed report；绝不重新扫描。"""

    decision: str
    snapshot_digest: str
    native_formal_cr_refs: tuple[str, ...]
    registered_legacy_ids: tuple[str, ...]
    registered_legacy_refs: tuple[str, ...]
    unregistered_contamination_refs: tuple[str, ...]
    overlap_conflicts: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "FormalCRPartitionReportV1",
            "decision": self.decision,
            "snapshot_digest": self.snapshot_digest,
            "native_formal_cr_refs": list(self.native_formal_cr_refs),
            "registered_legacy_ids": list(self.registered_legacy_ids),
            "registered_legacy_refs": list(self.registered_legacy_refs),
            "unregistered_contamination_refs": list(self.unregistered_contamination_refs),
            "overlap_conflicts": list(self.overlap_conflicts),
            "reason_codes": list(self.reason_codes),
            "evidence_refs": list(self.evidence_refs),
        }


ObjectOverrides = Mapping[str, tuple[Mapping[str, Any], bytes]]


def _load_declared_object(
    route: Any,
    logical_ref: str,
    object_overrides: ObjectOverrides | None,
) -> tuple[dict[str, Any], bytes]:
    if object_overrides is not None and logical_ref in object_overrides:
        payload, raw = object_overrides[logical_ref]
        return dict(payload), bytes(raw)
    path = route.resolve_ref(logical_ref)
    return load_yaml_object(path), path.read_bytes()


def _registry_refs_from_phase(phase: Mapping[str, Any]) -> tuple[str, ...]:
    result_refs = phase.get("result_refs")
    if result_refs is None:
        return ()
    if not isinstance(result_refs, list) or not all(isinstance(item, str) for item in result_refs):
        raise LegacyEvidenceError(
            "legacy_registry_invalid", "Phase result_refs must be a string list"
        )
    refs = tuple(
        _normalize_declared_ref(item)
        for item in result_refs
        if Path(item).name == "CONSUMER-ACCEPTANCE-SPEC.yaml"
    )
    if len(refs) > 1:
        raise LegacyEvidenceError(
            "legacy_registry_conflict",
            "a Phase must declare at most one consumer acceptance registry",
        )
    return refs


def validate_legacy_evidence_registry(
    registrations: Iterable[LegacyEvidenceRegistration],
) -> tuple[LegacyEvidenceRegistration, ...]:
    """验证显式 registry；同一 project/consumer/ref 绝不采用 last-wins。"""

    items = tuple(registrations)
    keys: set[tuple[str, str, str]] = set()
    registration_ids: set[str] = set()
    for registration in items:
        _validate_registration(registration)
        key = (
            registration.project_id,
            registration.consumer_id,
            registration.evidence_logical_ref,
        )
        if key in keys or registration.registration_id in registration_ids:
            raise LegacyEvidenceError(
                "legacy_registry_conflict",
                "legacy evidence registry contains a duplicate exact registration",
            )
        keys.add(key)
        registration_ids.add(registration.registration_id)
    return items


def load_declared_legacy_evidence_registry(
    project_root: Path,
    *,
    consumer_id: str,
    phase_ref: str | None = None,
    object_overrides: ObjectOverrides | None = None,
    route_override: Any | None = None,
) -> DeclaredLegacyEvidenceRegistry:
    """加载 Project 持久声明或兼容 Phase 声明的 legacy registry。

    Project 的 ``legacy_evidence_registry_ref`` 是长期 owner。旧项目缺少该字段时，
    只兼容读取指定 Phase（默认 active Phase）中一个精确命名的 result ref。
    不扫描目录、不匹配 wildcard，也不从 non-native CR 文件反向推断兼容资格。
    ``object_overrides`` 只用于原生事务的内存 post-state 视图。
    """

    if not isinstance(consumer_id, str) or not _SAFE_ID_RE.fullmatch(consumer_id):
        raise LegacyEvidenceError("legacy_registry_invalid", "consumer_id is invalid")
    try:
        route = route_override or require_process_route(project_root)
        project, _project_raw = _load_declared_object(
            route,
            "process/PROJECT.yaml",
            object_overrides,
        )
    except (OSError, ProcessRouteError, ValueError) as exc:
        raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
    if str(project.get("project_id") or "") != route.project_id:
        raise LegacyEvidenceError(
            "legacy_evidence_project_mismatch",
            "PROJECT project_id does not match route project_id",
        )
    project_registry_ref = _normalize_declared_ref(
        str(project.get("legacy_evidence_registry_ref") or "")
    )
    declared_phase_ref = _normalize_declared_ref(
        str(phase_ref if phase_ref is not None else project.get("active_phase_ref") or "")
    )
    registry_ref = project_registry_ref
    ownership_scope = "project" if project_registry_ref else "none"
    if not registry_ref and declared_phase_ref:
        try:
            phase, _phase_raw = _load_declared_object(
                route,
                declared_phase_ref,
                object_overrides,
            )
        except (OSError, ProcessRouteError, ValueError) as exc:
            raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
        if str(phase.get("project_id") or "") != route.project_id:
            raise LegacyEvidenceError(
                "legacy_evidence_project_mismatch",
                "declared Phase project_id does not match route project_id",
            )
        registry_refs = _registry_refs_from_phase(phase)
        if registry_refs:
            registry_ref = registry_refs[0]
            ownership_scope = "phase_compatibility"
    if not registry_ref:
        return DeclaredLegacyEvidenceRegistry(
            "",
            "",
            (),
            (),
            ownership_scope="none",
            declaration_phase_ref=declared_phase_ref,
        )
    try:
        registry, registry_raw = _load_declared_object(
            route,
            registry_ref,
            object_overrides,
        )
    except (OSError, ProcessRouteError, ValueError) as exc:
        raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
    registrations, evidence_paths = _registrations_from_consumer_spec(
        route=route,
        registry=registry,
        consumer_id=consumer_id,
    )
    return DeclaredLegacyEvidenceRegistry(
        registry_logical_ref=registry_ref,
        registry_sha256=sha256(registry_raw).hexdigest(),
        registrations=validate_legacy_evidence_registry(registrations),
        evidence_paths=tuple(evidence_paths),
        ownership_scope=ownership_scope,
        declaration_phase_ref=declared_phase_ref,
    )


def _registration_contract(
    registration: LegacyEvidenceRegistration,
) -> tuple[Any, ...]:
    """返回不含 registry-local ID 的长期兼容合同。"""

    return (
        registration.project_id,
        registration.evidence_kind,
        registration.evidence_logical_ref,
        registration.evidence_sha256,
        registration.follow_up_logical_ref,
        registration.follow_up_sha256,
        registration.expected_lifecycle,
        registration.expected_decision,
        registration.expected_follow_up_count,
        registration.expected_follow_up_ids,
        registration.expected_follow_up_statuses,
        registration.allowed_operations,
    )


def registered_legacy_cr_ids(
    bundle: DeclaredLegacyEvidenceRegistry,
) -> tuple[str, ...]:
    """按数值顺序返回 registry 中精确绑定的 legacy CR ID。"""

    ids: list[str] = []
    for registration in bundle.registrations:
        match = re.search(r"CR-\d+", registration.evidence_logical_ref)
        if match is not None:
            ids.append(match.group(0))
    return tuple(sorted(ids, key=lambda item: (int(item.split("-", 1)[1]), item)))


def _partition_digest(domain: str, payload: Any) -> str:
    encoded = json.dumps(
        {
            "schema_version": 1,
            "domain": domain,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _cr_id_from_ref(logical_ref: str) -> str:
    match = re.search(r"CR-\d+", Path(logical_ref).name)
    return match.group(0) if match is not None else ""


def load_legacy_registry_snapshot(
    project_root: Path,
    *,
    consumer_id: str = "formal-cr-discovery",
    registry_ref: str = "",
    phase_ref: str | None = None,
    object_overrides: ObjectOverrides | None = None,
    route_override: Any | None = None,
) -> LegacyRegistrySnapshotV1:
    """加载一次 project-declared registry 并冻结 exact ID/path identity。

    ``registry_ref`` 只用于要求调用方声明与 PROJECT 真相精确相等，不能用来
    覆盖或旁路 PROJECT。这样 CLI/consumer 无法各自选择不同 registry。
    """

    bundle = load_declared_legacy_evidence_registry(
        project_root,
        consumer_id=consumer_id,
        phase_ref=phase_ref,
        object_overrides=object_overrides,
        route_override=route_override,
    )
    expected_ref = _normalize_declared_ref(registry_ref)
    if expected_ref and expected_ref != bundle.registry_logical_ref:
        raise LegacyEvidenceError(
            "legacy_registry_ref_mismatch",
            "requested registry ref does not match the project-declared registry",
            details={
                "requested_registry_ref": expected_ref,
                "declared_registry_ref": bundle.registry_logical_ref,
            },
        )
    entries: list[LegacyRegistryEntryV1] = []
    ids: set[str] = set()
    refs: set[str] = set()
    for registration in bundle.registrations:
        cr_id = _cr_id_from_ref(registration.evidence_logical_ref)
        if not cr_id:
            raise LegacyEvidenceError(
                "legacy_registry_invalid",
                "registered legacy evidence ref has no canonical CR ID",
            )
        if cr_id in ids or registration.evidence_logical_ref in refs:
            raise LegacyEvidenceError(
                "legacy_registry_conflict",
                "legacy registry maps one CR ID or exact path more than once",
                details={
                    "cr_id": cr_id,
                    "evidence_logical_ref": registration.evidence_logical_ref,
                },
            )
        ids.add(cr_id)
        refs.add(registration.evidence_logical_ref)
        entries.append(
            LegacyRegistryEntryV1(
                cr_id=cr_id,
                evidence_logical_ref=registration.evidence_logical_ref,
                evidence_sha256=registration.evidence_sha256,
            )
        )
    entries.sort(key=lambda item: (int(item.cr_id.split("-", 1)[1]), item.evidence_logical_ref))
    id_values = [entry.cr_id for entry in entries]
    ref_values = sorted(entry.evidence_logical_ref for entry in entries)
    return LegacyRegistrySnapshotV1(
        registry_logical_ref=bundle.registry_logical_ref,
        registry_payload_digest=bundle.registry_sha256 or sha256(b"").hexdigest(),
        entries=tuple(entries),
        registered_legacy_ids_digest=_partition_digest(
            "formal-cr-registered-legacy-ids-v1", id_values
        ),
        excluded_paths_digest=_partition_digest("formal-cr-excluded-legacy-paths-v1", ref_values),
    )


def discover_formal_cr_snapshot(
    project_root: Path,
    registry: LegacyRegistrySnapshotV1,
    *,
    route_override: Any | None = None,
    read_context: Any | None = None,
) -> FormalCRDiscoverySnapshotV1:
    """扫描 formal CR 输入一次，并保留所有未登记 contamination。"""

    route = route_override or require_process_route(project_root)
    change_root = route.resolve_ref("process/changes")
    registered_by_ref = {entry.evidence_logical_ref: entry for entry in registry.entries}
    registered_by_id = {entry.cr_id: entry for entry in registry.entries}
    native_refs: list[str] = []
    native_ids: dict[str, str] = {}
    legacy_refs: list[str] = []
    contamination_refs: list[str] = []
    conflicts: list[str] = []
    manifest: list[dict[str, str]] = []

    candidates = sorted(change_root.glob("CR-*.md")) if change_root.is_dir() else []
    for path in candidates:
        if "FOLLOW-UP" in path.name:
            continue
        logical_ref = route.format_ref(path)
        raw = path.read_bytes() if read_context is None else read_context.read_bytes(logical_ref)
        manifest.append({"logical_ref": logical_ref, "payload_digest": sha256(raw).hexdigest()})
        fields = parse_frontmatter(raw.decode("utf-8"))
        filename_cr_id = _cr_id_from_ref(logical_ref)
        declared_cr_id = str(fields.get("cr_id") or "")
        gate_profile = str(fields.get("gate_profile") or "")
        tuple_errors = validate_native_status_tuple(
            str(fields.get("lifecycle_status") or ""),
            str(fields.get("readiness_status") or ""),
            str(fields.get("gate_status") or ""),
        )
        is_native = (
            str(fields.get("schema_version") or "") == "1"
            and str(fields.get("kind") or "") == "cr"
            and bool(filename_cr_id)
            and declared_cr_id == filename_cr_id
            and gate_profile in default_gate_profiles().get("profiles", {})
            and not tuple_errors
        )
        registered_entry = registered_by_ref.get(logical_ref)
        if registered_entry is not None:
            legacy_refs.append(logical_ref)
            if is_native:
                conflicts.append(f"registered_path_is_native:{logical_ref}")
            if filename_cr_id != registered_entry.cr_id:
                conflicts.append(
                    f"registered_path_id_mismatch:{registered_entry.cr_id}:{logical_ref}"
                )
            continue
        if not is_native:
            contamination_refs.append(logical_ref)
            continue
        if filename_cr_id in native_ids:
            conflicts.append(
                f"duplicate_native_cr_id:{filename_cr_id}:{native_ids[filename_cr_id]}:{logical_ref}"
            )
        native_ids[filename_cr_id] = logical_ref
        native_refs.append(logical_ref)

    for cr_id, native_ref in native_ids.items():
        registered_entry = registered_by_id.get(cr_id)
        if registered_entry is not None:
            conflicts.append(
                "native_legacy_id_overlap:"
                f"{cr_id}:{native_ref}:{registered_entry.evidence_logical_ref}"
            )
    missing_registered_refs = sorted(set(registered_by_ref) - set(legacy_refs))
    if missing_registered_refs:
        conflicts.extend(
            f"registered_path_missing_from_formal_tree:{ref}" for ref in missing_registered_refs
        )

    native_refs_tuple = tuple(sorted(native_refs))
    legacy_refs_tuple = tuple(sorted(legacy_refs))
    contamination_tuple = tuple(sorted(contamination_refs))
    conflicts_tuple = tuple(sorted(set(conflicts)))
    manifest_digest = _partition_digest("formal-cr-process-tree-manifest-v1", manifest)
    payload = {
        "registry_logical_ref": registry.registry_logical_ref,
        "registry_payload_digest": registry.registry_payload_digest,
        "registered_legacy_ids": list(registry.registered_legacy_ids),
        "registered_legacy_ids_digest": registry.registered_legacy_ids_digest,
        "excluded_legacy_refs": list(registry.excluded_legacy_refs),
        "excluded_paths_digest": registry.excluded_paths_digest,
        "process_tree_manifest_digest": manifest_digest,
        "native_formal_cr_refs": list(native_refs_tuple),
        "registered_legacy_refs": list(legacy_refs_tuple),
        "unregistered_contamination_refs": list(contamination_tuple),
        "overlap_conflicts": list(conflicts_tuple),
    }
    return FormalCRDiscoverySnapshotV1(
        registry_logical_ref=registry.registry_logical_ref,
        registry_payload_digest=registry.registry_payload_digest,
        registered_legacy_ids=registry.registered_legacy_ids,
        registered_legacy_ids_digest=registry.registered_legacy_ids_digest,
        excluded_legacy_refs=registry.excluded_legacy_refs,
        excluded_paths_digest=registry.excluded_paths_digest,
        process_tree_manifest_digest=manifest_digest,
        native_formal_cr_refs=native_refs_tuple,
        registered_legacy_refs=legacy_refs_tuple,
        unregistered_contamination_refs=contamination_tuple,
        overlap_conflicts=conflicts_tuple,
        snapshot_digest=_partition_digest("formal-cr-discovery-snapshot-v1", payload),
    )


def build_partition_report(
    snapshot: FormalCRDiscoverySnapshotV1,
) -> FormalCRPartitionReportV1:
    """解释 snapshot；此函数故意不接收 filesystem/project root。"""

    reasons: list[str] = []
    if snapshot.unregistered_contamination_refs:
        reasons.append("UNREGISTERED_NON_NATIVE_CR")
    if snapshot.overlap_conflicts:
        reasons.append("LEGACY_NATIVE_OVERLAP_OR_CONFLICT")
    if not reasons:
        reasons.append("FORMAL_CR_PARTITION_CONSISTENT")
    evidence = tuple(
        sorted(
            {
                ref
                for ref in (
                    snapshot.registry_logical_ref,
                    *snapshot.native_formal_cr_refs,
                    *snapshot.registered_legacy_refs,
                    *snapshot.unregistered_contamination_refs,
                )
                if ref
            }
        )
    )
    return FormalCRPartitionReportV1(
        decision=(
            "BLOCKED"
            if snapshot.unregistered_contamination_refs or snapshot.overlap_conflicts
            else "PASS"
        ),
        snapshot_digest=snapshot.snapshot_digest,
        native_formal_cr_refs=snapshot.native_formal_cr_refs,
        registered_legacy_ids=snapshot.registered_legacy_ids,
        registered_legacy_refs=snapshot.registered_legacy_refs,
        unregistered_contamination_refs=snapshot.unregistered_contamination_refs,
        overlap_conflicts=snapshot.overlap_conflicts,
        reason_codes=tuple(reasons),
        evidence_refs=evidence,
    )


def load_formal_cr_partition(
    project_root: Path,
    *,
    consumer_id: str,
    registry_ref: str = "",
    phase_ref: str | None = None,
    object_overrides: ObjectOverrides | None = None,
    route_override: Any | None = None,
    read_context: Any | None = None,
) -> tuple[
    LegacyRegistrySnapshotV1,
    FormalCRDiscoverySnapshotV1,
    FormalCRPartitionReportV1,
]:
    """一次加载、一次扫描，返回所有 authoritative consumer 的共享输入。"""

    project_root = project_root.resolve()
    effective_route = route_override or require_process_route(project_root)
    project_path = effective_route.resolve_ref("process/PROJECT.yaml")
    if project_path.is_file():
        registry = load_legacy_registry_snapshot(
            project_root,
            consumer_id=consumer_id,
            registry_ref=registry_ref,
            phase_ref=phase_ref,
            object_overrides=object_overrides,
            route_override=effective_route,
        )
    else:
        registry = LegacyRegistrySnapshotV1(
            registry_logical_ref="",
            registry_payload_digest=sha256(b"").hexdigest(),
            entries=(),
            registered_legacy_ids_digest=_partition_digest(
                "formal-cr-registered-legacy-ids-v1", []
            ),
            excluded_paths_digest=_partition_digest("formal-cr-excluded-legacy-paths-v1", []),
        )
    snapshot = discover_formal_cr_snapshot(
        project_root,
        registry,
        route_override=effective_route,
        read_context=read_context,
    )
    return registry, snapshot, build_partition_report(snapshot)


def snapshot_excluded_legacy_paths(
    project_root: Path,
    snapshot: FormalCRDiscoverySnapshotV1,
    *,
    route_override: Any | None = None,
) -> frozenset[Path]:
    """在 consumer 边界把 canonical refs 转回当前 route 的 exact paths。"""

    route = route_override or require_process_route(project_root)
    return frozenset(
        route.resolve_ref(logical_ref).resolve() for logical_ref in snapshot.excluded_legacy_refs
    )


def validate_legacy_evidence_registry_continuity(
    source: DeclaredLegacyEvidenceRegistry,
    target: DeclaredLegacyEvidenceRegistry,
) -> dict[str, Any]:
    """证明 target 完整继承 source 的仍有效 legacy registration。"""

    source_contracts = {
        registration.evidence_logical_ref: _registration_contract(registration)
        for registration in source.registrations
    }
    target_contracts = {
        registration.evidence_logical_ref: _registration_contract(registration)
        for registration in target.registrations
    }
    lost_refs = sorted(
        ref for ref, contract in source_contracts.items() if target_contracts.get(ref) != contract
    )
    if (
        source.registry_logical_ref
        and source.registry_logical_ref == target.registry_logical_ref
        and source.registry_sha256 != target.registry_sha256
    ):
        lost_refs = sorted(set(lost_refs) | set(source_contracts))
    if lost_refs:
        lost_ids = sorted(
            {
                match.group(0)
                for ref in lost_refs
                if (match := re.search(r"CR-\d+", ref)) is not None
            },
            key=lambda item: (int(item.split("-", 1)[1]), item),
        )
        details = {
            "lost_registration_ids": lost_ids,
            "source_registry_ref": source.registry_logical_ref,
            "target_registry_ref": target.registry_logical_ref,
            "source_registry_sha256": source.registry_sha256,
            "target_registry_sha256": target.registry_sha256,
        }
        raise LegacyEvidenceError(
            "legacy_evidence_registry_continuity_lost",
            "legacy evidence registry continuity lost for "
            + (", ".join(lost_ids) if lost_ids else ", ".join(lost_refs))
            + f"; source={source.registry_logical_ref or 'none'}"
            + f"; target={target.registry_logical_ref or 'none'}",
            details=details,
        )
    return {
        "decision": "PASS",
        "source_registry_ref": source.registry_logical_ref,
        "target_registry_ref": target.registry_logical_ref,
        "registered_ids": list(registered_legacy_cr_ids(target)),
        "registry_digest": target.registry_sha256,
        "ownership_scope": target.ownership_scope,
    }


def query_declared_legacy_evidence(
    project_root: Path,
    *,
    query_id: str,
) -> dict[str, Any]:
    """按 exact CR/follow-up ID 查询已声明的 legacy sidecar lane。"""

    if not isinstance(query_id, str) or not _SAFE_ID_RE.fullmatch(query_id):
        raise LegacyEvidenceError("legacy_evidence_query_invalid", "query ID is invalid")
    bundle = load_declared_legacy_evidence_registry(
        project_root,
        consumer_id="cr-query",
    )
    for registration in bundle.registrations:
        cr_match = re.search(r"CR-\d+", registration.evidence_logical_ref)
        cr_id = cr_match.group(0) if cr_match else ""
        if query_id != cr_id and query_id not in registration.expected_follow_up_ids:
            continue
        view = inspect_registered_legacy_evidence(
            project_root,
            registration=registration,
            consumer_id="cr-query",
        )
        base = {
            "schema_version": 1,
            "decision": "PASS",
            "classification": "immutable_legacy_closed_evidence",
            "source_kind": view.source_kind,
            "compatibility_kind": view.compatibility_kind,
            "project_id": view.project_id,
            "query_id": query_id,
            "registry_ref": bundle.registry_logical_ref,
            "registry_sha256": bundle.registry_sha256,
            "evidence_ref": view.evidence_logical_ref,
            "evidence_sha256": view.evidence_sha256,
            "legacy_lifecycle": view.legacy_lifecycle,
            "legacy_decision": view.legacy_decision,
            "native_lifecycle_event_count": 0,
            "mutation_count": 0,
        }
        if query_id == cr_id:
            return {
                **base,
                "follow_up_ref": view.follow_up_logical_ref,
                "follow_up_sha256": view.follow_up_sha256,
                "follow_up_ids": list(view.follow_up_ids),
            }
        follow_up = get_registered_follow_up(view, follow_up_id=query_id)
        return {
            **base,
            "follow_up_ref": follow_up.source_logical_ref,
            "follow_up_sha256": view.follow_up_sha256,
            "follow_up_status": follow_up.status,
            "follow_up_relationship": follow_up.relationship,
            "source_anchor": follow_up.source_anchor,
        }
    raise LegacyEvidenceError(
        "legacy_evidence_not_registered",
        "query ID is not present in the declared exact registry",
    )


def _normalize_declared_ref(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    logical_ref = raw if raw.startswith("process/") else f"process/{raw}"
    _validate_logical_ref(logical_ref)
    return logical_ref


def _registrations_from_consumer_spec(
    *,
    route: Any,
    registry: dict[str, Any],
    consumer_id: str,
) -> tuple[list[LegacyEvidenceRegistration], list[Path]]:
    if (
        registry.get("schema_version") != 1
        or str(registry.get("project_id") or "") != route.project_id
        or str(registry.get("spec_status") or "") != "ready-for-provider-delivery"
    ):
        raise LegacyEvidenceError(
            "legacy_registry_invalid",
            "consumer acceptance registry identity or readiness is invalid",
        )
    spec_id = str(registry.get("spec_id") or "")
    if not _SAFE_ID_RE.fullmatch(spec_id):
        raise LegacyEvidenceError("legacy_registry_invalid", "registry spec_id is invalid")
    raw_inputs = registry.get("immutable_consumer_inputs")
    raw_fixtures = registry.get("fixture_contract")
    if not isinstance(raw_inputs, list) or not isinstance(raw_fixtures, list):
        raise LegacyEvidenceError(
            "legacy_registry_invalid",
            "registry immutable inputs and fixture contract must be lists",
        )
    inputs: dict[str, dict[str, Any]] = {}
    for item in raw_inputs:
        if not isinstance(item, dict):
            raise LegacyEvidenceError(
                "legacy_registry_invalid", "registry immutable input must be an object"
            )
        item_id = str(item.get("id") or "")
        if not _SAFE_ID_RE.fullmatch(item_id) or item_id in inputs:
            raise LegacyEvidenceError(
                "legacy_registry_conflict", "registry immutable input ID is invalid or duplicate"
            )
        inputs[item_id] = item
    follow_up_expectations: dict[str, dict[str, str]] = {}
    for fixture in raw_fixtures:
        if not isinstance(fixture, dict):
            continue
        source_id = str(fixture.get("source") or "")
        expected = fixture.get("expected")
        if not source_id or not isinstance(expected, dict):
            continue
        if source_id in follow_up_expectations:
            raise LegacyEvidenceError(
                "legacy_registry_conflict", "follow-up fixture source is declared more than once"
            )
        follow_up_expectations[source_id] = {
            str(item_id): str(status) for item_id, status in expected.items()
        }

    registrations: list[LegacyEvidenceRegistration] = []
    evidence_paths: list[Path] = []
    for body_id, body in inputs.items():
        match = re.fullmatch(r"(?P<compact>CR(?P<number>\d+))-BODY", body_id)
        if match is None:
            continue
        compact = match.group("compact")
        cr_id = f"CR-{match.group('number')}"
        follow_up_id = f"{compact}-FOLLOW-UPS"
        follow_up = inputs.get(follow_up_id)
        expected_statuses = follow_up_expectations.get(follow_up_id)
        if follow_up is None or not expected_statuses:
            raise LegacyEvidenceError(
                "legacy_registry_invalid",
                f"{body_id} lacks an exact follow-up input and status fixture",
            )
        evidence_ref = _normalize_declared_ref(str(body.get("ref") or ""))
        follow_up_ref = _normalize_declared_ref(str(follow_up.get("ref") or ""))
        if (
            not evidence_ref.startswith(f"process/changes/{cr_id}")
            or follow_up_ref != f"process/works/{cr_id}/FOLLOW-UPS.yaml"
        ):
            raise LegacyEvidenceError(
                "legacy_registry_invalid", "legacy evidence refs do not match their exact CR ID"
            )
        evidence_digest = str(body.get("sha256") or "")
        follow_up_digest = str(follow_up.get("sha256") or "")
        if not _SHA256_RE.fullmatch(evidence_digest) or not _SHA256_RE.fullmatch(follow_up_digest):
            raise LegacyEvidenceError(
                "legacy_registry_invalid", "legacy evidence digests must be lowercase SHA-256"
            )
        try:
            evidence_path = route.resolve_ref(evidence_ref)
            follow_up_path = route.resolve_ref(follow_up_ref)
            evidence_raw = evidence_path.read_bytes()
            follow_up_raw = follow_up_path.read_bytes()
        except (OSError, ProcessRouteError) as exc:
            raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
        if (
            sha256(evidence_raw).hexdigest() != evidence_digest
            or sha256(follow_up_raw).hexdigest() != follow_up_digest
        ):
            raise LegacyEvidenceError(
                "legacy_evidence_digest_mismatch",
                "declared legacy evidence does not match the registry digest",
            )
        lifecycle, decision = _parse_legacy_outcome(evidence_raw)
        parsed_follow_ups = _parse_follow_ups(follow_up_raw, follow_up_ref)
        parsed_statuses = {item.follow_up_id: item.status for item in parsed_follow_ups}
        if parsed_statuses != expected_statuses:
            raise LegacyEvidenceError(
                "legacy_follow_up_query_failed",
                "follow-up IDs or statuses do not match the declared fixture",
            )
        registrations.append(
            LegacyEvidenceRegistration(
                schema_version=1,
                registration_id=f"{spec_id}-{compact.lower()}",
                project_id=route.project_id,
                consumer_id=consumer_id,
                evidence_kind=EVIDENCE_KIND,
                evidence_logical_ref=evidence_ref,
                evidence_sha256=evidence_digest,
                follow_up_logical_ref=follow_up_ref,
                follow_up_sha256=follow_up_digest,
                expected_lifecycle=lifecycle,
                expected_decision=decision,
                expected_follow_up_count=len(expected_statuses),
                expected_follow_up_ids=tuple(expected_statuses),
                expected_follow_up_statuses=tuple(expected_statuses.items()),
                allowed_operations=ALLOWED_OPERATIONS,
            )
        )
        evidence_paths.append(evidence_path.resolve())
    return registrations, evidence_paths


def inspect_registered_legacy_evidence(
    project_root: Path,
    *,
    registration: LegacyEvidenceRegistration,
    consumer_id: str,
) -> LegacyEvidenceView:
    """验证两份 raw source 后返回完整 immutable sidecar view。

    所有身份、operation 与 logical-ref 检查均发生在 route 或 target I/O 之前；
    两份 digest 都匹配之前不会调用任一 parser。
    """

    if registration is None:
        raise LegacyEvidenceError("legacy_evidence_not_registered", "registration is required")
    _validate_registration(registration)
    if consumer_id != registration.consumer_id:
        raise LegacyEvidenceError(
            "legacy_evidence_consumer_mismatch", "consumer_id does not match registration"
        )
    for operation in ("inspect_evidence", "list_follow_ups", "get_follow_up"):
        _require_operation(registration, operation)

    try:
        route = require_process_route(project_root)
    except ProcessRouteError as exc:
        raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
    except Exception as exc:  # pragma: no cover - harness boundary
        raise LegacyEvidenceError("CHECK_HARNESS_ERROR", str(exc)) from exc

    if route.project_id != registration.project_id:
        raise LegacyEvidenceError(
            "legacy_evidence_project_mismatch", "route project_id does not match registration"
        )

    try:
        evidence_path = route.resolve_ref(registration.evidence_logical_ref)
        follow_up_path = route.resolve_ref(registration.follow_up_logical_ref)
    except ProcessRouteError as exc:
        raise LegacyEvidenceError("legacy_evidence_ref_invalid", str(exc)) from exc
    except Exception as exc:  # pragma: no cover - resolver harness boundary
        raise LegacyEvidenceError("CHECK_HARNESS_ERROR", str(exc)) from exc

    try:
        evidence_raw = evidence_path.read_bytes()
        follow_up_raw = follow_up_path.read_bytes()
    except OSError as exc:
        raise LegacyEvidenceError("legacy_evidence_route_unavailable", str(exc)) from exc
    except Exception as exc:  # pragma: no cover - unexpected read boundary
        raise LegacyEvidenceError("CHECK_HARNESS_ERROR", str(exc)) from exc

    if sha256(evidence_raw).hexdigest() != registration.evidence_sha256:
        raise LegacyEvidenceError(
            "legacy_evidence_digest_mismatch", "evidence raw bytes do not match registration digest"
        )
    if sha256(follow_up_raw).hexdigest() != registration.follow_up_sha256:
        raise LegacyEvidenceError(
            "legacy_evidence_digest_mismatch",
            "follow-up raw bytes do not match registration digest",
        )

    lifecycle, decision = _parse_legacy_outcome(evidence_raw)
    if lifecycle != registration.expected_lifecycle or decision != registration.expected_decision:
        raise LegacyEvidenceError(
            "legacy_evidence_outcome_mismatch", "legacy outcome does not match registration"
        )
    follow_ups = _parse_follow_ups(follow_up_raw, registration.follow_up_logical_ref)
    _validate_follow_ups(registration, follow_ups)

    return LegacyEvidenceView(
        source_kind="registered_legacy_evidence",
        compatibility_kind="registered_legacy_closed_evidence",
        registration_id=registration.registration_id,
        project_id=registration.project_id,
        consumer_id=registration.consumer_id,
        evidence_kind=registration.evidence_kind,
        evidence_logical_ref=registration.evidence_logical_ref,
        evidence_sha256=registration.evidence_sha256,
        follow_up_logical_ref=registration.follow_up_logical_ref,
        follow_up_sha256=registration.follow_up_sha256,
        legacy_lifecycle=lifecycle,
        legacy_decision=decision,
        lifecycle_view="closed",
        readiness_view="ready_with_risk",
        gate_view="closed",
        follow_up_ids=registration.expected_follow_up_ids,
        follow_ups=follow_ups,
    )


def list_registered_follow_ups(
    verified: LegacyEvidenceView,
) -> tuple[LegacyFollowUpView, ...]:
    """返回已整体验证的完整 follow-up 集合，绝不在这里重新读取 target。"""

    _validate_verified_view(verified)
    return verified.follow_ups


def get_registered_follow_up(
    verified: LegacyEvidenceView, *, follow_up_id: str
) -> LegacyFollowUpView:
    """仅以 exact ID 查询已验证集合；不作大小写、前缀或模糊匹配。"""

    _validate_verified_view(verified)
    for follow_up in verified.follow_ups:
        if follow_up.follow_up_id == follow_up_id:
            return follow_up
    raise LegacyEvidenceError("follow_up_not_found", "follow-up ID is not present in verified view")


def convert_to_formal_cr(_: LegacyEvidenceView) -> None:
    """明确拒绝把 sidecar view 转换为 native formal object。"""

    raise LegacyEvidenceError(
        "legacy_evidence_formal_conversion_unsupported",
        "registered legacy evidence cannot be converted to FormalCR or an index item",
    )


def _validate_registration(registration: LegacyEvidenceRegistration) -> None:
    if not isinstance(registration, LegacyEvidenceRegistration):
        raise LegacyEvidenceError("legacy_registry_invalid", "registration has an unsupported type")
    if registration.schema_version != SUPPORTED_SCHEMA_VERSION:
        raise LegacyEvidenceError(
            "legacy_registry_invalid", "unsupported registration schema_version"
        )
    if (
        isinstance(registration.expected_follow_up_count, bool)
        or not isinstance(registration.expected_follow_up_count, int)
        or not isinstance(registration.expected_follow_up_ids, tuple)
        or not isinstance(registration.expected_follow_up_statuses, tuple)
        or not isinstance(registration.allowed_operations, frozenset)
    ):
        raise LegacyEvidenceError(
            "legacy_registry_invalid", "registration immutable field types are invalid"
        )
    if not all(
        isinstance(value, str) and _SAFE_ID_RE.fullmatch(value)
        for value in (
            registration.registration_id,
            registration.project_id,
            registration.consumer_id,
        )
    ):
        raise LegacyEvidenceError(
            "legacy_registry_invalid", "registration identity fields are invalid"
        )
    if registration.evidence_kind != EVIDENCE_KIND:
        raise LegacyEvidenceError("legacy_registry_invalid", "unsupported evidence_kind")
    _validate_logical_ref(registration.evidence_logical_ref)
    _validate_logical_ref(registration.follow_up_logical_ref)
    if not _SHA256_RE.fullmatch(registration.evidence_sha256) or not _SHA256_RE.fullmatch(
        registration.follow_up_sha256
    ):
        raise LegacyEvidenceError(
            "legacy_registry_invalid", "SHA-256 digests must be lowercase hex"
        )
    if (
        registration.expected_lifecycle,
        registration.expected_decision,
    ) not in SUPPORTED_LEGACY_OUTCOMES:
        raise LegacyEvidenceError("legacy_registry_invalid", "unsupported expected legacy outcome")
    if (
        registration.expected_follow_up_count < 0
        or registration.expected_follow_up_count != len(registration.expected_follow_up_ids)
        or registration.expected_follow_up_count != len(registration.expected_follow_up_statuses)
        or len(set(registration.expected_follow_up_ids)) != len(registration.expected_follow_up_ids)
        or not all(
            isinstance(item, str) and _SAFE_ID_RE.fullmatch(item)
            for item in registration.expected_follow_up_ids
        )
        or tuple(item_id for item_id, _status in registration.expected_follow_up_statuses)
        != registration.expected_follow_up_ids
        or not all(
            isinstance(status, str) and bool(status)
            for _item_id, status in registration.expected_follow_up_statuses
        )
    ):
        raise LegacyEvidenceError(
            "legacy_registry_invalid", "follow-up count and IDs are not exact"
        )
    if (
        not registration.allowed_operations
        or not all(isinstance(item, str) for item in registration.allowed_operations)
        or not registration.allowed_operations <= ALLOWED_OPERATIONS
    ):
        raise LegacyEvidenceError(
            "legacy_registry_invalid", "registration operation allowlist is invalid"
        )


def _validate_logical_ref(logical_ref: str) -> None:
    parts = logical_ref.split("/") if isinstance(logical_ref, str) else []
    if (
        len(parts) < 2
        or parts[0] != "process"
        or any(part in {"", ".", ".."} for part in parts)
        or any(character in logical_ref for character in ("\\", "*", "?", "[", "]", ":", "\x00"))
        or logical_ref.startswith("/")
    ):
        raise LegacyEvidenceError(
            "legacy_evidence_ref_invalid", "logical ref must be canonical process/<relative>"
        )


def _require_operation(registration: LegacyEvidenceRegistration, operation: str) -> None:
    if operation not in registration.allowed_operations:
        raise LegacyEvidenceError(
            "legacy_evidence_operation_denied", f"operation denied: {operation}"
        )


def _parse_legacy_outcome(raw: bytes) -> tuple[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LegacyEvidenceError("legacy_evidence_parse_failed", "evidence is not UTF-8") from exc
    frontmatter_match = re.match(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", text, re.DOTALL)
    frontmatter_fields: dict[str, list[str]] = {}
    if frontmatter_match is not None:
        for match in _OUTCOME_FIELD_RE.finditer(frontmatter_match.group("body")):
            frontmatter_fields.setdefault(match.group("key"), []).append(
                match.group("value").strip()
            )
    native_lifecycle_values = frontmatter_fields.get("lifecycle_status", [])
    native_readiness_values = frontmatter_fields.get("readiness_status", [])
    frontmatter_legacy_values = (
        frontmatter_fields.get("status", [])
        + frontmatter_fields.get("lifecycle", [])
        + frontmatter_fields.get("decision", [])
        + frontmatter_fields.get("outcome", [])
    )
    has_native_shape = bool(native_lifecycle_values or native_readiness_values)

    # 历史 CR-053/054/055 使用 native-like frontmatter，但它们仍只是已登记的
    # immutable legacy evidence。两种形态混用会产生两个 outcome owner，必须拒绝。
    if frontmatter_legacy_values and has_native_shape:
        raise LegacyEvidenceError(
            "legacy_evidence_parse_failed",
            "legacy outcome mixes status/decision with lifecycle_status/readiness_status",
        )
    if has_native_shape:
        if len(native_lifecycle_values) != 1 or len(native_readiness_values) != 1:
            raise LegacyEvidenceError(
                "legacy_evidence_parse_failed",
                "legacy lifecycle_status/readiness_status outcome is not unambiguous",
            )
        normalized_frontmatter = parse_frontmatter(text)
        lifecycle = str(normalized_frontmatter.get("lifecycle_status") or "")
        readiness = str(normalized_frontmatter.get("readiness_status") or "")
        if (lifecycle, readiness) != ("closed", "READY_WITH_RISK"):
            raise LegacyEvidenceError(
                "legacy_evidence_parse_failed",
                "legacy native-like outcome is not closed/READY_WITH_RISK",
            )
        return lifecycle, "PASS_WITH_RISK"

    # 旧式 status/decision 证据可能没有 frontmatter，继续保留历史全文扫描行为；
    # native-like 字段则只在 frontmatter 中生效，正文示例不能冒充 outcome。
    fields: dict[str, list[str]] = {}
    for match in _OUTCOME_FIELD_RE.finditer(text):
        fields.setdefault(match.group("key"), []).append(match.group("value").strip())
    lifecycle_values = fields.get("status", []) + fields.get("lifecycle", [])
    decision_values = fields.get("decision", []) + fields.get("outcome", [])
    if lifecycle_values == ["closed-pass-with-risk"] and not decision_values:
        return "closed-pass-with-risk", "PASS_WITH_RISK"
    if len(lifecycle_values) != 1 or len(decision_values) != 1:
        raise LegacyEvidenceError(
            "legacy_evidence_parse_failed",
            "legacy closed/PASS_WITH_RISK outcome is not unambiguous",
        )
    return lifecycle_values[0], decision_values[0]


def _parse_follow_ups(raw: bytes, source_logical_ref: str) -> tuple[LegacyFollowUpView, ...]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LegacyEvidenceError(
            "legacy_follow_up_query_failed", "follow-up source is not UTF-8"
        ) from exc
    id_matches = tuple(_FOLLOW_UP_ID_RE.finditer(text))
    if not id_matches:
        raise LegacyEvidenceError("legacy_follow_up_query_failed", "no stable follow-up IDs found")
    views: list[LegacyFollowUpView] = []
    for index, match in enumerate(id_matches):
        block_end = id_matches[index + 1].start() if index + 1 < len(id_matches) else len(text)
        block = text[match.start() : block_end]
        fields = {
            item.group("key"): item.group("value").strip() for item in _FIELD_RE.finditer(block)
        }
        follow_up_id = match.group("id")
        if fields.get("id", follow_up_id) != follow_up_id or not fields.get("status"):
            raise LegacyEvidenceError(
                "legacy_follow_up_query_failed", "follow-up lacks stable ID or status"
            )
        line_number = text.count("\n", 0, match.start()) + 1
        views.append(
            LegacyFollowUpView(
                follow_up_id=follow_up_id,
                status=fields["status"],
                relationship=fields.get("relationship", ""),
                source_logical_ref=source_logical_ref,
                source_anchor=f"line:{line_number}",
            )
        )
    return tuple(views)


def _validate_follow_ups(
    registration: LegacyEvidenceRegistration, follow_ups: tuple[LegacyFollowUpView, ...]
) -> None:
    ids = tuple(item.follow_up_id for item in follow_ups)
    statuses = tuple((item.follow_up_id, item.status) for item in follow_ups)
    if (
        len(ids) != registration.expected_follow_up_count
        or len(set(ids)) != len(ids)
        or frozenset(ids) != frozenset(registration.expected_follow_up_ids)
        or statuses != registration.expected_follow_up_statuses
    ):
        raise LegacyEvidenceError(
            "legacy_follow_up_query_failed",
            "follow-up count, exact ID set, order, or status does not match registration",
        )


def _validate_verified_view(verified: LegacyEvidenceView) -> None:
    if not isinstance(verified, LegacyEvidenceView) or (
        verified.source_kind != "registered_legacy_evidence"
        or verified.compatibility_kind != "registered_legacy_closed_evidence"
    ):
        raise LegacyEvidenceError(
            "legacy_follow_up_query_failed", "view is not a verified legacy view"
        )


__all__ = [
    "ALLOWED_OPERATIONS",
    "EVIDENCE_KIND",
    "SUPPORTED_SCHEMA_VERSION",
    "SUPPORTED_LEGACY_OUTCOMES",
    "LegacyEvidenceError",
    "LegacyEvidenceRegistration",
    "DeclaredLegacyEvidenceRegistry",
    "LegacyEvidenceView",
    "LegacyFollowUpView",
    "convert_to_formal_cr",
    "get_registered_follow_up",
    "inspect_registered_legacy_evidence",
    "load_declared_legacy_evidence_registry",
    "list_registered_follow_ups",
    "query_declared_legacy_evidence",
    "registered_legacy_cr_ids",
    "validate_legacy_evidence_registry_continuity",
    "validate_legacy_evidence_registry",
]
