"""基于 worktree、命令、环境与分层证据裁决 full-regression 复用。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import _resolve_runtime_ref


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json_ref(project_root: Path, ref: str) -> tuple[dict[str, Any], str]:
    path = (
        _resolve_runtime_ref(project_root, ref)
        if ref.startswith("process/")
        else project_root / ref
    )
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"FULL_REUSE_INPUT_MISSING:{ref}")
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"FULL_REUSE_INPUT_INVALID:{ref}")
    return payload, _sha256(raw)


def _path_entry(path: Path, *, status: str) -> dict[str, str]:
    if path.is_symlink():
        return {
            "status": status,
            "kind": "symlink",
            "digest": _sha256(os.readlink(path).encode()),
        }
    if path.is_file():
        return {
            "status": status,
            "kind": "regular",
            "digest": _sha256(path.read_bytes()),
        }
    return {"status": status, "kind": "missing", "digest": "missing"}


def build_worktree_inventory(project_root: Path) -> dict[str, dict[str, str]]:
    root = project_root.resolve()
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "-uall"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise ValueError("FULL_REUSE_GIT_INVENTORY_UNAVAILABLE")
    parts = [item for item in completed.stdout.split(b"\0") if item]
    inventory: dict[str, dict[str, str]] = {}
    index = 0
    while index < len(parts):
        row = parts[index]
        if len(row) < 4:
            raise ValueError("FULL_REUSE_GIT_INVENTORY_INVALID")
        status = row[:2].decode("ascii")
        rel = row[3:].decode("utf-8", errors="surrogateescape")
        index += 1
        if status[0] in {"R", "C"}:
            if index >= len(parts):
                raise ValueError("FULL_REUSE_GIT_RENAME_INVALID")
            index += 1
        inventory[rel] = _path_entry(root / rel, status=status)
    return dict(sorted(inventory.items()))


def _normalize_uv_version(raw: str) -> str:
    """把 ``uv --version`` 的可选 target triplet 归一为语义版本。"""

    parts = raw.strip().split()
    if len(parts) >= 2 and parts[0] == "uv":
        return parts[1]
    return "unavailable"


def _current_environment() -> dict[str, str]:
    completed = subprocess.run(
        ["uv", "--version"], capture_output=True, text=True, check=False
    )
    uv_version = (
        _normalize_uv_version(completed.stdout)
        if completed.returncode == 0
        else "unavailable"
    )
    return {
        "platform": platform.system(),
        "python": f"{platform.python_implementation()} {platform.python_version()}",
        "uv": uv_version,
    }


def _validate_baseline(baseline: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if (
        baseline.get("kind") != "FullRegressionBaselineV1"
        or baseline.get("schema_version") != 1
    ):
        return ["BASELINE_SCHEMA_INVALID"]
    command = baseline.get("command")
    environment = baseline.get("environment")
    result = baseline.get("result")
    pending_cases = baseline.get("pending_cases")
    if not isinstance(command, Mapping) or not isinstance(environment, Mapping):
        return ["BASELINE_COMMAND_OR_ENVIRONMENT_INVALID"]
    command_digest = canonical_digest(command)
    environment_digest = canonical_digest(environment)
    profile = {
        "command_fingerprint": command_digest,
        "environment_fingerprint": environment_digest,
        "expected": {
            "passed": (result or {}).get("passed"),
            "deselected": (result or {}).get("deselected"),
            "warnings": (result or {}).get("warnings"),
            "subtests_passed": (result or {}).get("subtests_passed"),
        },
        "pending_cases": pending_cases,
    }
    if baseline.get("command_fingerprint") != command_digest:
        blockers.append("COMMAND_FINGERPRINT_INVALID")
    if baseline.get("environment_fingerprint") != environment_digest:
        blockers.append("ENVIRONMENT_FINGERPRINT_INVALID")
    if baseline.get("profile_fingerprint") != canonical_digest(profile):
        blockers.append("PROFILE_FINGERPRINT_INVALID")
    return blockers


def _post_full_impact_paths(
    baseline: Mapping[str, Any],
) -> tuple[tuple[str, ...], list[str]]:
    """只接纳 CR-072 已批准的验证元数据后置收敛路径。"""

    amendment = baseline.get("post_full_impact")
    if amendment is None:
        return (), []
    if not isinstance(amendment, Mapping):
        return (), ["POST_FULL_IMPACT_SCHEMA_INVALID"]
    paths = amendment.get("paths")
    if (
        amendment.get("policy") != "verification-metadata-only-v1"
        or not isinstance(paths, list)
        or not paths
        or any(not isinstance(path, str) or not path for path in paths)
        or len(paths) != len(set(paths))
    ):
        return (), ["POST_FULL_IMPACT_SCHEMA_INVALID"]
    # 该切片只允许把验证结果投影回产品矩阵；代码、测试、配置和发布
    # 合同都不能借此排除出 full fingerprint。
    allowed = {"docs/product/TEST-MATRIX.md"}
    invalid = sorted(set(paths) - allowed)
    if invalid:
        return (), ["POST_FULL_IMPACT_PATH_NOT_METADATA"]
    required = (
        "reason",
        "approval_source",
        "baseline_residual_count",
        "amended_residual_count",
        "amended_residual_fingerprint",
    )
    if any(amendment.get(field) in (None, "") for field in required):
        return (), ["POST_FULL_IMPACT_BINDING_INCOMPLETE"]
    return tuple(sorted(paths)), []


def assess_full_regression_reuse(
    project_root: Path,
    *,
    baseline_ref: str,
    targeted_evidence_ref: str,
) -> dict[str, Any]:
    root = project_root.resolve()
    baseline, baseline_digest = _read_json_ref(root, baseline_ref)
    targeted, targeted_digest = _read_json_ref(root, targeted_evidence_ref)
    blockers = _validate_baseline(baseline)
    if (
        targeted.get("kind") != "TargetedValidationEvidenceV1"
        or targeted.get("schema_version") != 1
    ):
        blockers.append("TARGETED_EVIDENCE_SCHEMA_INVALID")
    if targeted.get("cr_id") != baseline.get("cr_id"):
        blockers.append("TARGETED_EVIDENCE_CR_MISMATCH")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    current_head = head.stdout.strip() if head.returncode == 0 else ""
    if current_head != baseline.get("release_head_oid"):
        blockers.append("RELEASE_HEAD_DRIFT")
    current_environment = _current_environment()
    if canonical_digest(current_environment) != baseline.get(
        "environment_fingerprint"
    ):
        blockers.append("ENVIRONMENT_DRIFT")
    inventory = build_worktree_inventory(root)
    planned = tuple(str(item) for item in baseline.get("planned_impact_paths") or [])
    post_full_paths, post_full_blockers = _post_full_impact_paths(baseline)
    blockers.extend(post_full_blockers)
    raw_residual = {
        key: value for key, value in inventory.items() if key not in planned
    }
    raw_residual_fingerprint = canonical_digest(raw_residual)
    residual = {
        key: value
        for key, value in raw_residual.items()
        if key not in post_full_paths
    }
    residual_fingerprint = canonical_digest(residual)
    if post_full_paths:
        amendment = baseline.get("post_full_impact")
        assert isinstance(amendment, Mapping)
        if (
            len(raw_residual) != amendment.get("baseline_residual_count")
            or len(residual) != amendment.get("amended_residual_count")
            or residual_fingerprint
            != amendment.get("amended_residual_fingerprint")
            or any(path not in raw_residual for path in post_full_paths)
        ):
            blockers.append("POST_FULL_IMPACT_FINGERPRINT_INVALID")
    elif raw_residual_fingerprint != baseline.get(
        "baseline_residual_fingerprint"
    ):
        blockers.append("UNPLANNED_RELEASE_PATH_DRIFT")
    baseline_entries = baseline.get("baseline_impact_entries")
    if not isinstance(baseline_entries, Mapping) or set(baseline_entries) != set(
        planned
    ):
        blockers.append("BASELINE_IMPACT_ENTRIES_INVALID")
        baseline_entries = {}
    current_entries: dict[str, dict[str, str]] = {}
    changed_paths: list[str] = []
    for rel in planned:
        entry = inventory.get(rel)
        if entry is None:
            entry = _path_entry(
                root / rel,
                status="clean" if (root / rel).exists() else "absent",
            )
        current_entries[rel] = entry
        if entry != baseline_entries.get(rel):
            changed_paths.append(rel)
    for rel in post_full_paths:
        current_entries[rel] = raw_residual[rel]
        changed_paths.append(rel)
    commands = (
        targeted.get("commands")
        if isinstance(targeted.get("commands"), list)
        else []
    )
    layers = {
        str(item.get("layer"))
        for item in commands
        if isinstance(item, Mapping) and item.get("result") == "PASS"
    }
    if not {"targeted", "compatibility"}.issubset(layers):
        blockers.append("TARGETED_COMPATIBILITY_LAYERS_INCOMPLETE")
    covered: set[str] = set()
    for item in commands:
        if not isinstance(item, Mapping) or item.get("result") != "PASS":
            continue
        identity = item.get("identity")
        if (
            not isinstance(identity, Mapping)
            or item.get("command_identity_digest") != canonical_digest(identity)
        ):
            blockers.append("COMMAND_IDENTITY_DIGEST_INVALID")
            continue
        source_hashes = item.get("source_hashes")
        if not isinstance(source_hashes, Mapping):
            blockers.append("SOURCE_HASH_BINDING_MISSING")
            continue
        for rel, expected in source_hashes.items():
            if (
                rel not in current_entries
                or current_entries[rel].get("digest") != expected
            ):
                blockers.append(f"TARGETED_SOURCE_HASH_DRIFT:{rel}")
            else:
                covered.add(str(rel))
    uncovered = sorted(set(changed_paths) - covered)
    if uncovered:
        blockers.append("CHANGED_PATH_COVERAGE_INCOMPLETE")
    decision = "RERUN_REQUIRED" if blockers else "REUSE_ALLOWED"
    result = {
        "schema_version": 1,
        "kind": "FullRegressionReuseDecisionV1",
        "cr_id": baseline.get("cr_id"),
        "decision": decision,
        "baseline_ref": baseline_ref,
        "baseline_digest": baseline_digest,
        "targeted_evidence_ref": targeted_evidence_ref,
        "targeted_evidence_digest": targeted_digest,
        "source_fingerprint": canonical_digest(inventory),
        "raw_residual_fingerprint": raw_residual_fingerprint,
        "residual_fingerprint": residual_fingerprint,
        "baseline_residual_fingerprint": baseline.get(
            "baseline_residual_fingerprint"
        ),
        "command_fingerprint": baseline.get("command_fingerprint"),
        "environment_fingerprint": canonical_digest(current_environment),
        "profile_fingerprint": baseline.get("profile_fingerprint"),
        "changed_paths": sorted(changed_paths),
        "post_full_impact_paths": list(post_full_paths),
        "post_full_impact_policy": (
            (baseline.get("post_full_impact") or {}).get("policy")
            if post_full_paths
            else None
        ),
        "impact_classifications": {
            path: "verification-metadata-only" for path in post_full_paths
        },
        "uncovered_paths": uncovered,
        "blockers": sorted(set(blockers)),
        "full_rerun_count": 0 if decision == "REUSE_ALLOWED" else 1,
        "mutation_count": 0,
    }
    result["decision_digest"] = canonical_digest(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m meta_flow.checks.full_regression_reuse"
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--targeted-evidence", required=True)
    parsed = parser.parse_args(argv)
    try:
        result = assess_full_regression_reuse(
            parsed.project_root,
            baseline_ref=parsed.baseline,
            targeted_evidence_ref=parsed.targeted_evidence,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": 1,
            "kind": "FullRegressionReuseDecisionV1",
            "decision": "RERUN_REQUIRED",
            "blockers": [str(exc).split(":", 1)[0]],
            "mutation_count": 0,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["decision"] == "REUSE_ALLOWED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
