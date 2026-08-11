"""Work 关闭的可恢复多对象事务。

本模块只拥有 Work close 的 plan/authorization/apply/recovery。CR status-sync 与
CR termination 保留各自既有 owner；统一检查入口只聚合它们的事务状态，不接管
其领域语义。
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.project.governance import load_phase
from meta_flow.project.model import is_safe_ref, load_project
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.work.lifecycle import transition_work
from meta_flow.work.model import load_work

TRANSACTION_SCHEMA_VERSION = 1
AUTHORIZATION_KIND = "work-close-authorization-v1"
TRANSACTION_ROOT_REL = Path(".meta-flow-runtime/work-close/transactions")
LOCK_REL = Path(".meta-flow-runtime/work-close/writer.lock")
TERMINAL_TRANSACTION_STATES = {"COMMITTED", "RECOVERED"}
TRANSACTION_STATES = {"PREPARED", "APPLYING", "PARTIAL", *TERMINAL_TRANSACTION_STATES}
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_FIELDS = {
    "schema_version",
    "kind",
    "authorization_id",
    "work_id",
    "plan_digest",
    "state",
    "created_at",
    "updated_at",
    "attempted_refs",
    "applied_refs",
    "targets",
}
_MANIFEST_OPTIONAL_FIELDS = {"failure", "recovery_failures"}
_TARGET_FIELDS = {
    "ref",
    "before_digest",
    "after_digest",
    "before_bytes_b64",
    "after_bytes_b64",
}


def _digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _render(payload: Mapping[str, Any]) -> bytes:
    return (dump_yaml(dict(payload)) + "\n").encode("utf-8")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _safe_authorization_id(value: str) -> str:
    if not value or len(value) > 128 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in value
    ):
        raise ValueError("authorization_id is invalid")
    return value


@dataclass(frozen=True, slots=True)
class WorkCloseTargetV1:
    ref: str
    before_digest: str
    after_digest: str
    after_bytes: bytes

    def as_plan_dict(self) -> dict[str, str]:
        return {
            "ref": self.ref,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
        }


@dataclass(frozen=True, slots=True)
class WorkClosePlanV1:
    decision: str
    work_id: str
    expected_status: str
    outcome: str
    result_ref: str
    targets: tuple[WorkCloseTargetV1, ...]
    blockers: tuple[str, ...]
    plan_digest: str

    @property
    def ready(self) -> bool:
        return self.decision == "READY" and not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "operation": "work.close",
            "decision": self.decision,
            "work_id": self.work_id,
            "expected_status": self.expected_status,
            "outcome": self.outcome,
            "result_ref": self.result_ref,
            "targets": [target.as_plan_dict() for target in self.targets],
            "blockers": list(self.blockers),
            "plan_digest": self.plan_digest,
            "mutation_count": 0,
        }


@dataclass(frozen=True, slots=True)
class WorkCloseAuthorizationV1:
    schema_version: int
    kind: str
    authorization_id: str
    work_id: str
    plan_digest: str
    target_refs: tuple[str, ...]
    expires_at: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> WorkCloseAuthorizationV1:
        expected = {
            "schema_version",
            "kind",
            "authorization_id",
            "work_id",
            "plan_digest",
            "target_refs",
            "expires_at",
        }
        if set(payload) != expected:
            raise ValueError("work close authorization fields mismatch")
        refs = payload["target_refs"]
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError("target_refs must be a list of strings")
        return cls(
            schema_version=int(payload["schema_version"]),
            kind=str(payload["kind"]),
            authorization_id=_safe_authorization_id(str(payload["authorization_id"])),
            work_id=str(payload["work_id"]),
            plan_digest=str(payload["plan_digest"]),
            target_refs=tuple(refs),
            expires_at=str(payload["expires_at"]),
        )

    def validate_for(self, plan: WorkClosePlanV1) -> None:
        if self.schema_version != TRANSACTION_SCHEMA_VERSION or self.kind != AUTHORIZATION_KIND:
            raise ValueError("work close authorization kind/version mismatch")
        if self.work_id != plan.work_id or self.plan_digest != plan.plan_digest:
            raise ValueError("work close authorization does not bind the current plan")
        if self.target_refs != tuple(target.ref for target in plan.targets):
            raise ValueError("work close authorization target_refs mismatch")
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("work close authorization expires_at is invalid") from exc
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("work close authorization is expired")


@dataclass(frozen=True, slots=True)
class WorkCloseReceiptV1:
    decision: str
    authorization_id: str
    work_id: str
    plan_digest: str
    mutation_count: int
    applied_refs: tuple[str, ...]
    recovery_required: bool
    reason_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "decision": self.decision,
            "authorization_id": self.authorization_id,
            "work_id": self.work_id,
            "plan_digest": self.plan_digest,
            "mutation_count": self.mutation_count,
            "applied_refs": list(self.applied_refs),
            "recovery_required": self.recovery_required,
            "reason_codes": list(self.reason_codes),
        }


def _validate_result(process_root: Path, work_id: str, outcome: str, result_ref: str) -> None:
    if outcome not in {"completed", "cancelled"}:
        raise ValueError("outcome must be completed or cancelled")
    if outcome == "cancelled":
        if result_ref:
            raise ValueError("cancelled Work must not add result_ref")
        return
    if not result_ref or not is_safe_ref(result_ref):
        raise ValueError("completed Work requires result_ref")
    path = process_root.resolve() / result_ref
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Work result is missing or not regular: {result_ref}")
    payload = load_yaml_object(path)
    if (
        set(payload) != {"schema_version", "work_id", "decision"}
        or payload.get("schema_version") != 1
        or payload.get("work_id") != work_id
        or payload.get("decision") != "PASS"
    ):
        raise ValueError("completed Work requires one exact matching PASS result")


def _plan_digest(plan_fields: Mapping[str, Any]) -> str:
    return canonical_digest(dict(plan_fields))


def plan_work_close(
    process_root: Path,
    work_id: str,
    *,
    expected_status: str,
    outcome: str,
    result_ref: str = "",
) -> WorkClosePlanV1:
    """只读生成 Work/Project/Phase 的完整关闭候选。"""

    root = process_root.resolve()
    blockers: list[str] = []
    targets: list[WorkCloseTargetV1] = []
    try:
        _validate_result(root, work_id, outcome, result_ref)
        current = load_work(root, work_id)
        if current.status == outcome and (
            outcome == "cancelled" or current.result_ref == result_ref
        ):
            closed = current
        else:
            if current.status != expected_status:
                raise ValueError(
                    f"Work status changed: expected {expected_status}, current {current.status}"
                )
            closed = transition_work(current, outcome, result_ref=result_ref)

        project = load_project(root)
        updated_project = replace(
            project,
            active_work_refs=tuple(
                ref for ref in project.active_work_refs if ref != closed.work_ref
            ),
        )
        candidates: list[tuple[str, bytes]] = [
            (closed.work_ref, _render(closed.as_dict())),
            ("PROJECT.yaml", _render(updated_project.as_dict())),
        ]
        if closed.phase_ref:
            phase = load_phase(root, closed.phase_ref)
            phase_results = phase.result_refs
            if result_ref and result_ref not in phase_results:
                phase_results = (*phase_results, result_ref)
            updated_phase = replace(
                phase,
                work_refs=tuple(ref for ref in phase.work_refs if ref != closed.work_ref),
                result_refs=phase_results,
            )
            candidates.append((closed.phase_ref, _render(updated_phase.as_dict())))

        for ref, after in candidates:
            path = root / ref
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"transaction target is not a regular file: {ref}")
            before = path.read_bytes()
            if before != after:
                targets.append(
                    WorkCloseTargetV1(ref, _digest_bytes(before), _digest_bytes(after), after)
                )
    except (OSError, ValueError) as exc:
        blockers.append(str(exc))

    fields = {
        "schema_version": TRANSACTION_SCHEMA_VERSION,
        "operation": "work.close",
        "work_id": work_id,
        "expected_status": expected_status,
        "outcome": outcome,
        "result_ref": result_ref,
        "targets": [target.as_plan_dict() for target in targets],
        "blockers": blockers,
    }
    return WorkClosePlanV1(
        decision="BLOCKED" if blockers else "READY",
        work_id=work_id,
        expected_status=expected_status,
        outcome=outcome,
        result_ref=result_ref,
        targets=tuple(targets),
        blockers=tuple(blockers),
        plan_digest=_plan_digest(fields),
    )


def _transaction_dir(root: Path, authorization_id: str) -> Path:
    return root / TRANSACTION_ROOT_REL / _safe_authorization_id(authorization_id)


def _manifest_path(root: Path, authorization_id: str) -> Path:
    return _transaction_dir(root, authorization_id) / "manifest.json"


def _require_runtime_chain(
    root: Path,
    authorization_id: str | None = None,
    *,
    create: bool,
) -> None:
    parts = [Path(".meta-flow-runtime"), Path("work-close")]
    if authorization_id is not None:
        parts.extend([Path("transactions"), Path(_safe_authorization_id(authorization_id))])
    current = root.resolve()
    for part in parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise ValueError(f"work close runtime path is not a plain directory: {current}")
        elif create:
            current.mkdir()
        else:
            raise ValueError("work close transaction runtime path is missing")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    content = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _write_atomic(path, content)


def _replace_bytes(path: Path, content: bytes) -> None:
    _write_atomic(path, content)


def _acquire_lock(root: Path, authorization_id: str) -> Path:
    _require_runtime_chain(root, create=True)
    path = root / LOCK_REL
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(authorization_id + "\n")
    except FileExistsError as exc:
        raise ValueError("work close writer lock is already held") from exc
    return path


def _release_lock(path: Path, authorization_id: str) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.read_text(encoding="utf-8").strip() != authorization_id
    ):
        raise ValueError("work close writer lock ownership changed")
    path.unlink()


def _manifest(plan: WorkClosePlanV1, authorization: WorkCloseAuthorizationV1) -> dict[str, Any]:
    return {
        "schema_version": TRANSACTION_SCHEMA_VERSION,
        "kind": "work-close-transaction-v1",
        "authorization_id": authorization.authorization_id,
        "work_id": plan.work_id,
        "plan_digest": plan.plan_digest,
        "state": "PREPARED",
        "created_at": _now(),
        "updated_at": _now(),
        "attempted_refs": [],
        "applied_refs": [],
        "targets": [
            {
                **target.as_plan_dict(),
                "before_bytes_b64": base64.b64encode(
                    b""
                ).decode("ascii"),
                "after_bytes_b64": base64.b64encode(target.after_bytes).decode("ascii"),
            }
            for target in plan.targets
        ],
    }


def _attach_before_bytes(root: Path, manifest: dict[str, Any]) -> None:
    for target in manifest["targets"]:
        path = root / target["ref"]
        current = path.read_bytes()
        if _digest_bytes(current) != target["before_digest"]:
            raise ValueError(f"work close target preimage drift: {target['ref']}")
        target["before_bytes_b64"] = base64.b64encode(current).decode("ascii")


def _validate_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_authorization_id: str,
) -> None:
    fields = set(manifest)
    if not _MANIFEST_FIELDS <= fields or fields - _MANIFEST_FIELDS - _MANIFEST_OPTIONAL_FIELDS:
        raise ValueError("work close manifest fields mismatch")
    if (
        manifest.get("schema_version") != TRANSACTION_SCHEMA_VERSION
        or manifest.get("kind") != "work-close-transaction-v1"
    ):
        raise ValueError("work close manifest kind/version mismatch")
    authorization_id = _safe_authorization_id(str(manifest.get("authorization_id") or ""))
    if authorization_id != expected_authorization_id:
        raise ValueError("work close manifest authorization identity mismatch")
    work_id = _safe_authorization_id(str(manifest.get("work_id") or ""))
    if not _DIGEST_RE.fullmatch(str(manifest.get("plan_digest") or "")):
        raise ValueError("work close manifest plan digest is invalid")
    if manifest.get("state") not in TRANSACTION_STATES:
        raise ValueError("work close manifest state is invalid")
    raw_targets = manifest.get("targets")
    attempted_refs = manifest.get("attempted_refs")
    applied_refs = manifest.get("applied_refs")
    if (
        not isinstance(raw_targets, list)
        or not isinstance(attempted_refs, list)
        or not isinstance(applied_refs, list)
    ):
        raise ValueError("work close manifest target accounting is invalid")
    target_refs: list[str] = []
    for target in raw_targets:
        if not isinstance(target, Mapping) or set(target) != _TARGET_FIELDS:
            raise ValueError("work close manifest target fields mismatch")
        ref = str(target.get("ref") or "")
        parts = Path(ref).parts
        phase_ref = (
            len(parts) == 3
            and parts[0] == "phases"
            and bool(parts[1])
            and parts[2] == "PHASE.yaml"
        )
        if (
            not is_safe_ref(ref)
            or ref not in {"PROJECT.yaml", f"works/{work_id}/WORK.yaml"}
            and not phase_ref
        ):
            raise ValueError(f"work close manifest target is outside fixed projector: {ref}")
        before_digest = str(target.get("before_digest") or "")
        after_digest = str(target.get("after_digest") or "")
        if not _DIGEST_RE.fullmatch(before_digest) or not _DIGEST_RE.fullmatch(after_digest):
            raise ValueError("work close manifest target digest is invalid")
        try:
            before = base64.b64decode(str(target["before_bytes_b64"]), validate=True)
            after = base64.b64decode(str(target["after_bytes_b64"]), validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("work close manifest target bytes are invalid") from exc
        if _digest_bytes(before) != before_digest or _digest_bytes(after) != after_digest:
            raise ValueError("work close manifest target bytes/digest mismatch")
        target_refs.append(ref)
    if len(target_refs) != len(set(target_refs)) or len(target_refs) > 3:
        raise ValueError("work close manifest target set is invalid")
    for field, refs in (
        ("attempted_refs", attempted_refs),
        ("applied_refs", applied_refs),
    ):
        if (
            any(not isinstance(ref, str) for ref in refs)
            or len(refs) != len(set(refs))
            or any(ref not in target_refs for ref in refs)
            or refs != target_refs[: len(refs)]
        ):
            raise ValueError(f"work close manifest {field} are invalid")
    if applied_refs != attempted_refs[: len(applied_refs)]:
        raise ValueError("work close manifest applied_refs exceed attempted_refs")


def _rollback(root: Path, manifest: dict[str, Any]) -> tuple[bool, list[str]]:
    failed: list[str] = []
    for target in reversed(manifest["targets"]):
        ref = target["ref"]
        path = root / ref
        try:
            current = path.read_bytes()
            current_digest = _digest_bytes(current)
            if current_digest not in {target["after_digest"], target["before_digest"]}:
                raise ValueError("target bytes no longer match transaction generations")
            before = base64.b64decode(target["before_bytes_b64"], validate=True)
            if current_digest == target["after_digest"] and current != before:
                _replace_bytes(path, before)
        except (OSError, ValueError) as exc:
            failed.append(f"{ref}: {exc}")
    return not failed, failed


def _generation_errors(root: Path, manifest: Mapping[str, Any]) -> list[str]:
    state = str(manifest.get("state") or "")
    expected_generation = "after_digest" if state == "COMMITTED" else "before_digest"
    errors: list[str] = []
    for target in manifest["targets"]:
        ref = str(target["ref"])
        try:
            current_digest = _digest_bytes((root / ref).read_bytes())
        except OSError as exc:
            errors.append(f"work close target unreadable: {ref}:{exc}")
            continue
        if current_digest != target[expected_generation]:
            errors.append(
                f"work close terminal generation mismatch: {ref}:{state}"
            )
    return errors


def apply_work_close(
    process_root: Path,
    plan: WorkClosePlanV1,
    authorization: WorkCloseAuthorizationV1,
) -> WorkCloseReceiptV1:
    root = process_root.resolve()
    if not plan.ready:
        raise ValueError("blocked Work close plan cannot be applied")
    authorization.validate_for(plan)
    manifest_path = _manifest_path(root, authorization.authorization_id)
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError("work close authorization_id was already consumed")
    _require_runtime_chain(root, authorization.authorization_id, create=True)
    lock = _acquire_lock(root, authorization.authorization_id)
    manifest = _manifest(plan, authorization)
    attempted: list[str] = []
    applied: list[str] = []
    try:
        _attach_before_bytes(root, manifest)
        _validate_manifest(
            manifest,
            expected_authorization_id=authorization.authorization_id,
        )
        _write_json_atomic(manifest_path, manifest)
        manifest["state"] = "APPLYING"
        _write_json_atomic(manifest_path, manifest)
        for target in manifest["targets"]:
            path = root / target["ref"]
            current = path.read_bytes()
            if _digest_bytes(current) != target["before_digest"]:
                raise ValueError(f"work close target preimage drift: {target['ref']}")
            attempted.append(target["ref"])
            manifest["attempted_refs"] = list(attempted)
            manifest["updated_at"] = _now()
            _write_json_atomic(manifest_path, manifest)
            _replace_bytes(path, base64.b64decode(target["after_bytes_b64"]))
            applied.append(target["ref"])
            manifest["applied_refs"] = list(applied)
            manifest["updated_at"] = _now()
            _write_json_atomic(manifest_path, manifest)
        manifest["state"] = "COMMITTED"
        manifest["updated_at"] = _now()
        _write_json_atomic(manifest_path, manifest)
        return WorkCloseReceiptV1(
            "PASS",
            authorization.authorization_id,
            plan.work_id,
            plan.plan_digest,
            len(applied),
            tuple(applied),
            False,
        )
    except Exception as exc:
        manifest["attempted_refs"] = list(attempted)
        manifest["applied_refs"] = list(applied)
        recovered, failures = _rollback(root, manifest)
        manifest["state"] = "RECOVERED" if recovered else "PARTIAL"
        manifest["updated_at"] = _now()
        manifest["failure"] = str(exc)
        manifest["recovery_failures"] = failures
        _write_json_atomic(manifest_path, manifest)
        return WorkCloseReceiptV1(
            "RECOVERED" if recovered else "PARTIAL",
            authorization.authorization_id,
            plan.work_id,
            plan.plan_digest,
            len(applied),
            tuple(applied),
            not recovered,
            (
                "WORK_CLOSE_APPLY_FAILED",
                *(("WORK_CLOSE_RECOVERY_FAILED",) if failures else ()),
            ),
        )
    finally:
        _release_lock(lock, authorization.authorization_id)


def inspect_work_close_transactions(process_root: Path) -> dict[str, Any]:
    root = process_root.resolve()
    transaction_root = root / TRANSACTION_ROOT_REL
    transactions: list[dict[str, Any]] = []
    errors: list[str] = []
    if transaction_root.is_symlink():
        errors.append("work close transaction root is a symlink")
        return {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "decision": "BLOCKED",
            "transactions": transactions,
            "unresolved_count": len(errors),
            "errors": errors,
        }
    if transaction_root.is_dir():
        for path in sorted(transaction_root.glob("*/manifest.json")):
            try:
                if path.parent.is_symlink() or path.is_symlink():
                    raise ValueError("transaction path is a symlink")
                payload = json.loads(path.read_text(encoding="utf-8"))
                _validate_manifest(
                    payload,
                    expected_authorization_id=path.parent.name,
                )
                state = str(payload.get("state") or "")
                if state == "PARTIAL":
                    errors.append(
                        f"partial work close transaction requires recovery: {path.parent.name}"
                    )
                elif state not in TERMINAL_TRANSACTION_STATES:
                    errors.append(f"unresolved work close transaction: {path.parent.name}:{state}")
                else:
                    errors.extend(_generation_errors(root, payload))
                transactions.append(
                    {
                        "authorization_id": path.parent.name,
                        "work_id": str(payload.get("work_id") or ""),
                        "state": state,
                        "manifest_ref": path.relative_to(root).as_posix(),
                    }
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"invalid work close manifest {path}: {exc}")
    lock = root / LOCK_REL
    if lock.exists() or lock.is_symlink():
        errors.append("work close writer lock remains present")
    return {
        "schema_version": TRANSACTION_SCHEMA_VERSION,
        "decision": "BLOCKED" if errors else "PASS",
        "transactions": transactions,
        "unresolved_count": len(errors),
        "errors": errors,
    }


def recover_work_close_transaction(
    process_root: Path,
    authorization_id: str,
) -> WorkCloseReceiptV1:
    root = process_root.resolve()
    _require_runtime_chain(root, authorization_id, create=False)
    path = _manifest_path(root, authorization_id)
    if not path.is_file() or path.is_symlink():
        raise ValueError("work close transaction manifest is missing")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _validate_manifest(manifest, expected_authorization_id=authorization_id)
    state = str(manifest.get("state") or "")
    if state in TERMINAL_TRANSACTION_STATES:
        generation_errors = _generation_errors(root, manifest)
        if generation_errors:
            raise ValueError("; ".join(generation_errors))
        return WorkCloseReceiptV1(
            "NO_CHANGE",
            authorization_id,
            str(manifest.get("work_id") or ""),
            str(manifest.get("plan_digest") or ""),
            0,
            tuple(manifest.get("applied_refs") or ()),
            state == "PARTIAL",
        )
    lock = _acquire_lock(root, authorization_id)
    try:
        recovered, failures = _rollback(root, manifest)
        manifest["state"] = "RECOVERED" if recovered else "PARTIAL"
        manifest["updated_at"] = _now()
        manifest["recovery_failures"] = failures
        _write_json_atomic(path, manifest)
        return WorkCloseReceiptV1(
            "RECOVERED" if recovered else "PARTIAL",
            authorization_id,
            str(manifest.get("work_id") or ""),
            str(manifest.get("plan_digest") or ""),
            len(manifest.get("applied_refs") or ()),
            tuple(manifest.get("applied_refs") or ()),
            not recovered,
            ("WORK_CLOSE_RECOVERY_FAILED",) if failures else (),
        )
    finally:
        _release_lock(lock, authorization_id)


__all__ = [
    "AUTHORIZATION_KIND",
    "WorkCloseAuthorizationV1",
    "WorkClosePlanV1",
    "WorkCloseReceiptV1",
    "apply_work_close",
    "inspect_work_close_transactions",
    "plan_work_close",
    "recover_work_close_transaction",
]
