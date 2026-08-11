from __future__ import annotations

from pathlib import Path

from meta_flow.checks import cr_tracking, handoff_dispatch, state_transition
from meta_flow.semantics import SEMANTIC_KERNEL_VERSION, SEMANTIC_OWNER_MANIFEST, outcome
from meta_flow.semantics.attempt import (
    ACTIVE_HANDOFF_STATUSES,
    ALL_ATTEMPT_STATUSES,
    ALL_HANDOFF_STATUSES,
    TERMINAL_ATTEMPT_STATUSES,
    plan_rework,
)
from meta_flow.semantics.cr_status import (
    NATIVE_GATE_STATUSES,
    NATIVE_LIFECYCLE_STATUSES,
    NATIVE_READINESS_STATUSES,
    validate_native_status_tuple,
    validate_native_transition,
)
from meta_flow.state import event_ledger
from meta_flow.workflow.cr_model import FORMAL_CR_STATUSES


def test_kernel_version_and_cr_semantics_have_distinct_names() -> None:
    assert SEMANTIC_KERNEL_VERSION == "1.0.0"
    assert SEMANTIC_OWNER_MANIFEST == {
        "authority-pair-v2": "meta_flow.semantics.authority",
        "route-consumers-v1": "meta_flow.semantics.route",
        "native-cr-status-v1": "meta_flow.semantics.cr_status",
        "attempt-rework-v1": "meta_flow.semantics.attempt",
        "legacy-evidence-v1": "meta_flow.workflow.legacy_evidence_registry",
        "governance-ownership-v1": "meta_flow.semantics.ownership",
        "preregistration-semantics-v1": "meta_flow.semantics.preregistration",
        "outcome-boundary-v1": "meta_flow.semantics.outcome",
        "semantic-receipt-v1": "meta_flow.semantics.receipt",
        "lifecycle-transaction-v1": "meta_flow.work.lifecycle_transaction",
        "terminal-lineage-v1": "meta_flow.workflow.terminal_lineage",
        "usage-admission-v1": "meta_flow.work.usage_admission",
        "reference-lifecycle-v1": "meta_flow.project.reference_lifecycle",
        "detector-qualification-v1": "meta_flow.checks.detector_qualification",
    }
    assert "implemented" in FORMAL_CR_STATUSES
    assert "implemented" not in NATIVE_LIFECYCLE_STATUSES
    assert cr_tracking.ALLOWED_LIFECYCLE_STATUSES is NATIVE_LIFECYCLE_STATUSES
    assert cr_tracking.ALLOWED_READINESS_STATUSES is NATIVE_READINESS_STATUSES
    assert cr_tracking.ALLOWED_GATE_STATUSES is NATIVE_GATE_STATUSES


def test_cr064_cr065_representative_native_tuples_and_edges_remain_legal() -> None:
    assert validate_native_status_tuple("closed", "READY_WITH_RISK", "cp8_closed") == []
    assert validate_native_status_tuple("closed", "READY", "closed") == []
    assert validate_native_transition(
        ("active", "not_ready", "implementation_in_progress"),
        ("active", "not_ready", "verification_in_progress"),
    ) == []
    assert validate_native_transition(
        ("closed", "ready", "cp8_closed"),
        ("active", "not_ready", "cp2_pending"),
    )


def test_attempt_and_handoff_consumers_reexport_kernel_objects() -> None:
    assert event_ledger.ALL_ATTEMPT_STATUSES is ALL_ATTEMPT_STATUSES
    assert event_ledger.TERMINAL_ATTEMPT_STATUSES is TERMINAL_ATTEMPT_STATUSES
    assert handoff_dispatch.ACTIVE_SUBAGENT_STATUSES is ACTIVE_HANDOFF_STATUSES
    assert handoff_dispatch.KNOWN_HANDOFF_STATUSES is ALL_HANDOFF_STATUSES
    assert state_transition.PASS_LIKE_DECISIONS is outcome.PASS_LIKE_VERIFICATION_DECISIONS
    assert state_transition.FAILURE_DECISIONS is outcome.FAILURE_VERIFICATION_DECISIONS


def test_rework_plan_reuses_work_thread_and_never_creates_worktree() -> None:
    plan = plan_rework(
        previous_work_id="W-1",
        next_work_id="W-1",
        previous_thread_id="thread-1",
        next_thread_id="thread-1",
        previous_attempt_id="attempt-1",
        next_attempt_id="attempt-2",
        previous_dispatch_id="dispatch-1",
        next_dispatch_id="dispatch-2",
        failed_layer="full",
        source_changed=False,
        command_changed=False,
        worktree_policy="root-branch-only",
    )
    assert plan.decision == "READY"
    assert plan.reuse_work is True
    assert plan.reuse_thread is True
    assert plan.new_attempt is True
    assert plan.new_dispatch is True
    assert plan.create_worktree is False
    assert plan.layers == ("full",)

    source_rework = plan_rework(
        previous_work_id="W-1",
        next_work_id="W-1",
        previous_thread_id="thread-1",
        next_thread_id="thread-1",
        previous_attempt_id="attempt-1",
        next_attempt_id="attempt-2",
        previous_dispatch_id="dispatch-1",
        next_dispatch_id="dispatch-2",
        failed_layer="compatibility",
        source_changed=True,
        command_changed=False,
        worktree_policy="root-branch-only",
    )
    assert source_rework.layers == ("static", "targeted", "compatibility", "full")


def test_rework_plan_blocks_new_work_old_terminal_identity_or_worktree() -> None:
    plan = plan_rework(
        previous_work_id="W-1",
        next_work_id="W-2",
        previous_thread_id="thread-1",
        next_thread_id="thread-2",
        previous_attempt_id="attempt-1",
        next_attempt_id="attempt-1",
        previous_dispatch_id="dispatch-1",
        next_dispatch_id="dispatch-1",
        failed_layer="targeted",
        source_changed=False,
        command_changed=False,
        worktree_policy="paired-worktree",
    )
    assert plan.decision == "BLOCKED"
    assert set(plan.reason_codes) == {
        "REWORK_MUST_REUSE_WORK",
        "REWORK_MUST_REUSE_VERIFIED_THREAD",
        "REWORK_REQUIRES_NEW_ATTEMPT_ID",
        "REWORK_REQUIRES_NEW_DISPATCH_ID",
        "REWORK_MUST_NOT_CREATE_WORKTREE",
    }


def test_migrated_consumers_do_not_redeclare_semantic_sets() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = {
        "event-ledger": root / "meta_flow/state/event_ledger.py",
        "handoff": root / "meta_flow/checks/handoff_dispatch.py",
        "cr-tracking": root / "meta_flow/checks/cr_tracking.py",
        "read-expansion": root / "meta_flow/context_pack/read_expansion.py",
        "story-contract": root / "meta_flow/context_pack/story_contract.py",
        "story-evidence": root / "meta_flow/workflow/story_evidence.py",
        "state-transition": root / "meta_flow/checks/state_transition.py",
        "cp-result": root / "meta_flow/checks/cp_result.py",
        "failure-routing": root / "meta_flow/policies/failure_routing.py",
        "authority": root / "meta_flow/semantics/authority.py",
    }
    forbidden = {
        "event-ledger": ("TERMINAL_ATTEMPT_STATUSES = frozenset",),
        "handoff": ("ACTIVE_SUBAGENT_STATUSES = frozenset",),
        "cr-tracking": ("ALLOWED_LIFECYCLE_STATUSES = {",),
        "read-expansion": (
            '{"required", "optional", "forbidden"}',
            '"full_lld_required_by_policy"',
        ),
        "story-contract": (
            '{"required", "optional", "forbidden"}',
            '"full_lld_required_by_policy"',
        ),
        "story-evidence": ('requirement != "required"',),
        "state-transition": (
            'PASS_LIKE_DECISIONS = {',
            'FAILURE_DECISIONS = {',
            'FAILURE_STOP_REASONS = {',
        ),
        "cp-result": (
            'GENERAL_DECISIONS = {',
            'CP7_DECISIONS = GENERAL_DECISIONS |',
            'RELEASE_DECISIONS = {',
        ),
        "failure-routing": ('FAILURE_CLASSES = {',),
        "authority": (
            'status not in {"APPLIED", "RECOVERED", "NO_CHANGE", "BLOCKED", "PARTIAL"}',
        ),
    }
    for owner, path in sources.items():
        text = path.read_text(encoding="utf-8")
        assert all(token not in text for token in forbidden[owner])
