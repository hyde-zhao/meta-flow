"""Work lifecycle-preflight 的零写规则集（STORY-CR075-S01）。

纯函数规则：R1-1（scope vs target 契约）、R2-1（execution contract
revision/ref/digest 逐字段）、R2-2（FAIL 后 blocker/handoff scope 计划）、
close/publication 前置与 verify-packet（CHE-074-CP7）执行前检查。
全部输出 typed findings，不抛 traceback、不产生 mutation。
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Mapping

ACCEPTANCE_HEADINGS: tuple[str, ...] = (
    "## 5. acceptance_criteria",
    "## 量化验收",
    "## 验收标准",
    "## acceptance",
)


def finding(
    check_id: str,
    name: str,
    decision: str,
    *,
    code: str = "",
    detail: str = "",
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": check_id,
        "name": name,
        "decision": decision,
    }
    if code:
        payload["code"] = code
    if detail:
        payload["detail"] = detail
    payload.update(extra)
    return payload


def check_scope_targets(
    allowed_patterns: tuple[str, ...] | list[str],
    target_refs: tuple[str, ...] | list[str],
    *,
    check_id: str = "PREFLIGHT-SCOPE-01",
) -> dict[str, Any]:
    """R1-1：全部计划 target 必须落在 scope 授权写域内。"""

    outside = sorted(
        ref
        for ref in target_refs
        if not any(fnmatch(ref, pattern) or ref == pattern for pattern in allowed_patterns)
    )
    if outside:
        return finding(
            check_id,
            "scope-vs-target contract",
            "BLOCKED",
            code="RECEIPT_TARGET_OUTSIDE_BUSINESS_SCOPE",
            detail="planned targets exceed the Work write scope",
            outside_targets=outside,
            allowed_patterns=sorted(allowed_patterns),
        )
    return finding(
        check_id,
        "scope-vs-target contract",
        "PASS",
        detail=f"{len(list(target_refs))} targets inside scope",
    )


def check_contract_fields(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    fields: tuple[str, ...] = ("revision", "ref", "digest"),
    *,
    check_id: str = "PREFLIGHT-CONTRACT-01",
) -> dict[str, Any]:
    """R2-1：execution contract 的 revision/ref/digest 逐字段校验。"""

    drift = sorted(
        field
        for field in fields
        if str(expected.get(field, "")) != str(actual.get(field, ""))
    )
    if drift:
        return finding(
            check_id,
            "execution contract field parity",
            "BLOCKED",
            code="CONTRACT_FIELD_DRIFT",
            detail="bound contract fields drift from recomputed values",
            drifted_fields=drift,
            expected={field: expected.get(field) for field in drift},
            actual={field: actual.get(field) for field in drift},
        )
    return finding(check_id, "execution contract field parity", "PASS")


def check_fail_handoff_scope(
    allowed_patterns: tuple[str, ...] | list[str],
    handoff_targets: tuple[str, ...] | list[str],
    blockers: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    *,
    check_id: str = "PREFLIGHT-FAIL-01",
) -> dict[str, Any]:
    """R2-2：FAIL 路径的 handoff 计划 target ⊆ scope 且 blocker 记录可计划。"""

    findings: list[dict[str, Any]] = []
    scope_finding = check_scope_targets(allowed_patterns, handoff_targets, check_id=check_id + "-a")
    if scope_finding["decision"] != "PASS":
        findings.append(scope_finding)
    unplannable = [
        dict(blocker)
        for blocker in blockers
        if not str(blocker.get("code") or "") or not str(blocker.get("route") or "")
    ]
    if unplannable:
        findings.append(
            finding(
                check_id + "-b",
                "failure blocker plan",
                "BLOCKED",
                code="BLOCKER_RECORD_INCOMPLETE",
                detail="failure blockers require code and route for a plannable recovery",
                blockers=unplannable,
            )
        )
    if findings:
        merged = findings[0]
        merged["decision"] = "BLOCKED"
        merged.setdefault("detail", "")
        for extra in findings[1:]:
            merged["detail"] = (merged["detail"] + "; " + extra.get("detail", "")).strip("; ")
        return merged
    return finding(
        check_id,
        "failure blocker/handoff scope plan",
        "PASS",
        detail=f"{len(list(handoff_targets))} handoff targets in scope; {len(list(blockers))} blockers plannable",
    )


def check_close_preconditions(
    *,
    current_status: str,
    expected_status: str,
    outcome: str,
    result_ref: str,
    result_exists: bool,
    result_valid: bool,
    result_error: str = "",
    check_id: str = "PREFLIGHT-CLOSE-01",
) -> dict[str, Any]:
    """close/publication 前置：状态机、result_ref 存在与 PASS schema。"""

    problems: list[str] = []
    if outcome not in {"completed", "cancelled"}:
        problems.append("outcome must be completed or cancelled")
    if outcome == "completed":
        if not result_ref:
            problems.append("completed Work requires result_ref")
        elif not result_exists:
            problems.append(f"result missing or not regular: {result_ref}")
        elif not result_valid:
            problems.append(result_error or "result schema mismatch")
    else:
        if result_ref:
            problems.append("cancelled Work must not add result_ref")
    if expected_status != current_status:
        problems.append(f"status drift: expected {expected_status}, current {current_status}")
    if problems:
        return finding(
            check_id,
            "close preconditions",
            "BLOCKED",
            code="CLOSE_PRECONDITION_FAILED",
            detail="; ".join(problems),
        )
    return finding(check_id, "close preconditions", "PASS")


def check_publication_preconditions(
    binding: Mapping[str, Any],
    *,
    work_id: str,
    scope_digest: str,
    result_ref: str,
    expected_release_oid: str,
    actual_release_oid: str,
    check_id: str = "PREFLIGHT-PUBLISH-01",
) -> dict[str, Any]:
    """publication 前置：binding 身份逐字段 + release OID 一致。"""

    problems: list[str] = []
    if str(binding.get("work_id") or "") != work_id:
        problems.append("publication binding work_id mismatch")
    if str(binding.get("scope_digest") or "") != scope_digest:
        problems.append("publication binding scope_digest mismatch")
    if str(binding.get("result_ref") or "") != result_ref:
        problems.append("publication binding result_ref mismatch")
    if expected_release_oid and expected_release_oid != actual_release_oid:
        problems.append(
            f"release OID drift: bound {expected_release_oid[:12]}, current {actual_release_oid[:12]}"
        )
    if problems:
        return finding(
            check_id,
            "publication preconditions",
            "BLOCKED",
            code="PUBLICATION_PRECONDITION_FAILED",
            detail="; ".join(problems),
        )
    return finding(check_id, "publication preconditions", "PASS")


def acceptance_section_items(story_text: str) -> list[str]:
    """CHE-074-CP7：acceptance 标题多形态兼容抽取（编号项或项目符号）。"""

    for heading in ACCEPTANCE_HEADINGS:
        items = _section_items(story_text, heading)
        if items:
            return items
    return []


def _section_items(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = next(
        (index + 1 for index, line in enumerate(lines) if line.strip() == heading),
        None,
    )
    if start is None:
        return []
    items: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        stripped = line.strip()
        match = re.match(r"(?:[-*]|\d+[.)])\s+(.+)$", stripped)
        if match and match.group(1).strip():
            items.append(match.group(1).strip())
    return items


def check_verify_packet_acceptance(
    story_text: str,
    *,
    check_id: str = "PREFLIGHT-PACKET-01",
) -> dict[str, Any]:
    """verify-packet 执行前检查：acceptance 锚缺失 → typed harness finding。"""

    items = acceptance_section_items(story_text)
    if not items:
        return finding(
            check_id,
            "verify-packet acceptance anchors",
            "BLOCKED",
            code="VERIFY_PACKET_ACCEPTANCE_ANCHORS_MISSING",
            detail=(
                "story text has no acceptance bullets under any known heading: "
                + ", ".join(ACCEPTANCE_HEADINGS)
            ),
            mutation_count=0,
        )
    return finding(
        check_id,
        "verify-packet acceptance anchors",
        "PASS",
        detail=f"{len(items)} acceptance anchors",
        anchors=items,
    )


def check_evidence_kinds(
    evaluations: list[Mapping[str, Any]],
    *,
    check_id: str = "PREFLIGHT-EVIDENCE-01",
) -> dict[str, Any]:
    """MF-BUG-15：evidence-kind registry 判定汇总（unknown 不静默降级）。"""

    blocked = [dict(item) for item in evaluations if item.get("decision") == "BLOCKED"]
    review = [dict(item) for item in evaluations if item.get("decision") == "NEEDS_REVIEW"]
    if blocked:
        return finding(
            check_id,
            "evidence-kind registry",
            "BLOCKED",
            code="EVIDENCE_KIND_BLOCKED",
            detail="known kinds with missing capabilities; see evaluations",
            evaluations=[dict(item) for item in evaluations],
        )
    if review:
        return finding(
            check_id,
            "evidence-kind registry",
            "NEEDS_REVIEW",
            code="UNKNOWN_EVIDENCE_KIND",
            detail="unknown evidence kinds require registry classification before retry",
            evaluations=[dict(item) for item in evaluations],
        )
    return finding(
        check_id,
        "evidence-kind registry",
        "PASS",
        detail=f"{len(evaluations)} known kinds evaluated",
    )


def summarize(checks: list[Mapping[str, Any]]) -> str:
    """decision 汇总：任一 BLOCKED→BLOCKED；否则任一 NEEDS_REVIEW→NEEDS_REVIEW；否则 PASS。"""

    decisions = {str(check.get("decision") or "") for check in checks}
    if "BLOCKED" in decisions:
        return "BLOCKED"
    if "NEEDS_REVIEW" in decisions:
        return "NEEDS_REVIEW"
    return "PASS"


def resolve_work_envelope(process_root: Path, work_id: str) -> Any:
    """加载 Work envelope；失败时抛出的 ValueError 由编排层 typed 化。"""

    from meta_flow.work.model import load_work

    return load_work(process_root, work_id)


def logical_ref_exists(process_root: Path, logical_ref: str) -> bool:
    path = process_root / logical_ref
    return path.is_file() and not path.is_symlink()
