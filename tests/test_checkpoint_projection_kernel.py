from __future__ import annotations

from typing import Any

import pytest

from meta_flow.state import checkpoint_projection


def _result(
    *,
    cr_id: str = "CR-063",
    checkpoint: str = "CP5",
    decision: str = "PASS",
    story_id: str = "",
    revision: int | None = None,
    supersedes_ref: str = "",
    event_id: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "cr_id": cr_id,
        "checkpoint": checkpoint,
        "decision": decision,
        "items": [],
        "blockers": [],
        "waivers": [],
    }
    if story_id:
        payload["story_id"] = story_id
    if revision is not None:
        payload["revision"] = revision
    if supersedes_ref:
        payload["supersedes_ref"] = supersedes_ref
    if event_id:
        payload["event_id"] = event_id
    return payload


def _event(
    event_id: str,
    result_ref: str,
    *,
    cr_id: str = "CR-063",
    checkpoint: str = "CP5",
    decision: str = "PASS",
    story_id: str = "",
    supersedes_event_id: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_id": event_id,
        "event_type": "checkpoint_result",
        "cr_id": cr_id,
        "checkpoint": checkpoint,
        "decision": decision,
        "result_ref": result_ref,
    }
    if story_id:
        payload["story_id"] = story_id
    if supersedes_event_id:
        payload["supersedes_event_id"] = supersedes_event_id
    return payload


def _alias(
    event_id: str,
    alias_ref: str,
    canonical_ref: str,
    corrects_event_id: str,
    *,
    cr_id: str = "CR-063",
    checkpoint: str = "CP5",
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": "checkpoint_result_alias_correction",
        "cr_id": cr_id,
        "checkpoint": checkpoint,
        "decision": "PASS",
        "result_ref": alias_ref,
        "canonical_result_ref": canonical_ref,
        "corrects_event_id": corrects_event_id,
    }


def _project(
    events: list[dict[str, Any]],
    results: dict[str, dict[str, Any]],
    *,
    cr_id: str = "CR-063",
    checkpoint: str = "CP5",
) -> checkpoint_projection.CheckpointProjectionV1:
    return checkpoint_projection.project_checkpoint_events(
        events,
        results,
        cr_id=cr_id,
        checkpoint=checkpoint,
    )


def test_graph_01_single_legacy_result() -> None:
    ref = "process/checks/CP5-CR-063.result.json"
    projection = _project([_event("event-v1", ref)], {ref: _result()})

    assert projection.decision == "PASS"
    assert projection.head("CP5").result_ref == ref
    assert projection.head("CP5").selection_mode == "explicit_graph"


def test_legacy_ledger_order_compatibility_chooses_latest_same_subject() -> None:
    old_ref = "process/checks/CP5-CR-063-old.result.json"
    current_ref = "process/checks/CP5-CR-063-revalidation.result.json"
    projection = _project(
        [
            _event("legacy-old", old_ref),
            _event("legacy-revalidation", current_ref),
        ],
        {
            old_ref: _result(decision="BLOCKED"),
            current_ref: _result(),
        },
    )

    head = projection.head("CP5")
    assert projection.decision == "PASS"
    assert head.result_ref == current_ref
    assert head.selection_mode == "legacy_ledger_order"
    assert head.provenance_event_ids == ("legacy-old", "legacy-revalidation")


def test_unlinked_explicit_revisions_do_not_use_legacy_order() -> None:
    first_ref = "process/checks/CP5-CR-063-explicit-v1a.result.json"
    second_ref = "process/checks/CP5-CR-063-explicit-v1b.result.json"
    projection = _project(
        [_event("explicit-v1a", first_ref), _event("explicit-v1b", second_ref)],
        {
            first_ref: _result(revision=1),
            second_ref: _result(revision=1),
        },
    )

    assert projection.decision == "BLOCKED"
    assert "CURRENT_HEAD_NOT_UNIQUE" in {finding.code for finding in projection.findings}


def test_graph_02_legal_result_successor_chain() -> None:
    v1 = "process/checks/CP5-CR-063-v1.result.json"
    v2 = "process/checks/CP5-CR-063-v2.result.json"
    v3 = "process/checks/CP5-CR-063-v3.result.json"
    projection = _project(
        [_event("event-v1", v1), _event("event-v2", v2), _event("event-v3", v3)],
        {
            v1: _result(decision="BLOCKED"),
            v2: _result(revision=2, supersedes_ref=v1, event_id="event-v2"),
            v3: _result(revision=3, supersedes_ref=v2, event_id="event-v3"),
        },
    )

    assert projection.decision == "PASS"
    assert projection.head("CP5").result_ref == v3
    assert projection.head("CP5").revision == 3


def test_graph_03_legal_alias_correction() -> None:
    alias_ref = "process/checks/CP5-CR-063-alias.result.json"
    canonical_ref = "process/checks/CP5-CR-063-canonical.result.json"
    projection = _project(
        [
            _event("alias-event", alias_ref),
            _event("canonical-event", canonical_ref),
            _alias(
                "alias-correction",
                alias_ref,
                canonical_ref,
                "alias-event",
            ),
        ],
        {canonical_ref: _result()},
    )

    assert projection.decision == "PASS"
    assert projection.head("CP5").result_ref == canonical_ref


def test_graph_04_superseded_old_file_may_be_missing() -> None:
    old_ref = "process/checks/CP5-CR-063-old.result.json"
    current_ref = "process/checks/CP5-CR-063-current.result.json"
    projection = _project(
        [
            _event("event-old", old_ref, decision="BLOCKED"),
            _event(
                "event-current",
                current_ref,
                supersedes_event_id="event-old",
            ),
        ],
        {current_ref: _result()},
    )

    assert projection.decision == "PASS"
    assert projection.head("CP5").result_ref == current_ref


def test_graph_05_alias_source_may_be_missing_when_canonical_target_exists() -> None:
    alias_ref = "process/checks/CP5-CR-063-legacy-alias.result.json"
    current_ref = "process/checks/CP5-CR-063-current.result.json"
    events = [
        _event("event-alias", alias_ref),
        _event("event-current", current_ref),
        _alias("correction", alias_ref, current_ref, "event-alias"),
    ]
    required_refs, findings = checkpoint_projection.required_result_refs(
        events,
        cr_id="CR-063",
        checkpoint="CP5",
    )
    projection = _project(events, {current_ref: _result()})

    assert not findings
    assert required_refs == (current_ref,)
    assert projection.decision == "PASS"


@pytest.mark.parametrize(
    "unrelated_events",
    [
        [
            _event(
                "cr-other-missing",
                "process/checks/CP5-CR-999-missing.result.json",
                cr_id="CR-999",
            )
        ],
        [
            _event(
                "cr-other-alias",
                "process/checks/CP5-CR-999-alias.result.json",
                cr_id="CR-999",
            ),
            _alias(
                "cr-other-invalid-correction",
                "process/checks/CP5-CR-999-alias.result.json",
                "process/checks/CP5-CR-999-other.result.json",
                "missing-event",
                cr_id="CR-999",
            ),
        ],
    ],
)
def test_graph_06_07_unrelated_cr_cannot_contaminate_target(
    unrelated_events: list[dict[str, Any]],
) -> None:
    target_ref = "process/checks/CP5-CR-063.result.json"
    projection = _project(
        [_event("target", target_ref), *unrelated_events],
        {target_ref: _result()},
    )

    assert projection.decision == "PASS"
    assert projection.selected_event_count == 1


def test_graph_08_current_canonical_head_missing_blocks() -> None:
    ref = "process/checks/CP5-CR-063-missing.result.json"
    projection = _project([_event("missing", ref)], {})

    assert projection.decision == "BLOCKED"
    assert {finding.code for finding in projection.findings} == {"RESULT_FILE_MISSING"}


def test_graph_09_same_checkpoint_name_isolated_by_cr() -> None:
    target_ref = "process/checks/CP5-CR-063.result.json"
    other_ref = "process/checks/CP5-CR-999.result.json"
    projection = _project(
        [
            _event("target", target_ref),
            _event("other", other_ref, cr_id="CR-999"),
        ],
        {
            target_ref: _result(),
            other_ref: _result(cr_id="CR-999"),
        },
    )

    assert projection.decision == "PASS"
    assert [head.result_ref for head in projection.heads] == [target_ref]


def test_graph_10_successor_fork_blocks() -> None:
    v1 = "process/checks/CP5-CR-063-v1.result.json"
    v2a = "process/checks/CP5-CR-063-v2a.result.json"
    v2b = "process/checks/CP5-CR-063-v2b.result.json"
    projection = _project(
        [_event("v1", v1), _event("v2a", v2a), _event("v2b", v2b)],
        {
            v1: _result(),
            v2a: _result(revision=2, supersedes_ref=v1),
            v2b: _result(revision=2, supersedes_ref=v1),
        },
    )

    assert projection.decision == "BLOCKED"
    assert "RESULT_SUCCESSOR_FORK" in {finding.code for finding in projection.findings}


def test_graph_11_successor_cycle_blocks() -> None:
    v2 = "process/checks/CP5-CR-063-v2.result.json"
    v3 = "process/checks/CP5-CR-063-v3.result.json"
    projection = _project(
        [_event("v2", v2), _event("v3", v3)],
        {
            v2: _result(revision=2, supersedes_ref=v3),
            v3: _result(revision=3, supersedes_ref=v2),
        },
    )

    assert projection.decision == "BLOCKED"
    assert "RESULT_SUCCESSOR_CYCLE" in {finding.code for finding in projection.findings}


@pytest.mark.parametrize("mode", ["duplicate-event", "identity-mismatch"])
def test_graph_12_duplicate_event_or_result_identity_mismatch_blocks(
    mode: str,
) -> None:
    ref = "process/checks/CP5-CR-063.result.json"
    events = [_event("event", ref)]
    result = _result()
    if mode == "duplicate-event":
        events.append(_event("event", ref))
    else:
        result["checkpoint"] = "CP3"

    projection = _project(events, {ref: result})

    assert projection.decision == "BLOCKED"
    assert {finding.code for finding in projection.findings} & {
        "DUPLICATE_EVENT_ID",
        "RESULT_EVENT_IDENTITY_MISMATCH",
    }


def test_c0_event_level_supersedes_chain_has_one_head() -> None:
    ref = "process/checks/C0-CR-063-PROJECTOR-CUTOVER.result.json"
    events = [
        _event("c0-v1", ref, checkpoint="C0"),
        _event(
            "c0-v2",
            ref,
            checkpoint="C0",
            supersedes_event_id="c0-v1",
        ),
        _event(
            "c0-v3",
            ref,
            checkpoint="C0",
            supersedes_event_id="c0-v2",
        ),
    ]
    projection = _project(
        events,
        {ref: _result(checkpoint="C0")},
        checkpoint="C0",
    )

    assert projection.decision == "PASS"
    assert projection.head("C0").event_id == "c0-v3"
