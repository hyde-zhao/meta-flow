from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.checks.detector_qualification import (
    WriterCallV1,
    check_baseline_ancestor,
    check_detector_qualification,
    qualify_dynamic_allowlist,
    scan_full_writer_baseline,
    scan_incremental_writers,
)

OBSERVATION_WRITER_CALLS = {
    "26adaf23ee3b339374d22f561afd13624fedbe072bf1070bf80f9c0c8b1b0ec3": (
        "meta_flow/migration/observation_storage.py",
        "compare_and_swap",
        96,
        "open",
        "self.path.with_name(f'.{self.path.name}.lock')",
        "symbolic-path",
    ),
    "ff7fa0a6ffeb22fd3b8dd0ca1338937581509e563a9e6f4a7cfd5bdd1a91e839": (
        "meta_flow/migration/observation_storage.py",
        "compare_and_swap",
        100,
        "write",
        "self.path.with_name(f'.{self.path.name}.lock')",
        "symbolic-path",
    ),
    "3b0b9a960a9eafc033026b4ea06557da03d9fe76cd864c1b3677886b3b7b03a2": (
        "meta_flow/migration/observation_storage.py",
        "compare_and_swap",
        117,
        "write",
        "descriptor",
        "dynamic",
    ),
    "16e7658120d087776866201cc0e7df6ac616027452cf7fb02eca46686c5e3169": (
        "meta_flow/migration/observation_storage.py",
        "compare_and_swap",
        120,
        "replace",
        "self.path",
        "symbolic-path",
    ),
    "184615795a0587ca35a719244516e8370593875e1236f6b01002371b4fde6500": (
        "meta_flow/migration/observation_storage.py",
        "compare_and_swap",
        128,
        "unlink",
        "Path(temporary_name)",
        "symbolic-path",
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


def test_repository_r14_incremental_hard_gate_has_no_unqualified_current_writer() -> None:
    root = Path(__file__).parents[1]

    report = check_detector_qualification(root)

    assert report["decision"] == "PASS"
    assert report["qualification"] == "product-full-baseline-plus-incremental-hard-gate-v2"
    assert report["legacy_d0_calibration"]["unresolved_file_writer_calls"] == 1053
    assert report["full_source_baseline"]["decision"] == "PASS"
    assert report["full_source_baseline"]["ambiguous_writer_call_count"] == 0
    assert report["unresolved_unallowlisted_count"] == 0
    assert report["allowlisted_dynamic_writer_call_count"] == 0
    assert report["incremental_writer_call_count"] == 0
    unresolved_findings = [
        finding
        for finding in report["findings"]
        if finding.startswith("DETECTOR_NEW_UNRESOLVED_WRITER:")
    ]
    assert unresolved_findings == []
    assert report["writer_calls"] == []


def test_repository_observation_writer_full_baseline_is_exact() -> None:
    root = Path(__file__).parents[1]
    report = scan_full_writer_baseline(
        root,
        source_roots=("meta_flow", "scripts"),
        include_calls=True,
    )
    observed = {
        item["call_id"]: (
            item["ref"],
            item["function"],
            item["line"],
            item["operation"],
            item["target_expression"],
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
