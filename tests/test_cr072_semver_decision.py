from __future__ import annotations

import copy
import json
from contextlib import redirect_stdout
from io import StringIO

import pytest

from meta_flow import package_cli
from meta_flow.policies.semver_decision import (
    SemVerBootstrapDecisionV1,
    SemVerDecisionInputV1,
    build_cr072_bootstrap,
    decide_semver,
)


def _mapping(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "package_id": "0.6.1-release-package",
        "cr_id": "CR-072",
        "base_version": "0.6.0",
        "requested_version": "0.6.1",
        "added_public_operations": ["package.semver-decide", "package.release-check"],
        "added_public_schemas": ["SemVerDecisionV1"],
        "added_compatible_capabilities": ["governance-compiler"],
        "bug_fix_ids": ["ISSUE-001"],
        "breaking_evidence": [],
        "unknown_compatibility_evidence": [],
        "source_digest": "a" * 64,
        "plan_digest": "b" * 64,
        "policy_digest": "c" * 64,
        "compatibility_digest": "d" * 64,
        "claimed_category": "patch",
    }
    value.update(updates)
    return value


def _value(**updates: object) -> SemVerDecisionInputV1:
    return SemVerDecisionInputV1.from_mapping(_mapping(**updates))


def test_sv001_new_public_contract_truthfully_recommends_next_minor() -> None:
    value = _value()
    result = decide_semver(value)
    assert result.normal_machine_recommendation == "next-minor"
    assert result.normal_recommended_version == "0.7.0"
    assert result.decision == "BLOCKED"
    assert [item.code for item in result.diagnostics] == [
        "REQUESTED_VERSION_SEMVER_MISMATCH"
    ]
    assert result.selected_version == ""
    # caller 的 patch 声明既不能改分类，也不进入 machine digest。
    assert value.classification_digest == _value(claimed_category="minor").classification_digest


def test_sv002_bugfix_only_recommends_and_selects_next_patch() -> None:
    result = decide_semver(
        _value(
            added_public_operations=[],
            added_public_schemas=[],
            added_compatible_capabilities=[],
        )
    )
    assert result.decision == "PASS"
    assert result.normal_machine_recommendation == "next-patch"
    assert result.selected_version == "0.6.1"
    assert result.bootstrap_used is False


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"breaking_evidence": ["public-schema-field-removed"]}, "BREAKING_CHANGE_DETECTED"),
        ({"unknown_compatibility_evidence": ["consumer-proof-missing"]}, "COMPATIBILITY_UNKNOWN"),
    ],
)
def test_sv003_breaking_or_unknown_blocks_before_bootstrap(
    updates: dict[str, object], code: str
) -> None:
    value = _value(**updates)
    bootstrap = build_cr072_bootstrap(value)
    result = decide_semver(value, bootstrap)
    assert result.decision == "BLOCKED"
    assert result.bootstrap_used is False
    assert result.bootstrap_consumption_key == ""
    assert code in {item.code for item in result.diagnostics}


def test_sv004_exact_bootstrap_preserves_truthful_minor_and_selects_061() -> None:
    value = _value()
    bootstrap = build_cr072_bootstrap(value)
    result = decide_semver(value, bootstrap)
    assert result.decision == "PASS"
    assert result.normal_machine_recommendation == "next-minor"
    assert result.normal_recommended_version == "0.7.0"
    assert result.selected_version == "0.6.1"
    assert result.bootstrap_used is True
    assert len(result.bootstrap_consumption_key) == 64
    assert bootstrap.reusable is False
    assert bootstrap.enforce_after == "0.6.1"


def test_sv005_replay_is_deterministically_blocked() -> None:
    value = _value()
    bootstrap = build_cr072_bootstrap(value)
    first = decide_semver(value, bootstrap)
    replay = decide_semver(
        value,
        bootstrap,
        consumed_bootstrap_keys=[first.bootstrap_consumption_key],
    )
    assert replay.decision == "BLOCKED"
    assert [item.code for item in replay.diagnostics] == ["BOOTSTRAP_ALREADY_CONSUMED"]


def test_sv006_cross_version_bootstrap_is_blocked() -> None:
    value = _value(requested_version="0.6.2")
    bootstrap = build_cr072_bootstrap(value)
    result = decide_semver(value, bootstrap)
    assert result.decision == "BLOCKED"
    assert [item.code for item in result.diagnostics] == ["BOOTSTRAP_VERSION_MISMATCH"]


@pytest.mark.parametrize("field", ["source_digest", "plan_digest", "policy_digest"])
def test_sv007_bootstrap_binding_drift_is_blocked(field: str) -> None:
    value = _value()
    raw = build_cr072_bootstrap(value).as_dict()
    raw[field] = "e" * 64
    raw_without_digest = {key: item for key, item in raw.items() if key != "decision_digest"}
    from meta_flow.workflow.package_plan import canonical_digest

    raw["decision_digest"] = canonical_digest(raw_without_digest)
    bootstrap = SemVerBootstrapDecisionV1.from_mapping(raw)
    result = decide_semver(value, bootstrap)
    assert result.decision == "BLOCKED"
    assert [item.code for item in result.diagnostics] == [
        "BOOTSTRAP_BINDING_DIGEST_MISMATCH"
    ]


def test_sv008_closed_immutable_input_and_bootstrap_digest() -> None:
    raw = _mapping()
    value = SemVerDecisionInputV1.from_mapping(raw)
    raw["added_public_operations"].append("package.fake")  # type: ignore[union-attr]
    assert "package.fake" not in value.added_public_operations
    with pytest.raises(ValueError, match="SEMVER_INPUT_FIELDS_MISMATCH"):
        SemVerDecisionInputV1.from_mapping({**_mapping(), "extra": True})
    bootstrap_raw = build_cr072_bootstrap(value).as_dict()
    broken = copy.deepcopy(bootstrap_raw)
    broken["reusable"] = True
    with pytest.raises(ValueError, match="SEMVER_BOOTSTRAP_CONSTANT_MISMATCH"):
        SemVerBootstrapDecisionV1.from_mapping(broken)


def test_semver_public_cli_is_zero_write_and_uses_cp2_bootstrap(tmp_path) -> None:
    source = tmp_path / "input.json"
    source.write_text(json.dumps(_mapping(), sort_keys=True) + "\n", encoding="utf-8")
    before = source.read_bytes()
    output = StringIO()
    with redirect_stdout(output):
        exit_code = package_cli.main(
            [
                "semver-decide",
                "--cr",
                "CR-072",
                "--input",
                "input.json",
                "--requested-version",
                "0.6.1",
                "--bootstrap-ref",
                "docs/product/REQUIREMENTS.md#CP2-DQ-02-072",
                "--project-root",
                str(tmp_path),
                "--format",
                "json",
            ]
        )
    result = json.loads(output.getvalue())
    assert exit_code == 0
    assert result["decision"] == "PASS"
    assert result["normal_machine_recommendation"] == "next-minor"
    assert result["selected_version"] == "0.6.1"
    assert result["mutation_count"] == 0
    assert source.read_bytes() == before
