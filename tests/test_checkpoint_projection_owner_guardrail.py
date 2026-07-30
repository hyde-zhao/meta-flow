from __future__ import annotations

import ast
from pathlib import Path

from meta_flow.policies import c0_cutover, route_plan
from meta_flow.state import checkpoint_projection

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "meta_flow/state/checkpoint_projection.py"
WRITE_OWNER = ROOT / "meta_flow/policies/c0_cutover.py"
THIN_ADAPTER = ROOT / "meta_flow/policies/route_plan.py"
CONSUMER_PATHS = {
    "cp_result": ROOT / "meta_flow/checks/cp_result.py",
    "cr_tracking": ROOT / "meta_flow/checks/cr_tracking.py",
    "cr_lifecycle/status-sync": ROOT / "meta_flow/workflow/cr_lifecycle.py",
    "state_transition": ROOT / "meta_flow/checks/state_transition.py",
    "publisher": ROOT / "meta_flow/repository/publisher.py",
}
WRITE_PRODUCER_PATHS = {
    "cp_result": ROOT / "meta_flow/checks/cp_result.py",
    "c0_cutover": WRITE_OWNER,
}
THIN_ADAPTER_PATHS = {"route_plan": THIN_ADAPTER}
REMOVED_C0_V1_FUNCTIONS = {
    "validate_c0_authorization",
    "_git_common_dir",
    "_c0_private_root",
    "_c0_process_lock_path",
    "_claim_c0_authorization",
    "_atomic_write_text",
    "_optional_text",
    "_append_ndjson",
    "_c0_result_ref",
    "_c0_summary_ref",
    "_load_valid_c0_ledger_events",
    "_c0_cutover_events",
    "_c0_revision_event_id",
    "_build_c0_apply_targets",
    "_c0_current_digest",
    "_c0_already_applied",
}


def test_consumer_registry_is_exact_and_every_consumer_imports_owner() -> None:
    assert checkpoint_projection.REGISTERED_CONSUMERS == tuple(CONSUMER_PATHS)
    for consumer, path in CONSUMER_PATHS.items():
        source = path.read_text(encoding="utf-8")
        assert "checkpoint_projection" in source, consumer


def test_write_producer_and_thin_adapter_registries_are_exact() -> None:
    assert checkpoint_projection.REGISTERED_WRITE_PRODUCERS == tuple(
        WRITE_PRODUCER_PATHS
    )
    assert checkpoint_projection.REGISTERED_THIN_ADAPTERS == tuple(
        THIN_ADAPTER_PATHS
    )
    assert c0_cutover.C0_WRITE_OWNER == (
        "meta_flow.policies.c0_cutover:C0CutoverPlanV2"
    )


def test_successor_and_alias_event_semantics_exist_only_in_canonical_owner() -> None:
    forbidden_literals = {
        "checkpoint_result_superseded",
        "checkpoint_result_alias_correction",
    }
    violations: list[str] = []
    for path in sorted((ROOT / "meta_flow").rglob("*.py")):
        if path == OWNER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in forbidden_literals:
                violations.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}:{node.value}")
    assert violations == []


def _function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(matches) == 1, name
    return matches[0]


def _first_executable_statement(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ast.stmt:
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    assert body, function.name
    return body[0]


def test_route_plan_legacy_c0_v1_python_boundary_is_disabled_and_helpers_are_removed() -> None:
    tree = ast.parse(
        THIN_ADAPTER.read_text(encoding="utf-8"),
        filename=THIN_ADAPTER.as_posix(),
    )
    apply_boundary = _function(tree, "apply_c0_cutover")
    first = _first_executable_statement(apply_boundary)
    assert isinstance(first, ast.Return)
    assert isinstance(first.value, ast.Call)
    assert isinstance(first.value.func, ast.Name)
    assert first.value.func.id == "_c0_v1_disabled_result"

    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert function_names.isdisjoint(REMOVED_C0_V1_FUNCTIONS)

    result = route_plan.apply_c0_cutover(
        project_root=ROOT,
        cr_id="CR-063",
        work_id="GOV-006-PROJECTION-001",
        story_result_refs=[],
        expected_plan_digest="",
        authorization=None,
    )
    assert result == {
        "status": "BLOCKED",
        "decision": "BLOCKED",
        "reason": "C0_V1_MUTATION_DISABLED",
        "replacement_operation": "route-c0-cutover-apply",
        "mutation_count": 0,
    }


def test_write_side_successor_semantics_are_owned_and_adapters_remain_thin() -> None:
    allowed_paths = {OWNER, *WRITE_PRODUCER_PATHS.values()}
    closure_paths = {
        *CONSUMER_PATHS.values(),
        *WRITE_PRODUCER_PATHS.values(),
        *THIN_ADAPTER_PATHS.values(),
    }
    forbidden_literals = {
        "checkpoint_result_superseded",
        "checkpoint_result_alias_correction",
        "supersedes_event_id",
        "supersedes_plan_digest",
        "cutover_revision",
    }
    violations: list[str] = []
    for path in sorted(closure_paths):
        if path in allowed_paths:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in forbidden_literals:
                violations.append(
                    f"{path.relative_to(ROOT).as_posix()}:{node.lineno}:{node.value}"
                )
    assert violations == []


def test_no_consumer_reintroduces_private_current_head_projector() -> None:
    forbidden_names = {
        "project_active_checkpoint_events",
        "project_checkpoint_successor_heads",
        "_checkpoint_result_heads",
        "_resolve_checkpoint_alias",
        "_select_checkpoint_current_head",
    }
    violations: list[str] = []
    for consumer, path in CONSUMER_PATHS.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in forbidden_names:
                    violations.append(f"{consumer}:{node.lineno}:{node.name}")
    assert violations == []
