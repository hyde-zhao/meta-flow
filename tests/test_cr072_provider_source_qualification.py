from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "qualify_provider_source.py"
_SPEC = importlib.util.spec_from_file_location("qualify_provider_source", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
ProviderSourceQualificationInputV1 = _MODULE.ProviderSourceQualificationInputV1
qualify_provider_source = _MODULE.qualify_provider_source


def _mapping(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "package_id": "0.6.1-release-package",
        "cr_id": "CR-072",
        "version": "0.6.1",
        "release_oid": "a" * 40,
        "process_oid": "b" * 40,
        "source_fingerprint": "c" * 64,
        "plan_digest": "d" * 64,
        "cost_digest": "e" * 64,
        "compatibility_digest": "f" * 64,
        "dirty_paths": [],
        "unresolved_harness_errors": 0,
        "checks": [
            {
                "check_id": "provider-contract",
                "operation_class": "provider-contract",
                "command_digest": "1" * 64,
                "result_digest": "2" * 64,
                "decision": "PASS",
                "wheel_build_count": 0,
            },
            {
                "check_id": "detector-qualification",
                "operation_class": "detector",
                "command_digest": "3" * 64,
                "result_digest": "4" * 64,
                "decision": "PASS",
                "wheel_build_count": 0,
            },
        ],
        "execution_class": "fixture",
        "authorization_ref": "",
        "authorization_digest": "",
    }
    value.update(updates)
    return value


def _value(**updates: object) -> ProviderSourceQualificationInputV1:
    return ProviderSourceQualificationInputV1.from_mapping(_mapping(**updates))


def test_qb001_source_qualification_is_source_only_and_fixture_is_non_authoritative() -> None:
    result = qualify_provider_source(_value())
    assert result["decision"] == "PASS"
    assert result["wheel_build_count"] == 0
    assert result["qualification_increment"] == 0
    assert result["authoritative"] is False
    assert result["mutation_count"] == 0
    assert len(result["receipt_digest"]) == 64


def test_release_action_source_qualification_requires_typed_authorization() -> None:
    with pytest.raises(ValueError, match="PROVIDER_SOURCE_AUTHORIZATION_REQUIRED"):
        _value(execution_class="release-action")
    result = qualify_provider_source(
        _value(
            execution_class="release-action",
            authorization_ref="process/authorizations/provider-source.json",
            authorization_digest="9" * 64,
        )
    )
    assert result["decision"] == "PASS"
    assert result["authoritative"] is True
    assert result["qualification_increment"] == 1
    assert result["wheel_build_count"] == 0


def test_qb004_hidden_build_is_typed_blocked() -> None:
    checks = _mapping()["checks"]
    assert isinstance(checks, list)
    hidden = [dict(item) for item in checks]
    hidden[0]["wheel_build_count"] = 1
    result = qualify_provider_source(_value(checks=hidden))
    assert result["decision"] == "BLOCKED"
    assert result["wheel_build_count"] == 0
    assert "SOURCE_QUALIFICATION_HIDDEN_BUILD" in result["diagnostics"]


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"dirty_paths": ["meta_flow/changed.py"]}, "PROVIDER_SOURCE_DIRTY"),
        ({"unresolved_harness_errors": 1}, "CHECK_HARNESS_ERROR_UNRESOLVED"),
    ],
)
def test_dirty_source_or_harness_error_blocks(
    updates: dict[str, object], code: str
) -> None:
    result = qualify_provider_source(_value(**updates))
    assert result["decision"] == "BLOCKED"
    assert code in result["diagnostics"]
    assert result["qualification_increment"] == 0


def test_failed_source_check_is_not_misreported_as_pass() -> None:
    checks = _mapping()["checks"]
    assert isinstance(checks, list)
    failed = [dict(item) for item in checks]
    failed[1]["decision"] = "CHECK_HARNESS_ERROR"
    result = qualify_provider_source(_value(checks=failed))
    assert result["decision"] == "BLOCKED"
    assert "PROVIDER_SOURCE_CHECK_FAILED" in result["diagnostics"]


def test_source_qualification_schema_is_closed_and_copies_nested_input() -> None:
    raw = _mapping()
    value = ProviderSourceQualificationInputV1.from_mapping(raw)
    raw["checks"][0]["decision"] = "BLOCKED"  # type: ignore[index]
    assert value.checks[0].decision == "PASS"
    with pytest.raises(ValueError, match="PROVIDER_SOURCE_INPUT_FIELDS_MISMATCH"):
        ProviderSourceQualificationInputV1.from_mapping({**_mapping(), "wheel": "x.whl"})


def test_source_qualifier_has_no_build_backend_or_wheel_path_contract() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(name.startswith(("build", "hatchling", "setuptools")) for name in imports)
    assert "--wheel" not in source
    assert "subprocess" not in imports


def test_source_qualifier_cli_is_zero_write(tmp_path) -> None:
    input_path = tmp_path / "source-input.json"
    input_path.write_text(json.dumps(_mapping(), sort_keys=True) + "\n", encoding="utf-8")
    before = input_path.read_bytes()
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(input_path), "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    result = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert result["decision"] == "PASS"
    assert result["wheel_build_count"] == 0
    assert result["mutation_count"] == 0
    assert input_path.read_bytes() == before
