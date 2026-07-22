"""GOV-004 项目接入的统一计划、OID 与 typed authorization 契约。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from meta_flow.workspace.git_sync import run_git

PLAN_SCHEMA_VERSION = 2
PLAN_FIELDS = (
    "schema_version",
    "operation",
    "decision",
    "decision_ref",
    "project_id",
    "release_repo",
    "process_repo",
    "base_oids",
    "actions",
    "conflicts",
    "rollback_plan",
    "plan_digest",
)
OPERATIONS = {"project.init", "project.adopt-snapshot", "project.recover"}
DRY_RUN_DECISIONS = {"READY", "BLOCKED", "NOOP"}
APPLY_DECISIONS = {"PASS", "PARTIAL", "BLOCKED", "NOOP"}
OBSERVATION_STATES = {"absent", "unborn", "commit"}
AUTHORIZATION_SOURCE = "typed-user-confirmation"
AUTHORIZATION_KIND = "project-onboarding"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class OnboardingContractError(ValueError):
    """可预期的项目接入契约阻断。"""


@dataclass(frozen=True)
class OnboardingAuthorization:
    schema_version: int
    authorization_id: str
    authorization_source: str
    authorization_kind: str
    operation: str
    decision_ref: str
    project_id: str
    plan_digest: str
    expected_oids: dict[str, Any]
    expires_at: str
    single_use: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OnboardingAuthorization:
        required = {
            "schema_version",
            "authorization_id",
            "authorization_source",
            "authorization_kind",
            "operation",
            "decision_ref",
            "project_id",
            "plan_digest",
            "expected_oids",
            "expires_at",
            "single_use",
        }
        if set(payload) != required:
            missing = sorted(required - set(payload))
            extra = sorted(set(payload) - required)
            raise OnboardingContractError(
                f"authorization fields mismatch: missing={missing}, extra={extra}"
            )
        return cls(**payload)


def canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _git_value(root: Path, args: list[str]) -> str:
    result = run_git(args, cwd=root)
    return result.stdout.strip() if result.ok else ""


def observe_repository(root: Path) -> dict[str, str]:
    """返回只包含 ``state`` 与 ``oid`` 的 exact observation。"""

    resolved = root.resolve(strict=False)
    if not resolved.is_dir():
        return {"state": "absent", "oid": ""}
    top = _git_value(resolved, ["rev-parse", "--show-toplevel"])
    if not top or Path(top).resolve(strict=False) != resolved:
        return {"state": "absent", "oid": ""}
    oid = _git_value(resolved, ["rev-parse", "--verify", "HEAD"])
    if not oid:
        return {"state": "unborn", "oid": ""}
    observation = {"state": "commit", "oid": oid.lower()}
    validate_observation(observation)
    return observation


def validate_observation(payload: Any) -> None:
    if not isinstance(payload, dict) or set(payload) != {"state", "oid"}:
        raise OnboardingContractError("repository observation must contain exactly state and oid")
    state = payload.get("state")
    oid = payload.get("oid")
    if state not in OBSERVATION_STATES or not isinstance(oid, str):
        raise OnboardingContractError("repository observation state/oid is invalid")
    if state == "commit" and not _OID_RE.fullmatch(oid):
        raise OnboardingContractError("commit observation requires one 40-character lowercase OID")
    if state in {"absent", "unborn"} and oid:
        raise OnboardingContractError("absent/unborn observation requires an empty OID")


def _common_dir(root: Path) -> Path | None:
    if observe_repository(root)["state"] == "absent":
        return None
    common = _git_value(root, ["rev-parse", "--git-common-dir"])
    if not common:
        return None
    path = Path(common)
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def release_git_common_dir(root: Path) -> Path:
    common = _common_dir(root.resolve())
    if common is None:
        raise OnboardingContractError("release repository has no Git common directory")
    return common


def _portable_relative_name(root: Path, workspace_parent: Path) -> str:
    resolved = root.resolve(strict=False)
    parent = workspace_parent.resolve(strict=False)
    if resolved.parent != parent or resolved.name in {"", ".", ".."}:
        raise OnboardingContractError("repository must be one sibling under workspace_parent")
    return resolved.name


def repository_descriptor(root: Path, *, role: str, workspace_parent: Path) -> dict[str, Any]:
    if role not in {"release", "process"}:
        raise OnboardingContractError("repository role must be release or process")
    resolved = root.resolve(strict=False)
    observation = observe_repository(resolved)
    branch = _git_value(resolved, ["branch", "--show-current"]) if observation["state"] != "absent" else ""
    status = run_git(["status", "--porcelain=v1"], cwd=resolved) if observation["state"] != "absent" else None
    common = _common_dir(resolved)
    common_identity = canonical_digest(str(common)) if common is not None else ""
    return {
        "role": role,
        "anchor": "workspace_parent",
        "relative_path": _portable_relative_name(resolved, workspace_parent),
        "observation": observation,
        "dirty": bool(status is not None and (not status.ok or status.stdout.strip())),
        "branch": branch,
        "common_dir_identity": common_identity,
    }


def validate_portable_ref(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value or value.startswith("/"):
        raise OnboardingContractError(f"{field} must be one repository-relative POSIX ref")
    windows = PureWindowsPath(value)
    raw = value.split("/")
    path = PurePosixPath(value)
    if (
        windows.drive
        or windows.root
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in raw)
        or path.parts != tuple(raw)
    ):
        raise OnboardingContractError(f"{field} must not contain an absolute, empty, dot, or parent segment")


def _validate_repo_descriptor(payload: Any, *, role: str) -> None:
    required = {
        "role",
        "anchor",
        "relative_path",
        "observation",
        "dirty",
        "branch",
        "common_dir_identity",
    }
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise OnboardingContractError(f"{role}_repo descriptor is incomplete")
    if payload["role"] != role or payload["anchor"] != "workspace_parent":
        raise OnboardingContractError(f"{role}_repo role/anchor mismatch")
    validate_portable_ref(payload["relative_path"], field=f"{role}_repo.relative_path")
    validate_observation(payload["observation"])
    if not isinstance(payload["dirty"], bool):
        raise OnboardingContractError(f"{role}_repo.dirty must be boolean")


def build_plan_envelope(
    *,
    operation: str,
    decision: str,
    decision_ref: str,
    project_id: str,
    release_repo: dict[str, Any],
    process_repo: dict[str, Any],
    base_oids: dict[str, Any],
    actions: Iterable[dict[str, Any]],
    conflicts: Iterable[dict[str, Any]],
    rollback_plan: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "operation": operation,
        "decision": decision,
        "decision_ref": decision_ref,
        "project_id": project_id,
        "release_repo": release_repo,
        "process_repo": process_repo,
        "base_oids": base_oids,
        "actions": list(actions),
        "conflicts": list(conflicts),
        "rollback_plan": rollback_plan,
    }
    payload["plan_digest"] = canonical_digest(payload)
    validate_plan_envelope(payload, allow_apply_decision=True)
    return payload


def validate_plan_envelope(payload: Any, *, allow_apply_decision: bool = False) -> None:
    if not isinstance(payload, dict) or set(payload) != set(PLAN_FIELDS):
        actual = sorted(payload) if isinstance(payload, dict) else []
        raise OnboardingContractError(f"plan envelope must contain exactly the 12 fields: {actual}")
    if payload["schema_version"] != PLAN_SCHEMA_VERSION or payload["operation"] not in OPERATIONS:
        raise OnboardingContractError("plan schema_version or operation is invalid")
    allowed_decisions = DRY_RUN_DECISIONS | (APPLY_DECISIONS if allow_apply_decision else set())
    if payload["decision"] not in allowed_decisions:
        raise OnboardingContractError("plan decision is invalid")
    validate_portable_ref(payload["decision_ref"], field="decision_ref")
    if not _PROJECT_ID_RE.fullmatch(str(payload["project_id"])):
        raise OnboardingContractError("project_id is invalid")
    _validate_repo_descriptor(payload["release_repo"], role="release")
    _validate_repo_descriptor(payload["process_repo"], role="process")
    base = payload["base_oids"]
    if not isinstance(base, dict) or not {"release", "process"}.issubset(base):
        raise OnboardingContractError("base_oids must contain release and process observations")
    validate_observation(base["release"])
    validate_observation(base["process"])
    if "source_snapshot" in base:
        validate_observation(base["source_snapshot"])
    for action in payload["actions"]:
        required = {"action_id", "side", "kind", "target_ref", "ownership", "precondition", "expected_effect"}
        if not isinstance(action, dict) or not required.issubset(action):
            raise OnboardingContractError("action is missing required fields")
        validate_portable_ref(action["target_ref"], field="actions.target_ref")
    for conflict in payload["conflicts"]:
        required = {"code", "side", "target_ref", "message", "recovery_action"}
        if not isinstance(conflict, dict) or not required.issubset(conflict):
            raise OnboardingContractError("conflict is missing required fields")
        validate_portable_ref(conflict["target_ref"], field="conflicts.target_ref")
    rollback_required = {
        "strategy",
        "transaction_ref",
        "release_actions",
        "process_actions",
        "resume_actions",
        "cleanup_actions",
        "manual_only_actions",
    }
    if not isinstance(payload["rollback_plan"], dict) or set(payload["rollback_plan"]) != rollback_required:
        raise OnboardingContractError("rollback_plan fields mismatch")
    validate_portable_ref(payload["rollback_plan"]["transaction_ref"], field="rollback_plan.transaction_ref")
    if not _DIGEST_RE.fullmatch(str(payload["plan_digest"])):
        raise OnboardingContractError("plan_digest is invalid")
    expected = canonical_digest({key: payload[key] for key in PLAN_FIELDS[:-1]})
    if payload["plan_digest"] != expected:
        raise OnboardingContractError("plan_digest does not match canonical envelope")


def load_authorization(path: Path) -> OnboardingAuthorization:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OnboardingContractError(f"authorization is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OnboardingContractError("authorization must be one JSON object")
    return OnboardingAuthorization.from_dict(payload)


def validate_authorization(plan: dict[str, Any], authorization: OnboardingAuthorization) -> None:
    validate_plan_envelope(plan, allow_apply_decision=True)
    if authorization.schema_version != 1:
        raise OnboardingContractError("authorization schema_version must be 1")
    if not _SAFE_ID_RE.fullmatch(authorization.authorization_id):
        raise OnboardingContractError("authorization_id is invalid")
    if authorization.authorization_source != AUTHORIZATION_SOURCE:
        raise OnboardingContractError("authorization_source must be typed-user-confirmation")
    if authorization.authorization_kind != AUTHORIZATION_KIND:
        raise OnboardingContractError("authorization_kind must be project-onboarding")
    if not authorization.single_use:
        raise OnboardingContractError("project onboarding authorization must be single-use")
    expected = (
        plan["operation"],
        plan["decision_ref"],
        plan["project_id"],
        plan["plan_digest"],
        plan["base_oids"],
    )
    actual = (
        authorization.operation,
        authorization.decision_ref,
        authorization.project_id,
        authorization.plan_digest,
        authorization.expected_oids,
    )
    if actual != expected:
        raise OnboardingContractError(
            "authorization does not match operation/decision_ref/project/plan/expected OIDs"
        )
    try:
        expiry = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OnboardingContractError("authorization expires_at is invalid") from exc
    if expiry.tzinfo is None:
        raise OnboardingContractError("authorization expires_at must include timezone")
    if expiry.astimezone(UTC) <= datetime.now(UTC):
        raise OnboardingContractError("project onboarding authorization is expired")


def assert_expected_observations(
    *,
    plan: dict[str, Any],
    release_root: Path,
    process_root: Path,
    source_root: Path | None = None,
    stage: str,
) -> None:
    actual: dict[str, Any] = {
        "release": observe_repository(release_root),
        "process": observe_repository(process_root),
    }
    if source_root is not None:
        actual["source_snapshot"] = observe_repository(source_root)
    if actual != plan["base_oids"]:
        raise OnboardingContractError(
            f"OID observation drift at {stage}: expected={plan['base_oids']}, actual={actual}"
        )


def authorization_claim_path(release_root: Path, authorization_id: str) -> Path:
    if not _SAFE_ID_RE.fullmatch(authorization_id):
        raise OnboardingContractError("authorization_id is invalid")
    return (
        release_git_common_dir(release_root)
        / "meta-flow"
        / "authorizations"
        / "project-onboarding"
        / f"{authorization_id}.json"
    )


def claim_authorization(
    release_root: Path,
    plan: dict[str, Any],
    authorization: OnboardingAuthorization,
) -> Path:
    validate_authorization(plan, authorization)
    path = authorization_claim_path(release_root, authorization.authorization_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "authorization_id": authorization.authorization_id,
        "operation": authorization.operation,
        "decision_ref": authorization.decision_ref,
        "project_id": authorization.project_id,
        "plan_digest": authorization.plan_digest,
        "expected_oids": authorization.expected_oids,
        "claimed_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise OnboardingContractError("authorization was already consumed") from exc
    return path


def transaction_manifest_path(release_root: Path, authorization_id: str) -> Path:
    if not _SAFE_ID_RE.fullmatch(authorization_id):
        raise OnboardingContractError("authorization_id is invalid")
    return (
        release_git_common_dir(release_root)
        / "meta-flow"
        / "project-onboarding"
        / "transactions"
        / authorization_id
        / "manifest.json"
    )


def write_transaction_manifest(
    release_root: Path,
    authorization_id: str,
    payload: dict[str, Any],
    *,
    create_only: bool,
) -> Path:
    path = transaction_manifest_path(release_root, authorization_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if create_only:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    else:
        path.write_text(serialized, encoding="utf-8")
    return path


def load_transaction_manifest(release_root: Path, authorization_id: str) -> dict[str, Any]:
    path = transaction_manifest_path(release_root, authorization_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OnboardingContractError(f"transaction manifest is unavailable or invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise OnboardingContractError("transaction manifest must be one object")
    return payload


def path_digest(path: Path) -> str:
    if path.is_symlink():
        return canonical_digest({"kind": "symlink", "target": path.readlink().as_posix()})
    if path.is_file():
        return sha256(path.read_bytes()).hexdigest()
    if path.is_dir():
        return canonical_digest({"kind": "directory", "entries": sorted(item.name for item in path.iterdir())})
    return canonical_digest({"kind": "absent"})


def portable_target_path(
    *,
    release_root: Path,
    process_root: Path,
    target_ref: str,
) -> Path:
    validate_portable_ref(target_ref, field="target_ref")
    parts = PurePosixPath(target_ref).parts
    if parts[0] == "release":
        root = release_root.resolve()
    elif parts[0] == "process":
        root = process_root.resolve()
    else:
        raise OnboardingContractError("target_ref must start with release/ or process/")
    if len(parts) == 1 or parts[1] == "repository":
        return root
    candidate = root.joinpath(*parts[1:]).resolve(strict=False)
    if not candidate.is_relative_to(root):
        raise OnboardingContractError("target_ref escapes its repository")
    return candidate


__all__ = [
    "APPLY_DECISIONS",
    "AUTHORIZATION_KIND",
    "AUTHORIZATION_SOURCE",
    "DRY_RUN_DECISIONS",
    "OnboardingAuthorization",
    "OnboardingContractError",
    "PLAN_FIELDS",
    "PLAN_SCHEMA_VERSION",
    "assert_expected_observations",
    "authorization_claim_path",
    "build_plan_envelope",
    "canonical_digest",
    "claim_authorization",
    "load_authorization",
    "load_transaction_manifest",
    "observe_repository",
    "path_digest",
    "portable_target_path",
    "release_git_common_dir",
    "repository_descriptor",
    "transaction_manifest_path",
    "validate_authorization",
    "validate_observation",
    "validate_plan_envelope",
    "validate_portable_ref",
    "write_transaction_manifest",
]
