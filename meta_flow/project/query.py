"""只读最小 Project/Phase/Work 查询投影。"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.governance import load_phase
from meta_flow.project.model import load_project
from meta_flow.project.onboarding import check_independent_process_route
from meta_flow.work.model import load_work


@dataclass(frozen=True)
class ProjectQueryResult:
    decision: str
    project: dict[str, Any]
    phase: dict[str, Any] | None
    work: dict[str, Any] | None
    objects_read: int
    refs: tuple[str, ...]
    errors: tuple[str, ...]


def query_project_status(
    process_root: Path,
    *,
    work_id: str | None = None,
    max_objects: int = 5,
) -> ProjectQueryResult:
    if max_objects < 1 or max_objects > 5:
        raise ValueError("default query max_objects must be between 1 and 5")
    errors: list[str] = []
    refs: list[str] = []
    objects_read = 0
    try:
        project = load_project(process_root)
        objects_read += 1
        refs.append("PROJECT.yaml")
    except (OSError, ValueError) as exc:
        return ProjectQueryResult("BLOCKED", {}, None, None, objects_read, tuple(refs), (str(exc),))
    phase_payload: dict[str, Any] | None = None
    if project.active_phase_ref and objects_read < max_objects:
        try:
            phase = load_phase(process_root, project.active_phase_ref)
            objects_read += 1
            refs.append(project.active_phase_ref)
            if phase.project_id != project.project_id:
                errors.append("active Phase project_id does not match Project")
            else:
                phase_payload = phase.as_dict()
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    selected_work_id = work_id
    if selected_work_id is None and len(project.active_work_refs) == 1:
        parts = Path(project.active_work_refs[0]).parts
        if len(parts) == 3 and parts[0] == "works" and parts[2] == "WORK.yaml":
            selected_work_id = parts[1]
        else:
            errors.append(f"active Work ref has invalid shape: {project.active_work_refs[0]}")
    work_payload: dict[str, Any] | None = None
    if selected_work_id is not None and objects_read < max_objects:
        expected_ref = f"works/{selected_work_id}/WORK.yaml"
        if expected_ref not in project.active_work_refs:
            errors.append(f"requested Work is not active in Project: {expected_ref}")
        else:
            try:
                work = load_work(process_root, selected_work_id)
                objects_read += 1
                refs.append(expected_ref)
                if work.project_id != project.project_id:
                    errors.append("active Work project_id does not match Project")
                else:
                    work_payload = work.as_dict()
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
    return ProjectQueryResult(
        decision="BLOCKED" if errors else "PASS",
        project=project.as_dict(),
        phase=phase_payload,
        work=work_payload,
        objects_read=objects_read,
        refs=tuple(refs),
        errors=tuple(errors),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project query")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", default=None)
    parser.add_argument("--max-objects", type=int, default=5)
    parsed = parser.parse_args(argv or [])
    health = check_independent_process_route(parsed.project_root)
    if not health.ok or health.process_repo_root is None:
        payload = {
            "decision": "BLOCKED",
            "errors": list(health.errors),
            "objects_read": 0,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    try:
        result = query_project_status(
            health.process_repo_root,
            work_id=parsed.work_id,
            max_objects=parsed.max_objects,
        )
    except ValueError as exc:
        print(
            json.dumps(
                {"decision": "BLOCKED", "errors": [str(exc)], "objects_read": 0},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                **result.__dict__,
                "refs": list(result.refs),
                "errors": list(result.errors),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.decision == "PASS" else 1
