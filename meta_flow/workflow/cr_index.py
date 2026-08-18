"""CR index, bootstrap and close orchestration leaf."""
# ruff: noqa: I001, F401, UP034
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from meta_flow.project.process_route import _resolve_runtime_ref as resolve_runtime_ref
from meta_flow.project.read_contract import ReadContextProtocol
from meta_flow.project.scale import load_yaml_object
from meta_flow.state import current
from meta_flow.workspace.git_sync import run_git
from meta_flow.workflow.cr_model import CLOSED_GATE_STATUS, CRRecord, now_utc, parse_frontmatter
from meta_flow.workflow.cr_projection import (
    CR_ARCHIVE_ROOT_REL, CR_LEDGER_REL, _atomic_write_text, append_ledger_event,
    summary_from_cr_file, write_evidence_index, write_summary,
)
from meta_flow.workflow.cr_records import (
    CR_SUMMARY_ROOT_REL, LEGACY_SOURCE_REL, _git_fact, _impact_split_payload,
    _normalized_capability_refs, _process_root, _record_required_evidence, _rel as rel,
    discover_formal_crs, record_from_cr_file,
)

CR_INDEX_REL = Path('process/changes/CR-INDEX.json')

INDEX_SCHEMA_VERSION = 1


def load_terminal_predecessor_inventory(
    receipts: list[dict[str, Any]],
    *,
    cr_id: str,
    predecessor_revision_id: str,
    expected_digest: str,
    expected_revision_bytes_digest: str = "",
) -> dict[str, Any]:
    """BL-001 admission: exactly one terminal, digest-bound predecessor receipt."""
    matches = [receipt for receipt in receipts if receipt.get('cr_id') == cr_id and receipt.get('predecessor_revision_id') == predecessor_revision_id]
    if not matches:
        raise ValueError('MISSING_PREDECESSOR_INVENTORY')
    if len(matches) != 1:
        raise ValueError('AMBIGUOUS_PREDECESSOR')
    receipt = matches[0]
    if receipt.get('terminal_status') not in {'verified', 'completed', 'closed'}:
        raise ValueError('NON_TERMINAL_PREDECESSOR')
    inventory = receipt.get('inventory')
    if (
        not isinstance(inventory, list)
        or not inventory
        or inventory != sorted(set(inventory))
        or any(not isinstance(item, str) or not item for item in inventory)
        or receipt.get('inventory_digest') != expected_digest
        or _canonical_digest(inventory) != expected_digest
        or (
            expected_revision_bytes_digest
            and receipt.get('revision_bytes_digest')
            != expected_revision_bytes_digest
        )
    ):
        raise ValueError('STALE_PREDECESSOR_BINDING')
    return dict(receipt)


def rebuild_scope_amend_index(revision: dict[str, Any]) -> dict[str, Any]:
    """A deterministic derived projection, never a separately editable truth."""
    required_v2 = {
        'schema_version', 'cr_id', 'work_id', 'revision_id',
        'predecessor_revision_id', 'predecessor_revision_bytes_digest',
        'scope_digest', 'previous_scope', 'scope', 'invalidated_refs',
        'plan_digest', 'validation_graph_digest',
    }
    required_v3 = required_v2 | {'previous_objective', 'objective'}
    schema_version = revision.get('schema_version')
    if not (
        (schema_version == 2 and set(revision) == required_v2)
        or (schema_version == 3 and set(revision) == required_v3)
    ):
        raise ValueError('INVALID_SCOPE_AMEND_REVISION')
    index = {
        'cr_id': revision['cr_id'],
        'work_id': revision['work_id'],
        'revision_id': revision['revision_id'],
        'scope_digest': revision['scope_digest'],
        'plan_digest': revision['plan_digest'],
        'validation_graph_digest': revision['validation_graph_digest'],
        'predecessor_revision_id': revision['predecessor_revision_id'],
    }
    if schema_version == 3:
        index['objective'] = revision['objective']
        index['objective_transition_digest'] = _canonical_digest(
            {
                'previous_objective': revision['previous_objective'],
                'objective': revision['objective'],
            }
        )
    return index

def _cr_numeric_sort_key(cr_id: str) -> tuple[int, str]:
    match = re.fullmatch('CR-(\\d+)', cr_id)
    return (int(match.group(1)), cr_id) if match else (sys.maxsize, cr_id)

def _canonical_digest(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def _index_item(record: CRRecord, text: str) -> dict[str, Any]:
    return {'id': record.cr_id, 'cr_type': record.cr_type, 'title': record.title, 'status': record.status, 'lifecycle_status': record.status, 'readiness': record.readiness, 'readiness_status': record.readiness, 'gate_status': record.gate_status, 'gate_profile': record.gate_profile, 'full_ref': record.full_ref, 'formal_cr_path': record.full_ref, 'summary_ref': record.summary_ref, 'goal_ref': record.goal_ref, 'goal_statement': record.goal_statement, 'approval_focus': record.approval_focus, 'decision_burden': record.decision_burden, 'conflict_keys': record.conflict_keys, 'impact_surface': record.impact_surface, **_impact_split_payload(record), 'impact_capability_resolution': record.impact_capability_resolution, 'impact_capability_normalized': _normalized_capability_refs(record.impact_capability_resolution), 'authz_policy_refs': record.authz_policy_refs, 'risk_refs': record.risk_refs, 'product_baseline_refresh_required': record.product_baseline_refresh_required, 'required_phase': record.required_phase, 'required_agent': record.required_agent, 'required_gate': record.required_gate, 'block_story_decomposition_until': record.block_story_decomposition_until, 'affected_product_docs': record.affected_product_docs, 'affected_use_cases': record.affected_use_cases, 'routing_design_ref': record.routing_design_ref, 'required_evidence': _record_required_evidence(record, text), 'required_capabilities': record.required_capabilities}

def _record_override(record: CRRecord, updates: dict[str, str]) -> CRRecord:
    fields: dict[str, str] = {}
    if updates.get('lifecycle_status'):
        fields['status'] = updates['lifecycle_status']
    if updates.get('readiness_status'):
        fields['readiness'] = updates['readiness_status']
    if updates.get('gate_status'):
        fields['gate_status'] = updates['gate_status']
    return replace(record, **fields) if fields else record

def _native_cr_minimum(
    project_root: Path,
    *,
    resolver: Any = resolve_runtime_ref,
    read_context: ReadContextProtocol | None = None,
) -> int:
    """Return the project-specific first native CR number.

    Fresh projects default to CR-001.  A migrated project may declare its
    explicit legacy/native boundary in LEGACY-SOURCE.yaml; no project-specific
    number is hard-coded into the reusable builder.
    """
    path = resolver(project_root, LEGACY_SOURCE_REL.as_posix())
    if not path.is_file():
        return 1
    payload = (
        load_yaml_object(path)
        if read_context is None
        else read_context.read_yaml_object(
            LEGACY_SOURCE_REL.as_posix(), loader=load_yaml_object
        )
    )
    value = str(payload.get('native_cr_minimum') or 'CR-001')
    match = re.fullmatch('CR-(\\d+)', value)
    if match is None:
        raise ValueError(f'{LEGACY_SOURCE_REL.as_posix()} native_cr_minimum must use CR-nnn naming')
    return int(match.group(1))

def _validate_native_formal_cr(
    project_root: Path,
    cr_id: str,
    path: Path,
    *,
    minimum: int,
    text: str | None = None,
    rel_fn: Any = rel,
) -> None:
    fields = parse_frontmatter(text if text is not None else path.read_text(encoding='utf-8'))
    problems: list[str] = []
    if str(fields.get('schema_version') or '') != '1':
        problems.append('schema_version=1 is required')
    if str(fields.get('kind') or '') != 'cr':
        problems.append('kind=cr is required')
    if str(fields.get('cr_id') or '') != cr_id:
        problems.append('frontmatter cr_id must exactly match the filename CR id')
    numeric = _cr_numeric_sort_key(cr_id)[0]
    if numeric < minimum:
        problems.append(f'CR number is earlier than native_cr_minimum=CR-{minimum:03d}')
    if problems:
        raise ValueError(f'non-native formal CR contamination at {rel_fn(project_root, path)}: ' + '; '.join(problems))

def build_index(
    project_root: Path,
    *,
    record_overrides: dict[str, dict[str, str]] | None = None,
    read_context: ReadContextProtocol | None = None,
    resolve_runtime_ref_fn: Any | None = None,
    rel_fn: Any | None = None,
    excluded_legacy_paths: frozenset[Path] = frozenset(),
) -> dict[str, Any]:
    """Build a pure projection from formal CR files only.

    Existing CR-INDEX bytes, summaries, ledgers and legacy repositories are
    deliberately not inputs.  ``record_overrides`` is used only by a
    status-sync plan to project its not-yet-applied formal truth.
    """
    project_root = project_root.resolve()
    resolver = resolve_runtime_ref_fn or resolve_runtime_ref
    relative = rel_fn or rel
    items: list[dict[str, Any]] = []
    formal_crs = discover_formal_crs(
        project_root,
        _resolve_runtime_ref_fn=resolver,
        _rel_fn=relative,
        excluded_legacy_paths=excluded_legacy_paths,
    )
    minimum = _native_cr_minimum(
        project_root,
        resolver=resolver,
        read_context=read_context,
    )
    overrides = record_overrides or {}
    for cr_id, path in formal_crs.items():
        text = (
            path.read_text(encoding='utf-8')
            if read_context is None
            else read_context.read_text(relative(project_root, path))
        )
        _validate_native_formal_cr(
            project_root,
            cr_id,
            path,
            minimum=minimum,
            text=text,
            rel_fn=relative,
        )
        record = record_from_cr_file(
            project_root,
            path,
            _rel_fn=relative,
            read_context=read_context,
            text=text,
        )
        record = _record_override(record, overrides.get(cr_id, {}))
        items.append(_index_item(record, text))
    items.sort(key=lambda item: _cr_numeric_sort_key(str(item['id'])))
    semantic = {'schema_version': INDEX_SCHEMA_VERSION, 'items': items}
    return {'schema_version': INDEX_SCHEMA_VERSION, 'generated_at': now_utc(), 'semantic_digest': _canonical_digest(semantic), 'items': items}

def validate_index_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ['CR-INDEX must be a JSON object']
    if payload.get('schema_version') != INDEX_SCHEMA_VERSION:
        errors.append(f'schema_version must be {INDEX_SCHEMA_VERSION}')
    if not isinstance(payload.get('generated_at'), str) or not payload.get('generated_at'):
        errors.append('generated_at must be a non-empty string')
    items = payload.get('items')
    if not isinstance(items, list):
        return [*errors, 'items must be a list']
    required = {'id', 'cr_type', 'title', 'lifecycle_status', 'readiness_status', 'gate_status', 'formal_cr_path', 'summary_ref'}
    ids: list[str] = []
    for offset, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append(f'items[{offset}] must be an object')
            continue
        missing = sorted(required - set(item))
        if missing:
            errors.append(f"items[{offset}] missing fields: {','.join(missing)}")
        item_id = str(item.get('id') or '')
        if not re.fullmatch('CR-\\d+', item_id):
            errors.append(f'items[{offset}].id is invalid: {item_id}')
        ids.append(item_id)
        for key in ('formal_cr_path', 'summary_ref'):
            value = str(item.get(key) or '')
            if not value.startswith('process/') or Path(value).is_absolute() or '..' in Path(value).parts:
                errors.append(f'items[{offset}].{key} must be one safe process/ logical ref')
    if len(ids) != len(set(ids)):
        errors.append('items contain duplicate CR IDs')
    if ids != sorted(ids, key=_cr_numeric_sort_key):
        errors.append('items must be ordered by numeric CR ID')
    expected_digest = _canonical_digest({'schema_version': payload.get('schema_version'), 'items': items})
    if payload.get('semantic_digest') != expected_digest:
        errors.append('semantic_digest does not match schema_version + items')
    return errors

def plan_index(project_root: Path, *, rebuild_corrupt: bool=False) -> dict[str, Any]:
    project_root = project_root.resolve()
    path = resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    try:
        excluded_legacy_paths: frozenset[Path] = frozenset()
        if (project_root / '.meta-flow' / 'workspace.yaml').is_file():
            from meta_flow.workflow.legacy_evidence_registry import (
                load_declared_legacy_evidence_registry,
            )

            legacy_bundle = load_declared_legacy_evidence_registry(
                project_root,
                consumer_id='cr-index',
            )
            excluded_legacy_paths = frozenset(legacy_bundle.evidence_paths)
        expected = build_index(
            project_root,
            excluded_legacy_paths=excluded_legacy_paths,
        )
    except ValueError as exc:
        return {'decision': 'BLOCKED', 'action': 'none', 'mutation_count': 0, 'reason': str(exc), 'index_ref': CR_INDEX_REL.as_posix()}
    expected_digest = str(expected['semantic_digest'])
    if not path.is_file():
        return {'decision': 'READY', 'action': 'create', 'mutation_count': 1, 'semantic_digest': expected_digest, 'index_ref': CR_INDEX_REL.as_posix(), 'expected': expected}
    before_text = path.read_text(encoding='utf-8')
    before_digest = hashlib.sha256(before_text.encode('utf-8')).hexdigest()
    try:
        existing = json.loads(before_text)
    except json.JSONDecodeError as exc:
        if not rebuild_corrupt:
            return {'decision': 'BLOCKED', 'action': 'none', 'mutation_count': 0, 'reason': f'CR-INDEX invalid JSON; use explicit --rebuild: {exc}', 'before_bytes_digest': before_digest, 'index_ref': CR_INDEX_REL.as_posix()}
        existing = None
    existing_errors = validate_index_payload(existing) if existing is not None else []
    if existing_errors and (not rebuild_corrupt):
        return {'decision': 'BLOCKED', 'action': 'none', 'mutation_count': 0, 'reason': '; '.join(existing_errors), 'before_bytes_digest': before_digest, 'index_ref': CR_INDEX_REL.as_posix()}
    if isinstance(existing, dict) and existing.get('semantic_digest') == expected_digest:
        return {'decision': 'READY', 'action': 'noop', 'mutation_count': 0, 'semantic_digest': expected_digest, 'before_bytes_digest': before_digest, 'index_ref': CR_INDEX_REL.as_posix(), 'expected': expected}
    if not rebuild_corrupt:
        return {'decision': 'BLOCKED', 'action': 'none', 'mutation_count': 0, 'reason': 'CR-INDEX stale projection differs from formal truth; use explicit --rebuild', 'semantic_digest': expected_digest, 'existing_semantic_digest': str(existing.get('semantic_digest') or '') if isinstance(existing, dict) else '', 'before_bytes_digest': before_digest, 'index_ref': CR_INDEX_REL.as_posix()}
    return {'decision': 'READY', 'action': 'rebuild', 'mutation_count': 1, 'semantic_digest': expected_digest, 'before_bytes_digest': before_digest, 'index_ref': CR_INDEX_REL.as_posix(), 'expected': expected}

def write_index(project_root: Path, *, rebuild_corrupt: bool=False, expected_process_oid: str='') -> Path:
    project_root = project_root.resolve()
    path = resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix())
    plan = plan_index(project_root, rebuild_corrupt=rebuild_corrupt)
    if plan['decision'] != 'READY':
        raise ValueError(str(plan.get('reason') or 'CR-INDEX plan is blocked'))
    if expected_process_oid:
        process_root = _process_root(project_root)
        actual = run_git(['rev-parse', '--verify', 'HEAD'], cwd=process_root)
        if not actual.ok or actual.stdout.strip() != expected_process_oid:
            raise ValueError('process HEAD differs from expected_process_oid')
    if plan['mutation_count']:
        text = json.dumps(plan['expected'], ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        _atomic_write_text(path, text)
    return path

def load_index(project_root: Path, *, resolve_runtime_ref_fn: Any | None = None) -> dict[str, Any]:
    resolver = resolve_runtime_ref_fn or resolve_runtime_ref
    path = resolver(project_root, CR_INDEX_REL.as_posix())
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise ValueError(f'{path} invalid JSON: {exc}') from exc

def _write_bootstrap_cr_file(project_root: Path, *, cr_id: str, title: str, scope: str, gate_status: str, readiness: str) -> Path:
    if not re.fullmatch('CR-\\d{3,}', cr_id):
        raise ValueError('bootstrap CR id must use CR-xxx naming, for example CR-001')
    path = resolve_runtime_ref(project_root, f'process/changes/{cr_id}.md')
    if path.exists():
        raise FileExistsError(f'CR already exists: {path}')
    created_at = now_utc()
    text = f'---\nschema_version: 1\nkind: cr\ncr_id: "{cr_id}"\ncr_type: "process"\ntitle: "{title}"\nlifecycle_status: "active"\nreadiness_status: "{readiness}"\ngate_status: "{gate_status}"\ngate_profile: "standard"\nconflict_keys: ["bootstrap", "adoption-readiness"]\nimpact_surface: ["process", "workspace", "state", "context", "human-gate"]\nauthz_policy_refs: ["NO_CREDENTIAL_READ", "NO_RUNTIME", "NO_PRODUCTION_WRITE", "NO_TRADING"]\nrisk_refs: []\ncreated_at: "{created_at}"\ncreated_by: "meta-flow cr bootstrap"\n---\n\n# {cr_id} {title}\n\n## 变更描述\n\n{scope}\n\n## 不授权范围\n\n- credentials / secret / account read\n- runtime / SaaS / production write\n- trading / live / publish\n- CR-033 runtime trace follow-up activation\n\n## 启动约束\n\n- Formal CR IDs must use `CR-xxx`; `MF-xxx` is historical alias only.\n- Business remediation starts only after CP0/context/human gate readiness is reviewed.\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path

def _update_current_active_change(project_root: Path, cr_id: str, context_ref: str) -> None:
    current.update_current_state(project_root, {'active_change': cr_id, 'active_context_ref': context_ref, 'current_phase': 'init', 'next_action': {'type': 'cp0_ready', 'text': f'Review CP0 bootstrap readiness for {cr_id}, then launch the first human gate.'}, 'updated_at': now_utc()}, actor='meta_flow.workflow.cr_lifecycle', reason='bootstrap active change')

def _write_cp0_result(project_root: Path, cr_id: str, context_ref: str) -> Path:
    result_path = resolve_runtime_ref(project_root, f'process/checks/CP0-{cr_id}-BOOTSTRAP.result.json')
    result = {'schema_version': 1, 'checkpoint': 'CP0', 'cr_id': cr_id, 'decision': 'PASS', 'context_ref': context_ref, 'evidence_ref': '', 'dispatch_refs': [], 'items': [{'id': 'CP0-BS-01', 'name': 'workspace/state/bootstrap artifacts exist', 'status': 'PASS', 'severity': 'INFO', 'evidence_refs': ['process/state/STATE.current.json', 'process/changes/CR-INDEX.json', context_ref]}, {'id': 'CP0-BS-02', 'name': 'runtime and credential actions are not authorized', 'status': 'PASS', 'severity': 'INFO', 'evidence_refs': [(CR_SUMMARY_ROOT_REL / f'{cr_id}.summary.json').as_posix()]}], 'blockers': [], 'waivers': [], 'next_route': 'human_gate', 'checked_at': now_utc()}
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return result_path

def bootstrap_cr(
    project_root: Path,
    *,
    cr_id: str,
    title: str,
    scope: str,
    gate_status: str = 'cp2_pending',
    readiness: str = 'READY',
    rebuild_corrupt: bool = False,
) -> dict[str, Path]:
    project_root = project_root.resolve()
    from meta_flow.context_pack import builder
    from meta_flow.policies import failure_routing
    failure_routing.write_default_failure_routing_policy(project_root)
    failure_routing.write_default_waiver_policy(project_root)
    cr_path = _write_bootstrap_cr_file(project_root, cr_id=cr_id, title=title, scope=scope, gate_status=gate_status, readiness=readiness)
    summary = summary_from_cr_file(project_root, cr_path)
    summary_path = write_summary(project_root, cr_id, summary)
    evidence_path = write_evidence_index(project_root, cr_id, summary)
    index_path = write_index(project_root, rebuild_corrupt=rebuild_corrupt)
    context, context_path = builder.build_context_pack(project_root, stage='CP0', profile='adoption-bootstrap', cr_id=cr_id)
    context_ref = rel(project_root, context_path)
    _update_current_active_change(project_root, cr_id, context_ref)
    try:
        current.render_state_file(project_root, force=False)
    except FileExistsError:
        pass
    cp0_result_path = _write_cp0_result(project_root, cr_id, context_ref)
    cp0_summary_path = cp0_result_path.with_suffix('.summary.md')
    from meta_flow.checks import cp_result
    if cp0_summary_path.exists() or cp0_summary_path.is_symlink():
        raise FileExistsError(
            f'bootstrap CP0 summary target already exists: {cp0_summary_path}'
        )
    _atomic_write_text(
        cp0_summary_path,
        cp_result.render_summary(
            json.loads(cp0_result_path.read_text(encoding='utf-8'))
        ),
    )
    ledger_path = append_ledger_event(project_root, {'event': 'active', 'id': cr_id, 'cr_type': summary.get('cr_type'), 'status': 'active', 'readiness': summary.get('readiness'), 'summary_ref': rel(project_root, summary_path), 'full_ref': summary.get('full_ref'), 'evidence_index_ref': rel(project_root, evidence_path), 'context_ref': context_ref, 'cp0_result_ref': rel(project_root, cp0_result_path), 'created_at': now_utc()})
    return {'cr': cr_path, 'summary': summary_path, 'evidence_index': evidence_path, 'index': index_path, 'context': context_path, 'cp0_result': cp0_result_path, 'cp0_summary': cp0_summary_path, 'ledger': ledger_path}

def close_cr(project_root: Path, cr_id: str, *, readiness: str, work_id: str, effective_at: str, expected_process_oid: str, expected_plan_digest: str, authorization: Any | None, plan_status_sync: Any, apply_status_sync: Any, append_ledger_event: Any, resolve_runtime_ref: Any, rel: Any, current_state_updater: Any, discover_formal_crs_fn: Any | None = None) -> dict[str, Path]:
    """Compatibility API routed through the typed status-sync transaction."""
    discover = discover_formal_crs_fn or discover_formal_crs
    plan = plan_status_sync(project_root, cr_id, status='closed', readiness=readiness, gate_status=CLOSED_GATE_STATUS, work_id=work_id, expected_process_oid=expected_process_oid, effective_at=effective_at)
    result = apply_status_sync(project_root, plan, authorization=authorization, expected_plan_digest=expected_plan_digest)
    if result['status'] not in {'PASS', 'NO_CHANGE'}:
        raise RuntimeError(f"close {result['status']}: {result.get('reason', '')}")
    if result['status'] == 'NO_CHANGE':
        cr_path = discover(project_root)[cr_id]
        return {'cr': cr_path, 'summary': resolve_runtime_ref(project_root, (CR_SUMMARY_ROOT_REL / f'{cr_id}.summary.json').as_posix()), 'evidence_index': resolve_runtime_ref(project_root, (CR_ARCHIVE_ROOT_REL / cr_id / 'evidence-index.json').as_posix()), 'index': resolve_runtime_ref(project_root, CR_INDEX_REL.as_posix()), 'ledger': resolve_runtime_ref(project_root, CR_LEDGER_REL.as_posix())}
    by_ref = result['paths']
    return {'cr': by_ref[rel(project_root, discover(project_root)[cr_id])], 'summary': by_ref[(CR_SUMMARY_ROOT_REL / f'{cr_id}.summary.json').as_posix()], 'evidence_index': by_ref[(CR_ARCHIVE_ROOT_REL / cr_id / 'evidence-index.json').as_posix()], 'index': by_ref[CR_INDEX_REL.as_posix()], 'ledger': by_ref[CR_LEDGER_REL.as_posix()]}

def _dirty_path_digest(root: Path) -> str:
    result = run_git(['status', '--porcelain=v1', '--untracked-files=all'], cwd=root)
    if not result.ok:
        return _canonical_digest([])
    return _canonical_digest(sorted((line for line in result.stdout.splitlines() if line)))
