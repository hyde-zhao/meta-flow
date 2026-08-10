from __future__ import annotations

import inspect
import shutil
import subprocess
from pathlib import Path

from meta_flow.execution_control.consumer_scan import (
    SCANNER_REF,
    TRACKED_DISCOVERY_COMMAND,
    scan_execution_control_consumers,
)


def _write(root: Path, ref: str, text: str) -> None:
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture(root: Path, *, track_scanner: bool = True) -> Path:
    scanner_source = Path(__file__).parents[1] / SCANNER_REF
    target = root / SCANNER_REF
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(scanner_source, target)
    _write(
        root,
        "meta_flow/execution_control/migration.py",
        "def current_execution_control_policy():\n    return 'enforce-new'\n\n"
        "def _mint_materialization_capability():\n    return None\n\n"
        "def _perform_receipt_create_only():\n    return None\n\n"
        "def _apply_security_gate():\n"
        "    _mint_materialization_capability()\n"
        "    _perform_receipt_create_only()\n",
    )
    _write(
        root,
        "meta_flow/work/assurance.py",
        "from meta_flow.execution_control.migration import current_execution_control_policy\n"
        "VALUE = current_execution_control_policy()\n",
    )
    _write(
        root,
        "meta_flow/cli.py",
        "from meta_flow.work import cli as work_cli\n"
        "from meta_flow import evolution_cli\n\n"
        "def dispatch():\n"
        "    work_cli.main([])\n"
        "    evolution_cli.main([])\n",
    )
    _write(
        root,
        "tests/test_short_name.py",
        "def current_execution_control_policy():\n    return 'local'\n\n"
        "def test_local():\n    assert current_execution_control_policy() == 'local'\n",
    )
    subprocess.run(("git", "init", "-q", str(root)), check=True)
    tracked = [
        "meta_flow/execution_control/migration.py",
        "meta_flow/cli.py",
        "meta_flow/work/assurance.py",
        "tests/test_short_name.py",
    ]
    if track_scanner:
        tracked.append(SCANNER_REF)
    subprocess.run(("git", "-C", str(root), "add", "--", *tracked), check=True)
    return target


def test_scanner_owns_discovery_and_emits_closed_deterministic_census(
    tmp_path: Path,
) -> None:
    assert tuple(inspect.signature(scan_execution_control_consumers).parameters) == (
        "release_root",
    )
    assert TRACKED_DISCOVERY_COMMAND == (
        "git",
        "ls-files",
        "-z",
        "--",
        "meta_flow",
        "tests",
    )
    _fixture(tmp_path)

    first = scan_execution_control_consumers(tmp_path)
    second = scan_execution_control_consumers(tmp_path)

    assert first.decision == "READY"
    assert first.as_dict() == second.as_dict()
    assert first.mutation_count == 0
    assert first.parsed_refs == tuple(sorted(item.ref for item in first.sources))
    assert first.excluded_refs == ()
    assert all(len(item.sha256) == 64 and item.bytes > 0 for item in first.sources)
    assert any(
        edge.symbol
        == "meta_flow.execution_control.migration.current_execution_control_policy"
        and edge.consumer_ref == "meta_flow/work/assurance.py"
        for edge in first.edges
    )
    assert not any(
        edge.consumer_ref == "tests/test_short_name.py"
        and edge.symbol
        == "meta_flow.execution_control.migration.current_execution_control_policy"
        for edge in first.edges
    )
    assert all(value == 0 for _, value in first.exit_counters)
    assert "impacted_consumer_failure_count" not in dict(first.exit_counters)
    assert "unresolved_fixture_capability_count" not in dict(first.exit_counters)
    assert first.explicit_dispatch_edges == (
        "meta_flow/cli.py:meta_flow.evolution_cli.main",
        "meta_flow/cli.py:meta_flow.work.cli.main",
    )
    assert first.result_digest and first.scanner_contract_digest


def test_scanner_fails_closed_for_untracked_source_syntax_and_unclassified_consumer(
    tmp_path: Path,
) -> None:
    untracked = tmp_path / "untracked"
    _fixture(untracked, track_scanner=False)
    assert scan_execution_control_consumers(untracked).reason_codes == (
        "SCANNER_SOURCE_NOT_TRACKED",
    )

    syntax = tmp_path / "syntax"
    _fixture(syntax)
    _write(syntax, "meta_flow/work/assurance.py", "def broken(:\n")
    assert scan_execution_control_consumers(syntax).reason_codes == (
        "SCANNER_SYNTAX_ERROR",
    )

    unknown = tmp_path / "unknown"
    _fixture(unknown)
    _write(
        unknown,
        "meta_flow/unknown.py",
        "from meta_flow.execution_control.migration import current_execution_control_policy\n"
        "VALUE = current_execution_control_policy()\n",
    )
    subprocess.run(
        ("git", "-C", str(unknown), "add", "--", "meta_flow/unknown.py"),
        check=True,
    )
    blocked = scan_execution_control_consumers(unknown)
    assert blocked.decision == "BLOCKED"
    assert blocked.reason_codes == ("SCANNER_UNCLASSIFIED_CONSUMER",)
    assert dict(blocked.exit_counters)["unclassified_consumer_count"] == 1


def test_scanner_source_fingerprint_changes_when_tracked_bytes_drift(tmp_path: Path) -> None:
    scanner = _fixture(tmp_path)
    before = scan_execution_control_consumers(tmp_path)
    scanner.write_text(scanner.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    after = scan_execution_control_consumers(tmp_path)
    assert before.decision == after.decision == "READY"
    assert before.scanner_source_digest != after.scanner_source_digest
    assert before.source_set_digest != after.source_set_digest
    assert before.result_digest != after.result_digest


def test_scanner_blocks_dispatch_and_private_security_edge_drift(tmp_path: Path) -> None:
    dispatch = tmp_path / "dispatch"
    _fixture(dispatch)
    _write(dispatch, "meta_flow/cli.py", "def dispatch():\n    return None\n")
    blocked_dispatch = scan_execution_control_consumers(dispatch)
    assert blocked_dispatch.reason_codes == ("SCANNER_EXPLICIT_DISPATCH_EDGE_INVALID",)
    assert dict(blocked_dispatch.exit_counters)["explicit_dispatch_error_count"] == 2

    security = tmp_path / "security"
    _fixture(security)
    with (security / "meta_flow/execution_control/migration.py").open("a", encoding="utf-8") as stream:
        stream.write("\ndef bypass():\n    _mint_materialization_capability()\n")
    blocked_security = scan_execution_control_consumers(security)
    assert "SCANNER_SECURITY_CALL_EDGE_INVALID" in blocked_security.reason_codes
    assert dict(blocked_security.exit_counters)["security_call_edge_count"] == 1
