from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.checks.detector_qualification import (
    BASELINE_REL,
    WriterCallV1,
    check_baseline_ancestor,
    check_detector_qualification,
    qualify_dynamic_allowlist,
    scan_full_writer_baseline,
    scan_incremental_writers,
)
from meta_flow.project.process_route import require_process_route

OBSERVATION_WRITER_EVIDENCE_SHA256 = (
    "9509fff7e710da7976f339b171da878b6d9689ff82fd90ec4926ca9e991ab9e2"
)
OBSERVATION_WRITER_CALLS = {
    "70927273969163e40a03b1d032a37dafa74c1a17a1b839bd810a48dd1b25102b": (
        "meta_flow/migration/observation_storage.py",
        "compare_and_swap",
        96,
        "open",
        "<dynamic>",
        "dynamic",
    ),
    "1e133e56debea2cbf9047c81cc3ce81db760c5343e0ec9ea3d3bd9d7305676c0": (
        "meta_flow/migration/observation_storage.py",
        "compare_and_swap",
        100,
        "write",
        "<dynamic>",
        "dynamic",
    ),
    "cd3e46f49f0e47aa29d4f6dd15be4674d9d77706ee9b4ea7b3c28e3845b3c35b": (
        "meta_flow/migration/observation_storage.py",
        "compare_and_swap",
        117,
        "write",
        "<dynamic>",
        "dynamic",
    ),
    "0919d309dbae3c4b6e4c0ca9784aa1f07f9be9eb8c161ea6f26355d24370dbe6": (
        "meta_flow/migration/observation_storage.py",
        "compare_and_swap",
        120,
        "replace",
        "<dynamic>",
        "dynamic",
    ),
    "e3a2e9a9d027921684837ce93083351efa3a053c8d22c953adccb46f81f9c25c": (
        "meta_flow/migration/observation_storage.py",
        "compare_and_swap",
        128,
        "unlink",
        "<dynamic>",
        "dynamic",
    ),
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "release"
    (root / "meta_flow").mkdir(parents=True)
    _git(root, "init", "-b", "main")
    (root / "meta_flow/base.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "baseline",
    )
    return root, _git(root, "rev-parse", "HEAD")


def test_incremental_scanner_only_observes_added_lines_and_classifies_targets(
    tmp_path: Path,
) -> None:
    root, baseline = _repo(tmp_path)
    (root / "meta_flow/new.py").write_text(
        "from pathlib import Path\n"
        "def resolved():\n"
        "    Path('state/result.json').write_text('ok', encoding='utf-8')\n"
        "def dynamic(target):\n"
        "    target.write_text('x', encoding='utf-8')\n",
        encoding="utf-8",
    )

    calls, findings, stats = scan_incremental_writers(
        root,
        baseline_oid=baseline,
        source_roots=("meta_flow",),
    )

    assert findings == ()
    assert stats["changed_file_count"] == 1
    assert [call.target_kind for call in calls] == ["literal-or-alias", "dynamic"]
    assert calls[0].target == "state/result.json"


def test_unchanged_historical_writer_is_outside_incremental_denominator(
    tmp_path: Path,
) -> None:
    root, _initial = _repo(tmp_path)
    (root / "meta_flow/base.py").write_text(
        "def legacy(target):\n    target.write_text('legacy')\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "legacy writer baseline",
    )
    baseline = _git(root, "rev-parse", "HEAD")
    (root / "meta_flow/other.py").write_text("VALUE = 2\n", encoding="utf-8")

    calls, findings, _stats = scan_incremental_writers(
        root,
        baseline_oid=baseline,
        source_roots=("meta_flow",),
    )

    assert findings == ()
    assert calls == ()


def test_repository_r13_incremental_hard_gate_preserves_only_preexisting_blocker() -> None:
    root = Path(__file__).parents[1]

    report = check_detector_qualification(root)

    assert report["decision"] == "BLOCKED"
    assert report["qualification"] == "product-full-baseline-plus-incremental-hard-gate-v2"
    assert report["legacy_d0_calibration"]["unresolved_file_writer_calls"] == 1053
    assert report["full_source_baseline"]["decision"] == "PASS"
    assert report["full_source_baseline"]["ambiguous_writer_call_count"] == 0
    assert report["unresolved_unallowlisted_count"] == 1
    assert report["allowlisted_dynamic_writer_call_count"] == 41
    unresolved_findings = [
        finding
        for finding in report["findings"]
        if finding.startswith("DETECTOR_NEW_UNRESOLVED_WRITER:")
    ]
    assert unresolved_findings == [
        "DETECTOR_NEW_UNRESOLVED_WRITER:"
        "7cae419855a1fc8c8162890ee9a4b1cbd0a1297634d032c215770e5e7c4c373f:"
        "meta_flow/workflow/cr_index.py:375"
    ]
    dynamic_calls = [
        item for item in report["writer_calls"] if item["target_kind"] == "dynamic"
    ]
    qualified_calls = [
        item
        for item in dynamic_calls
        if item["call_id"]
        != "7cae419855a1fc8c8162890ee9a4b1cbd0a1297634d032c215770e5e7c4c373f"
    ]
    assert len(dynamic_calls) == 42
    assert len(qualified_calls) == 41
    assert {item["ref"] for item in qualified_calls} == {
        "meta_flow/execution_control/repair_admission.py",
        "meta_flow/migration/observation_storage.py",
        "meta_flow/state/projection_transaction.py",
        "meta_flow/work/init_transaction.py",
        "meta_flow/work/lifecycle.py",
        "meta_flow/work/lifecycle_transaction.py",
        "scripts/qualify_provider_artifact.py",
        "scripts/run_provider_artifact_canary.py",
    }
    assert {item["function"] for item in qualified_calls} == {
        "_platform_lock",
        "_acquire_lock",
        "_claim_lock",
        "_release_lock",
        "acquire_shared_projection_writer_lock",
        "record_shared_projection_successor",
        "discard_shared_projection_successor",
        "_ensure_plain_directory",
        "_write_atomic",
        "_remove_created_directories",
        "_ensure_plain_claim_directory",
        "_unlink_owned_regular",
        "claim_repair_authorization",
        "compare_and_swap",
        "finish",
        "main",
        "atomic_remove_regular_file",
        "update_work_status",
    }


def test_repository_observation_writer_qualification_is_exact_and_evidence_bound() -> None:
    root = Path(__file__).parents[1]
    report = check_detector_qualification(root)
    observed = {
        item["call_id"]: (
            item["ref"],
            item["function"],
            item["line"],
            item["operation"],
            item["target"],
            item["target_kind"],
        )
        for item in report["writer_calls"]
        if item["ref"] == "meta_flow/migration/observation_storage.py"
    }
    assert observed == OBSERVATION_WRITER_CALLS
    assert not any(
        "meta_flow/migration/observation_storage.py" in finding
        for finding in report["findings"]
    )

    process_root = require_process_route(root).process_root
    baseline = json.loads((process_root / BASELINE_REL).read_text(encoding="utf-8"))
    entries = {
        item["call_id"]: item
        for item in baseline["dynamic_allowlist"]
        if item["owner"] == "meta_flow.migration.observation_storage"
    }
    assert set(entries) == set(OBSERVATION_WRITER_CALLS)
    assert all(
        item["evidence_ref"]
        == "process/governance/OBSERVATION-STORAGE-WRITER-QUALIFICATION.md"
        and item["evidence_sha256"] == OBSERVATION_WRITER_EVIDENCE_SHA256
        and item["reason"].strip()
        for item in entries.values()
    )
    evidence = process_root / entries[next(iter(entries))]["evidence_ref"].removeprefix(
        "process/"
    )
    assert sha256(evidence.read_bytes()).hexdigest() == OBSERVATION_WRITER_EVIDENCE_SHA256
    source = root / "meta_flow/migration/observation_storage.py"
    assert (
        sha256(source.read_bytes()).hexdigest()
        == "1801ac607fcbb68cad453c4ab58cc288f27c8d681532e5c51b30567d492fa659"
    )


def test_repository_full_writer_baseline_is_currently_classified() -> None:
    root = Path(__file__).parents[1]

    report = scan_full_writer_baseline(
        root,
        source_roots=("meta_flow", "scripts"),
        include_calls=False,
    )

    assert report["decision"] == "PASS"
    assert report["ambiguous_writer_call_count"] == 0
    assert report["classified_writer_call_count"] == report["writer_call_count"]
    assert report["excluded_non_file_call_count"] > 0


def test_full_writer_baseline_types_receivers_and_binds_streams(tmp_path: Path) -> None:
    root = tmp_path / "release"
    source = root / "meta_flow/sample.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "def writers(root: Path, file_ops):\n"
        "    target = root / 'result.json'\n"
        "    target.write_text('ok')\n"
        "    with target.open('a') as stream:\n"
        "        stream.write('more')\n"
        "    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT)\n"
        "    os.write(descriptor, b'x')\n"
        "    with os.fdopen(descriptor, 'wb') as handle:\n"
        "        handle.write(b'y')\n"
        "    temp = root / 'temp.json'\n"
        "    with file_ops.open_exclusive(temp) as custom:\n"
        "        custom.write(b'z')\n"
        "def non_files(value, mapping: dict[str, str]):\n"
        "    items: set[str] = {'x'}\n"
        "    value.replace('a', 'b')\n"
        "    items.remove('x')\n"
        "    mapping.copy()\n",
        encoding="utf-8",
    )

    report = scan_full_writer_baseline(root, source_roots=("meta_flow",))

    assert report["decision"] == "PASS"
    assert report["ambiguous_writer_call_count"] == 0
    assert report["exclusion_counts"]["string-or-object-replace"] == 1
    assert report["exclusion_counts"]["typed-container-remove"] == 1
    assert report["exclusion_counts"]["typed-container-copy"] == 1
    assert report["classification_counts"]["descriptor-open"] == 1
    assert report["classification_counts"]["write-mode-open-stream"] == 3


def test_full_writer_baseline_blocks_untyped_writer_like_method(tmp_path: Path) -> None:
    root = tmp_path / "release"
    source = root / "meta_flow/ambiguous.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def mutate(candidate):\n    candidate.remove('unknown')\n",
        encoding="utf-8",
    )

    report = scan_full_writer_baseline(root, source_roots=("meta_flow",))

    assert report["decision"] == "BLOCKED"
    assert report["ambiguous_writer_call_count"] == 1
    assert report["ambiguous_calls"][0]["classification"] == ("ambiguous-non-module-writer-method")


def test_full_writer_baseline_blocks_dynamic_open_mode(tmp_path: Path) -> None:
    root = tmp_path / "release"
    source = root / "meta_flow/dynamic_open.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from pathlib import Path\n"
        "def mutate(path: Path, mode: str):\n"
        "    return open(path, mode)\n",
        encoding="utf-8",
    )

    report = scan_full_writer_baseline(root, source_roots=("meta_flow",))

    assert report["decision"] == "BLOCKED"
    assert report["ambiguous_calls"][0]["classification"] == ("ambiguous-dynamic-open-mode")


def test_full_writer_baseline_stops_at_file_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "release"
    source = root / "meta_flow"
    source.mkdir(parents=True)
    (source / "first.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "second.py").write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.setattr("meta_flow.checks.detector_qualification.MAX_FILES", 1)

    report = scan_full_writer_baseline(root, source_roots=("meta_flow",))

    assert report["decision"] == "BLOCKED"
    assert report["source_file_count"] == 2
    assert report["findings"] == ["DETECTOR_FULL_FILE_BUDGET_EXCEEDED"]


def test_full_writer_baseline_keeps_function_assignments_isolated(tmp_path: Path) -> None:
    root = tmp_path / "release"
    source = root / "meta_flow/scopes.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from pathlib import Path\n"
        "def first(root: Path):\n"
        "    target = root / 'first.json'\n"
        "    target.write_text('one')\n"
        "def second():\n"
        "    target = 'text'\n"
        "    return target.replace('t', 'T')\n",
        encoding="utf-8",
    )

    report = scan_full_writer_baseline(root, source_roots=("meta_flow",))

    assert report["decision"] == "PASS"
    writer = report["writer_calls"][0]
    assert writer["target_expression"] == "root / 'first.json'"
    assert writer["target_kind"] == "symbolic-path"


def test_changed_alias_requalifies_unchanged_writer_call(tmp_path: Path) -> None:
    root, _initial = _repo(tmp_path)
    source = root / "meta_flow/base.py"
    source.write_text(
        "from pathlib import Path\n"
        "def writer():\n"
        "    target = Path('before.json')\n"
        "    target.write_text('x')\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "writer baseline",
    )
    baseline = _git(root, "rev-parse", "HEAD")
    source.write_text(
        "from pathlib import Path\n"
        "def writer():\n"
        "    target = Path('after.json')\n"
        "    target.write_text('x')\n",
        encoding="utf-8",
    )

    calls, findings, _stats = scan_incremental_writers(
        root,
        baseline_oid=baseline,
        source_roots=("meta_flow",),
    )

    assert findings == ()
    assert len(calls) == 1
    assert calls[0].line == 4
    assert calls[0].target == "after.json"


def test_extended_file_writer_primitives_are_detected(tmp_path: Path) -> None:
    root, baseline = _repo(tmp_path)
    (root / "meta_flow/new.py").write_text(
        "import os\n"
        "import shutil\n"
        "from pathlib import Path\n"
        "os.remove('obsolete.json')\n"
        "shutil.move('source.json', 'archive/target.json')\n"
        "Path('marker').touch()\n",
        encoding="utf-8",
    )

    calls, findings, _stats = scan_incremental_writers(
        root,
        baseline_oid=baseline,
        source_roots=("meta_flow",),
    )

    assert findings == ()
    assert [(call.operation, call.target) for call in calls] == [
        ("remove", "obsolete.json"),
        ("move", "archive/target.json"),
        ("touch", "marker"),
    ]


def test_string_replace_on_path_named_value_is_not_a_file_writer(tmp_path: Path) -> None:
    root, baseline = _repo(tmp_path)
    (root / "meta_flow/new.py").write_text(
        "def normalize(rel_path: str) -> str:\n    return rel_path.replace('\\\\', '/')\n",
        encoding="utf-8",
    )

    calls, findings, _stats = scan_incremental_writers(
        root,
        baseline_oid=baseline,
        source_roots=("meta_flow",),
    )

    assert findings == ()
    assert calls == ()


def test_parse_and_budget_failures_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, baseline = _repo(tmp_path)
    (root / "meta_flow/broken.py").write_text("def broken(:\n", encoding="utf-8")

    _calls, findings, _stats = scan_incremental_writers(
        root,
        baseline_oid=baseline,
        source_roots=("meta_flow",),
    )
    assert findings == ("DETECTOR_PARSE_FAILED:meta_flow/broken.py",)

    monkeypatch.setattr("meta_flow.checks.detector_qualification.MAX_FILES", 0)
    _calls, findings, _stats = scan_incremental_writers(
        root,
        baseline_oid=baseline,
        source_roots=("meta_flow",),
    )
    assert findings == ("DETECTOR_FILE_BUDGET_EXCEEDED",)


def test_allowlist_rejects_unlisted_stale_missing_or_drifted_evidence(
    tmp_path: Path,
) -> None:
    call = WriterCallV1(
        "call-current",
        "meta_flow/new.py",
        "writer",
        10,
        "write_text",
        "<dynamic>",
        "dynamic",
    )
    evidence = tmp_path / "contract.md"
    evidence.write_text("contract\n", encoding="utf-8")
    ref = "process/contract.md"
    valid = {
        "call_id": call.call_id,
        "owner": "owner",
        "reason": "reviewed dynamic target",
        "evidence_ref": ref,
        "evidence_sha256": sha256(evidence.read_bytes()).hexdigest(),
    }

    allowlist, findings = qualify_dynamic_allowlist((call,), [], tmp_path)
    assert allowlist == {}
    assert findings[0].startswith("DETECTOR_NEW_UNRESOLVED_WRITER:")

    stale = {**valid, "call_id": "call-stale"}
    _allowlist, findings = qualify_dynamic_allowlist((call,), [stale], tmp_path)
    assert any(item.startswith("DETECTOR_ALLOWLIST_STALE:call-stale") for item in findings)

    missing = {**valid, "evidence_ref": "process/missing.md"}
    _allowlist, findings = qualify_dynamic_allowlist((call,), [missing], tmp_path)
    assert "DETECTOR_ALLOWLIST_EVIDENCE_MISSING:call-current" in findings

    drifted = {**valid, "evidence_sha256": "0" * 64}
    _allowlist, findings = qualify_dynamic_allowlist((call,), [drifted], tmp_path)
    assert "DETECTOR_ALLOWLIST_EVIDENCE_DRIFT:call-current" in findings


def test_non_ancestor_baseline_is_blocked(tmp_path: Path) -> None:
    root, _baseline = _repo(tmp_path)

    assert check_baseline_ancestor(root, "0" * 40) == ("DETECTOR_BASELINE_NOT_ANCESTOR",)
