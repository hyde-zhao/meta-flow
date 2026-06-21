"""Module boundary, import direction, and risk ring checks."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.policies.gate_profiles import classify_gate_profile


MODULE_BOUNDARIES_REL = Path("docs/design/MODULE-BOUNDARIES.yaml")
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


@dataclass(frozen=True)
class ImportRecord:
    file_path: Path
    rel_path: str
    source_boundary: str
    imported_module: str
    line_no: int


def boundaries_path(project_root: Path) -> Path:
    return project_root / MODULE_BOUNDARIES_REL


def _read_json_compatible_yaml(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json_compatible_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def default_boundaries(project_root: Path) -> dict[str, Any]:
    package_name = project_root.resolve().name.replace("-", "_")
    return {
        "schema_version": 1,
        "module_boundaries": {
            "core": {
                "package": f"{package_name}.core",
                "paths": [f"{package_name}/core"],
                "may_import": [],
                "must_not_import": [
                    f"{package_name}.data",
                    f"{package_name}.research",
                    f"{package_name}.adapters",
                    f"{package_name}.trading",
                ],
                "risk_profile": "standard-code",
            },
            "data": {
                "package": f"{package_name}.data",
                "paths": [f"{package_name}/data"],
                "may_import": [f"{package_name}.core"],
                "must_not_import": [f"{package_name}.research", f"{package_name}.trading"],
                "risk_profile": "standard-code",
            },
            "research": {
                "package": f"{package_name}.research",
                "paths": [f"{package_name}/research"],
                "may_import": [f"{package_name}.core", f"{package_name}.data"],
                "must_not_import": [
                    f"{package_name}.trading",
                    f"{package_name}.adapters.qmt_terminal_direct",
                    f"{package_name}.adapters.miniqmt_gateway",
                ],
                "risk_profile": "standard-code",
            },
            "adapters": {
                "package": f"{package_name}.adapters",
                "paths": [f"{package_name}/adapters"],
                "may_import": [f"{package_name}.core"],
                "must_not_import": [],
                "optional_sdk_allowed": True,
                "risk_profile": "runtime-high-risk",
            },
            "trading": {
                "package": f"{package_name}.trading",
                "paths": [f"{package_name}/trading"],
                "may_import": [f"{package_name}.core"],
                "must_not_import": [f"{package_name}.research"],
                "risk_profile": "runtime-high-risk",
            },
        },
        "risk_rings": {
            "runtime_high_risk_if_touched": [
                "trading/**",
                "**/qmt*/**",
                "**/miniqmt*/**",
                "**/xtquant*/**",
                "**/credentials/**",
                "**/.env*",
            ],
            "forbidden_imports": [
                {"from": "research", "to": "trading"},
                {"from": "core", "to": "adapters"},
                {"from": "core", "to": "trading"},
                {"from": "data", "to": "trading"},
                {"from": "strategies", "to": "trading"},
            ],
        },
    }


def write_default_boundaries(project_root: Path, *, force: bool = False) -> Path:
    path = boundaries_path(project_root.resolve())
    if path.exists() and not force:
        return path
    _write_json_compatible_yaml(path, default_boundaries(project_root.resolve()))
    return path


def load_boundaries(project_root: Path) -> dict[str, Any]:
    path = boundaries_path(project_root.resolve())
    if not path.is_file():
        return {}
    return _read_json_compatible_yaml(path)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _module_boundaries(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    boundaries = data.get("module_boundaries") or {}
    return {str(name): item for name, item in boundaries.items() if isinstance(item, dict)}


def validate_boundaries(project_root: Path) -> list[str]:
    project_root = project_root.resolve()
    path = boundaries_path(project_root)
    errors: list[str] = []
    if not path.is_file():
        return [f"MODULE-BOUNDARIES missing: {path}"]
    data = load_boundaries(project_root)
    if data.get("schema_version") != 1:
        errors.append("MODULE-BOUNDARIES schema_version must be 1")
    boundaries = _module_boundaries(data)
    if not boundaries:
        errors.append("module_boundaries must be a non-empty object")
        return errors
    packages: dict[str, str] = {}
    path_owners: dict[str, str] = {}
    for name, item in boundaries.items():
        package = str(item.get("package") or "")
        if not package:
            errors.append(f"{name} missing package")
        elif package in packages:
            errors.append(f"duplicate package owner: {package} -> {packages[package]}, {name}")
        else:
            packages[package] = name
        paths = _as_list(item.get("paths"))
        if not paths:
            errors.append(f"{name} paths must be a non-empty list")
        for raw_path in paths:
            normalized = raw_path.rstrip("/")
            if normalized in path_owners and path_owners[normalized] != name:
                errors.append(f"path has multiple boundary owners: {normalized} -> {path_owners[normalized]}, {name}")
            path_owners[normalized] = name
        for list_key in ("may_import", "must_not_import"):
            if list_key in item and not isinstance(item.get(list_key), list):
                errors.append(f"{name} {list_key} must be a list")
    return errors


def _iter_python_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in project_root.rglob("*.py"):
        rel_parts = path.relative_to(project_root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        files.append(path)
    return sorted(files)


def _matches_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _boundary_for_file(rel_path: str, boundaries: dict[str, dict[str, Any]]) -> str:
    normalized = rel_path.replace("\\", "/")
    for name, item in boundaries.items():
        for root in _as_list(item.get("paths")):
            root_prefix = root.rstrip("/") + "/"
            if normalized.startswith(root_prefix):
                return name
    return ""


def _boundary_for_import(module: str, boundaries: dict[str, dict[str, Any]]) -> str:
    for name, item in boundaries.items():
        package = str(item.get("package") or "")
        if package and _matches_prefix(module, package):
            return name
    return ""


def _imports_from_file(path: Path) -> list[tuple[str, int]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append((node.module, node.lineno))
    return imports


def collect_import_records(project_root: Path) -> list[ImportRecord]:
    project_root = project_root.resolve()
    data = load_boundaries(project_root)
    boundaries = _module_boundaries(data)
    records: list[ImportRecord] = []
    for path in _iter_python_files(project_root):
        rel_path = path.relative_to(project_root).as_posix()
        source_boundary = _boundary_for_file(rel_path, boundaries)
        if not source_boundary:
            continue
        for imported_module, line_no in _imports_from_file(path):
            records.append(
                ImportRecord(
                    file_path=path,
                    rel_path=rel_path,
                    source_boundary=source_boundary,
                    imported_module=imported_module,
                    line_no=line_no,
                )
            )
    return records


def check_imports(project_root: Path) -> tuple[list[str], list[str]]:
    project_root = project_root.resolve()
    errors = validate_boundaries(project_root)
    warnings: list[str] = []
    if errors:
        return errors, warnings
    data = load_boundaries(project_root)
    boundaries = _module_boundaries(data)
    package_boundaries = {name for name in boundaries}
    for record in collect_import_records(project_root):
        source = boundaries[record.source_boundary]
        imported_boundary = _boundary_for_import(record.imported_module, boundaries)
        for forbidden in _as_list(source.get("must_not_import")):
            if _matches_prefix(record.imported_module, forbidden):
                errors.append(
                    f"{record.rel_path}:{record.line_no} {record.source_boundary} must not import {record.imported_module}"
                )
        if imported_boundary and imported_boundary != record.source_boundary:
            may_import = _as_list(source.get("may_import"))
            imported_package = str(boundaries[imported_boundary].get("package") or "")
            allowed = any(_matches_prefix(imported_package, allowed_package) for allowed_package in may_import)
            if may_import and not allowed:
                errors.append(
                    f"{record.rel_path}:{record.line_no} {record.source_boundary} imports {imported_boundary} "
                    f"without may_import allowance: {record.imported_module}"
                )
    if not package_boundaries:
        warnings.append("no module boundaries configured")
    return errors, warnings


def _boundary_touched_by_path(path: str, boundaries: dict[str, dict[str, Any]]) -> str:
    normalized = path.replace("\\", "/")
    for name, item in boundaries.items():
        for root in _as_list(item.get("paths")):
            root_prefix = root.rstrip("/") + "/"
            if normalized == root.rstrip("/") or normalized.startswith(root_prefix):
                return name
    return ""


def check_risk_rings(
    project_root: Path,
    *,
    changed_files: list[str] | None = None,
    impacts: list[str] | None = None,
) -> tuple[list[str], list[str], dict[str, Any]]:
    project_root = project_root.resolve()
    data = load_boundaries(project_root)
    boundaries = _module_boundaries(data)
    errors: list[str] = []
    warnings: list[str] = []
    classification = classify_gate_profile(changed_files or [], impacts or [])
    touched_boundaries = [
        boundary
        for file_path in changed_files or []
        for boundary in [_boundary_touched_by_path(file_path, boundaries)]
        if boundary
    ]
    for boundary in sorted(set(touched_boundaries)):
        profile = str(boundaries.get(boundary, {}).get("risk_profile") or "")
        if profile == "runtime-high-risk" and classification["profile"] != "runtime-high-risk":
            errors.append(f"touching runtime-high-risk boundary requires runtime-high-risk profile: {boundary}")
    import_errors, import_warnings = check_imports(project_root)
    errors.extend(import_errors)
    warnings.extend(import_warnings)
    return errors, warnings, {"classification": classification, "touched_boundaries": sorted(set(touched_boundaries))}


def check_architecture_fitness(project_root: Path) -> tuple[list[str], list[str]]:
    errors = validate_boundaries(project_root)
    warnings: list[str] = []
    if not errors:
        import_errors, import_warnings = check_imports(project_root)
        errors.extend(import_errors)
        warnings.extend(import_warnings)
    data = load_boundaries(project_root.resolve())
    for name, item in _module_boundaries(data).items():
        if not item.get("package"):
            errors.append(f"{name} fitness missing package")
        if not item.get("paths"):
            errors.append(f"{name} fitness missing paths")
        if item.get("risk_profile") == "runtime-high-risk" and not item.get("must_not_import"):
            warnings.append(f"{name} is runtime-high-risk but has no explicit must_not_import isolation")
    return errors, warnings


def _print_module_help() -> None:
    print(
        "usage: meta-flow module <command> [options]\n\n"
        "Commands:\n"
        "  init                  Write default docs/design/MODULE-BOUNDARIES.yaml.\n"
        "  check-boundaries      Validate module boundary config.\n"
        "  check-imports         Scan Python imports against module boundaries.\n"
        "  check-risk-rings      Check changed files and imports against runtime risk rings.\n"
        "  architecture-fitness  Run boundary, import, and isolation checks.\n\n"
        "Examples:\n"
        "  meta-flow module init --project-root .\n"
        "  meta-flow module check-imports --project-root .\n"
        "  meta-flow module check-risk-rings --changed-files quant_lab/trading/order.py --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_module_help()
        return 0
    command = args[0]
    if command == "init":
        parser = argparse.ArgumentParser(prog="meta-flow module init")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--force", action="store_true")
        parsed = parser.parse_args(args[1:])
        path = write_default_boundaries(parsed.project_root, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "check-boundaries":
        parser = argparse.ArgumentParser(prog="meta-flow module check-boundaries")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed = parser.parse_args(args[1:])
        errors = validate_boundaries(parsed.project_root)
        print("Module Boundary Check: " + ("FAIL" if errors else "OK"))
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "check-imports":
        parser = argparse.ArgumentParser(prog="meta-flow module check-imports")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed = parser.parse_args(args[1:])
        errors, warnings = check_imports(parsed.project_root)
        print("Import Boundary Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "check-risk-rings":
        parser = argparse.ArgumentParser(prog="meta-flow module check-risk-rings")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--changed-files", nargs="*", default=[])
        parser.add_argument("--impact", nargs="*", default=[])
        parsed = parser.parse_args(args[1:])
        errors, warnings, details = check_risk_rings(
            parsed.project_root,
            changed_files=parsed.changed_files,
            impacts=parsed.impact,
        )
        classification = details["classification"]
        print("Risk Ring Check: " + ("FAIL" if errors else "OK"))
        print(f"- profile: {classification['profile']}")
        print(f"- reason: {classification['reason']}")
        print(f"- touched_boundaries: {', '.join(details['touched_boundaries']) or '-'}")
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "architecture-fitness":
        parser = argparse.ArgumentParser(prog="meta-flow module architecture-fitness")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed = parser.parse_args(args[1:])
        errors, warnings = check_architecture_fitness(parsed.project_root)
        print("Architecture Fitness Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(
        "未知 module 命令: "
        f"{command}. 目前支持: init, check-boundaries, check-imports, check-risk-rings, architecture-fitness"
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
