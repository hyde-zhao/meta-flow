"""Phase ``result_refs`` 的 typed、可恢复原生事务。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.project.governance import load_phase, load_roadmap, validate_phase_payload
from meta_flow.project.governance_projection import (
    GOVERNANCE_PROJECTION_KIND,
    GOVERNANCE_PROJECTION_REL,
    build_governance_projection_for_phase_postimage,
    render_governance_projection,
    validate_governance_projection,
)
from meta_flow.project.model import load_project
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.state import current
from meta_flow.state.formal_projection import (
    build_formal_truth_snapshot,
    derive_formal_truth_patch,
)
from meta_flow.state.projection_transaction import (
    TransactionLockHandle,
    acquire_transaction_lock,
    apply_state_projection_transaction,
    atomic_replace_bytes,
    claim_transaction_lock,
    ensure_transaction_directory,
    inspect_state_projection_transaction,
    recover_state_projection_transaction,
    release_transaction_lock,
    state_projection_lock_path,
    transaction_lock_identity,
    validate_transaction_lock,
)
from meta_flow.work.lifecycle_transaction import (
    acquire_shared_projection_writer_lock,
    assert_work_close_shared_projection_lineage,
    discard_shared_projection_successor,
    plan_shared_projection_successor_preflight,
    record_shared_projection_successor,
    release_shared_projection_writer_lock,
)
from meta_flow.work.model import Work, load_work
from meta_flow.work.scope import check_scope

PUBLIC_OPERATION_DECLARATIONS = (
    ("project.phase-metadata", ("meta-flow", "project", "phase-metadata")),
)

PLAN_KIND = "PhaseMetadataPlanV1"
AUTHORIZATION_KIND = "PhaseMetadataAuthorizationV1"
RECEIPT_KIND = "PhaseMetadataReceiptV1"
TRANSACTION_KIND = "PhaseMetadataTransactionV1"
OPERATION = "project.phase-metadata"
TRANSACTION_ROOT_REL = Path(".meta-flow-runtime/phase-metadata")
MANIFEST_REL = TRANSACTION_ROOT_REL / "transaction.json"
LOCK_REL = TRANSACTION_ROOT_REL / "writer.lock"
TERMINAL_STATES = frozenset({"COMMITTED", "RECOVERED"})
STATE_TARGET_REFS = frozenset(
    {
        "process/state/STATE.current.json",
        "process/STATE.md",
        "process/current/CURRENT.json",
    }
)
FIXED_TARGET_REFS = frozenset(
    {
        "process/governance/GOVERNANCE-BASELINE.json",
        *STATE_TARGET_REFS,
    }
)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PhaseMetadataPartialError(RuntimeError):
    """事务无法完全回滚时携带真实剩余 mutation。"""

    def __init__(self, result: Mapping[str, Any]) -> None:
        super().__init__("Phase metadata transaction entered PARTIAL")
        self.result = dict(result)


def _digest(value: bytes | None) -> str:
    return "missing" if value is None else hashlib.sha256(value).hexdigest()


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _head_oid(root: Path, *, repository: str, errors: list[str]) -> str:
    result = _git(root, "rev-parse", "--verify", "HEAD")
    oid = result.stdout.strip().lower()
    if result.returncode != 0 or not _OID_RE.fullmatch(oid):
        errors.append(f"{repository} repository HEAD is unavailable")
        return ""
    return oid


def _repository_facts(release_root: Path, process_root: Path) -> tuple[dict[str, Any], str]:
    facts: dict[str, Any] = {}
    for name, root in (("release", release_root), ("process", process_root)):
        status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
        if status.returncode != 0:
            raise ValueError(f"{name} repository status is unavailable")
        lines = sorted(
            line.rstrip()
            for line in status.stdout.splitlines()
            if line.strip() and not _runtime_status_line(line)
        )
        facts[name] = {
            "head": _git(root, "rev-parse", "--verify", "HEAD").stdout.strip().lower(),
            "dirty_path_count": len(lines),
            "dirty_path_set_digest": _canonical_digest(lines),
        }
    return facts, _canonical_digest(facts)


def _runtime_status_line(line: str) -> bool:
    """排除 native coordination runtime；它不是授权的 Git domain candidate。"""

    payload = line[3:] if len(line) >= 4 else line
    paths = tuple(part.strip().strip('"') for part in payload.split(" -> "))
    return bool(paths) and all(path.startswith(".meta-flow-runtime/") for path in paths)


def _logical_ref(value: str, *, prefix: str | None = None) -> tuple[str, str]:
    text = str(value or "").strip()
    path = Path(text)
    if (
        not text.startswith("process/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Phase metadata refs must use safe process/... logical paths")
    relative = Path(*path.parts[1:]).as_posix()
    if prefix is not None and not relative.startswith(prefix + "/"):
        raise ValueError(f"Phase metadata ref must be under process/{prefix}/")
    return text, relative


def _phase_logical_ref(value: str) -> tuple[str, str]:
    logical, relative = _logical_ref(value, prefix="phases")
    parts = Path(relative).parts
    if len(parts) != 3 or parts[-1] != "PHASE.yaml":
        raise ValueError("Phase metadata target must be process/phases/<id>/PHASE.yaml")
    return logical, relative


def _target_path(process_root: Path, logical_ref: str) -> Path:
    _logical, relative = _logical_ref(logical_ref)
    root = process_root.resolve()
    path = (root / relative).resolve(strict=False)
    if not path.is_relative_to(root):
        raise ValueError(f"Phase metadata target escapes process repository: {logical_ref}")
    return path


def _read_bytes(path: Path) -> bytes | None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Phase metadata target is not a regular file: {path}")
    return path.read_bytes() if path.is_file() else None


def _render_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _render_yaml(payload: Mapping[str, Any]) -> bytes:
    return (dump_yaml(dict(payload)) + "\n").encode("utf-8")


def _validate_effective_at(value: str) -> str:
    if not value:
        raise ValueError("--effective-at is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("effective_at must be one ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("effective_at must include an explicit timezone")
    return value


def _safe_id(value: str, *, subject: str) -> str:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{subject} is invalid")
    return value


def _scope_allows(work: Work, operation: str, refs: tuple[str, ...]) -> list[str]:
    return [
        f"Work scope denies {operation}: {ref}"
        for ref in refs
        if not check_scope(work.scope, operation, ref).allowed
    ]


def _validate_append_evidence(
    process_root: Path,
    *,
    target_phase_ref: str,
    authorizing_work_id: str,
    append_ref: str,
) -> list[str]:
    errors: list[str] = []
    path = process_root.resolve() / append_ref
    if path.is_symlink() or not path.is_file():
        return [f"Phase result evidence is missing or not regular: process/{append_ref}"]
    if path.stat().st_size <= 0 or path.stat().st_size > 1024 * 1024:
        errors.append(f"Phase result evidence size is invalid: process/{append_ref}")
    try:
        payload = load_yaml_object(path)
    except (OSError, ValueError) as exc:
        errors.append(f"Phase result evidence is not a machine object: process/{append_ref}: {exc}")
        return errors
    if append_ref == GOVERNANCE_PROJECTION_REL.as_posix():
        if payload.get("kind") != GOVERNANCE_PROJECTION_KIND:
            errors.append(
                "governance baseline result ref does not identify the canonical projection"
            )
        return errors
    if payload.get("schema_version") != 1 or not isinstance(payload.get("kind"), str):
        errors.append(f"Phase result evidence kind/schema is invalid: {append_ref}")
    parts = Path(append_ref).parts
    if len(parts) < 3 or parts[0] != "works":
        errors.append(
            "Phase metadata only accepts canonical governance baseline or evidence owned by a closed Work"
        )
        return errors
    owner_work_id = parts[1]
    if owner_work_id == authorizing_work_id:
        errors.append("Phase metadata cannot replace the current Work close/result contract")
        return errors
    try:
        owner = load_work(process_root, owner_work_id)
    except (OSError, ValueError) as exc:
        errors.append(f"Phase result evidence owner Work is unreadable: {owner_work_id}: {exc}")
        return errors
    if owner.status != "completed":
        errors.append(f"Phase result evidence owner Work must be completed: {owner_work_id}")
    if owner.phase_ref != target_phase_ref:
        errors.append(f"Phase result evidence owner Work belongs to another Phase: {owner_work_id}")
    if not check_scope(owner.scope, "write", append_ref).allowed:
        errors.append(f"Phase result evidence is outside owner Work scope: process/{append_ref}")
    payload_work_id = str(payload.get("work_id") or "")
    if payload_work_id != owner_work_id:
        errors.append(f"Phase result evidence work_id differs from owner Work: {append_ref}")
    decision = str(payload.get("decision") or "")
    if decision not in {"PASS", "PASS_WITH_RISK"}:
        errors.append(f"Phase result evidence decision is not admissible: {append_ref}:{decision}")
    return errors


@dataclass(frozen=True, slots=True)
class PhaseMetadataAuthorizationV1:
    schema_version: int
    kind: str
    authorization_id: str
    project_id: str
    work_id: str
    phase_ref: str
    append_result_refs: tuple[str, ...]
    scope_digest: str
    plan_digest: str
    target_refs: tuple[str, ...]
    target_set_digest: str
    repository_facts_digest: str
    release_oid: str
    process_oid: str
    expires_at: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> PhaseMetadataAuthorizationV1:
        expected = {
            "schema_version",
            "kind",
            "authorization_id",
            "project_id",
            "work_id",
            "phase_ref",
            "append_result_refs",
            "scope_digest",
            "plan_digest",
            "target_refs",
            "target_set_digest",
            "repository_facts_digest",
            "release_oid",
            "process_oid",
            "expires_at",
        }
        if set(payload) != expected:
            raise ValueError("Phase metadata authorization fields mismatch")
        append_refs = payload["append_result_refs"]
        target_refs = payload["target_refs"]
        if (
            not isinstance(append_refs, list)
            or not append_refs
            or not all(isinstance(ref, str) for ref in append_refs)
            or len(append_refs) != len(set(append_refs))
        ):
            raise ValueError("append_result_refs must be a non-empty unique string list")
        if (
            not isinstance(target_refs, list)
            or not target_refs
            or not all(isinstance(ref, str) for ref in target_refs)
            or len(target_refs) != len(set(target_refs))
        ):
            raise ValueError("target_refs must be a non-empty unique string list")
        return cls(
            schema_version=int(payload["schema_version"]),
            kind=str(payload["kind"]),
            authorization_id=_safe_id(str(payload["authorization_id"]), subject="authorization_id"),
            project_id=str(payload["project_id"]),
            work_id=_safe_id(str(payload["work_id"]), subject="work_id"),
            phase_ref=str(payload["phase_ref"]),
            append_result_refs=tuple(str(ref) for ref in append_refs),
            scope_digest=str(payload["scope_digest"]),
            plan_digest=str(payload["plan_digest"]),
            target_refs=tuple(str(ref) for ref in target_refs),
            target_set_digest=str(payload["target_set_digest"]),
            repository_facts_digest=str(payload["repository_facts_digest"]),
            release_oid=str(payload["release_oid"]),
            process_oid=str(payload["process_oid"]),
            expires_at=str(payload["expires_at"]),
        )

    def validate_for(self, plan: PhaseMetadataPlan) -> None:
        if self.schema_version != 1 or self.kind != AUTHORIZATION_KIND:
            raise ValueError("Phase metadata authorization kind/version mismatch")
        expected = (
            plan.project_id,
            plan.work_id,
            plan.phase_ref,
            plan.append_result_refs,
            plan.scope_digest,
            plan.plan_digest,
            tuple(sorted(plan.targets)),
            plan.target_set_digest,
            plan.repository_facts_digest,
            plan.release_oid,
            plan.process_oid,
        )
        actual = (
            self.project_id,
            self.work_id,
            self.phase_ref,
            self.append_result_refs,
            self.scope_digest,
            self.plan_digest,
            self.target_refs,
            self.target_set_digest,
            self.repository_facts_digest,
            self.release_oid,
            self.process_oid,
        )
        if actual != expected:
            raise ValueError("Phase metadata authorization does not bind the current plan")
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Phase metadata authorization expires_at is invalid") from exc
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("Phase metadata authorization is expired")


@dataclass(frozen=True)
class PhaseMetadataPlan:
    release_root: Path
    process_root: Path
    project_id: str
    work_id: str
    phase_ref: str
    append_result_refs: tuple[str, ...]
    scope_digest: str
    effective_at: str
    release_oid: str
    process_oid: str
    repository_facts: Mapping[str, Any]
    repository_facts_digest: str
    targets: Mapping[str, bytes]
    preimages: Mapping[str, str]
    target_set_digest: str
    decision: str
    errors: tuple[str, ...]
    plan_digest: str

    @property
    def changed_refs(self) -> list[str]:
        return sorted(
            ref for ref, after in self.targets.items() if self.preimages.get(ref) != _digest(after)
        )

    def as_dict(self) -> dict[str, Any]:
        changed = self.changed_refs if self.decision != "BLOCKED" else []
        return {
            "schema_version": 1,
            "kind": PLAN_KIND,
            "operation": OPERATION,
            "decision": self.decision,
            "dry_run": True,
            "mutation_count": 0,
            "planned_mutation_count": len(changed),
            "project_id": self.project_id,
            "work_id": self.work_id,
            "phase_ref": self.phase_ref,
            "append_result_refs": list(self.append_result_refs),
            "scope_digest": self.scope_digest,
            "effective_at": self.effective_at,
            "expected_oids": {
                "release_head": self.release_oid,
                "process_head": self.process_oid,
            },
            "repository_facts": dict(self.repository_facts),
            "repository_facts_digest": self.repository_facts_digest,
            "target_set_digest": self.target_set_digest,
            "targets": [
                {
                    "ref": ref,
                    "expected_preimage": self.preimages[ref],
                    "postimage_digest": _digest(self.targets[ref]),
                    "changed": ref in changed,
                }
                for ref in sorted(self.targets)
            ],
            "authorization": {
                "kind": AUTHORIZATION_KIND,
                "storage": "outside-release-and-process-repositories",
                "expires_at_required": True,
            },
            "transaction": {
                "strategy": "journaled-logical-multi-file-transaction",
                "recovery_required_on_partial": True,
            },
            "errors": list(self.errors),
            "plan_digest": self.plan_digest,
        }


def _blocked_plan(
    *,
    release_root: Path,
    process_root: Path,
    project_id: str,
    work_id: str,
    phase_ref: str,
    append_result_refs: tuple[str, ...],
    scope_digest: str,
    effective_at: str,
    release_oid: str,
    process_oid: str,
    repository_facts: Mapping[str, Any],
    repository_facts_digest: str,
    errors: list[str],
) -> PhaseMetadataPlan:
    identity = {
        "operation": OPERATION,
        "project_id": project_id,
        "work_id": work_id,
        "phase_ref": phase_ref,
        "append_result_refs": list(append_result_refs),
        "scope_digest": scope_digest,
        "effective_at": effective_at,
        "expected_oids": [release_oid, process_oid],
        "repository_facts_digest": repository_facts_digest,
        "errors": errors,
    }
    return PhaseMetadataPlan(
        release_root=release_root.resolve(),
        process_root=process_root.resolve(),
        project_id=project_id,
        work_id=work_id,
        phase_ref=phase_ref,
        append_result_refs=append_result_refs,
        scope_digest=scope_digest,
        effective_at=effective_at,
        release_oid=release_oid,
        process_oid=process_oid,
        repository_facts=dict(repository_facts),
        repository_facts_digest=repository_facts_digest,
        targets={},
        preimages={},
        target_set_digest=_canonical_digest([]),
        decision="BLOCKED",
        errors=tuple(errors),
        plan_digest=_canonical_digest(identity),
    )


def plan_phase_metadata_update(
    release_root: Path,
    process_root: Path,
    *,
    project_id: str,
    work_id: str,
    phase_ref: str,
    append_result_refs: tuple[str, ...] | list[str],
    scope_digest: str,
    effective_at: str,
    _ignore_transaction_locks: bool = False,
) -> PhaseMetadataPlan:
    """构造 Phase result_refs append 的完整零写 post-image。"""

    release = release_root.resolve()
    process = process_root.resolve()
    errors: list[str] = []
    release_oid = _head_oid(release, repository="release", errors=errors)
    process_oid = _head_oid(process, repository="process", errors=errors)
    try:
        repository_facts, repository_facts_digest = _repository_facts(release, process)
    except ValueError as exc:
        repository_facts, repository_facts_digest = {}, ""
        errors.append(str(exc))
    try:
        effective = _validate_effective_at(effective_at)
        phase_logical, phase_relative = _phase_logical_ref(phase_ref)
        normalized_append = tuple(_logical_ref(ref)[0] for ref in append_result_refs)
        if not normalized_append or len(normalized_append) != len(set(normalized_append)):
            raise ValueError("append_result_refs must be non-empty and unique")
    except ValueError as exc:
        errors.append(str(exc))
        effective = effective_at
        phase_logical, phase_relative = phase_ref, ""
        normalized_append = tuple(str(ref) for ref in append_result_refs)
    if not _DIGEST_RE.fullmatch(scope_digest):
        errors.append("scope_digest must be lowercase sha256")
    if errors:
        return _blocked_plan(
            release_root=release,
            process_root=process,
            project_id=project_id,
            work_id=work_id,
            phase_ref=phase_logical,
            append_result_refs=normalized_append,
            scope_digest=scope_digest,
            effective_at=effective,
            release_oid=release_oid,
            process_oid=process_oid,
            repository_facts=repository_facts,
            repository_facts_digest=repository_facts_digest,
            errors=errors,
        )
    try:
        project = load_project(process)
        roadmap = load_roadmap(process, project.roadmap_ref)
        phase = load_phase(process, phase_relative)
        authorizing_work = load_work(process, work_id)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        return _blocked_plan(
            release_root=release,
            process_root=process,
            project_id=project_id,
            work_id=work_id,
            phase_ref=phase_logical,
            append_result_refs=normalized_append,
            scope_digest=scope_digest,
            effective_at=effective,
            release_oid=release_oid,
            process_oid=process_oid,
            repository_facts=repository_facts,
            repository_facts_digest=repository_facts_digest,
            errors=errors,
        )
    if project.project_id != project_id or roadmap.project_id != project_id:
        errors.append("Project/Roadmap identity differs from the requested project_id")
    if authorizing_work.project_id != project_id:
        errors.append("authorizing Work belongs to another project")
    if authorizing_work.status != "active":
        errors.append("authorizing Work must be active")
    if authorizing_work.work_ref not in project.active_work_refs:
        errors.append("authorizing Work must be declared by PROJECT.active_work_refs")
    if authorizing_work.phase_ref != project.active_phase_ref:
        errors.append("authorizing Work must belong to the current active Phase")
    if authorizing_work.scope.digest != scope_digest:
        errors.append("authorizing Work scope digest differs from --scope-digest")
    if phase_relative not in roadmap.phase_refs:
        errors.append("target Phase must be declared by ROADMAP.phase_refs")
    if phase.status not in {"active", "planned"}:
        errors.append("Phase metadata append requires an active or planned Phase")
    target_relatives = (
        phase_relative,
        GOVERNANCE_PROJECTION_REL.as_posix(),
        "state/STATE.current.json",
        "STATE.md",
        "current/CURRENT.json",
    )
    errors.extend(_scope_allows(authorizing_work, "write", target_relatives))
    append_relatives = tuple(_logical_ref(ref)[1] for ref in normalized_append)
    errors.extend(_scope_allows(authorizing_work, "read", append_relatives))
    for append_ref in append_relatives:
        errors.extend(
            _validate_append_evidence(
                process,
                target_phase_ref=phase_relative,
                authorizing_work_id=work_id,
                append_ref=append_ref,
            )
        )
        if append_ref == GOVERNANCE_PROJECTION_REL.as_posix() and phase.status != "planned":
            errors.append("governance baseline metadata append is reserved for a planned Phase")
    if not _ignore_transaction_locks:
        try:
            assert_work_close_shared_projection_lineage(process)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    current_governance = validate_governance_projection(release, process)
    if current_governance.get("decision") != "PASS":
        errors.extend(
            "current governance projection is invalid: " + str(item)
            for item in current_governance.get("errors", [])
        )
    from meta_flow.project.phase_transition import inspect_phase_transition

    phase_transition_inspection = inspect_phase_transition(
        release,
        process,
        _ignore_locks=_ignore_transaction_locks,
    )
    if phase_transition_inspection.get("decision") != "PASS":
        errors.append("unresolved Phase transition must be recovered before metadata update")
    metadata_inspection = inspect_phase_metadata(
        release,
        process,
        _ignore_locks=_ignore_transaction_locks,
    )
    if metadata_inspection.get("decision") != "PASS":
        errors.append("unresolved Phase metadata transaction requires inspect/recover")
    state = current.load_current_state(release)
    if not state:
        errors.append("STATE.current.json is required before Phase metadata update")
    else:
        try:
            current_snapshot = build_formal_truth_snapshot(release, process_root=process)
            if state.get("formal_truth_projection") != current_snapshot:
                errors.append(
                    "formal truth projection must be current before Phase metadata update"
                )
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    if errors:
        return _blocked_plan(
            release_root=release,
            process_root=process,
            project_id=project_id,
            work_id=work_id,
            phase_ref=phase_logical,
            append_result_refs=normalized_append,
            scope_digest=scope_digest,
            effective_at=effective,
            release_oid=release_oid,
            process_oid=process_oid,
            repository_facts=repository_facts,
            repository_facts_digest=repository_facts_digest,
            errors=errors,
        )
    missing_refs = tuple(ref for ref in append_relatives if ref not in phase.result_refs)
    post_phase = (
        phase
        if not missing_refs
        else replace(
            phase,
            result_refs=(*phase.result_refs, *missing_refs),
            updated_at=effective,
        )
    )
    phase_payload = post_phase.as_dict()
    findings = validate_phase_payload(phase_payload)
    if findings:
        errors.extend(item.message for item in findings)
    try:
        governance = build_governance_projection_for_phase_postimage(
            process,
            phase_ref=phase_relative,
            phase_payload=phase_payload,
            require_current=True,
        )
        assert state is not None
        phase_bytes = _render_yaml(phase_payload)
        overrides = {phase_logical: (phase_payload, phase_bytes)}
        post_snapshot = build_formal_truth_snapshot(
            release,
            process_root=process,
            object_overrides=overrides,
        )
        if missing_refs:
            patch = derive_formal_truth_patch(state, post_snapshot)
            patch["updated_at"] = effective
            state_candidate = current.build_current_state_candidate(
                release,
                patch,
                actor="meta_flow.project.phase_metadata",
                reason="atomic Phase result_refs metadata append",
                base_state=state,
            )
        else:
            state_candidate = state
        current_entry = current.build_current_entry(release, state_snapshot=state_candidate)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        governance = {}
        phase_bytes = b""
        state_candidate = state or {}
        current_entry = {}
    if errors:
        return _blocked_plan(
            release_root=release,
            process_root=process,
            project_id=project_id,
            work_id=work_id,
            phase_ref=phase_logical,
            append_result_refs=normalized_append,
            scope_digest=scope_digest,
            effective_at=effective,
            release_oid=release_oid,
            process_oid=process_oid,
            repository_facts=repository_facts,
            repository_facts_digest=repository_facts_digest,
            errors=errors,
        )
    targets: dict[str, bytes] = {
        phase_logical: phase_bytes,
        "process/governance/GOVERNANCE-BASELINE.json": render_governance_projection(governance),
        "process/state/STATE.current.json": current.render_current_state_candidate(
            state_candidate
        ).encode("utf-8"),
        "process/STATE.md": current.render_state_markdown(state_candidate).encode("utf-8"),
        "process/current/CURRENT.json": _render_json(current_entry),
    }
    if not missing_refs:
        # 已存在的 ref 必须是 exact byte no-op；不得因重跑更新时间或重渲染格式。
        targets = {ref: _read_bytes(_target_path(process, ref)) or b"" for ref in targets}
    preimages: dict[str, str] = {}
    for ref in targets:
        try:
            before = _read_bytes(_target_path(process, ref))
            if before is None:
                errors.append(f"Phase metadata target must already exist: {ref}")
            preimages[ref] = _digest(before)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    target_set = [
        {"ref": ref, "before": preimages.get(ref, "invalid"), "after": _digest(targets[ref])}
        for ref in sorted(targets)
    ]
    target_set_digest = _canonical_digest(target_set)
    changed_refs = sorted(
        ref for ref, after in targets.items() if preimages.get(ref) != _digest(after)
    )
    decision = "BLOCKED" if errors else ("NOOP" if not changed_refs else "READY")
    identity = {
        "operation": OPERATION,
        "project_id": project_id,
        "work_id": work_id,
        "phase_ref": phase_logical,
        "append_result_refs": list(normalized_append),
        "scope_digest": scope_digest,
        "effective_at": effective,
        "expected_oids": {"release_head": release_oid, "process_head": process_oid},
        "repository_facts_digest": repository_facts_digest,
        "target_set_digest": target_set_digest,
        "decision": decision,
        "errors": errors,
    }
    return PhaseMetadataPlan(
        release_root=release,
        process_root=process,
        project_id=project_id,
        work_id=work_id,
        phase_ref=phase_logical,
        append_result_refs=normalized_append,
        scope_digest=scope_digest,
        effective_at=effective,
        release_oid=release_oid,
        process_oid=process_oid,
        repository_facts=repository_facts,
        repository_facts_digest=repository_facts_digest,
        targets=targets,
        preimages=preimages,
        target_set_digest=target_set_digest,
        decision=decision,
        errors=tuple(errors),
        plan_digest=_canonical_digest(identity),
    )


def require_external_phase_metadata_authorization_path(
    release_root: Path,
    process_root: Path,
    authorization_path: Path,
) -> Path:
    lexical = authorization_path.absolute()
    resolved = authorization_path.resolve()
    for repository_root in (release_root.resolve(), process_root.resolve()):
        if lexical.is_relative_to(repository_root) or resolved.is_relative_to(repository_root):
            raise ValueError(
                "Phase metadata authorization must be stored outside release/process repositories"
            )
    if (
        authorization_path.is_symlink()
        or not resolved.is_file()
        or resolved.stat().st_size > 64 * 1024
    ):
        raise ValueError("Phase metadata authorization is missing, unsafe, or over budget")
    return resolved


def _runtime_paths(process_root: Path) -> tuple[Path, Path, Path]:
    root = process_root.resolve() / TRANSACTION_ROOT_REL
    ensure_transaction_directory(root)
    return root, process_root.resolve() / MANIFEST_REL, process_root.resolve() / LOCK_REL


def _record(ref: str, before: bytes, after: bytes) -> dict[str, Any]:
    return {
        "ref": ref,
        "before_digest": _digest(before),
        "after_digest": _digest(after),
        "before_bytes_b64": base64.b64encode(before).decode("ascii"),
        "after_bytes_b64": base64.b64encode(after).decode("ascii"),
    }


def _allowed_manifest_ref(ref: str) -> bool:
    if ref in FIXED_TARGET_REFS:
        return True
    try:
        _phase_logical_ref(ref)
    except ValueError:
        return False
    return True


def _decode_record(raw: Mapping[str, Any]) -> tuple[str, bytes, bytes]:
    expected = {
        "ref",
        "before_digest",
        "after_digest",
        "before_bytes_b64",
        "after_bytes_b64",
    }
    if set(raw) != expected:
        raise ValueError("Phase metadata target record fields mismatch")
    ref = str(raw.get("ref") or "")
    if not _allowed_manifest_ref(ref):
        raise ValueError(f"Phase metadata manifest target is not allowed: {ref}")
    try:
        before = base64.b64decode(str(raw["before_bytes_b64"]), validate=True)
        after = base64.b64decode(str(raw["after_bytes_b64"]), validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("Phase metadata target bytes are invalid") from exc
    if _digest(before) != raw["before_digest"] or _digest(after) != raw["after_digest"]:
        raise ValueError("Phase metadata target digest mismatch")
    return ref, before, after


def _load_manifest(process_root: Path) -> tuple[Path, dict[str, Any] | None]:
    path = process_root.resolve() / MANIFEST_REL
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Phase metadata manifest is unsafe")
    if not path.is_file():
        return path, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Phase metadata manifest is invalid") from exc
    required = {
        "schema_version",
        "kind",
        "transaction_id",
        "state",
        "project_id",
        "work_id",
        "authorization_id",
        "phase_ref",
        "plan_digest",
        "target_set_digest",
        "repository_facts_digest",
        "attempted_refs",
        "applied_refs",
        "targets",
    }
    allowed = {*required, "failure", "recovery_failures", "successor_id"}
    if (
        not isinstance(payload, dict)
        or not required.issubset(payload)
        or set(payload) - allowed
        or payload.get("schema_version") != 1
        or payload.get("kind") != TRANSACTION_KIND
        or payload.get("state") not in {"PREPARED", "APPLYING", "PARTIAL", *TERMINAL_STATES}
    ):
        raise ValueError("Phase metadata manifest shape/kind/state is invalid")
    for field in ("transaction_id", "project_id", "work_id", "authorization_id"):
        _safe_id(str(payload.get(field) or ""), subject=field)
    _phase_logical_ref(str(payload.get("phase_ref") or ""))
    for field in ("plan_digest", "target_set_digest", "repository_facts_digest"):
        if not _DIGEST_RE.fullmatch(str(payload.get(field) or "")):
            raise ValueError(f"Phase metadata manifest {field} is invalid")
    targets = payload.get("targets")
    if not isinstance(targets, list) or not 1 <= len(targets) <= 5:
        raise ValueError("Phase metadata manifest targets are invalid")
    decoded = [_decode_record(item) for item in targets if isinstance(item, Mapping)]
    refs = [item[0] for item in decoded]
    phase_refs = [ref for ref in refs if ref not in FIXED_TARGET_REFS]
    if len(decoded) != len(targets) or len(refs) != len(set(refs)) or len(phase_refs) != 1:
        raise ValueError("Phase metadata manifest target set is invalid")
    for field in ("attempted_refs", "applied_refs"):
        values = payload.get(field)
        if not isinstance(values, list) or values != refs[: len(values)]:
            raise ValueError(f"Phase metadata manifest {field} is not an ordered prefix")
    if len(payload["applied_refs"]) > len(payload["attempted_refs"]):
        raise ValueError("Phase metadata manifest accounting is invalid")
    successor_id = str(payload.get("successor_id") or "")
    if successor_id and not re.fullmatch(r"project-phase-metadata-[0-9a-f]{32}", successor_id):
        raise ValueError("Phase metadata successor_id is invalid")
    return path, payload


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_replace_bytes(path, _render_json(payload))


def _write_target(path: Path, value: bytes) -> None:
    atomic_replace_bytes(path, value)


def _release_handles(*handles: TransactionLockHandle | None) -> None:
    failure: Exception | None = None
    for handle in handles:
        if handle is None:
            continue
        try:
            release_transaction_lock(handle)
        except Exception as exc:
            if failure is None:
                failure = exc
    if failure is not None:
        raise failure


def inspect_phase_metadata(
    release_root: Path,
    process_root: Path,
    *,
    _ignore_locks: bool = False,
) -> dict[str, Any]:
    try:
        _path, payload = _load_manifest(process_root)
    except (OSError, ValueError) as exc:
        return {"decision": "BLOCKED", "state": "INVALID", "findings": [str(exc)]}
    findings: list[str] = []
    if payload is None:
        if not _ignore_locks:
            try:
                if transaction_lock_identity(process_root.resolve() / LOCK_REL) is not None:
                    findings.append("ORPHAN_PHASE_METADATA_LOCK")
            except (OSError, ValueError) as exc:
                findings.append(f"PHASE_METADATA_LOCK_UNSAFE:{exc}")
        return {
            "decision": "BLOCKED" if findings else "PASS",
            "state": "NONE",
            "findings": findings,
        }
    if payload["state"] not in TERMINAL_STATES:
        findings.append(f"UNRESOLVED_PHASE_METADATA:{payload['state']}")
    if not _ignore_locks:
        try:
            if transaction_lock_identity(process_root.resolve() / LOCK_REL) is not None:
                findings.append("PHASE_METADATA_LOCK_PRESENT")
            if transaction_lock_identity(state_projection_lock_path(release_root)) is not None:
                findings.append("STATE_PROJECTION_LOCK_PRESENT")
        except (OSError, ValueError) as exc:
            findings.append(f"PHASE_METADATA_LOCK_UNSAFE:{exc}")
    return {
        "decision": "BLOCKED" if findings else "PASS",
        "state": payload["state"],
        "transaction_id": payload["transaction_id"],
        "findings": findings,
    }


def _restore(
    release_root: Path,
    process_root: Path,
    payload: dict[str, Any],
    *,
    state_lock_handle: TransactionLockHandle,
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    attempted = set(payload["attempted_refs"])
    state_before: dict[str, bytes] = {}
    for raw in reversed(payload["targets"]):
        ref, before, after = _decode_record(raw)
        if ref not in attempted:
            continue
        if ref in STATE_TARGET_REFS:
            state_before[ref] = before
            continue
        path = _target_path(process_root, ref)
        try:
            observed = _read_bytes(path)
            if _digest(observed) == _digest(before):
                continue
            if _digest(observed) != _digest(after):
                failures.append(f"GENERATION_DRIFT:{ref}")
                continue
            atomic_replace_bytes(path, before)
        except (OSError, ValueError) as exc:
            failures.append(f"RESTORE_FAILED:{ref}:{type(exc).__name__}")
    if state_before:
        try:
            inspection = inspect_state_projection_transaction(release_root, _ignore_lock=True)
            if inspection["decision"] != "PASS":
                recovery = recover_state_projection_transaction(
                    release_root,
                    lock_handle=state_lock_handle,
                )
                if recovery["decision"] not in {"RECOVERED", "NO_CHANGE"}:
                    failures.extend(
                        f"STATE_RECOVERY_FAILED:{item}" for item in recovery.get("findings", [])
                    )
            if not failures:
                apply_state_projection_transaction(
                    release_root,
                    state_before,
                    lock_handle=state_lock_handle,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append(f"STATE_RESTORE_FAILED:{type(exc).__name__}:{exc}")
    recovered_refs: list[str] = []
    for raw in reversed(payload["targets"]):
        ref, before, _after = _decode_record(raw)
        if ref not in attempted:
            continue
        try:
            if _digest(_read_bytes(_target_path(process_root, ref))) == _digest(before):
                recovered_refs.append(ref)
            elif not any(ref in failure for failure in failures):
                failures.append(f"RESTORE_INCOMPLETE:{ref}")
        except (OSError, ValueError) as exc:
            failures.append(f"RESTORE_VERIFY_FAILED:{ref}:{type(exc).__name__}")
    return failures, recovered_refs


def recover_phase_metadata(release_root: Path, process_root: Path) -> dict[str, Any]:
    release = release_root.resolve()
    process = process_root.resolve()
    manifest_path, payload = _load_manifest(process)
    lock_path = process / LOCK_REL
    if payload is None:
        handle: TransactionLockHandle | None = None
        try:
            identity = transaction_lock_identity(lock_path)
            if identity is not None:
                handle = claim_transaction_lock(lock_path, identity, create_if_missing=False)
            return {
                "decision": "NO_CHANGE",
                "state": "NONE",
                "recovered_refs": [],
                "lock_recovered": handle is not None,
                "findings": [],
            }
        finally:
            _release_handles(handle)
    transaction_id = str(payload["transaction_id"])
    metadata_handle: TransactionLockHandle | None = None
    state_handle: TransactionLockHandle | None = None
    shared_handle = None
    shared_writer_id = "phase-metadata-recover-" + transaction_id
    try:
        shared_handle = acquire_shared_projection_writer_lock(process, shared_writer_id)
        if payload["state"] in TERMINAL_STATES:
            needs_successor = payload["state"] == "COMMITTED" and "successor_id" not in payload
            if needs_successor:
                metadata_handle = claim_transaction_lock(
                    lock_path,
                    transaction_id,
                    create_if_missing=True,
                )
                before_digests = {
                    str(raw["ref"]).removeprefix("process/"): str(raw["before_digest"])
                    for raw in payload["targets"]
                    if str(raw["ref"]) not in STATE_TARGET_REFS
                }
                successor_id = record_shared_projection_successor(
                    process,
                    operation=OPERATION,
                    writer_id=transaction_id,
                    before_digests=before_digests,
                    allowed_refs=tuple(before_digests),
                )
                payload["successor_id"] = successor_id
                _write_manifest(manifest_path, payload)
            return {
                "decision": "NO_CHANGE",
                "state": payload["state"],
                "recovered_refs": [],
                "shared_projection_successor_id": str(payload.get("successor_id") or ""),
                "findings": [],
            }
        state_handle = claim_transaction_lock(
            state_projection_lock_path(release),
            transaction_id,
            create_if_missing=True,
        )
        metadata_handle = claim_transaction_lock(lock_path, transaction_id, create_if_missing=True)
        _path, current_payload = _load_manifest(process)
        if current_payload is None or current_payload["transaction_id"] != transaction_id:
            raise ValueError("Phase metadata transaction changed during recovery")
        payload = current_payload
        failures: list[str] = []
        successor_id = str(payload.get("successor_id") or "")
        if successor_id:
            try:
                discard_shared_projection_successor(
                    process,
                    successor_id=successor_id,
                    operation=OPERATION,
                    writer_id=transaction_id,
                )
                payload.pop("successor_id", None)
            except (OSError, ValueError) as exc:
                failures.append(f"SUCCESSOR_RECOVERY_FAILED:{type(exc).__name__}:{exc}")
        restore_failures, recovered_refs = _restore(
            release,
            process,
            payload,
            state_lock_handle=state_handle,
        )
        failures.extend(restore_failures)
        payload["state"] = "PARTIAL" if failures else "RECOVERED"
        if failures:
            payload["recovery_failures"] = failures
        _write_manifest(manifest_path, payload)
        return {
            "decision": "PARTIAL" if failures else "RECOVERED",
            "state": payload["state"],
            "recovered_refs": recovered_refs,
            "lock_recovered": True,
            "findings": failures,
        }
    except (OSError, ValueError) as exc:
        return {
            "decision": "BLOCKED",
            "state": payload["state"],
            "recovered_refs": [],
            "findings": [str(exc)],
        }
    finally:
        try:
            _release_handles(metadata_handle, state_handle)
        finally:
            if shared_handle is not None:
                release_shared_projection_writer_lock(shared_handle, shared_writer_id)


def apply_phase_metadata_update(
    plan: PhaseMetadataPlan,
    authorization: PhaseMetadataAuthorizationV1,
) -> dict[str, Any]:
    if plan.decision == "BLOCKED":
        raise ValueError("Phase metadata plan is blocked: " + "; ".join(plan.errors))
    authorization.validate_for(plan)
    fresh = plan_phase_metadata_update(
        plan.release_root,
        plan.process_root,
        project_id=plan.project_id,
        work_id=plan.work_id,
        phase_ref=plan.phase_ref,
        append_result_refs=plan.append_result_refs,
        scope_digest=plan.scope_digest,
        effective_at=plan.effective_at,
    )
    if fresh.plan_digest != plan.plan_digest:
        raise ValueError("Phase metadata source, OID, scope, repository facts, or target drifted")
    if inspect_phase_metadata(plan.release_root, plan.process_root)["decision"] != "PASS":
        raise ValueError("unresolved Phase metadata transaction requires inspect/recover")
    if plan.decision == "NOOP":
        return {
            "schema_version": 1,
            "kind": RECEIPT_KIND,
            "operation": OPERATION,
            "decision": "PASS",
            "disposition": "NOOP",
            "authorization_id": authorization.authorization_id,
            "mutation_count": 0,
            "plan_digest": plan.plan_digest,
        }
    changed = plan.changed_refs
    transaction_id = _canonical_digest(
        {
            "authorization_id": authorization.authorization_id,
            "plan_digest": plan.plan_digest,
            "targets": [
                {"ref": ref, "before": plan.preimages[ref], "after": _digest(plan.targets[ref])}
                for ref in changed
            ],
        }
    )[:32]
    shared_writer_id = "phase-metadata-" + transaction_id
    shared_handle = None
    state_handle: TransactionLockHandle | None = None
    metadata_handle: TransactionLockHandle | None = None
    _runtime_root, manifest_path, lock_path = _runtime_paths(plan.process_root)
    ordered_refs = [
        *sorted(ref for ref in changed if ref not in STATE_TARGET_REFS),
        *sorted(ref for ref in changed if ref in STATE_TARGET_REFS),
    ]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": TRANSACTION_KIND,
        "transaction_id": transaction_id,
        "state": "PREPARED",
        "project_id": plan.project_id,
        "work_id": plan.work_id,
        "authorization_id": authorization.authorization_id,
        "phase_ref": plan.phase_ref,
        "plan_digest": plan.plan_digest,
        "target_set_digest": plan.target_set_digest,
        "repository_facts_digest": plan.repository_facts_digest,
        "attempted_refs": [],
        "applied_refs": [],
        "targets": [
            _record(
                ref,
                _read_bytes(_target_path(plan.process_root, ref)) or b"",
                plan.targets[ref],
            )
            for ref in ordered_refs
        ],
    }
    formal_before = {
        ref.removeprefix("process/"): str(raw["before_digest"])
        for raw in payload["targets"]
        if str(raw["ref"]) not in STATE_TARGET_REFS
        for ref in (str(raw["ref"]),)
    }
    journal_started = False
    successor_preflight: tuple[tuple[str, str, str, str], ...] = ()
    try:
        shared_handle = acquire_shared_projection_writer_lock(
            plan.process_root,
            shared_writer_id,
        )
        state_handle = acquire_transaction_lock(
            state_projection_lock_path(plan.release_root),
            transaction_id,
        )
        metadata_handle = acquire_transaction_lock(lock_path, transaction_id)
        validate_transaction_lock(
            state_handle,
            expected_path=state_projection_lock_path(plan.release_root),
        )
        validate_transaction_lock(metadata_handle, expected_path=lock_path)
        locked_plan = plan_phase_metadata_update(
            plan.release_root,
            plan.process_root,
            project_id=plan.project_id,
            work_id=plan.work_id,
            phase_ref=plan.phase_ref,
            append_result_refs=plan.append_result_refs,
            scope_digest=plan.scope_digest,
            effective_at=plan.effective_at,
            _ignore_transaction_locks=True,
        )
        if locked_plan.plan_digest != plan.plan_digest:
            raise ValueError("Phase metadata plan drifted while acquiring writer locks")
        authorization.validate_for(locked_plan)
        successor_preflight = plan_shared_projection_successor_preflight(
            plan.process_root,
            operation=OPERATION,
            writer_id=transaction_id,
            before_digests=formal_before,
            allowed_refs=tuple(formal_before),
        )
        _write_manifest(manifest_path, payload)
        journal_started = True
        payload["state"] = "APPLYING"
        _write_manifest(manifest_path, payload)
        formal_records = [
            raw for raw in payload["targets"] if str(raw["ref"]) not in STATE_TARGET_REFS
        ]
        state_records = [raw for raw in payload["targets"] if str(raw["ref"]) in STATE_TARGET_REFS]
        for raw in formal_records:
            ref, _before, after = _decode_record(raw)
            payload["attempted_refs"].append(ref)
            _write_manifest(manifest_path, payload)
            _write_target(_target_path(plan.process_root, ref), after)
            payload["applied_refs"].append(ref)
            _write_manifest(manifest_path, payload)
        state_targets: dict[str, bytes] = {}
        for raw in state_records:
            ref, _before, after = _decode_record(raw)
            payload["attempted_refs"].append(ref)
            state_targets[ref] = after
            _write_manifest(manifest_path, payload)
        if state_targets:
            assert state_handle is not None
            state_receipt = apply_state_projection_transaction(
                plan.release_root,
                state_targets,
                lock_handle=state_handle,
            )
            if state_receipt["decision"] != "PASS" or state_receipt["mutation_count"] != len(
                state_targets
            ):
                raise RuntimeError("State projection subtransaction did not apply frozen targets")
            for ref in sorted(state_targets):
                payload["applied_refs"].append(ref)
                _write_manifest(manifest_path, payload)
        drifted = [
            ref
            for ref in ordered_refs
            if _digest(_read_bytes(_target_path(plan.process_root, ref)))
            != _digest(plan.targets[ref])
        ]
        if drifted:
            raise RuntimeError(
                "Phase metadata postimage verification failed: " + ", ".join(drifted)
            )
        payload["state"] = "COMMITTED"
        _write_manifest(manifest_path, payload)
        successor_id = record_shared_projection_successor(
            plan.process_root,
            operation=OPERATION,
            writer_id=transaction_id,
            before_digests=formal_before,
            allowed_refs=tuple(formal_before),
            expected_preflight=successor_preflight,
        )
        payload["successor_id"] = successor_id
        _write_manifest(manifest_path, payload)
        return {
            "schema_version": 1,
            "kind": RECEIPT_KIND,
            "operation": OPERATION,
            "decision": "PASS",
            "disposition": "APPLIED",
            "authorization_id": authorization.authorization_id,
            "transaction_id": transaction_id,
            "mutation_count": len(changed),
            "applied_refs": list(payload["applied_refs"]),
            "shared_projection_successor_id": successor_id,
            "plan_digest": plan.plan_digest,
        }
    except Exception as exc:
        if not journal_started:
            raise
        payload["failure"] = f"{type(exc).__name__}:{exc}"
        failures: list[str] = []
        successor_id = str(payload.get("successor_id") or "")
        if successor_id:
            try:
                discard_shared_projection_successor(
                    plan.process_root,
                    successor_id=successor_id,
                    operation=OPERATION,
                    writer_id=transaction_id,
                )
                payload.pop("successor_id", None)
            except (OSError, ValueError) as cleanup_exc:
                failures.append(
                    f"SUCCESSOR_RECOVERY_FAILED:{type(cleanup_exc).__name__}:{cleanup_exc}"
                )
        assert state_handle is not None
        restore_failures, recovered_refs = _restore(
            plan.release_root,
            plan.process_root,
            payload,
            state_lock_handle=state_handle,
        )
        failures.extend(restore_failures)
        unrecovered_refs = [
            ref
            for raw in payload["targets"]
            for ref, before, _after in (_decode_record(raw),)
            if ref in payload["attempted_refs"]
            and _digest(_read_bytes(_target_path(plan.process_root, ref))) != _digest(before)
        ]
        payload["state"] = "PARTIAL" if failures else "RECOVERED"
        if failures:
            payload["recovery_failures"] = failures
        try:
            _write_manifest(manifest_path, payload)
        except (OSError, ValueError) as manifest_exc:
            failures.append(
                f"RECOVERY_MANIFEST_WRITE_FAILED:{type(manifest_exc).__name__}:{manifest_exc}"
            )
            payload["state"] = "PARTIAL"
        if failures:
            raise PhaseMetadataPartialError(
                {
                    "schema_version": 1,
                    "kind": RECEIPT_KIND,
                    "operation": OPERATION,
                    "decision": "PARTIAL",
                    "disposition": "RECOVERY_REQUIRED",
                    "authorization_id": authorization.authorization_id,
                    "transaction_id": transaction_id,
                    "mutation_count": len(unrecovered_refs),
                    "attempted_refs": list(payload["attempted_refs"]),
                    "applied_refs": list(payload["applied_refs"]),
                    "recovered_refs": recovered_refs,
                    "unrecovered_refs": unrecovered_refs,
                    "findings": failures,
                    "plan_digest": plan.plan_digest,
                }
            ) from exc
        raise
    finally:
        try:
            _release_handles(metadata_handle, state_handle)
        finally:
            if shared_handle is not None:
                release_shared_projection_writer_lock(shared_handle, shared_writer_id)


def _cli_blocked(project_id: str, error_code: str, error: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": PLAN_KIND,
        "operation": OPERATION,
        "project_id": project_id,
        "decision": "BLOCKED",
        "dry_run": True,
        "mutation_count": 0,
        "planned_mutation_count": 0,
        "error_code": error_code,
        "errors": [error],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project phase-metadata")
    parser.add_argument("action", choices=("plan", "apply", "inspect", "recover"))
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--work-id")
    parser.add_argument("--phase-ref")
    parser.add_argument("--append-result-ref", action="append", default=[])
    parser.add_argument("--scope-digest")
    parser.add_argument("--effective-at")
    parser.add_argument("--authorization", type=Path)
    parsed = parser.parse_args(argv or [])
    from meta_flow.project.process_route import ProcessRouteError, require_project_process_route

    try:
        route = require_project_process_route(
            parsed.project_root.resolve(),
            project_id=parsed.project_id,
        )
    except ProcessRouteError as exc:
        print(json.dumps(_cli_blocked(parsed.project_id, exc.error_code, str(exc)), sort_keys=True))
        return 2
    if parsed.action in {"inspect", "recover"}:
        try:
            result = (
                inspect_phase_metadata(route.project_root, route.process_root)
                if parsed.action == "inspect"
                else recover_phase_metadata(route.project_root, route.process_root)
            )
        except (OSError, ValueError) as exc:
            result = _cli_blocked(parsed.project_id, "phase_metadata_recovery_blocked", str(exc))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("decision") in {"PASS", "NO_CHANGE", "RECOVERED"} else 2
    missing = [
        name
        for name, value in (
            ("--work-id", parsed.work_id),
            ("--phase-ref", parsed.phase_ref),
            ("--append-result-ref", parsed.append_result_ref),
            ("--scope-digest", parsed.scope_digest),
            ("--effective-at", parsed.effective_at),
        )
        if not value
    ]
    if missing:
        print(
            json.dumps(
                _cli_blocked(
                    parsed.project_id,
                    "phase_metadata_input_missing",
                    "missing required metadata inputs: " + ", ".join(missing),
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    try:
        plan = plan_phase_metadata_update(
            route.project_root,
            route.process_root,
            project_id=parsed.project_id,
            work_id=str(parsed.work_id),
            phase_ref=str(parsed.phase_ref),
            append_result_refs=tuple(str(ref) for ref in parsed.append_result_ref),
            scope_digest=str(parsed.scope_digest),
            effective_at=str(parsed.effective_at),
        )
    except Exception as exc:  # pragma: no cover - defensive public boundary
        print(
            json.dumps(
                _cli_blocked(
                    parsed.project_id, "CHECK_HARNESS_ERROR", f"{type(exc).__name__}: {exc}"
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    if parsed.action == "plan":
        print(json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True))
        return 2 if plan.decision == "BLOCKED" else 0
    if parsed.authorization is None:
        print(
            json.dumps(
                {
                    "plan": plan.as_dict(),
                    "decision": "BLOCKED",
                    "error_code": "phase_metadata_authorization_missing",
                    "error": "apply requires --authorization",
                    "mutation_count": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    try:
        authorization_path = require_external_phase_metadata_authorization_path(
            route.project_root,
            route.process_root,
            parsed.authorization,
        )
        payload = json.loads(authorization_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Phase metadata authorization must contain an object")
        authorization = PhaseMetadataAuthorizationV1.from_mapping(payload)
        receipt = apply_phase_metadata_update(plan, authorization)
    except PhaseMetadataPartialError as exc:
        print(
            json.dumps(
                {"plan": plan.as_dict(), "receipt": exc.result}, ensure_ascii=False, sort_keys=True
            )
        )
        return 2
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "plan": plan.as_dict(),
                    "decision": "BLOCKED",
                    "error_code": "phase_metadata_apply_blocked",
                    "error": str(exc),
                    "mutation_count": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps({"plan": plan.as_dict(), "receipt": receipt}, ensure_ascii=False, sort_keys=True)
    )
    return 0


__all__ = [
    "AUTHORIZATION_KIND",
    "PhaseMetadataAuthorizationV1",
    "PhaseMetadataPartialError",
    "PhaseMetadataPlan",
    "apply_phase_metadata_update",
    "inspect_phase_metadata",
    "main",
    "plan_phase_metadata_update",
    "recover_phase_metadata",
    "require_external_phase_metadata_authorization_path",
]
