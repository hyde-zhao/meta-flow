"""CR lifecycle governance for Meta Flow state v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.checks import cr_tracking
from meta_flow.design import feature_registry
from meta_flow.policies import authz, route_plan
from meta_flow.project.governance import load_phase
from meta_flow.project.model import load_project
from meta_flow.project.process_route import _resolve_runtime_ref, require_process_route
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.state import current, event_ledger
from meta_flow.work.lifecycle import transition_work
from meta_flow.work.model import load_work
from meta_flow.work.scope import check_scope
from meta_flow.workspace.git_sync import run_git

CR_LEDGER_REL = Path("process/state/CR-LEDGER.ndjson")
CR_INDEX_REL = Path("process/changes/CR-INDEX.json")
CR_SUMMARY_ROOT_REL = Path("process/changes/summaries")
CR_ARCHIVE_ROOT_REL = Path("process/archive")
LEGACY_SOURCE_REL = Path("process/legacy/LEGACY-SOURCE.yaml")
IMPACT_SURFACE_RULES_REL = Path("process/project/IMPACT-SURFACE-RULES.yaml")
STATE_CURRENT_REL = Path("process/state/STATE.current.json")
CR_ID_RE = re.compile(r"CR-\d+")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
ALLOWED_LIFECYCLE_STATUSES = {
    "candidate",
    "proposed",
    "active",
    "implemented",
    "verified",
    "ready",
    "closed",
    "superseded",
    "cancelled",
    "blocked",
}
FINISHED_STATUSES = {"closed", "superseded", "cancelled"}
CLOSED_GATE_STATUS = "cp8_closed"
INDEX_SCHEMA_VERSION = 1
TERMINATION_TUPLES = {
    "cancelled": {
        "lifecycle_status": "cancelled",
        "readiness_status": "n/a",
        "gate_status": "closed",
    },
    "superseded": {
        "lifecycle_status": "superseded",
        "readiness_status": "n/a",
        "gate_status": "closed",
    },
}
TERMINATION_AUTHORIZATION_FIELDS = {
    "schema_version",
    "authorization_id",
    "authorization_source",
    "authorization_kind",
    "operation",
    "cr_id",
    "work_id",
    "termination_reason",
    "terminal_tuple",
    "expected_release_oid",
    "expected_process_oid",
    "scope_digest",
    "plan_digest",
    "expires_at",
    "single_use",
}
TERMINATION_AUTHORIZATION_SOURCE = "typed-user-confirmation"
TERMINATION_AUTHORIZATION_KIND = "cr-termination"
TERMINATION_OPERATION = "cr.terminate"
STATUS_SYNC_AUTHORIZATION_FIELDS = {
    "schema_version",
    "authorization_id",
    "authorization_source",
    "authorization_kind",
    "operation",
    "cr_id",
    "work_id",
    "desired_transition",
    "effective_at",
    "expected_release_oid",
    "expected_process_oid",
    "scope_digest",
    "targets",
    "plan_digest",
    "expires_at",
    "single_use",
}
STATUS_SYNC_AUTHORIZATION_SOURCE = "typed-user-confirmation"
STATUS_SYNC_AUTHORIZATION_KIND = "cr-status-sync"
STATUS_SYNC_OPERATION = "cr.status-sync"
SAFE_AUTHORIZATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
OID_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_CR_TYPES = {
    "product-scope",
    "architecture",
    "feature",
    "refactor",
    "bugfix",
    "docs",
    "process",
    "runtime",
    "release",
    "experiment",
}
CR_TYPE_ALIASES = {
    "requirement-change": "product-scope",
    "architecture-realignment": "architecture",
    "implementation-gate": "feature",
    "runtime-authorization": "runtime",
    "ledger-maintenance": "process",
    "spike": "experiment",
}
IMPACT_SPLIT_FIELDS = (
    "impact_capability_refs",
    "impact_feature_refs",
    "impact_module_paths",
    "impact_policy_refs",
    "impact_process_refs",
    "impact_runtime_refs",
    "impact_data_refs",
)
OPEN_DEPENDENCY_STATUSES = {"active", "blocked", "proposed"}
GOVERNANCE_BASELINE_MARKERS = (
    "process/policies",
    "process/policy",
    "process/state",
    "process/project",
    "process/roadmap",
    "roadmap",
    "authz",
    "policy",
    "policies",
    "gate_profile",
    "gate_profiles",
    "delivery/rules",
    "agent-skill-contract",
    "directory-contract",
)
CP1_PRODUCT_BASELINE_DOCS = (
    "docs/product/use-cases.md",
    "docs/product/requirements.md",
    "docs/product/scenarios",
    "docs/product/test-matrix",
    "docs/product/story-map",
    "docs/product/mvp-scope",
    "docs/product/release-slices",
    "docs/product/backlog",
)
CP1_FULL_REQUIRED_CHECKS = (
    "use_case_completeness",
    "requirements_traceability",
    "scenario_coverage",
    "story_map_alignment",
    "mvp_scope_alignment",
)
CP1_LIGHTWEIGHT_REQUIRED_CHECKS = (
    "cr_tracking",
    "impact_surface",
    "affected_use_case_refs",
)
ARCHIVE_BACKUP_PATH_MARKERS = (
    "process/archive/",
    "process/backups/",
    "process/backup/",
    "/archive/",
    "/backups/",
    "/backup/",
)
HOUSEKEEPING_CR_MARKERS = (
    "housekeeping",
    "archive",
    "backup",
    "retention",
    "cleanup",
    "clean-up",
    "ledger-compaction",
    "state-slim",
)


@dataclass(frozen=True)
class CRRecord:
    cr_id: str
    cr_type: str
    title: str
    status: str
    readiness: str
    gate_status: str
    gate_profile: str
    full_ref: str
    summary_ref: str
    conflict_keys: list[str]
    impact_surface: list[str]
    impact_capability_refs: list[str]
    impact_feature_refs: list[str]
    impact_module_paths: list[str]
    impact_policy_refs: list[str]
    impact_process_refs: list[str]
    impact_runtime_refs: list[str]
    impact_data_refs: list[str]
    impact_capability_resolution: dict[str, Any]
    authz_policy_refs: list[str]
    risk_refs: list[str]
    goal_ref: str
    goal_statement: str
    user_goal_impact: str
    split_rationale: str
    why_not_merge_with_parent: str
    why_not_story_or_task: str
    approval_focus: str
    decision_burden: str
    approve_effect: str
    reject_effect: str
    not_authorized_by_approve: list[str]
    product_baseline_refresh_required: bool
    required_phase: str
    required_agent: str
    required_gate: str
    block_story_decomposition_until: str
    affected_product_docs: list[str]
    affected_use_cases: list[str]
    routing_design_ref: str
    required_evidence: list[str]
    required_capabilities: list[str]


@dataclass(frozen=True)
class NativeCRStatusProjectionV1:
    """由四个原生 CR 真相源收敛得到的单一状态投影。"""

    cr_id: str
    lifecycle_status: str
    readiness_status: str
    gate_status: str
    formal_cr_ref: str
    summary_ref: str
    ledger_event_id: str
    decision: str
    findings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "kind": "NativeCRStatusProjectionV1",
            "schema_version": 1,
            "findings": list(self.findings),
        }


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class AggregateCompletionProjector:
    """Project one persisted PASS aggregate through CR ledger and current-state writers."""

    def __init__(self, *, project_root: Path, expected_state_updated_at: str) -> None:
        self.project_root = project_root.resolve()
        self.expected_state_updated_at = expected_state_updated_at

    def project_aggregate(self, *, result: Any, receipt: Any) -> dict[str, Any]:
        if not getattr(result, "cr_id", "") or not getattr(receipt, "aggregate_id", ""):
            raise ValueError("aggregate projection receipt identity is missing")
        if getattr(result, "aggregate_id", "") != getattr(receipt, "aggregate_id", ""):
            raise ValueError("aggregate projection result/receipt identity mismatch")
        if (
            str(getattr(result, "overall", "")) != "PASS"
            or getattr(result, "terminal", False) is not True
            or str(getattr(result, "projection_decision", "")) != "ELIGIBLE"
            or getattr(receipt, "readback_valid", False) is not True
            or getattr(receipt, "current_selected", False) is not True
        ):
            raise ValueError("aggregate projection requires persisted/readback current 2/2 PASS")
        cr_id = str(getattr(result, "cr_id", "") or "")
        aggregate_ref = str(getattr(receipt, "aggregate_ref", "") or "")
        writer_receipts: dict[str, Any] = {}
        try:
            state_receipt = current.project_aggregate_completion(
                self.project_root,
                cr_id=cr_id,
                aggregate_id=str(result.aggregate_id),
                aggregate_ref=aggregate_ref,
                payload_digest=str(result.payload_digest),
                expected_updated_at=self.expected_state_updated_at,
            )
        except (OSError, RuntimeError, ValueError) as error:
            return {
                "status": "failed",
                "writer_receipts": writer_receipts,
                "error": f"state_current:{type(error).__name__}:{error}",
            }
        writer_receipts["state_current"] = state_receipt
        existing_event = next(
            (
                event
                for event in load_ledger_events(self.project_root)
                if event.get("event") == "aggregate_projection"
                and event.get("id") == cr_id
                and event.get("aggregate_ref") == aggregate_ref
            ),
            None,
        )
        try:
            if existing_event is None:
                ledger_path = append_ledger_event(
                    self.project_root,
                    {
                        "event": "aggregate_projection",
                        "id": cr_id,
                        "status": "active",
                        "aggregate_id": result.aggregate_id,
                        "aggregate_ref": aggregate_ref,
                        "payload_digest": result.payload_digest,
                        "projection_disposition": state_receipt.get("status"),
                        "projected_at": now_utc(),
                    },
                )
                ledger_receipt = {
                    "status": "projected",
                    "ledger_ref": _rel(self.project_root, ledger_path),
                }
            else:
                ledger_receipt = {
                    "status": "idempotent-existing",
                    "ledger_ref": CR_LEDGER_REL.as_posix(),
                }
        except (OSError, RuntimeError, ValueError) as error:
            return {
                "status": "partial",
                "writer_receipts": writer_receipts,
                "error": f"cr_ledger:{type(error).__name__}:{error}",
            }
        writer_receipts["cr_ledger"] = ledger_receipt
        return {
            "status": "complete",
            "writer_receipts": writer_receipts,
        }


def _strip_scalar(value: Any) -> str:
    raw = str(value).strip()
    if " #" in raw:
        raw = raw.split(" #", 1)[0].rstrip()
    return raw.strip().strip("`").strip('"').strip("'")


def _frontmatter(text: str) -> str:
    match = FRONTMATTER_RE.match(text)
    return match.group(1) if match else ""


def _replace_frontmatter(text: str, frontmatter: str) -> str:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return f"---\n{frontmatter.rstrip()}\n---\n\n{text}"
    return f"---\n{frontmatter.rstrip()}\n---\n" + text[match.end() :]


def parse_frontmatter(text: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    current_list_key = ""
    for line in _frontmatter(text).splitlines():
        if line.startswith("  - ") and current_list_key:
            values.setdefault(current_list_key, []).append(_strip_scalar(line.strip()[2:]))
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_list_key = key
        values[key] = _strip_scalar(value) if value else []
    return values


def _format_frontmatter_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def update_frontmatter_fields(path: Path, updates: dict[str, str]) -> bool:
    """Update scalar frontmatter fields, preserving unrelated body content."""

    text = path.read_text(encoding="utf-8")
    updated = render_frontmatter_fields(text, updates)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def render_frontmatter_fields(text: str, updates: dict[str, str]) -> str:
    """Render scalar frontmatter changes without touching the source file."""

    clean_updates = {key: value for key, value in updates.items() if value != ""}
    if not clean_updates:
        return text
    frontmatter = _frontmatter(text)
    lines = frontmatter.splitlines()
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if ":" not in stripped or stripped.startswith("#") or line.startswith((" ", "\t")):
            next_lines.append(line)
            continue
        key = stripped.split(":", 1)[0].strip()
        if key in clean_updates:
            indent = line[: len(line) - len(line.lstrip())]
            next_lines.append(f"{indent}{key}: {_format_frontmatter_value(clean_updates[key])}")
            seen.add(key)
        else:
            next_lines.append(line)
    for key, value in clean_updates.items():
        if key not in seen:
            next_lines.append(f"{key}: {_format_frontmatter_value(value)}")
    return _replace_frontmatter(text, "\n".join(next_lines))


def _gate_checkpoint_projection(gate_status: str) -> tuple[str, str] | None:
    """Map the lifecycle gate to the exact Checkpoint Index row projection."""

    mapping = {
        "cp2_pending": ("CP2", "pending"),
        "cp3_pending": ("CP3", "pending"),
        "cp5_pending": ("CP5", "pending"),
        "implementation_in_progress": ("CP6", "in-progress"),
        "cp7_pending": ("CP7", "pending"),
        "verification_in_progress": ("CP7", "in-progress"),
        "cp8_pending": ("CP8", "pending"),
        "cp8_closed": ("CP8", "approved"),
        "cp8_recovery_closed": ("CP8", "approved"),
        "closed": ("CP8", "approved"),
    }
    return mapping.get(gate_status)


def _checkpoint_result_projection(
    project_root: Path,
    cr_id: str,
) -> dict[str, str]:
    """Project canonical CR-level checkpoint results without guessing completion."""

    checks_root = _resolve_runtime_ref(project_root, "process/checks")
    if not checks_root.is_dir():
        return {}
    projected: dict[str, str] = {}
    for result_path in sorted(checks_root.glob(f"CP[0-8]-{cr_id}-*.result.json")):
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid checkpoint result JSON: {_rel(project_root, result_path)}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                f"checkpoint result must be an object: {_rel(project_root, result_path)}"
            )
        checkpoint = str(payload.get("checkpoint") or "").upper()
        decision = str(payload.get("decision") or "").upper()
        if not re.fullmatch(r"CP[0-8]", checkpoint) or not decision:
            continue
        previous = projected.get(checkpoint)
        if previous is not None and previous != decision:
            raise ValueError(
                f"conflicting canonical checkpoint results for {cr_id} {checkpoint}: "
                f"{previous} != {decision}"
            )
        projected[checkpoint] = decision
    return projected


def _render_exact_section_rows(
    text: str,
    heading: str,
    replacements: dict[str, str],
) -> str:
    """Replace exact first-column table rows inside one optional section."""

    heading_pattern = re.compile(
        rf"^## (?:(?:\d+(?:\.\d+)*)\.?\s+)?{re.escape(heading)}$"
    )
    lines = text.splitlines(keepends=True)
    starts = [
        index
        for index, line in enumerate(lines)
        if heading_pattern.fullmatch(line.rstrip("\r\n"))
    ]
    if not starts:
        return text
    if len(starts) != 1:
        raise ValueError(f"duplicate CR body section: {heading}")
    start = starts[0] + 1
    end = next(
        (
            index
            for index in range(start, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    seen: set[str] = set()
    for index in range(start, end):
        raw = lines[index]
        line_ending = "\n" if raw.endswith("\n") else ""
        cells = [cell.strip() for cell in raw.rstrip("\r\n").split("|")]
        if len(cells) < 4 or cells[0] != "":
            continue
        key = cells[1]
        if key not in replacements:
            continue
        if key in seen:
            raise ValueError(f"duplicate CR body table row: {heading}/{key}")
        cells[2] = replacements[key]
        lines[index] = "| " + " | ".join(cells[1:-1]) + " |" + line_ending
        seen.add(key)
    return "".join(lines)


def render_status_body_projection(
    text: str,
    *,
    lifecycle_status: str,
    readiness_status: str,
    gate_status: str,
    checkpoint_results: dict[str, str] | None = None,
) -> str:
    """Project lifecycle truth into the optional CR body status tables."""

    rendered = _render_exact_section_rows(
        text,
        "CR 类型与门禁策略",
        {
            "生命周期状态": lifecycle_status,
            "就绪状态": readiness_status,
            "门禁状态": gate_status,
        },
    )
    checkpoint_projection = dict(checkpoint_results or {})
    checkpoint = _gate_checkpoint_projection(gate_status)
    if checkpoint is not None:
        checkpoint_id, checkpoint_status = checkpoint
        if checkpoint_status == "approved" or checkpoint_id not in checkpoint_projection:
            checkpoint_projection[checkpoint_id] = checkpoint_status
    if not checkpoint_projection:
        return rendered
    return _render_exact_section_rows(
        rendered,
        "Checkpoint Index",
        checkpoint_projection,
    )


def parse_inline_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_strip_scalar(item) for item in value if _strip_scalar(item)]
    raw = _strip_scalar(value)
    if not raw or raw in {"[]", "{}"}:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1].strip()
    return [item.strip().strip('"').strip("'") for item in raw.split(",") if item.strip()]


def parse_bool(value: Any) -> bool:
    raw = _strip_scalar(value).lower()
    return raw in {"true", "yes", "y", "1"}


def normalize_cr_type(value: Any) -> str:
    raw = _strip_scalar(value)
    if not raw:
        return "feature"
    return CR_TYPE_ALIASES.get(raw, raw)


def _rel(project_root: Path, path: Path) -> str:
    project_root = project_root.resolve()
    path = path.resolve(strict=False)
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        process_root = _process_root(project_root)
        try:
            relative = path.relative_to(process_root)
        except ValueError:
            raise ValueError(f"path is outside release and process repositories: {path}") from None
        return (Path("process") / relative).as_posix()


def _process_root(project_root: Path) -> Path:
    """Resolve the process root for binding projects and legacy test fixtures."""

    return _resolve_runtime_ref(project_root.resolve(), "process/PROJECT.yaml").parent.resolve(strict=False)


def _cr_id_from_path(path: Path) -> str:
    match = CR_ID_RE.search(path.name)
    return match.group(0) if match else ""


def _resolve_capability_refs(
    project_root: Path, refs: list[str], *, mode: str = "audit"
) -> dict[str, Any]:
    return feature_registry.resolve_refs(project_root, refs, kind="capability", mode=mode)


def _normalized_capability_refs(resolution: dict[str, Any]) -> list[str]:
    normalized: list[str] = []
    for result in resolution.get("results", []):
        if (
            isinstance(result, dict)
            and result.get("status") == "resolved"
            and result.get("canonical_id")
        ):
            normalized.append(str(result["canonical_id"]))
    return normalized


def _capability_blockers(resolution: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    mode = str(resolution.get("mode") or "audit")
    for result in resolution.get("results", []):
        if not isinstance(result, dict):
            continue
        status = result.get("status")
        is_blocker = status in {"unresolved", "conflict"} or (
            mode == "enforce" and status == "deprecated"
        )
        if is_blocker:
            blockers.append(
                {
                    "input_ref": result.get("input_ref", ""),
                    "status": status or "",
                    "code": result.get("code", ""),
                    "severity": result.get("severity", ""),
                    "canonical_id": result.get("canonical_id", ""),
                    "deprecated_by": result.get("deprecated_by", ""),
                    "candidates": result.get("candidates", []),
                }
            )
    return blockers


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def _impact_split_payload(record: CRRecord) -> dict[str, list[str]]:
    return {
        "impact_capability_refs": record.impact_capability_refs,
        "impact_feature_refs": record.impact_feature_refs,
        "impact_module_paths": record.impact_module_paths,
        "impact_policy_refs": record.impact_policy_refs,
        "impact_process_refs": record.impact_process_refs,
        "impact_runtime_refs": record.impact_runtime_refs,
        "impact_data_refs": record.impact_data_refs,
    }


def _categorized_legacy_impact(
    impact_surface: list[str], *, project_root: Path | None = None
) -> dict[str, list[str]]:
    derived: dict[str, list[str]] = {field: [] for field in IMPACT_SPLIT_FIELDS}
    for value in impact_surface:
        category = _legacy_impact_category(value, project_root=project_root)
        if category is not None:
            field, normalized = category
            derived[field].append(normalized)
    return {key: _unique(values) for key, values in derived.items()}


def _legacy_impact_category(
    value: str, *, project_root: Path | None = None
) -> tuple[str, str] | None:
    builtin = _builtin_legacy_impact_category(value, include_generic_module=False)
    if builtin is not None:
        return builtin
    if project_root is None:
        return _builtin_legacy_impact_category(value, include_generic_module=True)
    project_rule = _project_legacy_impact_category(project_root, value)
    if project_rule is not None:
        return project_rule
    return _builtin_legacy_impact_category(value, include_generic_module=True)


def _builtin_legacy_impact_category(
    value: str, *, include_generic_module: bool = True
) -> tuple[str, str] | None:
    lowered = value.lower()
    if value.startswith("CAP-") or lowered.startswith("capability:"):
        return "impact_capability_refs", value.split(":", 1)[-1]
    if value.startswith("FEAT-") or lowered.startswith("feature:"):
        return "impact_feature_refs", value.split(":", 1)[-1]
    if value.startswith("NO_") or value.startswith("AUTHZ-") or lowered.startswith("policy:"):
        return "impact_policy_refs", value.split(":", 1)[-1]
    if lowered.startswith("process") or lowered.startswith("workflow:"):
        return "impact_process_refs", value.split(":", 1)[-1]
    if any(marker in lowered for marker in ("runtime", "trading", "live", "publish")):
        return "impact_runtime_refs", value
    if (
        lowered.startswith("data:")
        or lowered.startswith("data/")
        or "/data" in lowered
        or "data_" in lowered
    ):
        return "impact_data_refs", value.split(":", 1)[-1]
    if include_generic_module and ("/" in value or value.endswith(".py")):
        return "impact_module_paths", value
    return None


def _project_legacy_impact_category(project_root: Path, value: str) -> tuple[str, str] | None:
    rules_path = _resolve_runtime_ref(project_root, IMPACT_SURFACE_RULES_REL.as_posix())
    if not rules_path.is_file():
        return None
    data = load_yaml_object(rules_path)
    if data.get("schema_version") != 1:
        raise ValueError(f"{IMPACT_SURFACE_RULES_REL.as_posix()} schema_version must be 1")
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError(f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules must be a list")
    for index, rule in enumerate(rules, start=1):
        field, normalized = _apply_impact_rule(rule, value, index=index)
        if field:
            return field, normalized
    return None


def _apply_impact_rule(rule: Any, value: str, *, index: int) -> tuple[str, str]:
    if not isinstance(rule, dict):
        raise ValueError(f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules[{index}] must be an object")
    target_field = str(rule.get("target_field") or "")
    if target_field not in IMPACT_SPLIT_FIELDS:
        raise ValueError(
            f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules[{index}].target_field is invalid: {target_field}"
        )
    match = str(rule.get("match") or "prefix")
    pattern = str(rule.get("pattern") or "")
    if not pattern:
        raise ValueError(
            f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules[{index}].pattern must be non-empty"
        )
    matched = False
    if match == "prefix":
        matched = value.startswith(pattern)
    elif match == "exact":
        matched = value == pattern
    elif match == "contains":
        matched = pattern in value
    elif match == "suffix":
        matched = value.endswith(pattern)
    elif match == "regex":
        try:
            matched = re.search(pattern, value) is not None
        except re.error as exc:
            raise ValueError(
                f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules[{index}].pattern invalid regex: {exc}"
            ) from exc
    else:
        raise ValueError(
            f"{IMPACT_SURFACE_RULES_REL.as_posix()} rules[{index}].match is invalid: {match}"
        )
    if not matched:
        return "", ""
    normalized = value
    if rule.get("strip_prefix") is True and value.startswith(pattern):
        normalized = value[len(pattern) :]
    if isinstance(rule.get("replacement"), str) and rule.get("replacement"):
        normalized = str(rule["replacement"])
    return target_field, normalized


def _uncategorized_legacy_impact(
    impact_surface: list[str], *, project_root: Path | None = None
) -> list[str]:
    return _unique(
        [
            value
            for value in impact_surface
            if _legacy_impact_category(value, project_root=project_root) is None
        ]
    )


def _impact_followup_candidates(
    cr_id: str, uncategorized_legacy: list[str]
) -> list[dict[str, Any]]:
    if not uncategorized_legacy:
        return []
    return [
        {
            "candidate_id": f"{cr_id}-IMPACT-UNCATEGORIZED",
            "kind": "manual-impact-classification",
            "summary": f"{cr_id}: manually classify uncategorized legacy impact_surface values",
            "input_refs": uncategorized_legacy,
            "recommended_action": "Add explicit impact_* split fields or extend classification rules in a follow-up Story.",
            "write_policy": "candidate-only",
        }
    ]


def _merge_impact_fields(
    base: dict[str, list[str]], extra: dict[str, list[str]]
) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for field in IMPACT_SPLIT_FIELDS:
        merged[field] = _unique([*base.get(field, []), *extra.get(field, [])])
    return merged


def _effective_impact_fields(
    record: CRRecord, *, project_root: Path | None = None
) -> dict[str, list[str]]:
    return _merge_impact_fields(
        _impact_split_payload(record),
        _categorized_legacy_impact(record.impact_surface, project_root=project_root),
    )


def _extract_section_lines(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            break
    if start is None:
        return []
    collected: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        stripped = line.strip()
        if stripped:
            collected.append(stripped)
    return collected


def _section_summary(text: str, heading: str, *, max_items: int = 3) -> list[str]:
    values: list[str] = []
    for line in _extract_section_lines(text, heading):
        if line.startswith("|") or line.startswith(">") or line.startswith("["):
            continue
        cleaned = line.lstrip("- ").strip()
        if cleaned:
            values.append(cleaned)
        if len(values) >= max_items:
            break
    return values


def _body_text(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def _record_required_evidence(record: CRRecord, text: str = "") -> list[str]:
    inferred = authz.infer_required_evidence_from_text(
        " ".join(
            [
                record.title,
                record.goal_statement,
                record.user_goal_impact,
                " ".join(record.impact_data_refs),
                " ".join(record.impact_runtime_refs),
                _body_text(text),
            ]
        )
    )
    return _unique([*record.required_evidence, *inferred])


def collect_scope_authz_findings(
    record: CRRecord, *, text: str = ""
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return blocking conflicts and review findings for CR scope/authz consistency."""

    required_evidence = _record_required_evidence(record, text)
    authz_caps = authz.normalize_capability_aliases(
        record.authz_policy_refs + record.not_authorized_by_approve
    )
    required_from_evidence = authz.required_capabilities_for_evidence(required_evidence)
    forbidden = set(authz_caps["forbidden"])
    allowed = set(authz_caps["allowed"])
    required_capabilities = set(record.required_capabilities)
    blockers: list[dict[str, Any]] = []
    needs_review: list[dict[str, Any]] = []

    explicit_overlap = sorted(required_capabilities.intersection(forbidden))
    if explicit_overlap:
        blockers.append(
            {
                "level": "L1",
                "code": "explicit_scope_authz_conflict",
                "required_capabilities": explicit_overlap,
                "authz_policy_refs": record.authz_policy_refs,
                "decision": "BLOCKED",
            }
        )

    direct_evidence_overlap = sorted(set(required_from_evidence["direct"]).intersection(forbidden))
    prerequisite_overlap = sorted(
        set(required_from_evidence["prerequisites"]).intersection(forbidden)
        - set(direct_evidence_overlap)
    )
    if direct_evidence_overlap:
        blockers.append(
            {
                "level": "L2",
                "code": "required_evidence_forbidden_by_authz",
                "required_evidence": required_evidence,
                "required_capabilities": direct_evidence_overlap,
                "authz_policy_refs": record.authz_policy_refs,
                "decision": "BLOCKED",
            }
        )
    if prerequisite_overlap:
        needs_review.append(
            {
                "level": "L2",
                "code": "required_evidence_prerequisite_authz_conflict",
                "required_evidence": required_evidence,
                "required_capabilities": prerequisite_overlap,
                "authz_policy_refs": record.authz_policy_refs,
                "decision": "NEEDS_REVIEW",
            }
        )

    high_risk_evidence = {"real_lake_validation", "historical_backtest", "oos_walkforward"}
    if (
        high_risk_evidence.intersection(required_evidence)
        and "real_lake_read" not in allowed
        and "real_lake_read" not in forbidden
    ):
        needs_review.append(
            {
                "level": "L3",
                "code": "high_risk_validation_authz_boundary_not_explicit",
                "required_evidence": sorted(high_risk_evidence.intersection(required_evidence)),
                "decision": "NEEDS_REVIEW",
            }
        )
    if required_from_evidence["unknown"]:
        needs_review.append(
            {
                "level": "L3",
                "code": "unknown_required_evidence_kind",
                "required_evidence": required_from_evidence["unknown"],
                "decision": "NEEDS_REVIEW",
            }
        )
    return blockers, needs_review


def _governance_dependency_values(
    record: CRRecord, *, project_root: Path | None = None
) -> list[str]:
    effective = _effective_impact_fields(record, project_root=project_root)
    values: list[str] = []
    values.extend(record.conflict_keys)
    values.extend(record.impact_surface)
    values.extend(record.authz_policy_refs)
    for field in IMPACT_SPLIT_FIELDS:
        values.extend(effective.get(field, []))
    return _unique([str(value) for value in values if str(value)])


def _governance_markers(values: list[str]) -> set[str]:
    markers: set[str] = set()
    for value in values:
        lowered = value.lower()
        for marker in GOVERNANCE_BASELINE_MARKERS:
            if marker in lowered:
                markers.add(marker)
    return markers


def _is_open_governance_baseline_cr(record: CRRecord, *, project_root: Path | None = None) -> bool:
    if record.status not in OPEN_DEPENDENCY_STATUSES or record.cr_type != "process":
        return False
    return bool(
        _governance_markers(_governance_dependency_values(record, project_root=project_root))
    )


def collect_governance_dependency_findings(
    project_root: Path,
    target: CRRecord,
) -> list[dict[str, Any]]:
    """Return warning-only findings for CRs depending on open governance baseline changes."""

    if target.status not in OPEN_DEPENDENCY_STATUSES:
        return []
    target_values = _governance_dependency_values(target, project_root=project_root)
    target_markers = _governance_markers(target_values)
    if not target_markers:
        return []
    findings: list[dict[str, Any]] = []
    for cr_id, path in discover_formal_crs(project_root).items():
        if cr_id == target.cr_id:
            continue
        other = record_from_cr_file(project_root, path)
        if not _is_open_governance_baseline_cr(other, project_root=project_root):
            continue
        other_values = _governance_dependency_values(other, project_root=project_root)
        other_markers = _governance_markers(other_values)
        marker_overlap = sorted(target_markers.intersection(other_markers))
        direct_overlap = sorted(set(target_values).intersection(other_values))
        if marker_overlap or direct_overlap:
            findings.append(
                {
                    "code": "open_governance_dependency_needs_review",
                    "decision": "NEEDS_REVIEW",
                    "blocking": False,
                    "current_cr": target.cr_id,
                    "governance_cr": other.cr_id,
                    "governance_ref": other.full_ref,
                    "marker_overlap": marker_overlap,
                    "direct_overlap": direct_overlap,
                    "reason": "open governance baseline CR may change policy/authz/roadmap/process-state assumptions",
                }
            )
    return findings


def classify_cp1_review_profile(record: CRRecord) -> dict[str, Any]:
    """Classify how much CP1 use-case completeness review the CR needs."""

    product_doc_values = [value.lower() for value in record.affected_product_docs]
    impact_values = [
        value.lower()
        for value in record.impact_surface + record.impact_process_refs + record.impact_module_paths
    ]
    product_baseline_touched = record.product_baseline_refresh_required or any(
        any(marker in value for marker in CP1_PRODUCT_BASELINE_DOCS)
        for value in [*product_doc_values, *impact_values]
    )
    if product_baseline_touched:
        return {
            "profile": "full",
            "decision": "FULL_CP1_REQUIRED",
            "required_checks": list(CP1_FULL_REQUIRED_CHECKS),
            "reason": "product baseline docs or product_baseline_refresh_required indicate use-case completeness must be rechecked",
        }
    if record.affected_use_cases:
        return {
            "profile": "lightweight_existing_use_case_extension",
            "decision": "LIGHTWEIGHT_CP1",
            "required_checks": list(CP1_LIGHTWEIGHT_REQUIRED_CHECKS),
            "affected_use_cases": record.affected_use_cases,
            "reason": "CR extends existing use-case refs without refreshing the product baseline",
        }
    if record.cr_type in {"process", "refactor", "bugfix", "docs", "runtime", "release"}:
        return {
            "profile": "not_applicable",
            "decision": "CP1_NOT_REQUIRED",
            "required_checks": ["cr_tracking", "impact_surface"],
            "reason": "CR type does not change user scenarios or product baseline by default",
        }
    return {
        "profile": "standard",
        "decision": "STANDARD_CP1_REVIEW",
        "required_checks": list(CP1_FULL_REQUIRED_CHECKS),
        "reason": "CR may affect product behavior but does not provide enough evidence for lightweight CP1",
    }


def _archive_backup_refs(record: CRRecord, *, project_root: Path | None = None) -> list[str]:
    effective = _effective_impact_fields(record, project_root=project_root)
    values: list[str] = []
    values.extend(record.impact_surface)
    for field in (
        "impact_module_paths",
        "impact_process_refs",
        "impact_data_refs",
    ):
        values.extend(effective.get(field, []))
    refs: list[str] = []
    for value in values:
        normalized = str(value).strip().replace("\\", "/")
        lowered = normalized.lower()
        if any(marker in lowered for marker in ARCHIVE_BACKUP_PATH_MARKERS):
            refs.append(normalized)
    return _unique(refs)


def _is_housekeeping_cr(record: CRRecord) -> bool:
    values = [record.title, record.cr_type, *record.conflict_keys, *record.impact_surface]
    lowered = " ".join(str(value).lower() for value in values if str(value))
    return record.cr_type == "process" and any(
        marker in lowered for marker in HOUSEKEEPING_CR_MARKERS
    )


def collect_archive_isolation_findings(
    record: CRRecord,
    *,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return warning-only findings for archive/backups paths mixed into business CR scope."""

    if record.status not in OPEN_DEPENDENCY_STATUSES:
        return []
    archive_refs = _archive_backup_refs(record, project_root=project_root)
    if not archive_refs or _is_housekeeping_cr(record):
        return []
    return [
        {
            "code": "archive_backup_scope_needs_isolation",
            "decision": "NEEDS_REVIEW",
            "blocking": False,
            "current_cr": record.cr_id,
            "archive_refs": archive_refs,
            "reason": "archive/backups paths should be isolated in housekeeping CRs or explicitly justified",
        }
    ]


def _first_section_summary(text: str, heading: str) -> str:
    values = _section_summary(text, heading, max_items=1)
    return values[0] if values else ""


def discover_formal_crs(project_root: Path) -> dict[str, Path]:
    root = _resolve_runtime_ref(project_root, "process/changes")
    if not root.is_dir():
        return {}
    crs: dict[str, Path] = {}
    for path in sorted(root.glob("CR-*.md")):
        if "FOLLOW-UP" in path.name:
            continue
        cr_id = _cr_id_from_path(path)
        if cr_id:
            if cr_id in crs:
                raise ValueError(
                    f"duplicate formal CR id {cr_id}: {_rel(project_root, crs[cr_id])}, {_rel(project_root, path)}"
                )
            crs[cr_id] = path
    return crs


def record_from_cr_file(project_root: Path, path: Path) -> CRRecord:
    text = path.read_text(encoding="utf-8")
    fields = parse_frontmatter(text)
    cr_id = fields.get("cr_id") or _cr_id_from_path(path)
    if not cr_id:
        raise ValueError(f"无法从 CR 文件识别 cr_id: {path}")
    status = fields.get("lifecycle_status") or fields.get("status") or "active"
    if status == "open":
        status = "active"
    summary_ref = (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()
    impact_capability_refs = parse_inline_list(fields.get("impact_capability_refs", ""))
    capability_resolution = _resolve_capability_refs(
        project_root, impact_capability_refs, mode="audit"
    )
    return CRRecord(
        cr_id=cr_id,
        cr_type=normalize_cr_type(fields.get("cr_type") or fields.get("cr_kind") or "feature"),
        title=fields.get("title") or path.stem,
        status=status,
        readiness=fields.get("readiness_status") or "not_ready",
        gate_status=fields.get("gate_status") or "not_started",
        gate_profile=fields.get("gate_profile") or "",
        full_ref=_rel(project_root, path),
        summary_ref=summary_ref,
        conflict_keys=parse_inline_list(fields.get("conflict_keys", "")),
        impact_surface=parse_inline_list(fields.get("impact_surface", "")),
        impact_capability_refs=impact_capability_refs,
        impact_feature_refs=parse_inline_list(fields.get("impact_feature_refs", "")),
        impact_module_paths=parse_inline_list(fields.get("impact_module_paths", "")),
        impact_policy_refs=parse_inline_list(fields.get("impact_policy_refs", "")),
        impact_process_refs=parse_inline_list(fields.get("impact_process_refs", "")),
        impact_runtime_refs=parse_inline_list(fields.get("impact_runtime_refs", "")),
        impact_data_refs=parse_inline_list(fields.get("impact_data_refs", "")),
        impact_capability_resolution=capability_resolution,
        authz_policy_refs=parse_inline_list(fields.get("authz_policy_refs", "")),
        risk_refs=parse_inline_list(fields.get("risk_refs", "")),
        goal_ref=fields.get("goal_ref", ""),
        goal_statement=fields.get("goal_statement", ""),
        user_goal_impact=fields.get("user_goal_impact", ""),
        split_rationale=fields.get("split_rationale", ""),
        why_not_merge_with_parent=fields.get("why_not_merge_with_parent", ""),
        why_not_story_or_task=fields.get("why_not_story_or_task", ""),
        approval_focus=fields.get("approval_focus", ""),
        decision_burden=fields.get("decision_burden", ""),
        approve_effect=fields.get("approve_effect", ""),
        reject_effect=fields.get("reject_effect", ""),
        not_authorized_by_approve=parse_inline_list(fields.get("not_authorized_by_approve", "")),
        product_baseline_refresh_required=parse_bool(
            fields.get("product_baseline_refresh_required", "")
        ),
        required_phase=fields.get("required_phase", ""),
        required_agent=fields.get("required_agent", ""),
        required_gate=fields.get("required_gate", ""),
        block_story_decomposition_until=fields.get("block_story_decomposition_until", ""),
        affected_product_docs=parse_inline_list(fields.get("affected_product_docs", "")),
        affected_use_cases=parse_inline_list(fields.get("affected_use_cases", "")),
        routing_design_ref=fields.get("routing_design_ref", ""),
        required_evidence=parse_inline_list(fields.get("required_evidence", "")),
        required_capabilities=parse_inline_list(fields.get("required_capabilities", "")),
    )


def summary_from_cr_file(
    project_root: Path, path: Path, *, readiness: str | None = None
) -> dict[str, Any]:
    record = record_from_cr_file(project_root, path)
    text = path.read_text(encoding="utf-8")
    summary = {
        "id": record.cr_id,
        "cr_type": record.cr_type,
        "title": record.title,
        "status": record.status,
        "readiness": readiness or record.readiness,
        "gate_status": record.gate_status,
        "gate_profile": record.gate_profile,
        "decision": "pending",
        "scope_summary": _section_summary(text, "## 变更描述") or [record.title],
        "impact_surface": record.impact_surface,
        **_impact_split_payload(record),
        "impact_capability_resolution": record.impact_capability_resolution,
        "impact_capability_normalized": _normalized_capability_refs(
            record.impact_capability_resolution
        ),
        "conflict_keys": record.conflict_keys,
        "remaining_risks": record.risk_refs,
        "followup_candidates": [],
        "authz_policy_refs": record.authz_policy_refs,
        "goal_ref": record.goal_ref,
        "goal_statement": record.goal_statement or _first_section_summary(text, "## 目标影响摘要"),
        "user_goal_impact": record.user_goal_impact,
        "split_rationale": record.split_rationale or _first_section_summary(text, "## 拆分理由"),
        "why_not_merge_with_parent": record.why_not_merge_with_parent,
        "why_not_story_or_task": record.why_not_story_or_task,
        "approval_focus": record.approval_focus,
        "decision_burden": record.decision_burden,
        "approve_effect": record.approve_effect or _first_section_summary(text, "## approve 后果"),
        "reject_effect": record.reject_effect,
        "not_authorized_by_approve": record.not_authorized_by_approve
        or _section_summary(text, "## 不授权范围"),
        "product_baseline_refresh_required": record.product_baseline_refresh_required,
        "required_phase": record.required_phase,
        "required_agent": record.required_agent,
        "required_gate": record.required_gate,
        "block_story_decomposition_until": record.block_story_decomposition_until,
        "affected_product_docs": record.affected_product_docs,
        "affected_use_cases": record.affected_use_cases,
        "routing_design_ref": record.routing_design_ref,
        "required_evidence": _record_required_evidence(record, text),
        "required_capabilities": record.required_capabilities,
        "full_ref": record.full_ref,
        "evidence_index_ref": (
            CR_ARCHIVE_ROOT_REL / record.cr_id / "evidence-index.json"
        ).as_posix(),
        "updated_at": now_utc(),
    }
    blockers, needs_review = collect_scope_authz_findings(record, text=text)
    summary["scope_authz_consistency"] = {
        "decision": "BLOCKED" if blockers else "NEEDS_REVIEW" if needs_review else "PASS",
        "blockers": blockers,
        "needs_review": needs_review,
    }
    governance_findings = collect_governance_dependency_findings(project_root, record)
    summary["governance_dependency_review"] = {
        "decision": "NEEDS_REVIEW" if governance_findings else "PASS",
        "findings": governance_findings,
    }
    archive_findings = collect_archive_isolation_findings(record, project_root=project_root)
    summary["cp1_review_profile"] = classify_cp1_review_profile(record)
    summary["archive_isolation_review"] = {
        "decision": "NEEDS_REVIEW" if archive_findings else "PASS",
        "findings": archive_findings,
    }
    return summary


def write_summary(project_root: Path, cr_id: str, summary: dict[str, Any]) -> Path:
    path = _resolve_runtime_ref(project_root, CR_SUMMARY_ROOT_REL.as_posix()) / f"{cr_id}.summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # CR summaries are hot/warm routing objects with a 4 KiB budget.  Compact
    # JSON preserves the schema while avoiding formatting-only budget drift.
    path.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def write_evidence_index(project_root: Path, cr_id: str, summary: dict[str, Any]) -> Path:
    path = _resolve_runtime_ref(project_root, CR_ARCHIVE_ROOT_REL.as_posix()) / cr_id / "evidence-index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cr_id": cr_id,
        "summary_ref": (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix(),
        "full_ref": summary.get("full_ref"),
        "evidence_refs": [],
        "created_at": now_utc(),
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def append_ledger_event(project_root: Path, event: dict[str, Any]) -> Path:
    path = _resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_ledger_events(project_root: Path) -> list[dict[str, Any]]:
    path = _resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix())
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} invalid JSON: {exc}") from exc
    return events


def project_native_cr_status(
    project_root: Path,
    *,
    cr_id: str,
) -> NativeCRStatusProjectionV1:
    """交叉验证 formal CR、summary、index 和 append-only ledger 的状态。

    publisher 等下游只能消费这个投影，不再各自解释 frontmatter。
    """

    findings: list[str] = []
    formal_crs = discover_formal_crs(project_root)
    formal_path = formal_crs.get(cr_id)
    if formal_path is None:
        return NativeCRStatusProjectionV1(
            cr_id=cr_id,
            lifecycle_status="",
            readiness_status="",
            gate_status="",
            formal_cr_ref="",
            summary_ref="",
            ledger_event_id="",
            decision="BLOCKED",
            findings=("FORMAL_CR_MISSING",),
        )
    record = record_from_cr_file(project_root, formal_path)
    formal_ref = record.full_ref
    summary_ref = record.summary_ref
    formal_tuple = (
        cr_tracking.normalize_lifecycle_status(record.status),
        cr_tracking.normalize_readiness_status(record.readiness),
        cr_tracking.normalize_gate_status(record.gate_status),
    )
    if cr_tracking.validate_native_status_tuple(*formal_tuple):
        findings.append("FORMAL_CR_STATUS_TUPLE_INVALID")

    index = load_index(project_root)
    index_items = index.get("items") if isinstance(index, dict) else None
    index_item = next(
        (
            item
            for item in index_items or []
            if isinstance(item, dict) and str(item.get("id") or "") == cr_id
        ),
        None,
    )
    if index_item is None:
        findings.append("CR_INDEX_ITEM_MISSING")
    else:
        index_tuple = (
            cr_tracking.normalize_lifecycle_status(
                str(index_item.get("lifecycle_status") or ""),
                fallback_status=str(index_item.get("status") or ""),
            ),
            cr_tracking.normalize_readiness_status(
                str(
                    index_item.get("readiness_status")
                    or index_item.get("readiness")
                    or ""
                )
            ),
            cr_tracking.normalize_gate_status(
                str(index_item.get("gate_status") or "")
            ),
        )
        if index_tuple != formal_tuple:
            findings.append("CR_INDEX_STATUS_DIVERGED")
        if str(
            index_item.get("full_ref")
            or index_item.get("formal_cr_path")
            or ""
        ) != formal_ref:
            findings.append("CR_INDEX_FORMAL_REF_DIVERGED")
        if str(index_item.get("summary_ref") or "") != summary_ref:
            findings.append("CR_INDEX_SUMMARY_REF_DIVERGED")

    summary_path = _resolve_runtime_ref(project_root, summary_ref)
    summary: dict[str, Any] = {}
    if not summary_path.is_file():
        findings.append("CR_SUMMARY_MISSING")
    else:
        try:
            loaded_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            findings.append("CR_SUMMARY_INVALID_JSON")
        else:
            if not isinstance(loaded_summary, dict):
                findings.append("CR_SUMMARY_INVALID_SHAPE")
            else:
                summary = loaded_summary
    if summary:
        summary_tuple = (
            cr_tracking.normalize_lifecycle_status(
                str(summary.get("status") or "")
            ),
            cr_tracking.normalize_readiness_status(
                str(summary.get("readiness") or "")
            ),
            cr_tracking.normalize_gate_status(
                str(summary.get("gate_status") or "")
            ),
        )
        if str(summary.get("id") or "") != cr_id:
            findings.append("CR_SUMMARY_ID_DIVERGED")
        if str(summary.get("full_ref") or "") != formal_ref:
            findings.append("CR_SUMMARY_FORMAL_REF_DIVERGED")
        if summary_tuple != formal_tuple:
            findings.append("CR_SUMMARY_STATUS_DIVERGED")

    ledger_events = [
        event
        for event in load_ledger_events(project_root)
        if str(event.get("id") or event.get("cr_id") or "") == cr_id
        and all(
            key in event
            for key in ("status", "readiness", "gate_status")
        )
    ]
    ledger_event = ledger_events[-1] if ledger_events else None
    ledger_event_id = ""
    if ledger_event is None:
        findings.append("CR_LEDGER_STATUS_EVENT_MISSING")
    else:
        ledger_event_id = str(ledger_event.get("event_id") or "")
        ledger_tuple = (
            cr_tracking.normalize_lifecycle_status(
                str(ledger_event.get("status") or "")
            ),
            cr_tracking.normalize_readiness_status(
                str(ledger_event.get("readiness") or "")
            ),
            cr_tracking.normalize_gate_status(
                str(ledger_event.get("gate_status") or "")
            ),
        )
        if not ledger_event_id:
            findings.append("CR_LEDGER_EVENT_ID_MISSING")
        if str(ledger_event.get("full_ref") or "") != formal_ref:
            findings.append("CR_LEDGER_FORMAL_REF_DIVERGED")
        if str(ledger_event.get("summary_ref") or "") != summary_ref:
            findings.append("CR_LEDGER_SUMMARY_REF_DIVERGED")
        if ledger_tuple != formal_tuple:
            findings.append("CR_LEDGER_STATUS_DIVERGED")

    return NativeCRStatusProjectionV1(
        cr_id=cr_id,
        lifecycle_status=formal_tuple[0],
        readiness_status=formal_tuple[1],
        gate_status=formal_tuple[2],
        formal_cr_ref=formal_ref,
        summary_ref=summary_ref,
        ledger_event_id=ledger_event_id,
        decision="PASS" if not findings else "BLOCKED",
        findings=tuple(findings),
    )


def _cr_numeric_sort_key(cr_id: str) -> tuple[int, str]:
    match = re.fullmatch(r"CR-(\d+)", cr_id)
    return (int(match.group(1)), cr_id) if match else (sys.maxsize, cr_id)


def _canonical_digest(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _index_item(record: CRRecord, text: str) -> dict[str, Any]:
    return {
        "id": record.cr_id,
        "cr_type": record.cr_type,
        "title": record.title,
        "status": record.status,
        "lifecycle_status": record.status,
        "readiness": record.readiness,
        "readiness_status": record.readiness,
        "gate_status": record.gate_status,
        "gate_profile": record.gate_profile,
        "full_ref": record.full_ref,
        "formal_cr_path": record.full_ref,
        # summary 是派生对象；引用只由 CR ID 决定，index 构建不读取 summary 内容或存在性。
        "summary_ref": record.summary_ref,
        "goal_ref": record.goal_ref,
        "goal_statement": record.goal_statement,
        "approval_focus": record.approval_focus,
        "decision_burden": record.decision_burden,
        "conflict_keys": record.conflict_keys,
        "impact_surface": record.impact_surface,
        **_impact_split_payload(record),
        "impact_capability_resolution": record.impact_capability_resolution,
        "impact_capability_normalized": _normalized_capability_refs(
            record.impact_capability_resolution
        ),
        "authz_policy_refs": record.authz_policy_refs,
        "risk_refs": record.risk_refs,
        "product_baseline_refresh_required": record.product_baseline_refresh_required,
        "required_phase": record.required_phase,
        "required_agent": record.required_agent,
        "required_gate": record.required_gate,
        "block_story_decomposition_until": record.block_story_decomposition_until,
        "affected_product_docs": record.affected_product_docs,
        "affected_use_cases": record.affected_use_cases,
        "routing_design_ref": record.routing_design_ref,
        "required_evidence": _record_required_evidence(record, text),
        "required_capabilities": record.required_capabilities,
    }


def _record_override(record: CRRecord, updates: dict[str, str]) -> CRRecord:
    fields: dict[str, str] = {}
    if updates.get("lifecycle_status"):
        fields["status"] = updates["lifecycle_status"]
    if updates.get("readiness_status"):
        fields["readiness"] = updates["readiness_status"]
    if updates.get("gate_status"):
        fields["gate_status"] = updates["gate_status"]
    return replace(record, **fields) if fields else record


def _native_cr_minimum(project_root: Path) -> int:
    """Return the project-specific first native CR number.

    Fresh projects default to CR-001.  A migrated project may declare its
    explicit legacy/native boundary in LEGACY-SOURCE.yaml; no project-specific
    number is hard-coded into the reusable builder.
    """

    path = _resolve_runtime_ref(project_root, LEGACY_SOURCE_REL.as_posix())
    if not path.is_file():
        return 1
    payload = load_yaml_object(path)
    value = str(payload.get("native_cr_minimum") or "CR-001")
    match = re.fullmatch(r"CR-(\d+)", value)
    if match is None:
        raise ValueError(
            f"{LEGACY_SOURCE_REL.as_posix()} native_cr_minimum must use CR-nnn naming"
        )
    return int(match.group(1))


def _validate_native_formal_cr(
    project_root: Path,
    cr_id: str,
    path: Path,
    *,
    minimum: int,
) -> None:
    fields = parse_frontmatter(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if str(fields.get("schema_version") or "") != "1":
        problems.append("schema_version=1 is required")
    if str(fields.get("kind") or "") != "cr":
        problems.append("kind=cr is required")
    if str(fields.get("cr_id") or "") != cr_id:
        problems.append("frontmatter cr_id must exactly match the filename CR id")
    numeric = _cr_numeric_sort_key(cr_id)[0]
    if numeric < minimum:
        problems.append(f"CR number is earlier than native_cr_minimum=CR-{minimum:03d}")
    if problems:
        raise ValueError(
            f"non-native formal CR contamination at {_rel(project_root, path)}: "
            + "; ".join(problems)
        )


def build_index(
    project_root: Path,
    *,
    record_overrides: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a pure projection from formal CR files only.

    Existing CR-INDEX bytes, summaries, ledgers and legacy repositories are
    deliberately not inputs.  ``record_overrides`` is used only by a
    status-sync plan to project its not-yet-applied formal truth.
    """

    project_root = project_root.resolve()
    items: list[dict[str, Any]] = []
    formal_crs = discover_formal_crs(project_root)
    minimum = _native_cr_minimum(project_root)
    overrides = record_overrides or {}
    for cr_id, path in formal_crs.items():
        _validate_native_formal_cr(project_root, cr_id, path, minimum=minimum)
        record = record_from_cr_file(project_root, path)
        record = _record_override(record, overrides.get(cr_id, {}))
        items.append(_index_item(record, path.read_text(encoding="utf-8")))
    items.sort(key=lambda item: _cr_numeric_sort_key(str(item["id"])))
    semantic = {"schema_version": INDEX_SCHEMA_VERSION, "items": items}
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": now_utc(),
        "semantic_digest": _canonical_digest(semantic),
        "items": items,
    }


def validate_index_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["CR-INDEX must be a JSON object"]
    if payload.get("schema_version") != INDEX_SCHEMA_VERSION:
        errors.append(f"schema_version must be {INDEX_SCHEMA_VERSION}")
    if not isinstance(payload.get("generated_at"), str) or not payload.get("generated_at"):
        errors.append("generated_at must be a non-empty string")
    items = payload.get("items")
    if not isinstance(items, list):
        return [*errors, "items must be a list"]
    required = {
        "id",
        "cr_type",
        "title",
        "lifecycle_status",
        "readiness_status",
        "gate_status",
        "formal_cr_path",
        "summary_ref",
    }
    ids: list[str] = []
    for offset, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append(f"items[{offset}] must be an object")
            continue
        missing = sorted(required - set(item))
        if missing:
            errors.append(f"items[{offset}] missing fields: {','.join(missing)}")
        item_id = str(item.get("id") or "")
        if not re.fullmatch(r"CR-\d+", item_id):
            errors.append(f"items[{offset}].id is invalid: {item_id}")
        ids.append(item_id)
        for key in ("formal_cr_path", "summary_ref"):
            value = str(item.get(key) or "")
            if not value.startswith("process/") or Path(value).is_absolute() or ".." in Path(value).parts:
                errors.append(f"items[{offset}].{key} must be one safe process/ logical ref")
    if len(ids) != len(set(ids)):
        errors.append("items contain duplicate CR IDs")
    if ids != sorted(ids, key=_cr_numeric_sort_key):
        errors.append("items must be ordered by numeric CR ID")
    expected_digest = _canonical_digest(
        {"schema_version": payload.get("schema_version"), "items": items}
    )
    if payload.get("semantic_digest") != expected_digest:
        errors.append("semantic_digest does not match schema_version + items")
    return errors


def plan_index(project_root: Path, *, rebuild_corrupt: bool = False) -> dict[str, Any]:
    project_root = project_root.resolve()
    path = _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    try:
        expected = build_index(project_root)
    except ValueError as exc:
        return {
            "decision": "BLOCKED",
            "action": "none",
            "mutation_count": 0,
            "reason": str(exc),
            "index_ref": CR_INDEX_REL.as_posix(),
        }
    expected_digest = str(expected["semantic_digest"])
    if not path.is_file():
        return {
            "decision": "READY",
            "action": "create",
            "mutation_count": 1,
            "semantic_digest": expected_digest,
            "index_ref": CR_INDEX_REL.as_posix(),
            "expected": expected,
        }
    before_text = path.read_text(encoding="utf-8")
    before_digest = hashlib.sha256(before_text.encode("utf-8")).hexdigest()
    try:
        existing = json.loads(before_text)
    except json.JSONDecodeError as exc:
        if not rebuild_corrupt:
            return {
                "decision": "BLOCKED",
                "action": "none",
                "mutation_count": 0,
                "reason": f"CR-INDEX invalid JSON; use explicit --rebuild: {exc}",
                "before_bytes_digest": before_digest,
                "index_ref": CR_INDEX_REL.as_posix(),
            }
        existing = None
    existing_errors = validate_index_payload(existing) if existing is not None else []
    if existing_errors and not rebuild_corrupt:
        return {
            "decision": "BLOCKED",
            "action": "none",
            "mutation_count": 0,
            "reason": "; ".join(existing_errors),
            "before_bytes_digest": before_digest,
            "index_ref": CR_INDEX_REL.as_posix(),
        }
    if isinstance(existing, dict) and existing.get("semantic_digest") == expected_digest:
        return {
            "decision": "READY",
            "action": "noop",
            "mutation_count": 0,
            "semantic_digest": expected_digest,
            "before_bytes_digest": before_digest,
            "index_ref": CR_INDEX_REL.as_posix(),
            "expected": expected,
        }
    if not rebuild_corrupt:
        return {
            "decision": "BLOCKED",
            "action": "none",
            "mutation_count": 0,
            "reason": "CR-INDEX stale projection differs from formal truth; use explicit --rebuild",
            "semantic_digest": expected_digest,
            "existing_semantic_digest": (
                str(existing.get("semantic_digest") or "") if isinstance(existing, dict) else ""
            ),
            "before_bytes_digest": before_digest,
            "index_ref": CR_INDEX_REL.as_posix(),
        }
    return {
        "decision": "READY",
        "action": "rebuild",
        "mutation_count": 1,
        "semantic_digest": expected_digest,
        "before_bytes_digest": before_digest,
        "index_ref": CR_INDEX_REL.as_posix(),
        "expected": expected,
    }


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    target_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(target_mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_index(
    project_root: Path,
    *,
    rebuild_corrupt: bool = False,
    expected_process_oid: str = "",
) -> Path:
    project_root = project_root.resolve()
    path = _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    plan = plan_index(project_root, rebuild_corrupt=rebuild_corrupt)
    if plan["decision"] != "READY":
        raise ValueError(str(plan.get("reason") or "CR-INDEX plan is blocked"))
    if expected_process_oid:
        process_root = _process_root(project_root)
        actual = run_git(["rev-parse", "--verify", "HEAD"], cwd=process_root)
        if not actual.ok or actual.stdout.strip() != expected_process_oid:
            raise ValueError("process HEAD differs from expected_process_oid")
    if plan["mutation_count"]:
        text = json.dumps(plan["expected"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        _atomic_write_text(path, text)
    return path


def load_index(project_root: Path) -> dict[str, Any]:
    path = _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} invalid JSON: {exc}") from exc


def _write_bootstrap_cr_file(
    project_root: Path,
    *,
    cr_id: str,
    title: str,
    scope: str,
    gate_status: str,
    readiness: str,
) -> Path:
    if not re.fullmatch(r"CR-\d{3,}", cr_id):
        raise ValueError("bootstrap CR id must use CR-xxx naming, for example CR-001")
    path = _resolve_runtime_ref(project_root, f"process/changes/{cr_id}.md")
    if path.exists():
        raise FileExistsError(f"CR already exists: {path}")
    created_at = now_utc()
    text = f"""---
schema_version: 1
kind: cr
cr_id: "{cr_id}"
cr_type: "process"
title: "{title}"
lifecycle_status: "active"
readiness_status: "{readiness}"
gate_status: "{gate_status}"
gate_profile: "standard"
conflict_keys: ["bootstrap", "adoption-readiness"]
impact_surface: ["process", "workspace", "state", "context", "human-gate"]
authz_policy_refs: ["NO_CREDENTIAL_READ", "NO_RUNTIME", "NO_PRODUCTION_WRITE", "NO_TRADING"]
risk_refs: []
created_at: "{created_at}"
created_by: "meta-flow cr bootstrap"
---

# {cr_id} {title}

## 变更描述

{scope}

## 不授权范围

- credentials / secret / account read
- runtime / SaaS / production write
- trading / live / publish
- CR-033 runtime trace follow-up activation

## 启动约束

- Formal CR IDs must use `CR-xxx`; `MF-xxx` is historical alias only.
- Business remediation starts only after CP0/context/human gate readiness is reviewed.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _update_current_active_change(project_root: Path, cr_id: str, context_ref: str) -> None:
    current.update_current_state(
        project_root,
        {
            "active_change": cr_id,
            "active_context_ref": context_ref,
            "current_phase": "init",
            "next_action": {
                "type": "cp0_ready",
                "text": f"Review CP0 bootstrap readiness for {cr_id}, then launch the first human gate.",
            },
            "updated_at": now_utc(),
        },
        actor="meta_flow.workflow.cr_lifecycle",
        reason="bootstrap active change",
    )


def _write_cp0_result(project_root: Path, cr_id: str, context_ref: str) -> Path:
    result_path = _resolve_runtime_ref(
        project_root, f"process/checks/CP0-{cr_id}-BOOTSTRAP.result.json"
    )
    result = {
        "schema_version": 1,
        "checkpoint": "CP0",
        "cr_id": cr_id,
        "decision": "PASS",
        "context_ref": context_ref,
        "evidence_ref": "",
        "dispatch_refs": [],
        "items": [
            {
                "id": "CP0-BS-01",
                "name": "workspace/state/bootstrap artifacts exist",
                "status": "PASS",
                "severity": "INFO",
                "evidence_refs": [
                    "process/state/STATE.current.json",
                    "process/changes/CR-INDEX.json",
                    context_ref,
                ],
            },
            {
                "id": "CP0-BS-02",
                "name": "runtime and credential actions are not authorized",
                "status": "PASS",
                "severity": "INFO",
                "evidence_refs": [(CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()],
            },
        ],
        "blockers": [],
        "waivers": [],
        "next_route": "human_gate",
        "checked_at": now_utc(),
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result_path


def bootstrap_cr(
    project_root: Path,
    *,
    cr_id: str,
    title: str,
    scope: str,
    gate_status: str = "cp2_pending",
    readiness: str = "READY",
) -> dict[str, Path]:
    project_root = project_root.resolve()
    from meta_flow.context_pack import builder
    from meta_flow.policies import failure_routing

    failure_routing.write_default_failure_routing_policy(project_root)
    failure_routing.write_default_waiver_policy(project_root)
    cr_path = _write_bootstrap_cr_file(
        project_root,
        cr_id=cr_id,
        title=title,
        scope=scope,
        gate_status=gate_status,
        readiness=readiness,
    )
    summary = summary_from_cr_file(project_root, cr_path)
    summary_path = write_summary(project_root, cr_id, summary)
    evidence_path = write_evidence_index(project_root, cr_id, summary)
    index_path = write_index(project_root)
    context, context_path = builder.build_context_pack(
        project_root,
        stage="CP0",
        profile="adoption-bootstrap",
        cr_id=cr_id,
    )
    context_ref = _rel(project_root, context_path)
    _update_current_active_change(project_root, cr_id, context_ref)
    try:
        current.render_state_file(project_root, force=False)
    except FileExistsError:
        pass
    cp0_result_path = _write_cp0_result(project_root, cr_id, context_ref)
    cp0_summary_path = cp0_result_path.with_suffix(".summary.md")
    from meta_flow.checks import cp_result

    cp0_summary_path.write_text(
        cp_result.render_summary(json.loads(cp0_result_path.read_text(encoding="utf-8"))),
        encoding="utf-8",
    )
    ledger_path = append_ledger_event(
        project_root,
        {
            "event": "active",
            "id": cr_id,
            "cr_type": summary.get("cr_type"),
            "status": "active",
            "readiness": summary.get("readiness"),
            "summary_ref": _rel(project_root, summary_path),
            "full_ref": summary.get("full_ref"),
            "evidence_index_ref": _rel(project_root, evidence_path),
            "context_ref": context_ref,
            "cp0_result_ref": _rel(project_root, cp0_result_path),
            "created_at": now_utc(),
        },
    )
    return {
        "cr": cr_path,
        "summary": summary_path,
        "evidence_index": evidence_path,
        "index": index_path,
        "context": context_path,
        "cp0_result": cp0_result_path,
        "cp0_summary": cp0_summary_path,
        "ledger": ledger_path,
    }


def close_cr(
    project_root: Path,
    cr_id: str,
    *,
    readiness: str,
    work_id: str,
    effective_at: str,
    expected_process_oid: str,
    expected_plan_digest: str,
    authorization: StatusSyncAuthorization | None,
) -> dict[str, Path]:
    """Compatibility API routed through the typed status-sync transaction."""

    plan = plan_status_sync(
        project_root,
        cr_id,
        status="closed",
        readiness=readiness,
        gate_status=CLOSED_GATE_STATUS,
        work_id=work_id,
        expected_process_oid=expected_process_oid,
        effective_at=effective_at,
    )
    result = apply_status_sync(
        project_root,
        plan,
        authorization=authorization,
        expected_plan_digest=expected_plan_digest,
    )
    if result["status"] not in {"PASS", "NO_CHANGE"}:
        raise RuntimeError(f"close {result['status']}: {result.get('reason', '')}")
    if result["status"] == "NO_CHANGE":
        cr_path = discover_formal_crs(project_root)[cr_id]
        return {
            "cr": cr_path,
            "summary": _resolve_runtime_ref(
                project_root,
                (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix(),
            ),
            "evidence_index": _resolve_runtime_ref(
                project_root,
                (CR_ARCHIVE_ROOT_REL / cr_id / "evidence-index.json").as_posix(),
            ),
            "index": _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix()),
            "ledger": _resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix()),
        }
    by_ref = result["paths"]
    return {
        "cr": by_ref[_rel(project_root, discover_formal_crs(project_root)[cr_id])],
        "summary": by_ref[
            (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()
        ],
        "evidence_index": by_ref[
            (CR_ARCHIVE_ROOT_REL / cr_id / "evidence-index.json").as_posix()
        ],
        "index": by_ref[CR_INDEX_REL.as_posix()],
        "ledger": by_ref[CR_LEDGER_REL.as_posix()],
    }


@dataclass(frozen=True)
class StatusSyncTarget:
    order: int
    ref: str
    path: Path
    truth_or_derived: str
    before: str | None
    after: str

    @property
    def before_digest(self) -> str:
        return _canonical_digest(self.before) if self.before is not None else _canonical_digest("")

    @property
    def after_digest(self) -> str:
        return _canonical_digest(self.after)

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "ref": self.ref,
            "truth_or_derived": self.truth_or_derived,
            "before_exists": self.before is not None,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
        }


@dataclass(frozen=True)
class StatusSyncAuthorization:
    schema_version: int
    authorization_id: str
    authorization_source: str
    authorization_kind: str
    operation: str
    cr_id: str
    work_id: str
    desired_transition: dict[str, str]
    effective_at: str
    expected_release_oid: str
    expected_process_oid: str
    scope_digest: str
    targets: list[dict[str, Any]]
    plan_digest: str
    expires_at: str
    single_use: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StatusSyncAuthorization:
        if set(payload) != STATUS_SYNC_AUTHORIZATION_FIELDS:
            missing = sorted(STATUS_SYNC_AUTHORIZATION_FIELDS - set(payload))
            extra = sorted(set(payload) - STATUS_SYNC_AUTHORIZATION_FIELDS)
            raise ValueError(
                "status-sync authorization fields mismatch: "
                f"missing={missing}, extra={extra}"
            )
        return cls(**payload)


@dataclass(frozen=True)
class StatusSyncPlan:
    decision: str
    cr_id: str
    work_id: str
    desired_transition: dict[str, str]
    expected_facts: dict[str, str]
    scope_digest: str
    targets: tuple[StatusSyncTarget, ...]
    reason: str = ""
    effective_at: str = ""

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "operation": STATUS_SYNC_OPERATION,
            "decision": self.decision,
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "desired_transition": self.desired_transition,
            "effective_at": self.effective_at,
            "expected_facts": self.expected_facts,
            "scope_digest": self.scope_digest,
            "targets": [target.as_dict() for target in self.targets],
            "reason": self.reason,
        }

    @property
    def plan_digest(self) -> str:
        return _canonical_digest(self._digest_payload())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "operation": STATUS_SYNC_OPERATION,
            "decision": self.decision,
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "desired_transition": self.desired_transition,
            "effective_at": self.effective_at,
            "expected_facts": self.expected_facts,
            "scope_digest": self.scope_digest,
            "targets": [target.as_dict() for target in self.targets],
            "mutation_allowlist": [target.ref for target in self.targets],
            "planned_mutation_count": (
                len(self.targets) if self.decision == "READY" else 0
            ),
            "mutation_count": 0,
            "plan_digest": self.plan_digest,
            "reason": self.reason,
        }


def _git_fact(root: Path, *args: str) -> str:
    result = run_git(list(args), cwd=root)
    return result.stdout.strip() if result.ok else ""


def _dirty_path_digest(root: Path) -> str:
    result = run_git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=root)
    if not result.ok:
        return _canonical_digest([])
    return _canonical_digest(sorted(line for line in result.stdout.splitlines() if line))


def _status_sync_facts(project_root: Path, *, work_id: str) -> tuple[dict[str, str], str]:
    release_root = project_root.resolve()
    process_root = _process_root(release_root)
    common = _git_fact(process_root, "rev-parse", "--git-common-dir")
    common_identity = _canonical_digest(common or "non-git-fixture")
    scope_digest = ""
    if work_id:
        scope_digest = load_work(process_root, work_id).scope.digest
    return (
        {
            "release_head_oid": _git_fact(release_root, "rev-parse", "--verify", "HEAD"),
            "process_head_oid": _git_fact(process_root, "rev-parse", "--verify", "HEAD"),
            "process_git_common_dir_identity": common_identity,
            "current_branch": _git_fact(process_root, "branch", "--show-current"),
            "dirty_path_digest": _dirty_path_digest(process_root),
        },
        scope_digest,
    )


def _target(
    project_root: Path,
    order: int,
    path: Path,
    after: str,
    truth_or_derived: str,
) -> StatusSyncTarget:
    return StatusSyncTarget(
        order=order,
        ref=_rel(project_root, path),
        path=path,
        truth_or_derived=truth_or_derived,
        before=path.read_text(encoding="utf-8") if path.is_file() else None,
        after=after,
    )


def _json_semantically_matches(
    path: Path,
    expected: dict[str, Any],
    *,
    volatile_fields: tuple[str, ...] = (),
) -> bool:
    if not path.is_file():
        return False
    try:
        observed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(observed, dict):
        return False
    observed = dict(observed)
    expected = dict(expected)
    for field in volatile_fields:
        observed.pop(field, None)
        expected.pop(field, None)
    return observed == expected


def _ledger_contains_status_sync_transition(
    path: Path,
    *,
    cr_id: str,
    lifecycle_status: str,
    readiness_status: str,
    gate_status: str,
) -> bool:
    """Match semantic status truth; dirty-path facts remain transaction preconditions only."""

    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return False
        if (
            isinstance(event, dict)
            and event.get("event_type") == "status_sync"
            and str(event.get("id") or "") == cr_id
            and cr_tracking.normalize_lifecycle_status(
                str(event.get("status") or "")
            )
            == cr_tracking.normalize_lifecycle_status(lifecycle_status)
            and cr_tracking.normalize_readiness_status(
                str(event.get("readiness") or "")
            )
            == cr_tracking.normalize_readiness_status(readiness_status)
            and cr_tracking.normalize_gate_status(
                str(event.get("gate_status") or "")
            )
            == cr_tracking.normalize_gate_status(gate_status)
        ):
            return True
    return False


def _normalize_status_sync_effective_at(value: str) -> str:
    if not value:
        return now_utc()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("status-sync effective_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("status-sync effective_at must include timezone")
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def plan_status_sync(
    project_root: Path,
    cr_id: str,
    *,
    status: str = "",
    readiness: str = "",
    gate_status: str = "",
    work_id: str = "",
    historical_migration: bool = False,
    historical_gate_status: str = "",
    historical_lifecycle_status: str = "",
    expected_process_oid: str = "",
    rebuild_corrupt_index: bool = False,
    effective_at: str = "",
) -> StatusSyncPlan:
    """Build a zero-mutation status-sync transaction plan."""

    project_root = project_root.resolve()
    timestamp = _normalize_status_sync_effective_at(effective_at)
    facts, scope_digest = _status_sync_facts(project_root, work_id=work_id)
    if expected_process_oid and facts["process_head_oid"] != expected_process_oid:
        return StatusSyncPlan(
            "BLOCKED",
            cr_id,
            work_id,
            {},
            facts,
            scope_digest,
            (),
            "process HEAD differs from expected OID",
            timestamp,
        )
    crs = discover_formal_crs(project_root)
    if cr_id not in crs:
        raise FileNotFoundError(f"未找到正式 CR: {cr_id}")
    cr_path = crs[cr_id]
    before_text = cr_path.read_text(encoding="utf-8")
    fields = parse_frontmatter(before_text)
    before_status = str(fields.get("lifecycle_status") or fields.get("status") or "active")
    before_readiness = str(fields.get("readiness_status") or "not_ready")
    before_gate = str(fields.get("gate_status") or "not_started")
    target_status = status or before_status
    target_readiness = readiness or before_readiness
    target_gate = gate_status or before_gate
    if target_status == "closed":
        if gate_status and gate_status != CLOSED_GATE_STATUS:
            raise ValueError(f"status=closed requires gate_status={CLOSED_GATE_STATUS}")
        target_gate = CLOSED_GATE_STATUS
    elif target_gate and target_gate not in cr_tracking.ALLOWED_GATE_STATUSES:
        raise ValueError(f"invalid gate_status: {target_gate}")
    native = str(fields.get("schema_version") or "") == "1" and str(fields.get("kind") or "") == "cr"
    if native:
        transition_errors = cr_tracking.validate_native_transition(
            (before_status, before_readiness, before_gate),
            (target_status, target_readiness, target_gate),
            historical_migration=historical_migration,
        )
        if transition_errors:
            return StatusSyncPlan(
                "BLOCKED",
                cr_id,
                work_id,
                {},
                facts,
                scope_digest,
                (),
                "; ".join(transition_errors),
            )
    index_path = _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    if index_path.is_file():
        try:
            formal_truth_index = build_index(project_root)
        except ValueError as exc:
            return StatusSyncPlan(
                "BLOCKED", cr_id, work_id, {}, facts, scope_digest, (), str(exc)
            )
        try:
            existing_index = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            if not rebuild_corrupt_index:
                return StatusSyncPlan(
                    "BLOCKED", cr_id, work_id, {}, facts, scope_digest, (), f"CR-INDEX invalid JSON: {exc}"
                )
        else:
            index_errors = validate_index_payload(existing_index)
            if index_errors and not rebuild_corrupt_index:
                return StatusSyncPlan(
                    "BLOCKED", cr_id, work_id, {}, facts, scope_digest, (), "; ".join(index_errors)
                )
            if (
                not index_errors
                and existing_index.get("semantic_digest")
                != formal_truth_index.get("semantic_digest")
                and not rebuild_corrupt_index
            ):
                return StatusSyncPlan(
                    "BLOCKED",
                    cr_id,
                    work_id,
                    {},
                    facts,
                    scope_digest,
                    (),
                    "CR-INDEX stale projection differs from formal truth rebuild digest",
                )
    updates = {
        "lifecycle_status": target_status,
        "readiness_status": target_readiness,
        "gate_status": target_gate,
        "historical_gate_status": historical_gate_status,
        "historical_lifecycle_status": historical_lifecycle_status,
    }
    if "status" in fields:
        updates["status"] = target_status
    cr_after = render_frontmatter_fields(before_text, updates)
    cr_after = render_status_body_projection(
        cr_after,
        lifecycle_status=target_status,
        readiness_status=target_readiness,
        gate_status=target_gate,
        checkpoint_results=_checkpoint_result_projection(project_root, cr_id),
    )
    summary = summary_from_cr_file(project_root, cr_path, readiness=target_readiness)
    summary["status"] = target_status
    summary["readiness"] = target_readiness
    summary["gate_status"] = target_gate
    summary["updated_at"] = timestamp
    summary_path = _resolve_runtime_ref(
        project_root, (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()
    )
    summary_after = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    evidence_path = _resolve_runtime_ref(
        project_root, (CR_ARCHIVE_ROOT_REL / cr_id / "evidence-index.json").as_posix()
    )
    evidence = {
        "cr_id": cr_id,
        "summary_ref": (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix(),
        "full_ref": summary.get("full_ref"),
        "evidence_refs": [],
        "created_at": timestamp,
    }
    evidence_after = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ledger_path = _resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix())
    ledger_event = {
        "event_id": _canonical_digest(
            {"event": "status_sync", "id": cr_id, "transition": updates, "facts": facts}
        ),
        "event": "status_sync",
        "event_type": "status_sync",
        "id": cr_id,
        "cr_type": summary.get("cr_type"),
        "status": target_status,
        "readiness": target_readiness,
        "gate_status": target_gate,
        "summary_ref": _rel(project_root, summary_path),
        "full_ref": summary.get("full_ref"),
        "evidence_index_ref": _rel(project_root, evidence_path),
        "frontmatter_changed": cr_after != before_text,
        "historical_migration": historical_migration,
        "synced_at": timestamp,
    }
    ledger_after = event_ledger.render_appended_event(ledger_path, ledger_event)
    expected_index = build_index(
        project_root,
        record_overrides={cr_id: updates},
    )
    expected_index["generated_at"] = timestamp
    index_after = json.dumps(expected_index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    targets: list[StatusSyncTarget] = [
        _target(project_root, 10, cr_path, cr_after, "truth"),
    ]
    state_path = _resolve_runtime_ref(project_root, STATE_CURRENT_REL.as_posix())
    if state_path.is_file() and not historical_migration:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state_patch: dict[str, Any] = {"updated_at": timestamp}
        if target_status in FINISHED_STATUSES and state.get("active_change") == cr_id:
            state_patch.update(
                {
                    "active_change": None,
                    "active_context_ref": None,
                    "current_phase": "delivered" if target_status == "closed" else str(state.get("current_phase") or "delivered"),
                    "pending_gate": None,
                    "pending_checklist_path": None,
                    "next_action": {
                        "type": "done",
                        "text": f"{cr_id} status synced as {target_status}; choose next CR.",
                        "stop_reason": "delivered" if target_status == "closed" else "no_remaining_route",
                    },
                }
            )
        elif target_status in {"active", "blocked"} and not state.get("active_change"):
            state_patch.update(
                {
                    "active_change": cr_id,
                    "next_action": {
                        "type": "status_synced",
                        "text": f"{cr_id} status synced as {target_status}; continue from the Work route.",
                    },
                }
            )
        if len(state_patch) > 1:
            state_after = current.render_current_state_candidate(
                current.build_current_state_candidate(
                    project_root,
                    state_patch,
                    actor="meta_flow.workflow.cr_lifecycle",
                    reason=f"status-sync {cr_id}",
                )
            )
            targets.append(_target(project_root, 20, state_path, state_after, "truth"))
    targets.extend(
        [
            _target(project_root, 30, summary_path, summary_after, "derived"),
            _target(project_root, 40, evidence_path, evidence_after, "derived"),
            _target(project_root, 50, ledger_path, ledger_after, "derived"),
            _target(project_root, 90, index_path, index_after, "derived"),
        ]
    )
    if work_id:
        work = load_work(_process_root(project_root), work_id)
        denied = [
            target.ref
            for target in targets
            if not check_scope(
                work.scope,
                "write",
                target.ref.removeprefix("process/"),
            ).allowed
        ]
        if denied:
            return StatusSyncPlan(
                "BLOCKED",
                cr_id,
                work_id,
                {},
                facts,
                scope_digest,
                (),
                "targets outside Work write scope: " + ", ".join(denied),
            )
    desired_transition = {
        "lifecycle_status": target_status,
        "readiness_status": target_readiness,
        "gate_status": target_gate,
    }
    truth_current = all(
        target.before is not None and target.before_digest == target.after_digest
        for target in targets
        if target.truth_or_derived == "truth"
    )
    derived_current = (
        _json_semantically_matches(
            summary_path,
            summary,
            volatile_fields=("updated_at",),
        )
        and _json_semantically_matches(
            evidence_path,
            evidence,
            volatile_fields=("created_at",),
        )
        and _ledger_contains_status_sync_transition(
            ledger_path,
            cr_id=cr_id,
            lifecycle_status=target_status,
            readiness_status=target_readiness,
            gate_status=target_gate,
        )
        and index_path.is_file()
        and json.loads(index_path.read_text(encoding="utf-8")).get(
            "semantic_digest"
        )
        == expected_index.get("semantic_digest")
    )
    if truth_current and derived_current:
        return StatusSyncPlan(
            "NO_CHANGE",
            cr_id,
            work_id,
            desired_transition,
            facts,
            scope_digest,
            (),
            "status tuple and native projections are already synchronized",
            timestamp,
        )
    return StatusSyncPlan(
        "READY",
        cr_id,
        work_id,
        desired_transition,
        facts,
        scope_digest,
        tuple(sorted(targets, key=lambda item: item.order)),
        effective_at=timestamp,
    )


def _transaction_root(project_root: Path) -> Path:
    process_root = _process_root(project_root)
    common = _git_fact(process_root, "rev-parse", "--git-common-dir")
    if common:
        path = Path(common)
        common_root = path if path.is_absolute() else (process_root / path)
    else:
        common_root = process_root / ".meta-flow-fixture-git"
    return common_root.resolve(strict=False) / "meta-flow" / "transactions"


def _current_target_digest(target: StatusSyncTarget) -> str:
    if not target.path.is_file():
        return _canonical_digest("")
    return _canonical_digest(target.path.read_text(encoding="utf-8"))


def load_status_sync_authorization(path: Path) -> StatusSyncAuthorization:
    payload = _load_json_object(path, subject="status-sync authorization")
    return StatusSyncAuthorization.from_dict(payload)


def validate_status_sync_authorization(
    plan: StatusSyncPlan,
    authorization: StatusSyncAuthorization,
) -> None:
    if plan.decision != "READY":
        raise ValueError("status-sync authorization requires one READY plan")
    if not plan.work_id or not plan.scope_digest:
        raise ValueError("status-sync typed apply requires work_id and scope digest")
    if authorization.schema_version != 1:
        raise ValueError("status-sync authorization schema_version must be 1")
    if not SAFE_AUTHORIZATION_ID_RE.fullmatch(authorization.authorization_id):
        raise ValueError("status-sync authorization_id is invalid")
    if authorization.authorization_source != STATUS_SYNC_AUTHORIZATION_SOURCE:
        raise ValueError(
            "status-sync authorization_source must be typed-user-confirmation"
        )
    if authorization.authorization_kind != STATUS_SYNC_AUTHORIZATION_KIND:
        raise ValueError(
            "status-sync authorization_kind must be cr-status-sync"
        )
    if authorization.operation != STATUS_SYNC_OPERATION:
        raise ValueError("status-sync authorization operation mismatch")
    if authorization.single_use is not True:
        raise ValueError("status-sync authorization must be single-use")
    expected = (
        plan.cr_id,
        plan.work_id,
        plan.desired_transition,
        plan.effective_at,
        plan.expected_facts.get("release_head_oid", ""),
        plan.expected_facts.get("process_head_oid", ""),
        plan.scope_digest,
        [target.as_dict() for target in plan.targets],
        plan.plan_digest,
    )
    actual = (
        authorization.cr_id,
        authorization.work_id,
        authorization.desired_transition,
        authorization.effective_at,
        authorization.expected_release_oid,
        authorization.expected_process_oid,
        authorization.scope_digest,
        authorization.targets,
        authorization.plan_digest,
    )
    if actual != expected:
        raise ValueError(
            "status-sync authorization does not match "
            "CR/Work/transition/effective_at/OIDs/scope/targets/plan"
        )
    if not OID_RE.fullmatch(authorization.expected_release_oid):
        raise ValueError("status-sync expected_release_oid is invalid")
    if not OID_RE.fullmatch(authorization.expected_process_oid):
        raise ValueError("status-sync expected_process_oid is invalid")
    if not DIGEST_RE.fullmatch(authorization.scope_digest):
        raise ValueError("status-sync scope_digest is invalid")
    if not DIGEST_RE.fullmatch(authorization.plan_digest):
        raise ValueError("status-sync plan_digest is invalid")
    try:
        expires_at = datetime.fromisoformat(
            authorization.expires_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("status-sync authorization expires_at is invalid") from exc
    if expires_at.tzinfo is None:
        raise ValueError(
            "status-sync authorization expires_at must include timezone"
        )
    if expires_at.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError("status-sync authorization is expired")


def _status_sync_claim_path(
    project_root: Path,
    authorization_id: str,
) -> Path:
    if not SAFE_AUTHORIZATION_ID_RE.fullmatch(authorization_id):
        raise ValueError("status-sync authorization_id is invalid")
    return (
        _transaction_root(project_root).parent
        / "status-sync"
        / "authorizations"
        / f"{authorization_id}.json"
    )


def _claim_status_sync_authorization(
    project_root: Path,
    plan: StatusSyncPlan,
    authorization: StatusSyncAuthorization,
) -> Path:
    validate_status_sync_authorization(plan, authorization)
    path = _status_sync_claim_path(project_root, authorization.authorization_id)
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
        "claimed_at": now_utc(),
    }
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
    except FileExistsError as exc:
        raise ValueError(
            "status-sync authorization was already consumed"
        ) from exc
    return path


def _status_sync_writer_lock_path(project_root: Path) -> Path:
    return _transaction_root(project_root.resolve()).parent / "status-sync.lock"


def _acquire_status_sync_writer_lock(
    project_root: Path,
    *,
    transaction_id: str,
    purpose: str,
) -> dict[str, Any] | None:
    """Acquire the cooperative global writer lock and persist owner identity."""

    lock_path = _status_sync_writer_lock_path(project_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    acquired_at = now_utc()
    owner = {
        "schema_version": 1,
        "owner_token": uuid.uuid4().hex,
        "owner_process_identity": f"pid:{os.getpid()}:instance:{uuid.uuid4().hex}",
        "owner_started_at": acquired_at,
        "acquired_at": acquired_at,
        "transaction_id": transaction_id,
        "purpose": purpose,
        "lease_state": "held",
    }
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(owner, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        lock_path.unlink(missing_ok=True)
        raise
    return owner


def _release_status_sync_writer_lock(project_root: Path, owner: dict[str, Any]) -> bool:
    """Release only the lock whose persisted owner token matches the caller."""

    lock_path = _status_sync_writer_lock_path(project_root)
    try:
        first_stat = lock_path.stat()
        persisted = json.loads(lock_path.read_text(encoding="utf-8"))
        second_stat = lock_path.stat()
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    if (
        persisted.get("owner_token") != owner.get("owner_token")
        or persisted.get("owner_process_identity") != owner.get("owner_process_identity")
        or (first_stat.st_dev, first_stat.st_ino) != (second_stat.st_dev, second_stat.st_ino)
    ):
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return False
    return True


def apply_status_sync(
    project_root: Path,
    plan: StatusSyncPlan,
    *,
    authorization: StatusSyncAuthorization | None = None,
    expected_plan_digest: str = "",
    _fail_after_replace: int | None = None,
    _fail_recovery: bool = False,
    _fault: str = "",
) -> dict[str, Any]:
    """Apply one prepared status-sync plan with verified backups and recovery."""

    project_root = project_root.resolve()
    if plan.decision == "NO_CHANGE":
        return {
            "status": "NO_CHANGE",
            "reason": plan.reason,
            "mutation_count": 0,
        }
    if plan.decision != "READY":
        return {"status": "BLOCKED", "reason": plan.reason, "mutation_count": 0}
    if not expected_plan_digest or expected_plan_digest != plan.plan_digest:
        return {
            "status": "BLOCKED",
            "reason": "expected plan digest does not match the current plan",
            "mutation_count": 0,
        }
    if authorization is None:
        return {
            "status": "BLOCKED",
            "reason": "status-sync apply requires typed authorization",
            "mutation_count": 0,
        }
    try:
        validate_status_sync_authorization(plan, authorization)
    except ValueError as exc:
        return {
            "status": "BLOCKED",
            "reason": str(exc),
            "mutation_count": 0,
        }
    observed_facts, observed_scope = _status_sync_facts(project_root, work_id=plan.work_id)
    if observed_facts != plan.expected_facts or observed_scope != plan.scope_digest:
        return {"status": "BLOCKED", "reason": "expected facts or scope digest drifted", "mutation_count": 0}
    drifted = [target.ref for target in plan.targets if _current_target_digest(target) != target.before_digest]
    if drifted:
        return {"status": "BLOCKED", "reason": "target digest drift: " + ", ".join(drifted), "mutation_count": 0}
    transaction_root = _transaction_root(project_root)
    transaction_root.mkdir(parents=True, exist_ok=True)
    unresolved = [
        path
        for path in transaction_root.glob("*/manifest.json")
        if path.is_file()
    ]
    if unresolved:
        return {"status": "BLOCKED", "reason": "unresolved status-sync transaction exists", "mutation_count": 0}
    transaction_id = uuid.uuid4().hex
    lock_owner = _acquire_status_sync_writer_lock(
        project_root,
        transaction_id=transaction_id,
        purpose="apply",
    )
    if lock_owner is None:
        return {"status": "BLOCKED", "reason": "status-sync writer lock exists", "mutation_count": 0}
    try:
        _claim_status_sync_authorization(project_root, plan, authorization)
    except ValueError as exc:
        _release_status_sync_writer_lock(project_root, lock_owner)
        return {
            "status": "BLOCKED",
            "reason": str(exc),
            "mutation_count": 0,
        }
    transaction_dir = transaction_root / transaction_id
    backup_root = transaction_dir / "backups"
    after_root = transaction_dir / "after"
    backup_root.mkdir(parents=True)
    after_root.mkdir(parents=True)
    idempotency_key = _canonical_digest(
        {
            "command": "status-sync",
            "plan_digest": plan.plan_digest,
            "authorization_id": authorization.authorization_id,
        }
    )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "idempotency_key": idempotency_key,
        "work_id": plan.work_id,
        "cr_id": plan.cr_id,
        "command": "status-sync",
        "plan_digest": plan.plan_digest,
        "authorization_id": authorization.authorization_id,
        "desired_transition": plan.desired_transition,
        "effective_at": plan.effective_at,
        "expected_facts": plan.expected_facts,
        "scope_digest": plan.scope_digest,
        "lock": dict(lock_owner),
        "targets": [],
        "receipts": [],
        "recovery_state": "prepared",
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    applied: list[StatusSyncTarget] = []
    try:
        for target in plan.targets:
            backup = backup_root / f"{target.order:03d}.before"
            prepared_after = after_root / f"{target.order:03d}.after"
            backup.write_text(target.before or "", encoding="utf-8")
            prepared_after.write_text(target.after, encoding="utf-8")
            backup_digest = _canonical_digest(backup.read_text(encoding="utf-8"))
            if backup_digest != target.before_digest:
                raise RuntimeError(f"backup digest mismatch: {target.ref}")
            if _canonical_digest(prepared_after.read_text(encoding="utf-8")) != target.after_digest:
                raise RuntimeError(f"prepared after digest mismatch: {target.ref}")
            manifest["targets"].append(
                {
                    **target.as_dict(),
                    "before_content_ref": f"backups/{backup.name}",
                    "before_content_digest": backup_digest,
                    "after_content_ref": f"after/{prepared_after.name}",
                    "backup_created_at": now_utc(),
                    "backup_verified_at": now_utc(),
                    "apply_status": "prepared",
                    "recovery_status": "not-required",
                }
            )
        manifest_path = transaction_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest["recovery_state"] = "applying"
        if _fault == "before-first-replace":
            raise RuntimeError("injected failure before first replace")
        for offset, target in enumerate(plan.targets, 1):
            if _fault == "before-index-last" and target.ref == CR_INDEX_REL.as_posix():
                raise RuntimeError("injected failure before index-last replace")
            _atomic_write_text(target.path, target.after)
            applied.append(target)
            if _fault == "after-replace-before-receipt":
                raise RuntimeError("injected abrupt exit after replace before receipt")
            manifest["targets"][offset - 1]["apply_status"] = "applied"
            manifest["receipts"].append(
                {
                    "target_ref": target.ref,
                    "operation": "replace" if target.before is not None else "create",
                    "observed_before_digest": target.before_digest,
                    "observed_after_digest": _current_target_digest(target),
                    "completed_at": now_utc(),
                }
            )
            manifest["updated_at"] = now_utc()
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if _fail_after_replace == offset:
                raise RuntimeError(f"injected failure after replace {offset}")
            if _fault == "after-receipt-before-next":
                raise RuntimeError("injected abrupt exit after receipt before next target")
            if (
                _fault == "after-truth-before-derived"
                and target.truth_or_derived == "truth"
                and offset < len(plan.targets)
                and plan.targets[offset].truth_or_derived == "derived"
            ):
                raise RuntimeError("injected failure after truth before derived")
        if _fault == "during-read-back":
            raise RuntimeError("injected failure during read-back")
        readback_failures = [
            target.ref for target in plan.targets if _current_target_digest(target) != target.after_digest
        ]
        if readback_failures:
            raise RuntimeError("read-back mismatch: " + ", ".join(readback_failures))
        manifest["recovery_state"] = "committed"
        manifest["lock"]["lease_state"] = "released"
        manifest["updated_at"] = now_utc()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths = {target.ref: target.path for target in plan.targets}
        shutil.rmtree(transaction_dir)
        return {
            "status": "PASS",
            "transaction_id": transaction_id,
            "idempotency_key": idempotency_key,
            "plan_digest": plan.plan_digest,
            "authorization_id": authorization.authorization_id,
            "mutation_count": len(plan.targets),
            "paths": paths,
        }
    except Exception as exc:
        manifest["recovery_state"] = "recovery-required"
        recovery_errors: list[str] = []
        for target in reversed(applied):
            try:
                if _fail_recovery:
                    raise RuntimeError("injected recovery failure")
                if target.before is None:
                    if target.path.exists():
                        target.path.unlink()
                else:
                    _atomic_write_text(target.path, target.before)
                if _current_target_digest(target) != target.before_digest:
                    raise RuntimeError("recovery digest mismatch")
                for entry in manifest["targets"]:
                    if entry["ref"] == target.ref:
                        entry["recovery_status"] = "restored"
            except Exception as recovery_error:
                recovery_errors.append(f"{target.ref}: {recovery_error}")
        status = "PARTIAL" if recovery_errors else "RECOVERED" if applied else "BLOCKED"
        manifest["recovery_state"] = status.lower()
        manifest["lock"]["lease_state"] = "released"
        manifest["updated_at"] = now_utc()
        (transaction_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if status in {"BLOCKED", "RECOVERED"}:
            shutil.rmtree(transaction_dir)
        result = {
            "status": status,
            "transaction_id": transaction_id,
            "idempotency_key": idempotency_key,
            "plan_digest": plan.plan_digest,
            "authorization_id": authorization.authorization_id,
            "mutation_count": len(applied),
            "reason": str(exc),
            "recovery_errors": recovery_errors,
        }
        if status == "PARTIAL":
            result["rollback_evidence_ref"] = (
                "private://status-sync/transactions/"
                f"{transaction_id}/manifest.json"
            )
        return result
    finally:
        _release_status_sync_writer_lock(project_root, lock_owner)


def inspect_status_sync_transactions(project_root: Path) -> dict[str, Any]:
    """Inspect unresolved private manifests without changing repository state."""

    root = _transaction_root(project_root.resolve())
    transactions: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*/manifest.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                transactions.append(
                    {
                        "transaction_id": path.parent.name,
                        "recovery_state": "partial",
                        "error": str(exc),
                    }
                )
                continue
            transactions.append(
                {
                    "transaction_id": payload.get("transaction_id") or path.parent.name,
                    "cr_id": payload.get("cr_id") or "",
                    "work_id": payload.get("work_id") or "",
                    "recovery_state": payload.get("recovery_state") or "",
                    "target_refs": [
                        str(item.get("ref") or "")
                        for item in payload.get("targets") or []
                        if isinstance(item, dict)
                    ],
                }
            )
    return {
        "decision": "PASS",
        "transaction_count": len(transactions),
        "transactions": transactions,
    }


def recover_status_sync_transaction(
    project_root: Path,
    transaction_id: str,
    *,
    action: str,
    typed_authorized: bool = False,
) -> dict[str, Any]:
    """Explicitly resume, rollback, or abandon one unresolved transaction."""

    if action not in {"resume", "rollback", "abandon"}:
        raise ValueError("recovery action must be resume, rollback, or abandon")
    if not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise ValueError("transaction_id must be one 32-character lowercase hex identity")
    project_root = project_root.resolve()
    transaction_dir = _transaction_root(project_root) / transaction_id
    manifest_path = transaction_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"status-sync transaction not found: {transaction_id}")
    if action == "abandon" and not typed_authorized:
        return {
            "status": "BLOCKED",
            "reason": "abandon requires typed authorization",
            "mutation_count": 0,
        }
    lock_owner = _acquire_status_sync_writer_lock(
        project_root,
        transaction_id=transaction_id,
        purpose=f"recovery:{action}",
    )
    if lock_owner is None:
        return {
            "status": "BLOCKED",
            "reason": "status-sync writer lock exists",
            "mutation_count": 0,
        }
    manifest: dict[str, Any] = {}
    remove_transaction = False
    result: dict[str, Any]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        prior_lock = manifest.get("lock")
        if isinstance(prior_lock, dict):
            manifest.setdefault("lock_history", []).append(prior_lock)
        manifest["lock"] = dict(lock_owner)
        manifest["recovery_state"] = "recovering"
        manifest["updated_at"] = now_utc()
        _atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        if action == "abandon":
            manifest["recovery_state"] = "abandoned"
            manifest["updated_at"] = now_utc()
            result = {"status": "PASS", "action": "abandon", "mutation_count": 1}
        else:
            facts, scope_digest = _status_sync_facts(
                project_root, work_id=str(manifest.get("work_id") or "")
            )
            expected = manifest.get("expected_facts") or {}
            stable_keys = {
                "release_head_oid",
                "process_head_oid",
                "process_git_common_dir_identity",
                "current_branch",
            }
            if (
                any(facts.get(key) != expected.get(key) for key in stable_keys)
                or scope_digest != manifest.get("scope_digest")
            ):
                manifest["recovery_state"] = "recovery-required"
                result = {
                    "status": "BLOCKED",
                    "reason": "recovery expected facts or scope digest drifted",
                    "mutation_count": 0,
                }
            else:
                targets = sorted(
                    [item for item in manifest.get("targets") or [] if isinstance(item, dict)],
                    key=lambda item: int(item.get("order") or 0),
                    reverse=action == "rollback",
                )
                changed = 0
                errors: list[str] = []
                for item in targets:
                    ref = str(item.get("ref") or "")
                    try:
                        path = _resolve_runtime_ref(project_root, ref)
                        before_exists = bool(item.get("before_exists"))
                        before_content = (
                            transaction_dir / str(item["before_content_ref"])
                        ).read_text(encoding="utf-8")
                        after_content = (
                            transaction_dir / str(item["after_content_ref"])
                        ).read_text(encoding="utf-8")
                        current_digest = (
                            _canonical_digest(path.read_text(encoding="utf-8"))
                            if path.is_file()
                            else _canonical_digest("")
                        )
                        before_digest = str(item.get("before_digest") or "")
                        after_digest = str(item.get("after_digest") or "")
                        desired_digest = after_digest if action == "resume" else before_digest
                        if current_digest == desired_digest:
                            continue
                        if current_digest not in {before_digest, after_digest}:
                            raise RuntimeError(
                                "current digest matches neither prepared before nor after content"
                            )
                        if action == "resume":
                            _atomic_write_text(path, after_content)
                        elif before_exists:
                            _atomic_write_text(path, before_content)
                        elif path.exists():
                            path.unlink()
                        observed = (
                            _canonical_digest(path.read_text(encoding="utf-8"))
                            if path.is_file()
                            else _canonical_digest("")
                        )
                        if observed != desired_digest:
                            raise RuntimeError("recovery read-back digest mismatch")
                        changed += 1
                    except Exception as exc:
                        errors.append(f"{ref}: {exc}")
                if errors:
                    manifest["recovery_state"] = "partial"
                    result = {
                        "status": "PARTIAL",
                        "action": action,
                        "mutation_count": changed,
                        "errors": errors,
                    }
                else:
                    manifest["recovery_state"] = (
                        "committed" if action == "resume" else "recovered"
                    )
                    remove_transaction = True
                    result = {
                        "status": "PASS" if action == "resume" else "RECOVERED",
                        "action": action,
                        "mutation_count": changed,
                    }
        manifest["updated_at"] = now_utc()
        if not remove_transaction:
            manifest["lock"]["lease_state"] = "released"
            _atomic_write_text(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
        else:
            shutil.rmtree(transaction_dir)
        return result
    finally:
        _release_status_sync_writer_lock(project_root, lock_owner)


@dataclass(frozen=True)
class TerminationAuthorization:
    schema_version: int
    authorization_id: str
    authorization_source: str
    authorization_kind: str
    operation: str
    cr_id: str
    work_id: str
    termination_reason: str
    terminal_tuple: dict[str, str]
    expected_release_oid: str
    expected_process_oid: str
    scope_digest: str
    plan_digest: str
    expires_at: str
    single_use: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TerminationAuthorization:
        if set(payload) != TERMINATION_AUTHORIZATION_FIELDS:
            missing = sorted(TERMINATION_AUTHORIZATION_FIELDS - set(payload))
            extra = sorted(set(payload) - TERMINATION_AUTHORIZATION_FIELDS)
            raise ValueError(
                f"termination authorization fields mismatch: missing={missing}, extra={extra}"
            )
        return cls(**payload)


@dataclass(frozen=True)
class TerminationTarget:
    order: int
    ref: str
    path: Path
    truth_or_derived: str
    before: str | None
    after: str

    @property
    def before_digest(self) -> str:
        return _canonical_digest(self.before if self.before is not None else "")

    @property
    def after_digest(self) -> str:
        return _canonical_digest(self.after)

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "ref": self.ref,
            "truth_or_derived": self.truth_or_derived,
            "before_exists": self.before is not None,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
        }


@dataclass(frozen=True)
class TerminationPlan:
    decision: str
    cr_id: str
    work_id: str
    termination_reason: str
    terminal_tuple: dict[str, str]
    expected_facts: dict[str, str]
    binding: dict[str, str]
    scope_digest: str
    targets: tuple[TerminationTarget, ...]
    reason: str = ""

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "operation": TERMINATION_OPERATION,
            "decision": self.decision,
            "cr_id": self.cr_id,
            "work_id": self.work_id,
            "termination_reason": self.termination_reason,
            "terminal_tuple": self.terminal_tuple,
            "expected_facts": self.expected_facts,
            "binding": self.binding,
            "scope_digest": self.scope_digest,
            "targets": [target.as_dict() for target in self.targets],
            "reason": self.reason,
        }

    @property
    def plan_digest(self) -> str:
        return _canonical_digest(self._digest_payload())

    def as_dict(self) -> dict[str, Any]:
        target_refs = [target.ref for target in self.targets]
        return {
            **self._digest_payload(),
            "expected_oids": {
                "producer_release": self.expected_facts.get("producer_release_oid", ""),
                "target_release": self.expected_facts.get("target_release_oid", ""),
                "process": self.expected_facts.get("process_head_oid", ""),
            },
            "mutation_count": 0,
            "planned_mutation_count": len(self.targets),
            "mutation_allowlist": target_refs,
            "exact_changed_leaf_paths": target_refs,
            "transaction_order": [
                {
                    "order": target.order,
                    "ref": target.ref,
                    "truth_or_derived": target.truth_or_derived,
                }
                for target in self.targets
            ],
            "rollback": {
                "strategy": "reverse-order-exact-preimage-restore",
                "order": list(reversed(target_refs)),
                "partial_evidence": "private://cr-termination/transactions/<transaction-id>/manifest.json",
            },
            "apply_private_effects": [
                "single-use authorization claim",
                "recoverable transaction evidence",
            ],
            "plan_digest": self.plan_digest,
        }


def _portable_termination_error(
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


def _termination_facts(
    project_root: Path,
    *,
    work_id: str,
) -> tuple[dict[str, str], dict[str, str], str, Path]:
    release_root = project_root.resolve()
    route = require_process_route(release_root)
    process_root = route.process_root
    producer_root = Path(__file__).resolve().parents[2]
    facts = {
        "producer_release_oid": _git_fact(
            producer_root, "rev-parse", "--verify", "HEAD"
        ).lower(),
        "target_release_oid": _git_fact(
            release_root, "rev-parse", "--verify", "HEAD"
        ).lower(),
        "process_head_oid": _git_fact(
            process_root, "rev-parse", "--verify", "HEAD"
        ).lower(),
        "process_git_common_dir_identity": _canonical_digest(
            _git_fact(process_root, "rev-parse", "--git-common-dir")
            or "non-git-fixture"
        ),
        "process_dirty_path_digest": _dirty_path_digest(process_root),
    }
    for key in ("producer_release_oid", "target_release_oid", "process_head_oid"):
        if not OID_RE.fullmatch(facts[key]):
            raise ValueError(f"{key} is not one exact Git OID")
    work = load_work(process_root, work_id)
    binding = {
        "status": "healthy",
        "project_id": route.project_id,
        "layout_version": route.layout_version,
        "route_mode": route.route_mode,
    }
    return facts, binding, work.scope.digest, process_root


def _termination_target(
    project_root: Path,
    order: int,
    path: Path,
    after: str,
    truth_or_derived: str,
) -> TerminationTarget | None:
    before = path.read_text(encoding="utf-8") if path.is_file() else None
    if before == after:
        return None
    return TerminationTarget(
        order=order,
        ref=_rel(project_root, path),
        path=path,
        truth_or_derived=truth_or_derived,
        before=before,
        after=after,
    )


def _render_termination_body_projection(
    text: str,
    *,
    terminal_tuple: dict[str, str],
) -> str:
    rendered = _render_exact_section_rows(
        text,
        "CR 类型与门禁策略",
        {
            "生命周期状态": terminal_tuple["lifecycle_status"],
            "就绪状态": terminal_tuple["readiness_status"],
            "门禁状态": terminal_tuple["gate_status"],
        },
    )
    return _render_exact_section_rows(
        rendered,
        "Checkpoint Index",
        {"CP8": "not-applicable"},
    )


def _load_json_object(path: Path, *, subject: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{subject} is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{subject} must be one JSON object")
    return payload


def _termination_projection_is_complete(
    project_root: Path,
    *,
    cr_id: str,
    work_id: str,
    terminal_tuple: dict[str, str],
    process_root: Path,
) -> tuple[bool, str]:
    work = load_work(process_root, work_id)
    if work.status not in {"cancelled", "archived"}:
        return False, f"Work remains non-terminal: {work.status}"
    project = load_project(process_root)
    if work.work_ref in project.active_work_refs:
        return False, "Project still references the terminated Work"
    if work.phase_ref:
        phase = load_phase(process_root, work.phase_ref)
        if work.work_ref in phase.work_refs:
            return False, "Phase still references the terminated Work"
    summary_path = _resolve_runtime_ref(
        project_root, (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()
    )
    if not summary_path.is_file():
        return False, "termination summary is missing"
    summary = _load_json_object(summary_path, subject="termination summary")
    if (
        str(summary.get("status") or "") != terminal_tuple["lifecycle_status"]
        or str(summary.get("readiness") or "").lower()
        != terminal_tuple["readiness_status"]
        or str(summary.get("gate_status") or "").lower()
        != terminal_tuple["gate_status"]
    ):
        return False, "termination summary tuple is inconsistent"
    index_path = _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    if not index_path.is_file():
        return False, "CR-INDEX is missing"
    index = _load_json_object(index_path, subject="CR-INDEX")
    index_errors = validate_index_payload(index)
    if index_errors:
        return False, "; ".join(index_errors)
    expected_index = build_index(project_root)
    if index.get("semantic_digest") != expected_index.get("semantic_digest"):
        return False, "CR-INDEX differs from formal truth"
    ledger_path = _resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix())
    if not ledger_path.is_file():
        return False, "CR ledger is missing"
    matching_event = any(
        str(event.get("event_type") or "") == "cr_termination"
        and str(event.get("id") or "") == cr_id
        and str(event.get("status") or "") == terminal_tuple["lifecycle_status"]
        for event in load_ledger_events(project_root)
    )
    if not matching_event:
        return False, "CR termination ledger event is missing"
    state_path = _resolve_runtime_ref(project_root, STATE_CURRENT_REL.as_posix())
    if state_path.is_file():
        state = _load_json_object(state_path, subject="STATE.current.json")
        if state.get("active_change") == cr_id:
            return False, "STATE.current.json still references the terminated CR"
    return True, ""


def _blocked_termination_plan(
    *,
    cr_id: str,
    work_id: str,
    termination_reason: str,
    terminal_tuple: dict[str, str],
    expected_facts: dict[str, str],
    binding: dict[str, str],
    scope_digest: str,
    reason: str,
) -> TerminationPlan:
    return TerminationPlan(
        decision="BLOCKED",
        cr_id=cr_id,
        work_id=work_id,
        termination_reason=termination_reason,
        terminal_tuple=terminal_tuple,
        expected_facts=expected_facts,
        binding=binding,
        scope_digest=scope_digest,
        targets=(),
        reason=reason,
    )


def plan_cr_termination(
    project_root: Path,
    cr_id: str,
    *,
    work_id: str,
    termination_status: str,
    termination_reason: str,
    expected_process_oid: str = "",
) -> TerminationPlan:
    """Build a deterministic, zero-mutation CR termination transaction."""

    release_root = project_root.resolve()
    terminal_tuple = dict(TERMINATION_TUPLES.get(termination_status) or {})
    facts: dict[str, str] = {}
    binding: dict[str, str] = {}
    scope_digest = ""
    process_root: Path | None = None
    if not CR_ID_RE.fullmatch(cr_id):
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=termination_reason,
            terminal_tuple=terminal_tuple,
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            reason="CR id must use CR-xxx naming",
        )
    if not terminal_tuple:
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=termination_reason,
            terminal_tuple={},
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            reason="termination status must be cancelled or superseded",
        )
    normalized_reason = termination_reason.strip()
    if not normalized_reason or len(normalized_reason) > 1000:
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            reason="termination reason must contain 1-1000 characters",
        )
    if not work_id:
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            reason="work_id is required",
        )
    try:
        facts, binding, scope_digest, process_root = _termination_facts(
            release_root, work_id=work_id
        )
        if expected_process_oid and expected_process_oid != facts["process_head_oid"]:
            raise ValueError("process HEAD differs from expected OID")
        crs = discover_formal_crs(release_root)
        if cr_id not in crs:
            raise ValueError(f"formal CR is missing: {cr_id}")
        cr_path = crs[cr_id]
        cr_before = cr_path.read_text(encoding="utf-8")
        fields = parse_frontmatter(cr_before)
        source_follow_up_id = str(fields.get("source_follow_up_id") or "")
        if source_follow_up_id and source_follow_up_id != work_id:
            raise ValueError("CR source_follow_up_id does not match work_id")
        current_tuple = {
            "lifecycle_status": cr_tracking.normalize_lifecycle_status(
                fields.get("lifecycle_status") or fields.get("status") or ""
            ),
            "readiness_status": cr_tracking.normalize_readiness_status(
                fields.get("readiness_status") or ""
            ),
            "gate_status": cr_tracking.normalize_gate_status(
                fields.get("gate_status") or ""
            ),
        }
        current_values = tuple(current_tuple.values())
        target_values = tuple(terminal_tuple.values())
        if current_values == target_values:
            complete, incomplete_reason = _termination_projection_is_complete(
                release_root,
                cr_id=cr_id,
                work_id=work_id,
                terminal_tuple=terminal_tuple,
                process_root=process_root,
            )
            if not complete:
                raise ValueError(
                    "terminal CR has incomplete projection: " + incomplete_reason
                )
            return TerminationPlan(
                decision="NO_CHANGE",
                cr_id=cr_id,
                work_id=work_id,
                termination_reason=normalized_reason,
                terminal_tuple=terminal_tuple,
                expected_facts=facts,
                binding=binding,
                scope_digest=scope_digest,
                targets=(),
            )
        if current_tuple["lifecycle_status"] in FINISHED_STATUSES:
            raise ValueError(
                "a terminal CR cannot be changed to a different terminal state"
            )
        source_errors = cr_tracking.validate_native_status_tuple(*current_values)
        target_errors = cr_tracking.validate_native_status_tuple(*target_values)
        if source_errors or target_errors:
            raise ValueError("; ".join([*source_errors, *target_errors]))

        work = load_work(process_root, work_id)
        terminated_work = transition_work(work, "cancelled")
        project = load_project(process_root)
        if work.work_ref not in project.active_work_refs:
            raise ValueError("Project active_work_refs does not contain the target Work")
        terminated_project = replace(
            project,
            active_work_refs=tuple(
                ref for ref in project.active_work_refs if ref != work.work_ref
            ),
        )
        phase = load_phase(process_root, work.phase_ref) if work.phase_ref else None
        if phase is not None and work.work_ref not in phase.work_refs:
            raise ValueError("Phase work_refs does not contain the target Work")
        terminated_phase = (
            replace(
                phase,
                work_refs=tuple(ref for ref in phase.work_refs if ref != work.work_ref),
            )
            if phase is not None
            else None
        )

        index_path = _resolve_runtime_ref(release_root, CR_INDEX_REL.as_posix())
        existing_index: dict[str, Any] | None = None
        if index_path.is_file():
            existing_index = _load_json_object(index_path, subject="CR-INDEX")
            index_errors = validate_index_payload(existing_index)
            if index_errors:
                raise ValueError("; ".join(index_errors))
            formal_truth_index = build_index(release_root)
            if (
                existing_index.get("semantic_digest")
                != formal_truth_index.get("semantic_digest")
            ):
                raise ValueError("CR-INDEX differs from current formal truth")

        cr_after = render_frontmatter_fields(
            cr_before,
            {
                "lifecycle_status": terminal_tuple["lifecycle_status"],
                "readiness_status": terminal_tuple["readiness_status"],
                "gate_status": terminal_tuple["gate_status"],
                "status": terminal_tuple["lifecycle_status"],
            },
        )
        cr_after = _render_termination_body_projection(
            cr_after, terminal_tuple=terminal_tuple
        )
        summary_path = _resolve_runtime_ref(
            release_root,
            (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix(),
        )
        if summary_path.is_file():
            summary = _load_json_object(summary_path, subject="CR summary")
            if str(summary.get("id") or "") != cr_id:
                raise ValueError("CR summary identity mismatch")
            if str(summary.get("full_ref") or "") != _rel(release_root, cr_path):
                raise ValueError("CR summary full_ref mismatch")
        else:
            summary = summary_from_cr_file(release_root, cr_path)
            summary.pop("updated_at", None)
        summary.update(
            {
                "status": terminal_tuple["lifecycle_status"],
                "readiness": terminal_tuple["readiness_status"],
                "gate_status": terminal_tuple["gate_status"],
                "decision": terminal_tuple["lifecycle_status"],
                "termination_reason": normalized_reason,
                "terminal_tuple": terminal_tuple,
            }
        )
        summary_after = (
            json.dumps(
                summary,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        ledger_path = _resolve_runtime_ref(release_root, CR_LEDGER_REL.as_posix())
        ledger_event = {
            "event_id": _canonical_digest(
                {
                    "operation": TERMINATION_OPERATION,
                    "id": cr_id,
                    "work_id": work_id,
                    "termination_reason": normalized_reason,
                    "terminal_tuple": terminal_tuple,
                    "expected_facts": facts,
                    "scope_digest": scope_digest,
                }
            ),
            "event": "terminated",
            "event_type": "cr_termination",
            "id": cr_id,
            "work_id": work_id,
            "cr_type": normalize_cr_type(
                fields.get("cr_type") or fields.get("cr_kind") or "feature"
            ),
            "status": terminal_tuple["lifecycle_status"],
            "readiness": terminal_tuple["readiness_status"],
            "gate_status": terminal_tuple["gate_status"],
            "summary_ref": _rel(release_root, summary_path),
            "full_ref": _rel(release_root, cr_path),
            "termination_reason": normalized_reason,
            "terminal_tuple": terminal_tuple,
        }
        ledger_after = event_ledger.render_appended_event(ledger_path, ledger_event)
        projected_index = build_index(
            release_root,
            record_overrides={
                cr_id: {
                    "lifecycle_status": terminal_tuple[
                        "lifecycle_status"
                    ],
                    "readiness_status": terminal_tuple[
                        "readiness_status"
                    ],
                    "gate_status": terminal_tuple["gate_status"],
                    "status": terminal_tuple["lifecycle_status"],
                }
            },
        )
        projected_index["generated_at"] = (
            str(existing_index.get("generated_at") or "")
            if existing_index is not None
            else "1970-01-01T00:00:00+00:00"
        )
        index_after = (
            json.dumps(
                projected_index,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

        candidate_targets: list[TerminationTarget | None] = [
            _termination_target(release_root, 10, cr_path, cr_after, "truth"),
            _termination_target(
                release_root,
                20,
                process_root / work.work_ref,
                dump_yaml(terminated_work.as_dict()) + "\n",
                "truth",
            ),
            _termination_target(
                release_root,
                30,
                process_root / "PROJECT.yaml",
                dump_yaml(terminated_project.as_dict()) + "\n",
                "truth",
            ),
        ]
        if terminated_phase is not None:
            candidate_targets.append(
                _termination_target(
                    release_root,
                    40,
                    process_root / terminated_phase.phase_ref,
                    dump_yaml(terminated_phase.as_dict()) + "\n",
                    "truth",
                )
            )
        state_path = _resolve_runtime_ref(
            release_root, STATE_CURRENT_REL.as_posix()
        )
        if state_path.is_file():
            state = _load_json_object(state_path, subject="STATE.current.json")
            if state.get("active_change") == cr_id:
                state_after = current.render_current_state_candidate(
                    current.build_current_state_candidate(
                        release_root,
                        {
                            "active_change": None,
                            "active_context_ref": None,
                            "pending_gate": None,
                            "pending_checklist_path": None,
                            "next_action": {
                                "type": "done",
                                "text": (
                                    f"{cr_id} terminated as "
                                    f"{terminal_tuple['lifecycle_status']}."
                                ),
                                "stop_reason": "no_remaining_route",
                            },
                        },
                        actor="meta_flow.workflow.cr_lifecycle",
                        reason=f"terminate {cr_id}",
                    )
                )
                candidate_targets.append(
                    _termination_target(
                        release_root, 45, state_path, state_after, "truth"
                    )
                )
        candidate_targets.extend(
            [
                _termination_target(
                    release_root, 50, summary_path, summary_after, "derived"
                ),
                _termination_target(
                    release_root, 60, ledger_path, ledger_after, "derived"
                ),
                _termination_target(
                    release_root, 90, index_path, index_after, "derived"
                ),
            ]
        )
        targets = tuple(
            sorted(
                (target for target in candidate_targets if target is not None),
                key=lambda target: target.order,
            )
        )
        denied = [
            target.ref
            for target in targets
            if not check_scope(
                work.scope,
                "write",
                target.ref.removeprefix("process/"),
            ).allowed
        ]
        if denied:
            raise ValueError(
                "termination targets outside Work write scope: "
                + ", ".join(denied)
            )
        return TerminationPlan(
            decision="READY",
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            targets=targets,
        )
    except Exception as exc:
        return _blocked_termination_plan(
            cr_id=cr_id,
            work_id=work_id,
            termination_reason=normalized_reason,
            terminal_tuple=terminal_tuple,
            expected_facts=facts,
            binding=binding,
            scope_digest=scope_digest,
            reason=_portable_termination_error(
                exc,
                project_root=release_root,
                process_root=process_root,
            ),
        )


def load_termination_authorization(path: Path) -> TerminationAuthorization:
    payload = _load_json_object(path, subject="termination authorization")
    return TerminationAuthorization.from_dict(payload)


def validate_termination_authorization(
    plan: TerminationPlan,
    authorization: TerminationAuthorization,
) -> None:
    if plan.decision != "READY":
        raise ValueError("termination authorization requires one READY plan")
    if authorization.schema_version != 1:
        raise ValueError("termination authorization schema_version must be 1")
    if not SAFE_AUTHORIZATION_ID_RE.fullmatch(authorization.authorization_id):
        raise ValueError("termination authorization_id is invalid")
    if (
        authorization.authorization_source
        != TERMINATION_AUTHORIZATION_SOURCE
    ):
        raise ValueError(
            "termination authorization_source must be typed-user-confirmation"
        )
    if authorization.authorization_kind != TERMINATION_AUTHORIZATION_KIND:
        raise ValueError(
            "termination authorization_kind must be cr-termination"
        )
    if authorization.operation != TERMINATION_OPERATION:
        raise ValueError("termination authorization operation mismatch")
    if authorization.single_use is not True:
        raise ValueError("termination authorization must be single-use")
    expected = (
        plan.cr_id,
        plan.work_id,
        plan.termination_reason,
        plan.terminal_tuple,
        plan.expected_facts.get("target_release_oid", ""),
        plan.expected_facts.get("process_head_oid", ""),
        plan.scope_digest,
        plan.plan_digest,
    )
    actual = (
        authorization.cr_id,
        authorization.work_id,
        authorization.termination_reason,
        authorization.terminal_tuple,
        authorization.expected_release_oid,
        authorization.expected_process_oid,
        authorization.scope_digest,
        authorization.plan_digest,
    )
    if actual != expected:
        raise ValueError(
            "termination authorization does not match CR/Work/reason/tuple/OIDs/scope/plan"
        )
    if not OID_RE.fullmatch(authorization.expected_release_oid):
        raise ValueError("termination expected_release_oid is invalid")
    if not OID_RE.fullmatch(authorization.expected_process_oid):
        raise ValueError("termination expected_process_oid is invalid")
    if not DIGEST_RE.fullmatch(authorization.scope_digest):
        raise ValueError("termination scope_digest is invalid")
    if not DIGEST_RE.fullmatch(authorization.plan_digest):
        raise ValueError("termination plan_digest is invalid")
    try:
        expires_at = datetime.fromisoformat(
            authorization.expires_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("termination authorization expires_at is invalid") from exc
    if expires_at.tzinfo is None:
        raise ValueError(
            "termination authorization expires_at must include timezone"
        )
    if expires_at.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError("termination authorization is expired")


def _termination_private_root(project_root: Path) -> Path:
    return (
        _transaction_root(project_root).parent
        / "cr-termination"
    )


def _termination_claim_path(
    project_root: Path,
    authorization_id: str,
) -> Path:
    if not SAFE_AUTHORIZATION_ID_RE.fullmatch(authorization_id):
        raise ValueError("termination authorization_id is invalid")
    return (
        _termination_private_root(project_root)
        / "authorizations"
        / f"{authorization_id}.json"
    )


def _claim_termination_authorization(
    project_root: Path,
    plan: TerminationPlan,
    authorization: TerminationAuthorization,
) -> Path:
    validate_termination_authorization(plan, authorization)
    path = _termination_claim_path(project_root, authorization.authorization_id)
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
        "claimed_at": now_utc(),
    }
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
    except FileExistsError as exc:
        raise ValueError(
            "termination authorization was already consumed"
        ) from exc
    return path


def _termination_current_digest(target: TerminationTarget) -> str:
    if not target.path.is_file():
        return _canonical_digest("")
    return _canonical_digest(target.path.read_text(encoding="utf-8"))


def apply_cr_termination(
    project_root: Path,
    plan: TerminationPlan,
    *,
    authorization: TerminationAuthorization | None,
    expected_plan_digest: str,
    _fail_after_replace: int | None = None,
    _fail_recovery: bool = False,
    _fault: str = "",
) -> dict[str, Any]:
    """Apply one typed, exact-preimage termination transaction."""

    release_root = project_root.resolve()
    if plan.decision == "NO_CHANGE":
        return {
            "status": "NO_CHANGE",
            "plan_digest": plan.plan_digest,
            "mutation_count": 0,
            "path_refs": [],
        }
    if plan.decision != "READY":
        return {
            "status": "BLOCKED",
            "reason": plan.reason,
            "mutation_count": 0,
        }
    if not expected_plan_digest or expected_plan_digest != plan.plan_digest:
        return {
            "status": "BLOCKED",
            "reason": "expected plan digest does not match the current plan",
            "mutation_count": 0,
        }
    if authorization is None:
        return {
            "status": "BLOCKED",
            "reason": "termination apply requires typed authorization",
            "mutation_count": 0,
        }
    fresh = plan_cr_termination(
        release_root,
        plan.cr_id,
        work_id=plan.work_id,
        termination_status=plan.terminal_tuple["lifecycle_status"],
        termination_reason=plan.termination_reason,
        expected_process_oid=plan.expected_facts["process_head_oid"],
    )
    if fresh.decision != "READY" or fresh.plan_digest != plan.plan_digest:
        return {
            "status": "BLOCKED",
            "reason": "termination plan drifted before apply",
            "mutation_count": 0,
        }
    drifted = [
        target.ref
        for target in plan.targets
        if _termination_current_digest(target) != target.before_digest
    ]
    if drifted:
        return {
            "status": "BLOCKED",
            "reason": "termination target preimage drift: " + ", ".join(drifted),
            "mutation_count": 0,
        }
    try:
        validate_termination_authorization(plan, authorization)
    except ValueError as exc:
        return {
            "status": "BLOCKED",
            "reason": str(exc),
            "mutation_count": 0,
        }
    transaction_root = (
        _termination_private_root(release_root) / "transactions"
    )
    transaction_root.mkdir(parents=True, exist_ok=True)
    unresolved = list(transaction_root.glob("*/manifest.json"))
    if unresolved:
        return {
            "status": "BLOCKED",
            "reason": "unresolved CR termination transaction exists",
            "mutation_count": 0,
        }
    transaction_id = uuid.uuid4().hex
    lock_owner = _acquire_status_sync_writer_lock(
        release_root,
        transaction_id=transaction_id,
        purpose="cr-terminate",
    )
    if lock_owner is None:
        return {
            "status": "BLOCKED",
            "reason": "process writer lock exists",
            "mutation_count": 0,
        }
    transaction_dir = transaction_root / transaction_id
    backup_root = transaction_dir / "backups"
    after_root = transaction_dir / "after"
    backup_root.mkdir(parents=True)
    after_root.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "command": "cr terminate",
        "cr_id": plan.cr_id,
        "work_id": plan.work_id,
        "termination_reason": plan.termination_reason,
        "terminal_tuple": plan.terminal_tuple,
        "expected_facts": plan.expected_facts,
        "scope_digest": plan.scope_digest,
        "plan_digest": plan.plan_digest,
        "authorization_id": authorization.authorization_id,
        "lock": dict(lock_owner),
        "targets": [],
        "receipts": [],
        "recovery_state": "prepared",
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    applied: list[TerminationTarget] = []
    manifest_path = transaction_dir / "manifest.json"
    try:
        _claim_termination_authorization(release_root, plan, authorization)
        if _fault == "after-claim-before-first-replace":
            raise RuntimeError(
                "injected failure after authorization claim"
            )
        for target in plan.targets:
            backup = backup_root / f"{target.order:03d}.before"
            prepared_after = after_root / f"{target.order:03d}.after"
            backup.write_text(target.before or "", encoding="utf-8")
            prepared_after.write_text(target.after, encoding="utf-8")
            if (
                _canonical_digest(backup.read_text(encoding="utf-8"))
                != target.before_digest
            ):
                raise RuntimeError(f"backup digest mismatch: {target.ref}")
            if (
                _canonical_digest(
                    prepared_after.read_text(encoding="utf-8")
                )
                != target.after_digest
            ):
                raise RuntimeError(
                    f"prepared after digest mismatch: {target.ref}"
                )
            manifest["targets"].append(
                {
                    **target.as_dict(),
                    "before_content_ref": f"backups/{backup.name}",
                    "after_content_ref": f"after/{prepared_after.name}",
                    "apply_status": "prepared",
                    "rollback_status": "not-required",
                }
            )
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest["recovery_state"] = "applying"
        for offset, target in enumerate(plan.targets, 1):
            _atomic_write_text(target.path, target.after)
            applied.append(target)
            manifest["targets"][offset - 1]["apply_status"] = "applied"
            manifest["receipts"].append(
                {
                    "target_ref": target.ref,
                    "observed_before_digest": target.before_digest,
                    "observed_after_digest": _termination_current_digest(
                        target
                    ),
                    "completed_at": now_utc(),
                }
            )
            manifest["updated_at"] = now_utc()
            manifest_path.write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            if _fail_after_replace == offset:
                raise RuntimeError(
                    f"injected failure after replace {offset}"
                )
        readback_failures = [
            target.ref
            for target in plan.targets
            if _termination_current_digest(target) != target.after_digest
        ]
        if readback_failures:
            raise RuntimeError(
                "termination read-back mismatch: "
                + ", ".join(readback_failures)
            )
        manifest["recovery_state"] = "committed"
        manifest["lock"]["lease_state"] = "released"
        manifest["updated_at"] = now_utc()
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(transaction_dir)
        return {
            "status": "PASS",
            "transaction_id": transaction_id,
            "plan_digest": plan.plan_digest,
            "authorization_id": authorization.authorization_id,
            "mutation_count": len(plan.targets),
            "path_refs": [target.ref for target in plan.targets],
        }
    except Exception as exc:
        recovery_errors: list[str] = []
        for target in reversed(applied):
            try:
                if _fail_recovery:
                    raise RuntimeError("injected rollback failure")
                if target.before is None:
                    target.path.unlink(missing_ok=True)
                else:
                    _atomic_write_text(target.path, target.before)
                if (
                    _termination_current_digest(target)
                    != target.before_digest
                ):
                    raise RuntimeError("rollback digest mismatch")
                for entry in manifest["targets"]:
                    if entry["ref"] == target.ref:
                        entry["rollback_status"] = "restored"
            except Exception as recovery_error:
                recovery_errors.append(
                    f"{target.ref}: {recovery_error}"
                )
        status = (
            "PARTIAL"
            if recovery_errors
            else "RECOVERED"
            if applied
            else "BLOCKED"
        )
        manifest["recovery_state"] = status.lower()
        manifest["lock"]["lease_state"] = "released"
        manifest["updated_at"] = now_utc()
        if manifest_path.parent.is_dir():
            manifest_path.write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        if status in {"BLOCKED", "RECOVERED"}:
            shutil.rmtree(transaction_dir)
        result = {
            "status": status,
            "transaction_id": transaction_id,
            "plan_digest": plan.plan_digest,
            "authorization_id": authorization.authorization_id,
            "mutation_count": len(applied),
            "reason": str(exc),
            "rollback_errors": recovery_errors,
        }
        if status == "PARTIAL":
            result["rollback_evidence_ref"] = (
                "private://cr-termination/transactions/"
                f"{transaction_id}/manifest.json"
            )
        return result
    finally:
        _release_status_sync_writer_lock(release_root, lock_owner)


def sync_cr_status(
    project_root: Path,
    cr_id: str,
    *,
    status: str = "",
    readiness: str = "",
    gate_status: str = "",
    work_id: str = "",
    historical_migration: bool = False,
    historical_gate_status: str = "",
    historical_lifecycle_status: str = "",
    expected_process_oid: str = "",
    effective_at: str = "",
    expected_plan_digest: str = "",
    authorization: StatusSyncAuthorization | None = None,
) -> dict[str, Path]:
    """Compatibility API backed by the typed recoverable plan/apply transaction."""

    plan = plan_status_sync(
        project_root,
        cr_id,
        status=status,
        readiness=readiness,
        gate_status=gate_status,
        work_id=work_id,
        historical_migration=historical_migration,
        historical_gate_status=historical_gate_status,
        historical_lifecycle_status=historical_lifecycle_status,
        expected_process_oid=expected_process_oid,
        effective_at=effective_at,
    )
    result = apply_status_sync(
        project_root,
        plan,
        authorization=authorization,
        expected_plan_digest=expected_plan_digest,
    )
    if result["status"] not in {"PASS", "NO_CHANGE"}:
        raise RuntimeError(f"status-sync {result['status']}: {result.get('reason', '')}")
    if result["status"] == "NO_CHANGE":
        cr_path = discover_formal_crs(project_root)[cr_id]
        return {
            "cr": cr_path,
            "summary": _resolve_runtime_ref(
                project_root,
                (CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix(),
            ),
            "evidence_index": _resolve_runtime_ref(
                project_root,
                (CR_ARCHIVE_ROOT_REL / cr_id / "evidence-index.json").as_posix(),
            ),
            "index": _resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix()),
            "ledger": _resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix()),
        }
    by_ref = result["paths"]
    return {
        "cr": by_ref[_rel(project_root, discover_formal_crs(project_root)[cr_id])],
        "summary": by_ref[(CR_SUMMARY_ROOT_REL / f"{cr_id}.summary.json").as_posix()],
        "evidence_index": by_ref[(CR_ARCHIVE_ROOT_REL / cr_id / "evidence-index.json").as_posix()],
        "index": by_ref[CR_INDEX_REL.as_posix()],
        "ledger": by_ref[CR_LEDGER_REL.as_posix()],
    }


def collect_check_errors(project_root: Path) -> list[str]:
    project_root = project_root.resolve()
    errors: list[str] = []
    try:
        events = load_ledger_events(project_root)
    except ValueError as exc:
        return [str(exc)]
    try:
        index = load_index(project_root)
    except ValueError as exc:
        index = {}
        errors.append(str(exc))
    try:
        expected_index = build_index(project_root)
    except ValueError as exc:
        expected_index = {}
        errors.append(str(exc))
    if index:
        errors.extend(validate_index_payload(index))
        if (
            expected_index
            and index.get("semantic_digest") != expected_index.get("semantic_digest")
        ):
            errors.append(
                "CR-INDEX stale projection differs from formal truth rebuild digest"
            )
    items = {item.get("id"): item for item in index.get("items", []) if isinstance(item, dict)}
    current_path = _resolve_runtime_ref(project_root, STATE_CURRENT_REL.as_posix())
    current_state: dict[str, Any] = {}
    if current_path.is_file():
        try:
            current_state = json.loads(current_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{current_path} invalid JSON: {exc}")
    for event in events:
        cr_id = event.get("id")
        status = event.get("status")
        cr_type = event.get("cr_type")
        if status and status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(f"CR ledger event {cr_id}: invalid status {status}")
        if cr_type and cr_type not in ALLOWED_CR_TYPES:
            errors.append(f"CR ledger event {cr_id}: invalid cr_type {cr_type}")
        summary_ref = event.get("summary_ref")
        if status == "closed":
            if not summary_ref:
                errors.append(f"closed CR {cr_id} missing summary_ref")
            elif not _resolve_runtime_ref(project_root, str(summary_ref)).is_file():
                errors.append(f"closed CR {cr_id} summary_ref missing on disk: {summary_ref}")
            if current_state.get("active_change") == cr_id:
                errors.append(f"STATE.current.json active_change points to closed CR: {cr_id}")
        if cr_id and cr_id in items:
            index_status = items[cr_id].get("status")
            if status == "closed" and index_status not in {
                "closed",
                "active",
                "implemented",
                "verified",
                "ready",
            }:
                errors.append(f"CR index status for {cr_id} is inconsistent: {index_status}")
    for item_id, item in items.items():
        status = item.get("status")
        if status in FINISHED_STATUSES and not item.get("summary_ref"):
            errors.append(f"CR index finished item {item_id} missing summary_ref")
        if status and status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(f"CR index item {item_id}: invalid status {status}")
        cr_type = item.get("cr_type")
        if cr_type and cr_type not in ALLOWED_CR_TYPES:
            errors.append(f"CR index item {item_id}: invalid cr_type {cr_type}")
    for cr_id, path in discover_formal_crs(project_root).items():
        text = path.read_text(encoding="utf-8")
        frontmatter_fields = parse_frontmatter(text)
        record = record_from_cr_file(project_root, path)
        has_route_contract = bool(frontmatter_fields.get("route_plan_ref")) or any(
            str(key).startswith("cr_trait_") for key in frontmatter_fields
        )
        if record.status not in FINISHED_STATUSES and has_route_contract:
            route_errors, _route_warnings = route_plan.validate_route_plan_for_cr(
                project_root, path
            )
            errors.extend(route_errors)
        blockers, _needs_review = collect_scope_authz_findings(record, text=text)
        for blocker in blockers:
            capabilities = ", ".join(blocker.get("required_capabilities") or [])
            evidence = ", ".join(blocker.get("required_evidence") or [])
            suffix = f" evidence={evidence}" if evidence else ""
            errors.append(
                f"{cr_id} scope/authz {blocker.get('level')} {blocker.get('code')}: "
                f"required_capabilities={capabilities}{suffix}"
            )
    return errors


def collect_check_warnings(project_root: Path) -> list[str]:
    project_root = project_root.resolve()
    warnings: list[str] = []
    for cr_id, path in discover_formal_crs(project_root).items():
        frontmatter_fields = parse_frontmatter(path.read_text(encoding="utf-8"))
        record = record_from_cr_file(project_root, path)
        has_route_contract = bool(frontmatter_fields.get("route_plan_ref")) or any(
            str(key).startswith("cr_trait_") for key in frontmatter_fields
        )
        if record.status not in FINISHED_STATUSES and has_route_contract:
            _route_errors, route_warnings = route_plan.validate_route_plan_for_cr(
                project_root, path
            )
            warnings.extend(route_warnings)
        for finding in collect_governance_dependency_findings(project_root, record):
            markers = ", ".join(finding.get("marker_overlap") or [])
            direct = ", ".join(finding.get("direct_overlap") or [])
            overlap = markers or direct or "-"
            warnings.append(
                f"{cr_id} governance dependency {finding.get('code')}: "
                f"governance_cr={finding.get('governance_cr')} overlap={overlap} "
                f"decision={finding.get('decision')}"
            )
        for finding in collect_archive_isolation_findings(record, project_root=project_root):
            refs = ", ".join(finding.get("archive_refs") or [])
            warnings.append(
                f"{cr_id} archive isolation {finding.get('code')}: "
                f"archive_refs={refs or '-'} decision={finding.get('decision')}"
            )
    return warnings


def _conflict_surface(item: dict[str, Any]) -> set[str]:
    values: list[str] = []
    values.extend(str(value) for value in item.get("impact_surface") or [] if str(value))
    for field in IMPACT_SPLIT_FIELDS:
        values.extend(str(value) for value in item.get(field) or [] if str(value))
    values.extend(
        str(value) for value in item.get("impact_capability_normalized") or [] if str(value)
    )
    return set(values)


def conflict_report(project_root: Path, cr_id: str) -> tuple[list[str], list[str]]:
    project_root = project_root.resolve()
    index = load_index(project_root)
    items = [item for item in index.get("items", []) if isinstance(item, dict)]
    target = next((item for item in items if item.get("id") == cr_id), None)
    if not target:
        raise FileNotFoundError(f"CR index 中未找到 {cr_id}；请先运行 meta-flow cr index")
    target_keys = set(target.get("conflict_keys") or [])
    target_surface = _conflict_surface(target)
    conflicts: list[str] = []
    warnings: list[str] = []
    for item in items:
        other_id = item.get("id")
        if other_id == cr_id:
            continue
        if item.get("status") not in {"active", "blocked", "proposed"}:
            continue
        key_overlap = target_keys.intersection(item.get("conflict_keys") or [])
        surface_overlap = target_surface.intersection(_conflict_surface(item))
        if key_overlap or surface_overlap:
            conflicts.append(
                f"{cr_id} overlaps {other_id}: conflict_keys={sorted(key_overlap)} impact_surface={sorted(surface_overlap)}"
            )
    if not target_keys and not target_surface:
        warnings.append(
            f"{cr_id} has no conflict_keys or impact fields; conflict detection is weak"
        )
    return conflicts, warnings


def proposed_conflict_report(
    project_root: Path,
    *,
    cr_id: str,
    conflict_keys: list[str],
    impact_surface: list[str],
    impact_fields: dict[str, list[str]],
    title: str = "",
    scope: str = "",
) -> dict[str, Any]:
    """Preview one transient CR candidate without writing lifecycle artifacts."""

    project_root = project_root.resolve()
    if not CR_ID_RE.fullmatch(cr_id):
        return {
            "decision": "INVALID",
            "code": "CR_CONFLICT_PROPOSED_INPUT_INVALID",
            "cr_id": cr_id,
            "mutation_count": 0,
            "planned_mutation_count": 0,
            "conflicts": [],
            "warnings": [],
        }
    index = load_index(project_root)
    items = [item for item in index.get("items", []) if isinstance(item, dict)]
    if any(str(item.get("id") or "") == cr_id for item in items):
        return {
            "decision": "INVALID",
            "code": "CR_CONFLICT_PROPOSED_ID_EXISTS",
            "cr_id": cr_id,
            "mutation_count": 0,
            "planned_mutation_count": 0,
            "conflicts": [],
            "warnings": [],
        }

    normalized_keys = sorted(set(value.strip() for value in conflict_keys if value.strip()))
    normalized_surface = sorted(
        set(value.strip() for value in impact_surface if value.strip())
    )
    normalized_fields = {
        field: sorted(
            set(value.strip() for value in impact_fields.get(field, []) if value.strip())
        )
        for field in IMPACT_SPLIT_FIELDS
    }
    if not normalized_keys and not normalized_surface and not any(normalized_fields.values()):
        return {
            "decision": "INVALID",
            "code": "CR_CONFLICT_PROPOSED_INPUT_REQUIRED",
            "cr_id": cr_id,
            "mutation_count": 0,
            "planned_mutation_count": 0,
            "conflicts": [],
            "warnings": [],
        }

    capability_resolution = _resolve_capability_refs(
        project_root,
        normalized_fields["impact_capability_refs"],
        mode="audit",
    )
    candidate = {
        "id": cr_id,
        "title": title,
        "scope": scope,
        "status": "proposed",
        "conflict_keys": normalized_keys,
        "impact_surface": normalized_surface,
        **normalized_fields,
        "impact_capability_normalized": _normalized_capability_refs(
            capability_resolution
        ),
    }
    candidate_keys = set(candidate["conflict_keys"])
    candidate_surface = _conflict_surface(candidate)
    conflicts: list[dict[str, Any]] = []
    for item in sorted(
        items, key=lambda value: _cr_numeric_sort_key(str(value.get("id") or ""))
    ):
        if item.get("status") not in OPEN_DEPENDENCY_STATUSES:
            continue
        key_overlap = sorted(candidate_keys.intersection(item.get("conflict_keys") or []))
        surface_overlap = sorted(candidate_surface.intersection(_conflict_surface(item)))
        if key_overlap or surface_overlap:
            conflicts.append(
                {
                    "existing_cr_id": str(item.get("id") or ""),
                    "matched_conflict_keys": key_overlap,
                    "matched_impact_surface": surface_overlap,
                }
            )
    return {
        "decision": "CONFLICT" if conflicts else "NO_CONFLICT",
        "code": "CR_CONFLICT" if conflicts else "CR_CONFLICT_NONE",
        "cr_id": cr_id,
        "mutation_count": 0,
        "planned_mutation_count": 0,
        "candidate": candidate,
        "conflicts": conflicts,
        "warnings": [],
    }


def build_impact_report(project_root: Path, *, mode: str = "enforce") -> dict[str, Any]:
    project_root = project_root.resolve()
    if mode not in {"audit", "enforce"}:
        raise ValueError("mode must be audit or enforce")
    items: list[dict[str, Any]] = []
    blocker_count = 0
    uncategorized_cr_count = 0
    uncategorized_legacy_count = 0
    for cr_id, path in discover_formal_crs(project_root).items():
        record = record_from_cr_file(project_root, path)
        explicit = _impact_split_payload(record)
        derived_from_legacy = _categorized_legacy_impact(
            record.impact_surface, project_root=project_root
        )
        uncategorized_legacy = _uncategorized_legacy_impact(
            record.impact_surface, project_root=project_root
        )
        if uncategorized_legacy:
            uncategorized_cr_count += 1
            uncategorized_legacy_count += len(uncategorized_legacy)
        effective = _effective_impact_fields(record, project_root=project_root)
        capability_resolution = _resolve_capability_refs(
            project_root,
            effective["impact_capability_refs"],
            mode=mode,
        )
        blockers = _capability_blockers(capability_resolution)
        blocker_count += len(blockers)
        items.append(
            {
                "id": cr_id,
                "title": record.title,
                "status": record.status,
                "full_ref": record.full_ref,
                "old_impact_surface": record.impact_surface,
                "explicit_split_fields": explicit,
                "derived_from_legacy": derived_from_legacy,
                "uncategorized_legacy": uncategorized_legacy,
                "effective_split_fields": effective,
                "impact_capability_resolution": capability_resolution,
                "impact_capability_normalized": _normalized_capability_refs(capability_resolution),
                "blockers": blockers,
                "followup_candidates": _impact_followup_candidates(cr_id, uncategorized_legacy),
            }
        )
    return {
        "schema_version": 1,
        "kind": "cr-impact-surface-migration-report",
        "generated_at": now_utc(),
        "mode": mode,
        "write_policy": "side-effect-free",
        "canonical_registry_written": False,
        "summary": {
            "cr_count": len(items),
            "blocker_count": blocker_count,
            "uncategorized_cr_count": uncategorized_cr_count,
            "uncategorized_legacy_count": uncategorized_legacy_count,
        },
        "items": sorted(items, key=lambda item: item["id"]),
    }


def write_impact_report(path: Path, report: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _load_summary(project_root: Path, cr_id: str) -> dict[str, Any]:
    path = _resolve_runtime_ref(project_root, CR_SUMMARY_ROOT_REL.as_posix()) / f"{cr_id}.summary.json"
    if not path.is_file():
        crs = discover_formal_crs(project_root)
        if cr_id not in crs:
            raise FileNotFoundError(f"未找到正式 CR: {cr_id}")
        return summary_from_cr_file(project_root, crs[cr_id])
    return json.loads(path.read_text(encoding="utf-8"))


def render_cr_brief(project_root: Path, cr_id: str, *, mode: str = "audit") -> str:
    if mode not in {"audit", "enforce"}:
        raise ValueError("mode must be audit or enforce")
    root = project_root.resolve()
    summary = _load_summary(root, cr_id)
    record: CRRecord | None = None
    crs = discover_formal_crs(root)
    if cr_id in crs:
        record = record_from_cr_file(root, crs[cr_id])
    capability_refs = (
        _effective_impact_fields(record, project_root=root)["impact_capability_refs"]
        if record is not None
        else [str(item) for item in summary.get("impact_capability_refs") or [] if str(item)]
    )
    capability_resolution = _resolve_capability_refs(root, capability_refs, mode=mode)
    capability_normalized = _normalized_capability_refs(capability_resolution)
    lines = [
        f"# {summary.get('id')} {summary.get('title')}",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| 目标 | {summary.get('goal_statement') or summary.get('scope_summary', [''])[0]} |",
        f"| 目标引用 | {summary.get('goal_ref') or '-'} |",
        f"| 用户目标影响 | {summary.get('user_goal_impact') or '-'} |",
        f"| CR 类型 / 状态 | {summary.get('cr_type')} / {summary.get('status')} |",
        f"| gate / readiness | {summary.get('gate_status') or '-'} / {summary.get('readiness') or '-'} |",
        f"| 审批重点 | {summary.get('approval_focus') or '-'} |",
        f"| 决策负担 | {summary.get('decision_burden') or '-'} |",
        f"| 拆分理由 | {summary.get('split_rationale') or '-'} |",
        f"| approve 后果 | {summary.get('approve_effect') or '-'} |",
        f"| reject 后果 | {summary.get('reject_effect') or '-'} |",
        f"| 完整 CR | `{summary.get('full_ref')}` |",
    ]
    not_authorized = summary.get("not_authorized_by_approve") or []
    if not_authorized:
        lines.extend(["", "## approve 不授权", ""])
        lines.extend(f"- {item}" for item in not_authorized)
    if summary.get("impact_surface"):
        lines.extend(["", "## 影响面", ""])
        lines.extend(f"- {item}" for item in summary.get("impact_surface", []))
    uncategorized_legacy = (
        _uncategorized_legacy_impact(record.impact_surface, project_root=root)
        if record is not None
        else _uncategorized_legacy_impact(
            [str(item) for item in summary.get("impact_surface") or [] if str(item)],
            project_root=root,
        )
    )
    split_lines: list[str] = []
    split_labels = {
        "impact_capability_refs": "capability",
        "impact_feature_refs": "feature",
        "impact_module_paths": "module",
        "impact_policy_refs": "policy",
        "impact_process_refs": "process",
        "impact_runtime_refs": "runtime",
        "impact_data_refs": "data",
    }
    for field, label in split_labels.items():
        for value in summary.get(field) or []:
            split_lines.append(f"- {label}: {value}")
    for value in capability_normalized:
        split_lines.append(f"- capability.normalized: {value}")
    if capability_refs:
        split_lines.append(f"- capability.resolution_mode: {mode}")
    if split_lines:
        lines.extend(["", "## 结构化影响面", ""])
        lines.extend(split_lines)
    if uncategorized_legacy:
        lines.extend(["", "## 未分类 legacy impact_surface", ""])
        lines.extend(f"- {item}" for item in uncategorized_legacy)
        for candidate in _impact_followup_candidates(
            str(summary.get("id") or cr_id), uncategorized_legacy
        ):
            lines.append(f"- follow-up candidate: {candidate['candidate_id']}")
    capability_blockers = _capability_blockers(capability_resolution)
    if capability_blockers:
        lines.extend(["", "## capability ref blockers", ""])
        lines.extend(
            f"- {item['input_ref']}: {item['status']} {item['code']}"
            for item in capability_blockers
        )
    return "\n".join(lines) + "\n"


def render_goal_brief(project_root: Path, goal_ref: str) -> str:
    index = load_index(project_root.resolve())
    items = [
        item
        for item in index.get("items", [])
        if isinstance(item, dict) and item.get("goal_ref") == goal_ref
    ]
    if not items:
        raise FileNotFoundError(
            f"CR-INDEX.json 中未找到 goal_ref={goal_ref!r} 的 CR；请先运行 meta-flow cr index"
        )
    lines = [
        f"# Goal Brief: {goal_ref}",
        "",
        "| CR | 状态 | 类型 | 目标贡献 | 决策负担 | gate |",
        "|---|---|---|---|---|---|",
    ]
    for item in items:
        summary: dict[str, Any]
        try:
            summary = _load_summary(project_root, str(item["id"]))
        except (FileNotFoundError, json.JSONDecodeError):
            summary = item
        contribution = (
            summary.get("user_goal_impact")
            or summary.get("goal_statement")
            or item.get("title")
            or "-"
        )
        lines.append(
            f"| `{item.get('id')}` | {item.get('status')} | {item.get('cr_type')} | {contribution} | "
            f"{item.get('decision_burden') or '-'} | {item.get('gate_status') or '-'} |"
        )
    return "\n".join(lines) + "\n"


def aggregate_main(argv: list[str] | None = None) -> int:
    """Run the explicit CR-051 aggregate evidence gate without implicit lifecycle actions."""
    from meta_flow.workflow.artifact_aggregate import (
        AggregateRequest,
        FileAggregateStore,
        PersistDisposition,
        ProjectFileLegResultReader,
        ProjectionStatus,
        coordinate_aggregate,
    )

    parser = argparse.ArgumentParser(
        prog="meta-flow cr aggregate",
        description=(
            "Validate explicit source/artifact published handles, compute the aggregate, and "
            "optionally persist or project a 2/2 PASS through controlled writers."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", dest="cr_id", required=True)
    parser.add_argument("--project-id", default="")
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--source-handle", type=Path, required=True)
    parser.add_argument("--artifact-handle", type=Path, required=True)
    parser.add_argument("--source-mode", choices=("source-default",), default="source-default")
    parser.add_argument(
        "--artifact-mode",
        choices=("shared-artifact-project-first",),
        default="shared-artifact-project-first",
    )
    parser.add_argument("--policy-version", default="aggregate-v1")
    parser.add_argument("--expected-current-ref", default=None)
    parser.add_argument("--store-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project-completion", action="store_true")
    parser.add_argument("--expected-state-updated-at", default="")
    parsed = parser.parse_args(list(argv or []))
    if not CR_ID_RE.fullmatch(parsed.cr_id):
        parser.error("--id must use CR-xxx naming")
    if parsed.project_completion and parsed.dry_run:
        parser.error("--project-completion cannot be combined with --dry-run")
    if parsed.project_completion and not parsed.expected_state_updated_at:
        parser.error("--expected-state-updated-at is required with --project-completion")

    project_root = parsed.project_root.resolve()
    handles: list[dict[str, Any]] = []
    for label, path in (
        ("source", parsed.source_handle),
        ("artifact", parsed.artifact_handle),
    ):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"unable to read {label} handle: {exc}")
        if not isinstance(payload, dict):
            parser.error(f"{label} handle must be a JSON object")
        handles.append(payload)

    request = AggregateRequest(
        operation_id=parsed.operation_id,
        logical_attempt=parsed.attempt,
        cr_id=parsed.cr_id,
        project_id=parsed.project_id or project_root.name,
        required_legs=("source", "artifact"),
        expected_modes=(
            ("source", parsed.source_mode),
            ("artifact", parsed.artifact_mode),
        ),
        policy_version=parsed.policy_version,
    )
    reader = ProjectFileLegResultReader(project_root)
    store_root = parsed.store_root
    if store_root is not None and not store_root.is_absolute():
        store_root = project_root / store_root
    store = (
        None
        if parsed.dry_run
        else FileAggregateStore(project_root=project_root, store_root=store_root)
    )
    projector = (
        AggregateCompletionProjector(
            project_root=project_root,
            expected_state_updated_at=parsed.expected_state_updated_at,
        )
        if parsed.project_completion
        else None
    )
    command = coordinate_aggregate(
        request,
        handles,
        reader=reader,
        store=store,
        projector=projector,
        expected_current_ref=parsed.expected_current_ref,
        dry_run=parsed.dry_run,
        project=parsed.project_completion,
    )
    print(json.dumps(command.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    if command.validation_errors:
        return 2
    if command.write_receipt is not None and command.write_receipt.disposition in {
        PersistDisposition.CONFLICT,
        PersistDisposition.FAILED,
    }:
        return 3
    if command.projection_receipt is not None and command.projection_receipt.status in {
        ProjectionStatus.PARTIAL,
        ProjectionStatus.FAILED,
    }:
        return 4
    return 0


def _print_cr_help() -> None:
    print(
        "usage: meta-flow cr <command> [options]\n\n"
        "Commands:\n"
        "  bootstrap  Create an active bootstrap CR plus summary, index, ledger, CP0 result, and context.\n"
        "  index      Preview a pure CR-INDEX projection; --apply writes it and --rebuild acknowledges corrupt bytes.\n"
        "  summary    Generate process/changes/summaries/<CR>.summary.json.\n"
        "  brief      Print a goal-oriented CR brief from summary/frontmatter.\n"
        "  goal-brief Print all CRs attached to one goal_ref.\n"
        "  impact-report Print a side-effect-free impact surface migration report as JSON.\n"
        "  terminate  Plan or apply an exact-OID, typed, recoverable native CR termination.\n"
        "  status-sync Plan or apply a typed CR status projection transaction.\n"
        "  status-sync-inspect Inspect unresolved private status-sync manifests.\n"
        "  status-sync-resume Resume one explicitly selected unresolved transaction.\n"
        "  status-sync-rollback Roll back one explicitly selected unresolved transaction.\n"
        "  status-sync-abandon Mark one inspected transaction abandoned with typed authorization.\n"
        "  aggregate  Validate explicit published leg handles and persist/project a guarded aggregate.\n"
        "  branch-open Open paired project/artifact CR branches from fresh remote defaults.\n"
        "  branch-publish Publish existing committed CR refs; never stage or commit.\n"
        "  branch-merge Explicitly fast-forward paired remote defaults from published tips.\n"
        "  branch-finish Re-prove merge facts, retain recovery refs, then clean CR branches.\n"
        "  close      Compatibility alias for a typed closed status-sync transaction.\n"
        "  check      Validate CR ledger, index, summaries, and active state refs.\n"
        "  public-operations-check Validate the public operation registry and console discovery.\n"
        "  conflicts  Compare active/proposed/blocked CR conflict keys from CR-INDEX.json.\n\n"
        "Examples:\n"
        '  meta-flow cr bootstrap --id CR-001 --title "target adoption bootstrap" --scope "Initialize Meta Flow adoption readiness." --project-root .\n'
        "  meta-flow cr index --project-root .\n"
        "  meta-flow cr index --project-root . --apply --expected-process-oid <oid>\n"
        "  meta-flow cr summary --id CR-101 --project-root .\n"
        "  meta-flow cr brief --id CR-101 --project-root .\n"
        "  meta-flow cr brief --id CR-101 --mode enforce --project-root .\n"
        "  meta-flow cr goal-brief --goal-ref GOAL-001 --project-root .\n"
        "  meta-flow cr impact-report --project-root .\n"
        '  meta-flow cr terminate --id CR-101 --work-id WORK-101 --status cancelled --reason "superseded by a clean replacement" --expected-process-oid <oid> --project-root .\n'
        '  meta-flow cr terminate --id CR-101 --work-id WORK-101 --status cancelled --reason "superseded by a clean replacement" --expected-process-oid <oid> --expected-plan-digest <digest> --authorization-file authorization.json --apply --project-root .\n'
        "  meta-flow cr status-sync --id CR-101 --status closed --readiness READY_WITH_RISK --gate-status cp8_closed --work-id WORK-101 --effective-at <timestamp> --project-root .\n"
        "  meta-flow cr status-sync --id CR-101 --status closed --work-id WORK-101 --effective-at <timestamp> --project-root . --apply --expected-process-oid <oid> --expected-plan-digest <digest> --authorization-file authorization.json\n"
        "  meta-flow cr aggregate --id CR-051 --operation-id operation-001 --attempt 1 --source-handle source.json --artifact-handle artifact.json --dry-run --project-root .\n"
        "  meta-flow cr branch-open --id CR-101 --slug safe-change --dry-run --project-root .\n"
        "  meta-flow cr branch-publish --id CR-101 --branch cr/cr-101-safe-change --dry-run --project-root .\n"
        "  meta-flow cr branch-merge --id CR-101 --branch cr/cr-101-safe-change --publish-result publish.json --dry-run --project-root .\n"
        "  meta-flow cr branch-finish --id CR-101 --branch cr/cr-101-safe-change --merge-result merge.json --dry-run --project-root .\n"
        "  meta-flow cr close --id CR-101 --readiness READY_WITH_RISK --work-id WORK-101 --effective-at <timestamp> --project-root .\n"
        "  meta-flow cr public-operations-check --project-root .\n"
        "  meta-flow cr conflicts --id CR-102 --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_cr_help()
        return 0
    command = args[0]
    if command == "aggregate":
        return aggregate_main(args[1:])
    if command == "public-operations-check":
        from meta_flow.policies import public_operations

        return public_operations.main(args[1:])
    if command in {"branch-open", "branch-publish", "branch-merge", "branch-finish"}:
        from meta_flow.workflow.git_branch_lifecycle import branch_main

        return branch_main(command, args[1:])
    parser = argparse.ArgumentParser(prog=f"meta-flow cr {command}")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", dest="cr_id", default="")
    parser.add_argument("--title", default="Meta Flow adoption bootstrap")
    parser.add_argument(
        "--scope", default="Bootstrap Meta Flow adoption readiness for this target project."
    )
    parser.add_argument(
        "--gate-status",
        default="cp2_pending",
        help="Gate status; status-sync --status closed uses and requires cp8_closed.",
    )
    parser.add_argument("--readiness", default="READY")
    parser.add_argument("--status", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--expected-process-oid", default="")
    parser.add_argument("--expected-plan-digest", default="")
    parser.add_argument("--effective-at", default="")
    parser.add_argument("--work-id", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--authorization-file", type=Path, default=None)
    parser.add_argument("--historical-migration", action="store_true")
    parser.add_argument("--historical-gate-status", default="")
    parser.add_argument("--historical-lifecycle-status", default="")
    parser.add_argument("--transaction-id", default="")
    parser.add_argument("--typed-authorized", action="store_true")
    parser.add_argument("--goal-ref", default="")
    parser.add_argument("--mode", choices=["audit", "enforce"], default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--proposed", action="store_true")
    parser.add_argument("--conflict-key", action="append", default=[])
    parser.add_argument("--impact-surface", action="append", default=[])
    parser.add_argument("--impact-capability-ref", action="append", default=[])
    parser.add_argument("--impact-feature-ref", action="append", default=[])
    parser.add_argument("--impact-module-path", action="append", default=[])
    parser.add_argument("--impact-policy-ref", action="append", default=[])
    parser.add_argument("--impact-process-ref", action="append", default=[])
    parser.add_argument("--impact-runtime-ref", action="append", default=[])
    parser.add_argument("--impact-data-ref", action="append", default=[])
    parsed = parser.parse_args(args[1:])
    project_root = parsed.project_root.resolve()

    if command == "bootstrap":
        if not parsed.cr_id:
            raise SystemExit("--id is required and must use CR-xxx naming")
        paths = bootstrap_cr(
            project_root,
            cr_id=parsed.cr_id,
            title=parsed.title,
            scope=parsed.scope,
            gate_status=parsed.gate_status,
            readiness=parsed.readiness,
        )
        for key, path in paths.items():
            print(f"{key}: {path}")
        return 0
    if command == "index":
        plan = plan_index(project_root, rebuild_corrupt=parsed.rebuild)
        printable = {key: value for key, value in plan.items() if key != "expected"}
        if not parsed.apply:
            print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if plan["decision"] == "READY" else 1
        if plan["decision"] != "READY":
            print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
            return 1
        path = write_index(
            project_root,
            rebuild_corrupt=parsed.rebuild,
            expected_process_oid=parsed.expected_process_oid,
        )
        print(json.dumps({**printable, "wrote": _rel(project_root, path)}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command == "summary":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        crs = discover_formal_crs(project_root)
        if parsed.cr_id not in crs:
            raise SystemExit(f"未找到正式 CR: {parsed.cr_id}")
        summary = summary_from_cr_file(project_root, crs[parsed.cr_id])
        path = write_summary(project_root, parsed.cr_id, summary)
        print(f"wrote: {path}")
        return 0
    if command == "brief":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        print(render_cr_brief(project_root, parsed.cr_id, mode=parsed.mode or "audit"), end="")
        return 0
    if command == "goal-brief":
        if not parsed.goal_ref:
            raise SystemExit("--goal-ref is required")
        print(render_goal_brief(project_root, parsed.goal_ref), end="")
        return 0
    if command == "impact-report":
        report = build_impact_report(project_root, mode=parsed.mode or "enforce")
        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if parsed.output:
            path = write_impact_report(parsed.output, report)
            print(f"wrote: {path}")
        else:
            print(rendered, end="")
        return 0
    if command == "close":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        plan = plan_status_sync(
            project_root,
            parsed.cr_id,
            status="closed",
            readiness=parsed.readiness,
            gate_status=CLOSED_GATE_STATUS,
            work_id=parsed.work_id,
            expected_process_oid=parsed.expected_process_oid,
            effective_at=parsed.effective_at,
        )
        if not parsed.apply:
            print(
                json.dumps(
                    plan.as_dict(),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if plan.decision in {"READY", "NO_CHANGE"} else 1
        authorization: StatusSyncAuthorization | None = None
        authorization_error = ""
        if parsed.authorization_file is None:
            authorization_error = "close apply requires --authorization-file"
        else:
            try:
                authorization = load_status_sync_authorization(
                    parsed.authorization_file
                )
            except (OSError, ValueError) as exc:
                authorization_error = str(exc)
        if authorization_error:
            result = {
                "status": "BLOCKED",
                "reason": authorization_error,
                "mutation_count": 0,
            }
        else:
            result = apply_status_sync(
                project_root,
                plan,
                authorization=authorization,
                expected_plan_digest=parsed.expected_plan_digest,
            )
        printable = {key: value for key, value in result.items() if key != "paths"}
        if "paths" in result:
            printable["path_refs"] = sorted(result["paths"])
        print(
            json.dumps(
                printable,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if result["status"] in {"PASS", "NO_CHANGE"} else 1
    if command == "terminate":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        plan = plan_cr_termination(
            project_root,
            parsed.cr_id,
            work_id=parsed.work_id,
            termination_status=parsed.status,
            termination_reason=parsed.reason,
            expected_process_oid=parsed.expected_process_oid,
        )
        if not parsed.apply:
            print(
                json.dumps(
                    plan.as_dict(),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if plan.decision in {"READY", "NO_CHANGE"} else 1
        authorization: TerminationAuthorization | None = None
        authorization_error = ""
        if parsed.authorization_file is None:
            authorization_error = (
                "termination apply requires --authorization-file"
            )
        else:
            try:
                authorization = load_termination_authorization(
                    parsed.authorization_file
                )
            except (OSError, ValueError) as exc:
                authorization_error = str(exc)
        if authorization_error:
            result = {
                "status": "BLOCKED",
                "reason": authorization_error,
                "mutation_count": 0,
            }
        else:
            result = apply_cr_termination(
                project_root,
                plan,
                authorization=authorization,
                expected_plan_digest=parsed.expected_plan_digest,
            )
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if result["status"] in {"PASS", "NO_CHANGE"} else 1
    if command == "status-sync":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        plan = plan_status_sync(
            project_root,
            parsed.cr_id,
            status=parsed.status,
            readiness=parsed.readiness if "--readiness" in args else "",
            gate_status=parsed.gate_status if "--gate-status" in args else "",
            work_id=parsed.work_id,
            historical_migration=parsed.historical_migration,
            historical_gate_status=parsed.historical_gate_status,
            historical_lifecycle_status=parsed.historical_lifecycle_status,
            expected_process_oid=parsed.expected_process_oid,
            rebuild_corrupt_index=parsed.rebuild,
            effective_at=parsed.effective_at,
        )
        if not parsed.apply:
            print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if plan.decision in {"READY", "NO_CHANGE"} else 1
        authorization = None
        authorization_error = ""
        if parsed.authorization_file is None:
            authorization_error = (
                "status-sync apply requires --authorization-file"
            )
        else:
            try:
                authorization = load_status_sync_authorization(
                    parsed.authorization_file
                )
            except (OSError, ValueError) as exc:
                authorization_error = str(exc)
        if authorization_error:
            result = {
                "status": "BLOCKED",
                "reason": authorization_error,
                "mutation_count": 0,
            }
        else:
            result = apply_status_sync(
                project_root,
                plan,
                authorization=authorization,
                expected_plan_digest=parsed.expected_plan_digest,
            )
        printable = {key: value for key, value in result.items() if key != "paths"}
        if "paths" in result:
            printable["path_refs"] = sorted(result["paths"])
        print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] in {"PASS", "NO_CHANGE"} else 1
    if command == "status-sync-inspect":
        print(json.dumps(inspect_status_sync_transactions(project_root), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if command in {"status-sync-resume", "status-sync-rollback", "status-sync-abandon"}:
        if not parsed.transaction_id:
            raise SystemExit("--transaction-id is required")
        action = command.removeprefix("status-sync-")
        result = recover_status_sync_transaction(
            project_root,
            parsed.transaction_id,
            action=action,
            typed_authorized=parsed.typed_authorized,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] in {"PASS", "RECOVERED"} else 1
    if command == "check":
        errors = collect_check_errors(project_root)
        warnings = collect_check_warnings(project_root)
        print("CR Lifecycle Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "conflicts":
        if not parsed.cr_id:
            raise SystemExit("--id is required")
        proposed_fields = {
            "impact_capability_refs": parsed.impact_capability_ref,
            "impact_feature_refs": parsed.impact_feature_ref,
            "impact_module_paths": parsed.impact_module_path,
            "impact_policy_refs": parsed.impact_policy_ref,
            "impact_process_refs": parsed.impact_process_ref,
            "impact_runtime_refs": parsed.impact_runtime_ref,
            "impact_data_refs": parsed.impact_data_ref,
        }
        has_candidate_fields = bool(
            parsed.conflict_key
            or parsed.impact_surface
            or any(proposed_fields.values())
        )
        if parsed.proposed:
            if parsed.output is not None:
                result = {
                    "decision": "INVALID",
                    "code": "CR_CONFLICT_PROPOSED_INPUT_INVALID",
                    "cr_id": parsed.cr_id,
                    "mutation_count": 0,
                    "planned_mutation_count": 0,
                    "conflicts": [],
                    "warnings": ["--output is forbidden for zero-write proposed preview"],
                }
            else:
                result = proposed_conflict_report(
                    project_root,
                    cr_id=parsed.cr_id,
                    conflict_keys=parsed.conflict_key,
                    impact_surface=parsed.impact_surface,
                    impact_fields=proposed_fields,
                    title=parsed.title if "--title" in args else "",
                    scope=parsed.scope if "--scope" in args else "",
                )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            if result["decision"] == "INVALID":
                return 2
            return 1 if result["decision"] == "CONFLICT" else 0
        if has_candidate_fields:
            print(
                json.dumps(
                    {
                        "decision": "INVALID",
                        "code": "CR_CONFLICT_PROPOSED_INPUT_INVALID",
                        "cr_id": parsed.cr_id,
                        "mutation_count": 0,
                        "planned_mutation_count": 0,
                        "conflicts": [],
                        "warnings": ["candidate fields require --proposed"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
        conflicts, warnings = conflict_report(project_root, parsed.cr_id)
        print("CR Conflicts: " + ("FAIL" if conflicts else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for conflict in conflicts:
            print(f"- CONFLICT: {conflict}")
        return 1 if conflicts else 0
    raise SystemExit(
        f"未知 cr 命令: {command}. 目前支持: bootstrap, index, summary, brief, goal-brief, impact-report, "
        "terminate, status-sync, status-sync-inspect, status-sync-resume, status-sync-rollback, status-sync-abandon, "
        "aggregate, branch-open, branch-publish, branch-merge, branch-finish, close, check, "
        "public-operations-check, conflicts"
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
