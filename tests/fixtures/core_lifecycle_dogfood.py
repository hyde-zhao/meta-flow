"""在隔离双仓中执行 Meta Flow 的多 Work 核心生命周期自举验证夹具。"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from typing import Any

from meta_flow import cli as meta_flow_cli
from meta_flow.execution_control.contract import ExecutionUnitV1
from meta_flow.project.governance import (
    Phase,
    Roadmap,
    load_phase,
    write_phase_create_only,
    write_roadmap_create_only,
)
from meta_flow.project.governance_projection import (
    GOVERNANCE_PROJECTION_REL,
    ImmutableCommitRole,
    build_governance_projection,
    validate_governance_projection,
)
from meta_flow.project.model import load_project, replace_project
from meta_flow.project.onboarding import (
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND as PROJECT_AUTHORIZATION_KIND,
)
from meta_flow.project.onboarding_contract import AUTHORIZATION_SOURCE, OnboardingAuthorization
from meta_flow.state import current as state_current
from meta_flow.work.lifecycle import update_work_status
from meta_flow.work.lifecycle_transaction import (
    AUTHORIZATION_KIND as WORK_CLOSE_AUTHORIZATION_KIND,
)
from meta_flow.work.lifecycle_transaction import plan_work_close
from meta_flow.work.model import build_work
from meta_flow.work.risk import RiskFacts, classify_work
from meta_flow.work.scope import WorkScope
from meta_flow.work.store import apply_work_init, plan_work_init_from_release_root
from meta_flow.workflow import cr_lifecycle


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _invoke_cli(name: str, arguments: list[str]) -> str:
    """经过 ``meta_flow.cli`` 顶层路由执行命令，并隔离输出。"""

    output = io.StringIO()
    errors = io.StringIO()
    previous_argv = sys.argv
    sys.argv = ["meta-flow", *arguments]
    try:
        with redirect_stdout(output), redirect_stderr(errors):
            try:
                meta_flow_cli.main()
            except SystemExit as exc:
                exit_code = 0 if exc.code in (None, 0) else int(exc.code)
            else:
                exit_code = 0
    finally:
        sys.argv = previous_argv
    if exit_code != 0:
        detail = errors.getvalue().strip() or output.getvalue().strip()
        raise ValueError(f"{name} failed with exit code {exit_code}: {detail}")
    return output.getvalue().strip()


def _invoke_json_cli(name: str, arguments: list[str]) -> dict[str, Any]:
    """执行输出单个 JSON 对象的公共 CLI，并校验机器输出。"""

    output = _invoke_cli(name, arguments)
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} did not emit one JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{name} JSON output must be an object")
    return payload


def _init_project(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    release = root / "meta-flow-dogfood"
    release.mkdir()
    _git(release, "init", "-b", "main")
    (release / "README.md").write_text("# Meta Flow lifecycle dogfood\n", encoding="utf-8")
    _git(release, "add", "README.md")
    _git(
        release,
        "-c",
        "user.name=Meta Flow Dogfood",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initial",
    )
    plan = plan_project_init(
        ProjectInitRequest(release, "meta-flow-dogfood", "Meta Flow lifecycle dogfood")
    )
    payload = plan.as_dict()
    apply_project_init(
        plan,
        OnboardingAuthorization(
            1,
            "core-lifecycle-dogfood-project",
            AUTHORIZATION_SOURCE,
            PROJECT_AUTHORIZATION_KIND,
            payload["operation"],
            payload["decision_ref"],
            payload["project_id"],
            payload["plan_digest"],
            payload["base_oids"],
            "2099-01-01T00:00:00+00:00",
        ),
    )
    process = root / "meta-flow-dogfood-process"
    phase = Phase(
        1,
        "meta-flow-dogfood",
        "P1-core-lifecycle",
        "证明多 Work 共享投影与预算准入自洽",
        "active",
        result_refs=(GOVERNANCE_PROJECTION_REL.as_posix(),),
    )
    write_phase_create_only(process, phase)
    write_roadmap_create_only(
        process,
        Roadmap(
            1,
            "meta-flow-dogfood",
            "完成核心生命周期自举验证",
            "active",
            (phase.phase_ref,),
        ),
    )
    project = load_project(process)
    replace_project(
        process,
        replace(
            project,
            status="active",
            roadmap_ref="ROADMAP.yaml",
            active_phase_ref=phase.phase_ref,
        ),
        expected_project_id=project.project_id,
    )
    _git(process, "add", ".")
    _git(
        process,
        "-c",
        "user.name=Meta Flow Dogfood",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        "initialize governance truth",
    )
    roles = (
        ImmutableCommitRole("release_input", "release", _git(release, "rev-parse", "HEAD")),
        ImmutableCommitRole("process_input", "process", _git(process, "rev-parse", "HEAD")),
    )
    baseline = build_governance_projection(process, roles)
    baseline_path = process / GOVERNANCE_PROJECTION_REL
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (process / "changes").mkdir(exist_ok=True)
    index = cr_lifecycle.build_index(release)
    (process / "changes/CR-INDEX.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    state_current.init_current_state(release, project_id="meta-flow-dogfood")
    state_current.render_state_file(release, force=True)
    state_current.refresh_current_entry(release)
    state_current.refresh_formal_truth_projection(release)
    return release, process


def _work(process: Path, work_id: str, phase_ref: str):
    request_ref = f"works/{work_id}/REQUEST.md"
    request_path = process / request_ref
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text("# 自举请求\n\n用户确认：是。\n", encoding="utf-8")
    work = build_work(
        work_id=work_id,
        project_id="meta-flow-dogfood",
        objective=f"验证 {work_id} 生命周期",
        request_ref=request_ref,
        phase_ref=phase_ref,
        scope=WorkScope(
            1,
            (request_ref,),
            ("README.md",),
            ("core-lifecycle-targeted",),
        ),
        classification=classify_work(
            RiskFacts(change_kind="code", touched_path_count=2, multi_step=True)
        ),
        release_base_oid="a" * 40,
        process_base_oid="b" * 40,
    )
    return replace(
        work,
        execution_unit=ExecutionUnitV1(
            unit_id=work_id,
            root_concept="core-lifecycle-dogfood",
            slice_id=work_id,
            container_role="primary",
            revision=1,
            supersedes_unit_id="",
            contract_ref=request_ref,
            contract_digest="c" * 64,
        ),
    )


def _prepare_work(
    release: Path,
    process: Path,
    *,
    phase_ref: str,
    work_id: str,
) -> str:
    work = _work(process, work_id, phase_ref)
    apply_work_init(plan_work_init_from_release_root(release, work))
    update_work_status(process, work_id, expected_status="planned", new_status="active")
    result_ref = f"works/{work_id}/RESULT.json"
    (process / result_ref).write_text(
        json.dumps(
            {"schema_version": 1, "work_id": work_id, "decision": "PASS"}
        )
        + "\n",
        encoding="utf-8",
    )
    return result_ref


def _authorization_file(root: Path, process: Path, work_id: str, result_ref: str) -> Path:
    plan = plan_work_close(
        process,
        work_id,
        expected_status="active",
        outcome="completed",
        result_ref=result_ref,
    )
    if not plan.ready:
        raise ValueError("dogfood Work close plan is blocked: " + "; ".join(plan.blockers))
    path = root / f"{work_id}-close-authorization.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": WORK_CLOSE_AUTHORIZATION_KIND,
                "authorization_id": f"dogfood-close-{work_id.lower()}",
                "work_id": work_id,
                "plan_digest": plan.plan_digest,
                "target_refs": [target.ref for target in plan.targets],
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _assert_checks(release: Path, process: Path) -> dict[str, str]:
    checks: dict[str, str] = {}
    _invoke_cli(
        "work close-inspect",
        ["work", "close-inspect", "--project-root", str(release)],
    )
    checks["close_inspect"] = "PASS"
    _invoke_cli(
        "project check",
        ["project", "check", "--project-root", str(release)],
    )
    checks["project_check"] = "PASS"
    _invoke_cli(
        "state check",
        ["state", "check", "--project-root", str(release), "--mode", "enforce"],
    )
    checks["state_check"] = "PASS"
    if state_current.validate_current_projection(release):
        raise ValueError("CURRENT projection check failed")
    checks["current_check"] = "PASS"
    if validate_governance_projection(release, process)["decision"] != "PASS":
        raise ValueError("governance baseline check failed")
    checks["governance_baseline"] = "PASS"
    _invoke_cli(
        "check cr-tracking",
        ["check", "cr-tracking", "--project-root", str(release), "--strict-warnings"],
    )
    checks["cr_tracking"] = "PASS"
    return checks


def run_core_lifecycle_dogfood(root: Path) -> dict[str, Any]:
    """执行真实公共 CLI 组合，返回不含临时绝对路径的稳定摘要。"""

    release, process = _init_project(root)
    phase_ref = load_phase(
        process,
        "phases/P1-core-lifecycle/PHASE.yaml",
    ).phase_ref
    ledger_bytes = {
        path.name: path.read_bytes()
        for path in (process / "state").glob("*-LEDGER.ndjson")
    }
    cr_index_bytes = (process / "changes/CR-INDEX.json").read_bytes()
    steps: list[dict[str, Any]] = []
    usage_boundary: dict[str, Any] = {}
    for work_id in ("W-000", "W-001", "W-002"):
        result_ref = _prepare_work(
            release,
            process,
            phase_ref=phase_ref,
            work_id=work_id,
        )
        after_init_checks = _assert_checks(release, process)
        if work_id == "W-000":
            usage_boundary = _consume_minimum_verification_budget(release, work_id)
        authorization = _authorization_file(root, process, work_id, result_ref)
        _invoke_json_cli(
            f"work close {work_id}",
            [
                "work",
                "close",
                "--project-root",
                str(release),
                "--work-id",
                work_id,
                "--result-ref",
                result_ref,
                "--apply",
                "--authorization",
                str(authorization),
            ],
        )
        steps.append(
            {
                "work_id": work_id,
                "after_init_checks": after_init_checks,
                "after_close_checks": _assert_checks(release, process),
            }
        )

    if not usage_boundary:
        raise ValueError("dogfood did not consume the minimum verification budget")
    if {
        path.name: path.read_bytes()
        for path in (process / "state").glob("*-LEDGER.ndjson")
    } != ledger_bytes:
        raise ValueError("unrelated ledger bytes changed during Work lifecycle")
    if (process / "changes/CR-INDEX.json").read_bytes() != cr_index_bytes:
        raise ValueError("CR-INDEX bytes changed without a CR mutation")
    if (release / "process").exists() or (release / "process").is_symlink():
        raise ValueError("dogfood unexpectedly created a release-local process path")
    return {
        "schema_version": 1,
        "kind": "CoreLifecycleDogfoodReceiptV1",
        "decision": "PASS",
        "route_mode": "sibling-binding",
        "phase_ref": "process/" + phase_ref,
        "usage_boundary": usage_boundary,
        "close_order": [step["work_id"] for step in steps],
        "steps": steps,
        "unrelated_ledgers_unchanged": True,
        "cr_index_unchanged": True,
    }


def _consume_minimum_verification_budget(
    release: Path,
    work_id: str,
) -> dict[str, Any]:
    arguments = [
        "--project-root",
        str(release),
        "--work-id",
        work_id,
        "--event-id",
        "dogfood-targeted-1",
        "--stage",
        "verification",
        "--reads",
        "1",
        "--check-groups",
        "1",
        "--tokens",
        "1500",
    ]
    admission = _invoke_json_cli(
        "work usage-plan",
        ["work", "usage-plan", *arguments],
    )
    admission_digest = admission.get("plan_digest")
    if not isinstance(admission_digest, str) or not admission_digest:
        raise ValueError("work usage-plan omitted plan_digest")
    _invoke_json_cli(
        "work usage-add",
        ["work", "usage-add", *arguments, "--admission-digest", admission_digest],
    )
    return {
        "decision": admission["decision"],
        "stage_limit": admission["stage_budget"]["check_groups"],
        "projected": admission["projected_stage"]["check_groups"],
        "post_action": admission["post_action"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_core_lifecycle_dogfood")
    parser.parse_args(argv or [])
    try:
        with tempfile.TemporaryDirectory(prefix="meta-flow-core-lifecycle-dogfood-") as directory:
            result = run_core_lifecycle_dogfood(Path(directory))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "CoreLifecycleDogfoodReceiptV1",
                    "decision": "BLOCKED",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
