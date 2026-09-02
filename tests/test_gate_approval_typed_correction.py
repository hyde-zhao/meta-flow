"""CR-076 R1（S02）：gate typed projection recovery 的 typed correction 合同。

GATE-LEDGER 中 approval_kind_version=1 但 approval_kind 越界的毒行
（budget_amendment / implementation_authorization）产生
GATE_APPROVAL_KIND_UNKNOWN，必须经由追加式 ``gate_approval_typed_correction``
事件修复（append-only，不改写历史行）：

- correction 禁止产出 checkpoint passage（防伪造门禁推进）；
- 合法行（含原本 passage）不得被 correction 改写；
- typed correction 与 legacy migration（correction/cutover）完全分离；
- summary 投影 ValueError 必须以 typed BLOCKED 呈现，不向 CLI 泄漏 traceback。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cr_lifecycle_test_support import (
    LifecycleFixtureCollaborators,
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
from meta_flow.state import current, event_ledger
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


def _poison_event() -> dict:
    """构造与真实 GATE-LEDGER 285/287-290 同形状的毒行（scope 字段齐备）。"""

    return {
        "event_id": "GATE-CR076-SCOPE-AUTH-V1",
        "event_type": "human_gate_approval",
        "gate": "CR076_P6_SCOPE_AUTHORIZATION",
        "status": "approved",
        "decision": "approve",
        "cr_id": "CR-076",
        "work_id": "WORK-076",
        "approval_kind_version": 1,
        "approval_kind": "implementation_authorization",
        "scope_version": 1,
        "scope_digest": "a" * 64,
        "authorized_actions": ["publish-artifacts"],
        "decision_ref": "process/checkpoints/CP6-CR-076.md",
    }


def _typed_correction(target: dict, **overrides: object) -> dict:
    """构造指向 target 行的合法 typed correction（默认改为 scope_amendment）。"""

    correction: dict = {
        "event_id": "GATE-CR076-TYPED-CORRECTION-V1",
        "event_type": "gate_approval_typed_correction",
        "corrects_event_id": target["event_id"],
        "original_event_digest": event_ledger.canonical_digest(
            event_ledger._clean_event(target)
        ),
        "cr_id": target["cr_id"],
        "work_id": target["work_id"],
        "approval_kind_version": 1,
        "approval_kind": "scope_amendment",
    }
    correction.update(overrides)
    return correction


def test_poison_row_without_correction_keeps_kind_unknown() -> None:
    """现状基线：毒行无 correction 时维持 GATE_APPROVAL_KIND_UNKNOWN。"""

    projection = event_ledger.project_gate_approvals([_poison_event()])[0]

    assert "GATE_APPROVAL_KIND_UNKNOWN" in projection.finding_codes
    assert projection.passage is False
    assert projection.approval_kind == ""


def test_valid_correction_repairs_projection_without_passage() -> None:
    """合法 correction -> findings 空、passage=False、kind=scope_amendment。"""

    poison = _poison_event()
    events = [poison, _typed_correction(poison)]

    projection = event_ledger.project_gate_approvals(events)[0]

    assert projection.finding_codes == ()
    assert projection.passage is False
    assert projection.approval_kind == "scope_amendment"
    # 身份字段取原行：correction 不得改写 event_id/cr_id/work_id。
    assert projection.event_id == poison["event_id"]
    assert projection.cr_id == "CR-076"
    assert projection.work_id == "WORK-076"
    assert projection.scope_version == 1


def test_correction_forbidden_to_produce_passage() -> None:
    """毒行修复禁止产出 passage：kind=checkpoint_passage -> KIND_FORBIDDEN。"""

    poison = _poison_event()
    correction = _typed_correction(poison, approval_kind="checkpoint_passage")

    projection = event_ledger.project_gate_approvals([poison, correction])[0]

    assert "GATE_APPROVAL_TYPED_CORRECTION_KIND_FORBIDDEN" in projection.finding_codes
    # 校验失败时原行维持原 findings，投影不修正。
    assert "GATE_APPROVAL_KIND_UNKNOWN" in projection.finding_codes
    assert projection.passage is False


def test_correction_digest_mismatch_keeps_original_findings() -> None:
    """digest 不匹配 -> DIGEST_MISMATCH，原行 findings 维持。"""

    poison = _poison_event()
    correction = _typed_correction(poison, original_event_digest="0" * 64)

    projection = event_ledger.project_gate_approvals([poison, correction])[0]

    assert "GATE_APPROVAL_TYPED_CORRECTION_DIGEST_MISMATCH" in projection.finding_codes
    assert "GATE_APPROVAL_KIND_UNKNOWN" in projection.finding_codes
    assert projection.passage is False


def test_correction_crossing_target_is_rejected() -> None:
    """correction cr_id 与原行不一致 -> CROSSES_TARGET。"""

    poison = _poison_event()
    correction = _typed_correction(poison, cr_id="CR-OTHER")

    projection = event_ledger.project_gate_approvals([poison, correction])[0]

    assert "GATE_APPROVAL_TYPED_CORRECTION_CROSSES_TARGET" in projection.finding_codes
    assert "GATE_APPROVAL_KIND_UNKNOWN" in projection.finding_codes


def test_duplicate_corrections_for_same_target_are_rejected() -> None:
    """同一原行两条 correction -> DUPLICATE，不取任何一条修正。"""

    poison = _poison_event()
    first = _typed_correction(poison)
    second = _typed_correction(
        poison, event_id="GATE-CR076-TYPED-CORRECTION-V2"
    )

    projection = event_ledger.project_gate_approvals([poison, first, second])[0]

    assert "GATE_APPROVAL_TYPED_CORRECTION_DUPLICATE" in projection.finding_codes
    assert "GATE_APPROVAL_KIND_UNKNOWN" in projection.finding_codes


def test_legitimate_passage_row_is_never_rewritten_by_correction() -> None:
    """合法 checkpoint_passage 行不受任何 typed correction 影响。"""

    passage = {
        "event_id": "GATE-CR076-PASSAGE-V1",
        "event_type": "human_gate_approval",
        "gate": "CP6_FINAL_VERIFICATION",
        "status": "approved",
        "decision": "approve",
        "cr_id": "CR-076",
        "work_id": "WORK-076",
        "approval_kind_version": 1,
        "approval_kind": "checkpoint_passage",
        "checkpoint": "CP6",
        "result_ref": "process/checks/CP6-CR-076-CODING-DONE.result.json",
    }
    poison = _poison_event()
    events = [
        passage,
        poison,
        # 指向合法 passage 行的 correction 不得改写该行。
        _typed_correction(passage, event_id="GATE-CR076-CORRECT-PASSAGE-V1"),
    ]

    passage_projection, poison_projection = event_ledger.project_gate_approvals(events)

    assert passage_projection.passage is True
    assert passage_projection.finding_codes == ()
    assert passage_projection.approval_kind == "checkpoint_passage"
    assert passage_projection.checkpoint == "CP6"
    assert (
        passage_projection.result_ref
        == "process/checks/CP6-CR-076-CODING-DONE.result.json"
    )
    # 毒行只受指向自己的 correction 影响。
    assert "GATE_APPROVAL_KIND_UNKNOWN" in poison_projection.finding_codes


def test_legacy_manifest_projection_is_unchanged_by_typed_correction() -> None:
    """legacy manifest 行投影零回归；typed correction 不触发 migration 路径。"""

    legacy_id = next(iter(event_ledger._LEGACY_GATE_APPROVAL_MANIFEST_V1))
    expected_kind, expected_checkpoint, expected_result_ref = (
        event_ledger._LEGACY_GATE_APPROVAL_MANIFEST_V1[legacy_id]
    )
    legacy = {
        "event_id": legacy_id,
        "event_type": "human_gate_approval",
        "gate": "LEGACY_VALUE_MUST_NOT_BE_PARSED",
        "status": "approved",
        "decision": "approve",
        "cr_id": "CR-LEGACY",
        "work_id": "W-LEGACY",
        "interaction_id": legacy_id,
    }
    poison = _poison_event()
    correction = _typed_correction(poison)

    legacy_projection, _poison_projection = event_ledger.project_gate_approvals(
        [legacy, poison, correction]
    )

    assert legacy_projection.approval_kind == str(expected_kind)
    assert legacy_projection.checkpoint == expected_checkpoint
    assert legacy_projection.result_ref == expected_result_ref
    assert legacy_projection.finding_codes == ()
    assert legacy_projection.passage is (
        expected_kind is event_ledger.GateApprovalKindV1.CHECKPOINT_PASSAGE
    )
    # typed correction 不得触发 legacy migration/cutover/correction findings。
    assert "GATE_APPROVAL_CUTOVER_PARTIAL" not in legacy_projection.finding_codes


def test_correction_targeting_legacy_row_reports_target_unknown() -> None:
    """typed correction 指向非 typed-v1 行 -> TARGET_UNKNOWN，不修正任何投影。"""

    legacy_id = next(iter(event_ledger._LEGACY_GATE_APPROVAL_MANIFEST_V1))
    legacy = {
        "event_id": legacy_id,
        "event_type": "human_gate_approval",
        "gate": "LEGACY_VALUE_MUST_NOT_BE_PARSED",
        "status": "approved",
        "decision": "approve",
        "cr_id": "CR-LEGACY",
        "work_id": "W-LEGACY",
        "interaction_id": legacy_id,
    }
    correction = _typed_correction(
        {**legacy, "approval_kind_version": 1, "approval_kind": "scope_amendment"}
    )
    # correction 声称修正 legacy 行本身。
    correction["corrects_event_id"] = legacy_id

    projection = event_ledger.project_gate_approvals([legacy, correction])[0]

    assert "GATE_APPROVAL_TYPED_CORRECTION_TARGET_UNKNOWN" in projection.finding_codes
    assert projection.passage is False


def test_insufficient_correction_reports_merged_findings() -> None:
    """correction 通过安全校验但 merged 仍缺字段 -> INSUFFICIENT + merged findings。"""

    poison = _poison_event()
    del poison["scope_digest"]
    correction = _typed_correction(poison)

    projection = event_ledger.project_gate_approvals([poison, correction])[0]

    assert (
        "GATE_APPROVAL_TYPED_CORRECTION_INSUFFICIENT" in projection.finding_codes
    )
    assert "GATE_APPROVAL_SCOPE_DIGEST_REQUIRED" in projection.finding_codes
    assert projection.passage is False


def _prepare_status_sync_fixture(tmp_path: Path) -> Path:
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


def test_summary_projection_divergence_is_typed_blocked(tmp_path: Path) -> None:
    """summary 投影 ValueError -> BLOCKED + SUMMARY_PROJECTION_DIVERGENT + mutation=0。"""

    release = _prepare_status_sync_fixture(tmp_path)

    def divergent_summary(*args: object, **kwargs: object):
        raise ValueError(
            "gate decision owner approval is invalid: GATE_APPROVAL_KIND_UNKNOWN"
        )

    with patch.object(
        cr_status_sync,
        "summary_from_cr_file",
        side_effect=divergent_summary,
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
    assert plan.reason.startswith("SUMMARY_PROJECTION_DIVERGENT:")
    assert "GATE_APPROVAL_KIND_UNKNOWN" in plan.reason
    assert "repair=" in plan.reason
    assert plan.targets == ()


def test_summary_projection_divergence_does_not_raise_traceback(tmp_path: Path) -> None:
    """同场景下 plan_status_sync 不抛异常（typed receipt 而非 traceback）。"""

    release = _prepare_status_sync_fixture(tmp_path)

    def divergent_summary(*args: object, **kwargs: object):
        raise ValueError(
            "gate decision owner approval is invalid: GATE_APPROVAL_KIND_UNKNOWN"
        )

    with patch.object(
        cr_status_sync,
        "summary_from_cr_file",
        side_effect=divergent_summary,
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
