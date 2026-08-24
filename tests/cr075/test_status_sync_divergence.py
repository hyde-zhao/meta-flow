"""CR-075 MF-BUG-13：checkpoint projection divergence 的 typed BLOCKED（A-P0-06）。

历史 CHECKPOINT-LEDGER/result divergence 使 status-sync 以 typed BLOCKED +
repair 指引呈现（mutation=0），不得向 CLI 泄漏 traceback。
"""

from __future__ import annotations

import sys
import tempfile
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

from meta_flow.project.onboarding import ProjectInitRequest, apply_project_init, plan_project_init
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import resolve_runtime_ref
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.state import current
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
    resolve_runtime_ref=resolve_runtime_ref,
    dump_yaml=dump_yaml,
    load_yaml_object=load_yaml_object,
    work_scope=WorkScope,
)
sys.path.insert(0, str(Path(__file__).parents[1]))


def _prepare(tmp_path: Path) -> Path:
    release, _process, cr_path, _scope = _write_termination_fixture(
        tmp_path, collaborators=_FIXTURE_COLLABORATORS
    )
    # fixture 默认 cp8_pending；本用例需要合法边 cp5_pending -> implementation_in_progress。
    text = cr_path.read_text(encoding="utf-8")
    assert 'gate_status: "cp8_pending"' in text
    cr_path.write_text(
        text.replace('gate_status: "cp8_pending"', 'gate_status: "cp5_pending"'),
        encoding="utf-8",
    )
    current.write_current_state(release, current.default_current_state(release))
    current.update_current_state(
        release,
        {"active_change": "CR-101", "current_phase": "documentation"},
    )
    return release


def test_checkpoint_divergence_is_typed_blocked_with_repair_hint(tmp_path: Path) -> None:
    """divergence -> BLOCKED + CHECKPOINT_PROJECTION_DIVERGENT + repair 指引 + mutation=0。"""

    release = _prepare(tmp_path)

    def divergent_loader(*args: object, **kwargs: object):
        raise ValueError("checkpoint result identity is unavailable: process/checks/X.json")

    with patch.object(
        cr_status_sync.checkpoint_projection,
        "load_checkpoint_projection",
        side_effect=divergent_loader,
    ):
        plan = cr_status_sync.plan_status_sync(
            release,
            "CR-101",
            status="active",
            readiness="not_ready",
            gate_status="implementation_in_progress",
            work_id="WORK-101",
            effective_at="2026-08-24T00:00:00+00:00",
        )

    assert plan.decision == "BLOCKED"
    assert plan.reason.startswith("CHECKPOINT_PROJECTION_DIVERGENT:")
    assert "checkpoint result identity is unavailable" in plan.reason
    assert "repair=" in plan.reason
    # targets 为空集即 mutation=0 的机器证据（StatusSyncPlan 无 mutation_count 字段）。
    assert plan.targets == ()


def test_checkpoint_divergence_does_not_raise_traceback(tmp_path: Path) -> None:
    """同场景下 plan_status_sync 不抛异常（typed receipt 而非 traceback）。"""

    release = _prepare(tmp_path)

    def divergent_loader(*args: object, **kwargs: object):
        raise ValueError("checkpoint result identity is invalid: process/checks/Y.json")

    with patch.object(
        cr_status_sync.checkpoint_projection,
        "load_checkpoint_projection",
        side_effect=divergent_loader,
    ):
        try:
            plan = cr_status_sync.plan_status_sync(
                release,
                "CR-101",
                status="active",
                readiness="not_ready",
                gate_status="implementation_in_progress",
                work_id="WORK-101",
                effective_at="2026-08-24T00:00:00+00:00",
            )
        except ValueError as exc:  # pragma: no cover - 防回归守卫
            raise AssertionError(f"traceback leaked: {exc}") from exc

    assert plan.decision == "BLOCKED"
