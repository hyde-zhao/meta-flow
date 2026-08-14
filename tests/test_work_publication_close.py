from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import pytest

from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.project.governance import (
    Phase,
    Roadmap,
    write_phase_create_only,
    write_roadmap_create_only,
)
from meta_flow.project.governance_projection import (
    GOVERNANCE_PROJECTION_REL,
    ImmutableCommitRole,
    build_governance_projection,
    validate_governance_projection,
)
from meta_flow.project.model import load_project, replace_project
from meta_flow.project.onboarding import (
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND as PROJECT_AUTHORIZATION_KIND,
)
from meta_flow.project.onboarding_contract import AUTHORIZATION_SOURCE, OnboardingAuthorization
from meta_flow.project.scale import dump_yaml
from meta_flow.repository.publisher import observe_repo
from meta_flow.state import current as state_current
from meta_flow.work.cli import publication_close_main
from meta_flow.work.handoff import build_handoff, write_handoff
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.lifecycle_transaction import (
    AUTHORIZATION_KIND,
    WorkCloseAuthorizationV1,
    apply_work_close,
    inspect_work_close_transactions,
    plan_work_close,
)
from meta_flow.work.model import build_work, load_work, with_status, write_work_create_only
from meta_flow.work.publication_close import (
    PUBLICATION_AUTHORIZATION_KIND,
    WorkPublicationCloseAuthorizationV1,
    apply_work_publication_close,
    plan_work_publication_close,
    publication_candidate_set_digest,
)
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _init_project(root: Path) -> tuple[Path, Path]:
    release = root / "demo"
    release.mkdir()
    _git(release, "init", "-b", "main")
    (release / "README.md").write_text("# Demo\n", encoding="utf-8")
    (release / ".gitignore").write_text(".meta-flow-runtime/\n", encoding="utf-8")
    _git(release, "add", "README.md", ".gitignore")
    _git(
        release,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial",
    )
    plan = plan_project_init(ProjectInitRequest(release, "demo", "Demo"))
    payload = plan.as_dict()
    apply_project_init(
        plan,
        OnboardingAuthorization(
            1,
            "publication-close-fixture",
            AUTHORIZATION_SOURCE,
            PROJECT_AUTHORIZATION_KIND,
            payload["operation"],
            payload["decision_ref"],
            payload["project_id"],
            payload["plan_digest"],
            payload["base_oids"],
            "2099-01-01T00:00:00+00:00",
        ),
    )
    _git(release, "add", ".meta-flow/workspace.yaml")
    _git(
        release,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "bind process repository",
    )
    process = root / "demo-process"
    (process / ".gitignore").write_text(".meta-flow-runtime/\n", encoding="utf-8")
    _git(process, "add", ".")
    _git(
        process,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial process",
    )
    remotes = root / "remotes"
    remotes.mkdir()
    for role, repository in (("release", release), ("process", process)):
        remote = remotes / f"{role}.git"
        _git(remotes, "init", "--bare", remote.name)
        _git(repository, "remote", "add", "origin", str(remote))
        _git(repository, "push", "-u", "origin", "main")
    return release, process


def _changed_paths(root: Path, before_oid: str, after_oid: str) -> list[str]:
    output = subprocess.run(
        ["git", "diff", "--name-only", "-z", f"{before_oid}..{after_oid}", "--"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    return sorted(item for item in output.split("\0") if item)


def _publication_fixture(
    tmp_path: Path, *, governed: bool = False
) -> tuple[Path, Path, str, str]:
    release, process = _init_project(tmp_path)
    release_oid = _git(release, "rev-parse", "HEAD")
    process_oid = _git(process, "rev-parse", "HEAD")
    phase_ref = ""
    if governed:
        phase = Phase(
            1,
            "demo",
            "P1",
            "验证 publication-close 原子投影",
            "active",
            result_refs=(GOVERNANCE_PROJECTION_REL.as_posix(),),
        )
        write_phase_create_only(process, phase)
        write_roadmap_create_only(
            process,
            Roadmap(1, "demo", "完成 publication-close 验证", "active", (phase.phase_ref,)),
        )
        project = load_project(process)
        replace_project(
            process,
            replace(
                project,
                roadmap_ref="ROADMAP.yaml",
                active_phase_ref=phase.phase_ref,
            ),
            expected_project_id=project.project_id,
        )
        roles = (
            ImmutableCommitRole("release_input", "release", release_oid),
            ImmutableCommitRole("process_input", "process", process_oid),
        )
        projection = build_governance_projection(process, roles)
        projection_path = process / GOVERNANCE_PROJECTION_REL
        projection_path.parent.mkdir(parents=True, exist_ok=True)
        projection_path.write_text(
            json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        phase_ref = phase.phase_ref
    work_id = "W-PUBLISH"
    request_ref = f"works/{work_id}/REQUEST.md"
    request_path = process / request_ref
    request_path.parent.mkdir(parents=True)
    request_path.write_text("# 发布后关闭\n", encoding="utf-8")
    work = build_work(
        work_id=work_id,
        project_id="demo",
        objective="发布验证证据后原生关闭",
        request_ref=request_ref,
        scope=WorkScope(
            version=1,
            allowed_reads=(request_ref, f"process/works/{work_id}/**"),
            allowed_writes=(
                ("process/**",)
                if governed
                else (f"process/works/{work_id}/**", "process/PROJECT.yaml")
            ),
            required_checks=("targeted",),
        ),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid=release_oid,
        process_base_oid=process_oid,
        phase_ref=phase_ref,
        execution_unit=ExecutionUnitV1(
            unit_id=work_id,
            root_concept="publication-close",
            slice_id=work_id,
            container_role="primary",
            revision=1,
            supersedes_unit_id="",
            contract_ref=request_ref,
            contract_digest="c" * 64,
        ),
    )
    apply_work_init(plan_work_init_from_release_root(release, work))
    update_work_status(process, work_id, expected_status="planned", new_status="active")
    if governed:
        (process / "changes").mkdir(exist_ok=True)
        state_current.init_current_state(release, project_id="demo")
        state_current.render_state_file(release, force=True)
        state_current.refresh_current_entry(release)
        state_current.refresh_formal_truth_projection(release)
    result_ref = f"works/{work_id}/RESULT.json"
    (process / result_ref).write_text(
        json.dumps({"schema_version": 1, "work_id": work_id, "decision": "PASS"})
        + "\n",
        encoding="utf-8",
    )
    (process / f"works/{work_id}/USAGE.json").write_text(
        json.dumps({"schema_version": 1, "events": []}) + "\n",
        encoding="utf-8",
    )
    paused = update_work_status(
        process,
        work_id,
        expected_status="active",
        new_status="paused",
    )
    write_handoff(
        process,
        build_handoff(
            paused,
            release_oid=release_oid,
            process_oid=process_oid,
            completed=("验证与发布完成",),
            remaining=("原生关闭 Work",),
            blockers=("publication OID drift",),
            next_step="使用 publication-close typed authorization",
            evidence_refs=(result_ref,),
        ),
    )
    _git(process, "add", ".")
    _git(
        process,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "publish Work evidence",
    )
    published_process_oid = _git(process, "rev-parse", "HEAD")
    _git(process, "push", "origin", "main")
    receipt_ref = f"works/{work_id}/PUBLICATION-RECEIPT.json"
    receipt = {
        "schema_version": 1,
        "kind": "WorkPublicationReceiptV1",
        "decision": "PASS",
        "project_id": "demo",
        "work_id": work_id,
        "scope_digest": paused.scope.digest,
        "result_ref": f"process/{result_ref}",
        "repositories": {
            "release": {
                "paused_oid": release_oid,
                "published_oid": release_oid,
                "remote": "origin",
                "ref": "refs/heads/main",
                "changed_paths": [],
                "pending_paths": [],
                "commit_authorization_ids": [],
                "push_authorization_ids": [],
            },
            "process": {
                "paused_oid": process_oid,
                "published_oid": published_process_oid,
                "remote": "origin",
                "ref": "refs/heads/main",
                "changed_paths": _changed_paths(process, process_oid, published_process_oid),
                "pending_paths": [receipt_ref],
                "commit_authorization_ids": ["AUTH-PROCESS-COMMIT"],
                "push_authorization_ids": ["AUTH-PROCESS-PUSH"],
            },
        },
    }
    (process / receipt_ref).write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return release, process, result_ref, receipt_ref


def _authorization(plan, authorization_id: str) -> WorkPublicationCloseAuthorizationV1:
    binding = plan.publication_binding
    assert binding is not None
    return WorkPublicationCloseAuthorizationV1.from_mapping(
        {
            "schema_version": 1,
            "kind": PUBLICATION_AUTHORIZATION_KIND,
            "authorization_id": authorization_id,
            "work_id": plan.work_id,
            "plan_digest": plan.plan_digest,
            "target_refs": [target.ref for target in plan.targets],
            "scope_digest": binding.scope_digest,
            "result_ref": binding.result_ref,
            "handoff_ref": binding.handoff_ref,
            "handoff_digest": binding.handoff_digest,
            "publication_receipt_ref": binding.publication_receipt_ref,
            "publication_receipt_digest": binding.publication_receipt_digest,
            "repository_facts_digest": binding.repository_facts_digest,
            "paused_oids": dict(binding.paused_oids),
            "published_oids": dict(binding.published_oids),
            "expires_at": "2099-01-01T00:00:00+00:00",
            "single_use": True,
        }
    )


def _plan(release: Path, result_ref: str, receipt_ref: str):
    return plan_work_publication_close(
        release,
        "W-PUBLISH",
        result_ref=f"process/{result_ref}",
        publication_receipt_ref=f"process/{receipt_ref}",
    )


def _candidate_coverage(
    repository: dict[str, object],
    *,
    role: str,
    paths: list[str],
) -> dict[str, object]:
    commit_ids = list(repository["commit_authorization_ids"])
    push_ids = list(repository["push_authorization_ids"])
    return {
        "coverage_type": "typed_candidate_set_authorization",
        "paths": paths,
        "candidate_set_digest": publication_candidate_set_digest(
            role=role,
            paused_oid=str(repository["paused_oid"]),
            published_oid=str(repository["published_oid"]),
            paths=paths,
            commit_authorization_ids=commit_ids,
            push_authorization_ids=push_ids,
        ),
        "commit_authorization_ids": commit_ids,
        "push_authorization_ids": push_ids,
    }


def _upgrade_receipt_v2(
    process: Path,
    receipt_ref: str,
    *,
    recovery_work: dict[str, str] | None = None,
    process_coverage: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    receipt_path = process / receipt_ref
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    payload["kind"] = "WorkPublicationReceiptV2"
    payload["recovery_work"] = recovery_work
    for role in ("release", "process"):
        repository = payload["repositories"][role]
        changed_paths = list(repository["changed_paths"])
        if role == "process" and process_coverage is not None:
            coverage = process_coverage
        elif changed_paths:
            coverage = [_candidate_coverage(repository, role=role, paths=changed_paths)]
        else:
            coverage = []
        repository["path_coverage"] = sorted(
            coverage,
            key=lambda item: (item["paths"][0], item["coverage_type"]),
        )
    receipt_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _publish_batch_to_exact_path_count(
    process: Path,
    receipt_ref: str,
    *,
    path_count: int,
) -> dict[str, object]:
    receipt_path = process / receipt_ref
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    repository = payload["repositories"]["process"]
    current_count = len(repository["changed_paths"])
    assert current_count < path_count
    batch_root = process / "batch-publication"
    batch_root.mkdir()
    for index in range(path_count - current_count):
        (batch_root / f"artifact-{index:03d}.json").write_text(
            json.dumps({"index": index}) + "\n", encoding="utf-8"
        )
    _git(process, "add", "batch-publication")
    _git(
        process,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "publish accumulated batch",
    )
    published_oid = _git(process, "rev-parse", "HEAD")
    _git(process, "push", "origin", "main")
    repository["published_oid"] = published_oid
    repository["changed_paths"] = _changed_paths(
        process, repository["paused_oid"], published_oid
    )
    receipt_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert len(repository["changed_paths"]) == path_count
    return _upgrade_receipt_v2(process, receipt_ref)


def _add_prior_work_publication(
    release: Path,
    process: Path,
    receipt_ref: str,
    *,
    status: str = "completed",
    result_decision: str = "PASS",
    allow_shared_path: bool = True,
) -> dict[str, object]:
    work_id = "W-PRIOR"
    request_ref = f"works/{work_id}/REQUEST.md"
    work = build_work(
        work_id=work_id,
        project_id="demo",
        objective="提供批量发布中的前序路径归属",
        request_ref=request_ref,
        scope=WorkScope(
            version=1,
            allowed_reads=(request_ref,),
            allowed_writes=(
                f"process/works/{work_id}/**",
                *(('process/changes/CR-INDEX.json',) if allow_shared_path else ()),
            ),
            required_checks=("targeted",),
        ),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid=_git(release, "rev-parse", "HEAD"),
        process_base_oid=_git(process, "rev-parse", "HEAD"),
    )
    result_ref = f"works/{work_id}/RESULT.json"
    write_work_create_only(process, work)
    owner_dir = process / "works" / work_id
    (owner_dir / "REQUEST.md").write_text("# prior Work\n", encoding="utf-8")
    (owner_dir / "USAGE.json").write_text(
        json.dumps({"schema_version": 1, "events": []}) + "\n", encoding="utf-8"
    )
    (owner_dir / "RESULT.json").write_text(
        json.dumps(
            {"schema_version": 1, "work_id": work_id, "decision": result_decision}
        )
        + "\n",
        encoding="utf-8",
    )
    updated = with_status(work, status, result_ref=result_ref if status == "completed" else "")
    (owner_dir / "WORK.yaml").write_text(
        dump_yaml(updated.as_dict()) + "\n", encoding="utf-8"
    )
    changes = process / "changes"
    changes.mkdir(exist_ok=True)
    (changes / "CR-INDEX.json").write_text("{}\n", encoding="utf-8")
    _git(process, "add", f"works/{work_id}", "changes/CR-INDEX.json")
    _git(
        process,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "publish prior Work artifacts",
    )
    published_oid = _git(process, "rev-parse", "HEAD")
    _git(process, "push", "origin", "main")
    receipt_path = process / receipt_ref
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    repository = payload["repositories"]["process"]
    previous_paths = set(repository["changed_paths"])
    repository["published_oid"] = published_oid
    repository["changed_paths"] = _changed_paths(
        process, repository["paused_oid"], published_oid
    )
    receipt_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    prior_paths = sorted(set(repository["changed_paths"]) - previous_paths)
    candidate_paths = sorted(previous_paths)
    coverage: list[dict[str, object]] = [
        {
            "coverage_type": "prior_work",
            "paths": prior_paths,
            "owner_work_ref": f"process/works/{work_id}/WORK.yaml",
            "owner_scope_digest": updated.scope.digest,
            "owner_result_ref": f"process/{result_ref}",
            "owner_terminal_status": "completed",
        }
    ]
    if candidate_paths:
        coverage.append(
            _candidate_coverage(repository, role="process", paths=candidate_paths)
        )
    return _upgrade_receipt_v2(
        process,
        receipt_ref,
        process_coverage=coverage,
    )


def _add_recovery_work_pending_paths(
    release: Path,
    process: Path,
    receipt_ref: str,
) -> tuple[dict[str, object], str]:
    work_id = "W-RECOVERY"
    request_ref = f"works/{work_id}/REQUEST.md"
    work = build_work(
        work_id=work_id,
        project_id="demo",
        objective="恢复 publication-close",
        request_ref=request_ref,
        scope=WorkScope(
            version=1,
            allowed_reads=(request_ref,),
            allowed_writes=(f"process/works/{work_id}/**",),
            required_checks=("targeted",),
        ),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid=_git(release, "rev-parse", "HEAD"),
        process_base_oid=_git(process, "rev-parse", "HEAD"),
    )
    active = with_status(work, "active")
    write_work_create_only(process, active)
    recovery_dir = process / "works" / work_id
    (recovery_dir / "REQUEST.md").write_text("# recovery Work\n", encoding="utf-8")
    (recovery_dir / "BLOCKER.json").write_text("{}\n", encoding="utf-8")
    payload = _upgrade_receipt_v2(
        process,
        receipt_ref,
        recovery_work={
            "work_ref": f"process/works/{work_id}/WORK.yaml",
            "scope_digest": active.scope.digest,
            "required_status": "active",
        },
    )
    payload["repositories"]["process"]["pending_paths"] = list(
        observe_repo(process).changed_paths
    )
    (process / receipt_ref).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload, active.scope.digest


def test_publication_close_is_the_only_authorized_paused_completion_path(
    tmp_path: Path,
) -> None:
    release, process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    standard = plan_work_close(
        process,
        "W-PUBLISH",
        expected_status="paused",
        outcome="completed",
        result_ref=result_ref,
    )
    assert not standard.ready
    assert "invalid Work transition: paused -> completed" in "; ".join(standard.blockers)

    before_work = load_work(process, "W-PUBLISH")
    handoff_before = (process / "works/W-PUBLISH/HANDOFF.yaml").read_bytes()
    usage_before = (process / "works/W-PUBLISH/USAGE.json").read_bytes()
    plan = _plan(release, result_ref, receipt_ref)
    assert plan.ready, plan.blockers
    assert plan.operation == "work.publication-close"
    receipt = apply_work_publication_close(
        release,
        plan,
        _authorization(plan, "AUTH-PUBLICATION-CLOSE"),
    )

    closed = load_work(process, "W-PUBLISH")
    assert receipt.decision == "PASS"
    assert closed.status == "completed"
    assert closed.result_ref == result_ref
    assert closed.release_base_oid == before_work.release_base_oid
    assert closed.process_base_oid == before_work.process_base_oid
    assert (process / "works/W-PUBLISH/HANDOFF.yaml").read_bytes() == handoff_before
    assert (process / "works/W-PUBLISH/USAGE.json").read_bytes() == usage_before
    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    manifest = json.loads(
        (
            process
            / ".meta-flow-runtime/work-close/transactions/AUTH-PUBLICATION-CLOSE/manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["operation"] == "work.publication-close"
    assert manifest["publication_binding"]["handoff_digest"] == plan.publication_binding.handoff_digest


def test_publication_close_blocks_unexplained_or_remote_oid_drift(tmp_path: Path) -> None:
    release, process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    receipt_path = process / receipt_ref
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["repositories"]["process"]["commit_authorization_ids"] = []
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    blocked = _plan(release, result_ref, receipt_ref)
    assert not blocked.ready
    assert blocked.targets == ()
    assert "requires paths and commit/push authorization IDs" in "; ".join(blocked.blockers)

    payload["repositories"]["process"]["commit_authorization_ids"] = [
        "AUTH-PROCESS-COMMIT"
    ]
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    process_remote = Path(_git(process, "remote", "get-url", "origin"))
    paused_oid = payload["repositories"]["process"]["paused_oid"]
    subprocess.run(
        ["git", "--git-dir", str(process_remote), "update-ref", "refs/heads/main", paused_oid],
        check=True,
    )
    remote_blocked = _plan(release, result_ref, receipt_ref)
    assert not remote_blocked.ready
    assert remote_blocked.targets == ()
    assert "live remote OID differs" in "; ".join(remote_blocked.blockers)


def test_publication_close_blocks_scope_and_plan_drift_before_write(tmp_path: Path) -> None:
    release, process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    receipt_path = process / receipt_ref
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    (process / "OUTSIDE.md").write_text("outside\n", encoding="utf-8")
    _git(process, "add", "OUTSIDE.md")
    _git(
        process,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "unexpected published path",
    )
    outside_oid = _git(process, "rev-parse", "HEAD")
    _git(process, "push", "origin", "main")
    payload["repositories"]["process"].update(
        {
            "published_oid": outside_oid,
            "changed_paths": _changed_paths(process, payload["repositories"]["process"]["paused_oid"], outside_oid),
        }
    )
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    scope_blocked = _plan(release, result_ref, receipt_ref)
    assert not scope_blocked.ready
    assert "outside Work scope: OUTSIDE.md" in "; ".join(scope_blocked.blockers)

    drift_root = tmp_path / "drift"
    drift_root.mkdir()
    drift_release, drift_process, drift_result_ref, drift_receipt_ref = _publication_fixture(
        drift_root
    )
    plan = _plan(drift_release, drift_result_ref, drift_receipt_ref)
    assert plan.ready, plan.blockers
    authorization = _authorization(plan, "AUTH-PUBLICATION-DRIFT")
    result_path = drift_process / drift_result_ref
    result_path.write_text(
        json.dumps({"schema_version": 1, "work_id": "W-PUBLISH", "decision": "FAIL"})
        + "\n",
        encoding="utf-8",
    )
    work_before = (drift_process / "works/W-PUBLISH/WORK.yaml").read_bytes()
    try:
        apply_work_publication_close(drift_release, plan, authorization)
    except ValueError as exc:
        assert "plan drifted before apply" in str(exc)
    else:
        raise AssertionError("stale publication-close plan was applied")
    assert (drift_process / "works/W-PUBLISH/WORK.yaml").read_bytes() == work_before


def test_publication_close_writer_failure_recovers_exact_preimage(tmp_path: Path) -> None:
    release, process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    plan = _plan(release, result_ref, receipt_ref)
    assert plan.ready, plan.blockers
    work_before = (process / "works/W-PUBLISH/WORK.yaml").read_bytes()
    project_before = (process / "PROJECT.yaml").read_bytes()
    from meta_flow.work import lifecycle_transaction

    original = lifecycle_transaction._replace_bytes
    calls = 0

    def fail_second(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected publication-close target failure")
        original(path, content)

    with patch("meta_flow.work.lifecycle_transaction._replace_bytes", fail_second):
        receipt = apply_work_publication_close(
            release,
            plan,
            _authorization(plan, "AUTH-PUBLICATION-RECOVERED"),
        )

    assert receipt.decision == "RECOVERED"
    assert receipt.recovery_required is False
    assert (process / "works/W-PUBLISH/WORK.yaml").read_bytes() == work_before
    assert (process / "PROJECT.yaml").read_bytes() == project_before
    assert load_work(process, "W-PUBLISH").status == "paused"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_publication_close_rejects_wrong_authorization_kind_oid_and_dirty_drift(
    tmp_path: Path,
) -> None:
    release, process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    plan = _plan(release, result_ref, receipt_ref)
    assert plan.ready, plan.blockers
    work_before = (process / "works/W-PUBLISH/WORK.yaml").read_bytes()

    standard = WorkCloseAuthorizationV1(
        1,
        AUTHORIZATION_KIND,
        "AUTH-STANDARD-CLOSE",
        plan.work_id,
        plan.plan_digest,
        tuple(target.ref for target in plan.targets),
        "2099-01-01T00:00:00+00:00",
    )
    with pytest.raises(ValueError, match="cannot approve publication-close"):
        apply_work_close(process, plan, standard)

    authorization = _authorization(plan, "AUTH-PUBLICATION-BINDING")
    wrong_oids = replace(
        authorization,
        published_oids=(
            ("release", "f" * 40),
            ("process", dict(authorization.published_oids)["process"]),
        ),
    )
    with pytest.raises(ValueError, match="authorization binding mismatch"):
        apply_work_publication_close(release, plan, wrong_oids)

    (process / "UNAUTHORIZED-PENDING.md").write_text("drift\n", encoding="utf-8")
    with pytest.raises(ValueError, match="plan drifted before apply"):
        apply_work_publication_close(release, plan, authorization)
    assert (process / "works/W-PUBLISH/WORK.yaml").read_bytes() == work_before


def test_publication_close_authorization_rejects_non_transaction_safe_id(
    tmp_path: Path,
) -> None:
    release, _process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    plan = _plan(release, result_ref, receipt_ref)
    payload = {
        **asdict(_authorization(plan, "AUTH-PUBLICATION-SAFE")),
        "authorization_id": "AUTH:PUBLICATION:UNSAFE",
        "target_refs": [target.ref for target in plan.targets],
        "paused_oids": dict(plan.publication_binding.paused_oids),
        "published_oids": dict(plan.publication_binding.published_oids),
    }

    with pytest.raises(ValueError, match="authorization_id is invalid"):
        WorkPublicationCloseAuthorizationV1.from_mapping(payload)


def test_publication_close_atomically_converges_phase_governance_state_and_current(
    tmp_path: Path,
) -> None:
    release, process, result_ref, receipt_ref = _publication_fixture(
        tmp_path, governed=True
    )
    ledger_before = {
        path.relative_to(process).as_posix(): path.read_bytes()
        for path in (process / "state").glob("*-LEDGER.ndjson")
    }
    handoff_before = (process / "works/W-PUBLISH/HANDOFF.yaml").read_bytes()
    plan = _plan(release, result_ref, receipt_ref)
    assert plan.ready, plan.blockers
    refs = [target.ref for target in plan.targets]
    assert "phases/P1/PHASE.yaml" in refs
    assert GOVERNANCE_PROJECTION_REL.as_posix() in refs
    assert "state/STATE.current.json" in refs
    assert "STATE.md" in refs

    receipt = apply_work_publication_close(
        release,
        plan,
        _authorization(plan, "AUTH-PUBLICATION-GOVERNED"),
    )

    assert receipt.decision == "PASS"
    assert validate_governance_projection(release, process)["decision"] == "PASS"
    errors, warnings = state_current.check_current_state(release, mode="enforce")
    assert errors == []
    assert warnings == []
    assert state_current.validate_current_projection(release) == []
    state = state_current.load_current_state(release)
    assert state["formal_truth_projection"]["active_work_ids"] == []
    assert {
        path.relative_to(process).as_posix(): path.read_bytes()
        for path in (process / "state").glob("*-LEDGER.ndjson")
    } == ledger_before
    assert (process / "works/W-PUBLISH/HANDOFF.yaml").read_bytes() == handoff_before
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_publication_close_cli_returns_structured_plan_without_traceback(
    tmp_path: Path, capsys
) -> None:
    release, _process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    exit_code = publication_close_main(
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-PUBLISH",
            "--result-ref",
            f"process/{result_ref}",
            "--publication-receipt-ref",
            f"process/{receipt_ref}",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["operation"] == "work.publication-close"
    assert payload["decision"] == "READY"
    assert payload["mutation_count"] == 0


def test_publication_close_v2_admits_exact_211_path_candidate_set(
    tmp_path: Path,
) -> None:
    release, process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    payload = _publish_batch_to_exact_path_count(
        process,
        receipt_ref,
        path_count=211,
    )

    assert len(payload["repositories"]["process"]["changed_paths"]) == 211
    plan = _plan(release, result_ref, receipt_ref)
    assert plan.ready, plan.blockers
    receipt = apply_work_publication_close(
        release,
        plan,
        _authorization(plan, "AUTH-PUBLICATION-BATCH-211"),
    )
    assert receipt.decision == "PASS"
    assert load_work(process, "W-PUBLISH").status == "completed"
    assert inspect_work_close_transactions(process)["decision"] == "PASS"


def test_publication_close_v2_rejects_missing_duplicate_and_digest_drift(
    tmp_path: Path,
) -> None:
    release, process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    payload = _upgrade_receipt_v2(process, receipt_ref)
    receipt_path = process / receipt_ref
    repository = payload["repositories"]["process"]
    all_paths = list(repository["changed_paths"])

    missing_paths = all_paths[:-1]
    repository["path_coverage"] = [
        _candidate_coverage(repository, role="process", paths=missing_paths)
    ]
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    missing = _plan(release, result_ref, receipt_ref)
    assert not missing.ready
    assert missing.targets == ()
    assert "exactly partition changed_paths" in "; ".join(missing.blockers)

    repository["path_coverage"] = [
        _candidate_coverage(repository, role="process", paths=all_paths),
        _candidate_coverage(repository, role="process", paths=[all_paths[0]]),
    ]
    repository["path_coverage"].sort(
        key=lambda item: (item["paths"][0], item["coverage_type"])
    )
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    duplicate = _plan(release, result_ref, receipt_ref)
    assert not duplicate.ready
    assert "contains duplicates" in "; ".join(duplicate.blockers)

    repository["path_coverage"] = [
        {
            **_candidate_coverage(repository, role="process", paths=all_paths),
            "candidate_set_digest": "0" * 64,
        }
    ]
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    digest_drift = _plan(release, result_ref, receipt_ref)
    assert not digest_drift.ready
    assert "candidate_set_digest mismatch" in "; ".join(digest_drift.blockers)

    repository["path_coverage"] = [
        {
            **_candidate_coverage(repository, role="process", paths=all_paths),
            "commit_authorization_ids": ["AUTH-DIFFERENT-CANDIDATE-SET"],
        }
    ]
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    authorization_drift = _plan(release, result_ref, receipt_ref)
    assert not authorization_drift.ready
    assert "must exactly match repository authorization IDs" in "; ".join(
        authorization_drift.blockers
    )


@pytest.mark.parametrize(
    ("status", "result_decision", "allow_shared_path", "expected"),
    [
        ("paused", "PASS", True, "identity, status, scope, or result mismatch"),
        ("completed", "FAIL", True, "exact matching PASS result"),
        ("completed", "PASS", False, "outside prior Work scope"),
    ],
)
def test_publication_close_v2_prior_work_coverage_is_fail_closed(
    tmp_path: Path,
    status: str,
    result_decision: str,
    allow_shared_path: bool,
    expected: str,
) -> None:
    release, process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    _add_prior_work_publication(
        release,
        process,
        receipt_ref,
        status=status,
        result_decision=result_decision,
        allow_shared_path=allow_shared_path,
    )
    plan = _plan(release, result_ref, receipt_ref)
    assert not plan.ready
    assert plan.targets == ()
    assert expected in "; ".join(plan.blockers)


def test_publication_close_v2_prior_work_coverage_and_recovery_pending_are_admitted(
    tmp_path: Path,
) -> None:
    prior_root = tmp_path / "prior"
    prior_root.mkdir()
    release, process, result_ref, receipt_ref = _publication_fixture(prior_root)
    _add_prior_work_publication(release, process, receipt_ref)
    prior_plan = _plan(release, result_ref, receipt_ref)
    assert prior_plan.ready, prior_plan.blockers

    recovery_root = tmp_path / "recovery"
    recovery_root.mkdir()
    release, process, result_ref, receipt_ref = _publication_fixture(recovery_root)
    payload, _scope_digest = _add_recovery_work_pending_paths(
        release,
        process,
        receipt_ref,
    )
    recovery_plan = _plan(release, result_ref, receipt_ref)
    assert recovery_plan.ready, recovery_plan.blockers

    (process / "OUTSIDE-PENDING.json").write_text("{}\n", encoding="utf-8")
    payload["repositories"]["process"]["pending_paths"] = list(
        observe_repo(process).changed_paths
    )
    (process / receipt_ref).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    outside = _plan(release, result_ref, receipt_ref)
    assert not outside.ready
    assert "pending publication path is outside authorized scope" in "; ".join(
        outside.blockers
    )


def test_publication_close_v2_recovery_work_drift_invalidates_apply(
    tmp_path: Path,
) -> None:
    release, process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    _add_recovery_work_pending_paths(release, process, receipt_ref)
    plan = _plan(release, result_ref, receipt_ref)
    assert plan.ready, plan.blockers
    authorization = _authorization(plan, "AUTH-PUBLICATION-RECOVERY-DRIFT")
    primary_before = (process / "works/W-PUBLISH/WORK.yaml").read_bytes()

    update_work_status(
        process,
        "W-RECOVERY",
        expected_status="active",
        new_status="blocked",
    )
    with pytest.raises(ValueError, match="plan drifted before apply"):
        apply_work_publication_close(release, plan, authorization)
    assert (process / "works/W-PUBLISH/WORK.yaml").read_bytes() == primary_before


def test_publication_close_cli_requires_external_authorization_without_plan_drift(
    tmp_path: Path,
    capsys,
) -> None:
    release, process, result_ref, receipt_ref = _publication_fixture(tmp_path)
    plan = _plan(release, result_ref, receipt_ref)
    assert plan.ready, plan.blockers
    authorization_payload = {
        **asdict(_authorization(plan, "AUTH-PUBLICATION-EXTERNAL")),
        "target_refs": [target.ref for target in plan.targets],
        "paused_oids": dict(plan.publication_binding.paused_oids),
        "published_oids": dict(plan.publication_binding.published_oids),
    }
    inside = process / "works/W-PUBLISH/CLOSE-AUTHORIZATION.json"
    inside.write_text(json.dumps(authorization_payload) + "\n", encoding="utf-8")
    exit_code = publication_close_main(
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-PUBLISH",
            "--result-ref",
            f"process/{result_ref}",
            "--publication-receipt-ref",
            f"process/{receipt_ref}",
            "--authorization",
            str(inside),
            "--apply",
        ]
    )
    blocked = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert blocked["decision"] == "BLOCKED"
    assert "outside release/process repositories" in blocked["error"]
    inside.unlink()

    external = tmp_path / "external-publication-close-authorization.json"
    external.write_text(json.dumps(authorization_payload) + "\n", encoding="utf-8")
    exit_code = publication_close_main(
        [
            "--project-root",
            str(release),
            "--work-id",
            "W-PUBLISH",
            "--result-ref",
            f"process/{result_ref}",
            "--publication-receipt-ref",
            f"process/{receipt_ref}",
            "--authorization",
            str(external),
            "--apply",
        ]
    )
    applied = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert applied["decision"] == "PASS"
    assert applied["status"] == "completed"
