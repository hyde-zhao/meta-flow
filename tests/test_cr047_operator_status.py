from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from meta_flow.checks import cr_tracking

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ("codex", "claude", "qoder")
EXPECTED_FLAGS = "--scope project --component full --project-dir . --dry-run"


class CR047OperatorStatusTests(unittest.TestCase):
    def test_operator_docs_publish_three_noninteractive_examples(self) -> None:
        for relative in ("README.md", "delivery/README.md", "delivery/doc/USER-MANUAL.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            for platform in PLATFORMS:
                command = f"meta-flow install {platform} {EXPECTED_FLAGS}"
                self.assertIn(command, text, f"{relative} is missing {platform} noninteractive dry-run")

    def test_three_platform_dry_runs_are_side_effect_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            before = list(project.rglob("*"))
            for platform in PLATFORMS:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "meta_flow.cli",
                        "install",
                        platform,
                        "--scope",
                        "project",
                        "--component",
                        "full",
                        "--project-dir",
                        str(project),
                        "--dry-run",
                    ],
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
                self.assertIn("Dry run completed.", completed.stdout)
            self.assertEqual(before, list(project.rglob("*")))

    def test_noninteractive_project_install_requires_project_dir(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "meta_flow.cli",
                "install",
                "codex",
                "--scope",
                "project",
                "--component",
                "full",
                "--dry-run",
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("请显式传入 --project-dir", completed.stderr + completed.stdout)

    def test_cr046_protected_manifest_uses_identity_and_detects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            required = (
                "process/changes/CR-046.md",
                "process/changes/summaries/CR-046.summary.json",
                "process/archive/CR-046/evidence-index.json",
            )
            for relative in required:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"source": relative}) + "\n", encoding="utf-8")

            manifest = cr_tracking.build_protected_object_manifest(
                root,
                cr_id="CR-046",
                story_id="ST-WT-007",
            )
            self.assertEqual("object-identity", manifest["identity_mode"])
            self.assertIs(False, manifest["path_prefix_only_identification"])
            self.assertEqual([], cr_tracking.verify_protected_object_manifest(root, manifest))

            (root / required[0]).write_text("mutated\n", encoding="utf-8")
            findings = cr_tracking.verify_protected_object_manifest(root, manifest)
            self.assertTrue(any("hash changed" in finding for finding in findings), findings)

    def test_protected_ledger_ignores_unrelated_append_that_mentions_cr_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "process/changes/CR-046.md",
                "process/changes/summaries/CR-046.summary.json",
                "process/archive/CR-046/evidence-index.json",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"source": relative}) + "\n", encoding="utf-8")
            ledger = root / "process/state/GATE-LEDGER.ndjson"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            protected = {
                "event_id": "GATE-CR046-CP8-APPROVED",
                "event_type": "human_gate_approval",
                "gate": "CP8",
                "status": "approved",
                "cr_id": "CR-046",
            }
            unrelated = {
                "event_id": "GATE-CR047-CP8-OPEN",
                "event_type": "human_gate_opened",
                "gate": "CP8",
                "status": "pending",
                "cr_id": "CR-047",
                "pending_non_authorized_items": ["CR-046 protected original rewrite"],
            }
            ledger.write_text(json.dumps(protected) + "\n", encoding="utf-8")

            manifest = cr_tracking.build_protected_object_manifest(
                root,
                cr_id="CR-046",
                story_id="ST-WT-007",
            )
            ledger.write_text(
                json.dumps(protected) + "\n" + json.dumps(unrelated) + "\n",
                encoding="utf-8",
            )

            self.assertEqual([], cr_tracking.verify_protected_object_manifest(root, manifest))

            protected["status"] = "rewritten"
            ledger.write_text(
                json.dumps(protected) + "\n" + json.dumps(unrelated) + "\n",
                encoding="utf-8",
            )
            findings = cr_tracking.verify_protected_object_manifest(root, manifest)
            self.assertTrue(any("hash changed" in finding for finding in findings), findings)


if __name__ == "__main__":
    unittest.main()
