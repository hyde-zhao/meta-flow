"""S5 的 package-owned canonical execution-control runtime context。

本模块只从 release root 的健康 binding 构造事实；它不接受调用方注入的
AdmissionFacts、policy、provider receipt 或 process root。provider receipt 在 T2
接入前以 typed ``MISSING`` 候选状态表示，绝不作为 writer 降级开关。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

from meta_flow.execution_control.admission import execution_inventory_digest
from meta_flow.execution_control.contract import (
    AdmissionFactsV1,
    ExecutionUnitV1,
    canonical_digest,
)
from meta_flow.execution_control.migration import (
    current_execution_control_policy,
    load_provider_activation_receipt,
)
from meta_flow.project.model import Project, load_project
from meta_flow.project.process_route import require_project_process_route
from meta_flow.work.model import Work, load_work


def _digest(value: object) -> str:
    return canonical_digest(value)


_SAFE_WORK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _safe_work_id(ref: str) -> str:
    path = PurePosixPath(ref)
    if len(path.parts) != 3 or path.parts[0] != "works" or path.parts[2] != "WORK.yaml":
        raise ValueError("active_work_ref must be exactly works/<work-id>/WORK.yaml")
    work_id = path.parts[1]
    if not _SAFE_WORK_ID_RE.fullmatch(work_id):
        raise ValueError("active_work_ref must contain one safe work ID")
    return work_id


def _safe_ref(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("ref must be a string")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("ref must be safe")
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class ActiveExecutionInventoryV1:
    """由 Project 显式 active refs 投影的有界 inventory，禁止目录发现。"""

    decision: str
    reason_codes: tuple[str, ...]
    refs: tuple[str, ...]
    units: tuple[ExecutionUnitV1, ...]
    legacy_refs: tuple[str, ...]
    object_count: int
    objects_read: int
    inventory_digest: str
    mutation_count: int = 0


def project_active_execution_inventory(
    process_root: Path,
    project: Project,
    *,
    max_objects: int = 5,
) -> ActiveExecutionInventoryV1:
    """只读取 ``Project.active_work_refs`` 的 exact refs，任何异常都零写阻断。"""

    if type(max_objects) is not int or max_objects < 0:
        raise ValueError("max_objects must be a non-negative integer")
    refs = tuple(project.active_work_refs)
    if len(refs) != len(set(refs)):
        return ActiveExecutionInventoryV1(
            "BLOCKED", ("ACTIVE_INVENTORY_DUPLICATE_REF",), refs, (), (), 0, 0, _digest([])
        )
    if len(refs) > max_objects:
        return ActiveExecutionInventoryV1(
            "BLOCKED", ("ACTIVE_INVENTORY_BUDGET_EXCEEDED",), refs, (), (), 0, 0, _digest([])
        )
    units: list[ExecutionUnitV1] = []
    typed_refs: list[tuple[str, ExecutionUnitV1]] = []
    legacy_refs: list[str] = []
    objects_read = 0
    for ref in refs:
        try:
            work_id = _safe_work_id(ref)
        except ValueError:
            return ActiveExecutionInventoryV1(
                "BLOCKED", ("ACTIVE_INVENTORY_UNSAFE_REF",), refs, (), (), 0, objects_read, _digest([])
            )
        try:
            work = load_work(process_root, work_id)
            objects_read += 1
        except (OSError, ValueError, KeyError):
            return ActiveExecutionInventoryV1(
                "BLOCKED", ("ACTIVE_INVENTORY_DANGLING_REF",), refs, (), (), 0, objects_read, _digest([])
            )
        if work.work_ref != ref:
            return ActiveExecutionInventoryV1(
                "BLOCKED", ("ACTIVE_INVENTORY_REF_MISMATCH",), refs, (), (), 0, objects_read, _digest([])
            )
        if work.execution_unit is not None:
            units.append(work.execution_unit)
            typed_refs.append((ref, work.execution_unit))
        else:
            legacy_refs.append(ref)
    normalized = tuple(sorted(units, key=lambda item: item.unit_id))
    normalized_typed = tuple(sorted(typed_refs, key=lambda item: item[0]))
    normalized_legacy = tuple(sorted(legacy_refs))
    return ActiveExecutionInventoryV1(
        "READY",
        (),
        refs,
        normalized,
        normalized_legacy,
        len(refs),
        objects_read,
        _digest(
            {
                "typed": [{"ref": ref, "unit": unit.as_dict()} for ref, unit in normalized_typed],
                "legacy_refs": normalized_legacy,
            }
        ),
    )


def _git_value(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise ValueError("repository fact unavailable")
    return completed.stdout


def _repository_facts(release_root: Path, process_root: Path) -> tuple[str, str, str, str]:
    """读取双仓 OID 与合并 dirty 摘要；不做任何 Git mutation。"""

    release_oid = _git_value(release_root, "rev-parse", "HEAD").strip()
    process_oid = _git_value(process_root, "rev-parse", "HEAD").strip()
    release_dirty = _git_value(
        release_root, "status", "--porcelain=v2", "-z", "--untracked-files=all"
    )
    process_dirty = _git_value(
        process_root, "status", "--porcelain=v2", "-z", "--untracked-files=all"
    )
    return release_oid, process_oid, _digest([release_dirty, process_dirty]), _digest(
        {"release": release_oid, "process": process_oid}
    )


@dataclass(frozen=True, slots=True)
class ExecutionControlContextV1:
    release_root: Path
    process_root: Path
    decision: str
    reason_codes: tuple[str, ...]
    schema_version: int
    context_revision: int
    operation: str
    project_id: str
    release_root_identity: str
    process_root_identity: str
    release_oid: str
    process_oid: str
    route_digest: str
    dirty_path_digest: str
    scope_digest: str
    authorization_digest: str
    profile_digest: str
    inventory: ActiveExecutionInventoryV1
    target_preimage_digest: str
    project_active_owner_digest: str
    provider_receipt_status: str
    provider_receipt_digest: str
    policy_digest: str
    context_digest: str
    mutation_count: int = 0

    def admission_facts(self) -> AdmissionFactsV1:
        """只从当前 package-owned context 投影准入事实。"""

        return AdmissionFactsV1(
            release_oid=self.release_oid,
            process_oid=self.process_oid,
            dirty_path_digest=self.dirty_path_digest,
            scope_digest=self.scope_digest,
            authorization_digest=self.authorization_digest,
            profile_digest=self.profile_digest,
            inventory_digest=execution_inventory_digest(self.inventory.units),
            target_preimage_digest=self.target_preimage_digest,
            project_active_owner_digest=self.project_active_owner_digest,
        )


@dataclass(frozen=True, slots=True)
class RequestMaterializationCandidateV1:
    """plan-bound request target；它不是 authorization，也不能携带路径 authority。"""

    schema_version: int
    request_ref: str
    content_bytes: bytes
    content_digest: str
    source_kind: str
    source_ref: str
    source_digest: str
    before_preimage_digest: str
    candidate_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("request candidate schema_version must be 1")
        request_ref = _safe_ref(self.request_ref)
        source_ref = _safe_ref(self.source_ref)
        if not isinstance(self.content_bytes, bytes):
            raise ValueError("request candidate content_bytes must be bytes")
        try:
            self.content_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("request candidate content must be UTF-8") from exc
        if not isinstance(self.source_kind, str) or not _SAFE_WORK_ID_RE.fullmatch(
            self.source_kind
        ):
            raise ValueError("request candidate source_kind must be one safe ID")
        for field in (
            "content_digest",
            "source_digest",
            "before_preimage_digest",
            "candidate_digest",
        ):
            if not _SHA256_RE.fullmatch(getattr(self, field)):
                raise ValueError(f"request candidate {field} must be lowercase SHA-256")
        if sha256(self.content_bytes).hexdigest() != self.content_digest:
            raise ValueError("request candidate content digest drift")
        expected = _digest(
            {
                "schema_version": 1,
                "request_ref": request_ref,
                "content_digest": self.content_digest,
                "source_kind": self.source_kind,
                "source_ref": source_ref,
                "source_digest": self.source_digest,
                "before_preimage_digest": self.before_preimage_digest,
            }
        )
        if expected != self.candidate_digest:
            raise ValueError("request candidate digest drift")

    @classmethod
    def from_mapping(cls, payload: dict[str, object]) -> RequestMaterializationCandidateV1:
        expected = {
            "schema_version",
            "request_ref",
            "content_bytes",
            "content_digest",
            "source_kind",
            "source_ref",
            "source_digest",
            "before_preimage_digest",
            "candidate_digest",
        }
        if set(payload) != expected:
            raise ValueError("request candidate fields mismatch")
        return cls(
            schema_version=payload["schema_version"],
            request_ref=payload["request_ref"],
            content_bytes=payload["content_bytes"],
            content_digest=payload["content_digest"],
            source_kind=payload["source_kind"],
            source_ref=payload["source_ref"],
            source_digest=payload["source_digest"],
            before_preimage_digest=payload["before_preimage_digest"],
            candidate_digest=payload["candidate_digest"],
        )

    @classmethod
    def build(
        cls,
        *,
        request_ref: str,
        content_bytes: bytes,
        source_kind: str,
        source_ref: str,
        source_digest: str,
        before_preimage_digest: str,
    ) -> RequestMaterializationCandidateV1:
        content_digest = sha256(content_bytes).hexdigest()
        payload = {
            "schema_version": 1,
            "request_ref": _safe_ref(request_ref),
            "content_digest": content_digest,
            "source_kind": source_kind,
            "source_ref": _safe_ref(source_ref),
            "source_digest": source_digest,
            "before_preimage_digest": before_preimage_digest,
        }
        return cls(
            schema_version=1,
            request_ref=payload["request_ref"],
            content_bytes=content_bytes,
            content_digest=content_digest,
            source_kind=source_kind,
            source_ref=payload["source_ref"],
            source_digest=source_digest,
            before_preimage_digest=before_preimage_digest,
            candidate_digest=_digest(payload),
        )


def _root_identity(root: Path) -> str:
    """只存 canonical root 的摘要，不把设备绝对路径写入 context。"""

    return _digest({"canonical_root": str(root.resolve())})


def target_preimage_digest(path: Path) -> str:
    """canonical target preimage owner；planner 与 producer 必须共用。"""

    if path.is_symlink():
        return _digest({"kind": "symlink", "target": str(path.readlink())})
    if path.is_file():
        return _digest({"kind": "file", "bytes": path.read_bytes().hex()})
    if path.exists():
        return _digest({"kind": "other"})
    return _digest({"kind": "missing"})


def build_execution_control_context(
    release_root: Path,
    work: Work,
    *,
    operation: str,
) -> ExecutionControlContextV1:
    """从 release root 重新解析 route 并构造 plan/apply 各自的不可变 context。"""

    if operation not in {"plan", "apply"}:
        raise ValueError("operation must be plan or apply")
    root = release_root.resolve()
    route = require_project_process_route(root, project_id=work.project_id)
    project = load_project(route.process_root)
    if project.project_id != work.project_id:
        raise ValueError("route project_id differs from Work project_id")
    inventory = project_active_execution_inventory(
        route.process_root, project, max_objects=work.budget.reads
    )
    try:
        release_oid, process_oid, dirty_digest, repository_digest = _repository_facts(
            root, route.process_root
        )
    except ValueError:
        release_oid = process_oid = ""
        dirty_digest = repository_digest = _digest([])
        repository_error = "REPOSITORY_FACTS_UNAVAILABLE"
    else:
        repository_error = ""
    target = route.process_root / work.work_ref
    target_preimage = target_preimage_digest(target)
    route_digest = _digest(
        {"project_id": route.project_id, "route_mode": route.route_mode, "repository": repository_digest}
    )
    scope_digest = work.scope.digest
    authorization_digest = _digest(
        {"project_id": work.project_id, "work_id": work.work_id, "scope": scope_digest}
    )
    profile_digest = _digest({"risk_profile": work.risk_profile})
    active_owner_digest = _digest(project.active_work_refs)
    reasons = tuple(sorted((*inventory.reason_codes, *( [repository_error] if repository_error else []))))
    decision = "BLOCKED" if reasons else "READY"
    receipt = load_provider_activation_receipt()
    policy = current_execution_control_policy()
    receipt_digest = (
        receipt.receipt.receipt_digest
        if receipt.receipt is not None
        else _digest({"status": receipt.status, "reason_codes": receipt.reason_codes})
    )
    policy_digest = _digest(
        {
            "effective_writer_mode": policy.effective_writer_mode,
            "budget": policy.budget.as_dict(),
            "candidate_receipt_status": policy.candidate_receipt_status,
            "reason_codes": policy.reason_codes,
        }
    )
    provider_reasons = (
        ("PROVIDER_RECEIPT_UNKNOWN_SCHEMA_OR_POLICY",)
        if receipt.status == "BLOCKED" or policy.effective_writer_mode == "blocked"
        else ()
    )
    reasons = tuple(sorted((*reasons, *provider_reasons)))
    decision = "BLOCKED" if reasons else "READY"
    payload = {
        "schema_version": 1,
        "context_revision": 1,
        "operation": operation,
        "project_id": work.project_id,
        "release_root_identity": _root_identity(root),
        "process_root_identity": _root_identity(route.process_root),
        "release_oid": release_oid,
        "process_oid": process_oid,
        "route_digest": route_digest,
        "dirty_path_digest": dirty_digest,
        "scope_digest": scope_digest,
        "authorization_digest": authorization_digest,
        "profile_digest": profile_digest,
        "inventory_digest": inventory.inventory_digest,
        "target_preimage_digest": target_preimage,
        "project_active_owner_digest": active_owner_digest,
        "provider_receipt_status": receipt.status,
        "provider_receipt_digest": receipt_digest,
        "policy_digest": policy_digest,
        "decision": decision,
        "reason_codes": reasons,
    }
    return ExecutionControlContextV1(
        release_root=root,
        process_root=route.process_root,
        decision=decision,
        reason_codes=reasons,
        schema_version=1,
        context_revision=1,
        operation=operation,
        project_id=work.project_id,
        release_root_identity=payload["release_root_identity"],
        process_root_identity=payload["process_root_identity"],
        release_oid=release_oid,
        process_oid=process_oid,
        route_digest=route_digest,
        dirty_path_digest=dirty_digest,
        scope_digest=scope_digest,
        authorization_digest=authorization_digest,
        profile_digest=profile_digest,
        inventory=inventory,
        target_preimage_digest=target_preimage,
        project_active_owner_digest=active_owner_digest,
        provider_receipt_status=receipt.status,
        provider_receipt_digest=receipt_digest,
        policy_digest=policy_digest,
        context_digest=_digest(payload),
    )


__all__ = [
    "ActiveExecutionInventoryV1",
    "ExecutionControlContextV1",
    "RequestMaterializationCandidateV1",
    "build_execution_control_context",
    "project_active_execution_inventory",
    "target_preimage_digest",
]
