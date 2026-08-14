"""Repair execution container 的 typed、single-use 准入契约。

全局 ``ContainerBudgetV1`` 继续 deny repair。本模块只在候选 Work、被阻断的
前序 Work、blocker 证据、双仓 OID 与一次性人工授权全部一致时，生成一个只能由
canonical admission evaluator 消费的计划期 binding。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from meta_flow.execution_control.contract import ExecutionUnitV1, canonical_digest
from meta_flow.work.model import Work, load_work

AUTHORIZATION_KIND = "RepairAdmissionAuthorizationV1"
BINDING_KIND = "RepairAdmissionBindingV1"
BLOCKER_EVIDENCE_KIND = "WorkBlockerEvidenceV1"
REPAIR_BLOCKER_CATEGORIES = frozenset(
    {"usage-hard-stop", "transaction-recovery", "provider-capability-gap"}
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")


def _safe_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"repair authorization {field} is invalid")
    return value


def _safe_code(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _CODE_RE.fullmatch(value):
        raise ValueError(f"repair authorization {field} is invalid")
    return value


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"repair authorization {field} must be lowercase SHA-256")
    return value


def _oid(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _OID_RE.fullmatch(value):
        raise ValueError(f"repair authorization {field} must be one exact Git OID")
    return value


def _safe_ref(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or any(
        character in value for character in "\r\n\\"
    ):
        raise ValueError(f"repair authorization {field} must be one safe ref")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"repair authorization {field} must be one safe ref")
    return path.as_posix()


def _expiry(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("repair authorization expires_at must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("repair authorization expires_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("repair authorization expires_at must include timezone")
    return value


@dataclass(frozen=True, slots=True)
class RepairAdmissionAuthorizationV1:
    schema_version: int
    kind: str
    authorization_id: str
    authorization_source: str
    project_id: str
    candidate_work_id: str
    predecessor_work_id: str
    root_concept: str
    slice_id: str
    predecessor_scope_digest: str
    predecessor_status: str
    predecessor_blocker_category: str
    predecessor_blocker_code: str
    predecessor_blocker_ref: str
    predecessor_blocker_digest: str
    predecessor_blocker_fingerprint: str
    candidate_scope_digest: str
    release_oid: str
    process_oid: str
    expires_at: str
    single_use: bool

    FIELDS = frozenset(
        {
            "schema_version",
            "kind",
            "authorization_id",
            "authorization_source",
            "project_id",
            "candidate_work_id",
            "predecessor_work_id",
            "root_concept",
            "slice_id",
            "predecessor_scope_digest",
            "predecessor_status",
            "predecessor_blocker_category",
            "predecessor_blocker_code",
            "predecessor_blocker_ref",
            "predecessor_blocker_digest",
            "predecessor_blocker_fingerprint",
            "candidate_scope_digest",
            "release_oid",
            "process_oid",
            "expires_at",
            "single_use",
        }
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.kind != AUTHORIZATION_KIND:
            raise ValueError("repair authorization schema/kind is unsupported")
        _safe_id(self.authorization_id, field="authorization_id")
        if self.authorization_source != "typed-user-confirmation":
            raise ValueError(
                "repair authorization source must be typed-user-confirmation"
            )
        for field in (
            "project_id",
            "candidate_work_id",
            "predecessor_work_id",
            "root_concept",
            "slice_id",
        ):
            _safe_id(getattr(self, field), field=field)
        for field in (
            "predecessor_scope_digest",
            "predecessor_blocker_digest",
            "predecessor_blocker_fingerprint",
            "candidate_scope_digest",
        ):
            _sha256(getattr(self, field), field=field)
        if self.predecessor_status != "blocked":
            raise ValueError("repair authorization predecessor_status must be blocked")
        if self.predecessor_blocker_category not in REPAIR_BLOCKER_CATEGORIES:
            raise ValueError("repair authorization blocker category is unsupported")
        _safe_code(self.predecessor_blocker_code, field="predecessor_blocker_code")
        expected_ref = f"works/{self.predecessor_work_id}/BLOCKER.json"
        if _safe_ref(
            self.predecessor_blocker_ref, field="predecessor_blocker_ref"
        ) != expected_ref:
            raise ValueError(
                "repair authorization blocker ref must be predecessor BLOCKER.json"
            )
        _oid(self.release_oid, field="release_oid")
        _oid(self.process_oid, field="process_oid")
        _expiry(self.expires_at)
        if self.single_use is not True:
            raise ValueError("repair authorization must be single-use")

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, Any]
    ) -> RepairAdmissionAuthorizationV1:
        if not isinstance(payload, Mapping) or frozenset(payload) != cls.FIELDS:
            raise ValueError("repair authorization fields mismatch")
        return cls(**{field: payload[field] for field in cls.FIELDS})

    def as_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in sorted(self.FIELDS)}

    @property
    def authorization_digest(self) -> str:
        return canonical_digest(self.as_dict())


@dataclass(frozen=True, slots=True)
class RepairAdmissionBindingV1:
    kind: str
    authorization_id: str
    authorization_digest: str
    project_id: str
    candidate_work_id: str
    candidate_unit_digest: str
    candidate_scope_digest: str
    predecessor_work_id: str
    predecessor_unit_digest: str
    predecessor_scope_digest: str
    predecessor_status: str
    predecessor_blocker_category: str
    predecessor_blocker_code: str
    predecessor_blocker_digest: str
    predecessor_blocker_fingerprint: str
    root_concept: str
    slice_id: str
    release_oid: str
    process_oid: str
    expires_at: str

    FIELDS = frozenset(
        {
            "kind",
            "authorization_id",
            "authorization_digest",
            "project_id",
            "candidate_work_id",
            "candidate_unit_digest",
            "candidate_scope_digest",
            "predecessor_work_id",
            "predecessor_unit_digest",
            "predecessor_scope_digest",
            "predecessor_status",
            "predecessor_blocker_category",
            "predecessor_blocker_code",
            "predecessor_blocker_digest",
            "predecessor_blocker_fingerprint",
            "root_concept",
            "slice_id",
            "release_oid",
            "process_oid",
            "expires_at",
        }
    )

    def __post_init__(self) -> None:
        if self.kind != BINDING_KIND:
            raise ValueError("repair binding kind is unsupported")
        for field in (
            "authorization_id",
            "project_id",
            "candidate_work_id",
            "predecessor_work_id",
            "root_concept",
            "slice_id",
        ):
            _safe_id(getattr(self, field), field=field)
        for field in (
            "authorization_digest",
            "candidate_unit_digest",
            "candidate_scope_digest",
            "predecessor_unit_digest",
            "predecessor_scope_digest",
            "predecessor_blocker_digest",
            "predecessor_blocker_fingerprint",
        ):
            _sha256(getattr(self, field), field=field)
        if self.predecessor_status != "blocked":
            raise ValueError("repair binding predecessor status must be blocked")
        if self.predecessor_blocker_category not in REPAIR_BLOCKER_CATEGORIES:
            raise ValueError("repair binding blocker category is unsupported")
        _safe_code(self.predecessor_blocker_code, field="predecessor_blocker_code")
        _oid(self.release_oid, field="release_oid")
        _oid(self.process_oid, field="process_oid")
        _expiry(self.expires_at)

    def as_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in sorted(self.FIELDS)}

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> RepairAdmissionBindingV1:
        if not isinstance(payload, Mapping) or frozenset(payload) != cls.FIELDS:
            raise ValueError("repair binding fields mismatch")
        return cls(**{field: payload[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class RepairAdmissionEvaluationV1:
    decision: str
    conflicts: tuple[str, ...]
    binding: RepairAdmissionBindingV1 | None


@dataclass(frozen=True, slots=True)
class ExistingRepairBindingsV1:
    conflicts: tuple[str, ...]
    bindings: tuple[RepairAdmissionBindingV1, ...]


@dataclass(frozen=True, slots=True)
class RepairAuthorizationClaimV1:
    path: Path
    authorization_id: str
    authorization_digest: str

    def finish(self, state: str) -> None:
        if state not in {"CONSUMED", "FAILED"}:
            raise ValueError("repair authorization claim state is invalid")
        if self.path.parent.is_symlink() or not self.path.parent.is_dir():
            raise ValueError("repair authorization claim parent drifted")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("authorization_id") != self.authorization_id
            or payload.get("authorization_digest") != self.authorization_digest
            or payload.get("state") != "CLAIMED"
        ):
            raise ValueError("repair authorization claim ownership drifted")
        payload["state"] = state
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary_identity: tuple[int, int] | None = None
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                opened = os.fstat(stream.fileno())
                temporary_identity = (opened.st_dev, opened.st_ino)
                stream.write(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            _fsync_directory(self.path.parent)
        finally:
            _unlink_owned_regular(temporary, temporary_identity)


def repair_blocker_fingerprint(
    *,
    predecessor_work_id: str,
    predecessor_status: str,
    predecessor_scope_digest: str,
    predecessor_blocker_category: str,
    predecessor_blocker_code: str,
    predecessor_blocker_digest: str,
) -> str:
    return canonical_digest(
        {
            "predecessor_work_id": predecessor_work_id,
            "predecessor_status": predecessor_status,
            "predecessor_scope_digest": predecessor_scope_digest,
            "predecessor_blocker_category": predecessor_blocker_category,
            "predecessor_blocker_code": predecessor_blocker_code,
            "predecessor_blocker_digest": predecessor_blocker_digest,
        }
    )


def load_repair_admission_authorization(
    path: Path,
) -> RepairAdmissionAuthorizationV1:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024:
        raise ValueError("repair authorization path must be one bounded regular file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("repair authorization must be one JSON object")
    return RepairAdmissionAuthorizationV1.from_mapping(payload)


def _git_common_dir(process_root: Path) -> Path:
    completed = subprocess.run(
        ["git", "-C", str(process_root.resolve()), "rev-parse", "--git-common-dir"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise ValueError("repair authorization claim root is unavailable")
    common = Path(completed.stdout.strip())
    return (common if common.is_absolute() else process_root / common).resolve()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unlink_owned_regular(path: Path, identity: tuple[int, int] | None) -> bool:
    """只删除当前调用创建且 inode 未漂移的 regular file。"""

    if identity is None:
        return False
    try:
        current = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != identity:
        return False
    path.unlink()
    return True


def _ensure_plain_claim_directory(process_root: Path, target: Path) -> None:
    common = _git_common_dir(process_root)
    try:
        relative = target.relative_to(common)
    except ValueError as exc:
        raise ValueError("repair authorization claim path escaped Git common-dir") from exc
    cursor = common
    if cursor.is_symlink() or not cursor.is_dir():
        raise ValueError("repair authorization Git common-dir is unsafe")
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink() or (cursor.exists() and not cursor.is_dir()):
            raise ValueError("repair authorization claim directory is unsafe")
        if not cursor.exists():
            cursor.mkdir()
            _fsync_directory(cursor.parent)


def repair_authorization_claim_path(
    process_root: Path, authorization_id: str
) -> Path:
    safe_id = _safe_id(authorization_id, field="authorization_id")
    return (
        _git_common_dir(process_root)
        / "meta-flow"
        / "execution-control"
        / "repair-authorization-claims"
        / f"{safe_id}.json"
    )


def repair_admission_binding_ref(candidate_work_id: str) -> str:
    """返回 candidate Work 拥有的 portable durable binding ref。"""

    safe_id = _safe_id(candidate_work_id, field="candidate_work_id")
    return f"works/{safe_id}/REPAIR-ADMISSION.json"


def render_repair_admission_binding(binding: RepairAdmissionBindingV1) -> bytes:
    """按 canonical JSON 生成可纳入 Work-init 原子事务的 post-image。"""

    if not isinstance(binding, RepairAdmissionBindingV1):
        raise ValueError("repair admission binding must be typed")
    return (
        json.dumps(binding.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _blocker_category_matches(
    category: str, code: str, payload: Mapping[str, Any]
) -> bool:
    upper = code.upper()
    if category == "usage-hard-stop":
        return "USAGE" in upper and ("HARD" in upper or "BUDGET" in upper)
    if category == "transaction-recovery":
        return any(token in upper for token in ("PARTIAL", "RECOVER", "TRANSACTION"))
    classification = str(payload.get("classification") or "").lower()
    return "gap" in classification or any(
        token in upper for token in ("GAP", "PUBLICATION", "SCOPE")
    )


def plan_repair_admission_binding(
    process_root: Path,
    candidate: Work,
    *,
    release_oid: str,
    process_oid: str,
    authorization_path: Path | None,
    now: datetime | None = None,
) -> RepairAdmissionEvaluationV1:
    """只读生成 repair binding；任何未知或漂移都返回 closed conflict。"""

    unit = candidate.execution_unit
    if unit is None or unit.container_role != "repair":
        if authorization_path is None:
            return RepairAdmissionEvaluationV1("NOT_APPLICABLE", (), None)
        return RepairAdmissionEvaluationV1(
            "BLOCKED", ("REPAIR_AUTHORIZATION_ROLE_MISMATCH",), None
        )
    if authorization_path is None:
        return RepairAdmissionEvaluationV1(
            "BLOCKED", ("REPAIR_AUTHORIZATION_REQUIRED",), None
        )
    try:
        authorization = load_repair_admission_authorization(authorization_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return RepairAdmissionEvaluationV1(
            "BLOCKED", ("REPAIR_AUTHORIZATION_INVALID",), None
        )
    conflicts: set[str] = set()
    current = (now or datetime.now(UTC)).astimezone(UTC)
    expiry = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
    if expiry.astimezone(UTC) <= current:
        conflicts.add("REPAIR_AUTHORIZATION_EXPIRED")
    if authorization.project_id != candidate.project_id:
        conflicts.add("REPAIR_AUTHORIZATION_PROJECT_MISMATCH")
    if authorization.candidate_work_id != candidate.work_id:
        conflicts.add("REPAIR_AUTHORIZATION_CANDIDATE_MISMATCH")
    if authorization.root_concept != unit.root_concept:
        conflicts.add("REPAIR_AUTHORIZATION_ROOT_MISMATCH")
    if authorization.slice_id != unit.slice_id:
        conflicts.add("REPAIR_AUTHORIZATION_SLICE_MISMATCH")
    if authorization.candidate_scope_digest != candidate.scope.digest:
        conflicts.add("REPAIR_AUTHORIZATION_CANDIDATE_SCOPE_DRIFT")
    if authorization.release_oid != release_oid or authorization.process_oid != process_oid:
        conflicts.add("REPAIR_AUTHORIZATION_OID_DRIFT")
    try:
        predecessor = load_work(process_root, authorization.predecessor_work_id)
    except (OSError, ValueError):
        predecessor = None
        conflicts.add("REPAIR_PREDECESSOR_UNAVAILABLE")
    if predecessor is not None:
        predecessor_unit = predecessor.execution_unit
        if predecessor.project_id != candidate.project_id:
            conflicts.add("REPAIR_PREDECESSOR_PROJECT_MISMATCH")
        if predecessor.status != authorization.predecessor_status or predecessor.status != "blocked":
            conflicts.add("REPAIR_PREDECESSOR_STATUS_DRIFT")
        if predecessor.scope.digest != authorization.predecessor_scope_digest:
            conflicts.add("REPAIR_PREDECESSOR_SCOPE_DRIFT")
        if predecessor_unit is None:
            conflicts.add("REPAIR_PREDECESSOR_EXECUTION_UNIT_MISSING")
        elif (
            predecessor_unit.root_concept != unit.root_concept
            or predecessor_unit.slice_id != unit.slice_id
            or predecessor_unit.unit_id != predecessor.work_id
        ):
            conflicts.add("REPAIR_PREDECESSOR_SLICE_MISMATCH")
    blocker_path = process_root.resolve() / authorization.predecessor_blocker_ref
    blocker_payload: Mapping[str, Any] | None = None
    try:
        if blocker_path.is_symlink() or not blocker_path.is_file():
            raise ValueError("blocker evidence is not a regular file")
        blocker_bytes = blocker_path.read_bytes()
        if hashlib.sha256(blocker_bytes).hexdigest() != authorization.predecessor_blocker_digest:
            conflicts.add("REPAIR_PREDECESSOR_BLOCKER_DRIFT")
        parsed = json.loads(blocker_bytes)
        if not isinstance(parsed, Mapping):
            raise ValueError("blocker evidence must be an object")
        blocker_payload = parsed
    except (OSError, ValueError, json.JSONDecodeError):
        conflicts.add("REPAIR_PREDECESSOR_BLOCKER_INVALID")
    if blocker_payload is not None:
        if (
            blocker_payload.get("schema_version") != 1
            or blocker_payload.get("kind") != BLOCKER_EVIDENCE_KIND
            or blocker_payload.get("work_id") != authorization.predecessor_work_id
            or blocker_payload.get("decision") != "BLOCKED"
            or blocker_payload.get("blocker_id")
            != authorization.predecessor_blocker_code
        ):
            conflicts.add("REPAIR_PREDECESSOR_BLOCKER_MISMATCH")
        if not _blocker_category_matches(
            authorization.predecessor_blocker_category,
            authorization.predecessor_blocker_code,
            blocker_payload,
        ):
            conflicts.add("REPAIR_PREDECESSOR_BLOCKER_NOT_ELIGIBLE")
    expected_fingerprint = repair_blocker_fingerprint(
        predecessor_work_id=authorization.predecessor_work_id,
        predecessor_status=authorization.predecessor_status,
        predecessor_scope_digest=authorization.predecessor_scope_digest,
        predecessor_blocker_category=authorization.predecessor_blocker_category,
        predecessor_blocker_code=authorization.predecessor_blocker_code,
        predecessor_blocker_digest=authorization.predecessor_blocker_digest,
    )
    if authorization.predecessor_blocker_fingerprint != expected_fingerprint:
        conflicts.add("REPAIR_PREDECESSOR_BLOCKER_FINGERPRINT_DRIFT")
    try:
        claim_path = repair_authorization_claim_path(
            process_root, authorization.authorization_id
        )
    except ValueError:
        conflicts.add("REPAIR_AUTHORIZATION_CLAIM_UNAVAILABLE")
    else:
        if claim_path.exists() or claim_path.is_symlink():
            conflicts.add("REPAIR_AUTHORIZATION_ALREADY_CONSUMED")
    if conflicts or predecessor is None or predecessor.execution_unit is None:
        return RepairAdmissionEvaluationV1(
            "BLOCKED", tuple(sorted(conflicts)), None
        )
    binding = RepairAdmissionBindingV1(
        kind=BINDING_KIND,
        authorization_id=authorization.authorization_id,
        authorization_digest=authorization.authorization_digest,
        project_id=candidate.project_id,
        candidate_work_id=candidate.work_id,
        candidate_unit_digest=canonical_digest(unit),
        candidate_scope_digest=candidate.scope.digest,
        predecessor_work_id=predecessor.work_id,
        predecessor_unit_digest=canonical_digest(predecessor.execution_unit),
        predecessor_scope_digest=predecessor.scope.digest,
        predecessor_status=predecessor.status,
        predecessor_blocker_category=authorization.predecessor_blocker_category,
        predecessor_blocker_code=authorization.predecessor_blocker_code,
        predecessor_blocker_digest=authorization.predecessor_blocker_digest,
        predecessor_blocker_fingerprint=authorization.predecessor_blocker_fingerprint,
        root_concept=unit.root_concept,
        slice_id=unit.slice_id,
        release_oid=release_oid,
        process_oid=process_oid,
        expires_at=authorization.expires_at,
    )
    return RepairAdmissionEvaluationV1("READY", (), binding)


def claim_repair_authorization(
    process_root: Path, binding: RepairAdmissionBindingV1
) -> RepairAuthorizationClaimV1:
    path = repair_authorization_claim_path(process_root, binding.authorization_id)
    _ensure_plain_claim_directory(process_root, path.parent)
    payload = {
        "schema_version": 1,
        "kind": "RepairAuthorizationClaimV1",
        "state": "CLAIMED",
        "authorization_id": binding.authorization_id,
        "authorization_digest": binding.authorization_digest,
        "candidate_work_id": binding.candidate_work_id,
        "predecessor_work_id": binding.predecessor_work_id,
        "candidate_scope_digest": binding.candidate_scope_digest,
        "predecessor_scope_digest": binding.predecessor_scope_digest,
        "release_oid": binding.release_oid,
        "process_oid": binding.process_oid,
        "binding": binding.as_dict(),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("repair authorization is already consumed") from exc
    try:
        ownership_descriptor = os.dup(descriptor)
    except Exception:
        os.close(descriptor)
        raise
    opened = os.fstat(ownership_descriptor)
    claim_identity = (opened.st_dev, opened.st_ino)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(path.parent)
    except Exception:
        try:
            if _unlink_owned_regular(path, claim_identity):
                _fsync_directory(path.parent)
        except OSError:
            pass
        raise
    finally:
        os.close(ownership_descriptor)
    return RepairAuthorizationClaimV1(
        path, binding.authorization_id, binding.authorization_digest
    )


def load_existing_repair_bindings(
    process_root: Path,
    units: tuple[ExecutionUnitV1, ...],
) -> ExistingRepairBindingsV1:
    """按显式 inventory unit ID 读取 portable binding；禁止目录发现。"""

    conflicts: set[str] = set()
    bindings: list[RepairAdmissionBindingV1] = []
    for unit in units:
        if not hasattr(unit, "container_role") or unit.container_role != "repair":
            continue
        try:
            path = process_root.resolve() / repair_admission_binding_ref(unit.unit_id)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024:
                raise ValueError("repair binding claim is unavailable")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("repair binding payload is missing")
            binding = RepairAdmissionBindingV1.from_mapping(payload)
            if (
                binding.candidate_work_id != unit.unit_id
                or binding.candidate_unit_digest != canonical_digest(unit)
            ):
                raise ValueError("repair binding claim drifted")
        except (OSError, ValueError, json.JSONDecodeError):
            conflicts.add("REPAIR_INVENTORY_AUTHORIZATION_INVALID")
            continue
        bindings.append(binding)
    if len({binding.candidate_work_id for binding in bindings}) != len(bindings):
        conflicts.add("REPAIR_INVENTORY_AUTHORIZATION_DUPLICATE")
    return ExistingRepairBindingsV1(
        tuple(sorted(conflicts)),
        tuple(sorted(bindings, key=lambda item: item.candidate_work_id)),
    )


__all__ = [
    "AUTHORIZATION_KIND",
    "BINDING_KIND",
    "RepairAdmissionAuthorizationV1",
    "RepairAdmissionBindingV1",
    "RepairAdmissionEvaluationV1",
    "ExistingRepairBindingsV1",
    "RepairAuthorizationClaimV1",
    "claim_repair_authorization",
    "load_repair_admission_authorization",
    "load_existing_repair_bindings",
    "plan_repair_admission_binding",
    "render_repair_admission_binding",
    "repair_admission_binding_ref",
    "repair_authorization_claim_path",
    "repair_blocker_fingerprint",
]
