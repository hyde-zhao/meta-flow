"""CR projection and shared writer primitives."""
# ruff: noqa: I001, UP034
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.checks import cr_tracking
from meta_flow.project.read_contract import ReadContextProtocol
from meta_flow.state import checkpoint_projection, current
from meta_flow.workflow.cr_model import now_utc
from meta_flow.workflow.cr_records import (
    CR_SUMMARY_ROOT_REL, _first_section_summary, _git_fact, _impact_split_payload,
    _normalized_capability_refs, _process_root, _record_required_evidence, _rel,
    _resolve_runtime_ref, _section_summary, classify_cp1_review_profile,
    collect_archive_isolation_findings, collect_governance_dependency_findings,
    collect_scope_authz_findings, discover_formal_crs, record_from_cr_file,
)

CR_LEDGER_REL = Path('process/state/CR-LEDGER.ndjson')

CR_ARCHIVE_ROOT_REL = Path('process/archive')

STATE_CURRENT_REL = Path('process/state/STATE.current.json')

@dataclass(frozen=True)
class NativeCRStatusProjectionV1:
    """由四个原生 CR 真相源收敛得到的单一状态投影。"""
    cr_id: str
    lifecycle_status: str
    readiness_status: str
    gate_status: str
    formal_cr_ref: str
    summary_ref: str
    ledger_event_id: str
    decision: str
    findings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, 'kind': 'NativeCRStatusProjectionV1', 'schema_version': 1, 'findings': list(self.findings)}

class AggregateCompletionProjector:
    """Project one persisted PASS aggregate through CR ledger and current-state writers."""

    def __init__(self, *, project_root: Path, expected_state_updated_at: str, append_ledger_event_fn: Any | None = None, rel_fn: Any | None = None) -> None:
        self.project_root = project_root.resolve()
        self.expected_state_updated_at = expected_state_updated_at
        self._append_ledger_event_fn = append_ledger_event_fn
        self._rel_fn = rel_fn

    def project_aggregate(self, *, result: Any, receipt: Any) -> dict[str, Any]:
        if not getattr(result, 'cr_id', '') or not getattr(receipt, 'aggregate_id', ''):
            raise ValueError('aggregate projection receipt identity is missing')
        if getattr(result, 'aggregate_id', '') != getattr(receipt, 'aggregate_id', ''):
            raise ValueError('aggregate projection result/receipt identity mismatch')
        if str(getattr(result, 'overall', '')) != 'PASS' or getattr(result, 'terminal', False) is not True or str(getattr(result, 'projection_decision', '')) != 'ELIGIBLE' or (getattr(receipt, 'readback_valid', False) is not True) or (getattr(receipt, 'current_selected', False) is not True):
            raise ValueError('aggregate projection requires persisted/readback current 2/2 PASS')
        cr_id = str(getattr(result, 'cr_id', '') or '')
        aggregate_ref = str(getattr(receipt, 'aggregate_ref', '') or '')
        writer_receipts: dict[str, Any] = {}
        try:
            state_receipt = current.project_aggregate_completion(self.project_root, cr_id=cr_id, aggregate_id=str(result.aggregate_id), aggregate_ref=aggregate_ref, payload_digest=str(result.payload_digest), expected_updated_at=self.expected_state_updated_at)
        except (OSError, RuntimeError, ValueError) as error:
            return {'status': 'failed', 'writer_receipts': writer_receipts, 'error': f'state_current:{type(error).__name__}:{error}'}
        writer_receipts['state_current'] = state_receipt
        existing_event = next((event for event in load_ledger_events(self.project_root) if event.get('event') == 'aggregate_projection' and event.get('id') == cr_id and (event.get('aggregate_ref') == aggregate_ref)), None)
        try:
            if existing_event is None:
                append = self._append_ledger_event_fn or append_ledger_event
                ledger_path = append(self.project_root, {'event': 'aggregate_projection', 'id': cr_id, 'status': 'active', 'aggregate_id': result.aggregate_id, 'aggregate_ref': aggregate_ref, 'payload_digest': result.payload_digest, 'projection_disposition': state_receipt.get('status'), 'projected_at': now_utc()})
                ledger_receipt = {'status': 'projected', 'ledger_ref': (self._rel_fn or _rel)(self.project_root, ledger_path)}
            else:
                ledger_receipt = {'status': 'idempotent-existing', 'ledger_ref': CR_LEDGER_REL.as_posix()}
        except (OSError, RuntimeError, ValueError) as error:
            return {'status': 'partial', 'writer_receipts': writer_receipts, 'error': f'cr_ledger:{type(error).__name__}:{error}'}
        writer_receipts['cr_ledger'] = ledger_receipt
        return {'status': 'complete', 'writer_receipts': writer_receipts}

def _gate_checkpoint_projection(gate_status: str) -> tuple[str, str] | None:
    """Map the lifecycle gate to the exact Checkpoint Index row projection."""
    mapping = {'cp2_pending': ('CP2', 'pending'), 'cp3_pending': ('CP3', 'pending'), 'cp5_pending': ('CP5', 'pending'), 'implementation_in_progress': ('CP6', 'in-progress'), 'cp7_pending': ('CP7', 'pending'), 'verification_in_progress': ('CP7', 'in-progress'), 'cp8_pending': ('CP8', 'pending'), 'cp8_closed': ('CP8', 'approved'), 'cp8_recovery_closed': ('CP8', 'approved'), 'closed': ('CP8', 'approved')}
    return mapping.get(gate_status)

def _checkpoint_result_projection(
    project_root: Path,
    cr_id: str,
    *,
    resolver: Any | None = None,
    read_context: ReadContextProtocol | None = None,
) -> dict[str, str]:
    """只消费 canonical owner 选出的 CR-level current heads。"""
    kwargs = {"resolver": resolver} if resolver is not None else {}
    projection = checkpoint_projection.load_checkpoint_projection(
        project_root,
        cr_id=cr_id,
        read_context=read_context,
        **kwargs,
    )
    if projection.findings:
        raise ValueError('checkpoint projection failed: ' + '; '.join((f'{finding.code}:{finding.message}' for finding in projection.findings)))
    return {head.checkpoint: head.decision for head in projection.heads if head.subject_id == cr_id and re.fullmatch('CP[0-8]', head.checkpoint)}

def _render_exact_section_rows(text: str, heading: str, replacements: dict[str, str]) -> str:
    """Replace exact first-column table rows inside one optional section."""
    heading_pattern = re.compile(f'^## (?:(?:\\d+(?:\\.\\d+)*)\\.?\\s+)?{re.escape(heading)}$')
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if heading_pattern.fullmatch(line.rstrip('\r\n'))]
    if not starts:
        return text
    if len(starts) != 1:
        raise ValueError(f'duplicate CR body section: {heading}')
    start = starts[0] + 1
    end = next((index for index in range(start, len(lines)) if lines[index].startswith('## ')), len(lines))
    seen: set[str] = set()
    for index in range(start, end):
        raw = lines[index]
        line_ending = '\n' if raw.endswith('\n') else ''
        cells = [cell.strip() for cell in raw.rstrip('\r\n').split('|')]
        if len(cells) < 4 or cells[0] != '':
            continue
        key = cells[1]
        if key not in replacements:
            continue
        if key in seen:
            raise ValueError(f'duplicate CR body table row: {heading}/{key}')
        cells[2] = replacements[key]
        lines[index] = '| ' + ' | '.join(cells[1:-1]) + ' |' + line_ending
        seen.add(key)
    return ''.join(lines)

def render_status_body_projection(text: str, *, lifecycle_status: str, readiness_status: str, gate_status: str, checkpoint_results: dict[str, str] | None=None) -> str:
    """Project lifecycle truth into the optional CR body status tables."""
    rendered = _render_exact_section_rows(text, 'CR 类型与门禁策略', {'生命周期状态': lifecycle_status, '就绪状态': readiness_status, '门禁状态': gate_status})
    checkpoint_projection = dict(checkpoint_results or {})
    checkpoint = _gate_checkpoint_projection(gate_status)
    if checkpoint is not None:
        checkpoint_id, checkpoint_status = checkpoint
        if checkpoint_status == 'approved' or checkpoint_id not in checkpoint_projection:
            checkpoint_projection[checkpoint_id] = checkpoint_status
    if not checkpoint_projection:
        return rendered
    return _render_exact_section_rows(rendered, 'Checkpoint Index', checkpoint_projection)

def summary_from_cr_file(
    project_root: Path,
    path: Path,
    *,
    readiness: str | None = None,
    read_context: ReadContextProtocol | None = None,
    text: str | None = None,
    rel_fn: Any | None = None,
) -> dict[str, Any]:
    relative = rel_fn or _rel
    if text is None:
        text = (
            path.read_text(encoding='utf-8')
            if read_context is None
            else read_context.read_text(relative(project_root, path))
        )
    record = record_from_cr_file(
        project_root,
        path,
        _rel_fn=relative,
        read_context=read_context,
        text=text,
    )
    summary = {'id': record.cr_id, 'cr_type': record.cr_type, 'title': record.title, 'status': record.status, 'readiness': readiness or record.readiness, 'gate_status': record.gate_status, 'gate_profile': record.gate_profile, 'decision': 'pending', 'scope_summary': _section_summary(text, '## 变更描述') or [record.title], 'impact_surface': record.impact_surface, **_impact_split_payload(record), 'impact_capability_resolution': record.impact_capability_resolution, 'impact_capability_normalized': _normalized_capability_refs(record.impact_capability_resolution), 'conflict_keys': record.conflict_keys, 'remaining_risks': record.risk_refs, 'followup_candidates': [], 'authz_policy_refs': record.authz_policy_refs, 'goal_ref': record.goal_ref, 'goal_statement': record.goal_statement or _first_section_summary(text, '## 目标影响摘要'), 'user_goal_impact': record.user_goal_impact, 'split_rationale': record.split_rationale or _first_section_summary(text, '## 拆分理由'), 'why_not_merge_with_parent': record.why_not_merge_with_parent, 'why_not_story_or_task': record.why_not_story_or_task, 'approval_focus': record.approval_focus, 'decision_burden': record.decision_burden, 'approve_effect': record.approve_effect or _first_section_summary(text, '## approve 后果'), 'reject_effect': record.reject_effect, 'not_authorized_by_approve': record.not_authorized_by_approve or _section_summary(text, '## 不授权范围'), 'product_baseline_refresh_required': record.product_baseline_refresh_required, 'required_phase': record.required_phase, 'required_agent': record.required_agent, 'required_gate': record.required_gate, 'block_story_decomposition_until': record.block_story_decomposition_until, 'affected_product_docs': record.affected_product_docs, 'affected_use_cases': record.affected_use_cases, 'routing_design_ref': record.routing_design_ref, 'required_evidence': _record_required_evidence(record, text), 'required_capabilities': record.required_capabilities, 'full_ref': record.full_ref, 'evidence_index_ref': (CR_ARCHIVE_ROOT_REL / record.cr_id / 'evidence-index.json').as_posix(), 'updated_at': now_utc()}
    blockers, needs_review = collect_scope_authz_findings(record, text=text)
    summary['scope_authz_consistency'] = {'decision': 'BLOCKED' if blockers else 'NEEDS_REVIEW' if needs_review else 'PASS', 'blockers': blockers, 'needs_review': needs_review}
    governance_findings = collect_governance_dependency_findings(project_root, record)
    summary['governance_dependency_review'] = {'decision': 'NEEDS_REVIEW' if governance_findings else 'PASS', 'findings': governance_findings}
    archive_findings = collect_archive_isolation_findings(record, project_root=project_root)
    summary['cp1_review_profile'] = classify_cp1_review_profile(record)
    summary['archive_isolation_review'] = {'decision': 'NEEDS_REVIEW' if archive_findings else 'PASS', 'findings': archive_findings}
    return summary

def write_summary(project_root: Path, cr_id: str, summary: dict[str, Any]) -> Path:
    path = _resolve_runtime_ref(project_root, CR_SUMMARY_ROOT_REL.as_posix()) / f'{cr_id}.summary.json'
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            existing = None
        if isinstance(existing, dict):
            existing_semantic = dict(existing)
            candidate_semantic = dict(summary)
            existing_semantic.pop('updated_at', None)
            candidate_semantic.pop('updated_at', None)
            if existing_semantic == candidate_semantic:
                return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
    return path

def write_evidence_index(project_root: Path, cr_id: str, summary: dict[str, Any]) -> Path:
    path = _resolve_runtime_ref(project_root, CR_ARCHIVE_ROOT_REL.as_posix()) / cr_id / 'evidence-index.json'
    data = {'cr_id': cr_id, 'summary_ref': (CR_SUMMARY_ROOT_REL / f'{cr_id}.summary.json').as_posix(), 'full_ref': summary.get('full_ref'), 'evidence_refs': [], 'created_at': now_utc()}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            existing = None
        if isinstance(existing, dict):
            existing_semantic = dict(existing)
            candidate_semantic = dict(data)
            existing_semantic.pop('created_at', None)
            candidate_semantic.pop('created_at', None)
            if existing_semantic == candidate_semantic:
                return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return path

def append_ledger_event(
    project_root: Path, event: dict[str, Any], *, resolve_runtime_ref_fn: Any | None = None
) -> Path:
    resolve = resolve_runtime_ref_fn or _resolve_runtime_ref
    path = resolve(project_root, CR_LEDGER_REL.as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + '\n')
    return path

def load_ledger_events(
    project_root: Path, *, resolve_runtime_ref_fn: Any | None = None
) -> list[dict[str, Any]]:
    resolve = resolve_runtime_ref_fn or _resolve_runtime_ref
    path = resolve(project_root, CR_LEDGER_REL.as_posix())
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f'{path}:{line_no} invalid JSON: {exc}') from exc
    return events

def project_native_cr_status(project_root: Path, *, cr_id: str, resolve_runtime_ref: Any, rel: Any, load_index: Any) -> NativeCRStatusProjectionV1:
    """交叉验证 formal CR、summary、index 和 append-only ledger 的状态。

    publisher 等下游只能消费这个投影，不再各自解释 frontmatter。
    """
    findings: list[str] = []
    formal_crs = discover_formal_crs(project_root, _resolve_runtime_ref_fn=resolve_runtime_ref, _rel_fn=rel)
    formal_path = formal_crs.get(cr_id)
    if formal_path is None:
        return NativeCRStatusProjectionV1(cr_id=cr_id, lifecycle_status='', readiness_status='', gate_status='', formal_cr_ref='', summary_ref='', ledger_event_id='', decision='BLOCKED', findings=('FORMAL_CR_MISSING',))
    record = record_from_cr_file(project_root, formal_path, _rel_fn=rel)
    formal_ref = record.full_ref
    summary_ref = record.summary_ref
    formal_tuple = (cr_tracking.normalize_lifecycle_status(record.status), cr_tracking.normalize_readiness_status(record.readiness), cr_tracking.normalize_gate_status(record.gate_status))
    if cr_tracking.validate_native_status_tuple(*formal_tuple):
        findings.append('FORMAL_CR_STATUS_TUPLE_INVALID')
    index = load_index(project_root)
    index_items = index.get('items') if isinstance(index, dict) else None
    index_item = next((item for item in index_items or [] if isinstance(item, dict) and str(item.get('id') or '') == cr_id), None)
    if index_item is None:
        findings.append('CR_INDEX_ITEM_MISSING')
    else:
        index_tuple = (cr_tracking.normalize_lifecycle_status(str(index_item.get('lifecycle_status') or ''), fallback_status=str(index_item.get('status') or '')), cr_tracking.normalize_readiness_status(str(index_item.get('readiness_status') or index_item.get('readiness') or '')), cr_tracking.normalize_gate_status(str(index_item.get('gate_status') or '')))
        if index_tuple != formal_tuple:
            findings.append('CR_INDEX_STATUS_DIVERGED')
        if str(index_item.get('full_ref') or index_item.get('formal_cr_path') or '') != formal_ref:
            findings.append('CR_INDEX_FORMAL_REF_DIVERGED')
        if str(index_item.get('summary_ref') or '') != summary_ref:
            findings.append('CR_INDEX_SUMMARY_REF_DIVERGED')
    summary_path = resolve_runtime_ref(project_root, summary_ref)
    summary: dict[str, Any] = {}
    if not summary_path.is_file():
        findings.append('CR_SUMMARY_MISSING')
    else:
        try:
            loaded_summary = json.loads(summary_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            findings.append('CR_SUMMARY_INVALID_JSON')
        else:
            if not isinstance(loaded_summary, dict):
                findings.append('CR_SUMMARY_INVALID_SHAPE')
            else:
                summary = loaded_summary
    if summary:
        summary_tuple = (cr_tracking.normalize_lifecycle_status(str(summary.get('status') or '')), cr_tracking.normalize_readiness_status(str(summary.get('readiness') or '')), cr_tracking.normalize_gate_status(str(summary.get('gate_status') or '')))
        if str(summary.get('id') or '') != cr_id:
            findings.append('CR_SUMMARY_ID_DIVERGED')
        if str(summary.get('full_ref') or '') != formal_ref:
            findings.append('CR_SUMMARY_FORMAL_REF_DIVERGED')
        if summary_tuple != formal_tuple:
            findings.append('CR_SUMMARY_STATUS_DIVERGED')
    ledger_events = [event for event in load_ledger_events(project_root, resolve_runtime_ref_fn=resolve_runtime_ref) if str(event.get('id') or event.get('cr_id') or '') == cr_id and all((key in event for key in ('status', 'readiness', 'gate_status')))]
    ledger_event = ledger_events[-1] if ledger_events else None
    ledger_event_id = ''
    if ledger_event is None:
        findings.append('CR_LEDGER_STATUS_EVENT_MISSING')
    else:
        ledger_event_id = str(ledger_event.get('event_id') or '')
        ledger_tuple = (cr_tracking.normalize_lifecycle_status(str(ledger_event.get('status') or '')), cr_tracking.normalize_readiness_status(str(ledger_event.get('readiness') or '')), cr_tracking.normalize_gate_status(str(ledger_event.get('gate_status') or '')))
        if not ledger_event_id:
            findings.append('CR_LEDGER_EVENT_ID_MISSING')
        if str(ledger_event.get('full_ref') or '') != formal_ref:
            findings.append('CR_LEDGER_FORMAL_REF_DIVERGED')
        if str(ledger_event.get('summary_ref') or '') != summary_ref:
            findings.append('CR_LEDGER_SUMMARY_REF_DIVERGED')
        if ledger_tuple != formal_tuple:
            findings.append('CR_LEDGER_STATUS_DIVERGED')
    return NativeCRStatusProjectionV1(cr_id=cr_id, lifecycle_status=formal_tuple[0], readiness_status=formal_tuple[1], gate_status=formal_tuple[2], formal_cr_ref=formal_ref, summary_ref=summary_ref, ledger_event_id=ledger_event_id, decision='PASS' if not findings else 'BLOCKED', findings=tuple(findings))

def _atomic_write_text(path: Path, text: str) -> None:
    if path.is_file() and path.read_text(encoding='utf-8') == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    target_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 420
    descriptor, temporary_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(target_mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()

def _transaction_root(project_root: Path, *, process_root: Path | None = None) -> Path:
    process_root = _process_root(project_root) if process_root is None else process_root.resolve()
    common = _git_fact(process_root, 'rev-parse', '--git-common-dir')
    if common:
        path = Path(common)
        common_root = path if path.is_absolute() else process_root / path
    else:
        common_root = process_root / '.meta-flow-fixture-git'
    return common_root.resolve(strict=False) / 'meta-flow' / 'transactions'

def _status_sync_writer_lock_path(
    project_root: Path,
    *,
    transaction_root: Path | None = None,
) -> Path:
    root = _transaction_root(project_root.resolve()) if transaction_root is None else transaction_root
    return root.parent / 'status-sync.lock'

def _acquire_status_sync_writer_lock(
    project_root: Path,
    *,
    transaction_id: str,
    purpose: str,
    transaction_root: Path | None = None,
) -> dict[str, Any] | None:
    """Acquire the cooperative global writer lock and persist owner identity."""
    lock_path = _status_sync_writer_lock_path(
        project_root,
        transaction_root=transaction_root,
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    acquired_at = now_utc()
    owner = {'schema_version': 1, 'owner_token': uuid.uuid4().hex, 'owner_process_identity': f'pid:{os.getpid()}:instance:{uuid.uuid4().hex}', 'owner_started_at': acquired_at, 'acquired_at': acquired_at, 'transaction_id': transaction_id, 'purpose': purpose, 'lease_state': 'held'}
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 384)
    except FileExistsError:
        return None
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(owner, ensure_ascii=False, sort_keys=True) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        lock_path.unlink(missing_ok=True)
        raise
    return owner

def _release_status_sync_writer_lock(
    project_root: Path,
    owner: dict[str, Any],
    *,
    transaction_root: Path | None = None,
) -> bool:
    """Release only the lock whose persisted owner token matches the caller."""
    lock_path = _status_sync_writer_lock_path(
        project_root,
        transaction_root=transaction_root,
    )
    try:
        first_stat = lock_path.stat()
        persisted = json.loads(lock_path.read_text(encoding='utf-8'))
        second_stat = lock_path.stat()
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    if persisted.get('owner_token') != owner.get('owner_token') or persisted.get('owner_process_identity') != owner.get('owner_process_identity') or (first_stat.st_dev, first_stat.st_ino) != (second_stat.st_dev, second_stat.st_ino):
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return False
    return True
