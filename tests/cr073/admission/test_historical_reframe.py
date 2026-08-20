from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.project.historical_reframe import (
    HistoricalClaimV1,
    HistoricalProviderIdentityV1,
    apply_historical_reframe,
    classify_historical_fact,
    plan_historical_reframe,
)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    release = tmp_path / "meta-flow"
    process = tmp_path / "meta-flow-process"
    (release / ".meta-flow").mkdir(parents=True)
    process.mkdir()
    for repository in (release, process):
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    (release / ".meta-flow" / "workspace.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture\n"
        "repo_role: release\n"
        "route_mode: sibling-binding\n"
        "process_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow-process\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture\n"
        "repo_role: process\n"
        "route_mode: sibling-binding\n"
        "release_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\nproject_id: fixture\nname: Fixture\nstatus: active\n",
        encoding="utf-8",
    )
    return release, process


def _provider() -> HistoricalProviderIdentityV1:
    return HistoricalProviderIdentityV1(
        package="meta-flow",
        version="0.6.1+candidate",
        source_kind="candidate-source",
        release_oid="a" * 40,
        process_oid="b" * 40,
        route_digest="c" * 64,
    )


def _authorization() -> str:
    return (
        "process/state/GATE-LEDGER.ndjson"
        "#GATE-CR073-CP5-ALL-STORIES-DESIGN-APPROVED-20260820-V1"
    )


def test_classification_never_promotes_missing_or_unbound_evidence_to_proven() -> None:
    payload = b"historical evidence\n"
    digest = sha256(payload).hexdigest()
    proven = classify_historical_fact(
        HistoricalClaimV1("known", "process/known.json", "known bytes", digest),
        observed_bytes=payload,
    )
    contradicted = classify_historical_fact(
        HistoricalClaimV1("drift", "process/drift.json", "drifted bytes", "d" * 64),
        observed_bytes=payload,
    )
    unknown = classify_historical_fact(
        HistoricalClaimV1("missing", "process/missing.json", "missing evidence"),
        observed_bytes=None,
        observation_error="SOURCE_MISSING",
    )

    assert proven.status == "proven"
    assert contradicted.status == "contradicted"
    assert unknown.status == "audited-known-historical-fact"
    assert unknown.source_digest == ""


def test_plan_apply_and_replay_are_create_only_and_semantic_noop(tmp_path: Path) -> None:
    release, process = _fixture(tmp_path)
    source = process / "changes" / "CR-071.md"
    source.parent.mkdir()
    source.write_text("historic bytes\n", encoding="utf-8")
    digest = sha256(source.read_bytes()).hexdigest()
    claim = HistoricalClaimV1(
        "cr071-source",
        "process/changes/CR-071.md",
        "CR-071 canonical source bytes are preserved",
        digest,
    )

    plan = plan_historical_reframe(
        release,
        cr_id="CR-071",
        claims=(claim,),
        provider_identity=_provider(),
        authorization_ref=_authorization(),
    )
    assert plan.decision == "READY"
    assert plan.mutation_count == 1
    result = apply_historical_reframe(
        release,
        plan=plan,
        expected_plan_digest=plan.plan_digest,
        current_provider_identity=_provider(),
        current_authorization_ref=_authorization(),
    )
    assert result["decision"] == "APPLIED"
    assert result["mutation_count"] == 1
    target = process / "archive" / "CR-071" / "CR-071-HISTORICAL-REFRAME.json"
    original_source = source.read_bytes()
    record = json.loads(target.read_text(encoding="utf-8"))
    assert record["facts"][0]["status"] == "proven"
    assert record["zero_fabrication"] is True
    assert source.read_bytes() == original_source

    replay = plan_historical_reframe(
        release,
        cr_id="CR-071",
        claims=(claim,),
        provider_identity=_provider(),
        authorization_ref=_authorization(),
    )
    assert replay.decision == "NO_CHANGE"
    assert replay.mutation_count == 0


def test_apply_rejects_source_provider_authorization_and_plan_drift(tmp_path: Path) -> None:
    release, process = _fixture(tmp_path)
    source = process / "checks" / "CP6.json"
    source.parent.mkdir()
    source.write_text("{}\n", encoding="utf-8")
    claim = HistoricalClaimV1(
        "cp6",
        "process/checks/CP6.json",
        "CP6 evidence is present",
        sha256(source.read_bytes()).hexdigest(),
    )
    plan = plan_historical_reframe(
        release,
        cr_id="CR-071",
        claims=(claim,),
        provider_identity=_provider(),
        authorization_ref=_authorization(),
    )

    source.write_text('{"changed":true}\n', encoding="utf-8")
    drift = apply_historical_reframe(
        release,
        plan=plan,
        expected_plan_digest=plan.plan_digest,
        current_provider_identity=_provider(),
        current_authorization_ref=_authorization(),
    )
    assert drift == {
        "decision": "BLOCKED",
        "blockers": ["SOURCE_PREIMAGE_DRIFT"],
        "mutation_count": 0,
    }
    assert not (process / "archive" / "CR-071" / "CR-071-HISTORICAL-REFRAME.json").exists()

    stale_provider = replace(_provider(), process_oid="e" * 40)
    provider_result = apply_historical_reframe(
        release,
        plan=plan,
        expected_plan_digest=plan.plan_digest,
        current_provider_identity=stale_provider,
        current_authorization_ref=_authorization(),
    )
    assert provider_result["blockers"] == ["PROVIDER_IDENTITY_DRIFT"]
    authorization_result = apply_historical_reframe(
        release,
        plan=plan,
        expected_plan_digest=plan.plan_digest,
        current_provider_identity=_provider(),
        current_authorization_ref=_authorization() + "-other",
    )
    assert authorization_result["blockers"] == ["AUTHORIZATION_DRIFT"]
    plan_result = apply_historical_reframe(
        release,
        plan=plan,
        expected_plan_digest="f" * 64,
        current_provider_identity=_provider(),
        current_authorization_ref=_authorization(),
    )
    assert plan_result["blockers"] == ["PLAN_DIGEST_MISMATCH"]


def test_unsafe_or_symlink_source_blocks_without_target_mutation(tmp_path: Path) -> None:
    release, process = _fixture(tmp_path)
    actual = process / "actual.json"
    actual.write_text("{}\n", encoding="utf-8")
    link = process / "linked.json"
    try:
        link.symlink_to(actual)
    except OSError:
        pytest.skip("symlink is unavailable on this platform")

    plan = plan_historical_reframe(
        release,
        cr_id="CR-071",
        claims=(HistoricalClaimV1("linked", "process/linked.json", "symlink evidence"),),
        provider_identity=_provider(),
        authorization_ref=_authorization(),
    )
    assert plan.decision == "BLOCKED"
    assert "SOURCE_SYMLINK_FORBIDDEN:process/linked.json" in plan.blockers
    assert plan.record is None
    assert not (process / "archive").exists()


def test_existing_different_target_is_a_conflict(tmp_path: Path) -> None:
    release, process = _fixture(tmp_path)
    source = process / "changes" / "CR-071.md"
    source.parent.mkdir()
    source.write_text("history\n", encoding="utf-8")
    target = process / "archive" / "CR-071" / "CR-071-HISTORICAL-REFRAME.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"foreign":true}\n', encoding="utf-8")

    plan = plan_historical_reframe(
        release,
        cr_id="CR-071",
        claims=(HistoricalClaimV1("source", "process/changes/CR-071.md", "history"),),
        provider_identity=_provider(),
        authorization_ref=_authorization(),
    )
    assert plan.decision == "BLOCKED"
    assert plan.blockers == ("TARGET_CONFLICT",)
    assert target.read_text(encoding="utf-8") == '{"foreign":true}\n'
