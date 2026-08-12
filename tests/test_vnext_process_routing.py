from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

from meta_flow import cli
from meta_flow.checks import cr_tracking, quality_governance
from meta_flow.context_pack import builder
from meta_flow.project.onboarding import (
    PROCESS_METADATA_REL,
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import (
    IndependentProcessRoute,
    ProcessRouteError,
    _resolve_runtime_ref,
    format_runtime_ref,
    require_process_route,
    require_project_process_route,
    resolve_ref_main,
)
from meta_flow.project.process_route_adapter import (
    RouteConsumerError,
    resolve_configured_consumer_route,
    resolve_consumer_route,
)
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.semantics.route import ROUTE_CONSUMER_POLICIES
from meta_flow.workflow import cr_lifecycle
from meta_flow.workspace.git_sync import push_workspace, workspace_repositories
from meta_flow.workspace.routing import inspect_legacy_consumer_route


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()


def _authorize(plan) -> OnboardingAuthorization:
    payload = plan.as_dict()
    return OnboardingAuthorization(
        schema_version=1,
        authorization_id=f"auth-{plan.plan_digest[:12]}",
        authorization_source=AUTHORIZATION_SOURCE,
        authorization_kind=AUTHORIZATION_KIND,
        operation=payload["operation"],
        decision_ref=payload["decision_ref"],
        project_id=payload["project_id"],
        plan_digest=payload["plan_digest"],
        expected_oids=payload["base_oids"],
        expires_at="2099-01-01T00:00:00+00:00",
    )


def _release(tmp_path: Path) -> tuple[Path, Path]:
    release = tmp_path / "demo"
    release.mkdir()
    _git(release, "init", "-b", "main")
    (release / "README.md").write_text("demo\n", encoding="utf-8")
    _git(release, "add", "README.md")
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
    apply_project_init(plan, _authorize(plan))
    return release, tmp_path / "demo-process"


def test_binding_only_route_resolves_process_ref_without_process_link(tmp_path: Path) -> None:
    release, process = _release(tmp_path)
    (process / "checks").mkdir()
    expected = process / "checks" / "CP0.json"

    route = require_process_route(release)

    assert not (release / "process").exists()
    assert route.process_root == process.resolve()
    assert route.resolve_ref("process/checks/CP0.json") == expected.resolve()
    assert route.source == ".meta-flow/workspace.yaml"


def test_route_formats_release_and_sibling_process_paths_as_canonical_refs(
    tmp_path: Path,
) -> None:
    release, process = _release(tmp_path)
    result_path = process / "checks" / "CP2-CR-069.result.json"
    result_path.parent.mkdir()
    result_path.write_text("{}\n", encoding="utf-8")
    alias_path = process / "result-alias.json"
    alias_path.symlink_to(result_path.relative_to(process))

    route = require_process_route(release)

    assert route.format_ref(release / "README.md") == "README.md"
    assert route.format_ref(result_path) == "process/checks/CP2-CR-069.result.json"
    assert route.format_ref(alias_path) == "process/checks/CP2-CR-069.result.json"
    assert format_runtime_ref(release, result_path) == "process/checks/CP2-CR-069.result.json"


@pytest.mark.parametrize("root_kind", ["release", "process"])
def test_route_formatter_rejects_repository_roots(
    tmp_path: Path,
    root_kind: str,
) -> None:
    release, process = _release(tmp_path)
    route = require_process_route(release)

    with pytest.raises(ProcessRouteError) as raised:
        route.format_ref(release if root_kind == "release" else process)

    assert raised.value.error_code == "logical_ref_invalid"


def test_route_formatter_rejects_paths_outside_both_repositories(tmp_path: Path) -> None:
    release, _process = _release(tmp_path)
    outside = tmp_path / "outside.txt"

    with pytest.raises(ProcessRouteError) as raised:
        require_process_route(release).format_ref(outside)

    assert raised.value.error_code == "logical_ref_escape"


def test_sibling_binding_consumers_share_canonical_formatter_without_relative_to_crash(
    tmp_path: Path,
) -> None:
    release, process = _release(tmp_path)
    checks = process / "checks"
    changes = process / "changes"
    summaries = changes / "summaries"
    archive = process / "archive" / "CR-069"
    stories = process / "stories"
    evidence = process / "evidence"
    for directory in (checks, summaries, archive, stories, evidence):
        directory.mkdir(parents=True, exist_ok=True)

    cp2_path = checks / "CP2-CR-069.result.json"
    cp2_path.write_text(
        json.dumps(
            {
                "cr_id": "CR-069",
                "commitments": {
                    "required_evidence": [{"id": "EV-R2", "required": True}]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (changes / "CR-069.md").write_text("# CR-069\n", encoding="utf-8")
    (summaries / "CR-069.summary.json").write_text("{}\n", encoding="utf-8")
    (archive / "evidence-index.json").write_text("{}\n", encoding="utf-8")
    (stories / "STORY-ST-EI-069-IMPLEMENTATION.md").write_text(
        "# implementation\n", encoding="utf-8"
    )
    (evidence / "ST-EI-069.index.json").write_text("{}\n", encoding="utf-8")

    required = builder._required_evidence_from_cp2(release, "CR-069")
    _results, errors, warnings = quality_governance._load_cp_results(release)
    manifest = cr_tracking.build_protected_object_manifest(
        release,
        cr_id="CR-069",
        story_id="ST-EI-069",
    )

    assert required[0]["source_result_ref"] == "process/checks/CP2-CR-069.result.json"
    assert any("process/checks/CP2-CR-069.result.json" in item for item in [*errors, *warnings])
    object_refs = {item["path"] for item in manifest["objects"]}
    assert "process/checks/CP2-CR-069.result.json" in object_refs
    assert "process/stories/STORY-ST-EI-069-IMPLEMENTATION.md" in object_refs
    assert "process/evidence/ST-EI-069.index.json" in object_refs
    assert not any(str(process.resolve()) in ref for ref in object_refs)


def test_mutation_route_binds_explicit_project_id(tmp_path: Path) -> None:
    release, _process = _release(tmp_path)

    assert require_project_process_route(release, project_id="demo").project_id == "demo"
    with pytest.raises(ProcessRouteError) as raised:
        require_project_process_route(release, project_id="other")
    assert raised.value.error_code == "route_project_mismatch"


@pytest.mark.parametrize(
    "logical_ref",
    [
        "",
        "PROJECT.yaml",
        "process",
        "process/",
        "process//PROJECT.yaml",
        "process/./PROJECT.yaml",
        "process/../outside",
        "/process/PROJECT.yaml",
        "C:/process/PROJECT.yaml",
        "C:\\process\\PROJECT.yaml",
        "\\\\server\\share\\PROJECT.yaml",
        "process\\PROJECT.yaml",
        "process/a:b",
        "process/a\x00b",
    ],
)
def test_logical_ref_negative_cases_fail_closed(tmp_path: Path, logical_ref: str) -> None:
    release, _process = _release(tmp_path)

    with pytest.raises(ProcessRouteError) as raised:
        require_process_route(release).resolve_ref(logical_ref)

    assert raised.value.error_code == "logical_ref_invalid"


def test_existing_intermediate_symlink_cannot_escape_process_repo(tmp_path: Path) -> None:
    release, process = _release(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (process / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ProcessRouteError) as raised:
        require_process_route(release).resolve_ref("process/escape/secret.txt")

    assert raised.value.error_code == "logical_ref_escape"


def test_missing_and_invalid_binding_have_stable_error_codes(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    missing.mkdir()
    with pytest.raises(ProcessRouteError) as not_initialized:
        require_process_route(missing)
    assert not_initialized.value.error_code == "route_not_initialized"

    release, _process = _release(tmp_path)
    (release / ".meta-flow" / "workspace.yaml").write_text("not: [valid\n", encoding="utf-8")
    with pytest.raises(ProcessRouteError) as invalid:
        require_process_route(release)
    assert invalid.value.error_code == "route_invalid"


def test_git_runtime_cannot_fallback_to_legacy_process_symlink(tmp_path: Path) -> None:
    release, process = _release(tmp_path)
    binding = release / ".meta-flow" / "workspace.yaml"
    binding.unlink()
    (release / "process").symlink_to("../demo-process", target_is_directory=True)
    project_before = (process / "PROJECT.yaml").read_bytes()

    with pytest.raises(ProcessRouteError) as raised:
        _resolve_runtime_ref(release, "process/PROJECT.yaml")

    assert raised.value.error_code == "route_not_initialized"
    assert (process / "PROJECT.yaml").read_bytes() == project_before


def test_bidirectional_binding_conflict_blocks_before_target_io(tmp_path: Path) -> None:
    release, process = _release(tmp_path)
    metadata_path = process / PROCESS_METADATA_REL
    metadata = load_yaml_object(metadata_path)
    metadata["release_repo"]["relative_path"] = "other-release"
    metadata_path.write_text(dump_yaml(metadata) + "\n", encoding="utf-8")

    with pytest.raises(ProcessRouteError) as raised:
        require_process_route(release)

    assert raised.value.error_code == "route_conflict"


def test_resolve_ref_cli_json_contract_and_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release, process = _release(tmp_path)

    code = resolve_ref_main(
        [
            "--project-root",
            str(release),
            "--logical-ref",
            "process/PROJECT.yaml",
            "--format",
            "json",
        ]
    )
    success = json.loads(capsys.readouterr().out)
    assert code == 0
    assert success == {
        "schema_version": 1,
        "ok": True,
        "project_id": "demo",
        "layout_version": "independent-process-repo-v1",
        "route_mode": "sibling-binding",
        "logical_ref": "process/PROJECT.yaml",
        "resolved_path": str((process / "PROJECT.yaml").resolve()),
    }

    blocked_code = resolve_ref_main(
        ["--project-root", str(release), "--logical-ref", "process/../outside"]
    )
    blocked = json.loads(capsys.readouterr().out)
    assert blocked_code == 2
    assert blocked["ok"] is False
    assert blocked["error_code"] == "logical_ref_invalid"


def test_top_level_project_dispatch_exposes_resolve_ref(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release, _process = _release(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli._run_project(
            [
                "resolve-ref",
                "--project-root",
                str(release),
                "--logical-ref",
                "process/PROJECT.yaml",
            ]
        )

    assert raised.value.code == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_cr_tracking_main_uses_binding_only_route_without_process_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release, process = _release(tmp_path)
    changes = process / "changes"
    changes.mkdir()
    (changes / "CR-INDEX.json").write_text(
        json.dumps(cr_lifecycle.build_index(release), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    code = cr_tracking.main(["--project-root", str(release)])
    captured = capsys.readouterr()

    assert code == 0
    assert "OK" in captured.out
    assert "process_link_health" not in captured.err
    assert not (release / "process").exists()


def test_cr_tracking_main_fails_closed_when_binding_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release, _process = _release(tmp_path)
    (release / ".meta-flow" / "workspace.yaml").unlink()

    code = cr_tracking.main(["--project-root", str(release)])
    captured = capsys.readouterr()

    assert code == 2
    assert "BLOCKED: route_not_initialized" in captured.err
    assert "workspace link" not in captured.err


def _adapter_route(tmp_path: Path, *, mode: str = "sibling-binding") -> IndependentProcessRoute:
    return IndependentProcessRoute(
        project_root=tmp_path / "release",
        process_root=tmp_path / "process",
        project_id="demo",
        layout_version="independent-process-repo-v1",
        route_mode=mode,
        source=".meta-flow/workspace.yaml",
    )


def test_route_consumer_adapter_projects_canonical_route_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from meta_flow.project import process_route_adapter

    route = _adapter_route(tmp_path)
    calls = 0

    def provider(project_root: Path) -> IndependentProcessRoute:
        nonlocal calls
        calls += 1
        assert project_root == tmp_path
        return route

    monkeypatch.setattr(process_route_adapter, "require_process_route", provider)

    view = resolve_consumer_route(tmp_path, consumer_id="workspace-check")

    assert calls == 1
    assert view.consumer_id == "workspace-check"
    assert view.project_id == route.project_id
    assert view.project_root is route.project_root
    assert view.process_root is route.process_root
    assert view.route_mode == route.route_mode
    assert view.source == route.source
    assert view.classification == "canonical-binding-read"
    assert view.status == "healthy"
    assert view.blocking is False


@pytest.mark.parametrize(
    "provider_code, expected_code",
    [
        ("route_not_initialized", "route_not_initialized"),
        ("route_invalid", "route_invalid"),
        ("process_repo_missing", "process_repo_missing"),
        ("route_conflict", "route_conflict"),
        ("route_project_mismatch", "route_project_mismatch"),
        ("logical_ref_invalid", "logical_ref_invalid"),
    ],
)
def test_route_consumer_adapter_normalizes_known_provider_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_code: str,
    expected_code: str,
) -> None:
    from meta_flow.project import process_route_adapter

    def provider(_project_root: Path) -> IndependentProcessRoute:
        raise ProcessRouteError(provider_code, "provider failed")

    monkeypatch.setattr(process_route_adapter, "require_process_route", provider)

    with pytest.raises(RouteConsumerError) as raised:
        resolve_consumer_route(tmp_path, consumer_id="workspace-check")

    assert raised.value.code == expected_code
    assert raised.value.blocking is True
    assert isinstance(raised.value.cause, ProcessRouteError)


def test_route_consumer_adapter_fails_closed_for_unknown_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from meta_flow.project import process_route_adapter

    def provider(_project_root: Path) -> IndependentProcessRoute:
        raise RuntimeError("harness unavailable")

    monkeypatch.setattr(process_route_adapter, "require_process_route", provider)

    with pytest.raises(RouteConsumerError) as raised:
        resolve_consumer_route(tmp_path, consumer_id="workspace-check")

    assert raised.value.code == "route_provider_unavailable"
    assert isinstance(raised.value.cause, RuntimeError)


@pytest.mark.parametrize("consumer_id", ["", "UPPER", "two words", "consumer/"])
def test_route_consumer_adapter_rejects_invalid_consumer_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, consumer_id: str
) -> None:
    from meta_flow.project import process_route_adapter

    def provider(_project_root: Path) -> IndependentProcessRoute:
        pytest.fail("invalid consumer_id must not invoke the canonical provider")

    monkeypatch.setattr(process_route_adapter, "require_process_route", provider)

    with pytest.raises(RouteConsumerError) as raised:
        resolve_consumer_route(tmp_path, consumer_id=consumer_id)

    assert raised.value.code == "route_consumer_invalid"


def test_route_consumer_adapter_rejects_unexpected_mode_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from meta_flow.project import process_route_adapter

    def provider(_project_root: Path) -> IndependentProcessRoute:
        pytest.fail("unsupported expected mode must not invoke the canonical provider")

    monkeypatch.setattr(process_route_adapter, "require_process_route", provider)

    with pytest.raises(RouteConsumerError) as raised:
        resolve_consumer_route(
            tmp_path, consumer_id="workspace-check", expected_mode="relative-symlink"
        )

    assert raised.value.code == "route_mode_unexpected"


def test_route_consumer_adapter_rejects_resolved_mode_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from meta_flow.project import process_route_adapter

    monkeypatch.setattr(
        process_route_adapter,
        "require_process_route",
        lambda _project_root: _adapter_route(tmp_path, mode="relative-symlink"),
    )

    with pytest.raises(RouteConsumerError) as raised:
        resolve_consumer_route(tmp_path, consumer_id="workspace-check")

    assert raised.value.code == "route_mode_unexpected"


def test_route_consumer_adapter_view_is_immutable_and_has_no_legacy_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import FrozenInstanceError

    from meta_flow.project import process_route_adapter

    monkeypatch.setattr(
        process_route_adapter,
        "require_process_route",
        lambda _project_root: _adapter_route(tmp_path),
    )
    view = resolve_consumer_route(tmp_path, consumer_id="workspace-check")

    with pytest.raises(FrozenInstanceError):
        view.consumer_id = "other"  # type: ignore[misc]

    source = Path(process_route_adapter.__file__).read_text(encoding="utf-8")
    assert "meta_flow.workspace" not in source
    assert "meta_flow.checks" not in source
    assert "meta_flow.cli" not in source
    assert "check_process_route" not in source


def test_route_semantic_kernel_owns_all_seven_direct_consumers() -> None:
    assert set(ROUTE_CONSUMER_POLICIES) == {
        "require-process-health",
        "legacy-workspace-link-postcheck",
        "legacy-workspace-bootstrap-postcheck",
        "workspace-git-discovery",
        "adoption-readiness",
        "workspace-doctor",
        "workspace-check",
    }
    assert {
        key
        for key, policy in ROUTE_CONSUMER_POLICIES.items()
        if policy.vnext_read
    } == {
        "workspace-git-discovery",
        "adoption-readiness",
        "workspace-doctor",
        "workspace-check",
    }


def test_legacy_gateway_rejects_unknown_consumer_and_binding_downgrade(
    tmp_path: Path,
) -> None:
    release, _process = _release(tmp_path)

    with pytest.raises(ValueError, match="unregistered route consumer"):
        inspect_legacy_consumer_route(release, consumer_id="unknown-consumer")
    with pytest.raises(ValueError, match="canonical binding route adapter"):
        inspect_legacy_consumer_route(release, consumer_id="workspace-check")


def test_all_seven_route_callers_use_classified_gateway_not_low_level_checker() -> None:
    package_root = Path(cli.__file__).resolve().parent
    gateway_calls: list[tuple[Path, ast.Call]] = []
    low_level_calls: list[tuple[Path, ast.Call]] = []
    for source_path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else ""
            )
            if name == "inspect_legacy_consumer_route":
                gateway_calls.append((source_path, node))
            elif name == "check_process_route":
                low_level_calls.append((source_path, node))

    assert low_level_calls == []
    assert len(gateway_calls) == 7


def test_logical_ref_consumers_do_not_reimplement_canonical_formatter() -> None:
    package_root = Path(cli.__file__).resolve().parent
    consumer_refs = (
        "checks/cp_result.py",
        "checks/cr_tracking.py",
        "context_pack/builder.py",
        "context_pack/story_contract.py",
        "workflow/cr_records.py",
        "workflow/story_evidence.py",
    )

    for relative in consumer_refs:
        source = (package_root / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        local_formatters = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in {"_canonical_runtime_ref", "format_rel"}
        }
        assert local_formatters == set(), relative


def test_configured_route_returns_none_only_for_explicit_legacy_workspace(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    assert (
        resolve_configured_consumer_route(legacy, consumer_id="workspace-check")
        is None
    )


def test_workspace_check_and_git_discovery_use_sibling_binding_without_link(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release, process = _release(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli._run_workspace(["check", "--project-root", str(release)])

    captured = capsys.readouterr()
    assert raised.value.code == 0
    assert "process_route_health: healthy" in captured.out
    assert "route_mode: sibling-binding" in captured.out
    assert "process path is missing" not in captured.out
    assert not (release / "process").exists()

    repos, warnings = workspace_repositories(release)
    by_label = {repo.label: repo for repo in repos}
    assert warnings == []
    assert by_label["project"].root == release
    assert by_label["process"].root == process
    assert by_label["project"].is_git_repo is True
    assert by_label["process"].is_git_repo is True


def test_workspace_push_dry_run_uses_sibling_binding_repository_discovery(
    tmp_path: Path,
) -> None:
    release, process = _release(tmp_path)
    release_remote = tmp_path / "release.git"
    process_remote = tmp_path / "process.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(release_remote)],
        text=True,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(process_remote)],
        text=True,
        capture_output=True,
        check=True,
    )
    _git(release, "remote", "add", "origin", str(release_remote))
    _git(process, "remote", "add", "origin", str(process_remote))
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
    process_branch = _git(process, "branch", "--show-current")
    _git(release, "push", "-u", "origin", "main")
    _git(process, "push", "-u", "origin", process_branch)

    status, lines = push_workspace(release, dry_run=True, allow_dirty=True)

    assert status == 0
    assert any("- project: git push --dry-run origin main" in line for line in lines)
    assert any(
        f"- process: git push --dry-run origin {process_branch}" in line
        for line in lines
    )
    assert not (release / "process").exists()


def test_workspace_push_mutation_stays_blocked_for_sibling_binding(
    tmp_path: Path,
) -> None:
    release, _process = _release(tmp_path)

    status, lines = push_workspace(release, dry_run=False, allow_dirty=True)

    assert status == 2
    assert any("canonical repository push" in line for line in lines)


def test_adoption_readiness_recognizes_sibling_binding_without_link(
    tmp_path: Path,
) -> None:
    from meta_flow.checks import adoption_readiness

    release, process = _release(tmp_path)
    items = adoption_readiness.collect_adoption_readiness(release)
    workspace_item = next(item for item in items if item.item_id == "workspace-route")

    assert workspace_item.status == "PASS"
    assert any("route_mode=sibling-binding" in message for message in workspace_item.messages)
    assert any(str(process) in message for message in workspace_item.messages)
    assert not (release / "process").exists()
    native_items = {
        item.item_id: item
        for item in items
        if item.item_id
        in {"state-v2", "workflow-ledgers", "human-gate-readiness"}
    }
    assert "meta-flow state init" in native_items["state-v2"].next_action
    assert "meta-flow state init" in native_items["workflow-ledgers"].next_action
    assert "meta-flow cr bootstrap" in native_items[
        "human-gate-readiness"
    ].next_action
    assert "meta-flow context build" in native_items[
        "human-gate-readiness"
    ].next_action
    assert "meta-flow check human-gate" in native_items[
        "human-gate-readiness"
    ].next_action
    assert all(
        "workspace bootstrap" not in item.next_action for item in native_items.values()
    )
