"""只读最小 Project/Phase/Work 查询投影。"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.project.governance import load_phase
from meta_flow.project.model import load_project
from meta_flow.project.process_route import ProcessRouteError, require_process_route
from meta_flow.project.read_contract import ReadContextProtocol, ReadContractError
from meta_flow.work.model import load_work
from meta_flow.work.read_context import OperationReadContext


@dataclass(frozen=True)
class ProjectQueryResult:
    decision: str
    project: dict[str, Any]
    phase: dict[str, Any] | None
    work: dict[str, Any] | None
    objects_read: int
    refs: tuple[str, ...]
    errors: tuple[str, ...]
    error_codes: tuple[str, ...] = ()
    blocked_ref: str = ""


def query_project_status(
    process_root: Path,
    *,
    work_id: str | None = None,
    max_objects: int = 5,
    read_context: ReadContextProtocol | None = None,
) -> ProjectQueryResult:
    if max_objects < 1 or max_objects > 5:
        raise ValueError("default query max_objects must be between 1 and 5")
    owned_context = read_context is None
    context = read_context or OperationReadContext(
        process_root,
        operation_id="project.query",
        operation_kind="query",
        allowed_reads=("PROJECT.yaml", "phases/**", "works/**"),
        max_objects=max_objects,
    )
    context.assert_operation("query")

    def finish(
        *,
        decision: str,
        project: dict[str, Any],
        phase: dict[str, Any] | None,
        work: dict[str, Any] | None,
        errors: list[str],
        error_codes: list[str] | None = None,
        blocked_ref: str = "",
    ) -> ProjectQueryResult:
        result = ProjectQueryResult(
            decision=decision,
            project=project,
            phase=phase,
            work=work,
            objects_read=context.objects_read,
            refs=context.refs,
            errors=tuple(errors),
            error_codes=tuple(error_codes or ()),
            blocked_ref=blocked_ref,
        )
        if owned_context:
            context.close()
        return result

    errors: list[str] = []
    try:
        project = load_project(process_root, read_context=context)
    except ReadContractError as exc:
        return finish(
            decision="BLOCKED",
            project={},
            phase=None,
            work=None,
            errors=[str(exc)],
            error_codes=[exc.error_code],
            blocked_ref=exc.logical_ref,
        )
    except (OSError, ValueError) as exc:
        return finish(
            decision="BLOCKED",
            project={},
            phase=None,
            work=None,
            errors=[str(exc)],
        )
    phase_payload: dict[str, Any] | None = None
    if project.active_phase_ref:
        try:
            phase = load_phase(
                process_root,
                project.active_phase_ref,
                read_context=context,
            )
            if phase.project_id != project.project_id:
                errors.append("active Phase project_id does not match Project")
            else:
                phase_payload = phase.as_dict()
        except ReadContractError as exc:
            return finish(
                decision="BLOCKED",
                project=project.as_dict(),
                phase=None,
                work=None,
                errors=[*errors, str(exc)],
                error_codes=[exc.error_code],
                blocked_ref=exc.logical_ref,
            )
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
    if selected_work_id is not None:
        expected_ref = f"works/{selected_work_id}/WORK.yaml"
        if expected_ref not in project.active_work_refs:
            errors.append(f"requested Work is not active in Project: {expected_ref}")
        else:
            try:
                work = load_work(
                    process_root,
                    selected_work_id,
                    read_context=context,
                )
                if work.project_id != project.project_id:
                    errors.append("active Work project_id does not match Project")
                else:
                    work_payload = work.as_dict()
            except ReadContractError as exc:
                return finish(
                    decision="BLOCKED",
                    project=project.as_dict(),
                    phase=phase_payload,
                    work=None,
                    errors=[*errors, str(exc)],
                    error_codes=[exc.error_code],
                    blocked_ref=exc.logical_ref,
                )
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
    return finish(
        decision="BLOCKED" if errors else "PASS",
        project=project.as_dict(),
        phase=phase_payload,
        work=work_payload,
        errors=errors,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow project query")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-id", default=None)
    parser.add_argument("--max-objects", type=int, default=5)
    parsed = parser.parse_args(argv or [])
    try:
        route = require_process_route(parsed.project_root)
    except ProcessRouteError as exc:
        payload = {
            "decision": "BLOCKED",
            "errors": [str(exc)],
            "error_codes": [exc.error_code],
            "objects_read": 0,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    try:
        with OperationReadContext.from_route(
            route,
            operation_id="project.query.cli",
            operation_kind="query",
            allowed_reads=("PROJECT.yaml", "phases/**", "works/**"),
            max_objects=parsed.max_objects,
        ) as read_context:
            result = query_project_status(
                route.process_root,
                work_id=parsed.work_id,
                max_objects=parsed.max_objects,
                read_context=read_context,
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
                "error_codes": list(result.error_codes),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.decision == "PASS" else 1
