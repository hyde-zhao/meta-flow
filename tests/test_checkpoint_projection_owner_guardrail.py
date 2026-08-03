from __future__ import annotations

import ast
from pathlib import Path

from meta_flow.state import checkpoint_projection

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "meta_flow/state/checkpoint_projection.py"
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
}
THIN_ADAPTER_PATHS = {"route_plan": THIN_ADAPTER}
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
