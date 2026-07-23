"""CR-aware route-plan derivation for Meta Flow."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from meta_flow.policies import gate_profiles
from meta_flow.project.process_route import ProcessRouteError, _resolve_runtime_ref

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


def _print_route_help() -> None:
    print(
        "usage: meta-flow route <command> [options]\n\n"
        "Commands:\n"
        "  plan  Derive a CR route plan from cr_type, cr_trait, and gate_profile.\n\n"
        "  check Validate a CR route_plan_ref against CR frontmatter.\n\n"
        "Examples:\n"
        "  meta-flow route plan --cr-type process --gate-profile process-lite --cr-trait '{\"uses_existing_evidence_only\": true}'\n"
        "  meta-flow route plan --from-cr process/changes/CR-045.md --output process/checks/CP0-CR045.route-plan.json --project-root .\n"
        "  meta-flow route check --from-cr process/changes/CR-045.md --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_route_help()
        return 0
    command = args[0]
    if command not in {"plan", "check"}:
        raise SystemExit(f"unknown route command: {command}. Currently supported: plan, check")
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
