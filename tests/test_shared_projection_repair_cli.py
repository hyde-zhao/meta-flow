"""CR-078 S2 回归：work shared-projection-repair CLI 全链。

楔死仓库（scope-amend 未登记后继的 0.6.5 存量态同构）→ 零写 plan →
mint 授权 → apply → close 族解锁；幂等重跑零 mutation；漂移 SUPERSEDED；
非法授权拒绝。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_scope_amend_shared_projection_successor import _amend, _transition

from meta_flow.work import cli as work_cli
from meta_flow.work.lifecycle_transaction import inspect_work_close_transactions


def _wedged_fixture(tmp_path: Path):
    """blocked→amend→删 receipt：0.6.5 存量楔死态同构。"""

    from test_scope_amend_shared_projection_successor import _blocked_fixture

    release, process, _block = _blocked_fixture(tmp_path)
    _plan, result = _amend(release, process, "auth-w001-r2")
    assert result["decision"] == "PASS"
    successor_id = result["shared_projection_successor_id"]
    (process / ".meta-flow-runtime/work-close/successors" / f"{successor_id}.json").unlink()
    report = inspect_work_close_transactions(process)
    assert report["decision"] == "BLOCKED"
    return release, process


def _run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> dict:
    code = work_cli.shared_projection_repair_main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    return {"code": code, "payload": payload}


def test_repair_cli_zero_write_plan_then_fixes_wedged_work_yaml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release, process = _wedged_fixture(tmp_path)
    before = {
        path: path.read_bytes()
        for path in sorted(process.rglob("*"))
        if path.is_file() and ".meta-flow-runtime" not in path.parts
    }

    result = _run_cli(["--project-root", str(release)], capsys)
    assert result["payload"]["classification"] == "COMMITTED_STALE_REPAIRABLE"
    targets = result["payload"]["repair_plan"]["targets"]
    assert any(target["ref"] == "works/W-001/WORK.yaml" for target in targets)
    after = {
        path: path.read_bytes()
        for path in sorted(process.rglob("*"))
        if path.is_file() and ".meta-flow-runtime" not in path.parts
    }
    assert after == before, "plan 阶段必须严格零写"

    plan_digest = result["payload"]["repair_plan"]["plan_digest"]
    target_refs = [target["ref"] for target in targets]
    authorization_path = tmp_path / "repair-authorization.json"
    authorization_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "SharedProjectionRepairAuthorizationV1",
                "authorization_id": "AUTH-CR078-REPAIR-W001-20260906-V1",
                "plan_digest": plan_digest,
                "target_refs": target_refs,
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    result = _run_cli(
        [
            "--project-root", str(release),
            "--apply",
            "--expected-plan-digest", plan_digest,
            "--authorization", str(authorization_path),
        ],
        capsys,
    )
    assert result["payload"]["decision"] == "PASS", result["payload"]

    assert inspect_work_close_transactions(process)["decision"] == "PASS"
    _transition(process, "W-001", "blocked", "active", "cr078-post-repair-resume")


def test_repair_cli_idempotent_rerun_is_zero_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release, process = _wedged_fixture(tmp_path)
    plan_result = _run_cli(["--project-root", str(release)], capsys)
    plan_digest = plan_result["payload"]["repair_plan"]["plan_digest"]
    authorization_path = tmp_path / "repair-authorization.json"
    authorization_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "SharedProjectionRepairAuthorizationV1",
                "authorization_id": "AUTH-CR078-REPAIR-REPLAY-20260906-V1",
                "plan_digest": plan_digest,
                "target_refs": [
                    target["ref"] for target in plan_result["payload"]["repair_plan"]["targets"]
                ],
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    applied = _run_cli(
        [
            "--project-root", str(release),
            "--apply",
            "--expected-plan-digest", plan_digest,
            "--authorization", str(authorization_path),
        ],
        capsys,
    )
    assert applied["payload"]["decision"] == "PASS"

    # 修复后：plan=COMMITTED_CURRENT exit 0；同授权重放被单次消费拒绝。
    fresh = _run_cli(["--project-root", str(release)], capsys)
    assert fresh["payload"]["classification"] == "COMMITTED_CURRENT"
    assert fresh["code"] == 0
    replay = _run_cli(
        [
            "--project-root", str(release),
            "--apply",
            "--expected-plan-digest", plan_digest,
            "--authorization", str(authorization_path),
        ],
        capsys,
    )
    assert replay["payload"]["decision"] == "BLOCKED"
    assert replay["code"] == 1
    successors = process / ".meta-flow-runtime/work-close/successors"
    assert len(list(successors.glob("shared-projection-repair-*.json"))) == 1


def test_repair_cli_superseded_on_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release, process = _wedged_fixture(tmp_path)
    plan_result = _run_cli(["--project-root", str(release)], capsys)
    plan_digest = plan_result["payload"]["repair_plan"]["plan_digest"]

    # mint 前再次漂移 WORK.yaml（新增外部写入）
    work_path = process / "works/W-001/WORK.yaml"
    work_path.write_bytes(work_path.read_bytes() + b"\n# external drift\n")

    result = _run_cli(
        ["--project-root", str(release), "--expected-plan-digest", plan_digest],
        capsys,
    )
    assert result["payload"]["classification"] == "SUPERSEDED"


def test_repair_cli_rejects_invalid_authorization(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release, process = _wedged_fixture(tmp_path)
    plan_result = _run_cli(["--project-root", str(release)], capsys)
    stale_digest = "0" * 64
    authorization_path = tmp_path / "bad-authorization.json"
    authorization_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "SharedProjectionRepairAuthorizationV1",
                "authorization_id": "AUTH-CR078-REPAIR-INVALID-20260906-V1",
                "plan_digest": stale_digest,
                "target_refs": [
                    target["ref"] for target in plan_result["payload"]["repair_plan"]["targets"]
                ],
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    result = _run_cli(
        [
            "--project-root", str(release),
            "--apply",
            "--expected-plan-digest", stale_digest,
            "--authorization", str(authorization_path),
        ],
        capsys,
    )
    assert result["payload"]["decision"] == "BLOCKED"
    assert result["code"] == 1
    assert inspect_work_close_transactions(process)["decision"] == "BLOCKED"
