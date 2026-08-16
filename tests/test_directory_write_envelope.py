from __future__ import annotations

import pytest

from meta_flow.work.directory_envelope import (
    DirectoryWriteEnvelopeV1,
    MatcherParseError,
    MatchReasonCode,
    ObjectClass,
    PathFactsV1,
    PlanApplyBindingV1,
    assert_plan_apply_semantics,
    match_write_envelope,
    parse_matcher_ast,
    select_fallback,
)

PATH = "meta_flow/work/directory_envelope.py"
PREIMAGE = "a" * 64


def envelope() -> DirectoryWriteEnvelopeV1:
    return DirectoryWriteEnvelopeV1(
        owner_story_id="STORY-CR071-S01", wave_id="W2", merge_order=10,
        exact_dirs=("meta_flow/work", "tests"),
        matcher=parse_matcher_ast({"op": "ANY_OF", "rules": [
            {"op": "EXACT_LEAF", "value": PATH},
            {"op": "EXACT_LEAF", "value": "tests/test_directory_write_envelope.py"},
        ]}),
        exclusions=("process", ".git"),
        fallback_exact_leaves=(PATH, "tests/test_directory_write_envelope.py"),
    )


def facts(path: str = PATH, object_class: ObjectClass = ObjectClass.REGULAR_EXISTING, **changes: object) -> PathFactsV1:
    values = dict(path=path, object_class=object_class, parent_safe=True, repository_contained=True,
                  logical_owner_count=1, expected_preimage_digest=PREIMAGE, current_preimage_digest=PREIMAGE)
    values.update(changes)
    return PathFactsV1(**values)


def binding(value: DirectoryWriteEnvelopeV1) -> PlanApplyBindingV1:
    return PlanApplyBindingV1(value.digest, value.digest, "1" * 40, "2" * 40, ((PATH, PREIMAGE),))


def decision(path: str = PATH, **kwargs: object):
    value = envelope()
    story_id = kwargs.pop("story_id", "STORY-CR071-S01")
    wave_id = kwargs.pop("wave_id", "W2")
    return match_write_envelope(value, path, story_id, wave_id, kwargs.pop("facts", facts(path)), binding(value), **kwargs)


def test_positive_exact_leaves_are_admitted_with_zero_mutations() -> None:
    assert decision().admitted
    assert decision("tests/test_directory_write_envelope.py", facts=facts("tests/test_directory_write_envelope.py", expected_preimage_digest=PREIMAGE, current_preimage_digest=PREIMAGE),).mutation_count == 0


@pytest.mark.parametrize("path", ["/tmp/x", "../x", "meta_flow//work/x", "meta_flow\\work\\x", "méta/x", "meta_flow/work/.hidden", "meta_flow/work/directory_envelope.py.bak"])
def test_path_adversaries_deny_without_mutation(path: str) -> None:
    result = decision(path, facts=facts(path))
    assert not result.admitted and result.mutation_count == 0


@pytest.mark.parametrize("object_class", [ObjectClass.SYMLINK, ObjectClass.IGNORED, ObjectClass.SUBMODULE, ObjectClass.OUTSIDE, ObjectClass.DUPLICATE_LOGICAL_OWNER, ObjectClass.MISSING_PARENT, ObjectClass.PARENT_TYPE_CONFLICT, ObjectClass.UNKNOWN])
def test_forbidden_object_classes_deny_before_matcher(object_class: ObjectClass) -> None:
    result = decision(facts=facts(object_class=object_class))
    assert result.reason_code is MatchReasonCode.OBJECT_FORBIDDEN and result.mutation_count == 0


def test_owner_wave_merge_and_preimage_guards_deny() -> None:
    assert decision(story_id="other").reason_code is MatchReasonCode.OWNER_MISMATCH
    assert decision(wave_id="W3").reason_code is MatchReasonCode.WAVE_MISMATCH
    assert decision(merge_order=20).reason_code is MatchReasonCode.MERGE_ORDER_MISMATCH
    drift = facts(current_preimage_digest="b" * 64)
    assert decision(facts=drift).reason_code is MatchReasonCode.PREIMAGE_DRIFT


def test_closed_ast_rejects_unknown_empty_duplicate_and_two_wildcards() -> None:
    bad = [
        {"op": "REGEX", "value": ".*"}, {"op": "ANY_OF", "rules": []},
        {"op": "ALL_OF", "rules": []},
        {"op": "ALL_OF", "rules": [{"op": "ASCII_BASENAME_PREFIX", "dir": "tests", "value": "test_"}, {"op": "ASCII_BASENAME_SUFFIX", "dir": "tests", "value": ".py"}]},
    ]
    for payload in bad:
        with pytest.raises(MatcherParseError):
            parse_matcher_ast(payload)


def test_any_of_keeps_wildcard_cardinality_per_branch() -> None:
    node = parse_matcher_ast({"op": "ANY_OF", "rules": [
        {"op": "ASCII_BASENAME_PREFIX", "dir": "tests", "value": "test_"},
        {"op": "ASCII_BASENAME_PREFIX", "dir": "meta_flow/work", "value": "validation_"},
    ]})
    value = DirectoryWriteEnvelopeV1("S", "W", 1, ("tests", "meta_flow/work"), node, fallback_exact_leaves=("tests/test_x.py",))
    assert value.digest == value.digest


def test_plan_apply_drift_requires_zero_write_replan() -> None:
    plan = decision()
    apply = decision()
    assert assert_plan_apply_semantics(plan, apply).admitted
    changed = PlanApplyBindingV1("x", envelope().digest, "1" * 40, "2" * 40, ((PATH, PREIMAGE),))
    stale = match_write_envelope(envelope(), PATH, "STORY-CR071-S01", "W2", facts(), changed)
    assert not stale.admitted and stale.mutation_count == 0
    assert assert_plan_apply_semantics(plan, stale).reason_code is MatchReasonCode.REPLAN_REQUIRED
    oid_drift = PlanApplyBindingV1(envelope().digest, envelope().digest, "3" * 40, "2" * 40, ((PATH, PREIMAGE),))
    fresh_apply = match_write_envelope(envelope(), PATH, "STORY-CR071-S01", "W2", facts(), oid_drift)
    assert assert_plan_apply_semantics(plan, fresh_apply).reason_code is MatchReasonCode.REPLAN_REQUIRED


def test_proof_failure_selects_exact_leaf_fallback() -> None:
    value = envelope()
    assert select_fallback(value, {"complete": True, "false_admit_count": 0}) is value
    fallback = select_fallback(value, {"complete": False, "false_admit_count": 0})
    assert fallback.fallback_mode
    assert match_write_envelope(fallback, PATH, "STORY-CR071-S01", "W2", facts(), binding(fallback)).admitted
    assert not match_write_envelope(fallback, "meta_flow/work/other.py", "STORY-CR071-S01", "W2", facts("meta_flow/work/other.py"), binding(fallback)).admitted
