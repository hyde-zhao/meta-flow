"""不可变发布包 Plan IR 的纯编译器。"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from meta_flow.workflow.package_plan import (
    PackageDiagnosticV1,
    PackagePlanInputV1,
    PackagePlanIRV1,
    canonical_digest,
)

COMPILER_ID = "meta-flow.package-compiler/v1"
_AUTHORITY_SECRET = secrets.token_bytes(32)
_PRIORITY_RE = re.compile(r"^P[0-9]$")
_NON_PRODUCTION_PATH_PARTS = {
    "__pycache__",
    "doc",
    "docs",
    "fixture",
    "fixtures",
    "helper",
    "helpers",
    "template",
    "templates",
    "test",
    "tests",
}


def _diagnostic(
    code: str,
    subject_kind: str,
    subject_id: str,
    *,
    message: str,
    owner_hint: str,
    recovery_action: str,
    source_ref: str = "process/DEVELOPMENT-PLAN.yaml",
) -> PackageDiagnosticV1:
    return PackageDiagnosticV1(
        severity="BLOCKER",
        code=code,
        subject_kind=subject_kind,
        subject_id=subject_id,
        source_ref=source_ref,
        message=message,
        owner_hint=owner_hint,
        recovery_action=recovery_action,
    )


def _diagnostic_key(item: PackageDiagnosticV1) -> tuple[str, ...]:
    return (
        item.severity,
        item.code,
        item.subject_kind,
        item.subject_id,
        item.source_ref,
        item.message,
    )


def _is_production_python_path(value: str) -> bool:
    if not value.endswith(".py") or value.startswith("/") or "\\" in value or "://" in value:
        return False
    parts = value.split("/")
    return bool(parts) and all(
        part not in {"", ".", ".."} and part.lower() not in _NON_PRODUCTION_PATH_PARTS
        for part in parts
    )


def _wave_key(value: str) -> tuple[int, str]:
    match = re.search(r"([0-9]+)$", value)
    return (int(match.group(1)) if match else 10**9, value)


def _source_fingerprint(value: PackagePlanInputV1) -> str:
    return canonical_digest([item.as_dict() for item in value.source_objects])


def _authority_token(source_fingerprint: str, semantic_digest: str) -> str:
    return hmac.new(
        _AUTHORITY_SECRET,
        f"{COMPILER_ID}:{source_fingerprint}:{semantic_digest}".encode(),
        hashlib.sha256,
    ).hexdigest()


def compile_package_plan(value: PackagePlanInputV1) -> PackagePlanIRV1:
    """将 closed input 编译为稳定 IR；无论结果如何都保持 mutation=0。"""

    diagnostics: list[PackageDiagnosticV1] = []
    package_subject = value.package_id or value.cr_id or "package"
    if not value.asset_set:
        diagnostics.append(
            _diagnostic(
                "PACKAGE_FIELD_MISSING",
                "package",
                package_subject,
                message="asset_set is required",
                owner_hint="Package owner",
                recovery_action="declare the complete publishable asset set",
            )
        )
    if not value.source_objects:
        diagnostics.append(
            _diagnostic(
                "PACKAGE_FIELD_MISSING",
                "package",
                package_subject,
                message="source_objects are required",
                owner_hint="Package compiler adapter",
                recovery_action="bind canonical source object digests",
            )
        )
    if not value.semver_bootstrap_ref:
        diagnostics.append(
            _diagnostic(
                "PACKAGE_FIELD_MISSING",
                "package",
                package_subject,
                message="semver_bootstrap_ref is required",
                owner_hint="Package owner",
                recovery_action="bind the approved one-shot SemVer bootstrap decision",
                source_ref="docs/product/REQUIREMENTS.md",
            )
        )

    work_ids = [item.work_id for item in value.works]
    if len(value.works) != 2 or len(set(work_ids)) != 2:
        diagnostics.append(
            _diagnostic(
                "WORK_CARDINALITY_INVALID",
                "package",
                package_subject,
                message=f"expected exactly 2 unique Work records, observed {len(set(work_ids))}",
                owner_hint="Host/CR owner",
                recovery_action="restore the approved two-Work release package",
            )
        )
    for work in value.works:
        if work.release_value != value.target_version:
            diagnostics.append(
                _diagnostic(
                    "PACKAGE_RELEASE_VALUE_MISMATCH",
                    "work",
                    work.work_id,
                    message="Work release value differs from package target_version",
                    owner_hint="Work owner",
                    recovery_action="converge all Work records on the shared release value",
                )
            )

    stories_by_id = {item.story_id: item for item in value.stories}
    if len(value.stories) != 6 or len(stories_by_id) != 6:
        diagnostics.append(
            _diagnostic(
                "PACKAGE_STORY_CARDINALITY_INVALID",
                "package",
                package_subject,
                message=f"expected exactly 6 unique Story records, observed {len(stories_by_id)}",
                owner_hint="Story planner",
                recovery_action="restore the approved six-Story package slice",
            )
        )

    work_id_set = set(work_ids)
    for story in value.stories:
        if story.work_id not in work_id_set:
            diagnostics.append(
                _diagnostic(
                    "PACKAGE_FIELD_MISSING",
                    "story",
                    story.story_id,
                    message=f"referenced Work is not in package: {story.work_id}",
                    owner_hint="Story planner",
                    recovery_action="bind the Story to one declared Work",
                )
            )
        if (
            not _PRIORITY_RE.fullmatch(story.priority)
            or not _PRIORITY_RE.fullmatch(story.requirement_priority)
            or story.priority != story.requirement_priority
        ):
            diagnostics.append(
                _diagnostic(
                    "STORY_PRIORITY_INVALID",
                    "story",
                    story.story_id,
                    message=(
                        "Story priority must be explicit and equal to requirement priority "
                        f"({story.priority!r} != {story.requirement_priority!r})"
                    ),
                    owner_hint="Story/Product owner",
                    recovery_action="resolve the priority conflict in canonical product and Story truth",
                )
            )

    primary_owners: dict[str, list[str]] = defaultdict(list)
    shared_owners: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for story in value.stories:
        for path in story.primary_paths:
            primary_owners[path].append(story.story_id)
        for path in story.shared_paths:
            shared_owners[path].append((story.story_id, story.merge_owner))

    for path in sorted(set(primary_owners) | set(shared_owners)):
        primary = sorted(set(primary_owners.get(path, [])))
        shared = sorted(set(shared_owners.get(path, [])))
        participants = sorted(set(primary) | {story_id for story_id, _owner in shared})
        merge_owners = {owner for _story_id, owner in shared if owner}
        shared_has_missing_owner = any(not owner for _story_id, owner in shared)
        conflict = len(primary) > 1 or (
            bool(shared) and (shared_has_missing_owner or len(merge_owners) != 1)
        )
        if conflict:
            diagnostics.append(
                _diagnostic(
                    "FILE_OWNER_CONFLICT",
                    "path",
                    path,
                    message=f"ownership participants are not uniquely mergeable: {participants}",
                    owner_hint="Story planner",
                    recovery_action="declare one primary owner or one shared merge owner",
                )
            )

    required_operations = {
        item.operation_id: item for item in value.required_public_operations
    }
    registry = {item.operation_id: item for item in value.operation_registry}
    for operation_id, required in sorted(required_operations.items()):
        registered = registry.get(operation_id)
        if registered is None or (
            registered.entry != required.entry
            or registered.mutation_mode != required.mutation_mode
        ):
            diagnostics.append(
                _diagnostic(
                    "PUBLIC_OPERATION_UNREGISTERED",
                    "operation",
                    operation_id,
                    message="operation id, argv prefix and mutation mode must exactly match registry",
                    owner_hint="CLI merge owner",
                    recovery_action="register the exact public operation contract",
                    source_ref="delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml",
                )
            )

    for story in value.stories:
        unknown_operations = sorted(set(story.public_operation_ids) - set(required_operations))
        for operation_id in unknown_operations:
            diagnostics.append(
                _diagnostic(
                    "PUBLIC_OPERATION_UNREGISTERED",
                    "story",
                    story.story_id,
                    message=f"Story requires undeclared operation {operation_id}",
                    owner_hint="CLI merge owner",
                    recovery_action="add the operation requirement and exact registry entry",
                    source_ref="delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml",
                )
            )
        production_ok = (
            bool(story.production_entrypoints)
            and bool(story.reachable_core_paths)
            and all(
                _is_production_python_path(path)
                for path in (*story.production_entrypoints, *story.reachable_core_paths)
            )
            and bool(set(story.primary_paths).intersection(story.reachable_core_paths))
        )
        if not production_ok:
            diagnostics.append(
                _diagnostic(
                    "PRODUCTION_ENTRYPOINT_UNREACHABLE",
                    "story",
                    story.story_id,
                    message="production entrypoint/core path is absent, helper-only, or outside primary ownership",
                    owner_hint="Story owner",
                    recovery_action="declare a reachable production adapter and primary core path",
                )
            )

    valid_edges: set[tuple[str, str, str]] = set()
    for story in value.stories:
        for dependency in story.dependencies:
            upstream = stories_by_id.get(dependency.upstream)
            if upstream is None or dependency.upstream == story.story_id:
                diagnostics.append(
                    _diagnostic(
                        "PACKAGE_DEPENDENCY_INVALID",
                        "story",
                        story.story_id,
                        message=f"dependency endpoint is invalid: {dependency.upstream}",
                        owner_hint="Plan owner",
                        recovery_action="bind the edge to two distinct package Story nodes",
                    )
                )
                continue
            if upstream.wave == story.wave:
                diagnostics.append(
                    _diagnostic(
                        "PACKAGE_DEPENDENCY_INVALID",
                        "story",
                        story.story_id,
                        message=f"same-wave dependency is forbidden: {dependency.upstream}",
                        owner_hint="Plan owner",
                        recovery_action="move the consumer to a later Wave or remove the dependency",
                    )
                )
            valid_edges.add((dependency.upstream, story.story_id, dependency.edge_type))

    indegree = {story_id: 0 for story_id in stories_by_id}
    downstream: dict[str, set[str]] = defaultdict(set)
    for upstream, consumer, _edge_type in valid_edges:
        if consumer not in downstream[upstream]:
            downstream[upstream].add(consumer)
            indegree[consumer] += 1
    ready = sorted(
        (story for story in value.stories if indegree[story.story_id] == 0),
        key=lambda story: (_wave_key(story.wave), story.story_id),
    )
    ordered_story_ids: list[str] = []
    while ready:
        story = ready.pop(0)
        ordered_story_ids.append(story.story_id)
        for consumer in sorted(downstream.get(story.story_id, set())):
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                ready.append(stories_by_id[consumer])
                ready.sort(key=lambda item: (_wave_key(item.wave), item.story_id))
    if len(ordered_story_ids) != len(stories_by_id):
        cycle_nodes = sorted(story_id for story_id, count in indegree.items() if count > 0)
        diagnostics.append(
            _diagnostic(
                "PACKAGE_DEPENDENCY_INVALID",
                "package",
                package_subject,
                message=f"dependency cycle contains: {','.join(cycle_nodes)}",
                owner_hint="Plan owner",
                recovery_action="remove the deterministic cycle before compilation",
            )
        )

    unique_diagnostics = tuple(
        sorted({_diagnostic_key(item): item for item in diagnostics}.values(), key=_diagnostic_key)
    )
    decision = "BLOCKED" if unique_diagnostics else "PASS"
    authoritative = decision == "PASS"
    owner_map = tuple(
        sorted(
            [
                (path, owners[0], "primary")
                for path, owners in primary_owners.items()
                if len(set(owners)) == 1 and path not in shared_owners
            ]
            + [
                (path, next(iter({owner for _story, owner in owners})), "shared")
                for path, owners in shared_owners.items()
                if len({owner for _story, owner in owners}) == 1
            ]
        )
    )
    ordered_groups: dict[str, list[str]] = defaultdict(list)
    for story_id in ordered_story_ids:
        ordered_groups[stories_by_id[story_id].wave].append(story_id)
    topological_waves = tuple(
        (wave, tuple(ordered_groups[wave]))
        for wave in sorted(ordered_groups, key=_wave_key)
    )
    source_fingerprint = _source_fingerprint(value)
    draft = PackagePlanIRV1(
        schema_version=1,
        compiler_id=COMPILER_ID,
        package_id=value.package_id,
        target_version=value.target_version,
        cr_id=value.cr_id,
        works=value.works,
        stories=value.stories,
        dependency_edges=tuple(sorted(valid_edges)),
        owner_map=owner_map,
        priority_map=tuple(sorted((item.story_id, item.priority) for item in value.stories)),
        operation_map=tuple(sorted(required_operations.values(), key=lambda item: item.operation_id)),
        topological_waves=topological_waves,
        source_fingerprint=source_fingerprint,
        diagnostics=unique_diagnostics,
        decision=decision,
        authoritative=authoritative,
        mutation_count=0,
        semantic_digest="",
    )
    digest_input = draft.as_dict()
    digest_input.pop("semantic_digest")
    semantic_digest = canonical_digest(digest_input)
    return PackagePlanIRV1(
        **{
            **{key: getattr(draft, key) for key in draft.__dataclass_fields__ if key != "_provenance_token"},
            "semantic_digest": semantic_digest,
            "_provenance_token": (
                _authority_token(source_fingerprint, semantic_digest) if authoritative else ""
            ),
        }
    )


def admit_compiled_plan(
    value: PackagePlanIRV1 | Mapping[str, Any], *, expected_fingerprint: str
) -> tuple[str, ...]:
    """仅准入当前进程中由 compiler 产生且 fingerprint 一致的 PASS IR。"""

    if not isinstance(value, PackagePlanIRV1):
        return ("HANDWRITTEN_PLAN_NON_AUTHORITATIVE",)
    errors: list[str] = []
    if not value.authoritative or value.decision != "PASS":
        errors.append("HANDWRITTEN_PLAN_NON_AUTHORITATIVE")
    if value.source_fingerprint != expected_fingerprint:
        errors.append("PACKAGE_SOURCE_FINGERPRINT_MISMATCH")
    digest_input = value.as_dict()
    digest_input.pop("semantic_digest")
    expected_digest = canonical_digest(digest_input)
    if value.semantic_digest != expected_digest:
        errors.append("PACKAGE_SEMANTIC_DIGEST_MISMATCH")
    expected_token = _authority_token(value.source_fingerprint, value.semantic_digest)
    if not value._provenance_token or not hmac.compare_digest(
        value._provenance_token, expected_token
    ):
        errors.append("HANDWRITTEN_PLAN_NON_AUTHORITATIVE")
    return tuple(sorted(set(errors)))


__all__ = ["COMPILER_ID", "admit_compiled_plan", "compile_package_plan"]
