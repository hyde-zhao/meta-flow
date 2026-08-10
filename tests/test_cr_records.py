from __future__ import annotations  # noqa: I001

import ast
import inspect
import subprocess
from pathlib import Path

from meta_flow.workflow import cr_lifecycle, cr_records


RECORD_MEMBERS = {
    "LEGACY_SOURCE_REL", "CR_SUMMARY_ROOT_REL", "IMPACT_SURFACE_RULES_REL", "IMPACT_SPLIT_FIELDS",
    "OPEN_DEPENDENCY_STATUSES", "GOVERNANCE_BASELINE_MARKERS", "CP1_PRODUCT_BASELINE_DOCS",
    "CP1_FULL_REQUIRED_CHECKS", "CP1_LIGHTWEIGHT_REQUIRED_CHECKS", "ARCHIVE_BACKUP_PATH_MARKERS",
    "HOUSEKEEPING_CR_MARKERS", "update_frontmatter_fields", "_rel", "_process_root", "_cr_id_from_path",
    "_resolve_capability_refs", "_normalized_capability_refs", "_capability_blockers", "_unique",
    "_impact_split_payload", "_categorized_legacy_impact", "_legacy_impact_category", "_builtin_legacy_impact_category",
    "_project_legacy_impact_category", "_apply_impact_rule", "_uncategorized_legacy_impact",
    "_impact_followup_candidates", "_merge_impact_fields", "_effective_impact_fields", "_extract_section_lines",
    "_section_summary", "_body_text", "_record_required_evidence", "collect_scope_authz_findings",
    "_governance_dependency_values", "_governance_markers", "_is_open_governance_baseline_cr",
    "collect_governance_dependency_findings", "classify_cp1_review_profile", "_archive_backup_refs",
    "_is_housekeeping_cr", "collect_archive_isolation_findings", "_first_section_summary", "discover_formal_crs",
    "record_from_cr_file", "_git_fact", "_load_json_object",
}

ALLOWED_EXTERNALS = {
    "meta_flow.design.feature_registry", "meta_flow.policies.authz",
    "meta_flow.project.process_route.format_runtime_ref",
    "meta_flow.project.process_route._resolve_runtime_ref",
    "meta_flow.project.scale.load_yaml_object", "meta_flow.workspace.git_sync.run_git",
}


def _write_cr(
    root: Path,
    cr_id: str,
    *,
    status: str = "active",
    extra_frontmatter: str = "",
) -> Path:
    path = root / "process" / "changes" / f"{cr_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''---
schema_version: 1
kind: cr
cr_id: "{cr_id}"
cr_type: "architecture"
title: "{cr_id} title"
lifecycle_status: "{status}"
readiness_status: "NOT_READY"
gate_status: "cp8_pending"
gate_profile: "standard"
conflict_keys: []
impact_surface: []
authz_policy_refs: [NO_CREDENTIAL_READ]
risk_refs: [RISK-001]
{extra_frontmatter}
---

## 变更描述

本 CR 用于测试生命周期治理。
''',
        encoding="utf-8",
    )
    return path


def _write_impact_rules(root: Path) -> None:
    path = root / cr_records.IMPACT_SURFACE_RULES_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '''schema_version: 1
rules:
  - match: prefix
    pattern: MOD-
    target_field: impact_module_paths
    strip_prefix: true
  - match: prefix
    pattern: SVC-
    target_field: impact_runtime_refs
''',
        encoding="utf-8",
    )


def test_records_exact_owner_allowlist_and_facade_reexport() -> None:
    tree = ast.parse(Path(cr_records.__file__).read_text(encoding="utf-8"))
    owned = {
        node.name if isinstance(node, ast.FunctionDef) else node.targets[0].id
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.Assign))
    }
    imports = {
        f"{node.module}.{alias.name}"
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("meta_flow")
        for alias in node.names
    }
    assert RECORD_MEMBERS <= owned
    assert len(RECORD_MEMBERS) == 47
    assert {value for value in imports if not value.startswith("meta_flow.workflow.cr_model.")} == ALLOWED_EXTERNALS
    assert cr_lifecycle.CR_SUMMARY_ROOT_REL is cr_records.CR_SUMMARY_ROOT_REL
    assert cr_lifecycle._load_json_object is cr_records._load_json_object


def test_records_call_time_collaborators_are_optional_and_not_captured(tmp_path: Path) -> None:
    discover_parameters = inspect.signature(cr_records.discover_formal_crs).parameters
    record_parameters = inspect.signature(cr_records.record_from_cr_file).parameters
    assert discover_parameters["_resolve_runtime_ref_fn"].default is None
    assert discover_parameters["_rel_fn"].default is None
    assert record_parameters["_rel_fn"].default is None

    changes = tmp_path / "process" / "changes"
    changes.mkdir(parents=True)
    cr_path = changes / "CR-901.md"
    cr_path.write_text(
        '---\ncr_id: "CR-901"\ncr_type: "refactor"\nstatus: "active"\n---\n',
        encoding="utf-8",
    )

    assert cr_records.discover_formal_crs(tmp_path) == {"CR-901": cr_path}
    assert cr_records.record_from_cr_file(tmp_path, cr_path).full_ref == (
        "process/changes/CR-901.md"
    )


def test_governance_dependency_findings_are_owned_by_records(tmp_path: Path) -> None:
    _write_cr(
        tmp_path,
        "CR-200",
        extra_frontmatter=(
            'cr_type: "process"\n'
            'conflict_keys: ["governance-authz"]\n'
            'impact_process_refs: ["process/policies/AUTHZ.md"]'
        ),
    )
    target_path = _write_cr(
        tmp_path,
        "CR-201",
        extra_frontmatter='impact_process_refs: ["process/policies/AUTHZ.md"]',
    )
    target = cr_records.record_from_cr_file(tmp_path, target_path)

    findings = cr_records.collect_governance_dependency_findings(tmp_path, target)

    assert findings[0]["code"] == "open_governance_dependency_needs_review"
    assert findings[0]["decision"] == "NEEDS_REVIEW"
    assert findings[0]["governance_cr"] == "CR-200"


def test_archive_isolation_findings_are_owned_by_records(tmp_path: Path) -> None:
    path = _write_cr(
        tmp_path,
        "CR-212",
        extra_frontmatter=(
            'cr_type: "feature"\n'
            'impact_process_refs: ["process/archive/legacy-migration/old.md"]'
        ),
    )
    record = cr_records.record_from_cr_file(tmp_path, path)

    findings = cr_records.collect_archive_isolation_findings(record)

    assert findings[0]["code"] == "archive_backup_scope_needs_isolation"
    assert findings[0]["decision"] == "NEEDS_REVIEW"
    assert findings[0]["archive_refs"] == [
        "process/archive/legacy-migration/old.md"
    ]


def test_project_impact_classification_is_owned_by_records(tmp_path: Path) -> None:
    _write_impact_rules(tmp_path)

    derived = cr_records._categorized_legacy_impact(
        ["MOD-meta_flow/project/rules.py", "SVC-order-router"],
        project_root=tmp_path,
    )

    assert derived["impact_module_paths"] == ["meta_flow/project/rules.py"]
    assert derived["impact_runtime_refs"] == ["SVC-order-router"]
    assert all(
        values == []
        for field, values in derived.items()
        if field not in {"impact_module_paths", "impact_runtime_refs"}
    )


def test_path_and_git_facts_are_owned_by_records(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
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
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    cr_path = _write_cr(tmp_path, "CR-214")

    expected_head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert cr_records._git_fact(tmp_path, "rev-parse", "--verify", "HEAD") == (
        expected_head
    )
    assert cr_records._git_fact(tmp_path, "branch", "--show-current") == "main"
    assert cr_records._rel(tmp_path, cr_path) == "process/changes/CR-214.md"
