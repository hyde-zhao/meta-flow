"""R12 schema/reference lifecycle：兼容读取、引用可达性与合法处置判定。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.project.model import is_safe_ref
from meta_flow.project.process_route import require_process_route
from meta_flow.project.scale import load_yaml_object

PUBLIC_OPERATION_DECLARATIONS = (
    ("reference-lifecycle.check", ("meta-flow", "check", "reference-lifecycle")),
)
CANDIDATES_REL = Path("policies/REFERENCE-LIFECYCLE-CANDIDATES.json")
TERMINAL_STATUSES = {"completed", "cancelled", "closed", "superseded", "archived"}
STRUCTURED_SOURCE_PATTERNS = (
    "PROJECT.yaml",
    "ROADMAP.yaml",
    "phases/*/PHASE.yaml",
    "works/*/WORK.yaml",
    "docs/design/CONCEPT-OWNERS.yaml",
    "docs/design/CAPABILITY-REGISTRY.yaml",
    "policies/SOURCE-OF-TRUTH-MAP.yaml",
)
REFERENCE_ROOTS = {
    "changes",
    "context",
    "current",
    "docs",
    "evidence",
    "governance",
    "phases",
    "policies",
    "returns",
    "state",
    "stories",
    "works",
}
ROOT_REFERENCE_FILES = {"PROJECT.yaml", "ROADMAP.yaml", "DEVELOPMENT-PLAN.yaml", "STATE.md"}


@dataclass(frozen=True, slots=True)
class ReferenceCandidateV1:
    ref: str
    requested_disposition: str
    lifecycle_status: str
    rebuildable: bool
    evidence_refs: tuple[str, ...]
    redirect_proven: bool = False

    def __post_init__(self) -> None:
        if not is_safe_ref(self.ref):
            raise ValueError("reference candidate ref is unsafe")
        if self.requested_disposition not in {"retain", "archive", "delete"}:
            raise ValueError("requested_disposition must be retain/archive/delete")
        if not self.lifecycle_status:
            raise ValueError("reference candidate lifecycle_status is required")
        if not self.evidence_refs:
            raise ValueError("reference candidate evidence_refs must not be empty")


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _walk_strings(nested)
    elif isinstance(value, list | tuple):
        for nested in value:
            yield from _walk_strings(nested)
    elif isinstance(value, str):
        yield value


def _structured_sources(process_root: Path) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for pattern in STRUCTURED_SOURCE_PATTERNS:
        paths.update(process_root.glob(pattern))
    return tuple(
        sorted(
            path for path in paths if path.exists() or path.is_symlink()
        )
    )


def build_reference_index(
    process_root: Path,
    *,
    findings: list[str] | None = None,
) -> dict[str, tuple[str, ...]]:
    """从有界 canonical structured sources 建 inbound index，不扫 prose。"""

    root = process_root.resolve()
    inbound: dict[str, set[str]] = {}
    for source in _structured_sources(root):
        source_ref = source.relative_to(root).as_posix()
        if source.is_symlink() or not source.is_file():
            if findings is not None:
                findings.append(f"REFERENCE_SOURCE_NOT_REGULAR:{source_ref}")
            continue
        try:
            payload = load_yaml_object(source)
        except (OSError, ValueError) as exc:
            if findings is not None:
                findings.append(
                    f"REFERENCE_SOURCE_PARSE_FAILED:{source_ref}:{type(exc).__name__}"
                )
            continue
        for value in _walk_strings(payload):
            normalized = value.removeprefix("process/")
            parts = Path(normalized).parts
            if (
                len(normalized) > 512
                or not is_safe_ref(normalized)
                or not parts
                or any(len(part) > 240 for part in parts)
                or (
                    normalized not in ROOT_REFERENCE_FILES
                    and parts[0] not in REFERENCE_ROOTS
                )
                or Path(normalized).suffix.lower()
                not in {".json", ".md", ".ndjson", ".yaml", ".yml"}
            ):
                continue
            inbound.setdefault(normalized, set()).add(source_ref)
    return {ref: tuple(sorted(sources)) for ref, sources in sorted(inbound.items())}


def _canonical_protected_refs(
    process_root: Path,
    *,
    findings: list[str] | None = None,
) -> set[str]:
    protected = {"PROJECT.yaml", "ROADMAP.yaml", "policies/SOURCE-OF-TRUTH-MAP.yaml"}
    for source in _structured_sources(process_root):
        ref = source.relative_to(process_root).as_posix()
        if ref.startswith("phases/") or ref in {
            "docs/design/CONCEPT-OWNERS.yaml",
            "docs/design/CAPABILITY-REGISTRY.yaml",
        }:
            protected.add(ref)
    truth_map = process_root / "policies/SOURCE-OF-TRUTH-MAP.yaml"
    if truth_map.is_file() and not truth_map.is_symlink():
        try:
            payload = load_yaml_object(truth_map)
            objects = payload.get("objects")
            if not isinstance(objects, dict):
                raise ValueError("source-of-truth map objects must be an object")
            for item in objects.values():
                if isinstance(item, dict):
                    path = str(item.get("path") or "").removeprefix("process/")
                    if is_safe_ref(path) and (process_root / path).exists():
                        protected.add(path)
        except (OSError, ValueError) as exc:
            if findings is not None:
                findings.append(
                    "REFERENCE_TRUTH_MAP_PARSE_FAILED:"
                    f"policies/SOURCE-OF-TRUTH-MAP.yaml:{type(exc).__name__}"
                )
    return protected


def classify_reference_candidate(
    process_root: Path,
    candidate: ReferenceCandidateV1,
    *,
    inbound_index: Mapping[str, tuple[str, ...]] | None = None,
    protected_refs: set[str] | None = None,
) -> dict[str, Any]:
    root = process_root.resolve()
    path = root / candidate.ref
    inbound = tuple((inbound_index or build_reference_index(root)).get(candidate.ref, ()))
    protected = candidate.ref in (
        protected_refs
        if protected_refs is not None
        else _canonical_protected_refs(root)
    )
    regular = path.is_file() and not path.is_symlink()
    terminal = candidate.lifecycle_status in TERMINAL_STATUSES
    orphan = not inbound
    blockers: list[str] = []
    if not regular:
        blockers.append("REFERENCE_TARGET_NOT_REGULAR")
    for evidence_ref in candidate.evidence_refs:
        normalized = evidence_ref.removeprefix("process/")
        evidence = root / normalized
        if not is_safe_ref(normalized) or evidence.is_symlink() or not evidence.is_file():
            blockers.append(f"REFERENCE_EVIDENCE_MISSING:{evidence_ref}")
    archive_eligible = (
        regular
        and terminal
        and not protected
        and (orphan or candidate.redirect_proven)
    )
    delete_eligible = archive_eligible and orphan and candidate.rebuildable
    if candidate.requested_disposition == "archive" and not archive_eligible:
        blockers.append("REFERENCE_ARCHIVE_NOT_ELIGIBLE")
    if candidate.requested_disposition == "delete" and not delete_eligible:
        blockers.append("REFERENCE_DELETE_NOT_ELIGIBLE")
    decision = "BLOCKED" if blockers else "PASS"
    payload = {
        "ref": candidate.ref,
        "decision": decision,
        "requested_disposition": candidate.requested_disposition,
        "lifecycle_status": candidate.lifecycle_status,
        "regular": regular,
        "canonical_protected": protected,
        "executable": bool(inbound),
        "executable_basis": "canonical-structured-inbound",
        "orphan": orphan,
        "inbound_refs": list(inbound),
        "archive_eligible": archive_eligible,
        "delete_eligible": delete_eligible,
        "rebuildable": candidate.rebuildable,
        "redirect_proven": candidate.redirect_proven,
        "blockers": sorted(set(blockers)),
    }
    payload["classification_digest"] = canonical_digest(payload)
    return payload


def _load_candidates(process_root: Path) -> tuple[tuple[ReferenceCandidateV1, ...], list[str]]:
    path = process_root / CANDIDATES_REL
    if path.is_symlink() or not path.is_file():
        return (), ["reference lifecycle candidate manifest is missing or not regular"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (), [f"reference lifecycle candidate manifest invalid: {exc}"]
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "kind",
        "candidates",
    }:
        return (), ["reference lifecycle candidate manifest fields mismatch"]
    schema_version = payload.get("schema_version")
    expected_kind = {
        1: "ReferenceLifecycleCandidatesV1",
        2: "ReferenceLifecycleCandidatesV2",
    }.get(schema_version)
    if expected_kind is None or payload.get("kind") != expected_kind:
        return (), ["reference lifecycle candidate manifest kind/version mismatch"]
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        return (), ["reference lifecycle candidates must be a list"]
    expected = {
        "ref",
        "requested_disposition",
        "lifecycle_status",
        "rebuildable",
        "evidence_refs",
    }
    expected_v2 = {*expected, "redirect_proven"}
    candidates: list[ReferenceCandidateV1] = []
    errors: list[str] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict) or set(raw) != (
            expected_v2 if schema_version == 2 else expected
        ):
            errors.append("reference lifecycle candidate fields mismatch")
            continue
        try:
            if type(raw["rebuildable"]) is not bool:
                raise ValueError("reference candidate rebuildable must be a boolean")
            if schema_version == 2 and type(raw["redirect_proven"]) is not bool:
                raise ValueError("reference candidate redirect_proven must be a boolean")
            if not isinstance(raw["evidence_refs"], list) or not all(
                isinstance(ref, str) for ref in raw["evidence_refs"]
            ):
                raise ValueError("reference candidate evidence_refs must be strings")
            candidates.append(
                ReferenceCandidateV1(
                    ref=str(raw["ref"]),
                    requested_disposition=str(raw["requested_disposition"]),
                    lifecycle_status=str(raw["lifecycle_status"]),
                    rebuildable=raw["rebuildable"],
                    evidence_refs=tuple(str(ref) for ref in raw["evidence_refs"]),
                    redirect_proven=(
                        raw["redirect_proven"] if schema_version == 2 else False
                    ),
                )
            )
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
    if len({candidate.ref for candidate in candidates}) != len(candidates):
        errors.append("reference lifecycle candidate refs must be unique")
    return tuple(candidates), errors


def check_reference_lifecycle(project_root: Path) -> dict[str, Any]:
    route = require_process_route(project_root.resolve())
    candidates, errors = _load_candidates(route.process_root)
    inbound = build_reference_index(route.process_root, findings=errors)
    protected = _canonical_protected_refs(route.process_root, findings=errors)
    results = [
        classify_reference_candidate(
            route.process_root,
            candidate,
            inbound_index=inbound,
            protected_refs=protected,
        )
        for candidate in candidates
    ]
    errors.extend(
        f"{result['ref']}:{blocker}"
        for result in results
        for blocker in result["blockers"]
    )
    dynamic_refs = sorted(ref for ref in inbound if _is_dynamic_ref(ref))
    broken_refs = sorted(
        ref
        for ref in inbound
        if not _is_dynamic_ref(ref)
        and not _reference_exists(route.process_root, route.project_root, ref)
    )
    broken_dispositions: list[dict[str, Any]] = []
    unresolved_broken_refs: list[str] = []
    for ref in broken_refs:
        sources = inbound[ref]
        if sources and all(
            _terminal_work_source(route.process_root, source_ref)
            for source_ref in sources
        ):
            broken_dispositions.append(
                {
                    "ref": ref,
                    "disposition": "retained-terminal-source-history-gap",
                    "source_refs": list(sources),
                    "reason": (
                        "all canonical inbound sources are terminal Work snapshots; "
                        "the absent target is retained as explicit immutable history, "
                        "not treated as executable current state"
                    ),
                }
            )
        else:
            unresolved_broken_refs.append(ref)
    errors.extend(f"BROKEN_INBOUND_REF:{ref}" for ref in unresolved_broken_refs)
    payload = {
        "schema_version": 1,
        "kind": "ReferenceLifecycleReportV1",
        "decision": "BLOCKED" if errors else "PASS",
        "candidate_count": len(candidates),
        "reference_index": {
            "indexed_ref_count": len(inbound),
            "broken_inbound_refs": broken_refs,
            "broken_inbound_dispositions": broken_dispositions,
            "unresolved_broken_inbound_refs": unresolved_broken_refs,
            "dynamic_inbound_refs": dynamic_refs,
            "parse_failure_count": len(
                [
                    error
                    for error in errors
                    if error.startswith("REFERENCE_SOURCE_PARSE_FAILED:")
                    or error.startswith("REFERENCE_TRUTH_MAP_PARSE_FAILED:")
                ]
            ),
        },
        "classifications": results,
        "errors": sorted(set(errors)),
        "mutation_count": 0,
    }
    payload["report_digest"] = canonical_digest(payload)
    return payload


def _safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _is_dynamic_ref(ref: str) -> bool:
    return any(token in ref for token in ("*", "?", "[", "]", "<", ">"))


def _reference_exists(process_root: Path, project_root: Path, ref: str) -> bool:
    if ref.startswith("release/"):
        return _safe_exists(project_root / ref.removeprefix("release/"))
    return _safe_exists(process_root / ref) or _safe_exists(project_root / ref)


def _terminal_work_source(process_root: Path, source_ref: str) -> bool:
    if not source_ref.startswith("works/") or not source_ref.endswith("/WORK.yaml"):
        return False
    path = process_root / source_ref
    if path.is_symlink() or not path.is_file():
        return False
    try:
        payload = load_yaml_object(path)
    except (OSError, ValueError):
        return False
    return str(payload.get("status") or "").lower() in TERMINAL_STATUSES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow check reference-lifecycle")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parsed = parser.parse_args(argv or [])
    try:
        report = check_reference_lifecycle(parsed.project_root)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "errors": [str(exc)]}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["decision"] == "PASS" else 1


__all__ = [
    "ReferenceCandidateV1",
    "build_reference_index",
    "check_reference_lifecycle",
    "classify_reference_candidate",
]
