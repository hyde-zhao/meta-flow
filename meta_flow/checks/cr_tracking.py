#!/usr/bin/env python3
"""校验 CR 跟踪台账、正式 CR 和 STATE.active_change 的一致性。"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from meta_flow.workspace.routing import require_process_health


FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
CR_ID_RE = re.compile(r"CR-\d+")
CANDIDATE_ID_RE = re.compile(r"(?:CR-\d+|FU-CR\d+-\d+|SP-CR\d+-\d+|RA-CR\d+-\d+)")
YAML_FENCE_RE = re.compile(r"```yaml\r?\n(.*?)\r?\n```", re.DOTALL)
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
ALLOWED_LIFECYCLE_STATUSES = {"candidate", "active", "blocked", "closed", "cancelled", "superseded"}
ALLOWED_READINESS_STATUSES = {"ready", "ready_with_risk", "not_ready", "n/a"}
ALLOWED_GATE_STATUSES = {
    "not_started",
    "cp2_pending",
    "cp3_pending",
    "cp5_pending",
    "cp7_pending",
    "cp8_pending",
    "implementation_in_progress",
    "verification_in_progress",
    "cp8_closed",
    "cp8_recovery_closed",
    "closed",
}
ALLOWED_CR_KINDS = {
    "requirement-change",
    "architecture-realignment",
    "implementation-gate",
    "runtime-authorization",
    "ledger-maintenance",
    "spike",
}
ALLOWED_GATE_PROFILES = {"full", "standard", "standard-code", "compact", "runtime", "spike"}
PATH_EMPTY_VALUES = {"", "-", "—", "n/a", "N/A", "无", "不适用"}


@dataclass
class FormalCR:
    cr_id: str
    status: str
    cr_kind: str
    lifecycle_status: str
    readiness_status: str
    gate_status: str
    gate_profile: str
    path: Path
    source: str
    parent_cr: str
    source_follow_up_id: str
    historical_baseline_status: str
    reframed_by: str


@dataclass
class FollowUpRow:
    item_id: str
    title: str
    status: str
    lifecycle_status: str
    readiness_status: str
    gate_status: str
    gate_profile: str
    kind: str
    formal_path: str
    relationship_text: str
    source_path: Path
    line_no: int
    source: str


@dataclass
class IndexItem:
    item_id: str
    title: str
    status: str
    lifecycle_status: str
    readiness_status: str
    gate_status: str
    gate_profile: str
    kind: str
    formal_path: str
    source_tracking: str
    blocked_by: list[str]
    candidate_id: str
    next_action: str
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
        "相关 active CR / blocked_by / superseded_by": "关联",
        "相关 active CR": "关联",
        "blocked_by": "关联",
        "superseded_by": "关联",
    }
    return aliases.get(header.strip().strip("`"), header.strip().strip("`"))


def is_separator_row(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def normalize_status(value: str) -> str:
    status = value.strip().strip("`").strip().strip('"').strip("'").lower()
    if not status:
        return ""
    if status.startswith("closed") or status in {"implemented", "approved"}:
        return "closed"
    if status.startswith("cancelled") or status == "deleted-by-user":
        return "cancelled"
    if status.startswith("blocked"):
        return "blocked"
    if status.startswith("active"):
        return "active"
    if status in {"spike-candidate", "spike candidate"}:
        return "spike_candidate"
    return status


def strip_scalar(value: str) -> str:
    raw = value.strip()
    if " #" in raw:
        raw = raw.split(" #", 1)[0].rstrip()
    return raw.strip().strip("`").strip().strip('"').strip("'")


def normalize_lifecycle_status(value: str, *, fallback_status: str = "") -> str:
    lifecycle = strip_scalar(value).lower().replace("-", "_")
    if lifecycle in ALLOWED_LIFECYCLE_STATUSES:
        return lifecycle
    status = normalize_status(fallback_status)
    if status in {"candidate", "spike_candidate"}:
        return "candidate"
    if status in {"open", "pending"}:
        return "active"
    if status in {"active", "blocked", "closed", "cancelled", "superseded"}:
        return status
    if status in {"converted-to-spike", "converted_to_spike"}:
        return "active"
    return lifecycle


def normalize_readiness_status(value: str) -> str:
    readiness = strip_scalar(value).lower().replace("-", "_")
    if readiness in {"na", "not_applicable", "not-applicable"}:
        return "n/a"
    return readiness


def normalize_gate_status(value: str, *, fallback_gate: str = "") -> str:
    gate = strip_scalar(value or fallback_gate).lower().replace("-", "_")
    if gate in {"not_started", "not_started", "未启动"}:
        return "not_started"
    if gate in {"not-started"}:
        return "not_started"
    return gate


def normalize_kind(value: str, *, fallback_status: str = "") -> str:
    kind = strip_scalar(value).lower()
    if kind in {"cr", "change", "follow-up", "follow_up"}:
        return "requirement-change"
    if kind in {"spike", "spike_candidate"} or normalize_status(fallback_status) == "spike_candidate":
        return "spike"
    return kind


def parse_inline_list(value: str) -> list[str]:
    raw = strip_scalar(value)
    if not raw or raw in {"[]", "{}"}:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1].strip()
    return [item.strip().strip('"').strip("'") for item in raw.split(",") if item.strip()]


def normalize_path(value: str) -> str:
    return value.strip().strip("`").strip()


def relation_text_from_cells(headers: list[str], cells: list[str]) -> str:
    relation_parts: list[str] = []
    for pos, header in enumerate(headers):
        if pos >= len(cells):
            continue
        header_text = header.strip()
        if (
            header_text == "关联"
            or "blocked_by" in header_text
            or "superseded_by" in header_text
            or ("相关" in header_text and "CR" in header_text)
        ):
            relation_parts.append(cells[pos].strip())
    return "; ".join(part for part in relation_parts if part)


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
            cr_kind=normalize_kind(fields.get("cr_kind", "")),
            lifecycle_status=normalize_lifecycle_status(
                fields.get("lifecycle_status", ""),
                fallback_status=fields.get("status", ""),
            ),
            readiness_status=normalize_readiness_status(fields.get("readiness_status", "")),
            gate_status=normalize_gate_status(fields.get("gate_status", "")),
            gate_profile=strip_scalar(fields.get("gate_profile", "")).lower(),
            path=path,
            source=fields.get("source", ""),
            parent_cr=fields.get("parent_cr", ""),
            source_follow_up_id=strip_scalar(fields.get("source_follow_up_id", "")),
            historical_baseline_status=strip_scalar(fields.get("historical_baseline_status", "")),
            reframed_by=strip_scalar(fields.get("reframed_by", "")),
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
            if CANDIDATE_ID_RE.fullmatch(item_id):
                status = normalize_status(cells[header_map["状态"]])
                kind = normalize_kind(cells[header_map.get("类型", -1)].strip() if "类型" in header_map else "", fallback_status=status)
                rows.append(
                    FollowUpRow(
                        item_id=item_id,
                        title=cells[header_map.get("标题", -1)].strip() if "标题" in header_map else "",
                        status=status,
                        lifecycle_status=normalize_lifecycle_status("", fallback_status=status),
                        readiness_status="n/a",
                        gate_status=normalize_gate_status(
                            cells[header_map.get("当前门控", -1)].strip() if "当前门控" in header_map else "",
                            fallback_gate="not_started",
                        ),
                        gate_profile="spike" if kind == "spike" else "",
                        kind=kind,
                        formal_path=normalize_path(cells[header_map.get("正式 CR 路径", -1)])
                        if "正式 CR 路径" in header_map
                        else "",
                        relationship_text=relation_text_from_cells(headers, cells),
                        source_path=path,
                        line_no=data_index + 1,
                        source="table",
                    )
                )
            data_index += 1
        index = data_index
    return rows


def parse_structured_follow_up_rows(path: Path) -> list[FollowUpRow]:
    text = read_text(path)
    rows: list[FollowUpRow] = []
    for fence in YAML_FENCE_RE.finditer(text):
        block = fence.group(1)
        if "follow_up_items:" not in block:
            continue
        block_start_line = text[: fence.start(1)].count("\n") + 1
        current: dict[str, str] | None = None
        current_line = block_start_line
        for offset, line in enumerate(block.splitlines(), 0):
            item_match = re.match(r"^\s*-\s+id:\s*(?P<value>.+?)\s*$", line)
            if item_match:
                if current:
                    rows.append(follow_up_row_from_mapping(current, path, current_line, source="yaml"))
                current = {"id": strip_scalar(item_match.group("value"))}
                current_line = block_start_line + offset
                continue
            if current is None:
                continue
            field_match = re.match(r"^\s{4}(?P<key>[A-Za-z0-9_]+):\s*(?P<value>.*?)\s*$", line)
            if field_match:
                current[field_match.group("key")] = field_match.group("value")
        if current:
            rows.append(follow_up_row_from_mapping(current, path, current_line, source="yaml"))
    return rows


def follow_up_row_from_mapping(mapping: dict[str, str], path: Path, line_no: int, *, source: str) -> FollowUpRow:
    status = normalize_status(mapping.get("status", ""))
    lifecycle_status = normalize_lifecycle_status(mapping.get("lifecycle_status", ""), fallback_status=status)
    kind = normalize_kind(mapping.get("kind", mapping.get("type", "")), fallback_status=status)
    if not status:
        status = "spike_candidate" if kind == "spike" and lifecycle_status == "candidate" else lifecycle_status
    return FollowUpRow(
        item_id=strip_scalar(mapping.get("id", "")),
        title=strip_scalar(mapping.get("title", "")),
        status=status,
        lifecycle_status=lifecycle_status,
        readiness_status=normalize_readiness_status(mapping.get("readiness_status", "")) or "n/a",
        gate_status=normalize_gate_status(mapping.get("gate_status", ""), fallback_gate="not_started"),
        gate_profile=strip_scalar(mapping.get("gate_profile", "")).lower(),
        kind=kind,
        formal_path=normalize_path(strip_scalar(mapping.get("formal_cr_path", ""))),
        relationship_text=strip_scalar(mapping.get("blocked_by", "")),
        source_path=path,
        line_no=line_no,
        source=source,
    )


def discover_follow_up_rows(project_root: Path, explicit_tracking: list[Path]) -> list[FollowUpRow]:
    if explicit_tracking:
        paths = [path if path.is_absolute() else project_root / path for path in explicit_tracking]
    else:
        paths = sorted((project_root / "process" / "changes").glob("CR-*-FOLLOW-UP-TRACKING-*.md"))
    rows: list[FollowUpRow] = []
    for path in paths:
        if path.is_file():
            rows.extend(parse_structured_follow_up_rows(path))
            rows.extend(parse_follow_up_rows(path))
    return rows


def parse_cr_index_items(index_path: Path) -> list[IndexItem]:
    if not index_path.is_file():
        return []
    items: list[IndexItem] = []
    lines = read_text(index_path).splitlines()
    in_items = False
    current: dict[str, str] | None = None
    current_line = 0
    for line_no, line in enumerate(lines, 1):
        if re.match(r"^items:\s*$", line):
            in_items = True
            continue
        if in_items and line and not line.startswith(" ") and not line.startswith("-"):
            break
        if not in_items:
            continue
        item_match = re.match(r"^\s*-\s+id:\s*(?P<value>.+?)\s*$", line)
        if item_match:
            if current:
                items.append(index_item_from_mapping(current, current_line))
            current = {"id": strip_scalar(item_match.group("value"))}
            current_line = line_no
            continue
        if current is None:
            continue
        field_match = re.match(r"^\s{4}(?P<key>[A-Za-z0-9_]+):\s*(?P<value>.*?)\s*$", line)
        if field_match:
            current[field_match.group("key")] = field_match.group("value")
    if current:
        items.append(index_item_from_mapping(current, current_line))
    return items


def parse_next_action_candidates(index_path: Path) -> list[tuple[str, int]]:
    if not index_path.is_file():
        return []
    refs: list[tuple[str, int]] = []
    in_queue = False
    for line_no, line in enumerate(read_text(index_path).splitlines(), 1):
        if re.match(r"^next_action_queue:\s*$", line):
            in_queue = True
            continue
        if in_queue and line and not line.startswith(" "):
            break
        if not in_queue:
            continue
        match = re.match(r"^\s{4}candidate_id:\s*(?P<value>.*?)\s*$", line)
        if match:
            refs.append((strip_scalar(match.group("value")), line_no))
    return refs


def index_item_from_mapping(mapping: dict[str, str], line_no: int) -> IndexItem:
    status = normalize_status(mapping.get("status", ""))
    lifecycle_status = normalize_lifecycle_status(mapping.get("lifecycle_status", ""), fallback_status=status)
    kind = normalize_kind(mapping.get("kind", mapping.get("type", "")), fallback_status=status)
    return IndexItem(
        item_id=strip_scalar(mapping.get("id", "")),
        title=strip_scalar(mapping.get("title", "")),
        status=status,
        lifecycle_status=lifecycle_status,
        readiness_status=normalize_readiness_status(mapping.get("readiness_status", "")) or "n/a",
        gate_status=normalize_gate_status(mapping.get("gate_status", ""), fallback_gate=mapping.get("next_gate", "")),
        gate_profile=strip_scalar(mapping.get("gate_profile", "")).lower(),
        kind=kind,
        formal_path=normalize_path(strip_scalar(mapping.get("formal_cr_path", ""))),
        source_tracking=normalize_path(strip_scalar(mapping.get("source_tracking", ""))),
        blocked_by=parse_inline_list(mapping.get("blocked_by", "")),
        candidate_id=strip_scalar(mapping.get("candidate_id", "")),
        next_action=strip_scalar(mapping.get("next_action", "")),
        line_no=line_no,
    )


def format_rel(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def formal_cr_for_follow_up_row(project_root: Path, formal_crs: dict[str, FormalCR], row: FollowUpRow) -> FormalCR | None:
    if row.formal_path in PATH_EMPTY_VALUES:
        return None
    resolved = resolve_project_path(project_root, row.formal_path).resolve()
    for formal in formal_crs.values():
        if formal.path.resolve() == resolved:
            return formal
    return None


def formal_row_points_to_cr(project_root: Path, row: FollowUpRow, formal: FormalCR) -> bool:
    if row.formal_path in PATH_EMPTY_VALUES:
        return False
    return resolve_project_path(project_root, row.formal_path).resolve() == formal.path.resolve()


def is_formal_active(formal: FormalCR) -> bool:
    return formal.status == "active" or formal.lifecycle_status == "active"


def is_formal_finished(formal: FormalCR) -> bool:
    return formal.status in FINISHED_FORMAL_STATUSES or formal.lifecycle_status in {"closed", "cancelled", "superseded"}


def collect_errors_and_warnings(
    project_root: Path,
    formal_crs: dict[str, FormalCR],
    rows: list[FollowUpRow],
    index_items: list[IndexItem],
    next_action_refs: list[tuple[str, int]],
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
        if ref.key != "active_change" and cr.status in FINISHED_FORMAL_STATUSES:
            continue
        if cr.status in FINISHED_FORMAL_STATUSES:
            errors.append(
                f"STATE line {ref.line_no} {ref.key} points to finished CR {ref.value} with status={cr.status}"
            )
        elif cr.status not in UNFINISHED_FORMAL_STATUSES:
            warnings.append(
                f"STATE line {ref.line_no} {ref.key} points to CR {ref.value} with non-standard status={cr.status or '<empty>'}"
            )
        if cr.lifecycle_status in {"closed", "cancelled", "superseded"}:
            errors.append(
                f"STATE line {ref.line_no} {ref.key} points to finished CR {ref.value} with lifecycle_status={cr.lifecycle_status}"
            )

    for cr in formal_crs.values():
        location = format_rel(project_root, cr.path)
        if cr.lifecycle_status and cr.lifecycle_status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(f"{location} invalid lifecycle_status for {cr.cr_id}: {cr.lifecycle_status}")
        if cr.readiness_status and cr.readiness_status not in ALLOWED_READINESS_STATUSES:
            errors.append(f"{location} invalid readiness_status for {cr.cr_id}: {cr.readiness_status}")
        if cr.gate_status and cr.gate_status not in ALLOWED_GATE_STATUSES:
            errors.append(f"{location} invalid gate_status for {cr.cr_id}: {cr.gate_status}")
        if cr.cr_kind and cr.cr_kind not in ALLOWED_CR_KINDS:
            errors.append(f"{location} invalid cr_kind for {cr.cr_id}: {cr.cr_kind}")
        if cr.gate_profile and cr.gate_profile not in ALLOWED_GATE_PROFILES:
            errors.append(f"{location} invalid gate_profile for {cr.cr_id}: {cr.gate_profile}")
        if cr.historical_baseline_status == "reframed" and not cr.reframed_by:
            warnings.append(f"{location} has historical_baseline_status=reframed but no reframed_by")

    top_refs = [ref for ref in state_refs if ref.key == "active_change" and ref.value]
    nested_refs = [
        ref
        for ref in state_refs
        if ref.key != "active_change"
        and ref.value
        and formal_crs.get(ref.value) is not None
        and formal_crs[ref.value].status not in FINISHED_FORMAL_STATUSES
    ]
    if top_refs and nested_refs:
        top_value = top_refs[0].value
        for ref in nested_refs:
            if ref.value != top_value:
                warnings.append(
                    f"STATE line {ref.line_no} nested active_change={ref.value} differs from top-level active_change={top_value}"
                )

    active_formal = [
        cr
        for cr in formal_crs.values()
        if cr.status == "active" or cr.lifecycle_status == "active"
    ]
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
        if not CANDIDATE_ID_RE.fullmatch(row.item_id):
            errors.append(f"{location} invalid follow-up id format: {row.item_id}")
        if row.status not in ALLOWED_FOLLOW_UP_STATUSES:
            errors.append(f"{location} invalid follow-up status for {row.item_id}: {row.status}")
        if row.lifecycle_status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(f"{location} invalid lifecycle_status for {row.item_id}: {row.lifecycle_status}")
        if row.readiness_status not in ALLOWED_READINESS_STATUSES:
            errors.append(f"{location} invalid readiness_status for {row.item_id}: {row.readiness_status}")
        if row.gate_status and row.gate_status not in ALLOWED_GATE_STATUSES:
            errors.append(f"{location} invalid gate_status for {row.item_id}: {row.gate_status}")
        if row.kind and row.kind not in ALLOWED_CR_KINDS:
            errors.append(f"{location} invalid kind for {row.item_id}: {row.kind}")
        if row.gate_profile and row.gate_profile not in ALLOWED_GATE_PROFILES:
            errors.append(f"{location} invalid gate_profile for {row.item_id}: {row.gate_profile}")
        formal_path_missing = row.formal_path in PATH_EMPTY_VALUES
        if row.lifecycle_status in {"active", "blocked", "closed"} and formal_path_missing:
            errors.append(f"{location} {row.item_id} status={row.status} requires 正式 CR 路径")
        if row.lifecycle_status == "candidate" and not formal_path_missing:
            warnings.append(f"{location} {row.item_id} is {row.status} but already has 正式 CR 路径={row.formal_path}")
        if not formal_path_missing:
            resolved = resolve_project_path(project_root, row.formal_path)
            if not resolved.is_file():
                errors.append(f"{location} {row.item_id} formal CR path does not exist: {row.formal_path}")

        formal = formal_crs.get(row.item_id)
        if formal is not None:
            if row.lifecycle_status == "candidate":
                errors.append(
                    f"{location} {row.item_id} is still {row.status} but formal CR file exists: "
                    f"{format_rel(project_root, formal.path)}"
                )
            if row.lifecycle_status == "active" and formal.status in FINISHED_FORMAL_STATUSES:
                errors.append(f"{location} {row.item_id} is active in tracking but formal status={formal.status}")
            if row.lifecycle_status == "closed" and formal.status not in FINISHED_FORMAL_STATUSES:
                errors.append(f"{location} {row.item_id} is closed in tracking but formal status={formal.status}")

        linked_formal = formal_cr_for_follow_up_row(project_root, formal_crs, row)
        if row.item_id.startswith("FU-") and not formal_path_missing and linked_formal is None:
            errors.append(f"{location} {row.item_id} formal CR path is not a discovered formal CR: {row.formal_path}")
        if row.item_id.startswith("FU-") and linked_formal is not None:
            if row.lifecycle_status == "active" and not is_formal_active(linked_formal):
                errors.append(
                    f"{location} {row.item_id} is active but linked formal CR {linked_formal.cr_id} "
                    f"is status={linked_formal.status or '<empty>'} lifecycle_status={linked_formal.lifecycle_status or '<empty>'}"
                )
            if row.lifecycle_status == "active" and f"related_active_cr={linked_formal.cr_id}" not in row.relationship_text:
                errors.append(
                    f"{location} {row.item_id} active follow-up row must include "
                    f"related_active_cr={linked_formal.cr_id}"
                )
            if row.lifecycle_status == "closed" and not is_formal_finished(linked_formal):
                errors.append(
                    f"{location} {row.item_id} is closed but linked formal CR {linked_formal.cr_id} "
                    f"is status={linked_formal.status or '<empty>'} lifecycle_status={linked_formal.lifecycle_status or '<empty>'}"
                )

    for cr in formal_crs.values():
        if cr.source != "cp8-follow-up":
            continue
        location = format_rel(project_root, cr.path)
        if cr.cr_id not in rows_by_id:
            warnings.append(f"{location} source=cp8-follow-up but no matching follow-up tracking row")
        if not cr.source_follow_up_id:
            continue
        source_rows = rows_by_id.get(cr.source_follow_up_id, [])
        if not source_rows:
            errors.append(f"{location} source_follow_up_id={cr.source_follow_up_id} has no matching follow-up row")
            continue
        linked_source_rows = [row for row in source_rows if formal_row_points_to_cr(project_root, row, cr)]
        if not linked_source_rows:
            errors.append(
                f"{location} source_follow_up_id={cr.source_follow_up_id} has no follow-up row pointing to this CR"
            )
            continue
        for row in linked_source_rows:
            row_location = f"{format_rel(project_root, row.source_path)}:{row.line_no}"
            if is_formal_active(cr):
                if row.lifecycle_status != "active":
                    errors.append(
                        f"{row_location} {row.item_id} must be active while source formal CR {cr.cr_id} is active"
                    )
                if f"related_active_cr={cr.cr_id}" not in row.relationship_text:
                    errors.append(
                        f"{row_location} {row.item_id} active source follow-up row must include "
                        f"related_active_cr={cr.cr_id}"
                    )
            if is_formal_finished(cr) and row.lifecycle_status != "closed":
                errors.append(
                    f"{row_location} {row.item_id} must be closed while source formal CR {cr.cr_id} is finished"
                )

    index_path = project_root / "process" / "changes" / "CR-INDEX.yaml"
    index_by_id = {item.item_id: item for item in index_items if item.item_id}
    if index_path.is_file():
        for cr in active_formal:
            if not any(item.item_id == cr.cr_id or item.formal_path == format_rel(project_root, cr.path) for item in index_items):
                warnings.append(f"CR-INDEX.yaml does not mention active formal CR {cr.cr_id}")

    for item in index_items:
        location = f"process/changes/CR-INDEX.yaml:{item.line_no}"
        if not CANDIDATE_ID_RE.fullmatch(item.item_id):
            errors.append(f"{location} invalid CR index item id format: {item.item_id}")
        if item.lifecycle_status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(f"{location} invalid lifecycle_status for {item.item_id}: {item.lifecycle_status}")
        if item.readiness_status not in ALLOWED_READINESS_STATUSES:
            errors.append(f"{location} invalid readiness_status for {item.item_id}: {item.readiness_status}")
        if item.gate_status and item.gate_status not in ALLOWED_GATE_STATUSES:
            errors.append(f"{location} invalid gate_status for {item.item_id}: {item.gate_status}")
        if item.kind and item.kind not in ALLOWED_CR_KINDS:
            errors.append(f"{location} invalid kind for {item.item_id}: {item.kind}")
        if item.gate_profile and item.gate_profile not in ALLOWED_GATE_PROFILES:
            errors.append(f"{location} invalid gate_profile for {item.item_id}: {item.gate_profile}")
        if item.status and item.lifecycle_status and normalize_lifecycle_status("", fallback_status=item.status) != item.lifecycle_status:
            warnings.append(
                f"{location} legacy status={item.status} disagrees with lifecycle_status={item.lifecycle_status}"
            )
        formal_path_missing = item.formal_path in PATH_EMPTY_VALUES
        if item.lifecycle_status in {"active", "blocked", "closed"} and formal_path_missing:
            errors.append(f"{location} {item.item_id} lifecycle_status={item.lifecycle_status} requires formal_cr_path")
        if item.lifecycle_status == "candidate" and not formal_path_missing:
            warnings.append(f"{location} {item.item_id} is candidate but already has formal_cr_path={item.formal_path}")
        if not formal_path_missing and not resolve_project_path(project_root, item.formal_path).is_file():
            errors.append(f"{location} {item.item_id} formal_cr_path does not exist: {item.formal_path}")
        for blocker in item.blocked_by:
            blocker_cr = formal_crs.get(blocker)
            if blocker_cr and (blocker_cr.status in FINISHED_FORMAL_STATUSES or blocker_cr.lifecycle_status == "closed"):
                warnings.append(f"{location} {item.item_id} blocked_by={blocker} points to closed CR")

    for item_id, row_group in rows_by_id.items():
        if item_id not in index_by_id:
            warnings.append(f"{format_rel(project_root, row_group[0].source_path)}:{row_group[0].line_no} {item_id} missing from CR-INDEX.yaml items")
            continue
        index_item = index_by_id[item_id]
        for row in row_group:
            if row.lifecycle_status != index_item.lifecycle_status:
                warnings.append(
                    f"{format_rel(project_root, row.source_path)}:{row.line_no} {item_id} lifecycle_status={row.lifecycle_status} "
                    f"differs from CR-INDEX lifecycle_status={index_item.lifecycle_status}"
                )

    for candidate_id, line_no in next_action_refs:
        if not candidate_id or candidate_id in PATH_EMPTY_VALUES or "000" in candidate_id:
            continue
        if candidate_id not in index_by_id:
            warnings.append(f"CR-INDEX.yaml:{line_no} next_action_queue candidate_id={candidate_id} is not in CR-INDEX.yaml items")

    return errors, warnings


def print_summary(formal_crs: dict[str, FormalCR], rows: list[FollowUpRow], index_items: list[IndexItem]) -> None:
    active = sorted(
        cr.cr_id for cr in formal_crs.values() if cr.status == "active" or cr.lifecycle_status == "active"
    )
    blocked = sorted(
        cr.cr_id for cr in formal_crs.values() if cr.status == "blocked" or cr.lifecycle_status == "blocked"
    )
    candidates = sorted({row.item_id for row in rows if row.lifecycle_status == "candidate" and row.kind != "spike"})
    spike_candidates = sorted({row.item_id for row in rows if row.lifecycle_status == "candidate" and row.kind == "spike"})
    indexed_candidates = sorted({item.item_id for item in index_items if item.lifecycle_status == "candidate"})
    print("CR tracking summary")
    print(f"- active formal CRs: {', '.join(active) if active else 'none'}")
    print(f"- blocked formal CRs: {', '.join(blocked) if blocked else 'none'}")
    print(f"- follow-up candidates: {', '.join(candidates) if candidates else 'none'}")
    print(f"- spike candidates: {', '.join(spike_candidates) if spike_candidates else 'none'}")
    print(f"- indexed candidates: {', '.join(indexed_candidates) if indexed_candidates else 'none'}")


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    require_process_health(project_root)
    state_path = project_root / "process" / "STATE.md"
    change_root = project_root / "process" / "changes"
    index_path = change_root / "CR-INDEX.yaml"
    formal_crs = discover_formal_crs(change_root)
    follow_up_rows = discover_follow_up_rows(project_root, args.tracking)
    index_items = parse_cr_index_items(index_path)
    next_action_refs = parse_next_action_candidates(index_path)
    state_refs = find_state_refs(state_path)
    errors, warnings = collect_errors_and_warnings(
        project_root=project_root,
        formal_crs=formal_crs,
        rows=follow_up_rows,
        index_items=index_items,
        next_action_refs=next_action_refs,
        state_refs=state_refs,
        allow_multiple_active=args.allow_multiple_active,
    )

    print_summary(formal_crs, follow_up_rows, index_items)
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
