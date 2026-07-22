"""portable-binding 项目的 snapshot-only 接入计划与受权 apply。"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from meta_flow.project.model import is_safe_ref, load_project
from meta_flow.project.onboarding import check_independent_process_route
from meta_flow.project.onboarding_contract import (
    OnboardingAuthorization,
    OnboardingContractError,
    assert_expected_observations,
    authorization_claim_path,
    build_plan_envelope,
    claim_authorization,
    load_authorization,
    observe_repository,
    path_digest,
    repository_descriptor,
    validate_authorization,
    write_transaction_manifest,
)
from meta_flow.project.process_route import (
    ProcessRouteError,
    require_project_process_route,
)
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.workspace.git_sync import run_git

ADOPTION_SCHEMA_VERSION = 2
ADOPTION_INDEX_REL = Path("legacy/INDEX.yaml")
ADOPTION_RECEIPT_DIR = Path(".meta-flow/adoption-receipts")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_WORK_FILES = {
    "WORK.yaml",
    "REQUEST.md",
    "HANDOFF.md",
    "RESULT.json",
    "USAGE.json",
    "VALIDATION.json",
    "REVIEW.md",
}


@dataclass(frozen=True)
class SnapshotAdoptionRequest:
    project_id: str
    source_id: str
    source_process_root: Path
    target_process_root: Path
    include_refs: tuple[str, ...]
    project_root: Path | None = None
    decision_ref: str = "decisions/project-adopt-snapshot"


@dataclass(frozen=True)
class SnapshotEntry:
    ref: str
    kind: str
    sha256: str
    mode: int
    link_text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class AdoptionAction:
    action: str
    ref: str
    reason: str


@dataclass(frozen=True)
class AdoptionConflict:
    code: str
    ref: str
    message: str


@dataclass(frozen=True)
class SnapshotAdoptionPlan:
    request: SnapshotAdoptionRequest
    project_root: Path
    source_root: Path
    target_root: Path
    source_oid: str
    target_oid: str
    entries: tuple[SnapshotEntry, ...]
    index_payload: dict[str, Any]
    actions: tuple[AdoptionAction, ...]
    conflicts: tuple[AdoptionConflict, ...]
    plan_digest: str
    envelope: dict[str, Any]

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.envelope)


AdoptionAuthorization = OnboardingAuthorization


@dataclass(frozen=True)
class AdoptionReceipt:
    envelope: dict[str, Any]
    authorization_id: str
    plan_digest: str
    decision: str
    created_refs: tuple[str, ...]
    mutation_count: int
    source_oid: str
    target_oid: str
    legacy_source_mode: str
    recovery_route: str

    def as_dict(self) -> dict[str, Any]:
        return dict(self.envelope)


class AdoptionApplyError(RuntimeError):
    def __init__(self, message: str, receipt: AdoptionReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt


def _git_root_and_oid(root: Path) -> tuple[Path | None, str, Path | None]:
    top = run_git(["rev-parse", "--show-toplevel"], cwd=root)
    if not top.ok:
        return None, "", None
    git_root = Path(top.stdout.strip()).resolve()
    if git_root != root.resolve():
        return git_root, "", None
    oid_result = run_git(["rev-parse", "--verify", "HEAD"], cwd=root)
    common_result = run_git(["rev-parse", "--git-common-dir"], cwd=root)
    common: Path | None = None
    if common_result.ok:
        common = Path(common_result.stdout.strip())
        if not common.is_absolute():
            common = root / common
        common = common.resolve()
    return git_root, oid_result.stdout.strip() if oid_result.ok else "", common


def _allowed_snapshot_ref(ref: str) -> bool:
    if not is_safe_ref(ref):
        return False
    path = PurePosixPath(ref)
    parts = path.parts
    if ref in {"PROJECT.yaml", "ROADMAP.yaml"}:
        return True
    if len(parts) == 3 and parts[0] == "phases" and parts[2] == "PHASE.yaml":
        return True
    return len(parts) == 3 and parts[0] == "works" and parts[2] in _WORK_FILES


def _entry_for(root: Path, ref: str) -> SnapshotEntry:
    path = root / ref
    if path.is_symlink():
        link_text = os.readlink(path)
        if Path(link_text).is_absolute() or ".." in PurePosixPath(link_text).parts:
            raise ValueError("snapshot symlink must use a non-parent relative target")
        return SnapshotEntry(ref, "symlink", sha256(link_text.encode()).hexdigest(), 0, link_text)
    if not path.is_file():
        raise ValueError("snapshot ref must be one existing regular file or safe symlink")
    return SnapshotEntry(
        ref=ref,
        kind="file",
        sha256=sha256(path.read_bytes()).hexdigest(),
        mode=stat.S_IMODE(path.stat().st_mode),
    )


def _target_matches(root: Path, entry: SnapshotEntry) -> bool:
    path = root / entry.ref
    if entry.kind == "symlink":
        return path.is_symlink() and os.readlink(path) == entry.link_text
    return (
        path.is_file()
        and not path.is_symlink()
        and sha256(path.read_bytes()).hexdigest() == entry.sha256
        and stat.S_IMODE(path.stat().st_mode) == entry.mode
    )


def _contract_actions(actions: tuple[AdoptionAction, ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for offset, action in enumerate(actions, 1):
        result.append(
            {
                "action_id": f"ADOPT-{offset:03d}",
                "side": "process",
                "kind": action.action,
                "target_ref": f"process/{action.ref}",
                "ownership": "project.adopt-snapshot",
                "precondition": "create-only-or-exact-match",
                "expected_effect": action.reason,
            }
        )
    return result


def _contract_conflicts(conflicts: tuple[AdoptionConflict, ...]) -> list[dict[str, Any]]:
    return [
        {
            "code": item.code,
            "side": "source" if item.code.startswith("source") else "process",
            "target_ref": f"process/input/{item.code or f'conflict-{offset:03d}'}",
            "message": item.message,
            "recovery_action": "resolve-conflict-and-rebuild-plan",
        }
        for offset, item in enumerate(conflicts, 1)
    ]


def _rollback_plan(actions: list[dict[str, Any]]) -> dict[str, Any]:
    refs = [item["target_ref"] for item in actions if item["kind"] != "noop"]
    return {
        "strategy": "explicit-non-atomic-recovery",
        "transaction_ref": "meta-flow/project-onboarding/transactions/authorization-id/manifest.json",
        "release_actions": [],
        "process_actions": refs,
        "resume_actions": refs,
        "cleanup_actions": refs,
        "manual_only_actions": [],
    }


def _build_envelope(
    *,
    request: SnapshotAdoptionRequest,
    project_root: Path,
    source_root: Path,
    target_root: Path,
    source_oid: str,
    actions: tuple[AdoptionAction, ...],
    conflicts: tuple[AdoptionConflict, ...],
    decision: str | None = None,
) -> dict[str, Any]:
    contract_actions = _contract_actions(actions)
    selected = decision or (
        "BLOCKED"
        if conflicts
        else "NOOP"
        if all(item.action == "noop" for item in actions)
        else "READY"
    )
    release_repo = repository_descriptor(
        project_root,
        role="release",
        workspace_parent=project_root.parent,
    )
    process_repo = repository_descriptor(
        target_root,
        role="process",
        workspace_parent=project_root.parent,
    )
    process_repo.update(
        {
            "source_id": request.source_id,
            "source_observation": observe_repository(source_root),
            "include_refs": list(request.include_refs),
        }
    )
    return build_plan_envelope(
        operation="project.adopt-snapshot",
        decision=selected,
        decision_ref=request.decision_ref,
        project_id=request.project_id,
        release_repo=release_repo,
        process_repo=process_repo,
        base_oids={
            "release": release_repo["observation"],
            "process": process_repo["observation"],
            "source_snapshot": {"state": "commit", "oid": source_oid} if source_oid else {"state": "unborn", "oid": ""},
        },
        actions=contract_actions,
        conflicts=_contract_conflicts(conflicts),
        rollback_plan=_rollback_plan(contract_actions),
    )


def plan_snapshot_adoption(request: SnapshotAdoptionRequest) -> SnapshotAdoptionPlan:
    source = request.source_process_root.resolve()
    target = request.target_process_root.resolve()
    project_root = (
        request.project_root.resolve()
        if request.project_root is not None
        else target.parent / "binding-required-release"
    )
    actions: list[AdoptionAction] = []
    conflicts: list[AdoptionConflict] = []
    entries: list[SnapshotEntry] = []

    if request.project_root is None:
        conflicts.append(
            AdoptionConflict(
                "binding_required",
                "project_root",
                "snapshot adoption requires a release project root with a healthy portable binding",
            )
        )
    else:
        try:
            route = require_project_process_route(project_root, project_id=request.project_id)
        except ProcessRouteError as exc:
            conflicts.append(AdoptionConflict("binding_invalid", "project_root", str(exc)))
        else:
            if route.process_root != target:
                conflicts.append(AdoptionConflict("target_route_mismatch", "target_process_root", "target process root must come from the release binding"))

    source_root, source_oid, source_common = _git_root_and_oid(source)
    _release_root, _release_oid, release_common = _git_root_and_oid(project_root)
    target_root, target_oid, target_common = _git_root_and_oid(target)
    if source_root != source or not source_oid:
        conflicts.append(AdoptionConflict("source_not_git", "source", "source must be one committed Git repository root"))
    if target_root != target:
        conflicts.append(AdoptionConflict("target_not_git", "target", "target must be the bound process Git repository root"))
    if source == target or source == project_root:
        conflicts.append(AdoptionConflict("source_target_overlap", "source", "source must be independent and read-only"))
    source_status = run_git(["status", "--porcelain=v1"], cwd=source)
    if source_root == source and (not source_status.ok or source_status.stdout.strip()):
        conflicts.append(AdoptionConflict("source_dirty", "source", "source snapshot Git root must be clean"))
    if source_common is not None and source_common in {target_common, release_common}:
        conflicts.append(AdoptionConflict("shared_git_control", "source", "source shares Git common dir with release or process"))
    if not _ID_RE.fullmatch(request.source_id):
        conflicts.append(AdoptionConflict("source_id_invalid", "source_id", "source_id is invalid"))
    if not request.include_refs:
        conflicts.append(AdoptionConflict("empty_snapshot", "include_refs", "include at least one current snapshot ref"))
    if len(set(request.include_refs)) != len(request.include_refs):
        conflicts.append(AdoptionConflict("duplicate_ref", "include_refs", "include_refs contains duplicates"))

    for ref in sorted(set(request.include_refs)):
        if not _allowed_snapshot_ref(ref):
            conflicts.append(AdoptionConflict("ref_not_allowed", ref, "ref is outside snapshot-only allowlist"))
            continue
        try:
            entry = _entry_for(source, ref)
        except (OSError, ValueError) as exc:
            conflicts.append(AdoptionConflict("source_ref_invalid", ref, str(exc)))
            continue
        entries.append(entry)
        if (target / ref).exists() or (target / ref).is_symlink():
            if _target_matches(target, entry):
                actions.append(AdoptionAction("noop", ref, "matching snapshot entry already exists"))
            else:
                conflicts.append(AdoptionConflict("target_conflict", ref, "target entry differs; overwrite is forbidden"))
        else:
            actions.append(AdoptionAction("create", ref, "copy one explicit current snapshot entry"))

    try:
        source_project = load_project(source)
    except (OSError, ValueError) as exc:
        conflicts.append(AdoptionConflict("source_project_invalid", "PROJECT.yaml", str(exc)))
    else:
        if source_project.project_id != request.project_id:
            conflicts.append(AdoptionConflict("project_id_mismatch", "PROJECT.yaml", "source Project belongs to another project"))

    index_payload = {
        "schema_version": ADOPTION_SCHEMA_VERSION,
        "project_id": request.project_id,
        "source_id": request.source_id,
        "source_oid": source_oid,
        "legacy_source_mode": "read-only",
        "entries": [entry.as_dict() for entry in entries],
    }
    index_path = target / ADOPTION_INDEX_REL
    if index_path.exists() or index_path.is_symlink():
        try:
            index_matches = load_yaml_object(index_path) == index_payload
        except (OSError, ValueError):
            index_matches = False
        if index_matches:
            actions.append(AdoptionAction("noop", ADOPTION_INDEX_REL.as_posix(), "matching source index already exists"))
        else:
            conflicts.append(AdoptionConflict("index_conflict", ADOPTION_INDEX_REL.as_posix(), "source index differs"))
    else:
        actions.append(AdoptionAction("create", ADOPTION_INDEX_REL.as_posix(), "write read-only source index"))

    frozen_actions = tuple(actions)
    frozen_conflicts = tuple(conflicts)
    envelope = _build_envelope(
        request=request,
        project_root=project_root,
        source_root=source,
        target_root=target,
        source_oid=source_oid,
        actions=frozen_actions,
        conflicts=frozen_conflicts,
    )
    return SnapshotAdoptionPlan(
        request=request,
        project_root=project_root,
        source_root=source,
        target_root=target,
        source_oid=source_oid,
        target_oid=target_oid,
        entries=tuple(entries),
        index_payload=index_payload,
        actions=frozen_actions,
        conflicts=frozen_conflicts,
        plan_digest=envelope["plan_digest"],
        envelope=envelope,
    )


def _copy_entry_create_only(source_root: Path, target_root: Path, entry: SnapshotEntry) -> None:
    source = source_root / entry.ref
    target = target_root / entry.ref
    if target.exists() or target.is_symlink():
        if _target_matches(target_root, entry):
            return
        raise FileExistsError(f"target snapshot entry exists and differs: {entry.ref}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if entry.kind == "symlink":
        target.symlink_to(entry.link_text)
    else:
        with target.open("xb") as stream:
            stream.write(source.read_bytes())
        target.chmod(entry.mode)
    if not _target_matches(target_root, entry):
        raise RuntimeError(f"post-copy verification failed: {entry.ref}")


def _receipt_envelope(
    plan: SnapshotAdoptionPlan,
    *,
    decision: str,
    outcomes: dict[str, str],
    error: str = "",
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for original in plan.envelope["actions"]:
        item = dict(original)
        item["outcome"] = outcomes.get(item["target_ref"], "unchanged")
        actions.append(item)
    conflicts = list(plan.envelope["conflicts"])
    if error:
        conflicts.append(
            {
                "code": "apply_failed",
                "side": "process",
                "target_ref": "process/transaction",
                "message": error,
                "recovery_action": "run-project-recover-inspect",
            }
        )
    return build_plan_envelope(
        operation="project.adopt-snapshot",
        decision=decision,
        decision_ref=plan.request.decision_ref,
        project_id=plan.request.project_id,
        release_repo=repository_descriptor(plan.project_root, role="release", workspace_parent=plan.project_root.parent),
        process_repo={
            **repository_descriptor(plan.target_root, role="process", workspace_parent=plan.project_root.parent),
            "source_id": plan.request.source_id,
            "source_observation": observe_repository(plan.source_root),
            "include_refs": list(plan.request.include_refs),
        },
        base_oids=plan.envelope["base_oids"],
        actions=actions,
        conflicts=conflicts,
        rollback_plan=plan.envelope["rollback_plan"],
    )


def apply_snapshot_adoption(
    plan: SnapshotAdoptionPlan,
    authorization: OnboardingAuthorization | None = None,
    *,
    _authorization_claimed: bool = False,
) -> AdoptionReceipt:
    if plan.blocked:
        raise ValueError("snapshot adoption plan is blocked")
    if (
        authorization is not None
        and not _authorization_claimed
        and authorization_claim_path(plan.project_root, authorization.authorization_id).exists()
    ):
        raise OnboardingContractError("authorization was already consumed")
    fresh = plan_snapshot_adoption(plan.request)
    if fresh.plan_digest != plan.plan_digest:
        raise OnboardingContractError("snapshot adoption plan is stale; rebuild plan and authorization")
    if plan.envelope["decision"] == "NOOP":
        return AdoptionReceipt(
            envelope=_receipt_envelope(plan, decision="NOOP", outcomes={}),
            authorization_id="",
            plan_digest=plan.plan_digest,
            decision="NOOP",
            created_refs=(),
            mutation_count=0,
            source_oid=plan.source_oid,
            target_oid=plan.target_oid,
            legacy_source_mode="read-only",
            recovery_route="none",
        )
    if authorization is None:
        raise OnboardingContractError("snapshot adoption apply requires typed authorization")
    if not _authorization_claimed:
        validate_authorization(plan.envelope, authorization)
    assert_expected_observations(
        plan=plan.envelope,
        release_root=plan.project_root,
        process_root=plan.target_root,
        source_root=plan.source_root,
        stage="authorization-consume",
    )
    assert_expected_observations(
        plan=plan.envelope,
        release_root=plan.project_root,
        process_root=plan.target_root,
        source_root=plan.source_root,
        stage="apply-final",
    )
    if not _authorization_claimed:
        claim_authorization(plan.project_root, plan.envelope, authorization)

    manifest = {
        "schema_version": 1,
        "authorization_id": authorization.authorization_id,
        "operation": "project.adopt-snapshot",
        "project_id": plan.request.project_id,
        "decision_ref": plan.request.decision_ref,
        "plan_digest": plan.plan_digest,
        "state": "claimed",
        "intent": {
            "source_id": plan.request.source_id,
            "source_oid": plan.source_oid,
            "include_refs": list(plan.request.include_refs),
            "process_repo_relative_path": plan.target_root.name,
        },
        "actions": [
            {
                "action_id": item["action_id"],
                "side": item["side"],
                "kind": item["kind"],
                "target_ref": item["target_ref"],
                "before_digest": "",
                "after_digest": "",
                "outcome": "pending",
            }
            for item in plan.envelope["actions"]
            if item["kind"] != "noop"
        ],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    write_transaction_manifest(
        plan.project_root,
        authorization.authorization_id,
        manifest,
        create_only=True,
    )
    created: list[str] = []
    outcomes: dict[str, str] = {}
    mutations = 0
    route_health_checked = False
    receipt_attempted = False

    def record(ref: str, path: Path, before_digest: str) -> None:
        target_ref = f"process/{ref}"
        created.append(ref)
        outcomes[target_ref] = "created"
        for item in manifest["actions"]:
            if item["target_ref"] == target_ref:
                item.update(
                    {
                        "before_digest": before_digest,
                        "after_digest": path_digest(path),
                        "outcome": "created",
                    }
                )
                break
        manifest["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        write_transaction_manifest(
            plan.project_root,
            authorization.authorization_id,
            manifest,
            create_only=False,
        )

    def write_terminal_receipt(*, decision: str, state: str, error: str = "") -> dict[str, Any]:
        nonlocal mutations, receipt_attempted
        receipt_attempted = True
        receipt_ref = (ADOPTION_RECEIPT_DIR / f"{authorization.authorization_id}.json").as_posix()
        receipt_path = plan.target_root / receipt_ref
        if receipt_path.exists() or receipt_path.is_symlink():
            raise FileExistsError("adoption terminal receipt already exists")
        envelope = _receipt_envelope(plan, decision=decision, outcomes=outcomes, error=error)
        serialized = json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        receipt_action = {
            "action_id": "ADOPT-RECEIPT",
            "side": "process",
            "kind": "create",
            "target_ref": f"process/{receipt_ref}",
            "before_digest": path_digest(receipt_path),
            "after_digest": sha256(serialized.encode("utf-8")).hexdigest(),
            "outcome": "created",
        }
        manifest["actions"] = [
            item for item in manifest["actions"] if item.get("action_id") != "ADOPT-RECEIPT"
        ] + [receipt_action]
        manifest["state"] = state
        manifest["terminal_receipt"] = {
            "decision": decision,
            "target_ref": f"process/{receipt_ref}",
            "status": "created",
            "digest": receipt_action["after_digest"],
            "manifest_state": state,
            "envelope": envelope,
        }
        manifest["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        write_transaction_manifest(
            plan.project_root,
            authorization.authorization_id,
            manifest,
            create_only=False,
        )
        try:
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            with receipt_path.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
        except Exception:
            receipt_action["after_digest"] = ""
            receipt_action["outcome"] = "missing"
            manifest["state"] = "receipt_missing"
            manifest["terminal_receipt"]["status"] = "missing"
            manifest["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            write_transaction_manifest(
                plan.project_root,
                authorization.authorization_id,
                manifest,
                create_only=False,
            )
            raise
        mutations += 1
        created.append(receipt_ref)
        outcomes[f"process/{receipt_ref}"] = "created"
        return envelope

    try:
        for entry in plan.entries:
            if not _target_matches(plan.target_root, entry):
                target_path = plan.target_root / entry.ref
                before = path_digest(target_path)
                _copy_entry_create_only(plan.source_root, plan.target_root, entry)
                mutations += 1
                record(entry.ref, target_path, before)
        index_path = plan.target_root / ADOPTION_INDEX_REL
        if not index_path.exists() and not index_path.is_symlink():
            before = path_digest(index_path)
            index_path.parent.mkdir(parents=True, exist_ok=True)
            with index_path.open("x", encoding="utf-8") as stream:
                stream.write(dump_yaml(plan.index_payload) + "\n")
            mutations += 1
            record(ADOPTION_INDEX_REL.as_posix(), index_path, before)

        route_health_checked = True
        health = check_independent_process_route(plan.project_root)
        if not health.ok:
            raise RuntimeError("post-apply route health failed")
        envelope = write_terminal_receipt(decision="PASS", state="passed")
        return AdoptionReceipt(
            envelope=envelope,
            authorization_id=authorization.authorization_id,
            plan_digest=plan.plan_digest,
            decision="PASS",
            created_refs=tuple(created),
            mutation_count=mutations,
            source_oid=plan.source_oid,
            target_oid=plan.target_oid,
            legacy_source_mode="read-only",
            recovery_route="none",
        )
    except Exception as exc:
        partial_state = "bound_partial" if route_health_checked else "process_partial"
        if manifest.get("state") != "receipt_missing":
            manifest["state"] = partial_state if mutations else "claimed"
        manifest["error"] = f"{type(exc).__name__}: apply failed"
        manifest["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        write_transaction_manifest(
            plan.project_root,
            authorization.authorization_id,
            manifest,
            create_only=False,
        )
        decision = "PARTIAL" if mutations else "BLOCKED"
        terminal_envelope = _receipt_envelope(
            plan,
            decision=decision,
            outcomes=outcomes,
            error=f"{type(exc).__name__}: snapshot adoption apply failed",
        )
        if decision == "PARTIAL" and not receipt_attempted:
            try:
                terminal_envelope = write_terminal_receipt(
                    decision="PARTIAL",
                    state=partial_state,
                    error=f"{type(exc).__name__}: snapshot adoption apply failed",
                )
            except Exception:
                manifest["state"] = "receipt_missing"
        receipt = AdoptionReceipt(
            envelope=terminal_envelope,
            authorization_id=authorization.authorization_id,
            plan_digest=plan.plan_digest,
            decision=decision,
            created_refs=tuple(created),
            mutation_count=mutations,
            source_oid=plan.source_oid,
            target_oid=plan.target_oid,
            legacy_source_mode="read-only",
            recovery_route=(
                "meta-flow project recover --project-root . --authorization-id "
                f"{authorization.authorization_id} --action inspect"
            ),
        )
        raise AdoptionApplyError(str(exc), receipt) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project adopt")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-process-root", type=Path, required=True)
    parser.add_argument("--include-ref", action="append", required=True)
    parser.add_argument("--decision-ref", default="decisions/project-adopt-snapshot")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorization", type=Path, default=None)
    parsed = parser.parse_args(argv or [])
    try:
        route = require_project_process_route(parsed.project_root, project_id=parsed.project_id)
    except ProcessRouteError as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    request = SnapshotAdoptionRequest(
        project_id=parsed.project_id,
        source_id=parsed.source_id,
        source_process_root=parsed.source_process_root,
        target_process_root=route.process_root,
        include_refs=tuple(parsed.include_ref),
        project_root=parsed.project_root,
        decision_ref=parsed.decision_ref,
    )
    plan = plan_snapshot_adoption(request)
    if not parsed.apply:
        print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 2 if plan.blocked else 0
    if plan.envelope["decision"] != "NOOP" and parsed.authorization is None:
        print(json.dumps({"plan": plan.as_dict(), "error": "--apply requires --authorization"}, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    try:
        authorization = load_authorization(parsed.authorization) if parsed.authorization else None
        receipt = apply_snapshot_adoption(plan, authorization)
    except (OSError, TypeError, OnboardingContractError, ValueError, AdoptionApplyError) as exc:
        payload: dict[str, Any] = {"plan": plan.as_dict(), "error": str(exc)}
        if isinstance(exc, AdoptionApplyError):
            payload["receipt"] = exc.receipt.as_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if isinstance(exc, AdoptionApplyError) else 2
    print(json.dumps({"plan": plan.as_dict(), "receipt": receipt.as_dict()}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
