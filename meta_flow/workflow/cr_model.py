"""CR lifecycle model primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

CR_ID_RE = re.compile(r"CR-\d+")

FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)

FORMAL_CR_STATUSES = {
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

# 兼容旧 import；这是 formal CR 文档 status，不是 native 三元组 lifecycle。
ALLOWED_LIFECYCLE_STATUSES = FORMAL_CR_STATUSES

FINISHED_STATUSES = {"closed", "superseded", "cancelled"}

CLOSED_GATE_STATUS = "cp8_closed"

DIRECT_CLOSED_GATE_STATUS = "closed"

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

def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

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
