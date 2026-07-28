from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from meta_flow import ask_user
from meta_flow.checks import human_gate
from meta_flow.checks.human_gate import collect_checkpoint_errors, collect_launch_message_errors

CONSOLE = Path(sys.executable).with_name("meta-flow")
LOGICAL_CHECKPOINT_REF = "process/checkpoints/CP3-HLD-REVIEW.md"

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


def init_paired_binding(root: Path) -> tuple[Path, Path]:
    release = root / "meta-flow"
    process = root / "meta-flow-process"
    release.mkdir()
    process.mkdir()
    for repository in (release, process):
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    binding = release / ".meta-flow" / "workspace.yaml"
    binding.parent.mkdir()
    binding.write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture-project\n"
        "repo_role: release\n"
        "route_mode: sibling-binding\n"
        "process_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow-process\n",
        encoding="utf-8",
    )
    (process / ".meta-flow-process.yaml").write_text(
        "schema_version: 1\n"
        "layout_version: independent-process-repo-v1\n"
        "workflow_model: vnext\n"
        "project_id: fixture-project\n"
        "repo_role: process\n"
        "route_mode: sibling-binding\n"
        "release_repo:\n"
        "  anchor: workspace_parent\n"
        "  relative_path: meta-flow\n",
        encoding="utf-8",
    )
    (process / "PROJECT.yaml").write_text(
        "schema_version: 1\n"
        "project_id: fixture-project\n"
        "name: Fixture Project\n"
        "status: active\n",
        encoding="utf-8",
    )
    checkpoint = process / "checkpoints" / "CP3-HLD-REVIEW.md"
    checkpoint.parent.mkdir()
    checkpoint.write_text(CHECKPOINT_TEXT, encoding="utf-8")
    return release, process


class AskUserTests(unittest.TestCase):
    def test_generated_human_gate_message_passes_existing_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "CP3-HLD-REVIEW.md"
            checkpoint.write_text(CHECKPOINT_TEXT, encoding="utf-8")
            checkpoint_errors, rows = collect_checkpoint_errors(checkpoint, CHECKPOINT_TEXT)
            self.assertEqual([], checkpoint_errors)

            message = ask_user.render_human_gate_message(LOGICAL_CHECKPOINT_REF, rows)
            self.assertEqual(
                [],
                collect_launch_message_errors(LOGICAL_CHECKPOINT_REF, message, rows),
            )
            self.assertIn(LOGICAL_CHECKPOINT_REF, message)
            self.assertNotIn(str(Path(directory).resolve()), message)
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
                exit_code = ask_user.main(
                    [
                        "human-gate",
                        "--checkpoint",
                        str(checkpoint),
                        "--format",
                        "codex-json",
                        "--legacy",
                    ]
                )

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
                exit_code = ask_user.main(
                    [
                        "human-gate",
                        "--checkpoint",
                        str(checkpoint),
                        "--replay",
                        "--legacy",
                    ]
                )

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
                    "--legacy",
                ]
            )

            self.assertEqual(1, exit_code)

    def test_human_gate_check_can_require_launch_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "CP3-HLD-REVIEW.md"
            checkpoint.write_text(CHECKPOINT_TEXT, encoding="utf-8")

            exit_code = human_gate.main(
                [
                    "--checkpoint",
                    str(checkpoint),
                    "--require-launch-message",
                    "--legacy",
                ]
            )

            self.assertEqual(1, exit_code)

    def test_ask_user_output_can_self_check_generated_launch_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "CP3-HLD-REVIEW.md"
            output = Path(directory) / "CP3-LAUNCH-MESSAGE.md"
            checkpoint.write_text(CHECKPOINT_TEXT, encoding="utf-8")

            exit_code = ask_user.main(
                [
                    "human-gate",
                    "--checkpoint",
                    str(checkpoint),
                    "--output",
                    str(output),
                    "--check-output",
                    "--legacy",
                ]
            )

            self.assertEqual(0, exit_code)
            self.assertTrue(output.is_file())

    def test_paired_binding_public_entries_round_trip_without_absolute_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            launch_ref = "process/checkpoints/CP3-LAUNCH-MESSAGE.md"
            launch = process / "checkpoints" / "CP3-LAUNCH-MESSAGE.md"

            generated = subprocess.run(
                [
                    str(CONSOLE),
                    "ask-user",
                    "human-gate",
                    "--project-root",
                    str(release),
                    "--checkpoint",
                    LOGICAL_CHECKPOINT_REF,
                    "--output",
                    launch_ref,
                    "--check-output",
                ],
                cwd=release,
                check=False,
                capture_output=True,
                text=True,
            )
            validated = subprocess.run(
                [
                    str(CONSOLE),
                    "check",
                    "human-gate",
                    "--project-root",
                    str(release),
                    "--checkpoint",
                    LOGICAL_CHECKPOINT_REF,
                    "--launch-message-file",
                    launch_ref,
                    "--require-launch-message",
                ],
                cwd=release,
                check=False,
                capture_output=True,
                text=True,
            )
            codex = subprocess.run(
                [
                    str(CONSOLE),
                    "ask-user",
                    "human-gate",
                    "--project-root",
                    str(release),
                    "--checkpoint",
                    LOGICAL_CHECKPOINT_REF,
                    "--replay",
                    "--format",
                    "codex-json",
                ],
                cwd=release,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, generated.returncode, generated.stderr)
            self.assertEqual(0, validated.returncode, validated.stderr)
            self.assertEqual("OK", validated.stdout.strip())
            self.assertEqual(0, codex.returncode, codex.stderr)
            self.assertFalse((release / "process").exists())
            self.assertTrue(launch.is_file())
            launch_text = launch.read_text(encoding="utf-8")
            self.assertIn(LOGICAL_CHECKPOINT_REF, launch_text)
            self.assertNotIn(str(process.resolve()), launch_text)
            self.assertNotIn(str(process.resolve()), codex.stdout)
            self.assertIn(
                LOGICAL_CHECKPOINT_REF,
                json.loads(codex.stdout)["fallback_message"],
            )

    def test_vnext_invalid_refs_and_missing_binding_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, process = init_paired_binding(Path(directory))
            output = process / "checkpoints" / "MUST-NOT-EXIST.md"
            invalid_refs = [
                str(process / "checkpoints" / "CP3-HLD-REVIEW.md"),
                "process/../outside.md",
                "process/checkpoints/MISSING.md",
            ]
            for invalid_ref in invalid_refs:
                completed = subprocess.run(
                    [
                        str(CONSOLE),
                        "ask-user",
                        "human-gate",
                        "--project-root",
                        str(release),
                        "--checkpoint",
                        invalid_ref,
                        "--output",
                        "process/checkpoints/MUST-NOT-EXIST.md",
                    ],
                    cwd=release,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(2, completed.returncode, completed.stderr)
                self.assertFalse(output.exists())
                self.assertNotIn(str(process.resolve()), completed.stdout)
                self.assertNotIn(str(process.resolve()), completed.stderr)

            (release / ".meta-flow" / "workspace.yaml").unlink()
            missing_binding = subprocess.run(
                [
                    str(CONSOLE),
                    "check",
                    "human-gate",
                    "--project-root",
                    str(release),
                    "--checkpoint",
                    LOGICAL_CHECKPOINT_REF,
                ],
                cwd=release,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(2, missing_binding.returncode)
            self.assertNotIn(str(process.resolve()), missing_binding.stdout)
            self.assertNotIn(str(process.resolve()), missing_binding.stderr)


if __name__ == "__main__":
    unittest.main()
