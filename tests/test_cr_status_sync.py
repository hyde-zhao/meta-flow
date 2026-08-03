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
    write_cr as _write_cr,
)
from cr_lifecycle_test_support import (
    write_termination_fixture as _write_termination_fixture,
)

from meta_flow.checks import cr_tracking
from meta_flow.project.onboarding import ProjectInitRequest, apply_project_init, plan_project_init
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.state import current
from meta_flow.work.scope import WorkScope
from meta_flow.workflow import cr_status_sync

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
write_cr = partial(_write_cr, collaborators=_FIXTURE_COLLABORATORS)
write_termination_fixture = partial(
    _write_termination_fixture,
    collaborators=_FIXTURE_COLLABORATORS,
)


def _authorization(
    plan: cr_status_sync.StatusSyncPlan,
    *,
    authorization_id: str = "AUTH-STATUS-SYNC-001",
) -> cr_status_sync.StatusSyncAuthorization:
    return cr_status_sync.StatusSyncAuthorization(
        schema_version=1,
        authorization_id=authorization_id,
        authorization_source=cr_status_sync.STATUS_SYNC_AUTHORIZATION_SOURCE,
        authorization_kind=cr_status_sync.STATUS_SYNC_AUTHORIZATION_KIND,
        operation=cr_status_sync.STATUS_SYNC_OPERATION,
        cr_id=plan.cr_id,
        work_id=plan.work_id,
        desired_transition=plan.desired_transition,
        effective_at=plan.effective_at,
        expected_release_oid=plan.expected_facts["release_head_oid"],
        expected_process_oid=plan.expected_facts["process_head_oid"],
        scope_digest=plan.scope_digest,
        targets=[target.as_dict() for target in plan.targets],
        plan_digest=plan.plan_digest,
        expires_at="2099-01-01T00:00:00+00:00",
        single_use=True,
    )


def _apply_ready(
    root: Path,
    plan: cr_status_sync.StatusSyncPlan,
    **kwargs: object,
) -> dict[str, object]:
    return cr_status_sync.apply_status_sync(
        root,
        plan,
        authorization=_authorization(plan),
        expected_plan_digest=plan.plan_digest,
        **kwargs,
    )


class CRStatusSyncOwnerTests(unittest.TestCase):
    def test_frozen_public_owner_members_are_exact(self) -> None:
        tree = ast.parse(Path(cr_status_sync.__file__).read_text(encoding="utf-8"))
        members = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        members |= {
            target.id
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Name)
        }
        expected = {
            "STATUS_SYNC_AUTHORIZATION_FIELDS", "STATUS_SYNC_AUTHORIZATION_SOURCE",
            "STATUS_SYNC_AUTHORIZATION_KIND", "STATUS_SYNC_OPERATION", "StatusSyncTarget",
            "StatusSyncAuthorization", "StatusSyncPlan", "_target", "_json_semantically_matches",
            "_ledger_contains_status_sync_transition", "_normalize_status_sync_effective_at",
            "plan_status_sync", "load_status_sync_authorization",
            "validate_status_sync_authorization", "apply_status_sync", "sync_cr_status",
        }
        self.assertEqual(expected, members)

    def test_public_sync_projects_all_status_surfaces_and_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = write_termination_fixture(Path(directory))
            current.write_current_state(release, current.default_current_state(release))
            current.update_current_state(
                release,
                {
                    "active_change": "CR-101",
                    "current_phase": "documentation",
                    "next_action": {"type": "await_user", "text": "review CP8"},
                },
            )
            inputs = {
                "status": "closed",
                "readiness": "READY_WITH_RISK",
                "gate_status": "cp8_closed",
                "work_id": "WORK-101",
                "effective_at": "2026-07-27T02:00:00+00:00",
            }
            plan = cr_status_sync.plan_status_sync(release, "CR-101", **inputs)
            paths = cr_status_sync.sync_cr_status(
                release,
                "CR-101",
                **inputs,
                expected_plan_digest=plan.plan_digest,
                authorization=_authorization(plan),
            )

            formal = (process / "changes" / "CR-101.md").read_text(encoding="utf-8")
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            index = json.loads(paths["index"].read_text(encoding="utf-8"))
            events = [json.loads(line) for line in paths["ledger"].read_text(encoding="utf-8").splitlines()]
            state = current.load_current_state(release)
            self.assertIn('lifecycle_status: "closed"', formal)
            self.assertEqual(("closed", "READY_WITH_RISK", "cp8_closed"), (
                summary["status"], summary["readiness"], summary["gate_status"]
            ))
            self.assertEqual("closed", index["items"][0]["status"])
            self.assertEqual("status_sync", events[-1]["event"])
            self.assertIsNone(state["active_change"])
            self.assertEqual("delivered", state["next_action"]["stop_reason"])

    def test_plan_projects_body_and_canonical_checkpoint_without_duplicate_truth_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = write_cr(root, "CR-101", status="active")
            cr_path.write_text(
                cr_path.read_text(encoding="utf-8")
                + """
## CR 类型与门禁策略

| 字段 | 内容 |
|---|---|
| 生命周期状态 | active |
| 就绪状态 | NOT_READY |
| 门禁状态 | cp3_pending |

## Checkpoint Index

| CP | 状态 | 机器结果 ref |
|---|---|---|
| CP7 | pending | process/checks/CP7-CR-101-AGGREGATE.result.json |
| CP8 | pending | process/checks/CP8-CR-101-DELIVERY.result.json |
""",
                encoding="utf-8",
            )
            result_path = root / "process/checks/CP7-CR-101-AGGREGATE.result.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text('{"checkpoint":"CP7","decision":"PASS"}\n', encoding="utf-8")

            plan = cr_status_sync.plan_status_sync(
                root,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
            )
            formal_target = next(
                target for target in plan.targets if target.ref == "process/changes/CR-101.md"
            )
            self.assertEqual("READY", plan.decision)
            self.assertIn("| 生命周期状态 | closed |", formal_target.after)
            self.assertIn("| CP7 | PASS | process/checks/CP7-CR-101-AGGREGATE.result.json |", formal_target.after)
            self.assertIn("| CP8 | approved | process/checks/CP8-CR-101-DELIVERY.result.json |", formal_target.after)
            self.assertEqual(1, sum(target.ref == formal_target.ref for target in plan.targets))

    def test_no_change_is_zero_write_even_with_unrelated_dirty_growth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = write_termination_fixture(Path(directory))
            inputs = {
                "status": "active",
                "readiness": "NOT_READY",
                "gate_status": "cp8_pending",
                "work_id": "WORK-101",
                "effective_at": "2026-07-27T03:00:00+00:00",
            }
            initial = cr_status_sync.plan_status_sync(release, "CR-101", **inputs)
            paths = cr_status_sync.sync_cr_status(
                release,
                "CR-101",
                **inputs,
                expected_plan_digest=initial.plan_digest,
                authorization=_authorization(initial),
            )
            ledger_before = paths["ledger"].read_bytes()
            unrelated = process / "checks/UNRELATED.result.json"
            unrelated.parent.mkdir(parents=True, exist_ok=True)
            unrelated.write_text('{"decision":"PASS"}\n', encoding="utf-8")

            plan = cr_status_sync.plan_status_sync(release, "CR-101", **inputs)
            result = cr_status_sync.apply_status_sync(release, plan)
            self.assertEqual("NO_CHANGE", plan.decision)
            self.assertEqual({"status": "NO_CHANGE", "reason": plan.reason, "mutation_count": 0}, result)
            self.assertEqual(ledger_before, paths["ledger"].read_bytes())

    def test_closed_defaults_to_canonical_gate_and_rejects_other_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(Path(directory))
            inputs = {
                "status": "closed",
                "readiness": "READY",
                "work_id": "WORK-101",
                "effective_at": "2026-07-27T05:00:00+00:00",
            }
            plan = cr_status_sync.plan_status_sync(release, "CR-101", **inputs)
            paths = cr_status_sync.sync_cr_status(
                release,
                "CR-101",
                **inputs,
                expected_plan_digest=plan.plan_digest,
                authorization=_authorization(plan),
            )
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            self.assertEqual("cp8_closed", summary["gate_status"])
            self.assertIn(summary["gate_status"], cr_tracking.ALLOWED_GATE_STATUSES)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cr(root, "CR-101", status="active")
            with self.assertRaisesRegex(ValueError, "status=closed requires gate_status=cp8_closed"):
                cr_status_sync.sync_cr_status(
                    root, "CR-101", status="closed", gate_status="cp8_approved"
                )

    def test_frozen_effective_at_makes_plan_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(Path(directory))
            inputs = {
                "status": "closed",
                "readiness": "READY_WITH_RISK",
                "gate_status": "cp8_closed",
                "work_id": "WORK-101",
                "effective_at": "2026-07-27T11:00:00+00:00",
            }
            first = cr_status_sync.plan_status_sync(release, "CR-101", **inputs)
            second = cr_status_sync.plan_status_sync(release, "CR-101", **inputs)
            changed = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                **{**inputs, "effective_at": "2026-07-27T11:00:01+00:00"},
            )
            self.assertEqual(first.as_dict(), second.as_dict())
            self.assertEqual(first.plan_digest, second.plan_digest)
            self.assertNotEqual(first.plan_digest, changed.plan_digest)
            self.assertEqual((0, 5), (
                first.as_dict()["mutation_count"], first.as_dict()["planned_mutation_count"]
            ))

    def test_typed_authorization_fails_closed_and_is_single_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, cr_path, _scope = write_termination_fixture(Path(directory))
            before = cr_path.read_bytes()
            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
                work_id="WORK-101",
                effective_at="2026-07-27T12:00:00+00:00",
            )
            authorization = _authorization(plan)
            wrong = cr_status_sync.StatusSyncAuthorization.from_dict(
                {**authorization.__dict__, "expected_release_oid": "0" * 40}
            )
            results = [
                cr_status_sync.apply_status_sync(
                    release, plan, expected_plan_digest=plan.plan_digest
                ),
                cr_status_sync.apply_status_sync(
                    release,
                    plan,
                    authorization=authorization,
                    expected_plan_digest="0" * 64,
                ),
                cr_status_sync.apply_status_sync(
                    release,
                    plan,
                    authorization=wrong,
                    expected_plan_digest=plan.plan_digest,
                ),
                cr_status_sync.apply_status_sync(
                    release,
                    plan,
                    authorization=authorization,
                    expected_plan_digest=plan.plan_digest,
                    _fault="before-first-replace",
                ),
            ]
            replay = cr_status_sync.apply_status_sync(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
            )
            self.assertTrue(all(result["status"] == "BLOCKED" for result in [*results, replay]))
            self.assertTrue(all(result["mutation_count"] == 0 for result in [*results, replay]))
            self.assertIn("already consumed", replay["reason"])
            self.assertEqual(before, cr_path.read_bytes())

    def test_authorization_loader_rejects_unknown_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(Path(directory))
            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
                work_id="WORK-101",
                effective_at="2026-07-27T13:00:00+00:00",
            )
            path = Path(directory) / "authorization.json"
            path.write_text(
                json.dumps({**_authorization(plan).__dict__, "unknown": True}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "fields mismatch"):
                cr_status_sync.load_status_sync_authorization(path)


if __name__ == "__main__":
    unittest.main()
