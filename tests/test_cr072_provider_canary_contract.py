from __future__ import annotations

import json
import runpy
from hashlib import sha256
from pathlib import Path

from meta_flow.installation.artifact import (
    build_provider_release_asset_set,
    sidecar_path_for_receipt,
)

ROOT = Path(__file__).parents[1]
CANARY = runpy.run_path(
    str(ROOT / "scripts/run_provider_artifact_canary.py"),
    run_name="__cr072_provider_canary_test__",
)


def _published_shape(tmp_path: Path) -> tuple[dict[str, object], dict[str, Path]]:
    assets = build_provider_release_asset_set("0.6.1")
    wheel = tmp_path / assets.wheel_filename
    sdist = tmp_path / assets.sdist_filename
    receipt = tmp_path / assets.receipt_filename
    sidecar = sidecar_path_for_receipt(receipt)
    harness = tmp_path / "core_lifecycle_dogfood.py"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    receipt.write_text("{}\n", encoding="utf-8")
    sidecar.write_text("{}\n", encoding="utf-8")
    harness.write_text("# isolated harness\n", encoding="utf-8")
    payload: dict[str, object] = {
        "distribution_version": "0.6.1",
        "artifact_filename": assets.wheel_filename,
        "artifact_sha256": sha256(b"wheel").hexdigest(),
        "receipt_digest": "a" * 64,
        "release_qualifying": True,
    }
    return payload, {
        "wheel": wheel,
        "sdist": sdist,
        "receipt": receipt,
        "sidecar": sidecar,
        "harness": harness,
    }


def test_clean_home_canary_uses_four_assets_and_public_cli(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    receipt, paths = _published_shape(tmp_path)
    environments: list[dict[str, str]] = []
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        environment: dict[str, str],
    ) -> str:
        commands.append(command)
        environments.append(environment.copy())
        assert cwd != ROOT
        if command[0] == "uv":
            return ""
        if command[0].endswith("meta-flow") and command[1] == "version":
            return json.dumps(
                {
                    "distribution_version": "0.6.1",
                    "status": "READY",
                    "provider_admission": {"decision": "READY"},
                }
            )
        if command[0].endswith("meta-flow") and command[1] == "install":
            return ""
        if "observe_provider_runtime_identity" in command[-1]:
            venv = Path(command[0]).parents[1]
            return json.dumps(
                {
                    "module_path": str(venv / "lib/meta_flow/__init__.py"),
                    "identity_digest": "b" * 64,
                    "release_readiness": {"decision": "PASS"},
                }
            )
        return json.dumps(
            {
                "decision": "PASS",
                "route_mode": "sibling-binding",
                "close_order": ["child", "parent"],
            }
        )

    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    monkeypatch.setenv("PYTHONHOME", str(ROOT / "fake-python"))
    monkeypatch.setenv("META_FLOW_SOURCE", str(ROOT))
    monkeypatch.setitem(
        CANARY["main"].__globals__,
        "load_provider_artifact_receipt",
        lambda _path: receipt,
    )
    monkeypatch.setitem(CANARY["main"].__globals__, "_run", fake_run)

    exit_code = CANARY["main"](
        [
            "--wheel",
            str(paths["wheel"]),
            "--sdist",
            str(paths["sdist"]),
            "--receipt",
            str(paths["receipt"]),
            "--harness",
            str(paths["harness"]),
            "--output",
            str(tmp_path / "canary-result.json"),
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result == json.loads((tmp_path / "canary-result.json").read_text(encoding="utf-8"))
    assert result["exit_code"] == 0
    assert result["decision"] == "PASS"
    assert result["provider_checkout_imported"] is False
    assert result["source_fallback_count"] == 0
    assert result["public_version_status"] == "READY"
    assert result["sdist_sha256"] == sha256(b"sdist").hexdigest()
    assert any(command[0].endswith("meta-flow") and command[1] == "version" for command in commands)
    assert any(command[0].endswith("meta-flow") and command[1] == "install" for command in commands)
    for environment in environments:
        assert "PYTHONPATH" not in environment
        assert "PYTHONHOME" not in environment
        assert "META_FLOW_SOURCE" not in environment
        assert environment["HOME"] != str(Path.home())
        assert environment["META_FLOW_PROVIDER_RECEIPT"] == str(paths["receipt"])


def test_release_canary_requires_sdist_and_fails_closed_on_symlink(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    receipt, paths = _published_shape(tmp_path)
    monkeypatch.setitem(
        CANARY["main"].__globals__,
        "load_provider_artifact_receipt",
        lambda _path: receipt,
    )

    missing_sdist = CANARY["main"](
        [
            "--wheel",
            str(paths["wheel"]),
            "--receipt",
            str(paths["receipt"]),
            "--harness",
            str(paths["harness"]),
            "--output",
            str(tmp_path / "missing-sdist-result.json"),
        ]
    )
    assert missing_sdist == 1
    missing_result = json.loads(capsys.readouterr().out)
    assert "requires the canonical sdist" in missing_result["error"]
    assert missing_result["exit_code"] == 1
    assert missing_result == json.loads(
        (tmp_path / "missing-sdist-result.json").read_text(encoding="utf-8")
    )

    paths["sdist"].unlink()
    victim = tmp_path / "victim.tar.gz"
    victim.write_bytes(b"do not follow")
    paths["sdist"].symlink_to(victim)
    unsafe_sdist = CANARY["main"](
        [
            "--wheel",
            str(paths["wheel"]),
            "--sdist",
            str(paths["sdist"]),
            "--receipt",
            str(paths["receipt"]),
            "--harness",
            str(paths["harness"]),
            "--output",
            str(tmp_path / "unsafe-sdist-result.json"),
        ]
    )
    assert unsafe_sdist == 1
    unsafe_result = json.loads(capsys.readouterr().out)
    assert "sdist path is unsafe" in unsafe_result["error"]
    assert unsafe_result["exit_code"] == 1
    assert victim.read_bytes() == b"do not follow"


def test_missing_public_version_cli_is_deterministically_blocked(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    receipt, paths = _published_shape(tmp_path)

    def fail_public_cli(
        command: list[str],
        *,
        cwd: Path,
        environment: dict[str, str],
    ) -> str:
        del cwd, environment
        if command[0] == "uv":
            return ""
        if "observe_provider_runtime_identity" in command[-1]:
            venv = Path(command[0]).parents[1]
            return json.dumps(
                {
                    "module_path": str(venv / "lib/meta_flow/__init__.py"),
                    "identity_digest": "b" * 64,
                    "release_readiness": {"decision": "PASS"},
                }
            )
        raise ValueError("public meta-flow version CLI is unavailable")

    monkeypatch.setitem(
        CANARY["main"].__globals__,
        "load_provider_artifact_receipt",
        lambda _path: receipt,
    )
    monkeypatch.setitem(CANARY["main"].__globals__, "_run", fail_public_cli)

    exit_code = CANARY["main"](
        [
            "--wheel",
            str(paths["wheel"]),
            "--sdist",
            str(paths["sdist"]),
            "--receipt",
            str(paths["receipt"]),
            "--harness",
            str(paths["harness"]),
            "--output",
            str(tmp_path / "missing-cli-result.json"),
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert result["decision"] == "BLOCKED"
    assert result["error"] == "public meta-flow version CLI is unavailable"
    assert result["exit_code"] == 1
    assert result == json.loads(
        (tmp_path / "missing-cli-result.json").read_text(encoding="utf-8")
    )


def test_canary_output_is_create_only_and_symlink_safe(
    tmp_path: Path,
    capsys,
) -> None:
    _receipt, paths = _published_shape(tmp_path)
    occupied = tmp_path / "occupied-result.json"
    occupied.write_text("do not replace\n", encoding="utf-8")

    occupied_exit = CANARY["main"](
        [
            "--wheel",
            str(paths["wheel"]),
            "--sdist",
            str(paths["sdist"]),
            "--receipt",
            str(paths["receipt"]),
            "--harness",
            str(paths["harness"]),
            "--output",
            str(occupied),
        ]
    )

    assert occupied_exit == 1
    assert "output must be a missing regular-file leaf" in capsys.readouterr().out
    assert occupied.read_text(encoding="utf-8") == "do not replace\n"

    victim = tmp_path / "victim-result.json"
    victim.write_text("do not follow\n", encoding="utf-8")
    unsafe = tmp_path / "unsafe-result.json"
    unsafe.symlink_to(victim)
    unsafe_exit = CANARY["main"](
        [
            "--wheel",
            str(paths["wheel"]),
            "--sdist",
            str(paths["sdist"]),
            "--receipt",
            str(paths["receipt"]),
            "--harness",
            str(paths["harness"]),
            "--output",
            str(unsafe),
        ]
    )

    assert unsafe_exit == 1
    assert "output must be a missing regular-file leaf" in capsys.readouterr().out
    assert victim.read_text(encoding="utf-8") == "do not follow\n"
