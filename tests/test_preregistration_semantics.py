from __future__ import annotations

import pytest

from meta_flow.context_pack import read_expansion
from meta_flow.semantics import preregistration


def test_strict_required_selects_canonical_trigger_and_enables_io() -> None:
    semantics = preregistration.interpret_preregistration_entry(
        {
            "trigger": preregistration.FULL_LLD_REQUIRED_TRIGGER,
            "consumer_requirement": "required",
        },
        strict=True,
    )

    assert semantics.requirement is preregistration.ConsumerRequirement.REQUIRED
    assert semantics.select_required_ref is True
    assert semantics.evaluate_target_io is True
    assert semantics.legacy_compatibility is False


@pytest.mark.parametrize("requirement", ["optional", "forbidden"])
def test_nonrequired_values_are_valid_but_never_evaluate_target_io(
    requirement: str,
) -> None:
    semantics = preregistration.interpret_preregistration_entry(
        {
            "trigger": preregistration.FULL_LLD_REQUIRED_TRIGGER,
            "consumer_requirement": requirement,
        },
        strict=True,
    )

    assert semantics.select_required_ref is False
    assert semantics.evaluate_target_io is False


@pytest.mark.parametrize("requirement", [None, "", "N/A", "unknown", 1])
def test_unknown_requirement_fails_closed(requirement: object) -> None:
    with pytest.raises(
        preregistration.PreregistrationSemanticsError,
        match="consumer_requirement must be required, optional or forbidden",
    ):
        preregistration.parse_consumer_requirement(requirement)


def test_required_with_noncanonical_trigger_fails_closed() -> None:
    with pytest.raises(
        preregistration.PreregistrationSemanticsError,
        match="required read_if_needed entry must use",
    ):
        preregistration.interpret_preregistration_entry(
            {"trigger": "human_audit", "consumer_requirement": "required"},
            strict=True,
        )


def test_legacy_packet_keeps_trigger_compatibility_without_claiming_tristate() -> None:
    semantics = preregistration.interpret_preregistration_entry(
        {"trigger": preregistration.FULL_LLD_REQUIRED_TRIGGER},
        strict=False,
    )

    assert semantics.requirement is None
    assert semantics.select_required_ref is True
    assert semantics.evaluate_target_io is True
    assert semantics.legacy_compatibility is True


@pytest.mark.parametrize("schema_version", [None, 1, 2])
def test_only_unversioned_v1_v2_keep_legacy_compatibility(
    schema_version: int | None,
) -> None:
    assert preregistration.packet_uses_strict_semantics(schema_version) is False


@pytest.mark.parametrize("schema_version", [3, 4])
def test_v3_v4_use_strict_semantics(schema_version: int) -> None:
    assert preregistration.packet_uses_strict_semantics(schema_version) is True


@pytest.mark.parametrize("schema_version", [0, 5, -1, True, "4"])
def test_unknown_or_malformed_packet_schema_fails_closed(
    schema_version: object,
) -> None:
    with pytest.raises(preregistration.PreregistrationSemanticsError):
        preregistration.packet_uses_strict_semantics(schema_version)


def test_future_packet_cannot_bypass_forbidden_semantics_as_legacy() -> None:
    packet = {
        "schema_version": 5,
        "lld_policy": "full-lld",
        "read_if_needed": [
            {
                "path": "process/stories/STORY-X-LLD.md",
                "trigger": preregistration.FULL_LLD_REQUIRED_TRIGGER,
                "consumer_requirement": "forbidden",
            }
        ],
    }

    with pytest.raises(ValueError, match="PACKET_SCHEMA_VERSION_UNSUPPORTED"):
        read_expansion.select_required_preregistration_refs(packet)
