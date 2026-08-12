"""Project governance public API with lazy imports to keep routing dependencies acyclic."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "Project": ("meta_flow.project.model", "Project"),
    "build_minimal_project": ("meta_flow.project.model", "build_minimal_project"),
    "load_project": ("meta_flow.project.model", "load_project"),
    "validate_project_payload": ("meta_flow.project.model", "validate_project_payload"),
    "apply_project_init": ("meta_flow.project.onboarding", "apply_project_init"),
    "check_independent_process_route": (
        "meta_flow.project.onboarding",
        "check_independent_process_route",
    ),
    "plan_project_init": ("meta_flow.project.onboarding", "plan_project_init"),
    "resolve_process_repo_root": (
        "meta_flow.project.onboarding",
        "resolve_process_repo_root",
    ),
    "IndependentProcessRoute": (
        "meta_flow.project.process_route",
        "IndependentProcessRoute",
    ),
    "ProcessRouteError": ("meta_flow.project.process_route", "ProcessRouteError"),
    "require_process_route": (
        "meta_flow.project.process_route",
        "require_process_route",
    ),
    "resolve_process_ref": (
        "meta_flow.project.process_route",
        "resolve_process_ref",
    ),
    "apply_project_scaffold": (
        "meta_flow.project.scaffold",
        "apply_project_scaffold",
    ),
    "build_project_scaffold_plan": (
        "meta_flow.project.scaffold",
        "build_project_scaffold_plan",
    ),
    "load_project_snapshot": (
        "meta_flow.project.state",
        "load_project_snapshot",
    ),
    "validate_project_current": (
        "meta_flow.project.state",
        "validate_project_current",
    ),
    "validate_project_objects": (
        "meta_flow.project.state",
        "validate_project_objects",
    ),
    "GovernanceBaselineRefreshPlan": (
        "meta_flow.project.governance_projection",
        "GovernanceBaselineRefreshPlan",
    ),
    "ImmutableCommitRole": (
        "meta_flow.project.governance_projection",
        "ImmutableCommitRole",
    ),
    "apply_governance_baseline_refresh": (
        "meta_flow.project.governance_projection",
        "apply_governance_baseline_refresh",
    ),
    "plan_governance_baseline_refresh": (
        "meta_flow.project.governance_projection",
        "plan_governance_baseline_refresh",
    ),
    "PhaseTransitionPlan": (
        "meta_flow.project.phase_transition",
        "PhaseTransitionPlan",
    ),
    "apply_phase_transition": (
        "meta_flow.project.phase_transition",
        "apply_phase_transition",
    ),
    "inspect_phase_transition": (
        "meta_flow.project.phase_transition",
        "inspect_phase_transition",
    ),
    "plan_phase_transition": (
        "meta_flow.project.phase_transition",
        "plan_phase_transition",
    ),
    "recover_phase_transition": (
        "meta_flow.project.phase_transition",
        "recover_phase_transition",
    ),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
