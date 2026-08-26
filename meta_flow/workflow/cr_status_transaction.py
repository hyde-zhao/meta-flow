"""Private status-sync transaction and recovery owner."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from meta_flow.project.read_contract import ReadContextProtocol
from meta_flow.work.model import load_work
from meta_flow.workflow.cr_model import SAFE_AUTHORIZATION_ID_RE, now_utc
from meta_flow.workflow.cr_projection import (
    _acquire_status_sync_writer_lock,
    _atomic_write_text,
    _release_status_sync_writer_lock,
    _transaction_root,
)
from meta_flow.workflow.cr_records import _git_fact, _process_root, _resolve_runtime_ref

# ADR-075-3（A-P0-05 V3 整改）：无 Work 的 system-only plan 使用确定性
# system scope digest 取代空串——空串过不了授权的 64-hex 格式校验，
# 真实 plan -> typed authorization -> apply 链路因此断裂。该 digest 只由
# 命名空间声明推导（无时间/随机输入），plan 与 apply 重验两侧一致。
SYSTEM_NAMESPACE_SCOPE_CLAIM = {
    "schema_version": 1,
    "namespace": "system",
    "operation": "cr.status-sync",
}


def _status_sync_facts(
    project_root: Path,
    *,
    work_id: str,
    canonical_digest: Any,
    dirty_path_digest: Any,
    read_context: ReadContextProtocol | None = None,
) -> tuple[dict[str, str], str]:
    release_root = project_root.resolve()
    process_root = (
        _process_root(release_root)
        if read_context is None
        else read_context.repository_root
    )
    common = _git_fact(process_root, "rev-parse", "--git-common-dir")
    common_identity = canonical_digest(common or "non-git-fixture")
    if work_id:
        scope_digest = load_work(
            process_root,
            work_id,
            read_context=read_context,
        ).scope.digest
    else:
        scope_digest = canonical_digest(dict(SYSTEM_NAMESPACE_SCOPE_CLAIM))
    return (
        {
            "release_head_oid": _git_fact(release_root, "rev-parse", "--verify", "HEAD"),
            "process_head_oid": _git_fact(process_root, "rev-parse", "--verify", "HEAD"),
            "process_git_common_dir_identity": common_identity,
            "current_branch": _git_fact(process_root, "branch", "--show-current"),
            "dirty_path_digest": dirty_path_digest(process_root),
        },
        scope_digest,
    )


def _current_target_digest(target: Any, *, canonical_digest: Any) -> str:
    if not target.path.is_file():
        return canonical_digest("")
    return canonical_digest(target.path.read_text(encoding="utf-8"))


def _status_sync_claim_path(
    project_root: Path,
    authorization_id: str,
    *,
    transaction_root: Path | None = None,
) -> Path:
    if not SAFE_AUTHORIZATION_ID_RE.fullmatch(authorization_id):
        raise ValueError("status-sync authorization_id is invalid")
    return (
        (
            _transaction_root(project_root)
            if transaction_root is None
            else transaction_root
        ).parent
        / "status-sync"
        / "authorizations"
        / f"{authorization_id}.json"
    )


def _claim_status_sync_authorization(
    project_root: Path,
    plan: Any,
    authorization: Any,
    *,
    transaction_root: Path | None = None,
) -> Path:
    path = _status_sync_claim_path(
        project_root,
        authorization.authorization_id,
        transaction_root=transaction_root,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "authorization_id": authorization.authorization_id,
        "operation": authorization.operation,
        "cr_id": authorization.cr_id,
        "work_id": authorization.work_id,
        "plan_digest": authorization.plan_digest,
        "expected_release_oid": authorization.expected_release_oid,
        "expected_process_oid": authorization.expected_process_oid,
        "scope_digest": authorization.scope_digest,
        "claimed_at": now_utc(),
    }
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
    except FileExistsError as exc:
        raise ValueError("status-sync authorization was already consumed") from exc
    return path


def _apply_status_sync_transaction(
    project_root: Path,
    validated: Mapping[str, Any],
    *,
    canonical_digest: Any,
    index_ref: str,
    fail_after_replace: int | None = None,
    fail_recovery: bool = False,
    fault: str = "",
    transaction_root: Path | None = None,
    lock_bound_admission_validator: Any | None = None,
) -> dict[str, Any]:
    """Apply validated mapping/path/scalar inputs without importing public status types."""
    project_root = project_root.resolve()
    try:
        plan_data = validated["plan"]
        authorization_data = validated["authorization"]
        if not isinstance(plan_data, Mapping) or not isinstance(authorization_data, Mapping):
            raise ValueError("validated status-sync input must contain structural mappings")
        plan = SimpleNamespace(
            **{
                **plan_data,
                "targets": tuple(SimpleNamespace(**target) for target in plan_data["targets"]),
            }
        )
        authorization = SimpleNamespace(**authorization_data)
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "status": "BLOCKED",
            "reason": f"invalid validated status-sync mapping: {exc}",
            "mutation_count": 0,
        }
    transaction_root = (
        _transaction_root(project_root)
        if transaction_root is None
        else transaction_root.resolve(strict=False)
    )
    transaction_root.mkdir(parents=True, exist_ok=True)
    unresolved = [path for path in transaction_root.glob("*/manifest.json") if path.is_file()]
    if unresolved:
        return {
            "status": "BLOCKED",
            "reason": "unresolved status-sync transaction exists",
            "mutation_count": 0,
        }
    transaction_id = uuid.uuid4().hex
    lock_owner = _acquire_status_sync_writer_lock(
        project_root,
        transaction_id=transaction_id,
        purpose="apply",
        transaction_root=transaction_root,
    )
    if lock_owner is None:
        return {
            "status": "BLOCKED",
            "reason": "status-sync writer lock exists",
            "mutation_count": 0,
        }
    if lock_bound_admission_validator is not None:
        try:
            admission_error = str(lock_bound_admission_validator() or "")
        except (OSError, ValueError) as exc:
            admission_error = f"lock-bound admission could not be rebuilt: {exc}"
        if admission_error:
            _release_status_sync_writer_lock(
                project_root,
                lock_owner,
                transaction_root=transaction_root,
            )
            return {
                "status": "BLOCKED",
                "reason": admission_error,
                "mutation_count": 0,
            }
    drifted_targets = [
        target.ref
        for target in plan.targets
        if _current_target_digest(target, canonical_digest=canonical_digest) != target.before_digest
    ]
    if drifted_targets:
        _release_status_sync_writer_lock(
            project_root,
            lock_owner,
            transaction_root=transaction_root,
        )
        return {
            "status": "BLOCKED",
            "reason": "target preimage drifted under writer lock: " + ", ".join(drifted_targets),
            "mutation_count": 0,
        }
    try:
        _claim_status_sync_authorization(
            project_root,
            plan,
            authorization,
            transaction_root=transaction_root,
        )
    except ValueError as exc:
        _release_status_sync_writer_lock(
            project_root,
            lock_owner,
            transaction_root=transaction_root,
        )
        return {
            "status": "BLOCKED",
            "reason": str(exc),
            "mutation_count": 0,
        }
    transaction_dir = transaction_root / transaction_id
    backup_root = transaction_dir / "backups"
    after_root = transaction_dir / "after"
    backup_root.mkdir(parents=True)
    after_root.mkdir(parents=True)
    idempotency_key = canonical_digest(
        {
            "command": "status-sync",
            "plan_digest": plan.plan_digest,
            "authorization_id": authorization.authorization_id,
        }
    )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "idempotency_key": idempotency_key,
        "work_id": plan.work_id,
        "cr_id": plan.cr_id,
        "command": "status-sync",
        "plan_digest": plan.plan_digest,
        "mutation_plan_digest": str(plan.mutation_plan.get("plan_digest") or ""),
        "authorization_id": authorization.authorization_id,
        "desired_transition": plan.desired_transition,
        "effective_at": plan.effective_at,
        "expected_facts": plan.expected_facts,
        "scope_digest": plan.scope_digest,
        "lock": dict(lock_owner),
        "targets": [],
        "receipts": [],
        "recovery_state": "prepared",
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    applied: list[Any] = []
    try:
        for target in plan.targets:
            backup = backup_root / f"{target.order:03d}.before"
            prepared_after = after_root / f"{target.order:03d}.after"
            backup.write_text(target.before or "", encoding="utf-8")
            prepared_after.write_text(target.after, encoding="utf-8")
            backup_digest = canonical_digest(backup.read_text(encoding="utf-8"))
            if backup_digest != target.before_digest:
                raise RuntimeError(f"backup digest mismatch: {target.ref}")
            if canonical_digest(prepared_after.read_text(encoding="utf-8")) != target.after_digest:
                raise RuntimeError(f"prepared after digest mismatch: {target.ref}")
            manifest["targets"].append(
                {
                    **{
                        "order": target.order,
                        "ref": target.ref,
                        "truth_or_derived": target.truth_or_derived,
                        "before_exists": target.before is not None,
                        "before_digest": target.before_digest,
                        "after_digest": target.after_digest,
                    },
                    "before_content_ref": f"backups/{backup.name}",
                    "before_content_digest": backup_digest,
                    "after_content_ref": f"after/{prepared_after.name}",
                    "backup_created_at": now_utc(),
                    "backup_verified_at": now_utc(),
                    "apply_status": "prepared",
                    "recovery_status": "not-required",
                }
            )
        manifest_path = transaction_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest["recovery_state"] = "applying"
        if fault == "before-first-replace":
            raise RuntimeError("injected failure before first replace")
        for offset, target in enumerate(plan.targets, 1):
            if fault == "before-index-last" and target.ref == index_ref:
                raise RuntimeError("injected failure before index-last replace")
            _atomic_write_text(target.path, target.after)
            applied.append(target)
            if fault == "after-replace-before-receipt":
                raise RuntimeError("injected abrupt exit after replace before receipt")
            manifest["targets"][offset - 1]["apply_status"] = "applied"
            manifest["receipts"].append(
                {
                    "target_ref": target.ref,
                    "operation": "replace" if target.before is not None else "create",
                    "observed_before_digest": target.before_digest,
                    "observed_after_digest": _current_target_digest(
                        target, canonical_digest=canonical_digest
                    ),
                    "completed_at": now_utc(),
                }
            )
            manifest["updated_at"] = now_utc()
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if fail_after_replace == offset:
                raise RuntimeError(f"injected failure after replace {offset}")
            if fault == "after-receipt-before-next":
                raise RuntimeError("injected abrupt exit after receipt before next target")
            if (
                fault == "after-truth-before-derived"
                and target.truth_or_derived == "truth"
                and offset < len(plan.targets)
                and plan.targets[offset].truth_or_derived == "derived"
            ):
                raise RuntimeError("injected failure after truth before derived")
        if fault == "during-read-back":
            raise RuntimeError("injected failure during read-back")
        readback_failures = [
            target.ref
            for target in plan.targets
            if _current_target_digest(target, canonical_digest=canonical_digest)
            != target.after_digest
        ]
        if readback_failures:
            raise RuntimeError("read-back mismatch: " + ", ".join(readback_failures))
        manifest["recovery_state"] = "committed"
        manifest["lock"]["lease_state"] = "released"
        manifest["updated_at"] = now_utc()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths = {target.ref: target.path for target in plan.targets}
        shutil.rmtree(transaction_dir)
        return {
            "status": "PASS",
            "transaction_id": transaction_id,
            "idempotency_key": idempotency_key,
            "plan_digest": plan.plan_digest,
            "authorization_id": authorization.authorization_id,
            "mutation_count": len(plan.targets),
            "paths": paths,
        }
    except Exception as exc:
        manifest["recovery_state"] = "recovery-required"
        recovery_errors: list[str] = []
        for target in reversed(applied):
            try:
                if fail_recovery:
                    raise RuntimeError("injected recovery failure")
                if target.before is None:
                    if target.path.exists():
                        target.path.unlink()
                else:
                    _atomic_write_text(target.path, target.before)
                if (
                    _current_target_digest(target, canonical_digest=canonical_digest)
                    != target.before_digest
                ):
                    raise RuntimeError("recovery digest mismatch")
                for entry in manifest["targets"]:
                    if entry["ref"] == target.ref:
                        entry["recovery_status"] = "restored"
            except Exception as recovery_error:
                recovery_errors.append(f"{target.ref}: {recovery_error}")
        status = "PARTIAL" if recovery_errors else "RECOVERED" if applied else "BLOCKED"
        manifest["recovery_state"] = status.lower()
        manifest["lock"]["lease_state"] = "released"
        manifest["updated_at"] = now_utc()
        (transaction_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if status in {"BLOCKED", "RECOVERED"}:
            shutil.rmtree(transaction_dir)
        result = {
            "status": status,
            "transaction_id": transaction_id,
            "idempotency_key": idempotency_key,
            "plan_digest": plan.plan_digest,
            "authorization_id": authorization.authorization_id,
            "mutation_count": len(applied),
            "reason": str(exc),
            "recovery_errors": recovery_errors,
        }
        if status == "PARTIAL":
            result["rollback_evidence_ref"] = (
                f"private://status-sync/transactions/{transaction_id}/manifest.json"
            )
        return result
    finally:
        _release_status_sync_writer_lock(
            project_root,
            lock_owner,
            transaction_root=transaction_root,
        )


def inspect_status_sync_transactions(project_root: Path) -> dict[str, Any]:
    """Inspect unresolved private manifests without changing repository state."""

    root = _transaction_root(project_root.resolve())
    transactions: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*/manifest.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                transactions.append(
                    {
                        "transaction_id": path.parent.name,
                        "recovery_state": "partial",
                        "error": str(exc),
                    }
                )
                continue
            transactions.append(
                {
                    "transaction_id": payload.get("transaction_id") or path.parent.name,
                    "cr_id": payload.get("cr_id") or "",
                    "work_id": payload.get("work_id") or "",
                    "recovery_state": payload.get("recovery_state") or "",
                    "target_refs": [
                        str(item.get("ref") or "")
                        for item in payload.get("targets") or []
                        if isinstance(item, dict)
                    ],
                }
            )
    return {
        "decision": "PASS",
        "transaction_count": len(transactions),
        "transactions": transactions,
    }


def recover_status_sync_transaction(
    project_root: Path,
    transaction_id: str,
    *,
    action: str,
    typed_authorized: bool = False,
    canonical_digest: Any,
    dirty_path_digest: Any,
) -> dict[str, Any]:
    """Explicitly resume, rollback, or abandon one unresolved transaction."""

    if action not in {"resume", "rollback", "abandon"}:
        raise ValueError("recovery action must be resume, rollback, or abandon")
    if not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise ValueError("transaction_id must be one 32-character lowercase hex identity")
    project_root = project_root.resolve()
    transaction_dir = _transaction_root(project_root) / transaction_id
    manifest_path = transaction_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"status-sync transaction not found: {transaction_id}")
    if action == "abandon" and not typed_authorized:
        return {
            "status": "BLOCKED",
            "reason": "abandon requires typed authorization",
            "mutation_count": 0,
        }
    lock_owner = _acquire_status_sync_writer_lock(
        project_root,
        transaction_id=transaction_id,
        purpose=f"recovery:{action}",
    )
    if lock_owner is None:
        return {
            "status": "BLOCKED",
            "reason": "status-sync writer lock exists",
            "mutation_count": 0,
        }
    manifest: dict[str, Any] = {}
    remove_transaction = False
    result: dict[str, Any]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        prior_lock = manifest.get("lock")
        if isinstance(prior_lock, dict):
            manifest.setdefault("lock_history", []).append(prior_lock)
        manifest["lock"] = dict(lock_owner)
        manifest["recovery_state"] = "recovering"
        manifest["updated_at"] = now_utc()
        _atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        if action == "abandon":
            manifest["recovery_state"] = "abandoned"
            manifest["updated_at"] = now_utc()
            result = {"status": "PASS", "action": "abandon", "mutation_count": 1}
        else:
            facts, scope_digest = _status_sync_facts(
                project_root,
                work_id=str(manifest.get("work_id") or ""),
                canonical_digest=canonical_digest,
                dirty_path_digest=dirty_path_digest,
            )
            expected = manifest.get("expected_facts") or {}
            stable_keys = {
                "release_head_oid",
                "process_head_oid",
                "process_git_common_dir_identity",
                "current_branch",
            }
            if any(
                facts.get(key) != expected.get(key) for key in stable_keys
            ) or scope_digest != manifest.get("scope_digest"):
                manifest["recovery_state"] = "recovery-required"
                result = {
                    "status": "BLOCKED",
                    "reason": "recovery expected facts or scope digest drifted",
                    "mutation_count": 0,
                }
            else:
                targets = sorted(
                    [item for item in manifest.get("targets") or [] if isinstance(item, dict)],
                    key=lambda item: int(item.get("order") or 0),
                    reverse=action == "rollback",
                )
                changed = 0
                errors: list[str] = []
                for item in targets:
                    ref = str(item.get("ref") or "")
                    try:
                        path = _resolve_runtime_ref(project_root, ref)
                        before_exists = bool(item.get("before_exists"))
                        before_content = (
                            transaction_dir / str(item["before_content_ref"])
                        ).read_text(encoding="utf-8")
                        after_content = (
                            transaction_dir / str(item["after_content_ref"])
                        ).read_text(encoding="utf-8")
                        current_digest = (
                            canonical_digest(path.read_text(encoding="utf-8"))
                            if path.is_file()
                            else canonical_digest("")
                        )
                        before_digest = str(item.get("before_digest") or "")
                        after_digest = str(item.get("after_digest") or "")
                        desired_digest = after_digest if action == "resume" else before_digest
                        if current_digest == desired_digest:
                            continue
                        if current_digest not in {before_digest, after_digest}:
                            raise RuntimeError(
                                "current digest matches neither prepared before nor after content"
                            )
                        if action == "resume":
                            _atomic_write_text(path, after_content)
                        elif before_exists:
                            _atomic_write_text(path, before_content)
                        elif path.exists():
                            path.unlink()
                        observed = (
                            canonical_digest(path.read_text(encoding="utf-8"))
                            if path.is_file()
                            else canonical_digest("")
                        )
                        if observed != desired_digest:
                            raise RuntimeError("recovery read-back digest mismatch")
                        changed += 1
                    except Exception as exc:
                        errors.append(f"{ref}: {exc}")
                if errors:
                    manifest["recovery_state"] = "partial"
                    result = {
                        "status": "PARTIAL",
                        "action": action,
                        "mutation_count": changed,
                        "errors": errors,
                    }
                else:
                    manifest["recovery_state"] = "committed" if action == "resume" else "recovered"
                    remove_transaction = True
                    result = {
                        "status": "PASS" if action == "resume" else "RECOVERED",
                        "action": action,
                        "mutation_count": changed,
                    }
        manifest["updated_at"] = now_utc()
        if not remove_transaction:
            manifest["lock"]["lease_state"] = "released"
            _atomic_write_text(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
        else:
            shutil.rmtree(transaction_dir)
        return result
    finally:
        _release_status_sync_writer_lock(project_root, lock_owner)
