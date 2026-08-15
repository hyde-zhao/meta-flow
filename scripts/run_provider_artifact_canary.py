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

from meta_flow.installation.artifact import load_provider_artifact_receipt


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_provider_artifact_canary")
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--harness",
        type=Path,
        default=Path("tests/fixtures/core_lifecycle_dogfood.py"),
    )
    parser.add_argument("--allow-non-release", action="store_true")
    args = parser.parse_args(argv)
    try:
        wheel = args.wheel.resolve()
        receipt_path = args.receipt.resolve()
        harness = args.harness.resolve()
        receipt = load_provider_artifact_receipt(receipt_path)
        if sha256(wheel.read_bytes()).hexdigest() != receipt["artifact_sha256"]:
            raise ValueError("provider wheel differs from the qualified artifact receipt")
        if not receipt["release_qualifying"] and not args.allow_non_release:
            raise ValueError("provider artifact receipt is not release qualifying")
        if not harness.is_file() or harness.is_symlink():
            raise ValueError("provider artifact canary harness must be one regular file")
        with tempfile.TemporaryDirectory(prefix="meta-flow-artifact-canary-") as directory:
            root = Path(directory)
            copied_harness = root / "core_lifecycle_canary.py"
            shutil.copyfile(harness, copied_harness)
            environment = {
                key: value
                for key, value in os.environ.items()
                if key not in {"PYTHONPATH", "PYTHONHOME", "META_FLOW_SOURCE"}
            }
            environment["META_FLOW_PROVIDER_RECEIPT"] = str(receipt_path)
            environment["META_FLOW_PROVIDER_MODE"] = (
                "release" if receipt["release_qualifying"] else "development"
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
                "provider_receipt_digest": receipt["receipt_digest"],
                "provider_identity_digest": identity["identity_digest"],
                "core_lifecycle_digest": _digest(lifecycle),
                "route_mode": lifecycle["route_mode"],
                "close_order": lifecycle["close_order"],
                "provider_checkout_imported": False,
                "install_dry_run": "PASS",
            }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "ProviderArtifactConsumerCanaryReceiptV1",
                    "decision": "BLOCKED",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
