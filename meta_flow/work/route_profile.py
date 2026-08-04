"""Work 的有限路由配置与当前切片写入约束。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.read_contract import is_safe_read_ref
from meta_flow.work.scope import WorkScope, check_scope

ROUTE_PROFILE_SCHEMA_VERSION = 1
ROUTINE_STAGES = ("clarification", "design", "implementation", "verification")
LEGACY_STAGES = tuple(f"CP{index}" for index in range(9))
ROUTE_PROFILE_KEYS = {
    "schema_version",
    "mode",
    "dispatch_mode",
    "legacy_cp_compatibility",
    "validation_profile",
    "failure_scope",
}


@dataclass(frozen=True)
class RouteProfile:
    schema_version: int = ROUTE_PROFILE_SCHEMA_VERSION
    mode: str = "routine-four-stage"
    dispatch_mode: str = "direct"
    legacy_cp_compatibility: bool = False
    validation_profile: str = "layered-v1"
    failure_scope: str = "current-slice-only"

    def __post_init__(self) -> None:
        if self.schema_version != ROUTE_PROFILE_SCHEMA_VERSION:
            raise ValueError(f"route_profile.schema_version must be {ROUTE_PROFILE_SCHEMA_VERSION}")
        if self.mode not in {"routine-four-stage", "legacy-cp0-cp8"}:
            raise ValueError("route_profile.mode is unsupported")
        if self.dispatch_mode not in {"direct", "functional-agent"}:
            raise ValueError("route_profile.dispatch_mode is unsupported")
        if type(self.legacy_cp_compatibility) is not bool:
            raise ValueError("route_profile.legacy_cp_compatibility must be boolean")
        if self.validation_profile != "layered-v1":
            raise ValueError("route_profile.validation_profile must be layered-v1")
        if self.failure_scope != "current-slice-only":
            raise ValueError("route_profile.failure_scope must be current-slice-only")
        if self.legacy_cp_compatibility != (self.mode == "legacy-cp0-cp8"):
            raise ValueError(
                "legacy-cp0-cp8 mode and legacy_cp_compatibility must be enabled together"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "dispatch_mode": self.dispatch_mode,
            "legacy_cp_compatibility": self.legacy_cp_compatibility,
            "validation_profile": self.validation_profile,
            "failure_scope": self.failure_scope,
        }


SAFE_ROUTE_PROFILE = RouteProfile()


def route_profile_from_payload(payload: Mapping[str, Any] | None) -> RouteProfile:
    if payload is None:
        return SAFE_ROUTE_PROFILE
    if not isinstance(payload, Mapping):
        raise ValueError("route_profile must be an object")
    unknown = set(payload) - ROUTE_PROFILE_KEYS
    missing = ROUTE_PROFILE_KEYS - set(payload)
    if unknown:
        raise ValueError(f"route_profile contains unknown fields: {','.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"route_profile missing fields: {','.join(sorted(missing))}")
    return RouteProfile(
        schema_version=payload["schema_version"],
        mode=payload["mode"],
        dispatch_mode=payload["dispatch_mode"],
        legacy_cp_compatibility=payload["legacy_cp_compatibility"],
        validation_profile=payload["validation_profile"],
        failure_scope=payload["failure_scope"],
    )


@dataclass(frozen=True)
class RouteDecision:
    decision: str
    mode: str
    dispatch_mode: str
    stages: tuple[str, ...]
    functional_agent_dispatches: int
    legacy_cp_artifacts_allowed: bool
    errors: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return self.decision == "BLOCKED"

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "stages": list(self.stages),
            "errors": list(self.errors),
        }


def evaluate_route_profile(
    profile: RouteProfile,
    *,
    risk_profile: str,
    work_kind: str,
    human_design_gate_ref: str = "",
    require_human_approval: bool = True,
) -> RouteDecision:
    errors: list[str] = []
    if risk_profile in {"G0", "G1"} and profile.dispatch_mode != "direct":
        errors.append("G0/G1 functional-agent dispatch requires an explicit G2 upgrade")
    if profile.legacy_cp_compatibility:
        if risk_profile != "G2":
            errors.append("legacy CP compatibility requires G2")
        if work_kind != "cr":
            errors.append("legacy CP compatibility requires a formal CR Work")
        if require_human_approval and (
            not human_design_gate_ref or not is_safe_read_ref(human_design_gate_ref)
        ):
            errors.append("legacy CP compatibility requires one safe human design gate ref")
    stages = LEGACY_STAGES if profile.legacy_cp_compatibility else ROUTINE_STAGES
    return RouteDecision(
        decision="BLOCKED" if errors else "READY",
        mode=profile.mode,
        dispatch_mode=profile.dispatch_mode,
        stages=stages,
        functional_agent_dispatches=0 if profile.dispatch_mode == "direct" else 1,
        legacy_cp_artifacts_allowed=profile.legacy_cp_compatibility and not errors,
        errors=tuple(errors),
    )


@dataclass(frozen=True)
class SliceMutationDecision:
    decision: str
    requested_ref: str
    matched_slice_rule: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"


def check_slice_mutation(
    profile: RouteProfile,
    *,
    work_allowed_writes: tuple[str, ...],
    slice_allowed_writes: tuple[str, ...],
    requested_ref: str,
) -> SliceMutationDecision:
    """要求 mutation 同时属于 Work 总范围和当前 slice allowlist。"""

    if profile.failure_scope != "current-slice-only":
        return SliceMutationDecision("DENY", requested_ref, "", "route profile is not slice-scoped")
    try:
        work_scope = WorkScope(1, (), work_allowed_writes, ())
        slice_scope = WorkScope(1, (), slice_allowed_writes, ())
        work_decision = check_scope(work_scope, "write", requested_ref)
        slice_decision = check_scope(slice_scope, "write", requested_ref)
    except ValueError as exc:
        return SliceMutationDecision("DENY", requested_ref, "", str(exc))
    if not work_decision.allowed:
        return SliceMutationDecision("DENY", requested_ref, "", "path is outside Work write scope")
    if not slice_decision.allowed:
        return SliceMutationDecision("DENY", requested_ref, "", "path is outside current slice")
    return SliceMutationDecision(
        "ALLOW",
        Path(requested_ref).as_posix(),
        slice_decision.matched_rule,
        "path is allowed by Work and current slice",
    )
