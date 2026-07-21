"""单项目 snapshot-only 过程仓接入计划与受权 apply。"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any

from meta_flow.project.model import is_safe_ref, load_project
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.workspace.git_sync import run_git

if TYPE_CHECKING:
    from meta_flow.workspace.legacy_route_adapter import _LegacyRouteAuthorization

ADOPTION_SCHEMA_VERSION = 1
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
    source_root: Path
    target_root: Path
    source_oid: str
    target_oid: str
    entries: tuple[SnapshotEntry, ...]
    index_payload: dict[str, Any]
    actions: tuple[AdoptionAction, ...]
    conflicts: tuple[AdoptionConflict, ...]
    plan_digest: str

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ADOPTION_SCHEMA_VERSION,
            "decision": "BLOCKED" if self.blocked else "READY",
            "project_id": self.request.project_id,
            "source_id": self.request.source_id,
            "source_root": str(self.source_root),
            "target_root": str(self.target_root),
            "source_oid": self.source_oid,
            "target_oid": self.target_oid,
            "entries": [entry.as_dict() for entry in self.entries],
            "actions": [action.__dict__ for action in self.actions],
            "conflicts": [conflict.__dict__ for conflict in self.conflicts],
            "plan_digest": self.plan_digest,
            "mutation_count": 0,
            "legacy_source_mode": "read-only",
        }


@dataclass(frozen=True)
class AdoptionAuthorization:
    authorization_id: str
    authorization_kind: str
    project_id: str
    plan_digest: str
    source_oid: str
    target_oid: str
    decision_ref: str
    expires_at: str
    single_use: bool = True


@dataclass(frozen=True)
class AdoptionReceipt:
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
        return self.__dict__.copy()


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
    parts = Path(ref).parts
    if ref in {"PROJECT.yaml", "ROADMAP.yaml"}:
        return True
    if len(parts) == 3 and parts[0] == "phases" and _ID_RE.fullmatch(parts[1]) and parts[2] == "PHASE.yaml":
        return True
    if len(parts) == 3 and parts[0] == "works" and _ID_RE.fullmatch(parts[1]) and parts[2] in _WORK_FILES:
        return True
    return bool(
        len(parts) == 4
        and parts[0] == "works"
        and _ID_RE.fullmatch(parts[1])
        and parts[2] == "receipts"
        and parts[3].endswith(".json")
        and _ID_RE.fullmatch(parts[3][:-5])
    )


def _entry_for(root: Path, ref: str) -> SnapshotEntry:
    path = root / ref
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    if path.is_symlink():
        link_text = os.readlink(path)
        link_path = Path(link_text)
        if link_path.is_absolute() or ".." in link_path.parts:
            raise ValueError(f"snapshot symlink is absolute or escaping: {ref}")
        digest = sha256(link_text.encode("utf-8")).hexdigest()
        return SnapshotEntry(ref, "symlink", digest, mode, link_text)
    if not path.is_file():
        raise ValueError(f"snapshot ref is not a regular file or symlink: {ref}")
    return SnapshotEntry(ref, "file", sha256(path.read_bytes()).hexdigest(), mode)


def _target_matches(root: Path, entry: SnapshotEntry) -> bool:
    path = root / entry.ref
    if entry.kind == "symlink":
        return path.is_symlink() and os.readlink(path) == entry.link_text
    return path.is_file() and not path.is_symlink() and sha256(path.read_bytes()).hexdigest() == entry.sha256


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def plan_snapshot_adoption(request: SnapshotAdoptionRequest) -> SnapshotAdoptionPlan:
    source = request.source_process_root.resolve()
    target = request.target_process_root.resolve()
    conflicts: list[AdoptionConflict] = []
    actions: list[AdoptionAction] = []
    entries: list[SnapshotEntry] = []
    if not _ID_RE.fullmatch(request.project_id):
        conflicts.append(AdoptionConflict("project_id", "project_id", "project_id is invalid"))
    if not _ID_RE.fullmatch(request.source_id):
        conflicts.append(AdoptionConflict("source_id", "source_id", "source_id is invalid"))
    if source == target:
        conflicts.append(AdoptionConflict("same_repo", "", "source and target process roots must differ"))
    source_git, source_oid, source_common = _git_root_and_oid(source)
    target_git, target_oid, target_common = _git_root_and_oid(target)
    if source_git != source:
        conflicts.append(AdoptionConflict("source_not_git_root", str(source), "source must be one Git repository root"))
    if target_git != target:
        conflicts.append(AdoptionConflict("target_not_git_root", str(target), "target must be one Git repository root"))
    if source_common is not None and source_common == target_common:
        conflicts.append(AdoptionConflict("shared_git_control", "", "source and target share Git common dir"))
    if not request.include_refs or "PROJECT.yaml" not in request.include_refs:
        conflicts.append(AdoptionConflict("project_missing", "PROJECT.yaml", "snapshot must explicitly include PROJECT.yaml"))
    if len(set(request.include_refs)) != len(request.include_refs):
        conflicts.append(AdoptionConflict("duplicate_ref", "", "include_refs contains duplicates"))

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
        target_path = target / ref
        if target_path.exists() or target_path.is_symlink():
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
            actions.append(AdoptionAction("noop", ADOPTION_INDEX_REL.as_posix(), "matching legacy index already exists"))
        else:
            conflicts.append(AdoptionConflict("index_conflict", ADOPTION_INDEX_REL.as_posix(), "legacy index differs"))
    else:
        actions.append(AdoptionAction("create", ADOPTION_INDEX_REL.as_posix(), "write read-only legacy source index"))

    digest_source = {
        "schema_version": ADOPTION_SCHEMA_VERSION,
        "project_id": request.project_id,
        "source_id": request.source_id,
        "source_root": str(source),
        "target_root": str(target),
        "source_oid": source_oid,
        "target_oid": target_oid,
        "entries": [entry.as_dict() for entry in entries],
        "index": index_payload,
        "actions": [action.__dict__ for action in actions],
        "conflicts": [conflict.__dict__ for conflict in conflicts],
    }
    return SnapshotAdoptionPlan(
        request=request,
        source_root=source,
        target_root=target,
        source_oid=source_oid,
        target_oid=target_oid,
        entries=tuple(entries),
        index_payload=index_payload,
        actions=tuple(actions),
        conflicts=tuple(conflicts),
        plan_digest=_digest(digest_source),
    )


def _validate_authorization(plan: SnapshotAdoptionPlan, authorization: AdoptionAuthorization) -> None:
    if not _ID_RE.fullmatch(authorization.authorization_id):
        raise ValueError("authorization_id is invalid")
    if authorization.authorization_kind not in {"local-fixture", "single-project-migration"}:
        raise ValueError("authorization_kind is invalid")
    if not authorization.single_use:
        raise ValueError("adoption authorization must be single-use")
    expected = (
        plan.request.project_id,
        plan.plan_digest,
        plan.source_oid,
        plan.target_oid,
    )
    actual = (
        authorization.project_id,
        authorization.plan_digest,
        authorization.source_oid,
        authorization.target_oid,
    )
    if actual != expected:
        raise ValueError("authorization does not match project/plan/source/target OIDs")
    try:
        expiry = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("authorization expires_at is invalid") from exc
    if expiry.tzinfo is None:
        raise ValueError("authorization expires_at must include timezone")
    if expiry.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError("adoption authorization is expired")


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
        raise RuntimeError(f"post-copy hash/link verification failed: {entry.ref}")


def apply_snapshot_adoption(
    plan: SnapshotAdoptionPlan,
    authorization: AdoptionAuthorization,
    *,
    capability: _LegacyRouteAuthorization,
) -> AdoptionReceipt:
    if plan.blocked:
        raise ValueError("snapshot adoption plan is blocked")
    _validate_authorization(plan, authorization)
    from meta_flow.workspace.legacy_route_adapter import (
        capability_for_adoption,
        claim_legacy_authorization,
    )

    expected_capability = capability_for_adoption(authorization)
    if capability != expected_capability:
        raise ValueError("adoption capability does not match AdoptionAuthorization")
    claim = claim_legacy_authorization(
        capability,
        command="project adopt",
        project_root=plan.target_root,
        project_id=plan.request.project_id,
        operation_digest_value=plan.plan_digest,
        expected_oids={"source": plan.source_oid, "target": plan.target_oid},
        claim_repo_root=plan.target_root,
        reject_binding=False,
    )
    fresh = plan_snapshot_adoption(plan.request)
    if fresh.plan_digest != plan.plan_digest:
        claim.finish("BLOCKED")
        raise ValueError("snapshot adoption plan is stale; rebuild plan and authorization")
    created: list[str] = []
    mutations = 0
    try:
        for entry in plan.entries:
            if not _target_matches(plan.target_root, entry):
                _copy_entry_create_only(plan.source_root, plan.target_root, entry)
                created.append(entry.ref)
                mutations += 1
        index_path = plan.target_root / ADOPTION_INDEX_REL
        if not index_path.exists() and not index_path.is_symlink():
            index_path.parent.mkdir(parents=True, exist_ok=True)
            with index_path.open("x", encoding="utf-8") as stream:
                stream.write(dump_yaml(plan.index_payload) + "\n")
            created.append(ADOPTION_INDEX_REL.as_posix())
            mutations += 1
        receipt = AdoptionReceipt(
            authorization_id=authorization.authorization_id,
            plan_digest=plan.plan_digest,
            decision="PASS",
            created_refs=tuple(created),
            mutation_count=mutations + 1,
            source_oid=plan.source_oid,
            target_oid=plan.target_oid,
            legacy_source_mode="read-only",
            recovery_route="none",
        )
        receipt_path = plan.target_root / ADOPTION_RECEIPT_DIR / f"{authorization.authorization_id}.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        with receipt_path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        claim.finish("PASS", mutation_count=receipt.mutation_count)
        return receipt
    except BaseException as exc:
        receipt = AdoptionReceipt(
            authorization_id=authorization.authorization_id,
            plan_digest=plan.plan_digest,
            decision="PARTIAL" if mutations else "BLOCKED",
            created_refs=tuple(created),
            mutation_count=mutations,
            source_oid=plan.source_oid,
            target_oid=plan.target_oid,
            legacy_source_mode="read-only",
            recovery_route="reobserve-and-build-new-plan-for-missing-entries",
        )
        claim.finish("PARTIAL" if mutations else "BLOCKED", mutation_count=mutations)
        if isinstance(exc, Exception):
            raise AdoptionApplyError(str(exc), receipt) from exc
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project adopt")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-process-root", type=Path, required=True)
    parser.add_argument("--target-process-root", type=Path, required=True)
    parser.add_argument("--include-ref", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorization", type=Path, default=None)
    parsed = parser.parse_args(argv or [])
    request = SnapshotAdoptionRequest(
        project_id=parsed.project_id,
        source_id=parsed.source_id,
        source_process_root=parsed.source_process_root,
        target_process_root=parsed.target_process_root,
        include_refs=tuple(parsed.include_ref),
    )
    plan = plan_snapshot_adoption(request)
    if not parsed.apply:
        print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if plan.blocked else 0
    if parsed.authorization is None:
        print(
            json.dumps(
                {"plan": plan.as_dict(), "error": "--apply requires --authorization"},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    try:
        raw = json.loads(parsed.authorization.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("authorization must be one JSON object")
        authorization = AdoptionAuthorization(**raw)
        from meta_flow.workspace.legacy_route_adapter import capability_for_adoption

        receipt = apply_snapshot_adoption(
            plan,
            authorization,
            capability=capability_for_adoption(authorization),
        )
    except (OSError, TypeError, ValueError, AdoptionApplyError) as exc:
        payload: dict[str, Any] = {"plan": plan.as_dict(), "error": str(exc)}
        if isinstance(exc, AdoptionApplyError):
            payload["receipt"] = exc.receipt.as_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    print(
        json.dumps(
            {"plan": plan.as_dict(), "receipt": receipt.as_dict()},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0
