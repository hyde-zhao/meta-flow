#!/usr/bin/env python3
"""将一个 provider wheel 绑定到当前 exact source checkout。"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from meta_flow.installation.artifact import build_provider_artifact_receipt


def _write_atomic(path: Path, payload: dict[str, object]) -> None:
    target = path.expanduser().resolve()
    if target.exists() and (not target.is_file() or target.is_symlink()):
        raise ValueError("provider artifact receipt target must be one regular file")
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qualify_provider_artifact")
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = build_provider_artifact_receipt(args.source_root, args.wheel)
        if not receipt["release_qualifying"] and not args.allow_dirty:
            raise ValueError(
                "provider source is dirty; release qualification requires a clean checkout"
            )
        _write_atomic(args.output, receipt)
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
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
