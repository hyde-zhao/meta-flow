from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from meta_flow import cli
from meta_flow.checks import cr_tracking
from meta_flow.project.onboarding import (
    PROCESS_METADATA_REL,
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.process_route import (
    ProcessRouteError,
    _resolve_runtime_ref,
    require_process_route,
    resolve_ref_main,
)
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.workflow import cr_lifecycle


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()


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
    apply_project_init(
        plan_project_init(ProjectInitRequest(release, "demo", "Demo"))
    )
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
