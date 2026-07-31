from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _missing_tokens(content: str, required_tokens: tuple[str, ...]) -> list[str]:
    return [token for token in required_tokens if token not in content]


def test_slim_rules_freeze_long_term_governance_lookup() -> None:
    content = _read("delivery/rules/AGENTS.md")
    required_tokens = (
        "长期治理查询与阶段规划",
        "process/PROJECT.yaml",
        "roadmap_ref",
        "process/ROADMAP.yaml",
        "全部 declared phase_refs",
        "有界例外",
        "禁止 sibling discovery",
        "机器事实 / 解释或推断 / 建议",
        "重叠矩阵",
        "memory 仅作线索",
    )

    assert _missing_tokens(content, required_tokens) == []


def test_state_router_has_repository_first_long_term_query_protocol() -> None:
    content = _read("delivery/skills/state-router/SKILL.md")
    required_tokens = (
        "长期治理 / 阶段目标查询",
        "阶段目标、长期路线、Roadmap",
        "process/PROJECT.yaml",
        "唯一 `roadmap_ref`",
        "全部 declared `phase_refs`",
        "禁止 sibling discovery",
        "active Phase 的详细路线",
        "机器事实",
        "解释/推断",
        "重叠矩阵",
        "memory 与仓库冲突时采用仓库机器事实",
        "此查询是只读操作",
    )

    assert _missing_tokens(content, required_tokens) == []


def test_phase_designer_requires_phase_overlap_adjudication() -> None:
    content = _read("delivery/skills/phase-designer/SKILL.md")
    required_tokens = (
        "PROJECT → roadmap_ref → 全部 declared phase_refs",
        "Phase 重叠矩阵",
        "生命周期结果",
        "进入条件",
        "退出条件",
        "非目标",
        "复用现有 Phase",
        "禁止 sibling discovery",
        "机器事实",
        "解释/推断",
        "规划建议",
        "project memory 只作线索",
    )

    assert _missing_tokens(content, required_tokens) == []


def test_missing_token_helper_detects_contract_regression() -> None:
    content = _read("delivery/rules/AGENTS.md").replace("重叠矩阵", "")

    assert _missing_tokens(content, ("重叠矩阵",)) == ["重叠矩阵"]
