import inspect
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.policies import c0_cutover, public_operations, route_plan
from meta_flow.project.scale import load_yaml_object


def test_retained_public_operations_are_zero_write_and_none() -> None:
    registry = Path("delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml")
    contracts = load_yaml_object(registry)
    entries = {item["operation"]: item for item in contracts["operations"]}
    expected = {
        "route.c0-cutover-plan": ("C0CutoverPlanV2", "zero-write", "none"),
        "route.c0-cutover-apply": ("C0CutoverReceiptV2", "zero-write", "none"),
    }
    assert set(expected).issubset(entries)
    for operation, (output_version, mutation_mode, authorization_mode) in expected.items():
        entry = entries[operation]
        assert entry["output_version"] == output_version
        assert entry["mutation_mode"] == mutation_mode
        assert entry["authorization_mode"] == authorization_mode
        assert public_operations.PUBLIC_OPERATION_ENTRIES[operation] == tuple(entry["entry"])


def test_four_retired_cli_commands_are_fail_closed_without_project_access() -> None:
    assert c0_cutover.RETIRED_GATE_LEDGER_REF == route_plan.C0_RETIRED_GATE_LEDGER_REF
    assert "diagnostic_ref=C0_RETIRED_GATE_LEDGER_REF" in inspect.getsource(
        route_plan._retired_c0_result
    )
    for command, expected_exit, expected_kind in (
        ("c0-dry-run", 1, "C0CutoverPlanV2"),
        ("c0-cutover-plan", 1, "C0CutoverPlanV2"),
        ("c0-apply", 2, "C0CutoverReceiptV2"),
        ("c0-cutover-apply", 2, "C0CutoverReceiptV2"),
    ):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = route_plan.main(
                [command, "--project-root", "/must-not-be-read", "--cr-id", "CR-064"]
            )
        payload = json.loads(output.getvalue())
        assert exit_code == expected_exit
        assert payload["kind"] == expected_kind
        assert payload["decision"] == "BLOCKED"
        if command in {"c0-dry-run", "c0-cutover-plan"}:
            assert payload["cr_id"] == "CR-064"
            assert payload["work_id"] == "GOV-006-KERNEL-001"


def test_route_help_describes_c0_as_retired_zero_write_compatibility() -> None:
    output = StringIO()
    with redirect_stdout(output):
        assert route_plan.main(["--help"]) == 0
    help_text = output.getvalue()
    for command in ("c0-dry-run", "c0-apply", "c0-cutover-plan", "c0-cutover-apply"):
        assert command in help_text
    assert "Retired" in help_text
    assert "zero-write" in help_text
    assert "first-activation five-target transaction" not in help_text
