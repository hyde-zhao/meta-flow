"""Codex/文本人工提问消息生成器。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from meta_flow.checks.human_gate import (
    DecisionRow,
    HumanGateRefV1,
    collect_checkpoint_errors,
    collect_launch_message_errors,
    resolve_human_gate_ref,
)
from meta_flow.project.process_route import ProcessRouteError

PUBLIC_OPERATION_DECLARATIONS = (
    ("human-gate.ask-user", ("meta-flow", "ask-user", "human-gate")),
)


def _clean_cell(value: str) -> str:
    return " ".join(value.replace("|", "/").split())


def _gate_id(checkpoint_ref: str | Path) -> str:
    return Path(checkpoint_ref).stem


def _render_decision_table(rows: list[DecisionRow]) -> str:
    if not rows:
        return "本轮待人工决策项: 0。原因: checkpoint 未列出新增人工取舍；仍需确认自动预检和不授权边界。"

    lines = [
        "| 决策 ID | 决策类型 | 待确认问题 | 推荐方案 | 备选方案 | 优劣摘要 | 影响 / 风险 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        cells = row.cells
        lines.append(
            "| "
            + " | ".join(
                _clean_cell(cells.get(header, ""))
                for header in (
                    "决策 ID",
                    "决策类型",
                    "待确认问题",
                    "推荐方案",
                    "备选方案",
                    "优劣分析",
                    "影响 / 风险",
                )
            )
            + " |"
        )
    return "\n".join(lines)


def render_human_gate_message(
    checkpoint_ref: str | Path,
    rows: list[DecisionRow],
) -> str:
    """生成可通过 human-gate 校验的人工门禁发起消息。"""

    canonical_ref = Path(checkpoint_ref).as_posix()
    gate = _gate_id(canonical_ref)
    decision_count = len(rows)
    table_or_reason = _render_decision_table(rows)
    decision_ids = ", ".join(row.decision_id for row in rows) if rows else "-"
    return f"""请审查人工门禁 `{gate}`。

checklist 路径: `{canonical_ref}`
自动预检结论: 已生成 Decision Brief；发起前请以 `meta-flow check human-gate --checkpoint {canonical_ref}` 的结果为准。

审批者摘要:
- 本次确认服务的整体目标: 请见 checkpoint `### 审批者摘要`；本消息只承载发起确认所需摘要。
- 推荐动作: 默认推荐 approve，除非你要求调整范围、风险、授权边界或推荐方案。
- approve 后会发生什么: 接受本轮 Decision Brief 中列出的推荐方案，并允许进入 checkpoint 声明的下一阶段。
- approve 不授权什么: 不授权真实运行、凭据读取、安全边界变更、外部接口调用、数据写入、publish、live / 交易类操作。
- 不确认会阻塞什么: 当前 checkpoint 后续推进会保持等待，直到你回复 approve / 修改 / reject。

Context Capsule: 请见 checkpoint 的 `### Context Capsule Summary`，其中包含 capsule、read_profile、默认读取策略和全文档读取边界。
决策收集覆盖: 请见 checkpoint 的 `### Decision Collection Coverage`，本消息只承载发起确认所需摘要。
决策分层:
- 必须用户决策: {decision_count}
- 高风险策略确认: 以 checkpoint `### 决策分层` 为准。
- agent 默认处理: 低风险、可逆、局部实现细节默认不进入用户主确认表，完整清单以 checkpoint 为准。
- 仅审计记录: 已按项目规则处理且无需用户拍板的事项只保留审计摘要。
本轮待人工决策项: {decision_count}
blocking / high-risk 决策摘要: {decision_ids if rows else "无；完整表见 checkpoint。"}

{table_or_reason}

如果你回复 approve，表示你接受以上 {decision_count} 项推荐方案，不表示授权以下不授权项。
不授权项: 不授权真实运行、凭据读取、安全边界变更、外部接口调用、数据写入、publish、live / 交易类操作；若 checkpoint 中列有额外不授权项，以 checkpoint 为准。

请只回复以下三个 exact 选项之一：
- approve
- 修改: <具体修改点>
- reject
"""


def build_codex_request_payload(
    checkpoint_ref: str | Path,
    rows: list[DecisionRow],
) -> dict[str, object]:
    """生成可映射到 Codex `request_user_input` 的结构化负载。"""

    gate = _gate_id(checkpoint_ref)
    message = render_human_gate_message(checkpoint_ref, rows)
    return {
        "tool": "request_user_input",
        "usage": "当当前 Codex 工具面提供 request_user_input 时，Host Orchestrator 使用该负载发起结构化人工确认；否则发送 fallback_message exact-text。",
        "questions": [
            {
                "id": "human_gate_decision",
                "header": "人工门禁",
                "question": f"请确认 {gate} 的人工门禁结果。默认推荐 approve；如需修改，请选择修改并填写具体修改点。",
                "options": [
                    {
                        "label": "approve (Recommended)",
                        "description": "接受本轮 Decision Brief 中列出的推荐方案，但不授权不授权项。",
                    },
                    {
                        "label": "修改",
                        "description": "要求重发门禁；必须填写具体修改点。",
                    },
                    {
                        "label": "reject",
                        "description": "拒绝本轮门禁结论并阻断推进。",
                    },
                ],
            }
        ],
        "exact_text_fallback": ["approve", "修改: <具体修改点>", "reject"],
        "fallback_message": message,
    }


def _load_checkpoint(
    checkpoint: HumanGateRefV1,
    *,
    legacy: bool,
) -> tuple[str, list[DecisionRow], list[str]]:
    text = checkpoint.resolved_path.read_text(encoding="utf-8")
    errors, rows = collect_checkpoint_errors(
        checkpoint.resolved_path,
        text,
        legacy=legacy,
    )
    return text, rows, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="meta-flow ask-user",
        description="Generate exact user prompts for Meta Flow human questions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    human_gate = subparsers.add_parser(
        "human-gate",
        help="Generate a Codex/text AskUserQuestion equivalent from a CP2/CP3/CP5/CP8 checkpoint.",
    )
    human_gate.add_argument("--project-root", type=Path, default=Path.cwd())
    human_gate.add_argument("--checkpoint", required=True, help="Canonical process/checkpoints/CP*.md logical ref")
    human_gate.add_argument("--launch-message-file", help="Validate and emit a canonical process/... launch message")
    human_gate.add_argument(
        "--replay",
        action="store_true",
        help="Regenerate the launch message from checkpoint content instead of requiring a persisted launch-message file.",
    )
    human_gate.add_argument("--format", choices=("markdown", "codex-json"), default="markdown")
    human_gate.add_argument("--output", help="Write generated output to a canonical process/... logical ref")
    human_gate.add_argument(
        "--check-output",
        action="store_true",
        help="After writing --output, run launch-message validation against the generated content.",
    )
    human_gate.add_argument(
        "--legacy",
        action="store_true",
        help="Use explicit physical paths for the pre-vNext legacy protocol.",
    )

    args = parser.parse_args(argv)
    if args.command != "human-gate":
        parser.error(f"unknown command: {args.command}")

    try:
        checkpoint = resolve_human_gate_ref(
            args.project_root,
            args.checkpoint,
            legacy=args.legacy,
            require_file=True,
        )
        output_ref = (
            resolve_human_gate_ref(
                args.project_root,
                args.output,
                legacy=args.legacy,
                require_file=False,
            )
            if args.output
            else None
        )
    except ProcessRouteError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2

    _, rows, errors = _load_checkpoint(checkpoint, legacy=args.legacy)
    message = ""
    if args.launch_message_file and args.replay:
        errors.append("--replay cannot be combined with --launch-message-file")
    elif args.launch_message_file:
        try:
            launch_message = resolve_human_gate_ref(
                args.project_root,
                args.launch_message_file,
                legacy=args.legacy,
                require_file=True,
            )
        except ProcessRouteError as exc:
            print(json.dumps(exc.as_dict(), ensure_ascii=False, sort_keys=True), file=sys.stderr)
            return 2
        message = launch_message.resolved_path.read_text(encoding="utf-8")
        errors.extend(
            collect_launch_message_errors(
                checkpoint.logical_ref,
                message,
                rows,
                legacy=args.legacy,
            )
        )

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if args.format == "codex-json":
        output = (
            json.dumps(
                build_codex_request_payload(checkpoint.logical_ref, rows),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    else:
        if not message:
            message = render_human_gate_message(checkpoint.logical_ref, rows)
            launch_errors = collect_launch_message_errors(
                checkpoint.logical_ref,
                message,
                rows,
                legacy=args.legacy,
            )
            if launch_errors:
                for error in launch_errors:
                    print(f"ERROR: generated launch message invalid: {error}", file=sys.stderr)
                return 1
        output = message.rstrip() + "\n"

    if output_ref is not None:
        output_ref.resolved_path.parent.mkdir(parents=True, exist_ok=True)
        output_ref.resolved_path.write_text(output, encoding="utf-8")
        if args.check_output:
            launch_errors = collect_launch_message_errors(
                checkpoint.logical_ref,
                output,
                rows,
                legacy=args.legacy,
            )
            if launch_errors:
                for error in launch_errors:
                    print(f"ERROR: generated output invalid: {error}", file=sys.stderr)
                return 1
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
