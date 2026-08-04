from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from meta_flow import cli
from meta_flow.state import event_ledger
from meta_flow.state.ledger_compaction import (
    LedgerCompactionError,
    apply_compaction,
    load_retention_policy,
    plan_ledger_compaction,
)


def _write_checkpoint_ledger(path: Path, *, count: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(count):
        rows.append(
            {
                "event_id": f"CP6-old-{index}",
                "event_type": "checkpoint_result",
                "checkpoint": "CP6",
                "decision": "PASS",
                "result_ref": f"process/checks/CP6-old-{index}.result.json",
                "cr_id": f"CR-{index:03d}",
                "checked_at": f"2020-01-0{min(index + 1, 9)}T00:00:00+00:00",
                "message": "this full ledger body must not be copied into archive summary",
            }
        )
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _write_small_policy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "default:",
                "  window_days: 1",
                "  keep_latest_n_events: 1",
                "  keep_latest_n_cr: 1",
                "  archive_rule: summary-index-backup",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run_cli(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["meta-flow", *args])
    try:
        cli.main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise


def test_ledger_compact_cli_is_separate_from_state_compact_help(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _run_cli(monkeypatch, ["state", "compact", "--help"])
    state_help = capsys.readouterr().out
    assert "does not compact NDJSON" in state_help
    assert "ledgers" in state_help
    assert "archive summary" not in state_help

    _run_cli(monkeypatch, ["ledger", "compact", "--help"])
    ledger_help = capsys.readouterr().out
    assert "retention/archive compaction" in ledger_help
    assert "--apply" in ledger_help


def test_retention_policy_defaults_and_invalid_policy(tmp_path: Path) -> None:
    policy = load_retention_policy(project_root=tmp_path)
    assert policy.window_days == 90
    assert policy.keep_latest_n_events == 500
    assert policy.keep_latest_n_cr == 20

    invalid = tmp_path / "process/policies/LEDGER-RETENTION.yaml"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("schema_version: 1\ndefault:\n  window_days: -1\n", encoding="utf-8")
    with pytest.raises(LedgerCompactionError, match="window_days"):
        load_retention_policy(invalid, project_root=tmp_path)


def test_default_policy_reads_canonical_retention_compaction(tmp_path: Path) -> None:
    canonical = tmp_path / "process/policies/RETENTION-POLICY.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ledgers": {
                    "append_only": True,
                    "default_context": "latest-window-or-index",
                    "compaction": {
                        "window_days": 30,
                        "keep_latest_n_events": 200,
                        "keep_latest_n_cr": 10,
                        "archive_rule": "summary-index-backup",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    policy = load_retention_policy(project_root=tmp_path)

    assert policy.window_days == 30
    assert policy.keep_latest_n_events == 200
    assert policy.keep_latest_n_cr == 10


def test_canonical_policy_rejects_invalid_compaction_schema(tmp_path: Path) -> None:
    canonical = tmp_path / "process/policies/RETENTION-POLICY.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ledgers": {
                    "compaction": {
                        "window_days": 30,
                        "keep_latest_n_events": 200,
                        "keep_latest_n_cr": 10,
                        "archive_rule": "summary-index-backup",
                        "unexpected": True,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(LedgerCompactionError, match="unknown fields: unexpected"):
        load_retention_policy(project_root=tmp_path)


def test_explicit_flat_legacy_policy_remains_compatible(tmp_path: Path) -> None:
    policy_path = tmp_path / "process/policies/legacy-flat.json"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "window_days": 7,
                "keep_latest_n_events": 11,
                "keep_latest_n_cr": 3,
                "archive_rule": "summary-index-backup",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    policy = load_retention_policy(policy_path, project_root=tmp_path)

    assert (policy.window_days, policy.keep_latest_n_events, policy.keep_latest_n_cr) == (
        7,
        11,
        3,
    )


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = tmp_path / "process/state/CHECKPOINT-LEDGER.ndjson"
    policy = tmp_path / "process/policies/LEDGER-RETENTION.yaml"
    _write_checkpoint_ledger(ledger)
    _write_small_policy(policy)
    before = ledger.read_text(encoding="utf-8")

    _run_cli(
        monkeypatch,
        [
            "ledger",
            "compact",
            "--project-root",
            str(tmp_path),
            "--ledger",
            "process/state/CHECKPOINT-LEDGER.ndjson",
            "--policy",
            str(policy),
        ],
    )

    output = capsys.readouterr().out
    assert "Ledger Compact DRY-RUN" in output
    assert "writes: none" in output
    assert ledger.read_text(encoding="utf-8") == before
    assert not (tmp_path / "process/archive").exists()


def test_apply_writes_archive_index_backup_marker_and_event_check_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = tmp_path / "process/state/CHECKPOINT-LEDGER.ndjson"
    policy = tmp_path / "process/policies/LEDGER-RETENTION.yaml"
    _write_checkpoint_ledger(ledger)
    _write_small_policy(policy)
    before = ledger.read_bytes()

    _run_cli(
        monkeypatch,
        [
            "ledger",
            "compact",
            "--project-root",
            str(tmp_path),
            "--ledger",
            "process/state/CHECKPOINT-LEDGER.ndjson",
            "--policy",
            str(policy),
            "--apply",
        ],
    )

    output = capsys.readouterr().out
    assert "Ledger Compact APPLY" in output
    assert "Apply Result" in output
    archive_root = tmp_path / "process/archive/ledger"
    summaries = list((archive_root / "checkpoint").glob("*.summary.json"))
    backups = list((archive_root / "backups").glob("*.bak.ndjson"))
    index_path = archive_root / "ledger-archive-index.json"
    assert len(summaries) == 1
    assert len(backups) == 1
    assert index_path.is_file()

    summary_text = summaries[0].read_text(encoding="utf-8")
    assert "full ledger body must not be copied" not in summary_text
    summary = json.loads(summary_text)
    assert summary["event_count"] == 5
    assert summary["backup_ref"].startswith("process/archive/ledger/backups/")

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["entries"][0]["event_count"] == 5
    assert index["entries"][0]["hash_before"]
    assert index["entries"][0]["hash_after"]

    compacted_events, errors = event_ledger.load_events(ledger)
    assert not errors
    assert compacted_events[-1]["event_type"] == "ledger_compacted"
    check_errors, _warnings = event_ledger.validate_event_ledger(ledger, ledger_type="checkpoint")
    assert check_errors == []

    ledger.write_bytes(backups[0].read_bytes())
    assert ledger.read_bytes() == before


def test_post_apply_failure_restores_source_bytes(tmp_path: Path) -> None:
    ledger = tmp_path / "process/state/CHECKPOINT-LEDGER.ndjson"
    _write_checkpoint_ledger(ledger)
    before = ledger.read_bytes()
    policy = load_retention_policy(project_root=tmp_path)
    small_policy = policy.__class__(
        window_days=1,
        keep_latest_n_events=1,
        keep_latest_n_cr=1,
    )
    plan = plan_ledger_compaction(
        ledger,
        project_root=tmp_path,
        policy=small_policy,
        ledger_type="checkpoint",
    )

    with (
        patch(
            "meta_flow.state.ledger_compaction.event_ledger.validate_event_ledger",
            return_value=(["injected post-apply failure"], []),
        ),
        pytest.raises(LedgerCompactionError, match="post-apply event check failed"),
    ):
        apply_compaction(plan)

    assert ledger.read_bytes() == before


def test_hash_mismatch_aborts_without_changing_current_payload(tmp_path: Path) -> None:
    ledger = tmp_path / "process/state/CHECKPOINT-LEDGER.ndjson"
    _write_checkpoint_ledger(ledger)
    policy = load_retention_policy(project_root=tmp_path)
    small_policy = policy.__class__(window_days=1, keep_latest_n_events=1, keep_latest_n_cr=1)
    plan = plan_ledger_compaction(ledger, project_root=tmp_path, policy=small_policy, ledger_type="checkpoint")
    changed = ledger.read_text(encoding="utf-8") + json.dumps(
        {
            "event_id": "CP6-new",
            "event_type": "checkpoint_result",
            "checkpoint": "CP6",
            "decision": "PASS",
            "result_ref": "process/checks/new.result.json",
            "checked_at": "2020-01-09T00:00:00+00:00",
        },
        sort_keys=True,
    ) + "\n"
    ledger.write_text(changed, encoding="utf-8")

    with pytest.raises(LedgerCompactionError, match="hash changed"):
        apply_compaction(plan)

    assert ledger.read_text(encoding="utf-8") == changed
    assert not (tmp_path / "process/archive").exists()


def test_path_guard_rejects_quant_lab_and_outside_project(tmp_path: Path) -> None:
    policy = load_retention_policy(project_root=tmp_path)
    with pytest.raises(LedgerCompactionError, match="forbidden"):
        plan_ledger_compaction(tmp_path / "process/quant-lab/state/LEDGER.ndjson", project_root=tmp_path, policy=policy)
    outside = tmp_path.parent / "outside-ledger.ndjson"
    outside.write_text("", encoding="utf-8")
    with pytest.raises(LedgerCompactionError, match="outside project root"):
        plan_ledger_compaction(outside, project_root=tmp_path, policy=policy)
