#!/usr/bin/env python3
"""Validate human gate Decision Brief files and optional launch messages."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ALLOWED_DECISION_TYPES = {
    "scope",
    "architecture",
    "security",
    "implementation",
    "runtime_authorization",
    "risk_acceptance",
    "follow_up_tracking",
}

EMPTY_VALUES = {"", "-", "—", "n/a", "N/A", "无", "无备选", "不适用"}
OLD_CONFIRMATION_ALIASES = ("1/通过", "2/修改", "3/不通过", "确认通过", "需要修改", "确认不通过")
APPROVAL_SUMMARY_TOKENS = (
    "本次确认服务的整体目标",
    "推荐动作",
    "approve 后会发生什么",
    "approve 不授权什么",
    "不确认会阻塞什么",
)
DECISION_LAYER_TOKENS = ("必须用户决策", "高风险策略确认", "agent 默认处理", "仅审计记录")


@dataclass
class DecisionRow:
    line_no: int
    cells: dict[str, str]

    @property
    def decision_id(self) -> str:
        return self.cells.get("决策 ID", "")


def split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip().strip("`") for cell in stripped.split("|")]


def normalize_header(header: str) -> str:
    header = re.sub(r"\s+", " ", header.strip().strip("`"))
    aliases = {
        "问题": "待确认问题",
        "优劣摘要": "优劣分析",
        "影响/风险": "影响 / 风险",
        "影响 / 风险": "影响 / 风险",
        "回退/切换条件": "回退 / 切换条件",
        "回退 / 切换条件": "回退 / 切换条件",
    }
    return aliases.get(header, header)


def is_separator_row(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def find_decision_table(text: str) -> tuple[list[str], list[DecisionRow]]:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip().startswith("### 待人工决策清单"):
            start = index
            break
    if start is None:
        return [], []

    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.lstrip().startswith("#") and index > start + 1:
            break
        if line.strip().startswith("|") and "决策 ID" in line:
            raw_headers = split_table_row(line)
            headers = [normalize_header(header) for header in raw_headers]
            rows: list[DecisionRow] = []
            data_index = index + 1
            if data_index < len(lines) and is_separator_row(lines[data_index]):
                data_index += 1
            for row_index in range(data_index, len(lines)):
                row_line = lines[row_index]
                if not row_line.strip().startswith("|"):
                    break
                if is_separator_row(row_line):
                    continue
                cells = split_table_row(row_line)
                if len(cells) < len(headers):
                    cells.extend([""] * (len(headers) - len(cells)))
                row = {headers[pos]: cells[pos].strip() for pos in range(len(headers))}
                if row.get("决策 ID") and not row.get("决策 ID", "").startswith("<"):
                    rows.append(DecisionRow(line_no=row_index + 1, cells=row))
            return headers, rows
    return [], []


def has_zero_decision_reason(text: str) -> bool:
    return bool(re.search(r"待人工决策项[：:]\s*0", text)) and ("原因" in text or "无新增取舍" in text)


def is_empty(value: str) -> bool:
    return value.strip().strip("`") in EMPTY_VALUES


def collect_checkpoint_errors(path: Path, text: str, *, legacy: bool = False) -> tuple[list[str], list[DecisionRow]]:
    errors: list[str] = []
    if "## Decision Brief" not in text:
        errors.append("missing section: ## Decision Brief")
    if not legacy:
        if "### 审批者摘要" not in text:
            errors.append("missing section: ### 审批者摘要")
        else:
            approval_section = text.split("### 审批者摘要", 1)[1].split("### Context Capsule Summary", 1)[0]
            for token in APPROVAL_SUMMARY_TOKENS:
                if token not in approval_section:
                    errors.append(f"审批者摘要 missing token: {token}")
        if "### 决策分层" not in text:
            errors.append("missing section: ### 决策分层")
        else:
            layer_section = text.split("### 决策分层", 1)[1].split("### 待人工决策清单", 1)[0]
            for token in DECISION_LAYER_TOKENS:
                if token not in layer_section:
                    errors.append(f"决策分层 missing token: {token}")
    if "### Context Capsule Summary" not in text:
        errors.append("missing section: ### Context Capsule Summary")
    else:
        capsule_section = text.split("### Context Capsule Summary", 1)[1].split("### Decision Collection Coverage", 1)[0]
        for token in ("capsule", "read_profile", "默认读取策略", "全文档读取"):
            if token not in capsule_section:
                errors.append(f"Context Capsule Summary missing token: {token}")
    if "### Decision Collection Coverage" not in text:
        errors.append("missing section: ### Decision Collection Coverage")
    else:
        coverage_section = text.split("### Decision Collection Coverage", 1)[1].split("### 待人工决策清单", 1)[0]
        for token in ("| 来源", "扫描状态", "候选问题数", "纳入待决策数", "分类 / N/A 原因"):
            if token not in coverage_section:
                errors.append(f"Decision Collection Coverage missing token: {token}")
    if "待人工决策清单" not in text:
        errors.append("missing section: 待人工决策清单")

    headers, rows = find_decision_table(text)
    if not headers:
        if not has_zero_decision_reason(text):
            errors.append("missing decision table or explicit zero-decision reason")
        return errors, []

    required_headers = [
        "决策 ID",
        "决策类型",
        "待确认问题",
        "推荐方案",
        "备选方案",
        "优劣分析",
        "影响 / 风险",
        "回退 / 切换条件",
    ]
    for header in required_headers:
        if header not in headers:
            errors.append(f"decision table missing required column: {header}")

    if not rows and not has_zero_decision_reason(text):
        errors.append("decision table has no rows and no explicit zero-decision reason")

    for row in rows:
        row_id = row.decision_id
        for header in required_headers:
            value = row.cells.get(header, "")
            if is_empty(value):
                errors.append(f"line {row.line_no} {row_id}: missing required field {header}")
        decision_type = row.cells.get("决策类型", "").strip().strip("`")
        if decision_type and decision_type not in ALLOWED_DECISION_TYPES:
            errors.append(
                f"line {row.line_no} {row_id}: invalid decision_type {decision_type!r}; "
                f"allowed={sorted(ALLOWED_DECISION_TYPES)}"
            )
        alternatives = row.cells.get("备选方案", "")
        if "无备选" in alternatives or alternatives.strip() in {"无", "不适用"}:
            errors.append(f"line {row.line_no} {row_id}: alternatives must not be empty or '无备选'")

    if rows:
        if "用户需决策事项" not in text:
            errors.append("missing 用户需决策事项 summary")
        else:
            summary = text.split("用户需决策事项", 1)[1]
            for row in rows:
                if row.decision_id not in summary:
                    errors.append(f"用户需决策事项 does not reference decision id: {row.decision_id}")

    if "CP8" in path.name:
        required_cp8_tokens = ("CP8 后续跟踪分流表", "关闭范围", "不授权范围", "风险接受项", "后续 CR 候选项", "取消 / deferred")
        for token in required_cp8_tokens:
            if token not in text:
                errors.append(f"CP8 checkpoint missing follow-up split token: {token}")

    return errors, rows


def collect_launch_message_errors(path: Path, text: str, rows: list[DecisionRow], *, legacy: bool = False) -> list[str]:
    errors: list[str] = []
    checkpoint_ref = path.as_posix()
    if checkpoint_ref not in text and path.name not in text:
        errors.append("launch message missing checkpoint path")
    for token in ("自动预检结论", "Context Capsule", "决策收集覆盖", "本轮待人工决策项", "approve", "修改: <具体修改点>", "reject"):
        if token not in text:
            errors.append(f"launch message missing token: {token}")
    for alias in OLD_CONFIRMATION_ALIASES:
        if alias in text:
            errors.append(f"launch message must not show legacy confirmation alias: {alias}")
    if not legacy:
        for token in ("审批者摘要", *APPROVAL_SUMMARY_TOKENS, "决策分层", *DECISION_LAYER_TOKENS):
            if token not in text:
                errors.append(f"launch message missing approval-oriented token: {token}")

    count_match = re.search(r"本轮待人工决策项[：:]\s*(\d+)", text)
    if not count_match:
        errors.append("launch message missing numeric decision count")
        declared_count = None
    else:
        declared_count = int(count_match.group(1))
        if declared_count != len(rows):
            errors.append(f"launch message decision count {declared_count} != checkpoint decision rows {len(rows)}")

    if rows:
        has_full_table = "| 决策 ID" in text and "决策类型" in text and "推荐方案" in text and "备选方案" in text
        has_compact_summary = ("blocking" in text or "high-risk" in text or "高风险" in text or "阻断" in text) and (
            "完整表" in text or "完整待决策表" in text or checkpoint_ref in text or path.name in text
        )
        if not has_full_table and not has_compact_summary:
            errors.append("launch message with decisions must include a full decision table or compact blocking/high-risk summary with checkpoint path")
        if has_full_table:
            for token in ("优劣", "影响 / 风险"):
                if token not in text:
                    errors.append(f"launch message missing decision table token: {token}")
            for row in rows:
                if row.decision_id not in text:
                    errors.append(f"launch message missing decision id: {row.decision_id}")
    elif declared_count == 0 and not ("原因" in text or "无新增取舍" in text):
        errors.append("zero-decision launch message must include a reason")

    for token in ("如果你回复 approve", "不表示授权", "不授权项"):
        if token not in text:
            errors.append(f"launch message missing user-perspective authorization token: {token}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate human gate Decision Brief and launch message.")
    parser.add_argument("--checkpoint", required=True, type=Path, help="Path to process/checkpoints/CP*.md")
    parser.add_argument("--launch-message-file", type=Path, help="Optional file containing the message to send to the user")
    parser.add_argument(
        "--require-launch-message",
        action="store_true",
        help="Fail unless --launch-message-file is provided and validates. Use before opening a human gate.",
    )
    parser.add_argument("--legacy", action="store_true", help="Validate the pre-CR036 legacy human-gate protocol.")
    args = parser.parse_args(argv)

    if not args.checkpoint.is_file():
        print(f"ERROR: checkpoint file not found: {args.checkpoint}", file=sys.stderr)
        return 1
    checkpoint_text = args.checkpoint.read_text(encoding="utf-8")
    errors, rows = collect_checkpoint_errors(args.checkpoint, checkpoint_text, legacy=args.legacy)

    if args.require_launch_message and not args.launch_message_file:
        errors.append("--require-launch-message requires --launch-message-file")
    if args.launch_message_file:
        if not args.launch_message_file.is_file():
            errors.append(f"launch message file not found: {args.launch_message_file}")
        else:
            message_text = args.launch_message_file.read_text(encoding="utf-8")
            errors.extend(collect_launch_message_errors(args.checkpoint, message_text, rows, legacy=args.legacy))

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
