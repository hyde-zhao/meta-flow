from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.policies import authz, gate_profiles


class GateProfileTests(unittest.TestCase):
    def test_docs_only_classifies_as_docs_lite(self) -> None:
        result = gate_profiles.classify_gate_profile(["README.md", "docs/usage.md"], [])

        self.assertEqual("docs-lite", result["profile"])

    def test_process_checker_classifies_as_process_lite(self) -> None:
        result = gate_profiles.classify_gate_profile(["meta_flow/checks/token_budget.py"], [])

        self.assertEqual("process-lite", result["profile"])

    def test_single_module_classifies_as_standard_lite(self) -> None:
        result = gate_profiles.classify_gate_profile(["quant_lab/research/artifact.py"], ["compact_artifact"])

        self.assertEqual("standard-lite", result["profile"])

    def test_runtime_terms_force_runtime_high_risk(self) -> None:
        result = gate_profiles.classify_gate_profile(["quant_lab/adapters/qmt/runtime.py"], ["credential"])

        self.assertEqual("runtime-high-risk", result["profile"])
        self.assertIn("credential", result["matched_terms"])

    def test_architecture_terms_force_architecture_major(self) -> None:
        result = gate_profiles.classify_gate_profile([], ["manifest_schema"])

        self.assertEqual("architecture-major", result["profile"])

    def test_gate_check_validates_written_default_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate_profiles.write_default_gate_profiles(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = gate_profiles.main(["check", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("Gate Profile Check: OK", output.getvalue())

    def test_plan_prints_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate_profiles.write_default_gate_profiles(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = gate_profiles.main(["plan", "--profile", "standard-lite", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn('"profile": "standard-lite"', output.getvalue())


class AuthzPolicyTests(unittest.TestCase):
    def test_policy_list_uses_default_registry_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = authz.main(["list", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("NO_CREDENTIAL_READ", output.getvalue())
            self.assertFalse((root / "process" / "policies" / "AUTHZ-POLICY.json").exists())

    def test_policy_check_passes_for_written_default_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authz.write_default_authz_policy(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = authz.main(["check", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("Authz Policy Check: OK", output.getvalue())

    def test_policy_check_requires_refs_for_high_risk_terms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authz.write_default_authz_policy(root)
            artifact = root / "process" / "changes" / "summaries" / "CR-101.summary.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text('{"summary":"touch QMT runtime"}\n', encoding="utf-8")

            errors, _warnings = authz.check_artifact(root, artifact)

            self.assertIn("artifact mentions high-risk surface but lacks authz policy ref: NO_RUNTIME_CONNECTION", errors)

    def test_policy_check_allows_refs_for_high_risk_terms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authz.write_default_authz_policy(root)
            artifact = root / "process" / "changes" / "summaries" / "CR-101.summary.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                '{"summary":"touch QMT runtime","authz_policy_refs":["NO_RUNTIME_CONNECTION"]}\n',
                encoding="utf-8",
            )

            errors, _warnings = authz.check_artifact(root, artifact)

            self.assertEqual([], errors)

    def test_policy_check_rejects_expanded_text_in_ordinary_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authz.write_default_authz_policy(root)
            artifact = root / "process" / "changes" / "summaries" / "CR-101.summary.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text('{"summary":"不授权连接 QMT/MiniQMT/XtQuant/gateway/runtime。"}\n', encoding="utf-8")

            errors, _warnings = authz.check_artifact(root, artifact)

            self.assertTrue(any("ordinary artifact copies expanded policy text" in error for error in errors))

    def test_policy_expand_prints_expanded_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = authz.main(["expand", "NO_NAS_ACCESS", "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("expanded_text", output.getvalue())

    def test_repository_publication_alias_is_separate_from_runtime_and_data_publish(self) -> None:
        normalized = authz.normalize_capability_aliases(
            ["REPOSITORY_PUBLICATION_ALLOWED", "NO_REPOSITORY_PUBLICATION"]
        )

        self.assertEqual(["repository_publication"], normalized["allowed"])
        self.assertEqual(["repository_publication"], normalized["forbidden"])
        self.assertNotIn("provider_publish", normalized["allowed"])
        self.assertNotIn("lake_write", normalized["allowed"])
        self.assertNotIn("runtime_connection", normalized["allowed"])
        self.assertNotIn("trading", normalized["allowed"])

    def test_policy_check_distinguishes_git_push_from_lake_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authz.write_default_authz_policy(root)
            artifact = root / "process" / "changes" / "summaries" / "CR-101.summary.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text('{"summary":"post-CR repository publication via git push"}\n', encoding="utf-8")

            errors, _warnings = authz.check_artifact(root, artifact)

            self.assertIn("artifact mentions high-risk surface but lacks authz policy ref: NO_REPOSITORY_PUBLICATION", errors)
            self.assertFalse(any("NO_PROVIDER_LAKE_PUBLISH" in error for error in errors))

    def test_policy_check_accepts_repository_publication_ref_without_data_publish_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authz.write_default_authz_policy(root)
            artifact = root / "process" / "changes" / "summaries" / "CR-101.summary.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                '{"summary":"post-CR repository publication via git push","authz_policy_refs":["NO_REPOSITORY_PUBLICATION"]}\n',
                encoding="utf-8",
            )

            errors, _warnings = authz.check_artifact(root, artifact)

            self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
