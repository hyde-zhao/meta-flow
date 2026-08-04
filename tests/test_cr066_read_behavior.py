from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from meta_flow.context_pack.read_expansion import (
    V2_READ_EXPANSION_REASONS,
    build_event,
    validate_reason_evidence,
)
from meta_flow.policies import public_operations
from meta_flow.project.model import Project, write_project_create_only
from meta_flow.project.read_contract import ReadContextProtocol, ReadContractError
from meta_flow.work.io_metrics import IOMetrics
from meta_flow.work.model import build_work
from meta_flow.work.read_context import OperationReadContext
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.route_profile import (
    ROUTINE_STAGES,
    evaluate_route_profile,
    route_profile_from_payload,
)
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import apply_work_init, plan_work_init

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALID_REASON_EVIDENCE = {
    "capsule_missing": {"capsule_ref": "context/CAPSULE.json"},
    "field_conflict": {
        "conflict_field": "status",
        "sources": [
            {"ref": "context/CAPSULE.json", "digest": "a" * 64},
            {"ref": "STATE.md", "digest": "b" * 64},
        ],
    },
    "schema_validation_failed": {
        "schema_id": "ContextCapsuleV1",
        "error_code": "MISSING_REQUIRED_FIELD",
        "target_ref": "context/CAPSULE.json",
    },
    "human_audit": {"authorization_ref": "checkpoints/C66-G2.md"},
    "summary_insufficient": {"missing_slots": ["rollback", "owner"]},
}


def _write_read_objects(root: Path, count: int = 6) -> None:
    for index in range(1, count + 1):
        path = root / "objects" / f"{index}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"index": index}) + "\n", encoding="utf-8")


def test_capsule_sufficient_task_never_reads_full_document(tmp_path: Path) -> None:
    capsule = tmp_path / "context" / "CAPSULE.json"
    full = tmp_path / "STATE.md"
    capsule.parent.mkdir(parents=True)
    capsule.write_text('{"status":"ready","next":"targeted"}\n', encoding="utf-8")
    full.write_text("# Full state\nsecretly much larger\n", encoding="utf-8")
    metrics = IOMetrics("cr066-capsule-sufficient", enabled=True)
    context = OperationReadContext(
        tmp_path,
        operation_id="cr066-capsule-sufficient",
        operation_kind="query",
        allowed_reads=("context/CAPSULE.json", "STATE.md"),
        metrics=metrics,
    )

    result = context.read_json("context/CAPSULE.json")
    summary = metrics.summary()

    assert result == {"status": "ready", "next": "targeted"}
    assert context.refs == ("context/CAPSULE.json",)
    assert summary["totals"]["physical_reads"] == 1
    assert all(entry["logical_ref"] != "STATE.md" for entry in summary["entries"])
    assert sum(
        entry["physical_reads"]
        for entry in summary["entries"]
        if entry["logical_ref"] == "STATE.md"
    ) == 0


@pytest.mark.parametrize("reason", sorted(V2_READ_EXPANSION_REASONS))
def test_every_legal_full_read_reason_has_complete_machine_evidence(reason: str) -> None:
    evidence = VALID_REASON_EVIDENCE[reason]

    assert validate_reason_evidence(reason, evidence) == []


@pytest.mark.parametrize(
    ("reason", "evidence"),
    [
        ("", None),
        ("deep_review", {"authorization_ref": "checkpoints/legacy.md"}),
        ("human_audit", None),
        ("capsule_missing", {}),
        ("summary_insufficient", {"missing_slots": []}),
    ],
)
def test_invalid_full_read_is_blocked_before_target_open_and_ledger_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    evidence: dict[str, object] | None,
) -> None:
    target = tmp_path / "STATE.md"
    target.write_text("do not read\n", encoding="utf-8")
    ledger = tmp_path / "READ-EXPANSION-LEDGER.ndjson"
    physical_reads: list[Path] = []
    original = Path.read_bytes

    def tracked(path: Path) -> bytes:
        physical_reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)

    with pytest.raises(ValueError, match="target bytes=0"):
        build_event(
            tmp_path,
            requested_path="STATE.md",
            reason=reason,
            reason_evidence=evidence,
            stage="verification",
            agent="main-agent",
            context_ref="context/CAPSULE.json",
        )

    assert physical_reads == []
    assert not ledger.exists()


def test_legal_expansion_precheck_then_controlled_full_read_is_measured(
    tmp_path: Path,
) -> None:
    target = tmp_path / "STATE.md"
    target.write_text("# Full state\n", encoding="utf-8")
    evidence = VALID_REASON_EVIDENCE["human_audit"]
    metrics = IOMetrics("cr066-legal-expansion", enabled=True)

    assert validate_reason_evidence("human_audit", evidence) == []
    context = OperationReadContext(
        tmp_path,
        operation_id="cr066-legal-expansion",
        operation_kind="query",
        allowed_reads=("STATE.md",),
        metrics=metrics,
    )
    assert context.read_text("STATE.md") == "# Full state\n"

    summary = metrics.summary()
    assert summary["totals"]["physical_reads"] == 1
    assert summary["totals"]["bytes"] == len(target.read_bytes())


def test_sixth_object_has_stable_error_and_zero_physical_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_read_objects(tmp_path)
    physical_reads: list[str] = []
    original = Path.read_bytes

    def tracked(path: Path) -> bytes:
        physical_reads.append(path.name)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    metrics = IOMetrics("cr066-sixth-object", enabled=True)
    context = OperationReadContext(
        tmp_path,
        operation_id="cr066-sixth-object",
        operation_kind="query",
        allowed_reads=("objects/**",),
        max_objects=5,
        metrics=metrics,
    )
    for index in range(1, 6):
        context.read_json(f"objects/{index}.json")

    with pytest.raises(ReadContractError) as captured:
        context.read_json("objects/6.json")

    assert captured.value.error_code == "QUERY_OBJECT_BUDGET_EXCEEDED"
    assert captured.value.logical_ref == "objects/6.json"
    assert physical_reads == [f"{index}.json" for index in range(1, 6)]
    assert context.objects_read == 5
    assert metrics.summary()["totals"]["physical_reads"] == 5
    assert all(
        entry["logical_ref"] != "objects/6.json"
        for entry in metrics.summary()["entries"]
    )


def test_governance_loader_uses_injected_protocol_and_one_physical_resolution() -> None:
    metrics = IOMetrics("cr066-public-loader", enabled=True)
    context: ReadContextProtocol = OperationReadContext(
        PROJECT_ROOT,
        operation_id="cr066-public-loader",
        operation_kind="check",
        allowed_reads=(public_operations.DEFAULT_REGISTRY_REL.as_posix(),),
        logical_root="release-repository",
        metrics=metrics,
    )

    first = public_operations.load_public_operation_registry(
        PROJECT_ROOT,
        read_context=context,
    )
    second = public_operations.load_public_operation_registry(
        PROJECT_ROOT,
        read_context=context,
    )
    registry = public_operations.validate_public_operations(
        PROJECT_ROOT,
        check_console=False,
        read_context=context,
    )

    assert first == second
    assert registry["decision"] == "PASS", registry["errors"]
    assert registry["undocumented_public_operations"] == []
    assert metrics.summary()["totals"]["physical_reads"] == 1
    assert metrics.summary()["totals"]["cache_hits"] >= 2


def test_read_control_plane_has_no_hidden_global_context() -> None:
    modules = (
        PROJECT_ROOT / "meta_flow" / "work" / "read_context.py",
        PROJECT_ROOT / "meta_flow" / "project" / "query.py",
        PROJECT_ROOT / "meta_flow" / "context_pack" / "read_expansion.py",
    )
    forbidden_imports = {"contextvars"}
    forbidden_calls = {"ContextVar", "local"}

    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (
                node.names
                if isinstance(node, ast.Import)
                else [ast.alias(name=node.module or "")]
            )
        }
        module_level_contexts = [
            node
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(child, ast.Call)
                and (
                    getattr(child.func, "id", "") == "OperationReadContext"
                    or getattr(child.func, "attr", "") in forbidden_calls
                )
                for child in ast.walk(node)
            )
        ]
        assert not (imported & forbidden_imports), path
        assert module_level_contexts == [], path


@pytest.mark.parametrize("risk_profile", ["G0", "G1"])
def test_routine_work_is_direct_and_creates_no_legacy_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    risk_profile: str,
) -> None:
    monkeypatch.setenv("legacy_cp_compatibility", "true")
    monkeypatch.setenv("META_FLOW_LEGACY_CP_COMPATIBILITY", "true")
    profile = route_profile_from_payload(None)
    decision = evaluate_route_profile(
        profile,
        risk_profile=risk_profile,
        work_kind="work",
    )
    write_project_create_only(
        tmp_path,
        Project(1, "fixture", "Fixture", "active"),
    )
    request_ref = f"works/{risk_profile}-W/REQUEST.md"
    request = tmp_path / request_ref
    request.parent.mkdir(parents=True)
    request.write_text("confirmed routine request\n", encoding="utf-8")
    facts = (
        RiskFacts(change_kind="documentation", touched_path_count=1)
        if risk_profile == "G0"
        else RiskFacts(change_kind="code", touched_path_count=2)
    )
    classification = classify_work(facts)
    assert classification.risk_profile == risk_profile
    work = build_work(
        work_id=f"{risk_profile}-W",
        project_id="fixture",
        objective="routine external task",
        request_ref=request_ref,
        scope=WorkScope(
            1,
            (request_ref, "README.md"),
            ("README.md",),
            ("targeted",),
        ),
        classification=classification,
        release_base_oid="a" * 40,
        process_base_oid="b" * 40,
    )
    plan = plan_work_init(tmp_path, work)
    receipt = apply_work_init(plan)
    created = [
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    ]

    assert decision.decision == "READY"
    assert decision.stages == ROUTINE_STAGES
    assert decision.functional_agent_dispatches == 0
    assert decision.legacy_cp_artifacts_allowed is False
    assert profile.legacy_cp_compatibility is False
    assert profile.dispatch_mode == "direct"
    assert receipt.decision == "PASS"
    assert plan.route_decision.functional_agent_dispatches == 0
    assert plan.route_decision.legacy_cp_artifacts_allowed is False
    assert not any(Path(ref).name.startswith("CP") for ref in created)
    assert not any("checkpoint" in ref.lower() for ref in created)
    assert not any("status-sync" in ref.lower() for ref in created)
