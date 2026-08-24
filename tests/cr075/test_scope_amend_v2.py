"""CR-075 S02：handoff-free additive scope amendment 强化（STORY-CR075-S02）。

覆盖：scope_version+1 单调、additive-only 断言、失效引擎交集分支
（INVALIDATED_BY_SCOPE_VERSION / NO_SCOPE_INTERSECTION）、apply 后置标记、
R1-2 重放（G1 create-only 恢复场景，无功能 HANDOFF）。
"""

from __future__ import annotations

import json
from pathlib import Path

from meta_flow.work import scope_amend
from meta_flow.work.model import G1ScopeDeltaV1, WorkScope
from meta_flow.work.scope_amend import plan_receipt_invalidation


def _scope(version: int = 1) -> WorkScope:
    return WorkScope(
        version,
        ("works/W/REQUEST.md",),
        ("meta_flow/alpha/**",),
        ("CHECK-1",),
    )


def test_scope_version_increments_monotonically() -> None:
    delta = G1ScopeDeltaV1.from_mapping(
        {
            "schema_version": 1,
            "add_reads": [],
            "add_writes": ["meta_flow/beta/**"],
            "add_checks": [],
            "reason": "test",
        }
    )
    result = scope_amend._result_g1_scope(_scope(version=3), delta)
    assert result.version == 4
    assert set(result.allowed_writes) == {"meta_flow/alpha/**", "meta_flow/beta/**"}


def test_additive_only_assertion_holds_for_union_semantics() -> None:
    delta = G1ScopeDeltaV1.from_mapping(
        {
            "schema_version": 1,
            "add_reads": ["docs/x.md"],
            "add_writes": [],
            "add_checks": ["CHECK-2"],
            "reason": "test",
        }
    )
    result = scope_amend._result_g1_scope(_scope(), delta)
    scope_amend._assert_additive_only(_scope(), result)  # 不抛即通过


def test_receipt_invalidation_no_intersection_retains(tmp_path: Path) -> None:
    work_id = "W"
    receipts = tmp_path / "works" / work_id / "validation-receipts"
    receipts.mkdir(parents=True)
    (receipts / "PASS-targeted.json").write_text(
        json.dumps({"paths": ["meta_flow/gamma/**"], "decision": "PASS"}), encoding="utf-8"
    )
    delta = G1ScopeDeltaV1.from_mapping(
        {
            "schema_version": 1,
            "add_reads": [],
            "add_writes": ["meta_flow/beta/**"],
            "add_checks": [],
            "reason": "test",
        }
    )

    entries = plan_receipt_invalidation(tmp_path, work_id, delta)

    assert len(entries) == 1
    assert entries[0]["decision"] == "retained"
    assert entries[0]["reason"] == "NO_SCOPE_INTERSECTION"


def test_receipt_invalidation_intersection_marks_invalidated(tmp_path: Path) -> None:
    work_id = "W"
    receipts = tmp_path / "works" / work_id / "validation-receipts"
    receipts.mkdir(parents=True)
    (receipts / "PASS-targeted.json").write_text(
        json.dumps(
            {
                "paths": ["meta_flow/alpha/one.py", "meta_flow/gamma/x.py"],
                "decision": "PASS",
            }
        ),
        encoding="utf-8",
    )
    delta = G1ScopeDeltaV1.from_mapping(
        {
            "schema_version": 1,
            "add_reads": [],
            "add_writes": ["meta_flow/alpha/**"],
            "add_checks": [],
            "reason": "test",
        }
    )

    entries = plan_receipt_invalidation(tmp_path, work_id, delta)

    assert entries[0]["decision"] == "invalidated"
    assert entries[0]["reason"] == "INVALIDATED_BY_SCOPE_VERSION"
    assert "meta_flow/alpha/**" in entries[0].get("intersected_paths", [])


def test_receipt_invalidation_empty_when_directory_absent(tmp_path: Path) -> None:
    delta = G1ScopeDeltaV1.from_mapping(
        {
            "schema_version": 1,
            "add_reads": ["a.md"],
            "add_writes": [],
            "add_checks": [],
            "reason": "test",
        }
    )
    assert plan_receipt_invalidation(tmp_path, "W", delta) == ()


def test_receipt_invalidation_unreadable_receipt_fails_invalid(tmp_path: Path) -> None:
    work_id = "W"
    receipts = tmp_path / "works" / work_id / "validation-receipts"
    receipts.mkdir(parents=True)
    (receipts / "broken.json").write_text("{ not json", encoding="utf-8")
    delta = G1ScopeDeltaV1.from_mapping(
        {
            "schema_version": 1,
            "add_reads": ["a.md"],
            "add_writes": [],
            "add_checks": [],
            "reason": "test",
        }
    )

    entries = plan_receipt_invalidation(tmp_path, work_id, delta)

    assert entries[0]["decision"] == "invalidated"
    assert entries[0]["reason"] == "INVALIDATED_BY_SCOPE_VERSION_RECEIPT_UNREADABLE"


def test_mark_invalidated_receipts_writes_scope_version(tmp_path: Path) -> None:
    work_id = "W"
    receipts = tmp_path / "works" / work_id / "validation-receipts"
    receipts.mkdir(parents=True)
    receipt_path = receipts / "PASS-targeted.json"
    receipt_path.write_text(
        json.dumps({"paths": ["meta_flow/alpha/one.py"], "decision": "PASS"}),
        encoding="utf-8",
    )
    delta = G1ScopeDeltaV1.from_mapping(
        {
            "schema_version": 1,
            "add_reads": [],
            "add_writes": ["meta_flow/alpha/**"],
            "add_checks": [],
            "reason": "test",
        }
    )

    class _Plan:
        process_root = tmp_path
        result_scope = _scope(version=2)
        receipt_invalidation = plan_receipt_invalidation(tmp_path, work_id, delta)

    marks = scope_amend._mark_invalidated_receipts(_Plan())

    invalidated = next(m for m in marks if m["decision"] == "invalidated")
    assert invalidated["mark_applied"] is True
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["invalidated_by_scope_version"] == 2
    assert payload["invalidation_reason"] == "INVALIDATED_BY_SCOPE_VERSION"


def test_r1_2_replay_g1_create_only_recovery_no_handoff(tmp_path: Path) -> None:
    """R1-2：G1 Work 经 additive 修订后无 HANDOFF 产物，receipt 按交集失效。"""

    work_id = "W"
    work_dir = tmp_path / "works" / work_id
    (work_dir / "validation-receipts").mkdir(parents=True)
    (work_dir / "validation-receipts" / "PASS-1.json").write_text(
        json.dumps({"paths": ["meta_flow/alpha/x.py"], "decision": "PASS"}),
        encoding="utf-8",
    )
    (work_dir / "validation-receipts" / "PASS-2.json").write_text(
        json.dumps({"paths": ["meta_flow/gamma/y.py"], "decision": "PASS"}),
        encoding="utf-8",
    )

    # create-only 恢复需要写整个 alpha 域（目录级新增），域内旧证据失效。
    delta = G1ScopeDeltaV1.from_mapping(
        {
            "schema_version": 1,
            "add_reads": [],
            "add_writes": ["meta_flow/alpha/**"],
            "add_checks": [],
            "reason": "r1-2 create-only recovery",
        }
    )
    entries = plan_receipt_invalidation(tmp_path, work_id, delta)
    decisions = {e["receipt_ref"].rsplit("/", 1)[1]: e["decision"] for e in entries}

    # 交集失效、无交集保留：R1-2 的 create-only 恢复只作废受影响证据。
    assert decisions["PASS-1.json"] == "invalidated"
    assert decisions["PASS-2.json"] == "retained"
    # G1 additive 路径不产生功能 HANDOFF 文件。
    assert not (work_dir / "HANDOFF.yaml").exists()
