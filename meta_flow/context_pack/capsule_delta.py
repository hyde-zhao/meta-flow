"""Work/CR revision 的 base + stage delta capsule 契约。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PureWindowsPath
from typing import Any

from meta_flow.project.read_contract import is_safe_read_ref

CAPSULE_SCHEMA_VERSION = 1
CAPSULE_STAGES = ("clarification", "design", "implementation", "verification")
MAX_CAPSULE_CHAIN_DEPTH = 5
DELETE_MARKER = {"$capsule_delete": True}


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _validate_no_absolute_paths(value: Any, *, location: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) == "resolved_path":
                raise ValueError(f"capsule cannot persist resolved_path at {location}")
            _validate_no_absolute_paths(item, location=f"{location}.{key}")
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _validate_no_absolute_paths(item, location=f"{location}[{index}]")
        return
    if isinstance(value, str) and (
        Path(value).is_absolute() or PureWindowsPath(value).is_absolute()
    ):
        raise ValueError(f"capsule cannot persist an absolute path at {location}")


def _safe_refs(refs: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    if not all(is_safe_read_ref(ref) for ref in refs):
        raise ValueError(f"{field} must contain safe logical refs")
    if len(set(refs)) != len(refs):
        raise ValueError(f"{field} contains duplicate refs")
    return refs


def create_capsule_base(
    *,
    owner_kind: str,
    owner_id: str,
    revision: str,
    fields: Mapping[str, Any],
    evidence_refs: tuple[str, ...],
) -> dict[str, Any]:
    if owner_kind not in {"work", "cr"}:
        raise ValueError("capsule owner_kind must be work or cr")
    if not owner_id or not revision:
        raise ValueError("capsule owner_id and revision are required")
    copied_fields = dict(fields)
    _validate_no_absolute_paths(copied_fields)
    refs = _safe_refs(evidence_refs, field="evidence_refs")
    semantic = {
        "schema_version": CAPSULE_SCHEMA_VERSION,
        "kind": "CapsuleBaseV1",
        "owner_kind": owner_kind,
        "owner_id": owner_id,
        "revision": revision,
        "stage": "base",
        "fields": copied_fields,
        "evidence_refs": list(refs),
    }
    return {**semantic, "semantic_digest": _digest(semantic)}


def diff_capsule_fields(
    parent_fields: Mapping[str, Any], current_fields: Mapping[str, Any]
) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    for key in sorted(set(parent_fields) | set(current_fields)):
        if key not in current_fields:
            changed[key] = DELETE_MARKER.copy()
        elif key not in parent_fields or parent_fields[key] != current_fields[key]:
            changed[key] = current_fields[key]
    _validate_no_absolute_paths(changed)
    return changed


def create_capsule_delta(
    *,
    owner_kind: str,
    owner_id: str,
    revision: str,
    parent_ref: str,
    parent_digest: str,
    stage: str,
    changed_fields: Mapping[str, Any],
    stage_evidence: tuple[str, ...],
) -> dict[str, Any]:
    if owner_kind not in {"work", "cr"}:
        raise ValueError("capsule owner_kind must be work or cr")
    if not owner_id or not revision:
        raise ValueError("capsule owner_id and revision are required")
    if not is_safe_read_ref(parent_ref):
        raise ValueError("capsule parent_ref must be one safe logical ref")
    if len(parent_digest) != 64 or any(char not in "0123456789abcdef" for char in parent_digest):
        raise ValueError("capsule parent_digest must be one lowercase sha256")
    if stage not in CAPSULE_STAGES:
        raise ValueError("capsule delta stage is unsupported")
    copied = dict(changed_fields)
    if not copied:
        raise ValueError("capsule delta changed_fields must be non-empty")
    _validate_no_absolute_paths(copied)
    refs = _safe_refs(stage_evidence, field="stage_evidence")
    if not refs:
        raise ValueError("capsule delta requires stage evidence")
    semantic = {
        "schema_version": CAPSULE_SCHEMA_VERSION,
        "kind": "CapsuleDeltaV1",
        "owner_kind": owner_kind,
        "owner_id": owner_id,
        "revision": revision,
        "parent_ref": parent_ref,
        "parent_digest": parent_digest,
        "stage": stage,
        "changed_fields": copied,
        "stage_evidence": list(refs),
    }
    return {**semantic, "semantic_digest": _digest(semantic)}


def validate_capsule_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    kind = payload.get("kind")
    semantic = dict(payload)
    digest = semantic.pop("semantic_digest", None)
    if payload.get("schema_version") != CAPSULE_SCHEMA_VERSION:
        errors.append("capsule schema_version must be 1")
    if kind not in {"CapsuleBaseV1", "CapsuleDeltaV1"}:
        errors.append("capsule kind is unsupported")
    if digest != _digest(semantic):
        errors.append("capsule semantic_digest mismatch")
    try:
        _validate_no_absolute_paths(payload)
    except ValueError as exc:
        errors.append(str(exc))
    return errors


@dataclass(frozen=True)
class ComposedCapsule:
    owner_kind: str
    owner_id: str
    revision: str
    stage: str
    fields: dict[str, Any]
    evidence_refs: tuple[str, ...]
    chain_refs: tuple[str, ...]
    semantic_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "fields": self.fields.copy(),
            "evidence_refs": list(self.evidence_refs),
            "chain_refs": list(self.chain_refs),
        }


def compose_capsule(
    tip_ref: str,
    loader: Callable[[str], Mapping[str, Any]],
) -> ComposedCapsule:
    if not is_safe_read_ref(tip_ref):
        raise ValueError("capsule tip_ref must be one safe logical ref")
    reverse_chain: list[tuple[str, dict[str, Any]]] = []
    visited: set[str] = set()
    current_ref = tip_ref
    while True:
        if current_ref in visited:
            raise ValueError("capsule chain contains a cycle")
        visited.add(current_ref)
        try:
            payload = dict(loader(current_ref))
        except (KeyError, OSError) as exc:
            raise ValueError(f"capsule parent is missing: {current_ref}") from exc
        errors = validate_capsule_payload(payload)
        if errors:
            raise ValueError("; ".join(errors))
        reverse_chain.append((current_ref, payload))
        if len(reverse_chain) > MAX_CAPSULE_CHAIN_DEPTH:
            raise ValueError("capsule chain exceeds maximum depth; materialize a new base")
        if payload["kind"] == "CapsuleBaseV1":
            break
        current_ref = str(payload["parent_ref"])

    chain = list(reversed(reverse_chain))
    base_ref, base = chain[0]
    fields = dict(base["fields"])
    evidence = list(base["evidence_refs"])
    owner = (base["owner_kind"], base["owner_id"], base["revision"])
    previous_stage_index = -1
    previous_digest = str(base["semantic_digest"])
    previous_ref = base_ref
    stage = "base"
    for ref, delta in chain[1:]:
        if (delta["owner_kind"], delta["owner_id"], delta["revision"]) != owner:
            raise ValueError("capsule delta crosses owner or revision")
        if delta["parent_ref"] != previous_ref or delta["parent_digest"] != previous_digest:
            raise ValueError("capsule parent ref or digest drift")
        stage_index = CAPSULE_STAGES.index(str(delta["stage"]))
        if stage_index <= previous_stage_index:
            raise ValueError("capsule stage order is invalid")
        for key, value in delta["changed_fields"].items():
            if value == DELETE_MARKER:
                fields.pop(key, None)
            else:
                fields[key] = value
        evidence.extend(delta["stage_evidence"])
        previous_stage_index = stage_index
        previous_digest = str(delta["semantic_digest"])
        previous_ref = ref
        stage = str(delta["stage"])
    semantic = {
        "owner_kind": owner[0],
        "owner_id": owner[1],
        "revision": owner[2],
        "stage": stage,
        "fields": fields,
        "evidence_refs": evidence,
    }
    return ComposedCapsule(
        owner[0],
        owner[1],
        owner[2],
        stage,
        fields,
        tuple(evidence),
        tuple(ref for ref, _payload in chain),
        _digest(semantic),
    )


def materialize_capsule_base(composed: ComposedCapsule) -> dict[str, Any]:
    return create_capsule_base(
        owner_kind=composed.owner_kind,
        owner_id=composed.owner_id,
        revision=composed.revision,
        fields=composed.fields,
        evidence_refs=composed.evidence_refs,
    )
