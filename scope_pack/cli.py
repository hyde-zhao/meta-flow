"""Command line entry point for SCOPE-Pack."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    if os.environ.get("SCOPE_PACK_SOURCE"):
        roots.append(Path(os.environ["SCOPE_PACK_SOURCE"]).expanduser())

    cwd = Path.cwd()
    roots.extend([cwd, *cwd.parents])

    package_root = Path(__file__).resolve().parent
    roots.extend([package_root.parent, *package_root.parents])
    return roots


def _find_installer() -> Path:
    for root in _candidate_roots():
        candidate = root / "delivery" / "scripts" / "install.py"
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "无法定位 SCOPE-Pack 安装器。请在 meta-flow 仓库内运行，"
        "或设置 SCOPE_PACK_SOURCE 指向包含 delivery/scripts/install.py 的目录。"
    )


def _print_help() -> None:
    print(
        "usage: scope-pack <command> [options]\n\n"
        "Commands:\n"
        "  install    Install SCOPE-Pack assets into Claude Code, Codex, or OpenClaw.\n\n"
        "Examples:\n"
        "  scope-pack install --platform codex --scope user --component rules\n"
        "  scope-pack install --platform codex --scope project --project-dir /path/to/repo\n"
    )


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return

    command = args[0]
    if command != "install":
        raise SystemExit(f"未知命令: {command}. 目前支持: install")

    installer = _find_installer()
    sys.argv = [str(installer), *args[1:]]
    runpy.run_path(str(installer), run_name="__main__")


if __name__ == "__main__":
    main()
