"""STORY-CR076-S04 targeted 测试：journal 状态机扩展与 activation 验收点
（IL-02/IL-05 + IL-N02/N05/N06）。

权威 = cr076-installation-lifecycle TEST-PLAN + S04 LLD v1.0 §5/§6/§7。
"""

from __future__ import annotations

import pytest

from meta_flow.installation.authorization import ClaimedAuthorization
from meta_flow.installation.recovery import (
    ALLOWED_TRANSITIONS,
    JOURNAL_STATES,
    RecoveryError,
    create_journal,
    inspect_journal,
    journal_digest,
    record_activation_started,
    record_activation_verified,
    recover,
    transition,
    validate_journal,
)

D_A, D_B = "a" * 64, "b" * 64
NOW = "2026-09-01T00:00:00+00:00"
LATER = "2026-09-01T00:00:05+00:00"


def _claim(authorization_id: str = "auth-original", transaction_id: str = "txn-s04") -> ClaimedAuthorization:
    return ClaimedAuthorization(
        transaction_id=transaction_id,
        authorization_id=authorization_id,
        plan_digest=D_A,
        source_digest=D_A,
        target_digest=D_A,
        scope_digest=D_A,
        facts_digest=D_A,
    )


def _journal() -> dict:
    return create_journal(
        _claim(),
        operation="assets.install",
        source_identity_digest=D_A,
        target_identity_digest=D_B,
        timestamp=NOW,
    )


def _applying_with_action() -> dict:
    journal = dict(_journal())
    journal["state"] = "applying"
    journal["updated_at"] = NOW
    journal["action_receipts"] = [
        {
            "action_id": "action-1",
            "ordinal": 1,
            "state": "applied",
            "target_ref": "agents/a.md",
            "before_digest": D_A,
            "after_digest": D_B,
            "preimage_ref": "preimages/action-1",
            "started_at": NOW,
            "completed_at": NOW,
            "error_code": "",
        }
    ]
    return validate_journal(journal)


# ---------------------------------------------------------------- IL-02 状态机


def test_il02_journal_states_gain_activating_without_reordering_tail() -> None:
    """activating 插入 applying 与 applied 之间；终态集合与尾段状态零改动。"""

    assert JOURNAL_STATES == (
        "planned",
        "authorized",
        "applying",
        "activating",
        "applied",
        "rollback_pending",
        "rolled_back",
        "partial",
        "blocked",
        "receipt_missing",
        "abandoned",
    )


def test_il02_applying_to_applied_direct_path_unchanged() -> None:
    """无 activation 的既有直达边 applying→applied 保持合法（回归）。"""

    journal = _applying_with_action()
    direct = transition(journal, "applied", timestamp=LATER)
    assert direct["state"] == "applied"
    assert journal_digest(direct)


def test_il02_activation_chain_applying_activating_applied() -> None:
    journal = _applying_with_action()
    started = record_activation_started(journal, activation_preimage_digest=D_B, timestamp=LATER)
    assert started["state"] == "activating"
    verified = record_activation_verified(started, recomputed_digest=D_B, timestamp=LATER)
    assert transition(verified, "applied", timestamp=LATER)["state"] == "applied"


def test_il02_existing_transition_table_entries_unchanged() -> None:
    """除 applying 出边加 activating 与 activating 新条目外，既有条目逐键相等。"""

    assert ALLOWED_TRANSITIONS["planned"] == frozenset({"authorized", "blocked"})
    assert ALLOWED_TRANSITIONS["authorized"] == frozenset({"applying", "blocked"})
    assert ALLOWED_TRANSITIONS["applying"] == frozenset(
        {"activating", "applied", "rollback_pending", "partial", "receipt_missing"}
    )
    assert ALLOWED_TRANSITIONS["activating"] == frozenset({"applied", "rollback_pending", "partial"})
    assert ALLOWED_TRANSITIONS["applied"] == frozenset()


def test_il02_activation_receipt_shape_and_ordinal() -> None:
    journal = _applying_with_action()
    started = record_activation_started(journal, activation_preimage_digest=D_B, timestamp=LATER)
    (receipt,) = started["action_receipts"][1:]
    assert receipt["action_id"] == "activation-1"
    assert receipt["ordinal"] == 2
    assert receipt["state"] == "applied"
    assert receipt["target_ref"] == "activation/txn-s04"
    assert receipt["preimage_ref"] == "activation-preimages/txn-s04"
    assert receipt["before_digest"] == receipt["after_digest"] == D_B


# ------------------------------------------------- activation 前置（负向）


def test_activation_started_requires_applying_journal() -> None:
    with pytest.raises(RecoveryError, match="applying"):
        record_activation_started(_journal(), activation_preimage_digest=D_B, timestamp=LATER)


def test_activation_started_rejects_malformed_preimage() -> None:
    with pytest.raises(RecoveryError, match="digest"):
        record_activation_started(_applying_with_action(), activation_preimage_digest="zz", timestamp=LATER)


def test_activation_receipt_is_unique_per_transaction() -> None:
    """resume 重放路径：journal 回到 applying 但 activation receipt 已存在 → 拒绝。"""

    replayed = dict(_applying_with_action())
    replayed["action_receipts"].append(
        {
            "action_id": "activation-1",
            "ordinal": 2,
            "state": "applied",
            "target_ref": "activation/txn-s04",
            "before_digest": D_B,
            "after_digest": D_B,
            "preimage_ref": "activation-preimages/txn-s04",
            "started_at": NOW,
            "completed_at": NOW,
            "error_code": "",
        }
    )
    with pytest.raises(RecoveryError, match="already exists"):
        record_activation_started(validate_journal(replayed), activation_preimage_digest=D_B, timestamp=LATER)


def test_activation_verified_requires_activating_journal() -> None:
    with pytest.raises(RecoveryError, match="activating"):
        record_activation_verified(_applying_with_action(), recomputed_digest=D_B, timestamp=LATER)


# --------------------------------------- IL-05 / IL-N02 验收点与 preimage 漂移


def test_il05_verified_requires_recomputed_digest_equal_to_preimage() -> None:
    started = record_activation_started(_applying_with_action(), activation_preimage_digest=D_B, timestamp=LATER)
    verified = record_activation_verified(started, recomputed_digest=D_B, timestamp=LATER)
    activation = verified["action_receipts"][1]
    assert activation["state"] == "verified"
    assert activation["completed_at"] == LATER


def test_il05_n02_preimage_drift_raises_typed_recovery_error() -> None:
    started = record_activation_started(_applying_with_action(), activation_preimage_digest=D_B, timestamp=LATER)
    with pytest.raises(RecoveryError, match="ACTIVATION-PREIMAGE-DRIFT"):
        record_activation_verified(started, recomputed_digest=D_A, timestamp=LATER)


def test_il05_drift_does_not_mutate_input_journal() -> None:
    started = record_activation_started(_applying_with_action(), activation_preimage_digest=D_B, timestamp=LATER)
    before = journal_digest(started)
    with pytest.raises(RecoveryError):
        record_activation_verified(started, recomputed_digest=D_A, timestamp=LATER)
    assert journal_digest(started) == before


# ----------------------------- IL-N05 中断停留与 IL-N06 恢复授权不可复用


def test_n05_interrupted_activation_stays_activating_without_terminal() -> None:
    """fault injection：started 之后、verified 之前中断 → journal 停留 activating。"""

    started = record_activation_started(_applying_with_action(), activation_preimage_digest=D_B, timestamp=LATER)
    assert started["state"] == "activating"
    assert started["terminal_receipt_ref"] == ""
    observation = inspect_journal(started)
    assert observation.state == "activating"
    assert observation.planned_actions == 2
    assert observation.applied_actions == 2  # 动作 receipt + applied 态 activation receipt


def test_n06_recovery_rejects_reusing_original_authorization() -> None:
    started = record_activation_started(_applying_with_action(), activation_preimage_digest=D_B, timestamp=LATER)
    interrupted = transition(started, "partial", timestamp=LATER)
    with pytest.raises(RecoveryError, match="cannot reuse the original authorization"):
        recover(interrupted, "resume", new_claim_context=_claim("auth-original"))


def test_n06_inspect_consumes_no_authorization() -> None:
    started = record_activation_started(_applying_with_action(), activation_preimage_digest=D_B, timestamp=LATER)
    with pytest.raises(RecoveryError, match="must not consume authorization"):
        recover(started, "inspect", new_claim_context=_claim("auth-new"))


# -------------------------------- IL-07 rollback guard 覆盖 activation receipt


def test_il07_rollback_guard_covers_activation_receipt() -> None:
    """guard 遍历域含 applied 态 activation receipt：digest/preimage 匹配才可回滚。"""

    started = record_activation_started(_applying_with_action(), activation_preimage_digest=D_B, timestamp=LATER)
    interrupted = transition(started, "partial", timestamp=LATER)
    plan = recover(
        interrupted,
        "rollback",
        new_claim_context=_claim("auth-recovery"),
        current_digests={"agents/a.md": D_B, "activation/txn-s04": D_B},
        available_preimage_refs=frozenset({"preimages/action-1", "activation-preimages/txn-s04"}),
    )
    assert plan.recovery_action == "rollback"
    assert plan.action_ids == ("activation-1", "action-1")  # 逆序：activation 先回滚
    assert plan.next_state == "rollback_pending"


def test_il07_rollback_guard_blocks_on_activation_digest_mismatch() -> None:
    started = record_activation_started(_applying_with_action(), activation_preimage_digest=D_B, timestamp=LATER)
    interrupted = transition(started, "partial", timestamp=LATER)
    with pytest.raises(RecoveryError, match="guard failed"):
        recover(
            interrupted,
            "rollback",
            new_claim_context=_claim("auth-recovery"),
            current_digests={"agents/a.md": D_B},  # activation 目标缺观察 digest
            available_preimage_refs=frozenset({"preimages/action-1", "activation-preimages/txn-s04"}),
        )
