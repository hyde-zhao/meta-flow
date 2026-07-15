from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow import ask_user
from meta_flow.checks import human_gate
from meta_flow.checks.human_gate import collect_checkpoint_errors, collect_launch_message_errors

CHECKPOINT_TEXT = """# CP3 HLD Review

## Decision Brief

### 审批者摘要

| 字段 | 内容 |
|---|---|
| 本次确认服务的整体目标 | 验证新人工门禁消息可直接说明目标 |
| 推荐动作 | approve |
| approve 后会发生什么 | 进入下一阶段 |
| approve 不授权什么 | 不授权真实运行、凭据、publish 或 production write |
| 不确认会阻塞什么 | 阻塞 CP3 后续推进 |

### Context Capsule Summary

- capsule: `process/context/CP3-HLD-CONTEXT.yaml`
- read_profile: compact
- 默认读取策略: capsule-first
- 全文档读取: only if capsule is missing or conflicted

### Decision Collection Coverage

| 来源 | 扫描状态 | 候选问题数 | 纳入待决策数 | 分类 / N/A 原因 |
|---|---|---:|---:|---|
| HLD | scanned | 1 | 1 | architecture decision |

### 决策分层

| 分类 | 数量 | 处理方式 |
|---|---:|---|
| 必须用户决策 | 1 | 展示到待人工决策清单 |
| 高风险策略确认 | 0 | 本轮无 |
| agent 默认处理 | 0 | 本轮无 |
| 仅审计记录 | 0 | 本轮无 |

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

    def test_human_gate_replay_regenerates_without_persisted_launch_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "CP3-HLD-REVIEW.md"
            checkpoint.write_text(CHECKPOINT_TEXT, encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                exit_code = ask_user.main(["human-gate", "--checkpoint", str(checkpoint), "--replay"])

            self.assertEqual(0, exit_code)
            self.assertIn("请审查人工门禁", output.getvalue())
            self.assertFalse((Path(directory) / "CP3-LAUNCH-MESSAGE.md").exists())

    def test_human_gate_replay_rejects_persisted_launch_file_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "CP3-HLD-REVIEW.md"
            launch = Path(directory) / "CP3-LAUNCH-MESSAGE.md"
            checkpoint.write_text(CHECKPOINT_TEXT, encoding="utf-8")
            launch.write_text("legacy launch", encoding="utf-8")

            exit_code = ask_user.main(
                [
                    "human-gate",
                    "--checkpoint",
                    str(checkpoint),
                    "--launch-message-file",
                    str(launch),
                    "--replay",
                ]
            )

            self.assertEqual(1, exit_code)

    def test_human_gate_check_can_require_launch_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "CP3-HLD-REVIEW.md"
            checkpoint.write_text(CHECKPOINT_TEXT, encoding="utf-8")

            exit_code = human_gate.main(["--checkpoint", str(checkpoint), "--require-launch-message"])

            self.assertEqual(1, exit_code)

    def test_ask_user_output_can_self_check_generated_launch_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "CP3-HLD-REVIEW.md"
            output = Path(directory) / "CP3-LAUNCH-MESSAGE.md"
            checkpoint.write_text(CHECKPOINT_TEXT, encoding="utf-8")

            exit_code = ask_user.main(
                ["human-gate", "--checkpoint", str(checkpoint), "--output", str(output), "--check-output"]
            )

            self.assertEqual(0, exit_code)
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
