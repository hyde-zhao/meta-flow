from __future__ import annotations

import importlib.util
from pathlib import Path


def _guardrail_module():
    path = Path("scripts/check_delivery_guardrails.py").resolve()
    spec = importlib.util.spec_from_file_location("cr047_delivery_guardrail", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_root_agents_is_an_optional_generated_wrapper() -> None:
    guardrail = _guardrail_module()

    assert guardrail.is_optional_generated_root_rule(Path("AGENTS.md").resolve())
    assert not guardrail.is_optional_generated_root_rule(
        Path("delivery/rules/AGENTS.md").resolve()
    )


def test_tracked_cache_is_blocking_even_if_ignored() -> None:
    guardrail = _guardrail_module()

    assert (
        guardrail.cache_hygiene_severity(
            Path("tests/__pycache__"), tracked=True, ignored=True
        )
        == "BLOCK"
    )


def test_package_input_cache_is_blocking_before_ignore_classification() -> None:
    guardrail = _guardrail_module()

    assert (
        guardrail.cache_hygiene_severity(
            Path("meta_flow/__pycache__"), tracked=False, ignored=True, package_input=True
        )
        == "BLOCK"
    )


def test_ignored_local_non_package_cache_is_warning() -> None:
    guardrail = _guardrail_module()

    assert (
        guardrail.cache_hygiene_severity(
            Path("tests/__pycache__"), tracked=False, ignored=True
        )
        == "WARN"
    )


def test_unignored_local_cache_is_blocking() -> None:
    guardrail = _guardrail_module()

    assert (
        guardrail.cache_hygiene_severity(
            Path("tests/__pycache__"), tracked=False, ignored=False
        )
        == "BLOCK"
    )


def test_binding_profile_contract_allows_g2_binding_only() -> None:
    guardrail = _guardrail_module()
    valid = {
        "README.md": (
            "vNext binding-only 适用于 G0/G1/G2；"
            "当前 G2/正式 CR 只有经人工门显式选择才进入 legacy 扩展。"
        ),
        "delivery/rules/AGENTS.md": (
            "vNext binding-only 适用于 G0/G1/G2；"
            "legacy shared-artifact 需要人工门显式选择。"
        ),
    }

    assert guardrail.binding_profile_contract_errors(valid) == []


def test_binding_profile_contract_rejects_g0_g1_only_wording() -> None:
    guardrail = _guardrail_module()
    restricted = {
        "README.md": "vNext binding-only G0/G1 不创建 process。",
        "delivery/rules/AGENTS.md": "vNext binding-only G0/G1 适用双向 binding。",
    }

    errors = guardrail.binding_profile_contract_errors(restricted)

    assert any("must allow G0/G1/G2" in error for error in errors)
    assert any("must not restrict binding-only to G0/G1" in error for error in errors)
