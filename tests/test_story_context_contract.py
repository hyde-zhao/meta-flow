from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from meta_flow.context_pack import builder, read_expansion, story_contract
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.state import current


def write_minimal_state(root: Path) -> None:
    state = current.default_current_state(root)
    state["project_id"] = "fixture-project"
    current.write_current_state(root, state)
    current.refresh_current_entry(root)


def write_cr_summary(root: Path, cr_id: str = "CR-123") -> None:
    path = root / "process" / "changes" / "summaries" / f"{cr_id}.summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": cr_id, "status": "active"}) + "\n", encoding="utf-8")


def write_story(root: Path, *, lld_policy: str = "technical-note") -> Path:
    path = root / "process" / "stories" / "STORY-CR123-S01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
story_id: STORY-CR123-S01
cr_id: CR-123
title: Migrate manifest owner
feature_refs:
  - data.manifest
feature_design_refs:
  - docs/features/data-manifest/DESIGN.md
feature_contract_summary: data.manifest is the single manifest contract
cr_delta_summary: replace the legacy manifest owner
dependency_inputs:
  - ROOT: no upstream Story
lld_policy: {lld_policy}
risk_profile: standard-code
allowed_write_paths:
  - quant_lab/data/manifest/**
  - tests/data/manifest/**
forbidden_write_paths:
  - quant_lab/trading/**
acceptance:
  - legacy manifest can load
verification_plan:
  - pytest tests/data/manifest
authz_policy_refs:
  - NO_CREDENTIAL_READ
---

# Story
""",
        encoding="utf-8",
    )
    if lld_policy == "full-lld":
        path.with_name("STORY-CR123-S01-LLD.md").write_text("# Legacy LLD\n", encoding="utf-8")
    return path


def write_projected_story(root: Path) -> Path:
    story = root / "process" / "stories" / "STORY-CR123-S04.md"
    story.parent.mkdir(parents=True, exist_ok=True)
    story.write_text(
        """---
story_id: STORY-CR123-S04
cr_id: CR-123
title: Ledger migration
feature_refs: [governance.kernel]
feature_design_refs: [process/docs/features/kernel/DESIGN.md]
lld_policy: full-lld
risk_profile: runtime-high-risk
---

# Story

## 目标

对四类 ledger 执行 append-only 版本迁移。

## 量化验收

- ledger types：4。
- history rewrites：0。
""",
        encoding="utf-8",
    )
    lld = story.with_name("STORY-CR123-S04-LLD.md")
    lld.write_text(
        """# LLD

## 10. 测试设计

| Case | 操作 | 预期 |
|---|---|---|
| C20 | dispatch migration | PASS |
| C21 | replay | NO_CHANGE |
""",
        encoding="utf-8",
    )
    plan = root / "process" / "DEVELOPMENT-PLAN.yaml"
    plan.write_text(
        json.dumps(
            {
                "waves": [
                    {
                        "stories": [
                            {
                                "story_id": "STORY-CR123-S04",
                                "status": "dev-ready",
                                "dependency_type": [
                                    {
                                        "upstream": "STORY-CR123-S01",
                                        "type": "contract",
                                        "gate": "CP6 PASS",
                                    }
                                ],
                                "dev_gate": {
                                    "cp5_confirmed": True,
                                    "dependencies_satisfied": True,
                                    "file_conflict_free": True,
                                    "implementation_authorized": True,
                                    "lld_confirmed": True,
                                },
                                "file_ownership": {
                                    "primary": ["meta_flow/state/ledger_migration.py"],
                                    "shared": ["tests/test_cp_result_event_ledger.py"],
                                    "forbidden": ["process/state/**"],
                                },
                                "output_files": [
                                    "meta_flow/state/ledger_migration.py",
                                    "tests/test_cp_result_event_ledger.py",
                                ],
                            }
                        ]
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return story


def write_canonical_story(
    root: Path,
    *,
    dev_gate: dict[str, object] | None = None,
    acceptance_body: str = "1. canonical packet is READY.\n2. provenance remains native.",
    legacy_acceptance: str = "",
    legacy_acceptance_criteria: str = "",
    legacy_heading: str = "",
    change_id: str = "CR-123",
    legacy_cr_id: str = "",
    lld_policy: str = "  required_level: full-lld",
) -> Path:
    story = root / "process" / "stories" / "STORY-CR123-I01.md"
    story.parent.mkdir(parents=True, exist_ok=True)
    lld_policy_text = f"lld_policy:\n{lld_policy}" if lld_policy.startswith(" ") else f"lld_policy: {lld_policy}"
    story.write_text(
        f"""---
story_id: STORY-CR123-I01
change_id: {change_id}
title: Canonical packet contract
{legacy_cr_id}feature_id: governance.packet
feature_refs:
  - governance.shared
  - governance.packet
feature_design_refs:
  - process/docs/features/packet/DESIGN.md
{lld_policy_text}
lld_gate:
  required: true
  design_evidence_type: full-lld
  evidence_ref: process/docs/design/LLD-CR123-I01.md
{legacy_acceptance}{legacy_acceptance_criteria}---

# Story

## 目标

Build a canonical packet.

## 5. acceptance_criteria

{acceptance_body}
{legacy_heading}
""",
        encoding="utf-8",
    )
    lld_target = root / "process" / "docs" / "design" / "LLD-CR123-I01.md"
    lld_target.parent.mkdir(parents=True, exist_ok=True)
    lld_target.write_text("# Canonical LLD\n", encoding="utf-8")
    native_gate = dev_gate or {
        "cp5_confirmed": True,
        "dependencies_satisfied": True,
        "file_conflict_free": True,
        "implementation_authorized": True,
        "lld_confirmed": True,
        "checkpoint_projection_digest": "a" * 64,
        "checkpoint_result_ref": "process/checks/CP5-CR-123.result.json",
    }
    plan = root / "process" / "DEVELOPMENT-PLAN.yaml"
    plan.write_text(
        json.dumps(
            {
                "waves": [
                    {
                        "stories": [
                            {
                                "story_id": "STORY-CR123-I01",
                                "status": "dev-ready",
                                "dev_gate": native_gate,
                                "file_ownership": {"primary": ["meta_flow/context_pack/story_contract.py"]},
                                "output_files": ["meta_flow/context_pack/story_contract.py"],
                            }
                        ]
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return story


def write_revalidation_fixture(
    root: Path,
    *,
    authorization_patterns: list[str] | None = None,
    work_patterns: list[str] | None = None,
) -> dict[str, object]:
    """创建真实 Work/ref/target fixture；正向路径只需要替换 Git HEAD。"""

    write_minimal_state(root)
    write_cr_summary(root)
    story = write_projected_story(root)
    plan_path = root / "process" / "DEVELOPMENT-PLAN.yaml"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["waves"][0]["stories"][0]["status"] = "ready-for-verification"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    work_id = "WORK-1"
    attempt_id = "attempt-1"
    packet_ref = (
        "process/works/WORK-1/revalidation/attempt-1/artifacts/"
        "STORY-CR123-S04.CP6.work-packet.json"
    )
    return_ref = (
        "process/works/WORK-1/revalidation/attempt-1/artifacts/"
        "STORY-CR123-S04.CP6.return.json"
    )
    auth_ref = "process/works/WORK-1/revalidation/attempt-1/receipts/authorization.json"
    work_path = root / "process" / "works" / work_id / "WORK.yaml"
    work_path.parent.mkdir(parents=True, exist_ok=True)
    work_path.write_text(
        json.dumps(
            {
                "work_id": work_id,
                "status": "active",
                "scope_digest": "c" * 64,
                "scope": {
                    "allowed_writes": work_patterns
                    or ["works/WORK-1/revalidation/attempt-1/artifacts/**"]
                },
            }
        ),
        encoding="utf-8",
    )
    previous_ref = "process/checks/CP6-old.json"
    superseding_ref = "process/checks/CP5-new.json"
    previous_path = root / previous_ref
    superseding_path = root / superseding_ref
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    previous_bytes = b'{"decision":"PASS","revision":1}\n'
    superseding_bytes = b'{"decision":"PASS","revision":7}\n'
    previous_path.write_bytes(previous_bytes)
    superseding_path.write_bytes(superseding_bytes)
    authorization = {
        "schema_version": 1,
        "cr_id": "CR-123",
        "story_id": "STORY-CR123-S04",
        "work_id": work_id,
        "attempt_id": attempt_id,
        "release_oid": "a" * 40,
        "process_oid": "b" * 40,
        "scope_digest": "c" * 64,
        "previous_cp6_ref": previous_ref,
        "previous_cp6_digest": hashlib.sha256(previous_bytes).hexdigest(),
        "superseding_cp5_ref": superseding_ref,
        "superseding_cp5_digest": hashlib.sha256(superseding_bytes).hexdigest(),
        "plan_preimage_digest": canonical_digest(
            {"target_ref": packet_ref, "exists": False}
        ),
        "allowed_write_paths": authorization_patterns
        or ["process/works/WORK-1/revalidation/attempt-1/artifacts/**"],
    }
    auth_path = root / auth_ref
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(json.dumps(authorization), encoding="utf-8")
    return {
        "story": story,
        "plan_path": plan_path,
        "work_path": work_path,
        "auth_ref": auth_ref,
        "auth_path": auth_path,
        "authorization": authorization,
        "packet_ref": packet_ref,
        "packet_path": root / packet_ref,
        "return_ref": return_ref,
        "previous_path": previous_path,
        "superseding_path": superseding_path,
    }


def current_git_heads(root: Path):
    return lambda path: "a" * 40 if path.resolve() == root.resolve() else "b" * 40


class StoryContextContractTests(unittest.TestCase):
    def test_canonical_full_lld_uses_exact_gate_ref_for_read_and_preregistration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_canonical_story(root)

            packet, _output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            expected = "process/docs/design/LLD-CR123-I01.md"
            self.assertEqual(expected, packet["read_if_needed"][0]["path"])
            self.assertEqual(expected, packet["pre_dispatch_actions"][0]["requested_refs"][0])
            self.assertNotIn("process/stories/STORY-CR123-I01-LLD.md", json.dumps(packet))

    def test_legacy_flat_full_lld_derives_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root, lld_policy="full-lld")

            packet, _output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            self.assertEqual(
                "process/stories/STORY-CR123-S01-LLD.md",
                packet["read_if_needed"][0]["path"],
            )

    def test_canonical_lld_gate_failures_are_pre_writer_and_never_fallback(self) -> None:
        cases = [
            ("lld_gate:\n  required: true\n  design_evidence_type: full-lld\n", "LLD_GATE_MISSING"),
            (
                "lld_gate:\n  required: true\n  design_evidence_type: technical-note\n"
                "  evidence_ref: process/docs/design/LLD-CR123-I01.md\n",
                "LLD_GATE_POLICY_CONFLICT",
            ),
            (
                "lld_gate:\n  required: true\n  design_evidence_type: full-lld\n"
                "  evidence_ref: process/../secret.md\n",
                "LLD_REF_UNSAFE",
            ),
            (
                "lld_gate:\n  required: true\n  design_evidence_type: full-lld\n"
                "  evidence_ref: process/docs/design/MISSING.md\n",
                "LLD_REF_TARGET_MISSING",
            ),
        ]
        for gate, error in cases:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_minimal_state(root)
                write_cr_summary(root)
                story = write_canonical_story(root)
                text = story.read_text(encoding="utf-8")
                start = text.index("lld_gate:")
                end = text.index("---", start)
                story.write_text(text[:start] + gate + text[end:], encoding="utf-8")
                derived = story.with_name("STORY-CR123-I01-LLD.md")
                derived.write_text("# Must not be used\n", encoding="utf-8")
                output = root / "process" / "context" / "stories" / "existing.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("preserve\n", encoding="utf-8")

                with self.assertRaisesRegex(ValueError, error) as raised:
                    story_contract.build_story_packet(
                        root,
                        story_path=story,
                        stage="CP6",
                        budget=8000,
                        output=output,
                    )

                self.assertEqual("preserve\n", output.read_text(encoding="utf-8"))
                self.assertFalse((root / "process" / "policies" / "READ-POLICY.json").exists())
                self.assertNotIn(str(root), str(raised.exception))

    def test_canonical_story_card_projects_exact_gate_and_stable_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_canonical_story(root)
            plan = root / "process" / "DEVELOPMENT-PLAN.yaml"
            plan_bytes = plan.read_bytes()

            packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            self.assertEqual("READY", packet["admission"]["decision"])
            self.assertEqual("CR-123", packet["cr_id"])
            self.assertEqual("full-lld", packet["lld_policy"])
            self.assertEqual(["governance.packet", "governance.shared"], packet["feature_refs"])
            self.assertEqual(["process/docs/features/packet/DESIGN.md"], packet["feature_design_refs"])
            self.assertEqual(["canonical packet is READY.", "provenance remains native."], packet["acceptance"])
            self.assertEqual("CR-123: Canonical packet contract", packet["cr_delta"]["summary"])
            self.assertEqual(plan_bytes, plan.read_bytes())
            required_reads = {entry["path"] for entry in packet["allowed_reads"] if entry["required"]}
            self.assertIn("process/changes/summaries/CR-123.summary.json", required_reads)
            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)
            self.assertEqual([], errors)

    def test_canonical_story_cli_build_and_check_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_canonical_story(root)

            output = StringIO()
            with redirect_stdout(output):
                build_exit = story_contract.main(
                    ["build-story-packet", "--story", str(story), "--stage", "CP6", "--project-root", str(root)]
                )
            packet_path = root / "process" / "context" / "stories" / "STORY-CR123-I01.CP6.work-packet.json"
            with redirect_stdout(output):
                check_exit = story_contract.main(
                    ["check-story-packet", "--packet", str(packet_path), "--project-root", str(root)]
                )

            self.assertEqual(0, build_exit)
            self.assertEqual(0, check_exit)
            self.assertIn("Story Context Packet Check: OK", output.getvalue())
            packet = json.loads(
                (root / "process" / "context" / "stories" / "STORY-CR123-I01.CP6.work-packet.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("CR-123", packet["cr_id"])

    def test_canonical_and_legacy_acceptance_conflict_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_canonical_story(root, legacy_acceptance="acceptance:\n  - legacy mismatch\n")

            with self.assertRaisesRegex(ValueError, "canonical and legacy Story acceptance conflict"):
                story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

    def test_canonical_acceptance_compares_all_legacy_synonyms(self) -> None:
        cases = [
            {"legacy_acceptance": "acceptance:\n  - legacy mismatch\n", "source": "acceptance"},
            {
                "legacy_acceptance_criteria": "acceptance_criteria:\n  - legacy mismatch\n",
                "source": "acceptance_criteria",
            },
            {"legacy_heading": "\n## 量化验收\n\n- legacy mismatch\n", "source": "legacy_heading"},
        ]
        for case in cases:
            with self.subTest(source=case["source"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_minimal_state(root)
                write_cr_summary(root)
                story = write_canonical_story(root, **{key: value for key, value in case.items() if key != "source"})

                with self.assertRaisesRegex(ValueError, f"acceptance conflict: {case['source']}"):
                    story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

    def test_canonical_acceptance_equal_double_write_is_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_canonical_story(
                root,
                legacy_acceptance_criteria=(
                    "acceptance_criteria:\n"
                    "  - canonical packet is READY.\n"
                    "  - provenance remains native.\n"
                ),
                legacy_heading=(
                    "\n## 量化验收\n\n"
                    "- canonical packet is READY.\n"
                    "- provenance remains native.\n"
                ),
            )

            packet, _output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            self.assertEqual(["canonical packet is READY.", "provenance remains native."], packet["acceptance"])

    def test_canonical_formal_identity_defaults_to_change_id_and_conflicts_fail_closed(self) -> None:
        cases = [
            {"legacy_cr_id": "cr_id: CR-999\n", "explicit": "", "error": "legacy cr_id conflict"},
            {"legacy_cr_id": "", "explicit": "CR-999", "error": "explicit --cr conflict"},
            {"change_id": "", "legacy_cr_id": "", "explicit": "CR-123", "error": "change_id must be a non-empty string"},
            {"change_id": "   ", "legacy_cr_id": "", "explicit": "", "error": "change_id must be a non-empty string"},
        ]
        for case in cases:
            with self.subTest(error=case["error"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_minimal_state(root)
                write_cr_summary(root)
                story = write_canonical_story(
                    root,
                    **{key: value for key, value in case.items() if key in {"change_id", "legacy_cr_id"}},
                )

                with self.assertRaisesRegex(ValueError, case["error"]):
                    story_contract.build_story_packet(
                        root,
                        story_path=story,
                        stage="CP6",
                        budget=8000,
                        cr_id=case["explicit"],
                    )

    def test_canonical_malformed_policy_empty_acceptance_and_invalid_gate_fail_closed(self) -> None:
        cases = [
            {"lld_policy": "full-lld", "acceptance_body": "1. valid item", "dev_gate": None, "error": "lld_policy must be a mapping"},
            {"lld_policy": "  required_level: full-lld", "acceptance_body": "no list item", "dev_gate": None, "error": "acceptance_criteria"},
            {
                "lld_policy": "  required_level: full-lld",
                "acceptance_body": "1. valid item",
                "dev_gate": {
                    "cp5_confirmed": 1,
                    "dependencies_satisfied": True,
                    "file_conflict_free": True,
                    "implementation_authorized": True,
                    "lld_confirmed": True,
                },
                "error": "cp5_confirmed must be bool",
            },
        ]
        for case in cases:
            with self.subTest(error=case["error"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_minimal_state(root)
                write_cr_summary(root)
                story = write_canonical_story(root, **{key: value for key, value in case.items() if key != "error"})

                with self.assertRaisesRegex(ValueError, case["error"]):
                    story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

    def test_build_base_story_context_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)

            packet, output = story_contract.build_story_packet(root, story_path=story, stage="BASE", budget=8000)

            self.assertTrue(output.is_file())
            self.assertEqual("story_context_contract", packet["packet_type"])
            self.assertEqual("STORY-CR123-S01", packet["story_id"])
            self.assertIn("data.manifest", packet["feature_refs"])
            allowed = {entry["path"] for entry in packet["allowed_reads"]}
            self.assertIn("process/state/STATE.current.json", allowed)
            self.assertIn("process/stories/STORY-CR123-S01.md", allowed)
            self.assertIn("process/changes/summaries/CR-123.summary.json", allowed)

    def test_build_cp6_work_packet_has_parent_and_return_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)

            packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            self.assertTrue(output.name.endswith(".CP6.work-packet.json"))
            self.assertEqual("story_work_packet", packet["packet_type"])
            self.assertEqual("process/context/stories/STORY-CR123-S01.base.context.json", packet["parent_context_ref"])
            self.assertEqual("process/returns/STORY-CR123-S01.CP6.return.json", packet["expected_return_packet"])

    def test_cp6_packet_projects_contract_and_admission_from_native_development_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_projected_story(root)

            packet, output = story_contract.build_story_packet(
                root,
                story_path=story,
                stage="CP6",
                budget=8000,
            )

            self.assertEqual("READY", packet["admission"]["decision"])
            self.assertEqual(
                ["meta_flow/state/ledger_migration.py", "tests/test_cp_result_event_ledger.py"],
                packet["allowed_write_paths"],
            )
            self.assertEqual(["process/state/**"], packet["forbidden_write_paths"])
            self.assertEqual(2, len(packet["acceptance"]))
            self.assertEqual(4, len(packet["verification_plan"]))
            self.assertIn("STORY-CR123-S01:contract:CP6 PASS", packet["dependency_inputs"])
            self.assertTrue(packet["feature_contract_summary"])
            self.assertTrue(packet["cr_delta"]["summary"])
            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)
            self.assertEqual([], errors)

    def test_build_cp7_verify_packet_has_implementation_return_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)

            packet, _output = story_contract.build_story_packet(root, story_path=story, stage="CP7", budget=8000)

            self.assertEqual("story_verify_packet", packet["packet_type"])
            self.assertEqual("process/returns/STORY-CR123-S01.CP6.return.json", packet["implementation_return_ref"])
            self.assertEqual("process/returns/STORY-CR123-S01.CP7.return.json", packet["expected_return_packet"])

    def test_legal_missing_runtime_state_is_optional_and_does_not_create_state_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr_summary(root)
            write_story(root)

            packet, output = story_contract.build_story_packet(
                root,
                story_path=Path("process/stories/STORY-CR123-S01.md"),
                stage="CP6",
                budget=8000,
            )

            self.assertTrue(output.is_file())
            self.assertEqual("process/stories/STORY-CR123-S01.md", packet["story_ref"])
            self.assertNotIn(str(root), json.dumps(packet, ensure_ascii=False))
            state_entries = {
                entry["path"]: entry for entry in packet["allowed_reads"] if entry["path"].startswith("process/")
            }
            self.assertFalse(state_entries["process/state/STATE.current.json"]["required"])
            self.assertFalse(state_entries["process/current/CURRENT.json"]["required"])
            must_read = {entry["path"] for entry in packet["must_read"]}
            self.assertNotIn("process/state/STATE.current.json", must_read)
            self.assertNotIn("process/current/CURRENT.json", must_read)
            self.assertFalse((root / "process" / "state" / "STATE.current.json").exists())
            self.assertFalse((root / "process" / "current" / "CURRENT.json").exists())

    def test_state_without_current_entry_is_projected_before_and_after_packet_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = current.default_current_state(root)
            state["active_story"] = "STORY-CR123-S01"
            current.write_current_state(root, state)
            write_cr_summary(root)
            story = write_story(root)

            _packet, output = story_contract.build_story_packet(
                root,
                story_path=story,
                stage="CP6",
                budget=8000,
            )

            current_entry = json.loads(
                (root / "process" / "current" / "CURRENT.json").read_text(encoding="utf-8")
            )
            self.assertTrue(output.is_file())
            self.assertEqual(
                "process/context/stories/STORY-CR123-S01.CP6.work-packet.json",
                current_entry["story_packet_ref"],
            )
            self.assertEqual([], current.validate_current_projection(root))

    def test_current_entry_without_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current_path = root / "process" / "current" / "CURRENT.json"
            current_path.parent.mkdir(parents=True, exist_ok=True)
            current_path.write_text("{}\n", encoding="utf-8")
            write_cr_summary(root)
            story = write_story(root)

            with self.assertRaisesRegex(ValueError, "runtime state contract is partial"):
                story_contract.build_story_packet(
                    root,
                    story_path=story,
                    stage="CP6",
                    budget=8000,
                )

    def test_invalid_runtime_state_payload_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "process" / "state" / "STATE.current.json"
            current_path = root / "process" / "current" / "CURRENT.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            current_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text("{invalid\n", encoding="utf-8")
            current_path.write_text("{}\n", encoding="utf-8")
            write_cr_summary(root)
            story = write_story(root)

            with self.assertRaisesRegex(ValueError, "runtime state payload is empty or invalid"):
                story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

    def test_runtime_state_projection_drift_is_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            current_path = root / "process" / "current" / "CURRENT.json"
            current_entry = json.loads(current_path.read_text(encoding="utf-8"))
            current_entry["active_story"] = "STORY-DRIFT"
            current_path.write_text(json.dumps(current_entry) + "\n", encoding="utf-8")
            write_cr_summary(root)
            story = write_story(root)

            story_contract.build_story_packet(
                root,
                story_path=story,
                stage="CP6",
                budget=8000,
            )

            current_entry = json.loads(current_path.read_text(encoding="utf-8"))
            self.assertNotEqual("STORY-DRIFT", current_entry["active_story"])
            self.assertEqual([], current.validate_current_projection(root))

    def test_full_lld_story_puts_lld_in_read_if_needed_not_allowed_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root, lld_policy="full-lld")

            packet, _output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            allowed = {entry["path"] for entry in packet["allowed_reads"]}
            read_if_needed = {entry["path"] for entry in packet["read_if_needed"]}
            self.assertNotIn("process/stories/STORY-CR123-S01-LLD.md", allowed)
            self.assertIn("process/stories/STORY-CR123-S01-LLD.md", read_if_needed)
            self.assertEqual(
                [
                    {
                        "operation": "context.read-log",
                        "input_contract": "ReadExpansionPlanV2",
                        "actor": "host-orchestrator",
                        "required_before": "story-dispatch",
                        "requested_refs": [
                            "process/stories/STORY-CR123-S01-LLD.md"
                        ],
                        "reason": "summary_insufficient",
                        "reason_evidence": {
                            "missing_slots": ["full_lld_body"]
                        },
                    }
                ],
                packet["pre_dispatch_actions"],
            )
            self.assertEqual(
                tuple(packet["pre_dispatch_actions"][0]["requested_refs"]),
                read_expansion.select_required_preregistration_refs(packet),
            )
            self.assertEqual(3, packet["schema_version"])
            self.assertEqual("required", packet["read_if_needed"][0]["consumer_requirement"])

    def test_full_lld_packet_rejects_missing_host_preregistration_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root, lld_policy="full-lld")
            packet, output = story_contract.build_story_packet(
                root,
                story_path=story,
                stage="CP6",
                budget=8000,
            )
            packet["pre_dispatch_actions"] = []
            output.write_text(
                json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            errors, _warnings = story_contract.validate_story_packet(
                output,
                project_root=root,
            )

            self.assertIn(
                "deny-default read_if_needed requires exactly one Host pre_dispatch_action",
                errors,
            )

    def test_v3_packet_rejects_invalid_requirement_and_action_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root, lld_policy="full-lld")
            packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            packet["read_if_needed"][0]["consumer_requirement"] = "unknown"
            output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)
            self.assertIn("read_if_needed consumer_requirement must be required, optional or forbidden", errors)
            packet["read_if_needed"][0]["consumer_requirement"] = "required"
            packet["pre_dispatch_actions"][0]["input_contract"] = "ReadExpansionPlanV1"
            output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)
            self.assertIn("Host pre_dispatch_action input_contract must be ReadExpansionPlanV2", errors)
            packet["pre_dispatch_actions"][0]["input_contract"] = "ReadExpansionPlanV2"
            packet["pre_dispatch_actions"][0]["requested_refs"] = ["process/stories/OTHER-LLD.md"]
            output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)
            self.assertIn("Host pre_dispatch_action requested_refs mismatch read_if_needed", errors)

    def test_legacy_v1_packet_remains_readable_but_requires_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root, lld_policy="full-lld")
            packet, output = story_contract.build_story_packet(
                root,
                story_path=story,
                stage="CP6",
                budget=8000,
            )
            packet["schema_version"] = 1
            packet["pre_dispatch_actions"] = []
            output.write_text(
                json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            errors, warnings = story_contract.validate_story_packet(
                output,
                project_root=root,
            )

            self.assertEqual([], errors)
            self.assertTrue(
                any(
                    "regenerate before the next Story dispatch" in warning
                    for warning in warnings
                )
            )

    def test_check_passes_for_valid_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            _packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)

            stream = StringIO()
            with redirect_stdout(stream):
                exit_code = story_contract.main(["check-story-packet", "--packet", str(output), "--project-root", str(root)])

            self.assertEqual(0, exit_code)
            self.assertIn("Story Context Packet Check: OK", stream.getvalue())

    def test_check_rejects_deny_default_allowed_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            packet["allowed_reads"].append(
                {
                    "path": "process/STATE.md",
                    "mode": "full",
                    "estimated_tokens": 1,
                    "required": False,
                    "reason": "legacy_state",
                }
            )
            output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)

            self.assertIn("allowed_reads contains deny-default path: process/STATE.md", errors)

    def test_check_rejects_missing_write_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            packet["allowed_write_paths"] = []
            output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)

            self.assertIn("allowed_write_paths must be non-empty", errors)

    def test_check_rejects_absolute_path_without_echoing_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)
            packet, output = story_contract.build_story_packet(root, story_path=story, stage="CP6", budget=8000)
            packet["story_ref"] = str(story)
            output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)

            self.assertIn("Story packet contains absolute path values at: $.story_ref", errors)
            self.assertNotIn(str(root), "\n".join(errors))

    def test_cli_build_story_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = story_contract.main(
                    ["build-story-packet", "--story", str(story), "--stage", "CP6", "--project-root", str(root)]
                )

            self.assertEqual(0, exit_code)
            self.assertIn("wrote:", output.getvalue())

    def test_context_builder_dispatches_story_packet_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_minimal_state(root)
            write_cr_summary(root)
            story = write_story(root)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = builder.main(
                    ["build-story-packet", "--story", str(story), "--stage", "CP6", "--project-root", str(root)]
                )

            self.assertEqual(0, exit_code)
            self.assertIn("wrote:", output.getvalue())

    def test_p01_v2_revalidation_packet_is_attempt_scoped_and_create_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_revalidation_fixture(root)
            with patch.object(story_contract, "_git_head", side_effect=current_git_heads(root)):
                packet, output = story_contract.build_story_packet(
                    root,
                    story_path=fixture["story"],
                    stage="CP6",
                    budget=8000,
                    revalidation_authorization_ref=fixture["auth_ref"],
                )
                replay, _ = story_contract.build_story_packet(
                    root,
                    story_path=fixture["story"],
                    stage="CP6",
                    budget=8000,
                    revalidation_authorization_ref=fixture["auth_ref"],
                )
            self.assertEqual(4, packet["schema_version"])
            self.assertEqual("APPLIED", packet["packet_write"]["decision"])
            self.assertEqual(fixture["packet_path"], output)
            self.assertEqual(fixture["return_ref"], packet["expected_return_packet"])
            self.assertEqual(fixture["auth_ref"], packet["revalidation_binding"]["authorization_ref"])
            self.assertEqual("NO_CHANGE", replay["packet_write"]["decision"])
            errors, _warnings = story_contract.validate_story_packet(output, project_root=root)
            self.assertEqual([], errors)

    def test_p01_v2_ready_for_verification_without_auth_is_blocked_before_packet_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_revalidation_fixture(root)
            default_packet = root / "process" / "context" / "stories" / "STORY-CR123-S04.CP6.work-packet.json"

            with self.assertRaisesRegex(ValueError, "requires explicit revalidation authorization"):
                story_contract.build_story_packet(
                    root,
                    story_path=fixture["story"],
                    stage="CP6",
                    budget=8000,
                )

            self.assertFalse(default_packet.exists())
            self.assertFalse(fixture["packet_path"].exists())

    def test_p01_v2_authorization_ref_lineage_and_digest_matrix_blocks_before_writer(self) -> None:
        cases = (
            ("non-canonical-auth-ref", "auth-ref"),
            ("previous-missing", "previous-missing"),
            ("previous-digest", "previous-digest"),
            ("superseding-missing", "superseding-missing"),
            ("superseding-digest", "superseding-digest"),
            ("preimage", "preimage"),
        )
        for name, mutation in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture = write_revalidation_fixture(root)
                auth_ref = str(fixture["auth_ref"])
                auth_path = fixture["auth_path"]
                authorization = dict(fixture["authorization"])
                if mutation == "auth-ref":
                    auth_ref = "process/works/WORK-1/revalidation/attempt-1/receipts/alias.json"
                    alias = root / auth_ref
                    alias.write_bytes(auth_path.read_bytes())
                elif mutation == "previous-missing":
                    fixture["previous_path"].unlink()
                elif mutation == "previous-digest":
                    authorization["previous_cp6_digest"] = "0" * 64
                elif mutation == "superseding-missing":
                    fixture["superseding_path"].unlink()
                elif mutation == "superseding-digest":
                    authorization["superseding_cp5_digest"] = "0" * 64
                else:
                    authorization["plan_preimage_digest"] = "0" * 64
                if mutation in {"previous-digest", "superseding-digest", "preimage"}:
                    auth_path.write_text(json.dumps(authorization), encoding="utf-8")

                with patch.object(story_contract, "_git_head", side_effect=current_git_heads(root)), self.assertRaises(ValueError):
                    story_contract.build_story_packet(
                        root,
                        story_path=fixture["story"],
                        stage="CP6",
                        budget=8000,
                        revalidation_authorization_ref=auth_ref,
                    )

                self.assertFalse(fixture["packet_path"].exists())

    def test_p01_v2_authorization_and_native_work_both_must_allow_packet_and_return(self) -> None:
        cases = (
            (
                "authorization-denies-return",
                ["process/works/WORK-1/revalidation/attempt-1/artifacts/*.work-packet.json"],
                ["works/WORK-1/revalidation/attempt-1/artifacts/**"],
            ),
            (
                "work-denies-return",
                ["process/works/WORK-1/revalidation/attempt-1/artifacts/**"],
                ["works/WORK-1/revalidation/attempt-1/artifacts/*.work-packet.json"],
            ),
        )
        for name, authorization_patterns, work_patterns in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture = write_revalidation_fixture(
                    root,
                    authorization_patterns=authorization_patterns,
                    work_patterns=work_patterns,
                )
                with patch.object(story_contract, "_git_head", side_effect=current_git_heads(root)), self.assertRaisesRegex(ValueError, "allowlist"):
                    story_contract.build_story_packet(
                        root,
                        story_path=fixture["story"],
                        stage="CP6",
                        budget=8000,
                        revalidation_authorization_ref=fixture["auth_ref"],
                    )
                self.assertFalse(fixture["packet_path"].exists())

    def test_p01_v2_existing_different_packet_is_blocked_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_revalidation_fixture(root)
            packet_path = fixture["packet_path"]
            packet_path.parent.mkdir(parents=True, exist_ok=True)
            original = b'{"foreign":"bytes"}\n'
            packet_path.write_bytes(original)

            with patch.object(story_contract, "_git_head", side_effect=current_git_heads(root)):
                packet, output = story_contract.build_story_packet(
                    root,
                    story_path=fixture["story"],
                    stage="CP6",
                    budget=8000,
                    revalidation_authorization_ref=fixture["auth_ref"],
                )

            self.assertEqual(packet_path, output)
            self.assertEqual({"decision": "BLOCKED", "mutation_count": 0}, packet["packet_write"])
            self.assertEqual(original, packet_path.read_bytes())

    def test_p01_v2_create_once_fault_matrix_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "new-parent" / "packet.json"
            with patch.object(Path, "mkdir", side_effect=OSError("mkdir")):
                mkdir_result = story_contract._write_revalidation_packet_create_once(target, b"{}\n")
            self.assertEqual("PARTIAL", mkdir_result["decision"])
            self.assertEqual(0, mkdir_result["mutation_count"])

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "packet.json"
            target.write_bytes(b"existing")
            with patch.object(Path, "read_bytes", side_effect=OSError("read")):
                read_result = story_contract._write_revalidation_packet_create_once(target, b"{}\n")
            self.assertEqual({"decision": "PARTIAL", "mutation_count": 0}, read_result)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "packet.json"
            original_read_bytes = Path.read_bytes
            reads = 0

            def fail_postcheck(path: Path) -> bytes:
                nonlocal reads
                reads += 1
                if path == target:
                    raise OSError("postcheck")
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", fail_postcheck):
                postcheck_result = story_contract._write_revalidation_packet_create_once(target, b"{}\n")
            self.assertGreaterEqual(reads, 1)
            self.assertEqual({"decision": "PARTIAL", "mutation_count": 1}, postcheck_result)

    def test_p01_v2_write_fault_after_target_create_counts_target_mutation_and_preserves_partial_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "packet.json"
            real_open = Path.open
            partial = b'{"partial"'

            class WriteThenFail:
                def __enter__(self):
                    self.handle = real_open(target, "xb")
                    return self

                def write(self, _payload: bytes) -> int:
                    self.handle.write(partial)
                    self.handle.flush()
                    raise OSError("injected write-after-create failure")

                def __exit__(self, *_args: object) -> None:
                    self.handle.close()

            with patch.object(Path, "open", return_value=WriteThenFail()):
                result = story_contract._write_revalidation_packet_create_once(
                    target,
                    b'{"complete":true}\n',
                )

            self.assertEqual({"decision": "PARTIAL", "mutation_count": 1}, result)
            self.assertEqual(partial, target.read_bytes())

    def test_p01_v2_v4_validator_reloads_authorization_and_rejects_mutations(self) -> None:
        packet_mutations = (
            ("unknown", lambda packet: packet["revalidation_binding"].__setitem__("unknown", True)),
            ("missing", lambda packet: packet["revalidation_binding"].pop("scope_digest")),
            ("wrong-type", lambda packet: packet["revalidation_binding"].__setitem__("version", True)),
            ("cross-story", lambda packet: packet["revalidation_binding"].__setitem__("story_id", "STORY-OTHER")),
            ("cross-return", lambda packet: packet.__setitem__("expected_return_packet", "process/returns/OTHER.json")),
            ("non-canonical-auth", lambda packet: packet["revalidation_binding"].__setitem__("authorization_ref", "process/works/WORK-1/revalidation/attempt-1/receipts/alias.json")),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_revalidation_fixture(root)
            with patch.object(story_contract, "_git_head", side_effect=current_git_heads(root)):
                _packet, packet_path = story_contract.build_story_packet(
                    root,
                    story_path=fixture["story"],
                    stage="CP6",
                    budget=8000,
                    revalidation_authorization_ref=fixture["auth_ref"],
                )
            original = packet_path.read_bytes()
            for name, mutate in packet_mutations:
                with self.subTest(name=name):
                    packet = json.loads(original)
                    mutate(packet)
                    packet_path.write_text(json.dumps(packet), encoding="utf-8")
                    errors, _warnings = story_contract.validate_story_packet(packet_path, project_root=root)
                    self.assertIn("schema_version=4 revalidation_binding is invalid", errors)
            packet_path.write_bytes(original)
            original_auth = fixture["auth_path"].read_bytes()
            fixture["auth_path"].write_bytes(original_auth + b"\n")
            errors, _warnings = story_contract.validate_story_packet(packet_path, project_root=root)
            self.assertIn("schema_version=4 revalidation_binding is invalid", errors)
            fixture["auth_path"].write_bytes(original_auth)
            tampered_payload = json.loads(original_auth)
            tampered_payload["allowed_write_paths"] = [
                "process/works/WORK-1/revalidation/attempt-1/artifacts/*.json"
            ]
            fixture["auth_path"].write_text(json.dumps(tampered_payload), encoding="utf-8")
            errors, _warnings = story_contract.validate_story_packet(packet_path, project_root=root)
            self.assertIn("schema_version=4 revalidation_binding is invalid", errors)
            fixture["auth_path"].write_bytes(original_auth)
            fixture["auth_path"].unlink()
            errors, _warnings = story_contract.validate_story_packet(packet_path, project_root=root)
            self.assertIn("schema_version=4 revalidation_binding is invalid", errors)

    def test_p01_v2_v4_validator_uses_inferred_root_to_reload_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_revalidation_fixture(root)
            with patch.object(story_contract, "_git_head", side_effect=current_git_heads(root)):
                _packet, packet_path = story_contract.build_story_packet(
                    root,
                    story_path=fixture["story"],
                    stage="CP6",
                    budget=8000,
                    revalidation_authorization_ref=fixture["auth_ref"],
                )
            errors, _warnings = story_contract.validate_story_packet(packet_path)
            self.assertEqual([], errors)

            original_auth = fixture["auth_path"].read_bytes()
            fixture["auth_path"].write_bytes(original_auth + b"\n")
            errors, _warnings = story_contract.validate_story_packet(packet_path)
            self.assertIn("schema_version=4 revalidation_binding is invalid", errors)

            fixture["auth_path"].write_bytes(original_auth)
            tampered_payload = json.loads(original_auth)
            tampered_payload["allowed_write_paths"] = [
                "process/works/WORK-1/revalidation/attempt-1/artifacts/*.json"
            ]
            fixture["auth_path"].write_text(json.dumps(tampered_payload), encoding="utf-8")
            errors, _warnings = story_contract.validate_story_packet(packet_path)
            self.assertIn("schema_version=4 revalidation_binding is invalid", errors)
            fixture["auth_path"].unlink()
            errors, _warnings = story_contract.validate_story_packet(packet_path)
            self.assertIn("schema_version=4 revalidation_binding is invalid", errors)

    def test_p01_v2_public_subcommand_exit_and_output_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = write_revalidation_fixture(root)
            argv = [
                "build-story-packet",
                "--story", str(fixture["story"]),
                "--stage", "CP6",
                "--project-root", str(root),
                "--revalidation-authorization", str(fixture["auth_ref"]),
            ]
            stream = StringIO()
            with patch.object(story_contract, "_git_head", side_effect=current_git_heads(root)), redirect_stdout(stream):
                applied = story_contract.main(argv)
                no_change = story_contract.main(argv)
            self.assertEqual((0, 0), (applied, no_change))
            self.assertEqual(2, stream.getvalue().count("wrote:"))

            fixture["packet_path"].write_bytes(b"different\n")
            stream = StringIO()
            with patch.object(story_contract, "_git_head", side_effect=current_git_heads(root)), redirect_stdout(stream):
                blocked = story_contract.main(argv)
            self.assertNotEqual(0, blocked)
            self.assertIn("Story packet: BLOCKED", stream.getvalue())
            self.assertNotIn("wrote:", stream.getvalue())

            fixture["packet_path"].unlink()
            stream = StringIO()
            with patch.object(story_contract, "_git_head", side_effect=current_git_heads(root)), patch.object(
                story_contract,
                "_write_revalidation_packet_create_once",
                return_value={"decision": "PARTIAL", "mutation_count": 0},
            ), redirect_stdout(stream):
                partial = story_contract.main(argv)
            self.assertNotEqual(0, partial)
            self.assertIn("Story packet: PARTIAL", stream.getvalue())
            self.assertNotIn("wrote:", stream.getvalue())

    def test_p01_v2_revalidation_rejects_stale_current_facts_before_writer(self) -> None:
        for field in ("release_oid", "process_oid"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture = write_revalidation_fixture(root)

                def stale_head(
                    path: Path,
                    *,
                    fixture_root: Path = root,
                    stale_field: str = field,
                ) -> str:
                    is_release = path.resolve() == fixture_root.resolve()
                    if stale_field == "release_oid" and is_release:
                        return "0" * 40
                    if stale_field == "process_oid" and not is_release:
                        return "0" * 40
                    return "a" * 40 if is_release else "b" * 40

                with patch.object(story_contract, "_git_head", side_effect=stale_head), self.assertRaisesRegex(ValueError, "current facts mismatch"):
                    story_contract.build_story_packet(
                        root,
                        story_path=fixture["story"],
                        stage="CP6",
                        budget=8000,
                        revalidation_authorization_ref=fixture["auth_ref"],
                    )
                self.assertFalse(fixture["packet_path"].exists())

    def test_p01_v2_create_once_open_fault_after_parent_mkdir_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new-parent" / "packet.json"
            with patch.object(Path, "open", side_effect=OSError("injected open failure")):
                result = story_contract._write_revalidation_packet_create_once(target, b"{}\n")
            self.assertEqual({"decision": "PARTIAL", "mutation_count": 1}, result)
            self.assertTrue(target.parent.is_dir())

    def test_p01_v2_real_work_scope_normalizes_only_valid_process_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "process" / "works" / "WORK-1" / "WORK.yaml"
            work.parent.mkdir(parents=True)
            work.write_text(json.dumps({"work_id": "WORK-1", "status": "active", "scope_digest": "c" * 64, "scope": {"allowed_writes": ["works/WORK-1/**"]}}), encoding="utf-8")
            auth_path = root / "process" / "works" / "WORK-1" / "revalidation" / "attempt-1" / "receipts" / "authorization.json"
            auth_path.parent.mkdir(parents=True)
            auth_path.write_text(json.dumps({"schema_version": 1, "cr_id": "CR-123", "story_id": "STORY-CR123-S04", "work_id": "WORK-1", "attempt_id": "attempt-1", "release_oid": "a" * 40, "process_oid": "b" * 40, "scope_digest": "c" * 64, "previous_cp6_ref": "process/checks/old.json", "previous_cp6_digest": "d" * 64, "superseding_cp5_ref": "process/checks/new.json", "superseding_cp5_digest": "e" * 64, "plan_preimage_digest": "f" * 64, "allowed_write_paths": ["process/works/WORK-1/revalidation/attempt-1/artifacts/**"]}), encoding="utf-8")
            authorization, _digest = story_contract._load_revalidation_authorization(root, "process/works/WORK-1/revalidation/attempt-1/receipts/authorization.json")
            packet_ref, return_ref = story_contract._revalidation_artifact_refs(authorization)
            self.assertTrue(story_contract._native_work_allowed_targets(root, authorization, packet_ref, return_ref))
            self.assertFalse(story_contract._native_work_allowed_targets(root, authorization, packet_ref.replace("WORK-1", "OTHER"), return_ref))

    def test_p01_v2_current_work_fact_matrix_reads_real_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth_path = root / "process" / "works" / "WORK-1" / "revalidation" / "attempt-1" / "receipts" / "authorization.json"
            auth_path.parent.mkdir(parents=True)
            auth_path.write_text(json.dumps({"schema_version": 1, "cr_id": "CR-123", "story_id": "STORY-CR123-S04", "work_id": "WORK-1", "attempt_id": "attempt-1", "release_oid": "a" * 40, "process_oid": "b" * 40, "scope_digest": "c" * 64, "previous_cp6_ref": "process/checks/old.json", "previous_cp6_digest": "d" * 64, "superseding_cp5_ref": "process/checks/new.json", "superseding_cp5_digest": "e" * 64, "plan_preimage_digest": "f" * 64, "allowed_write_paths": ["process/works/WORK-1/revalidation/attempt-1/artifacts/**"]}), encoding="utf-8")
            authorization, _ = story_contract._load_revalidation_authorization(root, "process/works/WORK-1/revalidation/attempt-1/receipts/authorization.json")
            work_path = root / "process" / "works" / "WORK-1" / "WORK.yaml"
            for status, work_id, scope_ok, expected in (("active", "WORK-1", True, True), ("paused", "WORK-1", True, False), ("completed", "WORK-1", True, False), ("active", "OTHER", True, False), ("active", "WORK-1", False, False)):
                with self.subTest(status=status, work_id=work_id, scope_ok=scope_ok):
                    work_path.write_text(json.dumps({"work_id": work_id, "status": status, "scope_digest": "c" * 64 if scope_ok else "bad", "scope": {"allowed_writes": ["works/WORK-1/**"]}}), encoding="utf-8")
                    with patch.object(story_contract, "_git_head", side_effect=["a" * 40, "b" * 40]):
                        if expected:
                            self.assertEqual("c" * 64, story_contract._current_revalidation_facts(root, authorization)["scope_digest"])
                        else:
                            with self.assertRaises(ValueError):
                                story_contract._current_revalidation_facts(root, authorization)


if __name__ == "__main__":
    unittest.main()
