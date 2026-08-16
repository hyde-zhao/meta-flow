from meta_flow.work.validation_kernel import (
    PRECEDENCE,
    DecisionStatus,
    RuleDomainV1,
    capture_validation_snapshot,
    compare_shadow_graph,
    decision_from_graph,
    evaluate_work,
)


def snapshot(*, dirty_owned: bool = True):
    return capture_validation_snapshot("init-preflight", {"release_oid": "a" * 40, "process_oid": "b" * 40, "dirty_owned": dirty_owned})


def test_five_domains_fixed_order_and_single_authority() -> None:
    graph = evaluate_work(snapshot())
    assert tuple(item.domain for item in graph.items) == PRECEDENCE
    assert graph.decision is DecisionStatus.PASS
    assert graph.authoritative_decision_path_count == 1
    assert graph.duplicate_rule_owner_count == 0


def test_fail_closed_dirty_unowned_and_zero_write_decision() -> None:
    graph = evaluate_work(snapshot(dirty_owned=False))
    assert graph.decision is DecisionStatus.BLOCKED
    assert decision_from_graph(graph).mutation_count == 0


def test_invalid_rule_set_fails_closed() -> None:
    graph = evaluate_work(snapshot(), (RuleDomainV1.IDENTITY_CONTRACTS,))
    assert graph.decision is DecisionStatus.FAIL


def test_same_snapshot_is_deterministic_and_shadow_cannot_authorize() -> None:
    left = evaluate_work(snapshot())
    right = evaluate_work(snapshot())
    assert left.graph_digest == right.graph_digest
    assert compare_shadow_graph(left, right).cutover_eligible
    blocked = evaluate_work(snapshot(dirty_owned=False))
    assert not compare_shadow_graph(left, blocked).cutover_eligible
