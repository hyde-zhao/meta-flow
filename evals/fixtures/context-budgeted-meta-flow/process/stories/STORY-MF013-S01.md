---
story_id: STORY-MF013-S01
cr_id: CR-001
title: Validate context-budgeted e2e chain
feature_refs:
  - meta.context_budgeted_flow
feature_design_refs:
  - docs/features/context-budgeted-flow/DESIGN.md
feature_contract_summary: Context-budgeted chain must keep default reads limited to generated context, summaries, packets, returns, evidence indexes, and CP results.
cr_delta_summary: Add end-to-end regression coverage for context-budgeted runtime and Story governance artifacts.
dependency_inputs:
  - STATE.current.json fixture is present
  - CR-001 summary fixture is present
lld_policy: technical-note
risk_profile: process-lite
allowed_write_paths:
  - meta_flow/context_pack/**
  - tests/fixtures/context_budgeted/**
forbidden_write_paths:
  - process/STATE.md
  - process/DEVELOPMENT-PLAN.yaml
acceptance:
  - context pack excludes deny-default files
  - story return touched files stay inside allowed paths
  - cp result can append checkpoint ledger
verification_plan:
  - pytest tests/test_context_budgeted_flow_e2e.py
authz_policy_refs:
  - NO_CREDENTIAL_READ
---

# Story MF013 S01

Validate the context-budgeted governance chain using a small fixture.
