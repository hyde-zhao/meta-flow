"""Command line entry point for Meta Flow."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import runpy
import sys
from pathlib import Path

from meta_flow.project.process_route import (
    ProcessRouteError,
    _resolve_runtime_ref,
    require_process_route,
)
from meta_flow.workspace.routing import (
    bootstrap_process_workspace,
    inspect_legacy_consumer_route,
    legacy_workspace_plan,
    link_process_workspace,
)

LEGACY_STATE_CURRENT_REL = Path("process/state/STATE.current.json")
LEGACY_STATE_REL = Path("process/STATE.md")
_DIRECT_MUTATION_ENTRIES = {
    ("capability", "init"),
    ("concept", "init"),
    ("context", "build"),
    ("context", "build-story-packet"),
    ("context", "read-log"),
    ("cp", "applicability-build"),
    ("cp", "ledger-append"),
    ("cp", "render-summary"),
    ("cp", "successor-apply"),
    ("cp", "successor-recover"),
    ("cr", "aggregate"),
    ("cr", "branch-finish"),
    ("cr", "branch-merge"),
    ("cr", "branch-open"),
    ("cr", "branch-publish"),
    ("cr", "bootstrap"),
    ("cr", "summary"),
    ("event", "closure-apply"),
    ("event", "correction-apply"),
    ("event", "dispatch-not-required"),
    ("event", "append"),
    ("event", "inline-fallback"),
    ("feature", "build"),
    ("governance", "init"),
    ("governance", "truth-map-render"),
    ("identity", "init"),
    ("module", "init"),
    ("quality", "init"),
    ("state", "current-refresh"),
    ("state", "health-update"),
    ("state", "history-render"),
    ("state", "init"),
    ("state", "migrate-v2"),
    ("state", "render"),
    ("state", "compact"),
    ("story", "evidence-index"),
    ("story", "issue-revalidation-authority"),
    ("story", "verify-packet"),
    ("validation", "run"),
    ("work", "block"),
    ("work", "handoff"),
    ("work", "close-recover"),
    ("work", "pause"),
    ("work", "resume"),
    ("work", "start"),
    ("work", "usage-add"),
    ("workspace", "push"),
}
_DIRECT_MUTATION_COMMANDS = {"ask-user"}
_DIRECT_MUTATION_FLAGS = {"--write-default"}
_ACTION_MUTATION_ENTRIES = {
    ("project", "phase-metadata"): {"apply", "recover"},
    ("project", "phase-transition"): {"apply", "recover"},
}


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    if os.environ.get("META_FLOW_SOURCE"):
        roots.append(Path(os.environ["META_FLOW_SOURCE"]).expanduser())

    cwd = Path.cwd()
    roots.extend([cwd, *cwd.parents])

    package_root = Path(__file__).resolve().parent
    roots.extend([package_root.parent, *package_root.parents])
    return roots


def _provider_candidate_roots() -> list[Path]:
    """只从显式开发来源或实际导入 package 定位 provider 资产。"""

    roots: list[Path] = []
    if os.environ.get("META_FLOW_SOURCE"):
        roots.append(Path(os.environ["META_FLOW_SOURCE"]).expanduser())
    package_root = Path(__file__).resolve().parent
    roots.extend([package_root.parent, *package_root.parents])
    return roots


def _find_installer() -> Path:
    for root in _provider_candidate_roots():
        candidate = root / "delivery" / "scripts" / "install.py"
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "无法定位 Meta Flow 安装器。请在 meta-flow 仓库内运行，"
        "或设置 META_FLOW_SOURCE 指向包含 delivery/scripts/install.py 的目录。"
    )


def _find_workspace_root() -> Path:
    for root in _candidate_roots():
        if (root / ".meta-flow" / "workspace.yaml").is_file():
            return root
        if (root / LEGACY_STATE_CURRENT_REL).is_file() or (root / LEGACY_STATE_REL).is_file():
            return root
    return Path.cwd()


def _argument_value(args: list[str], name: str) -> str | None:
    try:
        index = args.index(name)
    except ValueError:
        return None
    if index + 1 >= len(args):
        return None
    return args[index + 1]


def _provider_target_root(args: list[str]) -> Path:
    raw = _argument_value(args, "--project-root") or _argument_value(args, "--project-dir")
    return Path(raw).expanduser().resolve() if raw else Path.cwd().resolve()


def _is_provider_mutation(command: str, args: list[str]) -> bool:
    invocation = (command, *(item for item in args if not item.startswith("-")))
    if command in _DIRECT_MUTATION_COMMANDS:
        return "--output" in args
    if any(item in _DIRECT_MUTATION_FLAGS for item in args):
        return True
    if invocation[:2] in _DIRECT_MUTATION_ENTRIES:
        return "--dry-run" not in args
    action_mutations = _ACTION_MUTATION_ENTRIES.get(invocation[:2])
    if (
        action_mutations is not None
        and len(invocation) > 2
        and invocation[2] in action_mutations
    ):
        return True
    if invocation[:2] in {
        ("cr", "status-sync-resume"),
        ("cr", "status-sync-rollback"),
        ("cr", "status-sync-abandon"),
    }:
        return True
    if invocation[:2] == ("cr", "impact-report"):
        return "--output" in args
    if invocation[:2] == ("route", "plan"):
        return "--output" in args
    if invocation[:2] == ("story", "revalidate-cp6"):
        return (_argument_value(args, "--action") or "") in {
            "apply",
            "completion",
            "recover",
            "replay",
        }
    if command == "eval" and args:
        eval_command = args[0]
        if eval_command in {"mutate", "run"}:
            return True
        if eval_command == "runtime-run":
            return (_argument_value(args, "--mode") or "manual-handoff") != "dry-run"
        if eval_command in {"release-check", "suite-health"}:
            return "--out" in args or "--json-out" in args
        if eval_command == "install-check":
            return "--eval" in args
        if eval_command == "feedback":
            return True
        if eval_command == "backlog":
            return len(args) > 1 and args[1] == "close"
    if "--apply" in args:
        return True
    if invocation[:2] == ("work", "init-recover"):
        action = _argument_value(args, "--action") or "inspect"
        return action != "inspect"
    return False


def _raise_provider_admission_blocked(
    *,
    operation: str,
    mode: str,
    reason_codes: list[str],
) -> None:
    print(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "ProviderRuntimeAdmissionFailureV1",
                "decision": "BLOCKED",
                "operation": operation,
                "mode": mode,
                "reason_codes": sorted(set(reason_codes)),
                "mutation_count": 0,
                "next_action": "run meta-flow version --format json",
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)


def _guard_provider_mutation(command: str, args: list[str]) -> None:
    if not _is_provider_mutation(command, args):
        return
    from meta_flow.installation.identity import (
        evaluate_provider_runtime_admission,
        observe_provider_runtime_identity,
    )

    identity = observe_provider_runtime_identity()
    explicit_mode = os.environ.get("META_FLOW_PROVIDER_MODE", "").strip()
    if explicit_mode:
        mode = explicit_mode
    else:
        target_root = _provider_target_root(args)
        source_root_raw = identity.get("source_root")
        source_root = Path(str(source_root_raw)).resolve() if source_root_raw else None
        try:
            target_root.relative_to(source_root) if source_root is not None else None
        except ValueError:
            mode = "release"
        else:
            mode = "development" if source_root is not None else "release"
    if mode not in {"development", "release"}:
        _raise_provider_admission_blocked(
            operation=f"{command}.{args[0] if args else ''}".rstrip("."),
            mode=mode,
            reason_codes=["INVALID_PROVIDER_MODE"],
        )
    admission = evaluate_provider_runtime_admission(
        identity,
        mode=mode,
        expected_identity_digest=(
            os.environ.get("META_FLOW_EXPECTED_PROVIDER_IDENTITY_DIGEST") or None
        ),
    )
    if admission["decision"] == "READY":
        return
    _raise_provider_admission_blocked(
        operation=f"{command}.{args[0] if args else ''}".rstrip("."),
        mode=mode,
        reason_codes=list(admission["reason_codes"]),
    )


def _read_state() -> tuple[Path, str]:
    root = _find_workspace_root()
    state_path = _resolve_runtime_ref(root, LEGACY_STATE_REL.as_posix())
    if not state_path.is_file():
        raise SystemExit(f"未找到运行态文件: {state_path}")
    return state_path, state_path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end == -1:
        return text
    return text[4:end]


def _scalar_value(frontmatter: str, key: str, *, nested: bool = False) -> str:
    prefix = "  " if nested else ""
    for line in frontmatter.splitlines():
        if not line.startswith(f"{prefix}{key}:"):
            continue
        raw = line.split(":", 1)[1].strip()
        return raw.strip('"')
    return ""


def _state_summary() -> dict[str, str]:
    root = _find_workspace_root()
    current_path = _resolve_runtime_ref(root, LEGACY_STATE_CURRENT_REL.as_posix())
    if current_path.is_file():
        from meta_flow.state.current import load_current_state

        state = load_current_state(root)
        next_action = state.get("next_action") or {}
        next_action_text = next_action.get("text", "") if isinstance(next_action, dict) else str(next_action)
        return {
            "state_path": str(current_path),
            "workflow_mode": str(state.get("workflow_mode") or "standard"),
            "current_phase": str(state.get("current_phase") or "unknown"),
            "blocked": str(state.get("blocked", False)).lower(),
            "active_change": str(state.get("active_change") or ""),
            "last_action": "",
            "next_action": next_action_text,
            "pending_gate": str(state.get("pending_gate") or ""),
            "pending_checklist_path": str(state.get("pending_checklist_path") or ""),
            "subagent_auto_dispatch": "enabled",
        }
    state_path, text = _read_state()
    fm = _frontmatter(text)
    return {
        "state_path": str(state_path),
        "workflow_mode": _scalar_value(fm, "workflow_mode") or "standard",
        "current_phase": _scalar_value(fm, "current_phase") or "unknown",
        "blocked": _scalar_value(fm, "blocked") or "false",
        "active_change": _scalar_value(fm, "active_change"),
        "last_action": _scalar_value(fm, "last_action"),
        "next_action": _scalar_value(fm, "next_action"),
        "pending_gate": _scalar_value(fm, "pending_gate", nested=True),
        "pending_checklist_path": _scalar_value(fm, "pending_checklist_path", nested=True),
        "subagent_auto_dispatch": _scalar_value(fm, "subagent_auto_dispatch", nested=True) or "enabled",
    }


def _print_status() -> None:
    summary = _state_summary()
    print(f"STATE: {summary['state_path']}")
    print(f"workflow_mode: {summary['workflow_mode']}")
    print(f"current_phase: {summary['current_phase']}")
    print(f"blocked: {summary['blocked']}")
    print(f"active_change: {summary['active_change'] or '-'}")
    print(f"pending_gate: {summary['pending_gate'] or '-'}")
    print(f"pending_checklist_path: {summary['pending_checklist_path'] or '-'}")
    print(f"subagent_auto_dispatch: {summary['subagent_auto_dispatch']}")
    print(f"last_action: {summary['last_action'] or '-'}")
    print(f"next_action: {summary['next_action'] or '-'}")


def _print_next() -> None:
    summary = _state_summary()
    if summary["blocked"].lower() == "true":
        print("当前工作流处于 blocked 状态。")
        print(f"STATE: {summary['state_path']}")
        print("下一步准确提示词: 处理阻塞: <写明要解除的阻塞、接受的风险或回退目标>")
        return
    if summary["pending_gate"]:
        path = summary["pending_checklist_path"] or "process/checkpoints/CP*.md"
        print(f"等待用户确认 {summary['pending_gate']}。")
        print(f"checklist 路径: {path}")
        print("下一步准确提示词: 请只回复以下三个 exact 选项之一: approve / 修改: <具体修改点> / reject")
        return
    if summary["next_action"]:
        print(f"下一步准确提示词: 执行下一步: {summary['next_action']}")
        return
    print(f"当前阶段: {summary['current_phase']}")
    print(f"下一步准确提示词: 推进阶段: {summary['current_phase']}")


def _run_workspace_doctor() -> int:
    root = _find_workspace_root()
    problems: list[str] = []
    warnings: list[str] = []
    health = None
    route_lines: list[str] = []
    if (root / ".meta-flow" / "workspace.yaml").is_file():
        from meta_flow.project.process_route_adapter import (
            RouteConsumerError,
            resolve_configured_consumer_route,
        )

        try:
            route = resolve_configured_consumer_route(
                root,
                consumer_id="workspace-doctor",
            )
        except RouteConsumerError as exc:
            problems.append(f"{exc.code}: {exc}")
            state_path = root / LEGACY_STATE_REL
            process_dirs: tuple[Path, ...] = ()
        else:
            if route is None:  # pragma: no cover - binding existence checked above
                raise AssertionError("configured workspace did not resolve a route")
            state_path = route.process_root / LEGACY_STATE_REL.relative_to("process")
            process_dirs = (
                route.process_root / "checks",
                route.process_root / "checkpoints",
            )
            route_lines = [
                "process_route_health: healthy",
                f"- route_mode: {route.route_mode}",
                f"- process_root: {route.process_root}",
            ]
    else:
        health = inspect_legacy_consumer_route(
            root,
            consumer_id="workspace-doctor",
        )
        state_path = root / LEGACY_STATE_REL
        process_dirs = (
            root / Path("process/checks"),
            root / Path("process/checkpoints"),
        )
        if health.blocking:
            problems.extend(health.errors)

    if not state_path.is_file():
        problems.append(f"缺少 {state_path}")
    for directory in process_dirs:
        if not directory.is_dir():
            warnings.append(f"缺少目录 {directory}")
    legacy_cp4 = root / "checkpoints" / "CP4-STORY-PLAN-REVIEW.md"
    if legacy_cp4.exists():
        warnings.append("发现旧 CP4 人工审查稿；当前规则下 CP4 只做自动预检并汇入 CP5。")

    if state_path.is_file():
        summary = _state_summary()
        if summary["subagent_auto_dispatch"] not in {"enabled", "disabled"}:
            warnings.append("orchestrator_session.subagent_auto_dispatch 建议为 enabled 或 disabled")
        if summary["workflow_mode"] not in {"standard", "fast-lane"}:
            warnings.append("workflow_mode 建议为 standard 或 fast-lane")

    if problems:
        print("Doctor: FAIL")
        if health is not None:
            route_lines = health.format_lines()
        for line in route_lines:
            print(line)
        for item in problems:
            print(f"- ERROR: {item}")
        for item in warnings:
            print(f"- WARN: {item}")
        return 1

    print("Doctor: OK")
    if health is not None:
        route_lines = health.format_lines()
    for line in route_lines:
        print(line)
    for item in warnings:
        print(f"- WARN: {item}")
    return 0


def _print_doctor_help() -> None:
    print(
        "usage: meta-flow doctor [all|workspace|tokens|context|artifacts|quality|workflow|adoption] [options]\n\n"
        "Commands:\n"
        "  workspace   Check local Meta Flow runtime structure. This is the legacy default.\n"
        "  tokens      Estimate token pressure and default-read deny-list candidates.\n"
        "  context     Summarize read expansion ledger and summary insufficiency feedback.\n"
        "  artifacts   Check known artifact byte budgets.\n"
        "  quality     Validate quality model and eval matrix policies.\n"
        "  workflow    Report minimal workflow metrics from CP results and ledgers.\n"
        "  adoption    Check target-project adoption readiness without writing files.\n"
        "  all         Run workspace, token, context, artifact, quality, and workflow doctors.\n\n"
        "Examples:\n"
        "  meta-flow doctor\n"
        "  meta-flow doctor tokens --project-root .\n"
        "  meta-flow doctor context --project-root .\n"
        "  meta-flow doctor artifacts --project-root .\n"
        "  meta-flow doctor quality --project-root .\n"
        "  meta-flow doctor workflow --project-root .\n"
        "  meta-flow doctor adoption --project-root .\n"
        "  meta-flow doctor all --project-root .\n"
    )


def _run_doctor(args: list[str]) -> None:
    if not args:
        raise SystemExit(_run_workspace_doctor())
    if args[0] in {"-h", "--help"}:
        _print_doctor_help()
        return

    command = args[0]
    forwarded = args[1:]
    if command == "workspace":
        raise SystemExit(_run_workspace_doctor())
    if command in {"tokens", "artifacts"}:
        from meta_flow.checks import token_budget

        raise SystemExit(token_budget.main(["--mode", command, *forwarded]))
    if command == "context":
        from meta_flow.checks import context_doctor

        raise SystemExit(context_doctor.main(forwarded))
    if command == "adoption":
        from meta_flow.checks import adoption_readiness

        raise SystemExit(adoption_readiness.main(forwarded))
    if command in {"quality", "workflow"}:
        import argparse

        from meta_flow.checks import quality_governance

        parser = argparse.ArgumentParser(prog=f"meta-flow doctor {command}")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed = parser.parse_args(forwarded)
        if command == "quality":
            raise SystemExit(quality_governance.run_quality_doctor(parsed.project_root))
        raise SystemExit(quality_governance.run_workflow_doctor(parsed.project_root))
    if command == "all":
        import argparse

        from meta_flow.checks import context_doctor, quality_governance, token_budget

        workspace_status = _run_workspace_doctor()
        tokens_status = token_budget.main(["--mode", "tokens", *forwarded])
        context_status = context_doctor.main(forwarded)
        artifacts_status = token_budget.main(["--mode", "artifacts", *forwarded])
        parser = argparse.ArgumentParser(prog="meta-flow doctor all")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed, _unknown = parser.parse_known_args(forwarded)
        quality_status = quality_governance.run_quality_doctor(parsed.project_root)
        workflow_status = quality_governance.run_workflow_doctor(parsed.project_root)
        raise SystemExit(1 if any((workspace_status, tokens_status, context_status, artifacts_status, quality_status, workflow_status)) else 0)
    raise SystemExit(f"未知 doctor 命令: {command}. 目前支持: all, workspace, tokens, context, artifacts, quality, workflow, adoption")


def _print_help() -> None:
    print(
        "usage: meta-flow <command> [options]\n\n"
        "Commands:\n"
        "  install    Install Meta Flow assets into Claude Code, Codex, or OpenClaw.\n"
        "  upgrade    Upgrade exact Meta Flow-owned assets through one lifecycle transaction.\n"
        "  uninstall  Uninstall Meta Flow assets recorded in INSTALL-MANIFEST.\n"
        "  reinstall  Force-refresh through one upgrade transaction (never uninstall+install).\n"
        "  recover    Inspect a durable installation journal; mutating recovery needs new authorization.\n"
        "  version    Show package and exact source diagnostics.\n"
        "  check      Run packaged Meta Flow validators.\n"
        "  capability Validate capability status and docs claims.\n"
        "  concept    Validate concept ownership and overlap.\n"
        "  context    Build, validate, and explain context-budgeted context packs.\n"
        "  cp         Validate CP result JSON, render summaries, and append checkpoint ledger events.\n"
        "  cr         Manage CR lifecycle records and guarded aggregate evidence gates.\n"
        "  design     Validate design deltas and long-lived design write-back status.\n"
        "  event      Append, list, and validate NDJSON process event ledgers.\n"
        "  eval       Validate and run local workflow evaluation packages.\n"
        "  evolution  Review, package, start, and evaluate bounded Meta Flow evolution.\n"
        "  feature    Manage Feature Registry and Story-to-Feature traceability.\n"
        "  failure    Validate failure routing policy and CP route_on_fail values.\n"
        "  gate       Classify and validate gate profiles.\n"
        "  route      Derive CR-aware checkpoint route plans.\n"
        "  governance Validate source-of-truth and retention lifecycle policies.\n"
        "  identity   Validate product/package/import/CLI identity.\n"
        "  ledger     Plan or apply retention/archive compaction for NDJSON event ledgers.\n"
        "  module     Validate module boundaries, imports, risk rings, and architecture fitness.\n"
        "  policy     List, expand, and validate authorization policies.\n"
        "  project    Scaffold and validate process/project governance state.\n"
        "  quality    Validate quality model and eval matrix policies.\n"
        "  repository Plan/apply one allowlisted commit or exact-OID fast-forward push.\n"
        "  retrospective Build and validate evidence-based project or phase retrospectives.\n"
        "  story      Validate Story return packets and evidence indexes.\n"
        "  validation Generate or execute profile-driven validation task evidence.\n"
        "  waiver     Validate waiver policy and CP waiver records.\n"
        "  work       Classify, create, check, and query vNext Work envelopes.\n"
        "  ask-user   Generate exact user prompts or Codex request_user_input payloads.\n"
        "  state      Migrate, render, and validate lightweight runtime state v2.\n"
        "  workspace  Legacy shared-artifact route/push commands; new projects use project/repository.\n"
        "  status     Show current process/STATE.md summary.\n"
        "  next       Show the exact next prompt; never falls back to vague continue/agree wording.\n"
        "  doctor     Check local Meta Flow runtime structure, token budgets, context expansion, or artifacts.\n\n"
        "Examples:\n"
        "  meta-flow install codex --scope user --component rules\n"
        "  meta-flow install claude --scope project --project-dir /path/to/repo\n"
        "  meta-flow upgrade codex --scope user --component rules\n"
        "  meta-flow uninstall codex --scope user\n"
        "  meta-flow reinstall codex --scope user --component rules\n"
        "  meta-flow recover --journal .meta-flow/transactions/txn-id.journal.json --action inspect\n"
        "  meta-flow version --format json\n"
        "  meta-flow check human-gate --checkpoint process/checkpoints/CP3-HLD-REVIEW.md\n"
        "  meta-flow ask-user human-gate --checkpoint process/checkpoints/CP3-HLD-REVIEW.md --replay --format codex-json\n"
        "  meta-flow context build --stage CP6 --profile standard-code --cr CR-101 --project-root .\n"
        "  meta-flow context check --context process/context/CP6-CR101.context.json --project-root .\n"
        "  meta-flow context sufficiency-check --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json\n"
        "  meta-flow context read-log --path process/STATE.md --reason human_audit --reason-evidence-json '{\"authorization_ref\":\"process/checkpoints/AUDIT.md\"}' --stage CP6 --agent meta-dev --context-ref process/context/CP6.context.json --project-root .\n"
        "  meta-flow context read-log-check --project-root .\n"
        "  meta-flow cr aggregate --id CR-051 --operation-id operation-001 --attempt 1 --source-handle source.json --artifact-handle artifact.json --dry-run --project-root .\n"
        "  meta-flow doctor context --project-root .\n"
        "  meta-flow cp result-check --result process/checks/CP6-STORY.result.json --project-root .\n"
        "  meta-flow event check --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint\n"
        "  meta-flow ledger compact --ledger process/state/CHECKPOINT-LEDGER.ndjson --project-root .\n"
        "  meta-flow capability check --artifact README.md --project-root .\n"
        "  meta-flow concept check --changed-files quant_lab/engine/contracts.py --project-root .\n"
        "  meta-flow identity check --project-root .\n"
        "  meta-flow identity scan --project-root .\n"
        "  meta-flow feature check --project-root .\n"
        "  meta-flow feature trace --project-root .\n"
        "  meta-flow failure route-check --result process/checks/CP7-STORY.result.json --project-root .\n"
        "  meta-flow waiver check --result process/checks/CP8-DELIVERY.result.json --project-root .\n"
        "  meta-flow story return-check --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .\n"
        "  meta-flow validation run --cr CR-155 --profile real-lake-readonly --reruns 2 --project-root .\n"
        "  meta-flow design delta-check --delta process/design-deltas/STORY-CR123-S01.delta.json --project-root .\n"
        "  meta-flow check module-boundaries --project-root .\n"
        "  meta-flow check imports --project-root .\n"
        "  meta-flow check risk-rings --changed-files quant_lab/trading/order.py --project-root .\n"
        "  meta-flow gate classify --changed-files README.md\n"
        "  meta-flow route plan --cr-type process --gate-profile process-lite --cr-trait '{\"uses_existing_evidence_only\": true}'\n"
        "  meta-flow governance truth-map-check --project-root .\n"
        "  meta-flow governance baseline-refresh --project-root . --project-id <project-id> --immutable-commit-role release_input=release:<oid> --immutable-commit-role process_input=process:<oid>\n"
        "  meta-flow policy list --project-root .\n"
        "  meta-flow project scaffold --project-root .\n"
        "  meta-flow project check --project-root .\n"
        "  meta-flow quality model-check --project-root .\n"
        "  meta-flow quality eval-check --project-root .\n"
        "  meta-flow check cr-tracking --project-root .\n"
        "  meta-flow workspace check\n"
        "  meta-flow workspace link --artifact-root ../meta-flow-artifacts --project-name meta-flow\n"
        "  meta-flow workspace bootstrap --artifact-root ../meta-flow-artifacts --project-name meta-flow\n"
        "  meta-flow workspace git-status --project-root .\n"
        "  meta-flow workspace push --project-root .\n"
        "  meta-flow doctor adoption --project-root .\n"
        "  meta-flow cr bootstrap --id CR-001 --title \"project adoption bootstrap\" --scope \"Initialize Meta Flow adoption readiness.\" --project-root .\n"
        "  meta-flow cr brief --id CR-001 --project-root .\n"
        "  meta-flow cr goal-brief --goal-ref GOAL-001 --project-root .\n"
        "  meta-flow eval validate --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml\n"
        "  meta-flow status\n"
    )


def _run_installer(command: str, args: list[str]) -> None:
    from meta_flow.installation.identity import (
        evaluate_provider_runtime_admission,
        observe_provider_runtime_identity,
    )

    explicit_provider_mode = os.environ.get("META_FLOW_PROVIDER_MODE", "").strip()
    provider_mode = explicit_provider_mode or (
        "development" if "--dry-run" in args else "release"
    )
    if provider_mode not in {"development", "release"}:
        _raise_provider_admission_blocked(
            operation=f"assets.{command}",
            mode=provider_mode,
            reason_codes=["INVALID_PROVIDER_MODE"],
        )
    if not any(item in {"-h", "--help"} for item in args):
        identity = observe_provider_runtime_identity()
        admission = evaluate_provider_runtime_admission(identity, mode=provider_mode)
        if admission["decision"] != "READY":
            _raise_provider_admission_blocked(
                operation=f"assets.{command}",
                mode=provider_mode,
                reason_codes=list(admission["reason_codes"]),
            )
    installer = _find_installer()
    forwarded = [*args]
    if "--provider-mode" not in forwarded:
        forwarded.extend(["--provider-mode", provider_mode])
    if command != "install":
        forwarded = [command, *forwarded]
    original_argv = sys.argv[:]
    try:
        sys.argv = [f"meta-flow {command}", *forwarded]
        namespace = runpy.run_path(str(installer), run_name="__meta_flow_installer__")
        namespace["main"]()
    finally:
        sys.argv = original_argv


def _print_reinstall_help() -> None:
    print(
        "usage: meta-flow reinstall <platform> [options]\n\n"
        "Normalize reinstall to one upgrade transaction with force_refresh=true.\n"
        "No uninstall phase is run, so one plan, authorization, journal, and terminal receipt\n"
        "cover the complete operation.\n\n"
        "Examples:\n"
        "  meta-flow reinstall codex --scope user --component rules\n"
        "  meta-flow reinstall claude --scope project --project-dir /path/to/repo\n"
    )


def _reinstall_uninstall_args(args: list[str]) -> list[str]:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("platform_arg", nargs="?")
    parser.add_argument("--platform", dest="platform_option", default="")
    parser.add_argument("--scope", default="")
    parser.add_argument("--project-dir", default="")
    parser.add_argument("--component", default="")
    parser.add_argument("--dry-run", action="store_true")
    parsed, _unknown = parser.parse_known_args(args)
    platform = parsed.platform_arg or parsed.platform_option
    if not platform:
        raise SystemExit("reinstall requires a target platform, for example `meta-flow reinstall codex`.")
    uninstall_args = [platform]
    if parsed.scope:
        uninstall_args.extend(["--scope", parsed.scope])
    if parsed.project_dir:
        uninstall_args.extend(["--project-dir", parsed.project_dir])
    if parsed.component:
        uninstall_args.extend(["--component", parsed.component])
    if parsed.dry_run:
        uninstall_args.append("--dry-run")
    return uninstall_args


def _run_reinstaller(args: list[str]) -> None:
    """Legacy private helper retained only for source compatibility tests.

    Production ``main`` no longer calls this two-transaction implementation.
    """

    if not args or args[0] in {"-h", "--help"}:
        _print_reinstall_help()
        return
    uninstall_args = _reinstall_uninstall_args(args)
    print("Reinstall step 1/2: uninstall")
    _run_installer("uninstall", uninstall_args)
    print("Reinstall step 2/2: install")
    _run_installer("install", args)


def _run_lifecycle_reinstaller(args: list[str]) -> None:
    """公开 reinstall：唯一分发为 upgrade + force-refresh。"""

    if not args or args[0] in {"-h", "--help"}:
        _print_reinstall_help()
        return
    from meta_flow.installation.migration import dispatch_lifecycle_adapter

    calls: list[tuple[str, list[str]]] = []

    def asset_adapter(
        operation: str,
        selector: object,
    ) -> None:
        if operation != "assets.upgrade" or not isinstance(selector, dict):
            raise SystemExit("reinstall normalization produced an invalid asset request")
        forwarded = [*args]
        if "--force-refresh" not in forwarded:
            forwarded.append("--force-refresh")
        calls.append(("upgrade", forwarded))

    dispatch_lifecycle_adapter(
        surface="assets",
        intent="reinstall",
        selector={},
        asset_adapter=asset_adapter,
        cli_adapter=lambda _operation, _selector: None,
    )
    if calls != [("upgrade", [*args, "--force-refresh"])]:
        raise SystemExit("reinstall must produce exactly one upgrade transaction")
    _run_installer(*calls[0])


def _run_version(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="meta-flow version")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--mode", choices=("development", "release"), default="release")
    parsed = parser.parse_args(args)

    from meta_flow.installation.identity import (
        evaluate_provider_runtime_admission,
        observe_provider_runtime_identity,
    )

    identity = observe_provider_runtime_identity()
    admission = evaluate_provider_runtime_admission(identity, mode=parsed.mode)
    source_ready = identity["source_discovery"]["decision"] == "PASS"
    release_ready = identity["release_readiness"]["decision"] == "PASS"
    payload: dict[str, object] = {
        **identity,
        "version": identity["distribution_version"],
        "source": identity["identity_source"],
        "oid": identity["source_commit"] or "",
        "delivery_tree_digest": identity["source_tree_digest"] or "",
        "ready": source_ready,
        "status": (
            "READY"
            if release_ready
            else "SOURCE_READY_RELEASE_BLOCKED"
            if source_ready
            else "IDENTITY_INCOMPLETE"
        ),
        "provider_admission": admission,
    }
    if parsed.format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(f"meta-flow {payload['version']}")
    print(f"status: {payload['status']}")
    print(f"source: {payload['source']}")
    print(f"git_oid: {payload['oid'] or '-'}")
    print(f"module_path: {payload['module_path']}")
    print(f"editable: {str(payload['editable']).lower()}")
    print(f"worktree_clean: {str(payload['worktree_clean']).lower()}")
    print(f"exact_commit_delivery: {str(payload['exact_commit_delivery']).lower()}")
    print(f"release_readiness: {payload['release_readiness']['decision']}")
    print(f"artifact_sha256: {payload['artifact_sha256'] or '-'}")
    print(f"delivery_tree_digest: {payload['delivery_tree_digest'] or '-'}")


def _run_lifecycle_recovery(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="meta-flow recover")
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument(
        "--action",
        choices=("inspect", "resume", "rollback", "abandon"),
        default="inspect",
    )
    parser.add_argument("--authorization", type=Path)
    parsed = parser.parse_args(args)
    if parsed.action != "inspect":
        if parsed.authorization is None:
            raise SystemExit(
                f"{parsed.action} requires one new --authorization; "
                "the original operation authorization cannot be reused."
            )
        raise SystemExit(
            "mutating recovery must be executed from a freshly rebuilt "
            "lifecycle.recover plan; direct journal mutation is disabled."
        )

    from meta_flow.installation.recovery import inspect_journal, validate_journal

    try:
        payload = json.loads(parsed.journal.read_text(encoding="utf-8"))
        observation = inspect_journal(validate_journal(payload))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"cannot inspect installation journal: {exc}") from exc
    print(
        json.dumps(
            dataclasses.asdict(observation),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _print_check_help() -> None:
    print(
        "usage: meta-flow check <validator> [options]\n\n"
        "Validators:\n"
        "  human-gate   Validate CP2/CP3/CP5/CP8 Decision Brief and optional launch message.\n"
        "  cr-tracking       Validate CR tracking consistency across STATE, CR files, follow-up tables, and CR-INDEX.\n"
        "  state-transition  Validate approve/auto-CP advance-to-next-gate behavior.\n\n"
        "  design-ownership       Validate FEATURE-REGISTRY ownership fields.\n"
        "  story-to-feature-trace Validate Story feature refs and LLD policy.\n\n"
        "  story-return          Validate Story Return Packet against Story context packet.\n"
        "  evidence-index        Validate Story Evidence Index.\n"
        "  lld-structure         Validate LLD / technical-note / waived evidence structure.\n"
        "  design-delta          Validate Story design delta structure and write-back status.\n\n"
        "  cp-result             Validate CP result JSON machine truth source.\n"
        "  event-ledger          Validate NDJSON event ledger structure.\n"
        "  handoff-dispatch      Validate dispatch evidence in process/handoffs/*.md.\n"
        "  read-expansion        Validate READ-EXPANSION-LEDGER.ndjson.\n\n"
        "  failure-routing      Validate failure route_on_fail governance.\n"
        "  waiver-policy        Validate waiver scope / expiry / approval_ref governance.\n\n"
        "  module-boundaries     Validate MODULE-BOUNDARIES ownership and dependency fields.\n"
        "  imports               Scan Python imports against MODULE-BOUNDARIES.\n"
        "  architecture-fitness  Run boundary, import, and isolation checks.\n"
        "  risk-rings            Check changed files and imports against runtime risk rings.\n\n"
        "  capability-claims     Validate capability status and docs claims.\n"
        "  concept-overlap       Validate concept owners and changed-file overlap.\n"
        "  package-identity      Validate repo/package/import/CLI identity.\n\n"
        "  truth-map             Validate source-of-truth machine policy.\n"
        "  governance-ownership  Validate canonical concept owners and consumer coverage.\n"
        "  terminal-lineage      Project typed Work/CR/dispatch/gate/evidence current/history terminal lineage.\n"
        "  reference-lifecycle   Validate legacy readability and retain/archive/delete reference decisions.\n"
        "  detector-qualification Validate current full plus post-baseline incremental writer gate.\n"
        "  retention-policy      Validate process retention lifecycle policy.\n\n"
        "Examples:\n"
        "  meta-flow check human-gate --checkpoint process/checkpoints/CP3-HLD-REVIEW.md\n"
        "  meta-flow check human-gate --checkpoint process/checkpoints/CP5-STORY-DESIGN-REVIEW.md --launch-message-file process/checkpoints/CP5-LAUNCH-MESSAGE.md\n"
        "  meta-flow check cr-tracking --project-root .\n"
        "  meta-flow check state-transition --route-plan process/checks/CP0-CR158.route-plan.json --result process/checks/CP4-CR158.result.json --project-root .\n"
        "  meta-flow check state-transition --route-plan process/checks/CP0-CR158.route-plan.json --approved-gate CP3 --project-root .\n"
        "  meta-flow check design-ownership --project-root .\n"
        "  meta-flow check story-to-feature-trace --project-root .\n"
        "  meta-flow check story-return --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .\n"
        "  meta-flow check evidence-index --index process/evidence/STORY-CR123-S01.CP6.index.json --project-root .\n"
        "  meta-flow check lld-structure --lld process/stories/STORY-CR123-S01-LLD.md --project-root .\n"
        "  meta-flow check design-delta --delta process/design-deltas/STORY-CR123-S01.delta.json --project-root .\n"
        "  meta-flow check cp-result --result process/checks/CP6-STORY.result.json --project-root .\n"
        "  meta-flow check event-ledger --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint\n"
        "  meta-flow check handoff-dispatch --project-root .\n"
        "  meta-flow check read-expansion --project-root .\n"
        "  meta-flow check failure-routing --result process/checks/CP7-STORY.result.json --project-root .\n"
        "  meta-flow check waiver-policy --result process/checks/CP8-DELIVERY.result.json --project-root .\n"
        "  meta-flow check module-boundaries --project-root .\n"
        "  meta-flow check imports --project-root .\n"
        "  meta-flow check risk-rings --changed-files quant_lab/trading/order.py --project-root .\n"
        "  meta-flow check capability-claims --artifact README.md --project-root .\n"
        "  meta-flow check concept-overlap --changed-files quant_lab/engine/contracts.py --project-root .\n"
        "  meta-flow check package-identity --project-root .\n"
        "  meta-flow check truth-map --project-root .\n"
        "  meta-flow check retention-policy --project-root .\n"
    )


def _run_check(args: list[str]) -> None:
    if not args or args[0] in {"-h", "--help"}:
        _print_check_help()
        return

    validator = args[0]
    forwarded = args[1:]
    if validator == "human-gate":
        from meta_flow.checks import human_gate

        raise SystemExit(human_gate.main(forwarded))
    if validator == "cr-tracking":
        from meta_flow.checks import cr_tracking

        raise SystemExit(cr_tracking.main(forwarded))
    if validator == "state-transition":
        from meta_flow.checks import state_transition

        raise SystemExit(state_transition.main(forwarded))
    if validator == "design-ownership":
        from meta_flow.design import feature_registry

        raise SystemExit(feature_registry.main(["check", *forwarded]))
    if validator == "story-to-feature-trace":
        from meta_flow.design import feature_registry

        raise SystemExit(feature_registry.main(["trace", *forwarded]))
    if validator == "story-return":
        from meta_flow.workflow import story_evidence

        raise SystemExit(story_evidence.main(["return-check", *forwarded]))
    if validator == "evidence-index":
        from meta_flow.workflow import story_evidence

        raise SystemExit(story_evidence.main(["evidence-check", *forwarded]))
    if validator == "lld-structure":
        from meta_flow.workflow import story_evidence

        raise SystemExit(story_evidence.main(["lld-check", *forwarded]))
    if validator == "design-delta":
        from meta_flow.workflow import story_evidence

        raise SystemExit(story_evidence.design_main(["delta-check", *forwarded]))
    if validator == "cp-result":
        from meta_flow.checks import cp_result

        raise SystemExit(cp_result.main(["result-check", *forwarded]))
    if validator == "event-ledger":
        from meta_flow.state import event_ledger

        raise SystemExit(event_ledger.main(["check", *forwarded]))
    if validator == "handoff-dispatch":
        from meta_flow.checks import handoff_dispatch

        raise SystemExit(handoff_dispatch.main(forwarded))
    if validator == "read-expansion":
        from meta_flow.context_pack import read_expansion

        raise SystemExit(read_expansion.main(["read-log-check", *forwarded]))
    if validator == "failure-routing":
        from meta_flow.policies import failure_routing

        raise SystemExit(failure_routing.failure_main(["route-check", *forwarded]))
    if validator == "waiver-policy":
        from meta_flow.policies import failure_routing

        raise SystemExit(failure_routing.waiver_main(["check", *forwarded]))
    if validator == "module-boundaries":
        from meta_flow.design import module_boundaries

        raise SystemExit(module_boundaries.main(["check-boundaries", *forwarded]))
    if validator == "imports":
        from meta_flow.design import module_boundaries

        raise SystemExit(module_boundaries.main(["check-imports", *forwarded]))
    if validator == "architecture-fitness":
        from meta_flow.design import module_boundaries

        raise SystemExit(module_boundaries.main(["architecture-fitness", *forwarded]))
    if validator == "risk-rings":
        from meta_flow.design import module_boundaries

        raise SystemExit(module_boundaries.main(["check-risk-rings", *forwarded]))
    if validator == "capability-claims":
        from meta_flow.design import product_governance

        raise SystemExit(product_governance.capability_main(["check", *forwarded]))
    if validator == "concept-overlap":
        from meta_flow.design import product_governance

        raise SystemExit(product_governance.concept_main(["check", *forwarded]))
    if validator == "package-identity":
        from meta_flow.design import product_governance

        raise SystemExit(product_governance.identity_main(["check", *forwarded]))
    if validator == "truth-map":
        from meta_flow.policies import governance

        raise SystemExit(governance.main(["truth-map-check", *forwarded]))
    if validator == "governance-ownership":
        from meta_flow.semantics import ownership

        raise SystemExit(ownership.main(forwarded))
    if validator == "terminal-lineage":
        from meta_flow.workflow import terminal_lineage

        raise SystemExit(terminal_lineage.main(forwarded))
    if validator == "reference-lifecycle":
        from meta_flow.project import reference_lifecycle

        raise SystemExit(reference_lifecycle.main(forwarded))
    if validator == "detector-qualification":
        from meta_flow.checks import detector_qualification

        raise SystemExit(detector_qualification.main(forwarded))
    if validator == "retention-policy":
        from meta_flow.policies import governance

        raise SystemExit(governance.main(["retention-check", *forwarded]))
    raise SystemExit(
        "未知检查器: "
        f"{validator}. 目前支持: human-gate, cr-tracking, design-ownership, story-to-feature-trace, "
        "state-transition, story-return, evidence-index, lld-structure, design-delta, cp-result, event-ledger, handoff-dispatch, read-expansion, "
        "failure-routing, waiver-policy, "
        "module-boundaries, imports, architecture-fitness, risk-rings, capability-claims, concept-overlap, "
        "package-identity, truth-map, governance-ownership, terminal-lineage, reference-lifecycle, detector-qualification, retention-policy"
    )


def _print_workspace_help() -> None:
    print(
        "usage: meta-flow workspace <command> [options]\n\n"
        "LEGACY: these commands manage the historical shared-artifact layout. "
        "New projects should use `meta-flow project init` and `meta-flow repository commit|push`.\n\n"
        "Commands:\n"
        "  check      Print process route health.\n"
        "  link       Dry-run or explicitly authorize a legacy process link.\n"
        "  bootstrap  Dry-run or explicitly authorize legacy state bootstrap.\n"
        "  git-status Print project and artifact git status together.\n"
        "  push       Push project and artifact git repositories together.\n\n"
        "Push refuses dirty working trees by default so process artifacts cannot be missed silently.\n\n"
        "Examples:\n"
        "  meta-flow workspace check\n"
        "  meta-flow workspace link --artifact-root ../meta-flow-artifacts --project-name meta-flow\n"
        "  meta-flow workspace link --artifact-root ../meta-flow-artifacts --project-name meta-flow --apply --authorization AUTH.json\n"
        "  meta-flow workspace bootstrap --artifact-root ../meta-flow-artifacts --project-name meta-flow\n"
        "  meta-flow workspace git-status --project-root .\n"
        "  meta-flow workspace push --project-root .\n"
    )


def _run_workspace(args: list[str]) -> None:
    if not args or args[0] in {"-h", "--help"}:
        _print_workspace_help()
        return
    command = args[0]
    if command == "check":
        import argparse

        parser = argparse.ArgumentParser(
            prog="meta-flow workspace check",
            description="Print process route health.",
        )
        parser.add_argument("--project-root", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        root = parsed.project_root.resolve() if parsed.project_root else _find_workspace_root()
        from meta_flow.project.process_route_adapter import (
            RouteConsumerError,
            resolve_configured_consumer_route,
        )

        try:
            route = resolve_configured_consumer_route(
                root,
                consumer_id="workspace-check",
            )
        except RouteConsumerError as error:
            print("process_route_health: blocked")
            print("- consumer: workspace-check")
            print(f"- error_code: {error.code}")
            print(f"- error: {error}")
            raise SystemExit(1) from error
        if route is not None:
            print("process_route_health: healthy")
            print(f"- consumer: {route.consumer_id}")
            print(f"- classification: {route.classification}")
            print(f"- route_mode: {route.route_mode}")
            print(f"- project_id: {route.project_id}")
            print(f"- process_root: {route.process_root}")
            raise SystemExit(0)
        health = inspect_legacy_consumer_route(
            root,
            consumer_id="workspace-check",
        )
        for line in health.format_lines():
            print(line)
        raise SystemExit(1 if health.blocking else 0)
    if command == "link":
        import argparse

        parser = argparse.ArgumentParser(
            prog="meta-flow workspace link",
            description="Create process -> <artifact-root>/process/<project-name> and process scaffold.",
        )
        parser.add_argument("--artifact-root", type=Path, required=True)
        parser.add_argument("--project-name", default=Path.cwd().name)
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--authorization", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        plan = legacy_workspace_plan(
            "workspace link",
            parsed.project_root,
            parsed.artifact_root,
            parsed.project_name,
        )
        if not parsed.apply:
            print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
            raise SystemExit(0 if plan.get("decision") == "READY" else 2)
        if parsed.authorization is None:
            raise SystemExit("--apply requires --authorization")
        from meta_flow.workspace.legacy_route_adapter import load_legacy_authorization

        try:
            capability = load_legacy_authorization(parsed.authorization)
            health = link_process_workspace(
                parsed.project_root,
                parsed.artifact_root,
                parsed.project_name,
                capability=capability,
            )
        except (OSError, ValueError) as exc:
            print(json.dumps({"plan": plan, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
            raise SystemExit(2) from exc
        for line in health.format_lines():
            print(line)
        if health.status == "state_missing":
            print("- NEXT: initialize process/STATE.md from the state-router template before running workflow commands.")
            raise SystemExit(0)
        raise SystemExit(1 if health.blocking else 0)
    if command == "bootstrap":
        import argparse

        parser = argparse.ArgumentParser(
            prog="meta-flow workspace bootstrap",
            description="Link process and initialize STATE.current.json, STATE.md, and base ledgers.",
        )
        parser.add_argument("--artifact-root", type=Path, required=True)
        parser.add_argument("--project-name", default=Path.cwd().name)
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--authorization", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        plan = legacy_workspace_plan(
            "workspace bootstrap",
            parsed.project_root,
            parsed.artifact_root,
            parsed.project_name,
            force=parsed.force,
        )
        if not parsed.apply:
            print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
            raise SystemExit(0 if plan.get("decision") == "READY" else 2)
        if parsed.authorization is None:
            raise SystemExit("--apply requires --authorization")
        from meta_flow.workspace.legacy_route_adapter import load_legacy_authorization

        try:
            capability = load_legacy_authorization(parsed.authorization)
            health = bootstrap_process_workspace(
                parsed.project_root,
                parsed.artifact_root,
                parsed.project_name,
                force=parsed.force,
                capability=capability,
            )
        except (OSError, ValueError) as exc:
            print(json.dumps({"plan": plan, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
            raise SystemExit(2) from exc
        for line in health.format_lines():
            print(line)
        print("- NEXT: run meta-flow doctor adoption --project-root . before starting a target-project CR.")
        raise SystemExit(1 if health.blocking else 0)
    if command == "git-status":
        import argparse

        from meta_flow.workspace.git_sync import format_git_status, workspace_repositories

        parser = argparse.ArgumentParser(
            prog="meta-flow workspace git-status",
            description="Print project and external artifact git status together.",
        )
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed = parser.parse_args(args[1:])
        repos, warnings = workspace_repositories(parsed.project_root)
        for line in format_git_status(repos, warnings):
            print(line)
        raise SystemExit(1 if any(not repo.is_git_repo or repo.error for repo in repos) else 0)
    if command == "push":
        import argparse

        from meta_flow.workspace.git_sync import legacy_workspace_push_plan, push_workspace

        parser = argparse.ArgumentParser(
            prog="meta-flow workspace push",
            description="Push project and external artifact git repositories together.",
        )
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--remote", default="origin")
        parser.add_argument("--branch", default=None)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--authorization", type=Path, default=None)
        parser.add_argument(
            "--allow-dirty",
            action="store_true",
            help="Allow pushing committed refs while either working tree is dirty.",
        )
        parsed = parser.parse_args(args[1:])
        plan = None
        capability = None
        if not parsed.dry_run:
            plan = legacy_workspace_push_plan(
                parsed.project_root,
                remote=parsed.remote,
                branch=parsed.branch,
                allow_dirty=parsed.allow_dirty,
            )
            if parsed.authorization is None:
                print(json.dumps({"plan": plan, "error": "push requires --authorization"}, ensure_ascii=False, sort_keys=True))
                raise SystemExit(2)
            from meta_flow.workspace.legacy_route_adapter import load_legacy_authorization

            try:
                capability = load_legacy_authorization(parsed.authorization)
            except (OSError, ValueError) as exc:
                print(json.dumps({"plan": plan, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
                raise SystemExit(2) from exc
        try:
            status, lines = push_workspace(
                parsed.project_root,
                remote=parsed.remote,
                branch=parsed.branch,
                dry_run=parsed.dry_run,
                allow_dirty=parsed.allow_dirty,
                capability=capability,
            )
        except ValueError as exc:
            print(json.dumps({"plan": plan, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
            raise SystemExit(2) from exc
        for line in lines:
            print(line)
        raise SystemExit(status)
    raise SystemExit(f"未知 workspace 命令: {command}. 目前支持: check, link, bootstrap, git-status, push")


def _run_eval(args: list[str]) -> None:
    from meta_flow.evals import runner

    raise SystemExit(runner.main(args))


def _run_ask_user(args: list[str]) -> None:
    from meta_flow import ask_user

    raise SystemExit(ask_user.main(args))


def _run_state(args: list[str]) -> None:
    from meta_flow.state import current

    raise SystemExit(current.main(args))


def _run_cr(args: list[str]) -> None:
    from meta_flow.workflow import cr_lifecycle

    raise SystemExit(cr_lifecycle.main(args))


def _run_cp(args: list[str]) -> None:
    from meta_flow.checks import cp_result

    raise SystemExit(cp_result.main(args))


def _run_event(args: list[str]) -> None:
    from meta_flow.state import event_ledger

    raise SystemExit(event_ledger.main(args))


def _run_ledger(args: list[str]) -> None:
    from meta_flow.state import ledger_compaction

    raise SystemExit(ledger_compaction.main(args))


def _run_story(args: list[str]) -> None:
    from meta_flow.workflow import story_evidence

    raise SystemExit(story_evidence.main(args))


def _run_design(args: list[str]) -> None:
    from meta_flow.workflow import story_evidence

    raise SystemExit(story_evidence.design_main(args))


def _run_validation(args: list[str]) -> None:
    from meta_flow.validation import task_runner

    raise SystemExit(task_runner.main(args))


def _run_context(args: list[str]) -> None:
    from meta_flow.context_pack import builder

    raise SystemExit(builder.main(args))


def _run_capability(args: list[str]) -> None:
    from meta_flow.design import product_governance

    raise SystemExit(product_governance.capability_main(args))


def _run_concept(args: list[str]) -> None:
    from meta_flow.design import product_governance

    raise SystemExit(product_governance.concept_main(args))


def _run_feature(args: list[str]) -> None:
    from meta_flow.design import feature_registry

    raise SystemExit(feature_registry.main(args))


def _run_gate(args: list[str]) -> None:
    from meta_flow.policies import gate_profiles

    raise SystemExit(gate_profiles.main(args))


def _run_route(args: list[str]) -> None:
    from meta_flow.policies import route_plan

    raise SystemExit(route_plan.main(args))


def _run_failure(args: list[str]) -> None:
    from meta_flow.policies import failure_routing

    raise SystemExit(failure_routing.failure_main(args))


def _run_governance(args: list[str]) -> None:
    from meta_flow.policies import governance

    raise SystemExit(governance.main(args))


def _run_module(args: list[str]) -> None:
    from meta_flow.design import module_boundaries

    raise SystemExit(module_boundaries.main(args))


def _run_identity(args: list[str]) -> None:
    from meta_flow.design import product_governance

    raise SystemExit(product_governance.identity_main(args))


def _run_policy(args: list[str]) -> None:
    from meta_flow.policies import authz

    raise SystemExit(authz.main(args))


def _run_project(args: list[str]) -> None:
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: meta-flow project <command> [options]\n\n"
            "Commands:\n"
            "  init      Preview or apply a vNext independent process repository.\n"
            "  adopt     Preview or explicitly authorize one snapshot-only project adoption.\n"
            "  recover   Inspect or explicitly recover one partial onboarding transaction.\n"
            "  status    Check the vNext project binding and independent process route.\n"
            "  query     Read at most five directly referenced Project/Phase/Work objects.\n"
            "  resolve-ref  Resolve one process/... logical ref through the vNext binding.\n"
            "  scaffold  Preview or apply process/project/PROJECT.current.json scaffold.\n"
            "  phase-metadata  Plan/apply/inspect/recover one typed Phase result_refs append.\n"
            "  phase-transition  Plan/apply/inspect/recover one durable Project/Phase transition.\n"
            "  check     Validate vNext binding when present; otherwise validate legacy project governance.\n\n"
            "Examples:\n"
            "  meta-flow project init --project-root . --project-id demo\n"
            "  meta-flow project init --project-root . --project-id demo --source-process-root ../snapshot-process\n"
            "  meta-flow project init --project-root . --project-id demo --apply --authorization /tmp/init-auth.json\n"
            "  meta-flow project adopt --project-root . --project-id demo --source-id snapshot --source-process-root ../snapshot --include-ref PROJECT.yaml\n"
            "  meta-flow project recover --project-root . --authorization-id auth-001 --action inspect\n"
            "  meta-flow project status --project-root .\n"
            "  meta-flow project query --project-root .\n"
            "  meta-flow project resolve-ref --project-root . --logical-ref process/PROJECT.yaml --format json\n"
            "  meta-flow project scaffold --project-root .\n"
            "  meta-flow project scaffold --project-root . --apply\n"
            "  meta-flow project phase-metadata plan --project-root . --project-id demo --work-id W1 --phase-ref process/phases/P1/PHASE.yaml --append-result-ref process/works/W0/EVIDENCE.json --scope-digest <sha256> --effective-at 2026-01-01T00:00:00Z\n"
            "  meta-flow project phase-transition plan --project-root . --project-id demo --from-phase-ref process/phases/P1/PHASE.yaml --to-phase-ref process/phases/P2/PHASE.yaml --closure-evidence-ref process/phases/P1/CLOSURE.json --effective-at 2026-01-01T00:00:00Z --immutable-commit-role release_input=release:<oid> --immutable-commit-role process_input=process:<oid>\n"
            "  meta-flow project check --project-root .\n"
        )
        return
    command = args[0]
    forwarded = args[1:]
    if command == "init":
        from meta_flow.project import onboarding

        raise SystemExit(onboarding.init_main(forwarded))
    if command == "adopt":
        from meta_flow.project import adoption

        raise SystemExit(adoption.main(forwarded))
    if command == "recover":
        from meta_flow.project import recovery

        raise SystemExit(recovery.main(forwarded))
    if command == "status":
        from meta_flow.project import onboarding

        raise SystemExit(onboarding.status_main(forwarded))
    if command == "query":
        from meta_flow.project import query

        raise SystemExit(query.main(forwarded))
    if command == "resolve-ref":
        from meta_flow.project import process_route

        raise SystemExit(process_route.resolve_ref_main(forwarded))
    if command == "scaffold":
        from meta_flow.project import scaffold

        raise SystemExit(scaffold.main(forwarded))
    if command == "phase-transition":
        from meta_flow.project import phase_transition

        raise SystemExit(phase_transition.main(forwarded))
    if command == "phase-metadata":
        from meta_flow.project import phase_metadata

        raise SystemExit(phase_metadata.main(forwarded))
    if command == "check":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed, _unknown = parser.parse_known_args(forwarded)
        if (parsed.project_root.resolve() / ".meta-flow" / "workspace.yaml").is_file():
            from meta_flow.project import onboarding

            raise SystemExit(
                onboarding.status_main(
                    forwarded,
                    prog="meta-flow project check",
                )
            )
        from meta_flow.project import state

        raise SystemExit(state.main(forwarded))
    raise SystemExit(
        f"未知 project 命令: {command}. 目前支持: init, adopt, recover, status, query, resolve-ref, scaffold, phase-metadata, phase-transition, check"
    )


def _run_work(args: list[str]) -> None:
    from meta_flow.work import cli as work_cli

    raise SystemExit(work_cli.main(args))


def _run_retrospective(args: list[str]) -> None:
    from meta_flow import retrospective_cli

    raise SystemExit(retrospective_cli.main(args))


def _run_evolution(args: list[str]) -> None:
    from meta_flow import evolution_cli

    raise SystemExit(evolution_cli.main(args))


def _run_repository(args: list[str]) -> None:
    from meta_flow.repository import cli as repository_cli

    raise SystemExit(repository_cli.main(args))


def _run_quality(args: list[str]) -> None:
    from meta_flow.checks import quality_governance

    raise SystemExit(quality_governance.quality_main(args))


def _run_waiver(args: list[str]) -> None:
    from meta_flow.policies import failure_routing

    raise SystemExit(failure_routing.waiver_main(args))


def _preflight_top_level_process_route(command: str, args: list[str]) -> None:
    """阻止顶层 check 命令把错误根静默解释为 legacy 布局。"""

    if not args or (command, args[0]) not in {
        ("project", "check"),
        ("state", "check"),
    }:
        return
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parsed, _unknown = parser.parse_known_args(args[1:])
    require_process_route(parsed.project_root)


def _dispatch_main() -> None:
    args = sys.argv[1:]
    if args == ["--version"]:
        _run_version([])
        return
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return

    command = args[0]
    _preflight_top_level_process_route(command, args[1:])
    if command not in {"version", "install", "upgrade", "uninstall", "reinstall"}:
        _guard_provider_mutation(command, args[1:])
    if command == "status":
        _print_status()
        return
    if command == "next":
        _print_next()
        return
    if command == "doctor":
        _run_doctor(args[1:])
        return
    if command in {"install", "upgrade", "uninstall"}:
        _run_installer(command, args[1:])
        return
    if command == "reinstall":
        _run_lifecycle_reinstaller(args[1:])
        return
    if command == "recover":
        _run_lifecycle_recovery(args[1:])
        return
    if command == "version":
        _run_version(args[1:])
        return
    if command == "check":
        _run_check(args[1:])
        return
    if command == "capability":
        _run_capability(args[1:])
        return
    if command == "concept":
        _run_concept(args[1:])
        return
    if command == "context":
        _run_context(args[1:])
        return
    if command == "cp":
        _run_cp(args[1:])
        return
    if command == "feature":
        _run_feature(args[1:])
        return
    if command == "failure":
        _run_failure(args[1:])
        return
    if command == "gate":
        _run_gate(args[1:])
        return
    if command == "route":
        _run_route(args[1:])
        return
    if command == "governance":
        _run_governance(args[1:])
        return
    if command == "module":
        _run_module(args[1:])
        return
    if command == "identity":
        _run_identity(args[1:])
        return
    if command == "policy":
        _run_policy(args[1:])
        return
    if command == "project":
        _run_project(args[1:])
        return
    if command == "work":
        _run_work(args[1:])
        return
    if command == "retrospective":
        _run_retrospective(args[1:])
        return
    if command == "evolution":
        _run_evolution(args[1:])
        return
    if command == "repository":
        _run_repository(args[1:])
        return
    if command == "quality":
        _run_quality(args[1:])
        return
    if command == "waiver":
        _run_waiver(args[1:])
        return
    if command == "workspace":
        _run_workspace(args[1:])
        return
    if command == "eval":
        _run_eval(args[1:])
        return
    if command == "ask-user":
        _run_ask_user(args[1:])
        return
    if command == "state":
        _run_state(args[1:])
        return
    if command == "cr":
        _run_cr(args[1:])
        return
    if command == "event":
        _run_event(args[1:])
        return
    if command == "ledger":
        _run_ledger(args[1:])
        return
    if command == "story":
        _run_story(args[1:])
        return
    if command == "validation":
        _run_validation(args[1:])
        return
    if command == "design":
        _run_design(args[1:])
        return
    raise SystemExit(
        "未知命令: "
        "install, upgrade, uninstall, reinstall, recover, version, check, capability, concept, context, cp, cr, design, event, eval, feature, failure, gate, route, identity, ledger, "
        "governance, module, policy, project, work, retrospective, evolution, repository, quality, story, validation, waiver, ask-user, state, status, next, doctor"
    )


def main() -> None:
    """顶层 CLI 错误边界：契约型路由失败必须稳定、零写且不暴露 traceback。"""

    try:
        _dispatch_main()
    except ProcessRouteError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": False,
                    "decision": "BLOCKED",
                    "error_code": "PROCESS_ROUTE_UNHEALTHY",
                    "route_error_code": exc.error_code,
                    "message": str(exc),
                    "logical_ref": exc.logical_ref,
                    "hint": "--project-root must reference the release repository root with a healthy .meta-flow/workspace.yaml binding",
                    "mutation_count": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None
if __name__ == "__main__":
    main()
