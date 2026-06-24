"""Command line entry point for Meta Flow."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

from meta_flow.workspace.routing import (
    bootstrap_process_workspace,
    check_process_route,
    link_process_workspace,
    require_process_health,
)


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    if os.environ.get("META_FLOW_SOURCE"):
        roots.append(Path(os.environ["META_FLOW_SOURCE"]).expanduser())

    cwd = Path.cwd()
    roots.extend([cwd, *cwd.parents])

    package_root = Path(__file__).resolve().parent
    roots.extend([package_root.parent, *package_root.parents])
    return roots


def _find_installer() -> Path:
    for root in _candidate_roots():
        candidate = root / "delivery" / "scripts" / "install.py"
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "无法定位 Meta Flow 安装器。请在 meta-flow 仓库内运行，"
        "或设置 META_FLOW_SOURCE 指向包含 delivery/scripts/install.py 的目录。"
    )


def _find_workspace_root() -> Path:
    for root in _candidate_roots():
        if (root / "process" / "state" / "STATE.current.json").is_file() or (root / "process" / "STATE.md").is_file():
            return root
    return Path.cwd()


def _read_state() -> tuple[Path, str]:
    root = _find_workspace_root()
    require_process_health(root)
    state_path = root / "process" / "STATE.md"
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
    current_path = root / "process" / "state" / "STATE.current.json"
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
    health = check_process_route(root)

    state_path = root / "process" / "STATE.md"
    if not state_path.is_file():
        problems.append(f"缺少 {state_path}")
    if health.blocking:
        problems.extend(health.errors)
    for rel in ("process/checks", "process/checkpoints"):
        if not (root / rel).is_dir():
            warnings.append(f"缺少目录 {rel}")
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
        for line in health.format_lines():
            print(line)
        for item in problems:
            print(f"- ERROR: {item}")
        for item in warnings:
            print(f"- WARN: {item}")
        return 1

    print("Doctor: OK")
    for line in health.format_lines():
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

        from meta_flow.checks import context_doctor
        from meta_flow.checks import quality_governance
        from meta_flow.checks import token_budget

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
        "  uninstall  Uninstall Meta Flow assets recorded in INSTALL-MANIFEST.\n"
        "  check      Run packaged Meta Flow validators.\n"
        "  capability Validate capability status and docs claims.\n"
        "  concept    Validate concept ownership and overlap.\n"
        "  context    Build, validate, and explain context-budgeted context packs.\n"
        "  cp         Validate CP result JSON, render summaries, and append checkpoint ledger events.\n"
        "  cr         Manage CR lifecycle ledgers, summaries, index, and conflicts.\n"
        "  design     Validate design deltas and long-lived design write-back status.\n"
        "  event      Append, list, and validate NDJSON process event ledgers.\n"
        "  eval       Validate and run local workflow evaluation packages.\n"
        "  feature    Manage Feature Registry and Story-to-Feature traceability.\n"
        "  failure    Validate failure routing policy and CP route_on_fail values.\n"
        "  gate       Classify and validate gate profiles.\n"
        "  governance Validate source-of-truth and retention lifecycle policies.\n"
        "  identity   Validate product/package/import/CLI identity.\n"
        "  module     Validate module boundaries, imports, risk rings, and architecture fitness.\n"
        "  policy     List, expand, and validate authorization policies.\n"
        "  quality    Validate quality model and eval matrix policies.\n"
        "  story      Validate Story return packets and evidence indexes.\n"
        "  waiver     Validate waiver policy and CP waiver records.\n"
        "  ask-user   Generate exact user prompts or Codex request_user_input payloads.\n"
        "  state      Migrate, render, and validate lightweight runtime state v2.\n"
        "  workspace  Check, link, bootstrap, status, or push the external process workspace.\n"
        "  status     Show current process/STATE.md summary.\n"
        "  next       Show the exact next prompt; never falls back to vague continue/agree wording.\n"
        "  doctor     Check local Meta Flow runtime structure, token budgets, context expansion, or artifacts.\n\n"
        "Examples:\n"
        "  meta-flow install codex --scope user --component rules\n"
        "  meta-flow install claude --scope project --project-dir /path/to/repo\n"
        "  meta-flow uninstall codex --scope user\n"
        "  meta-flow check human-gate --checkpoint process/checkpoints/CP3-HLD-REVIEW.md\n"
        "  meta-flow ask-user human-gate --checkpoint process/checkpoints/CP3-HLD-REVIEW.md --format codex-json\n"
        "  meta-flow context build --stage CP6 --profile standard-code --cr CR-101 --project-root .\n"
        "  meta-flow context check --context process/context/CP6-CR101.context.json --project-root .\n"
        "  meta-flow context sufficiency-check --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json\n"
        "  meta-flow context read-log --path process/STATE.md --reason human_audit --stage CP6 --agent meta-dev --context-ref process/context/CP6.context.json --project-root .\n"
        "  meta-flow context read-log-check --project-root .\n"
        "  meta-flow doctor context --project-root .\n"
        "  meta-flow cp result-check --result process/checks/CP6-STORY.result.json --project-root .\n"
        "  meta-flow event check --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint\n"
        "  meta-flow capability check --artifact README.md --project-root .\n"
        "  meta-flow concept check --changed-files quant_lab/engine/contracts.py --project-root .\n"
        "  meta-flow identity check --project-root .\n"
        "  meta-flow identity scan --project-root .\n"
        "  meta-flow feature check --project-root .\n"
        "  meta-flow feature trace --project-root .\n"
        "  meta-flow failure route-check --result process/checks/CP7-STORY.result.json --project-root .\n"
        "  meta-flow waiver check --result process/checks/CP8-DELIVERY.result.json --project-root .\n"
        "  meta-flow story return-check --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .\n"
        "  meta-flow design delta-check --delta process/design-deltas/STORY-CR123-S01.delta.json --project-root .\n"
        "  meta-flow check module-boundaries --project-root .\n"
        "  meta-flow check imports --project-root .\n"
        "  meta-flow check risk-rings --changed-files quant_lab/trading/order.py --project-root .\n"
        "  meta-flow gate classify --changed-files README.md\n"
        "  meta-flow governance truth-map-check --project-root .\n"
        "  meta-flow policy list --project-root .\n"
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
    installer = _find_installer()
    forwarded = [*args]
    if command == "uninstall":
        forwarded = ["uninstall", *forwarded]
    original_argv = sys.argv[:]
    try:
        sys.argv = [f"meta-flow {command}", *forwarded]
        namespace = runpy.run_path(str(installer), run_name="__meta_flow_installer__")
        namespace["main"]()
    finally:
        sys.argv = original_argv


def _print_check_help() -> None:
    print(
        "usage: meta-flow check <validator> [options]\n\n"
        "Validators:\n"
        "  human-gate   Validate CP2/CP3/CP5/CP8 Decision Brief and optional launch message.\n"
        "  cr-tracking  Validate CR tracking consistency across STATE, CR files, follow-up tables, and CR-INDEX.\n\n"
        "  design-ownership       Validate FEATURE-REGISTRY ownership fields.\n"
        "  story-to-feature-trace Validate Story feature refs and LLD policy.\n\n"
        "  story-return          Validate Story Return Packet against Story context packet.\n"
        "  evidence-index        Validate Story Evidence Index.\n"
        "  design-delta          Validate Story design delta structure and write-back status.\n\n"
        "  cp-result             Validate CP result JSON machine truth source.\n"
        "  event-ledger          Validate NDJSON event ledger structure.\n"
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
        "  retention-policy      Validate process retention lifecycle policy.\n\n"
        "Examples:\n"
        "  meta-flow check human-gate --checkpoint process/checkpoints/CP3-HLD-REVIEW.md\n"
        "  meta-flow check human-gate --checkpoint process/checkpoints/CP5-STORY-DESIGN-REVIEW.md --launch-message-file process/checkpoints/CP5-LAUNCH-MESSAGE.md\n"
        "  meta-flow check cr-tracking --project-root .\n"
        "  meta-flow check design-ownership --project-root .\n"
        "  meta-flow check story-to-feature-trace --project-root .\n"
        "  meta-flow check story-return --packet process/context/stories/STORY-CR123-S01.CP6.work-packet.json --return process/returns/STORY-CR123-S01.CP6.return.json --project-root .\n"
        "  meta-flow check evidence-index --index process/evidence/STORY-CR123-S01.CP6.index.json --project-root .\n"
        "  meta-flow check design-delta --delta process/design-deltas/STORY-CR123-S01.delta.json --project-root .\n"
        "  meta-flow check cp-result --result process/checks/CP6-STORY.result.json --project-root .\n"
        "  meta-flow check event-ledger --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint\n"
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
    if validator == "design-delta":
        from meta_flow.workflow import story_evidence

        raise SystemExit(story_evidence.design_main(["delta-check", *forwarded]))
    if validator == "cp-result":
        from meta_flow.checks import cp_result

        raise SystemExit(cp_result.main(["result-check", *forwarded]))
    if validator == "event-ledger":
        from meta_flow.state import event_ledger

        raise SystemExit(event_ledger.main(["check", *forwarded]))
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
    if validator == "retention-policy":
        from meta_flow.policies import governance

        raise SystemExit(governance.main(["retention-check", *forwarded]))
    raise SystemExit(
        "未知检查器: "
        f"{validator}. 目前支持: human-gate, cr-tracking, design-ownership, story-to-feature-trace, "
        "story-return, evidence-index, design-delta, cp-result, event-ledger, read-expansion, "
        "failure-routing, waiver-policy, "
        "module-boundaries, imports, architecture-fitness, risk-rings, capability-claims, concept-overlap, "
        "package-identity, truth-map, retention-policy"
    )


def _print_workspace_help() -> None:
    print(
        "usage: meta-flow workspace <command> [options]\n\n"
        "Commands:\n"
        "  check      Print process route health.\n"
        "  link       Create process -> <artifact-root>/process/<project-name> and process scaffold.\n"
        "  bootstrap  Link process and initialize STATE.current.json, STATE.md, and base ledgers.\n"
        "  git-status Print project and artifact git status together.\n"
        "  push       Push project and artifact git repositories together.\n\n"
        "Push refuses dirty working trees by default so process artifacts cannot be missed silently.\n\n"
        "Examples:\n"
        "  meta-flow workspace check\n"
        "  meta-flow workspace link --artifact-root ../meta-flow-artifacts --project-name meta-flow\n"
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
        health = check_process_route(root)
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
        parsed = parser.parse_args(args[1:])
        health = link_process_workspace(parsed.project_root, parsed.artifact_root, parsed.project_name)
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
        parsed = parser.parse_args(args[1:])
        health = bootstrap_process_workspace(
            parsed.project_root,
            parsed.artifact_root,
            parsed.project_name,
            force=parsed.force,
        )
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

        from meta_flow.workspace.git_sync import push_workspace

        parser = argparse.ArgumentParser(
            prog="meta-flow workspace push",
            description="Push project and external artifact git repositories together.",
        )
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--remote", default="origin")
        parser.add_argument("--branch", default=None)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--allow-dirty",
            action="store_true",
            help="Allow pushing committed refs while either working tree is dirty.",
        )
        parsed = parser.parse_args(args[1:])
        status, lines = push_workspace(
            parsed.project_root,
            remote=parsed.remote,
            branch=parsed.branch,
            dry_run=parsed.dry_run,
            allow_dirty=parsed.allow_dirty,
        )
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


def _run_story(args: list[str]) -> None:
    from meta_flow.workflow import story_evidence

    raise SystemExit(story_evidence.main(args))


def _run_design(args: list[str]) -> None:
    from meta_flow.workflow import story_evidence

    raise SystemExit(story_evidence.design_main(args))


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


def _run_quality(args: list[str]) -> None:
    from meta_flow.checks import quality_governance

    raise SystemExit(quality_governance.quality_main(args))


def _run_waiver(args: list[str]) -> None:
    from meta_flow.policies import failure_routing

    raise SystemExit(failure_routing.waiver_main(args))


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return

    command = args[0]
    if command == "status":
        _print_status()
        return
    if command == "next":
        _print_next()
        return
    if command == "doctor":
        _run_doctor(args[1:])
        return
    if command in {"install", "uninstall"}:
        _run_installer(command, args[1:])
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
    if command == "story":
        _run_story(args[1:])
        return
    if command == "design":
        _run_design(args[1:])
        return
    raise SystemExit(
        "未知命令: "
        "install, uninstall, check, capability, concept, context, cp, cr, design, event, eval, feature, failure, gate, identity, "
        "governance, module, policy, quality, story, waiver, ask-user, state, status, next, doctor"
    )


if __name__ == "__main__":
    main()
