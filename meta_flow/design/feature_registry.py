"""Feature registry and design ownership checks."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FEATURE_REGISTRY_REL = Path("docs/design/FEATURE-REGISTRY.yaml")
FEATURE_DESIGN_MATRIX_REL = Path("docs/design/FEATURE-DESIGN-MATRIX.yaml")
STORY_ROOT_REL = Path("process/stories")
ALLOWED_FEATURE_STATUSES = {
    "proposed",
    "planned",
    "implemented",
    "offline-fixture-only",
    "experimental",
    "advisory",
    "blocked",
    "deferred",
    "not-authorized",
    "future-slot",
    "optional",
    "waived",
    "n/a",
}
DESIGN_DOC_WAIVED_STATUSES = {"blocked", "deferred", "future-slot", "not-authorized", "waived", "n/a"}
ALLOWED_RISK_PROFILES = {
    "micro",
    "docs-lite",
    "process-lite",
    "standard-code",
    "architecture-major",
    "runtime-high-risk",
}
ALLOWED_LLD_POLICIES = {"full-lld", "technical-note", "waived"}
ALLOWED_DESIGN_DOC_POLICIES = {"full-design", "compact-design", "technical-note", "registry-only", "waived"}
TAXONOMY_REQUIRED_PROFILES = {"architecture-major", "product-redesign", "runtime-high-risk"}


@dataclass(frozen=True)
class StoryTrace:
    path: Path
    story_id: str
    feature_refs: list[str]
    feature_design_refs: list[str]
    lld_policy: str
    risk_profile: str


def registry_path(project_root: Path) -> Path:
    return project_root / FEATURE_REGISTRY_REL


def _rel(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json_compatible_yaml(path: Path) -> dict[str, Any]:
    try:
        return json.loads(_read_text(path))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json_compatible_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _title_from_design(path: Path) -> str:
    if not path.is_file():
        return path.parent.name.replace("-", " ").title()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.lstrip("# ").strip()
    return path.parent.name.replace("-", " ").title()


def _feature_id_from_dir(path: Path) -> str:
    return path.name.replace("-", ".").replace("_", ".")


def default_registry(project_root: Path) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    feature_root = project_root / "docs" / "features"
    if feature_root.is_dir():
        for feature_dir in sorted(item for item in feature_root.iterdir() if item.is_dir()):
            design_doc = feature_dir / "DESIGN.md"
            test_plan = feature_dir / "TEST-PLAN.md"
            features.append(
                {
                    "feature_id": _feature_id_from_dir(feature_dir),
                    "title": _title_from_design(design_doc),
                    "product_domain": "",
                    "capability": "",
                    "owner_context": _feature_id_from_dir(feature_dir).split(".")[0],
                    "status": "planned",
                    "risk_profile": "standard-code",
                    "design_doc_policy": "full-design",
                    "design_doc": _rel(project_root, design_doc),
                    "test_plan": _rel(project_root, test_plan),
                    "tasks_doc": _rel(project_root, feature_dir / "TASKS.md"),
                    "module_paths": [],
                    "public_api": [],
                    "forbidden_dependencies": [],
                    "authz_policy_refs": [],
                }
            )
    return {
        "schema_version": 1,
        "features": features,
    }


def write_registry(project_root: Path, *, force: bool = False) -> Path:
    path = registry_path(project_root.resolve())
    if path.exists() and not force:
        return path
    _write_json_compatible_yaml(path, default_registry(project_root.resolve()))
    return path


def load_registry(project_root: Path) -> dict[str, Any]:
    path = registry_path(project_root.resolve())
    if not path.is_file():
        return {}
    return _read_json_compatible_yaml(path)


def _features_by_id(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    features: dict[str, dict[str, Any]] = {}
    for item in registry.get("features") or []:
        if not isinstance(item, dict):
            continue
        feature_id = str(item.get("feature_id") or item.get("id") or "")
        if feature_id:
            features[feature_id] = item
    return features


def validate_registry(project_root: Path) -> tuple[list[str], list[str]]:
    project_root = project_root.resolve()
    path = registry_path(project_root)
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        return [f"FEATURE-REGISTRY missing: {path}"], []
    registry = load_registry(project_root)
    if registry.get("schema_version") != 1:
        errors.append("FEATURE-REGISTRY schema_version must be 1")
    features = registry.get("features")
    if not isinstance(features, list) or not features:
        errors.append("FEATURE-REGISTRY features must be a non-empty list")
        return errors, warnings
    seen: set[str] = set()
    module_owners: dict[str, str] = {}
    for index, item in enumerate(features, start=1):
        if not isinstance(item, dict):
            errors.append(f"features[{index}] must be an object")
            continue
        feature_id = str(item.get("feature_id") or item.get("id") or "")
        if not feature_id:
            errors.append(f"features[{index}] missing feature_id")
            continue
        if feature_id in seen:
            errors.append(f"duplicate feature_id: {feature_id}")
        seen.add(feature_id)
        for key in ("title", "owner_context", "status", "risk_profile"):
            if not item.get(key):
                errors.append(f"{feature_id} missing {key}")
        status = str(item.get("status") or "")
        if status and status not in ALLOWED_FEATURE_STATUSES:
            errors.append(f"{feature_id} invalid status: {status}")
        risk_profile = str(item.get("risk_profile") or "")
        if risk_profile and risk_profile not in ALLOWED_RISK_PROFILES:
            errors.append(f"{feature_id} invalid risk_profile: {risk_profile}")
        governance_profile = str(item.get("gate_profile") or item.get("taxonomy_profile") or risk_profile or "")
        if governance_profile in TAXONOMY_REQUIRED_PROFILES:
            for key in ("product_domain", "capability"):
                if not item.get(key):
                    errors.append(f"{feature_id} {governance_profile} requires {key}")
        design_doc_policy = str(item.get("design_doc_policy") or "full-design")
        if design_doc_policy not in ALLOWED_DESIGN_DOC_POLICIES:
            errors.append(f"{feature_id} invalid design_doc_policy: {design_doc_policy}")
        module_paths = item.get("module_paths")
        if not isinstance(module_paths, list) or not module_paths:
            errors.append(f"{feature_id} module_paths must be a non-empty list")
        else:
            for module_path in module_paths:
                normalized = str(module_path).rstrip("/")
                if normalized in module_owners and module_owners[normalized] != feature_id:
                    errors.append(
                        f"module path has multiple owners: {normalized} -> {module_owners[normalized]}, {feature_id}"
                    )
                module_owners[normalized] = feature_id
        for list_key in ("public_api", "forbidden_dependencies", "authz_policy_refs"):
            if list_key in item and not isinstance(item.get(list_key), list):
                errors.append(f"{feature_id} {list_key} must be a list")
        design_doc = str(item.get("design_doc") or "")
        requires_design_doc = design_doc_policy in {"full-design", "compact-design"} and status not in DESIGN_DOC_WAIVED_STATUSES
        if requires_design_doc:
            if not design_doc:
                errors.append(f"{feature_id} missing design_doc")
            elif not (project_root / design_doc).is_file():
                errors.append(f"{feature_id} design_doc missing on disk: {design_doc}")
        elif design_doc and not (project_root / design_doc).is_file():
            warnings.append(f"{feature_id} design_doc declared but missing on disk: {design_doc}")
        elif not design_doc:
            warnings.append(f"{feature_id} design_doc waived by status={status} design_doc_policy={design_doc_policy}")
    return errors, warnings


def _frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    if end == -1:
        return ""
    return text[4:end]


def _parse_scalar_or_list(value: str) -> str | list[str]:
    raw = value.strip().strip('"').strip("'")
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]
    return raw


def _parse_flat_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key = ""
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_key:
            data.setdefault(current_key, []).append(line.strip()[2:].strip().strip('"').strip("'"))
            continue
        if line.startswith("  ") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_key = key
        if value:
            data[key] = _parse_scalar_or_list(value)
        else:
            data[key] = []
    return data


def _load_story_data(path: Path) -> dict[str, Any]:
    text = _read_text(path)
    if path.suffix == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
    frontmatter = _frontmatter(text)
    if frontmatter:
        return _parse_flat_yaml(frontmatter)
    if path.suffix in {".yaml", ".yml"}:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return _parse_flat_yaml(text)
    return _parse_flat_yaml(text)


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _story_id_from_path(path: Path, data: dict[str, Any]) -> str:
    return str(data.get("story_id") or data.get("id") or path.stem)


def discover_story_files(project_root: Path) -> list[Path]:
    root = project_root / STORY_ROOT_REL
    if not root.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(root.glob("STORY-*")):
        if not path.is_file():
            continue
        name = path.name
        if "-LLD" in name or "-IMPLEMENTATION" in name or "-DEV-LOG" in name:
            continue
        if path.suffix not in {".md", ".yaml", ".yml", ".json"}:
            continue
        files.append(path)
    return files


def story_trace_from_file(path: Path) -> StoryTrace:
    data = _load_story_data(path)
    return StoryTrace(
        path=path,
        story_id=_story_id_from_path(path, data),
        feature_refs=_as_list(data.get("feature_refs") or data.get("affected_features")),
        feature_design_refs=_as_list(data.get("feature_design_refs") or data.get("design_doc_refs")),
        lld_policy=str(data.get("lld_policy") or data.get("required_level") or ""),
        risk_profile=str(data.get("risk_profile") or ""),
    )


def trace_stories(project_root: Path, story_paths: list[Path] | None = None) -> tuple[list[str], list[str], list[StoryTrace]]:
    project_root = project_root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    registry = load_registry(project_root)
    features = _features_by_id(registry)
    if not features:
        errors.append("FEATURE-REGISTRY has no features; run meta-flow feature build/check first")
    paths = [path.resolve() for path in story_paths] if story_paths else discover_story_files(project_root)
    traces = [story_trace_from_file(path) for path in paths]
    if not traces:
        warnings.append("no Story files found for story-to-feature trace")
    for trace in traces:
        rel_path = _rel(project_root, trace.path)
        if not trace.feature_refs:
            errors.append(f"{rel_path} missing feature_refs")
        for feature_id in trace.feature_refs:
            if feature_id not in features:
                errors.append(f"{rel_path} references unknown feature_id: {feature_id}")
        if not trace.feature_design_refs:
            errors.append(f"{rel_path} missing feature_design_refs")
        if not trace.lld_policy:
            errors.append(f"{rel_path} missing lld_policy")
        elif trace.lld_policy not in ALLOWED_LLD_POLICIES:
            errors.append(f"{rel_path} invalid lld_policy: {trace.lld_policy}")
        effective_risks = {trace.risk_profile}
        effective_risks.update(str(features.get(feature_id, {}).get("risk_profile") or "") for feature_id in trace.feature_refs)
        if "runtime-high-risk" in effective_risks and trace.lld_policy != "full-lld":
            errors.append(f"{rel_path} runtime-high-risk Story must use lld_policy=full-lld")
    return errors, warnings, traces


def _print_trace(project_root: Path, traces: list[StoryTrace]) -> None:
    grouped: dict[str, list[str]] = {}
    for trace in traces:
        for feature_id in trace.feature_refs or ["<missing>"]:
            grouped.setdefault(feature_id, []).append(trace.story_id)
    print("Story to Feature Trace:")
    if not grouped:
        print("- none")
        return
    for feature_id, story_ids in sorted(grouped.items()):
        print(f"- {feature_id}: {', '.join(story_ids)}")


def _print_feature_help() -> None:
    print(
        "usage: meta-flow feature <command> [options]\n\n"
        "Commands:\n"
        "  build  Build docs/design/FEATURE-REGISTRY.yaml from docs/features/*.\n"
        "  list   List registered features.\n"
        "  check  Validate feature registry and design ownership fields.\n"
        "  trace  Validate Story feature_refs / feature_design_refs / lld_policy.\n\n"
        "Examples:\n"
        "  meta-flow feature build --project-root .\n"
        "  meta-flow feature check --project-root .\n"
        "  meta-flow feature trace --project-root .\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        _print_feature_help()
        return 0
    command = args[0]
    if command == "build":
        parser = argparse.ArgumentParser(prog="meta-flow feature build")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--force", action="store_true")
        parsed = parser.parse_args(args[1:])
        path = write_registry(parsed.project_root, force=parsed.force)
        print(f"wrote: {path}")
        return 0
    if command == "list":
        parser = argparse.ArgumentParser(prog="meta-flow feature list")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed = parser.parse_args(args[1:])
        registry = load_registry(parsed.project_root)
        features = _features_by_id(registry)
        print("Feature Registry:")
        if not features:
            print("- none")
            return 0
        for feature_id, item in sorted(features.items()):
            print(f"- {feature_id}: {item.get('title')} ({item.get('status')}, {item.get('risk_profile')})")
        return 0
    if command == "check":
        parser = argparse.ArgumentParser(prog="meta-flow feature check")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parsed = parser.parse_args(args[1:])
        errors, warnings = validate_registry(parsed.project_root)
        print("Feature Registry Check: " + ("FAIL" if errors else "OK"))
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    if command == "trace":
        parser = argparse.ArgumentParser(prog="meta-flow feature trace")
        parser.add_argument("--project-root", type=Path, default=Path.cwd())
        parser.add_argument("--story", dest="stories", type=Path, action="append", default=[])
        parsed = parser.parse_args(args[1:])
        errors, warnings, traces = trace_stories(parsed.project_root, parsed.stories)
        print("Story Feature Trace Check: " + ("FAIL" if errors else "OK"))
        _print_trace(parsed.project_root.resolve(), traces)
        for warning in warnings:
            print(f"- WARN: {warning}")
        for error in errors:
            print(f"- ERROR: {error}")
        return 1 if errors else 0
    raise SystemExit(f"未知 feature 命令: {command}. 目前支持: build, list, check, trace")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
