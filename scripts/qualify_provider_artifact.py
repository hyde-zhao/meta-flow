#!/usr/bin/env python3
"""将一个 provider wheel 绑定到当前 exact source checkout。"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from meta_flow.installation.artifact import (
    build_provider_artifact_bundle,
    sidecar_path_for_receipt,
)


def _write_bytes_atomic(path: Path, rendered: bytes) -> None:
    target = Path(os.path.abspath(path.expanduser()))
    if target.exists() and (not target.is_file() or target.is_symlink()):
        raise ValueError("provider artifact receipt target must be one regular file")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _render(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _restore(path: Path, before: bytes | None) -> None:
    if before is None:
        path.unlink(missing_ok=True)
    else:
        _write_bytes_atomic(path, before)


def _write_bundle_atomic(
    receipt_path: Path,
    receipt: dict[str, object],
    sidecar: dict[str, object],
) -> Path:
    target = Path(os.path.abspath(receipt_path.expanduser()))
    sidecar_path = sidecar_path_for_receipt(target)
    for path in (target, sidecar_path):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(
                "provider artifact receipt bundle target must be a regular file or absent"
            )
    before_receipt = target.read_bytes() if target.is_file() else None
    before_sidecar = sidecar_path.read_bytes() if sidecar_path.is_file() else None
    try:
        # receipt 是 commit marker；sidecar 必须先落盘，避免新 receipt 缺少绑定。
        _write_bytes_atomic(sidecar_path, _render(sidecar))
        _write_bytes_atomic(target, _render(receipt))
        if (
            target.read_bytes() != _render(receipt)
            or sidecar_path.read_bytes() != _render(sidecar)
        ):
            raise ValueError("provider artifact receipt bundle postcheck failed")
    except Exception:
        _restore(target, before_receipt)
        _restore(sidecar_path, before_sidecar)
        raise
    return sidecar_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qualify_provider_artifact")
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt, sidecar = build_provider_artifact_bundle(args.source_root, args.wheel)
        if not receipt["release_qualifying"] and not args.allow_dirty:
            raise ValueError(
                "provider source is dirty; release qualification requires a clean checkout"
            )
        sidecar_path = _write_bundle_atomic(args.output, receipt, sidecar)
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "ProviderArtifactQualificationResultV1",
                    "decision": "BLOCKED",
                    "mutation_count": 0,
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "ProviderArtifactQualificationResultV1",
                "decision": "PASS",
                "mutation_count": 2,
                "qualification_increment": 0,
                "receipt_path": str(Path(os.path.abspath(args.output.expanduser()))),
                "sidecar_path": str(sidecar_path),
                "receipt_digest": receipt["receipt_digest"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
