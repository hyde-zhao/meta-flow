"""发布包 Plan Compiler 的不可变输入、诊断与 IR 合同。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$")
_EDGE_TYPES = {"contract", "runtime", "verification", "release"}


def canonical_json(value: object) -> str:
    """返回无时间字段、稳定键序的 canonical JSON。"""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _closed_mapping(value: object, fields: set[str], *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(code)
    return value


def _string(value: object, *, code: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(code)
    if pattern is not None and not pattern.fullmatch(value):
        raise ValueError(code)
    return value


def _string_tuple(value: object, *, code: str, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item or item != item.strip() for item in value
    ):
        raise ValueError(code)
    result = tuple(sorted(set(value)))
    if not allow_empty and not result:
        raise ValueError(code)
    return result


def _ordered_string_tuple(value: object, *, code: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value or any(
        not isinstance(item, str) or not item or item != item.strip() for item in value
    ):
        raise ValueError(code)
    return tuple(value)


@dataclass(frozen=True)
class SourceObjectV1:
    ref: str
    bytes_digest: str
    semantic_digest: str

    @classmethod
    def from_mapping(cls, value: object) -> SourceObjectV1:
        item = _closed_mapping(
            value,
            {"ref", "bytes_digest", "semantic_digest"},
            code="PACKAGE_SOURCE_FIELDS_MISMATCH",
        )
        ref = _string(item["ref"], code="PACKAGE_SOURCE_REF_INVALID")
        if ref.startswith("/") or "\\" in ref or "://" in ref or any(
            part in {"", ".", ".."} for part in ref.split("/")
        ):
            raise ValueError("PACKAGE_SOURCE_REF_INVALID")
        return cls(
            ref=ref,
            bytes_digest=_string(
                item["bytes_digest"], code="PACKAGE_SOURCE_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
            semantic_digest=_string(
                item["semantic_digest"], code="PACKAGE_SOURCE_DIGEST_INVALID", pattern=_DIGEST_RE
            ),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "ref": self.ref,
            "bytes_digest": self.bytes_digest,
            "semantic_digest": self.semantic_digest,
        }


@dataclass(frozen=True)
class WorkPlanNodeV1:
    work_id: str
    release_value: str

    @classmethod
    def from_mapping(cls, value: object) -> WorkPlanNodeV1:
        item = _closed_mapping(
            value, {"work_id", "release_value"}, code="PACKAGE_WORK_FIELDS_MISMATCH"
        )
        return cls(
            work_id=_string(item["work_id"], code="PACKAGE_WORK_ID_INVALID", pattern=_ID_RE),
            release_value=_string(
                item["release_value"], code="PACKAGE_RELEASE_VALUE_INVALID", pattern=_VERSION_RE
            ),
        )

    def as_dict(self) -> dict[str, str]:
        return {"work_id": self.work_id, "release_value": self.release_value}


@dataclass(frozen=True)
class DependencyInputV1:
    upstream: str
    edge_type: str

    @classmethod
    def from_mapping(cls, value: object) -> DependencyInputV1:
        item = _closed_mapping(
            value, {"upstream", "edge_type"}, code="PACKAGE_DEPENDENCY_FIELDS_MISMATCH"
        )
        edge_type = _string(item["edge_type"], code="PACKAGE_DEPENDENCY_TYPE_INVALID")
        if edge_type not in _EDGE_TYPES:
            raise ValueError("PACKAGE_DEPENDENCY_TYPE_INVALID")
        return cls(
            upstream=_string(
                item["upstream"], code="PACKAGE_DEPENDENCY_ENDPOINT_INVALID", pattern=_ID_RE
            ),
            edge_type=edge_type,
        )

    def as_dict(self) -> dict[str, str]:
        return {"upstream": self.upstream, "edge_type": self.edge_type}


@dataclass(frozen=True)
class StoryPlanNodeV1:
    story_id: str
    work_id: str
    priority: str
    requirement_priority: str
    wave: str
    dependencies: tuple[DependencyInputV1, ...]
    primary_paths: tuple[str, ...]
    shared_paths: tuple[str, ...]
    merge_owner: str
    feature_refs: tuple[str, ...]
    production_entrypoints: tuple[str, ...]
    reachable_core_paths: tuple[str, ...]
    public_operation_ids: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: object) -> StoryPlanNodeV1:
        fields = {
            "story_id",
            "work_id",
            "priority",
            "requirement_priority",
            "wave",
            "dependencies",
            "primary_paths",
            "shared_paths",
            "merge_owner",
            "feature_refs",
            "production_entrypoints",
            "reachable_core_paths",
            "public_operation_ids",
        }
        item = _closed_mapping(value, fields, code="PACKAGE_STORY_FIELDS_MISMATCH")
        if not isinstance(item["dependencies"], (list, tuple)):
            raise ValueError("PACKAGE_DEPENDENCIES_INVALID")
        dependencies = tuple(
            sorted(
                (DependencyInputV1.from_mapping(entry) for entry in item["dependencies"]),
                key=lambda entry: (entry.upstream, entry.edge_type),
            )
        )
        priority = _string(item["priority"], code="STORY_PRIORITY_INVALID")
        requirement_priority = _string(
            item["requirement_priority"], code="STORY_PRIORITY_INVALID"
        )
        merge_owner = item["merge_owner"]
        if not isinstance(merge_owner, str) or merge_owner != merge_owner.strip():
            raise ValueError("FILE_MERGE_OWNER_INVALID")
        return cls(
            story_id=_string(item["story_id"], code="PACKAGE_STORY_ID_INVALID", pattern=_ID_RE),
            work_id=_string(item["work_id"], code="PACKAGE_WORK_ID_INVALID", pattern=_ID_RE),
            priority=priority,
            requirement_priority=requirement_priority,
            wave=_string(item["wave"], code="PACKAGE_WAVE_INVALID", pattern=_ID_RE),
            dependencies=dependencies,
            primary_paths=_string_tuple(item["primary_paths"], code="FILE_OWNER_PATH_INVALID"),
            shared_paths=_string_tuple(item["shared_paths"], code="FILE_OWNER_PATH_INVALID"),
            merge_owner=merge_owner,
            feature_refs=_string_tuple(
                item["feature_refs"], code="PACKAGE_FEATURE_REFS_INVALID", allow_empty=False
            ),
            production_entrypoints=_string_tuple(
                item["production_entrypoints"], code="PRODUCTION_ENTRYPOINT_INVALID"
            ),
            reachable_core_paths=_string_tuple(
                item["reachable_core_paths"], code="PRODUCTION_ENTRYPOINT_INVALID"
            ),
            public_operation_ids=_string_tuple(
                item["public_operation_ids"], code="PUBLIC_OPERATION_ID_INVALID"
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "story_id": self.story_id,
            "work_id": self.work_id,
            "priority": self.priority,
            "requirement_priority": self.requirement_priority,
            "wave": self.wave,
            "dependencies": [item.as_dict() for item in self.dependencies],
            "primary_paths": list(self.primary_paths),
            "shared_paths": list(self.shared_paths),
            "merge_owner": self.merge_owner,
            "feature_refs": list(self.feature_refs),
            "production_entrypoints": list(self.production_entrypoints),
            "reachable_core_paths": list(self.reachable_core_paths),
            "public_operation_ids": list(self.public_operation_ids),
        }


@dataclass(frozen=True)
class PublicOperationRequirementV1:
    operation_id: str
    entry: tuple[str, ...]
    mutation_mode: str

    @classmethod
    def from_mapping(cls, value: object) -> PublicOperationRequirementV1:
        item = _closed_mapping(
            value,
            {"operation_id", "entry", "mutation_mode"},
            code="PUBLIC_OPERATION_FIELDS_MISMATCH",
        )
        operation_id = _string(
            item["operation_id"], code="PUBLIC_OPERATION_ID_INVALID", pattern=_OPERATION_RE
        )
        return cls(
            operation_id=operation_id,
            entry=_ordered_string_tuple(item["entry"], code="PUBLIC_OPERATION_ENTRY_INVALID"),
            mutation_mode=_string(item["mutation_mode"], code="PUBLIC_OPERATION_MODE_INVALID"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "entry": list(self.entry),
            "mutation_mode": self.mutation_mode,
        }


@dataclass(frozen=True)
class PackagePlanInputV1:
    schema_version: int
    package_id: str
    target_version: str
    cr_id: str
    works: tuple[WorkPlanNodeV1, ...]
    stories: tuple[StoryPlanNodeV1, ...]
    required_public_operations: tuple[PublicOperationRequirementV1, ...]
    operation_registry: tuple[PublicOperationRequirementV1, ...]
    asset_set: tuple[str, ...]
    semver_bootstrap_ref: str
    source_objects: tuple[SourceObjectV1, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PackagePlanInputV1:
        fields = {
            "schema_version",
            "package_id",
            "target_version",
            "cr_id",
            "works",
            "stories",
            "required_public_operations",
            "operation_registry",
            "asset_set",
            "semver_bootstrap_ref",
            "source_objects",
        }
        item = _closed_mapping(value, fields, code="PACKAGE_INPUT_FIELDS_MISMATCH")
        if item["schema_version"] != 1:
            raise ValueError("PACKAGE_INPUT_SCHEMA_INVALID")
        for field_name in (
            "works",
            "stories",
            "required_public_operations",
            "operation_registry",
            "source_objects",
        ):
            if not isinstance(item[field_name], (list, tuple)):
                raise ValueError(f"PACKAGE_{field_name.upper()}_INVALID")
        works = tuple(
            sorted(
                (WorkPlanNodeV1.from_mapping(entry) for entry in item["works"]),
                key=lambda entry: entry.work_id,
            )
        )
        stories = tuple(
            sorted(
                (StoryPlanNodeV1.from_mapping(entry) for entry in item["stories"]),
                key=lambda entry: entry.story_id,
            )
        )
        required_operations = tuple(
            sorted(
                (
                    PublicOperationRequirementV1.from_mapping(entry)
                    for entry in item["required_public_operations"]
                ),
                key=lambda entry: entry.operation_id,
            )
        )
        registry = tuple(
            sorted(
                (
                    PublicOperationRequirementV1.from_mapping(entry)
                    for entry in item["operation_registry"]
                ),
                key=lambda entry: entry.operation_id,
            )
        )
        sources = tuple(
            sorted(
                (SourceObjectV1.from_mapping(entry) for entry in item["source_objects"]),
                key=lambda entry: entry.ref,
            )
        )
        semver_ref = item["semver_bootstrap_ref"]
        if not isinstance(semver_ref, str) or semver_ref != semver_ref.strip():
            raise ValueError("SEMVER_BOOTSTRAP_REF_INVALID")
        return cls(
            schema_version=1,
            package_id=_string(item["package_id"], code="PACKAGE_ID_INVALID", pattern=_ID_RE),
            target_version=_string(
                item["target_version"], code="PACKAGE_VERSION_INVALID", pattern=_VERSION_RE
            ),
            cr_id=_string(item["cr_id"], code="PACKAGE_CR_ID_INVALID", pattern=_ID_RE),
            works=works,
            stories=stories,
            required_public_operations=required_operations,
            operation_registry=registry,
            asset_set=_string_tuple(item["asset_set"], code="PACKAGE_ASSET_SET_INVALID"),
            semver_bootstrap_ref=semver_ref,
            source_objects=sources,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "target_version": self.target_version,
            "cr_id": self.cr_id,
            "works": [item.as_dict() for item in self.works],
            "stories": [item.as_dict() for item in self.stories],
            "required_public_operations": [
                item.as_dict() for item in self.required_public_operations
            ],
            "operation_registry": [item.as_dict() for item in self.operation_registry],
            "asset_set": list(self.asset_set),
            "semver_bootstrap_ref": self.semver_bootstrap_ref,
            "source_objects": [item.as_dict() for item in self.source_objects],
        }


@dataclass(frozen=True)
class PackageDiagnosticV1:
    severity: str
    code: str
    subject_kind: str
    subject_id: str
    source_ref: str
    message: str
    owner_hint: str
    recovery_action: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "source_ref": self.source_ref,
            "message": self.message,
            "owner_hint": self.owner_hint,
            "recovery_action": self.recovery_action,
        }


@dataclass(frozen=True)
class PackagePlanIRV1:
    schema_version: int
    compiler_id: str
    package_id: str
    target_version: str
    cr_id: str
    works: tuple[WorkPlanNodeV1, ...]
    stories: tuple[StoryPlanNodeV1, ...]
    dependency_edges: tuple[tuple[str, str, str], ...]
    owner_map: tuple[tuple[str, str, str], ...]
    priority_map: tuple[tuple[str, str], ...]
    operation_map: tuple[PublicOperationRequirementV1, ...]
    topological_waves: tuple[tuple[str, tuple[str, ...]], ...]
    source_fingerprint: str
    diagnostics: tuple[PackageDiagnosticV1, ...]
    decision: str
    authoritative: bool
    mutation_count: int
    semantic_digest: str
    _provenance_token: str = field(default="", repr=False, compare=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "PackagePlanIRV1",
            "compiler_id": self.compiler_id,
            "package_id": self.package_id,
            "target_version": self.target_version,
            "cr_id": self.cr_id,
            "works": [item.as_dict() for item in self.works],
            "stories": [item.as_dict() for item in self.stories],
            "dependency_edges": [
                {"upstream": upstream, "downstream": downstream, "edge_type": edge_type}
                for upstream, downstream, edge_type in self.dependency_edges
            ],
            "owner_map": [
                {"path": path, "owner": owner, "ownership": ownership}
                for path, owner, ownership in self.owner_map
            ],
            "priority_map": [
                {"story_id": story_id, "priority": priority}
                for story_id, priority in self.priority_map
            ],
            "operation_map": [item.as_dict() for item in self.operation_map],
            "topological_waves": [
                {"wave": wave, "story_ids": list(story_ids)}
                for wave, story_ids in self.topological_waves
            ],
            "source_fingerprint": self.source_fingerprint,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "decision": self.decision,
            "authoritative": self.authoritative,
            "mutation_count": self.mutation_count,
            "semantic_digest": self.semantic_digest,
        }


__all__ = [
    "DependencyInputV1",
    "PackageDiagnosticV1",
    "PackagePlanInputV1",
    "PackagePlanIRV1",
    "PublicOperationRequirementV1",
    "SourceObjectV1",
    "StoryPlanNodeV1",
    "WorkPlanNodeV1",
    "canonical_digest",
    "canonical_json",
]
