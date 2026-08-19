"""单一 ``meta-flow package`` 公共命令组的薄适配器。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from meta_flow.checks.process_cost import (
    build_process_cost_report,
    collect_process_cost_input,
    load_process_cost_policy,
)
from meta_flow.policies.semver_decision import (
    SemVerBootstrapDecisionV1,
    SemVerDecisionInputV1,
    build_cr072_bootstrap,
    decide_semver,
)
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import load_yaml_object
from meta_flow.workflow.closure_build import (
    ClosureRequestV1,
    build_affected_closure,
    graph_from_package_plan,
)
from meta_flow.workflow.package_compiler import compile_package_plan
from meta_flow.workflow.package_plan import PackagePlanInputV1, canonical_digest
from meta_flow.workflow.release_order import (
    AggregateReleaseStateV1,
    FileReleaseWriter,
    ReleaseEventV1,
    ReleaseSnapshotV1,
    ReleaseTransitionAuthorizationV1,
    apply_release_advance,
    check_release_transition,
    plan_release_advance,
    recover_release_transition,
)

PUBLIC_OPERATION_DECLARATIONS = (
    ("package.cost-report", ("meta-flow", "package", "cost-report")),
    ("package.compile", ("meta-flow", "package", "compile")),
    ("package.closure-build", ("meta-flow", "package", "closure-build")),
    ("package.semver-decide", ("meta-flow", "package", "semver-decide")),
    ("package.release-check", ("meta-flow", "package", "release-check")),
    ("package.release-advance", ("meta-flow", "package", "release-advance")),
)

_DEVELOPMENT_PLAN_REF = "process/DEVELOPMENT-PLAN.yaml"
_PUBLIC_OPERATION_REGISTRY_REF = "delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml"
_NON_PRODUCTION_PARTS = {
    "doc",
    "docs",
    "fixture",
    "fixtures",
    "helper",
    "helpers",
    "template",
    "templates",
    "test",
    "tests",
}


def _print_help() -> None:
    print(
        "usage: meta-flow package "
        "<cost-report|compile|closure-build|semver-decide|release-check|release-advance> "
        "[options]\n\n"
        "Commands:\n"
        "  cost-report  Derive a zero-write ProcessCostReportV1 from canonical records.\n\n"
        "  compile      Compile canonical package truth to an immutable PackagePlanIRV1.\n\n"
        "  closure-build Build a zero-write affected closure from literal commit OIDs.\n\n"
        "  semver-decide Truthfully classify a package version and validate one bootstrap.\n\n"
        "  release-check Zero-write check one aggregate release transition.\n\n"
        "  release-advance Plan or typed-apply one aggregate release transition.\n\n"
        "Example:\n"
        "  meta-flow package cost-report --cr CR-072 --project-root . --format json\n"
        "  meta-flow package compile --cr CR-072 --project-root . --format json\n"
        "  meta-flow package closure-build --cr CR-072 --base-sha <40hex> "
        "--head-sha <40hex> --changed-root meta_flow/package_cli.py "
        "--project-root . --format json\n"
        "  meta-flow package semver-decide --cr CR-072 --input <logical-ref> "
        "--requested-version 0.6.1 --bootstrap-ref "
        "docs/product/REQUIREMENTS.md#CP2-DQ-02-072 --project-root . --format json\n"
        "  meta-flow package release-check --cr CR-072 --state <logical-ref> "
        "--candidate-event <logical-ref> --project-root . --format json"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _regular_source(path: Path, *, code: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(code)
    return path.read_bytes()


def _resolve_input_ref(project_root: Path, value: str, *, code: str) -> Path:
    if not value or value.startswith("/") or "\\" in value or "://" in value:
        raise ValueError(code)
    if value.startswith("process/"):
        return _resolve_runtime_ref(project_root.resolve(), value)
    candidate = (project_root.resolve() / value).resolve(strict=False)
    if not candidate.is_relative_to(project_root.resolve()):
        raise ValueError(code)
    return candidate


def _load_json_ref(project_root: Path, value: str, *, code: str) -> object:
    path = _resolve_input_ref(project_root, value, code=code)
    raw = _regular_source(path, code=code)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(code) from exc


def _is_production_path(value: str) -> bool:
    if not value.endswith(".py") or value.startswith("/") or "\\" in value or "://" in value:
        return False
    return all(
        part not in {"", ".", ".."} and part.lower() not in _NON_PRODUCTION_PARTS
        for part in value.split("/")
    )


def _module_for_path(value: str) -> str:
    return value[:-3].replace("/", ".") if value.endswith(".py") else ""


def collect_package_plan_input(project_root: Path, cr_id: str) -> PackagePlanInputV1:
    """从一份计划聚合与一份公共 operation registry 构造 closed input。"""

    root = project_root.resolve()
    plan_path = _resolve_runtime_ref(root, _DEVELOPMENT_PLAN_REF)
    plan_raw = _regular_source(plan_path, code="PACKAGE_PLAN_SOURCE_INVALID")
    plan = load_yaml_object(plan_path)
    registry_path = root / _PUBLIC_OPERATION_REGISTRY_REF
    registry_raw = _regular_source(registry_path, code="PACKAGE_OPERATION_REGISTRY_INVALID")
    registry = json.loads(registry_raw)
    if not isinstance(registry, dict) or not isinstance(registry.get("operations"), list):
        raise ValueError("PACKAGE_OPERATION_REGISTRY_INVALID")

    change_sets = plan.get("change_sets")
    if not isinstance(change_sets, list):
        raise ValueError("PACKAGE_CHANGE_SET_MISSING")
    matches = [
        item for item in change_sets if isinstance(item, dict) and item.get("cr_id") == cr_id
    ]
    if len(matches) != 1:
        raise ValueError("PACKAGE_CHANGE_SET_IDENTITY_INVALID")
    change_set = matches[0]
    release_version = str(change_set.get("release_version") or "")
    work_ids = sorted(set(str(item) for item in change_set.get("work_ids") or []))
    story_ids = sorted(set(str(item) for item in change_set.get("story_ids") or []))
    story_records = [
        story
        for wave in plan.get("waves") or []
        if isinstance(wave, dict)
        for story in wave.get("stories") or []
        if isinstance(story, dict) and story.get("story_id") in story_ids
    ]
    if {str(item.get("story_id")) for item in story_records} != set(story_ids):
        raise ValueError("PACKAGE_STORY_PLAN_INCOMPLETE")

    registry_operations: list[dict[str, Any]] = []
    registry_by_id: dict[str, dict[str, Any]] = {}
    for item in registry["operations"]:
        if not isinstance(item, dict):
            raise ValueError("PACKAGE_OPERATION_REGISTRY_INVALID")
        operation_id = item.get("operation")
        entry = item.get("entry")
        mutation_mode = item.get("mutation_mode")
        if not isinstance(operation_id, str) or not isinstance(entry, list):
            raise ValueError("PACKAGE_OPERATION_REGISTRY_INVALID")
        normalized = {
            "operation_id": operation_id,
            "entry": entry,
            "mutation_mode": mutation_mode,
        }
        registry_operations.append(normalized)
        registry_by_id[operation_id] = item

    story_modules: dict[str, set[str]] = {}
    for story in story_records:
        ownership = story.get("file_ownership")
        ownership = ownership if isinstance(ownership, dict) else {}
        paths = [
            str(path)
            for field in ("primary", "shared")
            for path in ownership.get(field) or []
            if isinstance(path, str)
        ]
        story_modules[str(story.get("story_id"))] = {
            module for module in (_module_for_path(path) for path in paths) if module
        }

    operations_by_story: dict[str, list[str]] = {story_id: [] for story_id in story_ids}
    required_operation_ids: set[str] = set()
    for operation_id, item in registry_by_id.items():
        projector = item.get("projector")
        if not isinstance(projector, str) or "." not in projector:
            continue
        matching_story_ids = [
            story_id
            for story_id, modules in story_modules.items()
            if any(projector == module or projector.startswith(module + ".") for module in modules)
        ]
        if matching_story_ids:
            required_operation_ids.add(operation_id)
            for story_id in matching_story_ids:
                operations_by_story[story_id].append(operation_id)

    stories: list[dict[str, Any]] = []
    for story in story_records:
        story_id = str(story.get("story_id") or "")
        ownership = story.get("file_ownership")
        ownership = ownership if isinstance(ownership, dict) else {}
        primary = sorted(
            set(str(path) for path in ownership.get("primary") or [] if isinstance(path, str))
        )
        shared = sorted(
            set(str(path) for path in ownership.get("shared") or [] if isinstance(path, str))
        )
        core_paths = sorted(path for path in primary if _is_production_path(path))
        entry_candidates = sorted(
            path
            for path in (*primary, *shared)
            if _is_production_path(path)
            and (
                path.startswith("scripts/")
                or path.endswith("/cli.py")
                or path in {"meta_flow/cli.py", "meta_flow/package_cli.py"}
            )
        )
        entrypoints = entry_candidates or core_paths[:1]
        dependency_types = {
            str(item.get("upstream")): str(item.get("type") or "contract")
            for item in story.get("dependency_type") or []
            if isinstance(item, dict) and item.get("upstream")
        }
        dependencies = [
            {
                "upstream": str(upstream),
                "edge_type": dependency_types.get(str(upstream), "contract"),
            }
            for upstream in story.get("depends_on") or []
        ]
        feature_refs = sorted(
            {
                Path(ref).parent.name
                for ref in story.get("feature_design_refs") or []
                if isinstance(ref, str) and ref.startswith("process/")
            }
        )
        priority = str(story.get("priority") or "")
        stories.append(
            {
                "story_id": story_id,
                "work_id": str(story.get("work_id") or ""),
                "priority": priority,
                "requirement_priority": priority,
                "wave": str(story.get("wave") or ""),
                "dependencies": dependencies,
                "primary_paths": primary,
                "shared_paths": shared,
                "merge_owner": str(ownership.get("merge_owner") or ""),
                "feature_refs": feature_refs,
                "production_entrypoints": entrypoints,
                "reachable_core_paths": core_paths,
                "public_operation_ids": sorted(set(operations_by_story.get(story_id, []))),
            }
        )

    required_operations = [
        {
            "operation_id": operation_id,
            "entry": registry_by_id[operation_id]["entry"],
            "mutation_mode": registry_by_id[operation_id]["mutation_mode"],
        }
        for operation_id in sorted(required_operation_ids)
    ]
    asset_set = change_set.get("asset_set")
    if not isinstance(asset_set, list):
        raise ValueError("PACKAGE_ASSET_SET_MISSING")
    mapping = {
        "schema_version": 1,
        "package_id": f"{release_version}-release-package",
        "target_version": release_version,
        "cr_id": cr_id,
        "works": [
            {"work_id": work_id, "release_value": release_version} for work_id in work_ids
        ],
        "stories": stories,
        "required_public_operations": required_operations,
        "operation_registry": registry_operations,
        "asset_set": asset_set,
        "semver_bootstrap_ref": str(change_set.get("semver_bootstrap_ref") or ""),
        "source_objects": [
            {
                "ref": _DEVELOPMENT_PLAN_REF,
                "bytes_digest": _sha256(plan_raw),
                "semantic_digest": canonical_digest(plan),
            },
            {
                "ref": _PUBLIC_OPERATION_REGISTRY_REF,
                "bytes_digest": _sha256(registry_raw),
                "semantic_digest": canonical_digest(registry),
            },
        ],
    }
    return PackagePlanInputV1.from_mapping(mapping)


def _compile(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow package compile")
    parser.add_argument("--cr", required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parsed = parser.parse_args(args)
    try:
        value = collect_package_plan_input(parsed.project_root, parsed.cr)
        result = compile_package_plan(value)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        failure = {
            "schema_version": 1,
            "kind": "PackagePlanCompileFailureV1",
            "decision": "BLOCKED",
            "error_code": "CHECK_HARNESS_ERROR",
            "detail_code": str(exc).split(":", 1)[0],
            "message": "package plan source collection failed",
            "mutation_count": 0,
        }
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True))
        return 1
    output = result.as_dict()
    if parsed.format == "json":
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{output['decision']} package={output['package_id']} "
            f"stories={len(output['stories'])} digest={output['semantic_digest']}"
        )
        for diagnostic in output["diagnostics"]:
            print(
                f"- {diagnostic['code']} {diagnostic['subject_kind']}:"
                f"{diagnostic['subject_id']}"
            )
    return 0 if result.decision == "PASS" else 1


def _closure_build(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow package closure-build")
    parser.add_argument("--cr", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--changed-root", action="append", required=True)
    parser.add_argument("--prior-fingerprint", default="")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parsed = parser.parse_args(args)
    try:
        plan = compile_package_plan(collect_package_plan_input(parsed.project_root, parsed.cr))
        nodes, edges = graph_from_package_plan(plan)
        request = ClosureRequestV1.from_mapping(
            {
                "schema_version": 1,
                "package_plan_digest": plan.semantic_digest,
                "base_sha": parsed.base_sha,
                "head_sha": parsed.head_sha,
                "changed_roots": parsed.changed_root,
                "graph_nodes": [item.as_dict() for item in nodes],
                "graph_edges": [item.as_dict() for item in edges],
                "prior_fingerprint": parsed.prior_fingerprint,
            }
        )
        result = build_affected_closure(request, plan)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        failure = {
            "schema_version": 1,
            "kind": "ClosureBuildFailureV1",
            "decision": "BLOCKED",
            "error_code": "CHECK_HARNESS_ERROR",
            "detail_code": str(exc).split(":", 1)[0],
            "message": "closure source collection failed",
            "mutation_count": 0,
        }
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True))
        return 1
    output = result.as_dict()
    if parsed.format == "json":
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{result.decision} direct={len(result.direct_nodes)} "
            f"transitive={len(result.transitive_nodes)} "
            f"noop={str(result.semantic_noop).lower()} digest={result.semantic_digest}"
        )
        for diagnostic in output["diagnostics"]:
            print(f"- {diagnostic['code']} {diagnostic['subject']}")
    return 0 if result.decision == "PASS" else 1


def _cost_report(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow package cost-report")
    parser.add_argument("--cr", required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=("json",), default="json")
    parsed = parser.parse_args(args)
    try:
        value = collect_process_cost_input(parsed.project_root, parsed.cr)
        policy = load_process_cost_policy(parsed.project_root)
        report = build_process_cost_report(value, policy)
    except (OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "ProcessCostReportFailureV1",
                    "decision": "BLOCKED",
                    "error_code": "CHECK_HARNESS_ERROR",
                    "detail_code": str(exc).split(":", 1)[0],
                    "message": "process cost source collection failed",
                    "mutation_count": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 1 if report["decision"] == "BLOCKED" else 0


def _semver_decide(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow package semver-decide")
    parser.add_argument("--cr", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--requested-version", required=True)
    parser.add_argument("--bootstrap-ref", default="")
    parser.add_argument("--consumed-bootstrap-key", action="append", default=[])
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parsed = parser.parse_args(args)
    try:
        value = SemVerDecisionInputV1.from_mapping(
            _load_json_ref(
                parsed.project_root,
                parsed.input,
                code="SEMVER_INPUT_REF_INVALID",
            )
        )
        if value.cr_id != parsed.cr or value.requested_version != parsed.requested_version:
            raise ValueError("SEMVER_CLI_BINDING_MISMATCH")
        bootstrap: SemVerBootstrapDecisionV1 | None = None
        if parsed.bootstrap_ref:
            if parsed.bootstrap_ref == "docs/product/REQUIREMENTS.md#CP2-DQ-02-072":
                bootstrap = build_cr072_bootstrap(value)
            else:
                bootstrap = SemVerBootstrapDecisionV1.from_mapping(
                    _load_json_ref(
                        parsed.project_root,
                        parsed.bootstrap_ref,
                        code="SEMVER_BOOTSTRAP_REF_INVALID",
                    )
                )
        result = decide_semver(
            value,
            bootstrap,
            consumed_bootstrap_keys=parsed.consumed_bootstrap_key,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        failure = {
            "schema_version": 1,
            "kind": "SemVerDecisionFailureV1",
            "decision": "BLOCKED",
            "error_code": "CHECK_HARNESS_ERROR",
            "detail_code": str(exc).split(":", 1)[0],
            "mutation_count": 0,
        }
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True))
        return 1
    output = result.as_dict()
    if parsed.format == "json":
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{result.decision} normal={result.normal_machine_recommendation} "
            f"selected={result.selected_version or '-'} "
            f"bootstrap={str(result.bootstrap_used).lower()}"
        )
        for diagnostic in result.diagnostics:
            print(f"- {diagnostic.code}")
    return 0 if result.decision == "PASS" else 1


def _release_check(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow package release-check")
    parser.add_argument("--cr", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--candidate-event", required=True)
    parser.add_argument("--evidence", default="")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parsed = parser.parse_args(args)
    try:
        state = AggregateReleaseStateV1.from_mapping(
            _load_json_ref(parsed.project_root, parsed.state, code="RELEASE_STATE_REF_INVALID")
        )
        event = ReleaseEventV1.from_mapping(
            _load_json_ref(
                parsed.project_root,
                parsed.candidate_event,
                code="RELEASE_EVENT_REF_INVALID",
            )
        )
        if state.cr_id != parsed.cr or event.cr_id != parsed.cr:
            raise ValueError("RELEASE_CLI_CR_MISMATCH")
        if parsed.evidence and event.evidence_ref != parsed.evidence:
            raise ValueError("RELEASE_CLI_EVIDENCE_MISMATCH")
        result = check_release_transition(state, event)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        failure = {
            "schema_version": 1,
            "kind": "ReleaseCheckFailureV1",
            "decision": "BLOCKED",
            "error_code": "CHECK_HARNESS_ERROR",
            "detail_code": str(exc).split(":", 1)[0],
            "mutation_count": 0,
        }
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True))
        return 1
    output = result.as_dict()
    if parsed.format == "json":
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{result.decision} event={event.event_id} action={event.action} mutation=0")
        for diagnostic in result.diagnostics:
            print(f"- {diagnostic.code}")
    return 0 if result.decision in {"PASS", "NO_CHANGE"} else 1


def _release_writer_paths(project_root: Path, ledger_ref: str, projection_ref: str) -> tuple[Path, Path]:
    for value in (ledger_ref, projection_ref):
        if not value.startswith("process/release/"):
            raise ValueError("RELEASE_WRITER_REF_OUT_OF_SCOPE")
    return (
        _resolve_runtime_ref(project_root.resolve(), ledger_ref),
        _resolve_runtime_ref(project_root.resolve(), projection_ref),
    )


def _release_advance(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="meta-flow package release-advance")
    parser.add_argument("--cr", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--candidate-event", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--fresh-snapshot", default="")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--authorization", default="")
    parser.add_argument("--expected-plan-digest", default="")
    parser.add_argument("--ledger-ref", default="")
    parser.add_argument("--projection-ref", default="")
    parsed = parser.parse_args(args)
    try:
        state = AggregateReleaseStateV1.from_mapping(
            _load_json_ref(parsed.project_root, parsed.state, code="RELEASE_STATE_REF_INVALID")
        )
        event = ReleaseEventV1.from_mapping(
            _load_json_ref(
                parsed.project_root,
                parsed.candidate_event,
                code="RELEASE_EVENT_REF_INVALID",
            )
        )
        snapshot = ReleaseSnapshotV1.from_mapping(
            _load_json_ref(
                parsed.project_root,
                parsed.snapshot,
                code="RELEASE_SNAPSHOT_REF_INVALID",
            )
        )
        if state.cr_id != parsed.cr or event.cr_id != parsed.cr:
            raise ValueError("RELEASE_CLI_CR_MISMATCH")
        plan = plan_release_advance(state, event, snapshot)
        if not parsed.apply and not parsed.recover:
            output = plan.as_dict()
        else:
            if not (
                parsed.authorization
                and parsed.expected_plan_digest
                and parsed.fresh_snapshot
                and parsed.ledger_ref
                and parsed.projection_ref
            ):
                raise ValueError("RELEASE_APPLY_INPUT_REQUIRED")
            if parsed.expected_plan_digest != plan.plan_digest:
                raise ValueError("RELEASE_EXPECTED_PLAN_DIGEST_MISMATCH")
            authorization = ReleaseTransitionAuthorizationV1.from_mapping(
                _load_json_ref(
                    parsed.project_root,
                    parsed.authorization,
                    code="RELEASE_AUTHORIZATION_REF_INVALID",
                )
            )
            fresh_snapshot = ReleaseSnapshotV1.from_mapping(
                _load_json_ref(
                    parsed.project_root,
                    parsed.fresh_snapshot,
                    code="RELEASE_FRESH_SNAPSHOT_REF_INVALID",
                )
            )
            ledger_path, projection_path = _release_writer_paths(
                parsed.project_root,
                parsed.ledger_ref,
                parsed.projection_ref,
            )
            writer = FileReleaseWriter(ledger_path, projection_path)
            if parsed.recover:
                receipt = recover_release_transition(
                    plan, authorization, fresh_snapshot, writer
                )
            else:
                receipt = apply_release_advance(
                    plan, authorization, fresh_snapshot, writer
                )
            output = receipt.as_dict()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        output = {
            "schema_version": 1,
            "kind": "ReleaseAdvanceFailureV1",
            "decision": "BLOCKED",
            "error_code": "CHECK_HARNESS_ERROR",
            "detail_code": str(exc).split(":", 1)[0],
            "mutation_count": 0,
        }
    if parsed.format == "json":
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{output['decision']} action={event.action if 'event' in locals() else '-'} "
            f"mutation={output.get('mutation_count', 0)}"
        )
        for diagnostic in output.get("diagnostics", []):
            print(f"- {diagnostic['code']}")
    return 0 if output["decision"] in {"PASS", "NO_CHANGE"} else 1


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return 0
    command = args[0]
    if command == "cost-report":
        return _cost_report(args[1:])
    if command == "compile":
        return _compile(args[1:])
    if command == "closure-build":
        return _closure_build(args[1:])
    if command == "semver-decide":
        return _semver_decide(args[1:])
    if command == "release-check":
        return _release_check(args[1:])
    if command == "release-advance":
        return _release_advance(args[1:])
    raise SystemExit(
        "未知 package 命令: "
        f"{command}. 目前支持: cost-report, compile, closure-build, "
        "semver-decide, release-check, release-advance"
    )


if __name__ == "__main__":
    raise SystemExit(main())
