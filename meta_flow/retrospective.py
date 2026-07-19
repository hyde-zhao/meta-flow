"""证据化项目/阶段复盘：只形成事实、判断和改进候选，不授权自修改。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from meta_flow.project.model import is_safe_ref
from meta_flow.project.scale import dump_yaml, load_yaml_object

RETROSPECTIVE_SCHEMA_VERSION = 1
RETROSPECTIVE_MAX_BYTES = 128 * 1024
RETROSPECTIVE_DIMENSIONS = (
    "value_outcome",
    "process_conformance_evidence",
    "quality_risk_recovery",
    "flow_efficiency",
    "token_context",
    "meta_flow_fit",
)
MEASUREMENT_QUALITIES = {"measured", "proxy", "unavailable"}
RETROSPECTIVE_STATUSES = {"draft", "facts_confirmed"}
SCOPE_KINDS = {"project", "release_slice", "phase", "work_set"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class StageUsage:
    stage: str
    measurement_quality: str
    tokens: int | None
    reads: int
    writes: int
    check_groups: int
    budget_tokens: int | None = None
    proxy_method: str = ""
    unavailable_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class RetrospectiveDimension:
    dimension_id: str
    measurement_quality: str
    facts: tuple[str, ...]
    inferences: tuple[str, ...]
    human_judgments: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    conclusion: str

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "facts": list(self.facts),
            "inferences": list(self.inferences),
            "human_judgments": list(self.human_judgments),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class ImprovementCandidate:
    candidate_id: str
    objective: str
    problem: str
    applicability: str
    evidence_refs: tuple[str, ...]
    expected_benefit: str
    risks: tuple[str, ...]
    restart_condition: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "evidence_refs": list(self.evidence_refs),
            "risks": list(self.risks),
        }


@dataclass(frozen=True)
class Retrospective:
    retro_id: str
    project_id: str
    scope_kind: str
    scope_ref: str
    window_start: str
    window_end: str
    frozen_at: str
    approver_summary: str
    dimensions: tuple[RetrospectiveDimension, ...]
    stage_usage: tuple[StageUsage, ...]
    candidates: tuple[ImprovementCandidate, ...]
    residual_risks: tuple[str, ...]
    evidence_quality_summary: str
    status: str = "draft"
    facts_confirmation_ref: str = ""
    implementation_authorized: bool = False
    publication_authorized: bool = False
    recursive_evolution_authorized: bool = False

    @property
    def ref(self) -> str:
        return f"retrospectives/{self.retro_id}.yaml"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RETROSPECTIVE_SCHEMA_VERSION,
            "retro_id": self.retro_id,
            "project_id": self.project_id,
            "scope_kind": self.scope_kind,
            "scope_ref": self.scope_ref,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "frozen_at": self.frozen_at,
            "approver_summary": self.approver_summary,
            "dimensions": [item.as_dict() for item in self.dimensions],
            "stage_usage": [item.as_dict() for item in self.stage_usage],
            "improvement_candidates": [item.as_dict() for item in self.candidates],
            "residual_risks": list(self.residual_risks),
            "evidence_quality_summary": self.evidence_quality_summary,
            "status": self.status,
            "facts_confirmation_ref": self.facts_confirmation_ref,
            "authorization_boundaries": {
                "implementation_authorized": self.implementation_authorized,
                "publication_authorized": self.publication_authorized,
                "recursive_evolution_authorized": self.recursive_evolution_authorized,
            },
        }


def _bounded_text(value: Any, *, label: str, max_length: int = 4_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length or "\x00" in value:
        raise ValueError(f"{label} must be a non-empty bounded string")
    return value


def _bounded_lines(values: Any, *, label: str, maximum: int = 50) -> tuple[str, ...]:
    if not isinstance(values, list | tuple) or len(values) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} entries")
    return tuple(_bounded_text(value, label=label, max_length=1_000) for value in values)


def _safe_refs(values: Any, *, label: str, required: bool = False) -> tuple[str, ...]:
    refs = _bounded_lines(values, label=label)
    if required and not refs:
        raise ValueError(f"{label} must not be empty")
    if not all(is_safe_ref(ref) for ref in refs):
        raise ValueError(f"{label} must contain safe process-repo-relative refs")
    return refs


def validate_stage_usage(item: StageUsage) -> None:
    _bounded_text(item.stage, label="stage", max_length=128)
    if item.measurement_quality not in MEASUREMENT_QUALITIES:
        raise ValueError("stage usage measurement_quality is invalid")
    for label, value in (
        ("reads", item.reads),
        ("writes", item.writes),
        ("check_groups", item.check_groups),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"stage usage {label} must be a non-negative integer")
    if item.measurement_quality == "unavailable":
        if item.tokens is not None or not item.unavailable_reason:
            raise ValueError("unavailable token usage requires tokens=null and a reason")
    elif type(item.tokens) is not int or item.tokens < 0:
        raise ValueError("measured/proxy token usage requires a non-negative token value")
    if item.measurement_quality == "proxy" and not item.proxy_method:
        raise ValueError("proxy token usage requires proxy_method")
    if item.budget_tokens is not None and (
        type(item.budget_tokens) is not int or item.budget_tokens <= 0
    ):
        raise ValueError("stage usage budget_tokens must be null or a positive integer")


def validate_retrospective(retro: Retrospective) -> None:
    for label, value in (("retro_id", retro.retro_id), ("project_id", retro.project_id)):
        if not _ID_RE.fullmatch(value):
            raise ValueError(f"{label} is invalid")
    if retro.scope_kind not in SCOPE_KINDS or not is_safe_ref(retro.scope_ref):
        raise ValueError("retrospective scope_kind/scope_ref is invalid")
    for label, value in (
        ("window_start", retro.window_start),
        ("window_end", retro.window_end),
        ("frozen_at", retro.frozen_at),
        ("approver_summary", retro.approver_summary),
        ("evidence_quality_summary", retro.evidence_quality_summary),
    ):
        _bounded_text(value, label=label)
    dimension_ids = tuple(item.dimension_id for item in retro.dimensions)
    if dimension_ids != RETROSPECTIVE_DIMENSIONS:
        raise ValueError("retrospective must contain the six dimensions in canonical order")
    for item in retro.dimensions:
        if item.measurement_quality not in MEASUREMENT_QUALITIES:
            raise ValueError(f"dimension {item.dimension_id} measurement_quality is invalid")
        _bounded_lines(item.facts, label=f"{item.dimension_id}.facts")
        _bounded_lines(item.inferences, label=f"{item.dimension_id}.inferences")
        _bounded_lines(item.human_judgments, label=f"{item.dimension_id}.human_judgments")
        _safe_refs(item.evidence_refs, label=f"{item.dimension_id}.evidence_refs")
        _bounded_text(item.conclusion, label=f"{item.dimension_id}.conclusion")
        if item.measurement_quality == "unavailable" and item.facts:
            raise ValueError(f"unavailable dimension {item.dimension_id} cannot claim measured facts")
    for item in retro.stage_usage:
        validate_stage_usage(item)
    candidate_ids: set[str] = set()
    for item in retro.candidates:
        if not _ID_RE.fullmatch(item.candidate_id) or item.candidate_id in candidate_ids:
            raise ValueError("improvement candidate IDs must be unique safe IDs")
        candidate_ids.add(item.candidate_id)
        if item.applicability not in {"project-local", "meta-flow-common", "evidence-insufficient"}:
            raise ValueError("improvement candidate applicability is invalid")
        for label, value in (
            ("objective", item.objective),
            ("problem", item.problem),
            ("expected_benefit", item.expected_benefit),
        ):
            _bounded_text(value, label=f"candidate.{label}")
        _safe_refs(item.evidence_refs, label="candidate.evidence_refs", required=True)
        _bounded_lines(item.risks, label="candidate.risks")
    _bounded_lines(retro.residual_risks, label="residual_risks")
    if retro.status not in RETROSPECTIVE_STATUSES:
        raise ValueError("retrospective status is invalid")
    if retro.status == "facts_confirmed" and not is_safe_ref(retro.facts_confirmation_ref):
        raise ValueError("facts_confirmed retrospective requires a safe confirmation ref")
    if retro.status == "draft" and retro.facts_confirmation_ref:
        raise ValueError("draft retrospective cannot claim a facts confirmation")
    if (
        retro.implementation_authorized is not False
        or retro.publication_authorized is not False
        or retro.recursive_evolution_authorized is not False
    ):
        raise ValueError("a retrospective report cannot authorize implementation/publication/recursion")


def retrospective_from_payload(payload: dict[str, Any]) -> Retrospective:
    allowed = {
        "schema_version",
        "retro_id",
        "project_id",
        "scope_kind",
        "scope_ref",
        "window_start",
        "window_end",
        "frozen_at",
        "approver_summary",
        "dimensions",
        "stage_usage",
        "improvement_candidates",
        "residual_risks",
        "evidence_quality_summary",
        "status",
        "facts_confirmation_ref",
        "authorization_boundaries",
    }
    if set(payload) != allowed or payload.get("schema_version") != RETROSPECTIVE_SCHEMA_VERSION:
        raise ValueError("retrospective schema contains missing or unknown fields")
    dimensions_payload = payload.get("dimensions")
    usage_payload = payload.get("stage_usage")
    candidates_payload = payload.get("improvement_candidates")
    boundaries = payload.get("authorization_boundaries")
    if not isinstance(dimensions_payload, list) or not all(
        isinstance(item, dict) for item in dimensions_payload
    ):
        raise ValueError("retrospective dimensions must be a list of objects")
    if not isinstance(usage_payload, list) or not all(isinstance(item, dict) for item in usage_payload):
        raise ValueError("retrospective stage_usage must be a list of objects")
    if not isinstance(candidates_payload, list) or not all(
        isinstance(item, dict) for item in candidates_payload
    ):
        raise ValueError("retrospective candidates must be a list of objects")
    if not isinstance(boundaries, dict) or set(boundaries) != {
        "implementation_authorized",
        "publication_authorized",
        "recursive_evolution_authorized",
    }:
        raise ValueError("retrospective authorization boundaries are invalid")
    dimension_fields = {
        "dimension_id",
        "measurement_quality",
        "facts",
        "inferences",
        "human_judgments",
        "evidence_refs",
        "conclusion",
    }
    usage_fields = {
        "stage",
        "measurement_quality",
        "tokens",
        "reads",
        "writes",
        "check_groups",
        "budget_tokens",
        "proxy_method",
        "unavailable_reason",
    }
    candidate_fields = {
        "candidate_id",
        "objective",
        "problem",
        "applicability",
        "evidence_refs",
        "expected_benefit",
        "risks",
        "restart_condition",
    }
    if any(set(item) != dimension_fields for item in dimensions_payload):
        raise ValueError("retrospective dimension schema contains missing or unknown fields")
    if any(set(item) != usage_fields for item in usage_payload):
        raise ValueError("retrospective stage_usage schema contains missing or unknown fields")
    if any(set(item) != candidate_fields for item in candidates_payload):
        raise ValueError("retrospective candidate schema contains missing or unknown fields")
    dimensions = tuple(
        RetrospectiveDimension(
            dimension_id=str(item.get("dimension_id") or ""),
            measurement_quality=str(item.get("measurement_quality") or ""),
            facts=_bounded_lines(item.get("facts"), label="dimension.facts"),
            inferences=_bounded_lines(item.get("inferences"), label="dimension.inferences"),
            human_judgments=_bounded_lines(
                item.get("human_judgments"), label="dimension.human_judgments"
            ),
            evidence_refs=_safe_refs(item.get("evidence_refs"), label="dimension.evidence_refs"),
            conclusion=str(item.get("conclusion") or ""),
        )
        for item in dimensions_payload
    )
    usage = tuple(
        StageUsage(
            stage=str(item.get("stage") or ""),
            measurement_quality=str(item.get("measurement_quality") or ""),
            tokens=item.get("tokens"),
            reads=item.get("reads"),
            writes=item.get("writes"),
            check_groups=item.get("check_groups"),
            budget_tokens=item.get("budget_tokens"),
            proxy_method=str(item.get("proxy_method") or ""),
            unavailable_reason=str(item.get("unavailable_reason") or ""),
        )
        for item in usage_payload
    )
    candidates = tuple(
        ImprovementCandidate(
            candidate_id=str(item.get("candidate_id") or ""),
            objective=str(item.get("objective") or ""),
            problem=str(item.get("problem") or ""),
            applicability=str(item.get("applicability") or ""),
            evidence_refs=_safe_refs(item.get("evidence_refs"), label="candidate.evidence_refs"),
            expected_benefit=str(item.get("expected_benefit") or ""),
            risks=_bounded_lines(item.get("risks"), label="candidate.risks"),
            restart_condition=str(item.get("restart_condition") or ""),
        )
        for item in candidates_payload
    )
    retro = Retrospective(
        retro_id=str(payload.get("retro_id") or ""),
        project_id=str(payload.get("project_id") or ""),
        scope_kind=str(payload.get("scope_kind") or ""),
        scope_ref=str(payload.get("scope_ref") or ""),
        window_start=str(payload.get("window_start") or ""),
        window_end=str(payload.get("window_end") or ""),
        frozen_at=str(payload.get("frozen_at") or ""),
        approver_summary=str(payload.get("approver_summary") or ""),
        dimensions=dimensions,
        stage_usage=usage,
        candidates=candidates,
        residual_risks=_bounded_lines(payload.get("residual_risks"), label="residual_risks"),
        evidence_quality_summary=str(payload.get("evidence_quality_summary") or ""),
        status=str(payload.get("status") or ""),
        facts_confirmation_ref=str(payload.get("facts_confirmation_ref") or ""),
        implementation_authorized=boundaries.get("implementation_authorized"),
        publication_authorized=boundaries.get("publication_authorized"),
        recursive_evolution_authorized=boundaries.get("recursive_evolution_authorized"),
    )
    validate_retrospective(retro)
    return retro


def retrospective_path(process_root: Path, retro_id: str) -> Path:
    if not _ID_RE.fullmatch(retro_id):
        raise ValueError("retro_id is invalid")
    return process_root.resolve() / "retrospectives" / f"{retro_id}.yaml"


def retrospective_report_path(process_root: Path, retro_id: str) -> Path:
    return retrospective_path(process_root, retro_id).with_suffix(".md")


def render_retrospective_markdown(retro: Retrospective) -> str:
    validate_retrospective(retro)
    lines = [
        f"# 项目复盘总结：{retro.retro_id}",
        "",
        "## 审批者摘要",
        "",
        retro.approver_summary,
        "",
        "## 复盘范围",
        "",
        f"- 项目：`{retro.project_id}`",
        f"- 范围：`{retro.scope_kind}` / `{retro.scope_ref}`",
        f"- 冻结窗口：`{retro.window_start}` 至 `{retro.window_end}`；冻结于 `{retro.frozen_at}`",
        "",
        "## 六维结论",
        "",
    ]
    for item in retro.dimensions:
        lines.extend(
            [
                f"### {item.dimension_id}",
                "",
                f"测量质量：`{item.measurement_quality}`",
                "",
                f"结论：{item.conclusion}",
                "",
                "- 事实：" + ("；".join(item.facts) if item.facts else "无可验证事实"),
                "- 推断：" + ("；".join(item.inferences) if item.inferences else "无"),
                "- 待人工判断：" + ("；".join(item.human_judgments) if item.human_judgments else "无"),
                "- 证据：" + ("、".join(f"`{ref}`" for ref in item.evidence_refs) if item.evidence_refs else "无"),
                "",
            ]
        )
    lines.extend(["## 各阶段资源消耗", ""])
    for item in retro.stage_usage:
        token_text = "unavailable" if item.tokens is None else str(item.tokens)
        lines.append(
            f"- `{item.stage}`：token={token_text} (`{item.measurement_quality}`)，"
            f"reads={item.reads}，writes={item.writes}，checks={item.check_groups}"
        )
    lines.extend(["", "## Meta Flow 改进候选", ""])
    for item in retro.candidates:
        lines.append(
            f"- `{item.candidate_id}` [{item.applicability}] {item.objective}；证据："
            + "、".join(f"`{ref}`" for ref in item.evidence_refs)
        )
    if not retro.candidates:
        lines.append("- 无")
    lines.extend(
        [
            "",
            "## 剩余风险与证据质量",
            "",
            "- 剩余风险：" + ("；".join(retro.residual_risks) if retro.residual_risks else "无"),
            f"- 证据质量：{retro.evidence_quality_summary}",
            "",
            "## 授权边界",
            "",
            "本报告只形成复盘事实、推断、人工判断和改进候选；不授权实现、commit、push、production 写入或递归自进化。",
            "",
        ]
    )
    return "\n".join(lines)


def write_retrospective_create_only(
    process_root: Path,
    retro: Retrospective,
) -> tuple[Path, Path]:
    validate_retrospective(retro)
    data_path = retrospective_path(process_root, retro.retro_id)
    report_path = retrospective_report_path(process_root, retro.retro_id)
    if data_path.exists() or data_path.is_symlink() or report_path.exists() or report_path.is_symlink():
        raise FileExistsError("retrospective data/report already exists")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(dump_yaml(retro.as_dict()) + "\n", encoding="utf-8")
    try:
        report_path.write_text(render_retrospective_markdown(retro), encoding="utf-8")
    except Exception:
        data_path.unlink()
        raise
    return data_path, report_path


def load_retrospective(process_root: Path, retro_id: str) -> Retrospective:
    path = retrospective_path(process_root, retro_id)
    if path.stat().st_size > RETROSPECTIVE_MAX_BYTES:
        raise ValueError("retrospective exceeds byte budget")
    return retrospective_from_payload(load_yaml_object(path))


def confirm_retrospective_facts(
    process_root: Path,
    retro_id: str,
    *,
    confirmation_ref: str,
) -> Retrospective:
    if not is_safe_ref(confirmation_ref):
        raise ValueError("confirmation_ref must be a safe process-repo-relative ref")
    current = load_retrospective(process_root, retro_id)
    if current.status != "draft":
        raise ValueError("retrospective facts can only be confirmed from draft")
    updated = replace(
        current,
        status="facts_confirmed",
        facts_confirmation_ref=confirmation_ref,
    )
    validate_retrospective(updated)
    data_path = retrospective_path(process_root, retro_id)
    report_path = retrospective_report_path(process_root, retro_id)
    decision_path = process_root.resolve() / confirmation_ref
    if decision_path.exists() or decision_path.is_symlink():
        raise FileExistsError("retrospective facts confirmation record already exists")
    temporary_data = data_path.with_name(f".{data_path.name}.tmp")
    temporary_report = report_path.with_name(f".{report_path.name}.tmp")
    temporary_decision = decision_path.with_name(f".{decision_path.name}.tmp")
    if temporary_data.exists() or temporary_report.exists() or temporary_decision.exists():
        raise FileExistsError("temporary retrospective confirmation path exists")
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_data.write_text(dump_yaml(updated.as_dict()) + "\n", encoding="utf-8")
    temporary_report.write_text(render_retrospective_markdown(updated), encoding="utf-8")
    temporary_decision.write_text(
        dump_yaml(
            {
                "schema_version": 1,
                "decision_type": "retrospective_facts_confirmation",
                "retro_id": retro_id,
                "decision": "confirmed",
                "implementation_authorized": False,
                "publication_authorized": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        # 先放置人类视图和决策证据，最后替换机器真相；失败时不会让机器真相声称已确认。
        os.replace(temporary_report, report_path)
        os.replace(temporary_decision, decision_path)
        os.replace(temporary_data, data_path)
    finally:
        for temporary in (temporary_data, temporary_report, temporary_decision):
            if temporary.exists() or temporary.is_symlink():
                temporary.unlink()
    return load_retrospective(process_root, retro_id)
