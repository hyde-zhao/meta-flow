"""Workflow evaluation utilities for Meta Flow."""

from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    from .runner import main as runner_main

    return runner_main(list(argv) if argv is not None else None)

__all__ = ["main"]
