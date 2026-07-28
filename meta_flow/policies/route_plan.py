"""CR-aware route-plan derivation for Meta Flow."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.checks import state_transition
from meta_flow.checks.frozen_cp6_evidence import FrozenCp6EvidenceV1
from meta_flow.policies import gate_profiles
from meta_flow.project.onboarding_contract import canonical_digest
from meta_flow.project.process_route import ProcessRouteError, _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.state.event_ledger import (
    load_events,
    validate_event_before_append,
    validate_event_ledger,
)
from meta_flow.work.model import load_work

CHECKPOINTS = tuple(f"CP{index}" for index in range(9))
HUMAN_GATE_CHECKPOINTS = {"CP2", "CP3", "CP5", "CP8"}
CP_TO_PHASE = {
    "CP0": "init",
    "CP1": "requirement-clarification",
    "CP2": "requirement-clarification",
    "CP3": "solution-design",
    "CP4": "story-planning",
    "CP5": "story-planning",
    "CP6": "story-execution",
    "CP7": "story-execution",
    "CP8": "documentation",
}
CHECKPOINT_RE = re.compile(r"^(CP[0-8])(?:-(lite|standard))?$")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
PRODUCT_BASELINE_TERMS = ("use-cases", "requirements", "scope", "product", "product-baseline")
CR_TRAIT_PREFIX = "cr_trait_"
CR_TRAIT_BOOL_FIELDS = {
    "uses_existing_evidence_only",
    "has_new_design",
    "has_new_implementation",
    "requires_architecture_review",
    "requires_story_decomposition",
    "requires_subagent_dispatch",
}
CR_TRAIT_TRI_STATE_BOOL_FIELDS = {"has_new_verification"}
CR_TRAIT_LIST_FIELDS = {"existing_evidence_refs"}
PROFILE_UPGRADE_TARGETS = {
    "architecture_review": "architecture-major",
    "story_decomposition": "standard-code",
    "implementation": "standard-code",
    "design": "standard-code",
}
C0_CONSUMERS = (
    ("C0-CONSUMER-01", "cp result-check"),
    ("C0-CONSUMER-02", "event dispatch-check"),
    ("C0-CONSUMER-03", "check handoff-dispatch"),
    ("C0-CONSUMER-04", "story return-check"),
    ("C0-CONSUMER-05", "story evidence-check"),
    ("C0-CONSUMER-06", "context check-story-packet"),
    ("C0-CONSUMER-07", "context sufficiency-check"),
    ("C0-CONSUMER-08", "context read-log-check"),
    ("C0-CONSUMER-09", "story lld-check"),
    ("C0-CONSUMER-10", "feature check"),
    ("C0-CONSUMER-11", "feature trace"),
)
C0_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "authorization_source",
        "authorization_kind",
        "operation",
        "decision_ref",
        "cr_id",
        "work_id",
        "expected_release_oid",
        "expected_process_oid",
        "scope_digest",
        "plan_digest",
        "mutation_allowlist",
        "expires_at",
        "single_use",
    }
)
C0_AUTHORIZATION_SOURCE = "typed-user-confirmation"
C0_AUTHORIZATION_KIND = "c0-projector-cutover"
C0_APPLY_OPERATION = "route-c0-apply"
C0_AUTHORIZATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
C0_OID_RE = re.compile(r"^[0-9a-f]{40}$")
C0_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class C0AuthorizationV1:
    """一次性 C0 projector cutover 授权。"""

    schema_version: int
    authorization_id: str
    authorization_source: str
    authorization_kind: str
    operation: str
    decision_ref: str
    cr_id: str
    work_id: str
    expected_release_oid: str
    expected_process_oid: str
    scope_digest: str
    plan_digest: str
    mutation_allowlist: tuple[str, ...]
    expires_at: str
    single_use: bool

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> C0AuthorizationV1:
        if set(payload) != C0_AUTHORIZATION_FIELDS:
            missing = sorted(C0_AUTHORIZATION_FIELDS - set(payload))
            extra = sorted(set(payload) - C0_AUTHORIZATION_FIELDS)
            raise ValueError(f"C0 authorization fields mismatch: missing={missing}, extra={extra}")
        values = dict(payload)
        allowlist = values.get("mutation_allowlist")
        if not isinstance(allowlist, list):
            raise ValueError("C0 authorization mutation_allowlist must be a list")
        values["mutation_allowlist"] = tuple(str(item) for item in allowlist)
        return cls(**values)


@dataclass(frozen=True)
class C0MutationTarget:
    order: int
    logical_ref: str
    path: Path
    before: str | None
    after: str

    @property
    def before_digest(self) -> str:
        return canonical_digest(self.before if self.before is not None else "")

    @property
    def after_digest(self) -> str:
        return canonical_digest(self.after)

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "logical_ref": self.logical_ref,
            "before_exists": self.before is not None,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
        }


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "y"}:
            return True
        if lowered in {"false", "no", "0", "n", "", "none", "null"}:
            return False
    return bool(value)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        stripped = value.strip().strip('"').strip("'")
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                inner = stripped[1:-1]
                return [piece.strip().strip('"').strip("'") for piece in inner.split(",") if piece.strip()]
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item)]
        return [piece for piece in stripped.replace(",", " ").split() if piece]
    return [str(value)]


def _strip_scalar(value: Any) -> str:
    return str(value or "").strip().strip('"').strip("'")


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def parse_cr_frontmatter(path: Path) -> dict[str, str]:
    return parse_frontmatter(path.read_text(encoding="utf-8"))


def _normalize_mapping_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = _strip_scalar(value)
        if stripped in {"", "-", "—", "n/a", "N/A", "null", "None"}:
            return ""
        return stripped
    return value


def cr_trait_from_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Build derive_route_plan() cr_trait input from CR frontmatter/summary fields."""

    nested = mapping.get("cr_trait")
    if isinstance(nested, dict):
        return {str(key): value for key, value in nested.items() if _normalize_mapping_value(value) != ""}
    trait: dict[str, Any] = {}
    for key, value in mapping.items():
        if not str(key).startswith(CR_TRAIT_PREFIX):
            continue
        trait_key = str(key)[len(CR_TRAIT_PREFIX) :]
        normalized = _normalize_mapping_value(value)
        if trait_key in CR_TRAIT_BOOL_FIELDS:
            trait[trait_key] = _as_bool(normalized)
        elif trait_key in CR_TRAIT_TRI_STATE_BOOL_FIELDS:
            if normalized != "":
                trait[trait_key] = _as_bool(normalized)
        elif trait_key in CR_TRAIT_LIST_FIELDS:
            values = _as_list(normalized)
            if values:
                trait[trait_key] = values
        elif normalized != "":
            trait[trait_key] = normalized
    return trait


def _normalize_stage_token(token: str) -> tuple[str, str]:
    match = CHECKPOINT_RE.fullmatch(token)
    if not match:
        raise ValueError(f"invalid gate profile stage: {token}")
    checkpoint = match.group(1)
    mode = match.group(2) or "standard"
    return checkpoint, mode


def normalize_profile_stage(stage: str | dict[str, Any], human_gates: set[str]) -> dict[str, Any]:
    if isinstance(stage, dict):
        checkpoint = str(stage.get("checkpoint") or "")
        if checkpoint not in CHECKPOINTS:
            raise ValueError(f"invalid gate profile checkpoint: {checkpoint or '-'}")
        mode = str(stage.get("mode") or "standard")
        if mode not in {"standard", "lite"}:
            raise ValueError(f"invalid gate profile mode for {checkpoint}: {mode}")
        human_gate = str(stage.get("human_gate") or "")
        if not human_gate:
            human_gate = _default_human_gate(checkpoint, mode, checkpoint in human_gates)
        return {"checkpoint": checkpoint, "mode": mode, "human_gate": human_gate}
    checkpoint, mode = _normalize_stage_token(str(stage))
    token = f"{checkpoint}-lite" if mode == "lite" else checkpoint
    required = token in human_gates or checkpoint in human_gates
    return {"checkpoint": checkpoint, "mode": mode, "human_gate": _default_human_gate(checkpoint, mode, required)}


def _default_human_gate(checkpoint: str, mode: str, required: bool) -> str:
    if checkpoint not in HUMAN_GATE_CHECKPOINTS:
        return "none"
    if required:
        return "required"
    if mode == "lite" and checkpoint in {"CP2", "CP3", "CP5"}:
        return "optional"
    return "none"


def normalize_profile(profile: dict[str, Any]) -> list[dict[str, Any]]:
    human_gates = {str(item) for item in profile.get("human_gates") or []}
    return [normalize_profile_stage(stage, human_gates) for stage in profile.get("stages") or []]


def phase_sequence_from_stages(stages: list[dict[str, Any] | str]) -> list[str]:
    """Derive the state-router phase sequence from route_plan.stages[]."""

    phases: list[str] = []
    for stage in stages:
        checkpoint = str(stage.get("checkpoint") or "") if isinstance(stage, dict) else str(stage)
        phase = CP_TO_PHASE.get(checkpoint)
        if phase and phase not in phases:
            phases.append(phase)
    return phases


def optional_gate_auto_clean_decision(
    *,
    checkpoint: str,
    human_gate: str,
    precheck_decision: str,
    decision_count: int,
    context_check_errors: list[str] | None = None,
    human_gate_errors: list[str] | None = None,
    blocking_items: list[str] | None = None,
    scope_authz_open: bool = False,
    user_requested_review: bool = False,
) -> dict[str, Any]:
    """Decide whether an optional human gate can advance without user approval."""

    blockers: list[str] = []
    if human_gate != "optional":
        blockers.append(f"{checkpoint} human_gate is {human_gate}, not optional")
    if precheck_decision not in {"PASS", "WAIVED"}:
        blockers.append(f"{checkpoint} precheck_decision is {precheck_decision}, expected PASS or WAIVED")
    if decision_count != 0:
        blockers.append("decision_items_present")
        blockers.append(f"{checkpoint} has {decision_count} pending decision item(s)")
    if context_check_errors:
        blockers.append("context check has errors")
    if human_gate_errors:
        blockers.append("human-gate check has errors")
    if blocking_items:
        blockers.append("blocking/high-risk items are still open")
    if scope_authz_open:
        blockers.append("scope/authz/product-baseline gray area is open")
    if user_requested_review:
        blockers.append("user requested explicit review")
    if blockers:
        return {
            "auto_clean": False,
            "approval_source": "required",
            "upgrade_to": "required",
            "blockers": blockers,
        }
    return {
        "auto_clean": True,
        "approval_source": "auto-clean-gate",
        "upgrade_to": "",
        "blockers": [],
    }


def _profile_stage_map(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {stage["checkpoint"]: stage for stage in normalize_profile(profile)}


def _stage(checkpoint: str, profile_stages: dict[str, dict[str, Any]], *, mode: str | None = None, human_gate: str | None = None) -> dict[str, Any]:
    outside_profile = checkpoint not in profile_stages
    base = dict(profile_stages.get(checkpoint) or {"checkpoint": checkpoint, "mode": "standard", "human_gate": "none"})
    if outside_profile and checkpoint in HUMAN_GATE_CHECKPOINTS:
        base["human_gate"] = "required"
    base["_outside_profile"] = outside_profile
    if mode:
        base["mode"] = mode
    if human_gate:
        base["human_gate"] = human_gate
    return base


def _n_a(reason: str) -> dict[str, Any]:
    return {"applies": False, "decision": "N/A", "reason": reason}


def _applies(stage: dict[str, Any], reason: str = "") -> dict[str, Any]:
    payload = {"applies": True, "mode": stage["mode"], "human_gate": stage.get("human_gate", "none")}
    if reason:
        payload["reason"] = reason
    return payload


def _waived(reason: str, waiver_ref: str = "") -> dict[str, Any]:
    payload = {"applies": True, "decision": "WAIVED", "reason": reason}
    if waiver_ref:
        payload["waiver_ref"] = waiver_ref
    return payload


def _has_product_baseline_impact(cr_type: str, impact_surface: list[str], product_baseline_refresh_required: bool) -> bool:
    if product_baseline_refresh_required or cr_type == "product-scope":
        return True
    joined = " ".join(impact_surface).lower()
    return any(term in joined for term in PRODUCT_BASELINE_TERMS)


def _cp2_human_gate(cr_type: str, impact_surface: list[str], product_baseline_refresh_required: bool, authz_policy_refs: list[str], trait: dict[str, Any]) -> str:
    if cr_type in {"product-scope", "architecture", "runtime"}:
        return "required"
    if _has_product_baseline_impact(cr_type, impact_surface, product_baseline_refresh_required):
        return "required"
    if authz_policy_refs:
        return "required"
    if _as_bool(trait.get("uses_existing_evidence_only")) and not _as_list(trait.get("existing_evidence_refs")):
        return "required"
    return "optional"


def derive_route_plan(
    *,
    cr_type: str,
    cr_trait: dict[str, Any] | None,
    gate_profile: str,
    product_baseline_refresh_required: bool = False,
    impact_surface: list[str] | None = None,
    authz_policy_refs: list[str] | None = None,
    profiles_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive the actual CP route for a CR from profile defaults and CR facts."""

    profiles = (profiles_data or gate_profiles.default_gate_profiles()).get("profiles") or {}
    if gate_profile not in profiles:
        raise ValueError(f"unknown gate_profile: {gate_profile}")
    trait = dict(cr_trait or {})
    impact = _as_list(impact_surface)
    authz_refs = _as_list(authz_policy_refs)
    profile_stages = _profile_stage_map(profiles[gate_profile])
    applicability: dict[str, dict[str, Any]] = {checkpoint: _n_a("not included in gate profile") for checkpoint in CHECKPOINTS}
    for checkpoint in profile_stages:
        applicability[checkpoint] = _n_a("not selected by route traits")
    stages: list[dict[str, Any]] = []
    warnings: list[str] = []
    blockers: list[str] = []
    profile_upgrade_required: list[dict[str, str]] = []

    def require_profile_upgrade(checkpoint: str, reason: str, recommended_profile: str) -> None:
        finding = {
            "checkpoint": checkpoint,
            "reason": reason,
            "current_gate_profile": gate_profile,
            "recommended_gate_profile": recommended_profile,
        }
        if finding not in profile_upgrade_required:
            profile_upgrade_required.append(finding)
            blockers.append(
                "profile_upgrade_required: "
                f"{checkpoint} requires {recommended_profile} because {reason}"
            )

    def apply_stage(stage: dict[str, Any], reason: str = "", *, upgrade_reason: str = "", recommended_profile: str = "") -> None:
        checkpoint = stage["checkpoint"]
        applicability[checkpoint] = _applies(stage, reason)
        if stage.get("_outside_profile") and checkpoint in HUMAN_GATE_CHECKPOINTS:
            require_profile_upgrade(
                checkpoint,
                upgrade_reason or f"{checkpoint} was added outside gate_profile",
                recommended_profile or "standard-code",
            )

    for checkpoint in ("CP0", "CP2", "CP8"):
        if checkpoint in profile_stages:
            apply_stage(profile_stages[checkpoint], "included in gate profile")

    cp1_required = gate_profile in {"architecture-major", "runtime-high-risk"} or _has_product_baseline_impact(
        cr_type, impact, product_baseline_refresh_required
    )
    if cp1_required:
        apply_stage(_stage("CP1", profile_stages), "required by gate profile or product baseline refresh")
        if "CP1" not in profile_stages:
            warnings.append("CP1 added because product baseline refresh or product-scope requires it")
    else:
        applicability["CP1"] = _n_a("no product baseline refresh or high-risk profile")

    if "CP2" in applicability and applicability["CP2"].get("applies"):
        applicability["CP2"]["human_gate"] = _cp2_human_gate(
            cr_type, impact, product_baseline_refresh_required, authz_refs, trait
        )

    uses_existing = _as_bool(trait.get("uses_existing_evidence_only"))
    has_new_design = _as_bool(trait.get("has_new_design"))
    has_new_impl = _as_bool(trait.get("has_new_implementation"))
    has_new_verification_raw = trait.get("has_new_verification")
    has_new_verification = None if has_new_verification_raw is None else _as_bool(has_new_verification_raw)
    requires_arch = _as_bool(trait.get("requires_architecture_review"))
    requires_story_decomp = _as_bool(trait.get("requires_story_decomposition"))
    waiver_reason = str(trait.get("verification_waiver_reason") or "").strip()
    waiver_ref = str(trait.get("verification_waiver_ref") or "").strip()

    if uses_existing and any((has_new_design, has_new_impl, has_new_verification is True)):
        blockers.append("uses_existing_evidence_only conflicts with new design/implementation/verification traits")

    if uses_existing:
        for checkpoint in ("CP3", "CP4", "CP5", "CP6", "CP7"):
            applicability[checkpoint] = _n_a("uses existing evidence only")
    else:
        if has_new_design or requires_arch:
            apply_stage(
                _stage("CP3", profile_stages, mode="standard" if requires_arch else None, human_gate="required" if requires_arch else None),
                "new design or architecture review required",
                upgrade_reason="architecture review required" if requires_arch else "new design requires design review",
                recommended_profile=PROFILE_UPGRADE_TARGETS["architecture_review"] if requires_arch else PROFILE_UPGRADE_TARGETS["design"],
            )
        if requires_story_decomp:
            if not applicability["CP3"].get("applies"):
                apply_stage(
                    _stage("CP3", profile_stages, mode="lite"),
                    "story decomposition requires at least CP3-lite",
                    upgrade_reason="story decomposition requires design baseline review",
                    recommended_profile=PROFILE_UPGRADE_TARGETS["story_decomposition"],
                )
            cp4_stage = _stage("CP4", profile_stages)
            apply_stage(cp4_stage, "story decomposition required")
            if cp4_stage.get("_outside_profile"):
                warnings.append("CP4 added outside gate_profile because story decomposition was requested")
            apply_stage(
                _stage("CP5", profile_stages),
                "story design evidence required",
                upgrade_reason="story decomposition requires CP5 story design confirmation",
                recommended_profile=PROFILE_UPGRADE_TARGETS["story_decomposition"],
            )
        if has_new_impl:
            if "CP5" in profile_stages:
                apply_stage(profile_stages["CP5"], "implementation design evidence required by gate profile")
            cp6_stage = _stage("CP6", profile_stages)
            apply_stage(cp6_stage, "new implementation required")
            if cp6_stage.get("_outside_profile"):
                require_profile_upgrade(
                    "CP6",
                    "new implementation requires implementation checkpoint in gate profile",
                    PROFILE_UPGRADE_TARGETS["implementation"],
                )
            if has_new_verification is False:
                if waiver_reason and waiver_ref:
                    applicability["CP7"] = _waived("new implementation verification explicitly waived", waiver_ref)
                else:
                    blockers.append(
                        "has_new_implementation=true requires CP7 unless both "
                        "verification_waiver_reason and verification_waiver_ref are set"
                    )
            else:
                if has_new_verification is None:
                    warnings.append("has_new_verification auto-derived from has_new_implementation")
                cp7_stage = _stage("CP7", profile_stages)
                apply_stage(cp7_stage, "verification derived from implementation")
                if cp7_stage.get("_outside_profile"):
                    require_profile_upgrade(
                        "CP7",
                        "new implementation requires verification checkpoint in gate profile",
                        PROFILE_UPGRADE_TARGETS["implementation"],
                    )
        elif has_new_verification:
            cp7_stage = _stage("CP7", profile_stages)
            apply_stage(cp7_stage, "new verification required")
            if cp7_stage.get("_outside_profile"):
                require_profile_upgrade(
                    "CP7",
                    "new verification requires verification checkpoint in gate profile",
                    PROFILE_UPGRADE_TARGETS["implementation"],
                )

    for checkpoint in CHECKPOINTS:
        item = applicability[checkpoint]
        if item.get("applies") and item.get("decision") != "WAIVED":
            stages.append({"checkpoint": checkpoint, "mode": item.get("mode", "standard"), "human_gate": item.get("human_gate", "none")})

    return {
        "schema_version": 1,
        "cr_type": cr_type,
        "gate_profile": gate_profile,
        "cr_trait": trait,
        "stages": stages,
        "phase_sequence": phase_sequence_from_stages(stages),
        "checkpoint_applicability": applicability,
        "warnings": warnings,
        "blockers": blockers,
        "profile_upgrade_required": profile_upgrade_required,
        "decision": "BLOCKED" if blockers else "PASS",
    }


def derive_route_plan_from_mapping(
    mapping: dict[str, Any],
    *,
    profiles_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive a route plan from CR frontmatter/summary-style fields."""

    cr_type = _strip_scalar(mapping.get("cr_type") or mapping.get("cr_kind") or "feature")
    gate_profile = _strip_scalar(mapping.get("gate_profile") or "standard-code")
    return derive_route_plan(
        cr_type=cr_type,
        cr_trait=cr_trait_from_mapping(mapping),
        gate_profile=gate_profile,
        product_baseline_refresh_required=_as_bool(mapping.get("product_baseline_refresh_required")),
        impact_surface=_as_list(mapping.get("impact_surface")),
        authz_policy_refs=_as_list(mapping.get("authz_policy_refs")),
        profiles_data=profiles_data,
    )


def write_route_plan(path: Path, plan: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _without_artifact_fields(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        key: plan.get(key)
        for key in (
            "schema_version",
            "cr_type",
            "gate_profile",
            "cr_trait",
            "stages",
            "phase_sequence",
            "checkpoint_applicability",
            "warnings",
            "blockers",
            "profile_upgrade_required",
            "decision",
        )
    }


def _route_plan_ref(mapping: dict[str, Any]) -> str:
    return _strip_scalar(mapping.get("route_plan_ref") or "").split("#", 1)[0]


def validate_route_plan_for_cr(
    project_root: Path,
    cr_path: Path,
    *,
    profiles_data: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Validate that a CR's route_plan_ref is present and matches frontmatter facts."""

    project_root = project_root.resolve()
    mapping = parse_cr_frontmatter(cr_path)
    cr_id = _strip_scalar(mapping.get("cr_id") or cr_path.stem)
    errors: list[str] = []
    warnings: list[str] = []
    ref = _route_plan_ref(mapping)
    if not ref:
        return [f"{cr_id} missing route_plan_ref"], warnings
    try:
        # ``process/...`` 是逻辑引用；绑定项目必须经统一 resolver 到过程仓，
        # 不能把它误当作发布仓内的物理相对路径。
        route_path = _resolve_runtime_ref(project_root, ref)
    except ProcessRouteError as exc:
        return [f"{cr_id} route_plan_ref resolution blocked ({exc.error_code}): {ref}"], warnings
    if not route_path.is_file():
        return [f"{cr_id} route_plan_ref missing on disk: {ref}"], warnings
    try:
        actual = json.loads(route_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{cr_id} route_plan_ref invalid JSON: {exc}"], warnings
    if not isinstance(actual, dict):
        return [f"{cr_id} route_plan_ref must contain a JSON object: {ref}"], warnings
    try:
        expected = derive_route_plan_from_mapping(
            mapping,
            profiles_data=profiles_data or gate_profiles.load_gate_profiles(project_root),
        )
    except ValueError as exc:
        return [f"{cr_id} route plan derivation failed: {exc}"], warnings
    if _without_artifact_fields(actual) != _without_artifact_fields(expected):
        errors.append(f"{cr_id} route_plan_ref is stale or inconsistent with CR frontmatter: {ref}")
    if actual.get("decision") == "BLOCKED":
        errors.append(f"{cr_id} route_plan_ref decision is BLOCKED: {ref}")
    if actual.get("warnings"):
        warnings.append(f"{cr_id} route_plan_ref has warnings: {', '.join(str(item) for item in actual.get('warnings') or [])}")
    return errors, warnings


def _load_trait(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    path = Path(raw)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("--cr-trait must be a JSON object or a path to one")
    return data


def _read_runtime_json(project_root: Path, logical_ref: str) -> dict[str, Any]:
    if not logical_ref.startswith("process/"):
        raise ValueError(f"C0 input must be a process logical ref: {logical_ref}")
    path = _resolve_runtime_ref(project_root, logical_ref)
    if not path.is_file():
        raise ValueError(f"C0 input is missing: {logical_ref}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"C0 input is invalid JSON: {logical_ref}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"C0 input must contain a JSON object: {logical_ref}")
    return payload


def _git_head_oid(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    oid = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", oid):
        raise ValueError(f"unable to read exact git HEAD for {repo_root.name}")
    return oid


def _run_c0_command(project_root: Path, args: list[str]) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(project_root)
    result = subprocess.run(
        [sys.executable, "-m", "meta_flow.cli", *args],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _c0_consumer_commands(
    *,
    story_inputs: list[dict[str, str]],
    s03_lld_ref: str,
) -> dict[str, list[list[str]]]:
    project = ["--project-root", "."]
    return {
        "cp result-check": [
            [
                "cp",
                "result-check",
                "--result",
                item["result_ref"],
                *project,
                "--check-consistency",
                "--correlation-profile",
                "audit",
            ]
            for item in story_inputs
        ],
        "event dispatch-check": [["event", "dispatch-check", *project]],
        "check handoff-dispatch": [["check", "handoff-dispatch", *project]],
        "story return-check": [
            [
                "story",
                "return-check",
                "--packet",
                item["context_ref"],
                "--return",
                item["return_ref"],
                *project,
            ]
            for item in story_inputs
        ],
        "story evidence-check": [
            ["story", "evidence-check", "--index", item["evidence_ref"], *project]
            for item in story_inputs
        ],
        "context check-story-packet": [
            ["context", "check-story-packet", "--packet", item["context_ref"], *project]
            for item in story_inputs
        ],
        "context sufficiency-check": [
            ["context", "sufficiency-check", "--packet", item["context_ref"], *project]
            for item in story_inputs
        ],
        "context read-log-check": [["context", "read-log-check", *project]],
        "story lld-check": [["story", "lld-check", "--lld", s03_lld_ref, *project]],
        "feature check": [["feature", "check", *project]],
        "feature trace": [["feature", "trace", *project]],
    }


def _release_root_has_process_entry(project_root: Path) -> bool:
    """检查发布根是否存在名为 process 的任意目录项。"""

    with os.scandir(project_root) as entries:
        return any(entry.name == "process" for entry in entries)


def _c0_return_ref(result: dict[str, Any], *, story_id: str) -> str:
    return_ref = str(
        result.get("return_ref")
        or f"process/returns/{story_id}.CP6.return.json"
    )
    if not return_ref.startswith("process/returns/") or not return_ref.endswith(".json"):
        raise ValueError("C0 return_ref must be one canonical process/returns/*.json ref")
    return return_ref


def build_c0_dry_run(
    *,
    project_root: Path,
    cr_id: str,
    work_id: str,
    story_result_refs: list[str],
) -> state_transition.C0ResultV1:
    """重放 bootstrap wave，并用一个 C0 projector 归一化 11 个公共 consumer。"""

    project_root = project_root.resolve()
    if len(story_result_refs) != 3 or len(set(story_result_refs)) != 3:
        raise ValueError("c0-dry-run requires exactly three distinct --story-result refs")
    process_project = _resolve_runtime_ref(project_root, "process/PROJECT.yaml")
    if not process_project.is_file():
        raise ValueError("bound process/PROJECT.yaml is missing")
    process_root = process_project.parent
    release_oid = _git_head_oid(project_root)
    process_oid = _git_head_oid(process_root)
    work = load_work(process_root, work_id)

    story_inputs: list[dict[str, str]] = []
    frozen_evidence: list[dict[str, Any]] = []
    input_evidence_refs: list[str] = []
    initial_blockers: list[str] = []
    for result_ref in story_result_refs:
        result = _read_runtime_json(project_root, result_ref)
        story_id = str(result.get("story_id") or "")
        if str(result.get("cr_id") or "") != cr_id:
            initial_blockers.append(f"C0_CR_ID_MISMATCH:{result_ref}")
        if str(result.get("checkpoint") or "") != "CP6" or str(result.get("decision") or "") != "PASS":
            initial_blockers.append(f"C0_CP6_RESULT_NOT_PASS:{result_ref}")
        if not story_id:
            raise ValueError(f"C0 result is missing story_id: {result_ref}")
        context_ref = str(result.get("context_ref") or "")
        evidence_ref = str(result.get("evidence_ref") or "")
        return_ref = _c0_return_ref(result, story_id=story_id)
        return_payload = _read_runtime_json(project_root, return_ref)
        evidence_payload = _read_runtime_json(project_root, evidence_ref)
        dependency_digests = {
            "cp6_result": canonical_digest(result),
            "return_packet": canonical_digest(return_payload),
            "evidence_index": canonical_digest(evidence_payload),
        }
        frozen = FrozenCp6EvidenceV1(
            story_id=story_id,
            release_oid=release_oid,
            process_oid=process_oid,
            scope_digest=work.scope.digest,
            implementation_digest=canonical_digest(return_payload),
            dependency_digests=dependency_digests,
            cp6_result_ref=result_ref,
        )
        frozen_evidence.append(frozen.as_dict())
        input_evidence_refs.extend((result_ref, return_ref, evidence_ref))
        story_inputs.append(
            {
                "story_id": story_id,
                "result_ref": result_ref,
                "return_ref": return_ref,
                "evidence_ref": evidence_ref,
                "context_ref": context_ref,
                "summary_ref": str(result.get("summary_ref") or ""),
            }
        )
    story_inputs.sort(key=lambda item: item["story_id"])
    frozen_evidence.sort(key=lambda item: str(item["story_id"]))
    if [item["story_id"] for item in story_inputs] != [
        f"STORY-{cr_id.replace('-', '')}-S01",
        f"STORY-{cr_id.replace('-', '')}-S02",
        f"STORY-{cr_id.replace('-', '')}-S03",
    ]:
        initial_blockers.append("C0_BOOTSTRAP_STORY_SET_MISMATCH")
    if work.release_base_oid != release_oid:
        initial_blockers.append("C0_RELEASE_OID_DRIFT")
    if work.process_base_oid != process_oid:
        initial_blockers.append("C0_PROCESS_OID_DRIFT")
    if _release_root_has_process_entry(project_root):
        initial_blockers.append("C0_RELEASE_PROCESS_ENTRY_MUST_BE_ABSENT")

    s03 = next((item for item in story_inputs if item["story_id"].endswith("-S03")), None)
    if s03 is None:
        raise ValueError("c0-dry-run requires the S03 CP6 result")
    summary_name = Path(s03["summary_ref"]).name
    if not summary_name.startswith("CP6-") or not summary_name.endswith("-CODING-DONE.md"):
        raise ValueError("S03 summary_ref cannot derive the approved LLD ref")
    s03_lld_ref = f"process/stories/{summary_name[4:-len('-CODING-DONE.md')]}-LLD.md"

    commands = _c0_consumer_commands(story_inputs=story_inputs, s03_lld_ref=s03_lld_ref)
    consumer_inventory = [
        state_transition.project_c0_consumer(
            consumer_id=consumer_id,
            operation=operation,
            attempts=[_run_c0_command(project_root, command) for command in commands[operation]],
            absolute_process_path=str(process_root),
        )
        for consumer_id, operation in C0_CONSUMERS
    ]
    planned_transitions = [
        {
            "subject": item["story_id"],
            "from": "bootstrap-cp6-pass",
            "to": "ready-for-verification",
            "apply_required": True,
        }
        for item in story_inputs
    ]
    planned_transitions.append(
        {
            "subject": cr_id,
            "from": "CUTOVER-GATE-C0-blocked",
            "to": "post-C0-native-wave",
            "unblocks": [f"STORY-{cr_id.replace('-', '')}-S04", f"STORY-{cr_id.replace('-', '')}-S05"],
            "apply_required": True,
        }
    )
    mutation_allowlist = (
        "process/DEVELOPMENT-PLAN.yaml",
        f"process/checks/C0-{cr_id}-PROJECTOR-CUTOVER.result.json",
        f"process/checks/C0-{cr_id}-PROJECTOR-CUTOVER.summary.md",
        "process/state/CHECKPOINT-LEDGER.ndjson",
        "process/state/GATE-LEDGER.ndjson",
    )
    return state_transition.build_c0_result(
        cr_id=cr_id,
        release_oid=release_oid,
        process_oid=process_oid,
        scope_digest=work.scope.digest,
        input_evidence_refs=input_evidence_refs,
        frozen_evidence=frozen_evidence,
        consumer_inventory=consumer_inventory,
        planned_transitions=planned_transitions,
        mutation_allowlist=mutation_allowlist,
        initial_blockers=initial_blockers,
    )


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _portable_c0_error(
    exc: Exception,
    *,
    project_root: Path,
    process_root: Path | None = None,
) -> str:
    text = str(exc)
    replacements = [(str(project_root.resolve()), "<release-root>")]
    if process_root is not None:
        replacements.append((str(process_root.resolve()), "<process-root>"))
    for source, replacement in replacements:
        text = text.replace(source, replacement)
    return text


def validate_c0_authorization(
    plan: state_transition.C0ResultV1,
    authorization: C0AuthorizationV1,
    *,
    work_id: str,
) -> None:
    """校验一次性 C0 授权与当前 dry-run 的精确绑定。"""

    if plan.decision != "READY":
        raise ValueError("C0 authorization requires one READY dry-run")
    if authorization.schema_version != 1:
        raise ValueError("C0 authorization schema_version must be 1")
    if not C0_AUTHORIZATION_ID_RE.fullmatch(authorization.authorization_id):
        raise ValueError("C0 authorization_id is invalid")
    if authorization.authorization_source != C0_AUTHORIZATION_SOURCE:
        raise ValueError("C0 authorization_source must be typed-user-confirmation")
    if authorization.authorization_kind != C0_AUTHORIZATION_KIND:
        raise ValueError("C0 authorization_kind must be c0-projector-cutover")
    if authorization.operation != C0_APPLY_OPERATION:
        raise ValueError("C0 authorization operation mismatch")
    if authorization.single_use is not True:
        raise ValueError("C0 authorization must be single-use")
    if not authorization.decision_ref.startswith("process/checkpoints/"):
        raise ValueError("C0 authorization decision_ref must be a process checkpoint ref")
    expected = (
        plan.cr_id,
        work_id,
        plan.release_oid,
        plan.process_oid,
        plan.scope_digest,
        plan.as_dict()["plan_digest"],
        tuple(plan.mutation_allowlist),
    )
    actual = (
        authorization.cr_id,
        authorization.work_id,
        authorization.expected_release_oid,
        authorization.expected_process_oid,
        authorization.scope_digest,
        authorization.plan_digest,
        tuple(authorization.mutation_allowlist),
    )
    if actual != expected:
        raise ValueError("C0 authorization does not match CR/Work/OIDs/scope/plan/allowlist")
    if not C0_OID_RE.fullmatch(authorization.expected_release_oid):
        raise ValueError("C0 expected_release_oid is invalid")
    if not C0_OID_RE.fullmatch(authorization.expected_process_oid):
        raise ValueError("C0 expected_process_oid is invalid")
    if not C0_DIGEST_RE.fullmatch(authorization.scope_digest):
        raise ValueError("C0 scope_digest is invalid")
    if not C0_DIGEST_RE.fullmatch(authorization.plan_digest):
        raise ValueError("C0 plan_digest is invalid")
    try:
        expires_at = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("C0 authorization expires_at is invalid") from exc
    if expires_at.tzinfo is None:
        raise ValueError("C0 authorization expires_at must include timezone")
    if expires_at.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError("C0 authorization is expired")


def _git_common_dir(repo_root: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    raw = result.stdout.strip()
    if result.returncode != 0 or not raw:
        raise ValueError(f"unable to resolve git common dir for {repo_root.name}")
    path = Path(raw)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _c0_private_root(project_root: Path) -> Path:
    return _git_common_dir(project_root) / "meta-flow" / "c0-cutover"


def _c0_process_lock_path(process_root: Path) -> Path:
    return _git_common_dir(process_root) / "meta-flow" / "c0-cutover.lock"


def _claim_c0_authorization(
    project_root: Path,
    authorization: C0AuthorizationV1,
) -> Path:
    path = (
        _c0_private_root(project_root)
        / "authorizations"
        / f"{authorization.authorization_id}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "authorization_id": authorization.authorization_id,
        "operation": authorization.operation,
        "cr_id": authorization.cr_id,
        "work_id": authorization.work_id,
        "plan_digest": authorization.plan_digest,
        "expected_release_oid": authorization.expected_release_oid,
        "expected_process_oid": authorization.expected_process_oid,
        "scope_digest": authorization.scope_digest,
        "claimed_at": _now_utc(),
    }
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise ValueError("C0 authorization was already consumed") from exc
    return path


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _optional_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _append_ndjson(before: str | None, event: dict[str, Any]) -> str:
    prefix = before or ""
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"


def _c0_result_ref(cr_id: str) -> str:
    return f"process/checks/C0-{cr_id}-PROJECTOR-CUTOVER.result.json"


def _c0_summary_ref(cr_id: str) -> str:
    return f"process/checks/C0-{cr_id}-PROJECTOR-CUTOVER.summary.md"


def _load_valid_c0_ledger_events(path: Path, *, ledger_type: str) -> list[dict[str, Any]]:
    errors, _warnings = validate_event_ledger(path, ledger_type=ledger_type)
    if errors:
        raise ValueError(f"C0 {ledger_type} ledger is invalid: {errors}")
    events, load_errors = load_events(path)
    if load_errors:
        raise ValueError(f"C0 {ledger_type} ledger cannot be loaded: {load_errors}")
    return events


def _c0_cutover_events(
    *,
    path: Path,
    ledger_type: str,
    cr_id: str,
) -> list[dict[str, Any]]:
    events = _load_valid_c0_ledger_events(path, ledger_type=ledger_type)
    if ledger_type == "checkpoint":
        return [
            event
            for event in events
            if event.get("event_type") == "checkpoint_result"
            and event.get("checkpoint") == "C0"
            and event.get("cr_id") == cr_id
        ]
    return [
        event
        for event in events
        if event.get("event_type") == "gate_passed"
        and event.get("gate") == f"CUTOVER-GATE-{cr_id}-C0"
        and event.get("cr_id") == cr_id
    ]


def _c0_revision_event_id(
    *,
    prefix: str,
    cr_id: str,
    plan_digest: str,
    authorization_id: str,
) -> str:
    revision_digest = canonical_digest(
        {
            "authorization_id": authorization_id,
            "plan_digest": plan_digest,
        }
    )
    return f"{prefix}-{cr_id}-{revision_digest}"


def _build_c0_apply_targets(
    *,
    project_root: Path,
    plan: state_transition.C0ResultV1,
    authorization: C0AuthorizationV1,
) -> tuple[tuple[C0MutationTarget, ...], dict[str, Any]]:
    development_plan_ref = "process/DEVELOPMENT-PLAN.yaml"
    development_plan_path = _resolve_runtime_ref(project_root, development_plan_ref)
    development_plan = load_yaml_object(development_plan_path)
    result_ref = _c0_result_ref(plan.cr_id)
    result_path = _resolve_runtime_ref(project_root, result_ref)
    prior_result: dict[str, Any] = {}
    if result_path.is_file():
        try:
            loaded_result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("C0 prior apply result is invalid JSON") from exc
        if not isinstance(loaded_result, dict):
            raise ValueError("C0 prior apply result must be an object")
        if loaded_result.get("kind") != "C0ApplyResultV1":
            raise ValueError("C0 prior apply result kind is invalid")
        prior_result = loaded_result
    prior_transitions = prior_result.get("story_transitions") or []
    if not isinstance(prior_transitions, list):
        raise ValueError("C0 prior story_transitions must be a list")
    projected_plan, story_transitions = state_transition.project_c0_development_plan(
        development_plan,
        cr_id=plan.cr_id,
        prior_transitions=prior_transitions,
    )
    completed_at = _now_utc()
    summary_ref = _c0_summary_ref(plan.cr_id)
    result_payload = {
        "schema_version": 1,
        "kind": "C0ApplyResultV1",
        "checkpoint": "C0",
        "cr_id": plan.cr_id,
        "work_id": authorization.work_id,
        "decision": "PASS",
        "status": "passed",
        "release_oid": plan.release_oid,
        "process_oid": plan.process_oid,
        "scope_digest": plan.scope_digest,
        "plan_digest": plan.as_dict()["plan_digest"],
        "authorization_id": authorization.authorization_id,
        "input_evidence_refs": list(plan.input_evidence_refs),
        "replay_pass_count": sum(
            1 for item in plan.replay_results if str(item.get("decision") or "") == "PASS"
        ),
        "consumer_pass_count": sum(
            1 for item in plan.consumer_inventory if str(item.get("status") or "") == "PASS"
        ),
        "bootstrap_consumer_count": plan.bootstrap_consumer_count,
        "legacy_projector_consumer_count": plan.legacy_projector_consumer_count,
        "story_transitions": list(story_transitions),
        "mutation_allowlist": list(plan.mutation_allowlist),
        "mutation_count": len(plan.mutation_allowlist),
        "completed_at": completed_at,
    }
    result_text = json.dumps(result_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    projected_statuses = {
        str(story.get("story_id") or ""): str(story.get("status") or "")
        for wave in projected_plan.get("waves", [])
        if isinstance(wave, dict)
        for story in wave.get("stories", [])
        if isinstance(story, dict)
    }
    story_status_lines = "".join(
        f"- {story_id}：`{projected_statuses.get(story_id, 'missing')}`\n"
        for story_id in sorted(projected_statuses)
        if story_id.startswith(f"STORY-{plan.cr_id.replace('-', '')}-S")
    )
    summary_text = (
        f"# C0 {plan.cr_id} Projector Cutover\n\n"
        "## Entry Criteria\n\n"
        f"- exact release OID：`{plan.release_oid}`\n"
        f"- exact process OID：`{plan.process_oid}`\n"
        f"- scope digest：`{plan.scope_digest}`\n"
        f"- plan digest：`{plan.as_dict()['plan_digest']}`\n\n"
        "## Checklist\n\n"
        "- Frozen CP6 replay：`3/3 PASS`\n"
        "- Public consumer replay：`11/11 PASS`\n"
        "- Bootstrap consumer：`0`\n"
        "- Legacy projector consumer：`0`\n"
        f"{story_status_lines}\n"
        "## Exit Criteria\n\n"
        "- C0 decision：`PASS`\n"
        "- C0 apply：`completed`\n"
        "- S04 可进入原生 CP6 admission；S05 不越过 S04 依赖。\n\n"
        "## Deliverables\n\n"
        f"- `{result_ref}`\n"
        f"- `{summary_ref}`\n"
        "- `process/DEVELOPMENT-PLAN.yaml`\n"
        "- `process/state/CHECKPOINT-LEDGER.ndjson`\n"
        "- `process/state/GATE-LEDGER.ndjson`\n"
    )
    plan_digest = plan.as_dict()["plan_digest"]
    checkpoint_event = {
        "event_id": _c0_revision_event_id(
            prefix="C0-PROJECTOR-CUTOVER-PASS",
            cr_id=plan.cr_id,
            plan_digest=plan_digest,
            authorization_id=authorization.authorization_id,
        ),
        "event_type": "checkpoint_result",
        "checkpoint": "C0",
        "decision": "PASS",
        "result_ref": result_ref,
        "cr_id": plan.cr_id,
        "work_id": authorization.work_id,
        "plan_digest": plan_digest,
        "authorization_id": authorization.authorization_id,
        "timestamp": completed_at,
    }
    gate_event = {
        "event_id": _c0_revision_event_id(
            prefix="GATE-C0-PASSED",
            cr_id=plan.cr_id,
            plan_digest=plan_digest,
            authorization_id=authorization.authorization_id,
        ),
        "event_type": "gate_passed",
        "gate": f"CUTOVER-GATE-{plan.cr_id}-C0",
        "status": "passed",
        "decision": "PASS",
        "result_ref": result_ref,
        "cr_id": plan.cr_id,
        "work_id": authorization.work_id,
        "plan_digest": plan_digest,
        "authorization_id": authorization.authorization_id,
        "timestamp": completed_at,
    }
    checkpoint_ledger_ref = "process/state/CHECKPOINT-LEDGER.ndjson"
    gate_ledger_ref = "process/state/GATE-LEDGER.ndjson"
    checkpoint_ledger_path = _resolve_runtime_ref(project_root, checkpoint_ledger_ref)
    gate_ledger_path = _resolve_runtime_ref(project_root, gate_ledger_ref)
    checkpoint_history = _c0_cutover_events(
        path=checkpoint_ledger_path,
        ledger_type="checkpoint",
        cr_id=plan.cr_id,
    )
    gate_history = _c0_cutover_events(
        path=gate_ledger_path,
        ledger_type="gate",
        cr_id=plan.cr_id,
    )
    if len(checkpoint_history) != len(gate_history):
        raise ValueError("C0 checkpoint/gate cutover history is inconsistent")
    same_plan_history = any(
        event.get("plan_digest") == plan_digest
        for event in checkpoint_history + gate_history
    )
    repairs_regression = any(
        transition.get("reason") == "C0_REPAIR_REGRESSIVE_PRIOR_PROJECTION"
        for transition in story_transitions
    )
    if same_plan_history and not repairs_regression:
        raise ValueError("C0 current plan already has ledger evidence but result projection is inconsistent")
    revision = len(checkpoint_history) + 1
    checkpoint_event_id = str(checkpoint_event["event_id"])
    gate_event_id = str(gate_event["event_id"])
    prior_checkpoint = checkpoint_history[-1] if checkpoint_history else None
    prior_gate = gate_history[-1] if gate_history else None
    checkpoint_event["cutover_revision"] = revision
    gate_event["cutover_revision"] = revision
    if prior_checkpoint and prior_gate:
        checkpoint_event["supersedes_event_id"] = str(prior_checkpoint.get("event_id") or "")
        gate_event["supersedes_event_id"] = str(prior_gate.get("event_id") or "")
        checkpoint_event["supersedes_plan_digest"] = str(
            prior_checkpoint.get("plan_digest") or ""
        )
        gate_event["supersedes_plan_digest"] = str(prior_gate.get("plan_digest") or "")
    result_payload.update(
        {
            "cutover_revision": revision,
            "checkpoint_event_id": checkpoint_event_id,
            "gate_event_id": gate_event_id,
            "supersedes_plan_digest": (
                str(prior_checkpoint.get("plan_digest") or "") if prior_checkpoint else ""
            ),
        }
    )
    result_text = json.dumps(result_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    validate_event_before_append(checkpoint_ledger_path, checkpoint_event, ledger_type="checkpoint")
    validate_event_before_append(gate_ledger_path, gate_event, ledger_type="gate")
    target_values = (
        (
            development_plan_ref,
            development_plan_path,
            json.dumps(projected_plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        ),
        (
            result_ref,
            _resolve_runtime_ref(project_root, result_ref),
            result_text,
        ),
        (
            summary_ref,
            _resolve_runtime_ref(project_root, summary_ref),
            summary_text,
        ),
        (
            checkpoint_ledger_ref,
            checkpoint_ledger_path,
            _append_ndjson(_optional_text(checkpoint_ledger_path), checkpoint_event),
        ),
        (
            gate_ledger_ref,
            gate_ledger_path,
            _append_ndjson(_optional_text(gate_ledger_path), gate_event),
        ),
    )
    targets = tuple(
        C0MutationTarget(
            order=index,
            logical_ref=logical_ref,
            path=path,
            before=_optional_text(path),
            after=after,
        )
        for index, (logical_ref, path, after) in enumerate(target_values, 1)
    )
    if tuple(target.logical_ref for target in targets) != tuple(plan.mutation_allowlist):
        raise ValueError("C0 apply targets do not match the dry-run mutation allowlist")
    return targets, result_payload


def _c0_current_digest(target: C0MutationTarget) -> str:
    current = _optional_text(target.path)
    return canonical_digest(current if current is not None else "")


def _c0_already_applied(
    *,
    project_root: Path,
    plan: state_transition.C0ResultV1,
) -> bool:
    result_path = _resolve_runtime_ref(project_root, _c0_result_ref(plan.cr_id))
    if not result_path.is_file():
        return False
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(result, dict):
        return False
    if (
        result.get("kind") != "C0ApplyResultV1"
        or result.get("decision") != "PASS"
        or result.get("plan_digest") != plan.as_dict()["plan_digest"]
    ):
        return False
    prior_transitions = result.get("story_transitions") or []
    if not isinstance(prior_transitions, list):
        return False
    if state_transition.has_c0_regressive_story_transition(
        prior_transitions,
        cr_id=plan.cr_id,
    ):
        return False
    development_plan_path = _resolve_runtime_ref(project_root, "process/DEVELOPMENT-PLAN.yaml")
    development_plan = load_yaml_object(development_plan_path)
    projected, _transitions = state_transition.project_c0_development_plan(
        development_plan,
        cr_id=plan.cr_id,
        prior_transitions=prior_transitions,
    )
    if canonical_digest(development_plan) != canonical_digest(projected):
        return False
    plan_digest = plan.as_dict()["plan_digest"]
    authorization_id = str(result.get("authorization_id") or "")
    checkpoint_path = _resolve_runtime_ref(
        project_root,
        "process/state/CHECKPOINT-LEDGER.ndjson",
    )
    gate_path = _resolve_runtime_ref(
        project_root,
        "process/state/GATE-LEDGER.ndjson",
    )
    checkpoint_matches = [
        event
        for event in _c0_cutover_events(
            path=checkpoint_path,
            ledger_type="checkpoint",
            cr_id=plan.cr_id,
        )
        if event.get("decision") == "PASS"
        and event.get("result_ref") == _c0_result_ref(plan.cr_id)
        and event.get("plan_digest") == plan_digest
        and event.get("authorization_id") == authorization_id
    ]
    gate_matches = [
        event
        for event in _c0_cutover_events(
            path=gate_path,
            ledger_type="gate",
            cr_id=plan.cr_id,
        )
        if event.get("decision") == "PASS"
        and event.get("status") == "passed"
        and event.get("result_ref") == _c0_result_ref(plan.cr_id)
        and event.get("plan_digest") == plan_digest
        and event.get("authorization_id") == authorization_id
    ]
    return len(checkpoint_matches) == 1 and len(gate_matches) == 1


def apply_c0_cutover(
    *,
    project_root: Path,
    cr_id: str,
    work_id: str,
    story_result_refs: list[str],
    expected_plan_digest: str,
    authorization: C0AuthorizationV1 | None,
    _fail_after_replace: int | None = None,
) -> dict[str, Any]:
    """执行 typed、single-use、可回滚的 C0 projector cutover。"""

    release_root = project_root.resolve()
    process_root: Path | None = None
    try:
        plan = build_c0_dry_run(
            project_root=release_root,
            cr_id=cr_id,
            work_id=work_id,
            story_result_refs=story_result_refs,
        )
        plan_digest = plan.as_dict()["plan_digest"]
        if plan.decision != "READY":
            return {
                "status": "BLOCKED",
                "decision": plan.decision,
                "blockers": list(plan.blockers),
                "mutation_count": 0,
            }
        if not expected_plan_digest or expected_plan_digest != plan_digest:
            return {
                "status": "BLOCKED",
                "reason": "expected C0 plan digest does not match current dry-run",
                "mutation_count": 0,
            }
        process_project = _resolve_runtime_ref(release_root, "process/PROJECT.yaml")
        process_root = process_project.parent
        if _c0_already_applied(project_root=release_root, plan=plan):
            return {
                "status": "NO_CHANGE",
                "decision": "PASS",
                "plan_digest": plan_digest,
                "mutation_count": 0,
                "path_refs": [],
            }
        if authorization is None:
            return {
                "status": "BLOCKED",
                "reason": "C0 apply requires typed authorization",
                "mutation_count": 0,
            }
        validate_c0_authorization(plan, authorization, work_id=work_id)
        targets, result_payload = _build_c0_apply_targets(
            project_root=release_root,
            plan=plan,
            authorization=authorization,
        )
        private_root = _c0_private_root(release_root)
        transaction_root = private_root / "transactions"
        transaction_root.mkdir(parents=True, exist_ok=True)
        unresolved = list(transaction_root.glob("*/manifest.json"))
        if unresolved:
            return {
                "status": "BLOCKED",
                "reason": "unresolved C0 transaction exists",
                "mutation_count": 0,
            }
        lock_path = _c0_process_lock_path(process_root)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        transaction_id = uuid.uuid4().hex
        try:
            with lock_path.open("x", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "transaction_id": transaction_id,
                            "operation": C0_APPLY_OPERATION,
                            "plan_digest": plan_digest,
                            "created_at": _now_utc(),
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                )
        except FileExistsError:
            return {
                "status": "BLOCKED",
                "reason": "C0 process writer lock exists",
                "mutation_count": 0,
            }
        transaction_dir = transaction_root / transaction_id
        backup_root = transaction_dir / "backups"
        after_root = transaction_dir / "after"
        backup_root.mkdir(parents=True)
        after_root.mkdir(parents=True)
        applied: list[C0MutationTarget] = []
        manifest_path = transaction_dir / "manifest.json"
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "transaction_id": transaction_id,
            "operation": C0_APPLY_OPERATION,
            "cr_id": cr_id,
            "work_id": work_id,
            "plan_digest": plan_digest,
            "authorization_id": authorization.authorization_id,
            "targets": [],
            "recovery_state": "prepared",
            "created_at": _now_utc(),
            "updated_at": _now_utc(),
        }
        try:
            fresh = build_c0_dry_run(
                project_root=release_root,
                cr_id=cr_id,
                work_id=work_id,
                story_result_refs=story_result_refs,
            )
            if fresh.decision != "READY" or fresh.as_dict()["plan_digest"] != plan_digest:
                raise RuntimeError("C0 plan drifted after acquiring the process writer lock")
            drifted = [
                target.logical_ref
                for target in targets
                if _c0_current_digest(target) != target.before_digest
            ]
            if drifted:
                raise RuntimeError("C0 target preimage drift: " + ", ".join(drifted))
            _claim_c0_authorization(release_root, authorization)
            for target in targets:
                backup = backup_root / f"{target.order:03d}.before"
                prepared_after = after_root / f"{target.order:03d}.after"
                backup.write_text(target.before or "", encoding="utf-8")
                prepared_after.write_text(target.after, encoding="utf-8")
                if canonical_digest(backup.read_text(encoding="utf-8")) != target.before_digest:
                    raise RuntimeError(f"C0 backup digest mismatch: {target.logical_ref}")
                if canonical_digest(prepared_after.read_text(encoding="utf-8")) != target.after_digest:
                    raise RuntimeError(f"C0 prepared-after digest mismatch: {target.logical_ref}")
                manifest["targets"].append(
                    {
                        **target.as_dict(),
                        "apply_status": "prepared",
                        "rollback_status": "not-required",
                    }
                )
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest["recovery_state"] = "applying"
            for offset, target in enumerate(targets, 1):
                if _c0_current_digest(target) != target.before_digest:
                    raise RuntimeError(f"C0 target changed during apply: {target.logical_ref}")
                _atomic_write_text(target.path, target.after)
                applied.append(target)
                manifest["targets"][offset - 1]["apply_status"] = "applied"
                manifest["updated_at"] = _now_utc()
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                if _fail_after_replace == offset:
                    raise RuntimeError(f"injected C0 failure after replace {offset}")
            readback_failures = [
                target.logical_ref
                for target in targets
                if _c0_current_digest(target) != target.after_digest
            ]
            if readback_failures:
                raise RuntimeError("C0 read-back mismatch: " + ", ".join(readback_failures))
            manifest["recovery_state"] = "committed"
            manifest["updated_at"] = _now_utc()
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            shutil.rmtree(transaction_dir)
            return {
                "status": "PASS",
                "decision": "PASS",
                "transaction_id": transaction_id,
                "authorization_id": authorization.authorization_id,
                "plan_digest": plan_digest,
                "mutation_count": len(targets),
                "path_refs": [target.logical_ref for target in targets],
                "story_transitions": result_payload["story_transitions"],
            }
        except Exception as exc:
            rollback_errors: list[str] = []
            for target in reversed(applied):
                try:
                    if target.before is None:
                        target.path.unlink(missing_ok=True)
                    else:
                        _atomic_write_text(target.path, target.before)
                    if _c0_current_digest(target) != target.before_digest:
                        raise RuntimeError("rollback digest mismatch")
                    for entry in manifest["targets"]:
                        if entry["logical_ref"] == target.logical_ref:
                            entry["rollback_status"] = "restored"
                except Exception as rollback_error:
                    rollback_errors.append(f"{target.logical_ref}: {rollback_error}")
            status = "PARTIAL" if rollback_errors else "RECOVERED" if applied else "BLOCKED"
            manifest["recovery_state"] = status.lower()
            manifest["updated_at"] = _now_utc()
            if manifest_path.parent.is_dir():
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            if status in {"BLOCKED", "RECOVERED"}:
                shutil.rmtree(transaction_dir)
            result = {
                "status": status,
                "reason": _portable_c0_error(
                    exc,
                    project_root=release_root,
                    process_root=process_root,
                ),
                "transaction_id": transaction_id,
                "authorization_id": authorization.authorization_id,
                "plan_digest": plan_digest,
                "mutation_count": len(applied),
                "rollback_errors": rollback_errors,
            }
            if status == "PARTIAL":
                result["rollback_evidence_ref"] = (
                    f"private://c0-cutover/transactions/{transaction_id}/manifest.json"
                )
            return result
        finally:
            lock_path.unlink(missing_ok=True)
    except (OSError, ProcessRouteError, ValueError) as exc:
        return {
            "status": "BLOCKED",
            "reason": _portable_c0_error(
                exc,
                project_root=release_root,
                process_root=process_root,
            ),
            "mutation_count": 0,
        }


def _print_route_help() -> None:
    print(
        "usage: meta-flow route <command> [options]\n\n"
        "Commands:\n"
        "  plan  Derive a CR route plan from cr_type, cr_trait, and gate_profile.\n\n"
        "  check Validate a CR route_plan_ref against CR frontmatter.\n\n"
        "  c0-dry-run Replay bootstrap CP6 evidence through the canonical C0 projector.\n\n"
        "  c0-apply Apply one typed, single-use C0 projector cutover transaction.\n\n"
        "Examples:\n"
        "  meta-flow route plan --cr-type process --gate-profile process-lite --cr-trait '{\"uses_existing_evidence_only\": true}'\n"
        "  meta-flow route plan --from-cr process/changes/CR-045.md --output process/checks/CP0-CR045.route-plan.json --project-root .\n"
        "  meta-flow route check --from-cr process/changes/CR-045.md --project-root .\n"
        "  meta-flow route c0-dry-run --project-root . --cr-id CR-061 --story-result process/checks/CP6-STORY-CR061-S01.result.json --story-result process/checks/CP6-STORY-CR061-S02.result.json --story-result process/checks/CP6-STORY-CR061-S03.result.json --format json\n"
        "  meta-flow route c0-apply --project-root . --cr-id CR-061 --story-result process/checks/CP6-STORY-CR061-S01.result.json --story-result process/checks/CP6-STORY-CR061-S02.result.json --story-result process/checks/CP6-STORY-CR061-S03.result.json --expected-plan-digest <digest> --authorization-json '{...}' --apply\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_route_help()
        return 0
    command = args[0]
    if command in {"c0-dry-run", "c0-apply"}:
        parser = argparse.ArgumentParser(prog=f"meta-flow route {command}")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--cr-id", required=True)
        parser.add_argument("--work-id", default="GOV-006-KERNEL-001")
        parser.add_argument("--story-result", action="append", default=[])
        parser.add_argument("--format", choices=("json",), default="json")
        if command == "c0-apply":
            parser.add_argument("--expected-plan-digest", default="")
            parser.add_argument("--authorization-json", default="")
            parser.add_argument("--apply", action="store_true")
        parsed = parser.parse_args(args[1:])
        if command == "c0-apply" and parsed.apply:
            try:
                authorization_payload = json.loads(parsed.authorization_json) if parsed.authorization_json else None
                if authorization_payload is not None and not isinstance(authorization_payload, dict):
                    raise ValueError("C0 authorization JSON must contain an object")
                authorization = (
                    C0AuthorizationV1.from_dict(authorization_payload)
                    if authorization_payload is not None
                    else None
                )
                result = apply_c0_cutover(
                    project_root=parsed.project_root,
                    cr_id=parsed.cr_id,
                    work_id=parsed.work_id,
                    story_result_refs=parsed.story_result,
                    expected_plan_digest=parsed.expected_plan_digest,
                    authorization=authorization,
                )
            except (json.JSONDecodeError, ValueError) as exc:
                result = {
                    "status": "BLOCKED",
                    "reason": _portable_c0_error(exc, project_root=parsed.project_root),
                    "mutation_count": 0,
                }
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if result.get("status") in {"PASS", "NO_CHANGE"} else 2
        try:
            result = build_c0_dry_run(
                project_root=parsed.project_root,
                cr_id=parsed.cr_id,
                work_id=parsed.work_id,
                story_result_refs=parsed.story_result,
            )
        except (OSError, ProcessRouteError, ValueError) as exc:
            print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
            return 2
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.decision == "READY" else 1
    if command not in {"plan", "check"}:
        raise SystemExit(
            f"unknown route command: {command}. Currently supported: plan, check, c0-dry-run, c0-apply"
        )
    parser = argparse.ArgumentParser(prog=f"meta-flow route {command}")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--from-cr", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--cr-type", default="")
    parser.add_argument("--gate-profile", default="")
    parser.add_argument("--cr-trait", default="{}")
    parser.add_argument("--product-baseline-refresh-required", action="store_true")
    parser.add_argument("--impact-surface", nargs="*", default=[])
    parser.add_argument("--authz-policy-refs", nargs="*", default=[])
    parsed = parser.parse_args(args[1:])
    profiles_data = gate_profiles.load_gate_profiles(parsed.project_root)
    if command == "check":
        if not parsed.from_cr:
            raise SystemExit("--from-cr is required for route check")
        errors, warnings = validate_route_plan_for_cr(parsed.project_root, parsed.from_cr, profiles_data=profiles_data)
        print("Route Plan Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if parsed.from_cr:
        mapping = parse_cr_frontmatter(parsed.from_cr)
        if not mapping:
            raise SystemExit(f"--from-cr has no readable frontmatter: {parsed.from_cr}")
        plan = derive_route_plan_from_mapping(mapping, profiles_data=profiles_data)
    else:
        if not parsed.cr_type or not parsed.gate_profile:
            raise SystemExit("--cr-type and --gate-profile are required unless --from-cr is used")
        plan = derive_route_plan(
            cr_type=parsed.cr_type,
            cr_trait=_load_trait(parsed.cr_trait),
            gate_profile=parsed.gate_profile,
            product_baseline_refresh_required=parsed.product_baseline_refresh_required,
            impact_surface=parsed.impact_surface,
            authz_policy_refs=parsed.authz_policy_refs,
            profiles_data=profiles_data,
        )
    payload = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True)
    if parsed.output:
        output = write_route_plan(parsed.output, plan)
        print(f"wrote: {output}")
    else:
        print(payload)
    return 1 if plan.get("blockers") else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
