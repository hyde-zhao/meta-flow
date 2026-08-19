from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from meta_flow.checks import full_regression_reuse
from meta_flow.project.onboarding_contract import canonical_digest


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def test_uv_version_normalization_ignores_optional_target_triplet() -> None:
    assert full_regression_reuse._normalize_uv_version("uv 0.11.6\n") == "0.11.6"
    assert (
        full_regression_reuse._normalize_uv_version(
            "uv 0.11.6 (x86_64-unknown-linux-gnu)\n"
        )
        == "0.11.6"
    )
    assert full_regression_reuse._normalize_uv_version("unexpected") == "unavailable"


def _fixture(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "release"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "Fixture")
    (root / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "target.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "core.py", "target.py")
    _git(root, "commit", "-m", "baseline")
    exclude = root / ".git/info/exclude"
    exclude.write_text(exclude.read_text(encoding="utf-8") + "\nevidence/\n", encoding="utf-8")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    environment = full_regression_reuse._current_environment()
    command = {
        "runner": ["uv"],
        "argv": ["pytest", "-q"],
        "environment_overrides": {},
    }
    result = {
        "passed": 1,
        "deselected": 0,
        "warnings": 0,
        "subtests_passed": 0,
    }
    profile = {
        "command_fingerprint": canonical_digest(command),
        "environment_fingerprint": canonical_digest(environment),
        "expected": result,
        "pending_cases": [],
    }
    baseline = {
        "schema_version": 1,
        "kind": "FullRegressionBaselineV1",
        "cr_id": "CR-TEST",
        "release_head_oid": head,
        "command": command,
        "environment": environment,
        "result": result,
        "pending_cases": [],
        "command_fingerprint": canonical_digest(command),
        "environment_fingerprint": canonical_digest(environment),
        "profile_fingerprint": canonical_digest(profile),
        "baseline_residual_fingerprint": canonical_digest({}),
        "planned_impact_paths": ["target.py"],
        "baseline_impact_entries": {
            "target.py": {
                "status": "clean",
                "kind": "regular",
                "digest": hashlib.sha256(b"VALUE = 1\n").hexdigest(),
            }
        },
    }
    baseline_ref = "evidence/baseline.json"
    evidence_ref = "evidence/targeted.json"
    _write_json(root / baseline_ref, baseline)
    return root, baseline_ref, evidence_ref


def test_reuse_allows_only_planned_drift_with_two_layer_hash_binding(
    tmp_path: Path,
) -> None:
    root, baseline_ref, evidence_ref = _fixture(tmp_path)
    (root / "target.py").write_text("VALUE = 2\n", encoding="utf-8")
    digest = hashlib.sha256(b"VALUE = 2\n").hexdigest()
    commands = []
    for layer in ("targeted", "compatibility"):
        identity = {"runner": "pytest", "argv": [layer]}
        commands.append(
            {
                "layer": layer,
                "result": "PASS",
                "identity": identity,
                "command_identity_digest": canonical_digest(identity),
                "source_hashes": {"target.py": digest},
            }
        )
    _write_json(
        root / evidence_ref,
        {
            "schema_version": 1,
            "kind": "TargetedValidationEvidenceV1",
            "cr_id": "CR-TEST",
            "commands": commands,
        },
    )

    result = full_regression_reuse.assess_full_regression_reuse(
        root,
        baseline_ref=baseline_ref,
        targeted_evidence_ref=evidence_ref,
    )

    assert result["decision"] == "REUSE_ALLOWED"
    assert result["changed_paths"] == ["target.py"]
    assert result["full_rerun_count"] == 0


def test_reuse_requires_full_when_residual_path_drifts(tmp_path: Path) -> None:
    root, baseline_ref, evidence_ref = _fixture(tmp_path)
    (root / "core.py").write_text("VALUE = 2\n", encoding="utf-8")
    _write_json(
        root / evidence_ref,
        {
            "schema_version": 1,
            "kind": "TargetedValidationEvidenceV1",
            "cr_id": "CR-TEST",
            "commands": [],
        },
    )

    result = full_regression_reuse.assess_full_regression_reuse(
        root,
        baseline_ref=baseline_ref,
        targeted_evidence_ref=evidence_ref,
    )

    assert result["decision"] == "RERUN_REQUIRED"
    assert "UNPLANNED_RELEASE_PATH_DRIFT" in result["blockers"]


def test_reuse_allows_explicit_test_matrix_projection_after_full(
    tmp_path: Path,
) -> None:
    root, baseline_ref, evidence_ref = _fixture(tmp_path)
    matrix = root / "docs/product/TEST-MATRIX.md"
    matrix.parent.mkdir(parents=True)
    matrix.write_text("covered\n", encoding="utf-8")
    baseline_path = root / baseline_ref
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    inventory = full_regression_reuse.build_worktree_inventory(root)
    residual = {
        key: value
        for key, value in inventory.items()
        if key not in {"target.py", "docs/product/TEST-MATRIX.md"}
    }
    baseline["post_full_impact"] = {
        "policy": "verification-metadata-only-v1",
        "paths": ["docs/product/TEST-MATRIX.md"],
        "reason": "fixture coverage projection",
        "approval_source": "user:fixture",
        "baseline_residual_count": len(residual) + 1,
        "amended_residual_count": len(residual),
        "amended_residual_fingerprint": canonical_digest(residual),
    }
    _write_json(baseline_path, baseline)
    matrix_digest = hashlib.sha256(b"covered\n").hexdigest()
    identity = {"runner": "git", "argv": ["diff", "--check"]}
    _write_json(
        root / evidence_ref,
        {
            "schema_version": 1,
            "kind": "TargetedValidationEvidenceV1",
            "cr_id": "CR-TEST",
            "commands": [
                {
                    "layer": "targeted",
                    "result": "PASS",
                    "identity": identity,
                    "command_identity_digest": canonical_digest(identity),
                    "source_hashes": {
                        "docs/product/TEST-MATRIX.md": matrix_digest
                    },
                },
                {
                    "layer": "compatibility",
                    "result": "PASS",
                    "identity": identity,
                    "command_identity_digest": canonical_digest(identity),
                    "source_hashes": {
                        "docs/product/TEST-MATRIX.md": matrix_digest
                    },
                },
            ],
        },
    )

    result = full_regression_reuse.assess_full_regression_reuse(
        root,
        baseline_ref=baseline_ref,
        targeted_evidence_ref=evidence_ref,
    )

    assert result["decision"] == "REUSE_ALLOWED"
    assert result["post_full_impact_paths"] == ["docs/product/TEST-MATRIX.md"]
    assert result["impact_classifications"] == {
        "docs/product/TEST-MATRIX.md": "verification-metadata-only"
    }


def test_reuse_rejects_post_full_runtime_path_exclusion(tmp_path: Path) -> None:
    root, baseline_ref, evidence_ref = _fixture(tmp_path)
    baseline_path = root / baseline_ref
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline["post_full_impact"] = {
        "policy": "verification-metadata-only-v1",
        "paths": ["core.py"],
        "reason": "invalid runtime exclusion",
        "approval_source": "user:fixture",
        "baseline_residual_count": 0,
        "amended_residual_count": 0,
        "amended_residual_fingerprint": canonical_digest({}),
    }
    _write_json(baseline_path, baseline)
    _write_json(
        root / evidence_ref,
        {
            "schema_version": 1,
            "kind": "TargetedValidationEvidenceV1",
            "cr_id": "CR-TEST",
            "commands": [],
        },
    )

    result = full_regression_reuse.assess_full_regression_reuse(
        root,
        baseline_ref=baseline_ref,
        targeted_evidence_ref=evidence_ref,
    )

    assert result["decision"] == "RERUN_REQUIRED"
    assert "POST_FULL_IMPACT_PATH_NOT_METADATA" in result["blockers"]
