from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from meta_flow.validation import task_runner


def _binding(root: Path) -> tuple[Path, Path]:
    release, process = root / "meta-flow", root / "meta-flow-process"
    for repo in (release, process):
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (release / ".meta-flow").mkdir()
    (release / ".meta-flow/workspace.yaml").write_text("schema_version: 1\nlayout_version: independent-process-repo-v1\nworkflow_model: vnext\nproject_id: fixture\nrepo_role: release\nroute_mode: sibling-binding\nprocess_repo:\n  anchor: workspace_parent\n  relative_path: meta-flow-process\n", encoding="utf-8")
    (process / ".meta-flow-process.yaml").write_text("schema_version: 1\nlayout_version: independent-process-repo-v1\nworkflow_model: vnext\nproject_id: fixture\nrepo_role: process\nroute_mode: sibling-binding\nrelease_repo:\n  anchor: workspace_parent\n  relative_path: meta-flow\n", encoding="utf-8")
    (process / "PROJECT.yaml").write_text("schema_version: 1\nproject_id: fixture\nname: Fixture\nstatus: active\n", encoding="utf-8")
    return release, process


class ValidationTaskBindingTests(unittest.TestCase):
    def test_sibling_logical_refs_write_only_logical_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = _binding(Path(directory))
            for ref, payload in (("state/ops.json", {"real_lake_read_count": 1}), ("admission.json", {"status": "PASS"})):
                path = process / ref
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload), encoding="utf-8")
            status, evidence = task_runner.run_validation_task(project_root=release, cr_id="CR-1", profile_name="real-lake-readonly", reruns=2, command="", execute=False, output_dir=Path("process/validation/out"), ops_counter=Path("process/state/ops.json"), admission_package=Path("process/admission.json"))
            self.assertEqual(0, status)
            self.assertTrue(evidence["run_ledger_ref"].startswith("process/"))
            self.assertTrue((process / "validation/out/evidence-index.json").is_file())
            output_files = [* (process / "validation/out").rglob("*.json"), * (process / "validation/out").rglob("*.ndjson")]
            serialized = "\n".join(path.read_text(encoding="utf-8") for path in output_files)
            self.assertNotIn(str(process.resolve()), serialized)
            self.assertIn('"source_ref": "process/state/ops.json"', serialized)
            self.assertIn('"source_ref": "process/admission.json"', serialized)

    def test_invalid_binding_and_escape_block_before_task_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = _binding(Path(directory))
            outside = Path(directory) / "outside"
            outside.mkdir()
            (process / "validation").mkdir()
            (process / "validation/escape").symlink_to(outside, target_is_directory=True)
            for output in (Path("process/validation/escape"),):
                with self.assertRaises(ValueError):
                    task_runner.run_validation_task(project_root=release, cr_id="CR-1", profile_name="real-lake-readonly", reruns=2, command="", execute=False, output_dir=output)
            for keyword in ("ops_counter", "admission_package"):
                kwargs = {keyword: Path("process/validation/escape")}
                with self.assertRaises(ValueError):
                    task_runner.run_validation_task(project_root=release, cr_id="CR-1", profile_name="real-lake-readonly", reruns=2, command="", execute=False, **kwargs)
            self.assertFalse((outside / "run-ledger.ndjson").exists())

    def test_missing_logical_inputs_fail_before_task_start_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = _binding(Path(directory))
            output = process / "validation/out"
            for keyword, ref in (("ops_counter", "process/state/missing.json"), ("admission_package", "process/missing-admission.json")):
                with self.subTest(keyword=keyword), self.assertRaises(FileNotFoundError):
                    task_runner.run_validation_task(project_root=release, cr_id="CR-1", profile_name="real-lake-readonly", reruns=2, command="", execute=False, output_dir=Path("process/validation/out"), **{keyword: Path(ref)})
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
