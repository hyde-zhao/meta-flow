"""证据化复盘 CLI；默认只做 dry-run。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from meta_flow.project.onboarding import check_independent_process_route
from meta_flow.project.scale import load_yaml_object
from meta_flow.retrospective import (
    confirm_retrospective_facts,
    load_retrospective,
    retrospective_from_payload,
    validate_retrospective,
    write_retrospective_create_only,
)


def _process_root(project_root: Path) -> Path:
    health = check_independent_process_route(project_root)
    if not health.ok or health.process_repo_root is None:
        raise ValueError("vNext project route is not healthy: " + "; ".join(health.errors))
    return health.process_repo_root


def build_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow retrospective build")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(argv)
    try:
        process_root = _process_root(parsed.project_root)
        retro = retrospective_from_payload(load_yaml_object(parsed.input))
        validate_retrospective(retro)
        if parsed.apply:
            data_path, report_path = write_retrospective_create_only(process_root, retro)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    payload = {
        "decision": "PASS" if parsed.apply else "READY",
        "retro_id": retro.retro_id,
        "scope_kind": retro.scope_kind,
        "dimension_count": len(retro.dimensions),
        "candidate_count": len(retro.candidates),
        "mutation_count": 2 if parsed.apply else 0,
        "implementation_authorized": False,
        "publication_authorized": False,
    }
    if parsed.apply:
        payload["data_ref"] = data_path.relative_to(process_root).as_posix()
        payload["report_ref"] = report_path.relative_to(process_root).as_posix()
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def check_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow retrospective check")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", required=True)
    parsed = parser.parse_args(argv)
    try:
        process_root = _process_root(parsed.project_root)
        retro = load_retrospective(process_root, parsed.id)
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {
                "decision": "PASS",
                "retro_id": retro.retro_id,
                "status": retro.status,
                "dimensions": [
                    {
                        "dimension_id": item.dimension_id,
                        "measurement_quality": item.measurement_quality,
                    }
                    for item in retro.dimensions
                ],
                "stage_usage_count": len(retro.stage_usage),
                "candidate_count": len(retro.candidates),
                "implementation_authorized": False,
                "publication_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def confirm_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow retrospective confirm-facts")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", required=True)
    parser.add_argument("--confirmation-ref", required=True)
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(argv)
    try:
        process_root = _process_root(parsed.project_root)
        current = load_retrospective(process_root, parsed.id)
        if current.status != "draft":
            raise ValueError("retrospective facts can only be confirmed from draft")
        if parsed.apply:
            current = confirm_retrospective_facts(
                process_root,
                parsed.id,
                confirmation_ref=parsed.confirmation_ref,
            )
    except (OSError, ValueError) as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {
                "decision": "PASS" if parsed.apply else "READY",
                "retro_id": parsed.id,
                "target_status": "facts_confirmed",
                "confirmation_ref": parsed.confirmation_ref,
                "mutation_count": 2 if parsed.apply else 0,
                "implementation_authorized": False,
                "publication_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv or []
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: meta-flow retrospective <build|check|confirm-facts> [options]\n\n"
            "All mutating commands are dry-run by default and require --apply.\n"
        )
        return 0
    command, forwarded = args[0], args[1:]
    if command == "build":
        return build_main(forwarded)
    if command == "check":
        return check_main(forwarded)
    if command == "confirm-facts":
        return confirm_main(forwarded)
    raise SystemExit("未知 retrospective 命令，目前支持: build, check, confirm-facts")
