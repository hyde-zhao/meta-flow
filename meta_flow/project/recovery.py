"""GOV-004 非原子项目接入事务的显式 inspect/resume/cleanup/abandon。"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.project.adoption import (
    SnapshotAdoptionPlan,
    SnapshotAdoptionRequest,
    apply_snapshot_adoption,
    plan_snapshot_adoption,
)
from meta_flow.project.onboarding import (
    PROCESS_LINK_MODE_NONE,
    ProjectInitPlan,
    ProjectInitRequest,
    apply_project_init,
    check_independent_process_route,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    OnboardingAuthorization,
    OnboardingContractError,
    assert_expected_observations,
    build_plan_envelope,
    claim_authorization,
    load_authorization,
    load_transaction_manifest,
    path_digest,
    portable_target_path,
    repository_descriptor,
    transaction_manifest_path,
    validate_authorization,
    validate_plan_envelope,
    write_transaction_manifest,
)

RECOVERY_ACTIONS = {"inspect", "resume", "cleanup", "abandon"}
RECOVERABLE_STATES = {
    "claimed",
    "process_partial",
    "release_partial",
    "bound_partial",
    "receipt_missing",
}
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_UNRESOLVED_PROCESS_REPO_NAME = "__meta_flow_unresolved_process__"
_UNRESOLVED_PROJECT_ID = "unresolved"


@dataclass(frozen=True)
class RecoveryRequest:
    project_root: Path
    authorization_id: str
    action: str
    decision_ref: str = "decisions/project-recover"
    source_process_root: Path | None = None


@dataclass(frozen=True)
class RecoveryPlan:
    request: RecoveryRequest
    project_root: Path
    process_root: Path
    original_manifest: dict[str, Any]
    original_operation: str
    resume_plan: ProjectInitPlan | SnapshotAdoptionPlan | None
    plan_digest: str
    envelope: dict[str, Any]

    @property
    def blocked(self) -> bool:
        return self.envelope["decision"] == "BLOCKED"

    def as_dict(self) -> dict[str, Any]:
        return dict(self.envelope)


@dataclass(frozen=True)
class RecoveryReceipt:
    envelope: dict[str, Any]
    decision: str
    action: str
    recovered_authorization_id: str
    mutation_count: int

    def as_dict(self) -> dict[str, Any]:
        return dict(self.envelope)


class RecoveryApplyError(RuntimeError):
    def __init__(self, message: str, receipt: RecoveryReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt


def _process_root(project_root: Path, manifest: dict[str, Any]) -> Path:
    intent = manifest.get("intent")
    relative = intent.get("process_repo_relative_path") if isinstance(intent, dict) else ""
    if not isinstance(relative, str) or not _SAFE_NAME_RE.fullmatch(relative):
        raise OnboardingContractError("transaction process repo ref is invalid")
    root = project_root.resolve()
    process = (root.parent / relative).resolve(strict=False)
    if process.parent != root.parent:
        raise OnboardingContractError("transaction process repo ref escapes workspace_parent")
    return process


def _conflict(code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "side": "release",
        "target_ref": f"release/recovery/{code}",
        "message": message,
        "recovery_action": "inspect-and-request-a-new-explicit-decision",
    }


def _recovery_rollback(actions: list[dict[str, Any]]) -> dict[str, Any]:
    refs = [item["target_ref"] for item in actions]
    return {
        "strategy": "explicit-non-atomic-recovery",
        "transaction_ref": "meta-flow/project-onboarding/transactions/authorization-id/manifest.json",
        "release_actions": [item for item in refs if item.startswith("release/")],
        "process_actions": [item for item in refs if item.startswith("process/")],
        "resume_actions": refs,
        "cleanup_actions": [item for item in refs if item.startswith("process/") or "/.meta-flow/" in item],
        "manual_only_actions": [item for item in refs if item.endswith("/.git") or item.endswith("/repository")],
    }


def _unresolved_process_descriptor() -> dict[str, Any]:
    """返回显式未知的 process 诊断值，不把 sibling 猜测伪装成仓库事实。"""

    return {
        "role": "process",
        "anchor": "workspace_parent",
        "relative_path": _UNRESOLVED_PROCESS_REPO_NAME,
        "observation": {"state": "absent", "oid": ""},
        "dirty": False,
        "branch": "",
        "common_dir_identity": "",
    }


def _manifest_failure_plan(
    request: RecoveryRequest,
    *,
    failure_code: str,
) -> RecoveryPlan:
    """为不可读 manifest 构造无 mutation/ownership claim 的统一 BLOCKED envelope。"""

    project_root = request.project_root.resolve()
    health = check_independent_process_route(project_root)
    if health.ok and health.process_repo_root is not None:
        process_root = health.process_repo_root.resolve()
        project_id = health.project_id
        process_repo = repository_descriptor(
            process_root,
            role="process",
            workspace_parent=project_root.parent,
        )
    else:
        # binding 不健康时不得扫描 sibling 或从损坏字节推断 ownership。
        process_root = (project_root.parent / _UNRESOLVED_PROCESS_REPO_NAME).resolve(
            strict=False
        )
        project_id = _UNRESOLVED_PROJECT_ID
        process_repo = _unresolved_process_descriptor()

    actions: list[dict[str, Any]] = []
    messages = {
        "transaction_manifest_missing": (
            "transaction manifest is missing; recovery ownership was not inferred"
        ),
        "transaction_manifest_invalid": (
            "transaction manifest is invalid; recovery ownership was not inferred"
        ),
        "transaction_manifest_ref_invalid": (
            "transaction manifest reference is invalid; recovery ownership was not inferred"
        ),
    }
    conflicts = [
        _conflict(
            failure_code,
            messages.get(
                failure_code,
                "transaction manifest is unavailable; recovery ownership was not inferred",
            ),
        )
    ]
    release_repo = repository_descriptor(
        project_root,
        role="release",
        workspace_parent=project_root.parent,
    )
    envelope = build_plan_envelope(
        operation="project.recover",
        decision="BLOCKED",
        decision_ref=request.decision_ref,
        project_id=project_id,
        release_repo=release_repo,
        process_repo=process_repo,
        base_oids={
            "release": release_repo["observation"],
            "process": process_repo["observation"],
        },
        actions=actions,
        conflicts=conflicts,
        rollback_plan=_recovery_rollback(actions),
    )
    return RecoveryPlan(
        request=request,
        project_root=project_root,
        process_root=process_root,
        original_manifest={},
        original_operation="",
        resume_plan=None,
        plan_digest=envelope["plan_digest"],
        envelope=envelope,
    )


def _resume_original_plan(
    request: RecoveryRequest,
    manifest: dict[str, Any],
    process_root: Path,
) -> ProjectInitPlan | SnapshotAdoptionPlan:
    operation = str(manifest.get("operation") or "")
    intent = manifest.get("intent")
    if not isinstance(intent, dict):
        raise OnboardingContractError("transaction intent is missing")
    project_id = str(manifest.get("project_id") or "")
    if operation == "project.init":
        project_name = str(intent.get("project_name") or "")
        source_ref = str(intent.get("source_ref") or "")
        source_root: Path | None = None
        if source_ref:
            if source_ref != "source/PROJECT.yaml" or request.source_process_root is None:
                raise OnboardingContractError(
                    "snapshot-seeded init resume requires --source-process-root"
                )
            source_root = request.source_process_root.resolve()
            source_oid = str(intent.get("source_oid") or "")
            source_digest = str(intent.get("source_project_digest") or "")
            from meta_flow.project.onboarding_contract import observe_repository

            if observe_repository(source_root) != {"state": "commit", "oid": source_oid}:
                raise OnboardingContractError(
                    "init resume source OID differs from the partial transaction"
                )
            project_path = source_root / "PROJECT.yaml"
            if project_path.is_symlink() or not project_path.is_file():
                raise OnboardingContractError("init resume source PROJECT.yaml is unavailable")
            if sha256(project_path.read_bytes()).hexdigest() != source_digest:
                raise OnboardingContractError(
                    "init resume source PROJECT.yaml digest differs from the partial transaction"
                )
        return plan_project_init(
            ProjectInitRequest(
                project_root=request.project_root,
                project_id=project_id,
                project_name=project_name,
                process_repo_root=process_root,
                source_process_root=source_root,
                process_link_mode=PROCESS_LINK_MODE_NONE,
                decision_ref=request.decision_ref,
            )
        )
    if operation == "project.adopt-snapshot":
        if request.source_process_root is None:
            raise OnboardingContractError("adoption resume requires --source-process-root")
        source_oid = str(intent.get("source_oid") or "")
        from meta_flow.project.onboarding_contract import observe_repository

        if observe_repository(request.source_process_root) != {"state": "commit", "oid": source_oid}:
            raise OnboardingContractError("adoption resume source OID differs from the partial transaction")
        include_refs = intent.get("include_refs")
        if not isinstance(include_refs, list) or not all(isinstance(item, str) for item in include_refs):
            raise OnboardingContractError("adoption resume include_refs are invalid")
        return plan_snapshot_adoption(
            SnapshotAdoptionRequest(
                project_id=project_id,
                source_id=str(intent.get("source_id") or ""),
                source_process_root=request.source_process_root,
                target_process_root=process_root,
                include_refs=tuple(include_refs),
                project_root=request.project_root,
                decision_ref=request.decision_ref,
            )
        )
    raise OnboardingContractError("transaction operation is not recoverable")


def _inspect_actions(
    *,
    project_root: Path,
    process_root: Path,
    manifest: dict[str, Any],
    state: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_actions = manifest.get("actions")
    if not isinstance(raw_actions, list):
        return [], [_conflict("manifest_actions_invalid", "transaction actions must be one list")]
    actions: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    operation = str(manifest.get("operation") or "")
    for offset, raw in enumerate(raw_actions, 1):
        if not isinstance(raw, dict):
            conflicts.append(_conflict("manifest_action_invalid", f"action {offset} is not an object"))
            continue
        target_ref = str(raw.get("target_ref") or "")
        side = str(raw.get("side") or "")
        kind = str(raw.get("kind") or "")
        outcome = str(raw.get("outcome") or "")
        before_digest = str(raw.get("before_digest") or "")
        after_digest = str(raw.get("after_digest") or "")
        blocked_reason = ""
        actual_digest = ""
        digest_matches = False
        manual_control = target_ref.endswith("/repository") or target_ref.endswith("/.git")
        try:
            target = portable_target_path(
                release_root=project_root,
                process_root=process_root,
                target_ref=target_ref,
            )
            actual_digest = path_digest(target)
        except (OSError, OnboardingContractError) as exc:
            blocked_reason = f"target observation failed: {exc}"
        else:
            if manual_control and outcome == "created":
                digest_matches = target.exists() or target.is_symlink()
                if not digest_matches:
                    blocked_reason = "manual-only control target is missing"
            elif outcome == "created" and after_digest:
                digest_matches = actual_digest == after_digest
                if not digest_matches:
                    blocked_reason = "managed target digest differs from transaction receipt"
            elif outcome in {"pending", "missing"}:
                blocked_reason = f"transaction action outcome is {outcome}"
            else:
                blocked_reason = "transaction action lacks a verifiable created receipt"
        if blocked_reason and outcome not in {"pending", "missing"}:
            conflicts.append(
                _conflict(
                    "manifest_action_integrity",
                    f"{target_ref or 'unknown target'}: {blocked_reason}",
                )
            )
        if manual_control and not blocked_reason:
            allowed_next_actions = ["resume", "abandon"]
        elif blocked_reason:
            allowed_next_actions = ["resume", "abandon"]
            if "digest differs" in blocked_reason:
                allowed_next_actions = ["abandon"]
        else:
            allowed_next_actions = ["resume", "cleanup", "abandon"]
        next_action = allowed_next_actions[0]
        actions.append(
            {
                "action_id": f"RECOVER-INSPECT-{offset:03d}",
                "side": side or "process",
                "kind": "inspect",
                "target_ref": target_ref or f"release/recovery/invalid-action-{offset:03d}",
                "ownership": str(raw.get("ownership") or operation or "unknown"),
                "precondition": "manifest-action-readable-and-target-observable",
                "expected_effect": f"next-action={next_action}",
                "state": state,
                "original_kind": kind,
                "outcome": outcome,
                "before_digest": before_digest,
                "after_digest": after_digest,
                "actual_digest": actual_digest,
                "digest_matches": digest_matches,
                "allowed_next_actions": allowed_next_actions,
                "blocked_reason": blocked_reason,
            }
        )
    if not actions and not conflicts:
        actions.append(
            {
                "action_id": "RECOVER-INSPECT-000",
                "side": "release",
                "kind": "inspect",
                "target_ref": "release/transaction-manifest",
                "ownership": operation or "project.recover",
                "precondition": "manifest-readable",
                "expected_effect": "next-action=abandon",
                "state": state,
                "original_kind": "transaction",
                "outcome": "no-actions",
                "before_digest": "",
                "after_digest": "",
                "actual_digest": "",
                "digest_matches": False,
                "allowed_next_actions": ["abandon"],
                "blocked_reason": "transaction manifest contains no action receipts",
            }
        )
    return actions, conflicts


def _terminal_receipt_recovery_action(
    *,
    project_root: Path,
    process_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    terminal = manifest.get("terminal_receipt")
    if not isinstance(terminal, dict):
        raise OnboardingContractError("receipt_missing manifest lacks terminal receipt evidence")
    target_ref = str(terminal.get("target_ref") or "")
    envelope = terminal.get("envelope")
    validate_plan_envelope(envelope, allow_apply_decision=True)
    serialized = json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    expected_digest = sha256(serialized.encode("utf-8")).hexdigest()
    if terminal.get("digest") != expected_digest:
        raise OnboardingContractError("terminal receipt evidence digest mismatch")
    if terminal.get("manifest_state") not in {
        "passed",
        "process_partial",
        "release_partial",
        "bound_partial",
    }:
        raise OnboardingContractError("terminal receipt recovery state is invalid")
    target = portable_target_path(
        release_root=project_root,
        process_root=process_root,
        target_ref=target_ref,
    )
    if target.exists() or target.is_symlink():
        raise OnboardingContractError("terminal receipt target already exists")
    return {
        "action_id": "RECOVER-RESUME-RECEIPT",
        "side": "process",
        "kind": "create-terminal-receipt",
        "target_ref": target_ref,
        "ownership": "project.recover-resume",
        "precondition": "receipt-missing-and-terminal-evidence-digest-match",
        "expected_effect": "write the exact terminal receipt recorded by the partial transaction",
        "source_digest": expected_digest,
    }


def plan_recovery(request: RecoveryRequest) -> RecoveryPlan:
    project_root = request.project_root.resolve()
    try:
        manifest_path = transaction_manifest_path(project_root, request.authorization_id)
    except OnboardingContractError:
        return _manifest_failure_plan(
            request,
            failure_code="transaction_manifest_ref_invalid",
        )
    try:
        manifest = load_transaction_manifest(project_root, request.authorization_id)
    except OnboardingContractError:
        return _manifest_failure_plan(
            request,
            failure_code=(
                "transaction_manifest_missing"
                if not manifest_path.exists()
                else "transaction_manifest_invalid"
            ),
        )
    try:
        process_root = _process_root(project_root, manifest)
    except OnboardingContractError:
        return _manifest_failure_plan(
            request,
            failure_code="transaction_manifest_invalid",
        )
    operation = str(manifest.get("operation") or "")
    state = str(manifest.get("state") or "")
    project_id = str(manifest.get("project_id") or "")
    if not operation or not state or not _PROJECT_ID_RE.fullmatch(project_id):
        return _manifest_failure_plan(
            request,
            failure_code="transaction_manifest_invalid",
        )
    actions: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    resume_plan: ProjectInitPlan | SnapshotAdoptionPlan | None = None

    if request.action not in RECOVERY_ACTIONS:
        conflicts.append(_conflict("action_invalid", "recovery action is invalid"))
    elif request.action == "inspect":
        actions, inspect_conflicts = _inspect_actions(
            project_root=project_root,
            process_root=process_root,
            manifest=manifest,
            state=state,
        )
        conflicts.extend(inspect_conflicts)
    elif state not in RECOVERABLE_STATES:
        # passed / abandoned 事务对所有 mutation recovery 都是幂等 NOOP。
        actions = []
    elif request.action == "resume":
        try:
            resume_plan = _resume_original_plan(request, manifest, process_root)
        except (OSError, ValueError) as exc:
            conflicts.append(_conflict("resume_plan_invalid", str(exc)))
        else:
            if resume_plan.blocked:
                conflicts.append(_conflict("resume_plan_blocked", "fresh original-operation plan is blocked"))
            elif state == "receipt_missing":
                try:
                    actions.append(
                        _terminal_receipt_recovery_action(
                            project_root=project_root,
                            process_root=process_root,
                            manifest=manifest,
                        )
                    )
                except (OSError, ValueError) as exc:
                    conflicts.append(_conflict("terminal_receipt_invalid", str(exc)))
            else:
                for offset, item in enumerate(resume_plan.envelope["actions"], 1):
                    if item["kind"] == "noop":
                        continue
                    actions.append(
                        {
                            **item,
                            "action_id": f"RECOVER-RESUME-{offset:03d}",
                            "ownership": "project.recover-resume",
                        }
                    )
    elif request.action == "cleanup":
        for offset, item in enumerate(reversed(manifest.get("actions") or []), 1):
            if not isinstance(item, dict) or item.get("outcome") != "created":
                continue
            target_ref = str(item.get("target_ref") or "")
            if target_ref.endswith("/.git") or target_ref.endswith("/repository"):
                continue
            try:
                path = portable_target_path(
                    release_root=project_root,
                    process_root=process_root,
                    target_ref=target_ref,
                )
            except OnboardingContractError as exc:
                conflicts.append(_conflict("cleanup_target_invalid", str(exc)))
                continue
            if not (path.exists() or path.is_symlink()):
                continue
            if path_digest(path) != item.get("after_digest"):
                conflicts.append(_conflict("cleanup_digest_mismatch", f"managed ref changed after partial apply: {target_ref}"))
                continue
            actions.append(
                {
                    "action_id": f"RECOVER-CLEANUP-{offset:03d}",
                    "side": str(item.get("side") or "process"),
                    "kind": "delete-managed-ref",
                    "target_ref": target_ref,
                    "ownership": "project.recover-cleanup",
                    "precondition": "created-by-transaction-and-after-digest-match",
                    "expected_effect": "remove only the unchanged transaction-owned ref",
                }
            )
    elif request.action == "abandon":
        actions.append(
            {
                "action_id": "RECOVER-ABANDON-001",
                "side": "release",
                "kind": "mark-abandoned",
                "target_ref": "release/transaction-manifest",
                "ownership": "project.recover-abandon",
                "precondition": "explicit-typed-authorization",
                "expected_effect": "mark the partial transaction abandoned without touching project refs",
            }
        )

    decision = "BLOCKED" if conflicts else "NOOP" if not actions or state in {"passed", "abandoned"} else "READY"
    release_repo = repository_descriptor(project_root, role="release", workspace_parent=project_root.parent)
    process_repo = repository_descriptor(process_root, role="process", workspace_parent=project_root.parent)
    base_oids: dict[str, Any] = {
        "release": release_repo["observation"],
        "process": process_repo["observation"],
    }
    if isinstance(resume_plan, SnapshotAdoptionPlan):
        source_observation = resume_plan.envelope["base_oids"]["source_snapshot"]
        base_oids["source_snapshot"] = source_observation
        process_repo.update(
            {
                "source_id": resume_plan.request.source_id,
                "source_observation": source_observation,
                "include_refs": list(resume_plan.request.include_refs),
            }
        )
    elif isinstance(resume_plan, ProjectInitPlan) and resume_plan.source_project_bytes is not None:
        base_oids["source_snapshot"] = resume_plan.envelope["base_oids"]["source_snapshot"]
    envelope = build_plan_envelope(
        operation="project.recover",
        decision=decision,
        decision_ref=request.decision_ref,
        project_id=project_id,
        release_repo=release_repo,
        process_repo=process_repo,
        base_oids=base_oids,
        actions=actions,
        conflicts=conflicts,
        rollback_plan=_recovery_rollback(actions),
    )
    return RecoveryPlan(
        request=request,
        project_root=project_root,
        process_root=process_root,
        original_manifest=manifest,
        original_operation=operation,
        resume_plan=resume_plan,
        plan_digest=envelope["plan_digest"],
        envelope=envelope,
    )


def _receipt_envelope(
    plan: RecoveryPlan,
    *,
    decision: str,
    outcomes: dict[str, str],
    error: str = "",
) -> dict[str, Any]:
    actions = []
    for original in plan.envelope["actions"]:
        item = dict(original)
        item["outcome"] = outcomes.get(item["target_ref"], "unchanged")
        actions.append(item)
    conflicts = list(plan.envelope["conflicts"])
    if error:
        conflicts.append(_conflict("recovery_apply_failed", error))
    return build_plan_envelope(
        operation="project.recover",
        decision=decision,
        decision_ref=plan.request.decision_ref,
        project_id=plan.envelope["project_id"],
        release_repo=repository_descriptor(plan.project_root, role="release", workspace_parent=plan.project_root.parent),
        process_repo=repository_descriptor(plan.process_root, role="process", workspace_parent=plan.project_root.parent),
        base_oids=plan.envelope["base_oids"],
        actions=actions,
        conflicts=conflicts,
        rollback_plan=plan.envelope["rollback_plan"],
    )


def apply_recovery(
    plan: RecoveryPlan,
    authorization: OnboardingAuthorization | None = None,
) -> RecoveryReceipt:
    if plan.blocked:
        raise OnboardingContractError("recovery plan is blocked")
    if plan.envelope["decision"] == "NOOP" or plan.request.action == "inspect":
        return RecoveryReceipt(
            envelope=_receipt_envelope(plan, decision="NOOP", outcomes={}),
            decision="NOOP",
            action=plan.request.action,
            recovered_authorization_id=plan.request.authorization_id,
            mutation_count=0,
        )
    if authorization is None:
        raise OnboardingContractError("mutating recovery requires typed authorization")
    validate_authorization(plan.envelope, authorization)
    assert_expected_observations(
        plan=plan.envelope,
        release_root=plan.project_root,
        process_root=plan.process_root,
        source_root=(
            plan.request.source_process_root
            if isinstance(plan.resume_plan, SnapshotAdoptionPlan)
            or (
                isinstance(plan.resume_plan, ProjectInitPlan)
                and plan.resume_plan.source_project_bytes is not None
            )
            else None
        ),
        stage="authorization-consume",
    )
    assert_expected_observations(
        plan=plan.envelope,
        release_root=plan.project_root,
        process_root=plan.process_root,
        source_root=(
            plan.request.source_process_root
            if isinstance(plan.resume_plan, SnapshotAdoptionPlan)
            or (
                isinstance(plan.resume_plan, ProjectInitPlan)
                and plan.resume_plan.source_project_bytes is not None
            )
            else None
        ),
        stage="apply-final",
    )
    claim_authorization(plan.project_root, plan.envelope, authorization)
    outcomes: dict[str, str] = {}

    if plan.request.action == "resume":
        if plan.resume_plan is None:
            raise OnboardingContractError("resume plan is unavailable")
        if plan.original_manifest.get("state") == "receipt_missing":
            action = _terminal_receipt_recovery_action(
                project_root=plan.project_root,
                process_root=plan.process_root,
                manifest=plan.original_manifest,
            )
            terminal = plan.original_manifest["terminal_receipt"]
            envelope = terminal["envelope"]
            serialized = json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            target = portable_target_path(
                release_root=plan.project_root,
                process_root=plan.process_root,
                target_ref=action["target_ref"],
            )
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("x", encoding="utf-8") as stream:
                    stream.write(serialized)
                original = dict(plan.original_manifest)
                original_terminal = dict(terminal)
                original_terminal["status"] = "recovered"
                original["terminal_receipt"] = original_terminal
                original["state"] = str(terminal["manifest_state"])
                original["receipt_recovered_by"] = authorization.authorization_id
                original["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
                original["actions"] = [
                    {
                        **item,
                        "outcome": "created",
                        "after_digest": action["source_digest"],
                    }
                    if isinstance(item, dict) and item.get("action_id") == "ADOPT-RECEIPT"
                    else item
                    for item in original.get("actions") or []
                ]
                write_transaction_manifest(
                    plan.project_root,
                    plan.request.authorization_id,
                    original,
                    create_only=False,
                )
            except Exception as exc:
                receipt = RecoveryReceipt(
                    envelope=_receipt_envelope(
                        plan,
                        decision="PARTIAL" if target.exists() else "BLOCKED",
                        outcomes={},
                        error=f"{type(exc).__name__}: terminal receipt recovery failed",
                    ),
                    decision="PARTIAL" if target.exists() else "BLOCKED",
                    action="resume",
                    recovered_authorization_id=plan.request.authorization_id,
                    mutation_count=1 if target.exists() else 0,
                )
                raise RecoveryApplyError(str(exc), receipt) from exc
            outcomes = {action["target_ref"]: "recovered"}
            return RecoveryReceipt(
                envelope=_receipt_envelope(plan, decision="PASS", outcomes=outcomes),
                decision="PASS",
                action="resume",
                recovered_authorization_id=plan.request.authorization_id,
                mutation_count=2,
            )
        delegated = replace(
            authorization,
            operation=plan.resume_plan.envelope["operation"],
            decision_ref=plan.resume_plan.envelope["decision_ref"],
            plan_digest=plan.resume_plan.envelope["plan_digest"],
            expected_oids=plan.resume_plan.envelope["base_oids"],
        )
        try:
            if isinstance(plan.resume_plan, ProjectInitPlan):
                result = apply_project_init(
                    plan.resume_plan,
                    delegated,
                    _authorization_claimed=True,
                )
            else:
                result = apply_snapshot_adoption(
                    plan.resume_plan,
                    delegated,
                    _authorization_claimed=True,
                )
        except Exception as exc:
            receipt = RecoveryReceipt(
                envelope=_receipt_envelope(
                    plan,
                    decision="PARTIAL",
                    outcomes=outcomes,
                    error=f"{type(exc).__name__}: recovery resume failed",
                ),
                decision="PARTIAL",
                action="resume",
                recovered_authorization_id=plan.request.authorization_id,
                mutation_count=0,
            )
            raise RecoveryApplyError(str(exc), receipt) from exc
        original = dict(plan.original_manifest)
        original["state"] = "abandoned"
        original["abandon_reason"] = "resumed-by-new-authorized-transaction"
        original["resumed_by"] = authorization.authorization_id
        original["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        write_transaction_manifest(
            plan.project_root,
            plan.request.authorization_id,
            original,
            create_only=False,
        )
        outcomes = {item["target_ref"]: "resumed" for item in plan.envelope["actions"]}
        return RecoveryReceipt(
            envelope=_receipt_envelope(plan, decision="PASS", outcomes=outcomes),
            decision="PASS",
            action="resume",
            recovered_authorization_id=plan.request.authorization_id,
            mutation_count=result.mutation_count,
        )

    transaction = {
        "schema_version": 1,
        "authorization_id": authorization.authorization_id,
        "operation": "project.recover",
        "project_id": plan.envelope["project_id"],
        "decision_ref": plan.request.decision_ref,
        "plan_digest": plan.plan_digest,
        "state": "claimed",
        "intent": {
            "recovery_action": plan.request.action,
            "recovered_authorization_id": plan.request.authorization_id,
            "process_repo_relative_path": plan.process_root.name,
        },
        "actions": [dict(item, outcome="pending") for item in plan.envelope["actions"]],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    write_transaction_manifest(
        plan.project_root,
        authorization.authorization_id,
        transaction,
        create_only=True,
    )
    mutations = 0
    try:
        if plan.request.action == "cleanup":
            resolved: list[tuple[dict[str, Any], Path]] = []
            old_actions = {
                str(item.get("target_ref")): item
                for item in plan.original_manifest.get("actions") or []
                if isinstance(item, dict)
            }
            for action in plan.envelope["actions"]:
                path = portable_target_path(
                    release_root=plan.project_root,
                    process_root=plan.process_root,
                    target_ref=action["target_ref"],
                )
                expected = old_actions[action["target_ref"]].get("after_digest")
                if path_digest(path) != expected:
                    raise OnboardingContractError("cleanup digest drifted after planning")
                resolved.append((action, path))
            for action, path in resolved:
                path.unlink()
                mutations += 1
                outcomes[action["target_ref"]] = "deleted"
        original = dict(plan.original_manifest)
        original["state"] = "abandoned"
        original["abandon_reason"] = (
            "safe-cleanup-completed" if plan.request.action == "cleanup" else "explicitly-abandoned"
        )
        original["recovered_by"] = authorization.authorization_id
        original["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        write_transaction_manifest(
            plan.project_root,
            plan.request.authorization_id,
            original,
            create_only=False,
        )
        mutations += 1
        if plan.request.action == "abandon":
            outcomes["release/transaction-manifest"] = "abandoned"
        transaction["state"] = "passed"
        transaction["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        write_transaction_manifest(
            plan.project_root,
            authorization.authorization_id,
            transaction,
            create_only=False,
        )
        return RecoveryReceipt(
            envelope=_receipt_envelope(plan, decision="PASS", outcomes=outcomes),
            decision="PASS",
            action=plan.request.action,
            recovered_authorization_id=plan.request.authorization_id,
            mutation_count=mutations,
        )
    except Exception as exc:
        transaction["state"] = "process_partial" if mutations else "claimed"
        transaction["error"] = f"{type(exc).__name__}: recovery apply failed"
        transaction["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        write_transaction_manifest(
            plan.project_root,
            authorization.authorization_id,
            transaction,
            create_only=False,
        )
        decision = "PARTIAL" if mutations else "BLOCKED"
        receipt = RecoveryReceipt(
            envelope=_receipt_envelope(
                plan,
                decision=decision,
                outcomes=outcomes,
                error=f"{type(exc).__name__}: recovery apply failed",
            ),
            decision=decision,
            action=plan.request.action,
            recovered_authorization_id=plan.request.authorization_id,
            mutation_count=mutations,
        )
        raise RecoveryApplyError(str(exc), receipt) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project recover")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--action", choices=sorted(RECOVERY_ACTIONS), required=True)
    parser.add_argument("--source-process-root", type=Path, default=None)
    parser.add_argument("--decision-ref", default="decisions/project-recover")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorization", type=Path, default=None)
    parsed = parser.parse_args(argv or [])
    try:
        plan = plan_recovery(
            RecoveryRequest(
                project_root=parsed.project_root,
                authorization_id=parsed.authorization_id,
                action=parsed.action,
                decision_ref=parsed.decision_ref,
                source_process_root=parsed.source_process_root,
            )
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    if not parsed.apply:
        print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 2 if plan.blocked else 0
    if plan.envelope["decision"] != "NOOP" and parsed.action != "inspect" and parsed.authorization is None:
        print(json.dumps({"plan": plan.as_dict(), "error": "mutating recovery requires --authorization"}, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    try:
        authorization = load_authorization(parsed.authorization) if parsed.authorization else None
        receipt = apply_recovery(plan, authorization)
    except (OSError, TypeError, OnboardingContractError, ValueError, RecoveryApplyError) as exc:
        payload: dict[str, Any] = {"plan": plan.as_dict(), "error": str(exc)}
        if isinstance(exc, RecoveryApplyError):
            payload["receipt"] = exc.receipt.as_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if isinstance(exc, RecoveryApplyError) else 2
    print(json.dumps({"plan": plan.as_dict(), "receipt": receipt.as_dict()}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
