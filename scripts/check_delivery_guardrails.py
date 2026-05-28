#!/usr/bin/env python3
"""Check repository guardrails for delivery asset ownership and Python cache hygiene."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DELIVERY_ROOT = ROOT / "delivery"
PROCESS_ROOT = ROOT / "process"
CHANGE_ROOT = PROCESS_ROOT / "changes"
PLATFORM_CONTRACTS = DELIVERY_ROOT / "doc" / "PLATFORM-CONTRACTS.yaml"
ALLOWED_DELIVERY_DIRS = {"agents", "doc", "rules", "scripts", "skills"}
ALLOWED_DELIVERY_SCRIPT_FILES = {"install.py", "install.sh", "install.ps1"}
REVISION_RECORD_TARGETS = {
    "process/USE-CASES.md": PROCESS_ROOT / "USE-CASES.md",
    "process/REQUIREMENTS.md": PROCESS_ROOT / "REQUIREMENTS.md",
}
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
SKILL_ROOT_ASSET_REF_RE = re.compile(r"<skill-root>/(?P<kind>templates|scripts)/(?P<path>[A-Za-z0-9_./-]+)")
TEMPLATE_REF_RE = re.compile(r"(?<![A-Za-z0-9_./-])templates/(?P<path>[A-Za-z0-9_./-]+)")
DELIVERY_SCRIPT_REF_RE = re.compile(r"delivery/scripts/(?P<name>[A-Za-z0-9_.-]+)")
CODEX_CONFIRMATION_TOKENS = (
    "request_user_input",
    "approve",
    "修改: <具体修改点>",
    "reject",
    "别名",
    "待人工决策",
    "备选方案",
    "优劣",
)
DELIVERY_ROUTING_TOKENS = ("production", "README", "docs", "交付")
GUARDRAIL_CONDITION_TOKENS = ("仅当当前仓库存在", "外部 production 项目不得硬引用")
CACHE_SCAN_EXCLUDED_DIRS = {".git", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
EXPECTED_CODEX_NICKNAMES = {
    "meta-po": ["po-zhao", "po-qian", "po-sun", "po-li", "po-zhou"],
    "meta-pm": ["pm-wu", "pm-zheng", "pm-wang", "pm-feng", "pm-chen"],
    "meta-se": ["se-chu", "se-wei", "se-jiang", "se-shen", "se-han"],
    "meta-dev": [
        "dev-yang",
        "dev-zhu",
        "dev-qin",
        "dev-you",
        "dev-xu",
        "dev-he",
        "dev-lv",
        "dev-shi",
        "dev-zhang",
        "dev-kong",
    ],
    "meta-qa": [
        "qa-he",
        "qa-lv",
        "qa-shi",
        "qa-zhang",
        "qa-kong",
        "qa-cao",
        "qa-yan",
        "qa-hua",
        "qa-jin",
        "qa-wei",
    ],
    "meta-doc": ["doc-cao", "doc-yan", "doc-hua", "doc-jin", "doc-wei"],
}
EXPECTED_CLAUDE_COLORS = {
    "meta-po": "red",
    "meta-pm": "orange",
    "meta-se": "yellow",
    "meta-dev": "green",
    "meta-qa": "cyan",
    "meta-doc": "purple",
}
CODEX_NICKNAME_RE = re.compile(r"^[A-Za-z0-9 _-]+$")


def is_under_excluded_cache_dir(path: Path) -> bool:
    rel_parts = path.relative_to(ROOT).parts
    return any(part in CACHE_SCAN_EXCLUDED_DIRS for part in rel_parts)


def load_platform_contracts(errors: list[str]) -> dict[str, object]:
    if not PLATFORM_CONTRACTS.is_file():
        errors.append(f"missing platform contract source: {PLATFORM_CONTRACTS.relative_to(ROOT)}")
        return {}
    try:
        return json.loads(PLATFORM_CONTRACTS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"platform contract must be JSON-compatible YAML: {PLATFORM_CONTRACTS.relative_to(ROOT)} -> {exc}")
        return {}


def collect_platform_contract_errors(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    try:
        codex = payload["contracts"]["codex"]  # type: ignore[index]
        claude = payload["contracts"]["claude"]  # type: ignore[index]
        project = codex["scopes"]["project"]  # type: ignore[index]
        user = codex["scopes"]["user"]  # type: ignore[index]
        claude_project = claude["scopes"]["project"]  # type: ignore[index]
        claude_user = claude["scopes"]["user"]  # type: ignore[index]
        forbidden_project = codex["forbidden"]["project"]  # type: ignore[index]
        forbidden_user = codex["forbidden"]["user"]  # type: ignore[index]
    except (AttributeError, KeyError, TypeError):
        return ["platform contract missing codex/claude scopes or codex forbidden entries"]

    expected = {
        "claude project rules": (claude_project.get("rules"), "CLAUDE.md"),
        "claude project agents": (claude_project.get("agents"), ".claude/agents"),
        "claude project skills": (claude_project.get("skills"), ".claude/skills"),
        "claude user rules": (claude_user.get("rules"), "~/.claude/CLAUDE.md"),
        "claude user agents": (claude_user.get("agents"), "~/.claude/agents"),
        "claude user skills": (claude_user.get("skills"), "~/.claude/skills"),
        "codex project agents": (project.get("agents"), ".codex/agents"),
        "codex project skills": (project.get("skills"), ".agents/skills"),
        "codex user agents": (user.get("agents"), "~/.codex/agents"),
        "codex user skills": (user.get("skills"), "~/.agents/skills"),
    }
    for label, (actual, required) in expected.items():
        if actual != required:
            errors.append(f"platform contract mismatch: {label} must be {required}, got {actual}")

    if ".codex/skills" not in forbidden_project:
        errors.append("platform contract must forbid codex project .codex/skills")
    if "~/.codex/skills" not in forbidden_user:
        errors.append("platform contract must forbid codex user ~/.codex/skills")
    return errors


def collect_codex_dry_run_errors(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    install_script = DELIVERY_ROOT / "scripts" / "install.py"
    if not install_script.is_file():
        return [f"missing installer: {install_script.relative_to(ROOT)}"]

    with tempfile.TemporaryDirectory(prefix="meta-flow-guardrail-") as tmp:
        project_root = Path(tmp)
        cases = [
            ("project", project_root / ".agents" / "skills" / "context-handoff" / "SKILL.md", ".codex/skills"),
            ("user", Path.home() / ".agents" / "skills" / "context-handoff" / "SKILL.md", str(Path.home() / ".codex" / "skills")),
        ]
        for scope, required_path, forbidden_path in cases:
            result = subprocess.run(
                [
                    sys.executable,
                    str(install_script),
                    "codex",
                    "--scope",
                    scope,
                    "--project-dir",
                    str(project_root),
                    "--content",
                    "skills",
                    "--skill",
                    "context-handoff",
                    "--dry-run",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout + result.stderr
            if result.returncode != 0:
                errors.append(f"codex {scope} dry-run failed with exit {result.returncode}: {output.strip()}")
                continue
            if str(required_path) not in output:
                errors.append(f"codex {scope} dry-run missing required skill path: {required_path}")
            if forbidden_path in output or ".codex/skills" in output:
                errors.append(f"codex {scope} dry-run must not target forbidden skill path: {forbidden_path}")

        conflict_root = project_root / "path-conflict"
        conflict_root.mkdir()
        blocker = conflict_root / ".codex"
        blocker.write_text("file occupying a directory path\n", encoding="utf-8")
        conflict_result = subprocess.run(
            [
                sys.executable,
                str(install_script),
                "codex",
                "--scope",
                "project",
                "--project-dir",
                str(conflict_root),
                "--content",
                "agents",
                "--agent",
                "meta-po",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        conflict_output = conflict_result.stdout + conflict_result.stderr
        if conflict_result.returncode == 0:
            errors.append("codex project install must fail when .codex is a file")
        if "安装路径被非目录占用:" not in conflict_output or str(blocker) not in conflict_output:
            errors.append("codex path conflict must report a clear occupied-path error")
        if "Traceback" in conflict_output or "NotADirectoryError" in conflict_output:
            errors.append("codex path conflict must not expose a Python traceback")

    contract_errors = collect_platform_contract_errors(payload)
    errors.extend(contract_errors)
    return errors


def collect_installer_component_errors() -> list[str]:
    errors: list[str] = []
    install_script = DELIVERY_ROOT / "scripts" / "install.py"
    pyproject = ROOT / "pyproject.toml"
    cli_module = ROOT / "meta_flow" / "cli.py"

    if not pyproject.is_file():
        errors.append("missing pyproject.toml for uv tool installation")
    else:
        try:
            project_config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"pyproject.toml is not valid TOML: {exc}")
        else:
            scripts = project_config.get("project", {}).get("scripts", {})
            if scripts.get("meta-flow") != "meta_flow.cli:main":
                errors.append("pyproject.toml must expose console script: meta-flow = meta_flow.cli:main")
            if project_config.get("project", {}).get("readme") != "delivery/README.md":
                errors.append("pyproject.toml project.readme must point at delivery/README.md")

    if not cli_module.is_file():
        errors.append("missing meta_flow/cli.py for meta-flow command")
    else:
        cli_text = cli_module.read_text(encoding="utf-8")
        for required in ("install", "META_FLOW_SOURCE", "delivery/scripts/install.py"):
            if required not in cli_text:
                errors.append(f"meta_flow/cli.py missing required token: {required}")

    if not install_script.is_file():
        return errors + [f"missing installer: {install_script.relative_to(ROOT)}"]

    help_cases = [
        {
            "label": "installer --help",
            "args": ["--help"],
            "required": ("<platform>", "--component", "rules", "agent", "full", "--content"),
        },
        {
            "label": "installer platform --help",
            "args": ["codex", "--help"],
            "required": ("<platform>", "--component", "rules", "agent", "full", "--content"),
        },
        {
            "label": "installer uninstall --help",
            "args": ["uninstall", "--help"],
            "required": ("Uninstall", "<platform>", "--component", "rules", "agent", "full"),
        },
        {
            "label": "installer uninstall platform --help",
            "args": ["uninstall", "codex", "--help"],
            "required": ("Uninstall", "<platform>", "--component", "rules", "agent", "full"),
        },
    ]
    for help_case in help_cases:
        help_result = subprocess.run(
            [sys.executable, str(install_script), *help_case["args"]],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        help_output = help_result.stdout + help_result.stderr
        if help_result.returncode != 0:
            errors.append(f"{help_case['label']} failed with exit {help_result.returncode}: {help_output.strip()}")
            continue
        for required in help_case["required"]:
            if required not in help_output:
                errors.append(f"{help_case['label']} missing help token: {required}")

    with tempfile.TemporaryDirectory(prefix="meta-flow-component-") as tmp:
        project_root = Path(tmp)
        cases = [
            {
                "label": "codex user default",
                "args": ["codex", "--scope", "user", "--project-dir", str(project_root), "--dry-run"],
                "required": ["Component: rules", str(Path.home() / ".codex" / "AGENTS.md")],
                "forbidden": [str(Path.home() / ".codex" / "agents" / "meta-po.toml"), str(Path.home() / ".agents" / "skills")],
            },
            {
                "label": "codex project default",
                "args": ["codex", "--scope", "project", "--project-dir", str(project_root), "--dry-run"],
                "required": ["Component: full", str(project_root / "AGENTS.md"), str(project_root / ".codex" / "agents" / "meta-po.toml"), str(project_root / ".agents" / "skills")],
                "forbidden": [".codex/skills"],
            },
            {
                "label": "claude project default",
                "args": ["claude", "--scope", "project", "--project-dir", str(project_root), "--dry-run"],
                "required": ["Component: full", str(project_root / "CLAUDE.md"), str(project_root / ".claude" / "agents" / "meta-po.md"), str(project_root / ".claude" / "skills")],
                "forbidden": [str(project_root / ".claude" / "CLAUDE.md")],
            },
            {
                "label": "codex full component",
                "args": ["codex", "--scope", "project", "--project-dir", str(project_root), "--component", "full", "--dry-run"],
                "required": ["Component: full", str(project_root / "AGENTS.md"), str(project_root / ".codex" / "agents" / "meta-po.toml"), str(project_root / ".agents" / "skills")],
                "forbidden": [".codex/skills"],
            },
            {
                "label": "legacy skills content",
                "args": [
                    "codex",
                    "--scope",
                    "project",
                    "--project-dir",
                    str(project_root),
                    "--content",
                    "skills",
                    "--skill",
                    "context-handoff",
                    "--dry-run",
                ],
                "required": ["Component: agent", "Legacy content: skills", str(project_root / ".agents" / "skills" / "context-handoff" / "SKILL.md")],
                "forbidden": [str(project_root / ".codex" / "agents" / "meta-po.toml"), ".codex/skills"],
            },
            {
                "label": "legacy platform option",
                "args": ["--platform", "codex", "--scope", "project", "--project-dir", str(project_root), "--component", "rules", "--dry-run"],
                "required": ["Component: rules", str(project_root / "AGENTS.md")],
                "forbidden": [".codex/skills"],
            },
        ]

        for case in cases:
            result = subprocess.run(
                [sys.executable, str(install_script), *case["args"]],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout + result.stderr
            if result.returncode != 0:
                errors.append(f"{case['label']} dry-run failed with exit {result.returncode}: {output.strip()}")
                continue
            for required in case["required"]:
                if required not in output:
                    errors.append(f"{case['label']} dry-run missing required output: {required}")
            for forbidden in case["forbidden"]:
                if forbidden in output:
                    errors.append(f"{case['label']} dry-run unexpectedly included: {forbidden}")

    return errors


def collect_cr004_protocol_errors() -> list[str]:
    errors: list[str] = []
    targets = [
        DELIVERY_ROOT / "agents" / "meta-po.md",
        DELIVERY_ROOT / "agents" / "meta-doc.md",
        DELIVERY_ROOT / "agents" / "meta-qa.md",
        DELIVERY_ROOT / "rules" / "AGENTS.md",
        DELIVERY_ROOT / "rules" / "CLAUDE.md",
        DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
    ]
    for target in targets:
        if not target.is_file():
            errors.append(f"missing CR-004 protocol target: {target.relative_to(ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        missing = [token for token in CODEX_CONFIRMATION_TOKENS if token not in text]
        if missing:
            errors.append(
                f"{target.relative_to(ROOT)} missing Codex confirmation protocol tokens: {', '.join(missing)}"
            )

    routing_targets = [
        DELIVERY_ROOT / "agents" / "meta-po.md",
        DELIVERY_ROOT / "agents" / "meta-pm.md",
        DELIVERY_ROOT / "agents" / "meta-doc.md",
        DELIVERY_ROOT / "skills" / "use-case-discovery" / "SKILL.md",
        DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
        DELIVERY_ROOT / "README.md",
        DELIVERY_ROOT / "rules" / "AGENTS.md",
        ROOT / "AGENTS.md",
    ]
    for target in routing_targets:
        if not target.is_file():
            errors.append(f"missing delivery routing target: {target.relative_to(ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        missing = [token for token in DELIVERY_ROUTING_TOKENS if token not in text]
        if missing:
            errors.append(f"{target.relative_to(ROOT)} missing delivery routing tokens: {', '.join(missing)}")

    state_template = DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md"
    if state_template.is_file():
        state_text = state_template.read_text(encoding="utf-8")
        for required in ("agent_lifecycle", "active_agents", "cp5_story_lld_review"):
            if required not in state_text:
                errors.append(f"{state_template.relative_to(ROOT)} missing lifecycle/state token: {required}")
    else:
        errors.append(f"missing state template: {state_template.relative_to(ROOT)}")

    handoff_skill = DELIVERY_ROOT / "skills" / "context-handoff" / "SKILL.md"
    if handoff_skill.is_file():
        handoff_text = handoff_skill.read_text(encoding="utf-8")
        for required in ("fork_context=false", "完整会话", "active_agents"):
            if required not in handoff_text:
                errors.append(f"{handoff_skill.relative_to(ROOT)} missing context-budget token: {required}")
    else:
        errors.append(f"missing context handoff skill: {handoff_skill.relative_to(ROOT)}")

    return errors


def collect_guardrail_command_scope_errors() -> list[str]:
    errors: list[str] = []
    targets = [
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        DELIVERY_ROOT / "rules" / "AGENTS.md",
        DELIVERY_ROOT / "rules" / "CLAUDE.md",
        DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
        DELIVERY_ROOT / "agents" / "meta-qa.md",
    ]
    for target in targets:
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        if "check_delivery_guardrails.py" not in text:
            continue
        missing = [token for token in GUARDRAIL_CONDITION_TOKENS if token not in text]
        if missing:
            errors.append(f"{target.relative_to(ROOT)} references check_delivery_guardrails.py without conditional scope tokens: {', '.join(missing)}")
        if "/home/hyde/projects/meta-flow/scripts/check_delivery_guardrails.py" in text and "不得硬引用" not in text:
            errors.append(f"{target.relative_to(ROOT)} must not hard-code the meta-flow guardrail absolute path")
    return errors


def collect_agent_dispatch_evidence_errors() -> list[str]:
    errors: list[str] = []
    targets = [
        DELIVERY_ROOT / "agents" / "meta-po.md",
        DELIVERY_ROOT / "skills" / "state-router" / "SKILL.md",
        DELIVERY_ROOT / "skills" / "state-router" / "templates" / "STATE-TEMPLATE.md",
        DELIVERY_ROOT / "skills" / "context-handoff" / "SKILL.md",
        DELIVERY_ROOT / "skills" / "checkpoint-manager" / "SKILL.md",
        DELIVERY_ROOT / "rules" / "AGENTS.md",
        DELIVERY_ROOT / "rules" / "CLAUDE.md",
        DELIVERY_ROOT / "doc" / "USER-MANUAL.md",
        DELIVERY_ROOT / "README.md",
        ROOT / "AGENTS.md",
    ]
    required_tokens = ("Agent Dispatch Evidence", "inline-fallback", "agent_id", "thread_id")
    for target in targets:
        if not target.is_file():
            errors.append(f"missing agent dispatch evidence target: {target.relative_to(ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            errors.append(f"{target.relative_to(ROOT)} missing agent dispatch evidence tokens: {', '.join(missing)}")

    meta_po = DELIVERY_ROOT / "agents" / "meta-po.md"
    if meta_po.is_file():
        text = meta_po.read_text(encoding="utf-8")
        for token in ("spawn_agent", "resume_agent", "send_input", "不得直接代替"):
            if token not in text:
                errors.append(f"{meta_po.relative_to(ROOT)} missing subagent hard-gate token: {token}")

    handoff_skill = DELIVERY_ROOT / "skills" / "context-handoff" / "SKILL.md"
    if handoff_skill.is_file():
        text = handoff_skill.read_text(encoding="utf-8")
        for token in ("dispatch:", "mode=subagent", "mode=inline-fallback", "not-subagent-executed"):
            if token not in text:
                errors.append(f"{handoff_skill.relative_to(ROOT)} missing dispatch frontmatter token: {token}")

    return errors


def collect_agent_display_profile_errors() -> list[str]:
    errors: list[str] = []
    install_script = DELIVERY_ROOT / "scripts" / "install.py"
    if not install_script.is_file():
        return [f"missing installer for display profile checks: {install_script.relative_to(ROOT)}"]

    source_text = install_script.read_text(encoding="utf-8")
    for token in ("AGENT_DISPLAY_PROFILES", "CODEX_NICKNAME_RE", "nickname_candidates", "claude_color", "po-zhao", "doc-wei"):
        if token not in source_text:
            errors.append(f"{install_script.relative_to(ROOT)} missing display profile token: {token}")

    with tempfile.TemporaryDirectory(prefix="meta-flow-display-") as tmp:
        project_root = Path(tmp)
        isolated_home = project_root / "home"
        isolated_home.mkdir()
        subprocess_env = {**os.environ, "HOME": str(isolated_home)}
        for platform in ("codex", "claude"):
            result = subprocess.run(
                [
                    sys.executable,
                    str(install_script),
                    platform,
                    "--scope",
                    "project",
                    "--project-dir",
                    str(project_root),
                    "--component",
                    "agent",
                ],
                cwd=ROOT,
                env=subprocess_env,
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout + result.stderr
            if result.returncode != 0:
                errors.append(f"{platform} display profile install failed with exit {result.returncode}: {output.strip()}")
                continue

        for agent_name, expected in EXPECTED_CODEX_NICKNAMES.items():
            agent_path = project_root / ".codex" / "agents" / f"{agent_name}.toml"
            if not agent_path.is_file():
                errors.append(f"missing codex agent for nickname check: {agent_path}")
                continue
            try:
                payload = tomllib.loads(agent_path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as exc:
                errors.append(f"codex agent TOML invalid for nickname check: {agent_path} -> {exc}")
                continue
            actual = payload.get("nickname_candidates")
            if actual != expected:
                errors.append(f"{agent_path.relative_to(project_root)} nickname_candidates must be {expected}, got {actual}")
            if isinstance(actual, list):
                invalid = [str(item) for item in actual if not CODEX_NICKNAME_RE.fullmatch(str(item))]
                if invalid:
                    errors.append(f"{agent_path.relative_to(project_root)} has invalid Codex nickname_candidates: {invalid}")

        for agent_name, expected_color in EXPECTED_CLAUDE_COLORS.items():
            agent_path = project_root / ".claude" / "agents" / f"{agent_name}.md"
            if not agent_path.is_file():
                errors.append(f"missing claude agent for color check: {agent_path}")
                continue
            text = agent_path.read_text(encoding="utf-8")
            fields = parse_frontmatter(text)
            if "nickname_candidates" in fields:
                errors.append(f"{agent_path.relative_to(project_root)} frontmatter must not contain Codex nickname_candidates")
            actual_color = fields.get("color")
            if actual_color != expected_color:
                errors.append(f"{agent_path.relative_to(project_root)} color must be {expected_color}, got {actual_color}")

    return errors


def parse_frontmatter(content: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def collect_git_changed_paths() -> set[str]:
    targets = list(REVISION_RECORD_TARGETS)
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", *targets],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def has_revision_record(content: str) -> bool:
    return "## 修订记录" in content


def cr_marks_document_changed(cr_path: Path, rel_path: str) -> bool:
    doc_name = Path(rel_path).name
    text = cr_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        normalized = line.replace("`", "")
        if rel_path not in normalized and doc_name not in normalized:
            continue
        if re.search(r"\|\s*false\s*\|", normalized):
            continue
        if re.search(r"\|\s*true\s*\|", normalized) or any(
            word in normalized for word in ("原文档更新", "新增", "修改", "更新", "重定义", "删除", "归档")
        ):
            return True
    return False


def collect_revision_record_errors() -> list[str]:
    errors: list[str] = []
    changed_paths = collect_git_changed_paths()
    cr_paths = sorted(CHANGE_ROOT.glob("CR-*.md")) if CHANGE_ROOT.is_dir() else []

    for rel_path, abs_path in REVISION_RECORD_TARGETS.items():
        if not abs_path.is_file():
            continue

        changed_now = rel_path in changed_paths
        changed_by_cr = any(cr_marks_document_changed(cr_path, rel_path) for cr_path in cr_paths)
        if not changed_now and not changed_by_cr:
            continue

        content = abs_path.read_text(encoding="utf-8")
        if not has_revision_record(content):
            errors.append(f"{rel_path} changed under CR flow but is missing required '## 修订记录'")

    return errors


def collect_errors() -> list[str]:
    errors: list[str] = []
    platform_contracts = load_platform_contracts(errors)
    if platform_contracts:
        errors.extend(collect_codex_dry_run_errors(platform_contracts))
    errors.extend(collect_installer_component_errors())
    errors.extend(collect_cr004_protocol_errors())
    errors.extend(collect_guardrail_command_scope_errors())
    errors.extend(collect_agent_dispatch_evidence_errors())
    errors.extend(collect_agent_display_profile_errors())
    errors.extend(collect_revision_record_errors())

    for child in sorted(path for path in DELIVERY_ROOT.iterdir() if path.is_dir()):
        if child.name not in ALLOWED_DELIVERY_DIRS:
            errors.append(f"delivery top-level directory not allowed: {child.relative_to(ROOT)}")

    for path in ROOT.rglob("__pycache__"):
        if is_under_excluded_cache_dir(path):
            continue
        if path.is_dir():
            errors.append(f"python cache directory must not exist: {path.relative_to(ROOT)}")
    for path in ROOT.rglob("*.pyc"):
        if is_under_excluded_cache_dir(path):
            continue
        if path.is_file():
            errors.append(f"python bytecode file must not exist: {path.relative_to(ROOT)}")

    delivery_scripts = DELIVERY_ROOT / "scripts"
    for path in sorted(delivery_scripts.glob("*")):
        if path.is_file() and path.name not in ALLOWED_DELIVERY_SCRIPT_FILES:
            errors.append(f"delivery/scripts only allows install entrypoints: {path.relative_to(ROOT)}")

    for path in DELIVERY_ROOT.rglob("*"):
        if not path.is_dir():
            continue
        rel = path.relative_to(DELIVERY_ROOT)
        if path.name == "templates" and (len(rel.parts) != 3 or rel.parts[0] != "skills"):
            errors.append(f"templates directory must live under delivery/skills/<skill>/templates: {path.relative_to(ROOT)}")
        if path.name == "scripts" and rel.parts[:1] != ("scripts",):
            if len(rel.parts) != 3 or rel.parts[0] != "skills":
                errors.append(f"scripts directory must live under delivery/skills/<skill>/scripts or delivery/scripts: {path.relative_to(ROOT)}")

    skills_root = DELIVERY_ROOT / "skills"
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        content = skill_file.read_text(encoding="utf-8")
        fields = parse_frontmatter(content)
        if fields.get("status") != "active":
            continue

        for match in DELIVERY_SCRIPT_REF_RE.finditer(content):
            if match.group("name") not in ALLOWED_DELIVERY_SCRIPT_FILES:
                errors.append(
                    f"active skill must not reference non-installer delivery/scripts assets: {skill_file.relative_to(ROOT)} -> {match.group('name')}"
                )
        if "delivery/review-templates" in content:
            errors.append(f"active skill must not reference shared review template directories: {skill_file.relative_to(ROOT)}")
        if re.search(r"\bpython\s+scripts/", content):
            errors.append(f"active skill must not use cwd-dependent 'python scripts/...' entrypoints: {skill_file.relative_to(ROOT)}")

        for match in SKILL_ROOT_ASSET_REF_RE.finditer(content):
            rel_path = Path(match.group("kind")) / match.group("path")
            if not (skill_dir / rel_path).exists():
                errors.append(f"active skill references missing asset: {skill_file.relative_to(ROOT)} -> {rel_path.as_posix()}")

        for match in TEMPLATE_REF_RE.finditer(content):
            rel_path = Path("templates") / match.group("path")
            if not (skill_dir / rel_path).exists():
                errors.append(f"active skill references missing asset: {skill_file.relative_to(ROOT)} -> {rel_path.as_posix()}")

    gitignore = ROOT / ".gitignore"
    if gitignore.is_file():
        text = gitignore.read_text(encoding="utf-8")
        for required in ("__pycache__/", "*.pyc"):
            if required not in text:
                errors.append(f".gitignore missing python cache rule: {required}")

    return errors


def main() -> int:
    errors = collect_errors()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
