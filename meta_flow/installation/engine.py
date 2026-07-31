"""S04 lifecycle authorization checkpoint handoff surface.

恢复与真实 target mutation 不属于本模块；executor 只能通过已 claim context
被调用，S07 将在其串行范围内消费本模块产生的 receipt/outcome。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from meta_flow.installation.authorization import AuthorizationClaims, ClaimedAuthorization
from meta_flow.installation.contracts import (
    ContractErrorCode,
    InstallationContractError,
    validate_plan,
)
from meta_flow.installation.planner import CheckpointComparison, compare_checkpoints

JournalWriter = Callable[[ClaimedAuthorization, str, Mapping[str, object]], None]
CheckpointObserver = Callable[[], Mapping[str, object]]


@dataclass(frozen=True)
class ExecutionOutcome:
    """executor 返回的精确 mutation 事实，不由 engine 猜测。"""

    mutation_count: int
    value: object | None


Executor = Callable[[ClaimedAuthorization], ExecutionOutcome]
DurableActionExecutor = Callable[
    [ClaimedAuthorization, Mapping[str, Any]],
    object,
]
PreimageProvider = Callable[[Mapping[str, Any]], tuple[str, str]]
TimestampProvider = Callable[[], str]


@dataclass(frozen=True)
class ExecutionReceipt:
    """S04 交给 S07 的最小可审计 terminal / handoff 结果。"""

    transaction_id: str
    authorization_id: str
    state: str
    terminal: str
    mutation_count: int
    comparisons: tuple[CheckpointComparison, ...]
    outcome: object | None
    retry_count: int = 0


def dispatch_authorized(
    *,
    plan: Mapping[str, Any],
    authorization: object,
    expected_checkpoints: Mapping[str, object],
    observed_checkpoints: Mapping[str, object] | CheckpointObserver,
    claims: AuthorizationClaims,
    executor: Executor,
    journal: JournalWriter | None = None,
) -> ExecutionReceipt:
    """执行 S04 固定顺序，任何 claim 前失败都不会调用 executor。

    顺序固定为：validate plan → C1/C2 → atomic claim → journal context → C3
    → executor → C4。semantic/ownership failure 没有 retry loop。
    """

    validate_plan(plan)
    if plan["decision"] != "READY":
        raise InstallationContractError(ContractErrorCode.IDENTITY_CONFLICT, "only READY plan may dispatch")

    preclaim = compare_checkpoints(
        expected_checkpoints,
        _observe_checkpoints(observed_checkpoints),
        checkpoints=("C1", "C2"),
    )
    if not _all_matched(preclaim):
        raise InstallationContractError(ContractErrorCode.IDENTITY_CONFLICT, "C1/C2 checkpoint drift blocks claim")

    context = claims.claim_once(authorization, plan=plan)
    all_comparisons: tuple[CheckpointComparison, ...] = preclaim
    try:
        if journal is not None:
            journal(context, "authorized", {"checkpoint": "C2"})
        c3 = compare_checkpoints(
            expected_checkpoints,
            _observe_checkpoints(observed_checkpoints),
            checkpoints=("C3",),
        )
        all_comparisons += c3
        if not _all_matched(c3):
            return _consumed_no_mutation(context, all_comparisons, journal, "checkpoint-drift")
    except Exception as exc:
        return _consumed_no_mutation(context, all_comparisons, journal, f"pre-mutation-failure:{type(exc).__name__}")

    outcome = executor(context)
    c4 = compare_checkpoints(
        expected_checkpoints,
        _observe_checkpoints(observed_checkpoints),
        checkpoints=("C4",),
    )
    all_comparisons += c4
    if not _all_matched(c4):
        receipt = ExecutionReceipt(
            transaction_id=context.transaction_id,
            authorization_id=context.authorization_id,
            state="partial",
            terminal="rollback_pending",
            mutation_count=outcome.mutation_count,
            comparisons=all_comparisons,
            outcome=outcome.value,
        )
        _journal_terminal(journal, context, receipt)
        return receipt

    receipt = ExecutionReceipt(
        transaction_id=context.transaction_id,
        authorization_id=context.authorization_id,
        state="applied",
        terminal="applied",
        mutation_count=outcome.mutation_count,
        comparisons=all_comparisons,
        outcome=outcome.value,
    )
    _journal_terminal(journal, context, receipt)
    return receipt


def dispatch_authorized_actions(
    *,
    plan: Mapping[str, Any],
    authorization: object,
    expected_checkpoints: Mapping[str, object],
    observed_checkpoints: Mapping[str, object] | CheckpointObserver,
    claims: AuthorizationClaims,
    action_executor: DurableActionExecutor,
    preimage_provider: PreimageProvider,
    journal_store: object,
    terminal_receipt_ref: str,
    clock: TimestampProvider,
) -> ExecutionReceipt:
    """按 action-before-write journal 契约执行 canonical action 序列。

    该入口不生成 plan 或授权。每个 action 的 durable planned receipt 成功
    CAS 后才调用 executor；任何写后失败保留真实 journal 状态。
    """

    from meta_flow.installation.canonical import canonical_digest
    from meta_flow.installation.recovery import (
        DurableJournalStore,
        create_journal,
        finalize_journal,
        record_action_outcome,
        record_action_started,
        transition,
    )

    if not isinstance(journal_store, DurableJournalStore):
        raise InstallationContractError(
            ContractErrorCode.NONCANONICAL_VALUE,
            "dispatch requires one DurableJournalStore",
        )
    validate_plan(plan)
    if plan["decision"] != "READY":
        raise InstallationContractError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "only READY plan may dispatch",
        )
    preclaim = compare_checkpoints(
        expected_checkpoints,
        _observe_checkpoints(observed_checkpoints),
        checkpoints=("C1", "C2"),
    )
    if not _all_matched(preclaim):
        raise InstallationContractError(
            ContractErrorCode.IDENTITY_CONFLICT,
            "C1/C2 checkpoint drift blocks claim",
        )

    context = claims.claim_once(authorization, plan=plan)
    timestamp = clock()
    journal = create_journal(
        context,
        operation=str(plan["operation"]),
        source_identity_digest=canonical_digest(plan["source_identity"]),
        target_identity_digest=canonical_digest(plan["target_identity"]),
        timestamp=timestamp,
    )
    try:
        persisted_digest = journal_store.persist(journal)
    except Exception as exc:
        return _consumed_no_mutation(
            context,
            preclaim,
            None,
            f"journal-create-failure:{type(exc).__name__}",
        )

    comparisons = preclaim
    c3 = compare_checkpoints(
        expected_checkpoints,
        _observe_checkpoints(observed_checkpoints),
        checkpoints=("C3",),
    )
    comparisons += c3
    if not _all_matched(c3):
        blocked = finalize_journal(
            journal,
            terminal_state="blocked",
            terminal_receipt_ref=terminal_receipt_ref,
            timestamp=clock(),
        )
        journal_store.persist(blocked, expected_digest=persisted_digest)
        return ExecutionReceipt(
            transaction_id=context.transaction_id,
            authorization_id=context.authorization_id,
            state="blocked",
            terminal="consumed_no_mutation",
            mutation_count=0,
            comparisons=comparisons,
            outcome="checkpoint-drift",
        )

    total_mutations = 0
    outcomes: list[object] = []
    for action in plan["actions"]:
        try:
            preimage_ref, before_digest = preimage_provider(action)
            started = record_action_started(
                journal,
                action,
                preimage_ref=preimage_ref,
                before_digest=before_digest,
                timestamp=clock(),
            )
            persisted_digest = journal_store.persist(
                started,
                expected_digest=persisted_digest,
            )
            journal = started
        except Exception as exc:
            failed = _journal_failure_state(journal, timestamp=clock())
            journal_store.persist(failed, expected_digest=persisted_digest)
            return ExecutionReceipt(
                transaction_id=context.transaction_id,
                authorization_id=context.authorization_id,
                state=failed["state"],
                terminal="consumed_no_mutation"
                if total_mutations == 0
                else "partial",
                mutation_count=total_mutations,
                comparisons=comparisons,
                outcome=f"preimage-failure:{type(exc).__name__}",
            )

        try:
            outcome = action_executor(context, action)
        except Exception as exc:
            journal = record_action_outcome(
                journal,
                action_id=str(action["action_id"]),
                after_digest="",
                error_code=f"EXECUTOR_EXCEPTION_{type(exc).__name__.upper()}",
                timestamp=clock(),
            )
            persisted_digest = journal_store.persist(
                journal,
                expected_digest=persisted_digest,
            )
            partial = finalize_journal(
                journal,
                terminal_state="partial",
                terminal_receipt_ref=terminal_receipt_ref,
                timestamp=clock(),
            )
            journal_store.persist(partial, expected_digest=persisted_digest)
            return ExecutionReceipt(
                transaction_id=context.transaction_id,
                authorization_id=context.authorization_id,
                state="partial",
                terminal="partial",
                mutation_count=total_mutations,
                comparisons=comparisons,
                outcome=f"executor-exception:{type(exc).__name__}",
            )
        after_digest = _outcome_field(outcome, "after_digest", "")
        error_code = _outcome_field(outcome, "error_code", "")
        mutation_count = _outcome_field(outcome, "mutation_count", 0)
        outcome_state = _outcome_field(outcome, "state", "applied")
        if not isinstance(after_digest, str) or not isinstance(error_code, str):
            raise InstallationContractError(
                ContractErrorCode.NONCANONICAL_VALUE,
                "action outcome digest/error must be strings",
            )
        if (
            not isinstance(mutation_count, int)
            or isinstance(mutation_count, bool)
            or mutation_count < 0
        ):
            raise InstallationContractError(
                ContractErrorCode.NONCANONICAL_VALUE,
                "action outcome mutation_count must be non-negative",
            )
        journal = record_action_outcome(
            journal,
            action_id=str(action["action_id"]),
            after_digest=after_digest,
            error_code=error_code,
            timestamp=clock(),
        )
        persisted_digest = journal_store.persist(
            journal,
            expected_digest=persisted_digest,
        )
        total_mutations += mutation_count
        outcomes.append(outcome)
        if error_code or outcome_state != "applied":
            partial = finalize_journal(
                journal,
                terminal_state="partial",
                terminal_receipt_ref=terminal_receipt_ref,
                timestamp=clock(),
            )
            journal_store.persist(partial, expected_digest=persisted_digest)
            return ExecutionReceipt(
                transaction_id=context.transaction_id,
                authorization_id=context.authorization_id,
                state="partial",
                terminal="partial",
                mutation_count=total_mutations,
                comparisons=comparisons,
                outcome=tuple(outcomes),
            )

    c4 = compare_checkpoints(
        expected_checkpoints,
        _observe_checkpoints(observed_checkpoints),
        checkpoints=("C4",),
    )
    comparisons += c4
    if not _all_matched(c4):
        rollback_pending = transition(
            journal,
            "rollback_pending",
            timestamp=clock(),
        )
        journal_store.persist(
            rollback_pending,
            expected_digest=persisted_digest,
        )
        return ExecutionReceipt(
            transaction_id=context.transaction_id,
            authorization_id=context.authorization_id,
            state="partial",
            terminal="rollback_pending",
            mutation_count=total_mutations,
            comparisons=comparisons,
            outcome=tuple(outcomes),
        )

    applied = finalize_journal(
        journal,
        terminal_state="applied",
        terminal_receipt_ref=terminal_receipt_ref,
        timestamp=clock(),
    )
    journal_store.persist(applied, expected_digest=persisted_digest)
    return ExecutionReceipt(
        transaction_id=context.transaction_id,
        authorization_id=context.authorization_id,
        state="applied",
        terminal="applied",
        mutation_count=total_mutations,
        comparisons=comparisons,
        outcome=tuple(outcomes),
    )


def _consumed_no_mutation(
    context: ClaimedAuthorization,
    comparisons: tuple[CheckpointComparison, ...],
    journal: JournalWriter | None,
    reason: str,
) -> ExecutionReceipt:
    receipt = ExecutionReceipt(
        transaction_id=context.transaction_id,
        authorization_id=context.authorization_id,
        state="blocked",
        terminal="consumed_no_mutation",
        mutation_count=0,
        comparisons=comparisons,
        outcome=reason,
    )
    _journal_terminal(journal, context, receipt)
    return receipt


def _journal_terminal(
    journal: JournalWriter | None,
    context: ClaimedAuthorization,
    receipt: ExecutionReceipt,
) -> None:
    if journal is None:
        return
    try:
        journal(
            context,
            receipt.state,
            {
                "terminal": receipt.terminal,
                "mutation_count": receipt.mutation_count,
                "retry_count": receipt.retry_count,
            },
        )
    except Exception:
        # receipt 已在内存中完整生成；S07 负责 durable journal/recovery 语义。
        return


def _all_matched(comparisons: tuple[CheckpointComparison, ...]) -> bool:
    return all(comparison.matched for comparison in comparisons)


def _observe_checkpoints(
    observed: Mapping[str, object] | CheckpointObserver,
) -> Mapping[str, object]:
    """在 C1/C2、C3、C4 边界重新取得 facts；静态 mapping 仅用于 fixture。"""

    return observed() if callable(observed) else observed


def _outcome_field(outcome: object, field: str, default: object) -> object:
    if isinstance(outcome, Mapping):
        return outcome.get(field, default)
    return getattr(outcome, field, default)


def _journal_failure_state(
    journal: Mapping[str, Any],
    *,
    timestamp: str,
) -> dict[str, Any]:
    from meta_flow.installation.recovery import transition

    next_state = "blocked" if journal["state"] == "authorized" else "partial"
    return transition(journal, next_state, timestamp=timestamp)


__all__ = [
    "ExecutionOutcome",
    "ExecutionReceipt",
    "dispatch_authorized",
    "dispatch_authorized_actions",
]
