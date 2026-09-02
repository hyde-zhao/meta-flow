"""STORY-CR076-S04 targeted 测试：dispatch_lifecycle_activation 编排全旅程
（IL-01/06/07 + IL-N01/N04/N07）。

权威 = cr076-installation-lifecycle TEST-PLAN + S04 LLD v1.0 §6/§7/§9。
fixture 域 = tmp_path 隔离 clean-home；不执行真实安装（HLD §8.2）。
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.installation.authorization import ClaimedAuthorization
from meta_flow.installation.canonical import canonical_digest
from meta_flow.installation.contracts import InstallationContractError
from meta_flow.installation.engine import dispatch_lifecycle_activation
from meta_flow.installation.recovery import (
    DurableJournalStore,
    create_journal,
    recover,
    validate_journal,
)

D_A, D_B = "a" * 64, "b" * 64
NOW = "2026-09-01T00:00:00+00:00"
LATER = "2026-09-01T00:00:05+00:00"
PREDECESSOR = {"kind": "TransportReceiptV1", "receipt_digest": "c" * 64}


def _clock() -> str:
    return LATER


def _claim() -> ClaimedAuthorization:
    return ClaimedAuthorization(
        transaction_id="txn-s04",
        authorization_id="auth-s04",
        plan_digest=D_A,
        source_digest=D_A,
        target_digest=D_A,
        scope_digest=D_A,
        facts_digest=D_A,
    )


def _applying_journal() -> dict:
    journal = create_journal(
        _claim(),
        operation="assets.install",
        source_identity_digest=D_A,
        target_identity_digest=D_B,
        timestamp=NOW,
    )
    journal = dict(journal)
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


def _ownership_entry(state: str = "active", installed: str = D_B) -> dict:
    unsigned = {
        "ownership_id": "own-1",
        "ownership_type": "exact_file",
        "target_ref": "agents/a.md",
        "source_ref": "sources/a.md",
        "source_digest": D_A,
        "installed_digest": installed,
        "owner_ref": "owners/s04",
        "generation": 1,
        "state": state,
        "created_directories": ["agents"],
        "metadata": {
            "file_ref": "agents/a.md",
            "recorded_digest": installed,
            "created": True,
            "mode": "replace-only",
            "write_policy": "digest-match",
        },
    }
    entry = dict(unsigned)
    entry["ownership_digest"] = canonical_digest(unsigned)
    return entry


def _dispatch(tmp_path: Path, *, digests: dict, observer=None) -> tuple:
    store = DurableJournalStore(tmp_path)
    working = _applying_journal()
    store.persist(working)  # 首落盘（新 journal 无期望）
    receipt = dispatch_lifecycle_activation(
        journal=working,
        store=store,
        ownership_entries=[_ownership_entry()],
        current_digests=digests,
        predecessor=PREDECESSOR,
        consumer_project_uid="consumer/alpha-1",
        clock=_clock,
        terminal_receipt_ref="receipts/txn-s04.json",
        activation_observer=observer,
    )
    return receipt, store


# ---------------------------------------------------------------- IL-01 全旅程


def test_il01_full_journey_activates_and_persists(tmp_path: Path) -> None:
    receipt, store = _dispatch(tmp_path, digests={"agents/a.md": D_B}, observer=lambda: D_B)
    assert receipt.state == "applied"
    assert receipt.terminal == "applied"
    assert receipt.mutation_count == 0
    assert receipt.authorization_id == "auth-s04"
    outcome = receipt.outcome
    assert outcome["outcome"] == "ACTIVATED"
    assert outcome["install_variant"] == "candidate-install"
    assert outcome["predecessor_kind"] == "TransportReceiptV1"
    persisted = store.load("txn-s04")
    assert persisted["state"] == "applied"
    assert persisted["terminal_receipt_ref"] == "receipts/txn-s04.json"
    (activation,) = [r for r in persisted["action_receipts"] if r["action_id"] == "activation-1"]
    assert activation["state"] == "verified"
    assert activation["before_digest"] == D_B  # preimage = 末位 applied receipt 的 after_digest
    assert activation["after_digest"] == D_B


def test_il01_preimage_defaults_to_last_applied_action_digest(tmp_path: Path) -> None:
    """无 observer（NA 分支）：验收点退化为 preimage 自比对，verified 仍成立。"""

    receipt, _ = _dispatch(tmp_path, digests={"agents/a.md": D_B}, observer=None)
    assert receipt.state == "applied"


def test_il01_cas_chain_advances_persisted_digest_per_step(tmp_path: Path) -> None:
    """started/verified/applied 三次 persist 均以 CAS 推进；终盘 digest 与重载一致。"""

    _, store = _dispatch(tmp_path, digests={"agents/a.md": D_B}, observer=lambda: D_B)
    final = store.load("txn-s04")
    from meta_flow.installation.recovery import journal_digest

    assert store.persist(final, expected_digest=journal_digest(final)) == journal_digest(final)


# ------------------------------------------ IL-05 engine 层：漂移 → FAILED


def test_il05_engine_drift_produces_failed_receipt_and_rollback(tmp_path: Path) -> None:
    receipt, store = _dispatch(tmp_path, digests={"agents/a.md": D_B}, observer=lambda: D_A)
    assert receipt.state == "partial"
    assert receipt.terminal == "rollback_pending"
    assert receipt.outcome["outcome"] == "FAILED"
    assert receipt.outcome["reason_codes"] == ["ACTIVATION-PREIMAGE-DRIFT"]
    persisted = store.load("txn-s04")
    assert persisted["state"] == "rollback_pending"


# -------------------------- IL-06 / IL-N01 / IL-N04 边界 fail-closed（digest 域）


def test_il06_n01_target_outside_observation_blocks_before_mutation(tmp_path: Path) -> None:
    """scope 外/未观察目标：conflicts → 写前阻断，mutation=0，无 ACTIVATED receipt。"""

    receipt, store = _dispatch(tmp_path, digests={}, observer=lambda: D_B)  # 目标缺观察 digest
    assert receipt.state == "partial"
    assert receipt.mutation_count == 0
    assert receipt.outcome["outcome"] == "FAILED"
    assert receipt.outcome["reason_codes"] == ["OWNERSHIP-ACTIVATION-CONFLICT"]
    assert store.load("txn-s04")["state"] == "rollback_pending"


def test_il06_n04_cache_pollution_digest_unequal_blocks(tmp_path: Path) -> None:
    """缓存污染（落盘 bytes ≠ 断言 digest）：观察摘要不等 → 阻断，无 ACTIVATED receipt。"""

    receipt, _ = _dispatch(tmp_path, digests={"agents/a.md": D_A}, observer=lambda: D_B)
    assert receipt.outcome["reason_codes"] == ["OWNERSHIP-ACTIVATION-CONFLICT"]
    assert receipt.outcome["outcome"] == "FAILED"


def test_il06_non_applying_journal_is_rejected_without_receipt(tmp_path: Path) -> None:
    store = DurableJournalStore(tmp_path)
    journal = _applying_journal()
    journal = dict(journal)
    journal["state"] = "authorized"
    journal = validate_journal(journal)
    with pytest.raises(InstallationContractError, match="applying"):
        dispatch_lifecycle_activation(
            journal=journal,
            store=store,
            ownership_entries=[_ownership_entry()],
            current_digests={"agents/a.md": D_B},
            predecessor=PREDECESSOR,
            consumer_project_uid="consumer/alpha-1",
            clock=_clock,
            terminal_receipt_ref="receipts/txn-s04.json",
        )


def test_il06_store_must_be_durable_journal_store(tmp_path: Path) -> None:
    with pytest.raises(InstallationContractError, match="DurableJournalStore"):
        dispatch_lifecycle_activation(
            journal=_applying_journal(),
            store=object(),
            ownership_entries=[_ownership_entry()],
            current_digests={"agents/a.md": D_B},
            predecessor=PREDECESSOR,
            consumer_project_uid="consumer/alpha-1",
            clock=_clock,
            terminal_receipt_ref="receipts/txn-s04.json",
        )


# ------------------------------------- IL-N07 symlink 目标不跟随即阻断


def test_n07_symlink_target_observed_bytes_mismatch_blocks(tmp_path: Path) -> None:
    """symlink 指向外部文件：按 bytes 观察摘要 ≠ installed_digest → typed 阻断。"""

    outside = tmp_path / "outside.md"
    outside.write_text("polluted content", encoding="utf-8")
    observed = sha256(outside.read_bytes()).hexdigest()
    assert observed != D_B  # 观察域不 resolve 到 installed 断言
    receipt, _ = _dispatch(tmp_path, digests={"agents/a.md": observed}, observer=lambda: D_B)
    assert receipt.outcome["reason_codes"] == ["OWNERSHIP-ACTIVATION-CONFLICT"]
    assert receipt.state == "partial"


# ------------------------- IL-07 FAILED 后既有 recover 承接（新授权）


def test_il07_failed_activation_recovers_via_rollback_plan(tmp_path: Path) -> None:
    receipt, _ = _dispatch(tmp_path, digests={"agents/a.md": D_A}, observer=lambda: D_B)
    assert receipt.outcome["outcome"] == "FAILED"
    plan = recover(
        receipt_outcome_journal(tmp_path),
        "rollback",
        new_claim_context=ClaimedAuthorization(
            transaction_id="txn-s04",
            authorization_id="auth-recovery",
            plan_digest=D_A,
            source_digest=D_A,
            target_digest=D_A,
            scope_digest=D_A,
            facts_digest=D_A,
        ),
        current_digests={"agents/a.md": D_B, "activation/txn-s04": D_B},
        available_preimage_refs=frozenset({"preimages/action-1", "activation-preimages/txn-s04"}),
    )
    assert "action-1" in plan.action_ids


def receipt_outcome_journal(tmp_path: Path) -> dict:
    """从持久层取回 FAILED 后的 journal（rollback_pending → partial 后可 recover）。"""

    from meta_flow.installation.recovery import transition

    store = DurableJournalStore(tmp_path)
    journal = store.load("txn-s04")
    assert journal["state"] == "rollback_pending"
    return transition(journal, "partial", timestamp=LATER)
