"""R2 机器检查：CR-076 Work 对象记账一致性（评审 NEEDS_REWORK 返修复核）。

断言四组事实（真实 process 仓，定位口径 = tests/cr076/conftest.py）：
1. WA/WB 两个 Work 的 WORK.yaml 存在、YAML 可解析、work_id 正确；
2. DEVELOPMENT-PLAN.yaml 中 STORY-CR076-S01..S05 的 work_id 绑定 = WA/WA/WB/WB/WB；
3. 五份 CP6 return packet 的 work_id 与 2 一致，且幽灵 Work
   WORK-CR076-DISTRIBUTION-PUBLICATION-001 在 packet 中零出现；
4. GATE-LEDGER.ndjson 行数 >= 290（append-only 不回退下限）。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

# tests/cr076 → tests → release 仓根 → 上级；真实 process 仓 = 同级 meta-flow-process
PROCESS_ROOT = Path(__file__).resolve().parents[2].parent / "meta-flow-process"

WORK_IDS = ("CR-076-WA-PUBLICATION-POLICY", "CR-076-WB-CONSUMER-DISTRIBUTION")
STORY_WORK_BINDING = {
    "STORY-CR076-S01": "CR-076-WA-PUBLICATION-POLICY",
    "STORY-CR076-S02": "CR-076-WA-PUBLICATION-POLICY",
    "STORY-CR076-S03": "CR-076-WB-CONSUMER-DISTRIBUTION",
    "STORY-CR076-S04": "CR-076-WB-CONSUMER-DISTRIBUTION",
    "STORY-CR076-S05": "CR-076-WB-CONSUMER-DISTRIBUTION",
}
GHOST_WORK_ID = "WORK-CR076-DISTRIBUTION-PUBLICATION-001"
GATE_LEDGER_MIN_LINES = 290


def test_work_yaml_objects_exist_and_parse():
    for work_id in WORK_IDS:
        path = PROCESS_ROOT / "works" / work_id / "WORK.yaml"
        assert path.is_file(), f"WORK.yaml missing: {path}"
        document = yaml.safe_load(path.read_bytes())
        assert isinstance(document, dict), f"WORK.yaml not a mapping: {path}"
        assert document.get("work_id") == work_id


def test_development_plan_story_work_bindings():
    path = PROCESS_ROOT / "DEVELOPMENT-PLAN.yaml"
    assert path.is_file(), f"DEVELOPMENT-PLAN.yaml missing: {path}"
    document = yaml.safe_load(path.read_bytes())
    pairs: list[tuple[str, str]] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            story_id = node.get("story_id")
            if isinstance(story_id, str) and story_id in STORY_WORK_BINDING:
                pairs.append((story_id, str(node.get("work_id") or "")))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    assert len(pairs) == 5, f"expected exactly 5 CR-076 story bindings, got: {pairs}"
    assert dict(pairs) == STORY_WORK_BINDING


def test_return_packets_match_work_binding_and_no_ghost_work():
    for story_id, work_id in STORY_WORK_BINDING.items():
        path = PROCESS_ROOT / "returns" / f"{story_id}.CP6.return.json"
        assert path.is_file(), f"return packet missing: {path}"
        document = json.loads(path.read_bytes())
        assert document.get("work_id") == work_id, f"{story_id} work_id mismatch"
        text = path.read_text(encoding="utf-8")
        assert GHOST_WORK_ID not in text, f"ghost work id leaked into {path}"


def test_gate_ledger_append_only_floor():
    path = PROCESS_ROOT / "state" / "GATE-LEDGER.ndjson"
    assert path.is_file(), f"GATE-LEDGER.ndjson missing: {path}"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= GATE_LEDGER_MIN_LINES, f"gate ledger regressed: {len(lines)} lines"
