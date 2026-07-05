from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow.workflow import story_evidence


def full_lld_text(story_id: str = "STORY-CR123-S01") -> str:
    sections = "\n".join(f"## {index}. Section\n\ncontent\n" for index in range(15))
    return f"""---
story_id: "{story_id}"
---

# {story_id} LLD

工程依据 目标 需求 模块拆分 代码结构 数据模型 API 流程 技术细节 安全 测试 实施 风险 DoD

{sections}
"""


class LLDStructureTests(unittest.TestCase):
    def test_full_lld_structure_passes_with_15_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "process" / "stories" / "STORY-CR123-S01-LLD.md"
            path.parent.mkdir(parents=True)
            path.write_text(full_lld_text(), encoding="utf-8")

            errors, warnings = story_evidence.validate_lld_structure(path, project_root=root)

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_full_lld_structure_fails_missing_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "process" / "stories" / "STORY-CR123-S01-LLD.md"
            path.parent.mkdir(parents=True)
            path.write_text(full_lld_text().replace("## 14. Section\n\ncontent\n", ""), encoding="utf-8")

            errors, _warnings = story_evidence.validate_lld_structure(path, project_root=root)

            self.assertIn("full-lld missing required section prefix: ## 14.", errors)

    def test_full_lld_structure_fails_missing_semantic_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "process" / "stories" / "STORY-CR123-S01-LLD.md"
            path.parent.mkdir(parents=True)
            path.write_text(full_lld_text().replace("模块拆分", ""), encoding="utf-8")

            errors, _warnings = story_evidence.validate_lld_structure(path, project_root=root)

            self.assertIn("full-lld missing required semantic token: 模块拆分", errors)

    def test_technical_note_requires_expected_evidence_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "process" / "stories" / "STORY-CR123-S02.md"
            path.parent.mkdir(parents=True)
            path.write_text(
                """# STORY-CR123-S02

## 技术说明

- 设计依据: existing process contract
- 文件影响: meta_flow/example.py
- 接口: CLI only
- 数据: none
- 权限: no runtime authorization
- 失败: fail closed
- 测试: unit fixture
- 风险: low
""",
                encoding="utf-8",
            )

            errors, warnings = story_evidence.validate_lld_structure(path, project_root=root)

            self.assertEqual([], errors)
            self.assertEqual([], warnings)

    def test_batch_lld_cli_reports_missing_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "process" / "stories" / "BATCH-CR123-LLD.md"
            path.parent.mkdir(parents=True)
            path.write_text(
                """# Batch LLD

## 0. Overview

### Story: STORY-CR123-S01

design_evidence_type: batch-lld
lld_policy_required_level: full-lld
batch_scope: adapter extension stories
homogeneous_story_pattern: same adapter contract
risk_level: low
shared_contract: common adapter interface
""",
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = story_evidence.main(["lld-check", "--project-root", str(root), "--lld", str(path)])

            self.assertEqual(1, exit_code)
            self.assertIn("batch-lld missing required section prefix: ## 9.", output.getvalue())

    def test_batch_lld_requires_homogeneous_low_risk_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "process" / "stories" / "BATCH-CR123-LLD.md"
            path.parent.mkdir(parents=True)
            sections = "\n".join(f"## {index}. Section\n\ncontent\n" for index in range(10))
            path.write_text(
                f"""# Batch LLD

{sections}

### Story: STORY-CR123-S01

design_evidence_type: batch-lld
lld_policy_required_level: technical-note
runtime-high-risk
""",
                encoding="utf-8",
            )

            errors, _warnings = story_evidence.validate_lld_structure(path, project_root=root)

            self.assertIn("batch-lld missing required batching token: batch_scope", errors)
            self.assertIn("batch-lld contains high-risk marker requiring full-lld review: runtime-high-risk", errors)

    def test_cp5_context_check_enforces_capsule_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "process" / "context" / "CP5-LLD-CONTEXT.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(
                """checkpoint: CP5
read_profile: compact
allowed_reads:
  - docs/design/HLD.md
""",
                encoding="utf-8",
            )

            errors, _warnings = story_evidence.validate_cp5_context_capsule(path, project_root=root)

            self.assertIn(
                "CP5 capsule-first violation: allowed_reads includes deny-default full doc without expansion reason: docs/design/HLD.md",
                errors,
            )

    def test_cp5_context_check_accepts_read_if_needed_full_docs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "process" / "context" / "CP5-LLD-CONTEXT.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(
                """checkpoint: CP5
read_profile: compact
allowed_reads:
  - process/context/CP5-LLD-CONTEXT.yaml
read_if_needed:
  - docs/design/HLD.md
do_not_read_by_default:
  - docs/design/HLD.md
  - docs/design/ARCHITECTURE-DECISION.md
  - docs/product/TEST-MATRIX.md
context_refs:
  - process/context/CP5-LLD-CONTEXT.yaml
""",
                encoding="utf-8",
            )

            errors, _warnings = story_evidence.validate_cp5_context_capsule(path, project_root=root)

            self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
