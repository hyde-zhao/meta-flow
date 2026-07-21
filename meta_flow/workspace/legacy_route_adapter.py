"""封闭的 legacy workspace 写能力与一次性授权占用。"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from meta_flow.workspace.git_sync import run_git

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OID_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_WORKSPACE_COMMANDS = {
    "workspace link",
    "workspace bootstrap",
    "workspace push",
}
_ADOPTION_COMMAND = "project adopt"


@dataclass(frozen=True)
class _LegacyRouteAuthorization:
    schema_version: int
    authorization_id: str
    command: str
    authorization_source: str
    authorization_kind: str
    decision_ref: str
    project_id: str
    operation_digest: str
    expected_oids: Mapping[str, str]
    expires_at: str
    single_use: bool = True


@dataclass(frozen=True)
class _LegacyAuthorizationClaim:
    path: Path
    authorization: _LegacyRouteAuthorization
    binding_presence: bool

    def finish(self, decision: str, *, mutation_count: int = 0) -> None:
        if decision not in {"PASS", "PARTIAL", "BLOCKED"}:
            raise ValueError("legacy claim decision must be PASS, PARTIAL, or BLOCKED")
        payload = _claim_payload(
            self.authorization,
            state=decision,
            binding_presence=self.binding_presence,
            mutation_count=mutation_count,
        )
        _atomic_replace_json(self.path, payload)


def load_legacy_authorization(path: Path) -> _LegacyRouteAuthorization:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("authorization must be one JSON object")
    try:
        return _LegacyRouteAuthorization(**raw)
    except TypeError as exc:
        raise ValueError(f"authorization schema mismatch: {exc}") from exc


def operation_digest(command: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"schema_version": 1, "command": command, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def current_git_oid(root: Path) -> str:
    result = run_git(["rev-parse", "--verify", "HEAD^{commit}"], cwd=root.resolve())
    return result.stdout.strip().lower() if result.ok else ""


def workspace_operation_payload(
    command: str,
    *,
    project_root: Path,
    project_id: str,
    parameters: Mapping[str, Any],
    expected_oids: Mapping[str, str],
) -> dict[str, Any]:
    """生成可供人工门确认的 dry-run 摘要；绝对路径只参与 digest，不进入 claim。"""

    digest = operation_digest(
        command,
        {
            "project_root": str(project_root.resolve()),
            "project_id": project_id,
            "parameters": dict(parameters),
            "expected_oids": dict(sorted(expected_oids.items())),
        },
    )
    return {
        "schema_version": 1,
        "decision": "READY",
        "command": command,
        "project_id": project_id,
        "operation_digest": digest,
        "expected_oids": dict(sorted(expected_oids.items())),
        "mutation_count": 0,
        "requires_apply": command in {"workspace link", "workspace bootstrap"},
        "requires_authorization": True,
    }


def capability_for_adoption(authorization: Any) -> _LegacyRouteAuthorization:
    return _LegacyRouteAuthorization(
        schema_version=1,
        authorization_id=authorization.authorization_id,
        command=_ADOPTION_COMMAND,
        authorization_source="typed-user-confirmation",
        authorization_kind=authorization.authorization_kind,
        decision_ref=authorization.decision_ref,
        project_id=authorization.project_id,
        operation_digest=authorization.plan_digest,
        expected_oids={
            "source": authorization.source_oid,
            "target": authorization.target_oid,
        },
        expires_at=authorization.expires_at,
        single_use=authorization.single_use,
    )


def _validate_decision_ref(value: str) -> None:
    if not value or "\\" in value or "\x00" in value or ":" in value:
        raise ValueError("decision_ref must be one repository-relative POSIX ref")
    ref = PurePosixPath(value)
    if ref.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("decision_ref must be one repository-relative POSIX ref")


def _validate_authorization(
    authorization: _LegacyRouteAuthorization,
    *,
    command: str,
    project_id: str,
    operation_digest_value: str,
    expected_oids: Mapping[str, str],
) -> None:
    if authorization.schema_version != 1:
        raise ValueError("legacy authorization schema_version must be 1")
    if not _ID_RE.fullmatch(authorization.authorization_id):
        raise ValueError("authorization_id is invalid")
    if command not in {*_WORKSPACE_COMMANDS, _ADOPTION_COMMAND} or authorization.command != command:
        raise ValueError("legacy authorization command is unknown or mismatched")
    if authorization.authorization_source != "typed-user-confirmation":
        raise ValueError("authorization_source must be typed-user-confirmation")
    expected_kinds = (
        {"workspace-operation"}
        if command in _WORKSPACE_COMMANDS
        else {"local-fixture", "single-project-migration"}
    )
    if authorization.authorization_kind not in expected_kinds:
        raise ValueError("authorization_kind is invalid for this command")
    _validate_decision_ref(authorization.decision_ref)
    if not _ID_RE.fullmatch(authorization.project_id) or authorization.project_id != project_id:
        raise ValueError("authorization project_id mismatch")
    if not authorization.single_use:
        raise ValueError("legacy authorization must be single-use")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", authorization.operation_digest):
        raise ValueError("operation_digest is invalid")
    if authorization.operation_digest.lower() != operation_digest_value.lower():
        raise ValueError("authorization operation_digest mismatch")
    actual_oids = dict(authorization.expected_oids)
    frozen_oids = dict(expected_oids)
    if actual_oids != frozen_oids:
        raise ValueError("authorization expected_oids mismatch")
    if any(value and not _OID_RE.fullmatch(value) for value in actual_oids.values()):
        raise ValueError("authorization expected_oids contains an invalid exact OID")
    try:
        expiry = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("authorization expires_at is invalid") from exc
    if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError("authorization is expired or lacks timezone")


def _git_common_dir(root: Path) -> Path:
    result = run_git(["rev-parse", "--git-common-dir"], cwd=root.resolve())
    if not result.ok:
        raise ValueError("claim root must be one Git worktree")
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = root.resolve() / common
    return common.resolve()


def _claim_payload(
    authorization: _LegacyRouteAuthorization,
    *,
    state: str,
    binding_presence: bool,
    mutation_count: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": state,
        "authorization_id": authorization.authorization_id,
        "command": authorization.command,
        "authorization_source": authorization.authorization_source,
        "authorization_kind": authorization.authorization_kind,
        "decision_ref": authorization.decision_ref,
        "project_id": authorization.project_id,
        "operation_digest": authorization.operation_digest,
        "expected_oids": dict(sorted(authorization.expected_oids.items())),
        "binding_presence": binding_presence,
        "mutation_count": mutation_count,
    }


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _exclusive_create_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        data = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)
    _fsync_parent(path.parent)


def _atomic_replace_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        data = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _fsync_parent(path.parent)


def claim_legacy_authorization(
    authorization: _LegacyRouteAuthorization,
    *,
    command: str,
    project_root: Path,
    project_id: str,
    operation_digest_value: str,
    expected_oids: Mapping[str, str],
    claim_repo_root: Path | None = None,
    reject_binding: bool = True,
) -> _LegacyAuthorizationClaim:
    """在第一次写入/网络调用前永久占用一次性授权。"""

    root = project_root.resolve()
    binding_presence = (root / ".meta-flow" / "workspace.yaml").exists()
    if reject_binding and binding_presence:
        raise ValueError("legacy_policy_denied: portable vNext binding is present")
    _validate_authorization(
        authorization,
        command=command,
        project_id=project_id,
        operation_digest_value=operation_digest_value,
        expected_oids=expected_oids,
    )
    common_dir = _git_common_dir((claim_repo_root or root).resolve())
    claim_path = (
        common_dir
        / "meta-flow"
        / "authorizations"
        / "claims"
        / f"{authorization.authorization_id}.json"
    )
    try:
        _exclusive_create_json(
            claim_path,
            _claim_payload(
                authorization,
                state="CLAIMED",
                binding_presence=binding_presence,
            ),
        )
    except FileExistsError as exc:
        raise ValueError("legacy authorization is already consumed") from exc
    return _LegacyAuthorizationClaim(claim_path, authorization, binding_presence)


__all__ = [
    "capability_for_adoption",
    "claim_legacy_authorization",
    "current_git_oid",
    "load_legacy_authorization",
    "operation_digest",
    "workspace_operation_payload",
]
