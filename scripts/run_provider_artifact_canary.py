#!/usr/bin/env python3
"""从非 editable wheel 执行隔离的 sibling-binding 核心生命周期 canary。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path

from meta_flow.installation.artifact import (
    build_provider_release_asset_set,
    load_provider_artifact_receipt,
    sidecar_path_for_receipt,
)


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"canary command failed ({completed.returncode}): {detail}")
    return completed.stdout


def _digest(payload: object) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(rendered).hexdigest()


def _regular_file(path: Path, *, label: str) -> Path:
    """不跟随任一路径组件的 symlink，返回绝对普通文件路径。"""

    target = Path(os.path.abspath(path.expanduser()))
    current = Path(target.anchor)
    for part in target.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"provider artifact canary {label} path is unsafe")
    if not target.is_file():
        raise ValueError(f"provider artifact canary {label} must be one regular file")
    return target


def _terminal_receipt_target(path: Path) -> Path:
    """验证 create-only 终态回执目标，不跟随 symlink 或创建父目录。"""

    target = Path(os.path.abspath(path.expanduser()))
    current = Path(target.anchor)
    for part in target.parts[1:-1]:
        current /= part
        if current.is_symlink() or not current.is_dir():
            raise ValueError("provider artifact canary output parent is unsafe")
    if target.is_symlink() or target.exists():
        raise ValueError("provider artifact canary output must be a missing regular-file leaf")
    return target


def _render_terminal_receipt(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _emit_terminal_receipt(
    output: Path,
    payload: dict[str, object],
    *,
    exit_code: int,
) -> int:
    terminal = {**payload, "exit_code": exit_code}
    rendered = _render_terminal_receipt(terminal)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(output, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        fallback = {
            "schema_version": 1,
            "kind": "ProviderArtifactConsumerCanaryReceiptV1",
            "decision": "BLOCKED",
            "error": f"terminal receipt write failed: {exc}",
            "exit_code": 1,
        }
        print(_render_terminal_receipt(fallback).decode("utf-8"), end="")
        return 1
    print(rendered.decode("utf-8"), end="")
    return exit_code


def _isolated_environment(
    root: Path,
    *,
    receipt_path: Path,
    release_qualifying: bool,
) -> dict[str, str]:
    allowed_keys = {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "CURL_CA_BUNDLE",
        "REQUESTS_CA_BUNDLE",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in allowed_keys or key.startswith("LC_")
    }
    directories = {
        "HOME": root / "home",
        "XDG_CONFIG_HOME": root / "xdg-config",
        "XDG_DATA_HOME": root / "xdg-data",
        "XDG_CACHE_HOME": root / "xdg-cache",
        "UV_CACHE_DIR": root / "uv-cache",
        "UV_TOOL_DIR": root / "uv-tools",
    }
    for key, directory in directories.items():
        directory.mkdir(parents=True, exist_ok=True)
        environment[key] = str(directory)
    environment["META_FLOW_PROVIDER_RECEIPT"] = str(receipt_path)
    environment["META_FLOW_PROVIDER_MODE"] = (
        "release" if release_qualifying else "development"
    )
    return environment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_provider_artifact_canary")
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--harness",
        type=Path,
        default=Path("tests/fixtures/core_lifecycle_dogfood.py"),
    )
    parser.add_argument("--allow-non-release", action="store_true")
    args = parser.parse_args(argv)
    output: Path | None = None
    try:
        output = _terminal_receipt_target(args.output)
        wheel = _regular_file(args.wheel, label="wheel")
        receipt_path = _regular_file(args.receipt, label="receipt")
        harness = _regular_file(args.harness, label="harness")
        receipt = load_provider_artifact_receipt(receipt_path)
        asset_set = build_provider_release_asset_set(receipt["distribution_version"])
        sidecar_path = _regular_file(
            sidecar_path_for_receipt(receipt_path),
            label="digest policy sidecar",
        )
        if wheel.name != asset_set.wheel_filename:
            raise ValueError("provider wheel filename differs from the canonical asset set")
        if receipt["artifact_filename"] != asset_set.wheel_filename:
            raise ValueError("provider receipt artifact filename differs from the asset set")
        if receipt_path.name != asset_set.receipt_filename:
            raise ValueError("provider receipt filename differs from the canonical asset set")
        if sidecar_path.name != asset_set.sidecar_filename:
            raise ValueError("provider sidecar filename differs from the canonical asset set")
        sdist = None
        if args.sdist is not None:
            sdist = _regular_file(args.sdist, label="sdist")
            if sdist.name != asset_set.sdist_filename:
                raise ValueError("provider sdist filename differs from the canonical asset set")
        elif receipt["release_qualifying"]:
            raise ValueError("release-qualifying provider canary requires the canonical sdist")
        asset_paths = tuple(
            path
            for path in (wheel, sdist, receipt_path, sidecar_path)
            if path is not None
        )
        if len({path.parent for path in asset_paths}) != 1:
            raise ValueError("provider canary assets must share one publishable directory")
        if sha256(wheel.read_bytes()).hexdigest() != receipt["artifact_sha256"]:
            raise ValueError("provider wheel differs from the qualified artifact receipt")
        if not receipt["release_qualifying"] and not args.allow_non_release:
            raise ValueError("provider artifact receipt is not release qualifying")
        with tempfile.TemporaryDirectory(prefix="meta-flow-artifact-canary-") as directory:
            root = Path(directory)
            copied_harness = root / "core_lifecycle_canary.py"
            shutil.copyfile(harness, copied_harness)
            environment = _isolated_environment(
                root,
                receipt_path=receipt_path,
                release_qualifying=bool(receipt["release_qualifying"]),
            )
            venv = root / "venv"
            _run(
                ["uv", "venv", "--python", "3.11", str(venv)],
                cwd=root,
                environment=environment,
            )
            python = venv / "bin" / "python"
            _run(
                ["uv", "pip", "install", "--python", str(python), str(wheel)],
                cwd=root,
                environment=environment,
            )
            identity_output = _run(
                [
                    str(python),
                    "-c",
                    "import json; from meta_flow.installation.identity import "
                    "observe_provider_runtime_identity; "
                    "print(json.dumps(observe_provider_runtime_identity(), sort_keys=True))",
                ],
                cwd=root,
                environment=environment,
            )
            identity = json.loads(identity_output)
            module_path = Path(str(identity["module_path"])).resolve()
            try:
                module_path.relative_to(venv)
            except ValueError as exc:
                raise ValueError("artifact canary imported provider outside its isolated venv") from exc
            expected_readiness = "PASS" if receipt["release_qualifying"] else "BLOCKED"
            if identity["release_readiness"]["decision"] != expected_readiness:
                raise ValueError("artifact runtime release readiness differs from qualification")
            public_version_output = _run(
                [str(venv / "bin" / "meta-flow"), "version", "--format", "json"],
                cwd=root,
                environment=environment,
            )
            public_version = json.loads(public_version_output)
            if public_version.get("distribution_version") != receipt["distribution_version"]:
                raise ValueError("public version CLI differs from the receipt version")
            if receipt["release_qualifying"] and (
                public_version.get("status") != "READY"
                or (public_version.get("provider_admission") or {}).get("decision")
                != "READY"
            ):
                raise ValueError("public version CLI is not READY for release canary")
            consumer = root / "consumer"
            consumer.mkdir()
            _run(
                [
                    str(venv / "bin" / "meta-flow"),
                    "install",
                    "codex",
                    "--scope",
                    "project",
                    "--component",
                    "rules",
                    "--project-dir",
                    str(consumer),
                    "--dry-run",
                ],
                cwd=root,
                environment=environment,
            )
            lifecycle_output = _run(
                [str(python), str(copied_harness)],
                cwd=root,
                environment=environment,
            )
            lifecycle = json.loads(lifecycle_output)
            if lifecycle.get("decision") != "PASS":
                raise ValueError("artifact core lifecycle canary did not pass")
            result = {
                "schema_version": 1,
                "kind": "ProviderArtifactConsumerCanaryReceiptV1",
                "decision": "PASS" if receipt["release_qualifying"] else "PASS_WITH_RISK",
                "release_qualifying": bool(receipt["release_qualifying"]),
                "artifact_sha256": receipt["artifact_sha256"],
                "sdist_sha256": sha256(sdist.read_bytes()).hexdigest() if sdist else None,
                "provider_receipt_digest": receipt["receipt_digest"],
                "provider_identity_digest": identity["identity_digest"],
                "release_asset_set_digest": asset_set.semantic_digest,
                "core_lifecycle_digest": _digest(lifecycle),
                "route_mode": lifecycle["route_mode"],
                "close_order": lifecycle["close_order"],
                "provider_checkout_imported": False,
                "source_fallback_count": 0,
                "public_version_status": public_version.get("status"),
                "isolated_home": True,
                "install_dry_run": "PASS",
            }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        blocked = {
            "schema_version": 1,
            "kind": "ProviderArtifactConsumerCanaryReceiptV1",
            "decision": "BLOCKED",
            "error": str(exc),
        }
        if output is None:
            print(
                _render_terminal_receipt({**blocked, "exit_code": 1}).decode("utf-8"),
                end="",
            )
            return 1
        return _emit_terminal_receipt(output, blocked, exit_code=1)
    return _emit_terminal_receipt(output, result, exit_code=0)


if __name__ == "__main__":
    raise SystemExit(main())
