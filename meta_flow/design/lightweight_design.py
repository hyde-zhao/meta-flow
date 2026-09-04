"""新 G2 的轻量设计证据合同与 fail-closed 判定。"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

import yaml

from meta_flow.work.governance_profile import effective_governance_profile

SCOPE_GOAL_NOTE_SCHEMA_VERSION = 1
ARCHITECTURE_IMPACT_NOTE_SCHEMA_VERSION = 1
SCOPE_GOAL_NOTE_MAX_LINES = 120
SCOPE_GOAL_NOTE_MAX_TOKENS = 3_000
SCOPE_GOAL_NOTE_CHARS_PER_TOKEN = 3.5

# Story 卡可声明的六类升级信号，与 ScopeGoalNoteV1 冻结 schema 一致。
SCOPE_ESCALATION_TRIGGERS = frozenset(
    {
        "PUBLIC_CONTRACT_DELTA",
        "SECURITY_OR_PERMISSION_DELTA",
        "DATA_OR_MIGRATION_DELTA",
        "CONCURRENCY_OR_TRANSACTION_DELTA",
        "ARCHITECTURE_BASELINE_DELTA",
        "CROSS_DEVICE_AUTH_DELTA",
    }
)

# 运行时事实扫描使用八类语义，不让六类文档分组掩盖 credential/生产写等风险。
CONSENT_TRIGGERS = frozenset(
    {
        "credential_or_secret",
        "security_boundary",
        "production_or_live_write",
        "irreversible_data_migration",
        "breaking_public_api_or_schema",
        "cross_device_auth_or_identity",
        "distributed_transaction_or_concurrency",
        "unexplained_cross_module_boundary",
    }
)

ARCHITECTURE_DELTA_FIELDS = (
    "public_interface",
    "data_schema",
    "state_transaction_concurrency",
    "permission_authorization",
    "dependency_direction",
    "runtime_external_system",
)

_SCOPE_TRIGGER_TO_CONSENT = {
    "PUBLIC_CONTRACT_DELTA": "breaking_public_api_or_schema",
    "SECURITY_OR_PERMISSION_DELTA": "security_boundary",
    "DATA_OR_MIGRATION_DELTA": "irreversible_data_migration",
    "CONCURRENCY_OR_TRANSACTION_DELTA": "distributed_transaction_or_concurrency",
    "ARCHITECTURE_BASELINE_DELTA": "unexplained_cross_module_boundary",
    "CROSS_DEVICE_AUTH_DELTA": "cross_device_auth_or_identity",
}
_STORY_ID_RE = re.compile(r"^STORY-[A-Z0-9-]+$")
_CR_ID_RE = re.compile(r"^CR-[0-9]+$")
_REQ_RE = re.compile(r"^REQ-[A-Z0-9-]+$")
_SCN_RE = re.compile(r"^SCN-[A-Z0-9-]+$")
_REF_RE = re.compile(r"^(?:process|docs|meta_flow|tests|delivery)/[^\\\s]+$")


def _closed_fields(
    payload: Mapping[str, Any],
    required: set[str],
    optional: set[str],
    code: str,
) -> None:
    if not required.issubset(payload) or set(payload) - required - optional:
        raise ValueError(code)


def _text(value: Any, code: str, *, minimum: int = 1) -> str:
    if not isinstance(value, str):
        raise ValueError(code)
    text = value.strip()
    if len(text) < minimum:
        raise ValueError(code)
    return text


def _strings(value: Any, code: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (required and not value):
        raise ValueError(code)
    if any(not isinstance(item, str) for item in value):
        raise ValueError(code)
    values = tuple(item.strip() for item in value)
    if any(not item for item in values) or len(set(values)) != len(values):
        raise ValueError(code)
    return values


def _mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def extract_scope_goal_note_from_story(text: str) -> tuple[dict[str, Any], str]:
    """从 Story 的“范围与目标”章节提取唯一 YAML/JSON 闭合对象。"""

    heading = re.search(r"(?m)^##[ \t]+范围与目标[ \t]*$", text)
    if heading is None:
        raise ValueError("SCOPE_GOAL_NOTE_SECTION_MISSING")
    tail = text[heading.end() :]
    next_heading = re.search(r"(?m)^##[ \t]+", tail)
    section = tail[: next_heading.start()] if next_heading else tail
    blocks = re.findall(
        r"```(?:yaml|yml|json)?[ \t]*\r?\n(.*?)\r?\n```",
        section,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if len(blocks) != 1:
        raise ValueError("SCOPE_GOAL_NOTE_SECTION_REQUIRES_ONE_DATA_BLOCK")
    raw = blocks[0]
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError("SCOPE_GOAL_NOTE_SECTION_PARSE_FAILED") from exc
    if not isinstance(payload, dict):
        raise ValueError("SCOPE_GOAL_NOTE_OBJECT_REQUIRED")
    return payload, raw


@dataclass(frozen=True, slots=True)
class ScopeGoalNoteV1:
    """与 scope-goal-note-v1.schema.json 同形的闭合对象。"""

    payload: Mapping[str, Any]

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        raw_text: str = "",
        effective_profile: str = "",
    ) -> ScopeGoalNoteV1:
        required = {
            "schema_version",
            "kind",
            "story_id",
            "design_evidence_type",
            "scope",
            "goal",
            "acceptance_boundary",
            "file_impact",
            "dependencies",
            "escalation_triggers",
            "limits",
        }
        optional = {"risk_profile_schema_version", "governance_profile"}
        _closed_fields(payload, required, optional, "SCOPE_GOAL_NOTE_FIELDS_INVALID")
        if payload.get("schema_version") != 1 or payload.get("kind") != "ScopeGoalNoteV1":
            raise ValueError("SCOPE_GOAL_NOTE_SCHEMA_INVALID")
        if payload.get("design_evidence_type") != "scope-goal-note":
            raise ValueError("SCOPE_GOAL_NOTE_EVIDENCE_TYPE_INVALID")
        story_id = _text(payload.get("story_id"), "SCOPE_GOAL_NOTE_STORY_ID_INVALID")
        if not _STORY_ID_RE.fullmatch(story_id):
            raise ValueError("SCOPE_GOAL_NOTE_STORY_ID_INVALID")
        if payload.get("risk_profile_schema_version") not in {None, 2}:
            raise ValueError("SCOPE_GOAL_NOTE_PROFILE_VERSION_INVALID")
        if payload.get("governance_profile") not in {None, "G2"}:
            raise ValueError("SCOPE_GOAL_NOTE_PROFILE_INVALID")
        if effective_profile and effective_profile != "G2":
            raise ValueError("SCOPE_GOAL_NOTE_EFFECTIVE_PROFILE_INVALID")

        scope = _mapping(payload.get("scope"), "SCOPE_GOAL_NOTE_SCOPE_INVALID")
        _closed_fields(scope, {"in", "out"}, set(), "SCOPE_GOAL_NOTE_SCOPE_FIELDS_INVALID")
        _strings(scope.get("in"), "SCOPE_GOAL_NOTE_IN_SCOPE_INVALID", required=True)
        _strings(scope.get("out"), "SCOPE_GOAL_NOTE_OUT_OF_SCOPE_INVALID")
        goal = _text(payload.get("goal"), "SCOPE_GOAL_NOTE_GOAL_INVALID", minimum=8)
        if len(goal) > 2_000:
            raise ValueError("SCOPE_GOAL_NOTE_GOAL_INVALID")

        acceptance = _mapping(
            payload.get("acceptance_boundary"), "SCOPE_GOAL_NOTE_ACCEPTANCE_INVALID"
        )
        _closed_fields(
            acceptance,
            {"requirement_refs", "scenario_refs", "must", "must_not"},
            set(),
            "SCOPE_GOAL_NOTE_ACCEPTANCE_FIELDS_INVALID",
        )
        requirement_refs = _strings(
            acceptance.get("requirement_refs"),
            "SCOPE_GOAL_NOTE_REQUIREMENT_REFS_INVALID",
            required=True,
        )
        scenario_refs = _strings(
            acceptance.get("scenario_refs"), "SCOPE_GOAL_NOTE_SCENARIO_REFS_INVALID"
        )
        _strings(acceptance.get("must"), "SCOPE_GOAL_NOTE_MUST_INVALID", required=True)
        _strings(acceptance.get("must_not"), "SCOPE_GOAL_NOTE_MUST_NOT_INVALID")
        if any(not _REQ_RE.fullmatch(ref) for ref in requirement_refs):
            raise ValueError("SCOPE_GOAL_NOTE_REQUIREMENT_REFS_INVALID")
        if any(not _SCN_RE.fullmatch(ref) for ref in scenario_refs):
            raise ValueError("SCOPE_GOAL_NOTE_SCENARIO_REFS_INVALID")

        impact = _mapping(payload.get("file_impact"), "SCOPE_GOAL_NOTE_FILE_IMPACT_INVALID")
        _closed_fields(
            impact,
            {"create", "modify", "delete", "forbidden", "primary_owner"},
            set(),
            "SCOPE_GOAL_NOTE_FILE_IMPACT_FIELDS_INVALID",
        )
        for key in ("create", "modify", "delete", "forbidden"):
            refs = _strings(impact.get(key), "SCOPE_GOAL_NOTE_FILE_REFS_INVALID")
            if any(not _REF_RE.fullmatch(ref) for ref in refs):
                raise ValueError("SCOPE_GOAL_NOTE_FILE_REFS_INVALID")
        _text(impact.get("primary_owner"), "SCOPE_GOAL_NOTE_PRIMARY_OWNER_INVALID", minimum=3)

        dependencies = _mapping(
            payload.get("dependencies"), "SCOPE_GOAL_NOTE_DEPENDENCIES_INVALID"
        )
        _closed_fields(
            dependencies,
            {"contract", "runtime", "file_conflict"},
            set(),
            "SCOPE_GOAL_NOTE_DEPENDENCY_FIELDS_INVALID",
        )
        for key in ("contract", "runtime", "file_conflict"):
            _strings(dependencies.get(key), "SCOPE_GOAL_NOTE_DEPENDENCIES_INVALID")

        triggers = _strings(
            payload.get("escalation_triggers"), "SCOPE_GOAL_NOTE_TRIGGER_INVALID"
        )
        if set(triggers) - SCOPE_ESCALATION_TRIGGERS:
            raise ValueError("SCOPE_GOAL_NOTE_TRIGGER_INVALID")
        limits = _mapping(payload.get("limits"), "SCOPE_GOAL_NOTE_LIMITS_INVALID")
        _closed_fields(
            limits,
            {"max_lines", "max_tokens"},
            set(),
            "SCOPE_GOAL_NOTE_LIMIT_FIELDS_INVALID",
        )
        if limits.get("max_lines") != SCOPE_GOAL_NOTE_MAX_LINES:
            raise ValueError("SCOPE_GOAL_NOTE_LINE_LIMIT_DECLARATION_INVALID")
        if limits.get("max_tokens") != SCOPE_GOAL_NOTE_MAX_TOKENS:
            raise ValueError("SCOPE_GOAL_NOTE_TOKEN_LIMIT_DECLARATION_INVALID")
        rendered = raw_text or json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        non_empty_lines = sum(bool(line.strip()) for line in rendered.splitlines())
        estimated_tokens = math.ceil(len(rendered) / SCOPE_GOAL_NOTE_CHARS_PER_TOKEN)
        if non_empty_lines > SCOPE_GOAL_NOTE_MAX_LINES:
            raise ValueError("SCOPE_GOAL_NOTE_LINE_LIMIT_EXCEEDED")
        if estimated_tokens > SCOPE_GOAL_NOTE_MAX_TOKENS:
            raise ValueError("SCOPE_GOAL_NOTE_TOKEN_LIMIT_EXCEEDED")
        return cls(json.loads(json.dumps(payload, ensure_ascii=False)))

    @property
    def story_id(self) -> str:
        return str(self.payload["story_id"])

    @property
    def escalation_triggers(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.payload["escalation_triggers"])

    def as_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False))

    @property
    def digest(self) -> str:
        return _digest(self.payload)


@dataclass(frozen=True, slots=True)
class ArchitectureImpactNoteV1:
    """CP3-lite 的 CR 级架构影响说明。"""

    payload: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ArchitectureImpactNoteV1:
        required = {
            "schema_version",
            "kind",
            "cr_id",
            "reused_architecture_refs",
            "affected_modules",
            "deltas",
            "failure_fallback_boundary",
            "consent_triggers",
            "path_simulations",
            "cp3_disposition",
        }
        optional = {
            "risk_profile_schema_version",
            "governance_profile",
            "delta_notes",
        }
        _closed_fields(payload, required, optional, "ARCHITECTURE_IMPACT_NOTE_FIELDS_INVALID")
        if payload.get("schema_version") != 1 or payload.get("kind") != "ArchitectureImpactNoteV1":
            raise ValueError("ARCHITECTURE_IMPACT_NOTE_SCHEMA_INVALID")
        cr_id = _text(payload.get("cr_id"), "ARCHITECTURE_IMPACT_CR_ID_INVALID")
        if not _CR_ID_RE.fullmatch(cr_id):
            raise ValueError("ARCHITECTURE_IMPACT_CR_ID_INVALID")
        if payload.get("risk_profile_schema_version") not in {None, 2}:
            raise ValueError("ARCHITECTURE_IMPACT_PROFILE_VERSION_INVALID")
        if payload.get("governance_profile") not in {None, "G2"}:
            raise ValueError("ARCHITECTURE_IMPACT_PROFILE_INVALID")
        refs = _strings(
            payload.get("reused_architecture_refs"),
            "ARCHITECTURE_IMPACT_REFS_INVALID",
            required=True,
        )
        if any(not _REF_RE.fullmatch(ref) for ref in refs):
            raise ValueError("ARCHITECTURE_IMPACT_REFS_INVALID")
        _strings(
            payload.get("affected_modules"),
            "ARCHITECTURE_IMPACT_MODULES_INVALID",
            required=True,
        )
        deltas = _mapping(payload.get("deltas"), "ARCHITECTURE_IMPACT_DELTAS_INVALID")
        _closed_fields(
            deltas,
            set(ARCHITECTURE_DELTA_FIELDS),
            set(),
            "ARCHITECTURE_IMPACT_DELTA_FIELDS_INVALID",
        )
        if any(deltas.get(field) not in {"none", "has"} for field in ARCHITECTURE_DELTA_FIELDS):
            raise ValueError("ARCHITECTURE_IMPACT_DELTA_VALUE_INVALID")
        notes = payload.get("delta_notes", {})
        if not isinstance(notes, Mapping) or set(notes) - set(ARCHITECTURE_DELTA_FIELDS):
            raise ValueError("ARCHITECTURE_IMPACT_DELTA_NOTES_INVALID")
        if any(
            deltas[field] == "has" and not str(notes.get(field) or "").strip()
            for field in ARCHITECTURE_DELTA_FIELDS
        ):
            raise ValueError("ARCHITECTURE_IMPACT_HAS_REQUIRES_NOTE")
        triggers = _strings(
            payload.get("consent_triggers"), "ARCHITECTURE_IMPACT_CONSENT_INVALID"
        )
        if set(triggers) - CONSENT_TRIGGERS:
            raise ValueError("ARCHITECTURE_IMPACT_CONSENT_INVALID")
        simulations = _mapping(
            payload.get("path_simulations"), "ARCHITECTURE_IMPACT_SIMULATIONS_INVALID"
        )
        _closed_fields(
            simulations,
            {"happy", "failure"},
            set(),
            "ARCHITECTURE_IMPACT_SIMULATION_FIELDS_INVALID",
        )
        for key in ("happy", "failure"):
            _text(
                simulations.get(key),
                "ARCHITECTURE_IMPACT_SIMULATION_INVALID",
                minimum=8,
            )
        _text(
            payload.get("failure_fallback_boundary"),
            "ARCHITECTURE_IMPACT_FALLBACK_INVALID",
            minimum=8,
        )
        has_delta = any(deltas[field] == "has" for field in ARCHITECTURE_DELTA_FIELDS)
        expected = "standard-escalation" if has_delta or triggers else "auto-clean-eligible"
        if payload.get("cp3_disposition") != expected:
            raise ValueError("ARCHITECTURE_IMPACT_DISPOSITION_MISMATCH")
        return cls(json.loads(json.dumps(payload, ensure_ascii=False)))

    @property
    def cr_id(self) -> str:
        return str(self.payload["cr_id"])

    @property
    def active_deltas(self) -> tuple[str, ...]:
        deltas = self.payload["deltas"]
        return tuple(field for field in ARCHITECTURE_DELTA_FIELDS if deltas[field] == "has")

    @property
    def consent_triggers(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.payload["consent_triggers"])

    @property
    def auto_clean_eligible(self) -> bool:
        return not self.active_deltas and not self.consent_triggers

    def as_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False))


def validate_scope_goal_note(
    payload: Mapping[str, Any],
    *,
    effective_profile: str,
    raw_text: str = "",
) -> list[str]:
    try:
        ScopeGoalNoteV1.from_mapping(
            payload,
            raw_text=raw_text,
            effective_profile=effective_profile,
        )
    except (TypeError, ValueError) as exc:
        return [str(exc)]
    return []


def evaluate_lightweight_design(
    note: ScopeGoalNoteV1 | Mapping[str, Any],
    architecture: ArchitectureImpactNoteV1 | Mapping[str, Any],
    *,
    mechanically_observed_impacts: Sequence[str] = (),
    mechanically_unknown_impacts: Sequence[str] = (),
) -> dict[str, Any]:
    """合并 Story 声明、CR 架构影响和机械事实，任何不确定性都阻断。"""

    scope_note = ScopeGoalNoteV1.from_mapping(note) if isinstance(note, Mapping) else note
    impact_note = (
        ArchitectureImpactNoteV1.from_mapping(architecture)
        if isinstance(architecture, Mapping)
        else architecture
    )
    blockers: list[str] = []
    declared = {
        _SCOPE_TRIGGER_TO_CONSENT[item] for item in scope_note.escalation_triggers
    }
    observed = {str(item) for item in mechanically_observed_impacts}
    unknown = {str(item) for item in mechanically_unknown_impacts}
    if (observed | unknown) - CONSENT_TRIGGERS:
        blockers.append("MECHANICAL_CONSENT_TRIGGER_INVALID")
    if unknown:
        blockers.append("ARCHITECTURE_IMPACT_UNKNOWN")
    triggers = declared | observed | set(impact_note.consent_triggers)
    if triggers:
        blockers.append("FULL_LLD_CONSENT_TRIGGERED")
    return {
        "decision": "REQUIRES_FULL_LLD" if blockers else "PASS",
        "story_id": scope_note.story_id,
        "cr_id": impact_note.cr_id,
        "scope_goal_note_digest": scope_note.digest,
        "reason_codes": list(dict.fromkeys(blockers)),
        "consent_triggers": sorted(triggers),
        "architecture_review_required": bool(impact_note.active_deltas),
        "required_lld_policy": "full-lld" if blockers else "scope-goal-note",
        "mutation_count": 0,
    }


def evaluate_story_design_policy(
    *,
    risk_profile: str,
    risk_profile_schema_version: int,
    lld_policy: str,
    lightweight_decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """执行 CP4/CP5 的 profile×证据档位四象限。"""

    effective = effective_governance_profile(risk_profile, risk_profile_schema_version)
    reasons: list[str] = []
    legacy_levels = {"full-lld", "batch-lld", "technical-note", "waived"}
    voluntary_full_lld = False
    if effective == "G3":
        if lld_policy not in legacy_levels:
            reasons.append("G3_LEGACY_DESIGN_EVIDENCE_REQUIRED")
    elif effective == "G2":
        if lld_policy not in {"scope-goal-note", "full-lld", "batch-lld"}:
            reasons.append("G2_DESIGN_EVIDENCE_POLICY_INVALID")
        elif lld_policy in {"full-lld", "batch-lld"}:
            voluntary_full_lld = True
        elif not isinstance(lightweight_decision, Mapping):
            reasons.append("G2_LIGHTWEIGHT_DESIGN_DECISION_REQUIRED")
        elif lightweight_decision.get("decision") != "PASS":
            reasons.extend(str(item) for item in lightweight_decision.get("reason_codes") or [])
            reasons.append("G3_CONSENT_REQUIRED")
    return {
        "decision": "BLOCKED" if reasons else "PASS",
        "effective_profile": effective,
        "lld_policy": lld_policy,
        "voluntary_full_lld": voluntary_full_lld,
        "reason_codes": list(dict.fromkeys(reasons)),
        "mutation_count": 0,
    }


__all__ = [
    "ARCHITECTURE_DELTA_FIELDS",
    "ARCHITECTURE_IMPACT_NOTE_SCHEMA_VERSION",
    "CONSENT_TRIGGERS",
    "SCOPE_ESCALATION_TRIGGERS",
    "SCOPE_GOAL_NOTE_CHARS_PER_TOKEN",
    "SCOPE_GOAL_NOTE_MAX_LINES",
    "SCOPE_GOAL_NOTE_MAX_TOKENS",
    "SCOPE_GOAL_NOTE_SCHEMA_VERSION",
    "ArchitectureImpactNoteV1",
    "ScopeGoalNoteV1",
    "evaluate_lightweight_design",
    "evaluate_story_design_policy",
    "extract_scope_goal_note_from_story",
    "validate_scope_goal_note",
]
