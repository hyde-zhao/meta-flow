from __future__ import annotations

import ast
import json
import tempfile
import unittest
from functools import partial
from pathlib import Path

from cr_lifecycle_test_support import (
    LifecycleFixtureCollaborators,
)
from cr_lifecycle_test_support import (
    write_termination_fixture as _write_termination_fixture,
)
from test_cr_status_sync import _apply_ready

from meta_flow.project.onboarding import ProjectInitRequest, apply_project_init, plan_project_init
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.work.scope import WorkScope
from meta_flow.workflow import cr_status_sync, cr_status_transaction
from meta_flow.workflow.cr_index import _canonical_digest, _dirty_path_digest
from meta_flow.workflow.cr_projection import (
    _acquire_status_sync_writer_lock,
    _release_status_sync_writer_lock,
    _status_sync_writer_lock_path,
)

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
write_termination_fixture = partial(
    _write_termination_fixture,
    collaborators=_FIXTURE_COLLABORATORS,
)


class CRStatusTransactionOwnerTests(unittest.TestCase):
    def test_frozen_transaction_members_and_no_public_back_import(self) -> None:
        source = Path(cr_status_transaction.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(
            {
                "_status_sync_facts", "_current_target_digest", "_status_sync_claim_path",
                "_claim_status_sync_authorization", "_apply_status_sync_transaction",
                "inspect_status_sync_transactions", "recover_status_sync_transaction",
            },
            functions,
        )
        imports = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        forbidden = {
            "meta_flow.workflow.cr_analysis",
            "meta_flow.workflow.cr_cli",
            "meta_flow.workflow.cr_index",
            "meta_flow.workflow.cr_lifecycle",
            "meta_flow.workflow.cr_status_sync",
            "meta_flow.workflow.cr_termination",
        }
        self.assertTrue(imports.isdisjoint(forbidden))
        self.assertNotIn("importlib", imports)
        self.assertNotIn("import_module", source)
        self.assertNotIn("__import__", source)

    def test_fault_ordering_recovers_before_index_is_written(self) -> None:
        expectations = {
            "before-first-replace": "BLOCKED",
            "after-replace-before-receipt": "RECOVERED",
            "after-receipt-before-next": "RECOVERED",
            "after-truth-before-derived": "RECOVERED",
            "before-index-last": "RECOVERED",
            "during-read-back": "RECOVERED",
        }
        for fault, expected in expectations.items():
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root, _process, cr_path, _scope = write_termination_fixture(Path(directory))
                before = cr_path.read_text(encoding="utf-8")
                plan = cr_status_sync.plan_status_sync(
                    root,
                    "CR-101",
                    status="closed",
                    readiness="READY_WITH_RISK",
                    work_id="WORK-101",
                    effective_at="2026-07-27T06:00:00+00:00",
                )

                result = _apply_ready(root, plan, _fault=fault)
                self.assertEqual(expected, result["status"])
                self.assertEqual(before, cr_path.read_text(encoding="utf-8"))
                self.assertFalse(
                    _resolve_runtime_ref(root, "process/changes/CR-INDEX.json").exists()
                )

    def test_partial_is_inspectable_and_explicit_rollback_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _process, cr_path, _scope = write_termination_fixture(Path(directory))
            before = cr_path.read_text(encoding="utf-8")
            plan = cr_status_sync.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                work_id="WORK-101",
                effective_at="2026-07-27T07:00:00+00:00",
            )
            partial = _apply_ready(
                root,
                plan,
                _fault="after-receipt-before-next",
                _fail_recovery=True,
            )
            inspected = cr_status_transaction.inspect_status_sync_transactions(root)
            recovered = cr_status_transaction.recover_status_sync_transaction(
                root,
                partial["transaction_id"],
                action="rollback",
                canonical_digest=_canonical_digest,
                dirty_path_digest=_dirty_path_digest,
            )
            self.assertEqual("PARTIAL", partial["status"])
            self.assertEqual(1, inspected["transaction_count"])
            self.assertEqual("RECOVERED", recovered["status"])
            self.assertEqual(before, cr_path.read_text(encoding="utf-8"))
            self.assertEqual(
                0,
                cr_status_transaction.inspect_status_sync_transactions(root)["transaction_count"],
            )

    def test_recovery_blocks_competing_writer_and_releases_only_its_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _process, _cr_path, _scope = write_termination_fixture(Path(directory))
            plan = cr_status_sync.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                work_id="WORK-101",
                effective_at="2026-07-27T08:00:00+00:00",
            )
            partial = _apply_ready(
                root,
                plan,
                _fault="after-receipt-before-next",
                _fail_recovery=True,
            )
            owner = _acquire_status_sync_writer_lock(
                root,
                transaction_id=partial["transaction_id"],
                purpose="recovery:test-contender",
            )
            self.assertIsNotNone(owner)
            assert owner is not None
            lock_path = _status_sync_writer_lock_path(root)
            persisted = json.loads(lock_path.read_text(encoding="utf-8"))

            blocked = cr_status_transaction.recover_status_sync_transaction(
                root,
                partial["transaction_id"],
                action="rollback",
                canonical_digest=_canonical_digest,
                dirty_path_digest=_dirty_path_digest,
            )
            wrong_owner = {**owner, "owner_token": "0" * 32}
            self.assertEqual("BLOCKED", blocked["status"])
            self.assertIn("writer lock", blocked["reason"])
            self.assertFalse(_release_status_sync_writer_lock(root, wrong_owner))
            self.assertEqual(
                persisted["owner_token"],
                json.loads(lock_path.read_text(encoding="utf-8"))["owner_token"],
            )
            self.assertTrue(_release_status_sync_writer_lock(root, owner))

            recovered = cr_status_transaction.recover_status_sync_transaction(
                root,
                partial["transaction_id"],
                action="rollback",
                canonical_digest=_canonical_digest,
                dirty_path_digest=_dirty_path_digest,
            )
            self.assertEqual("RECOVERED", recovered["status"])
            self.assertFalse(lock_path.exists())

    def test_recovery_does_not_auto_remove_stale_owner_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _process, _cr_path, _scope = write_termination_fixture(Path(directory))
            plan = cr_status_sync.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                work_id="WORK-101",
                effective_at="2026-07-27T09:00:00+00:00",
            )
            partial = _apply_ready(
                root,
                plan,
                _fault="after-receipt-before-next",
                _fail_recovery=True,
            )
            owner = _acquire_status_sync_writer_lock(
                root,
                transaction_id=partial["transaction_id"],
                purpose="recovery:stale-fixture",
            )
            assert owner is not None
            lock_path = _status_sync_writer_lock_path(root)
            stale = json.loads(lock_path.read_text(encoding="utf-8"))
            stale["acquired_at"] = "1970-01-01T00:00:00+00:00"
            lock_path.write_text(json.dumps(stale) + "\n", encoding="utf-8")

            blocked = cr_status_transaction.recover_status_sync_transaction(
                root,
                partial["transaction_id"],
                action="resume",
                canonical_digest=_canonical_digest,
                dirty_path_digest=_dirty_path_digest,
            )
            self.assertEqual("BLOCKED", blocked["status"])
            self.assertTrue(lock_path.is_file())
            self.assertTrue(_release_status_sync_writer_lock(root, owner))


if __name__ == "__main__":
    unittest.main()
