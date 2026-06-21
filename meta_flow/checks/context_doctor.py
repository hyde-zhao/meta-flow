"""Context doctor for read expansion and summary sufficiency feedback."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from meta_flow.context_pack import read_expansion


def run_context(project_root: Path, *, ledger: Path | None = None) -> int:
    errors, warnings = read_expansion.validate_ledger(project_root, ledger=ledger)
    summary = read_expansion.summarize_events(project_root, ledger=ledger)
    print("Context Doctor: " + ("FAIL" if errors else "OK"))
    print(f"project_root: {project_root.resolve()}")
    print(f"ledger: {summary['ledger']}")
    print(f"read_expansion_events: {summary['event_count']}")
    print(f"estimated_extra_tokens: {summary['estimated_extra_tokens']}")

    print("Frequently expanded files:")
    for path, count in summary["frequently_expanded_files"]:
        print(f"- {path}: {count}")
    if not summary["frequently_expanded_files"]:
        print("- none")

    print("Frequently expanded features:")
    for feature, count in summary["frequently_expanded_features"]:
        print(f"- {feature}: {count}")
    if not summary["frequently_expanded_features"]:
        print("- none")

    print("Expansion reason distribution:")
    for reason, count in summary["expansion_reason_distribution"]:
        print(f"- {reason}: {count}")
    if not summary["expansion_reason_distribution"]:
        print("- none")

    print("Missing context slots:")
    for slot, count in summary["missing_context_slots"]:
        print(f"- {slot}: {count}")
    if not summary["missing_context_slots"]:
        print("- none")

    print("Summary update recommendations:")
    for item in summary["summary_update_recommendations"]:
        print(f"- {item}")
    if not summary["summary_update_recommendations"]:
        print("- none")

    for warning in warnings:
        print(f"- WARN: {warning}")
    for error in errors:
        print(f"- ERROR: {error}")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow doctor context")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--ledger", type=Path, default=None)
    args = parser.parse_args(argv)
    return run_context(args.project_root, ledger=args.ledger)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
