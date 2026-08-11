"""治理概念 owner、真相边界与 consumer coverage 的组合硬门。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.semantics import outcome

CONCEPT_OWNERS_REL = Path("process/docs/design/CONCEPT-OWNERS.yaml")
SOURCE_OF_TRUTH_REL = Path("process/policies/SOURCE-OF-TRUTH-MAP.yaml")
CAPABILITY_REGISTRY_REL = Path("process/docs/design/CAPABILITY-REGISTRY.yaml")
FEATURE_REGISTRY_REL = Path("process/docs/design/FEATURE-REGISTRY.yaml")

CONCEPT_OWNERS_KIND = "GovernanceConceptOwnersV2"
CHECK_KIND = "GovernanceOwnershipCheckV1"
CHECK_COMMAND = "meta-flow check governance-ownership"
PUBLIC_OPERATION_DECLARATIONS = (
    ("governance-ownership.check", ("meta-flow", "check", "governance-ownership")),
)
DETECTOR_SOURCE_TYPES = (
    "registry",
    "ast-import-call",
    "cli-public-operation",
    "explicit-boundary-ref",
)
CONCEPT_TOP_FIELDS = {
    "schema_version",
    "kind",
    "universe",
    "detector_profile",
    "concept_owners",
    "consumer_mappings",
}
UNIVERSE_FIELDS = {
    "freeze_id",
    "canonical_concept_ids",
    "expansion_policy",
}
DETECTOR_FIELDS = {
    "profile_id",
    "qualification",
    "source_types",
    "ast_roots",
    "known_blind_spots",
}
CONCEPT_FIELDS = {
    "owner",
    "source_of_truth_boundary",
    "conformance_checker",
    "conflict_keys",
    "legacy_aliases",
    "forbidden_aliases",
}
MAPPING_FIELDS = {
    "consumer_id",
    "kind",
    "ref",
    "concept_id",
    "conformance_check",
}
MAX_AST_FILES = 512
MAX_AST_BYTES = 32 * 1024 * 1024
MAX_AST_FILE_BYTES = 2 * 1024 * 1024
_CONCEPT_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _digest_bytes(encoded)


def _regular_file(path: Path, *, ref: str, errors: list[str]) -> bool:
    if path.is_symlink() or not path.is_file():
        errors.append(f"source must be a regular file: {ref}")
        return False
    return True


def _load_source(path: Path, *, ref: str, errors: list[str]) -> dict[str, Any]:
    if not _regular_file(path, ref=ref, errors=errors):
        return {}
    try:
        return load_yaml_object(path)
    except (OSError, ValueError) as exc:
        errors.append(f"source is not a valid object: {ref}: {exc}")
        return {}


def _string_list(
    value: Any,
    *,
    subject: str,
    errors: list[str],
    non_empty: bool = True,
) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        errors.append(f"{subject} must be a list of non-empty strings")
        return []
    result = list(value)
    if non_empty and not result:
        errors.append(f"{subject} must not be empty")
    if len(result) != len(set(result)):
        errors.append(f"{subject} must not contain duplicates")
    return result


def _exact_fields(
    payload: dict[str, Any],
    expected: set[str],
    *,
    subject: str,
    errors: list[str],
) -> None:
    actual = set(payload)
    if actual == expected:
        return
    errors.append(
        f"{subject} fields mismatch: "
        f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
    )


def _owner_module_path(project_root: Path, owner: str) -> Path:
    return project_root.joinpath(*owner.split(".")).with_suffix(".py")


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _owner_import_bindings(tree: ast.AST, owner: str) -> set[str]:
    """返回 owner import 在本模块内实际绑定的名字。"""

    bindings: set[str] = set()
    owner_parent, _, owner_leaf = owner.rpartition(".")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == owner:
                    bindings.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == owner:
                bindings.update(alias.asname or alias.name for alias in node.names)
            elif node.module == owner_parent:
                bindings.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == owner_leaf
                )
    return bindings


def _loaded_names(tree: ast.AST) -> set[str]:
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }


def _discover_ast_consumers(
    project_root: Path,
    *,
    ast_roots: list[str],
    owners: dict[str, str],
    errors: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths: list[Path] = []
    for root_ref in ast_roots:
        root = project_root / root_ref
        if root.is_symlink() or not root.is_dir():
            errors.append(f"detector ast_root must be a regular directory: {root_ref}")
            continue
        paths.extend(path for path in root.rglob("*.py") if path.is_file())
    unique_paths = sorted(set(paths))
    if len(unique_paths) > MAX_AST_FILES:
        errors.append(
            f"detector AST file budget exceeded: {len(unique_paths)} > {MAX_AST_FILES}"
        )
        return [], {"scanned_file_count": 0, "scanned_byte_count": 0}

    discovered: list[dict[str, Any]] = []
    scanned_bytes = 0
    for path in unique_paths:
        ref = path.relative_to(project_root).as_posix()
        if path.is_symlink():
            errors.append(f"detector AST source must not be a symlink: {ref}")
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            errors.append(f"detector AST source unreadable: {ref}: {exc}")
            continue
        if len(raw) > MAX_AST_FILE_BYTES:
            errors.append(
                f"detector AST per-file budget exceeded: {ref}={len(raw)}"
            )
            continue
        scanned_bytes += len(raw)
        if scanned_bytes > MAX_AST_BYTES:
            errors.append(
                f"detector AST byte budget exceeded: {scanned_bytes} > {MAX_AST_BYTES}"
            )
            break
        try:
            tree = ast.parse(raw.decode("utf-8"), filename=ref)
        except (SyntaxError, UnicodeError) as exc:
            errors.append(f"detector AST parse failed: {ref}: {exc}")
            continue
        imported = _imported_modules(tree)
        loaded_names = _loaded_names(tree)
        concept_ids = sorted(
            concept_id
            for concept_id, owner in owners.items()
            if owner in imported
        )
        for concept_id in concept_ids:
            owner = owners[concept_id]
            bindings = _owner_import_bindings(tree, owner)
            if not bindings or not (bindings & loaded_names):
                errors.append(
                    "owner import is not consumed: "
                    f"ast-import-call:{ref} -> {owner}"
                )
            suffix = f"#{concept_id}" if len(concept_ids) > 1 else ""
            discovered.append(
                {
                    "consumer_id": f"ast-import-call:{ref}{suffix}",
                    "kind": "ast-import-call",
                    "ref": ref,
                    "candidate_concept_ids": [concept_id],
                }
            )
    return discovered, {
        "scanned_file_count": len(unique_paths),
        "scanned_byte_count": scanned_bytes,
    }


def _discover_registry_consumers(
    capability_registry: dict[str, Any],
    feature_registry: dict[str, Any],
    *,
    canonical_ids: set[str],
    errors: list[str],
) -> list[dict[str, Any]]:
    if capability_registry.get("schema_version") != 1:
        errors.append("CAPABILITY-REGISTRY schema_version must be 1")
    if feature_registry.get("schema_version") not in {1, 2}:
        errors.append("FEATURE-REGISTRY schema_version must be 1 or 2")
    feature_ids = {
        str(item.get("id") or item.get("feature_id") or "")
        for item in feature_registry.get("features") or []
        if isinstance(item, dict)
    }
    feature_ids.discard("")
    if not feature_ids:
        errors.append("FEATURE-REGISTRY must expose at least one feature ID")

    capabilities = capability_registry.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        errors.append("CAPABILITY-REGISTRY capabilities must be a non-empty list")
        return []
    discovered: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(capabilities, start=1):
        subject = f"CAPABILITY-REGISTRY capabilities[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{subject} must be an object")
            continue
        capability_id = item.get("id")
        if not isinstance(capability_id, str) or not capability_id:
            errors.append(f"{subject}.id must be non-empty")
            continue
        if capability_id in seen_ids:
            errors.append(f"duplicate capability ID: {capability_id}")
        seen_ids.add(capability_id)
        feature_refs = _string_list(
            item.get("feature_refs"),
            subject=f"{capability_id}.feature_refs",
            errors=errors,
        )
        unknown_features = sorted(set(feature_refs) - feature_ids)
        if unknown_features:
            errors.append(
                f"{capability_id}.feature_refs contain unknown IDs: {unknown_features}"
            )
        concept_refs = _string_list(
            item.get("concept_refs"),
            subject=f"{capability_id}.concept_refs",
            errors=errors,
        )
        unknown_concepts = sorted(set(concept_refs) - canonical_ids)
        if unknown_concepts:
            errors.append(
                f"{capability_id}.concept_refs contain unknown IDs: {unknown_concepts}"
            )
        discovered.append(
            {
                "consumer_id": f"registry:{capability_id}",
                "kind": "registry",
                "ref": (
                    "process/docs/design/CAPABILITY-REGISTRY.yaml"
                    f"#capabilities[{capability_id}]"
                ),
                "candidate_concept_ids": concept_refs,
            }
        )
    return discovered


def _discover_boundary_consumers(
    truth_map: dict[str, Any],
    *,
    errors: list[str],
) -> list[dict[str, Any]]:
    if truth_map.get("schema_version") != 2:
        errors.append("SOURCE-OF-TRUTH-MAP schema_version must be 2 for R5 ownership")
    objects = truth_map.get("objects")
    if not isinstance(objects, dict) or not objects:
        errors.append("SOURCE-OF-TRUTH-MAP objects must be a non-empty object")
        return []
    discovered: list[dict[str, Any]] = []
    for object_id, item in sorted(objects.items()):
        if not isinstance(item, dict):
            errors.append(f"SOURCE-OF-TRUTH-MAP objects.{object_id} must be an object")
            continue
        concept_id = item.get("canonical_concept_id")
        if concept_id is None:
            continue
        if not isinstance(concept_id, str) or not concept_id:
            errors.append(
                f"SOURCE-OF-TRUTH-MAP objects.{object_id}.canonical_concept_id invalid"
            )
            continue
        discovered.append(
            {
                "consumer_id": f"explicit-boundary-ref:{object_id}",
                "kind": "explicit-boundary-ref",
                "ref": (
                    "process/policies/SOURCE-OF-TRUTH-MAP.yaml"
                    f"#objects.{object_id}"
                ),
                "candidate_concept_ids": [concept_id],
            }
        )
    return discovered


def _cli_route_is_declared(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    required = (
        'validator == "governance-ownership"',
        "from meta_flow.semantics import ownership",
        "ownership.main(forwarded)",
    )
    return all(token in text for token in required)


def _integration_hard_gate_is_declared(project_root: Path, errors: list[str]) -> None:
    manifest_path = project_root / "meta_flow/semantics/__init__.py"
    guardrail_path = project_root / "scripts/check_delivery_guardrails.py"
    required_by_path = {
        manifest_path: (
            "governance-ownership-v1",
            "meta_flow.semantics.ownership",
        ),
        guardrail_path: (
            "from meta_flow.semantics.ownership import validate_ownership",
            "validate_ownership(ROOT)",
            "collect_governance_ownership_errors",
        ),
    }
    for path, required in required_by_path.items():
        ref = path.relative_to(project_root).as_posix()
        if path.is_symlink() or not path.is_file():
            errors.append(f"ownership integration source missing: {ref}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required if token not in text]
        if missing:
            errors.append(
                f"ownership integration hard gate missing tokens: {ref} -> {missing}"
            )


def _validate_concepts(
    project_root: Path,
    concept_map: dict[str, Any],
    truth_map: dict[str, Any],
    *,
    errors: list[str],
) -> tuple[list[str], dict[str, str], int]:
    _exact_fields(
        concept_map,
        CONCEPT_TOP_FIELDS,
        subject="CONCEPT-OWNERS",
        errors=errors,
    )
    if concept_map.get("schema_version") != 2:
        errors.append("CONCEPT-OWNERS schema_version must be 2 for R5 ownership")
    if concept_map.get("kind") != CONCEPT_OWNERS_KIND:
        errors.append(f"CONCEPT-OWNERS kind must be {CONCEPT_OWNERS_KIND}")
    universe = concept_map.get("universe")
    if not isinstance(universe, dict):
        errors.append("CONCEPT-OWNERS universe must be an object")
        universe = {}
    _exact_fields(
        universe,
        UNIVERSE_FIELDS,
        subject="CONCEPT-OWNERS universe",
        errors=errors,
    )
    canonical_ids = _string_list(
        universe.get("canonical_concept_ids"),
        subject="CONCEPT-OWNERS universe.canonical_concept_ids",
        errors=errors,
    )
    for concept_id in canonical_ids:
        if not _CONCEPT_ID_RE.fullmatch(concept_id):
            errors.append(f"invalid canonical concept ID: {concept_id}")
    if not isinstance(universe.get("freeze_id"), str) or not universe.get("freeze_id"):
        errors.append("CONCEPT-OWNERS universe.freeze_id must be non-empty")
    if universe.get("expansion_policy") != "explicit-revision-only":
        errors.append(
            "CONCEPT-OWNERS universe.expansion_policy must be explicit-revision-only"
        )

    concepts = concept_map.get("concept_owners")
    if not isinstance(concepts, dict) or not concepts:
        errors.append("CONCEPT-OWNERS concept_owners must be a non-empty object")
        concepts = {}
    if set(canonical_ids) != set(concepts):
        errors.append(
            "canonical concept universe differs from concept_owners keys: "
            f"universe={sorted(canonical_ids)}, owners={sorted(concepts)}"
        )

    truth_objects = truth_map.get("objects")
    truth_objects = truth_objects if isinstance(truth_objects, dict) else {}
    owners: dict[str, str] = {}
    valid_count = 0
    for concept_id, item in sorted(concepts.items()):
        before = len(errors)
        if not isinstance(item, dict):
            errors.append(f"concept_owners.{concept_id} must be an object")
            continue
        _exact_fields(
            item,
            CONCEPT_FIELDS,
            subject=f"concept_owners.{concept_id}",
            errors=errors,
        )
        owner = item.get("owner")
        if not isinstance(owner, str) or not owner:
            errors.append(f"concept_owners.{concept_id}.owner must be non-empty")
            owner = ""
        elif not _regular_file(
            _owner_module_path(project_root, owner),
            ref=owner,
            errors=errors,
        ):
            owner = ""
        if owner:
            owners[str(concept_id)] = owner
        if item.get("conformance_checker") != CHECK_COMMAND:
            errors.append(
                f"concept_owners.{concept_id}.conformance_checker must be {CHECK_COMMAND}"
            )
        for field in ("conflict_keys", "legacy_aliases", "forbidden_aliases"):
            _string_list(
                item.get(field),
                subject=f"concept_owners.{concept_id}.{field}",
                errors=errors,
                non_empty=(field == "conflict_keys"),
            )
        boundary = item.get("source_of_truth_boundary")
        prefix = "process/policies/SOURCE-OF-TRUTH-MAP.yaml#objects."
        if not isinstance(boundary, str) or not boundary.startswith(prefix):
            errors.append(
                f"concept_owners.{concept_id}.source_of_truth_boundary invalid"
            )
        else:
            object_id = boundary.removeprefix(prefix)
            truth_item = truth_objects.get(object_id)
            if not isinstance(truth_item, dict):
                errors.append(f"source-of-truth boundary missing: {boundary}")
            else:
                if truth_item.get("canonical_concept_id") != concept_id:
                    errors.append(f"source-of-truth boundary concept mismatch: {boundary}")
                if truth_item.get("owner") != owner:
                    errors.append(f"source-of-truth boundary owner mismatch: {boundary}")
                if truth_item.get("truth_role") != "machine_truth":
                    errors.append(f"source-of-truth boundary must be machine_truth: {boundary}")
                if truth_item.get("machine_truth") is not True:
                    errors.append(f"source-of-truth boundary machine_truth must be true: {boundary}")
                source_ref = truth_item.get("path")
                if not isinstance(source_ref, str) or not source_ref:
                    errors.append(f"source-of-truth boundary path missing: {boundary}")
                else:
                    source_path = (
                        _resolve_runtime_ref(project_root, source_ref)
                        if source_ref.startswith("process/")
                        else project_root / source_ref
                    )
                    _regular_file(source_path, ref=source_ref, errors=errors)
        matching_boundaries = [
            object_id
            for object_id, truth_item in truth_objects.items()
            if isinstance(truth_item, dict)
            and truth_item.get("canonical_concept_id") == concept_id
        ]
        if len(matching_boundaries) != 1:
            errors.append(
                f"canonical concept must have exactly one source boundary: "
                f"{concept_id} -> {sorted(matching_boundaries)}"
            )
        if len(errors) == before:
            valid_count += 1
    return canonical_ids, owners, valid_count


def validate_ownership(project_root: Path) -> dict[str, Any]:
    """在同一 source profile 下重算 owner 与 consumer coverage。"""

    root = project_root.resolve()
    errors: list[str] = []
    try:
        concept_path = _resolve_runtime_ref(root, CONCEPT_OWNERS_REL.as_posix())
        truth_path = _resolve_runtime_ref(root, SOURCE_OF_TRUTH_REL.as_posix())
        capability_path = _resolve_runtime_ref(
            root, CAPABILITY_REGISTRY_REL.as_posix()
        )
        feature_path = _resolve_runtime_ref(root, FEATURE_REGISTRY_REL.as_posix())
    except (OSError, ValueError) as exc:
        return {
            "schema_version": 1,
            "kind": CHECK_KIND,
            "decision": "BLOCKED",
            "errors": [str(exc)],
            "concept_coverage": {},
            "consumer_coverage": {},
            "detector": {},
            "sources": [],
            "source_fingerprint": "",
        }
    source_paths = [
        (CONCEPT_OWNERS_REL.as_posix(), concept_path),
        (SOURCE_OF_TRUTH_REL.as_posix(), truth_path),
        (CAPABILITY_REGISTRY_REL.as_posix(), capability_path),
        (FEATURE_REGISTRY_REL.as_posix(), feature_path),
        ("meta_flow/cli.py", root / "meta_flow/cli.py"),
        ("meta_flow/semantics/__init__.py", root / "meta_flow/semantics/__init__.py"),
        ("meta_flow/semantics/ownership.py", root / "meta_flow/semantics/ownership.py"),
        (
            "scripts/check_delivery_guardrails.py",
            root / "scripts/check_delivery_guardrails.py",
        ),
    ]
    concept_map = _load_source(
        concept_path, ref=CONCEPT_OWNERS_REL.as_posix(), errors=errors
    )
    truth_map = _load_source(
        truth_path, ref=SOURCE_OF_TRUTH_REL.as_posix(), errors=errors
    )
    capability_registry = _load_source(
        capability_path, ref=CAPABILITY_REGISTRY_REL.as_posix(), errors=errors
    )
    feature_registry = _load_source(
        feature_path, ref=FEATURE_REGISTRY_REL.as_posix(), errors=errors
    )

    canonical_ids, owners, valid_concepts = _validate_concepts(
        root,
        concept_map,
        truth_map,
        errors=errors,
    )
    outcome_disposition_report: dict[str, Any] = {}
    if "outcome-boundary" in canonical_ids:
        try:
            disposition_path = _resolve_runtime_ref(
                root, outcome.OUTCOME_CANDIDATE_DISPOSITIONS_REL.as_posix()
            )
            disposition_source_path = _resolve_runtime_ref(
                root, outcome.OUTCOME_CANDIDATE_SOURCE_REL.as_posix()
            )
            source_paths.extend(
                [
                    (
                        outcome.OUTCOME_CANDIDATE_DISPOSITIONS_REL.as_posix(),
                        disposition_path,
                    ),
                    (
                        outcome.OUTCOME_CANDIDATE_SOURCE_REL.as_posix(),
                        disposition_source_path,
                    ),
                ]
            )
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
        outcome_disposition_report = outcome.validate_candidate_dispositions(root)
        errors.extend(
            "outcome candidate disposition: " + str(error)
            for error in outcome_disposition_report.get("errors") or []
        )
    source_refs = {ref for ref, _path in source_paths}
    for owner in sorted(set(owners.values())):
        owner_ref = owner.replace(".", "/") + ".py"
        if owner_ref not in source_refs:
            source_paths.append((owner_ref, root / owner_ref))
            source_refs.add(owner_ref)
    canonical_id_set = set(canonical_ids)
    detector_profile = concept_map.get("detector_profile")
    if not isinstance(detector_profile, dict):
        errors.append("CONCEPT-OWNERS detector_profile must be an object")
        detector_profile = {}
    _exact_fields(
        detector_profile,
        DETECTOR_FIELDS,
        subject="CONCEPT-OWNERS detector_profile",
        errors=errors,
    )
    if (
        detector_profile.get("qualification")
        != "product-full-baseline-plus-incremental-hard-gate-v2"
    ):
        errors.append(
            "detector qualification must be product-full-baseline-plus-incremental-hard-gate-v2"
        )
    source_types = _string_list(
        detector_profile.get("source_types"),
        subject="detector_profile.source_types",
        errors=errors,
    )
    if source_types != list(DETECTOR_SOURCE_TYPES):
        errors.append(
            f"detector source_types must equal {list(DETECTOR_SOURCE_TYPES)}"
        )
    ast_roots = _string_list(
        detector_profile.get("ast_roots"),
        subject="detector_profile.ast_roots",
        errors=errors,
    )
    blind_spots = _string_list(
        detector_profile.get("known_blind_spots"),
        subject="detector_profile.known_blind_spots",
        errors=errors,
    )
    _integration_hard_gate_is_declared(root, errors)

    discovered = _discover_registry_consumers(
        capability_registry,
        feature_registry,
        canonical_ids=canonical_id_set,
        errors=errors,
    )
    ast_consumers, ast_stats = _discover_ast_consumers(
        root,
        ast_roots=ast_roots,
        owners=owners,
        errors=errors,
    )
    discovered.extend(ast_consumers)
    cli_path = root / "meta_flow/cli.py"
    if _cli_route_is_declared(cli_path):
        discovered.append(
            {
                "consumer_id": "cli-public-operation:meta-flow-check-governance-ownership",
                "kind": "cli-public-operation",
                "ref": CHECK_COMMAND,
                "candidate_concept_ids": ["governance-ownership"],
            }
        )
    else:
        errors.append(f"CLI route is missing or incomplete: {CHECK_COMMAND}")
    discovered.extend(_discover_boundary_consumers(truth_map, errors=errors))

    discovered_by_id: dict[str, dict[str, Any]] = {}
    duplicate_discovered: list[str] = []
    for consumer in discovered:
        consumer_id = str(consumer["consumer_id"])
        if consumer_id in discovered_by_id:
            duplicate_discovered.append(consumer_id)
        discovered_by_id[consumer_id] = consumer
    if duplicate_discovered:
        errors.append(
            f"detector produced duplicate consumer IDs: {sorted(set(duplicate_discovered))}"
        )

    raw_mappings = concept_map.get("consumer_mappings")
    if not isinstance(raw_mappings, list) or not raw_mappings:
        errors.append("CONCEPT-OWNERS consumer_mappings must be a non-empty list")
        raw_mappings = []
    mappings_by_id: dict[str, dict[str, Any]] = {}
    duplicate_mappings: list[str] = []
    for index, mapping in enumerate(raw_mappings, start=1):
        if not isinstance(mapping, dict):
            errors.append(f"consumer_mappings[{index}] must be an object")
            continue
        _exact_fields(
            mapping,
            MAPPING_FIELDS,
            subject=f"consumer_mappings[{index}]",
            errors=errors,
        )
        consumer_id = mapping.get("consumer_id")
        if not isinstance(consumer_id, str) or not consumer_id:
            errors.append(f"consumer_mappings[{index}].consumer_id must be non-empty")
            continue
        if consumer_id in mappings_by_id:
            duplicate_mappings.append(consumer_id)
        mappings_by_id[consumer_id] = mapping
        if mapping.get("concept_id") not in canonical_id_set:
            errors.append(
                f"consumer mapping references unknown concept: {consumer_id}"
            )
        if mapping.get("kind") not in DETECTOR_SOURCE_TYPES:
            errors.append(f"consumer mapping has unknown kind: {consumer_id}")
        if not isinstance(mapping.get("conformance_check"), str) or not mapping.get(
            "conformance_check"
        ):
            errors.append(f"consumer mapping conformance_check missing: {consumer_id}")
    if duplicate_mappings:
        errors.append(
            f"consumer mappings contain duplicate IDs: {sorted(set(duplicate_mappings))}"
        )

    discovered_ids = set(discovered_by_id)
    mapped_ids = set(mappings_by_id)
    unmapped = sorted(discovered_ids - mapped_ids)
    unknown_mapping_ids = sorted(mapped_ids - discovered_ids)
    unknown_concept_consumers = sorted(
        consumer_id
        for consumer_id, consumer in discovered_by_id.items()
        if any(
            concept_id not in canonical_id_set
            for concept_id in consumer.get("candidate_concept_ids") or []
        )
    )
    unknown = sorted(set(unknown_mapping_ids + unknown_concept_consumers))
    if unmapped:
        errors.append(f"discovered consumers are unmapped: {unmapped}")
    if unknown_mapping_ids:
        errors.append(
            "declared consumer mappings are not discovered: "
            f"{unknown_mapping_ids}"
        )
    valid_mapped: list[str] = []
    for consumer_id in sorted(discovered_ids & mapped_ids):
        consumer = discovered_by_id[consumer_id]
        mapping = mappings_by_id[consumer_id]
        candidate_ids = consumer.get("candidate_concept_ids")
        if not isinstance(candidate_ids, list) or len(candidate_ids) != 1:
            errors.append(
                f"consumer must resolve to exactly one candidate concept: "
                f"{consumer_id} -> {candidate_ids}"
            )
            continue
        if mapping.get("concept_id") != candidate_ids[0]:
            errors.append(f"consumer mapping concept mismatch: {consumer_id}")
            continue
        if mapping.get("kind") != consumer.get("kind"):
            errors.append(f"consumer mapping kind mismatch: {consumer_id}")
            continue
        if mapping.get("ref") != consumer.get("ref"):
            errors.append(f"consumer mapping ref mismatch: {consumer_id}")
            continue
        valid_mapped.append(consumer_id)

    sources: list[dict[str, str]] = []
    for ref, path in source_paths:
        if not _regular_file(path, ref=ref, errors=errors):
            continue
        sources.append({"ref": ref, "sha256": _digest_bytes(path.read_bytes())})
    source_fingerprint = _canonical_digest(sources) if len(sources) == len(source_paths) else ""
    concept_denominator = len(canonical_ids)
    consumer_denominator = len(discovered_by_id)
    concept_coverage = {
        "discovered": concept_denominator,
        "owned": valid_concepts,
        "multi_owner": 0,
        "unowned": max(concept_denominator - valid_concepts, 0),
        "unknown": len(unknown_concept_consumers),
        "percent": (
            100.0
            if concept_denominator > 0
            and valid_concepts == concept_denominator
            and not unknown_concept_consumers
            else 0.0
        ),
    }
    consumer_coverage = {
        "discovered": consumer_denominator,
        "mapped": len(valid_mapped),
        "unmapped": unmapped,
        "duplicate": sorted(set(duplicate_discovered + duplicate_mappings)),
        "unknown": unknown,
        "percent": (
            100.0
            if consumer_denominator > 0 and len(valid_mapped) == consumer_denominator
            else 0.0
        ),
    }
    if concept_denominator == 0:
        errors.append("concept coverage denominator must be greater than zero")
    if consumer_denominator == 0:
        errors.append("consumer coverage denominator must be greater than zero")
    if concept_coverage["percent"] != 100.0:
        errors.append("concept owner coverage must be 100%")
    if consumer_coverage["percent"] != 100.0:
        errors.append("consumer coverage must be 100%")

    return {
        "schema_version": 1,
        "kind": CHECK_KIND,
        "decision": "PASS" if not errors else "BLOCKED",
        "concept_coverage": concept_coverage,
        "consumer_coverage": consumer_coverage,
        "detector": {
            "profile_id": detector_profile.get("profile_id", ""),
            "qualification": detector_profile.get("qualification", ""),
            "source_types": source_types,
            "known_blind_spots": blind_spots,
            "ast": ast_stats,
        },
        "outcome_candidate_dispositions": outcome_disposition_report,
        "discovered_consumers": [
            discovered_by_id[consumer_id] for consumer_id in sorted(discovered_by_id)
        ],
        "sources": sources,
        "source_fingerprint": source_fingerprint,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=CHECK_COMMAND)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parsed = parser.parse_args(argv or [])
    report = validate_ownership(parsed.project_root)
    if parsed.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "Governance Ownership Check: "
            + ("OK" if report["decision"] == "PASS" else "FAIL")
        )
        concept = report.get("concept_coverage") or {}
        consumer = report.get("consumer_coverage") or {}
        print(
            "- concept_owner_coverage: "
            f"{concept.get('owned', 0)}/{concept.get('discovered', 0)} "
            f"({concept.get('percent', 0.0):.1f}%)"
        )
        print(
            "- consumer_coverage: "
            f"{consumer.get('mapped', 0)}/{consumer.get('discovered', 0)} "
            f"({consumer.get('percent', 0.0):.1f}%)"
        )
        print(f"- source_fingerprint: {report.get('source_fingerprint') or '-'}")
        for error in report.get("errors") or []:
            print(f"- ERROR: {error}")
    return 0 if report["decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
