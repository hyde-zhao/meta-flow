from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from functools import partial
from pathlib import Path
from unittest.mock import patch

from cr_lifecycle_test_support import LifecycleFixtureCollaborators
from cr_lifecycle_test_support import init_binding_project as _init_binding_project
from cr_lifecycle_test_support import write_termination_fixture as _write_termination_fixture

from meta_flow.project.onboarding import ProjectInitRequest, apply_project_init, plan_project_init
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.semantics.cr_status import validate_native_status_tuple, validate_native_transition
from meta_flow.state import current
from meta_flow.work.scope import WorkScope
from meta_flow.workflow import cr_termination
from meta_flow.workflow.cr_model import render_frontmatter_fields
from meta_flow.workflow.cr_termination_journal import CoordinationJournal, JournalBlocked

_FIXTURE_COLLABORATORS = LifecycleFixtureCollaborators(
    project_init_request=ProjectInitRequest,
    plan_project_init=plan_project_init,
    apply_project_init=apply_project_init,
    onboarding_authorization=OnboardingAuthorization,
    authorization_source=AUTHORIZATION_SOURCE,
    authorization_kind=AUTHORIZATION_KIND,
    resolve_runtime_ref=_resolve_runtime_ref,
    dump_yaml=dump_yaml,
    load_yaml_object=load_yaml_object,
    work_scope=WorkScope,
)
init_binding_project = partial(
    _init_binding_project,
    collaborators=_FIXTURE_COLLABORATORS,
)
write_termination_fixture = partial(
    _write_termination_fixture,
    collaborators=_FIXTURE_COLLABORATORS,
)


def _write_fixture(
    root: Path,
    *,
    cr_id: str = "CR-101",
    lifecycle_status: str = "active",
    readiness_status: str = "NOT_READY",
    gate_status: str = "cp8_pending",
    work_status: str = "active",
    retain_active_refs: bool = True,
    include_state_current: bool = False,
) -> tuple[Path, Path, Path, WorkScope]:
    release, process, cr_path, scope = write_termination_fixture(
        root,
        cr_id=cr_id,
        work_id=cr_id,
    )
    (process / "changes" / "summaries").mkdir(parents=True, exist_ok=True)
    (process / "state").mkdir(parents=True, exist_ok=True)
    (process / "current").mkdir(parents=True, exist_ok=True)
    cr_path.write_text(
        render_frontmatter_fields(
            cr_path.read_text(encoding="utf-8"),
            {
                "lifecycle_status": lifecycle_status,
                "readiness_status": readiness_status,
                "gate_status": gate_status,
            },
        ),
        encoding="utf-8",
    )
    work_path = process / "works" / cr_id / "WORK.yaml"
    work = load_yaml_object(work_path)
    work["status"] = work_status
    work_path.write_text(dump_yaml(work) + "\n", encoding="utf-8")
    if not retain_active_refs:
        project_path = process / "PROJECT.yaml"
        project = load_yaml_object(project_path)
        project.pop("active_work_refs", None)
        project_path.write_text(dump_yaml(project) + "\n", encoding="utf-8")
        phase_path = process / "phases" / "P1-termination" / "PHASE.yaml"
        phase = load_yaml_object(phase_path)
        phase["work_refs"] = []
        phase_path.write_text(dump_yaml(phase) + "\n", encoding="utf-8")
    if include_state_current:
        state = current.default_current_state(release, project_id="fixture")
        state.update(
            {
                "current_phase": "verification",
                "active_change": cr_id,
                "pending_gate": f"GATE-{cr_id}",
                "next_action": {
                    "type": "human_gate",
                    "text": f"Review {cr_id}",
                },
            }
        )
        state_path = process / "state" / "STATE.current.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        entry = current.build_current_entry(release, state_snapshot=state)
        entry_path = process / "current" / "CURRENT.json"
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        entry_path.write_text(
            json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return release, process, cr_path, scope


def _authorization(
    plan: cr_termination.TerminationPlan,
    *,
    authorization_id: str = "AUTH-TERMINATE-001",
) -> cr_termination.TerminationAuthorization:
    return cr_termination.TerminationAuthorization(
        schema_version=2,
        authorization_id=authorization_id,
        authorization_source=cr_termination.TERMINATION_AUTHORIZATION_SOURCE,
        authorization_kind=cr_termination.TERMINATION_AUTHORIZATION_KIND,
        operation=cr_termination.TERMINATION_OPERATION,
        cr_id=plan.cr_id,
        work_id=plan.work_id,
        termination_reason=plan.termination_reason,
        terminal_tuple=plan.terminal_tuple,
        authority_revision=cr_termination.AUTHORITY_REVISION,
        authority_digest=plan.authority_digest,
        source_tuple=plan.source_tuple,
        source_tuple_digest=plan.source_tuple_digest,
        target_set_digest=plan.target_set_digest,
        target_preimage_digest=plan.target_preimage_digest,
        mutation_allowlist_digest=plan.mutation_allowlist_digest,
        preservation_digest=plan.preservation_digest,
        lock_preimage_digest=plan.lock_preimage_digest,
        plan_digest=plan.plan_digest,
        expires_at="2099-01-01T00:00:00+00:00",
        single_use=True,
    )


def _plan(
    release: Path,
    *,
    cr_id: str = "CR-101",
    status: str = "cancelled",
    reason: str = "由替代路线接管",
) -> cr_termination.TerminationPlan:
    return cr_termination.plan_cr_termination(
        release,
        cr_id,
        work_id=cr_id,
        termination_status=status,
        termination_reason=reason,
    )


def _journal_root(process: Path) -> Path:
    common_text = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=process,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    common = Path(common_text)
    if not common.is_absolute():
        common = process / common
    return common.resolve() / "meta-flow" / "cr-termination-v2"


class CRTerminationTests(unittest.TestCase):
    def test_real_source_target_tuples_use_tuple_validator_not_transition_edges(self) -> None:
        cases = (
            (
                ("blocked", "not_ready", "cp8_pending"),
                ("cancelled", "n/a", "closed"),
            ),
            (
                ("active", "not_ready", "cp2_pending"),
                ("superseded", "n/a", "closed"),
            ),
        )
        for source, target in cases:
            with self.subTest(source=source, target=target):
                self.assertEqual([], validate_native_status_tuple(*source))
                self.assertEqual([], validate_native_status_tuple(*target))
                self.assertTrue(validate_native_transition(source, target))

    def test_plan_projects_closed_authority_and_reads_only_after_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, cr_path, _scope = _write_fixture(Path(directory))
            before = cr_path.read_bytes()

            plan = _plan(release)

            self.assertEqual("READY", plan.decision)
            self.assertEqual(0, plan.read_audit["unsafe_byte_reads"])
            self.assertTrue(plan.read_audit["inventory_complete_before_target_read"])
            self.assertEqual(cr_termination.SOURCE_TUPLE_FIELDS, set(plan.source_tuple))
            self.assertNotIn("scope_digest", plan.as_dict())
            self.assertEqual(
                ["formal_cr", "work", "project", "phase", "summary", "ledger", "index"],
                [target.role for target in plan.eligible_targets],
            )
            self.assertEqual(before, cr_path.read_bytes())
            self.assertFalse((_journal_root(_process)).exists())

    def test_business_scope_expansion_or_contraction_cannot_change_target_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            work_path = process / "works" / "CR-101" / "WORK.yaml"
            payload = load_yaml_object(work_path)

            narrow = WorkScope(1, (), (), ("cr-termination",))
            payload["scope"] = narrow.as_dict()
            payload["scope_digest"] = narrow.digest
            work_path.write_text(dump_yaml(payload) + "\n", encoding="utf-8")
            narrow_plan = _plan(release)

            broad = WorkScope(
                1,
                ("PROJECT.yaml", "changes/**", "state/**", "works/**"),
                ("PROJECT.yaml", "changes/**", "state/**", "works/**"),
                ("cr-termination",),
            )
            payload["scope"] = broad.as_dict()
            payload["scope_digest"] = broad.digest
            work_path.write_text(dump_yaml(payload) + "\n", encoding="utf-8")
            broad_plan = _plan(release)

            self.assertEqual("READY", narrow_plan.decision)
            self.assertEqual("READY", broad_plan.decision)
            self.assertEqual(narrow_plan.target_set_digest, broad_plan.target_set_digest)
            self.assertNotEqual(
                narrow_plan.target_preimage_digest,
                broad_plan.target_preimage_digest,
            )

    def test_already_cancelled_work_without_refs_is_eligible_but_not_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = _write_fixture(
                Path(directory),
                lifecycle_status="blocked",
                work_status="cancelled",
                retain_active_refs=False,
            )

            plan = _plan(release)

            self.assertEqual("READY", plan.decision)
            self.assertIn("work", {target.role for target in plan.eligible_targets})
            self.assertNotIn("work", {target.role for target in plan.targets})
            self.assertNotIn("project", {target.role for target in plan.targets})
            self.assertNotIn("phase", {target.role for target in plan.targets})

    def test_active_work_missing_required_refs_is_blocked_zero_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, cr_path, _scope = _write_fixture(
                Path(directory),
                retain_active_refs=False,
            )
            before = cr_path.read_bytes()

            plan = _plan(release)

            self.assertEqual("BLOCKED", plan.decision)
            self.assertIn("missing from PROJECT", plan.reason)
            self.assertEqual((), plan.targets)
            self.assertEqual(before, cr_path.read_bytes())

    def test_primary_work_substitution_is_blocked_before_non_work_target_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            source = process / "works" / "CR-101" / "WORK.yaml"
            successor = process / "works" / "SUCCESSOR" / "WORK.yaml"
            successor.parent.mkdir(parents=True)
            payload = load_yaml_object(source)
            payload["work_id"] = "SUCCESSOR"
            payload["request_ref"] = "works/SUCCESSOR/REQUEST.md"
            payload["usage_ref"] = "works/SUCCESSOR/USAGE.json"
            successor.write_text(dump_yaml(payload) + "\n", encoding="utf-8")

            plan = cr_termination.plan_cr_termination(
                release,
                "CR-101",
                work_id="SUCCESSOR",
                termination_status="cancelled",
                termination_reason="非法 successor 替换",
            )

            self.assertEqual("BLOCKED", plan.decision)
            self.assertIn("fixed primary Work identity", plan.reason)
            self.assertEqual(0, plan.read_audit["unsafe_byte_reads"])

    def test_state_and_current_are_conditional_roles_and_are_cleared_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(
                Path(directory),
                include_state_current=True,
            )
            plan = _plan(release)

            self.assertEqual("READY", plan.decision)
            self.assertIn("state", {target.role for target in plan.targets})
            self.assertIn("current_view", {target.role for target in plan.targets})
            result = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=_authorization(plan),
                expected_plan_digest=plan.plan_digest,
            )
            self.assertEqual("PASS", result["status"])
            state = json.loads(
                (process / "state" / "STATE.current.json").read_text(encoding="utf-8")
            )
            entry = json.loads((process / "current" / "CURRENT.json").read_text(encoding="utf-8"))
            self.assertIsNone(state["active_change"])
            self.assertIsNone(state["pending_gate"])
            self.assertIsNone(entry["active_change"])
            self.assertIsNone(entry["pending_gate"])
            self.assertNotIn("CR-101", json.dumps(entry, ensure_ascii=False))

    def test_path_symlink_and_inode_alias_mutants_fail_closed(self) -> None:
        with self.subTest("symlink-leaf"), tempfile.TemporaryDirectory() as directory:
            release, process, cr_path, _scope = _write_fixture(Path(directory))
            outside = Path(directory) / "outside.md"
            outside.write_text(cr_path.read_text(encoding="utf-8"), encoding="utf-8")
            cr_path.unlink()
            cr_path.symlink_to(outside)
            plan = _plan(release)
            self.assertEqual("BLOCKED", plan.decision)
            self.assertIn("symlink", plan.reason)

        with self.subTest("inode-alias"), tempfile.TemporaryDirectory() as directory:
            release, process, cr_path, _scope = _write_fixture(Path(directory))
            index_path = process / "changes" / "CR-INDEX.json"
            os.link(cr_path, index_path)
            plan = _plan(release)
            self.assertEqual("BLOCKED", plan.decision)
            self.assertIn("inode alias", plan.reason)

    def test_missing_or_replaced_createable_parent_is_blocked_before_domain_write(self) -> None:
        with self.subTest("missing-parent"), tempfile.TemporaryDirectory() as directory:
            release, process, cr_path, _scope = _write_fixture(Path(directory))
            summary_parent = process / "changes" / "summaries"
            summary_parent.rmdir()
            before = cr_path.read_bytes()
            plan = _plan(release)
            self.assertEqual("BLOCKED", plan.decision)
            self.assertIn("required summary path is missing", plan.reason)
            self.assertEqual(before, cr_path.read_bytes())

        with self.subTest("parent-race"), tempfile.TemporaryDirectory() as directory:
            release, process, cr_path, _scope = _write_fixture(Path(directory))
            plan = _plan(release)
            authorization = _authorization(plan)
            summary_parent = process / "changes" / "summaries"
            summary_parent.rmdir()
            outside = Path(directory) / "outside-summary"
            outside.mkdir()
            summary_parent.symlink_to(outside, target_is_directory=True)
            before = cr_path.read_bytes()
            result = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
            )
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual(0, result["mutation_count"])
            self.assertEqual(before, cr_path.read_bytes())
            self.assertEqual([], list(outside.iterdir()))

    def test_header_duplicate_oversize_and_missing_nofollow_are_blocked(self) -> None:
        with self.subTest("duplicate"), tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            work_path = process / "works" / "CR-101" / "WORK.yaml"
            work_path.write_text(
                work_path.read_text(encoding="utf-8") + "work_id: CR-101\n",
                encoding="utf-8",
            )
            self.assertIn("duplicate header", _plan(release).reason)

        with self.subTest("oversize"), tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            work_path = process / "works" / "CR-101" / "WORK.yaml"
            work_path.write_text("x" * (16 * 1024 + 1), encoding="utf-8")
            self.assertIn("bounded read", _plan(release).reason)

        with self.subTest("nofollow"), tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = _write_fixture(Path(directory))
            with patch.object(cr_termination.os, "O_NOFOLLOW", new=None, create=True):
                # hasattr 仍为真时 None 会在 flags 运算中失败，也必须 fail closed。
                plan = _plan(release)
            self.assertEqual("BLOCKED", plan.decision)
            self.assertEqual(0, plan.read_audit.get("unsafe_byte_reads", 0))

    def test_authorization_v2_loader_rejects_v1_extra_and_missing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = _write_fixture(Path(directory))
            plan = _plan(release)
            payload = _authorization(plan).__dict__
            root = Path(directory)

            for name, mutant in (
                ("v1", {**payload, "schema_version": 1}),
                ("extra", {**payload, "scope_digest": "0" * 64}),
                (
                    "missing",
                    {key: value for key, value in payload.items() if key != "authority_digest"},
                ),
            ):
                with self.subTest(name=name):
                    path = root / f"{name}.json"
                    path.write_text(json.dumps(mutant) + "\n", encoding="utf-8")
                    if name == "v1":
                        loaded = cr_termination.load_termination_authorization(path)
                        with self.assertRaisesRegex(ValueError, "schema_version must be 2"):
                            cr_termination.validate_termination_authorization(plan, loaded)
                    else:
                        with self.assertRaisesRegex(ValueError, "fields mismatch"):
                            cr_termination.load_termination_authorization(path)

            authorization = _authorization(plan)
            with self.assertRaisesRegex(ValueError, "authorization_id is invalid"):
                cr_termination.validate_termination_authorization(
                    plan,
                    replace(authorization, authorization_id=123),  # type: ignore[arg-type]
                )
            with self.assertRaisesRegex(ValueError, "route_mode is invalid"):
                cr_termination.validate_termination_authorization(
                    plan,
                    replace(
                        authorization,
                        source_tuple={**authorization.source_tuple, "route_mode": []},
                    ),
                )

    def test_authorization_digest_cross_substitution_and_replay_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = _write_fixture(Path(directory))
            plan = _plan(release)
            authorization = _authorization(plan)
            crossed = replace(
                authorization,
                target_set_digest=authorization.target_preimage_digest,
            )

            invalid = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=crossed,
                expected_plan_digest=plan.plan_digest,
            )
            self.assertEqual("BLOCKED", invalid["status"])
            self.assertEqual(0, invalid["mutation_count"])

            recovered = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
                _fail_after_replace=1,
            )
            replay = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
            )
            self.assertEqual("RECOVERED", recovered["status"])
            self.assertEqual("BLOCKED", replay["status"])
            self.assertIn("already consumed", replay["reason"])

    def test_invalid_authorization_does_not_acquire_lock_or_create_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            plan = _plan(release)
            invalid = replace(_authorization(plan), plan_digest="0" * 64)
            with patch.object(cr_termination, "_acquire_status_sync_writer_lock") as lock:
                result = cr_termination.apply_cr_termination(
                    release,
                    plan,
                    authorization=invalid,
                    expected_plan_digest=plan.plan_digest,
                )
            self.assertEqual("BLOCKED", result["status"])
            lock.assert_not_called()
            self.assertFalse(_journal_root(process).exists())

    def test_lock_in_forged_plan_dirty_cas_and_no_change_evidence_fail_closed(self) -> None:
        with self.subTest("lock-in-drift"), tempfile.TemporaryDirectory() as directory:
            release, process, cr_path, _scope = _write_fixture(Path(directory))
            plan = _plan(release)
            authorization = _authorization(plan)
            cr_path.write_text(
                cr_path.read_text(encoding="utf-8") + "\nlock-in-drift\n",
                encoding="utf-8",
            )
            before = cr_path.read_bytes()
            result = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
            )
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual(0, result["mutation_count"])
            self.assertEqual(before, cr_path.read_bytes())

        with self.subTest("forged-role-plan"), tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = _write_fixture(Path(directory))
            plan = _plan(release)
            forged_first = replace(plan.targets[0], role="index")
            forged = replace(plan, targets=(forged_first, *plan.targets[1:]))
            result = cr_termination.apply_cr_termination(
                release,
                forged,
                authorization=_authorization(forged),
                expected_plan_digest=forged.plan_digest,
            )
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual(0, result["mutation_count"])

        with self.subTest("journal-dirty-cas"), tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            before = _plan(release).source_tuple["process_dirty_path_digest"]
            plan = _plan(release)
            CoordinationJournal(
                process_git_common_dir=cr_termination._git_common_dir(process),
                project_id="fixture",
                process_git_common_dir_identity=plan.source_tuple[
                    "process_git_common_dir_identity"
                ],
            )
            after = _plan(release).source_tuple["process_dirty_path_digest"]
            self.assertEqual(before, after)

        with self.subTest("no-change-evidence-missing"), tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            evidence_path = process / "archive" / "CR-101" / "evidence-index.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text('{"result":"PASS"}\n', encoding="utf-8")
            summary_path = process / "changes" / "summaries" / "CR-101.summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "id": "CR-101",
                        "full_ref": "process/changes/CR-101.md",
                        "status": "active",
                        "readiness": "not_ready",
                        "gate_status": "cp8_pending",
                        "evidence_index_ref": "process/archive/CR-101/evidence-index.json",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            plan = _plan(release)
            applied = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=_authorization(plan),
                expected_plan_digest=plan.plan_digest,
            )
            self.assertEqual("PASS", applied["status"])
            self.assertEqual("NO_CHANGE", _plan(release).decision)
            evidence_path.unlink()
            incomplete = _plan(release)
            self.assertEqual("BLOCKED", incomplete.decision)
            self.assertIn("evidence", incomplete.reason.lower())

        with self.subTest("evidence-ref-authority"), tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            summary_path = process / "changes" / "summaries" / "CR-101.summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "id": "CR-101",
                        "full_ref": "process/changes/CR-101.md",
                        "status": "active",
                        "readiness": "not_ready",
                        "gate_status": "cp8_pending",
                        "evidence_index_ref": "release/outside.json",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            blocked = _plan(release)
            self.assertEqual("BLOCKED", blocked.decision)
            self.assertIn("process logical ref", blocked.reason)

    def test_apply_success_preserves_evidence_and_repeated_plan_is_no_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            evidence_path = process / "archive" / "CR-101" / "evidence-index.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text('{"result":"PASS"}\n', encoding="utf-8")
            summary_path = process / "changes" / "summaries" / "CR-101.summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps(
                    {
                        "id": "CR-101",
                        "full_ref": "process/changes/CR-101.md",
                        "title": "preserved",
                        "status": "active",
                        "readiness": "not_ready",
                        "gate_status": "cp8_pending",
                        "decision": "pending",
                        "evidence_index_ref": "process/archive/CR-101/evidence-index.json",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            plan = _plan(release)
            result = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=_authorization(plan),
                expected_plan_digest=plan.plan_digest,
            )

            self.assertEqual("PASS", result["status"])
            self.assertFalse(result["promotion_pending"])
            self.assertTrue(
                (_journal_root(process) / "terminal" / result["transaction_id"]).is_dir()
            )
            self.assertEqual('{"result":"PASS"}\n', evidence_path.read_text(encoding="utf-8"))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual("preserved", summary["title"])
            self.assertEqual(plan.preservation_digest, summary["preservation_digest"])
            repeated = _plan(release)
            self.assertEqual("NO_CHANGE", repeated.decision)

    def test_replace_before_accounting_recovers_from_durable_attempted_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, cr_path, _scope = _write_fixture(Path(directory))
            before = cr_path.read_bytes()
            plan = _plan(release)

            result = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=_authorization(plan),
                expected_plan_digest=plan.plan_digest,
                _fault="replace-before-accounting",
            )

            self.assertEqual("RECOVERED", result["status"])
            self.assertEqual(1, result["mutation_count"])
            self.assertEqual(before, cr_path.read_bytes())
            terminal = _journal_root(process) / "terminal" / result["transaction_id"]
            self.assertTrue(terminal.is_dir())
            self.assertTrue(any("RECOVERED" in path.name for path in terminal.glob("*.json")))

    def test_restore_failure_retains_partial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            plan = _plan(release)

            result = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=_authorization(plan),
                expected_plan_digest=plan.plan_digest,
                _fail_after_replace=1,
                _fail_recovery=True,
            )

            self.assertEqual("PARTIAL", result["status"])
            active = _journal_root(process) / "active" / result["transaction_id"]
            self.assertTrue(active.is_dir())
            self.assertTrue(any("PARTIAL" in path.name for path in active.glob("*.json")))
            self.assertIn("/active/", result["rollback_evidence_ref"])

    def test_committed_promotion_failure_returns_pass_with_pending_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            plan = _plan(release)

            result = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=_authorization(plan),
                expected_plan_digest=plan.plan_digest,
                _fault="promotion.before_replace",
            )

            self.assertEqual("PASS", result["status"])
            self.assertTrue(result["promotion_pending"])
            self.assertTrue((_journal_root(process) / "active" / result["transaction_id"]).is_dir())
            repeated = _plan(release)
            self.assertEqual("NO_CHANGE", repeated.decision)
            retried = cr_termination.apply_cr_termination(
                release,
                repeated,
                authorization=None,
                expected_plan_digest=repeated.plan_digest,
            )
            self.assertEqual("NO_CHANGE", retried["status"])
            self.assertEqual(1, retried["promotion_retried"])
            self.assertTrue(
                (_journal_root(process) / "terminal" / result["transaction_id"]).is_dir()
            )

        with self.subTest("committed-record-fault"), tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            plan = _plan(release)
            result = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=_authorization(plan),
                expected_plan_digest=plan.plan_digest,
                _fault="record.COMMITTED.after_persist",
            )
            self.assertEqual("PASS", result["status"])
            self.assertEqual("COMMITTED", result["recovery_status"])
            self.assertFalse(result["promotion_pending"])
            self.assertTrue(
                (_journal_root(process) / "terminal" / result["transaction_id"]).is_dir()
            )

        with self.subTest("promotion-after-replace"), tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            plan = _plan(release)
            result = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=_authorization(plan),
                expected_plan_digest=plan.plan_digest,
                _fault="promotion.after_replace",
            )
            self.assertEqual("PASS", result["status"])
            self.assertFalse(result["promotion_pending"])
            self.assertIn("/terminal/", result["journal_evidence_ref"])
            self.assertTrue(
                (_journal_root(process) / "terminal" / result["transaction_id"]).is_dir()
            )

    def test_journal_closed_schema_rejects_unknown_phase_payload_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = _write_fixture(Path(directory))
            plan = _plan(release)
            journal = CoordinationJournal(
                process_git_common_dir=cr_termination._git_common_dir(process),
                project_id="fixture",
                process_git_common_dir_identity=plan.source_tuple[
                    "process_git_common_dir_identity"
                ],
            )
            with self.assertRaisesRegex(JournalBlocked, "fields mismatch"):
                journal.append(
                    "TX-001",
                    "PREPARED",
                    {
                        "authorization_id": "AUTH-1",
                        "authority_digest": "0" * 64,
                        "source_tuple_digest": "0" * 64,
                        "target_set_digest": "0" * 64,
                        "target_preimage_digest": "0" * 64,
                        "mutation_allowlist_digest": "0" * 64,
                        "preservation_digest": "0" * 64,
                        "plan_digest": "0" * 64,
                        "targets": [],
                        "unknown": True,
                    },
                )
            invalid_type_payload = {
                "authorization_id": "AUTH-2",
                "authority_digest": 0,
                "source_tuple_digest": "0" * 64,
                "target_set_digest": "0" * 64,
                "target_preimage_digest": "0" * 64,
                "mutation_allowlist_digest": "0" * 64,
                "preservation_digest": "0" * 64,
                "plan_digest": "0" * 64,
                "targets": [],
            }
            with self.assertRaisesRegex(JournalBlocked, "SHA-256"):
                journal.append("TX-002", "PREPARED", invalid_type_payload)

            valid_payload = {**invalid_type_payload, "authority_digest": "0" * 64}
            journal.append("TX-003", "PREPARED", valid_payload)
            transaction_dir = journal.transaction_dir("TX-003")
            (transaction_dir / "unexpected.txt").write_text("mutant\n", encoding="utf-8")
            with self.assertRaisesRegex(JournalBlocked, "unexpected entry"):
                journal.records("TX-003")

            journal.append("TX-004", "PREPARED", valid_payload)
            record_path = journal.transaction_dir("TX-004") / "000001-PREPARED.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["payload"]["authority_digest"] = "1" * 64
            record_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(JournalBlocked, "record digest mismatch"):
                journal.records("TX-004")


if __name__ == "__main__":
    unittest.main()
