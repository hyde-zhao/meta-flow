from __future__ import annotations

import subprocess
from pathlib import Path

from meta_flow.work.git_inventory import (
    InventoryCandidate,
    build_inventory,
    staged_symmetric_difference,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_inventory_covers_all_eight_classes_and_partitions(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / ".gitignore").write_text("generated.txt\n", encoding="utf-8")
    (root / "regular.txt").write_text("tracked\n", encoding="utf-8")
    (root / "target.txt").write_text("target\n", encoding="utf-8")
    (root / "alias.txt").symlink_to("target.txt")
    _git(root, "add", ".gitignore", "regular.txt", "target.txt", "alias.txt")
    _git(root, "-c", "user.name=Meta Flow Test", "-c", "user.email=test@example.invalid", "commit", "-m", "base")
    candidates = [
        InventoryCandidate("release", "delivery", "regular.txt"),
        InventoryCandidate("release", "delivery", "alias.txt"),
        InventoryCandidate("release", "delivery", "new.txt"),
        InventoryCandidate("release", "delivery", "generated.txt"),
        InventoryCandidate("release", "delivery", "missing.txt", missing_is_validation=True),
        InventoryCandidate("release", "delivery", "../escape.txt"),
        InventoryCandidate("release", "delivery", "regular.txt"),
        InventoryCandidate("unknown", "delivery", "anything.txt"),
    ]

    result = build_inventory({"release": root}, candidates)

    assert result["candidate_count"] == 8
    assert result["remaining"] == result["unknown"] == 0
    assert result["classes"]["tracked_regular"] == ["release/regular.txt"]
    assert result["classes"]["tracked_symlink"] == ["release/alias.txt"]
    assert result["classes"]["prospective_untracked"] == ["release/new.txt"]
    assert result["classes"]["ignored_generated"] == ["release/generated.txt"]
    assert result["classes"]["missing"] == ["release/missing.txt"]
    assert result["classes"]["outside_repo"] == ["release/../escape.txt", "unknown/anything.txt"]
    assert result["classes"]["duplicate"] == ["release/regular.txt"]


def test_staged_symmetric_difference_is_exact_and_read_only(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "one.txt").write_text("one\n", encoding="utf-8")
    (root / "two.txt").write_text("two\n", encoding="utf-8")
    _git(root, "add", "one.txt")

    blocked = staged_symmetric_difference(root, ["one.txt", "two.txt"])
    passed = staged_symmetric_difference(root, ["one.txt"])

    assert blocked["decision"] == "BLOCKED"
    assert blocked["missing"] == ["two.txt"]
    assert passed["decision"] == "PASS"
    assert passed["symmetric_difference_count"] == 0
