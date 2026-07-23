from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.project.process_route import ProcessRouteError
from meta_flow.project.scale import dump_yaml
from meta_flow.repository import publisher
from meta_flow.repository.cli import commit_main, push_main
from meta_flow.repository.publisher import (
    PublicationEvidence,
    RepositoryApplyError,
    RepositoryAuthorization,
    apply_commit,
    apply_push,
    evaluate_publication_eligibility,
    execute_push_sequence,
)
from meta_flow.repository.publisher import (
    plan_commit as _plan_commit,
)
from meta_flow.repository.publisher import (
    plan_push as _plan_push,
)


@pytest.fixture(autouse=True)
def _isolated_process_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(project_root: Path, logical_ref: str) -> Path:
        assert logical_ref.startswith("process/")
        return project_root / "_process" / Path(*logical_ref.split("/")[1:])

    monkeypatch.setattr(publisher, "resolve_process_ref", resolve)


def _path_for_ref(project_root: Path, logical_ref: str) -> Path:
    return project_root / "_process" / Path(*logical_ref.split("/")[1:])


def _write_ref(project_root: Path, logical_ref: str, content: str) -> Path:
    path = _path_for_ref(project_root, logical_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _eligibility_fixture(tmp_path: Path, *, profile: str, reasons: list[str], cp8: dict[str, object]) -> None:
    work_ref = "process/works/W-001/WORK.yaml"
    route_ref = "process/checks/route.json"
    scope_digest = "a" * 64
    work_data = {
        "work_id": "W-001",
        "kind": "work",
        "risk_profile": profile,
        "risk_reason_codes": reasons,
        "required_gates": [],
        "scope_version": 7,
        "scope_digest": scope_digest,
    }
    snapshot = {
        "work_id": "W-001",
        "work_ref": work_ref,
        "kind": "work",
        "risk_profile": profile,
        "risk_reason_codes": reasons,
        "required_gates": [],
        "scope_version": 7,
        "scope_digest": scope_digest,
    }
    route_data = {
        "work_profile_snapshot": snapshot,
        "work_profile_digest": _canonical_digest(snapshot),
        "checkpoint_applicability": {"CP8": cp8},
    }
    work = _path_for_ref(tmp_path, work_ref)
    route = _path_for_ref(tmp_path, route_ref)
    work.parent.mkdir(parents=True, exist_ok=True)
    route.parent.mkdir(parents=True, exist_ok=True)
    work.write_text(
        dump_yaml(work_data),
        encoding="utf-8",
    )
    route.write_text(json.dumps(route_data), encoding="utf-8")


def _canonical_digest(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_publication_evidence(
    project_root: Path,
    repo_root: Path,
    *,
    operation: str,
    repo_role: str,
    remote: str = "",
    ref: str = "",
    profile: str = "G1",
    g2_approved: bool = False,
) -> tuple[PublicationEvidence, Path, Path]:
    process_root = project_root / "_process"
    sequence = len(tuple(process_root.glob("fixtures/*/publication-evidence.json")))
    prefix = f"publication-{sequence}"
    base_ref = f"process/fixtures/{prefix}"
    work_ref = f"{base_ref}/WORK.yaml"
    route_ref = f"{base_ref}/route.json"
    policy_ref = f"{base_ref}/target-policy.json"
    evidence_ref = f"{base_ref}/publication-evidence.json"
    work_path = _path_for_ref(project_root, work_ref)
    route_path = _path_for_ref(project_root, route_ref)
    scope_digest = "a" * 64
    canonical_refs = {
        "work": work_ref,
        "route_plan": route_ref,
        "target_policy": policy_ref,
    }
    if profile == "G2":
        canonical_refs.update(
            {
                "formal_cr": f"{base_ref}/CR-001.md",
                "cp8_result": f"{base_ref}/CP8.result.json",
                "cp8_checkpoint": f"{base_ref}/CP8.md",
                "gate_ledger": f"{base_ref}/GATE-LEDGER.ndjson",
            }
        )
    allowed_reads = [evidence_ref, *canonical_refs.values()]
    work = {
        "work_id": "W-001",
        "kind": "work",
        "risk_profile": profile,
        "risk_reason_codes": [],
        "required_gates": [],
        "scope_version": 7,
        "scope_digest": scope_digest,
        "scope": {
            "version": 7,
            "digest": scope_digest,
            "allowed_reads": allowed_reads,
        },
    }
    profile_snapshot = {
        "work_id": "W-001",
        "work_ref": work_ref,
        "kind": "work",
        "risk_profile": profile,
        "risk_reason_codes": [],
        "required_gates": [],
        "scope_version": 7,
        "scope_digest": scope_digest,
    }
    cp8 = (
        {"applies": True, "human_gate": "required"}
        if profile == "G2"
        else {"applies": False, "decision": "N/A", "reason": "profile-not-required"}
    )
    route = {
        "work_profile_snapshot": profile_snapshot,
        "work_profile_digest": _canonical_digest(profile_snapshot),
        "checkpoint_applicability": {"CP8": cp8},
    }
    target = {
        "operation": operation,
        "repo_role": repo_role,
        "remote": remote,
        "ref": ref,
        "preauthorized": True,
    }
    policy = {
        "decision": "APPROVED",
        "work_id": "W-001",
        "scope_version": 7,
        "scope_digest": scope_digest,
        "targets": [target],
    }
    work_path.parent.mkdir(parents=True, exist_ok=True)
    work_path.write_text(dump_yaml(work), encoding="utf-8")
    route_path.write_text(json.dumps(route), encoding="utf-8")
    _write_ref(project_root, policy_ref, json.dumps(policy))
    if profile == "G2":
        status = "approved" if g2_approved else "pending"
        lifecycle = "closed" if g2_approved else "active"
        readiness = "READY" if g2_approved else "NOT_READY"
        gate_status = "cp8_closed" if g2_approved else "cp8_pending"
        _write_ref(
            project_root,
            canonical_refs["formal_cr"],
            f"---\ncr_id: CR-001\nlifecycle_status: {lifecycle}\n"
            f"readiness_status: {readiness}\ngate_status: {gate_status}\n---\n",
        )
        _write_ref(
            project_root,
            canonical_refs["cp8_result"],
            json.dumps(
                {
                    "checkpoint": "CP8",
                    "decision": "PASS" if g2_approved else "BLOCKED",
                    "work_id": "W-001",
                    "scope_version": 7,
                    "scope_digest": scope_digest,
                }
            ),
        )
        _write_ref(
            project_root,
            canonical_refs["cp8_checkpoint"],
            f"---\nwork_id: W-001\nstatus: {status}\nscope_digest: {scope_digest}\n---\n",
        )
        _write_ref(
            project_root,
            canonical_refs["gate_ledger"],
            json.dumps(
                {
                    "event_type": "human_gate_approval",
                    "status": status,
                    "work_id": "W-001",
                    "cr_id": "CR-001",
                    "gate": "CP8",
                    "scope_digest": scope_digest,
                }
            )
            + "\n",
        )
    canonical_digests = {
        key: sha256(_path_for_ref(project_root, logical_ref).read_bytes()).hexdigest()
        for key, logical_ref in canonical_refs.items()
    }
    evidence_payload = {
        "schema_version": 1,
        "evidence_kind": "publication-eligibility",
        "work_id": "W-001",
        "scope_version": 7,
        "scope_digest": scope_digest,
        "work_profile_digest": _canonical_digest(profile_snapshot),
        "route_plan_digest": _canonical_digest(route),
        "canonical_refs": canonical_refs,
        "canonical_digests": canonical_digests,
        "repo_oids": {repo_role: git(repo_root, "rev-parse", "HEAD")},
        "requested_target": {
            "operation": operation,
            "repo_role": repo_role,
            "remote": remote,
            "ref": ref,
        },
    }
    evidence_path = _path_for_ref(project_root, evidence_ref)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return PublicationEvidence(project_root=project_root, evidence_ref=evidence_ref), work_path, route_path


def plan_commit(**kwargs):
    if kwargs.get("publication_evidence") is None:
        evidence, _work, _route = _canonical_publication_evidence(
            kwargs["repo_root"].parent,
            kwargs["repo_root"],
            operation="commit",
            repo_role=kwargs["repo_role"],
        )
        kwargs["publication_evidence"] = evidence
    return _plan_commit(**kwargs)


def plan_push(**kwargs):
    if kwargs.get("publication_evidence") is None:
        evidence, _work, _route = _canonical_publication_evidence(
            kwargs["repo_root"].parent,
            kwargs["repo_root"],
            operation="push",
            repo_role=kwargs["repo_role"],
            remote=kwargs["remote"],
            ref=kwargs["ref"],
        )
        kwargs["publication_evidence"] = evidence
    return _plan_push(**kwargs)


def test_plan_requires_canonical_publication_evidence_before_ready(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("pending\n", encoding="utf-8")

    plan = _plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: pending",
        expected_head_oid=before,
    )

    assert plan.blocked
    assert "PUBLICATION_EVIDENCE_REQUIRED" in plan.reason


def test_publication_scope_matches_process_relative_work_refs() -> None:
    work = {
        "scope": {
            "allowed_reads": [
                "works/W-001/WORK.yaml",
                "checks/route.json",
                "release/meta_flow/**",
            ]
        }
    }

    assert publisher._scope_allows_reads(
        work,
        (
            "process/works/W-001/WORK.yaml",
            "process/checks/route.json",
            "process/release/meta_flow/.publication-runtime/evidence.json",
        ),
    )
    assert not publisher._scope_allows_reads(
        work,
        ("process/changes/CR-999.md",),
    )


@pytest.mark.parametrize("profile", ["G0", "G1", "G2"])
def test_canonical_profile_fixtures_reach_expected_plan_branch(
    profile: str,
    tmp_path: Path,
) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("pending\n", encoding="utf-8")
    evidence, _work, _route = _canonical_publication_evidence(
        tmp_path,
        local,
        operation="commit",
        repo_role="release",
        profile=profile,
        g2_approved=profile == "G2",
    )

    plan = _plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: canonical fixture",
        expected_head_oid=before,
        publication_evidence=evidence,
    )

    assert not plan.blocked
    expected_branch = "G2_CP8_APPLIES" if profile == "G2" else "G0_G1_NOT_APPLICABLE_BY_PROFILE"
    assert plan.publication_eligibility is not None
    assert plan.publication_eligibility.branch == expected_branch


@pytest.mark.parametrize("operation", ["commit", "push"])
def test_forged_eligibility_fields_cannot_override_canonical_g2_truth(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local, bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    remote_before = git(local, "rev-parse", "origin/main")
    if operation == "commit":
        (local / "README.md").write_text("pending\n", encoding="utf-8")
        remote = ""
        ref = ""
    else:
        make_local_commit(local, "README.md", "pending push\n")
        remote = "origin"
        ref = "refs/heads/main"
    evidence, _work, _route = _canonical_publication_evidence(
        tmp_path,
        local,
        operation=operation,
        repo_role="release",
        remote=remote,
        ref=ref,
        profile="G2",
        g2_approved=False,
    )
    evidence_path = _path_for_ref(tmp_path, evidence.evidence_ref)
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["eligibility_facts"] = {
        "cp8_machine_pass_like": True,
        "cp8_checkpoint_approved": True,
        "cp8_gate_approved": True,
        "native_closed": True,
    }
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    if operation == "commit":
        plan = _plan_commit(
            project_id="demo",
            work_id="W-001",
            repo_role="release",
            repo_root=local,
            allowed_paths=("README.md",),
            message="docs: forged evidence",
            expected_head_oid=before,
            publication_evidence=evidence,
        )
        authorization = commit_auth(plan, "forged-commit")
        apply = apply_commit
    else:
        plan = _plan_push(
            project_id="demo",
            work_id="W-001",
            repo_role="release",
            repo_root=local,
            remote=remote,
            ref=ref,
            expected_remote_oid=remote_before,
            publication_evidence=evidence,
        )
        authorization = push_auth(plan, "forged-push")
        apply = apply_push

    authorization_calls = 0

    def unexpected_authorization(*_args, **_kwargs) -> None:
        nonlocal authorization_calls
        authorization_calls += 1

    monkeypatch.setattr(publisher, "_validate_authorization", unexpected_authorization)
    assert plan.blocked
    assert plan.publication_eligibility is not None
    assert plan.publication_eligibility.reason == "CP8_REQUIRED"
    with pytest.raises(ValueError, match="blocked"):
        apply(plan, authorization)
    assert authorization_calls == 0
    assert git(local, "diff", "--cached", "--name-only") == ""
    assert git(bare, "rev-parse", "refs/heads/main") == remote_before
    if operation == "commit":
        assert git(local, "rev-parse", "HEAD") == before


@pytest.mark.parametrize(
    "drift",
    ["missing_object", "stale_object", "evidence_digest", "repo_oid", "target"],
)
def test_apply_reloads_every_canonical_binding_before_authorization_and_mutation(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("pending\n", encoding="utf-8")
    evidence, _work, _route = _canonical_publication_evidence(
        tmp_path,
        local,
        operation="commit",
        repo_role="release",
        profile="G2",
        g2_approved=True,
    )
    plan = _plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: drift",
        expected_head_oid=before,
        publication_evidence=evidence,
    )
    assert not plan.blocked
    evidence_path = _path_for_ref(tmp_path, evidence.evidence_ref)
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    refs = payload["canonical_refs"]
    if drift == "missing_object":
        _path_for_ref(tmp_path, refs["cp8_result"]).unlink()
    elif drift == "stale_object":
        _path_for_ref(tmp_path, refs["cp8_checkpoint"]).write_text(
            "---\nwork_id: W-001\nstatus: pending\nscope_digest: stale\n---\n",
            encoding="utf-8",
        )
    elif drift == "evidence_digest":
        payload["canonical_digests"]["cp8_result"] = "0" * 64
        evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    elif drift == "repo_oid":
        payload["repo_oids"]["release"] = "0" * 40
        evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        payload["requested_target"]["operation"] = "push"
        evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    authorization_calls = 0

    def unexpected_authorization(*_args, **_kwargs) -> None:
        nonlocal authorization_calls
        authorization_calls += 1

    monkeypatch.setattr(publisher, "_validate_authorization", unexpected_authorization)
    with pytest.raises(ValueError, match="stale"):
        apply_commit(plan, commit_auth(plan, f"drift-{drift}"))
    assert authorization_calls == 0
    assert git(local, "diff", "--cached", "--name-only") == ""
    assert git(local, "rev-parse", "HEAD") == before


def test_publication_eligibility_g2_and_profile_na_branches(tmp_path: Path) -> None:
    _eligibility_fixture(tmp_path, profile="G2", reasons=["PUBLIC_CONTRACT"], cp8={"applies": True, "human_gate": "required"})
    blocked = evaluate_publication_eligibility(project_root=tmp_path, work_id="W-001", route_plan_ref="process/checks/route.json")
    assert (blocked.decision, blocked.reason, blocked.mutation_count) == ("BLOCKED", "CP8_REQUIRED", 0)

    _eligibility_fixture(tmp_path, profile="G1", reasons=[], cp8={"applies": False, "decision": "N/A", "reason": "profile-not-required"})
    g1 = evaluate_publication_eligibility(project_root=tmp_path, work_id="W-001", route_plan_ref="process/checks/route.json")
    assert (g1.decision, g1.reason, g1.branch) == ("READY", "eligible_by_profile", "G0_G1_NOT_APPLICABLE_BY_PROFILE")


def test_publication_eligibility_fails_closed_for_route_and_profile_conflicts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _eligibility_fixture(tmp_path, profile="G0", reasons=["PUBLIC_CONTRACT"], cp8={"applies": False, "decision": "N/A", "reason": "profile-not-required"})
    g2_reason = evaluate_publication_eligibility(project_root=tmp_path, work_id="W-001", route_plan_ref="process/checks/route.json")
    monkeypatch.setattr(
        "meta_flow.repository.publisher.resolve_process_ref",
        lambda _root, ref: (_ for _ in ()).throw(ProcessRouteError("route_invalid", "fixture", ref)),
    )
    untrusted = evaluate_publication_eligibility(project_root=tmp_path, work_id="W-001", route_plan_ref="/invalid")
    assert (g2_reason.decision, g2_reason.reason, g2_reason.mutation_count) == ("BLOCKED", "RECLASSIFICATION_REQUIRED_G2", 0)
    assert (untrusted.decision, untrusted.reason, untrusted.mutation_count) == ("BLOCKED", "ROUTE_PROFILE_UNTRUSTED", 0)


def test_commit_apply_rechecks_publication_evidence_before_git_add(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("pending\n", encoding="utf-8")
    del monkeypatch
    evidence, work_path, _route_path = _canonical_publication_evidence(
        tmp_path,
        local,
        operation="commit",
        repo_role="release",
    )
    plan = plan_commit(project_id="demo", work_id="W-001", repo_role="release", repo_root=local, allowed_paths=("README.md",), message="docs: pending", expected_head_oid=before, publication_evidence=evidence)
    assert not plan.blocked
    work_path.write_text(dump_yaml({"work_id": "W-001", "kind": "work", "risk_profile": "G1", "risk_reason_codes": ["PUBLIC_CONTRACT"], "required_gates": [], "scope_digest": "a" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        apply_commit(plan, commit_auth(plan))
    assert git(local, "diff", "--cached", "--name-only") == ""
    assert git(local, "rev-parse", "HEAD") == before


def test_push_apply_rechecks_publication_evidence_before_transport(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    local, bare = init_remote_pair(tmp_path, "release")
    remote_before = git(local, "rev-parse", "origin/main")
    local_oid = make_local_commit(local, "README.md", "pending push\n")
    del monkeypatch
    evidence, _work_path, route_path = _canonical_publication_evidence(
        tmp_path,
        local,
        operation="push",
        repo_role="release",
        remote="origin",
        ref="refs/heads/main",
    )
    plan = plan_push(project_id="demo", work_id="W-001", repo_role="release", repo_root=local, remote="origin", ref="refs/heads/main", expected_remote_oid=remote_before, publication_evidence=evidence)
    assert not plan.blocked
    route_path.write_text(json.dumps({"checkpoint_applicability": {"CP8": {"applies": True, "human_gate": "required"}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        apply_push(plan, push_auth(plan, "push-drift"))
    assert git(bare, "rev-parse", "refs/heads/main") == remote_before
    assert git(local, "rev-parse", "HEAD") == local_oid


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def configure_identity(root: Path) -> None:
    git(root, "config", "user.name", "Meta Flow Test")
    git(root, "config", "user.email", "meta-flow@example.invalid")


def init_remote_pair(root: Path, name: str) -> tuple[Path, Path]:
    bare = root / f"{name}.git"
    bare.mkdir()
    git(bare, "init", "--bare", "--initial-branch=main")
    local = root / name
    local.mkdir()
    git(local, "init", "-b", "main")
    configure_identity(local)
    (local / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    git(local, "add", "README.md")
    git(local, "commit", "-m", "initial")
    git(local, "remote", "add", "origin", str(bare))
    git(local, "push", "-u", "origin", "main")
    return local, bare


def commit_auth(plan, authorization_id: str = "commit-auth") -> RepositoryAuthorization:
    return RepositoryAuthorization(
        authorization_id=authorization_id,
        operation="commit",
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        plan_digest=plan.plan_digest,
        expected_oid=plan.expected_head_oid,
        expires_at="2099-01-01T00:00:00+00:00",
    )


def push_auth(plan, authorization_id: str) -> RepositoryAuthorization:
    return RepositoryAuthorization(
        authorization_id=authorization_id,
        operation="push",
        project_id=plan.project_id,
        work_id=plan.work_id,
        repo_role=plan.repo_role,
        plan_digest=plan.plan_digest,
        expected_oid=plan.expected_remote_oid,
        expires_at="2099-01-01T00:00:00+00:00",
    )


def make_local_commit(local: Path, path: str, text: str) -> str:
    target = local / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(local, "add", "--", path)
    git(local, "commit", "-m", f"update {path}")
    return git(local, "rev-parse", "HEAD")


def test_commit_plan_is_dry_run_and_stages_only_allowlisted_paths(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("updated\n", encoding="utf-8")

    plan = plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: update readme",
        expected_head_oid=before,
    )

    assert not plan.blocked
    assert plan.as_dict()["mutation_count"] == 0
    assert git(local, "rev-parse", "HEAD") == before
    assert git(local, "diff", "--cached", "--name-only") == ""

    receipt = apply_commit(plan, commit_auth(plan))

    assert receipt.decision == "PASS"
    assert receipt.before_oid == before
    assert receipt.after_oid == git(local, "rev-parse", "HEAD")
    assert receipt.committed_paths == ("README.md",)
    assert git(local, "status", "--porcelain=v1") == ""


def test_commit_plan_blocks_unexpected_or_pre_staged_paths(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("updated\n", encoding="utf-8")
    (local / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    git(local, "add", "unexpected.txt")

    plan = plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: update readme",
        expected_head_oid=before,
    )

    assert plan.blocked
    assert "unexpected_paths" in plan.reason
    assert "unexpected_staged_paths" in plan.reason
    with pytest.raises(ValueError, match="blocked"):
        apply_commit(plan, commit_auth(plan))
    assert git(local, "rev-parse", "HEAD") == before


def test_commit_plan_head_drift_blocks_before_staging(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("planned\n", encoding="utf-8")
    plan = plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: planned",
        expected_head_oid=before,
    )
    git(local, "add", "README.md")
    git(local, "commit", "-m", "advance")
    (local / "README.md").write_text("second\n", encoding="utf-8")

    with pytest.raises(ValueError, match="stale"):
        apply_commit(plan, commit_auth(plan))

    assert git(local, "diff", "--cached", "--name-only") == ""


def test_push_is_exact_oid_fast_forward_without_force(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    expected = git(local, "rev-parse", "origin/main")
    local_oid = make_local_commit(local, "README.md", "next\n")

    plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=expected,
    )

    assert not plan.blocked
    assert plan.local_oid == local_oid
    assert plan.argv == ("push", "origin", f"{local_oid}:refs/heads/main")
    assert all("force" not in arg for arg in plan.argv)
    receipt = apply_push(plan, push_auth(plan, "push-release"))
    assert receipt.decision == "PASS"
    assert receipt.before_oid == expected
    assert receipt.after_oid == local_oid
    assert all("force" not in arg for arg in receipt.argv)


def advance_remote(tmp_path: Path, bare: Path, name: str) -> str:
    other = tmp_path / name
    git(tmp_path, "clone", str(bare), str(other))
    configure_identity(other)
    oid = make_local_commit(other, "other.txt", "remote advance\n")
    git(other, "push", "origin", "main")
    return oid


def test_remote_oid_drift_blocks_old_push_plan_without_mutation(tmp_path: Path) -> None:
    local, bare = init_remote_pair(tmp_path, "release")
    expected = git(local, "rev-parse", "origin/main")
    make_local_commit(local, "README.md", "local next\n")
    plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=expected,
    )
    advanced = advance_remote(tmp_path, bare, "other-release")

    with pytest.raises(ValueError, match="stale"):
        apply_push(plan, push_auth(plan, "push-release"))

    assert git(bare, "rev-parse", "refs/heads/main") == advanced


def test_push_plan_blocks_dirty_non_ff_and_missing_ref(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    expected = git(local, "rev-parse", "origin/main")
    (local / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    dirty = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=expected,
    )
    missing = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/new",
        expected_remote_oid="",
    )

    assert dirty.blocked
    assert "dirty_repository" in dirty.reason
    assert missing.blocked
    assert "remote_ref_not_present" in missing.reason


def test_two_repo_sequence_reports_partial_and_never_rolls_back_success(tmp_path: Path) -> None:
    release, release_bare = init_remote_pair(tmp_path, "release")
    process, process_bare = init_remote_pair(tmp_path, "process")
    release_expected = git(release, "rev-parse", "origin/main")
    process_expected = git(process, "rev-parse", "origin/main")
    release_new = make_local_commit(release, "release.txt", "release\n")
    make_local_commit(process, "process.txt", "process\n")
    release_plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=release,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=release_expected,
    )
    process_plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="process",
        repo_root=process,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=process_expected,
    )
    process_advanced = advance_remote(tmp_path, process_bare, "other-process")

    result = execute_push_sequence(
        (
            (release_plan, push_auth(release_plan, "push-release")),
            (process_plan, push_auth(process_plan, "push-process")),
        )
    )

    assert result.decision == "PARTIAL"
    assert result.repository_status == {"release": "success", "process": "failed"}
    assert result.rollback_count == 0
    assert git(release_bare, "rev-parse", "refs/heads/main") == release_new
    assert git(process_bare, "rev-parse", "refs/heads/main") == process_advanced


def test_first_push_failure_leaves_second_not_started(tmp_path: Path) -> None:
    release, release_bare = init_remote_pair(tmp_path, "release")
    process, process_bare = init_remote_pair(tmp_path, "process")
    release_expected = git(release, "rev-parse", "origin/main")
    process_expected = git(process, "rev-parse", "origin/main")
    make_local_commit(release, "release.txt", "release\n")
    process_new = make_local_commit(process, "process.txt", "process\n")
    release_plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=release,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=release_expected,
    )
    process_plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="process",
        repo_root=process,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=process_expected,
    )
    release_advanced = advance_remote(tmp_path, release_bare, "other-release")

    result = execute_push_sequence(
        (
            (release_plan, push_auth(release_plan, "push-release")),
            (process_plan, push_auth(process_plan, "push-process")),
        )
    )

    assert result.decision == "FAILED"
    assert result.repository_status == {"release": "failed", "process": "not_started"}
    assert git(release_bare, "rev-parse", "refs/heads/main") == release_advanced
    assert git(process_bare, "rev-parse", "refs/heads/main") == process_expected
    assert process_new != process_expected


def test_authorization_cannot_cross_operation_or_plan(tmp_path: Path) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    expected = git(local, "rev-parse", "origin/main")
    make_local_commit(local, "README.md", "next\n")
    plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=expected,
    )
    wrong = replace(push_auth(plan, "auth"), operation="commit")

    with pytest.raises(ValueError, match="does not match"):
        apply_push(plan, wrong)
    with pytest.raises(ValueError, match="single-use"):
        apply_push(plan, replace(push_auth(plan, "auth"), single_use=1))


def test_push_sequence_requires_nonempty_unique_repository_roles(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one"):
        execute_push_sequence(())

    local, _bare = init_remote_pair(tmp_path, "release")
    expected = git(local, "rev-parse", "origin/main")
    make_local_commit(local, "README.md", "next\n")
    plan = plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=expected,
    )
    with pytest.raises(ValueError, match="unique"):
        execute_push_sequence(
            (
                (plan, push_auth(plan, "push-release-1")),
                (plan, push_auth(plan, "push-release-2")),
            )
        )


def test_repository_cli_is_dry_run_then_requires_exact_authorization(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    remote_before = git(local, "rev-parse", "origin/main")
    (local / "README.md").write_text("updated\n", encoding="utf-8")
    commit_evidence, _work_path, _route_path = _canonical_publication_evidence(
        tmp_path,
        local,
        operation="commit",
        repo_role="release",
    )
    commit_args = [
        "--project-id",
        "demo",
        "--work-id",
        "W-001",
        "--repo-role",
        "release",
        "--repo-root",
        str(local),
        "--allowed-path",
        "README.md",
        "--message",
        "docs: update",
        "--expected-head-oid",
        before,
        "--project-root",
        str(tmp_path),
        "--publication-evidence-ref",
        commit_evidence.evidence_ref,
    ]

    assert commit_main(commit_args) == 0
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_payload["decision"] == "READY"
    assert dry_payload["mutation_count"] == 0
    assert git(local, "rev-parse", "HEAD") == before

    commit_plan = _plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: update",
        expected_head_oid=before,
        publication_evidence=commit_evidence,
    )
    commit_auth_path = tmp_path / "commit-auth.yaml"
    commit_auth_path.write_text(
        dump_yaml(commit_auth(commit_plan, "commit-cli").__dict__) + "\n",
        encoding="utf-8",
    )
    assert commit_main([*commit_args, "--apply", "--authorization", str(commit_auth_path)]) == 0
    committed = json.loads(capsys.readouterr().out)
    assert committed["receipt"]["decision"] == "PASS"

    push_evidence, _work_path, _route_path = _canonical_publication_evidence(
        tmp_path,
        local,
        operation="push",
        repo_role="release",
        remote="origin",
        ref="refs/heads/main",
    )
    push_plan = _plan_push(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        remote="origin",
        ref="refs/heads/main",
        expected_remote_oid=remote_before,
        publication_evidence=push_evidence,
    )
    push_auth_path = tmp_path / "push-auth.yaml"
    push_auth_path.write_text(
        dump_yaml(push_auth(push_plan, "push-cli").__dict__) + "\n",
        encoding="utf-8",
    )
    push_args = [
        "--project-id",
        "demo",
        "--work-id",
        "W-001",
        "--repo-role",
        "release",
        "--repo-root",
        str(local),
        "--remote",
        "origin",
        "--ref",
        "refs/heads/main",
        "--expected-remote-oid",
        remote_before,
        "--project-root",
        str(tmp_path),
        "--publication-evidence-ref",
        push_evidence.evidence_ref,
    ]
    assert push_main(push_args) == 0
    assert json.loads(capsys.readouterr().out)["mutation_count"] == 0
    assert push_main([*push_args, "--apply", "--authorization", str(push_auth_path)]) == 0
    pushed = json.loads(capsys.readouterr().out)
    assert pushed["receipt"]["decision"] == "PASS"
    assert git(local, "rev-parse", "origin/main") == git(local, "rev-parse", "HEAD")


def test_commit_hook_failure_returns_partial_receipt_and_preserves_staged_truth(
    tmp_path: Path,
) -> None:
    local, _bare = init_remote_pair(tmp_path, "release")
    before = git(local, "rev-parse", "HEAD")
    (local / "README.md").write_text("updated\n", encoding="utf-8")
    plan = plan_commit(
        project_id="demo",
        work_id="W-001",
        repo_role="release",
        repo_root=local,
        allowed_paths=("README.md",),
        message="docs: update",
        expected_head_oid=before,
    )
    hook = local / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    os.chmod(hook, 0o700)

    with pytest.raises(RepositoryApplyError) as raised:
        apply_commit(plan, commit_auth(plan))

    assert raised.value.receipt.decision == "PARTIAL"
    assert raised.value.receipt.failed_stage == "git_commit"
    assert raised.value.receipt.staged_paths == ("README.md",)
    assert raised.value.receipt.recovery_route.endswith("preserve staged truth")
    assert git(local, "rev-parse", "HEAD") == before
    assert git(local, "diff", "--cached", "--name-only") == "README.md"
