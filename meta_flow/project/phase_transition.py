"""Project/Phase formal truth 与核心投影的可恢复逻辑事务。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from meta_flow.project.governance import load_phase, load_roadmap, validate_phase_payload
from meta_flow.project.governance_projection import (
    GOVERNANCE_PROJECTION_REL,
    ImmutableCommitRole,
    _normalize_immutable_commit_roles,
    _parse_immutable_commit_role,
    _validate_immutable_commit_roles,
    build_governance_projection_from_truth,
    build_governance_truth_from_payloads,
)
from meta_flow.project.model import load_project, validate_project_payload
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.state import current
from meta_flow.state.formal_projection import (
    build_formal_truth_snapshot,
    derive_formal_truth_patch,
)
from meta_flow.state.projection_transaction import (
    LOCK_REL as STATE_PROJECTION_LOCK_REL,
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
    discard_shared_projection_successor,
    record_shared_projection_successor,
    release_shared_projection_writer_lock,
)

PUBLIC_OPERATION_DECLARATIONS = (
    ("project.phase-transition", ("meta-flow", "project", "phase-transition")),
)

PLAN_KIND = "PhaseTransitionPlanV1"
RECEIPT_KIND = "PhaseTransitionReceiptV1"
TRANSACTION_KIND = "PhaseTransitionTransactionV1"
TRANSACTION_ROOT_REL = Path(".meta-flow-runtime/phase-transition")
MANIFEST_REL = TRANSACTION_ROOT_REL / "transaction.json"
LOCK_REL = TRANSACTION_ROOT_REL / "writer.lock"
TERMINAL_STATES = frozenset({"COMMITTED", "RECOVERED"})
FIXED_TARGET_REFS = frozenset(
    {
        "process/PROJECT.yaml",
        "process/governance/GOVERNANCE-BASELINE.json",
        "process/state/STATE.current.json",
        "process/STATE.md",
        "process/current/CURRENT.json",
    }
)
STATE_TARGET_REFS = frozenset(
    {
        "process/state/STATE.current.json",
        "process/STATE.md",
        "process/current/CURRENT.json",
    }
)
TERMINAL_WORK_STATUSES = frozenset({"completed", "cancelled", "archived"})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class PhaseTransitionPartialError(RuntimeError):
    """事务无法完全回滚时，携带真实剩余 mutation 的结构化收据。"""

    def __init__(self, result: Mapping[str, Any]) -> None:
        super().__init__("Phase transition entered PARTIAL")
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
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", oid):
        errors.append(f"{repository} repository HEAD is unavailable")
        return ""
    return oid


def _logical_ref(value: str, *, prefix: str | None = None) -> tuple[str, str]:
    text = str(value or "").strip()
    path = Path(text)
    if (
        not text.startswith("process/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("phase transition refs must use safe process/... logical paths")
    relative = Path(*path.parts[1:]).as_posix()
    if prefix is not None and not relative.startswith(prefix + "/"):
        raise ValueError(f"phase transition ref must be under process/{prefix}/")
    return text, relative


def _target_path(process_root: Path, logical_ref: str) -> Path:
    _logical, relative = _logical_ref(logical_ref)
    path = (process_root.resolve() / relative).resolve(strict=False)
    if not path.is_relative_to(process_root.resolve()):
        raise ValueError(f"phase transition target escapes process repository: {logical_ref}")
    return path


def _read_bytes(path: Path) -> bytes | None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"phase transition target is not a regular file: {path}")
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


def _tracked_at_head(process_root: Path, relative_ref: str) -> bool:
    result = _git(process_root, "cat-file", "-e", f"HEAD:{relative_ref}")
    return result.returncode == 0


def _dirty_targets(process_root: Path, relative_refs: list[str]) -> list[str]:
    result = _git(process_root, "status", "--porcelain=v1", "--", *relative_refs)
    if result.returncode != 0:
        return ["<git-status-unavailable>"]
    return [line.rstrip() for line in result.stdout.splitlines() if line.strip()]


@dataclass(frozen=True)
class PhaseTransitionPlan:
    release_root: Path
    process_root: Path
    project_id: str
    from_phase_ref: str
    to_phase_ref: str
    closure_evidence_ref: str
    effective_at: str
    immutable_commit_roles: tuple[ImmutableCommitRole, ...]
    release_oid: str
    process_oid: str
    targets: Mapping[str, bytes]
    preimages: Mapping[str, str]
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
            "operation": "project.phase-transition",
            "decision": self.decision,
            "dry_run": True,
            "mutation_count": 0,
            "planned_mutation_count": len(changed),
            "project_id": self.project_id,
            "from_phase_ref": self.from_phase_ref,
            "to_phase_ref": self.to_phase_ref,
            "closure_evidence_ref": self.closure_evidence_ref,
            "effective_at": self.effective_at,
            "expected_oids": {
                "release_head": self.release_oid,
                "process_head": self.process_oid,
            },
            "immutable_commit_roles": [item.as_dict() for item in self.immutable_commit_roles],
            "targets": [
                {
                    "ref": ref,
                    "expected_preimage": self.preimages[ref],
                    "postimage_digest": _digest(self.targets[ref]),
                    "changed": ref in changed,
                }
                for ref in sorted(self.targets)
            ],
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
    from_phase_ref: str,
    to_phase_ref: str,
    closure_evidence_ref: str,
    effective_at: str,
    roles: tuple[ImmutableCommitRole, ...],
    release_oid: str,
    process_oid: str,
    errors: list[str],
) -> PhaseTransitionPlan:
    identity = {
        "operation": "project.phase-transition",
        "project_id": project_id,
        "from_phase_ref": from_phase_ref,
        "to_phase_ref": to_phase_ref,
        "closure_evidence_ref": closure_evidence_ref,
        "effective_at": effective_at,
        "expected_oids": [release_oid, process_oid],
        "errors": errors,
    }
    return PhaseTransitionPlan(
        release_root=release_root.resolve(),
        process_root=process_root.resolve(),
        project_id=project_id,
        from_phase_ref=from_phase_ref,
        to_phase_ref=to_phase_ref,
        closure_evidence_ref=closure_evidence_ref,
        effective_at=effective_at,
        immutable_commit_roles=roles,
        release_oid=release_oid,
        process_oid=process_oid,
        targets={},
        preimages={},
        decision="BLOCKED",
        errors=tuple(errors),
        plan_digest=_canonical_digest(identity),
    )


def plan_phase_transition(
    release_root: Path,
    process_root: Path,
    *,
    project_id: str,
    from_phase_ref: str,
    to_phase_ref: str,
    closure_evidence_ref: str,
    effective_at: str,
    immutable_commit_roles: tuple[ImmutableCommitRole, ...]
    | list[ImmutableCommitRole]
    | tuple[dict[str, Any], ...]
    | list[dict[str, Any]],
) -> PhaseTransitionPlan:
    """构造全部 post-image；此函数不得写入 release/process 工作树。"""

    release = release_root.resolve()
    process = process_root.resolve()
    errors: list[str] = []
    try:
        from meta_flow.work.lifecycle_transaction import (
            assert_work_close_shared_projection_lineage,
        )

        assert_work_close_shared_projection_lineage(process)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    roles, role_errors = _normalize_immutable_commit_roles(immutable_commit_roles)
    errors.extend(role_errors)
    release_oid = _head_oid(release, repository="release", errors=errors)
    process_oid = _head_oid(process, repository="process", errors=errors)
    errors.extend(
        _validate_immutable_commit_roles(
            roles,
            release_root=release,
            process_root=process,
            release_head=release_oid,
            process_head=process_oid,
        )
    )
    try:
        effective = _validate_effective_at(effective_at)
        from_logical, from_relative = _logical_ref(from_phase_ref, prefix="phases")
        to_logical, to_relative = _logical_ref(to_phase_ref, prefix="phases")
        closure_logical, closure_relative = _logical_ref(closure_evidence_ref)
    except ValueError as exc:
        errors.append(str(exc))
        effective = effective_at
        from_logical, from_relative = from_phase_ref, ""
        to_logical, to_relative = to_phase_ref, ""
        closure_logical, closure_relative = closure_evidence_ref, ""
    if from_phase_ref == to_phase_ref:
        errors.append("from_phase_ref and to_phase_ref must differ")
    if errors:
        return _blocked_plan(
            release_root=release,
            process_root=process,
            project_id=project_id,
            from_phase_ref=from_phase_ref,
            to_phase_ref=to_phase_ref,
            closure_evidence_ref=closure_evidence_ref,
            effective_at=effective,
            roles=roles,
            release_oid=release_oid,
            process_oid=process_oid,
            errors=errors,
        )

    try:
        project = load_project(process)
        roadmap = load_roadmap(process, project.roadmap_ref)
        from_phase = load_phase(process, from_relative)
        to_phase = load_phase(process, to_relative)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        return _blocked_plan(
            release_root=release,
            process_root=process,
            project_id=project_id,
            from_phase_ref=from_logical,
            to_phase_ref=to_logical,
            closure_evidence_ref=closure_logical,
            effective_at=effective,
            roles=roles,
            release_oid=release_oid,
            process_oid=process_oid,
            errors=errors,
        )
    if project.project_id != project_id or roadmap.project_id != project_id:
        errors.append("Project/Roadmap identity differs from the requested project_id")
    if from_relative not in roadmap.phase_refs or to_relative not in roadmap.phase_refs:
        errors.append("from/to Phase must both be declared by ROADMAP.phase_refs")
    post_state = (
        project.active_phase_ref == from_relative
        and from_phase.status == "active"
        and to_phase.status == "planned"
    )
    already_transitioned = (
        project.active_phase_ref == to_relative
        and from_phase.status == "completed"
        and to_phase.status == "active"
    )
    if not post_state and not already_transitioned:
        errors.append(
            "phase transition requires active/planned source state or completed/active idempotent state"
        )
    if project.active_work_refs:
        errors.append("PROJECT.active_work_refs must be empty before Phase transition")
    if closure_relative not in from_phase.result_refs:
        errors.append("closure evidence must be declared by the from Phase result_refs")
    closure_path = process / closure_relative
    if closure_path.is_symlink() or not closure_path.is_file():
        errors.append("closure evidence is missing or not a regular file")
    elif not _tracked_at_head(process, closure_relative):
        errors.append("closure evidence must exist at the immutable process HEAD")
    if GOVERNANCE_PROJECTION_REL.as_posix() not in to_phase.result_refs:
        errors.append(
            "the to Phase must declare governance/GOVERNANCE-BASELINE.json in result_refs"
        )
    for work_ref in from_phase.work_refs:
        try:
            work = load_yaml_object(process / work_ref)
        except (OSError, ValueError) as exc:
            errors.append(f"from Phase Work is unreadable: {work_ref}: {exc}")
            continue
        if str(work.get("status") or "") not in TERMINAL_WORK_STATUSES:
            errors.append(f"from Phase Work is not terminal: {work_ref}")

    phase_payloads: dict[str, dict[str, Any]] = {}
    for ref in roadmap.phase_refs:
        try:
            phase_payloads[ref] = load_yaml_object(process / ref)
        except (OSError, ValueError) as exc:
            errors.append(f"declared Phase is unreadable: {ref}: {exc}")
    if errors:
        return _blocked_plan(
            release_root=release,
            process_root=process,
            project_id=project_id,
            from_phase_ref=from_logical,
            to_phase_ref=to_logical,
            closure_evidence_ref=closure_logical,
            effective_at=effective,
            roles=roles,
            release_oid=release_oid,
            process_oid=process_oid,
            errors=errors,
        )

    post_project = replace(
        project,
        active_phase_ref=to_relative,
        active_work_refs=(),
        updated_at=effective,
    )
    post_from = replace(from_phase, status="completed", updated_at=effective)
    post_to = replace(to_phase, status="active", updated_at=effective)
    post_project_payload = post_project.as_dict()
    post_from_payload = post_from.as_dict()
    post_to_payload = post_to.as_dict()
    project_findings = validate_project_payload(post_project_payload)
    phase_findings = [
        *validate_phase_payload(post_from_payload),
        *validate_phase_payload(post_to_payload),
    ]
    if project_findings or phase_findings:
        errors.extend(
            [item.message for item in project_findings] + [item.message for item in phase_findings]
        )
        return _blocked_plan(
            release_root=release,
            process_root=process,
            project_id=project_id,
            from_phase_ref=from_logical,
            to_phase_ref=to_logical,
            closure_evidence_ref=closure_logical,
            effective_at=effective,
            roles=roles,
            release_oid=release_oid,
            process_oid=process_oid,
            errors=errors,
        )
    post_phases = dict(phase_payloads)
    post_phases[from_relative] = post_from_payload
    post_phases[to_relative] = post_to_payload
    roadmap_payload = roadmap.as_dict()
    truth = build_governance_truth_from_payloads(
        post_project_payload,
        roadmap_payload,
        post_phases,
    )
    governance = build_governance_projection_from_truth(truth, roles)

    state = current.load_current_state(release)
    if not state:
        errors.append("STATE.current.json is required before Phase transition")
        return _blocked_plan(
            release_root=release,
            process_root=process,
            project_id=project_id,
            from_phase_ref=from_logical,
            to_phase_ref=to_logical,
            closure_evidence_ref=closure_logical,
            effective_at=effective,
            roles=roles,
            release_oid=release_oid,
            process_oid=process_oid,
            errors=errors,
        )
    project_bytes = _render_yaml(post_project_payload)
    from_bytes = _render_yaml(post_from_payload)
    to_bytes = _render_yaml(post_to_payload)
    overrides = {
        "process/PROJECT.yaml": (post_project_payload, project_bytes),
        from_logical: (post_from_payload, from_bytes),
        to_logical: (post_to_payload, to_bytes),
    }
    try:
        formal_snapshot = build_formal_truth_snapshot(
            release,
            process_root=process,
            object_overrides=overrides,
        )
        patch = derive_formal_truth_patch(state, formal_snapshot)
        patch["updated_at"] = effective
        state_candidate = current.build_current_state_candidate(
            release,
            patch,
            actor="meta_flow.project.phase_transition",
            reason="atomic Phase transition projection",
            base_state=state,
        )
        current_entry = current.build_current_entry(release, state_snapshot=state_candidate)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        return _blocked_plan(
            release_root=release,
            process_root=process,
            project_id=project_id,
            from_phase_ref=from_logical,
            to_phase_ref=to_logical,
            closure_evidence_ref=closure_logical,
            effective_at=effective,
            roles=roles,
            release_oid=release_oid,
            process_oid=process_oid,
            errors=errors,
        )

    targets: dict[str, bytes] = {
        from_logical: from_bytes,
        to_logical: to_bytes,
        "process/PROJECT.yaml": project_bytes,
        "process/governance/GOVERNANCE-BASELINE.json": _render_json(governance),
        "process/state/STATE.current.json": current.render_current_state_candidate(
            state_candidate
        ).encode("utf-8"),
        "process/STATE.md": current.render_state_markdown(state_candidate).encode("utf-8"),
        "process/current/CURRENT.json": _render_json(current_entry),
    }
    preimages: dict[str, str] = {}
    for ref in targets:
        try:
            before = _read_bytes(_target_path(process, ref))
            if before is None:
                errors.append(f"phase transition target must already exist: {ref}")
            preimages[ref] = _digest(before)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    changed_refs = sorted(
        ref for ref, after in targets.items() if preimages.get(ref) != _digest(after)
    )
    dirty = (
        _dirty_targets(process, [ref.removeprefix("process/") for ref in changed_refs])
        if changed_refs
        else []
    )
    if dirty:
        errors.append("phase transition target paths are dirty: " + "; ".join(dirty))
    decision = "BLOCKED" if errors else ("NOOP" if not changed_refs else "READY")
    identity = {
        "operation": "project.phase-transition",
        "project_id": project_id,
        "from_phase_ref": from_logical,
        "to_phase_ref": to_logical,
        "closure_evidence_ref": closure_logical,
        "effective_at": effective,
        "immutable_commit_roles": [item.as_dict() for item in roles],
        "expected_oids": {"release_head": release_oid, "process_head": process_oid},
        "targets": [
            {"ref": ref, "before": preimages[ref], "after": _digest(targets[ref])}
            for ref in sorted(targets)
        ],
        "decision": decision,
        "errors": errors,
    }
    return PhaseTransitionPlan(
        release_root=release,
        process_root=process,
        project_id=project_id,
        from_phase_ref=from_logical,
        to_phase_ref=to_logical,
        closure_evidence_ref=closure_logical,
        effective_at=effective,
        immutable_commit_roles=roles,
        release_oid=release_oid,
        process_oid=process_oid,
        targets=targets,
        preimages=preimages,
        decision=decision,
        errors=tuple(errors),
        plan_digest=_canonical_digest(identity),
    )


def _runtime_paths(release_root: Path) -> tuple[Path, Path, Path]:
    root = release_root.resolve() / TRANSACTION_ROOT_REL
    ensure_transaction_directory(root)
    return root, release_root.resolve() / MANIFEST_REL, release_root.resolve() / LOCK_REL


def _record(ref: str, before: bytes | None, after: bytes) -> dict[str, Any]:
    return {
        "ref": ref,
        "before_digest": _digest(before),
        "after_digest": _digest(after),
        "before_bytes_b64": None if before is None else base64.b64encode(before).decode("ascii"),
        "after_bytes_b64": base64.b64encode(after).decode("ascii"),
    }


def _allowed_manifest_ref(ref: str) -> bool:
    if ref in FIXED_TARGET_REFS:
        return True
    try:
        _logical, relative = _logical_ref(ref, prefix="phases")
    except ValueError:
        return False
    return len(Path(relative).parts) == 3 and Path(relative).name == "PHASE.yaml"


def _decode_record(raw: Mapping[str, Any]) -> tuple[str, bytes | None, bytes]:
    expected = {
        "ref",
        "before_digest",
        "after_digest",
        "before_bytes_b64",
        "after_bytes_b64",
    }
    if set(raw) != expected:
        raise ValueError("phase transition target record fields mismatch")
    ref = str(raw.get("ref") or "")
    if not _allowed_manifest_ref(ref):
        raise ValueError(f"phase transition manifest target is not allowed: {ref}")
    try:
        before = (
            None
            if raw["before_bytes_b64"] is None
            else base64.b64decode(str(raw["before_bytes_b64"]), validate=True)
        )
        after = base64.b64decode(str(raw["after_bytes_b64"]), validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("phase transition target bytes are invalid") from exc
    if _digest(before) != raw["before_digest"] or _digest(after) != raw["after_digest"]:
        raise ValueError("phase transition target digest mismatch")
    return ref, before, after


def _load_manifest(release_root: Path) -> tuple[Path, dict[str, Any] | None]:
    path = release_root.resolve() / MANIFEST_REL
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("phase transition manifest is unsafe")
    if not path.is_file():
        return path, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("phase transition manifest is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("phase transition manifest must contain an object")
    required = {
        "schema_version",
        "kind",
        "transaction_id",
        "state",
        "project_id",
        "attempted_refs",
        "applied_refs",
        "targets",
    }
    allowed = {*required, "failure", "recovery_failures", "successor_id"}
    if (
        not required.issubset(payload)
        or set(payload) - allowed
        or payload.get("schema_version") != 1
        or payload.get("kind") != TRANSACTION_KIND
    ):
        raise ValueError("phase transition manifest shape/kind is invalid")
    if not re.fullmatch(r"[0-9a-f]{32}", str(payload.get("transaction_id") or "")):
        raise ValueError("phase transition transaction_id is invalid")
    if payload.get("state") not in {"PREPARED", "APPLYING", "PARTIAL", *TERMINAL_STATES}:
        raise ValueError("phase transition manifest state is invalid")
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("phase transition manifest targets are invalid")
    decoded = [_decode_record(item) for item in targets if isinstance(item, dict)]
    refs = [item[0] for item in decoded]
    if len(decoded) != len(targets) or len(refs) != len(set(refs)) or len(refs) != 7:
        raise ValueError("phase transition manifest must contain seven unique targets")
    if set(refs) - FIXED_TARGET_REFS and len(set(refs) - FIXED_TARGET_REFS) != 2:
        raise ValueError("phase transition manifest Phase target set is invalid")
    for field in ("attempted_refs", "applied_refs"):
        values = payload.get(field)
        if not isinstance(values, list) or values != refs[: len(values)]:
            raise ValueError(f"phase transition manifest {field} is not an ordered prefix")
    if len(payload["applied_refs"]) > len(payload["attempted_refs"]):
        raise ValueError("phase transition manifest accounting is invalid")
    successor_id = str(payload.get("successor_id") or "")
    if successor_id and not re.fullmatch(
        r"project-phase-transition-[0-9a-f]{32}", successor_id
    ):
        raise ValueError("phase transition successor_id is invalid")
    return path, payload


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_replace_bytes(path, _render_json(payload))


def _write_target(path: Path, value: bytes) -> None:
    atomic_replace_bytes(path, value)


def _state_lock_path(release_root: Path) -> Path:
    return release_root.resolve() / STATE_PROJECTION_LOCK_REL


def _lock_matches(path: Path, transaction_id: str) -> bool:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"phase transition lock path is unsafe: {path}")
    if not path.exists():
        return False
    return path.read_text(encoding="utf-8") == transaction_id + "\n"


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
            if before is None:
                failures.append(f"RESTORE_PREIMAGE_MISSING:{ref}")
            else:
                state_before[ref] = before
            continue
        path = _target_path(process_root, ref)
        try:
            current_bytes = _read_bytes(path)
            if _digest(current_bytes) == _digest(before):
                continue
            if _digest(current_bytes) != _digest(after):
                failures.append(f"GENERATION_DRIFT:{ref}")
                continue
            if before is None:
                failures.append(f"RESTORE_PREIMAGE_MISSING:{ref}")
                continue
            _write_target(path, before)
        except (OSError, ValueError) as exc:
            failures.append(f"RESTORE_FAILED:{ref}:{type(exc).__name__}")
    state_failures: list[str] = []
    if state_before and not any(
        failure.startswith("RESTORE_PREIMAGE_MISSING:")
        and failure.removeprefix("RESTORE_PREIMAGE_MISSING:") in STATE_TARGET_REFS
        for failure in failures
    ):
        try:
            state_inspection = inspect_state_projection_transaction(
                release_root,
                _ignore_lock=True,
            )
            if state_inspection["decision"] != "PASS":
                recovery = recover_state_projection_transaction(
                    release_root,
                    lock_handle=state_lock_handle,
                )
                if recovery["decision"] not in {"RECOVERED", "NO_CHANGE"}:
                    state_failures.extend(
                        f"STATE_RECOVERY_FAILED:{finding}"
                        for finding in recovery.get("findings", [])
                    )
            if not state_failures:
                apply_state_projection_transaction(
                    release_root,
                    state_before,
                    lock_handle=state_lock_handle,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            state_failures.append(f"STATE_RESTORE_FAILED:{type(exc).__name__}:{exc}")
    failures.extend(state_failures)
    recovered_refs: list[str] = []
    for raw in reversed(payload["targets"]):
        ref, before, _after = _decode_record(raw)
        if ref not in attempted:
            continue
        try:
            if _digest(_read_bytes(_target_path(process_root, ref))) == _digest(before):
                recovered_refs.append(ref)
            elif not any(failure.endswith(ref) for failure in failures):
                failures.append(f"RESTORE_INCOMPLETE:{ref}")
        except (OSError, ValueError) as exc:
            failures.append(f"RESTORE_VERIFY_FAILED:{ref}:{type(exc).__name__}")
    return failures, recovered_refs


def inspect_phase_transition(
    release_root: Path,
    process_root: Path,
    *,
    _ignore_locks: bool = False,
) -> dict[str, Any]:
    try:
        _path, payload = _load_manifest(release_root)
    except (OSError, ValueError) as exc:
        return {"decision": "BLOCKED", "state": "INVALID", "findings": [str(exc)]}
    if payload is None:
        if _ignore_locks:
            return {"decision": "PASS", "state": "NONE", "findings": []}
        findings: list[str] = []
        try:
            if transaction_lock_identity(release_root.resolve() / LOCK_REL) is not None:
                findings.append("ORPHAN_PHASE_TRANSITION_LOCK")
            if transaction_lock_identity(_state_lock_path(release_root)) is not None:
                findings.append("STATE_PROJECTION_LOCK_PRESENT")
        except (OSError, ValueError) as exc:
            findings.append(f"PHASE_TRANSITION_LOCK_UNSAFE:{exc}")
        return {
            "decision": "BLOCKED" if findings else "PASS",
            "state": "NONE",
            "findings": findings,
        }
    findings: list[str] = []
    if payload["state"] not in TERMINAL_STATES:
        findings.append(f"UNRESOLVED_PHASE_TRANSITION:{payload['state']}")
    if not _ignore_locks:
        phase_lock = release_root.resolve() / LOCK_REL
        state_lock = _state_lock_path(release_root)
        try:
            if phase_lock.exists() or phase_lock.is_symlink():
                findings.append("PHASE_TRANSITION_LOCK_PRESENT")
            if transaction_lock_identity(state_lock) is not None:
                findings.append("STATE_PROJECTION_LOCK_PRESENT")
        except (OSError, ValueError) as exc:
            findings.append(f"PHASE_TRANSITION_LOCK_UNSAFE:{exc}")
    return {
        "decision": "BLOCKED" if findings else "PASS",
        "state": payload["state"],
        "transaction_id": payload["transaction_id"],
        "findings": findings,
    }


def recover_phase_transition(
    release_root: Path,
    process_root: Path,
) -> dict[str, Any]:
    release = release_root.resolve()
    manifest_path, payload = _load_manifest(release)
    if payload is None:
        phase_lock_path = release / LOCK_REL
        state_lock_path = _state_lock_path(release)
        phase_handle: TransactionLockHandle | None = None
        try:
            lock_recovered = False
            if transaction_lock_identity(state_lock_path) is not None:
                state_recovery = recover_state_projection_transaction(release)
                if state_recovery["decision"] not in {"NO_CHANGE", "RECOVERED"}:
                    return {
                        "decision": "BLOCKED",
                        "state": "NONE",
                        "recovered_refs": [],
                        "findings": list(state_recovery.get("findings", [])),
                    }
                lock_recovered = bool(state_recovery.get("lock_recovered"))
            phase_identity = transaction_lock_identity(phase_lock_path)
            if phase_identity is not None:
                phase_handle = claim_transaction_lock(
                    phase_lock_path,
                    phase_identity,
                    create_if_missing=False,
                )
                lock_recovered = True
            return {
                "decision": "NO_CHANGE",
                "state": "NONE",
                "recovered_refs": [],
                "lock_recovered": lock_recovered,
                "findings": [],
            }
        except (OSError, ValueError) as exc:
            return {
                "decision": "BLOCKED",
                "state": "NONE",
                "recovered_refs": [],
                "findings": [str(exc)],
            }
        finally:
            _release_handles(phase_handle)
    transaction_id = str(payload["transaction_id"])
    phase_lock_path = release / LOCK_REL
    state_lock_path = state_projection_lock_path(release)
    state_handle: TransactionLockHandle | None = None
    phase_handle: TransactionLockHandle | None = None
    shared_writer_handle = None
    shared_writer_id = "phase-recover-" + transaction_id
    try:
        if payload["state"] in TERMINAL_STATES:
            needs_successor_finalization = (
                payload["state"] == "COMMITTED" and "successor_id" not in payload
            )
            if needs_successor_finalization:
                shared_writer_handle = acquire_shared_projection_writer_lock(
                    process_root,
                    shared_writer_id,
                )
                if phase_lock_path.exists() or phase_lock_path.is_symlink():
                    phase_handle = claim_transaction_lock(
                        phase_lock_path,
                        transaction_id,
                        create_if_missing=False,
                    )
                else:
                    phase_handle = acquire_transaction_lock(
                        phase_lock_path,
                        transaction_id,
                    )
            state_lock_identity = transaction_lock_identity(state_lock_path)
            if state_lock_identity == transaction_id:
                state_handle = claim_transaction_lock(
                    state_lock_path, transaction_id, create_if_missing=False
                )
            elif state_lock_identity is not None:
                state_recovery = recover_state_projection_transaction(release)
                if state_recovery["decision"] not in {"NO_CHANGE", "RECOVERED"}:
                    return {
                        "decision": "BLOCKED",
                        "state": payload["state"],
                        "recovered_refs": [],
                        "findings": list(state_recovery.get("findings", [])),
                    }
            if phase_handle is None and (
                phase_lock_path.exists() or phase_lock_path.is_symlink()
            ):
                phase_handle = claim_transaction_lock(
                    phase_lock_path,
                    transaction_id,
                    create_if_missing=False,
                )
            inspection = inspect_phase_transition(
                release,
                process_root,
                _ignore_locks=True,
            )
            if inspection["decision"] == "PASS" and needs_successor_finalization:
                successor_before = {
                    ref.removeprefix("process/"): str(raw["before_digest"])
                    for raw in payload["targets"]
                    if str(raw["ref"])
                    not in STATE_TARGET_REFS | {"process/current/CURRENT.json"}
                    and str(raw["before_digest"]) != "missing"
                    for ref in (str(raw["ref"]),)
                }
                successor_id = record_shared_projection_successor(
                    process_root,
                    operation="project.phase-transition",
                    writer_id=transaction_id,
                    before_digests=successor_before,
                    allowed_refs=tuple(successor_before),
                )
                payload["successor_id"] = successor_id
                _write_manifest(manifest_path, payload)
            return {
                "decision": "NO_CHANGE" if inspection["decision"] == "PASS" else "BLOCKED",
                "state": payload["state"],
                "recovered_refs": [],
                "lock_recovered": state_handle is not None or phase_handle is not None,
                "shared_projection_successor_id": str(payload.get("successor_id") or ""),
                "findings": inspection["findings"],
            }
        shared_writer_handle = acquire_shared_projection_writer_lock(
            process_root,
            shared_writer_id,
        )
        state_handle = claim_transaction_lock(
            state_lock_path,
            transaction_id,
            create_if_missing=True,
        )
        phase_handle = claim_transaction_lock(
            phase_lock_path,
            transaction_id,
            create_if_missing=True,
        )
        assert state_handle is not None and phase_handle is not None
        _current_manifest_path, current_payload = _load_manifest(release)
        if current_payload is None or current_payload["transaction_id"] != transaction_id:
            raise ValueError("Phase transition changed while acquiring recovery locks")
        payload = current_payload
        cleanup_failures: list[str] = []
        successor_id = str(payload.get("successor_id") or "")
        if successor_id:
            try:
                discard_shared_projection_successor(
                    process_root,
                    successor_id=successor_id,
                    operation="project.phase-transition",
                    writer_id=transaction_id,
                )
                payload.pop("successor_id", None)
            except (OSError, ValueError) as cleanup_exc:
                cleanup_failures.append(
                    "SUCCESSOR_RECEIPT_RECOVERY_FAILED:"
                    f"{type(cleanup_exc).__name__}:{cleanup_exc}"
                )
        failures, recovered_refs = _restore(
            release,
            process_root,
            payload,
            state_lock_handle=state_handle,
        )
        failures = [*cleanup_failures, *failures]
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
            _release_handles(phase_handle, state_handle)
        finally:
            if shared_writer_handle is not None:
                release_shared_projection_writer_lock(
                    shared_writer_handle,
                    shared_writer_id,
                )


def apply_phase_transition(
    plan: PhaseTransitionPlan,
    *,
    expected_plan_digest: str,
    expected_release_oid: str,
    expected_process_oid: str,
) -> dict[str, Any]:
    if plan.decision == "BLOCKED":
        raise ValueError("phase transition plan is blocked: " + "; ".join(plan.errors))
    if (
        expected_plan_digest != plan.plan_digest
        or expected_release_oid != plan.release_oid
        or expected_process_oid != plan.process_oid
    ):
        raise ValueError("expected plan digest/OIDs do not match the Phase transition plan")
    current_plan = plan_phase_transition(
        plan.release_root,
        plan.process_root,
        project_id=plan.project_id,
        from_phase_ref=plan.from_phase_ref,
        to_phase_ref=plan.to_phase_ref,
        closure_evidence_ref=plan.closure_evidence_ref,
        effective_at=plan.effective_at,
        immutable_commit_roles=plan.immutable_commit_roles,
    )
    if current_plan.plan_digest != plan.plan_digest:
        raise ValueError("Phase transition source, OID, or target preimage drifted after planning")
    inspection = inspect_phase_transition(plan.release_root, plan.process_root)
    if inspection["decision"] != "PASS":
        raise ValueError("unresolved Phase transition requires inspect/recover")
    if plan.decision == "NOOP":
        return {
            "schema_version": 1,
            "kind": RECEIPT_KIND,
            "operation": "project.phase-transition",
            "decision": "PASS",
            "disposition": "NOOP",
            "mutation_count": 0,
            "plan_digest": plan.plan_digest,
        }
    changed = plan.changed_refs
    _runtime_root, manifest_path, lock_path = _runtime_paths(plan.release_root)
    transaction_id = _canonical_digest(
        [
            {"ref": ref, "before": plan.preimages[ref], "after": _digest(plan.targets[ref])}
            for ref in changed
        ]
    )[:32]
    shared_writer_id = "phase-transition-" + transaction_id
    shared_writer_handle = acquire_shared_projection_writer_lock(
        plan.process_root,
        shared_writer_id,
    )
    state_lock_handle: TransactionLockHandle | None = None
    phase_lock_handle: TransactionLockHandle | None = None
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
        "attempted_refs": [],
        "applied_refs": [],
        "targets": [
            _record(ref, _read_bytes(_target_path(plan.process_root, ref)), plan.targets[ref])
            for ref in ordered_refs
        ],
    }
    successor_before = {
        ref.removeprefix("process/"): str(raw["before_digest"])
        for raw in payload["targets"]
        if str(raw["ref"])
        not in STATE_TARGET_REFS | {"process/current/CURRENT.json"}
        and str(raw["before_digest"]) != "missing"
        for ref in (str(raw["ref"]),)
    }
    journal_started = False
    try:
        state_lock_handle = acquire_transaction_lock(
            state_projection_lock_path(plan.release_root),
            transaction_id,
        )
        phase_lock_handle = acquire_transaction_lock(lock_path, transaction_id)
        validate_transaction_lock(
            state_lock_handle,
            expected_path=state_projection_lock_path(plan.release_root),
        )
        validate_transaction_lock(phase_lock_handle, expected_path=lock_path)
        locked_inspection = inspect_phase_transition(
            plan.release_root,
            plan.process_root,
            _ignore_locks=True,
        )
        if locked_inspection["decision"] != "PASS":
            raise ValueError("unresolved Phase transition requires inspect/recover")
        locked_plan = plan_phase_transition(
            plan.release_root,
            plan.process_root,
            project_id=plan.project_id,
            from_phase_ref=plan.from_phase_ref,
            to_phase_ref=plan.to_phase_ref,
            closure_evidence_ref=plan.closure_evidence_ref,
            effective_at=plan.effective_at,
            immutable_commit_roles=plan.immutable_commit_roles,
        )
        if locked_plan.plan_digest != plan.plan_digest:
            raise ValueError(
                "Phase transition source or preimage drifted while acquiring writer locks"
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
            assert state_lock_handle is not None
            state_receipt = apply_state_projection_transaction(
                plan.release_root,
                state_targets,
                lock_handle=state_lock_handle,
            )
            if state_receipt["decision"] != "PASS" or state_receipt["mutation_count"] != len(
                state_targets
            ):
                raise RuntimeError(
                    "State projection subtransaction did not apply the frozen target set"
                )
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
                "Phase transition postimage verification failed: " + ", ".join(drifted)
            )
        payload["state"] = "COMMITTED"
        _write_manifest(manifest_path, payload)
        successor_id = record_shared_projection_successor(
            plan.process_root,
            operation="project.phase-transition",
            writer_id=transaction_id,
            before_digests=successor_before,
            allowed_refs=tuple(successor_before),
        )
        payload["successor_id"] = successor_id
        _write_manifest(manifest_path, payload)
        return {
            "schema_version": 1,
            "kind": RECEIPT_KIND,
            "operation": "project.phase-transition",
            "decision": "PASS",
            "disposition": "APPLIED",
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
        cleanup_failures: list[str] = []
        successor_id = str(payload.get("successor_id") or "")
        if successor_id:
            try:
                discard_shared_projection_successor(
                    plan.process_root,
                    successor_id=successor_id,
                    operation="project.phase-transition",
                    writer_id=transaction_id,
                )
                payload.pop("successor_id", None)
            except (OSError, ValueError) as cleanup_exc:
                cleanup_failures.append(
                    "SUCCESSOR_RECEIPT_RECOVERY_FAILED:"
                    f"{type(cleanup_exc).__name__}:{cleanup_exc}"
                )
        failures, recovered_refs = _restore(
            plan.release_root,
            plan.process_root,
            payload,
            state_lock_handle=state_lock_handle,
        )
        failures = [*cleanup_failures, *failures]
        unrecovered_refs = []
        for raw in payload["targets"]:
            ref, before, _after = _decode_record(raw)
            if ref not in payload["attempted_refs"]:
                continue
            try:
                if _digest(_read_bytes(_target_path(plan.process_root, ref))) != _digest(before):
                    unrecovered_refs.append(ref)
            except (OSError, ValueError) as verify_exc:
                unrecovered_refs.append(ref)
                failures.append(f"RECOVERY_ACCOUNTING_FAILED:{ref}:{type(verify_exc).__name__}")
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
            raise PhaseTransitionPartialError(
                {
                    "schema_version": 1,
                    "kind": RECEIPT_KIND,
                    "operation": "project.phase-transition",
                    "decision": "PARTIAL",
                    "disposition": "RECOVERY_REQUIRED",
                    "transaction_id": transaction_id,
                    "transaction_state": "PARTIAL",
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
            _release_handles(phase_lock_handle, state_lock_handle)
        finally:
            release_shared_projection_writer_lock(
                shared_writer_handle,
                shared_writer_id,
            )


def _cli_blocked(project_id: str, error_code: str, error: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": PLAN_KIND,
        "operation": "project.phase-transition",
        "project_id": project_id,
        "decision": "BLOCKED",
        "dry_run": True,
        "mutation_count": 0,
        "planned_mutation_count": 0,
        "error_code": error_code,
        "errors": [error],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project phase-transition")
    parser.add_argument("action", choices=("plan", "apply", "inspect", "recover"))
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--from-phase-ref")
    parser.add_argument("--to-phase-ref")
    parser.add_argument("--closure-evidence-ref")
    parser.add_argument("--effective-at")
    parser.add_argument(
        "--immutable-commit-role",
        action="append",
        type=_parse_immutable_commit_role,
        default=[],
    )
    parser.add_argument("--expected-plan-digest")
    parser.add_argument("--expected-release-oid")
    parser.add_argument("--expected-process-oid")
    parsed = parser.parse_args(argv or [])
    from meta_flow.project.process_route import ProcessRouteError, require_project_process_route

    try:
        route = require_project_process_route(
            parsed.project_root.resolve(),
            project_id=parsed.project_id,
        )
    except ProcessRouteError as exc:
        print(
            json.dumps(
                _cli_blocked(parsed.project_id, exc.error_code, str(exc)),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    if parsed.action in {"inspect", "recover"}:
        try:
            result = (
                inspect_phase_transition(route.project_root, route.process_root)
                if parsed.action == "inspect"
                else recover_phase_transition(route.project_root, route.process_root)
            )
        except (OSError, ValueError) as exc:
            result = _cli_blocked(parsed.project_id, "phase_transition_recovery_blocked", str(exc))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("decision") in {"PASS", "NO_CHANGE", "RECOVERED"} else 2
    missing = [
        name
        for name, value in (
            ("--from-phase-ref", parsed.from_phase_ref),
            ("--to-phase-ref", parsed.to_phase_ref),
            ("--closure-evidence-ref", parsed.closure_evidence_ref),
            ("--effective-at", parsed.effective_at),
            ("--immutable-commit-role", parsed.immutable_commit_role),
        )
        if not value
    ]
    if missing:
        print(
            json.dumps(
                _cli_blocked(
                    parsed.project_id,
                    "phase_transition_input_missing",
                    "missing required transition inputs: " + ", ".join(missing),
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    try:
        plan = plan_phase_transition(
            route.project_root,
            route.process_root,
            project_id=parsed.project_id,
            from_phase_ref=str(parsed.from_phase_ref),
            to_phase_ref=str(parsed.to_phase_ref),
            closure_evidence_ref=str(parsed.closure_evidence_ref),
            effective_at=str(parsed.effective_at),
            immutable_commit_roles=tuple(parsed.immutable_commit_role),
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
    missing_expected = [
        name
        for name, value in (
            ("--expected-plan-digest", parsed.expected_plan_digest),
            ("--expected-release-oid", parsed.expected_release_oid),
            ("--expected-process-oid", parsed.expected_process_oid),
        )
        if not value
    ]
    if missing_expected:
        print(
            json.dumps(
                _cli_blocked(
                    parsed.project_id,
                    "phase_transition_apply_input_missing",
                    "apply requires " + ", ".join(missing_expected),
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    try:
        receipt = apply_phase_transition(
            plan,
            expected_plan_digest=str(parsed.expected_plan_digest),
            expected_release_oid=str(parsed.expected_release_oid),
            expected_process_oid=str(parsed.expected_process_oid),
        )
    except PhaseTransitionPartialError as exc:
        print(
            json.dumps(
                {"plan": plan.as_dict(), "receipt": exc.result},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    except (OSError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "plan": plan.as_dict(),
                    "decision": "BLOCKED",
                    "error_code": "phase_transition_apply_blocked",
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
    "PhaseTransitionPlan",
    "PhaseTransitionPartialError",
    "apply_phase_transition",
    "inspect_phase_transition",
    "main",
    "plan_phase_transition",
    "recover_phase_transition",
]
