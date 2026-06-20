from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow import ask_user
from meta_flow.checks.human_gate import collect_launch_message_errors, collect_checkpoint_errors


CHECKPOINT_TEXT = """# CP3 HLD Review

## Decision Brief

### Context Capsule Summary

- capsule: `process/context/CP3-HLD-CONTEXT.yaml`
- read_profile: compact
- 默认读取策略: capsule-first
- 全文档读取: only if capsule is missing or conflicted

### Decision Collection Coverage

| 来源 | 扫描状态 | 候选问题数 | 纳入待决策数 | 分类 / N/A 原因 |
|---|---|---:|---:|---|
| HLD | scanned | 1 | 1 | architecture decision |

### 待人工决策清单

| 决策 ID | 决策类型 | 待确认问题 | 推荐方案 | 备选方案 | 优劣分析 | 影响 / 风险 | 回退 / 切换条件 |
|---|---|---|---|---|---|---|---|
| DQ-001 | architecture | 是否采用 compact next prompt | 采用 exact prompt | 保持现状 | 推荐方案减少歧义；备选方案改动小但 token 不稳定 | 影响 CLI 与规则文档 | 若用户要求自由文本则切换 |

用户需决策事项: DQ-001
"""


class AskUserTests(unittest.TestCase):
    def test_generated_human_gate_message_passes_existing_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "CP3-HLD-REVIEW.md"
            checkpoint.write_text(CHECKPOINT_TEXT, encoding="utf-8")
            checkpoint_errors, rows = collect_checkpoint_errors(checkpoint, CHECKPOINT_TEXT)
            self.assertEqual([], checkpoint_errors)

            message = ask_user.render_human_gate_message(checkpoint, rows)
            self.assertEqual([], collect_launch_message_errors(checkpoint, message, rows))
            self.assertIn("approve", message)
            self.assertIn("修改: <具体修改点>", message)
            self.assertIn("reject", message)
            self.assertNotIn("同意", message)
            self.assertNotIn("继续推进", message)

    def test_codex_json_payload_contains_request_user_input_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "CP3-HLD-REVIEW.md"
            checkpoint.write_text(CHECKPOINT_TEXT, encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                exit_code = ask_user.main(["human-gate", "--checkpoint", str(checkpoint), "--format", "codex-json"])

            self.assertEqual(0, exit_code)
            payload = json.loads(output.getvalue())
            self.assertEqual("request_user_input", payload["tool"])
            self.assertEqual(["approve", "修改: <具体修改点>", "reject"], payload["exact_text_fallback"])
            question = payload["questions"][0]
            self.assertEqual("human_gate_decision", question["id"])
            self.assertIn("approve (Recommended)", [option["label"] for option in question["options"]])


if __name__ == "__main__":
    unittest.main()
