"""STORY-CR076-S02 Feature B targeted 测试：bootstrap 归一化 scope（MF-BUG-18）。

SPR-01：apply 后既有台账行 bytes 零变化（字段级 diff 全等）；
多 CR 顺序 bootstrap 时间戳保持。SPR-N06：台账含其他 CR 既有行。
权威 = cr076-state-projection-recovery TEST-PLAN v1.1 + LLD FB2。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from meta_flow.execution_control.exact_file_transaction import ExactFileAuthorizationV1
from meta_flow.state import current
from meta_flow.workflow import cr_cli, cr_index

LEDGER_REF = "state/CR-LEDGER.ndjson"
EFFECTIVE_AT_1 = "2030-01-01T00:00:00+00:00"
EFFECTIVE_AT_2 = "2031-02-02T00:00:00+00:00"


def _initialize_current(root: Path) -> None:
    """最小 process fixture（对齐 tests/test_cr_index.py 同名 helper）。"""
    process = root / "process"
    process.mkdir(parents=True, exist_ok=True)
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: target-project\n"
        "repo_role: process\n"
        "route_mode: relative-symlink\n",
        encoding="utf-8",
    )
    current.write_current_state(
        root, current.default_current_state(root, project_id="target-project")
    )


def _bootstrap_apply(root: Path, cr_id: str, effective_at: str) -> None:
    """preview → 授权 → apply（复用 test_cr_index.py 既有 CLI 模式）。"""
    plan = cr_index.plan_bootstrap_cr(
        root, cr_id=cr_id, title=f"bootstrap-{cr_id}", scope="scope",
        effective_at=effective_at,
    )
    authorization = ExactFileAuthorizationV1(
        f"bootstrap-{cr_id.lower()}-apply",
        plan.exact_plan.operation,
        plan.plan_digest,
        plan.target_refs,
        (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )
    authorization_file = root / f"bootstrap-authorization-{cr_id}.json"
    authorization_file.write_text(
        json.dumps(authorization.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert (
        cr_cli.main(
            [
                "bootstrap", "--id", cr_id, "--title", f"bootstrap-{cr_id}", "--scope", "scope",
                "--effective-at", effective_at, "--project-root", str(root),
                "--apply", "--authorization-file", str(authorization_file),
            ]
        )
        == 0
    )


def _ledger_rows(root: Path) -> dict[str, list[str]]:
    """CR id → 该 CR 的原始行 bytes（保留原样，不做 JSON 往返）。"""
    ledger = root / "process" / LEDGER_REF
    grouped: dict[str, list[str]] = {}
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if line.strip():
            grouped.setdefault(json.loads(line).get("id", "?"), []).append(line)
    return grouped


def test_spr_01_n06_existing_rows_bytes_unchanged(tmp_path: Path) -> None:
    _initialize_current(tmp_path)
    _bootstrap_apply(tmp_path, "CR-001", EFFECTIVE_AT_1)
    rows_after_first = _ledger_rows(tmp_path)
    assert "CR-001" in rows_after_first  # 前置：第一轮已写入

    # 第二轮 bootstrap（CR-002）：ledger 已含 CR-001 既有行
    _bootstrap_apply(tmp_path, "CR-002", EFFECTIVE_AT_2)
    rows_after_second = _ledger_rows(tmp_path)

    # SPR-N06 字段级 diff 全等：既有 CR-001 行 bytes 零变化
    assert rows_after_second["CR-001"] == rows_after_first["CR-001"]
    # 多 CR 顺序 bootstrap 时间戳保持（bytes 全等 ⇒ 时间戳未被第二轮重戳）
    created = [json.loads(line).get("created_at") for line in rows_after_second["CR-001"]]
    assert created and all(value == EFFECTIVE_AT_1 for value in created)


def test_spr_01_new_rows_still_normalized(tmp_path: Path) -> None:
    _initialize_current(tmp_path)
    _bootstrap_apply(tmp_path, "CR-001", EFFECTIVE_AT_1)
    _bootstrap_apply(tmp_path, "CR-002", EFFECTIVE_AT_2)

    rows = _ledger_rows(tmp_path)
    # 归一化对当前 CR 新增行仍然生效（staging wall clock 收敛为 effective_at）
    assert "CR-002" in rows
    created = [json.loads(line).get("created_at") for line in rows["CR-002"]]
    assert created and all(value == EFFECTIVE_AT_2 for value in created)
