"""Lightweight runtime state v2 support."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.checks.token_budget import DEFAULT_BUDGETS, format_bytes, load_budgets
from meta_flow.project.process_route import (
    _resolve_injected_process_ref,
    _resolve_runtime_path,
    _resolve_runtime_ref,
)
from meta_flow.project.read_contract import ReadContextProtocol

STATE_SCHEMA_VERSION = 2
STATE_CURRENT_REL = Path("process/state/STATE.current.json")
STATE_CURRENT_DIR_REL = Path("process/current")
STATE_CURRENT_ENTRY_REL = STATE_CURRENT_DIR_REL / "CURRENT.json"
CURRENT_ALIAS_NAMES = (
    "state",
    "cr-index",
    "change",
    "context",
    "checkpoint",
    "story",
    "release",
    "handoff",
)
CURRENT_ALIAS_GITIGNORE_BEGIN = "# meta-flow:managed-current-aliases:begin"
CURRENT_ALIAS_GITIGNORE_END = "# meta-flow:managed-current-aliases:end"
STATE_MD_REL = Path("process/STATE.md")
STATE_HISTORY_REL = Path("process/state/HISTORY.md")
WORKFLOW_HEALTH_REL = Path("process/state/WORKFLOW-HEALTH.json")
STATE_ARCHIVE_ROOT_REL = Path("process/archive/state")
ROUTING_REL = Path("process/.meta-flow-process.yaml")
CR_INDEX_JSON_REL = Path("process/changes/CR-INDEX.json")
BASE_LEDGER_RELS = (
    Path("process/state/CR-LEDGER.ndjson"),
    Path("process/state/STORY-LEDGER.ndjson"),
    Path("process/state/CHECKPOINT-LEDGER.ndjson"),
    Path("process/state/HANDOFF-LEDGER.ndjson"),
    Path("process/state/AGENT-DISPATCH-LEDGER.ndjson"),
    Path("process/state/GATE-LEDGER.ndjson"),
    Path("process/state/RUN-LEDGER.ndjson"),
    Path("process/state/READ-EXPANSION-LEDGER.ndjson"),
)
STATE_DRY_RUN_KIND = "StateDryRunPlanV1"
CURRENT_EXECUTION_STATUSES = frozenset(
    {"idle", "active", "awaiting_gate", "awaiting_authorization", "blocked"}
)
AUTHORIZATION_STOP_REASONS = frozenset({"authorization_required"})
WORKFLOW_HEALTH_COUNTER_KEYS = {
    "repeated_issue_count",
    "hld_revision_count",
    "lld_clarification_count",
    "cp_retry_count",
    "story_rework_count",
    "artifact_hash_unchanged_count",
    "phase_round_count",
}
DISALLOWED_CURRENT_KEYS = {
    "closed_crs",
    "cr_tracking",
    "history",
    "decision_briefs",
    "parallel_execution",
    "human_gate_decisions",
    "checkpoints",
}
CURRENT_REQUIRED_KEYS = {
    "schema_version",
    "project_id",
    "workflow_mode",
    "current_phase",
    "blocked",
    "next_action",
    "routing_ref",
    "updated_at",
}
CURRENT_OPTIONAL_KEYS = {
    "active_change",
    "active_story",
    "pending_gate",
    "active_context_ref",
    "active_delegation_ref",
    "active_question_batch_ref",
    "artifact_routing_ref",
    "authz_policy_refs",
    "delivery_routing_ref",
    "next_session_handoff_ref",
    "open_risks",
    "release_context_ref",
    "source_refs",
    "target_project_profile_ref",
    "pending_checklist_path",
    "project_state_ref",
    "workflow_health_ref",
}
CURRENT_ALLOWED_KEYS = CURRENT_REQUIRED_KEYS | CURRENT_OPTIONAL_KEYS
SECRET_LIKE_KEY_PARTS = (
    "credential",
    "secret",
    "token",
    "cookie",
    "private_key",
    "private-key",
)
CURRENT_FIELD_BUDGETS = {
    "next_action": {"kind": "object", "max_text_bytes": 160, "max_json_bytes": 384},
    "source_refs": {
        "kind": "list",
        "max_items": 24,
        "max_item_json_bytes": 256,
        "max_json_bytes": 4096,
    },
    "open_risks": {
        "kind": "list",
        "max_items": 16,
        "max_item_json_bytes": 256,
        "max_json_bytes": 2048,
    },
    "authz_policy_refs": {
        "kind": "list[str]",
        "max_items": 16,
        "max_item_json_bytes": 128,
        "max_json_bytes": 1024,
    },
    "routing_ref": {"kind": "scalar", "max_bytes": 256},
    "active_context_ref": {"kind": "scalar", "max_bytes": 256},
    "active_delegation_ref": {"kind": "scalar", "max_bytes": 256},
    "active_question_batch_ref": {"kind": "scalar", "max_bytes": 256},
    "artifact_routing_ref": {"kind": "scalar", "max_bytes": 256},
    "delivery_routing_ref": {"kind": "scalar", "max_bytes": 256},
    "next_session_handoff_ref": {"kind": "scalar", "max_bytes": 256},
    "pending_checklist_path": {"kind": "scalar", "max_bytes": 256},
    "project_state_ref": {"kind": "scalar", "max_bytes": 256},
    "release_context_ref": {"kind": "scalar", "max_bytes": 256},
    "target_project_profile_ref": {"kind": "scalar", "max_bytes": 256},
    "workflow_health_ref": {"kind": "scalar", "max_bytes": 256},
}

SLIM_ARCHIVE_KEYS = {
    "agent_lifecycle",
    "authorization_boundary",
    "checkpoints",
    "checkpoint_results",
    "context_budget",
    "cr_tracking",
    "delegated_interaction",
    "delivery_routing",
    "artifact_routing",
    "follow_through_tracking",
    "history",
    "human_gate_decisions",
    "last_actions",
    "next_actions",
    "orchestrator_session",
    "parallel_execution",
    "release",
    "source_refs",
    "story_execution",
    "target_project_profile",
    "workflow_health",
}


@dataclass(frozen=True)
class CurrentStateFinding:
    severity: str
    code: str
    message: str
    key: str | None = None

    def as_cli_line(self) -> str:
        return f"{self.message}"


class StateValidationError(ValueError):
    """Raised when a controlled current-state update fails validation."""


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    if end == -1:
        return ""
    return text[4:end]


def _strip_scalar(value: str) -> str:
    raw = value.strip()
    if " #" in raw:
        raw = raw.split(" #", 1)[0].rstrip()
    return raw.strip().strip('"').strip("'")


def _scalar_value(frontmatter: str, key: str, *, section: str | None = None) -> str:
    in_section = section is None
    section_indent = ""
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if section is not None:
            if not line.startswith((" ", "\t")) and stripped == f"{section}:":
                in_section = True
                section_indent = line[: len(line) - len(line.lstrip())]
                continue
            if in_section and not line.startswith(f"{section_indent}  "):
                in_section = False
        if not in_section:
            continue
        candidate = stripped if section is not None else line
        if not candidate.startswith(f"{key}:"):
            continue
        return _strip_scalar(candidate.split(":", 1)[1])
    return ""


def _bool_value(value: str) -> bool:
    return value.strip().lower() in {"true", "yes", "1", "y"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _text_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _is_absent_optional(value: Any) -> bool:
    return value is None or value == "" or value == []


def _is_scalar_or_absent(value: Any) -> bool:
    return _is_absent_optional(value) or isinstance(value, str)


def _is_relative_state_ref(value: str) -> bool:
    path = Path(value)
    if not value or path.is_absolute():
        return False
    if ".." in path.parts:
        return False
    if value.startswith("process/quant-lab/") or value == "process/quant-lab":
        return False
    return True


def _compact_scalar(value: Any, *, max_bytes: int = 256) -> str:
    text = _strip_scalar(str(value)) if value is not None else ""
    if _text_size(text) <= max_bytes:
        return text
    encoded = text.encode("utf-8")[: max(0, max_bytes - 3)]
    return encoded.decode("utf-8", errors="ignore") + "..."


def _compact_list_item(value: Any) -> Any:
    if isinstance(value, str):
        return _compact_scalar(value)
    if not isinstance(value, dict):
        return _compact_scalar(value)
    preferred_keys = (
        "id",
        "cr_id",
        "story_id",
        "path",
        "ref",
        "context_ref",
        "summary_ref",
        "result_ref",
        "ledger_ref",
        "kind",
        "status",
        "severity",
    )
    compact: dict[str, Any] = {}
    for key in preferred_keys:
        if key in value and value[key] not in (None, "", [], {}):
            compact[key] = (
                _compact_scalar(value[key])
                if not isinstance(value[key], (list, dict))
                else value[key]
            )
    if not compact:
        compact = {"summary": _compact_scalar(value.get("summary") or value.get("title") or value)}
    while _json_size(compact) > 256 and compact:
        compact.pop(next(reversed(compact)))
    return compact or {"summary": _compact_scalar(value)}


def _bounded_list(value: Any, *, max_items: int, active_only: bool = False) -> list[Any]:
    raw_items = value if isinstance(value, list) else [] if value in (None, "", {}) else [value]
    if active_only:
        filtered = []
        for item in raw_items:
            if isinstance(item, dict) and str(
                item.get("status") or item.get("lifecycle_status") or ""
            ).lower() in {
                "closed",
                "cancelled",
                "superseded",
                "resolved",
            }:
                continue
            filtered.append(item)
        raw_items = filtered
    compacted = [_compact_list_item(item) for item in raw_items[-max_items:]]
    return compacted


def _latest_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("text", "summary", "next_action", "action", "title"):
            if value.get(key):
                return _compact_scalar(value[key], max_bytes=160)
    if isinstance(value, list) and value:
        return _latest_text(value[-1])
    if value:
        return _compact_scalar(value, max_bytes=160)
    return ""


def _nested_dict(value: Any, key: str) -> dict[str, Any]:
    if isinstance(value, dict) and isinstance(value.get(key), dict):
        return value[key]
    return {}


def _nested_scalar(value: Any, *keys: str) -> str:
    current_value = value
    for key in keys:
        if not isinstance(current_value, dict):
            return ""
        current_value = current_value.get(key)
    if current_value in (None, "", [], {}):
        return ""
    return _compact_scalar(current_value)


def _contains_secret_like_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SECRET_LIKE_KEY_PARTS):
                return True
            if _contains_secret_like_key(nested):
                return True
    if isinstance(value, list):
        return any(_contains_secret_like_key(item) for item in value)
    return False


def _finding(
    findings: list[CurrentStateFinding],
    severity: str,
    code: str,
    message: str,
    *,
    key: str | None = None,
) -> None:
    findings.append(CurrentStateFinding(severity=severity, code=code, message=message, key=key))


def _budget_severity(mode: str) -> str:
    return "ERROR" if mode == "enforce" else "WARN"


def _validate_budget_field(
    state: dict[str, Any], key: str, findings: list[CurrentStateFinding], *, mode: str
) -> None:
    if key not in state:
        return
    value = state[key]
    budget = CURRENT_FIELD_BUDGETS[key]
    kind = budget["kind"]
    if kind == "scalar":
        if not _is_scalar_or_absent(value):
            _finding(
                findings,
                "ERROR",
                "field_type",
                f"{key} must be a scalar string or null/empty",
                key=key,
            )
            return
    elif kind == "list[str]":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            _finding(findings, "ERROR", "field_type", f"{key} must be a list of strings", key=key)
            return
    elif kind == "list":
        if not isinstance(value, list):
            _finding(findings, "ERROR", "field_type", f"{key} must be a list", key=key)
            return
    elif kind == "object":
        if not isinstance(value, (dict, str)) and not _is_absent_optional(value):
            _finding(
                findings,
                "ERROR",
                "field_type",
                f"{key} must be an object, string, or null/empty",
                key=key,
            )
            return

    severity = _budget_severity(mode)
    max_bytes = budget.get("max_bytes")
    if max_bytes is not None and isinstance(value, str):
        actual_bytes = _text_size(value)
        if actual_bytes > int(max_bytes):
            _finding(
                findings,
                severity,
                "field_budget",
                f"{key} exceeds budget: {format_bytes(actual_bytes)} > {format_bytes(int(max_bytes))}",
                key=key,
            )

    max_text_bytes = budget.get("max_text_bytes")
    if max_text_bytes is not None:
        text_value = (
            value.get("text")
            if isinstance(value, dict)
            else value
            if isinstance(value, str)
            else None
        )
        if isinstance(text_value, str):
            actual_text_bytes = _text_size(text_value)
            if actual_text_bytes > int(max_text_bytes):
                _finding(
                    findings,
                    severity,
                    "field_budget",
                    f"{key}.text exceeds budget: {format_bytes(actual_text_bytes)} > {format_bytes(int(max_text_bytes))}",
                    key=key,
                )

    max_json_bytes = budget.get("max_json_bytes")
    actual_json_bytes = _json_size(value)
    if max_json_bytes is not None and actual_json_bytes > int(max_json_bytes):
        _finding(
            findings,
            severity,
            "field_budget",
            f"{key} exceeds budget: {format_bytes(actual_json_bytes)} > {format_bytes(int(max_json_bytes))}",
            key=key,
        )
    max_items = budget.get("max_items")
    if max_items is not None and isinstance(value, list) and len(value) > int(max_items):
        _finding(
            findings,
            severity,
            "field_budget",
            f"{key} exceeds item budget: {len(value)} > {max_items}",
            key=key,
        )
    max_item_json_bytes = budget.get("max_item_json_bytes")
    if max_item_json_bytes is not None and isinstance(value, list):
        for index, item in enumerate(value):
            item_size = _json_size(item)
            if item_size > int(max_item_json_bytes):
                _finding(
                    findings,
                    severity,
                    "field_budget",
                    f"{key}[{index}] exceeds item budget: {format_bytes(item_size)} > {format_bytes(int(max_item_json_bytes))}",
                    key=key,
                )


def validate_current_state_payload(
    state: dict[str, Any], *, mode: str = "audit"
) -> list[CurrentStateFinding]:
    if mode not in {"audit", "enforce"}:
        raise ValueError(f"unknown current-state validation mode: {mode}")
    findings: list[CurrentStateFinding] = []
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        _finding(
            findings,
            "ERROR",
            "schema_version",
            f"schema_version must be {STATE_SCHEMA_VERSION}",
            key="schema_version",
        )
    for key in sorted(CURRENT_REQUIRED_KEYS):
        if key not in state:
            _finding(
                findings, "ERROR", "missing_required", f"missing required field: {key}", key=key
            )
    unknown_keys = sorted(set(state) - CURRENT_ALLOWED_KEYS)
    for key in unknown_keys:
        severity = "ERROR" if mode == "enforce" else "WARN"
        _finding(
            findings,
            severity,
            "unknown_key",
            f"STATE.current.json contains unknown field: {key}",
            key=key,
        )
    for key in sorted(DISALLOWED_CURRENT_KEYS):
        if key in state:
            _finding(
                findings,
                "ERROR",
                "disallowed_key",
                f"STATE.current.json must not store long-running field: {key}",
                key=key,
            )
    if _contains_secret_like_key(state):
        _finding(
            findings,
            "ERROR",
            "secret_like_key",
            "STATE.current.json must not store credential/secret/token/cookie/private-key fields",
        )
    project_state_ref = state.get("project_state_ref")
    if isinstance(project_state_ref, str) and project_state_ref:
        if not _is_relative_state_ref(project_state_ref):
            _finding(
                findings,
                "ERROR",
                "ref_path",
                "project_state_ref must be a project-relative path and must not escape project root",
                key="project_state_ref",
            )
    for key in CURRENT_FIELD_BUDGETS:
        _validate_budget_field(state, key, findings, mode=mode)
    # A delivered state is intentionally encoded by the three canonical
    # pointers below.  Do not infer it from a historical transition event's
    # stop_reason: the current-state payload is its own truth source.
    if state.get("current_phase") == "delivered":
        for key in (
            "active_change",
            "pending_gate",
            "active_story",
            "active_context_ref",
            "active_delegation_ref",
        ):
            if not _is_absent_optional(state.get(key)):
                _finding(
                    findings,
                    "ERROR",
                    "delivered_active_reference",
                    f"delivered state must not retain {key}",
                    key=key,
                )
    return findings


def validate_current_state_for_write(state: dict[str, Any]) -> None:
    findings = validate_current_state_payload(state, mode="enforce")
    errors = [finding for finding in findings if finding.severity == "ERROR"]
    if errors:
        messages = "; ".join(finding.message for finding in errors)
        raise ValueError(f"STATE.current.json enforce validation failed: {messages}")


def validate_current_patch(
    patch: dict[str, Any], *, mode: str = "enforce"
) -> list[CurrentStateFinding]:
    if mode not in {"audit", "enforce"}:
        raise ValueError(f"unknown current-state validation mode: {mode}")
    findings: list[CurrentStateFinding] = []
    unknown_keys = sorted(set(patch) - CURRENT_ALLOWED_KEYS)
    for key in unknown_keys:
        severity = "ERROR" if mode == "enforce" else "WARN"
        _finding(
            findings,
            severity,
            "unknown_patch_key",
            f"current-state patch contains unknown field: {key}",
            key=key,
        )
    for key in sorted(DISALLOWED_CURRENT_KEYS):
        if key in patch:
            _finding(
                findings,
                "ERROR",
                "disallowed_patch_key",
                f"current-state patch must not store long-running field: {key}",
                key=key,
            )
    return findings


def _raise_on_error(
    findings: list[CurrentStateFinding], *, subject: str, actor: str = "", reason: str = ""
) -> None:
    errors = [finding for finding in findings if finding.severity == "ERROR"]
    if not errors:
        return
    context_parts = []
    if actor:
        context_parts.append(f"actor={actor[:128]}")
    if reason:
        context_parts.append(f"reason={reason[:256]}")
    context = f" ({'; '.join(context_parts)})" if context_parts else ""
    messages = "; ".join(f"{finding.code}: {finding.message}" for finding in errors)
    raise StateValidationError(f"{subject} validation failed{context}: {messages}")


def _deep_merge_current_state(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(base)
    for key, value in patch.items():
        existing = candidate.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            candidate[key] = _deep_merge_current_state(existing, value)
        else:
            candidate[key] = copy.deepcopy(value)
    return candidate


def current_state_path(project_root: Path) -> Path:
    return _resolve_runtime_ref(project_root, STATE_CURRENT_REL.as_posix())


def current_entry_path(project_root: Path) -> Path:
    return _resolve_runtime_ref(project_root, STATE_CURRENT_ENTRY_REL.as_posix())


def state_md_path(project_root: Path) -> Path:
    return _resolve_runtime_ref(project_root, STATE_MD_REL.as_posix())


def default_current_state(project_root: Path, *, project_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "project_id": project_id or project_root.resolve().name,
        "workflow_mode": "standard",
        "current_phase": "init",
        "blocked": False,
        "active_change": None,
        "active_story": None,
        "pending_gate": None,
        "next_action": {
            "type": "initialize_or_migrate",
            "text": "initialize process state or migrate legacy STATE.md",
        },
        "routing_ref": ROUTING_REL.as_posix(),
        "active_context_ref": None,
        "next_session_handoff_ref": None,
        "authz_policy_refs": [],
        "open_risks": [],
        "updated_at": now_utc(),
        "source_refs": [],
    }


def ensure_base_ledgers(project_root: Path) -> None:
    for ledger_rel in BASE_LEDGER_RELS:
        ledger_path = _resolve_runtime_ref(project_root, ledger_rel.as_posix())
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.touch(exist_ok=True)


def init_current_state(
    project_root: Path, *, project_id: str | None = None, force: bool = False
) -> Path:
    path = current_state_path(project_root.resolve())
    if path.exists() and not force:
        ensure_base_ledgers(project_root)
        return path
    state = default_current_state(project_root.resolve(), project_id=project_id)
    return write_current_state(project_root, state, force=force)


def _state_dry_run_payload(
    *,
    operation: str,
    planned_targets: list[str],
    target_refs: list[str],
    semantic_input: dict[str, Any],
) -> dict[str, Any]:
    unique_planned = sorted(set(planned_targets))
    return {
        "schema_version": 1,
        "kind": STATE_DRY_RUN_KIND,
        "operation": operation,
        "decision": "NO_CHANGE" if not unique_planned else "READY",
        "dry_run": True,
        "mutation_count": 0,
        "planned_mutation_count": len(unique_planned),
        "target_refs": target_refs,
        "semantic_digest": _sha256_json(semantic_input),
    }


def plan_init_current_state(
    project_root: Path,
    *,
    project_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Plan ``state init`` without invoking a writer or creating a parent directory."""

    root = project_root.resolve()
    target_refs = [
        STATE_CURRENT_REL.as_posix(),
        *(item.as_posix() for item in BASE_LEDGER_RELS),
    ]
    planned_targets: list[str] = []
    for logical_ref in target_refs:
        path = _resolve_runtime_ref(root, logical_ref)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise FileExistsError(f"state init target is not a regular file: {logical_ref}")
        if logical_ref == STATE_CURRENT_REL.as_posix():
            if force or not path.is_file():
                planned_targets.append(logical_ref)
        elif not path.is_file():
            planned_targets.append(logical_ref)
    return _state_dry_run_payload(
        operation="state.init",
        planned_targets=planned_targets,
        target_refs=target_refs,
        semantic_input={
            "operation": "state.init",
            "project_id": project_id or root.name,
            "force": force,
            "planned_targets": sorted(planned_targets),
        },
    )


def _bootstrap_legacy_state_at_process_root(
    project_root: Path,
    process_root: Path,
    *,
    project_id: str,
    force: bool = False,
) -> tuple[Path, Path]:
    """为已通过 typed capability 的 legacy bootstrap 显式初始化状态。

    该入口只接受调用方已经验证出的物理过程根，不通过 ``release/process``
    重新发现路由，因此不会把 legacy 软链接重新引入通用 runtime fallback。
    """

    release_root = project_root.resolve()
    target_root = process_root.resolve()
    state_path = target_root / STATE_CURRENT_REL.relative_to("process")
    state = default_current_state(release_root, project_id=project_id)
    validate_current_state_for_write(state)
    if not state_path.exists() or force:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        _write_current_state_file(state_path, state)
    else:
        state = _read_json(state_path)
        if not state:
            raise ValueError(f"legacy STATE.current.json is invalid: {state_path}")

    for ledger_rel in BASE_LEDGER_RELS:
        ledger_path = target_root / ledger_rel.relative_to("process")
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.touch(exist_ok=True)

    summary_path = target_root / STATE_MD_REL.relative_to("process")
    if summary_path.exists() and not force:
        existing = summary_path.read_text(encoding="utf-8", errors="ignore")
        if "generated-by: meta-flow state render" not in existing:
            raise FileExistsError(
                f"{summary_path} 已存在且不是 state render 生成物；如需覆盖请使用 --force"
            )
    else:
        summary_path.write_text(render_state_markdown(state), encoding="utf-8")

    current_dir = target_root / STATE_CURRENT_DIR_REL.relative_to("process")
    entry_path = target_root / STATE_CURRENT_ENTRY_REL.relative_to("process")
    entry = {
        "schema_version": 1,
        "status": _state_status(state),
        "phase": state.get("current_phase") or None,
        "health": "ok",
        "active_change": None,
        "active_story": None,
        "pending_gate": None,
        "state_ref": STATE_CURRENT_REL.as_posix(),
        "cr_index_ref": None,
        "available_index_refs": [],
        "change_ref": None,
        "context_ref": None,
        "checkpoint_ref": None,
        "story_packet_ref": None,
        "release_context_ref": None,
        "handoff_ref": None,
        "routing_ref": state.get("routing_ref") or ROUTING_REL.as_posix(),
        "updated_at": now_utc(),
        "stale_refs": [],
    }
    current_dir.mkdir(parents=True, exist_ok=True)
    _ensure_current_alias_gitignore(current_dir)
    _write_json(entry_path, entry)
    state_ref = current_dir / "state.ref"
    state_ref.write_text(STATE_CURRENT_REL.as_posix() + "\n", encoding="utf-8")
    state_link = current_dir / "state"
    if state_link.is_symlink() or state_link.is_file():
        state_link.unlink()
    state_link.symlink_to(os.path.relpath(state_path, start=current_dir))
    return state_path, summary_path


def migrate_legacy_state(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    path = state_md_path(project_root)
    if not path.is_file():
        raise FileNotFoundError(f"未找到 legacy 状态文件: {path}")
    text = path.read_text(encoding="utf-8")
    frontmatter = _frontmatter(text)
    if not frontmatter:
        raise ValueError(f"legacy STATE.md 缺少 frontmatter: {path}")

    pending_gate = (
        _scalar_value(frontmatter, "pending_gate", section="orchestrator_session") or None
    )
    pending_checklist_path = (
        _scalar_value(frontmatter, "pending_checklist_path", section="orchestrator_session") or None
    )
    next_action_text = _scalar_value(frontmatter, "next_action") or _scalar_value(
        frontmatter, "next_exact_prompt", section="orchestrator_session"
    )
    state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "project_id": _scalar_value(frontmatter, "project_id") or project_root.name,
        "workflow_mode": _scalar_value(frontmatter, "workflow_mode") or "standard",
        "current_phase": _scalar_value(frontmatter, "current_phase") or "unknown",
        "blocked": _bool_value(_scalar_value(frontmatter, "blocked")),
        "active_change": _scalar_value(frontmatter, "active_change") or None,
        "active_story": _scalar_value(frontmatter, "active_story") or None,
        "pending_gate": pending_gate,
        "next_action": {
            "type": "await_user" if pending_gate else "continue",
            "text": next_action_text or "推进当前阶段",
        },
        "routing_ref": ROUTING_REL.as_posix(),
        "active_context_ref": _scalar_value(frontmatter, "active_context_ref") or None,
        "next_session_handoff_ref": _scalar_value(frontmatter, "next_session_handoff_ref") or None,
        "authz_policy_refs": [],
        "open_risks": [],
        "updated_at": now_utc(),
        "source_refs": [
            {
                "path": STATE_MD_REL.as_posix(),
                "kind": "legacy-state",
            }
        ],
    }
    if pending_checklist_path:
        state["pending_checklist_path"] = pending_checklist_path
    return state


def write_current_state(project_root: Path, state: dict[str, Any], *, force: bool = False) -> Path:
    project_root = project_root.resolve()
    path = current_state_path(project_root)
    if path.exists() and not force:
        raise FileExistsError(f"{path} 已存在；如需覆盖请使用 --force")
    validate_current_state_for_write(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_current_state_file(path, state)
    ensure_base_ledgers(project_root)
    return path


def _write_current_state_file(path: Path, state: dict[str, Any]) -> None:
    text = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def load_current_state(
    project_root: Path,
    *,
    read_context: ReadContextProtocol | None = None,
) -> dict[str, Any]:
    path = (
        current_state_path(project_root.resolve())
        if read_context is None
        else read_context.resolve_path(STATE_CURRENT_REL.as_posix())
    )
    if read_context is None or not path.is_file():
        return _read_json(path)
    payload = read_context.read_json(STATE_CURRENT_REL.as_posix())
    return payload if isinstance(payload, dict) else {}


def _existing_rel(project_root: Path, rel_path: Path) -> str | None:
    path = _resolve_runtime_path(project_root, rel_path)
    return rel_path.as_posix() if path.is_file() else None


def _available_cr_index_refs(project_root: Path) -> list[str]:
    refs: list[str] = []
    for rel_path in (CR_INDEX_JSON_REL,):
        existing = _existing_rel(project_root, rel_path)
        if not existing:
            continue
        from meta_flow.workflow.cr_lifecycle import validate_index_payload

        path = _resolve_runtime_path(project_root, rel_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not validate_index_payload(payload):
            refs.append(existing)
    return refs


def _latest_matching_ref(project_root: Path, pattern: str) -> str | None:
    if pattern.startswith("process/"):
        process_root = _resolve_runtime_ref(project_root, "process/PROJECT.yaml").parent
        candidates = [
            path for path in process_root.glob(pattern.removeprefix("process/")) if path.is_file()
        ]
        prefix = "process/"
        relative_root = process_root
    else:
        candidates = [path for path in project_root.glob(pattern) if path.is_file()]
        prefix = ""
        relative_root = project_root
    if not candidates:
        return None
    candidates.sort(key=lambda path: (path.stat().st_mtime, path.as_posix()))
    return prefix + candidates[-1].relative_to(relative_root).as_posix()


def _state_status(state: dict[str, Any]) -> str:
    if bool(state.get("blocked", False)):
        return "blocked"
    if state.get("pending_gate") or state.get("pending_checklist_path"):
        return "awaiting_gate"
    next_action = state.get("next_action")
    if (
        isinstance(next_action, dict)
        and str(next_action.get("stop_reason") or "").strip().lower()
        in AUTHORIZATION_STOP_REASONS
    ):
        return "awaiting_authorization"
    if state.get("active_change") or state.get("active_story"):
        return "active"
    return "idle"


def _is_existing_ref(project_root: Path, rel_path: str) -> bool:
    if not rel_path:
        return False
    path = Path(rel_path)
    if path.is_absolute() or ".." in path.parts:
        return False
    return _resolve_runtime_path(project_root, path).is_file()


def _record_stale_ref(
    stale_refs: list[dict[str, str]], field: str, rel_path: str, *, reason: str = "missing"
) -> None:
    if rel_path:
        stale_refs.append({"field": field, "path": rel_path, "reason": reason})


def _choose_release_ref(
    project_root: Path, state: dict[str, Any], status: str, stale_refs: list[dict[str, str]]
) -> str | None:
    release_ref = str(state.get("release_context_ref") or "")
    active_context_ref = str(state.get("active_context_ref") or "")
    if not release_ref and status == "idle" and "RELEASE-CONTEXT" in active_context_ref:
        release_ref = active_context_ref
    if release_ref:
        if not _is_existing_ref(project_root, release_ref):
            _record_stale_ref(stale_refs, "release_context_ref", release_ref)
        return release_ref
    return (
        _latest_matching_ref(project_root, "process/release/RELEASE-CONTEXT*.yaml")
        or _latest_matching_ref(project_root, "process/release/RELEASE-CONTEXT*.yml")
        or _latest_matching_ref(project_root, "process/release/RELEASE-CONTEXT*.json")
    )


def _choose_handoff_ref(
    project_root: Path, state: dict[str, Any], stale_refs: list[dict[str, str]]
) -> str | None:
    # STATE.current 显式声明该字段时，null 也是 owner 的有效决定。
    # 只有完全缺失该字段的 legacy payload 才允许历史发现回退。
    if "next_session_handoff_ref" in state and not state.get("next_session_handoff_ref"):
        return None
    handoff_ref = str(state.get("next_session_handoff_ref") or "")
    if handoff_ref:
        if not _is_existing_ref(project_root, handoff_ref):
            _record_stale_ref(stale_refs, "next_session_handoff_ref", handoff_ref)
        return handoff_ref
    return _latest_matching_ref(
        project_root, "process/handoffs/NEXT-SESSION-*.md"
    ) or _latest_matching_ref(
        project_root,
        "process/handoffs/*.md",
    )


def _choose_story_packet_ref(project_root: Path, state: dict[str, Any]) -> str | None:
    explicit = str(state.get("active_story_packet_ref") or "")
    if explicit:
        return explicit
    active_story = str(state.get("active_story") or "")
    if not active_story:
        return None
    escaped = active_story.replace("/", "")
    return (
        _latest_matching_ref(project_root, f"process/context/stories/*{escaped}*.work-packet.json")
        or _latest_matching_ref(
            project_root, f"process/context/stories/*{escaped}*.verify-packet.json"
        )
        or _latest_matching_ref(project_root, f"process/context/stories/*{escaped}*.context.json")
    )


def _choose_checkpoint_ref(
    project_root: Path, state: dict[str, Any], stale_refs: list[dict[str, str]]
) -> str | None:
    checkpoint_ref = str(state.get("pending_checklist_path") or "")
    if checkpoint_ref and not _is_existing_ref(project_root, checkpoint_ref):
        _record_stale_ref(stale_refs, "pending_checklist_path", checkpoint_ref)
    return checkpoint_ref or None


def _choose_context_ref(
    project_root: Path, state: dict[str, Any], status: str, stale_refs: list[dict[str, str]]
) -> str | None:
    if status == "idle":
        return None
    context_ref = str(state.get("active_context_ref") or "")
    if context_ref and not _is_existing_ref(project_root, context_ref):
        _record_stale_ref(stale_refs, "active_context_ref", context_ref)
    return context_ref or None


def _change_ref(
    project_root: Path, active_change: str, stale_refs: list[dict[str, str]]
) -> str | None:
    if not active_change:
        return None
    rel_path = f"process/changes/{active_change}.md"
    if not _is_existing_ref(project_root, rel_path):
        _record_stale_ref(stale_refs, "active_change", rel_path)
    return rel_path


def build_current_entry(
    project_root: Path,
    *,
    read_context: ReadContextProtocol | None = None,
    state_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    state = (
        dict(state_snapshot)
        if state_snapshot is not None
        else load_current_state(project_root, read_context=read_context)
    )
    if not state:
        raise FileNotFoundError(f"STATE.current.json missing: {current_state_path(project_root)}")
    status = _state_status(state)
    stale_refs: list[dict[str, str]] = []
    active_change = state.get("active_change") or None
    active_story = state.get("active_story") or None
    pending_gate = state.get("pending_gate") or None
    available_index_refs = _available_cr_index_refs(project_root)
    context_ref = _choose_context_ref(project_root, state, status, stale_refs)
    checkpoint_ref = _choose_checkpoint_ref(project_root, state, stale_refs)
    story_packet_ref = _choose_story_packet_ref(project_root, state)
    if story_packet_ref and not _is_existing_ref(project_root, story_packet_ref):
        _record_stale_ref(stale_refs, "story_packet_ref", story_packet_ref)
    release_context_ref = _choose_release_ref(project_root, state, status, stale_refs)
    handoff_ref = _choose_handoff_ref(project_root, state, stale_refs)
    change_ref = _change_ref(project_root, str(active_change or ""), stale_refs)
    health = "ok"
    if not available_index_refs and active_change:
        health = "incomplete"
    if stale_refs:
        health = "stale_refs"
    return {
        "schema_version": 1,
        "status": status,
        "phase": state.get("current_phase") or None,
        "health": health,
        "active_change": active_change,
        "active_story": active_story,
        "pending_gate": pending_gate,
        "state_ref": STATE_CURRENT_REL.as_posix(),
        "cr_index_ref": available_index_refs[0] if available_index_refs else None,
        "available_index_refs": available_index_refs,
        "change_ref": change_ref,
        "context_ref": context_ref,
        "checkpoint_ref": checkpoint_ref,
        "story_packet_ref": story_packet_ref,
        "release_context_ref": release_context_ref,
        "handoff_ref": handoff_ref,
        "routing_ref": state.get("routing_ref") or ROUTING_REL.as_posix(),
        "updated_at": now_utc(),
        "stale_refs": stale_refs,
    }


def validate_current_projection(project_root: Path) -> list[CurrentStateFinding]:
    """Validate that ``process/current/CURRENT.json`` projects state v2.

    The projection is deliberately read-only: State remains the workflow
    owner and CURRENT remains a discoverability view.  This check therefore
    reports drift without trying to repair either object.
    """

    project_root = project_root.resolve()
    state = load_current_state(project_root)
    if not state:
        return [
            CurrentStateFinding(
                severity="ERROR",
                code="state_missing",
                message=f"STATE.current.json missing: {current_state_path(project_root)}",
            )
        ]
    entry_path = current_entry_path(project_root)
    if not entry_path.is_file():
        return [
            CurrentStateFinding(
                severity="ERROR",
                code="current_projection_missing",
                message=f"CURRENT.json missing: {entry_path}",
            )
        ]
    entry = _read_json(entry_path)
    if not entry:
        return [
            CurrentStateFinding(
                severity="ERROR",
                code="current_projection_invalid",
                message=f"CURRENT.json is empty or invalid JSON: {entry_path}",
            )
        ]

    expected = build_current_entry(project_root)
    findings: list[CurrentStateFinding] = []
    relationship_fields = (
        "schema_version",
        "active_change",
        "active_story",
        "pending_gate",
        "phase",
        "state_ref",
        "change_ref",
        "context_ref",
        "checkpoint_ref",
        "story_packet_ref",
        "cr_index_ref",
        "available_index_refs",
        "release_context_ref",
        "handoff_ref",
        "routing_ref",
        "status",
        "health",
        "stale_refs",
    )
    for key in relationship_fields:
        if entry.get(key) != expected.get(key):
            findings.append(
                CurrentStateFinding(
                    severity="ERROR",
                    code="current_projection_drift",
                    message=(
                        f"CURRENT.json {key}={entry.get(key)!r} does not match "
                        f"STATE-derived value {expected.get(key)!r}"
                    ),
                    key=key,
                )
            )
    expected_stale_refs = expected.get("stale_refs")
    if isinstance(expected_stale_refs, list) and expected_stale_refs:
        findings.append(
            CurrentStateFinding(
                severity="ERROR",
                code="current_projection_source_stale_ref",
                message=f"STATE-derived CURRENT projection contains stale refs: {expected_stale_refs}",
                key="stale_refs",
            )
        )
    return findings


def validate_state_markdown_projection(
    state: dict[str, Any], markdown_text: str
) -> list[CurrentStateFinding]:
    """Validate the generated human view against canonical State v2 bytes."""

    if "generated-by: meta-flow state render" not in markdown_text:
        return [
            CurrentStateFinding(
                severity="ERROR",
                code="state_markdown_unmanaged",
                message="STATE.md exists beside State v2 but is not a generated state render",
            )
        ]
    expected = render_state_markdown(state)
    if markdown_text == expected:
        return []
    return [
        CurrentStateFinding(
            severity="ERROR",
            code="state_markdown_projection_drift",
            message="STATE.md does not exactly match the STATE.current.json render",
        )
    ]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{_archive_timestamp()}.tmp")
    tmp_path.write_text(rendered, encoding="utf-8")
    tmp_path.replace(path)


def _clear_pointer(current_dir: Path, name: str) -> None:
    for path in (current_dir / f"{name}.ref", current_dir / name):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
        except OSError:
            pass


def _current_alias_gitignore_block() -> str:
    lines = [
        CURRENT_ALIAS_GITIGNORE_BEGIN,
        "# CURRENT.json 与 *.ref 是 canonical truth；以下软链接仅供本地发现。",
        *(f"/current/{name}" for name in CURRENT_ALIAS_NAMES),
        CURRENT_ALIAS_GITIGNORE_END,
    ]
    return "\n".join(lines) + "\n"


def _render_current_alias_gitignore(existing: str) -> str:
    has_begin = CURRENT_ALIAS_GITIGNORE_BEGIN in existing
    has_end = CURRENT_ALIAS_GITIGNORE_END in existing
    if has_begin != has_end:
        raise ValueError("current alias managed block 不完整")
    if existing.count(CURRENT_ALIAS_GITIGNORE_BEGIN) > 1 or existing.count(CURRENT_ALIAS_GITIGNORE_END) > 1:
        raise ValueError("current alias managed block 重复")

    block = _current_alias_gitignore_block()
    if has_begin:
        start = existing.index(CURRENT_ALIAS_GITIGNORE_BEGIN)
        end_marker = existing.index(CURRENT_ALIAS_GITIGNORE_END, start)
        end = existing.find("\n", end_marker)
        end = len(existing) if end == -1 else end + 1
        rendered = existing[:start] + block + existing[end:]
    else:
        prefix = existing
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        rendered = prefix + block
    return rendered


def _ensure_current_alias_gitignore(current_dir: Path) -> Path:
    """在过程仓根目录维护精确的 current alias 忽略规则。"""

    gitignore_path = current_dir.parent / ".gitignore"
    if gitignore_path.is_symlink() or (gitignore_path.exists() and not gitignore_path.is_file()):
        raise FileExistsError(f"{gitignore_path} 不是可安全更新的常规文件")

    existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.is_file() else ""
    try:
        rendered = _render_current_alias_gitignore(existing)
    except ValueError as exc:
        raise ValueError(f"{gitignore_path} 的 {exc}") from exc

    if rendered == existing:
        return gitignore_path
    tmp_path = gitignore_path.with_name(f".{gitignore_path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(rendered, encoding="utf-8")
    tmp_path.replace(gitignore_path)
    return gitignore_path


def _write_pointer(current_dir: Path, project_root: Path, name: str, rel_ref: str | None) -> None:
    if not rel_ref:
        _clear_pointer(current_dir, name)
        return
    ref_path = current_dir / f"{name}.ref"
    rendered_ref = rel_ref + "\n"
    if not ref_path.is_file() or ref_path.read_text(encoding="utf-8") != rendered_ref:
        ref_path.write_text(rendered_ref, encoding="utf-8")
    link_path = current_dir / name
    try:
        target = _resolve_runtime_path(project_root, rel_ref)
        if target.exists():
            relative_target = os.path.relpath(target, start=current_dir)
            if link_path.is_symlink() and os.readlink(link_path) == relative_target:
                return
            if link_path.is_symlink() or link_path.is_file():
                link_path.unlink()
            link_path.symlink_to(relative_target)
        elif link_path.is_symlink() or link_path.is_file():
            link_path.unlink()
    except OSError:
        pass


def _pointer_planned_targets(
    current_dir: Path,
    project_root: Path,
    name: str,
    rel_ref: str | None,
) -> list[str]:
    planned: list[str] = []
    ref_logical = (STATE_CURRENT_DIR_REL / f"{name}.ref").as_posix()
    alias_logical = (STATE_CURRENT_DIR_REL / name).as_posix()
    ref_path = current_dir / f"{name}.ref"
    link_path = current_dir / name
    if not rel_ref:
        if ref_path.is_symlink() or ref_path.is_file():
            planned.append(ref_logical)
        if link_path.is_symlink() or link_path.is_file():
            planned.append(alias_logical)
        return planned

    rendered_ref = rel_ref + "\n"
    if not ref_path.is_file() or ref_path.read_text(encoding="utf-8") != rendered_ref:
        planned.append(ref_logical)
    target = _resolve_runtime_path(project_root, rel_ref)
    if target.exists():
        relative_target = os.path.relpath(target, start=current_dir)
        if not link_path.is_symlink() or os.readlink(link_path) != relative_target:
            planned.append(alias_logical)
    elif link_path.is_symlink() or link_path.is_file():
        planned.append(alias_logical)
    return planned


def plan_current_entry_refresh(project_root: Path) -> dict[str, Any]:
    """Plan ``state current-refresh`` from read-only observations."""

    root = project_root.resolve()
    entry = build_current_entry(root)
    candidate_semantic = dict(entry)
    candidate_semantic.pop("updated_at", None)
    current_dir = _resolve_runtime_ref(root, STATE_CURRENT_DIR_REL.as_posix())
    path = _resolve_runtime_ref(root, STATE_CURRENT_ENTRY_REL.as_posix())
    gitignore_path = current_dir.parent / ".gitignore"
    if gitignore_path.is_symlink() or (gitignore_path.exists() and not gitignore_path.is_file()):
        raise FileExistsError("process/.gitignore is not a regular file")
    existing_gitignore = (
        gitignore_path.read_text(encoding="utf-8") if gitignore_path.is_file() else ""
    )
    rendered_gitignore = _render_current_alias_gitignore(existing_gitignore)

    planned_targets: list[str] = []
    if rendered_gitignore != existing_gitignore:
        planned_targets.append("process/.gitignore")
    existing = _read_json(path) if path.is_file() else {}
    existing_semantic = dict(existing)
    existing_semantic.pop("updated_at", None)
    if not existing or existing_semantic != candidate_semantic:
        planned_targets.append(STATE_CURRENT_ENTRY_REL.as_posix())

    pointer_refs = {
        "state": entry["state_ref"],
        "cr-index": entry.get("cr_index_ref"),
        "change": entry.get("change_ref"),
        "context": entry.get("context_ref"),
        "checkpoint": entry.get("checkpoint_ref"),
        "story": entry.get("story_packet_ref"),
        "release": entry.get("release_context_ref"),
        "handoff": entry.get("handoff_ref"),
    }
    for name in CURRENT_ALIAS_NAMES:
        planned_targets.extend(
            _pointer_planned_targets(current_dir, root, name, pointer_refs[name])
        )

    target_refs = [
        "process/.gitignore",
        STATE_CURRENT_ENTRY_REL.as_posix(),
        *(
            (STATE_CURRENT_DIR_REL / suffix).as_posix()
            for name in CURRENT_ALIAS_NAMES
            for suffix in (f"{name}.ref", name)
        ),
    ]
    return _state_dry_run_payload(
        operation="state.current-refresh",
        planned_targets=planned_targets,
        target_refs=target_refs,
        semantic_input={
            "operation": "state.current-refresh",
            "candidate": candidate_semantic,
            "pointer_refs": pointer_refs,
            "planned_targets": sorted(planned_targets),
        },
    )


def refresh_current_entry(
    project_root: Path,
    *,
    read_context: ReadContextProtocol | None = None,
    state_snapshot: dict[str, Any] | None = None,
) -> Path:
    project_root = project_root.resolve()
    entry = build_current_entry(
        project_root,
        read_context=read_context,
        state_snapshot=state_snapshot,
    )
    current_dir = _resolve_runtime_ref(project_root, STATE_CURRENT_DIR_REL.as_posix())
    current_dir.mkdir(parents=True, exist_ok=True)
    _ensure_current_alias_gitignore(current_dir)
    path = _resolve_runtime_ref(project_root, STATE_CURRENT_ENTRY_REL.as_posix())
    existing = _read_json(path) if path.is_file() else {}
    existing_semantic = dict(existing)
    candidate_semantic = dict(entry)
    existing_semantic.pop("updated_at", None)
    candidate_semantic.pop("updated_at", None)
    if existing and existing_semantic == candidate_semantic:
        entry["updated_at"] = existing.get("updated_at")
    else:
        _write_json(path, entry)
    pointer_refs = {
        "state": entry["state_ref"],
        "cr-index": entry.get("cr_index_ref"),
        "change": entry.get("change_ref"),
        "context": entry.get("context_ref"),
        "checkpoint": entry.get("checkpoint_ref"),
        "story": entry.get("story_packet_ref"),
        "release": entry.get("release_context_ref"),
        "handoff": entry.get("handoff_ref"),
    }
    for name in CURRENT_ALIAS_NAMES:
        _write_pointer(current_dir, project_root, name, pointer_refs[name])
    return path


def load_workflow_health(
    project_root: Path,
    *,
    read_context: ReadContextProtocol | None = None,
) -> dict[str, Any]:
    path = (
        _resolve_runtime_ref(project_root, WORKFLOW_HEALTH_REL.as_posix())
        if read_context is None
        else read_context.resolve_path(WORKFLOW_HEALTH_REL.as_posix())
    )
    if not path.is_file():
        return {
            "schema_version": 1,
            "updated_at": now_utc(),
            "phase_counters": {},
        }
    if read_context is None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = read_context.read_json(WORKFLOW_HEALTH_REL.as_posix())
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", 1)
    payload.setdefault("phase_counters", {})
    return payload


def update_workflow_health(
    project_root: Path,
    *,
    phase: str,
    increments: dict[str, int],
) -> tuple[dict[str, Any], Path]:
    if not phase:
        raise ValueError("phase is required")
    unknown = sorted(set(increments) - WORKFLOW_HEALTH_COUNTER_KEYS)
    if unknown:
        raise ValueError("unknown workflow health counters: " + ", ".join(unknown))
    project_root = project_root.resolve()
    payload = load_workflow_health(project_root)
    before_semantic = copy.deepcopy(payload)
    before_semantic.pop("updated_at", None)
    phase_counters = payload.setdefault("phase_counters", {})
    if not isinstance(phase_counters, dict):
        phase_counters = {}
        payload["phase_counters"] = phase_counters
    counters = phase_counters.setdefault(phase, {})
    if not isinstance(counters, dict):
        counters = {}
        phase_counters[phase] = counters
    for key, delta in increments.items():
        counters[key] = int(counters.get(key) or 0) + int(delta)
    path = _resolve_runtime_ref(project_root, WORKFLOW_HEALTH_REL.as_posix())
    after_semantic = copy.deepcopy(payload)
    after_semantic.pop("updated_at", None)
    if path.is_file() and before_semantic == after_semantic:
        return payload, path
    payload["updated_at"] = now_utc()
    _write_json(path, payload)
    if current_state_path(project_root).is_file():
        update_current_state(
            project_root,
            {
                "workflow_health_ref": WORKFLOW_HEALTH_REL.as_posix(),
                "updated_at": now_utc(),
            },
            actor="meta_flow.state.current",
            reason="workflow health counter update",
            mode="enforce",
        )
    return payload, path


def update_current_state(
    project_root: Path,
    patch: dict[str, Any],
    *,
    actor: str = "",
    reason: str = "",
    mode: str = "enforce",
    render: bool = False,
) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise StateValidationError(
            "current-state patch validation failed: invalid_patch: patch must be a dict"
        )
    project_root = project_root.resolve()
    path = current_state_path(project_root)
    candidate = build_current_state_candidate(
        project_root,
        patch,
        actor=actor,
        reason=reason,
        mode=mode,
    )

    _write_current_state_file(path, candidate)
    ensure_base_ledgers(project_root)
    if render:
        render_state_file(project_root, force=True)
    return candidate


def build_current_state_candidate(
    project_root: Path,
    patch: dict[str, Any],
    *,
    actor: str = "",
    reason: str = "",
    mode: str = "enforce",
    base_state: dict[str, Any] | None = None,
    read_context: ReadContextProtocol | None = None,
) -> dict[str, Any]:
    """Build and validate a current-state candidate without writing it."""

    if not isinstance(patch, dict):
        raise StateValidationError(
            "current-state patch validation failed: invalid_patch: patch must be a dict"
        )
    project_root = project_root.resolve()
    path = (
        current_state_path(project_root)
        if read_context is None
        else read_context.resolve_path(STATE_CURRENT_REL.as_posix())
    )
    if not path.is_file():
        raise FileNotFoundError(f"STATE.current.json missing: {path}")
    patch_findings = validate_current_patch(patch, mode=mode)
    _raise_on_error(patch_findings, subject="current-state patch", actor=actor, reason=reason)
    base = dict(base_state) if base_state is not None else load_current_state(
        project_root,
        read_context=read_context,
    )
    candidate = _deep_merge_current_state(base, patch)
    candidate_findings = validate_current_state_payload(candidate, mode=mode)
    _raise_on_error(
        candidate_findings, subject="STATE.current.json candidate", actor=actor, reason=reason
    )
    return candidate


def render_current_state_candidate(candidate: dict[str, Any]) -> str:
    """Render an already validated candidate for a larger transaction."""

    validate_current_state_for_write(candidate)
    return json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def project_aggregate_completion(
    project_root: Path,
    *,
    cr_id: str,
    aggregate_id: str,
    aggregate_ref: str,
    payload_digest: str,
    expected_updated_at: str,
) -> dict[str, Any]:
    """Project a persisted PASS aggregate as a completion candidate without closing the CR."""
    project_root = project_root.resolve()
    if not cr_id or not aggregate_id or not payload_digest:
        raise StateValidationError("aggregate projection identity fields must be non-empty")
    if not _is_relative_state_ref(aggregate_ref):
        raise StateValidationError("aggregate_ref must be a safe project-relative state ref")
    aggregate_path = _resolve_runtime_path(project_root, aggregate_ref)
    try:
        aggregate_path.relative_to(project_root)
    except ValueError as exc:
        raise StateValidationError("aggregate_ref escapes project root") from exc
    if not aggregate_path.is_file():
        raise StateValidationError(f"persisted aggregate is missing: {aggregate_ref}")
    try:
        aggregate_payload = json.loads(aggregate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateValidationError(f"persisted aggregate is unreadable: {exc}") from exc
    if not isinstance(aggregate_payload, dict):
        raise StateValidationError("persisted aggregate must be a JSON object")
    expected_fields = {
        "aggregate_id": aggregate_id,
        "cr_id": cr_id,
        "payload_digest": payload_digest,
        "overall": "PASS",
        "terminal": True,
        "projection_decision": "ELIGIBLE",
    }
    for field, expected in expected_fields.items():
        if aggregate_payload.get(field) != expected:
            raise StateValidationError(f"persisted aggregate projection guard mismatch for {field}")
    canonical_payload = dict(aggregate_payload)
    canonical_payload.pop("payload_digest", None)
    canonical_digest = hashlib.sha256(
        json.dumps(
            canonical_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if canonical_digest != payload_digest:
        raise StateValidationError("persisted aggregate canonical digest mismatch")
    state = load_current_state(project_root)
    if state.get("active_change") != cr_id:
        raise StateValidationError(
            f"aggregate projection active_change mismatch: expected {cr_id}, "
            f"found {state.get('active_change') or '-'}"
        )
    source_refs = list(state.get("source_refs") or [])
    if aggregate_ref in source_refs:
        return {
            "status": "idempotent-existing",
            "cr_id": cr_id,
            "aggregate_id": aggregate_id,
            "aggregate_ref": aggregate_ref,
            "payload_digest": payload_digest,
            "state_updated_at": state.get("updated_at"),
        }
    if not expected_updated_at or state.get("updated_at") != expected_updated_at:
        raise StateValidationError(
            "aggregate projection current-state CAS mismatch: expected_updated_at is stale"
        )
    source_refs.append(aggregate_ref)
    candidate = update_current_state(
        project_root,
        {
            "source_refs": source_refs,
            "next_action": {
                "type": "aggregate_pass_persisted",
                "text": (
                    f"Aggregate {aggregate_id[:12]} is persisted and validated; "
                    "continue verification without closing the CR."
                ),
            },
            "updated_at": now_utc(),
        },
        actor="meta_flow.state.current.project_aggregate_completion",
        reason=f"controlled aggregate projection for {cr_id}",
        mode="enforce",
    )
    return {
        "status": "projected",
        "cr_id": cr_id,
        "aggregate_id": aggregate_id,
        "aggregate_ref": aggregate_ref,
        "payload_digest": payload_digest,
        "state_updated_at": candidate.get("updated_at"),
    }


def _archive_timestamp() -> str:
    return now_utc().replace(":", "").replace("+", "Z").replace("-", "").replace("T", "-")


def _relative_archive_ref(timestamp: str, name: str) -> str:
    return (STATE_ARCHIVE_ROOT_REL / timestamp / name).as_posix()


def _archive_source_ref(timestamp: str) -> dict[str, str]:
    return {
        "kind": "state-slim-archive",
        "path": _relative_archive_ref(timestamp, "archived-fields.json"),
    }


def _extract_active_change(state: dict[str, Any]) -> str:
    if state.get("active_change"):
        return _compact_scalar(state["active_change"])
    cr_tracking = _nested_dict(state, "cr_tracking")
    for key in ("active_change", "active_cr", "active_cr_id"):
        if cr_tracking.get(key):
            return _compact_scalar(cr_tracking[key])
    orchestrator = _nested_dict(state, "orchestrator_session")
    if orchestrator.get("active_change"):
        return _compact_scalar(orchestrator["active_change"])
    return ""


def _extract_pending_gate(state: dict[str, Any]) -> str:
    if state.get("pending_gate"):
        return _compact_scalar(state["pending_gate"])
    return _nested_scalar(state, "orchestrator_session", "pending_gate")


def _extract_pending_checklist_path(state: dict[str, Any]) -> str:
    if state.get("pending_checklist_path"):
        return _compact_scalar(state["pending_checklist_path"])
    return _nested_scalar(state, "orchestrator_session", "pending_checklist_path")


def _extract_active_context_ref(state: dict[str, Any]) -> str:
    if state.get("active_context_ref"):
        return _compact_scalar(state["active_context_ref"])
    for parent, key in (
        ("context_budget", "active_context_ref"),
        ("context_budget", "current_context_ref"),
        ("orchestrator_session", "active_context_ref"),
    ):
        value = _nested_scalar(state, parent, key)
        if value:
            return value
    return ""


def _extract_ref_field(state: dict[str, Any], *, existing_key: str, archive_key: str) -> str:
    if state.get(existing_key):
        return _compact_scalar(state[existing_key])
    archived_value = state.get(archive_key)
    if isinstance(archived_value, dict):
        candidate_keys = (
            existing_key,
            f"{archive_key}_ref",
            f"active_{archive_key}_ref",
            "ref",
            "path",
            "context_ref",
            "release_context_ref",
            "active_release_context_ref",
            "summary_ref",
            "report_ref",
        )
        for key in candidate_keys:
            if archived_value.get(key):
                return _compact_scalar(archived_value[key])
    return ""


def _slim_next_action(state: dict[str, Any]) -> dict[str, str]:
    next_action = state.get("next_action")
    text = _latest_text(next_action)
    if not text:
        text = _latest_text(state.get("next_actions"))
    if not text:
        text = _latest_text(state.get("last_actions"))
    if not text:
        text = "Continue from current v2 state refs."
    action_type = "continue"
    if isinstance(next_action, dict) and next_action.get("type"):
        action_type = _compact_scalar(next_action["type"], max_bytes=64)
    return {"type": action_type, "text": text}


def _slim_source_refs(state: dict[str, Any], *, timestamp: str) -> list[Any]:
    refs = _bounded_list(state.get("source_refs"), max_items=23)
    archived = [key for key in sorted(SLIM_ARCHIVE_KEYS) if key in state]
    unknown = [
        key
        for key in sorted(set(state) - CURRENT_ALLOWED_KEYS - {"schema_version"})
        if key not in SLIM_ARCHIVE_KEYS
    ]
    if archived or unknown:
        refs.append(_archive_source_ref(timestamp))
    return refs[-24:]


def _slim_state_payload(
    state: dict[str, Any], *, project_root: Path, timestamp: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    base = default_current_state(
        project_root, project_id=str(state.get("project_id") or project_root.resolve().name)
    )
    base["workflow_mode"] = _compact_scalar(
        state.get("workflow_mode") or base["workflow_mode"], max_bytes=64
    )
    base["current_phase"] = _compact_scalar(
        state.get("current_phase") or base["current_phase"], max_bytes=128
    )
    base["blocked"] = bool(state.get("blocked", False))
    base["active_change"] = _extract_active_change(state) or None
    base["active_story"] = (
        _compact_scalar(state.get("active_story"), max_bytes=128)
        if state.get("active_story")
        else None
    )
    base["pending_gate"] = _extract_pending_gate(state) or None
    base["pending_checklist_path"] = _extract_pending_checklist_path(state) or None
    base["next_action"] = _slim_next_action(state)
    base["routing_ref"] = _compact_scalar(state.get("routing_ref") or ROUTING_REL.as_posix())
    base["active_context_ref"] = _extract_active_context_ref(state) or None
    base["next_session_handoff_ref"] = (
        _compact_scalar(state["next_session_handoff_ref"])
        if state.get("next_session_handoff_ref")
        else None
    )
    base["authz_policy_refs"] = _bounded_list(state.get("authz_policy_refs"), max_items=16)
    base["open_risks"] = _bounded_list(state.get("open_risks"), max_items=16, active_only=True)
    base["source_refs"] = _slim_source_refs(state, timestamp=timestamp)
    base["updated_at"] = now_utc()

    optional_archive_refs = {
        "active_delegation_ref": "delegated_interaction",
        "active_question_batch_ref": "parallel_execution",
        "artifact_routing_ref": "artifact_routing",
        "delivery_routing_ref": "delivery_routing",
        "release_context_ref": "release",
        "target_project_profile_ref": "target_project_profile",
        "workflow_health_ref": "workflow_health",
    }
    for state_key, archive_key in optional_archive_refs.items():
        value = _extract_ref_field(state, existing_key=state_key, archive_key=archive_key)
        if value:
            base[state_key] = value
    if state.get("project_state_ref"):
        base["project_state_ref"] = _compact_scalar(state["project_state_ref"])

    archived_fields = {
        key: copy.deepcopy(state[key])
        for key in sorted(SLIM_ARCHIVE_KEYS)
        if key in state and state[key] not in (None, "", [], {})
    }
    unknown_fields = {
        key: copy.deepcopy(state[key])
        for key in sorted(set(state) - CURRENT_ALLOWED_KEYS - {"schema_version"})
        if key not in SLIM_ARCHIVE_KEYS
    }
    archive = {
        "schema_version": 1,
        "generated_at": now_utc(),
        "source": STATE_CURRENT_REL.as_posix(),
        "source_sha256": _sha256_json(state),
        "source_size_bytes": _json_size(state),
        "archived_fields": archived_fields,
        "unknown_fields": unknown_fields,
    }
    return base, archive


def _slim_report(
    state: dict[str, Any], candidate: dict[str, Any], archive: dict[str, Any], *, timestamp: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": now_utc(),
        "command": "state slim",
        "source_ref": STATE_CURRENT_REL.as_posix(),
        "source_sha256": archive["source_sha256"],
        "source_size_bytes": archive["source_size_bytes"],
        "projected_size_bytes": _json_size(candidate),
        "archive_ref": _relative_archive_ref(timestamp, "archived-fields.json"),
        "report_ref": _relative_archive_ref(timestamp, "slim-report.json"),
        "archived_keys": sorted(archive["archived_fields"]),
        "unknown_archived_keys": sorted(archive["unknown_fields"]),
        "kept_keys": sorted(candidate),
        "budget_bytes": int(DEFAULT_BUDGETS["state_current_max_bytes"]),
    }


def plan_slim_current_state(
    project_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    project_root = project_root.resolve()
    path = current_state_path(project_root)
    if not path.is_file():
        raise FileNotFoundError(f"STATE.current.json missing: {path}")
    state = json.loads(path.read_text(encoding="utf-8"))
    timestamp = _archive_timestamp()
    candidate, archive = _slim_state_payload(state, project_root=project_root, timestamp=timestamp)
    validate_current_state_for_write(candidate)
    report = _slim_report(state, candidate, archive, timestamp=timestamp)
    return candidate, archive, report, timestamp


def apply_slim_current_state(project_root: Path, *, render: bool = False) -> dict[str, Any]:
    project_root = project_root.resolve()
    candidate, archive, report, timestamp = plan_slim_current_state(project_root)
    archive_dir = _resolve_runtime_ref(project_root, STATE_ARCHIVE_ROOT_REL.as_posix()) / timestamp
    archive_dir.mkdir(parents=True, exist_ok=False)
    (archive_dir / "archived-fields.json").write_text(
        json.dumps(archive, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (archive_dir / "slim-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_current_state_file(current_state_path(project_root), candidate)
    ensure_base_ledgers(project_root)
    if render:
        render_state_file(project_root, force=True)
    return report


def render_state_markdown(state: dict[str, Any]) -> str:
    next_action = state.get("next_action") or {}
    if isinstance(next_action, dict):
        next_action_text = str(next_action.get("text") or "-")
    else:
        next_action_text = str(next_action or "-")
    authz_refs = state.get("authz_policy_refs") or []
    risk_refs = state.get("open_risks") or []
    lines = [
        "# Current Meta Flow State",
        "",
        f"Project: {state.get('project_id', '-')}",
        f"Workflow mode: {state.get('workflow_mode', '-')}",
        f"Phase: {state.get('current_phase', '-')}",
        f"Blocked: {str(state.get('blocked', False)).lower()}",
        f"Active CR: {state.get('active_change') or 'none'}",
        f"Active Story: {state.get('active_story') or 'none'}",
        f"Pending gate: {state.get('pending_gate') or 'none'}",
        f"Next action: {next_action_text}",
        "",
        "Refs:",
        f"- state: {STATE_CURRENT_REL.as_posix()}",
        "- CR ledger: process/state/CR-LEDGER.ndjson",
        "- Story ledger: process/state/STORY-LEDGER.ndjson",
        "- Checkpoint ledger: process/state/CHECKPOINT-LEDGER.ndjson",
        "- Handoff ledger: process/state/HANDOFF-LEDGER.ndjson",
        "- Agent dispatch ledger: process/state/AGENT-DISPATCH-LEDGER.ndjson",
        "- Gate ledger: process/state/GATE-LEDGER.ndjson",
        "- Run ledger: process/state/RUN-LEDGER.ndjson",
        "- Read expansion ledger: process/state/READ-EXPANSION-LEDGER.ndjson",
        f"- routing: {state.get('routing_ref') or ROUTING_REL.as_posix()}",
        f"- active context: {state.get('active_context_ref') or 'none'}",
        "",
        "Policy refs:",
    ]
    if authz_refs:
        lines.extend(f"- {ref}" for ref in authz_refs)
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Open risks:")
    if risk_refs:
        lines.extend(f"- {ref}" for ref in risk_refs)
    else:
        lines.append("- none")
    lines.append("")
    lines.append(f"Updated at: {state.get('updated_at', '-')}")
    lines.append("")
    lines.append("<!-- generated-by: meta-flow state render -->")
    return "\n".join(lines) + "\n"


def render_state_file(project_root: Path, *, force: bool = False) -> Path:
    project_root = project_root.resolve()
    state = load_current_state(project_root)
    if not state:
        raise FileNotFoundError(f"未找到 v2 状态文件: {current_state_path(project_root)}")
    path = state_md_path(project_root)
    if path.exists() and not force:
        existing = path.read_text(encoding="utf-8", errors="ignore")
        if "generated-by: meta-flow state render" not in existing:
            raise FileExistsError(
                f"{path} 已存在且不是 state render 生成物；如需覆盖请使用 --force"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_state_markdown(state), encoding="utf-8")
    refresh_current_entry(project_root)
    return path


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def render_history_markdown(project_root: Path) -> str:
    project_root = project_root.resolve()
    cr_events = _load_ndjson(_resolve_runtime_ref(project_root, "process/state/CR-LEDGER.ndjson"))
    checkpoint_events = _load_ndjson(
        _resolve_runtime_ref(project_root, "process/state/CHECKPOINT-LEDGER.ndjson")
    )
    lines = [
        "# Meta Flow State History",
        "",
        "> Generated deny-default audit view. Machine truth remains in ledgers, CR index, summaries, checkpoint results, and archive files.",
        "",
        "## CR Events",
        "",
    ]
    if cr_events:
        lines.extend(
            [
                "| CR | Event | Status | Summary | Full Ref |",
                "|---|---|---|---|---|",
            ]
        )
        for event in cr_events:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(event.get("id") or event.get("cr_id") or "-"),
                        str(event.get("event") or event.get("event_type") or "-"),
                        str(event.get("status") or "-"),
                        str(event.get("summary_ref") or "-"),
                        str(event.get("full_ref") or "-"),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Checkpoint Events", ""])
    if checkpoint_events:
        lines.extend(
            [
                "| Checkpoint | Decision | Result | Context |",
                "|---|---|---|---|",
            ]
        )
        for event in checkpoint_events:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(event.get("checkpoint") or "-"),
                        str(event.get("decision") or "-"),
                        str(event.get("result_ref") or "-"),
                        str(event.get("context_ref") or "-"),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("<!-- generated-by: meta-flow state history-render -->")
    return "\n".join(lines) + "\n"


def render_history_file(project_root: Path, *, force: bool = False) -> Path:
    project_root = project_root.resolve()
    path = _resolve_runtime_ref(project_root, STATE_HISTORY_REL.as_posix())
    if path.exists() and not force:
        existing = path.read_text(encoding="utf-8", errors="ignore")
        if "generated-by: meta-flow state history-render" not in existing:
            raise FileExistsError(
                f"{path} 已存在且不是 history-render 生成物；如需覆盖请使用 --force"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_history_markdown(project_root), encoding="utf-8")
    return path


def check_current_state(
    project_root: Path,
    *,
    mode: str = "audit",
    process_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    project_root = project_root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    injected_root = process_root.resolve() if process_root is not None else None

    def read_ref(logical_ref: str) -> Path:
        if injected_root is not None:
            return _resolve_injected_process_ref(injected_root, logical_ref)
        return _resolve_runtime_ref(project_root, logical_ref)

    def read_path(value: str | Path) -> Path:
        candidate = Path(value)
        if injected_root is not None and not candidate.is_absolute():
            logical = candidate.as_posix()
            if logical.startswith("process/"):
                return _resolve_injected_process_ref(injected_root, logical)
        return _resolve_runtime_path(project_root, candidate)

    budgets = load_budgets(project_root, process_root=injected_root)
    state_path = read_ref(STATE_CURRENT_REL.as_posix())
    markdown_path = read_ref(STATE_MD_REL.as_posix())
    if not state_path.is_file():
        errors.append(f"STATE.current.json missing: {state_path}")
        return errors, warnings

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"STATE.current.json invalid JSON: {exc}")
        return errors, warnings

    current_max = int(
        budgets.get("state_current_max_bytes", DEFAULT_BUDGETS["state_current_max_bytes"])
    )
    current_size = state_path.stat().st_size
    if current_size > current_max:
        errors.append(
            f"STATE.current.json too large: {format_bytes(current_size)} > {format_bytes(current_max)}"
        )
    findings = validate_current_state_payload(state, mode=mode)
    warnings.extend(finding.as_cli_line() for finding in findings if finding.severity == "WARN")
    errors.extend(finding.as_cli_line() for finding in findings if finding.severity == "ERROR")
    legacy_long_keys = (set(state) & SLIM_ARCHIVE_KEYS) - CURRENT_ALLOWED_KEYS
    if legacy_long_keys or (set(state) - CURRENT_ALLOWED_KEYS - {"schema_version"}):
        warnings.append(
            "STATE.current.json contains legacy or long-running fields; run `meta-flow state slim --dry-run` and then `--apply` after review"
        )
    if "expanded_text" in json.dumps(state, ensure_ascii=False):
        errors.append("STATE.current.json must reference policy IDs, not expanded policy text")
    project_state_ref = state.get("project_state_ref")
    if isinstance(project_state_ref, str) and project_state_ref:
        try:
            project_state_exists = read_path(project_state_ref).is_file()
        except OSError:
            project_state_exists = False
        if not project_state_exists:
            errors.append(f"project_state_ref points to missing file: {project_state_ref}")
    workflow_health_ref = state.get("workflow_health_ref")
    if isinstance(workflow_health_ref, str) and workflow_health_ref:
        health_path = read_path(workflow_health_ref)
        if not _is_relative_state_ref(workflow_health_ref) or not health_path.is_file():
            errors.append(
                f"workflow_health_ref points to missing or unsafe file: {workflow_health_ref}"
            )
        else:
            try:
                health = json.loads(health_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                health = None
            if not isinstance(health, dict) or not isinstance(health.get("phase_counters"), dict):
                errors.append(
                    f"workflow_health_ref is not a valid workflow health report: {workflow_health_ref}"
                )
    for ledger_rel in BASE_LEDGER_RELS:
        ledger_path = read_ref(ledger_rel.as_posix())
        if not ledger_path.is_file():
            errors.append(f"base ledger missing: {ledger_path}")

    if not markdown_path.is_file():
        message = f"STATE.md summary missing: {markdown_path}"
        (errors if mode == "enforce" else warnings).append(message)
    else:
        md_max = int(budgets.get("state_md_max_bytes", DEFAULT_BUDGETS["state_md_max_bytes"]))
        md_size = markdown_path.stat().st_size
        if md_size > md_max:
            errors.append(f"STATE.md too large: {format_bytes(md_size)} > {format_bytes(md_max)}")
        md_text = markdown_path.read_text(encoding="utf-8", errors="ignore")
        if STATE_CURRENT_REL.as_posix() not in md_text:
            warnings.append("STATE.md does not reference process/state/STATE.current.json")
        for finding in validate_state_markdown_projection(state, md_text):
            target = errors if mode == "enforce" else warnings
            target.append(finding.message)

    # Injected process roots are used by read-only adoption inspection and do
    # not necessarily have a configured runtime route.  The canonical project
    # check path validates CURRENT through the binding-aware runtime resolver.
    if injected_root is None:
        for finding in validate_current_projection(project_root):
            target = errors if mode == "enforce" else warnings
            target.append(f"{finding.code}: {finding.message}")
    return errors, warnings


def _print_state_help() -> None:
    print(
        "usage: meta-flow state <command> [options]\n\n"
        "Commands:\n"
        "  init        Create a fresh process/state/STATE.current.json and base ledgers.\n"
        "  migrate-v2  Create process/state/STATE.current.json from legacy process/STATE.md.\n"
        "  render      Render process/STATE.md as a human summary from STATE.current.json.\n"
        "  current-refresh Refresh process/current/CURRENT.json and current *.ref/symlink pointers.\n"
        "  history-render Render process/state/HISTORY.md as a deny-default audit view from ledgers.\n"
        "  health-update Update phase-level workflow health counters.\n"
        "  slim        Archive legacy long fields and rewrite STATE.current.json as v2 refs/scalars.\n"
        "  check       Validate STATE.current.json and generated STATE.md budgets.\n"
        "  compact     Render the human summary and run state check; it does not slim state or compact ledgers.\n\n"
        "Examples:\n"
        "  meta-flow state init --project-root . --project-id my-project --dry-run\n"
        "  meta-flow state migrate-v2 --project-root .\n"
        "  meta-flow state render --project-root . --force\n"
        "  meta-flow state current-refresh --project-root . --dry-run\n"
        "  meta-flow state health-update --project-root . --phase CP5 --increment cp_retry_count=1\n"
        "  meta-flow state slim --project-root . --dry-run\n"
        "  meta-flow state slim --project-root . --apply --render\n"
        "  meta-flow state check --project-root . --mode audit\n"
        "  meta-flow state check --project-root . --mode enforce\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_state_help()
        return 0
    command = args[0]
    description = (
        "Render process/STATE.md from STATE.current.json and run state check; "
        "this command does not compact NDJSON event ledgers or slim STATE.current.json."
        if command == "compact"
        else None
    )
    parser = argparse.ArgumentParser(prog=f"meta-flow state {command}", description=description)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--mode", choices=("audit", "enforce"), default="audit")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--phase", default="")
    parser.add_argument("--increment", action="append", default=[])
    parsed = parser.parse_args(args[1:])
    project_root = parsed.project_root.resolve()

    if command == "init":
        if parsed.dry_run:
            print(
                json.dumps(
                    plan_init_current_state(
                        project_root,
                        project_id=parsed.project_id,
                        force=parsed.force,
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        path = init_current_state(project_root, project_id=parsed.project_id, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "migrate-v2":
        state = migrate_legacy_state(project_root)
        path = write_current_state(project_root, state, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "render":
        path = render_state_file(project_root, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "current-refresh":
        if parsed.dry_run:
            print(
                json.dumps(
                    plan_current_entry_refresh(project_root),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        path = refresh_current_entry(project_root)
        print(f"wrote: {path}")
        return 0
    if command == "history-render":
        path = render_history_file(project_root, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "health-update":
        increments: dict[str, int] = {}
        for item in parsed.increment:
            if "=" not in item:
                raise SystemExit(f"--increment must use key=value: {item}")
            key, raw_value = item.split("=", 1)
            try:
                increments[key] = int(raw_value)
            except ValueError as exc:
                raise SystemExit(f"--increment value must be an integer: {item}") from exc
        if not increments:
            raise SystemExit("health-update requires at least one --increment key=value")
        payload, path = update_workflow_health(
            project_root, phase=parsed.phase, increments=increments
        )
        print(f"wrote: {path}")
        print(f"phase: {parsed.phase}")
        print(
            "counters: "
            + json.dumps(
                payload.get("phase_counters", {}).get(parsed.phase, {}),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if command == "slim":
        if parsed.apply and parsed.dry_run:
            raise SystemExit("--apply and --dry-run are mutually exclusive")
        if parsed.apply:
            report = apply_slim_current_state(project_root, render=parsed.render)
            print("State v2 Slim: APPLIED")
        else:
            _candidate, _archive, report, _timestamp = plan_slim_current_state(project_root)
            print("State v2 Slim: DRY-RUN")
        print(f"- source_size: {format_bytes(int(report['source_size_bytes']))}")
        print(f"- projected_size: {format_bytes(int(report['projected_size_bytes']))}")
        print(f"- archive_ref: {report['archive_ref']}")
        print(
            "- archived_keys: "
            + (", ".join(report["archived_keys"]) if report["archived_keys"] else "none")
        )
        max_bytes = int(
            load_budgets(project_root).get(
                "state_current_max_bytes", DEFAULT_BUDGETS["state_current_max_bytes"]
            )
        )
        if int(report["projected_size_bytes"]) > max_bytes:
            print(
                f"- ERROR: projected STATE.current.json exceeds budget: {format_bytes(int(report['projected_size_bytes']))} > {format_bytes(max_bytes)}"
            )
            return 1
        return 0
    if command == "check":
        errors, warnings = check_current_state(project_root, mode=parsed.mode)
        print("State v2 Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "compact":
        render_state_file(project_root, force=parsed.force)
        errors, warnings = check_current_state(project_root, mode=parsed.mode)
        print("State v2 Compact: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(
        "未知 state 命令: "
        f"{command}. 目前支持: init, migrate-v2, render, current-refresh, history-render, health-update, slim, check, compact"
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
