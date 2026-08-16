"""Closed validation-policy contracts with explicit ordered layers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ValidationLayer(StrEnum):
    TARGETED = "targeted"
    COMPATIBILITY = "compatibility"
    FULL = "full"


class ValidationStrategy(StrEnum):
    TARGETED_ONLY = "targeted_only"
    TARGETED_THEN_COMPATIBILITY = "targeted_then_compatibility"
    TARGETED_COMPATIBILITY_FULL = "targeted_compatibility_full"


class ValidationPolicyErrorCode(StrEnum):
    INVALID_SCHEMA_VERSION = "INVALID_SCHEMA_VERSION"
    UNKNOWN_STRATEGY = "UNKNOWN_STRATEGY"
    UNKNOWN_LAYER = "UNKNOWN_LAYER"
    EMPTY_REQUIRED_LAYERS = "EMPTY_REQUIRED_LAYERS"
    DUPLICATE_REQUIRED_LAYER = "DUPLICATE_REQUIRED_LAYER"
    INVALID_LAYER_ORDER = "INVALID_LAYER_ORDER"
    REQUIRED_LAYER_OMITTED = "REQUIRED_LAYER_OMITTED"
    AMBIGUOUS_LEGACY_POLICY = "AMBIGUOUS_LEGACY_POLICY"
    UNKNOWN_LEGACY_POLICY = "UNKNOWN_LEGACY_POLICY"


class ValidationPolicyContractError(ValueError):
    """A safe, closed normalisation failure without raw policy values."""

    def __init__(self, code: ValidationPolicyErrorCode, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"validation policy contract rejected: {code.value} ({field})")


@dataclass(frozen=True)
class ValidationPolicyV2:
    schema_version: int
    default_strategy: ValidationStrategy
    required_layers: tuple[ValidationLayer, ...]
    risk_class: str
    scope_digest: str
    profile_revision: int

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise ValidationPolicyContractError(
                ValidationPolicyErrorCode.INVALID_SCHEMA_VERSION, "schema_version"
            )
        _validate_layers(self.default_strategy, self.required_layers)
        if not isinstance(self.risk_class, str) or not self.risk_class:
            raise ValidationPolicyContractError(ValidationPolicyErrorCode.UNKNOWN_LEGACY_POLICY, "risk_class")
        _validate_digest(self.scope_digest, "scope_digest")
        if not isinstance(self.profile_revision, int) or isinstance(self.profile_revision, bool) or self.profile_revision < 1:
            raise ValidationPolicyContractError(
                ValidationPolicyErrorCode.UNKNOWN_LEGACY_POLICY, "profile_revision"
            )


@dataclass(frozen=True)
class ValidationPolicyProvenanceV1:
    input_schema_version: int
    input_class: str
    policy_identity_digest: str
    reader_version: int
    decision_code: str


@dataclass(frozen=True)
class ValidationPolicyNormalizationResult:
    value: ValidationPolicyV2
    provenance: ValidationPolicyProvenanceV1


def normalize_validation_policy(
    value: ValidationPolicyV2 | Mapping[str, Any], *, policy_identity: str
) -> ValidationPolicyNormalizationResult:
    """Normalize an exact v2 or the one deterministic v1 schema to v2.

    Legacy flags which could prohibit a layer are intentionally not accepted;
    they are ambiguous rather than a reason to silently weaken requirements.
    """

    _validate_digest(policy_identity, "policy_identity")
    if isinstance(value, ValidationPolicyV2):
        return _result(value, 2, "v2", policy_identity, "ACCEPTED_V2")
    if not isinstance(value, Mapping):
        raise ValidationPolicyContractError(ValidationPolicyErrorCode.UNKNOWN_LEGACY_POLICY, "value")
    schema_version = value.get("schema_version")
    if schema_version == 2:
        _require_exact_keys(value, _V2_KEYS, "v2")
        return _result(_policy_from_mapping(value, strategy_field="default_strategy"), 2, "v2", policy_identity, "ACCEPTED_V2")
    if schema_version == 1:
        if "full_regression_allowed" in value:
            raise ValidationPolicyContractError(
                ValidationPolicyErrorCode.AMBIGUOUS_LEGACY_POLICY, "full_regression_allowed"
            )
        _require_exact_keys(value, _V1_KEYS, "legacy_shape")
        return _result(_policy_from_mapping(value, strategy_field="strategy"), 1, "v1-deterministic", policy_identity, "NORMALIZED_V1")
    if "schema_version" in value:
        raise ValidationPolicyContractError(
            ValidationPolicyErrorCode.INVALID_SCHEMA_VERSION, "schema_version"
        )
    raise ValidationPolicyContractError(ValidationPolicyErrorCode.UNKNOWN_LEGACY_POLICY, "legacy_shape")


_V2_KEYS = {
    "schema_version",
    "default_strategy",
    "required_layers",
    "risk_class",
    "scope_digest",
    "profile_revision",
}
_V1_KEYS = {"schema_version", "strategy", "required_layers", "risk_class", "scope_digest", "profile_revision"}


def _policy_from_mapping(value: Mapping[str, Any], *, strategy_field: str) -> ValidationPolicyV2:
    return ValidationPolicyV2(
        2,
        _strategy(value[strategy_field]),
        _layers(value["required_layers"]),
        value["risk_class"],
        value["scope_digest"],
        value["profile_revision"],
    )


def _result(
    value: ValidationPolicyV2,
    input_schema_version: int,
    input_class: str,
    policy_identity: str,
    decision_code: str,
) -> ValidationPolicyNormalizationResult:
    return ValidationPolicyNormalizationResult(
        value,
        ValidationPolicyProvenanceV1(
            input_schema_version,
            input_class,
            sha256(policy_identity.encode("ascii")).hexdigest(),
            2,
            decision_code,
        ),
    )


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ValidationPolicyContractError(ValidationPolicyErrorCode.AMBIGUOUS_LEGACY_POLICY, field)


def _strategy(value: object) -> ValidationStrategy:
    try:
        return ValidationStrategy(value)
    except (TypeError, ValueError) as error:
        raise ValidationPolicyContractError(ValidationPolicyErrorCode.UNKNOWN_STRATEGY, "strategy") from error


def _layers(value: object) -> tuple[ValidationLayer, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValidationPolicyContractError(ValidationPolicyErrorCode.UNKNOWN_LAYER, "required_layers")
    try:
        return tuple(ValidationLayer(item) for item in value)
    except (TypeError, ValueError) as error:
        raise ValidationPolicyContractError(ValidationPolicyErrorCode.UNKNOWN_LAYER, "required_layers") from error


def _validate_layers(strategy: ValidationStrategy, layers: tuple[ValidationLayer, ...]) -> None:
    if not layers:
        raise ValidationPolicyContractError(
            ValidationPolicyErrorCode.EMPTY_REQUIRED_LAYERS, "required_layers"
        )
    if len(set(layers)) != len(layers):
        raise ValidationPolicyContractError(
            ValidationPolicyErrorCode.DUPLICATE_REQUIRED_LAYER, "required_layers"
        )
    canonical = tuple(layer for layer in ValidationLayer if layer in layers)
    if layers != canonical:
        raise ValidationPolicyContractError(
            ValidationPolicyErrorCode.INVALID_LAYER_ORDER, "required_layers"
        )
    expected = {
        ValidationStrategy.TARGETED_ONLY: (ValidationLayer.TARGETED,),
        ValidationStrategy.TARGETED_THEN_COMPATIBILITY: (
            ValidationLayer.TARGETED,
            ValidationLayer.COMPATIBILITY,
        ),
        ValidationStrategy.TARGETED_COMPATIBILITY_FULL: tuple(ValidationLayer),
    }[strategy]
    if layers != expected:
        raise ValidationPolicyContractError(
            ValidationPolicyErrorCode.REQUIRED_LAYER_OMITTED, "required_layers"
        )


def _validate_digest(value: object, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValidationPolicyContractError(ValidationPolicyErrorCode.UNKNOWN_LEGACY_POLICY, field)
