"""Deterministic shared fixtures for CR leaf owners and the compatibility facade.

This module intentionally declares no test case and imports no production
module.  It is a counted shared test-support leaf, not a behavior owner.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LifecycleFixtureCollaborators:
    """测试模块显式注入的 production collaborators。"""

    project_init_request: Callable[..., Any]
    plan_project_init: Callable[[Any], Any]
    apply_project_init: Callable[[Any, Any], Any]
    onboarding_authorization: Callable[..., Any]
    authorization_source: str
    authorization_kind: str
    resolve_runtime_ref: Callable[[Path, str], Path]
    dump_yaml: Callable[[Mapping[str, Any]], str]
    load_yaml_object: Callable[[Path], dict[str, Any]]
    work_scope: Callable[..., Any]


def normalize_compatibility_snapshot(value: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Return a deterministic string-only representation for seam assertions."""

    return tuple(sorted((str(key), str(item)) for key, item in value.items()))


def init_binding_project(
    root: Path,
    *,
    collaborators: LifecycleFixtureCollaborators,
) -> tuple[Path, Path]:
    """创建带 sibling binding 的 release/process 测试仓。"""

    release = root / "fixture-release"
    release.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=release,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        cwd=release,
        check=True,
        capture_output=True,
    )
    plan = collaborators.plan_project_init(
        collaborators.project_init_request(release, "fixture", "Fixture Project")
    )
    payload = plan.as_dict()
    collaborators.apply_project_init(
        plan,
        collaborators.onboarding_authorization(
            1,
            "cr-lifecycle-fixture",
            collaborators.authorization_source,
            collaborators.authorization_kind,
            payload["operation"],
            payload["decision_ref"],
            payload["project_id"],
            payload["plan_digest"],
            payload["base_oids"],
            "2099-01-01T00:00:00+00:00",
        ),
    )
    return release, root / "fixture-process"


def write_cr(
    root: Path,
    cr_id: str,
    *,
    collaborators: LifecycleFixtureCollaborators,
    status: str = "active",
    conflict_keys: str = "",
    impact_surface: str = "",
    extra_frontmatter: str = "",
) -> Path:
    """写入 deterministic formal CR fixture。"""

    path = collaborators.resolve_runtime_ref(root, f"process/changes/{cr_id}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
schema_version: 1
kind: cr
cr_id: "{cr_id}"
cr_type: "architecture"
title: "{cr_id} title"
lifecycle_status: "{status}"
readiness_status: "NOT_READY"
gate_status: "cp8_pending"
gate_profile: "standard-code"
conflict_keys: [{conflict_keys}]
impact_surface: [{impact_surface}]
authz_policy_refs: [NO_CREDENTIAL_READ]
risk_refs: [RISK-001]
{extra_frontmatter}
---

## 变更描述

本 CR 用于测试生命周期治理。
""",
        encoding="utf-8",
    )
    return path


def write_termination_fixture(
    root: Path,
    *,
    collaborators: LifecycleFixtureCollaborators,
    cr_id: str = "CR-101",
    work_id: str = "WORK-101",
) -> tuple[Path, Path, Path, Any]:
    """写入 CR status-sync/termination 共享事务 fixture。"""

    release, process = init_binding_project(root, collaborators=collaborators)
    subprocess.run(
        ["git", "add", "--all"],
        cwd=process,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "-m",
            "initial process truth",
        ],
        cwd=process,
        check=True,
        capture_output=True,
    )
    cr_path = write_cr(release, cr_id, collaborators=collaborators)
    phase_ref = "phases/P1-termination/PHASE.yaml"
    work_ref = f"works/{work_id}/WORK.yaml"
    scope = collaborators.work_scope(
        version=1,
        allowed_reads=(
            "PROJECT.yaml",
            phase_ref,
            work_ref,
            "archive/**",
            "changes/**",
            "state/**",
        ),
        allowed_writes=(
            "PROJECT.yaml",
            phase_ref,
            work_ref,
            "archive/**",
            "changes/**",
            "state/**",
        ),
        required_checks=("cr-termination",),
    )
    release_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=release,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    process_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=process,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    project = collaborators.load_yaml_object(process / "PROJECT.yaml")
    project["active_phase_ref"] = phase_ref
    project["active_work_refs"] = [work_ref]
    (process / "PROJECT.yaml").write_text(
        collaborators.dump_yaml(project) + "\n",
        encoding="utf-8",
    )
    phase_path = process / phase_ref
    phase_path.parent.mkdir(parents=True, exist_ok=True)
    phase_path.write_text(
        collaborators.dump_yaml(
            {
                "schema_version": 1,
                "project_id": "fixture",
                "phase_id": "P1-termination",
                "objective": "验证原生 CR 终止事务",
                "status": "active",
                "work_refs": [work_ref],
                "result_refs": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    work_path = process / work_ref
    work_path.parent.mkdir(parents=True, exist_ok=True)
    work_path.write_text(
        collaborators.dump_yaml(
            {
                "schema_version": 1,
                "work_id": work_id,
                "project_id": "fixture",
                "kind": "cr",
                "objective": "验证原生 CR 终止事务",
                "status": "active",
                "request_ref": f"works/{work_id}/REQUEST.md",
                "request_confirmed": True,
                "phase_ref": phase_ref,
                "risk_profile": "G2",
                "risk_reason_codes": ["PUBLIC_CONTRACT"],
                "required_gates": ["GATE-DESIGN"],
                "scope": scope.as_dict(),
                "scope_digest": scope.digest,
                "budget": {
                    "reads": 20,
                    "writes": 20,
                    "check_groups": 4,
                    "tokens": 100000,
                },
                "usage_ref": f"works/{work_id}/USAGE.json",
                "base_oids": {
                    "release": release_oid,
                    "process": process_oid,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    request_path = process / "works" / work_id / "REQUEST.md"
    request_path.write_text("# fixture\n", encoding="utf-8")
    return release, process, cr_path, scope
