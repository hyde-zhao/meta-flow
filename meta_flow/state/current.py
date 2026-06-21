"""Lightweight runtime state v2 support."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from meta_flow.checks.token_budget import DEFAULT_BUDGETS, format_bytes, load_budgets


STATE_SCHEMA_VERSION = 2
STATE_CURRENT_REL = Path("process/state/STATE.current.json")
STATE_MD_REL = Path("process/STATE.md")
ROUTING_REL = Path("process/.meta-flow-process.yaml")
BASE_LEDGER_RELS = (
    Path("process/state/CHECKPOINT-LEDGER.ndjson"),
    Path("process/state/HANDOFF-LEDGER.ndjson"),
    Path("process/state/AGENT-DISPATCH-LEDGER.ndjson"),
    Path("process/state/GATE-LEDGER.ndjson"),
    Path("process/state/RUN-LEDGER.ndjson"),
)
DISALLOWED_CURRENT_KEYS = {
    "closed_crs",
    "cr_tracking",
    "history",
    "decision_briefs",
    "parallel_execution",
    "human_gate_decisions",
    "checkpoints",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def current_state_path(project_root: Path) -> Path:
    return project_root / STATE_CURRENT_REL


def state_md_path(project_root: Path) -> Path:
    return project_root / STATE_MD_REL


def default_current_state(project_root: Path) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "project_id": project_root.resolve().name,
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
        "authz_policy_refs": [],
        "open_risks": [],
        "updated_at": now_utc(),
        "source_refs": [],
    }


def migrate_legacy_state(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    path = state_md_path(project_root)
    if not path.is_file():
        raise FileNotFoundError(f"未找到 legacy 状态文件: {path}")
    text = path.read_text(encoding="utf-8")
    frontmatter = _frontmatter(text)
    if not frontmatter:
        raise ValueError(f"legacy STATE.md 缺少 frontmatter: {path}")

    pending_gate = _scalar_value(frontmatter, "pending_gate", section="orchestrator_session") or None
    pending_checklist_path = _scalar_value(frontmatter, "pending_checklist_path", section="orchestrator_session") or None
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for ledger_rel in BASE_LEDGER_RELS:
        ledger_path = project_root / ledger_rel
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.touch(exist_ok=True)
    return path


def load_current_state(project_root: Path) -> dict[str, Any]:
    return _read_json(current_state_path(project_root.resolve()))


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
            raise FileExistsError(f"{path} 已存在且不是 state render 生成物；如需覆盖请使用 --force")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_state_markdown(state), encoding="utf-8")
    return path


def check_current_state(project_root: Path) -> tuple[list[str], list[str]]:
    project_root = project_root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    budgets = load_budgets(project_root)
    state_path = current_state_path(project_root)
    markdown_path = state_md_path(project_root)
    if not state_path.is_file():
        errors.append(f"STATE.current.json missing: {state_path}")
        return errors, warnings

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"STATE.current.json invalid JSON: {exc}")
        return errors, warnings

    current_max = int(budgets.get("state_current_max_bytes", DEFAULT_BUDGETS["state_current_max_bytes"]))
    current_size = state_path.stat().st_size
    if current_size > current_max:
        errors.append(f"STATE.current.json too large: {format_bytes(current_size)} > {format_bytes(current_max)}")
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {STATE_SCHEMA_VERSION}")
    for key in ("project_id", "workflow_mode", "current_phase", "blocked", "next_action", "updated_at"):
        if key not in state:
            errors.append(f"missing required field: {key}")
    for key in sorted(DISALLOWED_CURRENT_KEYS):
        if key in state:
            errors.append(f"STATE.current.json must not store long-running field: {key}")
    authz_refs = state.get("authz_policy_refs", [])
    if not isinstance(authz_refs, list) or not all(isinstance(ref, str) for ref in authz_refs):
        errors.append("authz_policy_refs must be a list of policy ID strings")
    if "expanded_text" in json.dumps(state, ensure_ascii=False):
        errors.append("STATE.current.json must reference policy IDs, not expanded policy text")
    for ledger_rel in BASE_LEDGER_RELS:
        ledger_path = project_root / ledger_rel
        if not ledger_path.is_file():
            errors.append(f"base ledger missing: {ledger_path}")

    if not markdown_path.is_file():
        warnings.append(f"STATE.md summary missing: {markdown_path}")
    else:
        md_max = int(budgets.get("state_md_max_bytes", DEFAULT_BUDGETS["state_md_max_bytes"]))
        md_size = markdown_path.stat().st_size
        if md_size > md_max:
            errors.append(f"STATE.md too large: {format_bytes(md_size)} > {format_bytes(md_max)}")
        md_text = markdown_path.read_text(encoding="utf-8", errors="ignore")
        if STATE_CURRENT_REL.as_posix() not in md_text:
            warnings.append("STATE.md does not reference process/state/STATE.current.json")
    return errors, warnings


def _print_state_help() -> None:
    print(
        "usage: meta-flow state <command> [options]\n\n"
        "Commands:\n"
        "  migrate-v2  Create process/state/STATE.current.json from legacy process/STATE.md.\n"
        "  render      Render process/STATE.md as a human summary from STATE.current.json.\n"
        "  check       Validate STATE.current.json and generated STATE.md budgets.\n"
        "  compact     Render the human summary and run state check.\n\n"
        "Examples:\n"
        "  meta-flow state migrate-v2 --project-root .\n"
        "  meta-flow state render --project-root . --force\n"
        "  meta-flow state check --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_state_help()
        return 0
    command = args[0]
    parser = argparse.ArgumentParser(prog=f"meta-flow state {command}")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--force", action="store_true")
    parsed = parser.parse_args(args[1:])
    project_root = parsed.project_root.resolve()

    if command == "migrate-v2":
        state = migrate_legacy_state(project_root)
        path = write_current_state(project_root, state, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "render":
        path = render_state_file(project_root, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "check":
        errors, warnings = check_current_state(project_root)
        print("State v2 Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "compact":
        render_state_file(project_root, force=parsed.force)
        errors, warnings = check_current_state(project_root)
        print("State v2 Compact: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 state 命令: {command}. 目前支持: migrate-v2, render, check, compact")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
