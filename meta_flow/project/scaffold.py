"""Dry-run/apply scaffold for process/project/PROJECT.current.json."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.state import (
    PROJECT_CURRENT_REL,
    validate_project_current,
    validate_project_current_payload,
)
from meta_flow.state import current


@dataclass(frozen=True)
class ScaffoldAction:
    action: str
    path: str
    reason: str


@dataclass(frozen=True)
class ScaffoldPlan:
    project_root: Path
    project_id: str
    project_name: str
    project_state_ref: str
    payload: dict[str, Any]
    actions: tuple[ScaffoldAction, ...]

    @property
    def has_conflict(self) -> bool:
        return any(action.action == "conflict" for action in self.actions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_root": str(self.project_root),
            "project_id": self.project_id,
            "project_name": self.project_name,
            "project_state_ref": self.project_state_ref,
            "actions": [action.__dict__ for action in self.actions],
        }


def _read_current_project_id(project_root: Path) -> str:
    state = current.load_current_state(project_root)
    return str(state.get("project_id") or project_root.resolve().name)


def build_project_current_payload(
    *,
    project_id: str,
    project_name: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": project_id,
        "project_name": project_name,
        "updated_at": updated_at or current.now_utc(),
        "active_governance_refs": [],
        "source_refs": [],
    }


def _same_project_identity(existing: dict[str, Any], *, project_root: Path, project_id: str, project_name: str) -> bool:
    errors = [
        finding for finding in validate_project_current_payload(
            existing,
            project_root=project_root,
            require_ref_targets=True,
        )
        if finding.severity == "ERROR"
    ]
    if errors:
        return False
    return existing.get("project_id") == project_id and existing.get("project_name") == project_name


def build_project_scaffold_plan(
    project_root: Path,
    *,
    project_id: str | None = None,
    project_name: str | None = None,
) -> ScaffoldPlan:
    root = project_root.resolve()
    resolved_project_id = project_id or _read_current_project_id(root)
    resolved_project_name = project_name or resolved_project_id
    payload = build_project_current_payload(
        project_id=resolved_project_id,
        project_name=resolved_project_name,
    )
    project_dir = root / "process" / "project"
    project_current_path = root / PROJECT_CURRENT_REL
    actions: list[ScaffoldAction] = []
    if project_dir.exists() and not project_dir.is_dir():
        actions.append(ScaffoldAction("conflict", "process/project", "path exists and is not a directory"))
    elif project_dir.is_dir():
        actions.append(ScaffoldAction("noop", "process/project", "directory already exists"))
    else:
        actions.append(ScaffoldAction("create", "process/project", "create project governance scaffold directory"))

    if project_current_path.exists():
        try:
            existing = json.loads(project_current_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = None
        if isinstance(existing, dict) and _same_project_identity(
            existing,
            project_root=root,
            project_id=resolved_project_id,
            project_name=resolved_project_name,
        ):
            actions.append(ScaffoldAction("noop", PROJECT_CURRENT_REL.as_posix(), "valid PROJECT.current.json already exists"))
        else:
            actions.append(ScaffoldAction("conflict", PROJECT_CURRENT_REL.as_posix(), "existing PROJECT.current.json is invalid or has different project identity"))
    else:
        actions.append(ScaffoldAction("create", PROJECT_CURRENT_REL.as_posix(), "create minimal refs-only PROJECT.current.json"))

    return ScaffoldPlan(
        project_root=root,
        project_id=resolved_project_id,
        project_name=resolved_project_name,
        project_state_ref=PROJECT_CURRENT_REL.as_posix(),
        payload=payload,
        actions=tuple(actions),
    )


def _write_json_no_overwrite(path: Path, data: dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def apply_project_scaffold(plan: ScaffoldPlan, *, render_state: bool = False) -> dict[str, Any]:
    if plan.has_conflict:
        conflicts = [action.path for action in plan.actions if action.action == "conflict"]
        raise FileExistsError("project scaffold has conflicts: " + ", ".join(conflicts))
    errors = [
        finding.message
        for finding in validate_project_current_payload(plan.payload)
        if finding.severity == "ERROR"
    ]
    if errors:
        raise ValueError("PROJECT.current baseline is invalid: " + "; ".join(errors))

    project_dir = plan.project_root / "process" / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    project_current_path = plan.project_root / PROJECT_CURRENT_REL
    created: list[str] = []
    if not project_current_path.exists():
        _write_json_no_overwrite(project_current_path, plan.payload)
        created.append(PROJECT_CURRENT_REL.as_posix())

    check_errors, _warnings = validate_project_current(plan.project_root)
    if check_errors:
        raise ValueError("PROJECT.current check failed after scaffold: " + "; ".join(check_errors))
    updated_state = current.update_current_state(
        plan.project_root,
        {"project_state_ref": plan.project_state_ref},
        actor="meta-dev:CR037-S05",
        reason="project scaffold baseline",
        render=render_state,
    )
    return {
        "created": created,
        "project_state_ref": plan.project_state_ref,
        "updated_state_project_ref": updated_state.get("project_state_ref"),
    }


def _print_plan(plan: ScaffoldPlan) -> None:
    print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project scaffold")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--project-name", default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--render-state", action="store_true")
    parsed = parser.parse_args(argv or [])
    plan = build_project_scaffold_plan(
        parsed.project_root,
        project_id=parsed.project_id,
        project_name=parsed.project_name,
    )
    if not parsed.apply:
        _print_plan(plan)
        return 1 if plan.has_conflict else 0
    try:
        result = apply_project_scaffold(plan, render_state=parsed.render_state)
    except (FileExistsError, ValueError) as exc:
        _print_plan(plan)
        print(f"- ERROR: {exc}")
        return 1
    print(json.dumps({"plan": plan.as_dict(), "result": result}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
