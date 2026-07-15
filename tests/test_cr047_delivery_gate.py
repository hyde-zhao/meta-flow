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
