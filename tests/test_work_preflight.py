import pytest

from meta_flow.work.preflight import render_preflight, run_preflight


def context(**overrides: object) -> dict[str, object]:
    result = {"release_oid": "a" * 40, "process_oid": "b" * 40, "dirty_owned": True}
    result.update(overrides)
    return result


def test_preflight_uses_same_core_and_never_mutates() -> None:
    report = run_preflight(context())
    rendered = render_preflight(report)
    assert report.mutation_count == report.decision.mutation_count == rendered["mutation_count"] == 0
    assert rendered["decision"] == "PASS"


def test_preflight_dirty_unowned_is_blocked_and_safe() -> None:
    report = run_preflight(context(dirty_owned=False))
    assert report.decision.decision.value == "BLOCKED"
    assert report.mutation_count == 0


def test_preflight_rejects_unknown_or_malformed_context() -> None:
    with pytest.raises(ValueError):
        run_preflight({"release_oid": "a" * 40, "process_oid": "b" * 40, "dirty_owned": True, "unknown": True})
