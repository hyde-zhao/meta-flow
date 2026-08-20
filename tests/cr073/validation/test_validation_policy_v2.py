from __future__ import annotations

from dataclasses import replace

import pytest

from meta_flow.checks.full_regression_reuse import check_full_regression_reuse
from meta_flow.validation.policy_v2 import (
    ValidationLayerGraphV1,
    ValidationPolicyRequestV2,
    ValidationPolicyV2Provider,
    evaluate_validation_policy_v2,
)
from meta_flow.validation.receipt_identity import (
    ReceiptIdentityV2,
    build_receipt_identity_v2,
    build_source_manifest,
    normalize_semantic_environment,
)
from meta_flow.work.model import ValidationReuseRequestV2

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _environment(**updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "python": "CPython 3.11.15",
        "platform": "Linux",
        "architecture": "x86_64",
        "uv": "0.11.6",
        "cwd": "/private/worktree",
        "cache_dir": "/private/cache",
        "timestamp": "ignored",
    }
    values.update(updates)
    return values


def _identity(**updates: object) -> ReceiptIdentityV2:
    values: dict[str, object] = {
        "layer": "targeted",
        "source_fingerprint_digest": DIGEST_A,
        "profile_digest": DIGEST_B,
        "command_identity": "pytest-targeted-v1",
        "environment": _environment(),
        "source_manifest": {
            "meta_flow/a.py": DIGEST_A,
            "tests/test_a.py": DIGEST_B,
        },
        "provider_identity_digest": DIGEST_C,
        "outcome": "PASS",
        "partial_mutation": False,
    }
    values.update(updates)
    return build_receipt_identity_v2(**values)  # type: ignore[arg-type]


def _graph() -> ValidationLayerGraphV1:
    return ValidationLayerGraphV1(
        (("compatibility", "full"), ("targeted", "compatibility"))
    )


def _request(
    current: ReceiptIdentityV2,
    candidate: ReceiptIdentityV2 | None,
    *,
    full_default: bool = True,
    planner_action: str = "REUSE",
) -> ValidationPolicyRequestV2:
    return ValidationPolicyRequestV2(
        current,
        candidate,
        _graph(),
        full_default,
        planner_action,
    )


def test_semantically_equivalent_environment_ignores_incidental_paths() -> None:
    first = normalize_semantic_environment(_environment())
    second = normalize_semantic_environment(
        _environment(
            cwd="/another/worktree",
            cache_dir="/another/cache",
            timestamp="another-time",
        )
    )

    assert first == second
    assert first.python_major_minor == "3.11"
    assert first.toolchains == (("uv", "0.11"),)


@pytest.mark.parametrize(
    "updates",
    [
        {"architecture": ""},
        {"python": "unknown"},
        {"security_patch": "hidden-dimension"},
    ],
)
def test_missing_or_unknown_security_environment_fails_closed(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="SEMANTIC_ENVIRONMENT"):
        normalize_semantic_environment(_environment(**updates))


def test_source_manifest_is_permutation_stable_and_rejects_duplicate_refs() -> None:
    first = build_source_manifest(
        [("tests/test_a.py", DIGEST_B), ("meta_flow/a.py", DIGEST_A)]
    )
    second = build_source_manifest(
        [("meta_flow/a.py", DIGEST_A), ("tests/test_a.py", DIGEST_B)]
    )
    assert first == second
    assert first.digest == second.digest

    with pytest.raises(ValueError, match="SOURCE_MANIFEST"):
        build_source_manifest(
            [("meta_flow/a.py", DIGEST_A), ("meta_flow/a.py", DIGEST_B)]
        )


def test_complete_pass_identity_is_reused() -> None:
    current = _identity()
    decision = evaluate_validation_policy_v2(_request(current, current))

    assert decision.action == "REUSE"
    assert decision.affected_layers == ()
    assert decision.reason_codes == ()
    assert decision.mutation_count == 0


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (_identity(source_fingerprint_digest="d" * 64), "SOURCE_FINGERPRINT_DRIFT"),
        (_identity(profile_digest="d" * 64), "PROFILE_DRIFT"),
        (_identity(command_identity="pytest-targeted-v2"), "COMMAND_IDENTITY_DRIFT"),
        (_identity(environment=_environment(architecture="aarch64")), "ENVIRONMENT_DRIFT"),
        (
            _identity(source_manifest={"meta_flow/a.py": "d" * 64}),
            "SOURCE_MANIFEST_DRIFT",
        ),
        (_identity(provider_identity_digest="d" * 64), "PROVIDER_IDENTITY_DRIFT"),
        (_identity(outcome="FAIL"), "RECEIPT_OUTCOME_NOT_PASS"),
        (_identity(partial_mutation=True), "PARTIAL_MUTATION"),
    ],
)
def test_each_semantic_or_safety_drift_runs_only_affected_closure(
    candidate: ReceiptIdentityV2,
    reason: str,
) -> None:
    decision = evaluate_validation_policy_v2(
        _request(_identity(), candidate, planner_action="RUN")
    )

    assert decision.action == "RUN"
    assert decision.affected_layers == ("targeted", "compatibility", "full")
    assert reason in decision.reason_codes


def test_compatibility_drift_does_not_rebuild_targeted() -> None:
    current = _identity(layer="compatibility")
    candidate = replace(current, command_identity="pytest-compatibility-v2")
    decision = evaluate_validation_policy_v2(
        _request(current, candidate, planner_action="RUN")
    )

    assert decision.affected_layers == ("compatibility", "full")


def test_missing_v2_identity_runs_and_layer_mismatch_blocks() -> None:
    current = _identity()
    missing = evaluate_validation_policy_v2(
        _request(current, None, planner_action="RUN")
    )
    mismatch = evaluate_validation_policy_v2(
        _request(current, _identity(layer="full"), planner_action="BLOCKED")
    )

    assert missing.action == "RUN"
    assert missing.reason_codes == ("V2_RECEIPT_IDENTITY_MISSING",)
    assert mismatch.action == "BLOCKED"
    assert mismatch.reason_codes == ("RECEIPT_LAYER_MISMATCH",)


def test_concrete_provider_consumes_s02_typed_request_without_adapter_rules() -> None:
    request = ValidationReuseRequestV2(
        2,
        "targeted",
        DIGEST_A,
        DIGEST_A,
        DIGEST_B,
        DIGEST_B,
        "pytest-targeted-v1",
        "pytest-targeted-v1",
        (("architecture", "x86_64"), ("python", "3.11")),
        (("architecture", "x86_64"), ("python", "3.11")),
        DIGEST_C,
        DIGEST_C,
        DIGEST_A,
        DIGEST_A,
        "PASS",
        False,
    )
    provider = ValidationPolicyV2Provider()

    assert provider.evaluate_reuse(request).decision == "REUSE"
    drift = replace(request, current_environment=(("python", "3.12"),))
    result = provider.evaluate_reuse(drift)
    assert result.decision == "RUN"
    assert result.reason_codes == ("ENVIRONMENT_DRIFT",)


def test_profile_default_is_descriptive_and_planner_action_is_authoritative() -> None:
    current = _identity()
    candidate = replace(current, command_identity="changed")
    policy = evaluate_validation_policy_v2(
        _request(
            current,
            candidate,
            full_default=False,
            planner_action="RUN",
        )
    )
    checked = check_full_regression_reuse(
        policy,
        full_layer_default_for_profile=False,
        planner_action="RUN",
    )

    assert checked["decision"] == "PASS"
    assert checked["planner_action"] == "RUN"
    assert checked["full_layer_default_for_profile"] is False
    assert "permission" not in str(checked["semantic_note"]).lower()
    assert "PROFILE_DEFAULT_IS_NOT_PERMISSION" in policy.machine_notes


def test_layer_graph_cycle_is_rejected() -> None:
    with pytest.raises(ValueError, match="VALIDATION_LAYER_GRAPH_CYCLE"):
        ValidationLayerGraphV1(
            (("compatibility", "targeted"), ("targeted", "compatibility"))
        )
