"""PROJECT → ROADMAP → declared Phase 的长期治理投影生成与检查。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.model import Project, is_safe_ref, load_project
from meta_flow.project.scale import load_yaml_object

GOVERNANCE_PROJECTION_REL = Path("governance/GOVERNANCE-BASELINE.json")
GOVERNANCE_PROJECTION_KIND = "GovernanceBaselineProjectionV1"
GOVERNANCE_PROJECTION_SCHEMA_VERSION = 1
GOVERNANCE_REFRESH_PLAN_KIND = "GovernanceBaselineRefreshPlanV1"
GOVERNANCE_REFRESH_RECEIPT_KIND = "GovernanceBaselineRefreshReceiptV1"
PHASE_STATUSES = frozenset({"planned", "active", "blocked", "completed", "archived"})
RUNTIME_IDENTITY_ROLES = ("release_head", "process_head")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_PREIMAGE_ABSENT = "absent"

PUBLIC_OPERATION_DECLARATIONS = (
    (
        "governance.baseline-refresh",
        ("meta-flow", "governance", "baseline-refresh"),
    ),
)


@dataclass(frozen=True)
class ImmutableCommitRole:
    """治理投影中由调用方显式声明的不可变提交角色。"""

    role: str
    repository: str
    oid: str

    def as_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "repository": self.repository,
            "oid": self.oid,
        }


@dataclass(frozen=True)
class GovernanceBaselineRefreshPlan:
    """单文件治理投影刷新计划；对象本身不执行写入。"""

    release_root: Path
    process_root: Path
    project_id: str
    target_path: Path
    immutable_commit_roles: tuple[ImmutableCommitRole, ...]
    projection: dict[str, Any]
    release_oid: str
    process_oid: str
    target_preimage: str
    decision: str
    errors: tuple[str, ...]
    plan_digest: str

    @property
    def blocked(self) -> bool:
        return self.decision == "BLOCKED"

    @property
    def planned_mutation_count(self) -> int:
        return 1 if self.decision == "READY" else 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": GOVERNANCE_REFRESH_PLAN_KIND,
            "operation": "governance.baseline-refresh",
            "project_id": self.project_id,
            "decision": self.decision,
            "dry_run": True,
            "mutation_count": 0,
            "planned_mutation_count": self.planned_mutation_count,
            "target_ref": _logical(GOVERNANCE_PROJECTION_REL.as_posix()),
            "expected_oids": {
                "release_head": self.release_oid,
                "process_head": self.process_oid,
            },
            "expected_preimage": self.target_preimage,
            "immutable_commit_roles": [item.as_dict() for item in self.immutable_commit_roles],
            "projection": self.projection,
            "semantic_digest": self.projection.get("semantic_digest", ""),
            "transaction": {
                "strategy": "single-file-atomic-replace",
                "recovery_required": False,
            },
            "errors": list(self.errors),
            "plan_digest": self.plan_digest,
        }


class GovernanceProjectionApplyError(RuntimeError):
    """治理投影 apply 在任何写入前或原子替换后校验失败。"""


def _logical(ref: str) -> str:
    return f"process/{ref}"


def _safe_file(process_root: Path, ref: str, *, subject: str) -> Path:
    if not is_safe_ref(ref):
        raise ValueError(f"{subject} is not a safe process-relative ref: {ref}")
    path = process_root / ref
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{subject} does not resolve to a regular file: {_logical(ref)}")
    return path


def _string_list(value: Any, *, subject: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{subject} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{subject} must not contain duplicate refs")
    return list(value)


def build_governance_truth(
    process_root: Path,
    *,
    expected_project_id: str = "",
) -> dict[str, Any]:
    """Build the six-object long-term declaration closure without sibling discovery."""

    root = process_root.resolve()
    project: Project = load_project(root)
    if expected_project_id and project.project_id != expected_project_id:
        raise ValueError("PROJECT.yaml project_id differs from the requested project_id")
    if not project.roadmap_ref:
        raise ValueError("PROJECT.yaml does not declare roadmap_ref")
    roadmap_path = _safe_file(root, project.roadmap_ref, subject="PROJECT.roadmap_ref")
    roadmap = load_yaml_object(roadmap_path)
    if roadmap.get("schema_version") != 1:
        raise ValueError("ROADMAP.yaml schema_version must be 1")
    if roadmap.get("project_id") != project.project_id:
        raise ValueError("ROADMAP.yaml project_id differs from PROJECT.yaml")
    if roadmap.get("status") not in {"planned", "active", "blocked", "completed"}:
        raise ValueError("ROADMAP.yaml status is invalid")
    phase_refs = _string_list(roadmap.get("phase_refs"), subject="ROADMAP.phase_refs")
    phase_payloads: dict[str, dict[str, Any]] = {}

    for phase_ref in phase_refs:
        phase_path = _safe_file(root, phase_ref, subject="ROADMAP.phase_refs[]")
        phase = load_yaml_object(phase_path)
        phase_payloads[phase_ref] = phase
        if phase.get("schema_version") != 1:
            raise ValueError(f"{_logical(phase_ref)} schema_version must be 1")
        if phase.get("project_id") != project.project_id:
            raise ValueError(f"{_logical(phase_ref)} project_id differs from PROJECT.yaml")
        phase_id = phase.get("phase_id")
        if not isinstance(phase_id, str) or not phase_id:
            raise ValueError(f"{_logical(phase_ref)} phase_id must be non-empty")
        status = phase.get("status")
        if status not in PHASE_STATUSES:
            raise ValueError(f"{_logical(phase_ref)} status is invalid: {status}")
        logical_phase_ref = _logical(phase_ref)
        result_refs = _string_list(
            phase.get("result_refs", []), subject=f"{logical_phase_ref}.result_refs"
        )
        for result_ref in result_refs:
            # 投影 writer 必须能够首次创建自己的目标文件。其余 result ref 仍然
            # fail-closed，避免把不存在的阶段结果纳入长期治理闭包。
            if result_ref != GOVERNANCE_PROJECTION_REL.as_posix():
                _safe_file(root, result_ref, subject=f"{logical_phase_ref}.result_refs[]")
    return build_governance_truth_from_payloads(
        project.as_dict(),
        roadmap,
        phase_payloads,
    )


def build_governance_truth_from_payloads(
    project: dict[str, Any],
    roadmap: dict[str, Any],
    phases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """从已验证或事务 post-image 构造长期治理闭包，不执行 I/O。"""

    project_id = str(project.get("project_id") or "")
    roadmap_ref = str(project.get("roadmap_ref") or "")
    phase_refs = _string_list(roadmap.get("phase_refs"), subject="ROADMAP.phase_refs")
    if not roadmap_ref or roadmap.get("project_id") != project_id:
        raise ValueError("ROADMAP.yaml project_id differs from PROJECT.yaml")
    if set(phases) != set(phase_refs):
        raise ValueError("declared Phase payload set differs from ROADMAP.phase_refs")
    phase_statuses: dict[str, str] = {}
    active_phase_refs: list[str] = []
    active_result_refs: list[str] = []
    phase_ids: set[str] = set()
    for phase_ref in phase_refs:
        phase = phases[phase_ref]
        if phase.get("schema_version") != 1 or phase.get("project_id") != project_id:
            raise ValueError(f"{_logical(phase_ref)} schema/project identity is invalid")
        phase_id = str(phase.get("phase_id") or "")
        if not phase_id or phase_id in phase_ids:
            raise ValueError(f"duplicate or empty declared phase_id: {phase_id or '-'}")
        phase_ids.add(phase_id)
        status = str(phase.get("status") or "")
        if status not in PHASE_STATUSES:
            raise ValueError(f"{_logical(phase_ref)} status is invalid: {status}")
        logical_phase_ref = _logical(phase_ref)
        phase_statuses[logical_phase_ref] = status
        result_refs = _string_list(
            phase.get("result_refs", []),
            subject=f"{logical_phase_ref}.result_refs",
        )
        if status == "active":
            active_phase_refs.append(logical_phase_ref)
            active_result_refs.extend(_logical(ref) for ref in result_refs)
    if project.get("status") == "active" and len(active_phase_refs) != 1:
        raise ValueError(
            "an active PROJECT must have exactly one active declared Phase: "
            f"found {len(active_phase_refs)}"
        )
    project_active = str(project.get("active_phase_ref") or "")
    if project_active and active_phase_refs != [_logical(project_active)]:
        raise ValueError("PROJECT.active_phase_ref differs from the active declared Phase")
    projection_ref = _logical(GOVERNANCE_PROJECTION_REL.as_posix())
    if active_phase_refs and projection_ref not in active_result_refs:
        raise ValueError(
            f"the active Phase must declare the governance projection result_ref: {projection_ref}"
        )
    return {
        "project_ref": "process/PROJECT.yaml",
        "roadmap_ref": _logical(roadmap_ref),
        "phase_refs": [_logical(ref) for ref in phase_refs],
        "phase_statuses": phase_statuses,
        "active_phase_refs": active_phase_refs,
        "active_result_refs": active_result_refs,
    }


def _semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload.get("schema_version"),
        "kind": payload.get("kind"),
        "project_ref": payload.get("project_ref"),
        "roadmap_ref": payload.get("roadmap_ref"),
        "phase_refs": payload.get("phase_refs"),
        "phase_statuses": payload.get("phase_statuses"),
        "active_phase_refs": payload.get("active_phase_refs"),
        "active_result_refs": payload.get("active_result_refs"),
        "immutable_commit_roles": payload.get("immutable_commit_roles"),
        "runtime_identity_roles": payload.get("runtime_identity_roles"),
    }


def semantic_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        _semantic_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _normalize_immutable_commit_roles(
    roles: list[dict[str, Any] | ImmutableCommitRole]
    | tuple[dict[str, Any] | ImmutableCommitRole, ...],
) -> tuple[tuple[ImmutableCommitRole, ...], list[str]]:
    normalized: list[ImmutableCommitRole] = []
    errors: list[str] = []
    if not roles:
        return (), ["at least one immutable commit role is required"]
    seen: set[str] = set()
    for index, item in enumerate(roles):
        if isinstance(item, ImmutableCommitRole):
            role = item
        elif isinstance(item, dict) and set(item) == {"role", "repository", "oid"}:
            role = ImmutableCommitRole(
                role=str(item.get("role") or ""),
                repository=str(item.get("repository") or ""),
                oid=str(item.get("oid") or "").lower(),
            )
        else:
            errors.append(
                f"immutable_commit_roles[{index}] must use exact role/repository/oid shape"
            )
            continue
        if not role.role or role.role in seen:
            errors.append(f"immutable_commit_roles[{index}].role is empty or duplicate")
            continue
        seen.add(role.role)
        if role.repository not in {"release", "process"}:
            errors.append(f"immutable_commit_roles[{index}].repository is invalid")
            continue
        if not _OID_RE.fullmatch(role.oid):
            errors.append(f"immutable_commit_roles[{index}].oid must be lowercase 40-hex")
            continue
        normalized.append(role)
    return tuple(normalized), errors


def _validate_immutable_commit_roles(
    roles: tuple[ImmutableCommitRole, ...],
    *,
    release_root: Path,
    process_root: Path,
    release_head: str,
    process_head: str,
) -> list[str]:
    errors: list[str] = []
    for item in roles:
        repository_root = release_root if item.repository == "release" else process_root
        head_oid = release_head if item.repository == "release" else process_head
        if not head_oid:
            continue
        exists = _git(repository_root, "cat-file", "-e", f"{item.oid}^{{commit}}")
        if exists.returncode != 0:
            errors.append(f"immutable commit role {item.role} does not exist in {item.repository}")
            continue
        ancestor = _git(
            repository_root,
            "merge-base",
            "--is-ancestor",
            item.oid,
            head_oid,
        )
        if ancestor.returncode != 0:
            errors.append(
                f"immutable commit role {item.role} is not an ancestor of {item.repository} HEAD"
            )
    return errors


def build_governance_projection(
    process_root: Path,
    immutable_commit_roles: tuple[ImmutableCommitRole, ...],
) -> dict[str, Any]:
    """从声明闭包与显式不可变提交角色构造确定性投影。"""

    payload: dict[str, Any] = {
        "schema_version": GOVERNANCE_PROJECTION_SCHEMA_VERSION,
        "kind": GOVERNANCE_PROJECTION_KIND,
        **build_governance_truth(process_root),
        "immutable_commit_roles": [item.as_dict() for item in immutable_commit_roles],
        "runtime_identity_roles": list(RUNTIME_IDENTITY_ROLES),
    }
    payload["semantic_digest"] = semantic_digest(payload)
    return payload


def build_governance_projection_from_truth(
    truth: dict[str, Any],
    immutable_commit_roles: tuple[ImmutableCommitRole, ...],
) -> dict[str, Any]:
    """从事务冻结的长期治理闭包构造确定性投影。"""

    payload: dict[str, Any] = {
        "schema_version": GOVERNANCE_PROJECTION_SCHEMA_VERSION,
        "kind": GOVERNANCE_PROJECTION_KIND,
        **truth,
        "immutable_commit_roles": [item.as_dict() for item in immutable_commit_roles],
        "runtime_identity_roles": list(RUNTIME_IDENTITY_ROLES),
    }
    payload["semantic_digest"] = semantic_digest(payload)
    return payload


def build_governance_projection_for_phase_postimage(
    process_root: Path,
    *,
    phase_ref: str,
    phase_payload: dict[str, Any],
    require_current: bool = True,
) -> dict[str, Any]:
    """基于一个冻结的 Phase post-image 刷新既有治理投影。

    Work close 等上层多文件事务只能在既有投影与当前声明真相完全一致时调用
    本函数。它保留已经验证并发布过的 immutable commit roles，仅替换调用方
    明确拥有的 Phase post-image，避免上层 writer 重新推断身份角色或接纳陈旧
    投影。
    """

    root = process_root.resolve()
    projection_path = _safe_file(
        root,
        GOVERNANCE_PROJECTION_REL.as_posix(),
        subject="governance projection",
    )
    try:
        existing = json.loads(projection_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"governance projection is invalid JSON: {exc}") from exc
    if not isinstance(existing, dict):
        raise ValueError("governance projection must be a JSON object")
    raw_roles = existing.get("immutable_commit_roles")
    if not isinstance(raw_roles, list):
        raise ValueError("immutable_commit_roles must be a list")
    roles, role_errors = _normalize_immutable_commit_roles(raw_roles)
    if role_errors:
        raise ValueError("; ".join(role_errors))

    current_truth = build_governance_truth(root)
    expected_current = build_governance_projection_from_truth(current_truth, roles)
    if require_current and existing != expected_current:
        raise ValueError("governance projection must be current before Phase mutation")

    project = load_project(root)
    roadmap = load_yaml_object(_safe_file(root, project.roadmap_ref, subject="PROJECT.roadmap_ref"))
    phase_refs = _string_list(roadmap.get("phase_refs"), subject="ROADMAP.phase_refs")
    if phase_ref not in phase_refs:
        raise ValueError("Phase post-image is not declared by ROADMAP.phase_refs")
    phase_payloads = {
        ref: load_yaml_object(_safe_file(root, ref, subject="ROADMAP.phase_refs[]"))
        for ref in phase_refs
    }
    phase_payloads[phase_ref] = dict(phase_payload)
    post_truth = build_governance_truth_from_payloads(
        project.as_dict(),
        roadmap,
        phase_payloads,
    )
    return build_governance_projection_from_truth(post_truth, roles)


def _target_preimage(path: Path, errors: list[str]) -> tuple[str, bytes | None]:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        errors.append(
            "governance projection target is not a regular file: "
            f"{_logical(GOVERNANCE_PROJECTION_REL.as_posix())}"
        )
        return "invalid", None
    if not path.is_file():
        return _PREIMAGE_ABSENT, None
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest(), content


def _render_projection(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def render_governance_projection(payload: dict[str, Any]) -> bytes:
    """以治理投影唯一的 canonical JSON 格式渲染冻结 payload。"""

    return _render_projection(payload)


def _plan_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def plan_governance_baseline_refresh(
    release_root: Path,
    process_root: Path,
    *,
    project_id: str,
    immutable_commit_roles: list[dict[str, Any] | ImmutableCommitRole]
    | tuple[dict[str, Any] | ImmutableCommitRole, ...],
) -> GovernanceBaselineRefreshPlan:
    """构造零写入治理投影刷新计划。"""

    release = release_root.resolve()
    process = process_root.resolve()
    errors: list[str] = []
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

    target = process / GOVERNANCE_PROJECTION_REL
    if target.parent.is_symlink() or (target.parent.exists() and not target.parent.is_dir()):
        errors.append("governance projection parent is not a directory: process/governance")
    target_preimage, existing_content = _target_preimage(target, errors)
    projection: dict[str, Any] = {}
    try:
        projection = build_governance_projection(process, roles)
        if load_project(process).project_id != project_id:
            errors.append("PROJECT.yaml project_id differs from the requested project_id")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))

    rendered = _render_projection(projection) if projection else b""
    if errors:
        decision = "BLOCKED"
    elif existing_content == rendered:
        decision = "NOOP"
    else:
        decision = "READY"
    digest_payload = {
        "operation": "governance.baseline-refresh",
        "project_id": project_id,
        "decision": decision,
        "target_ref": _logical(GOVERNANCE_PROJECTION_REL.as_posix()),
        "expected_oids": {
            "release_head": release_oid,
            "process_head": process_oid,
        },
        "expected_preimage": target_preimage,
        "projection": projection,
        "errors": errors,
    }
    return GovernanceBaselineRefreshPlan(
        release_root=release,
        process_root=process,
        project_id=project_id,
        target_path=target,
        immutable_commit_roles=roles,
        projection=projection,
        release_oid=release_oid,
        process_oid=process_oid,
        target_preimage=target_preimage,
        decision=decision,
        errors=tuple(errors),
        plan_digest=_plan_digest(digest_payload),
    )


def _atomic_replace(path: Path, content: bytes) -> None:
    from meta_flow.state.projection_transaction import atomic_replace_bytes

    atomic_replace_bytes(path, content)


def apply_governance_baseline_refresh(
    plan: GovernanceBaselineRefreshPlan,
    *,
    expected_plan_digest: str,
    expected_release_oid: str,
    expected_process_oid: str,
    expected_preimage: str,
) -> dict[str, Any]:
    """在 OID、plan digest 与 preimage 全部匹配时原子写入一个投影文件。"""

    if plan.blocked:
        raise GovernanceProjectionApplyError(
            "governance baseline refresh plan is blocked: " + "; ".join(plan.errors)
        )
    expected = (
        expected_plan_digest,
        expected_release_oid,
        expected_process_oid,
        expected_preimage,
    )
    actual = (
        plan.plan_digest,
        plan.release_oid,
        plan.process_oid,
        plan.target_preimage,
    )
    if expected != actual:
        raise GovernanceProjectionApplyError(
            "expected plan digest/OIDs/preimage do not match the current plan"
        )

    from meta_flow.work.lifecycle_transaction import (
        acquire_shared_projection_writer_lock,
        release_shared_projection_writer_lock,
    )

    writer_id = "governance-baseline-" + plan.plan_digest[:32]
    lock = acquire_shared_projection_writer_lock(plan.process_root, writer_id)
    try:
        current_plan = plan_governance_baseline_refresh(
            plan.release_root,
            plan.process_root,
            project_id=plan.project_id,
            immutable_commit_roles=plan.immutable_commit_roles,
        )
        if current_plan.plan_digest != plan.plan_digest:
            raise GovernanceProjectionApplyError(
                "governance baseline source or target drifted after planning"
            )
        if current_plan.decision == "NOOP":
            check = validate_governance_projection(plan.release_root, plan.process_root)
            if check["decision"] != "PASS":
                raise GovernanceProjectionApplyError(
                    "existing governance projection failed validation: "
                    + "; ".join(check["errors"])
                )
            return {
                "schema_version": 1,
                "kind": GOVERNANCE_REFRESH_RECEIPT_KIND,
                "operation": "governance.baseline-refresh",
                "decision": "PASS",
                "disposition": "NOOP",
                "mutation_count": 0,
                "target_ref": _logical(GOVERNANCE_PROJECTION_REL.as_posix()),
                "semantic_digest": plan.projection["semantic_digest"],
                "plan_digest": plan.plan_digest,
            }
        if current_plan.decision != "READY":
            raise GovernanceProjectionApplyError(
                "governance baseline refresh is no longer ready"
            )

        _atomic_replace(plan.target_path, _render_projection(plan.projection))
        return {
            "schema_version": 1,
            "kind": GOVERNANCE_REFRESH_RECEIPT_KIND,
            "operation": "governance.baseline-refresh",
            "decision": "PASS",
            "disposition": "APPLIED",
            "mutation_count": 1,
            "target_ref": _logical(GOVERNANCE_PROJECTION_REL.as_posix()),
            "semantic_digest": plan.projection["semantic_digest"],
            "plan_digest": plan.plan_digest,
        }
    finally:
        release_shared_projection_writer_lock(lock, writer_id)


def validate_governance_projection(
    release_root: Path,
    process_root: Path,
) -> dict[str, Any]:
    """Validate declared truth, immutable commit roles, and runtime Git identities."""

    release = release_root.resolve()
    process = process_root.resolve()
    errors: list[str] = []
    try:
        truth = build_governance_truth(process)
    except (OSError, ValueError) as exc:
        return {
            "schema_version": 1,
            "kind": "GovernanceProjectionCheckV1",
            "decision": "BLOCKED",
            "errors": [str(exc)],
            "runtime_identity": {},
        }

    path = process / GOVERNANCE_PROJECTION_REL
    if path.is_symlink() or not path.is_file():
        errors.append(
            "governance projection is missing or not a regular file: "
            f"{_logical(GOVERNANCE_PROJECTION_REL.as_posix())}"
        )
        payload: dict[str, Any] = {}
    else:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"governance projection is invalid JSON: {exc}")
            payload = {}
        else:
            if not isinstance(loaded, dict):
                errors.append("governance projection must be a JSON object")
                payload = {}
            else:
                payload = loaded

    allowed_keys = {
        "schema_version",
        "kind",
        "project_ref",
        "roadmap_ref",
        "phase_refs",
        "phase_statuses",
        "active_phase_refs",
        "active_result_refs",
        "immutable_commit_roles",
        "runtime_identity_roles",
        "semantic_digest",
    }
    if payload:
        unknown = sorted(set(payload) - allowed_keys)
        if unknown:
            errors.append(f"governance projection has unknown fields: {', '.join(unknown)}")
        if payload.get("schema_version") != GOVERNANCE_PROJECTION_SCHEMA_VERSION:
            errors.append("governance projection schema_version must be 1")
        if payload.get("kind") != GOVERNANCE_PROJECTION_KIND:
            errors.append(f"governance projection kind must be {GOVERNANCE_PROJECTION_KIND}")
        for key, expected in truth.items():
            if payload.get(key) != expected:
                errors.append(f"governance projection {key} differs from declared truth")
        if payload.get("runtime_identity_roles") != list(RUNTIME_IDENTITY_ROLES):
            errors.append(
                "runtime_identity_roles must be [release_head, process_head] without persisted OIDs"
            )
        if payload.get("semantic_digest") != semantic_digest(payload):
            errors.append("governance projection semantic_digest mismatch")

    release_head = _head_oid(release, repository="release", errors=errors)
    process_head = _head_oid(process, repository="process", errors=errors)
    roles = payload.get("immutable_commit_roles", []) if payload else []
    if not isinstance(roles, list):
        errors.append("immutable_commit_roles must be a list")
        roles = []
    seen_roles: set[str] = set()
    for index, item in enumerate(roles):
        if not isinstance(item, dict) or set(item) != {"role", "repository", "oid"}:
            errors.append(
                f"immutable_commit_roles[{index}] must use exact role/repository/oid shape"
            )
            continue
        role = item.get("role")
        repository = item.get("repository")
        oid = item.get("oid")
        if not isinstance(role, str) or not role or role in seen_roles:
            errors.append(f"immutable_commit_roles[{index}].role is empty or duplicate")
            continue
        seen_roles.add(role)
        if repository not in {"release", "process"}:
            errors.append(f"immutable_commit_roles[{index}].repository is invalid")
            continue
        if not isinstance(oid, str) or not _OID_RE.fullmatch(oid):
            errors.append(f"immutable_commit_roles[{index}].oid must be lowercase 40-hex")
            continue
        repository_root = release if repository == "release" else process
        head_oid = release_head if repository == "release" else process_head
        if not head_oid:
            continue
        exists = _git(repository_root, "cat-file", "-e", f"{oid}^{{commit}}")
        if exists.returncode != 0:
            errors.append(f"immutable commit role {role} does not exist in {repository}")
            continue
        ancestor = _git(repository_root, "merge-base", "--is-ancestor", oid, head_oid)
        if ancestor.returncode != 0:
            errors.append(f"immutable commit role {role} is not an ancestor of {repository} HEAD")

    return {
        "schema_version": 1,
        "kind": "GovernanceProjectionCheckV1",
        "decision": "PASS" if not errors else "BLOCKED",
        "errors": errors,
        "runtime_identity": {
            "release_head": release_head,
            "process_head": process_head,
        },
        "declared_truth": truth,
    }


def _parse_immutable_commit_role(value: str) -> ImmutableCommitRole:
    """解析 ``ROLE=REPOSITORY:OID`` CLI 形式。"""

    try:
        role, repository_oid = value.split("=", 1)
        repository, oid = repository_oid.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "immutable commit role must use ROLE=release|process:OID"
        ) from exc
    role = role.strip()
    repository = repository.strip()
    oid = oid.strip().lower()
    if not role or repository not in {"release", "process"} or not _OID_RE.fullmatch(oid):
        raise argparse.ArgumentTypeError(
            "immutable commit role must use ROLE=release|process:40-hex-oid"
        )
    return ImmutableCommitRole(role=role, repository=repository, oid=oid)


def _blocked_cli_plan(
    *,
    project_id: str,
    error_code: str,
    error: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": GOVERNANCE_REFRESH_PLAN_KIND,
        "operation": "governance.baseline-refresh",
        "project_id": project_id,
        "decision": "BLOCKED",
        "dry_run": True,
        "mutation_count": 0,
        "planned_mutation_count": 0,
        "target_ref": _logical(GOVERNANCE_PROJECTION_REL.as_posix()),
        "expected_oids": {"release_head": "", "process_head": ""},
        "expected_preimage": "",
        "immutable_commit_roles": [],
        "projection": {},
        "semantic_digest": "",
        "transaction": {
            "strategy": "single-file-atomic-replace",
            "recovery_required": False,
        },
        "errors": [error],
        "error_code": error_code,
    }
    payload["plan_digest"] = _plan_digest(payload)
    return payload


def baseline_refresh_main(argv: list[str] | None = None) -> int:
    """``meta-flow governance baseline-refresh`` 的公开 CLI。"""

    parser = argparse.ArgumentParser(
        prog="meta-flow governance baseline-refresh",
        description=(
            "Plan or atomically refresh process/governance/GOVERNANCE-BASELINE.json "
            "from PROJECT, ROADMAP, and all declared Phase objects."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--immutable-commit-role",
        action="append",
        type=_parse_immutable_commit_role,
        required=True,
        metavar="ROLE=REPOSITORY:OID",
        help="Repeat for each immutable release/process commit role.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan-digest")
    parser.add_argument("--expected-release-oid")
    parser.add_argument("--expected-process-oid")
    parser.add_argument("--expected-preimage")
    parsed = parser.parse_args(argv or [])
    if parsed.apply and parsed.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")
    if parsed.apply:
        missing = [
            option
            for option, value in (
                ("--expected-plan-digest", parsed.expected_plan_digest),
                ("--expected-release-oid", parsed.expected_release_oid),
                ("--expected-process-oid", parsed.expected_process_oid),
                ("--expected-preimage", parsed.expected_preimage),
            )
            if not value
        ]
        if missing:
            parser.error("--apply requires " + ", ".join(missing))

    root = parsed.project_root.resolve()
    try:
        from meta_flow.project.process_route import (
            ProcessRouteError,
            require_project_process_route,
        )

        route = require_project_process_route(root, project_id=parsed.project_id)
        plan = plan_governance_baseline_refresh(
            route.project_root,
            route.process_root,
            project_id=parsed.project_id,
            immutable_commit_roles=tuple(parsed.immutable_commit_role),
        )
    except ProcessRouteError as exc:
        print(
            json.dumps(
                _blocked_cli_plan(
                    project_id=parsed.project_id,
                    error_code=exc.error_code,
                    error=str(exc),
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                _blocked_cli_plan(
                    project_id=parsed.project_id,
                    error_code="governance_baseline_plan_blocked",
                    error=str(exc),
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    except Exception as exc:  # pragma: no cover - defensive public CLI boundary
        print(
            json.dumps(
                _blocked_cli_plan(
                    project_id=parsed.project_id,
                    error_code="CHECK_HARNESS_ERROR",
                    error=f"{type(exc).__name__}: {exc}",
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    if not parsed.apply:
        print(json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True))
        return 2 if plan.blocked else 0
    try:
        receipt = apply_governance_baseline_refresh(
            plan,
            expected_plan_digest=str(parsed.expected_plan_digest),
            expected_release_oid=str(parsed.expected_release_oid),
            expected_process_oid=str(parsed.expected_process_oid),
            expected_preimage=str(parsed.expected_preimage),
        )
    except (GovernanceProjectionApplyError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "plan": plan.as_dict(),
                    "error_code": "governance_baseline_apply_blocked",
                    "error": str(exc),
                    "mutation_count": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {"plan": plan.as_dict(), "receipt": receipt},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "GOVERNANCE_REFRESH_PLAN_KIND",
    "GOVERNANCE_REFRESH_RECEIPT_KIND",
    "GOVERNANCE_PROJECTION_KIND",
    "GOVERNANCE_PROJECTION_REL",
    "GovernanceBaselineRefreshPlan",
    "GovernanceProjectionApplyError",
    "ImmutableCommitRole",
    "RUNTIME_IDENTITY_ROLES",
    "apply_governance_baseline_refresh",
    "baseline_refresh_main",
    "build_governance_projection",
    "build_governance_projection_for_phase_postimage",
    "build_governance_projection_from_truth",
    "build_governance_truth",
    "build_governance_truth_from_payloads",
    "plan_governance_baseline_refresh",
    "render_governance_projection",
    "semantic_digest",
    "validate_governance_projection",
]
