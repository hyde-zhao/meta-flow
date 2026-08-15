#!/usr/bin/env python3
"""校验 CR 跟踪台账、正式 CR 和 STATE.active_change 的一致性。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_flow.policies import gate_profiles
from meta_flow.project.process_route import (
    ProcessRouteError,
    _resolve_runtime_path,
    _resolve_runtime_ref,
    format_runtime_ref,
    require_process_route,
)
from meta_flow.semantics.cr_status import (
    NATIVE_GATE_STATUSES as ALLOWED_GATE_STATUSES,
)
from meta_flow.semantics.cr_status import (
    NATIVE_LIFECYCLE_STATUSES as ALLOWED_LIFECYCLE_STATUSES,
)
from meta_flow.semantics.cr_status import (
    NATIVE_READINESS_STATUSES as ALLOWED_READINESS_STATUSES,
)
from meta_flow.semantics.cr_status import (
    normalize_gate_status,
    normalize_lifecycle_status,
    normalize_readiness_status,
    validate_native_status_tuple,
)
from meta_flow.semantics.cr_status import (
    validate_native_transition as validate_native_transition,
)
from meta_flow.state import checkpoint_projection as canonical_checkpoint_projection
from meta_flow.state import current, event_ledger

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
ALLOWED_CR_KINDS = {
    "requirement-change",
    "architecture-realignment",
    "implementation-gate",
    "runtime-authorization",
    "ledger-maintenance",
    "spike",
}
LEGACY_GATE_PROFILES = {"full", "standard", "compact", "runtime", "spike"}
ALLOWED_GATE_PROFILES = (
    set(gate_profiles.default_gate_profiles().get("profiles", {})) | LEGACY_GATE_PROFILES
)
PATH_EMPTY_VALUES = {"", "-", "—", "n/a", "N/A", "无", "不适用"}
LEGACY_CR_INDEX_RELS = (
    Path("process/changes/CR-INDEX.yaml"),
    Path("process/changes/CR-INDEX.yml"),
)
PROTECTED_LEDGER_RELS = (
    Path("process/state/CR-LEDGER.ndjson"),
    Path("process/state/STORY-LEDGER.ndjson"),
    Path("process/state/CHECKPOINT-LEDGER.ndjson"),
    Path("process/state/HANDOFF-LEDGER.ndjson"),
    Path("process/state/AGENT-DISPATCH-LEDGER.ndjson"),
    Path("process/state/GATE-LEDGER.ndjson"),
    Path("process/state/RUN-LEDGER.ndjson"),
    Path("process/state/READ-EXPANSION-LEDGER.ndjson"),
)


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
    native: bool = False


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


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_project_file(project_root: Path, rel_path: str) -> Path:
    root = project_root.resolve()
    relative = Path(rel_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:2] == ("process", "quant-lab")
    ):
        raise ValueError(f"protected object escapes project boundary: {rel_path}")
    path = _resolve_runtime_path(root, rel_path).resolve(strict=True)
    process_root = _resolve_runtime_ref(root, "process/PROJECT.yaml").parent
    within_allowed_root = path.is_relative_to(root) or (
        relative.parts[:1] == ("process",) and path.is_relative_to(process_root)
    )
    if not within_allowed_root or not path.is_file():
        raise ValueError(f"protected object escapes project root or is not a file: {rel_path}")
    return path


def _ledger_event_identity(event: dict[str, Any]) -> str:
    return str(event.get("event_id") or event.get("dispatch_id") or "")


def _ledger_event_belongs_to_cr(event: dict[str, Any], cr_id: str) -> bool:
    for key in ("cr_id", "change_id", "id", "active_change"):
        if str(event.get(key) or "") == cr_id:
            return True
    identity = _ledger_event_identity(event)
    compact_id = cr_id.replace("-", "")
    return cr_id in identity or compact_id in identity


def _ledger_cr_event_payload(path: Path, cr_id: str) -> tuple[bytes, list[str]]:
    selected_lines: list[str] = []
    event_ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not _ledger_event_belongs_to_cr(event, cr_id):
            continue
        selected_lines.append(line)
        event_ids.append(_ledger_event_identity(event))
    payload = ("\n".join(selected_lines) + ("\n" if selected_lines else "")).encode("utf-8")
    return payload, event_ids


def _ledger_event_id_payload(path: Path, expected_ids: list[str]) -> tuple[bytes, list[str]]:
    """Select an already-manifested event set by exact object identity."""

    expected = set(expected_ids)
    selected_lines: list[str] = []
    event_ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        identity = _ledger_event_identity(event)
        if identity not in expected:
            continue
        selected_lines.append(line)
        event_ids.append(identity)
    payload = ("\n".join(selected_lines) + ("\n" if selected_lines else "")).encode("utf-8")
    return payload, event_ids


def build_protected_object_manifest(
    project_root: Path, *, cr_id: str, story_id: str
) -> dict[str, Any]:
    """Build an object-identity manifest for a closed CR's original evidence."""

    root = project_root.resolve()
    compact_id = cr_id.replace("-", "")
    candidate_refs: set[str] = {
        f"process/changes/{cr_id}.md",
        f"process/changes/summaries/{cr_id}.summary.json",
        f"process/archive/{cr_id}/evidence-index.json",
    }
    checks_root = _resolve_runtime_ref(root, "process/checks")
    if checks_root.is_dir():
        candidate_refs.update(
            format_runtime_ref(root, path)
            for path in checks_root.glob("*.result.json")
            if compact_id in path.name or cr_id in path.name
        )
    stories_root = _resolve_runtime_ref(root, "process/stories")
    if stories_root.is_dir():
        candidate_refs.update(
            format_runtime_ref(root, path)
            for path in stories_root.glob("STORY-ST-EI-*-IMPLEMENTATION.md")
        )
    evidence_root = _resolve_runtime_ref(root, "process/evidence")
    if evidence_root.is_dir():
        candidate_refs.update(
            format_runtime_ref(root, path)
            for path in evidence_root.glob("ST-EI-*.index.json")
        )

    objects: list[dict[str, Any]] = []
    for logical_ref in sorted(candidate_refs):
        path = _safe_project_file(root, logical_ref)
        objects.append(
            {
                "path": logical_ref,
                "object_type": "protected_file",
                "original_sha256": _sha256_bytes(path.read_bytes()),
                "immutable": True,
                "allowed_operation": "read|reference",
                "identity_source_ref": f"closed-cr:{cr_id}",
            }
        )
    for rel_path in PROTECTED_LEDGER_RELS:
        path = _resolve_runtime_path(root, rel_path)
        if not path.is_file():
            continue
        payload, event_ids = _ledger_cr_event_payload(path, cr_id)
        if not event_ids:
            continue
        objects.append(
            {
                "path": rel_path.as_posix(),
                "object_type": "ledger_cr_event_set",
                "identity_selector": {"cr_id": cr_id, "event_ids": event_ids},
                "selected_event_count": len(event_ids),
                "original_sha256": _sha256_bytes(payload),
                "immutable": True,
                "allowed_operation": "read|reference|append-unrelated",
                "identity_source_ref": f"closed-cr-ledger-events:{cr_id}",
            }
        )
    return {
        "schema_version": 1,
        "cr_id": cr_id,
        "story_id": story_id,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "identity_mode": "object-identity",
        "path_prefix_only_identification": False,
        "source_index_refs": [
            f"process/archive/{cr_id}/evidence-index.json",
            f"process/changes/summaries/{cr_id}.summary.json",
        ],
        "objects": sorted(objects, key=lambda item: (item["path"], item["object_type"])),
    }


def verify_protected_object_manifest(project_root: Path, manifest: dict[str, Any]) -> list[str]:
    """Return object-level findings; an empty list means byte identity holds."""

    root = project_root.resolve()
    cr_id = str(manifest.get("cr_id") or "")
    findings: list[str] = []
    if (
        manifest.get("identity_mode") != "object-identity"
        or manifest.get("path_prefix_only_identification") is not False
    ):
        findings.append(
            "manifest must use object identity and prohibit path-prefix-only identification"
        )
    for item in manifest.get("objects") or []:
        if not isinstance(item, dict):
            findings.append("manifest object is not a mapping")
            continue
        rel_path = str(item.get("path") or "")
        try:
            path = _safe_project_file(root, rel_path)
        except (OSError, ValueError) as exc:
            findings.append(str(exc))
            continue
        if item.get("object_type") == "ledger_cr_event_set":
            expected_ids = (item.get("identity_selector") or {}).get("event_ids") or []
            if expected_ids and all(expected_ids):
                payload, event_ids = _ledger_event_id_payload(path, expected_ids)
            else:
                payload, event_ids = _ledger_cr_event_payload(path, cr_id)
            observed = _sha256_bytes(payload)
            if event_ids != expected_ids:
                findings.append(f"protected ledger event identity changed: {rel_path}")
        else:
            observed = _sha256_bytes(path.read_bytes())
        if observed != item.get("original_sha256"):
            findings.append(f"protected original hash changed: {rel_path}")
    return findings


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


def normalize_kind(value: str, *, fallback_status: str = "") -> str:
    kind = strip_scalar(value).lower()
    if kind in {"cr", "change", "follow-up", "follow_up"}:
        return "requirement-change"
    if (
        kind in {"spike", "spike_candidate"}
        or normalize_status(fallback_status) == "spike_candidate"
    ):
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
    return _resolve_runtime_path(project_root, path)


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


def find_state_v2_refs(state_path: Path) -> list[StateRef]:
    """Read the canonical active change from State v2.

    ``STATE.md`` is a rendered human view and is only used as a legacy
    fallback when the v2 object is absent.
    """

    if not state_path.is_file():
        return []
    try:
        payload = json.loads(read_text(state_path))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    value = payload.get("active_change")
    return [StateRef(key="active_change", value=str(value or ""), line_no=1)]


def discover_formal_crs(
    change_root: Path,
    *,
    excluded_legacy_paths: frozenset[Path] = frozenset(),
) -> dict[str, FormalCR]:
    crs: dict[str, FormalCR] = {}
    if not change_root.is_dir():
        return crs
    for path in sorted(change_root.glob("CR-*.md")):
        if "FOLLOW-UP" in path.name:
            continue
        if path.resolve() in excluded_legacy_paths:
            continue
        text = read_text(path)
        fields = parse_frontmatter(text)
        cr_id = fields.get("cr_id") or (
            CR_ID_RE.search(path.name).group(0) if CR_ID_RE.search(path.name) else ""
        )
        if not cr_id:
            continue
        if cr_id in crs:
            raise ValueError(f"duplicate formal CR id {cr_id}: {crs[cr_id].path}, {path}")
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
            native=(
                strip_scalar(fields.get("schema_version", "")) == "1"
                and strip_scalar(fields.get("kind", "")) == "cr"
            ),
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
                kind = normalize_kind(
                    cells[header_map.get("类型", -1)].strip() if "类型" in header_map else "",
                    fallback_status=status,
                )
                rows.append(
                    FollowUpRow(
                        item_id=item_id,
                        title=cells[header_map.get("标题", -1)].strip()
                        if "标题" in header_map
                        else "",
                        status=status,
                        lifecycle_status=normalize_lifecycle_status("", fallback_status=status),
                        readiness_status="n/a",
                        gate_status=normalize_gate_status(
                            cells[header_map.get("当前门控", -1)].strip()
                            if "当前门控" in header_map
                            else "",
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
                    rows.append(
                        follow_up_row_from_mapping(current, path, current_line, source="yaml")
                    )
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


def follow_up_row_from_mapping(
    mapping: dict[str, str], path: Path, line_no: int, *, source: str
) -> FollowUpRow:
    status = normalize_status(mapping.get("status", ""))
    lifecycle_status = normalize_lifecycle_status(
        mapping.get("lifecycle_status", ""), fallback_status=status
    )
    kind = normalize_kind(mapping.get("kind", mapping.get("type", "")), fallback_status=status)
    if not status:
        status = (
            "spike_candidate"
            if kind == "spike" and lifecycle_status == "candidate"
            else lifecycle_status
        )
    return FollowUpRow(
        item_id=strip_scalar(mapping.get("id", "")),
        title=strip_scalar(mapping.get("title", "")),
        status=status,
        lifecycle_status=lifecycle_status,
        readiness_status=normalize_readiness_status(mapping.get("readiness_status", "")) or "n/a",
        gate_status=normalize_gate_status(
            mapping.get("gate_status", ""), fallback_gate="not_started"
        ),
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
        paths = [_resolve_runtime_path(project_root, path) for path in explicit_tracking]
    else:
        paths = sorted(
            _resolve_runtime_ref(project_root, "process/changes").glob(
                "CR-*-FOLLOW-UP-TRACKING-*.md"
            )
        )
    rows: list[FollowUpRow] = []
    for path in paths:
        if path.is_file():
            rows.extend(parse_structured_follow_up_rows(path))
            rows.extend(parse_follow_up_rows(path))
    return rows


def parse_cr_index_items(index_path: Path) -> list[IndexItem]:
    if not index_path.is_file():
        return []
    if index_path.suffix == ".json":
        data = json.loads(read_text(index_path))
        items = []
        for offset, item in enumerate(data.get("items", []), 1):
            mapping = {
                key: json.dumps(value) if isinstance(value, (list, dict)) else str(value)
                for key, value in item.items()
            }
            mapping.setdefault(
                "lifecycle_status", str(item.get("lifecycle_status") or item.get("status") or "")
            )
            mapping.setdefault(
                "readiness_status", str(item.get("readiness_status") or item.get("readiness") or "")
            )
            mapping.setdefault(
                "formal_cr_path", str(item.get("formal_cr_path") or item.get("full_ref") or "")
            )
            items.append(index_item_from_mapping(mapping, offset))
        return items
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


def validate_cr_index_projection(
    index_path: Path,
    *,
    expected_semantic_digest: str = "",
) -> list[str]:
    """Validate internal integrity and optional formal-truth rebuild equality."""

    if not index_path.is_file():
        return []
    try:
        payload = json.loads(read_text(index_path))
    except json.JSONDecodeError as exc:
        return [f"CR-INDEX.json invalid JSON: {exc}"]
    if not isinstance(payload, dict):
        return ["CR-INDEX.json must be an object"]
    errors: list[str] = []
    items = payload.get("items")
    if payload.get("schema_version") != 1:
        errors.append("CR-INDEX.json schema_version must be 1")
    if not isinstance(items, list):
        return [*errors, "CR-INDEX.json items must be a list"]
    ids = [str(item.get("id") or "") for item in items if isinstance(item, dict)]
    if len(ids) != len(items):
        errors.append("CR-INDEX.json items must contain objects only")
    if len(ids) != len(set(ids)):
        errors.append("CR-INDEX.json contains duplicate CR IDs")

    def numeric(value: str) -> tuple[int, str]:
        return (
            (int(value.split("-", 1)[1]), value)
            if re.fullmatch(r"CR-\d+", value)
            else (sys.maxsize, value)
        )

    if ids != sorted(ids, key=numeric):
        errors.append("CR-INDEX.json items must be ordered by numeric CR ID")
    semantic = json.dumps(
        {"schema_version": payload.get("schema_version"), "items": items},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    expected = hashlib.sha256(semantic.encode("utf-8")).hexdigest()
    if payload.get("semantic_digest") != expected:
        errors.append("CR-INDEX.json semantic_digest mismatch")
    if expected_semantic_digest and payload.get("semantic_digest") != expected_semantic_digest:
        errors.append("CR-INDEX.json stale projection differs from formal truth rebuild digest")
    return errors


def validate_formal_cr_truth_snapshot(
    project_root: Path,
    *,
    process_root: Path,
    excluded_legacy_paths: frozenset[Path],
    registered_legacy_ids: tuple[str, ...] = (),
    state_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """纯读取验证 formal-only CR index、legacy 分区与 State active_change。"""

    from meta_flow.workflow import cr_index

    errors: list[str] = []
    expected: dict[str, Any] = {}
    try:
        expected = cr_index.build_index(
            project_root,
            excluded_legacy_paths=excluded_legacy_paths,
        )
    except (OSError, ValueError) as exc:
        errors.append(f"formal CR truth cannot build native index: {exc}")
    native_ids = tuple(
        str(item.get("id") or "")
        for item in expected.get("items", [])
        if isinstance(item, Mapping)
    )
    overlap = sorted(set(native_ids) & set(registered_legacy_ids))
    if overlap:
        errors.append(
            "legacy evidence and native formal CR truth overlap: " + ", ".join(overlap)
        )
    expected_digest = str(expected.get("semantic_digest") or "")
    if expected_digest:
        errors.extend(
            validate_cr_index_projection(
                process_root.resolve() / "changes/CR-INDEX.json",
                expected_semantic_digest=expected_digest,
            )
        )
    active_change = str((state_snapshot or {}).get("active_change") or "")
    if active_change and active_change not in native_ids:
        errors.append(
            "STATE.current.active_change is absent from native formal CR truth: "
            + active_change
        )
    return {
        "decision": "BLOCKED" if errors else "PASS",
        "errors": errors,
        "native_ids": list(native_ids),
        "registered_legacy_ids": list(registered_legacy_ids),
        "semantic_digest": expected_digest,
    }


def find_legacy_cr_index_paths(project_root: Path) -> list[Path]:
    return [
        _resolve_runtime_path(project_root, rel)
        for rel in LEGACY_CR_INDEX_RELS
        if _resolve_runtime_path(project_root, rel).is_file()
    ]


def parse_next_action_candidates(index_path: Path) -> list[tuple[str, int]]:
    if not index_path.is_file():
        return []
    if index_path.suffix == ".json":
        data = json.loads(read_text(index_path))
        refs = []
        for offset, item in enumerate(data.get("next_action_queue", []), 1):
            refs.append((strip_scalar(str(item.get("candidate_id", ""))), offset))
        return refs
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
    lifecycle_status = normalize_lifecycle_status(
        mapping.get("lifecycle_status", ""), fallback_status=status
    )
    kind = normalize_kind(mapping.get("kind", mapping.get("type", "")), fallback_status=status)
    return IndexItem(
        item_id=strip_scalar(mapping.get("id", "")),
        title=strip_scalar(mapping.get("title", "")),
        status=status,
        lifecycle_status=lifecycle_status,
        readiness_status=normalize_readiness_status(mapping.get("readiness_status", "")) or "n/a",
        gate_status=normalize_gate_status(
            mapping.get("gate_status", ""), fallback_gate=mapping.get("next_gate", "")
        ),
        gate_profile=strip_scalar(mapping.get("gate_profile", "")).lower(),
        kind=kind,
        formal_path=normalize_path(strip_scalar(mapping.get("formal_cr_path", ""))),
        source_tracking=normalize_path(strip_scalar(mapping.get("source_tracking", ""))),
        blocked_by=parse_inline_list(mapping.get("blocked_by", "")),
        candidate_id=strip_scalar(mapping.get("candidate_id", "")),
        next_action=strip_scalar(mapping.get("next_action", "")),
        line_no=line_no,
    )


def formal_cr_for_follow_up_row(
    project_root: Path, formal_crs: dict[str, FormalCR], row: FollowUpRow
) -> FormalCR | None:
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
    return formal.status in FINISHED_FORMAL_STATUSES or formal.lifecycle_status in {
        "closed",
        "cancelled",
        "superseded",
    }


def _checkpoint_index_projection(text: str) -> dict[str, str]:
    projection: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = split_table_row(line)
        if len(cells) >= 2 and re.fullmatch(r"CP[0-8]", cells[0], re.IGNORECASE):
            projection[cells[0].upper()] = strip_scalar(cells[1]).upper()
    return projection


def _gate_progress_rank(gate_status: str) -> int:
    ranks = {
        "not_started": 0,
        "cp2_pending": 2,
        "cp3_pending": 3,
        "cp5_pending": 5,
        "implementation_in_progress": 6,
        "verification_in_progress": 7,
        "cp7_pending": 7,
        "cp8_pending": 8,
        "cp8_closed": 9,
        "cp8_recovery_closed": 9,
        "closed": 9,
    }
    return ranks.get(normalize_gate_status(gate_status), -1)


def validate_native_evidence_projection(project_root: Path, formal: FormalCR) -> list[str]:
    """交叉校验正式 CR、ADR、gate ledger 与 checkpoint result 的当前投影。"""

    errors: list[str] = []
    text = read_text(formal.path)
    checkpoint_projection = _checkpoint_index_projection(text)
    observed_progress: list[tuple[str, int, int]] = []
    work_ids: set[str] = set()

    try:
        gate_ledger = _resolve_runtime_ref(project_root, "process/state/GATE-LEDGER.ndjson")
        if gate_ledger.is_file():
            gate_events: list[dict[str, Any]] = []
            for line in read_text(gate_ledger).splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    gate_events.append(event)
            for approval in event_ledger.project_gate_approvals(gate_events):
                if approval.cr_id != formal.cr_id:
                    continue
                if (
                    "GATE_APPROVAL_LEGACY_BINDING_INVALID"
                    in approval.finding_codes
                ):
                    source = next(
                        (
                            event
                            for event in gate_events
                            if str(event.get("event_id") or "") == approval.event_id
                        ),
                        {},
                    )
                    checkpoint_match = re.search(
                        r"CP[0-8]",
                        str(source.get("checkpoint") or source.get("gate") or "").upper(),
                    )
                    if checkpoint_match is not None:
                        errors.append(
                            f"{formal.cr_id} Checkpoint Index "
                            f"{checkpoint_match.group(0)} is stale relative to "
                            "invalid legacy gate approval binding"
                        )
                    continue
                if not approval.passage:
                    continue
                checkpoint = approval.checkpoint
                if checkpoint_projection.get(checkpoint) not in {
                    "APPROVED",
                    "PASS",
                    "PASS_WITH_RISK",
                }:
                    errors.append(
                        f"{formal.cr_id} Checkpoint Index {checkpoint} is stale relative to approved gate ledger evidence"
                    )
                number = int(checkpoint[2:])
                # CP8 人工批准只证明发布终验通过；native close 是独立、受授权的
                # 相邻转换。若把 CP8 approval 视为 rank=9，会形成“先 close 才能
                # 记录 approval、但 close 又依赖 approval”的循环。
                required_rank = number if checkpoint == "CP8" else number + 1
                observed_progress.append((f"approved gate {checkpoint}", number, required_rank))
                if approval.work_id:
                    work_ids.add(approval.work_id)

        projection = canonical_checkpoint_projection.load_checkpoint_projection(
            project_root,
            cr_id=formal.cr_id,
        )
        errors.extend(
            f"{formal.cr_id} checkpoint projection {finding.code}: {finding.message}"
            for finding in projection.findings
        )
        for head in projection.heads:
            if head.subject_id != formal.cr_id or not re.fullmatch(
                r"CP[0-8]",
                head.checkpoint,
            ):
                continue
            checkpoint = head.checkpoint
            decision = head.decision
            projected = checkpoint_projection.get(checkpoint, "")
            if projected != decision and not (
                decision in {"PASS", "PASS_WITH_RISK"}
                and projected in {"PASS", "APPROVED", "PASS_WITH_RISK"}
            ):
                errors.append(
                    f"{formal.cr_id} Checkpoint Index "
                    f"{checkpoint}={projected or '<missing>'} is stale relative "
                    f"to canonical result decision={decision}"
                )
            number = int(checkpoint[2:])
            if decision in {"FAIL", "BLOCKED", "NEEDS_REWORK"}:
                required_rank = number
            elif checkpoint in {"CP2", "CP3", "CP5", "CP8"}:
                # 人工检查点的机器 PASS 只满足进入人工门的条件，不代表已越门。
                required_rank = number
            else:
                required_rank = number + 1
            observed_progress.append(
                (f"{checkpoint} canonical result {decision}", number, required_rank)
            )
            if head.result.get("work_id"):
                work_ids.add(str(head.result["work_id"]))
    except (OSError, ProcessRouteError):
        # 缺少辅助投影本身由其他 canonical 检查负责；这里不把 legacy fixture
        # 强行升级为 native process 布局。
        return errors

    formal_rank = _gate_progress_rank(formal.gate_status)
    for source, _checkpoint_number, required_rank in observed_progress:
        if formal_rank < required_rank:
            errors.append(
                f"{formal.cr_id} frontmatter gate_status={formal.gate_status or '<missing>'} "
                f"is stale relative to {source}"
            )

    for work_id in sorted(work_ids):
        try:
            adr_path = _resolve_runtime_ref(
                project_root,
                f"process/works/{work_id}/ARCHITECTURE-DECISION.md",
            )
        except ProcessRouteError:
            continue
        if not adr_path.is_file():
            continue
        adr_text = read_text(adr_path)
        if strip_scalar(parse_frontmatter(adr_text).get("status", "")).lower() != "accepted":
            continue
        for line_no, line in enumerate(adr_text.splitlines(), 1):
            if not line.strip().startswith("|") or not re.search(
                r"(?:CP[35]-)?DQ-[A-Za-z0-9-]+", line
            ):
                continue
            cells = [strip_scalar(cell).upper() for cell in split_table_row(line)]
            if "OPEN" in cells:
                errors.append(
                    f"{formal.cr_id} accepted ADR has stale OPEN decision queue row "
                    f"{format_runtime_ref(project_root, adr_path)}:{line_no}"
                )
    return errors


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
            errors.append(
                f"STATE line {ref.line_no} {ref.key} points to missing formal CR: {ref.value}"
            )
            continue
        if cr.native:
            if cr.lifecycle_status in {"closed", "cancelled", "superseded"}:
                errors.append(
                    f"STATE line {ref.line_no} {ref.key} points to finished CR {ref.value} with lifecycle_status={cr.lifecycle_status}"
                )
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

    for cr in formal_crs.values():
        location = format_runtime_ref(project_root, cr.path)
        if cr.lifecycle_status and cr.lifecycle_status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(
                f"{location} invalid lifecycle_status for {cr.cr_id}: {cr.lifecycle_status}"
            )
        if cr.readiness_status and cr.readiness_status not in ALLOWED_READINESS_STATUSES:
            errors.append(
                f"{location} invalid readiness_status for {cr.cr_id}: {cr.readiness_status}"
            )
        if cr.gate_status and cr.gate_status not in ALLOWED_GATE_STATUSES:
            errors.append(f"{location} invalid gate_status for {cr.cr_id}: {cr.gate_status}")
        if cr.native:
            errors.extend(
                f"{location} {cr.cr_id} {message}"
                for message in validate_native_status_tuple(
                    cr.lifecycle_status,
                    cr.readiness_status,
                    cr.gate_status,
                )
            )
        if cr.cr_kind and cr.cr_kind not in ALLOWED_CR_KINDS:
            errors.append(f"{location} invalid cr_kind for {cr.cr_id}: {cr.cr_kind}")
        if cr.gate_profile and cr.gate_profile not in ALLOWED_GATE_PROFILES:
            errors.append(f"{location} invalid gate_profile for {cr.cr_id}: {cr.gate_profile}")
        if cr.historical_baseline_status == "reframed" and not cr.reframed_by:
            warnings.append(
                f"{location} has historical_baseline_status=reframed but no reframed_by"
            )
        if cr.native and cr.lifecycle_status in {"active", "blocked"}:
            errors.extend(validate_native_evidence_projection(project_root, cr))

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
        cr for cr in formal_crs.values() if cr.status == "active" or cr.lifecycle_status == "active"
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

    index_by_id = {item.item_id: item for item in index_items if item.item_id}
    for ref in top_refs:
        if not ref.value:
            continue
        indexed = index_by_id.get(ref.value)
        if indexed is None:
            errors.append(
                f"STATE active_change={ref.value} is missing from canonical CR-INDEX.json"
            )
            continue
        if indexed.lifecycle_status in {"closed", "cancelled", "superseded"}:
            errors.append(
                f"STATE active_change={ref.value} points to terminal CR-INDEX lifecycle_status={indexed.lifecycle_status}"
            )

    rows_by_id: dict[str, list[FollowUpRow]] = {}
    for row in rows:
        rows_by_id.setdefault(row.item_id, []).append(row)
        location = f"{format_runtime_ref(project_root, row.source_path)}:{row.line_no}"
        if not CANDIDATE_ID_RE.fullmatch(row.item_id):
            errors.append(f"{location} invalid follow-up id format: {row.item_id}")
        if row.status not in ALLOWED_FOLLOW_UP_STATUSES:
            errors.append(f"{location} invalid follow-up status for {row.item_id}: {row.status}")
        if row.lifecycle_status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(
                f"{location} invalid lifecycle_status for {row.item_id}: {row.lifecycle_status}"
            )
        if row.readiness_status not in ALLOWED_READINESS_STATUSES:
            errors.append(
                f"{location} invalid readiness_status for {row.item_id}: {row.readiness_status}"
            )
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
            warnings.append(
                f"{location} {row.item_id} is {row.status} but already has 正式 CR 路径={row.formal_path}"
            )
        if not formal_path_missing:
            resolved = resolve_project_path(project_root, row.formal_path)
            if not resolved.is_file():
                errors.append(
                    f"{location} {row.item_id} formal CR path does not exist: {row.formal_path}"
                )

        formal = formal_crs.get(row.item_id)
        if formal is not None:
            if row.lifecycle_status == "candidate":
                errors.append(
                    f"{location} {row.item_id} is still {row.status} but formal CR file exists: "
                    f"{format_runtime_ref(project_root, formal.path)}"
                )
            if row.lifecycle_status == "active" and formal.status in FINISHED_FORMAL_STATUSES:
                errors.append(
                    f"{location} {row.item_id} is active in tracking but formal status={formal.status}"
                )
            if row.lifecycle_status == "closed" and formal.status not in FINISHED_FORMAL_STATUSES:
                errors.append(
                    f"{location} {row.item_id} is closed in tracking but formal status={formal.status}"
                )

        linked_formal = formal_cr_for_follow_up_row(project_root, formal_crs, row)
        if row.item_id.startswith("FU-") and not formal_path_missing and linked_formal is None:
            errors.append(
                f"{location} {row.item_id} formal CR path is not a discovered formal CR: {row.formal_path}"
            )
        if row.item_id.startswith("FU-") and linked_formal is not None:
            if row.lifecycle_status == "active" and not is_formal_active(linked_formal):
                errors.append(
                    f"{location} {row.item_id} is active but linked formal CR {linked_formal.cr_id} "
                    f"is status={linked_formal.status or '<empty>'} lifecycle_status={linked_formal.lifecycle_status or '<empty>'}"
                )
            if (
                row.lifecycle_status == "active"
                and f"related_active_cr={linked_formal.cr_id}" not in row.relationship_text
            ):
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
        location = format_runtime_ref(project_root, cr.path)
        expected_row_id = cr.source_follow_up_id or cr.cr_id
        if expected_row_id not in rows_by_id:
            warnings.append(
                f"{location} source=cp8-follow-up but no matching follow-up tracking row"
            )
        if not cr.source_follow_up_id:
            continue
        source_rows = rows_by_id.get(cr.source_follow_up_id, [])
        if not source_rows:
            errors.append(
                f"{location} source_follow_up_id={cr.source_follow_up_id} has no matching follow-up row"
            )
            continue
        linked_source_rows = [
            row for row in source_rows if formal_row_points_to_cr(project_root, row, cr)
        ]
        if not linked_source_rows:
            errors.append(
                f"{location} source_follow_up_id={cr.source_follow_up_id} has no follow-up row pointing to this CR"
            )
            continue
        for row in linked_source_rows:
            row_location = f"{format_runtime_ref(project_root, row.source_path)}:{row.line_no}"
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

    for cr in active_formal:
        if not any(
            item.item_id == cr.cr_id
            or item.formal_path == format_runtime_ref(project_root, cr.path)
            for item in index_items
        ):
            message = f"CR-INDEX.json does not mention active formal CR {cr.cr_id}"
            if cr.native:
                errors.append(message)
            else:
                warnings.append(message)

    for item in index_items:
        location = f"process/changes/CR-INDEX.json:{item.line_no}"
        if not CANDIDATE_ID_RE.fullmatch(item.item_id):
            errors.append(f"{location} invalid CR index item id format: {item.item_id}")
        if item.lifecycle_status not in ALLOWED_LIFECYCLE_STATUSES:
            formal = formal_crs.get(item.item_id)
            if formal and is_formal_finished(formal):
                warnings.append(
                    f"{location} historical lifecycle_status for closed {item.item_id} is legacy value: "
                    f"{item.lifecycle_status}"
                )
            else:
                errors.append(
                    f"{location} invalid lifecycle_status for {item.item_id}: {item.lifecycle_status}"
                )
        if item.readiness_status not in ALLOWED_READINESS_STATUSES:
            errors.append(
                f"{location} invalid readiness_status for {item.item_id}: {item.readiness_status}"
            )
        if item.gate_status and item.gate_status not in ALLOWED_GATE_STATUSES:
            errors.append(f"{location} invalid gate_status for {item.item_id}: {item.gate_status}")
        formal = formal_crs.get(item.item_id)
        if formal and formal.native:
            errors.extend(
                f"{location} {item.item_id} {message}"
                for message in validate_native_status_tuple(
                    item.lifecycle_status,
                    item.readiness_status,
                    item.gate_status,
                )
            )
            if item.lifecycle_status != formal.lifecycle_status:
                errors.append(
                    f"{location} {item.item_id} lifecycle_status differs from formal CR truth: "
                    f"{item.lifecycle_status} != {formal.lifecycle_status}"
                )
            if item.readiness_status != formal.readiness_status:
                errors.append(
                    f"{location} {item.item_id} readiness_status differs from formal CR truth: "
                    f"{item.readiness_status} != {formal.readiness_status}"
                )
            if item.gate_status != formal.gate_status:
                errors.append(
                    f"{location} {item.item_id} gate_status differs from formal CR truth: "
                    f"{item.gate_status} != {formal.gate_status}"
                )
        if item.kind and item.kind not in ALLOWED_CR_KINDS:
            errors.append(f"{location} invalid kind for {item.item_id}: {item.kind}")
        if item.gate_profile and item.gate_profile not in ALLOWED_GATE_PROFILES:
            errors.append(
                f"{location} invalid gate_profile for {item.item_id}: {item.gate_profile}"
            )
        if (
            item.status
            and item.lifecycle_status
            and normalize_lifecycle_status("", fallback_status=item.status) != item.lifecycle_status
        ):
            warnings.append(
                f"{location} legacy status={item.status} disagrees with lifecycle_status={item.lifecycle_status}"
            )
        formal_path_missing = item.formal_path in PATH_EMPTY_VALUES
        if item.lifecycle_status in {"active", "blocked", "closed"} and formal_path_missing:
            errors.append(
                f"{location} {item.item_id} lifecycle_status={item.lifecycle_status} requires formal_cr_path"
            )
        if item.lifecycle_status == "candidate" and not formal_path_missing:
            warnings.append(
                f"{location} {item.item_id} is candidate but already has formal_cr_path={item.formal_path}"
            )
        if (
            not formal_path_missing
            and not resolve_project_path(project_root, item.formal_path).is_file()
        ):
            errors.append(
                f"{location} {item.item_id} formal_cr_path does not exist: {item.formal_path}"
            )
        for blocker in item.blocked_by:
            blocker_cr = formal_crs.get(blocker)
            if blocker_cr and (
                blocker_cr.status in FINISHED_FORMAL_STATUSES
                or blocker_cr.lifecycle_status == "closed"
            ):
                warnings.append(
                    f"{location} {item.item_id} blocked_by={blocker} points to closed CR"
                )

    for item_id, row_group in rows_by_id.items():
        if item_id not in index_by_id:
            # CR-INDEX 是 formal-only 投影。合法 candidate/spike_candidate，
            # 以及通过 formal_cr_path 关联正式 CR 的 follow-up row，均不要求
            # 自身 ID 出现在 index。
            continue
        index_item = index_by_id[item_id]
        for row in row_group:
            if row.lifecycle_status != index_item.lifecycle_status:
                warnings.append(
                    f"{format_runtime_ref(project_root, row.source_path)}:{row.line_no} "
                    f"{item_id} lifecycle_status={row.lifecycle_status} "
                    f"differs from CR-INDEX lifecycle_status={index_item.lifecycle_status}"
                )

    for candidate_id, line_no in next_action_refs:
        if not candidate_id or candidate_id in PATH_EMPTY_VALUES or "000" in candidate_id:
            continue
        tracked_candidate = any(
            row.item_id == candidate_id and row.lifecycle_status == "candidate" for row in rows
        )
        if candidate_id not in index_by_id and not tracked_candidate:
            warnings.append(
                f"CR-INDEX.json:{line_no} next_action_queue candidate_id={candidate_id} is not in CR-INDEX.json items"
            )

    return errors, warnings


def validate_native_projection_closure(
    formal_crs: dict[str, FormalCR],
    *,
    projector: Any,
) -> list[str]:
    """Require every live native CR to converge across formal/summary/index/ledger truth.

    Terminal evidence lineage and historical repair remain owned by R10; this
    admission check must not rewrite or retroactively invalidate that corpus.
    """

    errors: list[str] = []
    for cr_id, formal in sorted(formal_crs.items()):
        if not formal.native or formal.lifecycle_status in {
            "closed",
            "cancelled",
            "superseded",
        }:
            continue
        projection = projector(cr_id)
        if str(getattr(projection, "decision", "")) == "PASS":
            continue
        findings = tuple(getattr(projection, "findings", ()) or ())
        detail = ",".join(str(item) for item in findings) or "UNKNOWN_PROJECTION_FAILURE"
        errors.append(f"native CR projection {cr_id} is not converged: {detail}")
    return errors


def print_summary(
    formal_crs: dict[str, FormalCR],
    rows: list[FollowUpRow],
    index_items: list[IndexItem],
    *,
    registered_legacy_ids: tuple[str, ...] = (),
) -> None:
    active = sorted(
        cr.cr_id
        for cr in formal_crs.values()
        if cr.status == "active" or cr.lifecycle_status == "active"
    )
    blocked = sorted(
        cr.cr_id
        for cr in formal_crs.values()
        if cr.status == "blocked" or cr.lifecycle_status == "blocked"
    )
    candidates = sorted(
        {row.item_id for row in rows if row.lifecycle_status == "candidate" and row.kind != "spike"}
    )
    spike_candidates = sorted(
        {row.item_id for row in rows if row.lifecycle_status == "candidate" and row.kind == "spike"}
    )
    indexed_candidates = sorted(
        {item.item_id for item in index_items if item.lifecycle_status == "candidate"}
    )
    print("CR tracking summary")
    print(f"- active formal CRs: {', '.join(active) if active else 'none'}")
    print(f"- blocked formal CRs: {', '.join(blocked) if blocked else 'none'}")
    print(
        "- registered legacy evidence: "
        + (", ".join(registered_legacy_ids) if registered_legacy_ids else "none")
    )
    print(f"- follow-up candidates: {', '.join(candidates) if candidates else 'none'}")
    print(f"- spike candidates: {', '.join(spike_candidates) if spike_candidates else 'none'}")
    print(
        f"- indexed candidates: {', '.join(indexed_candidates) if indexed_candidates else 'none'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate CR tracking consistency across STATE.active_change, formal CR files, "
            "follow-up tracking tables, and CR-INDEX.json."
        )
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Project root containing process/STATE.md",
    )
    parser.add_argument(
        "--tracking",
        type=Path,
        action="append",
        default=[],
        help="Optional follow-up tracking file. Defaults to process/changes/CR-*-FOLLOW-UP-TRACKING-*.md",
    )
    parser.add_argument(
        "--allow-multiple-active",
        action="store_true",
        help="Allow more than one formal CR with status=active",
    )
    parser.add_argument(
        "--allow-legacy-yaml",
        action="store_true",
        help="Allow CR-INDEX.yaml/yml as read-only legacy fallback during migration. New flows must use CR-INDEX.json.",
    )
    parser.add_argument("--strict-warnings", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    try:
        route = require_process_route(project_root)
    except ProcessRouteError as exc:
        print(f"BLOCKED: {exc.error_code}: {exc}", file=sys.stderr)
        return 2
    state_v2_path = route.resolve_ref("process/state/STATE.current.json")
    state_path = route.resolve_ref("process/STATE.md")
    change_root = route.resolve_ref("process/changes")
    index_path = change_root / "CR-INDEX.json"
    from meta_flow.workflow.legacy_evidence_registry import (
        LegacyEvidenceError,
        load_declared_legacy_evidence_registry,
    )

    try:
        legacy_bundle = load_declared_legacy_evidence_registry(
            project_root,
            consumer_id="cr-tracking",
        )
    except LegacyEvidenceError as exc:
        print(f"BLOCKED: {exc.code}: {exc}", file=sys.stderr)
        return 2
    formal_crs = discover_formal_crs(
        change_root,
        excluded_legacy_paths=frozenset(legacy_bundle.evidence_paths),
    )
    follow_up_rows = discover_follow_up_rows(project_root, args.tracking)
    registered_legacy_ids = tuple(
        match.group(0)
        for registration in legacy_bundle.registrations
        if (match := CR_ID_RE.search(registration.evidence_logical_ref)) is not None
    )
    formal_truth_check = validate_formal_cr_truth_snapshot(
        project_root,
        process_root=route.process_root,
        excluded_legacy_paths=frozenset(legacy_bundle.evidence_paths),
        registered_legacy_ids=registered_legacy_ids,
    )
    projection_errors = list(formal_truth_check["errors"])
    from meta_flow.workflow import cr_lifecycle

    try:
        index_items = parse_cr_index_items(index_path)
        next_action_refs = parse_next_action_candidates(index_path)
    except json.JSONDecodeError:
        index_items = []
        next_action_refs = []
    state_refs = (
        find_state_v2_refs(state_v2_path)
        if state_v2_path.is_file()
        else find_state_refs(state_path)
    )
    errors, warnings = collect_errors_and_warnings(
        project_root=project_root,
        formal_crs=formal_crs,
        rows=follow_up_rows,
        index_items=index_items,
        next_action_refs=next_action_refs,
        state_refs=state_refs,
        allow_multiple_active=args.allow_multiple_active,
    )
    errors.extend(projection_errors)
    try:
        errors.extend(
            validate_native_projection_closure(
                formal_crs,
                projector=lambda cr_id: cr_lifecycle.project_native_cr_status(
                    project_root,
                    cr_id=cr_id,
                    excluded_legacy_paths=frozenset(legacy_bundle.evidence_paths),
                ),
            )
        )
    except ValueError as exc:
        errors.append(f"native CR projection cannot be evaluated: {exc}")
    legacy_index_paths = find_legacy_cr_index_paths(project_root)
    if legacy_index_paths and not args.allow_legacy_yaml:
        errors.extend(
            f"legacy CR index is not allowed in canonical JSON mode: "
            f"{format_runtime_ref(project_root, path)}; "
            "migrate/delete it or pass --allow-legacy-yaml for read-only legacy fallback"
            for path in legacy_index_paths
        )
    elif legacy_index_paths:
        warnings.extend(
            f"legacy CR index present as read-only fallback: "
            f"{format_runtime_ref(project_root, path)}; CR-INDEX.json remains canonical"
            for path in legacy_index_paths
        )

    if state_v2_path.is_file():
        for finding in current.validate_current_projection(project_root):
            message = f"{finding.code}: {finding.message}"
            if finding.severity == "ERROR":
                errors.append(message)
            else:
                warnings.append(message)

    print_summary(
        formal_crs,
        follow_up_rows,
        index_items,
        registered_legacy_ids=registered_legacy_ids,
    )
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
