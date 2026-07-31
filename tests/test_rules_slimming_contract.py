"""S01 的 Rules 瘦身证据与失败不替换守护测试。"""

from __future__ import annotations

import json
from pathlib import Path

from meta_flow.project.onboarding_contract import canonical_digest, path_digest

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "delivery/rules/AGENTS.md"
INVENTORY = ROOT / "delivery/doc/RULES-SEMANTIC-INVENTORY.json"
EQUIVALENCE = ROOT / "delivery/doc/RULES-EQUIVALENCE.json"


def _load(path: Path) -> dict[str, object]:
    assert path.is_file(), f"missing evidence: {path.relative_to(ROOT)}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _range_size(value: object) -> int:
    assert isinstance(value, list) and len(value) == 2
    start, end = value
    assert isinstance(start, int) and isinstance(end, int) and start <= end
    return end - start + 1


def test_inventory_covers_each_baseline_line_once_and_has_exact_schema() -> None:
    inventory = _load(INVENTORY)
    assert inventory["record_schema"] == ["line_no", "class", "dimension", "normative_level", "precondition", "action", "failure_action", "canonical_ref", "canonical_exists", "equivalence_id"]
    coverage = inventory["coverage"]
    assert isinstance(coverage, dict)
    assert coverage == {"first_line": 1, "last_line": 347, "classified_count": 347, "unclassified_count": 0, "duplicate_line_count": 0}
    categories = inventory["categories"]
    assert isinstance(categories, list) and sum(_range_size(item["lines"]) for item in categories if isinstance(item, dict)) == 347
    assert {item["dimension"] for item in categories if isinstance(item, dict)} == {"process-routing", "safety-preflight", "authorization", "workflow-gates", "story-execution", "platform-path", "detail-contract", "duplicate-prose"}


def test_equivalence_is_one_to_one_across_eight_dimensions() -> None:
    evidence = _load(EQUIVALENCE)
    coverage = evidence["coverage"]
    assert isinstance(coverage, dict)
    assert coverage == {"old_line_count": 347, "mapped_line_count": 347, "unmapped_line_count": 0, "ambiguous_line_count": 0, "not_equivalent_count": 0}
    mappings = evidence["mappings"]
    assert isinstance(mappings, list) and len(mappings) == 8
    assert sum(_range_size(item["old_lines"]) for item in mappings if isinstance(item, dict)) == 347
    rules = RULES.read_text(encoding="utf-8")
    for item in mappings:
        assert isinstance(item, dict)
        assert item["failure_action"] == "BLOCKED"
        ref = str(item["canonical_ref"])
        if ref.startswith("#"):
            assert ref in rules
        else:
            assert (ROOT / ref).is_file()


def test_mandatory_preflight_negative_cases_are_detectable() -> None:
    rules = RULES.read_text(encoding="utf-8")
    required = ("确认返回类型", "先确认目标存在", "先读取当前原文或 native 结构化对象", "合法枚举与 transition graph", "禁止手工改派生状态")
    for token in required:
        assert token in rules
        assert token not in rules.replace(token, "")


def test_render_is_stable_and_recommended_thresholds_pass() -> None:
    first = RULES.read_bytes()
    second = RULES.read_bytes()
    assert first == second
    assert path_digest(RULES) == path_digest(RULES)
    assert len(first.splitlines()) <= 180
    assert len(first) <= 24576
    render = _load(EQUIVALENCE)["render"]
    assert isinstance(render, dict) and render["dynamic_fields_in_managed_bytes"] is False


def test_failed_equivalence_or_threshold_keeps_preimage_unchanged(tmp_path: Path) -> None:
    candidate = tmp_path / "AGENTS.md"
    preimage = RULES.read_bytes()
    candidate.write_bytes(preimage)
    failed = {"inventory_complete": True, "equivalence_pass": False, "threshold_pass": True, "two_render_digest_match": True}
    assert not all(failed.values())
    assert candidate.read_bytes() == preimage
    assert canonical_digest(failed) != canonical_digest({**failed, "equivalence_pass": True})
