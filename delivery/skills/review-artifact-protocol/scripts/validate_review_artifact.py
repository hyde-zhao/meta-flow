#!/usr/bin/env python3
"""Validate review findings/summary markdown artifacts without external deps."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REQUIRED = {
    "findings": {
        "frontmatter": {"artifact", "reviewer", "lane", "round", "status"},
        "markers": [
            "# Review Findings",
            "## 2. Findings",
            "## 3. 汇总结论",
            "<!-- findings-table -->",
        ],
    },
    "summary": {
        "frontmatter": {"artifact", "round", "status", "decision"},
        "markers": [
            "# Review Summary",
            "## 2. 严重度汇总",
            "## 3. 决策",
        ],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Markdown artifact to validate")
    parser.add_argument(
        "--kind",
        choices=("auto", "findings", "summary"),
        default="auto",
        help="Artifact kind; auto infers from title markers",
    )
    return parser.parse_args()


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        raise ValueError("missing yaml-like frontmatter")
    data: dict[str, str] = {}
    end = None
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            end = index
            break
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {line}")
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    if end is None:
        raise ValueError("unterminated frontmatter")
    body = "\n".join(lines[end + 1 :])
    return data, body


def infer_kind(body: str) -> str:
    if "# Review Findings" in body:
        return "findings"
    if "# Review Summary" in body:
        return "summary"
    raise ValueError("cannot infer review artifact kind")


def validate(path: Path, kind: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    resolved_kind = infer_kind(body) if kind == "auto" else kind
    rules = REQUIRED[resolved_kind]
    errors: list[str] = []

    for key in sorted(rules["frontmatter"]):
        if key not in frontmatter or not frontmatter[key]:
            errors.append(f"missing frontmatter key: {key}")

    for marker in rules["markers"]:
        if marker not in body:
            errors.append(f"missing marker: {marker}")

    return errors


def main() -> int:
    args = parse_args()
    try:
        errors = validate(args.path, args.kind)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
