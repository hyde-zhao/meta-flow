from __future__ import annotations

from meta_flow.work.decision_bundle import (
    build_retry_revalidation_receipt,
    execute_subgate_result,
    subgate_idempotency_key,
    validate_bundle,
)


def _bundle() -> dict:
    ids = ["B2", "B3", "B4"]
    return {
        "bundle_id": "CR056-STAGE-B",
        "revision": 1,
        "work_id": "CR-056",
        "authorization_snapshot": {
            "authorization_id": "AUTH-1",
            "authorized_by": "user",
            "authorized_at": "2026-07-21T00:00:00Z",
            "exact_subgate_ids": ids,
            "excluded_actions": ["commit", "push"],
            "expiry_or_revalidation_rule": "facts-scope-or-authz-drift",
        },
        "expected_facts": {
            "release_oid": "a" * 40,
            "process_oid": "b" * 40,
            "branch": "cr/cr-056-native-cr-governance",
            "dirty_path_digest": "c" * 64,
        },
        "scope_digest": "d" * 64,
        "subgates": [
            {
                "id": subgate_id,
                "order": offset,
                "action": f"run {subgate_id}",
                "preconditions": [],
                "authorization_required": True,
                "evidence_refs": [],
                "result": "authorized",
            }
            for offset, subgate_id in enumerate(ids, 1)
        ],
        "stop_policy": {"stop_results": ["failed", "blocked"]},
        "created_at": "2026-07-21T00:00:00Z",
    }


def test_bundle_requires_exact_authorized_subgate_set() -> None:
    bundle = _bundle()
    bundle["authorization_snapshot"]["exact_subgate_ids"] = ["B2", "B3"]

    assert {finding.code for finding in validate_bundle(bundle)} == {"authorization_scope"}


def test_subgate_failure_stops_every_later_subgate() -> None:
    bundle = _bundle()

    bundle, _events = execute_subgate_result(
        bundle,
        subgate_id="B2",
        result="passed",
        attempt=1,
        observed_at="2026-07-21T01:00:00Z",
        evidence_refs=["works/CR-056/IMPLEMENTATION.md#B2"],
    )
    bundle, events = execute_subgate_result(
        bundle,
        subgate_id="B3",
        result="failed",
        attempt=1,
        observed_at="2026-07-21T01:10:00Z",
    )

    assert [item["result"] for item in bundle["subgates"]] == [
        "passed",
        "failed",
        "not-started-by-stop-propagation",
    ]
    assert [event["event_type"] for event in events] == [
        "subgate_failed",
        "subgate_skipped_by_stop",
    ]


def test_same_terminal_result_is_idempotent_and_identity_is_revision_scoped() -> None:
    bundle, first = execute_subgate_result(
        _bundle(),
        subgate_id="B2",
        result="passed",
        attempt=1,
        observed_at="2026-07-21T01:00:00Z",
    )
    bundle, second = execute_subgate_result(
        bundle,
        subgate_id="B2",
        result="passed",
        attempt=1,
        observed_at="2026-07-21T01:00:00Z",
    )

    assert first and second == []
    assert subgate_idempotency_key("B", 1, "B2", 1) != subgate_idempotency_key("B", 2, "B2", 1)


def test_failed_subgate_can_retry_same_revision_with_attempt_plus_one() -> None:
    bundle, _events = execute_subgate_result(
        _bundle(),
        subgate_id="B2",
        result="failed",
        attempt=1,
        observed_at="2026-07-21T01:00:00Z",
    )
    receipt = build_retry_revalidation_receipt(
        bundle,
        subgate_id="B2",
        reviewed_attempt=1,
        approved_attempt=2,
        reviewed_at="2026-07-21T01:05:00Z",
    )

    bundle, events = execute_subgate_result(
        bundle,
        subgate_id="B2",
        result="passed",
        attempt=2,
        observed_at="2026-07-21T01:10:00Z",
        evidence_refs=["works/CR-056/VERIFICATION.md#retry"],
        retry_revalidation=receipt,
    )

    assert [item["result"] for item in bundle["subgates"]] == [
        "passed",
        "authorized",
        "authorized",
    ]
    assert [event["event_type"] for event in events] == [
        "subgate_retry_authorized",
        "subgate_passed",
        "subgate_reauthorized_after_retry",
        "subgate_reauthorized_after_retry",
    ]
    _same, transport_retry_events = execute_subgate_result(
        bundle,
        subgate_id="B2",
        result="passed",
        attempt=2,
        observed_at="2026-07-21T01:10:00Z",
    )
    assert transport_retry_events == []


def test_same_revision_execution_retry_requires_unchanged_facts_scope_and_authz() -> None:
    bundle, _events = execute_subgate_result(
        _bundle(),
        subgate_id="B2",
        result="blocked",
        attempt=1,
        observed_at="2026-07-21T01:00:00Z",
    )
    receipt = build_retry_revalidation_receipt(
        bundle,
        subgate_id="B2",
        reviewed_attempt=1,
        approved_attempt=2,
        reviewed_at="2026-07-21T01:05:00Z",
    )
    bundle["expected_facts"]["release_oid"] = "e" * 40

    try:
        execute_subgate_result(
            bundle,
            subgate_id="B2",
            result="passed",
            attempt=2,
            observed_at="2026-07-21T01:10:00Z",
            retry_revalidation=receipt,
        )
    except ValueError as error:
        assert "expected_facts" in str(error)
    else:
        raise AssertionError("facts drift must reject same-revision execution retry")


def test_same_revision_execution_retry_rejects_missing_receipt_and_attempt_gap() -> None:
    bundle, _events = execute_subgate_result(
        _bundle(),
        subgate_id="B2",
        result="failed",
        attempt=1,
        observed_at="2026-07-21T01:00:00Z",
    )

    for attempt, expected in ((2, "revalidation receipt"), (3, "attempt 2")):
        try:
            execute_subgate_result(
                bundle,
                subgate_id="B2",
                result="passed",
                attempt=attempt,
                observed_at="2026-07-21T01:10:00Z",
            )
        except ValueError as error:
            assert expected in str(error)
        else:
            raise AssertionError("invalid execution retry must be rejected")
