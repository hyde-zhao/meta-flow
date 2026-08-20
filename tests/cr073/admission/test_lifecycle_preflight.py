from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_flow.work.preflight import (
    LifecyclePathV1,
    WorkLifecycleCandidateV1,
    WorkLifecycleContextV1,
    render_preflight_result,
    run_lifecycle_preflight,
)
from meta_flow.work.validation_kernel import AdmissionItemV2, DecisionStatus

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _candidate(**updates: object) -> WorkLifecycleCandidateV1:
    values: dict[str, object] = {
        "work_id": "W-001",
        "business_reads": ("docs/input.md",),
        "business_writes": ("src/output.py",),
        "candidate_digest": DIGEST_A,
        "existing_digest": DIGEST_B,
    }
    values.update(updates)
    return WorkLifecycleCandidateV1(**values)  # type: ignore[arg-type]


def _context(**updates: object) -> WorkLifecycleContextV1:
    values: dict[str, object] = {
        "granted_business_reads": ("docs/input.md",),
        "granted_business_writes": ("src/output.py",),
    }
    values.update(updates)
    return WorkLifecycleContextV1(**values)  # type: ignore[arg-type]


def test_success_failure_and_noop_share_one_zero_write_decision() -> None:
    report = run_lifecycle_preflight(_candidate(), _context())
    rendered = render_preflight_result(report)

    assert report.mutation_count == 0
    assert rendered["decision"] == "READY"
    assert [item["path"] for item in rendered["simulations"]] == [
        "failure",
        "no_op",
        "success",
    ]
    failure = next(item for item in rendered["simulations"] if item["path"] == "failure")
    kinds = {item["object_kind"] for item in failure["system_owned_demands"]}
    assert {"failure-evidence", "blocker", "handoff", "transaction"} <= kinds
    success = next(item for item in rendered["simulations"] if item["path"] == "success")
    assert success["business_scope_demands"][-1]["logical_ref"] == "src/output.py"
    assert json.dumps(rendered, sort_keys=True) == json.dumps(
        render_preflight_result(run_lifecycle_preflight(_candidate(), _context())),
        sort_keys=True,
    )


@pytest.mark.parametrize(
    ("context", "expected_code"),
    [
        (
            WorkLifecycleContextV1(granted_business_writes=("src/output.py",)),
            "BUSINESS_READ_SCOPE_MISSING:docs/input.md",
        ),
        (
            WorkLifecycleContextV1(granted_business_reads=("docs/input.md",)),
            "BUSINESS_WRITE_SCOPE_MISSING:src/output.py",
        ),
        (
            WorkLifecycleContextV1(
                granted_business_reads=("docs/input.md",),
                granted_business_writes=("src/output.py",),
                supported_system_kinds=(
                    "blocker",
                    "failure-evidence",
                    "handoff",
                    "project-projection",
                    "transaction",
                    "usage",
                    "validation-receipt",
                ),
            ),
            "SYSTEM_DEMAND_UNAVAILABLE:work-envelope",
        ),
    ],
)
def test_missing_success_or_failure_demands_block_before_mutation(
    context: WorkLifecycleContextV1,
    expected_code: str,
) -> None:
    report = run_lifecycle_preflight(_candidate(), context)
    assert report.decision.decision.value == "BLOCKED"
    assert report.mutation_count == 0
    assert expected_code in {item.code for item in report.decision.items}


def test_matching_existing_work_is_no_change_without_apply_demands() -> None:
    report = run_lifecycle_preflight(
        _candidate(existing_digest=DIGEST_A),
        _context(),
    )
    assert report.decision.decision.value == "NO_CHANGE"
    success = next(item for item in report.simulations if item.path is LifecyclePathV1.SUCCESS)
    assert not [d for d in success.business_scope_demands if d.access.value == "write"]


def test_duplicate_validator_owner_fails_closed() -> None:
    def validator(_simulations: object) -> tuple[AdmissionItemV2, ...]:
        return (AdmissionItemV2("typed-ref", "TYPED_REF_OK", DecisionStatus.PASS),)

    report = run_lifecycle_preflight(
        _candidate(),
        _context(),
        validators=(("typed-ref", validator), ("typed-ref", validator)),
    )
    assert report.decision.decision.value == "BLOCKED"
    assert report.decision.duplicate_rule_owner_count == 1
    assert "DUPLICATE_RULE_OWNER" in {item.code for item in report.decision.items}


@pytest.mark.parametrize(
    "unsafe_ref",
    ["/etc/passwd", "../secret", "https://example.invalid/a", "token=abc", "user@example/a"],
)
def test_unsafe_or_secret_like_refs_fail_closed(unsafe_ref: str) -> None:
    with pytest.raises(ValueError, match="PREFLIGHT_REF_UNSAFE"):
        _candidate(business_reads=(unsafe_ref,))


def test_preflight_never_touches_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("filesystem mutation attempted")

    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "touch", forbidden)
    report = run_lifecycle_preflight(_candidate(), _context())
    assert report.mutation_count == 0

