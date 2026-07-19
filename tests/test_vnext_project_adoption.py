from __future__ import annotations

import json
import os
import stat
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from meta_flow.project.adoption import (
    ADOPTION_INDEX_REL,
    ADOPTION_RECEIPT_DIR,
    AdoptionAuthorization,
    SnapshotAdoptionRequest,
    apply_snapshot_adoption,
    plan_snapshot_adoption,
)
from meta_flow.project.governance import (
    Phase,
    Roadmap,
    write_phase_create_only,
    write_roadmap_create_only,
)
from meta_flow.project.model import Project, write_project_create_only
from meta_flow.project.scale import load_yaml_object
from meta_flow.work.model import build_work, write_work_create_only
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def init_git(root: Path, *, commit: bool) -> None:
    root.mkdir(parents=True)
    git(root, "init", "-b", "main")
    if commit:
        git(
            root,
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        )


def build_source(root: Path) -> tuple[Path, tuple[str, ...]]:
    source = root / "legacy-process"
    init_git(source, commit=False)
    phase_ref = "phases/PH-001/PHASE.yaml"
    work_ref = "works/W-001/WORK.yaml"
    write_project_create_only(
        source,
        Project(
            schema_version=1,
            project_id="demo",
            name="Demo",
            status="active",
            roadmap_ref="ROADMAP.yaml",
            active_phase_ref=phase_ref,
            active_work_refs=(work_ref,),
        ),
    )
    write_roadmap_create_only(
        source,
        Roadmap(1, "demo", "长期结果", "active", (phase_ref,)),
    )
    write_phase_create_only(
        source,
        Phase(1, "demo", "PH-001", "阶段结果", "active", (work_ref,)),
    )
    request_ref = "works/W-001/REQUEST.md"
    request_path = source / request_ref
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text("confirmed request\n", encoding="utf-8")
    request_path.chmod(0o640)
    work = build_work(
        work_id="W-001",
        project_id="demo",
        objective="当前工作",
        request_ref=request_ref,
        phase_ref=phase_ref,
        scope=WorkScope(1, (request_ref,), ("README.md",), ("pytest-work",)),
        classification=classify_work(
            RiskFacts(change_kind="documentation", touched_path_count=1)
        ),
        release_base_oid="a" * 40,
        process_base_oid="",
    )
    write_work_create_only(source, work)
    (source / "historical-CP.md").write_text("must remain legacy-only\n", encoding="utf-8")
    git(source, "add", ".")
    git(
        source,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "current snapshot",
    )
    refs = (
        "PROJECT.yaml",
        "ROADMAP.yaml",
        phase_ref,
        work_ref,
        request_ref,
    )
    return source, refs


def make_plan(tmp_path: Path):
    source, refs = build_source(tmp_path)
    target = tmp_path / "demo-process"
    init_git(target, commit=False)
    request = SnapshotAdoptionRequest(
        project_id="demo",
        source_id="legacy-meta-flow-artifacts",
        source_process_root=source,
        target_process_root=target,
        include_refs=refs,
    )
    return source, target, plan_snapshot_adoption(request)


def authorize(plan, authorization_id: str = "auth-001") -> AdoptionAuthorization:
    return AdoptionAuthorization(
        authorization_id=authorization_id,
        authorization_kind="local-fixture",
        project_id="demo",
        plan_digest=plan.plan_digest,
        source_oid=plan.source_oid,
        target_oid=plan.target_oid,
        expires_at="2099-01-01T00:00:00+00:00",
    )


def test_adoption_dry_run_has_manifest_and_zero_mutation(tmp_path: Path) -> None:
    source, target, plan = make_plan(tmp_path)

    assert not plan.blocked
    assert plan.as_dict()["mutation_count"] == 0
    assert len(plan.entries) == 5
    assert all(entry.sha256 for entry in plan.entries)
    assert not (target / "PROJECT.yaml").exists()
    assert not (target / ADOPTION_INDEX_REL).exists()
    assert git(source, "status", "--porcelain=v1") == ""


def test_authorized_snapshot_apply_copies_only_explicit_current_state(tmp_path: Path) -> None:
    source, target, plan = make_plan(tmp_path)
    source_before = {
        "oid": git(source, "rev-parse", "HEAD"),
        "status": git(source, "status", "--porcelain=v1"),
    }

    receipt = apply_snapshot_adoption(plan, authorize(plan))

    assert receipt.decision == "PASS"
    assert receipt.legacy_source_mode == "read-only"
    assert set(receipt.created_refs) == {
        *(entry.ref for entry in plan.entries),
        ADOPTION_INDEX_REL.as_posix(),
    }
    assert not (target / "historical-CP.md").exists()
    assert git(source, "rev-parse", "HEAD") == source_before["oid"]
    assert git(source, "status", "--porcelain=v1") == source_before["status"]
    request_mode = stat.S_IMODE((target / "works/W-001/REQUEST.md").stat().st_mode)
    assert request_mode == 0o640
    index = load_yaml_object(target / ADOPTION_INDEX_REL)
    assert index["source_id"] == "legacy-meta-flow-artifacts"
    assert index["legacy_source_mode"] == "read-only"
    assert "source_root" not in index
    receipt_path = target / ADOPTION_RECEIPT_DIR / "auth-001.json"
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["decision"] == "PASS"


def test_authorization_is_bound_to_plan_project_and_oids(tmp_path: Path) -> None:
    _source, target, plan = make_plan(tmp_path)
    invalid = replace(authorize(plan), plan_digest="0" * 64)

    with pytest.raises(ValueError, match="does not match"):
        apply_snapshot_adoption(plan, invalid)

    assert not (target / "PROJECT.yaml").exists()


def test_expired_or_non_single_use_authorization_is_rejected(tmp_path: Path) -> None:
    _source, target, plan = make_plan(tmp_path)

    with pytest.raises(ValueError, match="expired"):
        apply_snapshot_adoption(
            plan,
            replace(authorize(plan), expires_at="2000-01-01T00:00:00+00:00"),
        )
    with pytest.raises(ValueError, match="single-use"):
        apply_snapshot_adoption(plan, replace(authorize(plan), single_use=False))

    assert not (target / "PROJECT.yaml").exists()


def test_consumed_authorization_cannot_be_replayed(tmp_path: Path) -> None:
    _source, _target, plan = make_plan(tmp_path)
    authorization = authorize(plan)
    apply_snapshot_adoption(plan, authorization)

    with pytest.raises(ValueError, match="already consumed"):
        apply_snapshot_adoption(plan, authorization)


def test_source_oid_drift_blocks_before_target_mutation(tmp_path: Path) -> None:
    source, target, plan = make_plan(tmp_path)
    (source / "new.txt").write_text("new\n", encoding="utf-8")
    git(source, "add", "new.txt")
    git(
        source,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "advance source",
    )

    with pytest.raises(ValueError, match="stale"):
        apply_snapshot_adoption(plan, authorize(plan))

    assert not (target / "PROJECT.yaml").exists()


def test_target_conflict_is_fail_closed_and_never_overwritten(tmp_path: Path) -> None:
    _source, target, plan = make_plan(tmp_path)
    (target / "PROJECT.yaml").write_text("foreign\n", encoding="utf-8")
    before = (target / "PROJECT.yaml").read_text(encoding="utf-8")

    conflicted = plan_snapshot_adoption(plan.request)

    assert conflicted.blocked
    assert "target_conflict" in {item.code for item in conflicted.conflicts}
    assert (target / "PROJECT.yaml").read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "ref",
    ["../outside", ".git/config", "historical-CP.md", "other-project/PROJECT.yaml"],
)
def test_snapshot_allowlist_rejects_history_escape_and_unselected_shapes(tmp_path: Path, ref: str) -> None:
    source, _refs = build_source(tmp_path)
    target = tmp_path / "target"
    init_git(target, commit=False)

    plan = plan_snapshot_adoption(
        SnapshotAdoptionRequest(
            "demo",
            "legacy",
            source,
            target,
            ("PROJECT.yaml", ref),
        )
    )

    assert plan.blocked
    assert "ref_not_allowed" in {item.code for item in plan.conflicts}


def test_unselected_sibling_file_is_not_read_or_copied(tmp_path: Path) -> None:
    source, target, plan = make_plan(tmp_path)
    sibling = source / "other-project-private.txt"
    sibling.write_text("must not be copied\n", encoding="utf-8")
    before_stat = os.stat(sibling)

    receipt = apply_snapshot_adoption(plan, authorize(plan))

    assert receipt.decision == "PASS"
    assert not (target / sibling.name).exists()
    after_stat = os.stat(sibling)
    assert (after_stat.st_size, after_stat.st_mtime_ns) == (before_stat.st_size, before_stat.st_mtime_ns)
