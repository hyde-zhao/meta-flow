#!/usr/bin/env python3
"""Check repository guardrails for delivery asset ownership and Python cache hygiene."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DELIVERY_ROOT = ROOT / "delivery"
PROCESS_ROOT = ROOT / "process"
CHANGE_ROOT = PROCESS_ROOT / "changes"
PLATFORM_CONTRACTS = DELIVERY_ROOT / "doc" / "PLATFORM-CONTRACTS.yaml"
ALLOWED_DELIVERY_DIRS = {"agents", "doc", "rules", "scripts", "skills"}
ALLOWED_DELIVERY_SCRIPT_FILES = {"install.py", "install.sh", "install.ps1"}
REVISION_RECORD_TARGETS = {
    "docs/product/USE-CASES.md": ROOT / "docs" / "product" / "USE-CASES.md",
    "docs/product/REQUIREMENTS.md": ROOT / "docs" / "product" / "REQUIREMENTS.md",
}
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
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
        "allowed_reads",
        "do_not_read_by_default",
        "full_doc_read_reason",
        "capsule_missing",
        "field_conflict",
        "human_audit",
        "deep_review",
        "schema_validation_failed",
        "authz_policy_refs",
        "process/returns/*.return.json",
        "process/evidence/*.index.json",
        "process/checks/*.result.json",
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
        "process/state/STATE.current.json",
        "process/STATE.md",
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
    ),
    "delivery/skills/checkpoint-manager/SKILL.md": (
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "result JSON",
        "Evidence Index",
        "Story Return Packet",
        "full_doc_read_reason",
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
        "process/state/STATE.current.json",
        "do_not_read_by_default",
    ),
    "README.md": (
        "Agent / Skill",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "do_not_read_by_default",
    ),
    "AGENTS.md": (
        "Agent / Skill Contract Slimming",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "allowed_reads",
    ),
    "delivery/rules/AGENTS.md": (
        "Agent / Skill Contract Slimming",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "allowed_reads",
    ),
    "delivery/rules/CLAUDE.md": (
        "Agent / Skill Contract Slimming",
        "delivery/rules/AGENT-SKILL-CONTRACT.md",
        "process/state/STATE.current.json",
        "allowed_reads",
    ),
}
SOFTWARE_WORKFLOW_TOKEN_TARGETS = {
    "delivery/agents/meta-pm.md": ("scenario-expansion", "story-planning", "docs/product/SCENARIOS.yaml", "docs/product/TEST-MATRIX.md", "docs/product/MVP-SCOPE.md", "SGQ-*", "用户可见场景确认"),
    "delivery/agents/meta-se.md": ("blueprint-design", "implementation-design", "docs/design/BLUEPRINT.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "feature_design_refs", "lld_policy"),
    "delivery/agents/meta-dev.md": ("implementation-execution", "IMPLEMENTATION", "实现对象清单", "设计契约映射", "测试 / Fixture", "最小实现切片"),
    "delivery/agents/meta-qa.md": ("verification-execution", "quality-review", "release-readiness", "docs/quality/VERIFICATION-REPORT.md", "docs/quality/TEST-REPORT.md", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/CP7-VERIFICATION-CONTEXT.yaml", "process/context/CP8-DELIVERY-CONTEXT.yaml", "release_artifact_profile", "release_decision", "实现执行证据", "PASS_WITH_RISK"),
    "delivery/agents/README.md": ("docs/product/TEST-MATRIX.md", "Feature 设计", "verification-execution", "发布就绪"),
    "delivery/skills/README.md": ("scenario-expansion", "story-planning", "blueprint-design", "implementation-design", "implementation-execution", "verification-execution", "quality-review", "release-readiness", "process/checkpoints/CP*.md", "FEATURE-DESIGN-MATRIX.md", "lld_policy", "STORY-*-IMPLEMENTATION.md", "VERIFICATION-REPORT.md"),
    "delivery/skills/blueprint-design/templates/BLUEPRINT-TEMPLATE.md": ("决策类型", "推荐 / 备选优劣", "runtime_authorization", "follow_up_tracking"),
    "delivery/skills/story-planning/templates/MVP-SCOPE-TEMPLATE.md": ("决策类型", "推荐 / 备选优劣", "runtime_authorization", "follow_up_tracking"),
    "delivery/skills/story-planning/templates/BACKLOG-TEMPLATE.md": ("follow-up tracking", "CR-*-FOLLOW-UP-TRACKING", "STATE.md.cr_tracking"),
    "delivery/skills/release-readiness/SKILL.md": ("FEEDBACK.md", "follow-up tracking", "CR-*-FOLLOW-UP-TRACKING", "STATE.md.cr_tracking", "Release Context Capsule", "process/release/RELEASE-CONTEXT.yaml", "release_artifact_profile", "release_decision", "READY_WITH_RISK", "capsule-first"),
    "delivery/skills/release-readiness/templates/RELEASE-CONTEXT-TEMPLATE.yaml": ("release_artifact_profile", "release_decision", "quality_summary", "affected_surface", "install_validation_summary", "token_control"),
    "delivery/skills/release-readiness/templates/RELEASE-NOTES-TEMPLATE.md": ("版本号决策", "release_artifact_profile", "release_decision", "安装与升级", "回滚方式"),
    "delivery/skills/release-readiness/templates/DEPLOY-CHECKLIST-TEMPLATE.md": ("发布候选快照", "安装 / 升级 / 幂等验证矩阵", "release_decision", "不授权项"),
    "delivery/skills/release-readiness/templates/MIGRATION-TEMPLATE.md": ("兼容性判断表", "STATE.md", "Agent frontmatter", "Skill 输出格式", "命令参数"),
    "delivery/skills/release-readiness/templates/FEEDBACK-TEMPLATE.md": ("发布后观察计划", "follow-up tracking", "CR-*-FOLLOW-UP-TRACKING", "STATE.md.cr_tracking"),
    "delivery/skills/release-readiness/templates/FEEDBACK-TEMPLATE.md": ("follow-up tracking", "CR-*-FOLLOW-UP-TRACKING", "STATE.md.cr_tracking"),
    "delivery/skills/use-case-discovery/SKILL.md": ("scenario_confirmation_interactions", "SGQ-*", "不得静默场景发现", "用户可见场景确认"),
    "delivery/skills/use-case-discovery/templates/USE-CASES-TEMPLATE.md": ("用户可见场景确认证据", "SGQ-*", "confirmed", "静默生成场景"),
    "delivery/skills/implementation-execution/SKILL.md": ("IMPLEMENTATION", "实现对象清单", "设计契约映射", "测试 / Fixture", "最小实现切片", "平台差异", "handoff"),
    "delivery/skills/implementation-execution/templates/IMPLEMENTATION-TEMPLATE.md": ("实现对象清单", "设计契约映射", "单元测试 / Fixture", "最小实现切片", "平台差异", "QA / Review / Doc"),
    "delivery/skills/verification-execution/SKILL.md": ("VERIFICATION", "验证对象清单", "验证追踪矩阵", "设计契约验证", "分层验证计划", "PASS_WITH_RISK", "validation_mode"),
    "delivery/skills/verification-execution/templates/VERIFICATION-TEMPLATE.md": ("验证对象清单", "验证追踪矩阵", "设计契约验证清单", "分层验证计划", "Prompt / Skill Fixture", "阶段决策"),
    "delivery/skills/quality-review/SKILL.md": ("IMPLEMENTATION", "VERIFICATION", "实现执行证据", "验证对象清单", "设计契约映射", "Fixture", "阶段决策"),
    "delivery/skills/checkpoint-manager/SKILL.md": ("docs/product/SCENARIOS.yaml", "docs/product/TEST-MATRIX.md", "docs/design/BLUEPRINT.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "full-lld", "technical-note", "waived", "quality-review", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/*-CONTEXT.yaml", "decision_brief_profile", "release_artifact_profile", "release_decision", "实现执行证据", "IMPLEMENTATION", "验证对象清单", "PASS_WITH_RISK"),
    "delivery/skills/state-router/SKILL.md": ("docs/product/SCENARIOS.yaml", "docs/product/TEST-MATRIX.md", "docs/design/BLUEPRINT.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "design_evidence", "docs/quality/VERIFICATION-REPORT.md", "docs/quality/TEST-REPORT.md", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/*-CONTEXT.yaml", "context_budget", "workflow_health", "release_artifact_profile", "release_decision", "implementation-execution", "verification-execution", "STORY-*-IMPLEMENTATION.md", "PASS_WITH_RISK"),
    "delivery/skills/state-router/templates/STATE-TEMPLATE.md": ("artifacts:", "docs/product/SCENARIOS.yaml", "docs/design/BLUEPRINT.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "lld_policy", "docs/quality/VERIFICATION-REPORT.md", "docs/quality/TEST-REPORT.md", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "context_budget:", "workflow_health:", "decision_brief_profile", "route_validation", "release_artifact_profile_values", "release_decision_values", "implementation:", "cp7_result_values"),
    "delivery/rules/AGENTS.md": ("docs/product/SCENARIOS.yaml", "docs/product/TEST-MATRIX.md", "docs/product/MVP-SCOPE.md", "docs/design/BLUEPRINT.md", "docs/design/DOMAIN-MAP.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "lld_policy", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/", "Context Capsule", "workflow_health", "decision_brief_profile", "release_artifact_profile", "release_decision", "process/checkpoints/", "implementation-execution", "verification-execution", "IMPLEMENTATION", "VERIFICATION-REPORT", "PASS_WITH_RISK"),
    "delivery/rules/CLAUDE.md": ("docs/product/SCENARIOS.yaml", "docs/product/TEST-MATRIX.md", "docs/product/MVP-SCOPE.md", "docs/design/BLUEPRINT.md", "docs/design/DOMAIN-MAP.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "lld_policy", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/", "Context Capsule", "workflow_health", "decision_brief_profile", "release_artifact_profile", "release_decision", "process/checkpoints/", "implementation-execution", "verification-execution", "IMPLEMENTATION", "VERIFICATION-REPORT", "PASS_WITH_RISK"),
    "AGENTS.md": ("docs/product/SCENARIOS.yaml", "docs/product/TEST-MATRIX.md", "docs/product/MVP-SCOPE.md", "docs/design/BLUEPRINT.md", "docs/design/DOMAIN-MAP.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "lld_policy", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/", "Context Capsule", "workflow_health", "decision_brief_profile", "release_artifact_profile", "release_decision", "process/checkpoints/", "implementation-execution", "verification-execution", "IMPLEMENTATION", "VERIFICATION-REPORT", "PASS_WITH_RISK"),
    "README.md": ("docs/product/SCENARIOS.yaml", "docs/product/MVP-SCOPE.md", "docs/design/BLUEPRINT.md", "docs/design/FEATURE-DESIGN-MATRIX.md", "lld_policy", "docs/release/DEPLOY-CHECKLIST.md", "process/release/RELEASE-CONTEXT.yaml", "process/context/", "decision_brief_profile", "release_artifact_profile", "release_decision", "process/checkpoints/", "implementation-execution", "verification-execution", "IMPLEMENTATION", "VERIFICATION-REPORT"),
}
CACHE_SCAN_EXCLUDED_DIRS = {".git", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
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
    "meta-dm": PROCESS_ROOT / "archive" / "meta-dm.md",
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
        project = codex["scopes"]["project"]  # type: ignore[index]
        user = codex["scopes"]["user"]  # type: ignore[index]
        claude_project = claude["scopes"]["project"]  # type: ignore[index]
        claude_user = claude["scopes"]["user"]  # type: ignore[index]
        forbidden_project = codex["forbidden"]["project"]  # type: ignore[index]
        forbidden_user = codex["forbidden"]["user"]  # type: ignore[index]
    except (AttributeError, KeyError, TypeError):
        return ["platform contract missing codex/claude scopes or codex forbidden entries"]

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
                "required": ["Component: rules", str(Path.home() / ".codex" / "AGENTS.md")],
                "forbidden": [
                    str(Path.home() / ".codex" / "agents" / "meta-po.toml"),
                    str(Path.home() / ".codex" / "agents" / "host-orchestrator.toml"),
                    str(Path.home() / ".agents" / "skills"),
                ],
            },
            {
                "label": "codex project default",
                "args": ["codex", "--scope", "project", "--project-dir", str(project_root), "--dry-run"],
                "required": ["Component: full", str(project_root / "AGENTS.md"), str(project_root / ".codex" / "agents" / "meta-pm.toml"), str(project_root / ".agents" / "skills")],
                "forbidden": [".codex/skills", str(project_root / ".codex" / "agents" / "meta-po.toml"), str(project_root / ".codex" / "agents" / "host-orchestrator.toml")],
            },
            {
                "label": "claude project default",
                "args": ["claude", "--scope", "project", "--project-dir", str(project_root), "--dry-run"],
                "required": ["Component: full", str(project_root / "CLAUDE.md"), str(project_root / ".claude" / "agents" / "meta-pm.md"), str(project_root / ".claude" / "skills")],
                "forbidden": [str(project_root / ".claude" / "CLAUDE.md"), str(project_root / ".claude" / "agents" / "meta-po.md"), str(project_root / ".claude" / "agents" / "host-orchestrator.md")],
            },
            {
                "label": "codex full component",
                "args": ["codex", "--scope", "project", "--project-dir", str(project_root), "--component", "full", "--dry-run"],
                "required": ["Component: full", str(project_root / "AGENTS.md"), str(project_root / ".codex" / "agents" / "meta-pm.toml"), str(project_root / ".agents" / "skills")],
                "forbidden": [".codex/skills", str(project_root / ".codex" / "agents" / "meta-po.toml"), str(project_root / ".codex" / "agents" / "host-orchestrator.toml")],
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
        DELIVERY_ROOT / "rules" / "CLAUDE.md",
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
            errors.append(f"missing delivery routing target: {target.relative_to(ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        missing = [token for token in DELIVERY_ROUTING_TOKENS if token not in text]
        if missing:
            errors.append(f"{target.relative_to(ROOT)} missing delivery routing tokens: {', '.join(missing)}")

    state_template = DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md"
    if state_template.is_file():
        state_text = state_template.read_text(encoding="utf-8")
        for required in ("agent_lifecycle", "active_agents", "cp5_story_lld_review"):
            if required not in state_text:
                errors.append(f"{state_template.relative_to(ROOT)} missing lifecycle/state token: {required}")
    else:
        errors.append(f"missing state template: {state_template.relative_to(ROOT)}")

    handoff_skill = DELIVERY_ROOT / "skills" / "context-handoff" / "SKILL.md"
    if handoff_skill.is_file():
        handoff_text = handoff_skill.read_text(encoding="utf-8")
        for required in ("fork_context=false", "完整会话", "active_agents"):
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
        DELIVERY_ROOT / "rules" / "CLAUDE.md",
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
        if "/home/hyde/projects/meta-flow/scripts/check_delivery_guardrails.py" in text and "不得硬引用" not in text:
            errors.append(f"{target.relative_to(ROOT)} must not hard-code the meta-flow guardrail absolute path")
    return errors


def collect_agent_dispatch_evidence_errors() -> list[str]:
    errors: list[str] = []
    targets = [
        DELIVERY_ROOT / "skills" / "state-router" / "SKILL.md",
        DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md",
        DELIVERY_ROOT / "skills" / "context-handoff" / "SKILL.md",
        DELIVERY_ROOT / "skills" / "checkpoint-manager" / "SKILL.md",
        DELIVERY_ROOT / "rules" / "AGENTS.md",
        DELIVERY_ROOT / "rules" / "CLAUDE.md",
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
    for target in (state_router, state_template):
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
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
                errors.append(f"{target.relative_to(ROOT)} missing Codex dispatch/profile token: {token}")

    if state_template.is_file():
        text = state_template.read_text(encoding="utf-8")
        for token in (
            "dispatch_evidence_required",
            "active_agent_item_schema",
            "handoff-created",
            "spawn-requested",
        ):
            if token not in text:
                errors.append(f"{state_template.relative_to(ROOT)} missing dispatch state token: {token}")

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
        "model_reasoning_effort",
        "CODEX_AGENT_REASONING_PROFILES",
        "meta-dev-debugger",
        "meta-se-critical",
        "meta-qa-critical",
        "claude_color",
        "pm-wu",
        "doc-wei",
    ):
        if token not in source_text:
            errors.append(f"{install_script.relative_to(ROOT)} missing display profile token: {token}")

    with tempfile.TemporaryDirectory(prefix="meta-flow-display-") as tmp:
        project_root = Path(tmp)
        isolated_home = project_root / "home"
        isolated_home.mkdir()
        subprocess_env = {**os.environ, "HOME": str(isolated_home)}
        for platform in ("codex", "claude"):
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
            ("human_gate_decisions", "pending_human_decisions", "decision_collection_coverage", "pending_non_authorized_items", "meta-flow check human-gate"),
        ),
        "state-template": (
            DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md",
            ("human_gate_decisions", "pending_human_decisions", "decision_collection_coverage", "pending_non_authorized_items", "follow_up_tracking_path"),
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
            ("pending_human_decisions", "Human Gate Launch Protocol", "follow-up tracking"),
        ),
        "delivery-agents-rule": (
            DELIVERY_ROOT / "rules" / "AGENTS.md",
            ("Human Gate Launch Protocol", "pending_human_decisions", "不授权项", "FOLLOW-UP", "启动后续 CR", "冲突预检"),
        ),
        "delivery-claude-rule": (
            DELIVERY_ROOT / "rules" / "CLAUDE.md",
            ("Human Gate Launch Protocol", "pending_human_decisions", "不授权项", "FOLLOW-UP", "启动后续 CR", "冲突预检"),
        ),
        "root-agents-rule": (
            ROOT / "AGENTS.md",
            ("Human Gate Launch Protocol", "pending_human_decisions", "不授权项", "FOLLOW-UP", "启动后续 CR", "冲突预检"),
        ),
        "readme": (
            ROOT / "README.md",
            ("pending_human_decisions", "不授权项", "follow-up tracking", "启动后续 CR", "CR 冲突预检"),
        ),
        "delivery-readme": (
            DELIVERY_ROOT / "README.md",
            ("pending_human_decisions", "不授权项", "follow-up tracking", "启动后续 CR", "CR 冲突预检"),
        ),
        "user-manual": (
            DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
            ("pending_human_decisions", "不授权项", "follow-up tracking", "启动后续 CR", "CR 冲突预检"),
        ),
    }
    for label, (target, tokens) in token_targets.items():
        if not target.is_file():
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
        for token in ("STATE.active_change", "follow-up", "CR-INDEX.yaml", "--project-root"):
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
            ("cr_tracking", "CR-INDEX.yaml", "meta-flow check cr-tracking", "active formal CR", "stale_status_conflicts"),
        ),
        "state-template": (
            DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md",
            ("cr_tracking", "follow_up_candidates", "spike_candidates", "stale_status_conflicts", "CR-INDEX.yaml"),
        ),
        "change-impact-analysis": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "SKILL.md",
            ("CR-INDEX-TEMPLATE.yaml", "meta-flow check cr-tracking", "STATE.md.cr_tracking", "stale_status_conflicts"),
        ),
        "cr-template": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "templates" / "CR-TEMPLATE.md",
            ("cr_index_path", "STATE.md.cr_tracking", "CR-INDEX.yaml", "meta-flow check cr-tracking"),
        ),
        "follow-up-template": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "templates" / "FOLLOW-UP-TRACKING-TEMPLATE.md",
            ("cr_index_path", "STATE.md.cr_tracking", "CR-INDEX.yaml", "状态索引同步", "meta-flow check cr-tracking"),
        ),
        "cr-index-template": (
            DELIVERY_ROOT / "skills" / "change-impact-analysis" / "templates" / "CR-INDEX-TEMPLATE.yaml",
            ("active_crs", "follow_up_candidates", "spike_candidates", "stale_status_conflicts", "conflict_keys"),
        ),
        "skills-readme": (
            DELIVERY_ROOT / "skills" / "README.md",
            ("cr_tracking", "CR-INDEX.yaml", "CR 跟踪一致性检查"),
        ),
        "delivery-agents-rule": (
            DELIVERY_ROOT / "rules" / "AGENTS.md",
            ("CR 跟踪状态查询", "cr_tracking", "CR-INDEX.yaml", "stale_status_conflicts"),
        ),
        "delivery-claude-rule": (
            DELIVERY_ROOT / "rules" / "CLAUDE.md",
            ("CR 跟踪状态查询", "cr_tracking", "CR-INDEX.yaml", "stale_status_conflicts"),
        ),
        "root-agents-rule": (
            ROOT / "AGENTS.md",
            ("CR 跟踪状态查询", "cr_tracking", "CR-INDEX.yaml", "stale_status_conflicts"),
        ),
        "readme": (
            ROOT / "README.md",
            ("CR-INDEX.yaml", "meta-flow check cr-tracking", "active formal CR", "stale_status_conflicts"),
        ),
        "delivery-readme": (
            DELIVERY_ROOT / "README.md",
            ("CR-INDEX.yaml", "meta-flow check cr-tracking", "active formal CR", "stale_status_conflicts"),
        ),
        "user-manual": (
            DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
            ("CR-INDEX.yaml", "meta-flow check cr-tracking", "active formal CR", "stale_status_conflicts"),
        ),
    }
    for label, (target, tokens) in token_targets.items():
        if not target.is_file():
            errors.append(f"missing CR tracking protocol target {label}: {target.relative_to(ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        missing = [token for token in tokens if token not in text]
        if missing:
            errors.append(f"{target.relative_to(ROOT)} missing CR tracking protocol tokens: {', '.join(missing)}")
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
            "risks_and_decisions:",
            "read_expansion_log:",
        ):
            if token not in text:
                errors.append(f"{capsule_template.relative_to(ROOT)} missing context capsule token: {token}")

    state_template = DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md"
    if state_template.is_file():
        text = state_template.read_text(encoding="utf-8")
        required_tokens = (
            "context_budget:",
            "require_capsule_first",
            "process/context/CP2-REQUIREMENT-CONTEXT.yaml",
            "process/context/CP8-DELIVERY-CONTEXT.yaml",
            "workflow_health:",
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
        "delivery/skills/README.md": ("process/context/*-CONTEXT.yaml", "context_budget", "workflow_health"),
        "delivery/rules/AGENTS.md": ("全阶段 Context Capsule", "上下文预算", "Workflow Health", "Decision Brief 压缩"),
        "delivery/rules/CLAUDE.md": ("全阶段 Context Capsule", "上下文预算", "workflow_health", "Decision Brief 压缩"),
        "AGENTS.md": ("全阶段 Context Capsule", "上下文预算", "Workflow Health", "Decision Brief 压缩"),
        "README.md": ("process/context/", "decision_brief_profile", "Context Capsule"),
        "delivery/README.md": ("process/context/", "decision_brief_profile", "Context Capsule"),
        "delivery/doc/USER-MANUAL.md": ("process/context/*-CONTEXT.yaml", "decision_brief_profile", "Context Capsule"),
    }
    for rel_path, tokens in targets.items():
        path = ROOT / rel_path
        if not path.is_file():
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
            errors.append(f"missing agent/skill contract target: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append(f"{rel_path} missing agent/skill contract tokens: {', '.join(missing)}")

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


def collect_errors() -> list[str]:
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
    errors.extend(collect_revision_record_errors())
    errors.extend(collect_software_workflow_artifact_errors())
    errors.extend(collect_context_capsule_protocol_errors())
    errors.extend(collect_agent_skill_contract_errors())
    errors.extend(collect_context_budgeted_e2e_errors())
    errors.extend(collect_governance_lifecycle_errors())
    errors.extend(collect_context_sufficiency_errors())
    errors.extend(collect_failure_waiver_errors())
    errors.extend(collect_delivery_asset_lifecycle_errors())

    for child in sorted(path for path in DELIVERY_ROOT.iterdir() if path.is_dir()):
        if child.name not in ALLOWED_DELIVERY_DIRS:
            errors.append(f"delivery top-level directory not allowed: {child.relative_to(ROOT)}")

    for path in ROOT.rglob("__pycache__"):
        if is_under_excluded_cache_dir(path):
            continue
        if path.is_dir():
            errors.append(f"python cache directory must not exist: {path.relative_to(ROOT)}")
    for path in ROOT.rglob("*.pyc"):
        if is_under_excluded_cache_dir(path):
            continue
        if path.is_file():
            errors.append(f"python bytecode file must not exist: {path.relative_to(ROOT)}")

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

    return errors


def main() -> int:
    errors = collect_errors()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
