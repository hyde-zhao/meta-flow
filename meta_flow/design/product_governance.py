"""Capability, concept ownership, and package identity governance."""

from __future__ import annotations

import argparse
import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CAPABILITY_STATUS_REL = Path("docs/design/CAPABILITY-STATUS.yaml")
CONCEPT_OWNERS_REL = Path("docs/design/CONCEPT-OWNERS.yaml")
PACKAGE_IDENTITY_REL = Path("docs/design/PACKAGE-IDENTITY.yaml")
ALLOWED_CAPABILITY_STATUSES = {
    "implemented",
    "offline-fixture-only",
    "experimental",
    "advisory",
    "blocked",
    "deferred",
    "not-authorized",
    "future-slot",
    "future-adapter-slot",
    "optional",
}
ALLOWED_DOC_CLAIM_LEVELS = {"implemented", "guarded", "experimental", "future", "advisory", "blocked"}
RUNTIME_READY_TERMS = (
    "runtime-ready",
    "runtime ready",
    "production-ready",
    "production ready",
    "live-ready",
    "live ready",
    "真实运行可用",
    "生产可用",
    "实盘可用",
)
IMPLEMENTED_CLAIM_TERMS = (
    "implemented",
    "已实现",
    "可用",
    "default target",
    "默认 target",
    "默认目标",
)
DELIVERY_KEYWORDS = (
    "delivery",
    "deliverable",
    "release",
    "publish",
    "install",
    "build",
    "docs/",
    "docs\\",
    "部署",
    "发布",
    "交付",
    "安装",
)
FORBIDDEN_PRODUCTION_ROOTS = ("delivery/", ".agents/", ".claude/", ".codex/")


@dataclass(frozen=True)
class DeliveryRoutingReport:
    project_kind: str
    sut_type: str
    mode: str
    output_root: str
    forbidden_roots_when_production: list[str]
    evidence: list[str]
    decision_required: bool
    warnings: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_json_compatible_yaml(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json_compatible_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def capability_path(project_root: Path) -> Path:
    return project_root / CAPABILITY_STATUS_REL


def concept_path(project_root: Path) -> Path:
    return project_root / CONCEPT_OWNERS_REL


def identity_path(project_root: Path) -> Path:
    return project_root / PACKAGE_IDENTITY_REL


def default_capability_status(project_root: Path) -> dict[str, Any]:
    project_id = project_root.resolve().name.replace("-", "_")
    return {
        "schema_version": 1,
        "capabilities": {
            f"{project_id}.core": {
                "status": "implemented",
                "implemented_target": True,
                "runtime_authorized": False,
                "docs_claim_level": "implemented",
                "test_scope": "unit",
                "aliases": [f"{project_id} core"],
            },
            f"{project_id}.runtime": {
                "status": "not-authorized",
                "implemented_target": False,
                "runtime_authorized": False,
                "docs_claim_level": "blocked",
                "test_scope": "none",
                "aliases": [f"{project_id} runtime"],
            },
        },
    }


def default_concept_owners(project_root: Path) -> dict[str, Any]:
    package_name = project_root.resolve().name.replace("-", "_")
    return {
        "schema_version": 1,
        "concept_owners": {
            "data_contracts": {
                "owner": f"{package_name}.data.contracts",
                "conflict_keys": ["data_contracts"],
                "legacy_aliases": ["engine.contracts", "market_data.contracts"],
                "forbidden_aliases": [],
            },
            "source_registry": {
                "owner": f"{package_name}.data.source_registry",
                "conflict_keys": ["source_registry"],
                "legacy_aliases": ["engine.source_registry", "market_data.source_registry"],
                "forbidden_aliases": [],
            },
            "trading_runtime": {
                "owner": f"{package_name}.trading",
                "conflict_keys": ["trading_runtime"],
                "legacy_aliases": [],
                "forbidden_aliases": ["engine.paper_simulation", "engine.order_intent_draft"],
            },
        },
    }


def default_package_identity(project_root: Path) -> dict[str, Any]:
    project_name = project_root.resolve().name
    import_name = project_name.replace("-", "_")
    return {
        "schema_version": 1,
        "product_name": project_name,
        "repo_name": project_name,
        "python_import": import_name,
        "cli_name": import_name,
        "legacy_aliases": [],
        "package_mode": True,
        "public_api_files": [f"{import_name}/__init__.py"],
    }


def write_default_capability_status(project_root: Path, *, force: bool = False) -> Path:
    path = capability_path(project_root.resolve())
    if path.exists() and not force:
        return path
    _write_json_compatible_yaml(path, default_capability_status(project_root.resolve()))
    return path


def write_default_concept_owners(project_root: Path, *, force: bool = False) -> Path:
    path = concept_path(project_root.resolve())
    if path.exists() and not force:
        return path
    _write_json_compatible_yaml(path, default_concept_owners(project_root.resolve()))
    return path


def write_default_package_identity(project_root: Path, *, force: bool = False) -> Path:
    path = identity_path(project_root.resolve())
    if path.exists() and not force:
        return path
    _write_json_compatible_yaml(path, default_package_identity(project_root.resolve()))
    return path


def load_capability_status(project_root: Path) -> dict[str, Any]:
    return _read_json_compatible_yaml(capability_path(project_root.resolve()))


def load_concept_owners(project_root: Path) -> dict[str, Any]:
    return _read_json_compatible_yaml(concept_path(project_root.resolve()))


def load_package_identity(project_root: Path) -> dict[str, Any]:
    return _read_json_compatible_yaml(identity_path(project_root.resolve()))


def validate_capability_status(project_root: Path) -> list[str]:
    path = capability_path(project_root.resolve())
    if not path.is_file():
        return [f"CAPABILITY-STATUS missing: {path}"]
    data = load_capability_status(project_root)
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("CAPABILITY-STATUS schema_version must be 1")
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, dict) or not capabilities:
        return ["CAPABILITY-STATUS capabilities must be a non-empty object"]
    for capability_id, item in capabilities.items():
        if not isinstance(item, dict):
            errors.append(f"{capability_id} must be an object")
            continue
        status = str(item.get("status") or "")
        if status not in ALLOWED_CAPABILITY_STATUSES:
            errors.append(f"{capability_id} invalid status: {status}")
        claim_level = str(item.get("docs_claim_level") or "")
        if claim_level not in ALLOWED_DOC_CLAIM_LEVELS:
            errors.append(f"{capability_id} invalid docs_claim_level: {claim_level}")
        for key in ("implemented_target", "runtime_authorized"):
            if not isinstance(item.get(key), bool):
                errors.append(f"{capability_id} {key} must be boolean")
        if not item.get("test_scope"):
            errors.append(f"{capability_id} missing test_scope")
        if status in {"not-authorized", "blocked", "future-slot", "future-adapter-slot", "deferred"} and item.get(
            "runtime_authorized"
        ):
            errors.append(f"{capability_id} status={status} cannot have runtime_authorized=true")
    return errors


def _capability_aliases(capability_id: str, item: dict[str, Any]) -> list[str]:
    aliases = [capability_id, capability_id.replace(".", "_"), capability_id.replace(".", "-")]
    aliases.extend(str(alias) for alias in item.get("aliases") or [])
    return aliases


def _artifact_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def check_capability_claims(project_root: Path, artifact: Path | None = None) -> tuple[list[str], list[str]]:
    project_root = project_root.resolve()
    errors = validate_capability_status(project_root)
    warnings: list[str] = []
    if errors:
        return errors, warnings
    data = load_capability_status(project_root)
    capabilities = data.get("capabilities") or {}
    artifacts = [(project_root / artifact).resolve() if artifact and not artifact.is_absolute() else artifact.resolve()] if artifact else []
    if not artifacts:
        for candidate in (project_root / "README.md", project_root / "docs" / "README.md"):
            if candidate.is_file():
                artifacts.append(candidate)
    if not artifacts:
        warnings.append("no capability claim artifact found")
        return errors, warnings
    for artifact_path in artifacts:
        if not artifact_path.is_file():
            errors.append(f"artifact missing: {artifact_path}")
            continue
        text = _artifact_text(artifact_path)
        lowered = text.lower()
        for capability_id, item in capabilities.items():
            aliases = _capability_aliases(str(capability_id), item)
            if not any(alias.lower() in lowered for alias in aliases):
                continue
            status = str(item.get("status") or "")
            runtime_authorized = bool(item.get("runtime_authorized"))
            if not runtime_authorized and any(term in lowered for term in RUNTIME_READY_TERMS):
                errors.append(f"{artifact_path} claims runtime-ready capability without authorization: {capability_id}")
            if status in {"deferred", "future-slot", "future-adapter-slot", "not-authorized", "blocked"} and any(
                term.lower() in lowered for term in IMPLEMENTED_CLAIM_TERMS
            ):
                errors.append(f"{artifact_path} overclaims non-implemented capability {capability_id} as implemented/available")
            if status in {"offline-fixture-only", "experimental"} and any(term in lowered for term in RUNTIME_READY_TERMS):
                errors.append(f"{artifact_path} overclaims {status} capability {capability_id} as runtime-ready")
    return errors, warnings


def validate_concept_owners(project_root: Path) -> list[str]:
    path = concept_path(project_root.resolve())
    if not path.is_file():
        return [f"CONCEPT-OWNERS missing: {path}"]
    data = load_concept_owners(project_root)
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("CONCEPT-OWNERS schema_version must be 1")
    concepts = data.get("concept_owners")
    if not isinstance(concepts, dict) or not concepts:
        return ["CONCEPT-OWNERS concept_owners must be a non-empty object"]
    aliases: dict[str, str] = {}
    conflict_keys: dict[str, str] = {}
    owners: dict[str, str] = {}
    for concept_id, item in concepts.items():
        if not isinstance(item, dict):
            errors.append(f"{concept_id} must be an object")
            continue
        owner = str(item.get("owner") or "")
        if not owner:
            errors.append(f"{concept_id} missing owner")
        elif owner in owners and owners[owner] != concept_id:
            errors.append(f"owner assigned to multiple concepts: {owner} -> {owners[owner]}, {concept_id}")
        else:
            owners[owner] = str(concept_id)
        for key in ("legacy_aliases", "forbidden_aliases", "conflict_keys"):
            if key in item and not isinstance(item.get(key), list):
                errors.append(f"{concept_id} {key} must be a list")
        for conflict_key in item.get("conflict_keys") or []:
            key_text = str(conflict_key)
            if key_text in conflict_keys and conflict_keys[key_text] != concept_id:
                errors.append(f"conflict_key assigned to multiple concepts: {key_text} -> {conflict_keys[key_text]}, {concept_id}")
            conflict_keys[key_text] = str(concept_id)
        for key in ("legacy_aliases", "forbidden_aliases"):
            for alias in item.get(key) or []:
                alias_text = str(alias)
                if alias_text in aliases and aliases[alias_text] != concept_id:
                    errors.append(f"alias assigned to multiple concepts: {alias_text} -> {aliases[alias_text]}, {concept_id}")
                aliases[alias_text] = str(concept_id)
    return errors


def check_concept_overlap(project_root: Path, changed_files: list[str] | None = None) -> tuple[list[str], list[str]]:
    errors = validate_concept_owners(project_root)
    warnings: list[str] = []
    if errors:
        return errors, warnings
    data = load_concept_owners(project_root.resolve())
    concepts = data.get("concept_owners") or {}
    files = changed_files or []
    for file_path in files:
        normalized = file_path.replace("/", ".").replace("\\", ".").lower()
        for concept_id, item in concepts.items():
            owner = str(item.get("owner") or "")
            owner_path = owner.replace(".", "/")
            owner_normalized = owner.lower()
            if owner and (owner_normalized in normalized or owner_path.lower() in file_path.lower()):
                continue
            for alias in item.get("forbidden_aliases") or []:
                alias_text = str(alias)
                if alias_text.lower() in normalized:
                    errors.append(f"{file_path} touches forbidden alias for {concept_id}; owner is {owner}")
            for alias in item.get("legacy_aliases") or []:
                alias_text = str(alias)
                if alias_text.lower() in normalized:
                    warnings.append(f"{file_path} touches legacy alias for {concept_id}; prefer owner {owner}")
    return errors, warnings


def validate_package_identity(project_root: Path) -> tuple[list[str], list[str]]:
    project_root = project_root.resolve()
    path = identity_path(project_root)
    if not path.is_file():
        return [f"PACKAGE-IDENTITY missing: {path}"], []
    data = load_package_identity(project_root)
    errors: list[str] = []
    warnings: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("PACKAGE-IDENTITY schema_version must be 1")
    for key in ("product_name", "repo_name", "python_import", "cli_name"):
        if not data.get(key):
            errors.append(f"PACKAGE-IDENTITY missing {key}")
    if not isinstance(data.get("legacy_aliases", []), list):
        errors.append("PACKAGE-IDENTITY legacy_aliases must be a list")
    if not isinstance(data.get("public_api_files", []), list):
        errors.append("PACKAGE-IDENTITY public_api_files must be a list")
    package_mode = data.get("package_mode")
    if not isinstance(package_mode, bool):
        errors.append("PACKAGE-IDENTITY package_mode must be boolean")
    pyproject_path = project_root / "pyproject.toml"
    if pyproject_path.is_file():
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        pyproject_name = str((pyproject.get("project") or {}).get("name") or "")
        expected_name = str(data.get("repo_name") or "")
        if pyproject_name and expected_name and pyproject_name != expected_name:
            errors.append(f"pyproject project.name={pyproject_name} does not match repo_name={expected_name}")
        scripts = (pyproject.get("project") or {}).get("scripts") or {}
        cli_name = str(data.get("cli_name") or "")
        if package_mode and cli_name and cli_name not in scripts:
            warnings.append(f"pyproject project.scripts does not expose cli_name={cli_name}")
    elif package_mode:
        warnings.append("package_mode=true but pyproject.toml is missing")
    python_import = str(data.get("python_import") or "")
    if package_mode and python_import and not (project_root / python_import.replace(".", "/")).exists():
        errors.append(f"python_import package path missing: {python_import}")
    for api_file in data.get("public_api_files") or []:
        if not (project_root / str(api_file)).is_file():
            errors.append(f"public_api_file missing: {api_file}")
    readme = project_root / "README.md"
    if readme.is_file():
        readme_text = readme.read_text(encoding="utf-8", errors="ignore").lower()
        product_name = str(data.get("product_name") or "").lower()
        if product_name and product_name not in readme_text:
            warnings.append(f"README.md does not mention product_name={data.get('product_name')}")
    return errors, warnings


def _scan_text_artifacts(project_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for name in ("README.md", "README.rst", "README.txt"):
        path = project_root / name
        if path.is_file():
            candidates.append(path)
    docs_root = project_root / "docs"
    if docs_root.is_dir():
        for pattern in ("*.md", "*.rst", "*.txt", "*/*.md", "*/*.rst", "*/*.txt"):
            candidates.extend(path for path in docs_root.glob(pattern) if path.is_file())
    return sorted(set(candidates))


def _relative(project_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _project_kind(project_root: Path) -> str:
    if (project_root / "pyproject.toml").is_file():
        return "python-package"
    if (project_root / "package.json").is_file():
        return "node-package"
    return "generic-repo"


def scan_delivery_routing(project_root: Path) -> DeliveryRoutingReport:
    root = project_root.resolve()
    identity_errors, identity_warnings = validate_package_identity(root)
    evidence: list[str] = []
    warnings: list[str] = [*identity_warnings]
    errors: list[str] = [*identity_errors]
    project_kind = _project_kind(root)
    sut_type = "package" if project_kind.endswith("package") else "repository"

    if (root / "pyproject.toml").is_file():
        evidence.append("pyproject.toml")
    identity_file = identity_path(root)
    if identity_file.is_file():
        evidence.append(PACKAGE_IDENTITY_REL.as_posix())

    matched_docs: list[str] = []
    for path in _scan_text_artifacts(root):
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if any(keyword.lower() in text for keyword in DELIVERY_KEYWORDS):
            matched_docs.append(_relative(root, path))
    evidence.extend(matched_docs)

    if matched_docs:
        mode = "project-readme-contract"
        output_root = "project-defined"
        decision_required = False
    else:
        mode = "proposed-output"
        output_root = "docs/"
        decision_required = True
        warnings.append("delivery routing convention not found in README/docs; human confirmation required")

    return DeliveryRoutingReport(
        project_kind=project_kind,
        sut_type=sut_type,
        mode=mode,
        output_root=output_root,
        forbidden_roots_when_production=list(FORBIDDEN_PRODUCTION_ROOTS),
        evidence=evidence,
        decision_required=decision_required,
        warnings=warnings,
        errors=errors,
    )


def _print_delivery_routing_report(project_root: Path, report: DeliveryRoutingReport) -> None:
    print("Package Identity and Delivery Routing Scan: " + ("FAIL" if report.errors else "OK"))
    print(f"project_root: {project_root.resolve()}")
    print(f"project_kind: {report.project_kind}")
    print(f"validation_target.sut_type: {report.sut_type}")
    print(f"delivery_routing.mode: {report.mode}")
    print(f"delivery_routing.output_root: {report.output_root}")
    print(f"delivery_routing.decision_required: {str(report.decision_required).lower()}")
    print("forbidden_roots_when_production:")
    for root in report.forbidden_roots_when_production:
        print(f"- {root}")
    print("evidence:")
    if report.evidence:
        for item in report.evidence:
            print(f"- {item}")
    else:
        print("- none")
    for warning in report.warnings:
        print(f"- WARN: {warning}")
    for error in report.errors:
        print(f"- ERROR: {error}")


def _print_capability_help() -> None:
    print(
        "usage: meta-flow capability <command> [options]\n\n"
        "Commands:\n"
        "  init   Write default docs/design/CAPABILITY-STATUS.yaml.\n"
        "  check  Validate capability status registry and optional docs claims.\n\n"
        "Examples:\n"
        "  meta-flow capability init --project-root .\n"
        "  meta-flow capability check --artifact README.md --project-root .\n"
    )


def _print_concept_help() -> None:
    print(
        "usage: meta-flow concept <command> [options]\n\n"
        "Commands:\n"
        "  init   Write default docs/design/CONCEPT-OWNERS.yaml.\n"
        "  check  Validate concept owners and changed-file overlap.\n\n"
        "Examples:\n"
        "  meta-flow concept init --project-root .\n"
        "  meta-flow concept check --changed-files quant_lab/engine/contracts.py --project-root .\n"
    )


def _print_identity_help() -> None:
    print(
        "usage: meta-flow identity <command> [options]\n\n"
        "Commands:\n"
        "  init   Write default docs/design/PACKAGE-IDENTITY.yaml.\n"
        "  check  Validate repo/package/import/CLI identity.\n\n"
        "  scan   Report package identity plus delivery routing adoption hints without writing files.\n\n"
        "Examples:\n"
        "  meta-flow identity init --project-root .\n"
        "  meta-flow identity check --project-root .\n"
        "  meta-flow identity scan --project-root .\n"
    )


def capability_main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_capability_help()
        return 0
    command = args[0]
    if command == "init":
        parser = argparse.ArgumentParser(prog="meta-flow capability init")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--force", action="store_true")
        parsed = parser.parse_args(args[1:])
        path = write_default_capability_status(parsed.project_root, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "check":
        parser = argparse.ArgumentParser(prog="meta-flow capability check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--artifact", type=Path, default=None)
        parsed = parser.parse_args(args[1:])
        errors, warnings = check_capability_claims(parsed.project_root, parsed.artifact)
        print("Capability Claims Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 capability 命令: {command}. 目前支持: init, check")


def concept_main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_concept_help()
        return 0
    command = args[0]
    if command == "init":
        parser = argparse.ArgumentParser(prog="meta-flow concept init")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--force", action="store_true")
        parsed = parser.parse_args(args[1:])
        path = write_default_concept_owners(parsed.project_root, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "check":
        parser = argparse.ArgumentParser(prog="meta-flow concept check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--changed-files", nargs="*", default=[])
        parsed = parser.parse_args(args[1:])
        errors, warnings = check_concept_overlap(parsed.project_root, parsed.changed_files)
        print("Concept Overlap Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 concept 命令: {command}. 目前支持: init, check")


def identity_main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_identity_help()
        return 0
    command = args[0]
    if command == "init":
        parser = argparse.ArgumentParser(prog="meta-flow identity init")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--force", action="store_true")
        parsed = parser.parse_args(args[1:])
        path = write_default_package_identity(parsed.project_root, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "check":
        parser = argparse.ArgumentParser(prog="meta-flow identity check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_package_identity(parsed.project_root)
        print("Package Identity Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "scan":
        parser = argparse.ArgumentParser(prog="meta-flow identity scan")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed = parser.parse_args(args[1:])
        report = scan_delivery_routing(parsed.project_root)
        _print_delivery_routing_report(parsed.project_root, report)
        return 1 if report.errors else 0
    raise SystemExit(f"未知 identity 命令: {command}. 目前支持: init, check, scan")
