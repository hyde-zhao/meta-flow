from __future__ import annotations

import ast
import json
import tempfile
import unittest
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
from meta_flow.work.scope import WorkScope
from meta_flow.workflow import cr_projection, cr_records, cr_termination

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


def termination_authorization(
    plan: cr_termination.TerminationPlan,
    *,
    authorization_id: str = "AUTH-TERMINATE-001",
) -> cr_termination.TerminationAuthorization:
    return cr_termination.TerminationAuthorization(
        schema_version=1,
        authorization_id=authorization_id,
        authorization_source=cr_termination.TERMINATION_AUTHORIZATION_SOURCE,
        authorization_kind=cr_termination.TERMINATION_AUTHORIZATION_KIND,
        operation=cr_termination.TERMINATION_OPERATION,
        cr_id=plan.cr_id,
        work_id=plan.work_id,
        termination_reason=plan.termination_reason,
        terminal_tuple=plan.terminal_tuple,
        expected_release_oid=plan.expected_facts["target_release_oid"],
        expected_process_oid=plan.expected_facts["process_head_oid"],
        scope_digest=plan.scope_digest,
        plan_digest=plan.plan_digest,
        expires_at="2099-01-01T00:00:00+00:00",
        single_use=True,
    )


class CRTerminationTests(unittest.TestCase):
    def test_exact_owner_inventory_and_downward_collaborator_identity(self) -> None:
        source = Path(cr_termination.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        constants = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(
            {
                "TERMINATION_TUPLES",
                "TERMINATION_AUTHORIZATION_FIELDS",
                "TERMINATION_AUTHORIZATION_SOURCE",
                "TERMINATION_AUTHORIZATION_KIND",
                "TERMINATION_OPERATION",
            },
            constants,
        )
        self.assertEqual(
            {"TerminationAuthorization", "TerminationTarget", "TerminationPlan"},
            classes,
        )
        self.assertEqual(14, len(functions))
        self.assertIs(cr_records._load_json_object, cr_termination._load_json_object)
        self.assertIs(cr_projection._transaction_root, cr_termination._transaction_root)
        self.assertIs(cr_projection._atomic_write_text, cr_termination._atomic_write_text)
        self.assertIs(
            cr_projection._acquire_status_sync_writer_lock,
            cr_termination._acquire_status_sync_writer_lock,
        )
        self.assertIs(
            cr_projection._release_status_sync_writer_lock,
            cr_termination._release_status_sync_writer_lock,
        )

    def test_plan_supports_both_native_tuples_and_blocked_path_is_zero_mutation(self) -> None:
        for termination_status in ("cancelled", "superseded"):
            with self.subTest(status=termination_status), tempfile.TemporaryDirectory() as directory:
                release, process, cr_path, scope = write_termination_fixture(Path(directory))
                before = cr_path.read_bytes()
                plan = cr_termination.plan_cr_termination(
                    release,
                    "CR-101",
                    work_id="WORK-101",
                    termination_status=termination_status,
                    termination_reason="由替代路线接管",
                )
                self.assertEqual("READY", plan.decision)
                self.assertEqual(7, plan.as_dict()["planned_mutation_count"])
                self.assertEqual(scope.digest, plan.scope_digest)
                self.assertEqual(before, cr_path.read_bytes())
                self.assertFalse((process / "changes" / "CR-INDEX.json").exists())

        with tempfile.TemporaryDirectory() as directory:
            release, process, cr_path, _scope = write_termination_fixture(Path(directory))
            before = cr_path.read_bytes()
            blocked = cr_termination.plan_cr_termination(
                release,
                "CR-101",
                work_id="WORK-101",
                termination_status="closed",
                termination_reason="非法枚举",
            )
            self.assertEqual("BLOCKED", blocked.decision)
            self.assertEqual((), blocked.targets)
            self.assertEqual(before, cr_path.read_bytes())
            self.assertFalse((process / "changes" / "CR-INDEX.json").exists())

    def test_invalid_authorization_claim_lock_and_write_are_zero_then_claim_is_single_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(Path(directory))
            plan = cr_termination.plan_cr_termination(
                release,
                "CR-101",
                work_id="WORK-101",
                termination_status="cancelled",
                termination_reason="由替代路线接管",
            )
            authorization = termination_authorization(plan)
            wrong = cr_termination.TerminationAuthorization(
                **{**authorization.__dict__, "expected_process_oid": "0" * 40}
            )
            with (
                patch.object(cr_termination, "_claim_termination_authorization") as claim,
                patch.object(cr_termination, "_acquire_status_sync_writer_lock") as lock,
                patch.object(cr_termination, "_atomic_write_text") as write,
            ):
                missing = cr_termination.apply_cr_termination(
                    release,
                    plan,
                    authorization=None,
                    expected_plan_digest=plan.plan_digest,
                )
                invalid = cr_termination.apply_cr_termination(
                    release,
                    plan,
                    authorization=wrong,
                    expected_plan_digest=plan.plan_digest,
                )
                self.assertEqual("BLOCKED", missing["status"])
                self.assertEqual("BLOCKED", invalid["status"])
                claim.assert_not_called()
                lock.assert_not_called()
                write.assert_not_called()

            first = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
                _fault="after-claim-before-first-replace",
            )
            replay = cr_termination.apply_cr_termination(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
            )
            self.assertEqual("BLOCKED", first["status"])
            self.assertEqual("BLOCKED", replay["status"])
            self.assertIn("already consumed", replay["reason"])

    def test_authorization_loader_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(Path(directory))
            plan = cr_termination.plan_cr_termination(
                release,
                "CR-101",
                work_id="WORK-101",
                termination_status="cancelled",
                termination_reason="由替代路线接管",
            )
            authorization = termination_authorization(plan)
            path = Path(directory) / "authorization.json"
            path.write_text(json.dumps({**authorization.__dict__, "unknown": True}) + "\n")
            with self.assertRaisesRegex(ValueError, r"extra=\['unknown'\]"):
                cr_termination.load_termination_authorization(path)

    def test_terminate_apply_projects_cr_work_project_phase_summary_ledger_and_index(
            self,
        ) -> None:
            for termination_status in ("cancelled", "superseded"):
                with self.subTest(status=termination_status), tempfile.TemporaryDirectory() as directory:
                    release, process, _cr_path, _scope = write_termination_fixture(
                        Path(directory)
                    )
                    plan = cr_termination.plan_cr_termination(
                        release,
                        "CR-101",
                        work_id="WORK-101",
                        termination_status=termination_status,
                        termination_reason="由替代路线接管",
                    )
                    authorization = termination_authorization(
                        plan,
                        authorization_id=f"AUTH-{termination_status.upper()}",
                    )

                    result = cr_termination.apply_cr_termination(
                        release,
                        plan,
                        authorization=authorization,
                        expected_plan_digest=plan.plan_digest,
                    )

                    self.assertEqual("PASS", result["status"])
                    self.assertEqual(7, result["mutation_count"])
                    formal_text = (process / "changes" / "CR-101.md").read_text(
                        encoding="utf-8"
                    )
                    self.assertIn(
                        f'lifecycle_status: "{termination_status}"', formal_text
                    )
                    self.assertIn('readiness_status: "n/a"', formal_text)
                    self.assertIn('gate_status: "closed"', formal_text)
                    work = load_yaml_object(
                        process / "works" / "WORK-101" / "WORK.yaml"
                    )
                    project = load_yaml_object(process / "PROJECT.yaml")
                    phase = load_yaml_object(
                        process
                        / "phases"
                        / "P1-termination"
                        / "PHASE.yaml"
                    )
                    summary = json.loads(
                        (
                            process
                            / "changes"
                            / "summaries"
                            / "CR-101.summary.json"
                        ).read_text(encoding="utf-8")
                    )
                    index = json.loads(
                        (
                            process / "changes" / "CR-INDEX.json"
                        ).read_text(encoding="utf-8")
                    )
                    ledger = [
                        json.loads(line)
                        for line in (
                            process / "state" / "CR-LEDGER.ndjson"
                        )
                        .read_text(encoding="utf-8")
                        .splitlines()
                        if line.strip()
                    ]
                    self.assertEqual("cancelled", work["status"])
                    self.assertEqual([], project.get("active_work_refs", []))
                    self.assertEqual([], phase["work_refs"])
                    self.assertEqual(termination_status, summary["status"])
                    self.assertEqual("n/a", summary["readiness"])
                    self.assertEqual("closed", summary["gate_status"])
                    self.assertEqual(
                        termination_status,
                        index["items"][0]["lifecycle_status"],
                    )
                    self.assertEqual("n/a", index["items"][0]["readiness_status"])
                    self.assertEqual("closed", index["items"][0]["gate_status"])
                    self.assertEqual("cr_termination", ledger[-1]["event_type"])
                    self.assertEqual(termination_status, ledger[-1]["status"])
                    repeated = cr_termination.plan_cr_termination(
                        release,
                        "CR-101",
                        work_id="WORK-101",
                        termination_status=termination_status,
                        termination_reason="由替代路线接管",
                    )
                    self.assertEqual("NO_CHANGE", repeated.decision)
                    no_change = cr_termination.apply_cr_termination(
                        release,
                        repeated,
                        authorization=authorization,
                        expected_plan_digest=repeated.plan_digest,
                    )
                    self.assertEqual("NO_CHANGE", no_change["status"])
                    self.assertEqual(0, no_change["mutation_count"])

    def test_terminate_rejects_illegal_tuple_process_oid_and_plan_digest_drift(
            self,
        ) -> None:
            with tempfile.TemporaryDirectory() as directory:
                release, _process, _cr_path, _scope = write_termination_fixture(
                    Path(directory)
                )
                illegal = cr_termination.plan_cr_termination(
                    release,
                    "CR-101",
                    work_id="WORK-101",
                    termination_status="closed",
                    termination_reason="非法枚举",
                )
                oid_drift = cr_termination.plan_cr_termination(
                    release,
                    "CR-101",
                    work_id="WORK-101",
                    termination_status="cancelled",
                    termination_reason="由替代路线接管",
                    expected_process_oid="0" * 40,
                )
                plan = cr_termination.plan_cr_termination(
                    release,
                    "CR-101",
                    work_id="WORK-101",
                    termination_status="cancelled",
                    termination_reason="由替代路线接管",
                )
                authorization = termination_authorization(plan)

                digest_drift = cr_termination.apply_cr_termination(
                    release,
                    plan,
                    authorization=authorization,
                    expected_plan_digest="0" * 64,
                )

                self.assertEqual("BLOCKED", illegal.decision)
                self.assertEqual("BLOCKED", oid_drift.decision)
                self.assertEqual("BLOCKED", digest_drift["status"])
                self.assertIn("plan digest", digest_drift["reason"])

    def test_terminate_partial_mutation_reports_private_rollback_evidence(
            self,
        ) -> None:
            with tempfile.TemporaryDirectory() as directory:
                release, _process, _cr_path, _scope = write_termination_fixture(
                    Path(directory)
                )
                plan = cr_termination.plan_cr_termination(
                    release,
                    "CR-101",
                    work_id="WORK-101",
                    termination_status="cancelled",
                    termination_reason="由替代路线接管",
                )
                authorization = termination_authorization(plan)

                result = cr_termination.apply_cr_termination(
                    release,
                    plan,
                    authorization=authorization,
                    expected_plan_digest=plan.plan_digest,
                    _fail_after_replace=1,
                    _fail_recovery=True,
                )

                self.assertEqual("PARTIAL", result["status"])
                self.assertEqual(1, result["mutation_count"])
                self.assertTrue(result["rollback_errors"])
                self.assertEqual(
                    (
                        "private://cr-termination/transactions/"
                        f"{result['transaction_id']}/manifest.json"
                    ),
                    result["rollback_evidence_ref"],
                )


if __name__ == "__main__":
    unittest.main()
