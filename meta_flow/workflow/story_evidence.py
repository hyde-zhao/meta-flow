"""Story return packets, evidence indexes, and design deltas."""

from __future__ import annotations

import argparse
import json
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from meta_flow.context_pack import story_contract


EVIDENCE_ROOT_REL = Path("process/evidence")
DESIGN_DELTA_ROOT_REL = Path("process/design-deltas")

ALLOWED_RETURN_PACKET_TYPES = {"story_return_packet"}
ALLOWED_RETURN_STAGES = {"CP6", "CP7"}
ALLOWED_CP6_STATUSES = {
    "implemented",
    "implemented_with_risk",
    "partial",
    "blocked",
    "needs_design_clarification",
    "needs_user_decision",
    "needs_rework",
    "no_op",
    "superseded",
    "waived",
}
ALLOWED_CP7_STATUSES = {
    "verified",
    "verified_with_risk",
    "partial",
    "blocked",
    "needs_rework",
    "needs_design_clarification",
    "needs_user_decision",
    "no_op",
    "superseded",
    "waived",
}
NON_TERMINAL_STATUSES = {
    "blocked",
    "needs_design_clarification",
    "needs_user_decision",
    "needs_rework",
    "partial",
    "no_op",
    "superseded",
    "waived",
}
ALLOWED_DELTA_TYPES = {"none", "patch", "new_contract", "migration", "open_question"}
ALLOWED_DELTA_STATUSES = {"pending", "merged", "deferred", "waived"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} invalid JSON: {exc}") from exc


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _infer_project_root(path: Path) -> Path:
    for parent in path.resolve().parents:
        if parent.name == "process":
            return parent.parent
    return Path.cwd().resolve()


def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if str(item)]


def _entry_path(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("path") or "")
    return str(entry or "")


def _changed_file_path(entry: Any) -> str:
    return _entry_path(entry)


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    return any(rel_path == pattern or fnmatch(rel_path, pattern) for pattern in patterns)


def default_return_path(project_root: Path, story_id: str, stage: str) -> Path:
    return project_root / "process" / "returns" / f"{story_id}.{stage}.return.json"


def default_evidence_path(project_root: Path, story_id: str, stage: str) -> Path:
    return project_root / EVIDENCE_ROOT_REL / f"{story_id}.{stage}.index.json"


def default_design_delta_path(project_root: Path, story_id: str) -> Path:
    return project_root / DESIGN_DELTA_ROOT_REL / f"{story_id}.delta.json"


def load_return_packet(path: Path) -> dict[str, Any]:
    return _read_json(path.resolve())


def _allowed_statuses(stage: str) -> set[str]:
    if stage == "CP6":
        return ALLOWED_CP6_STATUSES
    if stage == "CP7":
        return ALLOWED_CP7_STATUSES
    return set()


def validate_return_packet(
    return_path: Path,
    *,
    packet_path: Path | None = None,
    project_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    return_path = return_path.resolve()
    if not return_path.is_file():
        return [f"Story return packet missing: {return_path}"], []
    root = project_root.resolve() if project_root else _infer_project_root(return_path)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        packet = load_return_packet(return_path)
    except ValueError as exc:
        return [str(exc)], []

    context: dict[str, Any] = {}
    if packet_path:
        if not packet_path.is_file():
            errors.append(f"Story context packet missing: {packet_path}")
        else:
            try:
                context = _read_json(packet_path.resolve())
            except ValueError as exc:
                errors.append(str(exc))

    if packet.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if packet.get("packet_type") not in ALLOWED_RETURN_PACKET_TYPES:
        errors.append(f"invalid packet_type: {packet.get('packet_type')}")
    stage = str(packet.get("stage") or "")
    if stage not in ALLOWED_RETURN_STAGES:
        errors.append(f"invalid stage: {stage or '-'}")
    status = str(packet.get("status") or "")
    if stage in ALLOWED_RETURN_STAGES and status not in _allowed_statuses(stage):
        errors.append(f"invalid status for {stage}: {status or '-'}")
    for key in ("story_id", "cr_id", "status", "touched_files", "boundary_check", "verification"):
        if key not in packet:
            errors.append(f"missing required field: {key}")

    if context:
        if packet.get("story_id") != context.get("story_id"):
            errors.append(f"story_id mismatch: return={packet.get('story_id')} context={context.get('story_id')}")
        if packet.get("stage") != context.get("stage"):
            errors.append(f"stage mismatch: return={packet.get('stage')} context={context.get('stage')}")
        expected = str(context.get("expected_return_packet") or "")
        if expected and _rel(root, return_path) != expected:
            warnings.append(f"return path differs from expected_return_packet: expected {expected}")

    touched_files = [_changed_file_path(entry) for entry in _as_list(packet.get("touched_files")) if _changed_file_path(entry)]
    if status not in NON_TERMINAL_STATUSES and stage == "CP6" and not touched_files:
        errors.append("CP6 implemented return must include touched_files")

    allowed_patterns = _string_list(context.get("allowed_write_paths")) if context else []
    forbidden_patterns = _string_list(context.get("forbidden_write_paths")) if context else []
    for rel_path in touched_files:
        if allowed_patterns and not _matches_any(rel_path, allowed_patterns):
            errors.append(f"touched file outside allowed_write_paths: {rel_path}")
        if forbidden_patterns and _matches_any(rel_path, forbidden_patterns):
            errors.append(f"touched file matches forbidden_write_paths: {rel_path}")

    boundary = packet.get("boundary_check") or {}
    if not isinstance(boundary, dict):
        errors.append("boundary_check must be an object")
        boundary = {}
    if boundary.get("allowed_paths_only") is False:
        errors.append("boundary_check.allowed_paths_only must not be false")
    for rel_path in _string_list(boundary.get("forbidden_paths_touched")):
        errors.append(f"boundary_check reports forbidden path touched: {rel_path}")
    for item in _string_list(boundary.get("unexpected_imports")):
        errors.append(f"boundary_check reports unexpected import: {item}")

    contract_changes = packet.get("contract_changes") or {}
    if contract_changes and not isinstance(contract_changes, dict):
        errors.append("contract_changes must be an object")
        contract_changes = {}
    if contract_changes.get("design_delta_required") is True:
        delta_ref = str(contract_changes.get("design_delta_ref") or "")
        if not delta_ref:
            errors.append("contract_changes.design_delta_ref is required when design_delta_required=true")
        elif not (root / delta_ref).is_file():
            warnings.append(f"design_delta_ref not found on disk: {delta_ref}")

    verification = packet.get("verification") or {}
    if not isinstance(verification, dict):
        errors.append("verification must be an object")
        verification = {}
    commands = _as_list(verification.get("commands_run"))
    evidence_refs = _string_list(packet.get("evidence_refs"))
    if status not in NON_TERMINAL_STATUSES and not commands and not evidence_refs:
        errors.append("successful return must include verification.commands_run or evidence_refs")
    for command in commands:
        if not isinstance(command, dict):
            errors.append("verification.commands_run entries must be objects")
            continue
        if not command.get("command") or not command.get("result"):
            errors.append("verification.commands_run entries require command and result")

    return errors, warnings


def build_evidence_index(
    project_root: Path,
    *,
    return_path: Path,
    output: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    root = project_root.resolve()
    return_path = return_path.resolve()
    packet = load_return_packet(return_path)
    story_id = str(packet.get("story_id") or "")
    stage = str(packet.get("stage") or "")
    if not story_id or not stage:
        raise ValueError("return packet must include story_id and stage")
    verification = packet.get("verification") or {}
    evidence = {
        "schema_version": 1,
        "story_id": story_id,
        "cr_id": packet.get("cr_id"),
        "stage": stage,
        "return_ref": _rel(root, return_path),
        "changed_files": _as_list(packet.get("touched_files")),
        "commands": _as_list(verification.get("commands_run")),
        "tests": _as_list(verification.get("tests")),
        "artifacts": _as_list(packet.get("artifacts")),
        "risks": _as_list(packet.get("risks")),
        "waivers": _as_list(packet.get("waivers")),
        "design_delta_ref": (packet.get("contract_changes") or {}).get("design_delta_ref"),
    }
    output_path = output.resolve() if output else default_evidence_path(root, story_id, stage)
    _write_json(output_path, evidence)
    return evidence, output_path


def validate_evidence_index(index_path: Path, *, project_root: Path | None = None) -> tuple[list[str], list[str]]:
    index_path = index_path.resolve()
    if not index_path.is_file():
        return [f"Evidence index missing: {index_path}"], []
    root = project_root.resolve() if project_root else _infer_project_root(index_path)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        evidence = _read_json(index_path)
    except ValueError as exc:
        return [str(exc)], []
    if evidence.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for key in ("story_id", "stage", "return_ref", "changed_files", "commands", "risks", "waivers"):
        if key not in evidence:
            errors.append(f"missing required field: {key}")
    return_ref = str(evidence.get("return_ref") or "")
    if return_ref and not (root / return_ref).is_file():
        errors.append(f"return_ref missing on disk: {return_ref}")
    stage = str(evidence.get("stage") or "")
    if stage not in ALLOWED_RETURN_STAGES:
        errors.append(f"invalid stage: {stage or '-'}")
    changed_files = evidence.get("changed_files")
    if changed_files is not None and not isinstance(changed_files, list):
        errors.append("changed_files must be a list")
    commands = evidence.get("commands")
    if commands is not None and not isinstance(commands, list):
        errors.append("commands must be a list")
    if not evidence.get("changed_files") and not evidence.get("commands"):
        warnings.append("evidence index has no changed_files and no commands")
    return errors, warnings


def validate_design_delta(
    delta_path: Path,
    *,
    project_root: Path | None = None,
    require_merged: bool = False,
) -> tuple[list[str], list[str]]:
    delta_path = delta_path.resolve()
    if not delta_path.is_file():
        return [f"Design delta missing: {delta_path}"], []
    root = project_root.resolve() if project_root else _infer_project_root(delta_path)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        delta = _read_json(delta_path)
    except ValueError as exc:
        return [str(exc)], []
    if delta.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for key in ("story_id", "feature_id", "delta_type", "status"):
        if key not in delta:
            errors.append(f"missing required field: {key}")
    delta_type = str(delta.get("delta_type") or "")
    if delta_type not in ALLOWED_DELTA_TYPES:
        errors.append(f"invalid delta_type: {delta_type or '-'}")
    status = str(delta.get("status") or "")
    if status not in ALLOWED_DELTA_STATUSES:
        errors.append(f"invalid status: {status or '-'}")
    target_doc = str(delta.get("target_doc") or "")
    if delta_type != "none":
        if not target_doc:
            errors.append("target_doc is required when delta_type is not none")
        elif not (root / target_doc).is_file():
            errors.append(f"target_doc missing on disk: {target_doc}")
        changes = delta.get("changes")
        if not isinstance(changes, list) or not changes:
            errors.append("changes must be a non-empty list when delta_type is not none")
        else:
            for item in changes:
                if not isinstance(item, dict):
                    errors.append("changes entries must be objects")
                    continue
                if not item.get("section") or not item.get("operation") or not item.get("summary"):
                    errors.append("changes entries require section, operation, and summary")
    if delta.get("requires_feature_doc_update") is True and status != "merged":
        message = "design delta requires feature doc update but is not merged"
        if require_merged:
            errors.append(message)
        else:
            warnings.append(message)
    if require_merged and status != "merged":
        errors.append("design delta status must be merged")
    if status == "merged" and not delta.get("merged_ref"):
        warnings.append("merged design delta should include merged_ref")
    return errors, warnings


def build_verify_packet_from_return(
    project_root: Path,
    *,
    return_path: Path,
    story_path: Path,
    output: Path | None = None,
    budget: int | None = None,
) -> tuple[dict[str, Any], Path]:
    root = project_root.resolve()
    return_path = return_path.resolve()
    packet = load_return_packet(return_path)
    story_id = str(packet.get("story_id") or "")
    stage = str(packet.get("stage") or "")
    if stage != "CP6":
        raise ValueError("verify packet can only be built from a CP6 return packet")
    if not story_id:
        raise ValueError("return packet must include story_id")
    return story_contract.build_story_packet(
        root,
        story_path=story_path,
        stage="CP7",
        cr_id=str(packet.get("cr_id") or ""),
        budget=budget,
        output=output,
        cp6_return_ref=_rel(root, return_path),
    )


def _print_story_help() -> None:
    print(
        "usage: meta-flow story <command> [options]\n\n"
        "Commands:\n"
        "  return-check    Validate a Story Return Packet against its Story Work/Verify Packet.\n"
        "  evidence-index  Build an Evidence Index from a Story Return Packet.\n"
        "  evidence-check  Validate an Evidence Index.\n"
        "  verify-packet   Build a CP7 Story Verify Packet from a CP6 Return Packet.\n\n"
        "Examples:\n"
        "  meta-flow story return-check --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .\n"
        "  meta-flow story evidence-index --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .\n"
        "  meta-flow story verify-packet --from-return process/returns/STORY-CR123-S01.CP6.return.json --story process/stories/STORY-CR123-S01.md --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_story_help()
        return 0
    command = args[0]
    if command == "return-check":
        parser = argparse.ArgumentParser(prog="meta-flow story return-check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--packet", dest="packet_path", type=Path, required=True)
        parser.add_argument("--return", dest="return_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_return_packet(
            parsed.return_path,
            packet_path=parsed.packet_path,
            project_root=parsed.project_root,
        )
        print("Story Return Packet Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "evidence-index":
        parser = argparse.ArgumentParser(prog="meta-flow story evidence-index")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--return", dest="return_path", type=Path, required=True)
        parser.add_argument("--output", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        _evidence, path = build_evidence_index(parsed.project_root, return_path=parsed.return_path, output=parsed.output)
        print(f"wrote: {path}")
        return 0
    if command == "evidence-check":
        parser = argparse.ArgumentParser(prog="meta-flow story evidence-check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--index", dest="index_path", type=Path, required=True)
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_evidence_index(parsed.index_path, project_root=parsed.project_root)
        print("Evidence Index Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "verify-packet":
        parser = argparse.ArgumentParser(prog="meta-flow story verify-packet")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--from-return", dest="return_path", type=Path, required=True)
        parser.add_argument("--story", dest="story_path", type=Path, required=True)
        parser.add_argument("--output", type=Path, default=None)
        parser.add_argument("--budget", type=int, default=None)
        parsed = parser.parse_args(args[1:])
        _packet, path = build_verify_packet_from_return(
            parsed.project_root,
            return_path=parsed.return_path,
            story_path=parsed.story_path,
            output=parsed.output,
            budget=parsed.budget,
        )
        print(f"wrote: {path}")
        return 0
    raise SystemExit(f"未知 story 命令: {command}")


def _print_design_help() -> None:
    print(
        "usage: meta-flow design <command> [options]\n\n"
        "Commands:\n"
        "  delta-check  Validate a Story design delta and optional CP8 merged status.\n\n"
        "Examples:\n"
        "  meta-flow design delta-check --delta process/design-deltas/STORY-CR123-S01.delta.json --project-root .\n"
        "  meta-flow design delta-check --delta process/design-deltas/STORY-CR123-S01.delta.json --require-merged --project-root .\n"
    )


def design_main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_design_help()
        return 0
    command = args[0]
    if command == "delta-check":
        parser = argparse.ArgumentParser(prog="meta-flow design delta-check")
        parser.add_argument("--project-root", type=Path, default=None)
        parser.add_argument("--delta", dest="delta_path", type=Path, required=True)
        parser.add_argument("--require-merged", action="store_true")
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_design_delta(
            parsed.delta_path,
            project_root=parsed.project_root,
            require_merged=parsed.require_merged,
        )
        print("Design Delta Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 design 命令: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
