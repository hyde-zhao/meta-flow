#!/usr/bin/env python3
"""
Meta Flow installer.

Installs workflow assets from the canonical delivery directories:
  - agents/
  - skills/
  - rules/

Supports two run modes:
  1. From project root (delivery/ is a subdirectory):
       uv run --python 3.11 python delivery/scripts/install.py claude
  2. From delivery/ as root (delivery pushed as standalone repo):
       python scripts/install.py claude

Examples:
  uv run --python 3.11 python delivery/scripts/install.py claude
  uv run --python 3.11 python delivery/scripts/install.py codex --scope user
  meta-flow install codex --scope user --component rules
  meta-flow upgrade codex --scope user --component rules
  meta-flow uninstall codex --scope user
  meta-flow reinstall codex --scope user --component rules
  uv run --python 3.11 python delivery/scripts/install.py codex --project-dir D:\\work\\demo
  uv run --python 3.11 python delivery/scripts/install.py claude --dry-run
  uv run --python 3.11 python delivery/scripts/install.py uninstall codex --scope user
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
from importlib import metadata
from pathlib import Path

VALID_PLATFORMS = ("claude", "codex", "openclaw", "qoder")
PLATFORM_ALIASES = {"claude-code": "claude", "qoder-cli": "qoder", "qodercli": "qoder"}
VALID_SCOPES = ("project", "user")
VALID_CONTENTS = ("all", "agents", "skills", "rules")
VALID_COMPONENTS = ("rules", "agent", "full")
KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
BUILT_IN_CODEX_AGENTS = {"default", "worker", "explorer"}
LEGACY_ORCHESTRATOR_AGENT_NAMES = frozenset({"meta-po", "host-orchestrator"})
MANAGED_VERSION = "1.0.0"
PLATFORM_CONTRACTS_PATH = Path("doc") / "PLATFORM-CONTRACTS.yaml"
MANAGED_MARKDOWN_TOKEN = "<!-- myflow-managed:"
MANAGED_TOML_TOKEN = "# myflow-managed:"
MANAGED_BLOCK_BEGIN = "<!-- myflow:managed:begin"
MANAGED_BLOCK_END = "<!-- myflow:managed:end -->"
CANONICAL_AGENT_FRONTMATTER_FIELDS = frozenset({"name", "description", "model", "model_reasoning_effort", "tools"})
CODEX_REQUIRED_AGENT_FIELDS = ("name", "description", "developer_instructions")
CODEX_REASONING_EFFORT_VALUES = frozenset({"minimal", "low", "medium", "high", "xhigh"})
CODEX_OPTIONAL_AGENT_FIELDS = frozenset(
    {
        "nickname_candidates",
        "model",
        "model_reasoning_effort",
        "sandbox_mode",
        "mcp_servers",
        "skills",
    }
)
CODEX_ALLOWED_AGENT_FIELDS = frozenset(CODEX_REQUIRED_AGENT_FIELDS) | CODEX_OPTIONAL_AGENT_FIELDS
CODEX_NICKNAME_RE = re.compile(r"^[A-Za-z0-9 _-]+$")
CLAUDE_AGENT_COLORS = frozenset({"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"})
QODER_EFFORT_VALUES = frozenset({"low", "medium", "high", "xhigh", "max"})
EFFORT_TO_QODER_MAP: dict[str, str] = {"minimal": "low", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh"}
AGENT_DISPLAY_PROFILES: dict[str, dict[str, object]] = {
    "meta-pm": {"codex_nicknames": ["pm-wu", "pm-zheng", "pm-wang", "pm-feng", "pm-chen"], "claude_color": "orange"},
    "meta-se": {"codex_nicknames": ["se-chu", "se-wei", "se-jiang", "se-shen", "se-han"], "claude_color": "yellow"},
    "meta-se-critical": {"codex_nicknames": ["se-critical-chu", "se-critical-wei", "se-critical-jiang"]},
    "meta-dev": {
        "codex_nicknames": [
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
        "claude_color": "green",
    },
    "meta-dev-debugger": {"codex_nicknames": ["debug-yang", "debug-zhu", "debug-qin", "debug-you", "debug-xu"]},
    "meta-qa": {
        "codex_nicknames": [
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
        "claude_color": "cyan",
    },
    "meta-qa-critical": {"codex_nicknames": ["qa-critical-he", "qa-critical-lv", "qa-critical-shi"]},
    "meta-doc": {"codex_nicknames": ["doc-cao", "doc-yan", "doc-hua", "doc-jin", "doc-wei"], "claude_color": "purple"},
}

# canonical Agent Markdown 同时供 Claude Code 与 Qoder 使用；OpenAI 模型只在 Codex 渲染时覆盖。
CODEX_AGENT_MODELS: dict[str, str] = {
    "meta-pm": "gpt-5.6-terra",
    "meta-se": "gpt-5.6-terra",
    "meta-dev": "gpt-5.6-terra",
    "meta-qa": "gpt-5.6-terra",
    "meta-doc": "gpt-5.6-luna",
}
CODEX_AGENT_REASONING_PROFILES: dict[str, tuple[dict[str, str], ...]] = {
    "meta-dev": (
        {
            "name": "meta-dev-debugger",
            "description": "Meta Flow 元工作流的开发故障追因专家。用于重复失败、跨模块 bug、状态机异常和数据一致性问题。",
            "model": "gpt-5.6-sol",
            "model_reasoning_effort": "high",
            "instructions": """
## Codex reasoning profile: meta-dev-debugger

你是 `meta-dev` 的高推理故障追因 profile，canonical role 仍为 `meta-dev`。
仅在实现失败超过阈值、CP7 回修反复、跨模块契约冲突、状态机异常、PIT / 数据泄漏 / 数据一致性风险或复杂 flaky test 时使用。

执行要求：
1. 先找根因，再提出或执行最小修复；不得扩大 Story / LLD 范围。
2. 明确列出证据路径、触发条件、影响文件、最小修复计划和必须回归的测试。
3. 如果修复需要改变架构、公共契约、文件 ownership 或用户授权，停止并交回 host-orchestrator 发起设计澄清或 CR。
4. 输出和状态回写仍按 `meta-dev` 的 CP6 / implementation-execution 合约执行。
""",
        },
    ),
    "meta-se": (
        {
            "name": "meta-se-critical",
            "description": "Meta Flow 元工作流的关键架构审查 profile。用于架构冻结、公共契约、跨模块边界和长期风险决策。",
            "model": "gpt-5.6-sol",
            "model_reasoning_effort": "xhigh",
            "instructions": """
## Codex reasoning profile: meta-se-critical

你是 `meta-se` 的关键架构审查 profile，canonical role 仍为 `meta-se`。
仅在架构冻结、公共 contract、跨模块边界、安全权限、外部接口、长期维护成本或重大 ADR 决策前使用。

执行要求：
1. 优先审查内部一致性、边界条件、回退策略、NFR、风险接受和 Use Case 到架构的可追溯性。
2. 必须给出推荐方案、至少一个可执行备选方案、when-to-switch 条件和影响面。
3. 发现阻断项时停止推进 Story 拆解，并交回 host-orchestrator 汇总为 CP3 / CP5 决策项。
4. 输出和状态回写仍按 `meta-se` 的 HLD / story-planning 合约执行。
""",
        },
    ),
    "meta-qa": (
        {
            "name": "meta-qa-critical",
            "description": "Meta Flow 元工作流的关键质量门 profile。用于 CP5/CP7/CP8、发布前和高风险验证裁决。",
            "model": "gpt-5.6-sol",
            "model_reasoning_effort": "xhigh",
            "instructions": """
## Codex reasoning profile: meta-qa-critical

你是 `meta-qa` 的关键质量门 profile，canonical role 仍为 `meta-qa`。
仅在 CP5 全量设计证据确认、CP7 最终验证、CP8 交付就绪、发布前、安全 / 安装 / 平台路径 / workflow harness 高风险验证时使用。

执行要求：
1. 专门寻找隐藏假设、误导性 PASS、缺失负向测试、证据断链、契约违背和 workflow 风险。
2. 必须区分 BLOCKING、REQUIRED、OPTIONAL 和风险接受项，并给出 PASS / PASS_WITH_RISK / FAIL / BLOCKED 建议。
3. 只有 handoff 而没有 `spawn_agent` / `resume_agent` / `send_input` / platform-task 证据时，必须判定调度证据不足。
4. 输出和状态回写仍按 `meta-qa` 的 verification-execution / quality-review / CP7 / CP8 合约执行。
""",
        },
    ),
}


@dataclass(frozen=True)
class SourceLayout:
    root: Path
    canonical_agents_dir: Path
    canonical_skills_dir: Path
    platform_contracts: Path
    agents_rule: Path | None


@dataclass(frozen=True)
class AgentDefinition:
    source: Path
    name: str
    description: str
    instructions: str
    model: str | None
    model_reasoning_effort: str | None
    tools: str | None
    extra_fields: tuple[str, ...]


@dataclass
class Transaction:
    original_text: dict[Path, str | None] = field(default_factory=dict)
    removed_dirs: dict[Path, list[tuple[Path, bytes]]] = field(default_factory=dict)


def fail(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    raise SystemExit(1)


def normalize_platform(platform: str) -> str:
    normalized = PLATFORM_ALIASES.get(platform, platform)
    if normalized not in VALID_PLATFORMS:
        fail(f"未知平台: {platform}。支持的平台: {', '.join(VALID_PLATFORMS)}")
    return normalized


def platform_manifest_names(platform: str) -> set[str]:
    names = {platform}
    names.update(alias for alias, canonical in PLATFORM_ALIASES.items() if canonical == platform)
    return names


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    items = [item.strip() for item in value.split(",") if item.strip()]
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def ensure_kebab_case(items: list[str], kind: str) -> None:
    invalid = [item for item in items if not KEBAB_CASE_RE.fullmatch(item)]
    if invalid:
        fail(f"{kind} 名称必须为 kebab-case 且长度为 3-40: {', '.join(invalid)}")


def reject_legacy_orchestrator_agents(requested_agents: list[str]) -> None:
    legacy_requested = sorted(set(requested_agents) & LEGACY_ORCHESTRATOR_AGENT_NAMES)
    if legacy_requested:
        fail(
            "主编排器现在由当前会话 Host Orchestrator 主进程承担，不再作为平台 agent 安装；"
            f"请不要使用 --agent {', '.join(legacy_requested)}。可安装的对象仅为功能子 agent。"
        )


def script_repo_root(script_path: Path) -> Path:
    return script_path.resolve().parent.parent


def find_git_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        git_dir = candidate / ".git"
        if git_dir.is_dir() or git_dir.is_file():
            return candidate
    return None


def find_provider_checkout_root(delivery_root: Path, script_path: Path) -> Path | None:
    """仅当安装器脚本本身属于 provider checkout 时返回 Git root。

    安装在 consumer 仓库 ``.venv`` 中的 wheel 不能因为祖先存在 ``.git``
    就被误判为 editable provider。
    """

    candidate = find_git_repo_root(delivery_root)
    if candidate is None:
        return None
    actual = script_path.resolve()
    expected = {
        (candidate / "delivery" / "scripts" / "install.py").resolve(),
        (candidate / "scripts" / "install.py").resolve(),
    }
    return candidate if actual in expected else None


def choose_existing(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def detect_source_layout(root: Path) -> SourceLayout:
    canonical_agents = root / "agents"
    canonical_skills = root / "skills"
    if not canonical_agents.is_dir() or not canonical_skills.is_dir():
        fail("需要存在 canonical 源目录 agents/ 和 skills/。")

    rules_dir = root / "rules"
    return SourceLayout(
        root=root,
        canonical_agents_dir=canonical_agents,
        canonical_skills_dir=canonical_skills,
        platform_contracts=root / PLATFORM_CONTRACTS_PATH,
        agents_rule=choose_existing(rules_dir / "AGENTS.md", root / "AGENTS.md"),
    )


def load_platform_contracts(path: Path) -> dict[str, object]:
    if not path.is_file():
        fail(f"缺少平台契约文件: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"无法解析平台契约文件（需为 JSON-compatible YAML）: {path} -> {exc}")

    contracts = payload.get("contracts")
    if not isinstance(contracts, dict):
        fail(f"平台契约文件缺少 contracts 对象: {path}")

    missing_platforms = sorted(set(VALID_PLATFORMS) - set(contracts))
    if missing_platforms:
        fail(f"平台契约缺少平台: {', '.join(missing_platforms)}")

    for platform in VALID_PLATFORMS:
        platform_contract = contracts.get(platform)
        if not isinstance(platform_contract, dict):
            fail(f"平台契约不是对象: {platform}")
        scopes = platform_contract.get("scopes")
        if not isinstance(scopes, dict):
            fail(f"平台契约缺少 scopes: {platform}")
        for scope in VALID_SCOPES:
            scope_contract = scopes.get(scope)
            if not isinstance(scope_contract, dict):
                fail(f"平台契约缺少 scope: {platform}/{scope}")
            missing_kinds = sorted({"rules", "agents", "skills"} - set(scope_contract))
            if missing_kinds:
                fail(f"平台契约缺少路径类型: {platform}/{scope} -> {', '.join(missing_kinds)}")
    return payload


def platform_scope_contract(contracts: dict[str, object], platform: str, scope: str) -> dict[str, str]:
    platform_contract = contracts["contracts"][platform]  # type: ignore[index]
    scope_contract = platform_contract["scopes"][scope]  # type: ignore[index]
    return scope_contract  # type: ignore[return-value]


def resolve_contract_path(path_value: str, workspace_root: Path) -> Path:
    if path_value.startswith("~/"):
        return Path(path_value).expanduser()
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate
    return workspace_root / candidate


def target_path(contracts: dict[str, object], platform: str, scope: str, kind: str, workspace_root: Path) -> Path:
    scope_contract = platform_scope_contract(contracts, platform, scope)
    return resolve_contract_path(scope_contract[kind], workspace_root)


def parse_frontmatter(content: str) -> tuple[dict[str, object], str]:
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    fields = parse_yaml_like(match.group(1))
    body = content[match.end() :].lstrip()
    return fields, body


def parse_yaml_like(block: str) -> dict[str, object]:
    fields: dict[str, object] = {}
    lines = block.splitlines()
    index = 0

    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if ":" not in raw_line:
            fail(f"无法解析 frontmatter 行: {raw_line}")

        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()

        if value in {"|", "|-", ">", ">-"}:
            block_lines: list[str] = []
            index += 1
            while index < len(lines):
                nested_line = lines[index]
                if nested_line.startswith("  "):
                    block_lines.append(nested_line[2:])
                    index += 1
                    continue
                if not nested_line.strip():
                    block_lines.append("")
                    index += 1
                    continue
                break

            text = "\n".join(block_lines).rstrip()
            if value.startswith(">"):
                fields[key] = " ".join(part.strip() for part in text.splitlines() if part.strip()).strip()
            else:
                fields[key] = text
            continue

        if value.startswith("[") or value.startswith("{"):
            fields[key] = ast.literal_eval(value)
        else:
            fields[key] = value.strip('"').strip("'")
        index += 1

    return fields


def load_canonical_agent(path: Path, permissive: bool) -> AgentDefinition | None:
    content = path.read_text(encoding="utf-8")
    fields, body = parse_frontmatter(content)
    if not fields:
        return None

    name = str(fields.get("name", "")).strip()
    description = str(fields.get("description", "")).strip()
    instructions = body.rstrip()
    if not name or not description or not instructions:
        fail(f"canonical agent 缺少必填字段或正文为空: {path}")
    if path.stem != name:
        fail(f"agent 文件名必须与 name 一致: {path.name} != {name}")
    if not KEBAB_CASE_RE.fullmatch(name):
        fail(f"agent name 必须为 kebab-case: {path}")

    unsupported = sorted(key for key in fields if key not in CANONICAL_AGENT_FRONTMATTER_FIELDS)
    if unsupported and not permissive:
        fail(
            "canonical agent frontmatter 仅支持 name/description/model/model_reasoning_effort/tools；"
            "Codex 的 developer_instructions 由 Markdown 正文渲染，禁止写 version、instructions 等其它顶层字段: "
            f"{path} -> {', '.join(unsupported)}"
        )

    model = str(fields["model"]).strip() if "model" in fields and str(fields["model"]).strip() else None
    model_reasoning_effort = (
        str(fields["model_reasoning_effort"]).strip()
        if "model_reasoning_effort" in fields and str(fields["model_reasoning_effort"]).strip()
        else None
    )
    if model_reasoning_effort and model_reasoning_effort not in CODEX_REASONING_EFFORT_VALUES:
        fail(
            "model_reasoning_effort 必须为 minimal/low/medium/high/xhigh: "
            f"{path} -> {model_reasoning_effort}"
        )
    tools = str(fields["tools"]).strip() if "tools" in fields and str(fields["tools"]).strip() else None
    return AgentDefinition(
        source=path,
        name=name,
        description=description,
        instructions=instructions,
        model=model,
        model_reasoning_effort=model_reasoning_effort,
        tools=tools,
        extra_fields=tuple(unsupported),
    )


def list_canonical_agents(layout: SourceLayout, permissive: bool) -> list[AgentDefinition]:
    agents: list[AgentDefinition] = []
    for path in sorted(layout.canonical_agents_dir.glob("*.md")):
        definition = load_canonical_agent(path, permissive)
        if definition is not None:
            agents.append(definition)
    return agents


def list_skill_dirs(layout: SourceLayout) -> list[Path]:
    return sorted(path for path in layout.canonical_skills_dir.iterdir() if path.is_dir() and (path / "SKILL.md").is_file())


def select_agent_definitions(definitions: list[AgentDefinition], requested: list[str]) -> list[AgentDefinition]:
    if not requested:
        return definitions

    requested_set = set(requested)
    selected = [definition for definition in definitions if definition.name in requested_set]
    missing = requested_set - {definition.name for definition in selected}
    if missing:
        fail(f"未找到这些 canonical agent: {', '.join(sorted(missing))}")
    return selected


def codex_agent_definition(agent: AgentDefinition) -> AgentDefinition:
    """返回仅用于 Codex 渲染的 Agent 定义，避免污染其他平台的模型字段。"""
    return replace(agent, model=CODEX_AGENT_MODELS.get(agent.name, agent.model))


def codex_profile_agent_definitions(agent: AgentDefinition) -> list[AgentDefinition]:
    profiles: list[AgentDefinition] = []
    for profile in CODEX_AGENT_REASONING_PROFILES.get(agent.name, ()):
        profile_name = profile["name"]
        profile_effort = profile["model_reasoning_effort"]
        if not KEBAB_CASE_RE.fullmatch(profile_name):
            fail(f"Codex reasoning profile name 必须为 kebab-case: {agent.name} -> {profile_name}")
        if profile_effort not in CODEX_REASONING_EFFORT_VALUES:
            fail(f"Codex reasoning profile effort 非法: {profile_name} -> {profile_effort}")
        profiles.append(
            AgentDefinition(
                source=agent.source,
                name=profile_name,
                description=profile["description"],
                instructions=f"{agent.instructions.rstrip()}\n\n{profile['instructions'].strip()}\n",
                model=profile.get("model", agent.model),
                model_reasoning_effort=profile_effort,
                tools=agent.tools,
                extra_fields=agent.extra_fields,
            )
        )
    return profiles


def codex_install_agent_definitions(selected_agents: list[AgentDefinition]) -> list[AgentDefinition]:
    install_agents: list[AgentDefinition] = []
    for agent in selected_agents:
        codex_agent = codex_agent_definition(agent)
        install_agents.append(codex_agent)
        install_agents.extend(codex_profile_agent_definitions(codex_agent))
    return install_agents


def select_skill_dirs(skill_dirs: list[Path], requested: list[str]) -> list[Path]:
    if not requested:
        return skill_dirs

    requested_set = set(requested)
    selected = [path for path in skill_dirs if path.name in requested_set]
    missing = requested_set - {path.name for path in selected}
    if missing:
        fail(f"未找到这些 skill: {', '.join(sorted(missing))}")
    return selected


def prompt_project_workspace_root(default_dir: Path) -> Path:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        fail("项目级安装未指定 --project-dir，且当前不是交互式终端。请显式传入 --project-dir。")

    print("未指定 --project-dir。")
    print(f"项目级安装会写入当前目录: {default_dir}")
    print("直接回车使用当前目录；输入其他目录可改用该目录；输入 q 取消。")

    while True:
        answer = input("安装目录 [当前目录]: ").strip()
        if not answer:
            return default_dir.resolve()
        if answer.lower() in {"q", "quit", "cancel", "取消"}:
            fail("已取消项目级安装。")

        selected = Path(answer).expanduser().resolve()
        print(f"将安装到: {selected}")
        confirm = input("确认使用该目录？[Y/n]: ").strip().lower()
        if confirm in {"", "y", "yes", "是"}:
            return selected
        if confirm in {"n", "no", "否"}:
            continue
        print("请输入 Y 或 n。")


def resolve_workspace_root(project_dir: str | None, scope: str) -> Path:
    if project_dir:
        return Path(project_dir).expanduser().resolve()

    if scope == "project":
        return prompt_project_workspace_root(Path.cwd())

    detected = find_git_repo_root(Path.cwd())
    if detected is None:
        return Path.cwd().resolve()
    return detected


def resolve_user_home_root(platform: str) -> Path:
    home = Path.home()
    roots = {
        "claude": home / ".claude",
        "codex": home / ".codex",
        "openclaw": home / ".openclaw",
    }
    return roots[platform]


def meta_flow_root(workspace_root: Path) -> Path:
    return Path.home() / ".meta-flow"


def install_state_root(workspace_root: Path, scope: str) -> Path:
    if scope == "project":
        return workspace_root / ".meta-flow"
    return meta_flow_root(workspace_root)


def manifest_path(workspace_root: Path, scope: str) -> Path:
    if scope == "project":
        return install_state_root(workspace_root, scope) / "INSTALL-MANIFEST.yaml"
    return install_state_root(workspace_root, scope) / "delivery" / "doc" / "INSTALL-MANIFEST.yaml"


def canonical_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def source_worktree_clean(root: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return not result.stdout.strip()


def source_delivery_tree_digest(root: Path) -> str:
    delivery = root / "delivery" if (root / "delivery").is_dir() else root
    records = {
        (Path("delivery") / path.relative_to(delivery)).as_posix(): sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(delivery.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
    rendered = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(rendered).hexdigest()


def capability_profile_digest(root: Path) -> str:
    delivery = root / "delivery" if (root / "delivery").is_dir() else root
    contract = delivery / "doc" / "PUBLIC-OPERATION-CONTRACTS.yaml"
    if not contract.is_file() or contract.is_symlink():
        return ""
    return sha256(contract.read_bytes()).hexdigest()


def _is_generated_distribution_file(relative: Path) -> bool:
    rendered = relative.as_posix()
    if "__pycache__" in relative.parts or relative.suffix == ".pyc":
        return True
    if ".dist-info/" not in rendered:
        return False
    return relative.name in {"INSTALLER", "RECORD", "REQUESTED", "direct_url.json"}


def installed_distribution_payload_digest(distribution_name: str = "meta-flow") -> str:
    """重算实际安装 distribution payload，不信任 receipt 自报值。"""

    try:
        distribution = metadata.distribution(distribution_name)
    except metadata.PackageNotFoundError:
        return ""
    root = Path(distribution.locate_file(".")).resolve()
    records: dict[str, str] = {}
    for item in distribution.files or ():
        relative = Path(str(item))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or _is_generated_distribution_file(relative)
        ):
            continue
        candidate = Path(distribution.locate_file(item)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if not candidate.is_file() or candidate.is_symlink():
            continue
        records[relative.as_posix()] = sha256(candidate.read_bytes()).hexdigest()
    if not records:
        return ""
    rendered = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(rendered).hexdigest()


def distribution_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file() and (root.parent / "pyproject.toml").is_file():
        pyproject = root.parent / "pyproject.toml"
    if not pyproject.is_file():
        return "unknown"
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = payload.get("project")
    if not isinstance(project, dict):
        return "unknown"
    value = project.get("version")
    return str(value) if isinstance(value, str) and value else "unknown"


def load_provider_receipt_facts(path_value: str) -> dict[str, object]:
    if not path_value:
        return {}
    path = Path(path_value).expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        fail("META_FLOW_PROVIDER_RECEIPT 必须指向普通文件。")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"无法解析 META_FLOW_PROVIDER_RECEIPT: {exc}")
    required = {
        "schema_version",
        "kind",
        "distribution_name",
        "distribution_version",
        "source_commit",
        "source_dirty",
        "source_tree_digest",
        "artifact_filename",
        "artifact_sha256",
        "capability_profile_digest",
        "installed_payload_digest",
        "release_qualifying",
        "receipt_digest",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        fail("META_FLOW_PROVIDER_RECEIPT 字段不完整。")
    if payload.get("kind") != "ProviderArtifactReceiptV1" or payload.get("schema_version") != 1:
        fail("META_FLOW_PROVIDER_RECEIPT identity 非法。")
    for key in ("distribution_name", "distribution_version", "artifact_filename"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            fail(f"META_FLOW_PROVIDER_RECEIPT {key} 非法。")
    if not isinstance(payload.get("source_commit"), str) or not re.fullmatch(
        r"[0-9a-f]{40}", payload["source_commit"]
    ):
        fail("META_FLOW_PROVIDER_RECEIPT source_commit 非法。")
    for key in (
        "source_tree_digest",
        "artifact_sha256",
        "capability_profile_digest",
        "installed_payload_digest",
        "receipt_digest",
    ):
        if not isinstance(payload.get(key), str) or not re.fullmatch(
            r"[0-9a-f]{64}", payload[key]
        ):
            fail(f"META_FLOW_PROVIDER_RECEIPT {key} 非法。")
    if not isinstance(payload.get("source_dirty"), bool) or not isinstance(
        payload.get("release_qualifying"), bool
    ):
        fail("META_FLOW_PROVIDER_RECEIPT boolean 字段非法。")
    unsigned = {key: value for key, value in payload.items() if key != "receipt_digest"}
    rendered = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if payload["receipt_digest"] != sha256(rendered).hexdigest():
        fail("META_FLOW_PROVIDER_RECEIPT digest 不匹配。")
    if payload["release_qualifying"] == payload["source_dirty"]:
        fail("META_FLOW_PROVIDER_RECEIPT release qualification 不一致。")
    return payload


def iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def toml_multiline(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"""', '\\"""')


def toml_array(values: list[str]) -> str:
    return "[" + ", ".join(toml_string(value) for value in values) + "]"


def markdown_audit(commit: str, generated: str) -> str:
    return f"<!-- myflow-managed: version={MANAGED_VERSION} canonical-commit={commit} generated={generated} -->"


def toml_audit(commit: str, generated: str) -> str:
    return f"# myflow-managed: version={MANAGED_VERSION} canonical-commit={commit} generated={generated}"


def inject_markdown_audit(content: str, commit: str, generated: str) -> str:
    audit = markdown_audit(commit, generated)
    match = FRONTMATTER_RE.match(content)
    if not match:
        return f"{audit}\n\n{content.lstrip()}"

    prefix = content[: match.end()].rstrip()
    body = content[match.end() :].lstrip()
    return f"{prefix}\n{audit}\n\n{body}"


def render_claude_agent(agent: AgentDefinition, commit: str, generated: str) -> str:
    display_profile = AGENT_DISPLAY_PROFILES.get(agent.name, {})
    color = str(display_profile.get("claude_color", "")).strip()
    if color and color not in CLAUDE_AGENT_COLORS:
        fail(f"Claude Code agent color 非法: {agent.name} -> {color}")

    frontmatter = [
        "---",
        f"name: {yaml_scalar(agent.name)}",
        f"description: {yaml_scalar(agent.description)}",
    ]
    if agent.model:
        frontmatter.append(f"model: {yaml_scalar(agent.model)}")
    if agent.tools:
        frontmatter.append(f"tools: {yaml_scalar(agent.tools)}")
    if color:
        frontmatter.append(f"color: {yaml_scalar(color)}")
    frontmatter.append("---")
    return "\n".join(frontmatter) + f"\n{markdown_audit(commit, generated)}\n\n{agent.instructions.rstrip()}\n"


def render_codex_agent(agent: AgentDefinition, commit: str, generated: str) -> str:
    display_profile = AGENT_DISPLAY_PROFILES.get(agent.name, {})
    nicknames = [str(item).strip() for item in display_profile.get("codex_nicknames", []) if str(item).strip()]
    invalid_nicknames = [nickname for nickname in nicknames if not CODEX_NICKNAME_RE.fullmatch(nickname)]
    if invalid_nicknames:
        fail(
            "Codex nickname_candidates 只能包含 ASCII 字母、数字、空格、连字符和下划线: "
            f"{agent.name} -> {', '.join(invalid_nicknames)}"
        )

    lines = [
        toml_audit(commit, generated),
        f"name = {toml_string(agent.name)}",
    ]
    if nicknames:
        lines.append(f"nickname_candidates = {toml_array(nicknames)}")
    lines.extend(
        [
            "description = \"\"\"",
            toml_multiline(agent.description),
            "\"\"\"",
        ]
    )
    if agent.model:
        lines.append(f"model = {toml_string(agent.model)}")
    if agent.model_reasoning_effort:
        lines.append(f"model_reasoning_effort = {toml_string(agent.model_reasoning_effort)}")
    lines.extend(
        [
            "developer_instructions = \"\"\"",
            toml_multiline(agent.instructions.rstrip()),
            "\"\"\"",
            "",
        ]
    )
    return "\n".join(lines)


def has_managed_file_audit(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    return MANAGED_MARKDOWN_TOKEN in text or MANAGED_TOML_TOKEN in text


def validate_codex_agent_render(content: str, agent: AgentDefinition) -> None:
    try:
        payload = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        fail(f"Codex agent 渲染结果不是合法 TOML: {agent.source} -> {exc}")

    missing = [field for field in CODEX_REQUIRED_AGENT_FIELDS if not str(payload.get(field, "")).strip()]
    if missing:
        fail(f"Codex agent 渲染结果缺少必填字段: {agent.source} -> {', '.join(missing)}")

    unsupported = sorted(key for key in payload if key not in CODEX_ALLOWED_AGENT_FIELDS)
    if unsupported:
        fail(f"Codex agent 渲染结果包含非官方 schema 字段: {agent.source} -> {', '.join(unsupported)}")


def render_qoder_agent(agent: AgentDefinition, commit: str, generated: str) -> str:
    display_profile = AGENT_DISPLAY_PROFILES.get(agent.name, {})
    color = str(display_profile.get("claude_color", "")).strip()
    if color and color not in CLAUDE_AGENT_COLORS:
        fail(f"Qoder agent color 非法: {agent.name} -> {color}")
    effort = EFFORT_TO_QODER_MAP.get(agent.model_reasoning_effort) if agent.model_reasoning_effort else None
    if agent.model_reasoning_effort and not effort:
        fail(f"Qoder agent effort 映射失败: {agent.name} -> {agent.model_reasoning_effort}")

    frontmatter = [
        "---",
        f"name: {yaml_scalar(agent.name)}",
        f"description: {yaml_scalar(agent.description)}",
    ]
    if agent.model:
        frontmatter.append(f"model: {yaml_scalar(agent.model)}")
    if agent.tools:
        frontmatter.append(f"tools: {yaml_scalar(agent.tools)}")
    if effort:
        frontmatter.append(f"effort: {effort}")
    if color:
        frontmatter.append(f"color: {yaml_scalar(color)}")
    frontmatter.append("---")
    return "\n".join(frontmatter) + f"\n{markdown_audit(commit, generated)}\n\n{agent.instructions.rstrip()}\n"


def build_openclaw_manifest(agent_entries: list[dict[str, str]], skill_entries: list[dict[str, str]]) -> str:
    payload = {
        "version": "1.0",
        "agents": agent_entries,
        "skills": skill_entries,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def record_original_text(transaction: Transaction, path: Path) -> None:
    if path not in transaction.original_text:
        transaction.original_text[path] = path.read_text(encoding="utf-8") if path.exists() else None


def path_components(path: Path) -> list[Path]:
    if path.is_absolute():
        current = Path(path.anchor)
        parts = path.parts[1:]
    else:
        current = Path()
        parts = path.parts

    components: list[Path] = []
    for part in parts:
        current = current / part
        components.append(current)
    return components


def path_conflict_message(path: Path) -> str:
    return (
        f"安装路径被非目录占用: {path}\n"
        "请删除、移动或重命名该文件后重试；安装器需要在该位置创建目录。"
    )


def ensure_directory(path: Path, dry_run: bool) -> None:
    for component in path_components(path):
        if component.exists() and not component.is_dir():
            fail(path_conflict_message(component))
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)


def ensure_file_target(path: Path, dry_run: bool) -> None:
    ensure_directory(path.parent, dry_run)
    if path.exists() and path.is_dir():
        fail(
            f"安装目标文件被目录占用: {path}\n"
            "请删除、移动或重命名该目录后重试；安装器需要在该位置写入文件。"
        )


def write_text(path: Path, content: str, transaction: Transaction, dry_run: bool) -> None:
    ensure_file_target(path, dry_run)
    if dry_run:
        print(f"[DryRun] write -> {path}")
        return
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    record_original_text(transaction, path)
    path.write_text(content, encoding="utf-8")


def copy_text_with_audit(src: Path, dest: Path, transaction: Transaction, dry_run: bool, commit: str, generated: str) -> None:
    content = src.read_text(encoding="utf-8")
    write_text(dest, inject_markdown_audit(content, commit, generated), transaction, dry_run)


def remove_path(path: Path, transaction: Transaction, dry_run: bool) -> None:
    if dry_run:
        print(f"[DryRun] remove -> {path}")
        return

    if path.is_dir():
        fail(
            "legacy directory uninstall is disabled: exact_leaf_set ownership "
            "must remove digest-matching leaves individually; recursive delete=0. "
            "请先运行一次新版 install 完成 exact leaf set 迁移，再执行 uninstall。"
        )

    if path.exists():
        record_original_text(transaction, path)
        path.unlink()


def rollback_transaction(transaction: Transaction) -> None:
    for path, files in transaction.removed_dirs.items():
        ensure_directory(path, dry_run=False)
        for relative_path, payload in files:
            restored = path / relative_path
            ensure_file_target(restored, dry_run=False)
            restored.write_bytes(payload)

    for path in sorted(transaction.original_text, reverse=True):
        original = transaction.original_text[path]
        if original is None:
            if path.exists():
                path.unlink()
            continue
        ensure_file_target(path, dry_run=False)
        path.write_text(original, encoding="utf-8")


@contextmanager
def rollback_on_failure(transaction: Transaction, dry_run: bool) -> Iterator[None]:
    """确保所有失败类型在重抛前回滚已记录的安装 mutation。"""

    try:
        yield
    except BaseException:
        if not dry_run:
            rollback_transaction(transaction)
        raise


def managed_block_begin_prefix(platform: str) -> str:
    return f"{MANAGED_BLOCK_BEGIN} platform={platform} "


def managed_block_end_marker(platform: str) -> str:
    return f"<!-- myflow:managed:end platform={platform} -->"


def managed_block_markers(commit: str, generated: str, platform: str) -> tuple[str, str]:
    begin = f"{MANAGED_BLOCK_BEGIN} platform={platform} v=1 commit={commit} generated={generated} -->"
    end = managed_block_end_marker(platform)
    return begin, end


def render_managed_block(content: str, commit: str, generated: str, platform: str) -> str:
    begin, end = managed_block_markers(commit, generated, platform)
    managed_content = inject_markdown_audit(content.rstrip() + "\n", commit, generated).rstrip()
    return f"{begin}\n{managed_content}\n{end}"


def find_managed_block_range(content: str, platform: str) -> tuple[int, int] | None:
    begin_prefix = managed_block_begin_prefix(platform)
    end_marker = managed_block_end_marker(platform)

    begin_index = content.find(begin_prefix)
    end_index = content.find(end_marker)

    if begin_index != -1 and end_index != -1:
        if begin_index > end_index:
            fail(f"managed block 哨兵顺序错误，请先手工修复: platform={platform}")
        return begin_index, end_index + len(end_marker)

    if begin_index != -1 or end_index != -1:
        fail(f"managed block 哨兵损坏，请先手工修复: platform={platform}")

    legacy_begin = content.find(f"{MANAGED_BLOCK_BEGIN} v=")
    legacy_end = content.find(MANAGED_BLOCK_END)

    if legacy_begin != -1 and legacy_end != -1:
        if legacy_begin > legacy_end:
            fail("managed block 哨兵顺序错误，请先手工修复 (legacy)")
        return legacy_begin, legacy_end + len(MANAGED_BLOCK_END)

    if legacy_begin != -1 or legacy_end != -1:
        fail("managed block 哨兵损坏，请先手工修复 (legacy)")

    return None


def upsert_managed_block(path: Path, canonical_content: str, transaction: Transaction, dry_run: bool, commit: str, generated: str, platform: str) -> None:
    block = render_managed_block(canonical_content, commit, generated, platform)

    ensure_file_target(path, dry_run)
    if not path.exists():
        write_text(path, block + "\n", transaction, dry_run)
        return

    existing = path.read_text(encoding="utf-8")
    found = find_managed_block_range(existing, platform)

    if found is None:
        separator = "\n\n" if existing and not existing.endswith("\n\n") else ""
        merged = existing.rstrip() + separator + block + "\n"
        write_text(path, merged if existing.strip() else block + "\n", transaction, dry_run)
        return

    begin_index, end_index = found
    replaced = existing[:begin_index].rstrip()
    suffix = existing[end_index:].lstrip("\r\n")
    parts = [part for part in [replaced, block, suffix.rstrip()] if part]
    write_text(path, "\n\n".join(parts) + "\n", transaction, dry_run)


def clear_managed_block(path: Path, transaction: Transaction, dry_run: bool, platform: str) -> None:
    if not path.exists():
        return
    ensure_file_target(path, dry_run)

    existing = path.read_text(encoding="utf-8")
    found = find_managed_block_range(existing, platform)
    if found is None:
        return

    begin_index, end_index = found
    prefix = existing[:begin_index].rstrip()
    suffix = existing[end_index:].lstrip("\r\n")
    parts = [part for part in [prefix, suffix.rstrip()] if part]
    write_text(path, "\n\n".join(parts) + "\n", transaction, dry_run)


def has_managed_block(path: Path, platform: str | None = None) -> bool:
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    if platform:
        if managed_block_begin_prefix(platform) in text and managed_block_end_marker(platform) in text:
            return True
        return f"{MANAGED_BLOCK_BEGIN} v=" in text and MANAGED_BLOCK_END in text
    return MANAGED_BLOCK_BEGIN in text and "<!-- myflow:managed:end" in text


def copy_skill_tree(
    src_dir: Path,
    dest_dir: Path,
    transaction: Transaction,
    dry_run: bool,
    commit: str,
    generated: str,
) -> list[Path]:
    installed_leaves: list[Path] = []
    for src_path in sorted(src_dir.rglob("*")):
        if src_path.is_dir():
            continue
        relative_path = src_path.relative_to(src_dir)
        dest_path = dest_dir / relative_path
        installed_leaves.append(dest_path)
        if relative_path == Path("SKILL.md"):
            copy_text_with_audit(src_path, dest_path, transaction, dry_run, commit, generated)
            continue
        if dry_run:
            ensure_file_target(dest_path, dry_run=True)
            print(f"[DryRun] {src_path} -> {dest_path}")
            continue
        ensure_file_target(dest_path, dry_run=False)
        if dest_path.is_file() and dest_path.read_bytes() == src_path.read_bytes():
            continue
        record_original_text(transaction, dest_path)
        shutil.copy2(src_path, dest_path)
    return installed_leaves


def counterpart_paths(platform: str, workspace_root: Path, contracts: dict[str, object]) -> dict[str, Path]:
    if platform not in {"codex", "claude", "qoder"}:
        return {}
    return {
        "agent-user": target_path(contracts, platform, "user", "agents", workspace_root),
        "agent-project": target_path(contracts, platform, "project", "agents", workspace_root),
        "skill-user": target_path(contracts, platform, "user", "skills", workspace_root),
        "skill-project": target_path(contracts, platform, "project", "skills", workspace_root),
    }


def scan_name_conflicts(
    platform: str,
    scope: str,
    workspace_root: Path,
    contracts: dict[str, object],
    agent_names: list[str],
    skill_names: list[str],
) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    paths = counterpart_paths(platform, workspace_root, contracts)
    if not paths:
        return conflicts
    current_scope = "user" if scope == "user" else "project"
    other_scope = "project" if current_scope == "user" else "user"

    if platform == "codex":
        for name in agent_names:
            if name in BUILT_IN_CODEX_AGENTS:
                fail(f"Codex subagent 名称禁止与 built-in 重名: {name}")
            other_path = paths[f"agent-{other_scope}"] / f"{name}.toml"
            if other_path.exists():
                conflicts.append({"kind": "agent", "name": name, "scope": other_scope, "path": str(other_path)})
        for name in skill_names:
            other_path = paths[f"skill-{other_scope}"] / name / "SKILL.md"
            if other_path.exists():
                conflicts.append({"kind": "skill", "name": name, "scope": other_scope, "path": str(other_path)})
        return conflicts

    for name in agent_names:
        other_path = paths[f"agent-{other_scope}"] / f"{name}.md"
        if other_path.exists():
            conflicts.append({"kind": "agent", "name": name, "scope": other_scope, "path": str(other_path)})
    for name in skill_names:
        other_path = paths[f"skill-{other_scope}"] / name / "SKILL.md"
        if other_path.exists():
            conflicts.append({"kind": "skill", "name": name, "scope": other_scope, "path": str(other_path)})
    return conflicts


def runtime_override_warnings(platform: str, scope: str, workspace_root: Path, contracts: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    if scope != "user":
        return warnings

    if platform == "codex":
        for candidate in [
            workspace_root / "AGENTS.override.md",
            target_path(contracts, "codex", "project", "rules", workspace_root),
            target_path(contracts, "codex", "project", "agents", workspace_root),
            target_path(contracts, "codex", "project", "skills", workspace_root),
        ]:
            if candidate.exists():
                warnings.append(f"检测到可能覆盖用户级 Codex 安装的项目层对象: {candidate}")
    if platform == "claude":
        for candidate in [
            workspace_root / "CLAUDE.md",
            workspace_root / "CLAUDE.local.md",
            target_path(contracts, "claude", "project", "rules", workspace_root),
            target_path(contracts, "claude", "project", "agents", workspace_root),
            target_path(contracts, "claude", "project", "skills", workspace_root),
        ]:
            if candidate.exists():
                warnings.append(f"检测到可能覆盖用户级 Claude Code 安装的项目层对象: {candidate}")
    if platform == "qoder":
        for candidate in [
            workspace_root / "AGENTS.md",
            workspace_root / "AGENTS.local.md",
            target_path(contracts, "qoder", "project", "rules", workspace_root),
            target_path(contracts, "qoder", "project", "agents", workspace_root),
            target_path(contracts, "qoder", "project", "skills", workspace_root),
        ]:
            if candidate.exists():
                warnings.append(f"检测到可能覆盖用户级 Qoder 安装的项目层对象: {candidate}")
    return warnings


def load_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"manifest_version": 1, "installs": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"无法解析 INSTALL-MANIFEST.yaml（当前实现使用 JSON 兼容 YAML 存储）: {path} -> {exc}")
    return {"manifest_version": 1, "installs": []}


def save_manifest(path: Path, payload: dict[str, object], transaction: Transaction, dry_run: bool) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", transaction, dry_run)


def manifest_entry_matches(existing: object, entry: dict[str, object]) -> bool:
    if not isinstance(existing, dict):
        return False
    return (
        existing.get("platform") in platform_manifest_names(str(entry["platform"]))
        and existing.get("scope") == entry["scope"]
        and existing.get("workspace_root") == entry["workspace_root"]
    )


def find_matching_install(
    payload: dict[str, object],
    platform: str,
    scope: str,
    workspace_root: Path,
) -> dict[str, object] | None:
    workspace_root_text = str(workspace_root)
    for entry in payload.get("installs", []):
        if (
            isinstance(entry, dict)
            and entry.get("platform") in platform_manifest_names(platform)
            and entry.get("scope") == scope
            and entry.get("workspace_root") == workspace_root_text
            and entry.get("status") == "installed"
        ):
            return entry
    return None


def upsert_manifest_entry(payload: dict[str, object], entry: dict[str, object]) -> None:
    installs = list(payload.get("installs", []))
    installs = [existing for existing in installs if not manifest_entry_matches(existing, entry)]
    installs.append(entry)
    payload["installs"] = installs


def component_entry_kinds(component: str) -> set[str]:
    return {
        "rules": {"managed-block"},
        "agent": {"agent", "skill"},
        "full": {"managed-block", "agent", "skill"},
    }[component]


def selected_entry_kinds(component: str, legacy_content: str | None) -> set[str]:
    if legacy_content == "agents":
        return {"agent"}
    if legacy_content == "skills":
        return {"skill"}
    if legacy_content == "rules":
        return {"managed-block"}
    return component_entry_kinds(component)


def install_rules(
    platform: str,
    scope: str,
    workspace_root: Path,
    contracts: dict[str, object],
    layout: SourceLayout,
    transaction: Transaction,
    dry_run: bool,
    commit: str,
    generated: str,
    manifest_entries: list[dict[str, str]],
) -> None:
    if platform == "codex":
        if not layout.agents_rule:
            fail("缺少 Codex rules 源文件：delivery/rules/AGENTS.md。请重新安装或更新 meta-flow 交付包。")
        dest = target_path(contracts, platform, scope, "rules", workspace_root)
        upsert_managed_block(dest, layout.agents_rule.read_text(encoding="utf-8"), transaction, dry_run, commit, generated, platform)
        manifest_entries.append({"kind": "managed-block", "path": str(dest), "remove_path": str(dest)})
        return

    if platform == "qoder":
        if not layout.agents_rule:
            fail("缺少 Qoder rules 源文件：delivery/rules/AGENTS.md。请重新安装或更新 meta-flow 交付包。")
        dest = target_path(contracts, platform, scope, "rules", workspace_root)
        upsert_managed_block(dest, layout.agents_rule.read_text(encoding="utf-8"), transaction, dry_run, commit, generated, platform)
        manifest_entries.append({"kind": "managed-block", "path": str(dest), "remove_path": str(dest)})
        return

    if platform == "claude":
        if not layout.agents_rule:
            fail("缺少 rules 源文件：delivery/rules/AGENTS.md。请重新安装或更新 meta-flow 交付包。")
        dest = target_path(contracts, platform, scope, "rules", workspace_root)
        upsert_managed_block(dest, layout.agents_rule.read_text(encoding="utf-8"), transaction, dry_run, commit, generated, platform)
        manifest_entries.append({"kind": "managed-block", "path": str(dest), "remove_path": str(dest)})


def install_agents(
    platform: str,
    scope: str,
    workspace_root: Path,
    contracts: dict[str, object],
    layout: SourceLayout,
    canonical_agents: list[AgentDefinition],
    requested_agents: list[str],
    transaction: Transaction,
    dry_run: bool,
    commit: str,
    generated: str,
    manifest_entries: list[dict[str, str]],
) -> list[str]:
    installed_names: list[str] = []

    selected_agents = select_agent_definitions(canonical_agents, requested_agents)
    if not selected_agents:
        fail(f"{platform} 平台没有可安装的 canonical agent。")

    if platform == "claude":
        base_dir = target_path(contracts, platform, scope, "agents", workspace_root)
        for agent in selected_agents:
            dest = base_dir / f"{agent.name}.md"
            write_text(dest, render_claude_agent(agent, commit, generated), transaction, dry_run)
            installed_names.append(agent.name)
            manifest_entries.append({"kind": "agent", "name": agent.name, "path": str(dest), "remove_path": str(dest)})
        return installed_names

    if platform == "qoder":
        base_dir = target_path(contracts, platform, scope, "agents", workspace_root)
        for agent in codex_install_agent_definitions(selected_agents):
            dest = base_dir / f"{agent.name}.md"
            content = render_qoder_agent(agent, commit, generated)
            write_text(dest, content, transaction, dry_run)
            installed_names.append(agent.name)
            manifest_entries.append({"kind": "agent", "name": agent.name, "path": str(dest), "remove_path": str(dest)})
        return installed_names

    if platform == "codex":
        base_dir = target_path(contracts, platform, scope, "agents", workspace_root)
        for agent in codex_install_agent_definitions(selected_agents):
            dest = base_dir / f"{agent.name}.toml"
            content = render_codex_agent(agent, commit, generated)
            validate_codex_agent_render(content, agent)
            write_text(dest, content, transaction, dry_run)
            installed_names.append(agent.name)
            manifest_entries.append({"kind": "agent", "name": agent.name, "path": str(dest), "remove_path": str(dest)})
        return installed_names

    base_dir = target_path(contracts, platform, scope, "agents", workspace_root)
    for agent in selected_agents:
        dest = base_dir / f"{agent.name}.md"
        copy_text_with_audit(agent.source, dest, transaction, dry_run, commit, generated)
        installed_names.append(agent.name)
        manifest_entries.append({"kind": "agent", "name": agent.name, "path": str(dest), "remove_path": str(dest)})
    return installed_names


def install_skills(
    platform: str,
    scope: str,
    workspace_root: Path,
    contracts: dict[str, object],
    skill_dirs: list[Path],
    transaction: Transaction,
    dry_run: bool,
    commit: str,
    generated: str,
    manifest_entries: list[dict[str, str]],
) -> list[str]:
    installed_names: list[str] = []
    base_dir = target_path(contracts, platform, scope, "skills", workspace_root)

    for skill_dir in skill_dirs:
        dest_dir = base_dir / skill_dir.name
        installed_leaves = copy_skill_tree(
            skill_dir,
            dest_dir,
            transaction,
            dry_run,
            commit,
            generated,
        )
        installed_names.append(skill_dir.name)
        manifest_entries.extend(
            {
                "kind": "skill",
                "name": skill_dir.name,
                "path": str(dest_path),
                "remove_path": str(dest_path),
            }
            for dest_path in installed_leaves
        )
    return installed_names


def write_openclaw_manifest(
    scope: str,
    workspace_root: Path,
    contracts: dict[str, object],
    manifest_entries: list[dict[str, str]],
    transaction: Transaction,
    dry_run: bool,
) -> None:
    base_dir = target_path(contracts, "openclaw", scope, "rules", workspace_root).parent
    agents: list[dict[str, str]] = []
    skills: list[dict[str, str]] = []
    for entry in manifest_entries:
        remove_path = Path(entry["remove_path"])
        if entry["kind"] == "agent":
            agents.append({"name": entry["name"], "file": remove_path.relative_to(base_dir).as_posix()})
        if entry["kind"] == "skill" and remove_path.name == "SKILL.md":
            skills.append(
                {
                    "name": entry["name"],
                    "file": remove_path.relative_to(base_dir).as_posix(),
                }
            )
    write_text(base_dir / "manifest.yaml", build_openclaw_manifest(agents, skills), transaction, dry_run)


def scan_managed_component_entries(
    platform: str,
    scope: str,
    workspace_root: Path,
    contracts: dict[str, object],
    component: str,
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    kinds = component_entry_kinds(component)

    if "managed-block" in kinds:
        rules_path = target_path(contracts, platform, scope, "rules", workspace_root)
        if has_managed_block(rules_path, platform):
            entries.append({"kind": "managed-block", "path": str(rules_path), "remove_path": str(rules_path)})

    if "agent" in kinds:
        agents_dir = target_path(contracts, platform, scope, "agents", workspace_root)
        if agents_dir.is_dir():
            for agent_path in sorted(path for path in agents_dir.iterdir() if path.is_file()):
                if has_managed_file_audit(agent_path):
                    entries.append(
                        {
                            "kind": "agent",
                            "name": agent_path.stem,
                            "path": str(agent_path),
                            "remove_path": str(agent_path),
                        }
                    )

    if "skill" in kinds:
        skills_dir = target_path(contracts, platform, scope, "skills", workspace_root)
        if skills_dir.is_dir():
            for skill_dir in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
                skill_file = skill_dir / "SKILL.md"
                if has_managed_file_audit(skill_file):
                    entries.append(
                        {
                            "kind": "skill",
                            "name": skill_dir.name,
                            "path": str(skill_file),
                            "remove_path": str(skill_file),
                        }
                    )

    return entries


def remove_manifest_entry(entry: dict[str, object], transaction: Transaction, dry_run: bool, platform: str) -> None:
    remove_target = Path(str(entry["remove_path"]))
    if entry["kind"] == "managed-block":
        clear_managed_block(remove_target, transaction, dry_run, platform)
        return
    remove_path(remove_target, transaction, dry_run)


def prune_stale_manifest_entries(
    platform: str,
    scope: str,
    workspace_root: Path,
    manifest_payload: dict[str, object],
    current_entries: list[dict[str, str]],
    transaction: Transaction,
    dry_run: bool,
    entry_kinds: set[str],
) -> int:
    matching = find_matching_install(manifest_payload, platform, scope, workspace_root)
    if matching is None:
        return 0

    current_remove_paths = {
        str(Path(entry["remove_path"]))
        for entry in current_entries
        if entry.get("kind") in entry_kinds and entry.get("remove_path")
    }
    pruned = 0
    for entry in matching.get("entries", []):
        if not isinstance(entry, dict) or str(entry.get("kind")) not in entry_kinds:
            continue
        remove_path_value = str(entry.get("remove_path", ""))
        if not remove_path_value or str(Path(remove_path_value)) in current_remove_paths:
            continue
        legacy_skill_root = Path(remove_path_value)
        if str(entry.get("kind")) == "skill" and legacy_skill_root.is_dir():
            migrated_leaves = [
                Path(value)
                for value in current_remove_paths
                if Path(value).is_relative_to(legacy_skill_root)
            ]
            if migrated_leaves:
                # 旧 manifest 用目录表示 skill ownership。一次正常 install 会把
                # 它迁移为当前 exact leaf set；迁移过程中不能递归删除该目录。
                continue
        remove_manifest_entry(entry, transaction, dry_run, platform)
        pruned += 1
    return pruned


def prune_legacy_orchestrator_agents(
    platform: str,
    scope: str,
    workspace_root: Path,
    contracts: dict[str, object],
    transaction: Transaction,
    dry_run: bool,
    entry_kinds: set[str],
) -> int:
    if "agent" not in entry_kinds:
        return 0

    agents_dir = target_path(contracts, platform, scope, "agents", workspace_root)
    extension = ".toml" if platform == "codex" else ".md"
    pruned = 0
    for name in sorted(LEGACY_ORCHESTRATOR_AGENT_NAMES):
        candidate = agents_dir / f"{name}{extension}"
        if not has_managed_file_audit(candidate):
            continue
        remove_path(candidate, transaction, dry_run)
        pruned += 1
    return pruned


def uninstall_platform(
    platform: str,
    scope: str,
    workspace_root: Path,
    contracts: dict[str, object],
    manifest_payload: dict[str, object],
    transaction: Transaction,
    dry_run: bool,
    component: str,
) -> dict[str, object]:
    matching = find_matching_install(manifest_payload, platform, scope, workspace_root)

    entry_kinds = component_entry_kinds(component)
    preflight_uninstall_manifest_entries(
        matching,
        entry_kinds=entry_kinds,
        platform=platform,
        scope=scope,
        component=component,
    )
    remaining_entries: list[dict[str, str]] = []
    removed_count = 0
    removed_paths: set[str] = set()

    if matching is not None:
        for entry in matching.get("entries", []):
            if not isinstance(entry, dict) or str(entry.get("kind")) not in entry_kinds:
                remaining_entries.append(entry)
                continue

            remove_manifest_entry(entry, transaction, dry_run, platform)
            removed_paths.add(str(Path(str(entry["remove_path"]))))
            removed_count += 1

    for entry in scan_managed_component_entries(platform, scope, workspace_root, contracts, component):
        remove_path_value = str(Path(entry["remove_path"]))
        if remove_path_value in removed_paths:
            continue
        remove_manifest_entry(entry, transaction, dry_run, platform)
        removed_paths.add(remove_path_value)
        removed_count += 1

    if removed_count == 0:
        fail(
            f"INSTALL-MANIFEST 中未找到 {workspace_root} 的 {platform}/{scope} 已安装记录，"
            "并且目标目录中也没有发现带 myflow-managed 标记的可卸载对象。"
        )

    if matching is None:
        matching = {
            "platform": platform,
            "scope": scope,
            "workspace_root": str(workspace_root),
            "status": "uninstalled",
            "entries": [],
            "cleanup_mode": "managed-scan",
        }
        manifest_payload.setdefault("installs", []).append(matching)
    else:
        matching["entries"] = remaining_entries

    matching.setdefault("uninstall_events", []).append(
        {
            "component": component,
            "uninstalled_at": iso_now(),
            "removed_entries": removed_count,
        }
    )
    if remaining_entries:
        matching["status"] = "installed"
        matching["updated_at"] = iso_now()
    else:
        matching["status"] = "uninstalled"
        matching["uninstalled_at"] = iso_now()
    _prune_empty_removed_parents(
        (Path(path) for path in removed_paths),
        workspace_root=workspace_root,
        dry_run=dry_run,
    )
    return matching


def preflight_uninstall_manifest_entries(
    matching: dict[str, object] | None,
    *,
    entry_kinds: set[str],
    platform: str,
    scope: str,
    component: str,
) -> None:
    """在首次删除前阻断旧式目录 ownership，避免 partial uninstall。"""

    if matching is None:
        return
    for entry in matching.get("entries", []):
        if not isinstance(entry, dict) or str(entry.get("kind")) not in entry_kinds:
            continue
        remove_path_value = str(entry.get("remove_path", ""))
        if not remove_path_value or not Path(remove_path_value).is_dir():
            continue
        fail(
            "检测到 legacy directory ownership，已在任何 mutation 前阻断 uninstall: "
            f"kind={entry.get('kind')} path={remove_path_value}。"
            f"请先运行 `meta-flow install {platform} --scope {scope} --component {component}` "
            "完成 exact leaf set 迁移，再执行 uninstall。"
        )


def _prune_empty_removed_parents(
    removed_paths: Iterable[Path],
    *,
    workspace_root: Path,
    dry_run: bool,
) -> None:
    """只清理由受管叶子产生的空父目录，绝不越过安装根。"""

    root = workspace_root.resolve()
    candidates: set[Path] = set()
    for removed in removed_paths:
        parent = removed.resolve(strict=False).parent
        while parent != root and parent.is_relative_to(root):
            candidates.add(parent)
            parent = parent.parent
    for candidate in sorted(candidates, key=lambda path: len(path.parts), reverse=True):
        if not candidate.is_dir() or any(candidate.iterdir()):
            continue
        if dry_run:
            print(f"[DryRun] remove empty directory -> {candidate}")
        else:
            candidate.rmdir()


def parse_args() -> argparse.Namespace:
    raw_args = sys.argv[1:]
    mode = "install"
    if raw_args and raw_args[0] in {
        "install",
        "upgrade",
        "uninstall",
        "reinstall",
    }:
        mode = raw_args[0]
        raw_args = raw_args[1:]

    prog = sys.argv[0]
    display_prog = prog
    if mode != "install" and not prog.endswith(f" {mode}"):
        display_prog = f"{prog} {mode}"
    action_text = {
        "install": "Install",
        "upgrade": "Upgrade",
        "uninstall": "Uninstall",
        "reinstall": "Force-refresh",
    }[mode]
    usage = (
        f"{display_prog} <platform> [options]\n"
        f"       {display_prog} --platform <platform> [options]  (legacy)"
    )
    if mode in {"install", "upgrade", "reinstall"}:
        epilog = (
            "Examples:\n"
            f"  {display_prog} codex --scope user\n"
            f"  {display_prog} claude --scope project --project-dir /path/to/project\n"
            f"  {display_prog} codex --scope project --component agent --dry-run"
        )
    else:
        epilog = (
            "Examples:\n"
            f"  {display_prog} codex --scope user\n"
            f"  {display_prog} claude --scope project --project-dir /path/to/project\n"
            f"  {display_prog} codex --component rules --dry-run"
        )

    parser = argparse.ArgumentParser(
        prog=display_prog,
        usage=usage,
        description=f"{action_text} Meta Flow assets for claude, codex, openclaw, or qoder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    platform_choices = (*VALID_PLATFORMS, *PLATFORM_ALIASES)
    parser.add_argument("platform_arg", nargs="?", choices=platform_choices, metavar="platform", help="目标平台：claude|codex|openclaw|qoder")
    parser.add_argument("--platform", dest="platform_option", choices=platform_choices, help="Legacy 目标平台选项；新命令优先使用位置参数")
    parser.add_argument("--scope", default="project", choices=VALID_SCOPES, help="安装范围")
    parser.add_argument("--project-dir", default=None, help="WORKSPACE_ROOT；project scope 未提供时交互确认当前目录或输入目录")
    parser.add_argument(
        "--component",
        default=None,
        choices=VALID_COMPONENTS,
        help=(
            "安装组件：rules=规则文件，agent=agents+skills，full=rules+agents+skills；未提供时 user 默认 rules，project 默认 full"
            if mode in {"install", "upgrade", "reinstall"}
            else "卸载组件：rules=规则文件，agent=agents+skills，full=rules+agents+skills；未提供时默认 full"
        ),
    )
    if mode in {"install", "upgrade", "reinstall"}:
        parser.add_argument(
            "--content",
            default=None,
            choices=VALID_CONTENTS,
            help="Legacy 安装内容：all|agents|skills|rules；保留兼容，优先使用 --component",
        )
        parser.add_argument("--agent", default="", help="仅安装指定 agent，逗号分隔")
        parser.add_argument("--skill", default="", help="仅安装指定 skill，逗号分隔")
        parser.add_argument("--permissive", action="store_true", help="允许忽略 canonical agent 中的未支持字段，并将其记录到 warnings")
    else:
        parser.set_defaults(content=None, agent="", skill="", permissive=False)
    parser.add_argument("--dry-run", action="store_true", help="仅打印将执行的操作")
    parser.add_argument(
        "--provider-mode",
        choices=("development", "release"),
        default="development",
        help="provider 身份准入模式；公开 meta-flow CLI 默认使用 release",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="在单一 upgrade transaction 中强制刷新受管内容",
    )
    parser.add_argument("--uninstall", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(raw_args)

    if args.uninstall:
        if mode == "uninstall":
            fail("已使用 uninstall 命令，无需再传 --uninstall。")
        mode = "uninstall"

    args.requested_intent = mode
    if mode == "reinstall":
        mode = "upgrade"
        args.force_refresh = True

    if args.platform_arg and args.platform_option:
        positional = normalize_platform(args.platform_arg)
        legacy = normalize_platform(args.platform_option)
        if positional != legacy:
            fail(f"位置平台 {args.platform_arg} 与 --platform {args.platform_option} 不一致。")

    platform = args.platform_arg or args.platform_option
    if not platform:
        parser.error("必须指定目标平台：claude|codex|openclaw|qoder，例如 `meta-flow install codex`。")

    args.mode = mode
    args.platform = normalize_platform(platform)
    return args


def resolve_install_selection(args: argparse.Namespace) -> tuple[bool, bool, bool, str]:
    if args.component and args.content:
        fail("--component 与 legacy --content 不能同时使用。")

    if args.component:
        component = args.component
    elif args.content:
        component = {
            "all": "full",
            "agents": "agent",
            "skills": "agent",
            "rules": "rules",
        }[args.content]
    else:
        component = "rules" if args.scope == "user" else "full"

    install_rules_enabled = component in ("rules", "full")
    install_agents_enabled = component in ("agent", "full")
    install_skills_enabled = component in ("agent", "full")

    if args.content == "agents":
        install_skills_enabled = False
    if args.content == "skills":
        install_agents_enabled = False

    if parse_csv(args.agent):
        install_agents_enabled = True
    if parse_csv(args.skill):
        install_skills_enabled = True

    return install_rules_enabled, install_agents_enabled, install_skills_enabled, component


def main() -> None:
    args = parse_args()
    workspace_root = resolve_workspace_root(args.project_dir, args.scope)
    delivery_root = script_repo_root(Path(__file__))
    layout = detect_source_layout(delivery_root)
    platform_contracts = load_platform_contracts(layout.platform_contracts)
    checkout_root = find_provider_checkout_root(delivery_root, Path(__file__))
    provider_receipt = load_provider_receipt_facts(
        os.environ.get("META_FLOW_PROVIDER_RECEIPT", "")
    )
    if checkout_root is not None:
        commit = canonical_commit(checkout_root)
        worktree_clean = source_worktree_clean(checkout_root)
    else:
        commit = str(provider_receipt.get("source_commit") or "unknown")
        worktree_clean = None
    delivery_tree_digest = source_delivery_tree_digest(delivery_root)
    profile_digest = capability_profile_digest(delivery_root)
    package_version = (
        str(provider_receipt.get("distribution_version"))
        if provider_receipt
        else distribution_version(delivery_root)
    )
    if args.provider_mode == "release":
        if checkout_root is not None:
            fail(
                "release provider install requires a non-editable qualified artifact; "
                "use --provider-mode development only for local checkout verification"
            )
        if not provider_receipt or provider_receipt.get("release_qualifying") is not True:
            fail("release provider install requires one release-qualifying artifact receipt")
        if provider_receipt.get("source_dirty") is not False:
            fail("release provider artifact receipt must bind a clean source checkout")
        if provider_receipt.get("source_tree_digest") != delivery_tree_digest:
            fail("installed delivery tree differs from provider artifact receipt")
        if provider_receipt.get("capability_profile_digest") != profile_digest:
            fail("installed capability profile differs from provider artifact receipt")
        installed_payload_digest = installed_distribution_payload_digest()
        if not installed_payload_digest:
            fail("installed provider payload digest is unavailable")
        if provider_receipt.get("installed_payload_digest") != installed_payload_digest:
            fail("installed provider payload differs from provider artifact receipt")
    generated = iso_now()
    target_manifest_path = manifest_path(workspace_root, args.scope)

    requested_agents = parse_csv(args.agent)
    requested_skills = parse_csv(args.skill)
    ensure_kebab_case(requested_agents, "agent")
    ensure_kebab_case(requested_skills, "skill")
    reject_legacy_orchestrator_agents(requested_agents)
    if args.mode == "uninstall" and (args.content or requested_agents or requested_skills):
        fail("uninstall 仅支持按 --component rules|agent|full 卸载，不支持 --content/--agent/--skill 过滤。")

    print(f"Workspace root: {workspace_root}")
    print(f"Canonical source root: {layout.root}")
    print(f"Platform contracts: {layout.platform_contracts}")
    print(f"Manifest path: {target_manifest_path}")
    print(f"Platform: {args.platform}")
    print(f"Scope: {args.scope}")
    print(f"Lifecycle intent: {args.requested_intent}")
    print(f"Lifecycle operation: assets.{args.mode}")
    print(f"Force refresh: {str(args.force_refresh).lower()}")

    transaction = Transaction()
    manifest_payload = load_manifest(target_manifest_path)

    # 普通重复安装在 canonical commit 未变化时复用首次审计时间，使所有渲染
    # bytes 与 manifest 保持稳定。源内容若实际变化，write_text 的 bytes 比较
    # 仍会产生真实 mutation；这里只消除纯时间戳漂移。
    existing_install = find_matching_install(
        manifest_payload,
        args.platform,
        args.scope,
        workspace_root,
    )
    if (
        args.mode == "install"
        and existing_install is not None
        and existing_install.get("canonical_commit") == commit
        and existing_install.get("source_tree_digest") == delivery_tree_digest
        and existing_install.get("provider_receipt_digest")
        == provider_receipt.get("receipt_digest")
        and isinstance(existing_install.get("installed_at"), str)
        and existing_install["installed_at"]
    ):
        generated = str(existing_install["installed_at"])

    if args.mode == "uninstall":
        resolved_component = args.component or "full"
        print(f"Component: {resolved_component}")
        with rollback_on_failure(transaction, dry_run=args.dry_run):
            uninstall_platform(
                args.platform,
                args.scope,
                workspace_root,
                platform_contracts,
                manifest_payload,
                transaction,
                args.dry_run,
                resolved_component,
            )
            active_installs = [
                installed
                for installed in manifest_payload.get("installs", [])
                if isinstance(installed, dict)
                and installed.get("status") == "installed"
                and installed.get("entries")
            ]
            if active_installs:
                save_manifest(
                    target_manifest_path,
                    manifest_payload,
                    transaction,
                    args.dry_run,
                )
            else:
                remove_path(target_manifest_path, transaction, args.dry_run)
                _prune_empty_removed_parents(
                    (target_manifest_path,),
                    workspace_root=workspace_root,
                    dry_run=args.dry_run,
                )
        print(f"Uninstalled {args.platform}/{args.scope} component={resolved_component}.")
        return

    canonical_agents = list_canonical_agents(layout, args.permissive)
    selected_skill_dirs = select_skill_dirs(list_skill_dirs(layout), requested_skills)

    install_rules_enabled, install_agents_enabled, install_skills_enabled, resolved_component = resolve_install_selection(args)
    print(f"Component: {resolved_component}")
    if args.content:
        print(f"Legacy content: {args.content}")
    prune_entry_kinds = selected_entry_kinds(resolved_component, args.content)

    if requested_agents and not install_agents_enabled:
        fail("指定了 --agent，但内容类型未包含 agents。")
    if requested_skills and not install_skills_enabled:
        fail("指定了 --skill，但内容类型未包含 skills。")

    warnings: list[str] = runtime_override_warnings(args.platform, args.scope, workspace_root, platform_contracts)
    manifest_entries: list[dict[str, str]] = []
    installed_agent_names: list[str] = []
    installed_skill_names: list[str] = []

    with rollback_on_failure(transaction, dry_run=args.dry_run):
        if install_rules_enabled:
            install_rules(args.platform, args.scope, workspace_root, platform_contracts, layout, transaction, args.dry_run, commit, generated, manifest_entries)

        if install_agents_enabled:
            installed_agent_names = install_agents(
                args.platform,
                args.scope,
                workspace_root,
                platform_contracts,
                layout,
                canonical_agents,
                requested_agents,
                transaction,
                args.dry_run,
                commit,
                generated,
                manifest_entries,
            )

        if install_skills_enabled:
            installed_skill_names = install_skills(
                args.platform,
                args.scope,
                workspace_root,
                platform_contracts,
                selected_skill_dirs,
                transaction,
                args.dry_run,
                commit,
                generated,
                manifest_entries,
            )

        conflicts = scan_name_conflicts(args.platform, args.scope, workspace_root, platform_contracts, installed_agent_names, installed_skill_names)

        if args.platform == "openclaw" and (install_agents_enabled or install_skills_enabled):
            write_openclaw_manifest(args.scope, workspace_root, platform_contracts, manifest_entries, transaction, args.dry_run)

        entry: dict[str, object] = {
            "platform": args.platform,
            "scope": args.scope,
            "status": "installed",
            "installed_at": generated,
            "workspace_root": str(workspace_root),
            "meta_flow_root": str(install_state_root(workspace_root, args.scope)),
            "canonical_commit": commit,
            "distribution_version": package_version,
            "provider_mode": args.provider_mode,
            "source_dirty": (
                bool(provider_receipt.get("source_dirty"))
                if checkout_root is None and provider_receipt
                else worktree_clean is not True
            ),
            "source_tree_digest": delivery_tree_digest,
            "artifact_sha256": provider_receipt.get("artifact_sha256"),
            "provider_receipt_digest": provider_receipt.get("receipt_digest"),
            "capability_profile_digest": profile_digest,
            "installed_payload_digest": provider_receipt.get("installed_payload_digest"),
            "schema_versions": {
                "installation_manifest": 2,
                "phase_metadata": 1,
                "phase_transition": 1,
                "provider_runtime_identity": 2,
                "work_publication_receipt": 2,
            },
            "warnings": warnings
            + [
                f"canonical agent {agent.name} 忽略未支持字段: {', '.join(agent.extra_fields)}"
                for agent in canonical_agents
                if agent.extra_fields and (not requested_agents or agent.name in requested_agents)
            ],
            "conflicts": conflicts,
            "entries": manifest_entries,
        }

        pruned_count = prune_stale_manifest_entries(
            args.platform,
            args.scope,
            workspace_root,
            manifest_payload,
            manifest_entries,
            transaction,
            args.dry_run,
            prune_entry_kinds,
        )
        if pruned_count:
            print(f"Pruned {pruned_count} stale managed item(s) from previous install.")
        legacy_pruned_count = prune_legacy_orchestrator_agents(
            args.platform,
            args.scope,
            workspace_root,
            platform_contracts,
            transaction,
            args.dry_run,
            prune_entry_kinds,
        )
        if legacy_pruned_count:
            print(f"Pruned {legacy_pruned_count} legacy orchestrator agent file(s).")
        upsert_manifest_entry(manifest_payload, entry)
        save_manifest(target_manifest_path, manifest_payload, transaction, args.dry_run)

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    if args.dry_run:
        print("Dry run completed.")
        return

    print(f"Installed {len(manifest_entries)} item(s).")


if __name__ == "__main__":
    main()
