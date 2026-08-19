"""关闭后 CR 的跨对象一致性检查。"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from meta_flow.checks import cr_tracking
from meta_flow.design import feature_registry
from meta_flow.project.model import is_safe_ref
from meta_flow.project.process_route import _resolve_runtime_ref, require_process_route
from meta_flow.project.scale import _load_compatible_yaml
from meta_flow.workflow.cr_model import parse_frontmatter

TERMINAL_ISSUE_STATUSES = frozenset(
    {"resolved", "closed", "cancelled", "superseded"}
)
TERMINAL_WORK_STATUSES = frozenset({"completed", "cancelled"})
PASS_DECISIONS = frozenset({"PASS", "PASS_WITH_RISK"})
READY_RELEASE_DECISIONS = frozenset({"READY", "READY_WITH_RISK"})
PUBLIC_OPERATION_DECLARATIONS = (
    ("check.post-close", ("meta-flow", "check", "post-close")),
)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    ref: str


def _load_text(project_root: Path, logical_ref: str) -> tuple[Path | None, str]:
    if not is_safe_ref(logical_ref, prefix="process"):
        return None, ""
    path = _resolve_runtime_ref(project_root, logical_ref)
    if path.is_symlink() or not path.is_file():
        return None, ""
    return path, path.read_text(encoding="utf-8")


def _load_mapping(project_root: Path, logical_ref: str) -> tuple[Path | None, dict[str, Any]]:
    path, text = _load_text(project_root, logical_ref)
    if path is None:
        return None, {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = _load_compatible_yaml(text)
    return path, payload if isinstance(payload, dict) else {}


def _frontmatter_mapping(project_root: Path, logical_ref: str) -> tuple[Path | None, dict[str, Any], str]:
    path, text = _load_text(project_root, logical_ref)
    if path is None:
        return None, {}, ""
    return path, parse_frontmatter(text), text


def _finding(findings: list[Finding], code: str, message: str, ref: str) -> None:
    findings.append(Finding(code=code, message=message, ref=ref))


def _index_item(index: dict[str, Any], cr_id: str) -> dict[str, Any]:
    items = index.get("items")
    if not isinstance(items, list):
        return {}
    return next(
        (
            item
            for item in items
            if isinstance(item, dict) and str(item.get("id") or "") == cr_id
        ),
        {},
    )


def _resolved_capabilities(payload: dict[str, Any]) -> set[str]:
    resolution = payload.get("impact_capability_resolution")
    resolution = resolution if isinstance(resolution, dict) else {}
    results = resolution.get("results")
    if not isinstance(results, list):
        return set()
    return {
        str(item.get("input_ref"))
        for item in results if isinstance(item, dict)
        if item.get("status") == "resolved" and item.get("input_ref")
    }


def check_post_close(
    project_root: Path,
    cr_id: str,
    *,
    release_context_ref: str = "process/release/RELEASE-CONTEXT.yaml",
) -> dict[str, Any]:
    """以 Release Context 的 closure_reconciliation 为清单执行零写检查。"""

    root = project_root.resolve()
    require_process_route(root)
    findings: list[Finding] = []
    checked_refs: set[str] = set()

    release_path, release = _load_mapping(root, release_context_ref)
    checked_refs.add(release_context_ref)
    if release_path is None:
        _finding(findings, "POST_CLOSE_RELEASE_CONTEXT_MISSING", "Release Context 不存在或路径不安全", release_context_ref)
        return _report(cr_id, release_context_ref, checked_refs, findings)
    if str(release.get("cr_id") or "") != cr_id:
        _finding(findings, "POST_CLOSE_RELEASE_OWNER_MISMATCH", "Release Context cr_id 与目标 CR 不一致", release_context_ref)
    if str(release.get("status") or "") != "released_remote_verified_native_closed":
        _finding(findings, "POST_CLOSE_RELEASE_CONTEXT_OPEN", "Release Context 尚未进入 native-closed 终态", release_context_ref)
    execution = release.get("release_execution")
    execution = execution if isinstance(execution, dict) else {}
    if str(execution.get("status") or "") != "RELEASED_REMOTE_VERIFIED_NATIVE_CLOSED":
        _finding(findings, "POST_CLOSE_RELEASE_EXECUTION_OPEN", "release_execution 尚未声明 native close 完成", release_context_ref)

    reconciliation = release.get("closure_reconciliation")
    reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
    if reconciliation.get("schema_version") != 1 or reconciliation.get("status") != "completed":
        _finding(findings, "POST_CLOSE_MANIFEST_INCOMPLETE", "closure_reconciliation 必须是 completed 的 v1 清单", release_context_ref)

    native_close = reconciliation.get("native_close")
    native_close = native_close if isinstance(native_close, dict) else {}
    cr_ref = str(native_close.get("cr_ref") or f"process/changes/{cr_id}.md")
    cr_path, cr_fields, cr_text = _frontmatter_mapping(root, cr_ref)
    checked_refs.add(cr_ref)
    if cr_path is None:
        _finding(findings, "POST_CLOSE_FORMAL_CR_MISSING", "正式 CR 不存在或路径不安全", cr_ref)
    else:
        expected_tuple = ("closed", "READY_WITH_RISK", "cp8_closed")
        actual_tuple = (
            str(cr_fields.get("lifecycle_status") or ""),
            str(cr_fields.get("readiness_status") or ""),
            str(cr_fields.get("gate_status") or ""),
        )
        if actual_tuple != expected_tuple:
            _finding(findings, "POST_CLOSE_CR_TUPLE_MISMATCH", f"正式 CR 终态 tuple 不一致: {actual_tuple}", cr_ref)

    phase_ref = str(native_close.get("phase_ref") or "")
    phase_path, phase = _load_mapping(root, phase_ref) if phase_ref else (None, {})
    if phase_ref:
        checked_refs.add(phase_ref)
    if phase_path is None or str(phase.get("status") or "") != "completed":
        _finding(findings, "POST_CLOSE_PHASE_NOT_COMPLETED", "承载 Phase 未处于 completed", phase_ref or release_context_ref)

    work_refs = native_close.get("work_refs")
    work_refs = work_refs if isinstance(work_refs, list) else []
    if not work_refs:
        _finding(findings, "POST_CLOSE_WORK_BINDING_MISSING", "native_close 未声明 Work refs", release_context_ref)
    for raw_ref in work_refs:
        work_ref = str(raw_ref)
        checked_refs.add(work_ref)
        work_path, work = _load_mapping(root, work_ref)
        if work_path is None or str(work.get("status") or "") not in TERMINAL_WORK_STATUSES:
            _finding(findings, "POST_CLOSE_WORK_NOT_TERMINAL", "Work 未处于 terminal 状态", work_ref)

    current_cp8 = reconciliation.get("current_cp8")
    current_cp8 = current_cp8 if isinstance(current_cp8, dict) else {}
    cp8_result_ref = str(current_cp8.get("result_ref") or "")
    cp8_checkpoint_ref = str(current_cp8.get("checkpoint_ref") or "")
    result_path, result = _load_mapping(root, cp8_result_ref) if cp8_result_ref else (None, {})
    checkpoint_path, checkpoint_fields, _ = (
        _frontmatter_mapping(root, cp8_checkpoint_ref)
        if cp8_checkpoint_ref
        else (None, {}, "")
    )
    checked_refs.update(ref for ref in (cp8_result_ref, cp8_checkpoint_ref) if ref)
    if result_path is None:
        _finding(findings, "POST_CLOSE_CP8_RESULT_MISSING", "current CP8 result 不存在", cp8_result_ref or release_context_ref)
    else:
        if str(result.get("cr_id") or "") != cr_id or str(result.get("checkpoint") or "") != "CP8":
            _finding(findings, "POST_CLOSE_CP8_OWNER_MISMATCH", "current CP8 result owner/checkpoint 不一致", cp8_result_ref)
        if str(result.get("decision") or "").upper() not in PASS_DECISIONS:
            _finding(findings, "POST_CLOSE_CP8_NOT_PASS", "current CP8 result 不是 PASS", cp8_result_ref)
        if str(result.get("release_decision") or "").upper() not in READY_RELEASE_DECISIONS:
            _finding(findings, "POST_CLOSE_CP8_NOT_READY", "current CP8 release_decision 不是 READY", cp8_result_ref)
    if checkpoint_path is None or str(checkpoint_fields.get("status") or "").lower() != "approved":
        _finding(findings, "POST_CLOSE_CP8_HUMAN_GATE_NOT_APPROVED", "current CP8 人工门未 approved", cp8_checkpoint_ref or release_context_ref)
    if cr_text and (cp8_result_ref not in cr_text or cp8_checkpoint_ref not in cr_text):
        _finding(findings, "POST_CLOSE_CP8_CURRENT_BINDING_STALE", "正式 CR 的 CP8 导航未绑定 current result/checkpoint", cr_ref)
    predecessor_refs = current_cp8.get("predecessor_result_refs")
    predecessor_refs = predecessor_refs if isinstance(predecessor_refs, list) else []
    if cp8_result_ref in {str(ref) for ref in predecessor_refs}:
        _finding(findings, "POST_CLOSE_CP8_LINEAGE_ALIAS", "current CP8 不得同时被声明为 predecessor", release_context_ref)
    for raw_ref in predecessor_refs:
        predecessor_ref = str(raw_ref)
        checked_refs.add(predecessor_ref)
        predecessor_path, _ = _load_mapping(root, predecessor_ref)
        if predecessor_path is None:
            _finding(findings, "POST_CLOSE_CP8_PREDECESSOR_MISSING", "predecessor 失败证据未保留", predecessor_ref)

    issue_refs = reconciliation.get("resolved_issue_refs")
    issue_refs = issue_refs if isinstance(issue_refs, list) else []
    if not issue_refs:
        _finding(findings, "POST_CLOSE_ISSUE_BINDING_MISSING", "closure_reconciliation 未声明 resolved issue", release_context_ref)
    for raw_ref in issue_refs:
        issue_ref = str(raw_ref)
        checked_refs.add(issue_ref)
        issue_path, issue_fields, _ = _frontmatter_mapping(root, issue_ref)
        if issue_path is None or str(issue_fields.get("status") or "").lower() not in TERMINAL_ISSUE_STATUSES:
            _finding(findings, "POST_CLOSE_ISSUE_NOT_TERMINAL", "关联 ISSUE 未进入 terminal 状态", issue_ref)

    tracking_ref = str(reconciliation.get("follow_up_tracking_ref") or "")
    tracking_path, tracking_fields, _ = _frontmatter_mapping(root, tracking_ref) if tracking_ref else (None, {}, "")
    if tracking_ref:
        checked_refs.add(tracking_ref)
    if tracking_path is None or str(tracking_fields.get("source_cr") or "") != cr_id:
        _finding(findings, "POST_CLOSE_FOLLOW_UP_OWNER_MISSING", "follow-up tracking 不存在或 source_cr 不匹配", tracking_ref or release_context_ref)
    elif not any(row.lifecycle_status == "candidate" for row in cr_tracking.parse_structured_follow_up_rows(tracking_path)):
        _finding(findings, "POST_CLOSE_FOLLOW_UP_CANDIDATE_MISSING", "follow-up tracking 没有 candidate 行", tracking_ref)

    required_capability_refs = reconciliation.get("required_capability_refs")
    required_capability_refs = [str(ref) for ref in required_capability_refs] if isinstance(required_capability_refs, list) else []
    capability_resolution = feature_registry.resolve_refs(
        root,
        required_capability_refs,
        kind="capability",
        mode="enforce",
    )
    unresolved = [
        item
        for item in capability_resolution.get("results", [])
        if isinstance(item, dict) and item.get("status") != "resolved"
    ]
    if not required_capability_refs or unresolved:
        _finding(findings, "POST_CLOSE_CAPABILITY_UNRESOLVED", f"required capability refs 未完全解析: {len(unresolved)}", "process/docs/design/CAPABILITY-REGISTRY.yaml")

    summary_ref = f"process/changes/summaries/{cr_id}.summary.json"
    index_ref = "process/changes/CR-INDEX.json"
    _, summary = _load_mapping(root, summary_ref)
    _, index = _load_mapping(root, index_ref)
    checked_refs.update({summary_ref, index_ref, "process/docs/design/CAPABILITY-REGISTRY.yaml"})
    if set(required_capability_refs) - _resolved_capabilities(summary):
        _finding(findings, "POST_CLOSE_SUMMARY_CAPABILITY_STALE", "CR summary capability projection 尚未收敛", summary_ref)
    index_entry = _index_item(index, cr_id)
    if set(required_capability_refs) - _resolved_capabilities(index_entry):
        _finding(findings, "POST_CLOSE_INDEX_CAPABILITY_STALE", "CR index capability projection 尚未收敛", index_ref)

    state_ref = "process/state/STATE.current.json"
    _, state = _load_mapping(root, state_ref)
    checked_refs.add(state_ref)
    if str(state.get("active_change") or "") == cr_id:
        _finding(findings, "POST_CLOSE_ACTIVE_CHANGE_STALE", "STATE.active_change 仍指向已关闭 CR", state_ref)

    return _report(cr_id, release_context_ref, checked_refs, findings)


def _report(
    cr_id: str,
    release_context_ref: str,
    checked_refs: set[str],
    findings: list[Finding],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "PostCloseReconciliationCheckV1",
        "cr_id": cr_id,
        "release_context_ref": release_context_ref,
        "decision": "BLOCKED" if findings else "PASS",
        "mutation_count": 0,
        "checked_refs": sorted(ref for ref in checked_refs if ref),
        "finding_count": len(findings),
        "findings": [asdict(item) for item in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate post-close CR/release/checkpoint/follow-up/capability convergence."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--id", dest="cr_id", required=True)
    parser.add_argument(
        "--release-context",
        default="process/release/RELEASE-CONTEXT.yaml",
    )
    parser.add_argument("--format", choices=("json", "text"), default="text")
    args = parser.parse_args(argv)
    try:
        result = check_post_close(
            args.project_root,
            args.cr_id,
            release_context_ref=args.release_context,
        )
    except (OSError, ValueError) as exc:
        result = {
            "schema_version": 1,
            "kind": "PostCloseReconciliationCheckV1",
            "cr_id": args.cr_id,
            "release_context_ref": args.release_context,
            "decision": "CHECK_HARNESS_ERROR",
            "mutation_count": 0,
            "finding_count": 1,
            "findings": [
                {
                    "code": "POST_CLOSE_CHECK_HARNESS_ERROR",
                    "message": str(exc),
                    "ref": args.release_context,
                }
            ],
        }
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{result['decision']}: {args.cr_id}; findings={result['finding_count']}")
        for item in result.get("findings", []):
            print(f"- {item['code']}: {item['message']} [{item['ref']}]")
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
