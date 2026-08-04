from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.work.validation_planner import build_validation_execution_plan
from meta_flow.work.validation_receipt import (
    create_validation_receipt,
    load_validation_receipt,
    write_validation_receipt,
)

LAYERS = ("targeted", "compatibility", "full")
ENVIRONMENT = {"python": "3.11.15", "platform": "linux-x86_64", "toolchain": "uv-0.8"}


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def receipt(layer: str, decision: str = "PASS", *, owner: str = "primary-dev"):
    return create_validation_receipt(
        layer=layer,
        fingerprint_digest=digest(f"fingerprint-{layer}"),
        command_identity=digest(f"command-{layer}"),
        environment_summary=ENVIRONMENT,
        decision=decision,
        result_digest=digest(f"result-{layer}-{decision}"),
        owner=owner,
    )


def inputs():
    return (
        {layer: digest(f"fingerprint-{layer}") for layer in LAYERS},
        {layer: digest(f"command-{layer}") for layer in LAYERS},
    )


def test_validation_starts_targeted_and_stops_downstream() -> None:
    fingerprints, commands = inputs()

    plan = build_validation_execution_plan(
        fingerprints=fingerprints,
        command_identities=commands,
    )

    assert plan.decision == "READY_TO_RUN"
    assert plan.next_layer == "targeted"
    assert [step.action for step in plan.steps] == ["RUN", "NOT_STARTED", "NOT_STARTED"]


def test_exact_pass_reuses_and_advances_one_layer() -> None:
    fingerprints, commands = inputs()

    plan = build_validation_execution_plan(
        fingerprints=fingerprints,
        command_identities=commands,
        receipts=(receipt("targeted"),),
    )

    assert [step.action for step in plan.steps] == [
        "REUSED_UNCHANGED",
        "RUN",
        "NOT_STARTED",
    ]
    assert plan.next_layer == "compatibility"


def test_fail_or_command_mismatch_is_never_reused() -> None:
    fingerprints, commands = inputs()
    failed = build_validation_execution_plan(
        fingerprints=fingerprints,
        command_identities=commands,
        receipts=(receipt("targeted", "FAIL"),),
    )
    commands["targeted"] = digest("different-command")
    mismatched = build_validation_execution_plan(
        fingerprints=fingerprints,
        command_identities=commands,
        receipts=(receipt("targeted"),),
    )

    assert failed.steps[0].action == "RUN"
    assert failed.steps[0].reason == "matching prior FAIL is never reusable"
    assert [step.action for step in failed.steps] == [
        "RUN",
        "NOT_STARTED",
        "NOT_STARTED",
    ]
    assert failed.next_layer == "targeted"
    assert mismatched.steps[0].action == "RUN"


def test_all_exact_passes_reuse_without_execution() -> None:
    fingerprints, commands = inputs()

    plan = build_validation_execution_plan(
        fingerprints=fingerprints,
        command_identities=commands,
        receipts=tuple(receipt(layer) for layer in LAYERS),
    )

    assert plan.decision == "REUSED_ALL"
    assert plan.next_layer == ""
    assert plan.full_execution_count == 0
    assert {step.action for step in plan.steps} == {"REUSED_UNCHANGED"}


def test_receipt_is_digest_bound_create_only_and_full_pass_has_one_owner(tmp_path: Path) -> None:
    original = receipt("full")

    path, mutated = write_validation_receipt(tmp_path, "W-001", original)
    same_path, second_mutation = write_validation_receipt(tmp_path, "W-001", original)

    assert mutated is True
    assert second_mutation is False
    assert path == same_path
    assert load_validation_receipt(path) == original

    with pytest.raises(ValueError, match="one different owner"):
        write_validation_receipt(tmp_path, "W-001", receipt("full", owner="reviewer"))


def test_receipt_rejects_missing_fingerprint_and_path_like_environment() -> None:
    with pytest.raises(ValueError, match="fingerprint_digest"):
        create_validation_receipt(
            layer="targeted",
            fingerprint_digest="",
            command_identity=digest("command"),
            environment_summary=ENVIRONMENT,
            decision="PASS",
            result_digest=digest("result"),
            owner="primary-dev",
        )
    with pytest.raises(ValueError, match="non-path"):
        create_validation_receipt(
            layer="targeted",
            fingerprint_digest=digest("fingerprint"),
            command_identity=digest("command"),
            environment_summary={**ENVIRONMENT, "toolchain": "/tmp/tool"},
            decision="PASS",
            result_digest=digest("result"),
            owner="primary-dev",
        )
