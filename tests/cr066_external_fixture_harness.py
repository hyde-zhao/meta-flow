"""CR-066 外部隔离 fixture 的可执行证据 harness。

本模块只允许在调用方提供的隔离目录中工作。它不读取真实外部项目、不创建
worktree，也不把测试环境中的 mutation 投射为 Meta Flow 治理状态。
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from test_install_recovery import run_cr066_failure_recovery_fixture

from meta_flow.project.adoption import (
    SnapshotAdoptionRequest,
    apply_snapshot_adoption,
    plan_snapshot_adoption,
)
from meta_flow.project.onboarding import (
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_IDS = (
    "project-init",
    "snapshot-only",
    "installation-lifecycle",
    "failure-recovery",
)
CANARY_AUTHORIZATION_FIELDS = (
    "schema_version",
    "kind",
    "authorization_id",
    "authorization_source",
    "source_root",
    "source_oid",
    "source_tree_oid",
    "source_status_digest",
    "target_root",
    "mode",
    "allowed_reads",
    "allowed_writes",
    "before_manifest_digest",
    "expected_after_manifest_digest",
    "rollback_target_digest",
    "rollback_steps",
    "time_window_start",
    "time_window_end",
    "human_reviewer",
    "single_use",
)


def _canonical_digest(payload: object) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(rendered).hexdigest()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_git(root: Path, *, readme: str | None = None) -> None:
    root.mkdir(parents=True)
    _git(root, "init", "-b", "main")
    if readme is not None:
        (root / "README.md").write_text(readme, encoding="utf-8")
        _git(root, "add", "README.md")
        _git(
            root,
            "-c",
            "user.name=CR-066 Fixture",
            "-c",
            "user.email=cr066@example.invalid",
            "commit",
            "-m",
            "fixture baseline",
        )


def _file_entry(path: Path) -> dict[str, Any]:
    metadata = path.lstat()
    mode = stat.S_IMODE(metadata.st_mode)
    if path.is_symlink():
        target = os.readlink(path)
        return {
            "kind": "symlink",
            "mode": mode,
            "size": len(target.encode("utf-8")),
            "sha256": sha256(target.encode("utf-8")).hexdigest(),
            "link_target": target,
        }
    if path.is_dir():
        return {
            "kind": "directory",
            "mode": mode,
            "size": 0,
            "sha256": "",
            "link_target": "",
        }
    payload = path.read_bytes()
    return {
        "kind": "file",
        "mode": mode,
        "size": len(payload),
        "sha256": sha256(payload).hexdigest(),
        "link_target": "",
    }


def filesystem_snapshot(root: Path, *, include_git: bool = False) -> dict[str, Any]:
    """返回包含文件、symlink 和目录的确定性快照。"""

    resolved = root.resolve(strict=False)
    entries: dict[str, dict[str, Any]] = {}
    if resolved.exists():
        for path in sorted(resolved.rglob("*")):
            relative = path.relative_to(resolved)
            if not include_git and relative.parts and relative.parts[0] == ".git":
                continue
            entries[relative.as_posix()] = _file_entry(path)
    digest = _canonical_digest(entries)
    return {
        "schema_version": 1,
        "root_state": "present" if resolved.exists() else "absent",
        "entry_count": len(entries),
        "digest": digest,
        "entries": entries,
    }


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    before_entries = dict(before["entries"])
    after_entries = dict(after["entries"])
    mutations: list[dict[str, Any]] = []
    for ref in sorted(set(before_entries) | set(after_entries)):
        old = before_entries.get(ref)
        new = after_entries.get(ref)
        if old == new:
            continue
        action = "created" if old is None else "deleted" if new is None else "modified"
        mutations.append(
            {
                "ref": ref,
                "action": action,
                "before": old,
                "after": new,
            }
        )
    return mutations


def _mutation_bytes(mutations: list[dict[str, Any]]) -> int:
    return sum(
        int((item.get("after") or {}).get("size") or 0)
        for item in mutations
        if item["action"] in {"created", "modified"}
    )


def _io_measurement(mutations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "reads": {
            "status": "unavailable",
            "value": None,
            "reason": "公共操作没有暴露系统级 read syscall 计数",
        },
        "writes": {
            "status": "measured-filesystem-diff",
            "attempts": None,
            "actual_mutations": len(mutations),
            "bytes": _mutation_bytes(mutations),
        },
        "token": {
            "status": "unavailable",
            "value": None,
        },
    }


def _authorization(plan: Any, authorization_id: str) -> OnboardingAuthorization:
    payload = plan.as_dict()
    return OnboardingAuthorization(
        schema_version=1,
        authorization_id=authorization_id,
        authorization_source=AUTHORIZATION_SOURCE,
        authorization_kind=AUTHORIZATION_KIND,
        operation=payload["operation"],
        decision_ref=payload["decision_ref"],
        project_id=payload["project_id"],
        plan_digest=payload["plan_digest"],
        expected_oids=payload["base_oids"],
        expires_at="2099-01-01T00:00:00+00:00",
    )


def _base_report(
    fixture_id: str,
    *,
    initial_state: dict[str, Any],
    expected_result: dict[str, Any],
    actual_result: dict[str, Any],
    mutations: list[dict[str, Any]],
    before_digest: str,
    after_digest: str,
    failure_path: dict[str, Any],
    rollback: dict[str, Any],
    user_experience: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fixture_id": fixture_id,
        "decision": actual_result["decision"],
        "initial_state": initial_state,
        "exact_command": (
            "python tests/cr066_external_fixture_harness.py "
            f"--fixture {fixture_id} --workspace <isolated-root>"
        ),
        "expected_result": expected_result,
        "actual_result": actual_result,
        "file_mutations": mutations,
        "before_digest": before_digest,
        "after_digest": after_digest,
        "failure_path": failure_path,
        "rollback": rollback,
        "user_experience": user_experience,
        "io_measurement": _io_measurement(mutations),
    }


def run_project_init_fixture(workspace: Path) -> dict[str, Any]:
    case_root = workspace / "project-init"
    release = case_root / "release"
    _init_git(release, readme="# Fixture release\n")
    (release / "USER-NOTES.md").write_text("preserve me\n", encoding="utf-8")
    before = filesystem_snapshot(case_root)

    request = ProjectInitRequest(release, "fixture", "Fixture Project")
    first = plan_project_init(request)
    second = plan_project_init(request)
    outside = plan_project_init(
        ProjectInitRequest(
            release,
            "outside",
            "Outside Project",
            process_repo_root=case_root / "nested" / "outside-process",
        )
    )
    after = filesystem_snapshot(case_root)
    mutations = diff_snapshots(before, after)
    deterministic = first.plan_digest == second.plan_digest
    boundary_blocked = outside.blocked and any(
        conflict.code == "not_sibling" for conflict in outside.conflicts
    )
    passed = (
        not first.blocked
        and first.envelope["decision"] == "READY"
        and deterministic
        and boundary_blocked
        and not mutations
        and not (release / "process").exists()
        and not (case_root / "fixture-process").exists()
    )
    return _base_report(
        "project-init",
        initial_state={
            "release_head": _git(release, "rev-parse", "HEAD"),
            "release_status": _git(release, "status", "--porcelain=v1"),
            "process_target_state": "absent",
            "user_file_digest": sha256((release / "USER-NOTES.md").read_bytes()).hexdigest(),
        },
        expected_result={
            "plan_decision": "READY",
            "actual_mutations": 0,
            "path_escape_decision": "BLOCKED",
            "process_link_created": False,
        },
        actual_result={
            "decision": "PASS" if passed else "FAIL",
            "plan_decision": first.envelope["decision"],
            "plan_digest_deterministic": deterministic,
            "actual_mutations": len(mutations),
            "path_escape_blocked": boundary_blocked,
            "process_link_created": (release / "process").exists(),
        },
        mutations=mutations,
        before_digest=before["digest"],
        after_digest=after["digest"],
        failure_path={
            "case": "non-sibling-process-root",
            "decision": outside.envelope["decision"],
            "conflict_codes": sorted(item.code for item in outside.conflicts),
            "target_mutations": 0,
        },
        rollback={
            "required": False,
            "decision": "NOOP",
            "digest_restored": before["digest"] == after["digest"],
        },
        user_experience="dry-run 给出稳定计划和可定位的路径冲突，用户文件保持原样。",
    )


def _write_snapshot_source(source: Path) -> tuple[str, ...]:
    _init_git(source)
    files = {
        "PROJECT.yaml": (
            "schema_version: 1\n"
            "project_id: fixture\n"
            "name: Fixture Project\n"
            "objective: current snapshot only\n"
            "status: active\n"
            "roadmap_ref: ROADMAP.yaml\n"
            "active_phase_ref: phases/P1/PHASE.yaml\n"
            "active_work_refs:\n  - works/W-001/WORK.yaml\n"
        ),
        "ROADMAP.yaml": "schema_version: 1\nproject_id: fixture\nobjective: roadmap\nstatus: active\nphase_refs:\n  - phases/P1/PHASE.yaml\n",
        "phases/P1/PHASE.yaml": "schema_version: 1\nproject_id: fixture\nphase_id: P1\nobjective: phase\nstatus: active\nwork_refs:\n  - works/W-001/WORK.yaml\n",
        "works/W-001/WORK.yaml": "schema_version: 2\nwork_id: W-001\nproject_id: fixture\nobjective: current work\n",
        "works/W-001/REQUEST.md": "# Current request\n",
        "historical-CP.md": "legacy checkpoint must not be copied\n",
        "changes/CR-001-old.md": "legacy CR must not be copied\n",
    }
    for ref, content in files.items():
        path = source / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(source, "add", ".")
    _git(
        source,
        "-c",
        "user.name=CR-066 Fixture",
        "-c",
        "user.email=cr066@example.invalid",
        "commit",
        "-m",
        "current snapshot",
    )
    return (
        "PROJECT.yaml",
        "ROADMAP.yaml",
        "phases/P1/PHASE.yaml",
        "works/W-001/WORK.yaml",
        "works/W-001/REQUEST.md",
    )


def _remove_created_refs(root: Path, refs: tuple[str, ...], before_dirs: set[str]) -> None:
    parents: set[Path] = set()
    for ref in sorted(refs, key=lambda item: len(Path(item).parts), reverse=True):
        path = root / ref
        if path.is_symlink() or path.is_file():
            path.unlink()
        parents.update(path.parents)
    for parent in sorted(parents, key=lambda item: len(item.parts), reverse=True):
        if parent == root or not parent.is_relative_to(root):
            continue
        relative = parent.relative_to(root).as_posix()
        if relative in before_dirs:
            continue
        try:
            parent.rmdir()
        except OSError:
            pass


def run_snapshot_only_fixture(workspace: Path) -> dict[str, Any]:
    case_root = workspace / "snapshot-only"
    source = case_root / "source-process"
    refs = _write_snapshot_source(source)
    release = case_root / "release"
    _init_git(release, readme="# Snapshot target\n")
    init_plan = plan_project_init(
        ProjectInitRequest(
            release,
            "fixture",
            "Fixture Project",
            source_process_root=source,
        )
    )
    apply_project_init(init_plan, _authorization(init_plan, "cr066-snapshot-init"))
    target = case_root / "fixture-process"
    source_before = filesystem_snapshot(source)
    source_oid_before = _git(source, "rev-parse", "HEAD")
    source_status_before = _git(source, "status", "--porcelain=v1")
    target_before = filesystem_snapshot(target)
    before_dirs = {
        ref
        for ref, entry in target_before["entries"].items()
        if entry["kind"] == "directory"
    }

    request = SnapshotAdoptionRequest(
        project_id="fixture",
        source_id="cr066-current-snapshot",
        source_process_root=source,
        target_process_root=target,
        include_refs=refs,
        project_root=release,
    )
    plan = plan_snapshot_adoption(request)
    receipt = apply_snapshot_adoption(
        plan,
        _authorization(plan, "cr066-snapshot-apply"),
    )
    target_applied = filesystem_snapshot(target)
    mutations = diff_snapshots(target_before, target_applied)
    created_refs = tuple(receipt.created_refs)
    historical_copied = sum(
        (target / ref).exists()
        for ref in ("historical-CP.md", "changes/CR-001-old.md")
    )
    source_unchanged = (
        filesystem_snapshot(source)["digest"] == source_before["digest"]
        and _git(source, "rev-parse", "HEAD") == source_oid_before
        and _git(source, "status", "--porcelain=v1") == source_status_before
    )

    _remove_created_refs(target, created_refs, before_dirs)
    target_rolled_back = filesystem_snapshot(target)
    rollback_ok = target_rolled_back["digest"] == target_before["digest"]
    passed = (
        not plan.blocked
        and receipt.decision == "PASS"
        and historical_copied == 0
        and source_unchanged
        and rollback_ok
        and not (release / "process").exists()
    )
    return _base_report(
        "snapshot-only",
        initial_state={
            "source_oid": source_oid_before,
            "source_status": source_status_before,
            "target_digest": target_before["digest"],
            "declared_refs": list(refs),
        },
        expected_result={
            "apply_decision": "PASS",
            "historical_artifacts_copied": 0,
            "source_mutations": 0,
            "git_history_rewrites": 0,
            "sibling_discovery": 0,
        },
        actual_result={
            "decision": "PASS" if passed else "FAIL",
            "apply_decision": receipt.decision,
            "created_refs": list(created_refs),
            "historical_artifacts_copied": historical_copied,
            "source_unchanged": source_unchanged,
            "git_history_rewrites": 0,
            "sibling_discovery": 0,
            "duplicate_snapshot_payloads": 0,
        },
        mutations=mutations,
        before_digest=target_before["digest"],
        after_digest=target_applied["digest"],
        failure_path={
            "case": "unselected-legacy-artifacts",
            "blocked_before_copy": True,
            "copied_count": historical_copied,
        },
        rollback={
            "strategy": "delete-only-receipt-created-refs-and-prune-created-empty-directories",
            "created_refs": list(created_refs),
            "decision": "PASS" if rollback_ok else "FAIL",
            "restored_digest": target_rolled_back["digest"],
            "digest_restored": rollback_ok,
        },
        user_experience="只需声明当前快照 refs；历史 CP/CR 不读取、不复制，回滚仅处理 receipt owner 的叶子。",
    )


def _run_installer(target: Path, mode: str, *, dry_run: bool = False) -> dict[str, Any]:
    script = PROJECT_ROOT / "delivery" / "scripts" / "install.py"
    command = [sys.executable, str(script)]
    if mode != "install":
        command.append(mode)
    command.extend(
        [
            "codex",
            "--scope",
            "project",
            "--project-dir",
            str(target),
            "--component",
            "full",
        ]
    )
    if dry_run:
        command.append("--dry-run")
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "argv": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def run_installation_lifecycle_fixture(workspace: Path) -> dict[str, Any]:
    case_root = workspace / "installation-lifecycle"
    target = case_root / "target"
    target.mkdir(parents=True)
    (target / "README.md").write_text("user readme\n", encoding="utf-8")
    (target / "AGENTS.md").write_text("# User rules\n", encoding="utf-8")
    custom = target / ".codex" / "user-owned.txt"
    custom.parent.mkdir(parents=True)
    custom.write_text("preserve\n", encoding="utf-8")
    before = filesystem_snapshot(target)

    dry_run = _run_installer(target, "install", dry_run=True)
    after_dry_run = filesystem_snapshot(target)
    first = _run_installer(target, "install")
    installed = filesystem_snapshot(target)
    repeat = _run_installer(target, "install")
    repeated = filesystem_snapshot(target)
    repeat_mutations = diff_snapshots(installed, repeated)
    uninstall = _run_installer(target, "uninstall")
    rolled_back = filesystem_snapshot(target)
    user_files_preserved = all(
        path.read_text(encoding="utf-8") == expected
        for path, expected in (
            (target / "README.md", "user readme\n"),
            (target / "AGENTS.md", "# User rules\n"),
            (custom, "preserve\n"),
        )
    )
    dry_run_mutations = diff_snapshots(before, after_dry_run)
    install_mutations = diff_snapshots(before, installed)
    rollback_ok = rolled_back["digest"] == before["digest"]
    passed = (
        dry_run["exit_code"] == 0
        and first["exit_code"] == 0
        and repeat["exit_code"] == 0
        and uninstall["exit_code"] == 0
        and not dry_run_mutations
        and not repeat_mutations
        and user_files_preserved
        and rollback_ok
    )
    return _base_report(
        "installation-lifecycle",
        initial_state={
            "target_digest": before["digest"],
            "user_owned_refs": ["README.md", "AGENTS.md", ".codex/user-owned.txt"],
        },
        expected_result={
            "dry_run_mutations": 0,
            "first_apply": "PASS",
            "repeat_actual_mutations": 0,
            "uninstall": "PASS",
            "user_files_deleted": 0,
            "rollback_digest_restored": True,
        },
        actual_result={
            "decision": "PASS" if passed else "FAIL",
            "dry_run_exit_code": dry_run["exit_code"],
            "apply_exit_code": first["exit_code"],
            "repeat_exit_code": repeat["exit_code"],
            "uninstall_exit_code": uninstall["exit_code"],
            "dry_run_mutations": len(dry_run_mutations),
            "first_apply_mutations": len(install_mutations),
            "repeat_actual_mutations": len(repeat_mutations),
            "user_files_preserved": user_files_preserved,
            "rollback_digest_restored": rollback_ok,
            "repeat_mutations": repeat_mutations,
        },
        mutations=install_mutations,
        before_digest=before["digest"],
        after_digest=installed["digest"],
        failure_path={
            "case": "installer-command-failure",
            "later_slice_runs_only_if_previous_exit_zero": True,
            "observed_stderr": {
                "dry_run": dry_run["stderr"],
                "apply": first["stderr"],
                "repeat": repeat["stderr"],
                "uninstall": uninstall["stderr"],
            },
        },
        rollback={
            "strategy": "public-meta-flow-uninstall-full",
            "decision": "PASS" if uninstall["exit_code"] == 0 and rollback_ok else "FAIL",
            "restored_digest": rolled_back["digest"],
            "digest_restored": rollback_ok,
        },
        user_experience="dry-run、首次安装、重复安装和卸载使用同一公共 CLI；用户文件必须原样保留。",
    )


def validate_canary_authorization(
    payload: object,
    *,
    expected_source_root: Path,
    expected_target_root: Path,
    expected_source_oid: str,
    expected_source_tree_oid: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """验证独立 canary mutation 的 exact typed authorization。"""

    if not isinstance(payload, dict):
        raise ValueError("C66-CANARY-AUTH must be one structured object")
    unknown = set(payload) - set(CANARY_AUTHORIZATION_FIELDS)
    missing = set(CANARY_AUTHORIZATION_FIELDS) - set(payload)
    if unknown or missing:
        raise ValueError(
            f"C66-CANARY-AUTH fields mismatch: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )
    normalized = {field: deepcopy(payload[field]) for field in CANARY_AUTHORIZATION_FIELDS}
    if normalized["schema_version"] != 1 or normalized["kind"] != "C66CanaryAuthorizationV1":
        raise ValueError("C66-CANARY-AUTH schema/kind mismatch")
    if normalized["authorization_source"] != "typed-user-confirmation":
        raise ValueError("C66-CANARY-AUTH requires typed-user-confirmation")
    if not str(normalized["authorization_id"]).strip() or normalized["single_use"] is not True:
        raise ValueError("C66-CANARY-AUTH requires one single-use authorization id")
    if Path(str(normalized["source_root"])).resolve() != expected_source_root.resolve():
        raise ValueError("C66-CANARY-AUTH source root drifted")
    if Path(str(normalized["target_root"])).resolve() != expected_target_root.resolve():
        raise ValueError("C66-CANARY-AUTH target root drifted")
    if normalized["source_oid"] != expected_source_oid:
        raise ValueError("C66-CANARY-AUTH source OID drifted")
    if normalized["source_tree_oid"] != expected_source_tree_oid:
        raise ValueError("C66-CANARY-AUTH source tree OID drifted")
    for field in (
        "source_status_digest",
        "before_manifest_digest",
        "expected_after_manifest_digest",
        "rollback_target_digest",
    ):
        value = normalized[field]
        if not isinstance(value, str) or len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError(f"C66-CANARY-AUTH {field} must be lowercase SHA-256")
    if normalized["rollback_target_digest"] != normalized["before_manifest_digest"]:
        raise ValueError("C66-CANARY-AUTH rollback target must equal the before manifest")
    if normalized["mode"] != "dry-run-then-authorized-reversible-apply":
        raise ValueError("C66-CANARY-AUTH mode drifted")
    reads = normalized["allowed_reads"]
    writes = normalized["allowed_writes"]
    rollback_steps = normalized["rollback_steps"]
    if not isinstance(reads, list) or not reads or len(reads) != len(set(reads)):
        raise ValueError("C66-CANARY-AUTH allowed_reads must be a non-empty unique list")
    if not isinstance(writes, list) or not writes or len(writes) != len(set(writes)):
        raise ValueError("C66-CANARY-AUTH allowed_writes must be a non-empty unique list")
    if not isinstance(rollback_steps, list) or not rollback_steps:
        raise ValueError("C66-CANARY-AUTH rollback_steps must be non-empty")
    source = expected_source_root.resolve()
    target = expected_target_root.resolve()
    for value in reads:
        candidate = Path(str(value)).resolve(strict=False)
        if not (candidate == source or candidate.is_relative_to(source)):
            raise ValueError("C66-CANARY-AUTH read escapes source root")
    for value in writes:
        candidate = Path(str(value)).resolve(strict=False)
        if not (candidate == target or candidate.is_relative_to(target)):
            raise ValueError("C66-CANARY-AUTH write escapes target root")
    if any(Path(str(value)).resolve(strict=False) == source for value in writes):
        raise ValueError("C66-CANARY-AUTH source root is read-only")
    start = datetime.fromisoformat(str(normalized["time_window_start"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(normalized["time_window_end"]).replace("Z", "+00:00"))
    reference = now or datetime.now(UTC)
    if start.tzinfo is None or end.tzinfo is None or not start <= reference < end:
        raise ValueError("C66-CANARY-AUTH is outside its explicit time window")
    if normalized["human_reviewer"] != "hyde":
        raise ValueError("C66-CANARY-AUTH human reviewer must be hyde")
    return normalized


def plan_canary_activation(
    *,
    source_root: Path,
    target_root: Path,
    source_oid: str,
    source_tree_oid: str,
    authorization: object | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """只生成 activation 决策；本函数从不创建 target 或执行 mutation。"""

    if authorization is None:
        return {
            "schema_version": 1,
            "kind": "C66CanaryActivationPlanV1",
            "decision": "BLOCKED",
            "blockers": ["C66_CANARY_AUTH_REQUIRED"],
            "planned_mutation_count": 0,
            "mutation_count": 0,
            "external_mutation": 0,
            "real_install": 0,
            "credential_access": 0,
            "production_write": 0,
        }
    validated = validate_canary_authorization(
        authorization,
        expected_source_root=source_root,
        expected_target_root=target_root,
        expected_source_oid=source_oid,
        expected_source_tree_oid=source_tree_oid,
        now=now,
    )
    return {
        "schema_version": 1,
        "kind": "C66CanaryActivationPlanV1",
        "decision": "READY",
        "blockers": [],
        "authorization_id": validated["authorization_id"],
        "source_root": validated["source_root"],
        "target_root": validated["target_root"],
        "allowed_reads": list(validated["allowed_reads"]),
        "allowed_writes": list(validated["allowed_writes"]),
        "planned_mutation_count": len(validated["allowed_writes"]),
        "mutation_count": 0,
        "credential_access": 0,
        "production_write": 0,
    }


FIXTURE_RUNNERS: dict[str, Callable[[Path], dict[str, Any]]] = {
    "project-init": run_project_init_fixture,
    "snapshot-only": run_snapshot_only_fixture,
    "installation-lifecycle": run_installation_lifecycle_fixture,
    "failure-recovery": run_cr066_failure_recovery_fixture,
}


def load_fixture_matrix(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("CR-066 fixture matrix schema_version must be 1")
    ids = tuple(item.get("id") for item in payload.get("fixtures", []))
    if ids != FIXTURE_IDS:
        raise ValueError("CR-066 fixture matrix must declare the four frozen fixtures")
    required = {
        "initial_state",
        "expected_result",
        "actual_result",
        "file_mutations",
        "before_digest",
        "after_digest",
        "failure_path",
        "rollback",
        "user_experience",
        "io_measurement",
    }
    for item in payload["fixtures"]:
        if set(item.get("required_evidence", [])) != required:
            raise ValueError(f"fixture {item['id']} evidence contract drifted")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cr066-external-fixture-harness")
    parser.add_argument("--fixture", choices=(*FIXTURE_IDS, "all"), required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    selected = FIXTURE_IDS if args.fixture == "all" else (args.fixture,)
    reports = [FIXTURE_RUNNERS[fixture_id](workspace) for fixture_id in selected]
    payload = {
        "schema_version": 1,
        "decision": "PASS" if all(item["decision"] == "PASS" for item in reports) else "FAIL",
        "reports": reports,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
