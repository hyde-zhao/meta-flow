"""Authorization policy registry for Meta Flow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


AUTHZ_POLICY_REL = Path("process/policies/AUTHZ-POLICY.json")
HIGH_RISK_POLICY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "NO_CREDENTIAL_READ": ("credential", "credentials", "secret", "token", ".env", "account", "凭据", "密钥", "账户"),
    "NO_NAS_ACCESS": ("nas", "网络盘"),
    "NO_RUNTIME_CONNECTION": ("qmt", "miniqmt", "xtquant", "gateway", "runtime", "真实运行"),
    "NO_ORDER_WRITE": (
        "submit_order",
        "cancel_order",
        "order_write",
        "order-write",
        "trading",
        "live",
        "simulation",
        "交易",
        "下单",
        "撤单",
    ),
    "NO_PROVIDER_LAKE_PUBLISH": (
        "provider_publish",
        "lake_write",
        "catalog_publish",
        "provider",
        "data lake",
        "catalog",
        "publish",
        "发布",
    ),
}


def default_authz_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policies": {
            "NO_CREDENTIAL_READ": {
                "title": "No credential/env/account read",
                "default": "denied",
                "requires": "explicit_per_run_authorization",
                "expanded_text": "不授权读取凭据、.env、账户、token、secret、原始日志中的敏感字段。",
            },
            "NO_NAS_ACCESS": {
                "title": "No NAS access",
                "default": "denied",
                "requires": "explicit_per_run_authorization",
                "expanded_text": "不授权真实 NAS list/read/copy/write/delete/publish。",
            },
            "NO_RUNTIME_CONNECTION": {
                "title": "No runtime connection",
                "default": "denied",
                "requires": "explicit_per_run_authorization",
                "expanded_text": "不授权连接 QMT/MiniQMT/XtQuant/gateway/runtime。",
            },
            "NO_ORDER_WRITE": {
                "title": "No order write",
                "default": "denied",
                "requires": "explicit_high_risk_gate",
                "expanded_text": "不授权 submit/cancel/order-write/simulation/live/trading。",
            },
            "NO_PROVIDER_LAKE_PUBLISH": {
                "title": "No provider/lake/catalog publish",
                "default": "denied",
                "requires": "explicit_release_gate",
                "expanded_text": "不授权 provider、data lake、catalog 发布或真实数据写入。",
            },
        },
    }


def policy_path(project_root: Path) -> Path:
    return project_root / AUTHZ_POLICY_REL


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_authz_policy(project_root: Path) -> dict[str, Any]:
    configured = _read_json(policy_path(project_root.resolve()))
    if configured:
        return configured
    return default_authz_policy()


def write_default_authz_policy(project_root: Path, *, force: bool = False) -> Path:
    path = policy_path(project_root.resolve())
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default_authz_policy(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_authz_policy(project_root: Path) -> list[str]:
    errors: list[str] = []
    policy = load_authz_policy(project_root)
    if policy.get("schema_version") != 1:
        errors.append("AUTHZ-POLICY schema_version must be 1")
    policies = policy.get("policies")
    if not isinstance(policies, dict) or not policies:
        return ["AUTHZ-POLICY policies must be a non-empty object"]
    for policy_id, item in policies.items():
        if not isinstance(item, dict):
            errors.append(f"{policy_id} must be an object")
            continue
        for key in ("title", "default", "requires", "expanded_text"):
            if not item.get(key):
                errors.append(f"{policy_id} missing {key}")
        if item.get("default") != "denied":
            errors.append(f"{policy_id} default must be denied")
    return errors


def _is_human_or_release_artifact(path: Path) -> bool:
    rel = path.as_posix()
    return "/process/checkpoints/" in rel or "/process/release/" in rel or "/docs/release/" in rel


def required_policy_refs_for_text(text: str) -> list[str]:
    lowered = text.lower()
    refs = []
    for policy_id, keywords in HIGH_RISK_POLICY_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            refs.append(policy_id)
    return refs


def check_artifact(project_root: Path, artifact: Path) -> tuple[list[str], list[str]]:
    project_root = project_root.resolve()
    artifact = artifact.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not artifact.is_file():
        return [f"artifact missing: {artifact}"], []
    policy = load_authz_policy(project_root)
    policies = policy.get("policies") or {}
    text = artifact.read_text(encoding="utf-8", errors="ignore")
    required_refs = required_policy_refs_for_text(text)
    for policy_id in required_refs:
        if policy_id not in text:
            errors.append(f"artifact mentions high-risk surface but lacks authz policy ref: {policy_id}")
    if not _is_human_or_release_artifact(artifact):
        for policy_id, item in policies.items():
            expanded = str(item.get("expanded_text") or "")
            if expanded and expanded in text:
                errors.append(f"ordinary artifact copies expanded policy text; use authz_policy_refs instead: {policy_id}")
    if not required_refs:
        warnings.append("no high-risk authorization surface detected")
    return errors, warnings


def _print_policy_help() -> None:
    print(
        "usage: meta-flow policy <command> [options]\n\n"
        "Commands:\n"
        "  list    List authorization policy IDs.\n"
        "  expand  Expand selected policy IDs for human gate or release decisions.\n"
        "  check   Validate AUTHZ-POLICY.json or a policy-bearing artifact.\n\n"
        "Examples:\n"
        "  meta-flow policy list --project-root .\n"
        "  meta-flow policy expand NO_CREDENTIAL_READ NO_NAS_ACCESS --project-root .\n"
        "  meta-flow policy check --artifact process/checkpoints/CP8-DELIVERY-READINESS.md --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_policy_help()
        return 0
    command = args[0]
    if command == "list":
        parser = argparse.ArgumentParser(prog="meta-flow policy list")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--write-default", action="store_true")
        parsed = parser.parse_args(args[1:])
        if parsed.write_default:
            path = write_default_authz_policy(parsed.project_root)
            print(f"wrote: {path}")
        policy = load_authz_policy(parsed.project_root)
        print("Authz Policies:")
        for policy_id, item in sorted((policy.get("policies") or {}).items()):
            print(f"- {policy_id}: {item.get('title')} ({item.get('requires')})")
        return 0
    if command == "expand":
        parser = argparse.ArgumentParser(prog="meta-flow policy expand")
        parser.add_argument("policy_ids", nargs="+")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed = parser.parse_args(args[1:])
        policies = load_authz_policy(parsed.project_root).get("policies") or {}
        missing = [policy_id for policy_id in parsed.policy_ids if policy_id not in policies]
        if missing:
            raise SystemExit(f"未知 policy ID: {', '.join(missing)}")
        for policy_id in parsed.policy_ids:
            item = policies[policy_id]
            print(f"{policy_id}: {item.get('title')}")
            print(f"- default: {item.get('default')}")
            print(f"- requires: {item.get('requires')}")
            print(f"- expanded_text: {item.get('expanded_text')}")
        return 0
    if command == "check":
        parser = argparse.ArgumentParser(prog="meta-flow policy check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--artifact", type=Path, default=None)
        parser.add_argument("--write-default", action="store_true")
        parsed = parser.parse_args(args[1:])
        if parsed.write_default:
            path = write_default_authz_policy(parsed.project_root)
            print(f"wrote: {path}")
        errors = validate_authz_policy(parsed.project_root)
        warnings: list[str] = []
        if parsed.artifact:
            artifact_errors, artifact_warnings = check_artifact(parsed.project_root, parsed.artifact)
            errors.extend(artifact_errors)
            warnings.extend(artifact_warnings)
        print("Authz Policy Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 policy 命令: {command}. 目前支持: list, expand, check")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

