from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.context_pack import builder
from meta_flow.state import current


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)


def write_cr_summary(root: Path, cr_id: str) -> None:
    path = root / "process" / "changes" / "summaries" / f"{cr_id}.summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "id": cr_id,
                "title": f"{cr_id} summary",
                "status": "active",
                "authz_policy_refs": ["NO_CREDENTIAL_READ"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    index = root / "process" / "changes" / "CR-INDEX.json"
    index.write_text(
        json.dumps({"schema_version": 1, "items": [{"id": cr_id, "summary_ref": path.relative_to(root).as_posix()}]})
        + "\n",
        encoding="utf-8",
    )


class ContextPackTests(unittest.TestCase):
    def test_build_writes_context_pack_and_read_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")

            output = root / "process" / "context" / "CP6-CR101.context.json"
            exit_code = builder.main(
                [
                    "build",
                    "--project-root",
                    str(root),
                    "--stage",
                    "CP6",
                    "--profile",
                    "standard-code",
                    "--cr",
                    "CR-101",
                    "--budget",
                    "16000",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            self.assertTrue(output.is_file())
            self.assertTrue((root / "process" / "policies" / "READ-POLICY.json").is_file())
            context = json.loads(output.read_text(encoding="utf-8"))
            allowed = {entry["path"] for entry in context["allowed_reads"]}
            must = {entry["path"] for entry in context["must_read"]}
            do_not = {entry["path_or_pattern"] for entry in context["do_not_read_by_default"]}
            self.assertIn("process/state/STATE.current.json", allowed)
            self.assertIn("process/current/CURRENT.json", allowed)
            self.assertIn("process/state/STATE.current.json", must)
            self.assertIn("process/current/CURRENT.json", must)
            self.assertIn("process/changes/summaries/CR-101.summary.json", allowed)
            self.assertIn("process/policies/READ-POLICY.json", allowed)
            self.assertIn("process/STATE.md", context["denied_default_reads"])
            self.assertIn("process/archive/**", context["denied_default_reads"])
            self.assertIn("process/archive/**", do_not)

    def test_check_passes_for_valid_generated_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")
            _context, output = builder.build_context_pack(
                root,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-101",
                budget=16000,
            )

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = builder.main(["check", "--project-root", str(root), "--context", str(output)])

            self.assertEqual(0, exit_code)
            self.assertIn("Context Pack Check: OK", stream.getvalue())

    def test_check_rejects_deny_default_allowed_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")
            context, output = builder.build_context_pack(
                root,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-101",
                budget=16000,
            )
            context["allowed_reads"].append(
                {
                    "path": "process/STATE.md",
                    "mode": "full",
                    "estimated_tokens": 1,
                    "required": False,
                    "reason": "legacy_state",
                }
            )
            output.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = builder.validate_context_pack(output, project_root=root)

            self.assertIn("allowed_reads contains deny-default path: process/STATE.md", errors)

    def test_check_fails_when_context_exceeds_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")
            context, output = builder.build_context_pack(
                root,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-101",
                budget=1,
            )
            self.assertGreater(context["budget"]["estimated_tokens"], context["budget"]["max_tokens"])

            errors, _warnings = builder.validate_context_pack(output, project_root=root)

            self.assertTrue(any("estimated_tokens exceeds budget" in error for error in errors))

    def test_check_fails_when_required_cr_summary_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            _context, output = builder.build_context_pack(
                root,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-404",
                budget=16000,
            )

            errors, _warnings = builder.validate_context_pack(output, project_root=root)

            self.assertIn("required allowed_read missing on disk: process/changes/summaries/CR-404.summary.json", errors)
            self.assertIn("cr_summary_ref missing on disk: process/changes/summaries/CR-404.summary.json", errors)

    def test_check_rejects_empty_zone_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root, "CR-101")
            context, output = builder.build_context_pack(
                root,
                stage="CP6",
                profile="standard-code",
                cr_id="CR-101",
                budget=16000,
            )
            context["must_read"] = []
            context["do_not_read_by_default"] = []
            output.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = builder.validate_context_pack(output, project_root=root)

            self.assertIn("must_read must be a non-empty list", errors)
            self.assertIn("do_not_read_by_default must be a non-empty list", errors)


if __name__ == "__main__":
    unittest.main()
