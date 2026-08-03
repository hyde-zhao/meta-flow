import ast
from pathlib import Path

from meta_flow.policies import c0_cutover


def test_retired_plan_preserves_type_and_is_deterministically_blocked() -> None:
    plan = c0_cutover.build_c0_cutover_plan(
        project_root=Path("/must-not-be-read"),
        cr_id="CR-064",
        work_id="WORK-064",
        semantic_plan=object(),
    )
    payload = plan.as_dict()
    assert payload["kind"] == "C0CutoverPlanV2"
    assert payload["decision"] == "BLOCKED"
    assert payload["blockers"] == ["C0_V2_RETIRED"]
    assert payload["actual_mutation_count"] == 0
    assert payload["planned_mutation_count"] == 0
    assert payload["targets"] == []
    assert payload["mutation_allowlist"] == []
    assert payload["rollback_order"] == []
    assert payload["cr_id"] == "CR-064"
    assert payload["work_id"] == "WORK-064"
    assert plan.retired_diagnostic_ref == c0_cutover.RETIRED_GATE_LEDGER_REF


def test_retired_apply_does_not_call_factory_or_create_receipt() -> None:
    def forbidden_factory() -> object:
        raise AssertionError("retired apply must not build a semantic plan")

    receipt = c0_cutover.apply_c0_cutover(
        project_root=Path("/must-not-be-read"),
        work_id="WORK-064",
        expected_plan_digest="provided-digest",
        semantic_plan_factory=forbidden_factory,
    )
    assert receipt["status"] == "BLOCKED"
    assert receipt["reason"] == "C0_V2_RETIRED"
    assert receipt["plan_digest"] == "provided-digest"
    assert receipt["mutation_count"] == 0
    assert receipt["path_refs"] == []
    assert receipt["receipt_ref"] == ""


def test_retired_stub_never_invokes_path_or_live_collaborators(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("retired stub must not perform live I/O")

    path_methods = (
        "resolve",
        "read_text",
        "write_text",
        "exists",
        "is_file",
        "is_dir",
        "open",
        "mkdir",
        "unlink",
        "replace",
        "rename",
    )
    for name in path_methods:
        if hasattr(Path, name):
            monkeypatch.setattr(Path, name, forbidden)

    plan = c0_cutover.build_c0_cutover_plan(
        project_root=Path("/must-not-be-read"), cr_id="CR-064", work_id="WORK-064"
    )
    receipt = c0_cutover.apply_c0_cutover(
        project_root=Path("/must-not-be-read"),
        work_id="WORK-064",
        semantic_plan_factory=forbidden,
    )
    assert plan.as_dict()["decision"] == "BLOCKED"
    assert receipt["reason"] == "C0_V2_RETIRED"


def test_retired_authorization_is_compatibility_only_and_live_helpers_are_absent() -> None:
    authorization = c0_cutover.C0CutoverAuthorizationV2.from_dict({"legacy": "accepted"})
    assert dict(authorization.payload) == {"legacy": "accepted"}
    for invalid_payload in (None, [], "legacy"):
        try:
            c0_cutover.C0CutoverAuthorizationV2.from_dict(invalid_payload)  # type: ignore[arg-type]
        except ValueError as exc:
            assert str(exc) == "C0 V2 authorization must be an object"
        else:
            raise AssertionError("non-Mapping authorization payload must fail closed")
    assert c0_cutover.validate_c0_cutover_authorization(
        c0_cutover.C0CutoverPlanV2(), authorization
    ) is None

    tree = ast.parse(Path(c0_cutover.__file__).read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    function_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert imported_modules.isdisjoint(
        {
            "os",
            "subprocess",
            "tempfile",
            "shutil",
            "uuid",
            "json",
            "meta_flow.project.process_route",
            "meta_flow.state.event_ledger",
            "meta_flow.state.checkpoint_projection",
        }
    )
    assert function_names.isdisjoint(
        {
            "_git_common_dir",
            "_c0_private_root",
            "_c0_process_lock_path",
            "_claim_c0_authorization",
            "_atomic_write",
            "_optional_text",
            "_append_ndjson",
            "_target_history",
            "_write_receipt",
            "_rollback_targets",
        }
    )
