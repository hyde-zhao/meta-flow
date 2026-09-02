from __future__ import annotations

# ruff: noqa: I001, UP031

import json

from meta_flow.workflow import cr_index
from meta_flow.workflow import cr_cli
from meta_flow.state import current
from pathlib import Path
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from meta_flow.execution_control.exact_file_transaction import (
    ExactFileAuthorizationV1,
    acquire_shared_projection_writer_lock,
    release_shared_projection_writer_lock,
)


def _write_cr(root: Path, cr_id: str = "CR-101") -> Path:
    path = cr_index.resolve_runtime_ref(root, f"process/changes/{cr_id}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '---\nschema_version: 1\nkind: cr\ncr_id: "%s"\ncr_type: "architecture"\n'
        'title: "example"\nlifecycle_status: "active"\nreadiness_status: "NOT_READY"\n'
        'gate_status: "cp5_pending"\ngate_profile: "standard-code"\nconflict_keys: []\n'
        "impact_surface: []\nauthz_policy_refs: []\nrisk_refs: []\n---\n\n## 变更描述\n\nexample\n"
        % cr_id,
        encoding="utf-8",
    )
    return path


def _apply_typed_bootstrap(
    root: Path,
    *,
    cr_id: str,
    title: str,
    scope: str,
    gate_status: str = "not_started",
    readiness: str = "not_ready",
    rebuild_corrupt: bool = False,
) -> dict[str, Path]:
    """测试 helper 仍显式构造并提交 plan-bound authorization。"""

    plan = cr_index.plan_bootstrap_cr(
        root,
        cr_id=cr_id,
        title=title,
        scope=scope,
        gate_status=gate_status,
        readiness=readiness,
        rebuild_corrupt=rebuild_corrupt,
    )
    authorization = ExactFileAuthorizationV1(
        f"test-{cr_id.lower()}-{plan.plan_digest[:12]}",
        plan.exact_plan.operation,
        plan.plan_digest,
        plan.target_refs,
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    result = cr_index.apply_bootstrap_cr(root, plan, authorization)
    assert result["decision"] == "PASS"
    return dict(result["paths"])


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | str]]:
    snapshot: dict[str, tuple[str, bytes | str]] = {}
    for path in sorted(root.rglob("*")):
        ref = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[ref] = ("symlink", path.readlink().as_posix())
        elif path.is_file():
            snapshot[ref] = ("file", path.read_bytes())
        elif path.is_dir():
            snapshot[ref] = ("directory", b"")
    return snapshot


def _initialize_current(root: Path) -> None:
    """建立带稳定 route-binding 锁 anchor 的最小 process fixture。"""

    process = root / "process"
    process.mkdir(parents=True, exist_ok=True)
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: target-project\n"
        "repo_role: process\n"
        "route_mode: relative-symlink\n",
        encoding="utf-8",
    )
    current.write_current_state(
        root,
        current.default_current_state(root, project_id="target-project"),
    )


def _initialize_sibling_binding_current(root: Path) -> tuple[Path, Path]:
    """建立两个独立临时 Git 仓，供 authoritative route consumer 测试使用。"""

    release = root / "target-project"
    process = root / "target-project-process"
    release.mkdir()
    process.mkdir()
    for repository in (release, process):
        initialized = cr_index.run_git(["init", "-b", "main"], cwd=repository)
        assert initialized.ok, initialized.stderr
    binding = release / ".meta-flow/workspace.yaml"
    binding.parent.mkdir()
    binding.write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: target-project\n"
        "repo_role: release\n"
        "route_mode: sibling-binding\n"
        "process_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: target-project-process\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: target-project\n"
        "repo_role: process\n"
        "route_mode: sibling-binding\n"
        "release_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: target-project\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\n"
        "project_id: target-project\n"
        "name: Target Project\n"
        "status: active\n",
        encoding="utf-8",
    )
    current.write_current_state(
        release,
        current.default_current_state(release, project_id="target-project"),
    )
    return release, process


def test_index_owner_exports_frozen_nineteen_members() -> None:
    expected = {
        "CR_INDEX_REL",
        "INDEX_SCHEMA_VERSION",
        "_cr_numeric_sort_key",
        "_canonical_digest",
        "_dirty_path_digest",
        "_index_item",
        "_record_override",
        "_native_cr_minimum",
        "_validate_native_formal_cr",
        "build_index",
        "validate_index_payload",
        "plan_index",
        "write_index",
        "load_index",
        "_write_bootstrap_cr_file",
        "_update_current_active_change",
        "_write_cp0_result",
        "apply_bootstrap_cr",
        "close_cr",
    }
    assert {name for name in expected if hasattr(cr_index, name)} == expected


def test_index_payload_validation_rejects_invalid_shape() -> None:
    assert cr_index.validate_index_payload({"schema_version": 999})


def test_terminal_predecessor_inventory_and_rebuild_projection_are_closed() -> None:
    inventory_digest = cr_index._canonical_digest(["x"])
    receipt = {
        "cr_id": "CR-071",
        "predecessor_revision_id": "R1",
        "terminal_status": "verified",
        "inventory": ["x"],
        "inventory_digest": inventory_digest,
        "revision_bytes_digest": "b" * 64,
    }
    assert cr_index.load_terminal_predecessor_inventory(
        [receipt],
        cr_id="CR-071",
        predecessor_revision_id="R1",
        expected_digest=inventory_digest,
        expected_revision_bytes_digest="b" * 64,
    )["inventory"] == ["x"]
    revision = {
        "schema_version": 2,
        "cr_id": "CR-071",
        "work_id": "CR-071-R2",
        "revision_id": "R2",
        "predecessor_revision_id": "R1",
        "predecessor_revision_bytes_digest": "b" * 64,
        "scope_digest": "a" * 64,
        "previous_scope": ["old"],
        "scope": ["new", "old"],
        "invalidated_refs": [],
        "plan_digest": "c" * 64,
        "validation_graph_digest": "d" * 64,
    }
    assert cr_index.rebuild_scope_amend_index(revision) == {
        "cr_id": "CR-071",
        "work_id": "CR-071-R2",
        "revision_id": "R2",
        "scope_digest": "a" * 64,
        "plan_digest": "c" * 64,
        "validation_graph_digest": "d" * 64,
        "predecessor_revision_id": "R1",
    }


def test_index_build_validate_plan_and_write_owner_behaviour(tmp_path: Path) -> None:
    release, _process = _initialize_sibling_binding_current(tmp_path)
    _write_cr(release)
    built = cr_index.build_index(release)
    assert built["items"][0]["id"] == "CR-101"
    assert cr_index.validate_index_payload(built) == []
    plan = cr_index.plan_index(release)
    assert plan["decision"] == "READY"
    path = cr_index.write_index(release)
    assert cr_index.load_index(release)["semantic_digest"] == built["semantic_digest"]
    assert path == cr_index.resolve_runtime_ref(release, cr_index.CR_INDEX_REL.as_posix())


def test_index_close_owner_uses_injected_collaborators(tmp_path: Path) -> None:
    cr_path = _write_cr(tmp_path)
    paths = {
        "process/changes/CR-101.md": cr_path,
        "process/changes/summaries/CR-101.summary.json": tmp_path / "summary.json",
        "process/archive/CR-101/evidence-index.json": tmp_path / "evidence.json",
        "process/changes/CR-INDEX.json": tmp_path / "index.json",
        "process/state/CR-LEDGER.ndjson": tmp_path / "ledger.ndjson",
    }
    result = cr_index.close_cr(
        tmp_path,
        "CR-101",
        readiness="READY",
        work_id="W",
        effective_at="now",
        expected_process_oid="",
        expected_plan_digest="",
        authorization=None,
        plan_status_sync=Mock(return_value=object()),
        apply_status_sync=Mock(return_value={"status": "PASS", "paths": paths}),
        append_ledger_event=Mock(),
        resolve_runtime_ref=Mock(),
        rel=lambda _root, _path: "process/changes/CR-101.md",
        current_state_updater=Mock(),
        discover_formal_crs_fn=Mock(return_value={"CR-101": cr_path}),
    )
    assert result["cr"] == cr_path


def test_index_bootstrap_owner_writes_expected_artifacts(tmp_path: Path) -> None:
    _initialize_current(tmp_path)
    paths = _apply_typed_bootstrap(
        tmp_path, cr_id="CR-001", title="bootstrap", scope="scope"
    )
    assert paths["cr"].is_file()
    assert paths["index"].is_file()
    assert paths["cp0_result"].is_file()
    fields = cr_index.parse_frontmatter(paths["cr"].read_text(encoding="utf-8"))
    assert (
        fields["lifecycle_status"],
        fields["readiness_status"],
        fields["gate_status"],
        fields["gate_profile"],
    ) == ("candidate", "not_ready", "not_started", "standard-code")


def test_index_bootstrap_rejects_illegal_initial_tuple_before_write(tmp_path: Path) -> None:
    _initialize_current(tmp_path)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match="candidate/not_ready/not_started"):
        _apply_typed_bootstrap(
            tmp_path,
            cr_id="CR-001",
            title="bootstrap",
            scope="scope",
            readiness="READY",
            gate_status="cp2_pending",
        )

    assert not (tmp_path / "process/changes/CR-001.md").exists()
    assert {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before


def test_index_bootstrap_updates_healthy_index_without_rebuild(tmp_path: Path) -> None:
    release, _process = _initialize_sibling_binding_current(tmp_path)
    _write_cr(release, "CR-100")
    cr_index.write_index(release)

    paths = _apply_typed_bootstrap(
        release,
        cr_id="CR-101",
        title="bootstrap",
        scope="scope",
    )

    assert paths["cr"].is_file()
    assert [item["id"] for item in cr_index.load_index(release)["items"]] == [
        "CR-100",
        "CR-101",
    ]


def test_index_bootstrap_cp0_summary_rejects_symlink_without_overwriting_target(
    tmp_path: Path,
) -> None:
    _initialize_current(tmp_path)
    summary = tmp_path / "process/checks/CP0-CR-001-BOOTSTRAP.result.summary.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    victim = tmp_path / "victim.md"
    victim_bytes = b"do not overwrite\n"
    victim.write_bytes(victim_bytes)
    summary.symlink_to(victim)

    with pytest.raises(FileExistsError, match="CP0 summary target already exists"):
        _apply_typed_bootstrap(
            tmp_path,
            cr_id="CR-001",
            title="bootstrap",
            scope="scope",
        )

    assert summary.is_symlink()
    assert victim.read_bytes() == victim_bytes


def test_bootstrap_exact_transaction_interrupt_recover_and_fresh_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _initialize_current(tmp_path)
    before = {
        path.relative_to(tmp_path / "process").as_posix(): path.read_bytes()
        for path in (tmp_path / "process").rglob("*")
        if path.is_file() and ".meta-flow-runtime" not in path.parts
    }
    plan = cr_index.plan_bootstrap_cr(
        tmp_path,
        cr_id="CR-001",
        title="bootstrap",
        scope="scope",
    )
    assert plan.target_refs
    assert not (tmp_path / "process/changes/CR-001.md").exists()
    authorization = ExactFileAuthorizationV1(
        "bootstrap-cr001-interrupt",
        plan.exact_plan.operation,
        plan.plan_digest,
        plan.target_refs,
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    from meta_flow.execution_control import exact_file_transaction

    original = exact_file_transaction._replace_bytes
    fired = False

    def interrupt_after_replace(path: Path, content: bytes) -> None:
        nonlocal fired
        original(path, content)
        if not fired:
            fired = True
            raise KeyboardInterrupt

    monkeypatch.setattr(exact_file_transaction, "_replace_bytes", interrupt_after_replace)
    with pytest.raises(KeyboardInterrupt):
        cr_index.apply_bootstrap_cr(tmp_path, plan, authorization)
    assert cr_index.inspect_bootstrap_transactions(tmp_path)["decision"] == "BLOCKED"

    monkeypatch.setattr(exact_file_transaction, "_replace_bytes", original)
    recovery = cr_index.recover_bootstrap_transaction(
        tmp_path,
        authorization.authorization_id,
    )
    assert recovery["decision"] == "RECOVERED"
    assert cr_index.inspect_bootstrap_transactions(tmp_path)["decision"] == "PASS"
    assert {
        path.relative_to(tmp_path / "process").as_posix(): path.read_bytes()
        for path in (tmp_path / "process").rglob("*")
        if path.is_file() and ".meta-flow-runtime" not in path.parts
    } == before
    replay = cr_index.apply_bootstrap_cr(tmp_path, plan, authorization)
    assert replay["decision"] == "BLOCKED"
    assert replay["mutation_count"] == 0
    assert replay["reason_codes"] == ["EXACT_FILE_AUTHORIZATION_ALREADY_CONSUMED"]

    retry = cr_index.plan_bootstrap_cr(
        tmp_path,
        cr_id="CR-001",
        title="bootstrap",
        scope="scope",
    )
    retry_authorization = ExactFileAuthorizationV1(
        "bootstrap-cr001-retry",
        retry.exact_plan.operation,
        retry.plan_digest,
        retry.target_refs,
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    result = cr_index.apply_bootstrap_cr(tmp_path, retry, retry_authorization)
    assert result["decision"] == "PASS"
    assert set(result["planned_refs"]) == set(result["actual_mutation_refs"])
    inspection = cr_index.inspect_bootstrap_transactions(tmp_path)
    assert inspection["decision"] == "PASS"
    assert {item["classification"] for item in inspection["transactions"]} == {
        "COMMITTED",
        "SUPERSEDED",
    }


def test_bootstrap_plan_is_deterministic_for_frozen_effective_at(tmp_path: Path) -> None:
    _initialize_current(tmp_path)
    effective_at = "2030-01-01T00:00:00+00:00"

    first = cr_index.plan_bootstrap_cr(
        tmp_path,
        cr_id="CR-001",
        title="bootstrap",
        scope="scope",
        effective_at=effective_at,
    )
    second = cr_index.plan_bootstrap_cr(
        tmp_path,
        cr_id="CR-001",
        title="bootstrap",
        scope="scope",
        effective_at=effective_at,
    )

    assert first.as_dict() == second.as_dict()
    assert not (tmp_path / "process/changes/CR-001.md").exists()


def test_bootstrap_preview_copies_only_canonical_process_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _initialize_current(tmp_path)
    sentinel = tmp_path / "data-or-build/large-consumer-asset.bin"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"consumer-data-must-not-be-traversed")
    original = cr_index.shutil.copytree
    sources: list[Path] = []
    destinations: list[Path] = []

    def guarded_copytree(source, destination, *args, **kwargs):
        resolved = Path(source).resolve()
        sources.append(resolved)
        destinations.append(Path(destination))
        if resolved == tmp_path.resolve():
            raise AssertionError("bootstrap must not copy the release root")
        return original(source, destination, *args, **kwargs)

    monkeypatch.setattr(cr_index.shutil, "copytree", guarded_copytree)

    plan = cr_index.plan_bootstrap_cr(
        tmp_path,
        cr_id="CR-001",
        title="bootstrap",
        scope="scope",
        effective_at="2030-01-01T00:00:00+00:00",
    )

    assert plan.exact_plan.targets
    process_root = (tmp_path / "process").resolve()
    assert process_root in sources
    assert all(
        source == process_root
        or source.is_relative_to(process_root)
        or source == (tmp_path / ".meta-flow").resolve()
        or source.is_relative_to((tmp_path / ".meta-flow").resolve())
        for source in sources
    )
    assert all(destination.name != "process" for destination in destinations)
    assert tmp_path.resolve() not in sources
    assert sentinel.parent.resolve() not in sources
    assert sentinel.read_bytes() == b"consumer-data-must-not-be-traversed"


@pytest.mark.parametrize("failure_mode", ["preimage-drift", "held-lock", "unsafe-lock"])
def test_bootstrap_exact_admission_failure_is_typed_and_zero_write(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    _initialize_current(tmp_path)
    plan = cr_index.plan_bootstrap_cr(
        tmp_path,
        cr_id="CR-001",
        title="bootstrap",
        scope="scope",
        effective_at="2030-01-01T00:00:00+00:00",
    )
    authorization = ExactFileAuthorizationV1(
        f"bootstrap-admission-{failure_mode}",
        plan.exact_plan.operation,
        plan.plan_digest,
        plan.target_refs,
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    process = tmp_path / "process"
    held = None
    if failure_mode == "preimage-drift":
        target = next(item for item in plan.exact_plan.targets if item.before_exists)
        path = process / target.ref
        path.write_bytes(path.read_bytes() + b"\n")
    elif failure_mode == "held-lock":
        held = acquire_shared_projection_writer_lock(process, "test-held-bootstrap-lock")
    else:
        unsafe = process / ".meta-flow-process.yaml"
        unsafe.unlink()
        unsafe.mkdir()

    before = _tree_snapshot(process)
    try:
        result = cr_index.apply_bootstrap_cr(tmp_path, plan, authorization)
        assert result["decision"] == "BLOCKED"
        assert result["mutation_count"] == 0
        assert result["actual_mutation_refs"] == []
        assert _tree_snapshot(process) == before
        assert not (
            process
            / ".meta-flow-runtime/exact-file"
            / authorization.authorization_id
            / "manifest.json"
        ).exists()
    finally:
        if held is not None:
            release_shared_projection_writer_lock(held, "test-held-bootstrap-lock")


def test_exact_fresh_locked_preimage_failure_keeps_entire_tree_zero_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """outer admission 通过后，锁内 fresh 首读失败也不得创建 runtime。"""

    _initialize_current(tmp_path)
    plan = cr_index.plan_bootstrap_cr(
        tmp_path,
        cr_id="CR-001",
        title="bootstrap",
        scope="scope",
        effective_at="2030-01-01T00:00:00+00:00",
    )
    authorization = ExactFileAuthorizationV1(
        "bootstrap-fresh-locked-drift",
        plan.exact_plan.operation,
        plan.plan_digest,
        plan.target_refs,
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    from meta_flow.execution_control import exact_file_transaction

    original = exact_file_transaction._exact_preimage
    calls = 0
    outer_count = len(plan.exact_plan.targets)

    def fail_locked_first_read(root: Path, target) -> bytes:
        nonlocal calls
        calls += 1
        if calls == outer_count + 1:
            raise ValueError("injected locked preimage drift")
        return original(root, target)

    monkeypatch.setattr(exact_file_transaction, "_exact_preimage", fail_locked_first_read)
    process = tmp_path / "process"
    before = _tree_snapshot(process)

    result = cr_index.apply_bootstrap_cr(tmp_path, plan, authorization)

    assert result["decision"] == "BLOCKED"
    assert result["mutation_count"] == 0
    assert _tree_snapshot(process) == before
    assert calls == outer_count + 1


def test_shared_lock_survives_formal_target_atomic_replace(tmp_path: Path) -> None:
    """正式 target 换 inode 时，第二 writer 仍被稳定 route anchor 拒绝。"""

    _initialize_current(tmp_path)
    process = tmp_path / "process"
    target = process / "state/STATE.current.json"
    replacement = target.with_name(".STATE.current.replacement.json")
    replacement.write_bytes(target.read_bytes())
    held = acquire_shared_projection_writer_lock(process, "first-writer")
    try:
        replacement.replace(target)
        with pytest.raises(ValueError, match="already held"):
            acquire_shared_projection_writer_lock(process, "second-writer")
    finally:
        release_shared_projection_writer_lock(held, "first-writer")


def test_cr_bootstrap_cli_preview_requires_typed_authorization_and_applies(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _initialize_current(tmp_path)
    effective_at = "2030-01-01T00:00:00+00:00"
    base_args = [
        "bootstrap",
        "--id",
        "CR-001",
        "--title",
        "bootstrap",
        "--scope",
        "scope",
        "--effective-at",
        effective_at,
        "--project-root",
        str(tmp_path),
    ]

    assert cr_cli.main(base_args) == 0
    preview = json.loads(capsys.readouterr().out)
    direct = cr_index.plan_bootstrap_cr(
        tmp_path,
        cr_id="CR-001",
        title="bootstrap",
        scope="scope",
        effective_at=effective_at,
    )
    assert preview == direct.as_dict()
    assert preview["mutation_count"] == 0
    assert not (tmp_path / "process/changes/CR-001.md").exists()

    # CR-076 S02 FA8：bootstrap 授权面迁移 exactly-one 三参（文案变化，阻断语义不变）
    with pytest.raises(SystemExit, match="requires exactly one of --authorization-file"):
        cr_cli.main([*base_args, "--apply"])
    assert not (tmp_path / "process/changes/CR-001.md").exists()

    authorization = ExactFileAuthorizationV1(
        "bootstrap-cli-apply",
        direct.exact_plan.operation,
        direct.plan_digest,
        direct.target_refs,
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    authorization_file = tmp_path / "bootstrap-authorization.json"
    authorization_file.write_text(
        json.dumps(authorization.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert cr_cli.main(
        [*base_args, "--apply", "--authorization-file", str(authorization_file)]
    ) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["kind"] == "ExactFileTransactionReceiptV1"
    assert receipt["decision"] == "PASS"
    assert receipt["plan_digest"] == preview["plan_digest"]
    assert (tmp_path / "process/changes/CR-001.md").is_file()


def test_cr_bootstrap_cli_interrupt_is_inspectable_and_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _initialize_current(tmp_path)
    effective_at = "2030-01-01T00:00:00+00:00"
    plan = cr_index.plan_bootstrap_cr(
        tmp_path,
        cr_id="CR-001",
        title="bootstrap",
        scope="scope",
        effective_at=effective_at,
    )
    authorization = ExactFileAuthorizationV1(
        "bootstrap-cli-interrupt",
        plan.exact_plan.operation,
        plan.plan_digest,
        plan.target_refs,
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    authorization_file = tmp_path / "bootstrap-authorization.json"
    authorization_file.write_text(
        json.dumps(authorization.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    from meta_flow.execution_control import exact_file_transaction

    original = exact_file_transaction._replace_bytes
    fired = False

    def interrupt_after_replace(path: Path, content: bytes) -> None:
        nonlocal fired
        original(path, content)
        if not fired:
            fired = True
            raise KeyboardInterrupt

    monkeypatch.setattr(exact_file_transaction, "_replace_bytes", interrupt_after_replace)
    with pytest.raises(KeyboardInterrupt):
        cr_cli.main(
            [
                "bootstrap",
                "--id",
                "CR-001",
                "--title",
                "bootstrap",
                "--scope",
                "scope",
                "--effective-at",
                effective_at,
                "--project-root",
                str(tmp_path),
                "--apply",
                "--authorization-file",
                str(authorization_file),
            ]
        )

    assert cr_cli.main(["bootstrap-inspect", "--project-root", str(tmp_path)]) == 2
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["kind"] == "ExactFileTransactionInspectionV1"
    assert inspected["decision"] == "BLOCKED"
    monkeypatch.setattr(exact_file_transaction, "_replace_bytes", original)
    assert cr_cli.main(
        [
            "bootstrap-recover",
            "--transaction-id",
            authorization.authorization_id,
            "--project-root",
            str(tmp_path),
        ]
    ) == 0
    recovered = json.loads(capsys.readouterr().out)
    assert recovered["kind"] == "ExactFileRecoveryReceiptV1"
    assert recovered["decision"] == "RECOVERED"
    assert cr_cli.main(["bootstrap-inspect", "--project-root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "PASS"
    assert not (tmp_path / "process/changes/CR-001.md").exists()
