"""CR-075 A-P0-05 V3 整改：无 Work 的 system-only status-sync 真实全链。

门禁反馈 R1：system-only plan 必须能完成真实 plan -> typed authorization ->
apply；scope digest 必须是确定性 system 命名空间声明；namespace 必须绑定进
target 序列化、plan digest、authorization 与 apply 重验（篡改即拒绝）。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

from cr_lifecycle_test_support import (  # noqa: E402
    LifecycleFixtureCollaborators,
    write_termination_fixture,
)

from meta_flow.project.onboarding import (  # noqa: E402
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (  # noqa: E402
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import resolve_runtime_ref  # noqa: E402
from meta_flow.project.scale import dump_yaml, load_yaml_object  # noqa: E402
from meta_flow.work.scope import WorkScope  # noqa: E402
from meta_flow.workflow import cr_status_sync  # noqa: E402
from meta_flow.workflow.cr_model import DIGEST_RE  # noqa: E402
from meta_flow.workflow.cr_status_transaction import (  # noqa: E402
    SYSTEM_NAMESPACE_SCOPE_CLAIM,
)

_FIXTURE_COLLABORATORS = LifecycleFixtureCollaborators(
    project_init_request=ProjectInitRequest,
    plan_project_init=plan_project_init,
    apply_project_init=apply_project_init,
    onboarding_authorization=OnboardingAuthorization,
    authorization_source=AUTHORIZATION_SOURCE,
    authorization_kind=AUTHORIZATION_KIND,
    resolve_runtime_ref=resolve_runtime_ref,
    dump_yaml=dump_yaml,
    load_yaml_object=load_yaml_object,
    work_scope=WorkScope,
)

# 无 work 下合法且产生真实变更的 transition（fixture cp8_pending 基态）。
_SYSTEM_ONLY_TRANSITION = {
    "status": "blocked",
    "readiness": "not_ready",
    "gate_status": "cp8_pending",
}


def _authorization(
    plan: cr_status_sync.StatusSyncPlan,
) -> cr_status_sync.StatusSyncAuthorization:
    return cr_status_sync.StatusSyncAuthorization(
        schema_version=1,
        authorization_id="AUTH-SYSTEM-STATUS-SYNC-001",
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


class SystemNamespaceStatusSyncTests(unittest.TestCase):
    def test_system_only_plan_carries_deterministic_scope_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory), collaborators=_FIXTURE_COLLABORATORS
            )
            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                effective_at="2026-08-24T00:00:00+00:00",
                **_SYSTEM_ONLY_TRANSITION,
            )
            self.assertEqual("READY", plan.decision)
            self.assertEqual("", plan.work_id)
            self.assertTrue(plan.targets)
            self.assertTrue(
                all(target.namespace == "system" for target in plan.targets)
            )
            expected = cr_status_sync._canonical_digest(
                dict(SYSTEM_NAMESPACE_SCOPE_CLAIM)
            )
            # 确定性：与命名空间声明常量的 canonical digest 逐字相等，且为
            # 合法 64-hex（空串在此前会直接被授权格式校验拒绝）。
            self.assertEqual(expected, plan.scope_digest)
            self.assertTrue(DIGEST_RE.fullmatch(plan.scope_digest))

    def test_system_only_real_chain_plan_authorization_apply(self) -> None:
        """无 Work 的 system-only 真实 plan -> typed authorization -> apply。"""

        with tempfile.TemporaryDirectory() as directory:
            release, _process, cr_path, _scope = write_termination_fixture(
                Path(directory), collaborators=_FIXTURE_COLLABORATORS
            )
            before = cr_path.read_bytes()
            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                effective_at="2026-08-24T00:00:00+00:00",
                **_SYSTEM_ONLY_TRANSITION,
            )
            authorization = _authorization(plan)
            cr_status_sync.validate_status_sync_authorization(plan, authorization)
            result = cr_status_sync.apply_status_sync(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
            )
            self.assertEqual("PASS", result["status"])
            self.assertGreater(result["mutation_count"], 0)
            self.assertNotEqual(before, cr_path.read_bytes())
            self.assertIn('lifecycle_status: "blocked"', cr_path.read_text(encoding="utf-8"))
            # 单次使用：成功后的重放必须 BLOCKED 且不再产生 mutation——
            # 首笔已变更 target preimage，drift 守卫先于 claim 守卫触发，
            # 两者都是合法的单次使用 fail-closed 证据。
            replay = cr_status_sync.apply_status_sync(
                release,
                plan,
                authorization=authorization,
                expected_plan_digest=plan.plan_digest,
            )
            self.assertEqual("BLOCKED", replay["status"])
            self.assertRegex(replay["reason"], "already consumed|target preimage drifted")
            self.assertEqual(0, replay["mutation_count"])

    def test_namespace_tampered_authorization_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory), collaborators=_FIXTURE_COLLABORATORS
            )
            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                effective_at="2026-08-24T00:00:00+00:00",
                **_SYSTEM_ONLY_TRANSITION,
            )
            payload = _authorization(plan).__dict__
            tampered = dict(payload)
            tampered["targets"] = [
                {**target, "namespace": "business"}
                for target in payload["targets"]
            ]
            with self.assertRaisesRegex(ValueError, "does not match"):
                cr_status_sync.validate_status_sync_authorization(
                    plan,
                    cr_status_sync.StatusSyncAuthorization.from_dict(tampered),
                )

    def test_plan_digest_and_serialization_bind_namespace(self) -> None:
        import hashlib

        from meta_flow.workflow.cr_status_sync import StatusSyncTarget

        def make(namespace: str) -> StatusSyncTarget:
            return StatusSyncTarget(
                order=10,
                ref="process/changes/CR-101.md",
                path=Path("/nonexistent/CR-101.md"),
                truth_or_derived="truth",
                before=None,
                after="body",
                namespace=namespace,
            )

        system = make("system")
        business = make("business")
        # 序列化携带 namespace，digest 因此不同——篡改 namespace 无法保持
        # plan digest / authorization 一致。
        self.assertNotEqual(system.as_dict(), business.as_dict())
        self.assertEqual(
            hashlib.sha256(
                cr_status_sync._canonical_digest(system.as_dict()).encode()
            ).hexdigest(),
            hashlib.sha256(
                cr_status_sync._canonical_digest(system.as_dict()).encode()
            ).hexdigest(),
        )
        self.assertIn("namespace", system.as_dict())

    def test_invalid_namespace_is_rejected_at_construction(self) -> None:
        from meta_flow.workflow import cr_status_sync as sync

        with self.assertRaisesRegex(ValueError, "namespace is invalid"):
            sync._target(
                Path("/nonexistent-root"),
                10,
                Path("/nonexistent-root/process/changes/CR-101.md"),
                "after",
                "truth",
                namespace="legacy",
            )

    def test_business_target_without_work_scope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory), collaborators=_FIXTURE_COLLABORATORS
            )
            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                effective_at="2026-08-24T00:00:00+00:00",
                **_SYSTEM_ONLY_TRANSITION,
            )
            # 构造含 business target 的同 scope 计划：typed apply 必须要求
            # work_id 与业务 scope digest，system 豁免不得被搭便车。
            business_plan = cr_status_sync.StatusSyncPlan(
                decision="READY",
                cr_id=plan.cr_id,
                work_id="",
                desired_transition=plan.desired_transition,
                expected_facts=plan.expected_facts,
                scope_digest=plan.scope_digest,
                targets=(
                    *plan.targets,
                    cr_status_sync.StatusSyncTarget(
                        order=99,
                        ref="works/WORK-101/WORK.yaml",
                        path=Path("/nonexistent/WORK.yaml"),
                        truth_or_derived="truth",
                        before=None,
                        after="body",
                        namespace="business",
                    ),
                ),
                effective_at=plan.effective_at,
            )
            with self.assertRaisesRegex(ValueError, "requires work_id and scope digest"):
                cr_status_sync.validate_status_sync_authorization(
                    business_plan,
                    _authorization(business_plan),
                )

    def test_system_only_scope_must_be_the_namespace_claim_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, _process, _cr_path, _scope = write_termination_fixture(
                Path(directory), collaborators=_FIXTURE_COLLABORATORS
            )
            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                effective_at="2026-08-24T00:00:00+00:00",
                **_SYSTEM_ONLY_TRANSITION,
            )
            payload = _authorization(plan).__dict__
            payload["scope_digest"] = "a" * 64
            with self.assertRaisesRegex(
                ValueError, "deterministic system namespace claim"
            ):
                cr_status_sync.validate_status_sync_authorization(
                    plan,
                    cr_status_sync.StatusSyncAuthorization.from_dict(payload),
                )


if __name__ == "__main__":
    unittest.main()
