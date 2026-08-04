from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.installation.authorization import (
    AUTHORIZATION_FIELDS,
    AUTHORIZATION_SOURCE,
    AuthorizationClaims,
    ClaimedAuthorization,
    authorization_binding,
)
from meta_flow.installation.canonical import build_plan, canonical_digest
from meta_flow.installation.engine import dispatch_authorized_actions
from meta_flow.installation.planner import CHECKPOINT_SCALARS, CHECKPOINTS
from meta_flow.installation.recovery import (
    ACTION_RECEIPT_FIELDS,
    ALLOWED_TRANSITIONS,
    JOURNAL_FIELDS,
    JOURNAL_STATES,
    RECOVERY_ACTIONS,
    DurableJournalStore,
    RecoveryError,
    create_journal,
    finalize_journal,
    inspect_journal,
    journal_digest,
    record_action_outcome,
    record_action_started,
    recover,
    transition,
    validate_journal,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
NOW = "2026-07-31T00:00:00+00:00"
LATER = "2026-07-31T00:00:01+00:00"


def _claim(
    authorization_id: str = "auth-new",
    transaction_id: str = "txn-1",
) -> ClaimedAuthorization:
    return ClaimedAuthorization(
        transaction_id=transaction_id,
        authorization_id=authorization_id,
        plan_digest=DIGEST_A,
        source_digest=DIGEST_A,
        target_digest=DIGEST_A,
        scope_digest=DIGEST_A,
        facts_digest=DIGEST_A,
    )


def _journal() -> dict[str, object]:
    return create_journal(
        _claim("auth-original"),
        operation="assets.install",
        source_identity_digest=DIGEST_A,
        target_identity_digest=DIGEST_B,
        timestamp=NOW,
    )


def _action() -> dict[str, object]:
    unsigned = {
        "action_id": "action-1",
        "action_kind": "write_exact_file",
        "component": "agents",
        "ownership_kind": "exact_file",
        "source_ref": "delivery/agents/meta-dev.toml",
        "target_ref": ".codex/agents/meta-dev.toml",
        "before_state": {"exists": False, "digest": ""},
        "desired_state": {"digest": DIGEST_B},
        "preconditions": [],
        "rollback_action": None,
        "ordinal": 1,
    }
    return {**unsigned, "action_digest": canonical_digest(unsigned)}


def _plan() -> dict[str, object]:
    manifest_unsigned = {
        "action_id": "action-2",
        "action_kind": "write_manifest",
        "component": "manifest",
        "ownership_kind": "manifest",
        "source_ref": None,
        "target_ref": ".meta-flow/INSTALL-MANIFEST.yaml",
        "before_state": {"exists": False, "digest": ""},
        "desired_state": {"digest": DIGEST_A},
        "preconditions": [],
        "rollback_action": None,
        "ordinal": 2,
    }
    return build_plan(
        operation="assets.install",
        decision_ref="decisions/recovery-test.json",
        request_intent="install exact assets",
        component="agents",
        scope="project",
        platform="codex",
        source_identity={
            "source": "checkout/meta-flow",
            "version": "1.2.3",
            "oid": "c" * 40,
            "delivery_tree_digest": DIGEST_A,
            "rules_source_digest": DIGEST_A,
            "inventory_digest": DIGEST_A,
        },
        target_identity={"project_id": "fixture", "digest": DIGEST_B},
        base_facts={"target_complete": True},
        actions=[_action(), manifest_unsigned],
        rollback_plan={
            "strategy": "explicit-recovery",
            "transaction_ref": "transactions/recovery-test.json",
        },
    )


def _authorization(plan: dict[str, object]) -> dict[str, object]:
    values: dict[str, object] = {
        "schema_version": 1,
        "authorization_id": "auth-dispatch",
        "authorization_source": AUTHORIZATION_SOURCE,
        "authorization_kind": "installation-mutation",
        **authorization_binding(plan),
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "single_use": True,
    }
    return {field: values[field] for field in AUTHORIZATION_FIELDS}


def _facts() -> dict[str, dict[str, str]]:
    return {
        checkpoint: {
            scalar: f"{checkpoint}-{scalar}"
            for scalar in CHECKPOINT_SCALARS
        }
        for checkpoint in CHECKPOINTS
    }


def _partial_journal() -> dict[str, object]:
    journal = record_action_started(
        _journal(),
        _action(),
        preimage_ref="preimages/action-1",
        before_digest="",
        timestamp=NOW,
    )
    journal = record_action_outcome(
        journal,
        action_id="action-1",
        after_digest=DIGEST_B,
        error_code="",
        timestamp=LATER,
    )
    return transition(journal, "partial", timestamp=LATER)


def _cr066_action(action_id: str, ordinal: int, target_ref: str) -> dict[str, object]:
    unsigned = {
        "action_id": action_id,
        "action_kind": "write_exact_file",
        "component": "agents",
        "ownership_kind": "exact_file",
        "source_ref": f"delivery/{action_id}.txt",
        "target_ref": target_ref,
        "before_state": {"exists": False, "digest": ""},
        "desired_state": {"digest": DIGEST_B},
        "preconditions": [],
        "rollback_action": None,
        "ordinal": ordinal,
    }
    return {**unsigned, "action_digest": canonical_digest(unsigned)}


def run_cr066_failure_recovery_fixture(workspace: Path) -> dict[str, object]:
    """供 CR-066 外部 harness 编排的 registered durable-recovery fixture。"""

    from cr066_external_fixture_harness import (
        _base_report,
        diff_snapshots,
        filesystem_snapshot,
    )

    final = "2026-08-04T00:00:02+00:00"
    case_root = workspace / "failure-recovery"
    target = case_root / "target"
    target.mkdir(parents=True)
    before = filesystem_snapshot(target)
    first_path = target / "first.txt"
    second_path = target / "second.txt"
    later_path = target / "later-slice.txt"
    first = _cr066_action("action-1", 1, "target/first.txt")
    second = _cr066_action("action-2", 2, "target/second.txt")

    journal = create_journal(
        _claim("auth-original", "txn-cr066-recovery"),
        operation="assets.install",
        source_identity_digest=DIGEST_A,
        target_identity_digest=DIGEST_B,
        timestamp=NOW,
    )
    journal = record_action_started(
        journal,
        first,
        preimage_ref="preimages/action-1",
        before_digest="",
        timestamp=NOW,
    )
    first_path.write_text("partial mutation\n", encoding="utf-8")
    first_digest = sha256(first_path.read_bytes()).hexdigest()
    journal = record_action_outcome(
        journal,
        action_id="action-1",
        after_digest=first_digest,
        error_code="",
        timestamp=LATER,
    )
    journal = record_action_started(
        journal,
        second,
        preimage_ref="preimages/action-2",
        before_digest="",
        timestamp=LATER,
    )
    partial = finalize_journal(
        journal,
        terminal_state="partial",
        terminal_receipt_ref="receipts/txn-cr066-recovery.partial.json",
        timestamp=LATER,
    )
    partial_snapshot = filesystem_snapshot(target)
    mutations = diff_snapshots(before, partial_snapshot)
    inspected = inspect_journal(partial)
    inspect_after = filesystem_snapshot(target)
    unauthenticated_blocked = False
    try:
        recover(partial, "rollback")
    except ValueError:
        unauthenticated_blocked = True

    resume_plan = recover(
        partial,
        "resume",
        new_claim_context=_claim("auth-resume", "txn-cr066-resume"),
    )
    rollback_plan = recover(
        partial,
        "rollback",
        new_claim_context=_claim("auth-rollback", "txn-cr066-rollback"),
        current_digests={"target/first.txt": first_digest},
        available_preimage_refs=frozenset({"preimages/action-1"}),
    )

    rollback_pending = transition(partial, "rollback_pending", timestamp=final)
    first_path.unlink()
    compensated = deepcopy(rollback_pending)
    for receipt in compensated["action_receipts"]:
        if receipt["action_id"] == "action-1":
            receipt["state"] = "compensated"
            receipt["completed_at"] = final
    compensated = validate_journal(compensated)
    rolled_back = transition(compensated, "rolled_back", timestamp=final)
    final_snapshot = filesystem_snapshot(target)
    rollback_ok = final_snapshot["digest"] == before["digest"]
    later_slice_executions = int(second_path.exists()) + int(later_path.exists())
    passed = (
        inspected.state == "partial"
        and inspected.mutation_count == 0
        and inspect_after["digest"] == partial_snapshot["digest"]
        and unauthenticated_blocked
        and resume_plan.action_ids == ("action-2",)
        and rollback_plan.action_ids == ("action-1",)
        and rolled_back["state"] == "rolled_back"
        and rollback_ok
        and later_slice_executions == 0
    )
    return _base_report(
        "failure-recovery",
        initial_state={
            "target_digest": before["digest"],
            "journal_state": "authorized",
            "planned_slices": ["action-1", "action-2", "later-slice"],
        },
        expected_result={
            "failure_state": "partial",
            "inspect_mutations": 0,
            "resume_pending_actions": ["action-2"],
            "rollback_actions": ["action-1"],
            "later_slice_executions": 0,
            "final_state": "rolled_back",
        },
        actual_result={
            "decision": "PASS" if passed else "FAIL",
            "failure_state": inspected.state,
            "inspect_mutations": inspected.mutation_count,
            "inspect_digest_unchanged": (
                inspect_after["digest"] == partial_snapshot["digest"]
            ),
            "unauthenticated_recovery_blocked": unauthenticated_blocked,
            "resume_pending_actions": list(resume_plan.action_ids),
            "rollback_actions": list(rollback_plan.action_ids),
            "later_slice_executions": later_slice_executions,
            "final_state": rolled_back["state"],
        },
        mutations=mutations,
        before_digest=before["digest"],
        after_digest=partial_snapshot["digest"],
        failure_path={
            "injected_after": "action-1-applied/action-2-journaled-before-write",
            "reported_state": inspected.state,
            "reported_as_success": False,
            "later_slice_executions": later_slice_executions,
        },
        rollback={
            "strategy": "new-typed-claim-plus-digest-and-preimage-guard",
            "decision": "PASS" if rollback_ok else "FAIL",
            "restored_digest": final_snapshot["digest"],
            "digest_restored": rollback_ok,
        },
        user_experience=(
            "partial 明确可见；inspect 只读；resume/rollback 都要求新的 claim，"
            "失败后不执行后续切片。"
        ),
    )


def test_journal_and_action_receipt_have_exact_schema() -> None:
    journal = record_action_started(
        _journal(),
        _action(),
        preimage_ref="preimages/action-1",
        before_digest="",
        timestamp=NOW,
    )

    assert tuple(journal) == JOURNAL_FIELDS
    assert tuple(journal["action_receipts"][0]) == ACTION_RECEIPT_FIELDS
    assert len(JOURNAL_STATES) == 10
    assert len(RECOVERY_ACTIONS) == 4


def test_unknown_or_secret_like_journal_keys_fail() -> None:
    journal = _journal()
    journal["token"] = "not-allowed"

    with pytest.raises(RecoveryError, match="unknown keys"):
        validate_journal(journal)


@pytest.mark.parametrize(
    ("current", "next_state"),
    [
        (current, next_state)
        for current, next_states in ALLOWED_TRANSITIONS.items()
        for next_state in next_states
    ],
)
def test_all_declared_transitions_are_allowed(
    current: str,
    next_state: str,
) -> None:
    journal = _journal()
    journal["state"] = current

    assert transition(journal, next_state, timestamp=LATER)["state"] == next_state


def test_illegal_transition_is_fail_closed() -> None:
    with pytest.raises(RecoveryError, match="illegal journal transition"):
        transition(_journal(), "applied", timestamp=LATER)


def test_durable_store_uses_digest_compare_and_set(tmp_path: Path) -> None:
    store = DurableJournalStore(tmp_path / "journals")
    journal = _journal()
    first_digest = store.persist(journal)
    loaded = store.load("txn-1")
    updated = transition(loaded, "applying", timestamp=LATER)

    with pytest.raises(RecoveryError, match="compare-and-set"):
        store.persist(updated)

    second_digest = store.persist(updated, expected_digest=first_digest)
    assert second_digest == journal_digest(updated)
    assert store.load("txn-1")["state"] == "applying"


def test_action_before_write_and_true_outcome_are_recorded() -> None:
    journal = record_action_started(
        _journal(),
        _action(),
        preimage_ref="preimages/action-1",
        before_digest="",
        timestamp=NOW,
    )
    assert journal["state"] == "applying"
    assert journal["action_receipts"][0]["state"] == "planned"
    assert journal["action_receipts"][0]["after_digest"] == ""

    journal = record_action_outcome(
        journal,
        action_id="action-1",
        after_digest=DIGEST_B,
        error_code="",
        timestamp=LATER,
    )
    assert journal["action_receipts"][0]["state"] == "applied"
    assert journal["action_receipts"][0]["after_digest"] == DIGEST_B


def test_terminal_receipt_is_unique_and_receipt_missing_is_explicit() -> None:
    journal = record_action_started(
        _journal(),
        _action(),
        preimage_ref="preimages/action-1",
        before_digest="",
        timestamp=NOW,
    )
    journal = record_action_outcome(
        journal,
        action_id="action-1",
        after_digest=DIGEST_B,
        error_code="",
        timestamp=LATER,
    )
    applied = finalize_journal(
        journal,
        terminal_state="applied",
        terminal_receipt_ref="receipts/txn-1.json",
        timestamp=LATER,
    )
    assert applied["state"] == "applied"
    assert applied["terminal_receipt_ref"] == "receipts/txn-1.json"

    with pytest.raises(RecoveryError, match="already exists"):
        finalize_journal(
            applied,
            terminal_state="applied",
            terminal_receipt_ref="receipts/other.json",
            timestamp=LATER,
        )

    missing = finalize_journal(
        journal,
        terminal_state="receipt_missing",
        terminal_receipt_ref="",
        timestamp=LATER,
    )
    assert missing["state"] == "receipt_missing"
    assert missing["terminal_receipt_ref"] == ""


def test_inspect_is_read_only_and_requires_no_authorization() -> None:
    journal = _partial_journal()

    observation = inspect_journal(journal)
    via_recover = recover(journal, "inspect")

    assert observation == via_recover
    assert observation.authorization_required is False
    assert observation.mutation_count == 0
    assert observation.applied_actions == 1


def test_resume_rollback_and_abandon_require_new_claim() -> None:
    journal = _partial_journal()
    for action in ("resume", "rollback", "abandon"):
        with pytest.raises(RecoveryError, match="new claimed authorization"):
            recover(journal, action)

    resume = recover(journal, "resume", new_claim_context=_claim())
    abandon = recover(journal, "abandon", new_claim_context=_claim())

    assert resume.recovery_action == "resume"
    assert resume.next_state == "planned"
    assert abandon.recovery_action == "abandon"
    assert abandon.next_state == "abandoned"
    assert resume.mutation_count == abandon.mutation_count == 0


def test_rollback_requires_after_digest_and_preimage_guard() -> None:
    journal = _partial_journal()

    with pytest.raises(RecoveryError, match="digest/preimage guard"):
        recover(
            journal,
            "rollback",
            new_claim_context=_claim(),
            current_digests={".codex/agents/meta-dev.toml": DIGEST_A},
            available_preimage_refs=frozenset({"preimages/action-1"}),
        )
    with pytest.raises(RecoveryError, match="digest/preimage guard"):
        recover(
            journal,
            "rollback",
            new_claim_context=_claim(),
            current_digests={".codex/agents/meta-dev.toml": DIGEST_B},
        )

    plan = recover(
        journal,
        "rollback",
        new_claim_context=_claim(),
        current_digests={".codex/agents/meta-dev.toml": DIGEST_B},
        available_preimage_refs=frozenset({"preimages/action-1"}),
    )
    assert plan.action_ids == ("action-1",)
    assert plan.next_state == "rollback_pending"
    assert plan.mutation_count == 0


def test_recovery_rejects_original_authorization_replay() -> None:
    journal = _partial_journal()
    original = _claim("auth-original", "txn-recovery")

    with pytest.raises(RecoveryError, match="original authorization"):
        recover(journal, "resume", new_claim_context=original)


def test_validation_does_not_mutate_input() -> None:
    journal = _journal()
    original = deepcopy(journal)

    validate_journal(journal)

    assert journal == original


def test_engine_persists_each_action_before_execution(tmp_path: Path) -> None:
    plan = _plan()
    store = DurableJournalStore(tmp_path / "journals")
    execution_states: list[str] = []

    def execute(context, action):
        execution_states.append(store.load(context.transaction_id)["state"])
        return {
            "state": "applied",
            "after_digest": DIGEST_B,
            "error_code": "",
            "mutation_count": 1,
            "action_id": action["action_id"],
        }

    receipt = dispatch_authorized_actions(
        plan=plan,
        authorization=_authorization(plan),
        expected_checkpoints=_facts(),
        observed_checkpoints=_facts(),
        claims=AuthorizationClaims(),
        action_executor=execute,
        preimage_provider=lambda action: (
            f"preimages/{action['action_id']}",
            "",
        ),
        journal_store=store,
        terminal_receipt_ref="receipts/recovery-test.json",
        clock=lambda: NOW,
    )
    journal = store.load(receipt.transaction_id)

    assert receipt.state == "applied"
    assert receipt.mutation_count == 2
    assert execution_states == ["applying", "applying"]
    assert [item["state"] for item in journal["action_receipts"]] == [
        "applied",
        "applied",
    ]
    assert journal["state"] == "applied"
    assert journal["terminal_receipt_ref"] == "receipts/recovery-test.json"


def test_engine_executor_exception_is_durable_partial(tmp_path: Path) -> None:
    plan = _plan()
    store = DurableJournalStore(tmp_path / "journals")

    receipt = dispatch_authorized_actions(
        plan=plan,
        authorization=_authorization(plan),
        expected_checkpoints=_facts(),
        observed_checkpoints=_facts(),
        claims=AuthorizationClaims(),
        action_executor=lambda _context, _action: (_ for _ in ()).throw(
            OSError("injected")
        ),
        preimage_provider=lambda action: (
            f"preimages/{action['action_id']}",
            "",
        ),
        journal_store=store,
        terminal_receipt_ref="receipts/recovery-test.json",
        clock=lambda: NOW,
    )
    journal = store.load(receipt.transaction_id)

    assert receipt.state == "partial"
    assert receipt.mutation_count == 0
    assert journal["state"] == "partial"
    assert (
        journal["action_receipts"][0]["error_code"]
        == "EXECUTOR_EXCEPTION_OSERROR"
    )
