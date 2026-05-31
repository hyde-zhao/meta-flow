#!/usr/bin/env python3
"""校验 CR 跟踪台账、正式 CR 和 STATE.active_change 的一致性。"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
CR_ID_RE = re.compile(r"CR-\d+")
ALLOWED_FOLLOW_UP_STATUSES = {
    "candidate",
    "active",
    "blocked",
    "spike_candidate",
    "converted-to-spike",
    "closed",
    "cancelled",
    "superseded",
}
UNFINISHED_FORMAL_STATUSES = {"open", "active", "blocked", "pending"}
FINISHED_FORMAL_STATUSES = {"closed", "cancelled", "superseded", "implemented", "approved"}
PATH_EMPTY_VALUES = {"", "-", "—", "n/a", "N/A", "无", "不适用"}


@dataclass
class FormalCR:
    cr_id: str
    status: str
    path: Path
    source: str
    parent_cr: str


@dataclass
class FollowUpRow:
    item_id: str
    title: str
    status: str
    kind: str
    formal_path: str
    source_path: Path
    line_no: int


@dataclass
class StateRef:
    key: str
    value: str
    line_no: int


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip().strip("`") for cell in stripped.split("|")]


def normalize_header(header: str) -> str:
    aliases = {
        "候选 CR": "候选编号",
        "候选 CR / Spike": "候选编号",
        "候选CR": "候选编号",
        "编号": "候选编号",
        "名称": "标题",
        "CR 路径": "正式 CR 路径",
        "正式路径": "正式 CR 路径",
    }
    return aliases.get(header.strip().strip("`"), header.strip().strip("`"))


def is_separator_row(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def normalize_status(value: str) -> str:
    return value.strip().strip("`").strip()


def normalize_path(value: str) -> str:
    return value.strip().strip("`").strip()


def resolve_project_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root / path


def find_state_refs(state_path: Path) -> list[StateRef]:
    if not state_path.is_file():
        return []
    refs: list[StateRef] = []
    for line_no, line in enumerate(read_text(state_path).splitlines(), 1):
        match = re.match(r"^(?P<indent>\s*)active_change:\s*[\"']?(?P<value>[^\"'\n#]*)", line)
        if not match:
            continue
        key = "active_change" if not match.group("indent") else "nested.active_change"
        refs.append(StateRef(key=key, value=match.group("value").strip(), line_no=line_no))
    return refs


def discover_formal_crs(change_root: Path) -> dict[str, FormalCR]:
    crs: dict[str, FormalCR] = {}
    if not change_root.is_dir():
        return crs
    for path in sorted(change_root.glob("CR-*.md")):
        if "FOLLOW-UP" in path.name:
            continue
        text = read_text(path)
        fields = parse_frontmatter(text)
        cr_id = fields.get("cr_id") or (CR_ID_RE.search(path.name).group(0) if CR_ID_RE.search(path.name) else "")
        if not cr_id:
            continue
        crs[cr_id] = FormalCR(
            cr_id=cr_id,
            status=normalize_status(fields.get("status", "")),
            path=path,
            source=fields.get("source", ""),
            parent_cr=fields.get("parent_cr", ""),
        )
    return crs


def parse_follow_up_rows(path: Path) -> list[FollowUpRow]:
    rows: list[FollowUpRow] = []
    lines = read_text(path).splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip().startswith("|") or "状态" not in line:
            index += 1
            continue
        headers = [normalize_header(header) for header in split_table_row(line)]
        header_map = {header: pos for pos, header in enumerate(headers)}
        if "候选编号" not in header_map or "状态" not in header_map:
            index += 1
            continue
        data_index = index + 1
        if data_index < len(lines) and is_separator_row(lines[data_index]):
            data_index += 1
        while data_index < len(lines) and lines[data_index].strip().startswith("|"):
            row_line = lines[data_index]
            if is_separator_row(row_line):
                data_index += 1
                continue
            cells = split_table_row(row_line)
            if len(cells) < len(headers):
                cells.extend([""] * (len(headers) - len(cells)))
            item_id = cells[header_map["候选编号"]].strip()
            if CR_ID_RE.fullmatch(item_id):
                rows.append(
                    FollowUpRow(
                        item_id=item_id,
                        title=cells[header_map.get("标题", -1)].strip() if "标题" in header_map else "",
                        status=normalize_status(cells[header_map["状态"]]),
                        kind=cells[header_map.get("类型", -1)].strip() if "类型" in header_map else "",
                        formal_path=normalize_path(cells[header_map.get("正式 CR 路径", -1)])
                        if "正式 CR 路径" in header_map
                        else "",
                        source_path=path,
                        line_no=data_index + 1,
                    )
                )
            data_index += 1
        index = data_index
    return rows


def discover_follow_up_rows(project_root: Path, explicit_tracking: list[Path]) -> list[FollowUpRow]:
    if explicit_tracking:
        paths = [path if path.is_absolute() else project_root / path for path in explicit_tracking]
    else:
        paths = sorted((project_root / "process" / "changes").glob("CR-*-FOLLOW-UP-TRACKING-*.md"))
    rows: list[FollowUpRow] = []
    for path in paths:
        if path.is_file():
            rows.extend(parse_follow_up_rows(path))
    return rows


def format_rel(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def collect_errors_and_warnings(
    project_root: Path,
    formal_crs: dict[str, FormalCR],
    rows: list[FollowUpRow],
    state_refs: list[StateRef],
    allow_multiple_active: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for ref in state_refs:
        if not ref.value:
            continue
        cr = formal_crs.get(ref.value)
        if cr is None:
            errors.append(f"STATE line {ref.line_no} {ref.key} points to missing formal CR: {ref.value}")
            continue
        if cr.status in FINISHED_FORMAL_STATUSES:
            errors.append(
                f"STATE line {ref.line_no} {ref.key} points to finished CR {ref.value} with status={cr.status}"
            )
        elif cr.status not in UNFINISHED_FORMAL_STATUSES:
            warnings.append(
                f"STATE line {ref.line_no} {ref.key} points to CR {ref.value} with non-standard status={cr.status or '<empty>'}"
            )

    top_refs = [ref for ref in state_refs if ref.key == "active_change" and ref.value]
    nested_refs = [ref for ref in state_refs if ref.key != "active_change" and ref.value]
    if top_refs and nested_refs:
        top_value = top_refs[0].value
        for ref in nested_refs:
            if ref.value != top_value:
                warnings.append(
                    f"STATE line {ref.line_no} nested active_change={ref.value} differs from top-level active_change={top_value}"
                )

    active_formal = [cr for cr in formal_crs.values() if cr.status == "active"]
    if len(active_formal) > 1 and not allow_multiple_active:
        ids = ", ".join(sorted(cr.cr_id for cr in active_formal))
        errors.append(f"multiple active formal CRs without explicit parallel authorization: {ids}")

    if top_refs and active_formal:
        top_value = top_refs[0].value
        active_ids = {cr.cr_id for cr in active_formal}
        if top_value not in active_ids:
            errors.append(
                f"STATE active_change={top_value} does not match active formal CR(s): {', '.join(sorted(active_ids))}"
            )

    rows_by_id: dict[str, list[FollowUpRow]] = {}
    for row in rows:
        rows_by_id.setdefault(row.item_id, []).append(row)
        location = f"{format_rel(project_root, row.source_path)}:{row.line_no}"
        if row.status not in ALLOWED_FOLLOW_UP_STATUSES:
            errors.append(f"{location} invalid follow-up status for {row.item_id}: {row.status}")
        formal_path_missing = row.formal_path in PATH_EMPTY_VALUES
        if row.status in {"active", "blocked", "closed", "converted-to-spike"} and formal_path_missing:
            errors.append(f"{location} {row.item_id} status={row.status} requires 正式 CR 路径")
        if row.status in {"candidate", "spike_candidate"} and not formal_path_missing:
            warnings.append(f"{location} {row.item_id} is {row.status} but already has 正式 CR 路径={row.formal_path}")
        if not formal_path_missing:
            resolved = resolve_project_path(project_root, row.formal_path)
            if not resolved.is_file():
                errors.append(f"{location} {row.item_id} formal CR path does not exist: {row.formal_path}")

        formal = formal_crs.get(row.item_id)
        if formal is not None:
            if row.status in {"candidate", "spike_candidate"}:
                errors.append(
                    f"{location} {row.item_id} is still {row.status} but formal CR file exists: "
                    f"{format_rel(project_root, formal.path)}"
                )
            if row.status == "active" and formal.status in FINISHED_FORMAL_STATUSES:
                errors.append(f"{location} {row.item_id} is active in tracking but formal status={formal.status}")
            if row.status == "closed" and formal.status not in FINISHED_FORMAL_STATUSES:
                errors.append(f"{location} {row.item_id} is closed in tracking but formal status={formal.status}")

    for cr in formal_crs.values():
        if cr.source == "cp8-follow-up" and cr.cr_id not in rows_by_id:
            warnings.append(
                f"{format_rel(project_root, cr.path)} source=cp8-follow-up but no matching follow-up tracking row"
            )

    index_path = project_root / "process" / "changes" / "CR-INDEX.yaml"
    if index_path.is_file():
        index_text = read_text(index_path)
        for cr in active_formal:
            if cr.cr_id not in index_text:
                warnings.append(f"CR-INDEX.yaml does not mention active formal CR {cr.cr_id}")

    return errors, warnings


def print_summary(formal_crs: dict[str, FormalCR], rows: list[FollowUpRow]) -> None:
    active = sorted(cr.cr_id for cr in formal_crs.values() if cr.status == "active")
    blocked = sorted(cr.cr_id for cr in formal_crs.values() if cr.status == "blocked")
    candidates = sorted(row.item_id for row in rows if row.status == "candidate")
    spike_candidates = sorted(row.item_id for row in rows if row.status == "spike_candidate")
    print("CR tracking summary")
    print(f"- active formal CRs: {', '.join(active) if active else 'none'}")
    print(f"- blocked formal CRs: {', '.join(blocked) if blocked else 'none'}")
    print(f"- follow-up candidates: {', '.join(candidates) if candidates else 'none'}")
    print(f"- spike candidates: {', '.join(spike_candidates) if spike_candidates else 'none'}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate CR tracking consistency across STATE.active_change, formal CR files, "
            "follow-up tracking tables, and optional CR-INDEX.yaml."
        )
    )
    parser.add_argument("--project-root", type=Path, default=Path("."), help="Project root containing process/STATE.md")
    parser.add_argument(
        "--tracking",
        type=Path,
        action="append",
        default=[],
        help="Optional follow-up tracking file. Defaults to process/changes/CR-*-FOLLOW-UP-TRACKING-*.md",
    )
    parser.add_argument("--allow-multiple-active", action="store_true", help="Allow more than one formal CR with status=active")
    parser.add_argument("--strict-warnings", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    state_path = project_root / "process" / "STATE.md"
    change_root = project_root / "process" / "changes"
    formal_crs = discover_formal_crs(change_root)
    follow_up_rows = discover_follow_up_rows(project_root, args.tracking)
    state_refs = find_state_refs(state_path)
    errors, warnings = collect_errors_and_warnings(
        project_root=project_root,
        formal_crs=formal_crs,
        rows=follow_up_rows,
        state_refs=state_refs,
        allow_multiple_active=args.allow_multiple_active,
    )

    print_summary(formal_crs, follow_up_rows)
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if errors or (warnings and args.strict_warnings):
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
