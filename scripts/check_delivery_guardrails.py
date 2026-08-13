#!/usr/bin/env python3
"""Check repository guardrails for delivery asset ownership and Python cache hygiene."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

ROOT = Path(__file__).resolve().parent.parent
DELIVERY_ROOT = ROOT / "delivery"
PROCESS_ROOT = ROOT / "process"
CHANGE_ROOT = PROCESS_ROOT / "changes"
PLATFORM_CONTRACTS = DELIVERY_ROOT / "doc" / "PLATFORM-CONTRACTS.yaml"
DELIVERY_RUNTIME_CONTRACT = DELIVERY_ROOT / "rules" / "DELIVERY-RUNTIME-CONTRACT.json"
CORE_LIFECYCLE_DOGFOOD_COMMAND = (
    "PYTHONDONTWRITEBYTECODE=1 uv run --python 3.11 python "
    "scripts/check_core_lifecycle_dogfood.py"
)
CORE_LIFECYCLE_DOGFOOD_FILES = (
    "tests/fixtures/core_lifecycle_dogfood.py",
    "scripts/check_core_lifecycle_dogfood.py",
    "tests/test_core_lifecycle_dogfood.py",
)
CORE_LIFECYCLE_DOGFOOD_DOCS = (
    "README.md",
    "delivery/README.md",
    "delivery/doc/USER-MANUAL.md",
)
ALLOWED_DELIVERY_DIRS = {"agents", "doc", "rules", "scripts", "skills"}
ALLOWED_DELIVERY_SCRIPT_FILES = {
    "install-cli.py",
    "install.py",
    "install.sh",
    "install.ps1",
}
INSTALLATION_ROLE_REGISTRY = {
    "delivery/rules/AGENTS.md": "rules_source",
    "delivery/doc/RULES-SEMANTIC-INVENTORY.json": "rules_source",
    "delivery/doc/RULES-EQUIVALENCE.json": "rules_source",
    "tests/test_rules_slimming_contract.py": "contract_test",
    "meta_flow/installation/contracts.py": "canonical_contract",
    "meta_flow/installation/canonical.py": "canonical_contract",
    "meta_flow/installation/identity.py": "source_identity",
    "tests/test_install_plan_contract.py": "contract_test",
    "meta_flow/installation/manifest.py": "manifest_ownership",
    "meta_flow/installation/ownership.py": "manifest_ownership",
    "tests/test_install_manifest_v2.py": "contract_test",
    "meta_flow/installation/planner.py": "checkpoint_planner",
    "meta_flow/installation/authorization.py": "authorization_dispatch",
    "meta_flow/installation/engine.py": "authorization_dispatch",
    "tests/test_install_authorization.py": "contract_test",
    "meta_flow/installation/asset_executor.py": "asset_executor",
    "delivery/scripts/install.py": "public_adapter",
    "tests/test_install_asset_ownership.py": "contract_test",
    "meta_flow/installation/cli_executor.py": "cli_executor",
    "delivery/scripts/install-cli.py": "public_adapter",
    "meta_flow/cli.py": "public_adapter",
    "tests/test_cli_lifecycle.py": "contract_test",
    "meta_flow/installation/recovery.py": "durable_recovery",
    "tests/test_install_recovery.py": "contract_test",
    "meta_flow/installation/migration.py": "migration_adapter",
    "tests/test_install_migration.py": "contract_test",
    "tests/fixtures/gov006/CASE-REGISTRY.json": "case_registry",
    "tests/test_gov006_case_registry.py": "contract_test",
    "tests/fixtures/gov006/matrix-fixtures.json": "case_registry",
    "tests/test_gov006_lifecycle_matrix.py": "contract_test",
    "tests/fixtures/gov006/fixture_runner.py": "isolated_fixture",
    "tests/test_gov006_isolated_e2e.py": "contract_test",
    "delivery/doc/PLATFORM-CONTRACTS.yaml": "platform_contract",
    "README.md": "lifecycle_docs",
    "delivery/README.md": "lifecycle_docs",
    "delivery/doc/USER-MANUAL.md": "lifecycle_docs",
    "scripts/check_delivery_guardrails.py": "guardrail_owner",
    "meta_flow/installation/__init__.py": "compatibility_facade",
    "tests/test_delivery_guardrails.py": "guardrail_test",
}
INSTALLATION_DISCOVERY_ROOTS = (
    "meta_flow",
    "delivery/scripts",
    "scripts",
    "tests",
)
INSTALLATION_FIXTURE_EXCLUSIONS = {
    "tests/fixtures/gov006/fixture_runner.py": (
        "task-specific temp runtime cleanup may use shutil.rmtree; "
        "real HOME/external roots are rejected first"
    ),
}
REVISION_RECORD_TARGETS = {
    "docs/product/USE-CASES.md": ROOT / "docs" / "product" / "USE-CASES.md",
    "docs/product/REQUIREMENTS.md": ROOT / "docs" / "product" / "REQUIREMENTS.md",
}
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
MANAGED_MARKDOWN_LINE_RE = re.compile(
    r"^<!-- myflow-managed: version=1\.0\.0 "
    r"canonical-commit=(?:unknown|[0-9a-f]{4,40}) "
    r"generated=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z -->$",
    re.MULTILINE,
)
SKILL_ROOT_ASSET_REF_RE = re.compile(r"<skill-root>/(?P<kind>templates|scripts)/(?P<path>[A-Za-z0-9_./-]+)")
TEMPLATE_REF_RE = re.compile(r"(?<![A-Za-z0-9_./-])templates/(?P<path>[A-Za-z0-9_./-]+)")
DELIVERY_SCRIPT_REF_RE = re.compile(r"delivery/scripts/(?P<name>[A-Za-z0-9_.-]+)")
CODEX_CONFIRMATION_TOKENS = (
    "request_user_input",
    "approve",
    "修改: <具体修改点>",
    "reject",
    "别名",
    "待人工决策",
    "决策类型",
    "备选方案",
    "优劣",
    "不授权项",
)
DELIVERY_ROUTING_TOKENS = ("production", "README", "docs", "交付")
GUARDRAIL_CONDITION_TOKENS = ("仅当当前仓库存在", "外部 production 项目不得硬引用")
BINDING_ALL_PROFILES_TOKEN = "vNext binding-only 适用于 G0/G1/G2"
BINDING_LEGACY_SELECTION_TOKEN = "人工门显式选择"
PROCESS_ROUTE_CONTRACT_TOKENS = (
    "## vNext 过程引用契约",
    "meta-flow project resolve-ref",
    "resolved_path",
    "不得自行拼 sibling",
    "不构造 legacy capability",
)
PROCESS_ROUTE_AGENT_TARGETS = (
    "delivery/agents/README.md",
    "delivery/agents/meta-dev.md",
    "delivery/agents/meta-doc.md",
    "delivery/agents/meta-pm.md",
    "delivery/agents/meta-qa.md",
    "delivery/agents/meta-se.md",
)
LEGACY_PROCESS_JOIN_ALLOWLIST = {
    "meta_flow/checks/adoption_readiness.py",
    "meta_flow/cli.py",
    "meta_flow/project/scaffold.py",
    "meta_flow/workspace/project_artifact_routing.py",
    "meta_flow/workspace/routing.py",
}
NON_GIT_FIXTURE_JOIN_LINE = (
    'legacy_link = root / "process"  # guardrail: legacy-non-git-fixture-only'
)
DIRECT_PROCESS_JOIN_RE = re.compile(
    r"(?:project_root|root|artifact_root)\s*/\s*(?:Path\()?['\"]process(?:/|['\"])"
)
SOFTWARE_WORKFLOW_REQUIRED_FILES = (
    "delivery/skills/blueprint-design/SKILL.md",
    "delivery/skills/blueprint-design/templates/BLUEPRINT-TEMPLATE.md",
    "delivery/skills/blueprint-design/templates/DOMAIN-MAP-TEMPLATE.md",
    "delivery/skills/blueprint-design/templates/DEPENDENCY-MAP-TEMPLATE.md",
    "delivery/skills/implementation-design/SKILL.md",
    "delivery/skills/implementation-design/templates/FEATURE-DESIGN-MATRIX-TEMPLATE.md",
    "delivery/skills/implementation-design/templates/FEATURE-DESIGN-TEMPLATE.md",
    "delivery/skills/implementation-design/templates/TEST-PLAN-TEMPLATE.md",
    "delivery/skills/implementation-design/templates/TASKS-TEMPLATE.md",
    "delivery/skills/lld-designer/SKILL.md",
    "delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md",
    "delivery/skills/lld-designer/templates/BATCH-LLD-TEMPLATE.md",
    "delivery/skills/implementation-execution/SKILL.md",
    "delivery/skills/implementation-execution/templates/IMPLEMENTATION-TEMPLATE.md",
    "delivery/skills/verification-execution/SKILL.md",
    "delivery/skills/verification-execution/templates/VERIFICATION-TEMPLATE.md",
    "delivery/skills/quality-review/SKILL.md",
    "delivery/skills/quality-review/templates/TEST-REPORT-TEMPLATE.md",
    "delivery/skills/quality-review/templates/REVIEW-TEMPLATE.md",
    "delivery/skills/quality-review/templates/FIXES-TEMPLATE.md",
    "delivery/skills/release-readiness/SKILL.md",
    "delivery/skills/release-readiness/templates/RELEASE-CONTEXT-TEMPLATE.yaml",
    "delivery/skills/release-readiness/templates/RELEASE-NOTES-TEMPLATE.md",
    "delivery/skills/release-readiness/templates/DEPLOY-CHECKLIST-TEMPLATE.md",
    "delivery/skills/release-readiness/templates/ROLLBACK-TEMPLATE.md",
    "delivery/skills/release-readiness/templates/MIGRATION-TEMPLATE.md",
    "delivery/skills/release-readiness/templates/FEEDBACK-TEMPLATE.md",
    "delivery/skills/context-manifest-builder/templates/CONTEXT-CAPSULE-TEMPLATE.yaml",
    "delivery/skills/scenario-expansion/templates/SCENARIOS-TEMPLATE.yaml",
    "delivery/skills/scenario-expansion/templates/TEST-MATRIX-TEMPLATE.md",
    "delivery/skills/story-planning/SKILL.md",
    "delivery/skills/story-planning/templates/STORY-MAP-TEMPLATE.md",
    "delivery/skills/story-planning/templates/MVP-SCOPE-TEMPLATE.md",
    "delivery/skills/story-planning/templates/RELEASE-SLICES-TEMPLATE.md",
    "delivery/skills/story-planning/templates/BACKLOG-TEMPLATE.md",
)
AGENT_SKILL_CONTRACT_REQUIRED_FILES = (
    "delivery/rules/AGENT-SKILL-CONTRACT.md",
    "delivery/rules/DIRECTORY-CONTRACT.md",
    "delivery/rules/DIRECTORY-CONTRACT.yaml",
)
CONTEXT_BUDGETED_E2E_REQUIRED_FILES = (
    "evals/fixtures/context-budgeted-meta-flow/README.md",
    "evals/fixtures/context-budgeted-meta-flow/process/state/STATE.current.json",
    "evals/fixtures/context-budgeted-meta-flow/process/state/CR-LEDGER.ndjson",
    "evals/fixtures/context-budgeted-meta-flow/process/state/AGENT-DISPATCH-LEDGER.ndjson",
    "evals/fixtures/context-budgeted-meta-flow/process/state/CHECKPOINT-LEDGER.ndjson",
    "evals/fixtures/context-budgeted-meta-flow/process/policies/READ-POLICY.json",
    "evals/fixtures/context-budgeted-meta-flow/process/changes/summaries/CR-001.summary.json",
    "evals/fixtures/context-budgeted-meta-flow/process/changes/CR-001.md",
    "evals/fixtures/context-budgeted-meta-flow/process/STATE.md",
    "evals/fixtures/context-budgeted-meta-flow/process/DEVELOPMENT-PLAN.yaml",
    "evals/fixtures/context-budgeted-meta-flow/process/stories/STORY-MF013-S01.md",
    "evals/fixtures/context-budgeted-meta-flow/process/returns/STORY-MF013-S01.CP6.return.json",
    "evals/fixtures/context-budgeted-meta-flow/process/evidence/STORY-MF013-S01.CP6.index.json",
    "evals/fixtures/context-budgeted-meta-flow/process/checks/CP6-STORY-MF013-S01.result.json",
    "evals/fixtures/context-budgeted-meta-flow/docs/design/FEATURE-REGISTRY.yaml",
    "evals/fixtures/context-budgeted-meta-flow/docs/features/context-budgeted-flow/DESIGN.md",
    "tests/test_context_budgeted_flow_e2e.py",
)
GOVERNANCE_LIFECYCLE_REQUIRED_FILES = (
    "meta_flow/policies/governance.py",
    "delivery/skills/context-manifest-builder/templates/SOURCE-OF-TRUTH-MAP-TEMPLATE.yaml",
    "delivery/skills/context-manifest-builder/templates/SOURCE-OF-TRUTH-MAP-DOC-TEMPLATE.md",
    "delivery/skills/context-manifest-builder/templates/RETENTION-POLICY-TEMPLATE.json",
    "delivery/skills/implementation-design/templates/FEATURE-REGISTRY-TEMPLATE.yaml",
    "delivery/skills/blueprint-design/templates/CONCEPT-OWNERS-TEMPLATE.yaml",
    "delivery/skills/change-impact-analysis/templates/CR-TEMPLATE.md",
    "tests/test_governance_policies.py",
)
GOVERNANCE_LIFECYCLE_TOKEN_TARGETS = {
    "meta_flow/policies/governance.py": (
        "SOURCE_OF_TRUTH_REL",
        "RETENTION_POLICY_REL",
        "process/STATE.md must not be machine_truth",
        "closed_cr.default_context must be summary_only",
        "truth-map-check",
        "truth-map-render",
        "retention-check",
    ),
    "meta_flow/cli.py": (
        "governance Validate source-of-truth and retention lifecycle policies",
        "truth-map",
        "retention-policy",
        "_run_governance",
    ),
    "delivery/skills/context-manifest-builder/templates/SOURCE-OF-TRUTH-MAP-TEMPLATE.yaml": (
        "process/policies/SOURCE-OF-TRUTH-MAP.yaml",
        "process/state/STATE.current.json",
        "process/STATE.md",
        "append_only_event_log",
        "generated_summary",
        "process/checks/*.result.json",
    ),
    "delivery/skills/context-manifest-builder/templates/RETENTION-POLICY-TEMPLATE.json": (
        "summary_only",
        "keep_latest_in_default_context",
        "high-risk-only",
        "latest-window-or-index",
    ),
    "delivery/skills/implementation-design/templates/FEATURE-REGISTRY-TEMPLATE.yaml": (
        "product_domain",
        "capability",
        "design_doc_policy",
    ),
    "delivery/skills/blueprint-design/templates/CONCEPT-OWNERS-TEMPLATE.yaml": (
        "conflict_keys",
        "legacy_aliases",
        "forbidden_aliases",
    ),
    "delivery/skills/change-impact-analysis/templates/CR-TEMPLATE.md": (
        "cr_type",
        "product-scope",
        "architecture",
        "runtime-high-risk",
        "Checkpoint Index",
        "process/checks/CP*.result.json",
        "process/checkpoints/CP*.md",
        "CHECKPOINT-LEDGER.ndjson",
        "GATE-LEDGER.ndjson",
    ),
    "delivery/README.md": (
        "Governance Truth Map",
        "process/policies/SOURCE-OF-TRUTH-MAP.yaml",
        "RETENTION-POLICY.json",
        "design_doc_policy",
        "cr_type",
    ),
    "docs/release/RELEASE-NOTES.md": (
        "Governance Truth Map",
        "Retention Policy",
        "cr_type",
        "conflict_keys",
    ),
    "tests/test_governance_policies.py": (
        "validate_truth_map",
        "validate_retention_policy",
        "truth-map-render",
        "process/STATE.md must not be machine_truth",
    ),
}
CONTEXT_SUFFICIENCY_REQUIRED_FILES = (
    "meta_flow/context_pack/read_expansion.py",
    "meta_flow/checks/context_doctor.py",
    "delivery/skills/context-manifest-builder/templates/STORY-CONTEXT-PACKET-TEMPLATE.json",
    "delivery/skills/context-manifest-builder/templates/READ-POLICY-TEMPLATE.json",
    "delivery/skills/context-manifest-builder/templates/ARTIFACT-BUDGETS-TEMPLATE.json",
    "tests/test_context_sufficiency_read_expansion.py",
)
CONTEXT_SUFFICIENCY_TOKEN_TARGETS = {
    "meta_flow/context_pack/story_contract.py": (
        "validate_context_sufficiency",
        "STRICT_SUFFICIENCY_PROFILES",
        "feature_contract_summary",
        "cr_delta.summary",
        "dependency_inputs",
        "sufficiency-check",
    ),
    "meta_flow/context_pack/read_expansion.py": (
        "READ_EXPANSION_LEDGER_REL",
        "read_expansion",
        "full_doc_read_allowed_when",
        "estimated_tokens",
        "summary_update_recommendations",
        "read-log-check",
    ),
    "meta_flow/checks/context_doctor.py": (
        "frequently_expanded_files",
        "frequently_expanded_features",
        "missing_context_slots",
        "expansion_reason_distribution",
        "summary_update_recommendations",
    ),
    "meta_flow/checks/cp_result.py": (
        "read_expansion_refs",
        "deny-default references require read_expansion_refs",
        "READ-EXPANSION-LEDGER",
    ),
    "meta_flow/checks/token_budget.py": (
        "output_profiles",
        "story_return_summary",
        "feature_design_summary",
    ),
    "meta_flow/workflow/story_evidence.py": (
        "partial",
        "needs_user_decision",
        "no_op",
        "superseded",
    ),
    "meta_flow/cli.py": (
        "doctor context",
        "sufficiency-check",
        "read-log",
        "read-expansion",
    ),
    "delivery/skills/context-manifest-builder/templates/STORY-CONTEXT-PACKET-TEMPLATE.json": (
        "feature_contract_summary",
        "feature_design_summary_ref",
        "cr_delta",
        "dependency_inputs",
        "context_sufficiency",
    ),
    "delivery/skills/context-manifest-builder/templates/READ-POLICY-TEMPLATE.json": (
        "process/state/READ-EXPANSION-LEDGER.ndjson",
    ),
    "delivery/skills/context-manifest-builder/templates/ARTIFACT-BUDGETS-TEMPLATE.json": (
        "output_profiles",
        "story_return_summary",
        "cp_summary",
        "decision_brief_compact",
        "feature_design_summary",
    ),
    "delivery/README.md": (
        "上下文足够性",
        "READ-EXPANSION-LEDGER",
        "summary_update_recommendations",
    ),
    "docs/release/RELEASE-NOTES.md": (
        "Context sufficiency / read expansion governance",
        "READ-EXPANSION-LEDGER",
        "output profile budgets",
    ),
    "tests/test_context_sufficiency_read_expansion.py": (
        "test_strict_profile_missing_sufficiency_slots_fails",
        "test_read_log_writes_and_check_accepts_allowed_reason",
        "test_context_doctor_reports_summary_feedback",
        "test_cp_result_requires_read_expansion_refs_for_deny_default_refs",
    ),
}
FAILURE_WAIVER_REQUIRED_FILES = (
    "meta_flow/policies/failure_routing.py",
    "delivery/skills/checkpoint-manager/templates/FAILURE-ROUTING-TEMPLATE.json",
    "delivery/skills/checkpoint-manager/templates/WAIVER-POLICY-TEMPLATE.json",
    "tests/test_failure_routing_waiver.py",
)
FAILURE_WAIVER_TOKEN_TARGETS = {
    "meta_flow/policies/failure_routing.py": (
        "FAILURE_ROUTING_REL",
        "WAIVER_POLICY_REL",
        "rework_same_story",
        "reopen_cp5_design",
        "require_user_decision",
        "create_followup_candidate",
        "escalate_runtime_high_risk",
        "block_release",
        "waive_with_risk_acceptance",
        "non_waivable",
        "approval_ref",
        "forces_release_status",
        "READY_WITH_RISK",
    ),
    "meta_flow/checks/cp_result.py": (
        "validate_result_governance",
        "failure_routing",
    ),
    "meta_flow/cli.py": (
        "failure    Validate failure routing policy",
        "waiver     Validate waiver policy",
        "failure-routing",
        "waiver-policy",
        "_run_failure",
        "_run_waiver",
    ),
    "delivery/skills/checkpoint-manager/templates/FAILURE-ROUTING-TEMPLATE.json": (
        "creates",
        "updates",
        "invalidates",
        "next_allowed_stage",
        "escalate_runtime_high_risk",
    ),
    "delivery/skills/checkpoint-manager/templates/WAIVER-POLICY-TEMPLATE.json": (
        "non_waivable",
        "missing_dispatch_evidence",
        "missing_read_expansion_log",
        "approval_ref",
        "forces_release_status",
    ),
    "delivery/skills/checkpoint-manager/SKILL.md": (
        "Failure Routing Policy",
        "Waiver Policy",
        "rework_same_story",
        "waive_with_risk_acceptance",
        "non-waivable",
    ),
    "delivery/rules/AGENT-SKILL-CONTRACT.md": (
        "FAILURE-ROUTING.json",
        "WAIVER-POLICY.json",
        "forces_release_status",
        "不可豁免项",
    ),
    "delivery/skills/release-readiness/SKILL.md": (
        "WAIVER-POLICY.json",
        "READY_WITH_RISK",
        "不可豁免",
        "NOT_READY",
    ),
    "delivery/README.md": (
        "Failure Routing / Waiver Governance",
        "FAILURE-ROUTING.json",
        "WAIVER-POLICY.json",
        "non-waivable",
    ),
    "docs/release/RELEASE-NOTES.md": (
        "Failure routing / waiver governance",
        "FAILURE-ROUTING.json",
        "WAIVER-POLICY.json",
        "不可豁免",
    ),
    "tests/test_failure_routing_waiver.py": (
        "test_blocker_failure_requires_route_on_fail",
        "test_non_waivable_item_cannot_be_waived",
        "test_ready_with_risk_waiver_cannot_silent_pass",
        "test_cp_result_check_includes_failure_and_waiver_governance",
    ),
}
CR058_EXECUTION_CLOSURE_TOKEN_TARGETS = {
    "meta_flow/policies/failure_routing.py": (
        "CHECK_HARNESS_ERROR",
        "DETERMINISTIC_SCHEMA_REPAIR",
        "REAL_CONTENT_FAILURE",
        "PARTIAL_MUTATION",
        "targeted_revalidation_only",
    ),
    "meta_flow/checks/quality_governance.py": (
        '"G2": (True, 2)',
        "NEEDS_DESIGN_CLARIFICATION",
        "targeted_revalidation_only",
    ),
    "meta_flow/work/usage.py": (
        "changed_leaf_paths",
        "collapsed_status_entries_ui_only",
        "PASS_WITH_BASELINE_LIMITATION",
        "authorized_proxy_ceiling",
    ),
    "meta_flow/work/decision_bundle.py": (
        "build_decision_bundle_delta",
        "read_expansion_refs",
        "requires_new_revision",
    ),
    "meta_flow/workflow/cr_projection.py": (
        "render_status_body_projection",
        "CR 类型与门禁策略",
        "Checkpoint Index",
    ),
    "meta_flow/checks/cr_tracking.py": (
        "source_follow_up_id",
        "CR-INDEX.json",
    ),
    "delivery/rules/AGENTS.md": (
        "治理执行闭环补充（CR-058）",
        "CHECK_HARNESS_ERROR",
        "1 / 2 / 2",
        "targeted revalidation",
        "PASS_WITH_BASELINE_LIMITATION",
        "formal-only index",
        "不授权 `git commit`",
    ),
    "delivery/rules/AGENT-SKILL-CONTRACT.md": (
        "Governance Execution Closure",
        "Decision Bundle",
        "changed-path",
        "cost closure",
        "repository publication authorization",
    ),
    "delivery/skills/state-router/SKILL.md": (
        "CR-058 merged gate 与恢复路由",
        "interaction_id",
        "batch status-sync",
        "NEEDS_DESIGN_CLARIFICATION",
    ),
    "delivery/skills/checkpoint-manager/SKILL.md": (
        "CR-058 检查点执行闭环",
        "deduplicated gate interactions",
        "authorized_proxy_ceiling",
        "repository publication authorization",
    ),
    "delivery/skills/release-readiness/SKILL.md": (
        "CR-058 profile-aware 关闭与发布边界",
        "profile-aware `N/A`",
        "PASS_WITH_BASELINE_LIMITATION",
        "typed authorization",
    ),
    "delivery/doc/USER-MANUAL.md": (
        "治理恢复、预算与发布边界",
        "changed_leaf_path_count",
        "actual token",
        "formal-only index",
        "不允许自动执行 `git commit`",
    ),
}
CR058_CANONICAL_MIRROR_PAIRS = (
    (
        "delivery/skills/release-readiness/SKILL.md",
        ".agents/skills/release-readiness/SKILL.md",
    ),
)
CONTEXT_BUDGETED_E2E_TOKEN_TARGETS = {
    "evals/fixtures/context-budgeted-meta-flow/README.md": (
        "STATE.current.json -> CR summary -> context pack -> Story packet -> Story return -> evidence index -> CP result -> checkpoint ledger",
        "deny-default",
        "process/STATE.md",
        "process/DEVELOPMENT-PLAN.yaml",
        "process/changes/CR-001.md",
    ),
    "evals/fixtures/context-budgeted-meta-flow/process/policies/READ-POLICY.json": (
        "process/STATE.md",
        "process/DEVELOPMENT-PLAN.yaml",
        "process/changes/*.md",
        "process/stories/*-LLD.md",
        "capsule_missing",
        "field_conflict",
        "human_audit",
        "deep_review",
        "schema_validation_failed",
    ),
    "evals/fixtures/context-budgeted-meta-flow/process/stories/STORY-MF013-S01.md": (
        "feature_refs:",
        "feature_design_refs:",
        "lld_policy:",
        "allowed_write_paths:",
        "forbidden_write_paths:",
        "acceptance:",
        "verification_plan:",
    ),
    "evals/fixtures/context-budgeted-meta-flow/process/returns/STORY-MF013-S01.CP6.return.json": (
        '"packet_type": "story_return_packet"',
        '"touched_files"',
        '"boundary_check"',
        '"design_delta_required": false',
        '"next_stage_recommendation": "ready_for_cp7"',
    ),
    "evals/fixtures/context-budgeted-meta-flow/process/evidence/STORY-MF013-S01.CP6.index.json": (
        '"schema_version": 1',
        '"return_ref"',
        '"changed_files"',
        '"commands"',
    ),
    "evals/fixtures/context-budgeted-meta-flow/process/checks/CP6-STORY-MF013-S01.result.json": (
        '"checkpoint": "CP6"',
        '"decision": "PASS"',
        '"context_ref"',
        '"dispatch_refs"',
        '"evidence_ref"',
    ),
    "tests/test_context_budgeted_flow_e2e.py": (
        "build_context_pack",
        "validate_context_pack",
        "build_story_packet",
        "validate_story_packet",
        "validate_return_packet",
        "build_evidence_index",
        "validate_cp_result",
        "append_checkpoint_ledger",
        "validate_event_ledger",
        "assert_no_denied_allowed_reads",
        "process/STATE.md",
        "process/DEVELOPMENT-PLAN.yaml",
        "process/changes/CR-001.md",
    ),
    "README.md": (
        "evals/fixtures/context-budgeted-meta-flow/",
        "tests/test_context_budgeted_flow_e2e.py",
        "STATE.current.json -> CR summary -> context pack -> Story packet -> Story return -> evidence index -> CP result -> checkpoint ledger",
    ),
    "delivery/README.md": (
        "evals/fixtures/context-budgeted-meta-flow/",
        "tests/test_context_budgeted_flow_e2e.py",
        "STATE.current.json -> CR summary -> context pack -> Story packet -> Story return -> evidence index -> CP result -> checkpoint ledger",
    ),
}
AGENT_SKILL_CONTRACT_TOKEN_TARGETS = {
    "delivery/rules/AGENT-SKILL-CONTRACT.md": (
        "Input Contract",
        "Output Contract",
        "Handoff Contract",
        "Skill Contract",
        "process/state/STATE.current.json",
        "process/current/CURRENT.json",
        "allowed_reads",
        "must_read",
        "do_not_read_by_default",
        "full_doc_read_reason",
        "process/archive/**",
        "capsule_missing",
        "field_conflict",
        "schema_validation_failed",
        "human_audit",
        "summary_insufficient",
        "reason_evidence",
        "target bytes=0",
        "mutation=0",
        "authz_policy_refs",
        "process/returns/*.return.json",
        "process/evidence/*.index.json",
        "process/checks/*.result.json",
        "Checkpoint Index",
        "process/checkpoints/CP*.md",
        "不得复制 CP result",
    ),
    "delivery/rules/DIRECTORY-CONTRACT.md": (
        "Current Discovery",
        "process/current/CURRENT.json",
        "idle",
        "handoff_ref",
        "CR-INDEX.json",
        "CR-INDEX.yaml",
        "process/archive/**",
        "READ-EXPANSION-LEDGER.ndjson",
    ),
    "delivery/rules/DIRECTORY-CONTRACT.yaml": (
        "current_discovery",
        "process/current/CURRENT.json",
        "idle",
        "handoff_ref",
        "CR-INDEX.json",
        "zone_read_rules",
    ),
    "delivery/agents/meta-pm.md": (
        "Input Contract",
        "Output Contract",
        "Handoff Contract",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "allowed_reads",
        "do_not_read_by_default",
        "full_doc_read_reason",
    ),
    "delivery/agents/meta-se.md": (
        "Input Contract",
        "Output Contract",
        "Handoff Contract",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "allowed_reads",
        "do_not_read_by_default",
        "feature_design_refs",
    ),
    "delivery/agents/meta-dev.md": (
        "Input Contract",
        "Output Contract",
        "Handoff Contract",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "allowed_reads",
        "do_not_read_by_default",
        "process/returns",
        "process/evidence",
        "Design Delta",
    ),
    "delivery/agents/meta-qa.md": (
        "Input Contract",
        "Output Contract",
        "Handoff Contract",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "allowed_reads",
        "do_not_read_by_default",
        "Evidence Index",
        "CP7 result JSON",
    ),
    "delivery/agents/meta-doc.md": (
        "Input Contract",
        "Output Contract",
        "Handoff Contract",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "allowed_reads",
        "do_not_read_by_default",
    ),
    "delivery/skills/context-handoff/SKILL.md": (
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "allowed_reads",
        "do_not_read_by_default",
        "story_packet_ref",
        "HANDOFF-LEDGER",
        "AGENT-DISPATCH-LEDGER",
    ),
    "delivery/skills/context-manifest-builder/SKILL.md": (
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "allowed_reads",
        "do_not_read_by_default",
        "full_doc_read_reason",
    ),
    "delivery/skills/context-manifest-builder/templates/CONTEXT-CAPSULE-TEMPLATE.yaml": (
        "allowed_reads:",
        "must_read:",
        "process/state/STATE.current.json",
        "process/current/CURRENT.json",
        "process/STATE.md",
        "process/archive/**",
        "do_not_read_by_default:",
    ),
    "delivery/skills/state-router/SKILL.md": (
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "STATE.md 是人类摘要",
        "Story packet",
    ),
    "delivery/skills/change-impact-analysis/SKILL.md": (
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "CR-LEDGER",
        "CR summary",
        "Checkpoint Index",
        "process/checks/CP*.result.json",
        "process/checkpoints/CP*.md",
    ),
    "delivery/skills/checkpoint-manager/SKILL.md": (
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "result JSON",
        "Evidence Index",
        "Story Return Packet",
        "full_doc_read_reason",
        "Checkpoint Index",
        "不得把 CP result",
    ),
    "delivery/skills/review-artifact-protocol/SKILL.md": (
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "allowed_reads",
        "evidence index",
        "do_not_read_by_default",
    ),
    "delivery/skills/release-readiness/SKILL.md": (
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "do_not_read_by_default",
        "RELEASE-CONTEXT.yaml",
    ),
    "delivery/README.md": (
        "Agent / Skill Contract",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "delivery/rules/DIRECTORY-CONTRACT.md",
        "process/state/STATE.current.json",
        "process/current/CURRENT.json",
        "do_not_read_by_default",
        "Checkpoint Index",
    ),
    "README.md": (
        "Agent / Skill",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "delivery/rules/DIRECTORY-CONTRACT.md",
        "process/state/STATE.current.json",
        "process/current/CURRENT.json",
        "do_not_read_by_default",
        "Checkpoint Index",
    ),
    "AGENTS.md": (
        "Agent / Skill Contract Slimming",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "delivery/rules/DIRECTORY-CONTRACT.md",
        "process/state/STATE.current.json",
        "process/current/CURRENT.json",
        "allowed_reads",
        "CR Checkpoint Index",
    ),
    "delivery/rules/AGENTS.md": (
        "Agent / Skill Contract Slimming",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "delivery/rules/DIRECTORY-CONTRACT.md",
        "process/state/STATE.current.json",
        "process/current/CURRENT.json",
        "allowed_reads",
        "CR Checkpoint Index",
    ),
}
ACTIVE_READ_EXPANSION_REASONS = (
    "capsule_missing",
    "field_conflict",
    "schema_validation_failed",
    "human_audit",
    "summary_insufficient",
)
ACTIVE_READ_EXPANSION_TEXT_TARGETS = (
    "delivery/rules/AGENT-SKILL-CONTRACT.md",
    "delivery/agents/meta-pm.md",
    "delivery/skills/change-impact-analysis/SKILL.md",
    ".agents/skills/change-impact-analysis/SKILL.md",
    "delivery/README.md",
)
READ_EXPANSION_EVIDENCE_TOKENS = (
    "reason_evidence",
    "capsule_ref",
    "conflict_field",
    "schema_id",
    "error_code",
    "authorization_ref",
    "missing_slots",
)

SOFTWARE_WORKFLOW_TOKEN_TARGETS = {
    "delivery/agents/meta-pm.md": ("scenario-expansion", "story-planning", "docs/product/SCENARIOS.yaml", "docs/product/TEST-MATRIX.md", "docs/product/MVP-SCOPE.md", "SGQ-*", "用户可见场景确认"),
    "delivery/agents/meta-se.md": ("blueprint-design", "implementation-design", "docs/design/BLUEPRINT.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "feature_design_refs", "lld_policy", "standard-lite", "allows_batch_lld", "Batch LLD"),
    "delivery/agents/meta-dev.md": ("implementation-execution", "IMPLEMENTATION", "实现对象清单", "设计契约映射", "测试 / Fixture", "最小实现切片", "batch-lld", "BATCH-*-LLD.md#story-story-{id}"),
    "delivery/agents/meta-qa.md": ("verification-execution", "quality-review", "release-readiness", "docs/quality/VERIFICATION-REPORT.md", "docs/quality/TEST-REPORT.md", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/CP7-VERIFICATION-CONTEXT.yaml", "process/context/CP8-DELIVERY-CONTEXT.yaml", "release_artifact_profile", "release_decision", "实现执行证据", "PASS_WITH_RISK"),
    "delivery/agents/README.md": ("docs/product/TEST-MATRIX.md", "Feature 设计", "verification-execution", "发布就绪"),
    "delivery/skills/README.md": ("scenario-expansion", "story-planning", "blueprint-design", "implementation-design", "implementation-execution", "verification-execution", "quality-review", "release-readiness", "process/checkpoints/CP*.md", "FEATURE-DESIGN-MATRIX.md", "lld_policy", "batch-lld", "Batch LLD", "STORY-*-IMPLEMENTATION.md", "VERIFICATION-REPORT.md"),
    "delivery/skills/blueprint-design/templates/BLUEPRINT-TEMPLATE.md": ("决策类型", "推荐 / 备选优劣", "runtime_authorization", "follow_up_tracking"),
    "delivery/skills/story-planning/templates/MVP-SCOPE-TEMPLATE.md": ("决策类型", "推荐 / 备选优劣", "runtime_authorization", "follow_up_tracking"),
    "delivery/skills/story-planning/templates/BACKLOG-TEMPLATE.md": ("follow-up tracking", "CR-*-FOLLOW-UP-TRACKING", "CR-INDEX.json", "CR-LEDGER.ndjson"),
    "delivery/skills/release-readiness/SKILL.md": ("FEEDBACK.md", "follow-up tracking", "CR-*-FOLLOW-UP-TRACKING", "CR-INDEX.json", "CR-LEDGER.ndjson", "Release Context Capsule", "process/release/RELEASE-CONTEXT.yaml", "release_artifact_profile", "release_decision", "READY_WITH_RISK", "NOT_READY", "capsule-first", "fact_diff", "promise_ref", "decision_impact"),
    "delivery/skills/release-readiness/templates/RELEASE-CONTEXT-TEMPLATE.yaml": ("release_artifact_profile", "release_decision", "quality_summary", "fact_diff", "promised_count", "missing_required_count", "evidence_index_refs", "affected_surface", "install_validation_summary", "token_control"),
    "delivery/skills/release-readiness/templates/RELEASE-NOTES-TEMPLATE.md": ("版本号决策", "release_artifact_profile", "release_decision", "安装与升级", "CP8 Fact Diff", "Evidence Index", "回滚方式"),
    "delivery/skills/release-readiness/templates/DEPLOY-CHECKLIST-TEMPLATE.md": ("发布候选快照", "CP8 Fact Diff", "安装 / 升级 / 幂等验证矩阵", "release_decision", "fact_diff 结论", "不授权项"),
    "delivery/skills/release-readiness/templates/ROLLBACK-TEMPLATE.md": ("回滚目标版本", "CP8 fact_diff", "不可回滚项"),
    "delivery/skills/release-readiness/templates/MIGRATION-TEMPLATE.md": ("兼容性判断表", "CP8 fact_diff", "STATE.md", "Agent frontmatter", "Skill 输出格式", "命令参数"),
    "delivery/skills/release-readiness/templates/FEEDBACK-TEMPLATE.md": ("follow-up tracking", "CR-*-FOLLOW-UP-TRACKING", "CR-INDEX.json", "CR-LEDGER.ndjson", "CP8 fact_diff"),
    "delivery/skills/context-manifest-builder/templates/AUTHZ-POLICY-TEMPLATE.json": ("NO_REPOSITORY_PUBLICATION", "post_cr_repository_publication_authorization", "git push"),
    "meta_flow/checks/cp_result.py": ("fact_diff", "release_decision", "MISSING_REQUIRED_EVIDENCE", "decision_impact", "checker_provenance", "fallback_review_ref"),
    "meta_flow/policies/authz.py": ("NO_REPOSITORY_PUBLICATION", "REPOSITORY_PUBLICATION_ALLOWED", "repository_publication", "post_cr_repository_publication_authorization"),
    "delivery/skills/use-case-discovery/SKILL.md": ("scenario_confirmation_interactions", "SGQ-*", "不得静默场景发现", "用户可见场景确认"),
    "delivery/skills/use-case-discovery/templates/USE-CASES-TEMPLATE.md": ("用户可见场景确认证据", "SGQ-*", "confirmed", "静默生成场景"),
    "delivery/skills/implementation-execution/SKILL.md": ("IMPLEMENTATION", "实现对象清单", "设计契约映射", "测试 / Fixture", "最小实现切片", "平台差异", "handoff"),
    "delivery/skills/implementation-execution/templates/IMPLEMENTATION-TEMPLATE.md": ("实现对象清单", "设计契约映射", "单元测试 / Fixture", "最小实现切片", "平台差异", "QA / Review / Doc"),
    "delivery/skills/lld-designer/SKILL.md": ("BATCH-LLD-TEMPLATE.md", "batch-lld", "standard-lite", "allows_batch_lld", "evidence_path", "拆回独立"),
    "delivery/skills/lld-designer/templates/BATCH-LLD-TEMPLATE.md": ("evidence_type: \"batch-lld\"", "allowed_profile: \"standard-lite\"", "Story Design Evidence", "#story-story", "CP5"),
    "delivery/skills/verification-execution/SKILL.md": ("VERIFICATION", "验证对象清单", "验证追踪矩阵", "设计契约验证", "分层验证计划", "PASS_WITH_RISK", "validation_mode"),
    "delivery/skills/verification-execution/templates/VERIFICATION-TEMPLATE.md": ("验证对象清单", "验证追踪矩阵", "设计契约验证清单", "分层验证计划", "Prompt / Skill Fixture", "阶段决策"),
    "delivery/skills/quality-review/SKILL.md": ("IMPLEMENTATION", "VERIFICATION", "实现执行证据", "验证对象清单", "设计契约映射", "Fixture", "阶段决策"),
    "delivery/skills/checkpoint-manager/SKILL.md": ("docs/product/SCENARIOS.yaml", "docs/product/TEST-MATRIX.md", "docs/design/BLUEPRINT.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "full-lld", "batch-lld", "technical-note", "waived", "BATCH-{cr_id-or-batch_id}", "quality-review", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/*-CONTEXT.yaml", "decision_brief_profile", "release_artifact_profile", "release_decision", "实现执行证据", "IMPLEMENTATION", "验证对象清单", "PASS_WITH_RISK"),
    "delivery/skills/state-router/SKILL.md": ("docs/product/SCENARIOS.yaml", "docs/product/TEST-MATRIX.md", "docs/design/BLUEPRINT.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "design_evidence", "batch-lld", "BATCH-*-LLD.md#story-story-{id}", "docs/quality/VERIFICATION-REPORT.md", "docs/quality/TEST-REPORT.md", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/*-CONTEXT.yaml", "read_expansion_log", "workflow_health_ref", "release_artifact_profile", "release_decision", "implementation-execution", "verification-execution", "STORY-*-IMPLEMENTATION.md", "PASS_WITH_RISK"),
    "delivery/skills/story-manager/SKILL.md": ("batch-lld", "lld_gate.design_evidence_type", "standard-lite", "allows_batch_lld"),
    "delivery/skills/story-manager/templates/STORY-TEMPLATE.md": ("batch-lld", "design_evidence_type"),
    "delivery/skills/state-router/templates/STATE-TEMPLATE.md": ("artifacts:", "docs/product/SCENARIOS.yaml", "docs/design/BLUEPRINT.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "lld_policy", "docs/quality/VERIFICATION-REPORT.md", "docs/quality/TEST-REPORT.md", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "read_expansion_ledger_ref", "workflow_health_ref", "decision_brief_profile", "route_validation", "release_artifact_profile_values", "release_decision_values", "implementation:", "cp7_result_values"),
    "delivery/rules/AGENTS.md": ("docs/product/SCENARIOS.yaml", "docs/product/TEST-MATRIX.md", "docs/product/MVP-SCOPE.md", "docs/design/BLUEPRINT.md", "docs/design/DOMAIN-MAP.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "lld_policy", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/", "Context Capsule", "workflow_health", "decision_brief_profile", "release_artifact_profile", "release_decision", "process/checkpoints/", "implementation-execution", "verification-execution", "IMPLEMENTATION", "VERIFICATION-REPORT", "PASS_WITH_RISK"),
    "AGENTS.md": ("docs/product/SCENARIOS.yaml", "docs/product/TEST-MATRIX.md", "docs/product/MVP-SCOPE.md", "docs/design/BLUEPRINT.md", "docs/design/DOMAIN-MAP.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "lld_policy", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/", "Context Capsule", "workflow_health", "decision_brief_profile", "release_artifact_profile", "release_decision", "process/checkpoints/", "implementation-execution", "verification-execution", "IMPLEMENTATION", "VERIFICATION-REPORT", "PASS_WITH_RISK"),
    "README.md": ("docs/product/SCENARIOS.yaml", "docs/product/MVP-SCOPE.md", "docs/design/BLUEPRINT.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "lld_policy", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/", "decision_brief_profile", "release_artifact_profile", "release_decision", "process/checkpoints/", "implementation-execution", "verification-execution", "IMPLEMENTATION", "VERIFICATION-REPORT"),
}
CACHE_SCAN_EXCLUDED_DIRS = {".git", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
OPTIONAL_GENERATED_ROOT_RULE = ROOT / "AGENTS.md"
RUNTIME_WARNINGS: list[str] = []


def is_optional_generated_root_rule(path: Path) -> bool:
    return path == OPTIONAL_GENERATED_ROOT_RULE


def cache_hygiene_severity(
    rel_path: Path,
    *,
    tracked: bool,
    ignored: bool,
    package_input: bool | None = None,
) -> str:
    """Classify cache evidence with package-input precedence over ignore state."""

    if tracked:
        return "BLOCK"
    if package_input is None:
        package_input = rel_path.parts[:1] in {("meta_flow",), ("delivery",)} and not ignored
    if package_input:
        return "BLOCK"
    if ignored:
        return "WARN"
    return "BLOCK"


def _git_path_flag(args: list[str], rel_path: Path) -> bool:
    result = subprocess.run(
        ["git", *args, "--", rel_path.as_posix()],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def collect_cache_hygiene_errors() -> list[str]:
    errors: list[str] = []
    cache_dirs = [
        path
        for path in ROOT.rglob("__pycache__")
        if path.is_dir() and not is_under_excluded_cache_dir(path)
    ]
    candidates = list(cache_dirs)
    candidates.extend(
        path
        for path in ROOT.rglob("*.pyc")
        if path.is_file()
        and not is_under_excluded_cache_dir(path)
        and not any(path.is_relative_to(cache_dir) for cache_dir in cache_dirs)
    )
    for path in sorted(set(candidates)):
        rel_path = path.relative_to(ROOT)
        tracked = _git_path_flag(["ls-files", "--error-unmatch"], rel_path)
        ignored = _git_path_flag(["check-ignore", "-q"], rel_path)
        package_input = rel_path.parts[:1] in {("meta_flow",), ("delivery",)} and not ignored
        severity = cache_hygiene_severity(
            rel_path,
            tracked=tracked,
            ignored=ignored,
            package_input=package_input,
        )
        kind = "directory" if path.is_dir() else "file"
        message = f"python cache {kind}: {rel_path}"
        if severity == "BLOCK":
            errors.append(message)
        else:
            RUNTIME_WARNINGS.append(f"ignored local {message}")
    return errors
EXPECTED_CODEX_NICKNAMES = {
    "meta-pm": ["pm-wu", "pm-zheng", "pm-wang", "pm-feng", "pm-chen"],
    "meta-se": ["se-chu", "se-wei", "se-jiang", "se-shen", "se-han"],
    "meta-se-critical": ["se-critical-chu", "se-critical-wei", "se-critical-jiang"],
    "meta-dev": [
        "dev-yang",
        "dev-zhu",
        "dev-qin",
        "dev-you",
        "dev-xu",
        "dev-he",
        "dev-lv",
        "dev-shi",
        "dev-zhang",
        "dev-kong",
    ],
    "meta-dev-debugger": ["debug-yang", "debug-zhu", "debug-qin", "debug-you", "debug-xu"],
    "meta-qa": [
        "qa-he",
        "qa-lv",
        "qa-shi",
        "qa-zhang",
        "qa-kong",
        "qa-cao",
        "qa-yan",
        "qa-hua",
        "qa-jin",
        "qa-wei",
    ],
    "meta-qa-critical": ["qa-critical-he", "qa-critical-lv", "qa-critical-shi"],
    "meta-doc": ["doc-cao", "doc-yan", "doc-hua", "doc-jin", "doc-wei"],
}
EXPECTED_CODEX_REASONING_EFFORTS = {
    "meta-pm": "medium",
    "meta-se": "high",
    "meta-se-critical": "xhigh",
    "meta-dev": "medium",
    "meta-dev-debugger": "high",
    "meta-qa": "high",
    "meta-qa-critical": "xhigh",
    "meta-doc": "low",
}
EXPECTED_CODEX_MODELS = {
    "meta-pm": "gpt-5.6-terra",
    "meta-se": "gpt-5.6-terra",
    "meta-se-critical": "gpt-5.6-sol",
    "meta-dev": "gpt-5.6-terra",
    "meta-dev-debugger": "gpt-5.6-sol",
    "meta-qa": "gpt-5.6-terra",
    "meta-qa-critical": "gpt-5.6-sol",
    "meta-doc": "gpt-5.6-luna",
}
EXPECTED_CLAUDE_COLORS = {
    "meta-pm": "orange",
    "meta-se": "yellow",
    "meta-dev": "green",
    "meta-qa": "cyan",
    "meta-doc": "purple",
}
CLAUDE_DIRECT_ASK_AGENTS = {"meta-pm", "meta-se"}
CLAUDE_NO_DIRECT_ASK_AGENTS = {"meta-dev", "meta-qa", "meta-doc"}
CODEX_NICKNAME_RE = re.compile(r"^[A-Za-z0-9 _-]+$")
ARCHIVED_AGENT_PATHS = {
    "meta-dm": DELIVERY_ROOT / "doc" / "archive" / "meta-dm.md",
}
LEGACY_ORCHESTRATOR_AGENT_NAMES = {"meta-po", "host-orchestrator"}
NON_DELIVERED_SKILL_PLACEHOLDERS = ("vendor-profile-loader", "constraint-normalizer")


def is_under_excluded_cache_dir(path: Path) -> bool:
    rel_parts = path.relative_to(ROOT).parts
    return any(part in CACHE_SCAN_EXCLUDED_DIRS for part in rel_parts)


def load_platform_contracts(errors: list[str]) -> dict[str, object]:
    if not PLATFORM_CONTRACTS.is_file():
        errors.append(f"missing platform contract source: {PLATFORM_CONTRACTS.relative_to(ROOT)}")
        return {}
    try:
        return json.loads(PLATFORM_CONTRACTS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"platform contract must be JSON-compatible YAML: {PLATFORM_CONTRACTS.relative_to(ROOT)} -> {exc}")
        return {}


def collect_platform_contract_errors(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    try:
        codex = payload["contracts"]["codex"]  # type: ignore[index]
        claude = payload["contracts"]["claude"]  # type: ignore[index]
        qoder = payload["contracts"]["qoder"]  # type: ignore[index]
        project = codex["scopes"]["project"]  # type: ignore[index]
        user = codex["scopes"]["user"]  # type: ignore[index]
        claude_project = claude["scopes"]["project"]  # type: ignore[index]
        claude_user = claude["scopes"]["user"]  # type: ignore[index]
        qoder_project = qoder["scopes"]["project"]  # type: ignore[index]
        qoder_user = qoder["scopes"]["user"]  # type: ignore[index]
        forbidden_project = codex["forbidden"]["project"]  # type: ignore[index]
        forbidden_user = codex["forbidden"]["user"]  # type: ignore[index]
    except (AttributeError, KeyError, TypeError):
        return ["platform contract missing codex/claude/qoder scopes or codex forbidden entries"]

    expected = {
        "claude project rules": (claude_project.get("rules"), "CLAUDE.md"),
        "claude project agents": (claude_project.get("agents"), ".claude/agents"),
        "claude project skills": (claude_project.get("skills"), ".claude/skills"),
        "claude user rules": (claude_user.get("rules"), "~/.claude/CLAUDE.md"),
        "claude user agents": (claude_user.get("agents"), "~/.claude/agents"),
        "claude user skills": (claude_user.get("skills"), "~/.claude/skills"),
        "codex project agents": (project.get("agents"), ".codex/agents"),
        "codex project skills": (project.get("skills"), ".agents/skills"),
        "codex user agents": (user.get("agents"), "~/.codex/agents"),
        "codex user skills": (user.get("skills"), "~/.agents/skills"),
        "qoder project rules": (qoder_project.get("rules"), "AGENTS.md"),
        "qoder project agents": (qoder_project.get("agents"), ".qoder/agents"),
        "qoder project skills": (qoder_project.get("skills"), ".qoder/skills"),
        "qoder user rules": (qoder_user.get("rules"), "~/.qoder/AGENTS.md"),
        "qoder user agents": (qoder_user.get("agents"), "~/.qoder/agents"),
        "qoder user skills": (qoder_user.get("skills"), "~/.qoder/skills"),
    }
    for label, (actual, required) in expected.items():
        if actual != required:
            errors.append(f"platform contract mismatch: {label} must be {required}, got {actual}")

    if ".codex/skills" not in forbidden_project:
        errors.append("platform contract must forbid codex project .codex/skills")
    if "~/.codex/skills" not in forbidden_user:
        errors.append("platform contract must forbid codex user ~/.codex/skills")
    return errors


def collect_codex_dry_run_errors(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    install_script = DELIVERY_ROOT / "scripts" / "install.py"
    if not install_script.is_file():
        return [f"missing installer: {install_script.relative_to(ROOT)}"]

    with tempfile.TemporaryDirectory(prefix="meta-flow-guardrail-") as tmp:
        project_root = Path(tmp)
        cases = [
            ("project", project_root / ".agents" / "skills" / "context-handoff" / "SKILL.md", ".codex/skills"),
            ("user", Path.home() / ".agents" / "skills" / "context-handoff" / "SKILL.md", str(Path.home() / ".codex" / "skills")),
        ]
        for scope, required_path, forbidden_path in cases:
            result = subprocess.run(
                [
                    sys.executable,
                    str(install_script),
                    "codex",
                    "--scope",
                    scope,
                    "--project-dir",
                    str(project_root),
                    "--content",
                    "skills",
                    "--skill",
                    "context-handoff",
                    "--dry-run",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout + result.stderr
            if result.returncode != 0:
                errors.append(f"codex {scope} dry-run failed with exit {result.returncode}: {output.strip()}")
                continue
            if str(required_path) not in output:
                errors.append(f"codex {scope} dry-run missing required skill path: {required_path}")
            if forbidden_path in output or ".codex/skills" in output:
                errors.append(f"codex {scope} dry-run must not target forbidden skill path: {forbidden_path}")

        conflict_root = project_root / "path-conflict"
        conflict_root.mkdir()
        blocker = conflict_root / ".codex"
        blocker.write_text("file occupying a directory path\n", encoding="utf-8")
        conflict_result = subprocess.run(
            [
                sys.executable,
                str(install_script),
                "codex",
                "--scope",
                "project",
                "--project-dir",
                str(conflict_root),
                "--content",
                "agents",
                "--agent",
                "meta-pm",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        conflict_output = conflict_result.stdout + conflict_result.stderr
        if conflict_result.returncode == 0:
            errors.append("codex project install must fail when .codex is a file")
        if "安装路径被非目录占用:" not in conflict_output or str(blocker) not in conflict_output:
            errors.append("codex path conflict must report a clear occupied-path error")
        if "Traceback" in conflict_output or "NotADirectoryError" in conflict_output:
            errors.append("codex path conflict must not expose a Python traceback")

        qoder_conflict_root = project_root / "qoder-path-conflict"
        qoder_conflict_root.mkdir()
        qoder_blocker = qoder_conflict_root / ".qoder"
        qoder_blocker.write_text("file occupying a directory path\n", encoding="utf-8")
        qoder_conflict_result = subprocess.run(
            [
                sys.executable,
                str(install_script),
                "qoder",
                "--scope",
                "project",
                "--project-dir",
                str(qoder_conflict_root),
                "--content",
                "agents",
                "--agent",
                "meta-pm",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        qoder_conflict_output = qoder_conflict_result.stdout + qoder_conflict_result.stderr
        if qoder_conflict_result.returncode == 0:
            errors.append("qoder project install must fail when .qoder is a file")
        if "安装路径被非目录占用:" not in qoder_conflict_output or str(qoder_blocker) not in qoder_conflict_output:
            errors.append("qoder path conflict must report a clear occupied-path error")
        if "Traceback" in qoder_conflict_output or "NotADirectoryError" in qoder_conflict_output:
            errors.append("qoder path conflict must not expose a Python traceback")

    contract_errors = collect_platform_contract_errors(payload)
    errors.extend(contract_errors)
    return errors


def collect_installer_component_errors() -> list[str]:
    errors: list[str] = []
    install_script = DELIVERY_ROOT / "scripts" / "install.py"
    pyproject = ROOT / "pyproject.toml"
    cli_module = ROOT / "meta_flow" / "cli.py"

    if not pyproject.is_file():
        errors.append("missing pyproject.toml for uv tool installation")
    else:
        try:
            project_config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"pyproject.toml is not valid TOML: {exc}")
        else:
            scripts = project_config.get("project", {}).get("scripts", {})
            if scripts.get("meta-flow") != "meta_flow.cli:main":
                errors.append("pyproject.toml must expose console script: meta-flow = meta_flow.cli:main")
            if project_config.get("project", {}).get("readme") != "delivery/README.md":
                errors.append("pyproject.toml project.readme must point at delivery/README.md")
            setuptools_config = project_config.get("tool", {}).get("setuptools", {})
            package_find = setuptools_config.get("packages", {}).get("find", {})
            package_data = setuptools_config.get("package-data", {})
            package_includes = set(package_find.get("include", [])) if isinstance(package_find, dict) else set()
            delivery_data = set(package_data.get("delivery", [])) if isinstance(package_data, dict) else set()
            if "meta_flow.*" not in package_includes:
                errors.append("pyproject.toml must package meta_flow.* so installed meta-flow can expose runtime check commands")
            if "delivery" not in package_includes or "delivery.scripts" not in package_includes:
                errors.append("pyproject.toml must package delivery and delivery.scripts so installed meta-flow can locate delivery/scripts/install.py")
            for required_pattern in ("**/*.md", "**/*.yaml", "**/*.sh", "**/*.ps1", "**/*.py"):
                if required_pattern not in delivery_data:
                    errors.append(f"pyproject.toml delivery package-data missing pattern: {required_pattern}")

    if not cli_module.is_file():
        errors.append("missing meta_flow/cli.py for meta-flow command")
    else:
        cli_text = cli_module.read_text(encoding="utf-8")
        for required in ("install", "META_FLOW_SOURCE", "delivery/scripts/install.py"):
            if required not in cli_text:
                errors.append(f"meta_flow/cli.py missing required token: {required}")

    if not install_script.is_file():
        return errors + [f"missing installer: {install_script.relative_to(ROOT)}"]

    help_cases = [
        {
            "label": "installer --help",
            "args": ["--help"],
            "required": ("<platform>", "--component", "rules", "agent", "full", "--content"),
        },
        {
            "label": "installer platform --help",
            "args": ["codex", "--help"],
            "required": ("<platform>", "--component", "rules", "agent", "full", "--content"),
        },
        {
            "label": "installer uninstall --help",
            "args": ["uninstall", "--help"],
            "required": ("Uninstall", "<platform>", "--component", "rules", "agent", "full"),
        },
        {
            "label": "installer uninstall platform --help",
            "args": ["uninstall", "codex", "--help"],
            "required": ("Uninstall", "<platform>", "--component", "rules", "agent", "full"),
        },
    ]
    for help_case in help_cases:
        help_result = subprocess.run(
            [sys.executable, str(install_script), *help_case["args"]],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        help_output = help_result.stdout + help_result.stderr
        if help_result.returncode != 0:
            errors.append(f"{help_case['label']} failed with exit {help_result.returncode}: {help_output.strip()}")
            continue
        for required in help_case["required"]:
            if required not in help_output:
                errors.append(f"{help_case['label']} missing help token: {required}")

    with tempfile.TemporaryDirectory(prefix="meta-flow-component-") as tmp:
        project_root = Path(tmp)
        cases = [
            {
                "label": "codex user default",
                "args": ["codex", "--scope", "user", "--project-dir", str(project_root), "--dry-run"],
                "required": [
                    "Component: rules",
                    str(Path.home() / ".codex" / "AGENTS.md"),
                    str(Path.home() / ".meta-flow" / "delivery" / "doc" / "INSTALL-MANIFEST.yaml"),
                ],
                "forbidden": [
                    str(Path.home() / ".codex" / "agents" / "meta-po.toml"),
                    str(Path.home() / ".codex" / "agents" / "host-orchestrator.toml"),
                    str(Path.home() / ".agents" / "skills"),
                ],
            },
            {
                "label": "codex project default",
                "args": ["codex", "--scope", "project", "--project-dir", str(project_root), "--dry-run"],
                "required": ["Component: full", str(project_root / "AGENTS.md"), str(project_root / ".codex" / "agents" / "meta-pm.toml"), str(project_root / ".agents" / "skills"), str(project_root / ".meta-flow" / "INSTALL-MANIFEST.yaml")],
                "forbidden": [".codex/skills", str(project_root / ".codex" / "agents" / "meta-po.toml"), str(project_root / ".codex" / "agents" / "host-orchestrator.toml"), str(Path.home() / ".meta-flow" / "delivery" / "doc" / "INSTALL-MANIFEST.yaml")],
            },
            {
                "label": "claude project default",
                "args": ["claude", "--scope", "project", "--project-dir", str(project_root), "--dry-run"],
                "required": ["Component: full", str(project_root / "CLAUDE.md"), str(project_root / ".claude" / "agents" / "meta-pm.md"), str(project_root / ".claude" / "skills"), str(project_root / ".meta-flow" / "INSTALL-MANIFEST.yaml")],
                "forbidden": [str(project_root / ".claude" / "CLAUDE.md"), str(project_root / ".claude" / "agents" / "meta-po.md"), str(project_root / ".claude" / "agents" / "host-orchestrator.md"), str(Path.home() / ".meta-flow" / "delivery" / "doc" / "INSTALL-MANIFEST.yaml")],
            },
            {
                "label": "codex full component",
                "args": ["codex", "--scope", "project", "--project-dir", str(project_root), "--component", "full", "--dry-run"],
                "required": ["Component: full", str(project_root / "AGENTS.md"), str(project_root / ".codex" / "agents" / "meta-pm.toml"), str(project_root / ".agents" / "skills"), str(project_root / ".meta-flow" / "INSTALL-MANIFEST.yaml")],
                "forbidden": [".codex/skills", str(project_root / ".codex" / "agents" / "meta-po.toml"), str(project_root / ".codex" / "agents" / "host-orchestrator.toml"), str(Path.home() / ".meta-flow" / "delivery" / "doc" / "INSTALL-MANIFEST.yaml")],
            },
            {
                "label": "legacy skills content",
                "args": [
                    "codex",
                    "--scope",
                    "project",
                    "--project-dir",
                    str(project_root),
                    "--content",
                    "skills",
                    "--skill",
                    "context-handoff",
                    "--dry-run",
                ],
                "required": ["Component: agent", "Legacy content: skills", str(project_root / ".agents" / "skills" / "context-handoff" / "SKILL.md")],
                "forbidden": [str(project_root / ".codex" / "agents" / "meta-po.toml"), str(project_root / ".codex" / "agents" / "host-orchestrator.toml"), ".codex/skills"],
            },
            {
                "label": "legacy platform option",
                "args": ["--platform", "codex", "--scope", "project", "--project-dir", str(project_root), "--component", "rules", "--dry-run"],
                "required": ["Component: rules", str(project_root / "AGENTS.md")],
                "forbidden": [".codex/skills"],
            },
            {
                "label": "qoder project default",
                "args": ["qoder", "--scope", "project", "--project-dir", str(project_root), "--dry-run"],
                "required": ["Component: full", str(project_root / "AGENTS.md"), str(project_root / ".qoder" / "agents" / "meta-pm.md"), str(project_root / ".qoder" / "skills"), str(project_root / ".meta-flow" / "INSTALL-MANIFEST.yaml")],
                "forbidden": [str(project_root / ".qoder" / "agents" / "meta-po.md"), str(project_root / ".qoder" / "agents" / "host-orchestrator.md"), str(Path.home() / ".meta-flow" / "delivery" / "doc" / "INSTALL-MANIFEST.yaml")],
            },
            {
                "label": "qoder user default",
                "args": ["qoder", "--scope", "user", "--project-dir", str(project_root), "--dry-run"],
                "required": ["Component: rules", str(Path.home() / ".qoder" / "AGENTS.md")],
                "forbidden": [str(Path.home() / ".qoder" / "agents" / "meta-po.md")],
            },
        ]

        for case in cases:
            result = subprocess.run(
                [sys.executable, str(install_script), *case["args"]],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout + result.stderr
            if result.returncode != 0:
                errors.append(f"{case['label']} dry-run failed with exit {result.returncode}: {output.strip()}")
                continue
            for required in case["required"]:
                if required not in output:
                    errors.append(f"{case['label']} dry-run missing required output: {required}")
            for forbidden in case["forbidden"]:
                if forbidden in output:
                    errors.append(f"{case['label']} dry-run unexpectedly included: {forbidden}")

        legacy_result = subprocess.run(
            [
                sys.executable,
                str(install_script),
                "codex",
                "--scope",
                "project",
                "--project-dir",
                str(project_root),
                "--component",
                "agent",
                "--agent",
                "meta-po",
                "--dry-run",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        legacy_output = legacy_result.stdout + legacy_result.stderr
        if legacy_result.returncode == 0:
            errors.append("installer must reject legacy orchestrator agent request: --agent meta-po")
        if "不再作为平台 agent 安装" not in legacy_output:
            errors.append("legacy orchestrator rejection must explain that the orchestrator is host-managed")

    return errors


def collect_cr004_protocol_errors() -> list[str]:
    errors: list[str] = []
    targets = [
        DELIVERY_ROOT / "agents" / "meta-doc.md",
        DELIVERY_ROOT / "agents" / "meta-qa.md",
        DELIVERY_ROOT / "rules" / "AGENTS.md",
        DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
    ]
    for target in targets:
        if not target.is_file():
            errors.append(f"missing CR-004 protocol target: {target.relative_to(ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        missing = [token for token in CODEX_CONFIRMATION_TOKENS if token not in text]
        if missing:
            errors.append(
                f"{target.relative_to(ROOT)} missing Codex confirmation protocol tokens: {', '.join(missing)}"
            )

    routing_targets = [
        DELIVERY_ROOT / "agents" / "meta-pm.md",
        DELIVERY_ROOT / "agents" / "meta-doc.md",
        DELIVERY_ROOT / "skills" / "use-case-discovery" / "SKILL.md",
        DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
        DELIVERY_ROOT / "README.md",
        DELIVERY_ROOT / "rules" / "AGENTS.md",
        ROOT / "AGENTS.md",
    ]
    for target in routing_targets:
        if not target.is_file():
            if is_optional_generated_root_rule(target):
                continue
            errors.append(f"missing delivery routing target: {target.relative_to(ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        missing = [token for token in DELIVERY_ROUTING_TOKENS if token not in text]
        if missing:
            errors.append(f"{target.relative_to(ROOT)} missing delivery routing tokens: {', '.join(missing)}")

    state_template = DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md"
    if state_template.is_file():
        state_text = state_template.read_text(encoding="utf-8")
        for required in ("AGENT-DISPATCH-LEDGER.ndjson", "active_agent_count", "cp5_story_lld_review"):
            if required not in state_text:
                errors.append(f"{state_template.relative_to(ROOT)} missing lifecycle/state token: {required}")
    else:
        errors.append(f"missing state template: {state_template.relative_to(ROOT)}")

    handoff_skill = DELIVERY_ROOT / "skills" / "context-handoff" / "SKILL.md"
    if handoff_skill.is_file():
        handoff_text = handoff_skill.read_text(encoding="utf-8")
        for required in ("fork_context=false", "完整会话", "AGENT-DISPATCH-LEDGER.ndjson"):
            if required not in handoff_text:
                errors.append(f"{handoff_skill.relative_to(ROOT)} missing context-budget token: {required}")
    else:
        errors.append(f"missing context handoff skill: {handoff_skill.relative_to(ROOT)}")

    return errors


def collect_guardrail_command_scope_errors() -> list[str]:
    errors: list[str] = []
    targets = [
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        DELIVERY_ROOT / "rules" / "AGENTS.md",
        DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
        DELIVERY_ROOT / "agents" / "meta-qa.md",
    ]
    for target in targets:
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        if "check_delivery_guardrails.py" not in text:
            continue
        missing = [token for token in GUARDRAIL_CONDITION_TOKENS if token not in text]
        if missing:
            errors.append(f"{target.relative_to(ROOT)} references check_delivery_guardrails.py without conditional scope tokens: {', '.join(missing)}")
        if re.search(r"/home/[^`\s]*/scripts/check_delivery_guardrails\.py", text) and "不得硬引用" not in text:
            errors.append(f"{target.relative_to(ROOT)} must not hard-code a guardrail absolute path")
    return errors


def collect_agent_dispatch_evidence_errors() -> list[str]:
    errors: list[str] = []
    targets = [
        DELIVERY_ROOT / "skills" / "state-router" / "SKILL.md",
        DELIVERY_ROOT / "skills" / "context-handoff" / "SKILL.md",
        DELIVERY_ROOT / "skills" / "checkpoint-manager" / "SKILL.md",
        DELIVERY_ROOT / "rules" / "AGENTS.md",
        DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
        DELIVERY_ROOT / "README.md",
        ROOT / "AGENTS.md",
    ]
    required_tokens = (
        "Agent Dispatch Evidence",
        "inline-fallback",
        "agent_id",
        "thread_id",
        "spawn_agent",
        "resume_agent",
        "send_input",
        "tool_name",
        "completed_at",
        "codex_agent_name",
        "reasoning_profile",
        "dispatch_trigger",
    )
    for target in targets:
        if not target.is_file():
            if is_optional_generated_root_rule(target):
                continue
            errors.append(f"missing agent dispatch evidence target: {target.relative_to(ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append(f"{target.relative_to(ROOT)} missing agent dispatch evidence tokens: {', '.join(missing)}")

    handoff_skill = DELIVERY_ROOT / "skills" / "context-handoff" / "SKILL.md"
    if handoff_skill.is_file():
        text = handoff_skill.read_text(encoding="utf-8")
        for token in (
            "dispatch:",
            "mode=subagent",
            "mode=inline-fallback",
            "mode=handoff-only",
            "not-subagent-executed",
            "spawn-requested",
            "tool_name",
            "completed_at",
            "codex_agent_name",
            "reasoning_profile",
            "dispatch_trigger",
            "创建 `mode=subagent` handoff 后必须立即调用",
            "不得进入 `running/completed`",
        ):
            if token not in text:
                errors.append(f"{handoff_skill.relative_to(ROOT)} missing dispatch frontmatter token: {token}")

    state_router = DELIVERY_ROOT / "skills" / "state-router" / "SKILL.md"
    state_template = DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md"
    if state_router.is_file():
        text = state_router.read_text(encoding="utf-8")
        for token in (
            "required_tools",
            "codex_reasoning_profiles",
            "meta-dev-debugger",
            "meta-se-critical",
            "meta-qa-critical",
            "subagent_auto_dispatch=enabled",
            "创建 `mode=subagent` handoff 后必须立即调用真实子 agent 工具",
        ):
            if token not in text:
                errors.append(f"{state_router.relative_to(ROOT)} missing Codex dispatch/profile token: {token}")

    if state_template.is_file():
        text = state_template.read_text(encoding="utf-8")
        for token in (
            "AGENT-DISPATCH-LEDGER.ndjson",
            "active_agent_count",
            "platform_capabilities_ref",
            "subagent_auto_dispatch",
        ):
            if token not in text:
                errors.append(f"{state_template.relative_to(ROOT)} missing slim dispatch state token: {token}")

    for target in (ROOT / "AGENTS.md", DELIVERY_ROOT / "rules" / "AGENTS.md"):
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        for token in (
            "codex_agent_name",
            "reasoning_profile",
            "dispatch_trigger",
            "spawn-requested",
        ):
            if token not in text:
                errors.append(f"{target.relative_to(ROOT)} missing canonical dispatch token: {token}")

    return errors


def collect_agent_display_profile_errors() -> list[str]:
    errors: list[str] = []
    install_script = DELIVERY_ROOT / "scripts" / "install.py"
    if not install_script.is_file():
        return [f"missing installer for display profile checks: {install_script.relative_to(ROOT)}"]

    source_text = install_script.read_text(encoding="utf-8")
    for token in (
        "AGENT_DISPLAY_PROFILES",
        "CODEX_NICKNAME_RE",
        "nickname_candidates",
        "CODEX_AGENT_MODELS",
        "model_reasoning_effort",
        "CODEX_AGENT_REASONING_PROFILES",
        "meta-dev-debugger",
        "meta-se-critical",
        "meta-qa-critical",
        "claude_color",
        "pm-wu",
        "doc-wei",
        "render_qoder_agent",
        "EFFORT_TO_QODER_MAP",
        "QODER_EFFORT_VALUES",
    ):
        if token not in source_text:
            errors.append(f"{install_script.relative_to(ROOT)} missing display profile token: {token}")

    with tempfile.TemporaryDirectory(prefix="meta-flow-display-") as tmp:
        project_root = Path(tmp)
        isolated_home = project_root / "home"
        isolated_home.mkdir()
        subprocess_env = {**os.environ, "HOME": str(isolated_home)}
        for platform in ("codex", "claude", "qoder"):
            result = subprocess.run(
                [
                    sys.executable,
                    str(install_script),
                    platform,
                    "--scope",
                    "project",
                    "--project-dir",
                    str(project_root),
                    "--component",
                    "agent",
                ],
                cwd=ROOT,
                env=subprocess_env,
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout + result.stderr
            if result.returncode != 0:
                errors.append(f"{platform} display profile install failed with exit {result.returncode}: {output.strip()}")
                continue

        for agent_name, expected in EXPECTED_CODEX_NICKNAMES.items():
            agent_path = project_root / ".codex" / "agents" / f"{agent_name}.toml"
            if not agent_path.is_file():
                errors.append(f"missing codex agent for nickname check: {agent_path}")
                continue
            try:
                payload = tomllib.loads(agent_path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as exc:
                errors.append(f"codex agent TOML invalid for nickname check: {agent_path} -> {exc}")
                continue
            actual = payload.get("nickname_candidates")
            if actual != expected:
                errors.append(f"{agent_path.relative_to(project_root)} nickname_candidates must be {expected}, got {actual}")
            if isinstance(actual, list):
                invalid = [str(item) for item in actual if not CODEX_NICKNAME_RE.fullmatch(str(item))]
                if invalid:
                    errors.append(f"{agent_path.relative_to(project_root)} has invalid Codex nickname_candidates: {invalid}")
            expected_effort = EXPECTED_CODEX_REASONING_EFFORTS[agent_name]
            actual_effort = payload.get("model_reasoning_effort")
            if actual_effort != expected_effort:
                errors.append(
                    f"{agent_path.relative_to(project_root)} model_reasoning_effort must be "
                    f"{expected_effort}, got {actual_effort}"
                )
            expected_model = EXPECTED_CODEX_MODELS[agent_name]
            actual_model = payload.get("model")
            if actual_model != expected_model:
                errors.append(
                    f"{agent_path.relative_to(project_root)} model must be "
                    f"{expected_model}, got {actual_model}"
                )

        for agent_name, expected_color in EXPECTED_CLAUDE_COLORS.items():
            agent_path = project_root / ".claude" / "agents" / f"{agent_name}.md"
            if not agent_path.is_file():
                errors.append(f"missing claude agent for color check: {agent_path}")
                continue
            text = agent_path.read_text(encoding="utf-8")
            fields = parse_frontmatter(text)
            if "nickname_candidates" in fields:
                errors.append(f"{agent_path.relative_to(project_root)} frontmatter must not contain Codex nickname_candidates")
            actual_color = fields.get("color")
            if actual_color != expected_color:
                errors.append(f"{agent_path.relative_to(project_root)} color must be {expected_color}, got {actual_color}")
            tools = {item.strip() for item in fields.get("tools", "").split(",") if item.strip()}
            if agent_name in CLAUDE_DIRECT_ASK_AGENTS and "AskUserQuestion" not in tools:
                errors.append(f"{agent_path.relative_to(project_root)} direct-ask agent must include AskUserQuestion in tools")
            if agent_name in CLAUDE_NO_DIRECT_ASK_AGENTS and "AskUserQuestion" in tools:
                errors.append(f"{agent_path.relative_to(project_root)} non-direct-ask agent must not include AskUserQuestion in tools")

        for agent_name, expected_effort in EXPECTED_CODEX_REASONING_EFFORTS.items():
            agent_path = project_root / ".qoder" / "agents" / f"{agent_name}.md"
            if not agent_path.is_file():
                errors.append(f"missing qoder agent for effort check: {agent_path}")
                continue
            text = agent_path.read_text(encoding="utf-8")
            fields = parse_frontmatter(text)
            if "nickname_candidates" in fields:
                errors.append(f"{agent_path.relative_to(project_root)} frontmatter must not contain Codex nickname_candidates")
            actual_effort = fields.get("effort")
            if actual_effort != expected_effort:
                errors.append(
                    f"{agent_path.relative_to(project_root)} effort must be "
                    f"{expected_effort}, got {actual_effort}"
                )

        for agent_name, expected_color in EXPECTED_CLAUDE_COLORS.items():
            agent_path = project_root / ".qoder" / "agents" / f"{agent_name}.md"
            if not agent_path.is_file():
                errors.append(f"missing qoder agent for color check: {agent_path}")
                continue
            text = agent_path.read_text(encoding="utf-8")
            fields = parse_frontmatter(text)
            actual_color = fields.get("color")
            if actual_color != expected_color:
                errors.append(f"{agent_path.relative_to(project_root)} color must be {expected_color}, got {actual_color}")
            tools = {item.strip() for item in fields.get("tools", "").split(",") if item.strip()}
            if agent_name in CLAUDE_DIRECT_ASK_AGENTS and "AskUserQuestion" not in tools:
                errors.append(f"{agent_path.relative_to(project_root)} direct-ask agent must include AskUserQuestion in tools")
            if agent_name in CLAUDE_NO_DIRECT_ASK_AGENTS and "AskUserQuestion" in tools:
                errors.append(f"{agent_path.relative_to(project_root)} non-direct-ask agent must not include AskUserQuestion in tools")

    return errors


def collect_human_gate_protocol_errors() -> list[str]:
    errors: list[str] = []
    validator = ROOT / "meta_flow" / "checks" / "human_gate.py"
    if not validator.is_file():
        errors.append(f"missing human gate validator: {validator.relative_to(ROOT)}")
    else:
        result = subprocess.run(
            [sys.executable, str(validator), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0:
            errors.append(f"human gate validator --help failed with exit {result.returncode}: {output.strip()}")
        for token in ("--checkpoint", "--launch-message-file", "Decision Brief"):
            if token not in output:
                errors.append(f"human gate validator help missing token: {token}")

    wrapper = ROOT / "scripts" / "check_human_gate_decision_brief.py"
    if not wrapper.is_file():
        errors.append(f"missing human gate compatibility wrapper: {wrapper.relative_to(ROOT)}")
    else:
        wrapper_text = wrapper.read_text(encoding="utf-8")
        if "meta_flow.checks.human_gate" not in wrapper_text:
            errors.append("human gate compatibility wrapper must delegate to meta_flow.checks.human_gate")

    token_targets = {
        "checkpoint-manager": (
            DELIVERY_ROOT / "skills" / "checkpoint-manager" / "SKILL.md",
            ("Human Gate Launch Protocol", "决策类型", "Decision Collection Coverage", "决策收集覆盖", "不授权项", "meta-flow check human-gate", "CP8 后续跟踪分流表"),
        ),
        "state-router": (
            DELIVERY_ROOT / "skills" / "state-router" / "SKILL.md",
            ("GATE-LEDGER.ndjson", "Decision Brief", "decision_collection_coverage", "pending_non_authorized_items", "meta-flow check human-gate"),
        ),
        "state-template": (
            DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md",
            ("GATE-LEDGER.ndjson", "Decision Brief", "decision_collection_coverage", "pending_non_authorized_items", "follow_up_tracking_path"),
        ),
        "human-gate-validator": (
            ROOT / "meta_flow" / "checks" / "human_gate.py",
            ("Decision Collection Coverage", "决策收集覆盖", "候选问题数", "纳入待决策数"),
        ),
        "ask-user-generator": (
            ROOT / "meta_flow" / "ask_user.py",
            ("request_user_input", "exact_text_fallback", "collect_launch_message_errors", "修改: <具体修改点>"),
        ),
        "cli-ask-user": (
            ROOT / "meta_flow" / "cli.py",
            ("ask-user", "下一步准确提示词", "request_user_input", "continue/agree"),
        ),
        "change-impact-analysis": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "SKILL.md",
            ("FOLLOW-UP-TRACKING-TEMPLATE.md", "candidate", "converted-to-spike", "superseded", "冲突预检"),
        ),
        "cr-template": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "templates" / "CR-TEMPLATE.md",
            ("后续事项台账", "candidate", "active", "closed"),
        ),
        "follow-up-template": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "templates" / "FOLLOW-UP-TRACKING-TEMPLATE.md",
            ("candidate", "active", "blocked", "converted-to-spike", "superseded", "不授权范围", "启动候选 CR", "冲突预检"),
        ),
        "meta-qa": (
            DELIVERY_ROOT / "agents" / "meta-qa.md",
            ("follow-up tracking", "not_authorized", "runtime_authorization", "后续 CR 候选"),
        ),
        "meta-doc": (
            DELIVERY_ROOT / "agents" / "meta-doc.md",
            ("CP8 后续跟踪", "不授权项", "follow-up tracking"),
        ),
        "skills-readme": (
            DELIVERY_ROOT / "skills" / "README.md",
            ("GATE-LEDGER.ndjson", "Human Gate Launch Protocol", "follow-up tracking"),
        ),
        "delivery-agents-rule": (
            DELIVERY_ROOT / "rules" / "AGENTS.md",
            ("Human Gate Launch Protocol", "GATE-LEDGER.ndjson", "不授权项", "FOLLOW-UP", "启动后续 CR", "冲突预检"),
        ),
        "root-agents-rule": (
            ROOT / "AGENTS.md",
            ("Human Gate Launch Protocol", "GATE-LEDGER.ndjson", "不授权项", "FOLLOW-UP", "启动后续 CR", "冲突预检"),
        ),
        "readme": (
            ROOT / "README.md",
            ("GATE-LEDGER.ndjson", "不授权项", "follow-up tracking", "启动后续 CR", "CR 冲突预检"),
        ),
        "delivery-readme": (
            DELIVERY_ROOT / "README.md",
            ("GATE-LEDGER.ndjson", "不授权项", "follow-up tracking", "启动后续 CR", "CR 冲突预检"),
        ),
        "user-manual": (
            DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
            ("GATE-LEDGER.ndjson", "不授权项", "follow-up tracking", "启动后续 CR", "CR 冲突预检"),
        ),
    }
    for label, (target, tokens) in token_targets.items():
        if not target.is_file():
            if is_optional_generated_root_rule(target):
                continue
            errors.append(f"missing human gate protocol target {label}: {target.relative_to(ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        missing = [token for token in tokens if token not in text]
        if missing:
            errors.append(f"{target.relative_to(ROOT)} missing human gate protocol tokens: {', '.join(missing)}")
    return errors


def collect_cr_tracking_protocol_errors() -> list[str]:
    errors: list[str] = []
    validator = ROOT / "meta_flow" / "checks" / "cr_tracking.py"
    if not validator.is_file():
        errors.append(f"missing CR tracking validator: {validator.relative_to(ROOT)}")
    else:
        result = subprocess.run(
            [sys.executable, str(validator), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0:
            errors.append(f"CR tracking validator --help failed with exit {result.returncode}: {output.strip()}")
        for token in ("STATE.active_change", "follow-up", "CR-INDEX.json", "--project-root"):
            if token not in output:
                errors.append(f"CR tracking validator help missing token: {token}")

    wrapper = ROOT / "scripts" / "check_cr_tracking_consistency.py"
    if not wrapper.is_file():
        errors.append(f"missing CR tracking compatibility wrapper: {wrapper.relative_to(ROOT)}")
    else:
        wrapper_text = wrapper.read_text(encoding="utf-8")
        if "meta_flow.checks.cr_tracking" not in wrapper_text:
            errors.append("CR tracking compatibility wrapper must delegate to meta_flow.checks.cr_tracking")

    token_targets = {
        "state-router": (
            DELIVERY_ROOT / "skills" / "state-router" / "SKILL.md",
            ("cr_tracking", "CR-INDEX.json", "meta-flow check cr-tracking", "active formal CR", "stale_status_conflicts"),
        ),
        "state-template": (
            DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md",
            ("cr_tracking_ref", "follow_up_candidates_ref", "spike_candidates_ref", "stale_status_conflicts_ref", "CR-INDEX.json"),
        ),
        "change-impact-analysis": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "SKILL.md",
            ("CR-INDEX-TEMPLATE.yaml", "meta-flow check cr-tracking", "CR-LEDGER.ndjson", "stale_status_conflicts"),
        ),
        "cr-template": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "templates" / "CR-TEMPLATE.md",
            ("cr_index_path", "CR-LEDGER.ndjson", "CR-INDEX.json", "meta-flow check cr-tracking"),
        ),
        "follow-up-template": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "templates" / "FOLLOW-UP-TRACKING-TEMPLATE.md",
            ("cr_index_path", "CR-LEDGER.ndjson", "CR-INDEX.json", "状态索引同步", "meta-flow check cr-tracking"),
        ),
        "cr-index-template": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "templates" / "CR-INDEX-TEMPLATE.yaml",
            ("active_crs", "follow_up_candidates", "spike_candidates", "stale_status_conflicts", "conflict_keys"),
        ),
        "skills-readme": (
            DELIVERY_ROOT / "skills" / "README.md",
            ("CR-LEDGER.ndjson", "CR-INDEX.json", "CR 跟踪一致性检查"),
        ),
        "delivery-agents-rule": (
            DELIVERY_ROOT / "rules" / "AGENTS.md",
            ("CR 跟踪状态查询", "CR-LEDGER.ndjson", "CR-INDEX.json", "stale_status_conflicts"),
        ),
        "root-agents-rule": (
            ROOT / "AGENTS.md",
            ("CR 跟踪状态查询", "CR-LEDGER.ndjson", "CR-INDEX.json", "stale_status_conflicts"),
        ),
        "readme": (
            ROOT / "README.md",
            ("CR-INDEX.json", "meta-flow check cr-tracking", "active formal CR", "stale_status_conflicts"),
        ),
        "delivery-readme": (
            DELIVERY_ROOT / "README.md",
            ("CR-INDEX.json", "meta-flow check cr-tracking", "active formal CR", "stale_status_conflicts"),
        ),
        "user-manual": (
            DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
            ("CR-INDEX.json", "meta-flow check cr-tracking", "active formal CR", "stale_status_conflicts"),
        ),
    }
    for label, (target, tokens) in token_targets.items():
        if not target.is_file():
            if is_optional_generated_root_rule(target):
                continue
            errors.append(f"missing CR tracking protocol target {label}: {target.relative_to(ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        missing = [token for token in tokens if token not in text]
        if missing:
            errors.append(f"{target.relative_to(ROOT)} missing CR tracking protocol tokens: {', '.join(missing)}")
    return errors


def collect_native_cr_governance_errors() -> list[str]:
    """校验 native CR、合并确认与 Git scope freeze 的 canonical 契约。"""

    errors: list[str] = []
    token_targets = {
        "meta_flow/workflow/cr_index.py": (
            "semantic_digest",
            "CR_INDEX_REL",
        ),
        "meta_flow/workflow/cr_status_sync.py": (
            "plan_status_sync",
            "apply_status_sync",
            "semantic_digest",
        ),
        "meta_flow/workflow/cr_status_transaction.py": (
            "inspect_status_sync_transactions",
            "recover_status_sync_transaction",
            "before_content_ref",
            "index-last",
        ),
        "meta_flow/checks/cr_tracking.py": (
            "validate_cr_index_projection",
            "validate_native_transition",
            "semantic_digest mismatch",
        ),
        "meta_flow/work/decision_bundle.py": (
            "bundle_id",
            "revision",
            "subgate_idempotency_key",
            "subgate_skipped_by_stop",
        ),
        "meta_flow/work/git_inventory.py": (
            "tracked_regular",
            "tracked_symlink",
            "prospective_untracked",
            "ignored_generated",
            "outside_repo",
            "staged_symmetric_difference",
        ),
        "delivery/rules/AGENTS.md": (
            "可删除重建投影",
            "Decision Bundle",
            "Git index 八分类",
            "禁止 `git add -f`",
        ),
        "delivery/rules/AGENT-SKILL-CONTRACT.md": (
            "native index rebuild",
            "Decision Bundle revision",
            "staged symmetric difference",
        ),
        "delivery/rules/DIRECTORY-CONTRACT.md": (
            "disposable projection",
            "status-sync",
            "Decision Bundle evidence",
        ),
        "delivery/doc/USER-MANUAL.md": (
            "Native CR 状态与可重建索引",
            "合并确认与 exact Git scope",
            "status-sync-inspect",
        ),
        "tests/test_cr056_decision_bundle.py": (
            "stop",
            "revision",
        ),
        "tests/test_cr056_git_index_inventory.py": (
            "tracked_symlink",
            "ignored_generated",
            "symmetric_difference",
        ),
    }
    for relative, tokens in token_targets.items():
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing native CR governance target: {relative}")
            continue
        content = path.read_text(encoding="utf-8")
        missing = [token for token in tokens if token not in content]
        if missing:
            errors.append(
                f"{relative} missing native CR governance tokens: {', '.join(missing)}"
            )

    manual_alias = ROOT / "docs" / "USER-MANUAL.md"
    if not manual_alias.is_symlink() or manual_alias.readlink().as_posix() != "../delivery/doc/USER-MANUAL.md":
        errors.append("docs/USER-MANUAL.md must remain the tracked delivery manual symlink alias")
    return errors


def collect_requirement_intake_routing_errors() -> list[str]:
    errors: list[str] = []
    token_targets = {
        "cr-model": (
            ROOT / "meta_flow" / "workflow" / "cr_model.py",
            (
                "product_baseline_refresh_required",
                "required_phase",
                "required_agent",
                "required_gate",
                "block_story_decomposition_until",
                "affected_product_docs",
                "affected_use_cases",
                "routing_design_ref",
            ),
        ),
        "cr-records": (
            ROOT / "meta_flow" / "workflow" / "cr_records.py",
            (
                "product_baseline_refresh_required",
                "required_phase",
                "required_agent",
                "required_gate",
                "block_story_decomposition_until",
                "affected_product_docs",
                "affected_use_cases",
                "routing_design_ref",
            ),
        ),
        "cr-projection": (
            ROOT / "meta_flow" / "workflow" / "cr_projection.py",
            (
                "product_baseline_refresh_required",
                "required_phase",
                "required_agent",
                "required_gate",
                "block_story_decomposition_until",
                "affected_product_docs",
                "affected_use_cases",
                "routing_design_ref",
            ),
        ),
        "cr-index": (
            ROOT / "meta_flow" / "workflow" / "cr_index.py",
            (
                "CR_INDEX_REL",
            ),
        ),
        "cr-model-tests": (
            ROOT / "tests" / "test_cr_model.py",
            (
                "product_baseline_refresh_required",
                "requirement-clarification",
                "meta-pm",
                "CP2-approved",
                "affected_product_docs",
                "affected_use_cases",
                "routing_design_ref",
            ),
        ),
        "change-impact-analysis": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "SKILL.md",
            (
                "CR first 不等于跳过产品澄清",
                "大块集中需求默认是目标包",
                "product_baseline_refresh_required",
                "required_phase=requirement-clarification",
                "required_agent=meta-pm",
                "required_gate=CP2",
                "block_story_decomposition_until=CP2-approved",
            ),
        ),
        "cr-template": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "templates" / "CR-TEMPLATE.md",
            (
                "product_baseline_refresh_required",
                "required_phase",
                "required_agent",
                "required_gate",
                "block_story_decomposition_until",
                "affected_product_docs",
                "affected_use_cases",
                "routing_design_ref",
                "产品基线重整门禁",
            ),
        ),
        "cr-index-template": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "templates" / "CR-INDEX-TEMPLATE.yaml",
            (
                "product_baseline_refresh_required",
                "required_phase",
                "required_agent",
                "required_gate",
                "block_story_decomposition_until",
                "affected_product_docs",
                "affected_use_cases",
                "routing_design_ref",
            ),
        ),
        "state-router": (
            DELIVERY_ROOT / "skills" / "state-router" / "SKILL.md",
            (
                "CR 产品基线重整优先路由",
                "product_baseline_refresh_required=true",
                "delegate_product_baseline_refresh",
                "block_story_decomposition_until=CP2-approved",
                "大块集中需求默认归类为目标包",
            ),
        ),
        "state-template": (
            DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md",
            (
                "requirement_intake_routing",
                "pending-product-baseline-refresh",
                "product_baseline_refresh_required",
                "delegate_product_baseline_refresh",
                "CP2-approved",
                "story_decomposition",
            ),
        ),
        "delivery-agents-rule": (
            DELIVERY_ROOT / "rules" / "AGENTS.md",
            (
                "CR first 不等于跳过产品澄清",
                "大块集中需求入口分流",
                "meta-pm",
                "CP2",
                "目标包",
            ),
        ),
        "root-agents-rule": (
            ROOT / "AGENTS.md",
            (
                "CR first 不等于跳过产品澄清",
                "大块集中需求入口分流",
                "meta-pm",
                "CP2",
                "目标包",
            ),
        ),
    }
    for label, (target, tokens) in token_targets.items():
        if not target.is_file():
            if is_optional_generated_root_rule(target):
                continue
            errors.append(f"missing requirement intake routing target {label}: {target.relative_to(ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        missing = [token for token in tokens if token not in text]
        if missing:
            errors.append(f"{target.relative_to(ROOT)} missing requirement intake routing tokens: {', '.join(missing)}")
    return errors


def parse_frontmatter(content: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def collect_git_changed_paths() -> set[str]:
    targets = list(REVISION_RECORD_TARGETS)
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", *targets],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def has_revision_record(content: str) -> bool:
    return "## 修订记录" in content


def cr_marks_document_changed(cr_path: Path, rel_path: str) -> bool:
    doc_name = Path(rel_path).name
    text = cr_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        normalized = line.replace("`", "")
        if rel_path not in normalized and doc_name not in normalized:
            continue
        if re.search(r"\|\s*false\s*\|", normalized):
            continue
        if re.search(r"\|\s*true\s*\|", normalized) or any(
            word in normalized for word in ("原文档更新", "新增", "修改", "更新", "重定义", "删除", "归档")
        ):
            return True
    return False


def collect_revision_record_errors() -> list[str]:
    errors: list[str] = []
    changed_paths = collect_git_changed_paths()
    cr_paths = sorted(CHANGE_ROOT.glob("CR-*.md")) if CHANGE_ROOT.is_dir() else []

    for rel_path, abs_path in REVISION_RECORD_TARGETS.items():
        if not abs_path.is_file():
            continue

        changed_now = rel_path in changed_paths
        changed_by_cr = any(cr_marks_document_changed(cr_path, rel_path) for cr_path in cr_paths)
        if not changed_now and not changed_by_cr:
            continue

        content = abs_path.read_text(encoding="utf-8")
        if not has_revision_record(content):
            errors.append(f"{rel_path} changed under CR flow but is missing required '## 修订记录'")

    return errors


def collect_software_workflow_artifact_errors() -> list[str]:
    errors: list[str] = []

    for rel_path in SOFTWARE_WORKFLOW_REQUIRED_FILES:
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing software workflow artifact file: {rel_path}")

    for rel_path, required_tokens in SOFTWARE_WORKFLOW_TOKEN_TARGETS.items():
        path = ROOT / rel_path
        if not path.is_file():
            if is_optional_generated_root_rule(path):
                continue
            errors.append(f"missing software workflow token target: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append(f"{rel_path} missing software workflow tokens: {', '.join(missing)}")

    forbidden_tokens = {
        "delivery/skills/implementation-design/SKILL.md": ("ARCHITECTURE.md", "process/ARCHITECTURE.md"),
    }
    for rel_path, tokens in forbidden_tokens.items():
        path = ROOT / rel_path
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        present = [token for token in tokens if token in text]
        if present:
            errors.append(f"{rel_path} contains deprecated software workflow tokens: {', '.join(present)}")

    return errors


def collect_context_capsule_protocol_errors() -> list[str]:
    errors: list[str] = []
    capsule_template = DELIVERY_ROOT / "skills" / "context-manifest-builder" / "templates" / "CONTEXT-CAPSULE-TEMPLATE.yaml"
    if not capsule_template.is_file():
        errors.append(f"missing context capsule template: {capsule_template.relative_to(ROOT)}")
    else:
        text = capsule_template.read_text(encoding="utf-8")
        for token in (
            "token_control:",
            "read_profile",
            "full_doc_read_policy",
            "must_read:",
            "read_if_needed:",
            "do_not_read_by_default:",
            "process/current/CURRENT.json",
            "process/archive/**",
            "risks_and_decisions:",
            "read_expansion_log:",
        ):
            if token not in text:
                errors.append(f"{capsule_template.relative_to(ROOT)} missing context capsule token: {token}")

    state_template = DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md"
    if state_template.is_file():
        text = state_template.read_text(encoding="utf-8")
        required_tokens = (
            "read_expansion_ledger_ref",
            "process/state/READ-EXPANSION-LEDGER.ndjson",
            "process/context/CP2-REQUIREMENT-CONTEXT.yaml",
            "process/context/CP8-DELIVERY-CONTEXT.yaml",
            "workflow_health_ref",
            "same_question_rounds_max",
            "decision_brief_profile",
            "route_validation",
            "forbidden_roots_when_production",
        )
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append(f"{state_template.relative_to(ROOT)} missing context/state tokens: {', '.join(missing)}")
    else:
        errors.append(f"missing state template for context protocol: {state_template.relative_to(ROOT)}")

    targets = {
        "delivery/skills/context-manifest-builder/SKILL.md": (
            "process/context/<CP>-<slug>-CONTEXT.yaml",
            "full_doc_read_reason",
            "read_expansion_log",
            "CONTEXT-CAPSULE-TEMPLATE.yaml",
        ),
        "delivery/skills/context-handoff/SKILL.md": (
            "context_policy:",
            "capsule_first",
            "full_doc_read_reason",
            "read_expansion_log",
        ),
        "delivery/skills/checkpoint-manager/SKILL.md": (
            "Context Capsule Summary",
            "decision_brief_profile",
            "full|compact|summary",
            "blocking / high-risk",
        ),
        "delivery/skills/state-router/SKILL.md": (
            "Context Capsule 与读取预算",
            "Workflow Health 失败模式阈值",
            "read_expansion_log",
            "phase_elapsed_rounds",
        ),
        "delivery/skills/platform-validator/SKILL.md": (
            "Production delivery route",
            "route_validation",
            "user_confirmed_output_route",
            "forbidden_roots_when_production",
        ),
        "delivery/agents/meta-pm.md": ("CP2-REQUIREMENT-CONTEXT.yaml", "read_expansion_log"),
        "delivery/agents/meta-se.md": ("CP3-DESIGN-CONTEXT.yaml", "CP5-LLD-CONTEXT.yaml", "read_expansion_log"),
        "delivery/agents/meta-dev.md": ("CP5-LLD-CONTEXT.yaml", "CP6-IMPLEMENTATION-CONTEXT.yaml", "read_expansion_log"),
        "delivery/agents/meta-qa.md": ("CP7-VERIFICATION-CONTEXT.yaml", "CP8-DELIVERY-CONTEXT.yaml", "route_validation"),
        "delivery/agents/meta-doc.md": ("CP8-DELIVERY-CONTEXT.yaml", "read_expansion_log"),
        "delivery/skills/README.md": ("process/context/*-CONTEXT.yaml", "READ-EXPANSION-LEDGER.ndjson", "workflow_health_ref"),
        "delivery/rules/AGENTS.md": ("全阶段 Context Capsule", "上下文预算", "Workflow Health", "Decision Brief 压缩"),
        "AGENTS.md": ("全阶段 Context Capsule", "上下文预算", "Workflow Health", "Decision Brief 压缩"),
        "README.md": ("process/context/", "decision_brief_profile", "Context Capsule"),
        "delivery/README.md": ("process/context/", "decision_brief_profile", "Context Capsule"),
        "delivery/doc/USER-MANUAL.md": ("process/context/*-CONTEXT.yaml", "decision_brief_profile", "Context Capsule"),
    }
    for rel_path, tokens in targets.items():
        path = ROOT / rel_path
        if not path.is_file():
            if is_optional_generated_root_rule(path):
                continue
            errors.append(f"missing context protocol target: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in tokens if token not in text]
        if missing:
            errors.append(f"{rel_path} missing context protocol tokens: {', '.join(missing)}")

    cp7_values = {"PASS", "PASS_WITH_RISK", "BLOCKED", "NEEDS_REWORK", "NEEDS_DESIGN_CLARIFICATION", "WAIVED"}
    cp7_targets = [
        DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md",
        DELIVERY_ROOT / "skills" / "state-router" / "SKILL.md",
        DELIVERY_ROOT / "skills" / "checkpoint-manager" / "SKILL.md",
        DELIVERY_ROOT / "agents" / "meta-qa.md",
    ]
    for target in cp7_targets:
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        missing = sorted(value for value in cp7_values if value not in text)
        if missing:
            errors.append(f"{target.relative_to(ROOT)} missing CP7 result values: {', '.join(missing)}")

    release_values = {"READY", "READY_WITH_RISK", "NOT_READY", "RELEASED", "FAILED"}
    release_targets = [
        DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md",
        DELIVERY_ROOT / "skills" / "release-readiness" / "SKILL.md",
        DELIVERY_ROOT / "skills" / "release-readiness" / "templates" / "RELEASE-CONTEXT-TEMPLATE.yaml",
        DELIVERY_ROOT / "agents" / "meta-qa.md",
    ]
    for target in release_targets:
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        missing = sorted(value for value in release_values if value not in text)
        if missing:
            errors.append(f"{target.relative_to(ROOT)} missing release decision values: {', '.join(missing)}")

    return errors


def collect_agent_skill_contract_errors() -> list[str]:
    errors: list[str] = []

    for rel_path in AGENT_SKILL_CONTRACT_REQUIRED_FILES:
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing agent/skill contract file: {rel_path}")

    for rel_path, required_tokens in AGENT_SKILL_CONTRACT_TOKEN_TARGETS.items():
        path = ROOT / rel_path
        if not path.is_file():
            if is_optional_generated_root_rule(path):
                continue
            errors.append(f"missing agent/skill contract target: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append(f"{rel_path} missing agent/skill contract tokens: {', '.join(missing)}")

    return errors


def collect_read_expansion_delivery_contract_errors() -> list[str]:
    """确保交付面只生成 v2 扩读理由并暴露逐理由机器证据。"""

    errors: list[str] = []
    legacy_reason = "deep" + "_review"
    template_root = (
        DELIVERY_ROOT / "skills" / "context-manifest-builder" / "templates"
    )
    policy_path = template_root / "READ-POLICY-TEMPLATE.json"
    story_path = template_root / "STORY-CONTEXT-PACKET-TEMPLATE.json"
    retention_path = template_root / "RETENTION-POLICY-TEMPLATE.json"
    payloads: dict[str, dict[str, object]] = {}
    for path in (policy_path, story_path, retention_path):
        relative = path.relative_to(ROOT).as_posix()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{relative} is not valid JSON: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{relative} must contain one JSON object")
            continue
        payloads[relative] = payload

    expected = list(ACTIVE_READ_EXPANSION_REASONS)
    for path in (policy_path, story_path):
        relative = path.relative_to(ROOT).as_posix()
        payload = payloads.get(relative)
        if payload is None:
            continue
        actual = payload.get("full_doc_read_allowed_when")
        if actual != expected:
            errors.append(
                f"{relative} full_doc_read_allowed_when must equal v2 exact reasons"
            )

    policy = payloads.get(policy_path.relative_to(ROOT).as_posix())
    if policy is not None:
        evidence = policy.get("full_doc_read_reason_evidence")
        if not isinstance(evidence, dict) or list(evidence) != expected:
            errors.append(
                "READ-POLICY-TEMPLATE.json must define evidence for every v2 reason"
            )
        elif any(not evidence.get(reason) for reason in expected):
            errors.append(
                "READ-POLICY-TEMPLATE.json reason evidence entries must be non-empty"
            )

    retention = payloads.get(retention_path.relative_to(ROOT).as_posix())
    if retention is not None and legacy_reason in json.dumps(
        retention, ensure_ascii=False
    ):
        errors.append(
            "RETENTION-POLICY-TEMPLATE.json must not generate the legacy expansion reason"
        )

    for relative in ACTIVE_READ_EXPANSION_TEXT_TARGETS:
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing active read-expansion contract target: {relative}")
            continue
        content = path.read_text(encoding="utf-8")
        if legacy_reason in content:
            errors.append(
                f"{relative} contains the legacy expansion reason in an active contract"
            )
        missing_reasons = [
            reason for reason in ACTIVE_READ_EXPANSION_REASONS if reason not in content
        ]
        if missing_reasons:
            errors.append(
                f"{relative} missing v2 read-expansion reasons: "
                + ", ".join(missing_reasons)
            )
        missing_evidence = [
            token for token in READ_EXPANSION_EVIDENCE_TOKENS if token not in content
        ]
        if missing_evidence:
            errors.append(
                f"{relative} missing read-expansion evidence tokens: "
                + ", ".join(missing_evidence)
            )
    return errors


def collect_context_budgeted_e2e_errors() -> list[str]:
    errors: list[str] = []

    for rel_path in CONTEXT_BUDGETED_E2E_REQUIRED_FILES:
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing context-budgeted e2e artifact file: {rel_path}")

    for rel_path, required_tokens in CONTEXT_BUDGETED_E2E_TOKEN_TARGETS.items():
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing context-budgeted e2e token target: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append(f"{rel_path} missing context-budgeted e2e tokens: {', '.join(missing)}")

    return errors


def collect_governance_lifecycle_errors() -> list[str]:
    errors: list[str] = []

    for rel_path in GOVERNANCE_LIFECYCLE_REQUIRED_FILES:
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing governance lifecycle artifact file: {rel_path}")

    for rel_path, required_tokens in GOVERNANCE_LIFECYCLE_TOKEN_TARGETS.items():
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing governance lifecycle token target: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append(f"{rel_path} missing governance lifecycle tokens: {', '.join(missing)}")

    return errors


def collect_governance_ownership_errors() -> list[str]:
    """把 R5 owner coverage 与 R13 增量 detector 作为机器硬门。"""

    from meta_flow.checks.detector_qualification import check_detector_qualification
    from meta_flow.semantics.ownership import validate_ownership

    report = validate_ownership(ROOT)
    errors = [
        f"governance ownership: {error}"
        for error in report.get("errors") or []
    ]
    detector = check_detector_qualification(ROOT)
    errors.extend(
        f"detector qualification: {finding}"
        for finding in detector.get("findings") or []
    )
    return errors


def collect_context_sufficiency_errors() -> list[str]:
    errors: list[str] = []

    for rel_path in CONTEXT_SUFFICIENCY_REQUIRED_FILES:
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing context sufficiency artifact file: {rel_path}")

    for rel_path, required_tokens in CONTEXT_SUFFICIENCY_TOKEN_TARGETS.items():
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing context sufficiency token target: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append(f"{rel_path} missing context sufficiency tokens: {', '.join(missing)}")

    return errors


def collect_failure_waiver_errors() -> list[str]:
    errors: list[str] = []

    for rel_path in FAILURE_WAIVER_REQUIRED_FILES:
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing failure/waiver governance artifact file: {rel_path}")

    for rel_path, required_tokens in FAILURE_WAIVER_TOKEN_TARGETS.items():
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing failure/waiver governance token target: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append(f"{rel_path} missing failure/waiver governance tokens: {', '.join(missing)}")

    return errors


def collect_canonical_mirror_errors(
    root: Path,
    pairs: tuple[tuple[str, str], ...],
) -> list[str]:
    """校验 canonical 与含一个合法 installer marker 的 mirror 语义等价。"""

    errors: list[str] = []
    for canonical_ref, mirror_ref in pairs:
        canonical = root / canonical_ref
        mirror = root / mirror_ref
        if canonical.is_symlink() or not canonical.is_file():
            errors.append(f"missing CR-058 canonical target: {canonical_ref}")
            continue
        if not mirror.exists() and not mirror.is_symlink():
            continue
        equivalent = False
        if mirror.is_file() and not mirror.is_symlink():
            try:
                canonical_text = canonical.read_text(encoding="utf-8")
                mirror_text = mirror.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                equivalent = False
            else:
                markers = list(MANAGED_MARKDOWN_LINE_RE.finditer(mirror_text))
                if len(markers) == 1 and "myflow-managed:" not in canonical_text:
                    marker = markers[0].group(0)
                    frontmatter = FRONTMATTER_RE.match(canonical_text)
                    if frontmatter is None:
                        expected = f"{marker}\n\n{canonical_text.lstrip()}"
                    else:
                        prefix = canonical_text[: frontmatter.end()].rstrip()
                        body = canonical_text[frontmatter.end() :].lstrip()
                        expected = f"{prefix}\n{marker}\n\n{body}"
                    equivalent = mirror_text == expected
        if not equivalent:
            errors.append(
                f"CR-058 canonical/mirror drift: {canonical_ref} / {mirror_ref}"
            )
    return errors


def _require_exact_object_keys(
    value: object,
    expected: set[str],
    label: str,
    errors: list[str],
) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        errors.append(f"delivery runtime contract {label} must be an object")
        return None
    actual = set(value)
    if actual != expected:
        errors.append(
            f"delivery runtime contract {label} keys must be exactly "
            f"{sorted(expected)}: found {sorted(actual)}"
        )
        return None
    return value


def _load_delivery_runtime_contract(
    root: Path,
    errors: list[str],
    contract: Mapping[str, object] | None = None,
) -> Mapping[str, object] | None:
    if contract is None:
        path = root / "delivery/rules/DELIVERY-RUNTIME-CONTRACT.json"
        if not path.is_file() or path.is_symlink():
            errors.append("missing canonical delivery runtime contract")
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid delivery runtime contract JSON: {exc}")
            return None
        contract = loaded

    top = _require_exact_object_keys(
        contract,
        {
            "schema_version",
            "kind",
            "canonical_owner_ref",
            "human_contract_refs",
            "platform_contract_ref",
            "route_contract",
            "state_contract",
            "checkpoint_contract",
            "source_roots",
            "source_mirror_pairs",
            "semantic_consumers",
            "required_tokens_by_ref",
            "forbidden_instructions",
        },
        "root",
        errors,
    )
    if top is None:
        return None
    if top["schema_version"] != 1 or top["kind"] != "DeliveryRuntimeContractV1":
        errors.append("delivery runtime contract identity must be version 1 / DeliveryRuntimeContractV1")
    if top["canonical_owner_ref"] != "delivery/rules/DELIVERY-RUNTIME-CONTRACT.json":
        errors.append("delivery runtime contract canonical_owner_ref is invalid")

    route = _require_exact_object_keys(
        top["route_contract"],
        {
            "default_mode",
            "legacy_opt_in_mode",
            "resolver_operation",
            "logical_prefix",
            "resolver_exit_2",
            "persist_resolved_path",
        },
        "route_contract",
        errors,
    )
    if route is not None and route != {
        "default_mode": "sibling-binding",
        "legacy_opt_in_mode": "relative-symlink",
        "resolver_operation": "meta-flow project resolve-ref",
        "logical_prefix": "process/",
        "resolver_exit_2": "BLOCKED",
        "persist_resolved_path": False,
    }:
        errors.append("delivery runtime route_contract semantic values are invalid")

    state = _require_exact_object_keys(
        top["state_contract"],
        {
            "machine_truth_ref",
            "discovery_projection_ref",
            "human_summary_ref",
            "execution_statuses",
            "explicit_null_handoff",
            "legacy_missing_handoff_field",
        },
        "state_contract",
        errors,
    )
    if state is not None:
        expected_state = {
            "machine_truth_ref": "process/state/STATE.current.json",
            "discovery_projection_ref": "process/current/CURRENT.json",
            "human_summary_ref": "process/STATE.md",
            "execution_statuses": [
                "idle",
                "active",
                "awaiting_gate",
                "awaiting_authorization",
                "blocked",
            ],
            "explicit_null_handoff": "authoritative-no-handoff",
            "legacy_missing_handoff_field": "discovery-fallback-allowed",
        }
        if state != expected_state:
            errors.append("delivery runtime state_contract semantic values are invalid")

    checkpoint = _require_exact_object_keys(
        top["checkpoint_contract"],
        {
            "automatic_truth_glob",
            "automatic_summary_glob",
            "human_gate_glob",
            "event_ledger_ref",
        },
        "checkpoint_contract",
        errors,
    )
    if checkpoint is not None and checkpoint != {
        "automatic_truth_glob": "process/checks/CP*.result.json",
        "automatic_summary_glob": "process/checks/CP*.summary.md",
        "human_gate_glob": "process/checkpoints/CP*.md",
        "event_ledger_ref": "process/state/CHECKPOINT-LEDGER.ndjson",
    }:
        errors.append("delivery runtime checkpoint_contract semantic values are invalid")

    _require_exact_object_keys(
        top["source_roots"],
        {"rules", "agents", "skills", "platforms"},
        "source_roots",
        errors,
    )
    return top


def collect_delivery_runtime_contract_errors(
    root: Path = ROOT,
    contract: Mapping[str, object] | None = None,
) -> list[str]:
    """校验 delivery runtime 唯一 owner、consumer 和 platform mirror 映射。"""

    errors: list[str] = []
    payload = _load_delivery_runtime_contract(root, errors, contract)
    if payload is None:
        return errors

    human_refs = payload["human_contract_refs"]
    consumer_refs = payload["semantic_consumers"]
    required = payload["required_tokens_by_ref"]
    forbidden = payload["forbidden_instructions"]
    pairs = payload["source_mirror_pairs"]
    if not isinstance(human_refs, list) or not all(isinstance(item, str) for item in human_refs):
        errors.append("delivery runtime human_contract_refs must be a string list")
    if not isinstance(consumer_refs, list) or not all(isinstance(item, str) for item in consumer_refs):
        errors.append("delivery runtime semantic_consumers must be a string list")
        consumer_refs = []
    if not isinstance(required, Mapping):
        errors.append("delivery runtime required_tokens_by_ref must be an object")
        required = {}
    if set(consumer_refs) != set(required):
        errors.append("delivery runtime semantic_consumers must exactly match required token targets")

    for rel_path, tokens in required.items():
        if not isinstance(rel_path, str) or not isinstance(tokens, list) or not all(
            isinstance(token, str) and token for token in tokens
        ):
            errors.append(f"delivery runtime required token entry is invalid: {rel_path!r}")
            continue
        path = root / rel_path
        if not path.is_file() or path.is_symlink():
            errors.append(f"missing delivery runtime semantic consumer: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in tokens if token not in text]
        if missing:
            errors.append(
                f"{rel_path} missing delivery runtime contract tokens: {', '.join(missing)}"
            )

    if not isinstance(forbidden, list):
        errors.append("delivery runtime forbidden_instructions must be a list")
    else:
        seen_rule_ids: set[str] = set()
        for index, item in enumerate(forbidden):
            rule = _require_exact_object_keys(
                item,
                {"rule_id", "token", "target_refs"},
                f"forbidden_instructions[{index}]",
                errors,
            )
            if rule is None:
                continue
            rule_id = rule["rule_id"]
            token = rule["token"]
            targets = rule["target_refs"]
            if not isinstance(rule_id, str) or not rule_id or rule_id in seen_rule_ids:
                errors.append(f"delivery runtime forbidden rule_id is invalid: {rule_id!r}")
                continue
            seen_rule_ids.add(rule_id)
            if not isinstance(token, str) or not token:
                errors.append(f"delivery runtime forbidden token is invalid: {rule_id}")
                continue
            if not isinstance(targets, list) or not targets or not all(
                isinstance(target, str) for target in targets
            ):
                errors.append(f"delivery runtime forbidden targets are invalid: {rule_id}")
                continue
            for target in targets:
                path = root / target
                if not path.is_file() or path.is_symlink():
                    errors.append(f"missing delivery runtime forbidden target: {target}")
                    continue
                if token in path.read_text(encoding="utf-8"):
                    errors.append(
                        f"delivery runtime forbidden instruction {rule_id} in {target}"
                    )

    platform_ref = payload["platform_contract_ref"]
    if not isinstance(platform_ref, str):
        errors.append("delivery runtime platform_contract_ref must be a string")
        platform_payload: Mapping[str, object] = {}
    else:
        platform_path = root / platform_ref
        try:
            loaded_platform = json.loads(platform_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid delivery runtime platform contract: {exc}")
            platform_payload = {}
        else:
            platform_payload = loaded_platform if isinstance(loaded_platform, Mapping) else {}
            if platform_payload.get("delivery_runtime_contract") != payload["canonical_owner_ref"]:
                errors.append("platform contract must reference the canonical delivery runtime contract")

    if not isinstance(pairs, list):
        errors.append("delivery runtime source_mirror_pairs must be a list")
        pairs = []
    seen_mirrors: set[str] = set()
    for index, item in enumerate(pairs):
        pair = _require_exact_object_keys(
            item,
            {"canonical_ref", "platform", "mirror_ref", "renderer"},
            f"source_mirror_pairs[{index}]",
            errors,
        )
        if pair is None:
            continue
        canonical_ref = pair["canonical_ref"]
        platform = pair["platform"]
        mirror_ref = pair["mirror_ref"]
        renderer = pair["renderer"]
        if not all(isinstance(value, str) and value for value in pair.values()):
            errors.append(f"delivery runtime source/mirror pair {index} has invalid values")
            continue
        if renderer not in {"markdown-audit", "claude-agent", "codex-agent"}:
            errors.append(f"delivery runtime source/mirror renderer is invalid: {renderer}")
        if mirror_ref in seen_mirrors:
            errors.append(f"delivery runtime mirror target is duplicated: {mirror_ref}")
        seen_mirrors.add(mirror_ref)
        if not (root / canonical_ref).is_file():
            errors.append(f"missing delivery runtime canonical source: {canonical_ref}")
        contracts = platform_payload.get("contracts", {})
        platform_spec = contracts.get(platform, {}) if isinstance(contracts, Mapping) else {}
        scopes = platform_spec.get("scopes", {}) if isinstance(platform_spec, Mapping) else {}
        project = scopes.get("project", {}) if isinstance(scopes, Mapping) else {}
        kind = "skills" if "/skills/" in canonical_ref else "agents"
        expected_root = project.get(kind) if isinstance(project, Mapping) else None
        if not isinstance(expected_root, str) or not (
            mirror_ref == expected_root or mirror_ref.startswith(expected_root.rstrip("/") + "/")
        ):
            errors.append(
                f"delivery runtime mirror target violates {platform} {kind} platform root: {mirror_ref}"
            )
    return errors


def collect_canonical_mirror_self_check_errors() -> list[str]:
    """用隔离临时目录证明 mirror 可选边界与 drift 检测未失效。"""

    pairs = (("canonical/SKILL.md", "mirror/SKILL.md"),)
    with tempfile.TemporaryDirectory(prefix="meta-flow-mirror-check-") as tmp:
        root = Path(tmp)
        canonical = root / pairs[0][0]
        mirror = root / pairs[0][1]

        missing_canonical = collect_canonical_mirror_errors(root, pairs)
        canonical.parent.mkdir(parents=True)
        canonical.write_text("---\nname: fixture\n---\n\ncanonical\n", encoding="utf-8")
        missing_mirror = collect_canonical_mirror_errors(root, pairs)
        mirror.parent.mkdir(parents=True)
        marker = (
            "<!-- myflow-managed: version=1.0.0 canonical-commit=abc1234 "
            "generated=2026-08-04T14:00:00Z -->"
        )
        mirror.write_text(
            f"---\nname: fixture\n---\n{marker}\n\ncanonical\n",
            encoding="utf-8",
        )
        valid_mirror = collect_canonical_mirror_errors(root, pairs)
        mirror.write_text(canonical.read_text(encoding="utf-8"), encoding="utf-8")
        markerless_mirror = collect_canonical_mirror_errors(root, pairs)
        mirror.write_text(f"{marker}\n\ndrift\n", encoding="utf-8")
        drifted_mirror = collect_canonical_mirror_errors(root, pairs)

    expected_missing = ["missing CR-058 canonical target: canonical/SKILL.md"]
    expected_drift = [
        "CR-058 canonical/mirror drift: canonical/SKILL.md / mirror/SKILL.md"
    ]
    errors: list[str] = []
    if missing_canonical != expected_missing:
        errors.append("CR-058 canonical/mirror self-check failed to reject missing canonical")
    if missing_mirror:
        errors.append("CR-058 canonical/mirror self-check rejected an uninstalled mirror")
    if valid_mirror:
        errors.append("CR-058 canonical/mirror self-check rejected a valid marked mirror")
    if markerless_mirror != expected_drift:
        errors.append("CR-058 canonical/mirror self-check accepted a markerless mirror")
    if drifted_mirror != expected_drift:
        errors.append("CR-058 canonical/mirror self-check failed to detect mirror drift")
    return errors


def collect_retired_cr_facade_token_errors() -> list[str]:
    """阻止仅为通过 guardrail 而把退役 owner token 回填到 facade。"""

    facade = ROOT / "meta_flow" / "workflow" / "cr_lifecycle.py"
    if not facade.is_file():
        return ["missing CR lifecycle compatibility facade"]
    retired_tokens = (
        "semantic_digest",
        "before_content_ref",
        "index-last",
        "product_baseline_refresh_required",
        "required_phase",
        "required_agent",
        "required_gate",
        "block_story_decomposition_until",
        "affected_product_docs",
        "affected_use_cases",
        "routing_design_ref",
        "CR 类型与门禁策略",
        "Checkpoint Index",
    )
    text = facade.read_text(encoding="utf-8")
    present = [token for token in retired_tokens if token in text]
    if not present:
        return []
    return [
        "meta_flow/workflow/cr_lifecycle.py must not regain retired owner tokens: "
        + ", ".join(present)
    ]


def collect_cr058_execution_closure_errors() -> list[str]:
    errors: list[str] = []
    for rel_path, required_tokens in CR058_EXECUTION_CLOSURE_TOKEN_TARGETS.items():
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing CR-058 execution closure target: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append(
                f"{rel_path} missing CR-058 execution closure tokens: "
                + ", ".join(missing)
            )

    errors.extend(collect_canonical_mirror_errors(ROOT, CR058_CANONICAL_MIRROR_PAIRS))
    errors.extend(collect_canonical_mirror_self_check_errors())
    return errors


def collect_delivery_asset_lifecycle_errors() -> list[str]:
    errors: list[str] = []

    for agent_name in sorted(LEGACY_ORCHESTRATOR_AGENT_NAMES):
        delivery_path = DELIVERY_ROOT / "agents" / f"{agent_name}.md"
        if delivery_path.exists():
            errors.append(f"legacy orchestrator agent must not remain in delivery agents: {delivery_path.relative_to(ROOT)}")

    for agent_name, archive_path in ARCHIVED_AGENT_PATHS.items():
        delivery_path = DELIVERY_ROOT / "agents" / f"{agent_name}.md"
        if delivery_path.exists():
            errors.append(f"archived agent must not remain in delivery agents: {delivery_path.relative_to(ROOT)}")
        if not archive_path.is_file():
            errors.append(f"archived agent must have process archive copy: {archive_path.relative_to(ROOT)}")
        else:
            text = archive_path.read_text(encoding="utf-8")
            if "DEPRECATED" not in text or "不得唤醒" not in text:
                errors.append(f"archived agent missing explicit deprecated/no-dispatch marker: {archive_path.relative_to(ROOT)}")

    package_builder = ROOT / "scripts" / "package_builder.py"
    if package_builder.is_file():
        text = package_builder.read_text(encoding="utf-8")
        meta_flow_match = re.search(r"META_FLOW_AGENTS\s*=\s*\{(?P<body>[^}]+)\}", text, re.DOTALL)
        if meta_flow_match and "meta-dm" in meta_flow_match.group("body"):
            errors.append(f"legacy package builder must not include archived meta-dm: {package_builder.relative_to(ROOT)}")

    active_agent_targets = [
        path for path in (DELIVERY_ROOT / "agents").glob("meta-*.md") if path.name != "meta-dm.md"
    ]
    active_agent_targets.extend([DELIVERY_ROOT / "rules" / "AGENTS.md", ROOT / "AGENTS.md"])
    for target in active_agent_targets:
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        for placeholder in NON_DELIVERED_SKILL_PLACEHOLDERS:
            if placeholder in text:
                errors.append(f"active delivery text must not reference non-delivered skill placeholder: {target.relative_to(ROOT)} -> {placeholder}")

    skills_root = DELIVERY_ROOT / "skills"
    if skills_root.is_dir():
        for skill_file in sorted(skills_root.glob("*/SKILL.md")):
            fields = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            if fields.get("status") != "active":
                errors.append(f"installed delivery skill must be active or moved out of delivery: {skill_file.relative_to(ROOT)}")

    cli_module = ROOT / "meta_flow" / "cli.py"
    if cli_module.is_file() and '"checkpoints/CP*.md"' in cli_module.read_text(encoding="utf-8"):
        errors.append(f"meta-flow CLI must use process/checkpoints fallback, not root checkpoints: {cli_module.relative_to(ROOT)}")

    return errors


def collect_process_route_contract_errors() -> list[str]:
    """阻止 vNext 消费方重新拼接发布仓 ``process`` 物理路径。"""

    errors: list[str] = []
    skill_files = sorted((DELIVERY_ROOT / "skills").glob("*/SKILL.md"))
    process_consumers = [
        path
        for path in skill_files
        if "process/" in path.read_text(encoding="utf-8")
    ]
    if len(process_consumers) != 29:
        errors.append(
            "binding-aware canonical Skill inventory must contain exactly 29 process consumers: "
            f"found {len(process_consumers)}"
        )
    for path in process_consumers:
        text = path.read_text(encoding="utf-8")
        missing = [token for token in PROCESS_ROUTE_CONTRACT_TOKENS if token not in text]
        if missing:
            errors.append(
                f"{path.relative_to(ROOT)} missing portable process route contract tokens: "
                f"{', '.join(missing)}"
            )

    for rel_path in PROCESS_ROUTE_AGENT_TARGETS:
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing binding-aware Agent contract target: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [
            token
            for token in ("meta-flow project resolve-ref", "resolved_path", "不得自行拼 sibling")
            if token not in text
        ]
        if missing:
            errors.append(
                f"{rel_path} missing portable process route contract tokens: {', '.join(missing)}"
            )

    for path in sorted((ROOT / "meta_flow").rglob("*.py")):
        rel_path = path.relative_to(ROOT).as_posix()
        if rel_path in LEGACY_PROCESS_JOIN_ALLOWLIST:
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if DIRECT_PROCESS_JOIN_RE.search(line):
                if (
                    rel_path == "meta_flow/project/process_route.py"
                    and line.strip() == NON_GIT_FIXTURE_JOIN_LINE
                ):
                    continue
                errors.append(
                    f"{rel_path}:{line_no} directly joins a process physical path outside the closed legacy allowlist"
                )

    return errors


def _infer_installation_role(relative: str, content: str) -> str:
    """按 source symbols/path 推断角色，不读取 registry 中的期望 role。"""

    if relative.startswith("tests/fixtures/gov006/"):
        return (
            "isolated_fixture"
            if relative.endswith("fixture_runner.py")
            else "case_registry"
        )
    if relative.startswith("tests/"):
        return (
            "guardrail_test"
            if relative.endswith("test_delivery_guardrails.py")
            else "contract_test"
        )
    if relative in {
        "delivery/scripts/install.py",
        "delivery/scripts/install-cli.py",
        "meta_flow/cli.py",
    }:
        return "public_adapter"
    if relative == "meta_flow/installation/__init__.py":
        return "compatibility_facade"
    if relative in {
        "delivery/rules/AGENTS.md",
        "delivery/doc/RULES-SEMANTIC-INVENTORY.json",
        "delivery/doc/RULES-EQUIVALENCE.json",
    }:
        return "rules_source"
    if relative == "delivery/doc/PLATFORM-CONTRACTS.yaml":
        return "platform_contract"
    if relative in {
        "README.md",
        "delivery/README.md",
        "delivery/doc/USER-MANUAL.md",
    }:
        return "lifecycle_docs"
    if relative == "scripts/check_delivery_guardrails.py":
        return "guardrail_owner"
    defined_symbols: set[str] = set()
    if relative.endswith(".py"):
        try:
            tree = ast.parse(content)
        except SyntaxError:
            pass
        else:
            defined_symbols = {
                node.name
                for node in tree.body
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                )
            }
    symbol_roles = (
        ("execute_asset_action", "asset_executor"),
        ("execute_cli_action", "cli_executor"),
        ("dispatch_authorized_actions", "authorization_dispatch"),
        ("inspect_v1_for_migration", "migration_adapter"),
        ("DurableJournalStore", "durable_recovery"),
        ("validate_manifest_v2", "manifest_ownership"),
        ("validate_ownership_entry", "manifest_ownership"),
        ("observe_checkout_source_identity", "source_identity"),
        ("compare_checkpoints", "checkpoint_planner"),
        ("build_plan", "canonical_contract"),
    )
    for symbol, role in symbol_roles:
        if symbol in defined_symbols:
            return role
    if relative.endswith("/contracts.py") or relative.endswith(
        "/canonical.py"
    ):
        return "canonical_contract"
    if relative.endswith("/authorization.py") or relative.endswith(
        "/engine.py"
    ):
        return "authorization_dispatch"
    return "unknown_installation_consumer"


def _installation_candidate(relative: str, content: str) -> bool:
    if relative in INSTALLATION_ROLE_REGISTRY:
        return True
    if relative.startswith("meta_flow/installation/"):
        return True
    return any(
        marker in content
        for marker in (
            "meta_flow.installation",
            "InstallationLifecycleV2",
            "INSTALLATION_ROLE_REGISTRY",
            "tests/fixtures/gov006/CASE-REGISTRY.json",
        )
    )


def _installation_forbidden_hits(
    relative: str,
    content: str,
) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    is_python = relative.endswith(".py")
    if is_python and re.search(r"\bshell\s*=\s*True\b", content):
        hits.append({"path": relative, "rule": "shell-true"})
    if is_python and re.search(r"\bpip\s+install\b", content):
        hits.append({"path": relative, "rule": "bare-pip-install"})
    if is_python:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            hits.append({"path": relative, "rule": "python-syntax-error"})
        else:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                called = node.func
                name = (
                    called.id
                    if isinstance(called, ast.Name)
                    else called.attr
                    if isinstance(called, ast.Attribute)
                    else ""
                )
                if (
                    name == "rmtree"
                    and relative not in INSTALLATION_FIXTURE_EXCLUSIONS
                ):
                    hits.append(
                        {
                            "path": relative,
                            "rule": (
                                "recursive-delete-outside-isolated-fixture"
                            ),
                        }
                    )
                if name == "_run_reinstaller":
                    hits.append(
                        {
                            "path": relative,
                            "rule": "legacy-two-transaction-reinstall-call",
                        }
                    )
                    break
    return hits


def build_installation_guardrail_report(
    root: Path = ROOT,
    *,
    extra_sources: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """返回 exact registry 与独立 source discovery 的闭包报告。"""

    supplied = dict(extra_sources or {})
    sources: dict[str, str] = {}
    for relative in INSTALLATION_ROLE_REGISTRY:
        path = root / relative
        if relative in supplied:
            sources[relative] = supplied.pop(relative)
        elif path.is_file():
            sources[relative] = path.read_text(encoding="utf-8")

    for relative_root in INSTALLATION_DISCOVERY_ROOTS:
        scan_root = root / relative_root
        if not scan_root.is_dir():
            continue
        for path in sorted(scan_root.rglob("*")):
            if (
                not path.is_file()
                or path.is_symlink()
                or path.suffix not in {".py", ".json"}
            ):
                continue
            relative = path.relative_to(root).as_posix()
            if relative in sources:
                continue
            content = path.read_text(encoding="utf-8")
            if _installation_candidate(relative, content):
                sources[relative] = content
    sources.update(supplied)

    discovered = {
        relative: _infer_installation_role(relative, content)
        for relative, content in sorted(sources.items())
        if _installation_candidate(relative, content)
    }
    registered_paths = set(INSTALLATION_ROLE_REGISTRY)
    discovered_paths = set(discovered)
    role_mismatch = [
        {
            "path": relative,
            "registered_role": INSTALLATION_ROLE_REGISTRY[relative],
            "discovered_role": discovered[relative],
        }
        for relative in sorted(registered_paths & discovered_paths)
        if INSTALLATION_ROLE_REGISTRY[relative] != discovered[relative]
    ]
    forbidden_hits = [
        hit
        for relative, content in sorted(sources.items())
        if relative in discovered
        for hit in _installation_forbidden_hits(relative, content)
    ]
    return {
        "registry_version": "InstallationGuardrailRegistryV1",
        "scan_roots": list(INSTALLATION_DISCOVERY_ROOTS),
        "fixture_exclusions": dict(INSTALLATION_FIXTURE_EXCLUSIONS),
        "registered": [
            {"path": path, "role": role}
            for path, role in INSTALLATION_ROLE_REGISTRY.items()
        ],
        "discovered": [
            {"path": path, "role": role}
            for path, role in discovered.items()
        ],
        "registered_only": sorted(registered_paths - discovered_paths),
        "discovered_only": sorted(discovered_paths - registered_paths),
        "role_mismatch": role_mismatch,
        "forbidden_hits": forbidden_hits,
    }


def collect_installation_architecture_errors() -> list[str]:
    report = build_installation_guardrail_report()
    errors: list[str] = []
    for field in (
        "registered_only",
        "discovered_only",
        "role_mismatch",
        "forbidden_hits",
    ):
        values = report[field]
        if values:
            errors.append(
                f"installation guardrail {field} must be empty: "
                f"{json.dumps(values, ensure_ascii=False, sort_keys=True)}"
            )
    return errors


def collect_core_lifecycle_dogfood_errors(root: Path = ROOT) -> list[str]:
    """保证多 Work 核心生命周期自举验证始终属于发布硬门。"""

    errors: list[str] = []
    for relative in CORE_LIFECYCLE_DOGFOOD_FILES:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            errors.append(f"missing core lifecycle dogfood asset: {relative}")

    implementation = root / "tests/fixtures/core_lifecycle_dogfood.py"
    if implementation.is_file() and not implementation.is_symlink():
        content = implementation.read_text(encoding="utf-8")
        required_tokens = (
            "meta_flow import cli as meta_flow_cli",
            '"usage-plan"',
            '"usage-add"',
            '"close-inspect"',
            '"project", "check"',
            '"state", "check"',
            "validate_current_projection",
            "validate_governance_projection",
            '"cr-tracking"',
            '"W-000", "W-001", "W-002"',
        )
        for token in required_tokens:
            if token not in content:
                errors.append(
                    "core lifecycle dogfood missing public contract token: " + token
                )
        work_slice = content.partition("def _prepare_work(")[2].partition(
            "def _authorization_file("
        )[0]
        if "refresh_formal_truth_projection" in work_slice:
            errors.append(
                "core lifecycle dogfood must not manually refresh formal truth projections"
            )
        for forbidden in ("quant-lab", "/home/", "relative-symlink"):
            if forbidden in content:
                errors.append(
                    "core lifecycle dogfood must stay isolated and binding-only: "
                    + forbidden
                )

    for relative in CORE_LIFECYCLE_DOGFOOD_DOCS:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            errors.append(f"missing core lifecycle dogfood preflight doc: {relative}")
            continue
        if CORE_LIFECYCLE_DOGFOOD_COMMAND not in path.read_text(encoding="utf-8"):
            errors.append(
                f"core lifecycle dogfood command missing from preflight: {relative}"
            )
    return errors


def collect_errors() -> list[str]:
    RUNTIME_WARNINGS.clear()
    errors: list[str] = []
    platform_contracts = load_platform_contracts(errors)
    if platform_contracts:
        errors.extend(collect_codex_dry_run_errors(platform_contracts))
    errors.extend(collect_installer_component_errors())
    errors.extend(collect_cr004_protocol_errors())
    errors.extend(collect_guardrail_command_scope_errors())
    errors.extend(collect_agent_dispatch_evidence_errors())
    errors.extend(collect_agent_display_profile_errors())
    errors.extend(collect_human_gate_protocol_errors())
    errors.extend(collect_cr_tracking_protocol_errors())
    errors.extend(collect_native_cr_governance_errors())
    errors.extend(collect_requirement_intake_routing_errors())
    errors.extend(collect_retired_cr_facade_token_errors())
    errors.extend(collect_revision_record_errors())
    errors.extend(collect_software_workflow_artifact_errors())
    errors.extend(collect_context_capsule_protocol_errors())
    errors.extend(collect_agent_skill_contract_errors())
    errors.extend(collect_read_expansion_delivery_contract_errors())
    errors.extend(collect_context_budgeted_e2e_errors())
    errors.extend(collect_governance_lifecycle_errors())
    errors.extend(collect_governance_ownership_errors())
    errors.extend(collect_context_sufficiency_errors())
    errors.extend(collect_failure_waiver_errors())
    errors.extend(collect_cr058_execution_closure_errors())
    errors.extend(collect_delivery_runtime_contract_errors())
    errors.extend(collect_delivery_asset_lifecycle_errors())
    errors.extend(collect_process_route_contract_errors())
    errors.extend(collect_installation_architecture_errors())
    errors.extend(collect_core_lifecycle_dogfood_errors())

    binding_profile_documents = {
        relative: (ROOT / relative).read_text(encoding="utf-8")
        for relative in ("README.md", "delivery/rules/AGENTS.md")
        if (ROOT / relative).is_file()
    }
    errors.extend(binding_profile_contract_errors(binding_profile_documents))

    for child in sorted(path for path in DELIVERY_ROOT.iterdir() if path.is_dir()):
        if child.name not in ALLOWED_DELIVERY_DIRS:
            errors.append(f"delivery top-level directory not allowed: {child.relative_to(ROOT)}")

    errors.extend(collect_cache_hygiene_errors())

    delivery_scripts = DELIVERY_ROOT / "scripts"
    for path in sorted(delivery_scripts.glob("*")):
        if path.is_file() and path.name not in ALLOWED_DELIVERY_SCRIPT_FILES:
            errors.append(f"delivery/scripts only allows install entrypoints: {path.relative_to(ROOT)}")

    for path in DELIVERY_ROOT.rglob("*"):
        if not path.is_dir():
            continue
        rel = path.relative_to(DELIVERY_ROOT)
        if path.name == "templates" and (len(rel.parts) != 3 or rel.parts[0] != "skills"):
            errors.append(f"templates directory must live under delivery/skills/<skill>/templates: {path.relative_to(ROOT)}")
        if path.name == "scripts" and rel.parts[:1] != ("scripts",):
            if len(rel.parts) != 3 or rel.parts[0] != "skills":
                errors.append(f"scripts directory must live under delivery/skills/<skill>/scripts or delivery/scripts: {path.relative_to(ROOT)}")

    skills_root = DELIVERY_ROOT / "skills"
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        content = skill_file.read_text(encoding="utf-8")
        fields = parse_frontmatter(content)
        if fields.get("status") != "active":
            continue

        if "## Gotchas" not in content:
            errors.append(f"active skill must contain a Gotchas section: {skill_file.relative_to(ROOT)}")

        for match in DELIVERY_SCRIPT_REF_RE.finditer(content):
            if match.group("name") not in ALLOWED_DELIVERY_SCRIPT_FILES:
                errors.append(
                    f"active skill must not reference non-installer delivery/scripts assets: {skill_file.relative_to(ROOT)} -> {match.group('name')}"
                )
        if "delivery/review-templates" in content:
            errors.append(f"active skill must not reference shared review template directories: {skill_file.relative_to(ROOT)}")
        if re.search(r"\bpython\s+scripts/", content):
            errors.append(f"active skill must not use cwd-dependent 'python scripts/...' entrypoints: {skill_file.relative_to(ROOT)}")

        for match in SKILL_ROOT_ASSET_REF_RE.finditer(content):
            rel_path = Path(match.group("kind")) / match.group("path")
            if not (skill_dir / rel_path).exists():
                errors.append(f"active skill references missing asset: {skill_file.relative_to(ROOT)} -> {rel_path.as_posix()}")

        for match in TEMPLATE_REF_RE.finditer(content):
            rel_path = Path("templates") / match.group("path")
            if not (skill_dir / rel_path).exists():
                errors.append(f"active skill references missing asset: {skill_file.relative_to(ROOT)} -> {rel_path.as_posix()}")

    gitignore = ROOT / ".gitignore"
    if gitignore.is_file():
        text = gitignore.read_text(encoding="utf-8")
        for required in ("__pycache__/", "*.pyc"):
            if required not in text:
                errors.append(f".gitignore missing python cache rule: {required}")
        if "/.meta-flow/INSTALL-MANIFEST.yaml" not in text:
            errors.append(".gitignore must ignore only the project-local Meta Flow install manifest")
        if re.search(r"(?m)^/?\.meta-flow/?$", text):
            errors.append(".gitignore must not ignore the whole .meta-flow directory; workspace.yaml is tracked truth")

    binding_contract_tokens = {
        "README.md": (
            "route_mode=sibling-binding",
            "--process-link-mode relative-symlink",
            ".meta-flow/workspace.yaml",
        ),
        "delivery/README.md": (
            "route_mode=sibling-binding",
            "legacy Agent/Skill",
            "workspace_root",
        ),
        "delivery/doc/USER-MANUAL.md": (
            "--process-link-mode none",
            "reciprocal sibling",
            ".meta-flow/INSTALL-MANIFEST.yaml",
        ),
        "delivery/rules/AGENTS.md": (
            "route_mode=sibling-binding",
            "relative-symlink",
            "声称 binding-only 已兼容全部 legacy Skill",
        ),
        "delivery/rules/AGENT-SKILL-CONTRACT.md": (
            "Binding-only 路径兼容门",
            "调用前必须 BLOCKED",
            "route-aware prompt",
        ),
        "delivery/rules/DIRECTORY-CONTRACT.md": (
            "reciprocal portable bindings",
            "workspace_parent",
            "human navigation only",
        ),
    }
    for relative, required_tokens in binding_contract_tokens.items():
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing binding contract file: {relative}")
            continue
        content = path.read_text(encoding="utf-8")
        for token in required_tokens:
            if token not in content:
                errors.append(f"binding contract missing token: {relative} -> {token}")

    return errors


def binding_profile_contract_errors(documents: dict[str, str]) -> list[str]:
    """校验 binding-only 与 G2/legacy 扩展流程的语义边界。"""

    errors: list[str] = []
    for relative in ("README.md", "delivery/rules/AGENTS.md"):
        content = documents.get(relative, "")
        if not content:
            errors.append(f"missing binding profile contract file: {relative}")
            continue
        if BINDING_ALL_PROFILES_TOKEN not in content:
            errors.append(
                f"binding profile contract must allow G0/G1/G2: {relative}"
            )
        if BINDING_LEGACY_SELECTION_TOKEN not in content:
            errors.append(
                f"binding profile contract must make legacy G2 selection explicit: {relative}"
            )
        if re.search(r"vNext binding-only\s+G0/G1(?:\s|，)", content):
            errors.append(
                f"binding profile contract must not restrict binding-only to G0/G1: {relative}"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv or ())
    if arguments == ["--installation-report"]:
        report = build_installation_guardrail_report()
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return int(
            any(
                report[field]
                for field in (
                    "registered_only",
                    "discovered_only",
                    "role_mismatch",
                    "forbidden_hits",
                )
            )
        )
    if arguments:
        print(
            "ERROR: only --installation-report is supported",
            file=sys.stderr,
        )
        return 2
    errors = collect_errors()
    for warning in RUNTIME_WARNINGS:
        print(f"WARN: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
