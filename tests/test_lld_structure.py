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
""",
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = story_evidence.main(["lld-check", "--project-root", str(root), "--lld", str(path)])

            self.assertEqual(1, exit_code)
            self.assertIn("batch-lld missing required section prefix: ## 9.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
