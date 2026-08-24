"""CR-075 MF-BUG-16：bootstrap/exact plan 的 .git 命名空间三层排除。

第一层：fixture copy ignore（既有）。
第二层：plan_bootstrap_cr rglob 收集排除 .git/**（新增）。
第三层：apply_exact_file_plan 对 .git target typed BLOCKED（新增）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from meta_flow.execution_control.exact_file_transaction import (
    ExactFileAuthorizationV1,
    ExactFilePlanV1,
    ExactFileTargetV1,
    apply_exact_file_plan,
    build_exact_file_plan,
)


def _process_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """最小 sibling-binding fixture：release + process 双独立 Git 仓。"""

    from meta_flow.workflow.cr_index import run_git

    release = tmp_path / "fixture-release"
    process = tmp_path / "fixture-release-process"
    release.mkdir(parents=True)
    process.mkdir(parents=True)
    for repository in (release, process):
        initialized = run_git(["init", "-b", "main"], cwd=repository)
        assert initialized.ok, initialized.stderr
    (release / ".meta-flow").mkdir()
    (release / ".meta-flow" / "workspace.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture-project\n"
        "repo_role: release\n"
        "route_mode: sibling-binding\n"
        "process_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: fixture-release-process\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture-project\n"
        "repo_role: process\n"
        "route_mode: sibling-binding\n"
        "release_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: fixture-release\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\n"
        "project_id: fixture-project\n"
        "name: Fixture Project\n"
        "status: active\n",
        encoding="utf-8",
    )
    from meta_flow.state import current

    current.write_current_state(
        release,
        current.default_current_state(release, project_id="fixture-project"),
    )
    return release, process


def test_git_exclusion_second_layer_bootstrap_plan_excludes_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """plan_bootstrap_cr 的 exact plan targets 不含 .git/**（含 staging init 泄漏场景）。"""

    from meta_flow.workflow import cr_index

    release, process = _process_fixture(tmp_path)

    # 模拟 MF-BUG-16 现场：staging 内 process 仓已有 .git/config（git init 产物）。
    original_copy = cr_index._copy_bootstrap_fixture

    def copy_with_git_leak(project_root: Path, staging_root: Path) -> Path:
        staged = original_copy(project_root, staging_root)
        (staged / ".git").mkdir(exist_ok=True)
        (staged / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        return staged

    monkeypatch.setattr(cr_index, "_copy_bootstrap_fixture", copy_with_git_leak)

    plan = cr_index.plan_bootstrap_cr(
        release,
        cr_id="CR-900",
        title="git exclusion probe",
        scope="meta_flow/**",
    )

    git_refs = [ref for ref in plan.exact_plan.target_refs if ".git" in Path(ref).parts]
    assert git_refs == [], f"bootstrap plan leaked .git refs: {git_refs}"


def test_git_exclusion_third_layer_apply_blocks_git_target(tmp_path: Path) -> None:
    """apply_exact_file_plan 对 .git/ target typed BLOCKED，mutation=0。"""

    release, process = _process_fixture(tmp_path)
    (process / ".git").mkdir(exist_ok=True)
    original_config = "[core]\n\trepositoryformatversion = 0\n"
    (process / ".git" / "config").write_text(original_config, encoding="utf-8")

    target = ExactFileTargetV1(
        ".git/config",
        True,
        __import__("hashlib").sha256(original_config.encode()).hexdigest(),
        b"[core]\n\tleaked = true\n",
        __import__("hashlib").sha256(b"[core]\n\tleaked = true\n").hexdigest(),
    )
    plan = build_exact_file_plan(
        "cr.bootstrap",
        (target,),
        semantic_binding_digest="0" * 64,
    )
    authorization = ExactFileAuthorizationV1(
        "AUTH-CR075-GIT-EXCLUSION-20260824-001",
        "cr.bootstrap",
        plan.plan_digest,
        plan.target_refs,
        "2999-01-01T00:00:00Z",
    )

    receipt = apply_exact_file_plan(process, plan, authorization)

    assert receipt["decision"] == "BLOCKED"
    assert receipt["reason_codes"] == ["EXACT_FILE_GIT_NAMESPACE_FORBIDDEN"]
    assert receipt["mutation_count"] == 0
    # 真实 .git/config bytes 零变化。
    assert (process / ".git" / "config").read_text(encoding="utf-8") == original_config


def test_git_exclusion_nested_git_dir_is_blocked(tmp_path: Path) -> None:
    """深嵌套 .git 目录（如 process/archive/x/.git/HEAD）同样被 apply deny。"""

    import hashlib

    release, process = _process_fixture(tmp_path)
    nested = process / "archive" / "CR-901"
    nested.mkdir(parents=True)
    (nested / ".git").mkdir()
    head = b"ref: refs/heads/main\n"
    (nested / ".git" / "HEAD").write_bytes(head)

    target = ExactFileTargetV1(
        "archive/CR-901/.git/HEAD",
        True,
        hashlib.sha256(head).hexdigest(),
        b"ref: refs/heads/evil\n",
        hashlib.sha256(b"ref: refs/heads/evil\n").hexdigest(),
    )
    plan = build_exact_file_plan("cr.bootstrap", (target,), semantic_binding_digest="1" * 64)
    authorization = ExactFileAuthorizationV1(
        "AUTH-CR075-GIT-EXCLUSION-20260824-002",
        "cr.bootstrap",
        plan.plan_digest,
        plan.target_refs,
        "2999-01-01T00:00:00Z",
    )

    receipt = apply_exact_file_plan(process, plan, authorization)

    assert receipt["decision"] == "BLOCKED"
    assert receipt["reason_codes"] == ["EXACT_FILE_GIT_NAMESPACE_FORBIDDEN"]
    assert (nested / ".git" / "HEAD").read_bytes() == head


def test_git_exclusion_normal_targets_still_apply(tmp_path: Path) -> None:
    """非 .git target 的 apply 语义不受 deny 守卫影响（守卫不误伤）。"""

    release, process = _process_fixture(tmp_path)
    import hashlib

    before = (process / "PROJECT.yaml").read_bytes()
    after = before + b"version: 2\n"
    target = ExactFileTargetV1(
        "PROJECT.yaml",
        True,
        hashlib.sha256(before).hexdigest(),
        after,
        hashlib.sha256(after).hexdigest(),
    )
    plan = build_exact_file_plan("cr.bootstrap", (target,), semantic_binding_digest="2" * 64)
    authorization = ExactFileAuthorizationV1(
        "AUTH-CR075-GIT-EXCLUSION-20260824-003",
        "cr.bootstrap",
        plan.plan_digest,
        plan.target_refs,
        "2999-01-01T00:00:00Z",
    )

    receipt = apply_exact_file_plan(process, plan, authorization)

    assert receipt["decision"] == "PASS"
    assert (process / "PROJECT.yaml").read_bytes() == after
