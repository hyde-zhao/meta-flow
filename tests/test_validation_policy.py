from __future__ import annotations

import pytest

from meta_flow.contracts import (
    ValidationLayer,
    ValidationPolicyContractError,
    ValidationPolicyErrorCode,
    ValidationPolicyV2,
    ValidationStrategy,
    normalize_validation_policy,
)

DIGEST = "b" * 64


def _v2_policy() -> dict[str, object]:
    return {
        "schema_version": 2,
        "default_strategy": "targeted_compatibility_full",
        "required_layers": ["targeted", "compatibility", "full"],
        "risk_class": "data-contract-high-risk",
        "scope_digest": DIGEST,
        "profile_revision": 1,
    }


def test_v2_policy_has_exact_full_order_and_is_deterministic() -> None:
    result = normalize_validation_policy(_v2_policy(), policy_identity=DIGEST)

    assert result.value == ValidationPolicyV2(
        2,
        ValidationStrategy.TARGETED_COMPATIBILITY_FULL,
        (ValidationLayer.TARGETED, ValidationLayer.COMPATIBILITY, ValidationLayer.FULL),
        "data-contract-high-risk",
        DIGEST,
        1,
    )
    assert result.provenance.input_class == "v2"


def test_deterministic_v1_policy_has_v2_decision_parity() -> None:
    v1 = {
        "schema_version": 1,
        "strategy": "targeted_compatibility_full",
        "required_layers": ["targeted", "compatibility", "full"],
        "risk_class": "data-contract-high-risk",
        "scope_digest": DIGEST,
        "profile_revision": 1,
    }

    modern = normalize_validation_policy(_v2_policy(), policy_identity=DIGEST)
    legacy = normalize_validation_policy(v1, policy_identity=DIGEST)

    assert legacy.value == modern.value
    assert legacy.provenance.input_class == "v1-deterministic"
    assert legacy.provenance.decision_code == "NORMALIZED_V1"


@pytest.mark.parametrize(
    ("layers", "code"),
    [
        ([], ValidationPolicyErrorCode.EMPTY_REQUIRED_LAYERS),
        (["targeted", "targeted"], ValidationPolicyErrorCode.DUPLICATE_REQUIRED_LAYER),
        (["compatibility", "targeted"], ValidationPolicyErrorCode.INVALID_LAYER_ORDER),
        (["targeted", "full"], ValidationPolicyErrorCode.REQUIRED_LAYER_OMITTED),
        (["targeted", "compatibility"], ValidationPolicyErrorCode.REQUIRED_LAYER_OMITTED),
        (["targeted", "compatibility", "unknown"], ValidationPolicyErrorCode.UNKNOWN_LAYER),
    ],
)
def test_required_layers_fail_closed(layers: list[str], code: ValidationPolicyErrorCode) -> None:
    candidate = _v2_policy()
    candidate["required_layers"] = layers

    with pytest.raises(ValidationPolicyContractError) as raised:
        normalize_validation_policy(candidate, policy_identity=DIGEST)

    assert raised.value.code is code


def test_strategy_cannot_weaken_or_expand_its_required_layers() -> None:
    candidate = _v2_policy()
    candidate["default_strategy"] = "targeted_only"

    with pytest.raises(ValidationPolicyContractError) as raised:
        normalize_validation_policy(candidate, policy_identity=DIGEST)

    assert raised.value.code is ValidationPolicyErrorCode.REQUIRED_LAYER_OMITTED


def test_prohibition_like_legacy_flag_is_ambiguous_and_private() -> None:
    secret = "credential-value"
    candidate = {
        "schema_version": 1,
        "strategy": "targeted_compatibility_full",
        "required_layers": ["targeted", "compatibility", "full"],
        "risk_class": secret,
        "scope_digest": DIGEST,
        "profile_revision": 1,
        "full_regression_allowed": False,
    }

    with pytest.raises(ValidationPolicyContractError) as raised:
        normalize_validation_policy(candidate, policy_identity=DIGEST)

    assert raised.value.code is ValidationPolicyErrorCode.AMBIGUOUS_LEGACY_POLICY
    assert secret not in str(raised.value)


def test_unknown_strategy_is_closed() -> None:
    candidate = _v2_policy()
    candidate["default_strategy"] = "skip_full"

    with pytest.raises(ValidationPolicyContractError) as raised:
        normalize_validation_policy(candidate, policy_identity=DIGEST)

    assert raised.value.code is ValidationPolicyErrorCode.UNKNOWN_STRATEGY
