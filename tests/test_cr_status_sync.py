from __future__ import annotations

import ast
import json
import tempfile
import unittest
from collections import Counter
from functools import partial
from pathlib import Path
from unittest.mock import patch

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
from meta_flow.project import process_route
from meta_flow.project.onboarding import ProjectInitRequest, apply_project_init, plan_project_init
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.state import current
from meta_flow.work.io_metrics import IOMetrics
from meta_flow.work.read_context import OperationReadContext
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
            node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        members |= {
            target.id
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Name)
        }
        expected = {
            "STATUS_SYNC_AUTHORIZATION_FIELDS",
            "STATUS_SYNC_AUTHORIZATION_SOURCE",
            "STATUS_SYNC_AUTHORIZATION_KIND",
            "STATUS_SYNC_OPERATION",
            "StatusSyncTarget",
            "StatusSyncAuthorization",
            "StatusSyncPlan",
            "_target",
            "_json_semantically_matches",
            "_ledger_contains_status_sync_transition",
            "_normalize_status_sync_effective_at",
            "plan_status_sync",
            "load_status_sync_authorization",
            "validate_status_sync_authorization",
            "apply_status_sync",
            "sync_cr_status",
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
            events = [
                json.loads(line)
                for line in paths["ledger"].read_text(encoding="utf-8").splitlines()
            ]
            state = current.load_current_state(release)
            self.assertIn('lifecycle_status: "closed"', formal)
            self.assertEqual(
                ("closed", "READY_WITH_RISK", "cp8_closed"),
                (summary["status"], summary["readiness"], summary["gate_status"]),
            )
            self.assertEqual("closed", index["items"][0]["status"])
            self.assertEqual("status_sync", events[-1]["event"])
            self.assertIsNone(state["active_change"])
            self.assertEqual("delivered", state["next_action"]["stop_reason"])

    def test_plan_projects_body_and_canonical_checkpoint_without_duplicate_truth_target(
        self,
    ) -> None:
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
            self.assertIn(
                "| CP7 | PASS | process/checks/CP7-CR-101-AGGREGATE.result.json |",
                formal_target.after,
            )
            self.assertIn(
                "| CP8 | approved | process/checks/CP8-CR-101-DELIVERY.result.json |",
                formal_target.after,
            )
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
            self.assertEqual(
                {"status": "NO_CHANGE", "reason": plan.reason, "mutation_count": 0}, result
            )
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
            with self.assertRaisesRegex(
                ValueError, "status=closed requires gate_status=cp8_closed"
            ):
                cr_status_sync.sync_cr_status(
                    root, "CR-101", status="closed", gate_status="cp8_approved"
                )

    def test_explicit_direct_close_requires_direct_routine_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(Path(directory))

            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="closed",
                work_id="WORK-101",
                effective_at="2026-07-27T05:30:00+00:00",
            )

            self.assertEqual("READY", plan.decision)
            self.assertEqual("closed", plan.desired_transition["gate_status"])

    def test_explicit_direct_close_without_work_blocks_before_cr_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = write_termination_fixture(Path(directory))
            metrics = IOMetrics("direct-close-no-work", enabled=True)
            context = OperationReadContext(
                process,
                operation_id="direct-close-no-work",
                operation_kind="plan",
                allowed_reads=("process/**", "works/**"),
                max_objects=128,
                metrics=metrics,
            )

            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="closed",
                effective_at="2026-07-27T05:31:00+00:00",
                read_context=context,
            )

            self.assertEqual("BLOCKED", plan.decision)
            self.assertEqual((), plan.targets)
            self.assertEqual(0, plan.as_dict()["mutation_count"])
            self.assertIn("work_id", plan.reason)
            self.assertFalse(
                any(
                    entry["logical_ref"].startswith("changes/CR-101")
                    for entry in metrics.summary()["entries"]
                )
            )

    def test_explicit_direct_close_rejects_non_direct_route_before_cr_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = write_termination_fixture(Path(directory))
            work_path = process / "works/WORK-101/WORK.yaml"
            work = load_yaml_object(work_path)
            work["route_profile"] = {
                "schema_version": 1,
                "mode": "routine-four-stage",
                "dispatch_mode": "functional-agent",
                "legacy_cp_compatibility": False,
                "validation_profile": "layered-v1",
                "failure_scope": "current-slice-only",
                "worktree_policy": "paired-worktree",
            }
            work_path.write_text(dump_yaml(work) + "\n", encoding="utf-8")
            metrics = IOMetrics("direct-close-wrong-route", enabled=True)
            context = OperationReadContext(
                process,
                operation_id="direct-close-wrong-route",
                operation_kind="plan",
                allowed_reads=("process/**", "works/**"),
                max_objects=128,
                metrics=metrics,
            )

            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="closed",
                work_id="WORK-101",
                effective_at="2026-07-27T05:32:00+00:00",
                read_context=context,
            )

            self.assertEqual("BLOCKED", plan.decision)
            self.assertEqual((), plan.targets)
            self.assertIn("routine-four-stage direct Work", plan.reason)
            self.assertFalse(
                any(
                    entry["logical_ref"].startswith("changes/CR-101")
                    for entry in metrics.summary()["entries"]
                )
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
            self.assertEqual(
                (0, 5),
                (first.as_dict()["mutation_count"], first.as_dict()["planned_mutation_count"]),
            )

    def test_plan_and_apply_use_separate_bounded_contexts_with_single_physical_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = write_termination_fixture(Path(directory))
            plan_metrics = IOMetrics("status-plan", enabled=True)
            plan_context = OperationReadContext(
                process,
                operation_id="status-plan",
                operation_kind="plan",
                allowed_reads=("process/**", "works/**"),
                max_objects=128,
                metrics=plan_metrics,
            )
            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
                work_id="WORK-101",
                effective_at="2026-07-27T11:30:00+00:00",
                read_context=plan_context,
            )
            authorization = _authorization(plan)
            apply_metrics = IOMetrics("status-apply", enabled=True)
            apply_context = OperationReadContext(
                process,
                operation_id="status-apply",
                operation_kind="apply",
                allowed_reads=tuple(
                    dict.fromkeys(
                        (
                            "works/WORK-101/WORK.yaml",
                            *(target.ref for target in plan.targets),
                        )
                    )
                ),
                max_objects=len(plan.targets) + 1,
                scope_digest=plan.scope_digest,
                authorization_digest=authorization.plan_digest,
                metrics=apply_metrics,
            )

            result = cr_status_sync.apply_status_sync(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
                read_context=apply_context,
            )

            self.assertEqual("PASS", result["status"])
            self.assertIsNot(plan_context, apply_context)
            self.assertEqual("CLOSED", plan_context.state)
            self.assertEqual("CLOSED", apply_context.state)
            self.assertGreater(plan_metrics.summary()["totals"]["cache_hits"], 0)
            self.assertTrue(
                all(entry["physical_reads"] <= 1 for entry in plan_metrics.summary()["entries"])
            )

    def test_plan_resolves_binding_route_once_and_reuses_frozen_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, cr_path, _scope = write_termination_fixture(Path(directory))
            physical_reads: Counter[Path] = Counter()
            original_read_text = Path.read_text
            original_read_bytes = Path.read_bytes

            def tracked_read_text(path: Path, *args: object, **kwargs: object) -> str:
                physical_reads[path.resolve(strict=False)] += 1
                return original_read_text(path, *args, **kwargs)

            def tracked_read_bytes(path: Path) -> bytes:
                physical_reads[path.resolve(strict=False)] += 1
                return original_read_bytes(path)

            with (
                patch.object(
                    process_route,
                    "check_independent_process_route",
                    wraps=process_route.check_independent_process_route,
                ) as route_health,
                patch.object(Path, "read_text", tracked_read_text),
                patch.object(Path, "read_bytes", tracked_read_bytes),
            ):
                plan = cr_status_sync.plan_status_sync(
                    release,
                    "CR-101",
                    status="closed",
                    readiness="READY_WITH_RISK",
                    gate_status="cp8_closed",
                    work_id="WORK-101",
                    effective_at="2026-07-27T11:35:00+00:00",
                )

            observed = {
                path: physical_reads[path.resolve(strict=False)]
                for path in (
                    release / ".meta-flow" / "workspace.yaml",
                    process / "PROJECT.yaml",
                    process / ".meta-flow-process.yaml",
                    cr_path,
                )
            }
            self.assertEqual("READY", plan.decision)
            self.assertEqual(1, route_health.call_count)
            self.assertEqual({path: 1 for path in observed}, observed)

    def test_apply_resolves_binding_route_once_and_reuses_frozen_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, _cr_path, _scope = write_termination_fixture(Path(directory))
            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
                work_id="WORK-101",
                effective_at="2026-07-27T11:40:00+00:00",
            )
            authorization = _authorization(plan)
            physical_reads: Counter[Path] = Counter()
            original_read_text = Path.read_text
            original_read_bytes = Path.read_bytes

            def tracked_read_text(path: Path, *args: object, **kwargs: object) -> str:
                physical_reads[path.resolve(strict=False)] += 1
                return original_read_text(path, *args, **kwargs)

            def tracked_read_bytes(path: Path) -> bytes:
                physical_reads[path.resolve(strict=False)] += 1
                return original_read_bytes(path)

            with (
                patch.object(
                    process_route,
                    "check_independent_process_route",
                    wraps=process_route.check_independent_process_route,
                ) as route_health,
                patch.object(Path, "read_text", tracked_read_text),
                patch.object(Path, "read_bytes", tracked_read_bytes),
            ):
                result = cr_status_sync.apply_status_sync(
                    release,
                    plan,
                    authorization=authorization,
                    expected_plan_digest=plan.plan_digest,
                )

            observed = {
                path: physical_reads[path.resolve(strict=False)]
                for path in (
                    release / ".meta-flow" / "workspace.yaml",
                    process / "PROJECT.yaml",
                    process / ".meta-flow-process.yaml",
                )
            }
            self.assertEqual("PASS", result["status"])
            self.assertEqual(1, route_health.call_count)
            self.assertEqual({path: 1 for path in observed}, observed)

    def test_apply_blocks_plan_context_reuse_and_target_preimage_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process, cr_path, _scope = write_termination_fixture(Path(directory))
            plan_context = OperationReadContext(
                process,
                operation_id="status-plan-no-reuse",
                operation_kind="plan",
                allowed_reads=("process/**", "works/**"),
                max_objects=128,
            )
            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                status="closed",
                readiness="READY_WITH_RISK",
                gate_status="cp8_closed",
                work_id="WORK-101",
                effective_at="2026-07-27T11:45:00+00:00",
                read_context=plan_context,
            )
            authorization = _authorization(plan)

            reused = cr_status_sync.apply_status_sync(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
                read_context=plan_context,
            )
            self.assertEqual("BLOCKED", reused["status"])
            self.assertEqual(0, reused["mutation_count"])
            self.assertIn("READ_CONTEXT_CLOSED", reused["reason"])

            cr_path.write_text(
                cr_path.read_text(encoding="utf-8") + "\n外部并发修改\n",
                encoding="utf-8",
            )
            changed = cr_path.read_text(encoding="utf-8")
            with patch.object(
                cr_status_sync,
                "_dirty_path_digest",
                return_value=plan.expected_facts["dirty_path_digest"],
            ):
                drifted = cr_status_sync.apply_status_sync(
                    release,
                    plan,
                    authorization=authorization,
                    expected_plan_digest=plan.plan_digest,
                )
            self.assertEqual("BLOCKED", drifted["status"])
            self.assertEqual(0, drifted["mutation_count"])
            self.assertIn("target preimage drifted", drifted["reason"])
            self.assertEqual(changed, cr_path.read_text(encoding="utf-8"))

    def test_plan_omits_summary_and_evidence_when_only_volatile_fields_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(Path(directory))
            inputs = {
                "status": "closed",
                "readiness": "READY_WITH_RISK",
                "gate_status": "cp8_closed",
                "work_id": "WORK-101",
            }
            seed = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                **inputs,
                effective_at="2026-07-27T11:50:00+00:00",
            )
            for target in seed.targets:
                if target.ref.endswith(".summary.json") or target.ref.endswith(
                    "evidence-index.json"
                ):
                    target.path.parent.mkdir(parents=True, exist_ok=True)
                    target.path.write_text(target.after, encoding="utf-8")

            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                **inputs,
                effective_at="2026-07-27T11:51:00+00:00",
            )

            refs = {target.ref for target in plan.targets}
            self.assertEqual("READY", plan.decision)
            self.assertNotIn("process/changes/summaries/CR-101.summary.json", refs)
            self.assertNotIn(
                "process/archive/CR-101/evidence-index.json",
                refs,
            )
            self.assertIn("process/changes/CR-101.md", refs)
            self.assertIn("process/state/CR-LEDGER.ndjson", refs)

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
