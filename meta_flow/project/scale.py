"""PROJECT-SCALE.yaml validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.policies import gate_profiles


PROJECT_SCALE_REL = Path("process/project/PROJECT-SCALE.yaml")
PROJECT_SCALE_SCHEMA_VERSION = 1
SCALE_LEVELS = {"lite", "standard", "full"}
REQUIRED_NOT_AUTHORIZED = {
    "skip_human_gate",
    "modify_gate_profiles",
    "runtime_authorization",
    "publish_authorization",
}
AUTHORIZATION_KEYWORDS = (
    "auto_approve",
    "auto-approve",
    "auto approve",
    "skip_gate",
    "skip-gate",
    "skip gate",
    "skip_cp",
    "skip-cp",
    "runtime_authorization",
    "publish_authorization",
    "modify_gate_profiles",
    "gate_policy_mutation",
    "write_gate_profiles",
)


@dataclass(frozen=True)
class ProjectFinding:
    severity: str
    code: str
    message: str
    key: str | None = None

    def as_cli_line(self) -> str:
        return self.message


@dataclass(frozen=True)
class ProjectScale:
    project_id: str
    scale_level: str
    gate_profile_bias: dict[str, Any]
    review_cadence_bias: dict[str, Any]
    not_authorized: tuple[str, ...]
    source_refs: tuple[dict[str, Any], ...]
    updated_at: str


def add_finding(
    findings: list[ProjectFinding],
    severity: str,
    code: str,
    message: str,
    *,
    key: str | None = None,
) -> None:
    findings.append(ProjectFinding(severity=severity, code=code, message=message, key=key))


def _strip_comment(line: str) -> str:
    in_quote: str | None = None
    for index, char in enumerate(line):
        if char in {"'", '"'}:
            in_quote = None if in_quote == char else char
        if char == "#" and in_quote is None:
            return line[:index]
    return line


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if text == "":
        return ""
    if text in {"[]", "{}"}:
        return [] if text == "[]" else {}
    if text in {"true", "false"}:
        return text == "true"
    if text in {"null", "~"}:
        return None
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        try:
            return json.loads(text.replace("'", '"'))
        except json.JSONDecodeError:
            inner = text[1:-1].strip()
            return [piece.strip().strip('"').strip("'") for piece in inner.split(",") if piece.strip()]
    try:
        return int(text)
    except ValueError:
        return text


def _parse_yaml_lines(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    if lines[index][1].startswith("- "):
        values: list[Any] = []
        while index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
            rest = lines[index][1][2:].strip()
            index += 1
            if rest == "":
                nested, index = _parse_yaml_lines(lines, index, indent + 2)
                values.append(nested)
            elif ":" in rest:
                key, raw_value = rest.split(":", 1)
                item: dict[str, Any] = {}
                if raw_value.strip():
                    item[key.strip()] = _parse_scalar(raw_value)
                else:
                    nested, index = _parse_yaml_lines(lines, index, indent + 2)
                    item[key.strip()] = nested
                while index < len(lines) and lines[index][0] > indent:
                    child_indent, child_text = lines[index]
                    if child_indent < indent + 2 or child_text.startswith("- "):
                        break
                    child_key, child_raw = child_text.split(":", 1)
                    index += 1
                    if child_raw.strip():
                        item[child_key.strip()] = _parse_scalar(child_raw)
                    else:
                        nested, index = _parse_yaml_lines(lines, index, child_indent + 2)
                        item[child_key.strip()] = nested
                values.append(item)
            else:
                values.append(_parse_scalar(rest))
        return values, index

    values: dict[str, Any] = {}
    while index < len(lines) and lines[index][0] == indent and not lines[index][1].startswith("- "):
        text = lines[index][1]
        if ":" not in text:
            raise ValueError(f"invalid YAML line: {text}")
        key, raw_value = text.split(":", 1)
        index += 1
        if raw_value.strip():
            values[key.strip()] = _parse_scalar(raw_value)
        else:
            if index < len(lines) and lines[index][0] > indent:
                nested, index = _parse_yaml_lines(lines, index, lines[index][0])
                values[key.strip()] = nested
            else:
                values[key.strip()] = {}
    return values, index


def load_yaml_object(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        prepared: list[tuple[int, str]] = []
        for raw_line in text.splitlines():
            line = _strip_comment(raw_line).rstrip()
            if not line.strip():
                continue
            prepared.append((len(line) - len(line.lstrip(" ")), line.strip()))
        data, index = _parse_yaml_lines(prepared, 0, prepared[0][0] if prepared else 0)
        if index != len(prepared):
            raise ValueError(f"{path} contains unsupported YAML structure")
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def dump_yaml(value: Any, *, indent: int = 0) -> str:
    spaces = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if item == []:
                lines.append(f"{spaces}{key}: []")
                continue
            if item == {}:
                lines.append(f"{spaces}{key}: {{}}")
                continue
            if isinstance(item, dict | list):
                lines.append(f"{spaces}{key}:")
                lines.append(dump_yaml(item, indent=indent + 2))
            else:
                lines.append(f"{spaces}{key}: {_format_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{spaces}[]"
        lines = []
        for item in value:
            if isinstance(item, dict):
                first = True
                for key, nested in item.items():
                    prefix = "- " if first else "  "
                    if nested == []:
                        lines.append(f"{spaces}{prefix}{key}: []")
                        first = False
                        continue
                    if nested == {}:
                        lines.append(f"{spaces}{prefix}{key}: {{}}")
                        first = False
                        continue
                    if isinstance(nested, dict | list):
                        lines.append(f"{spaces}{prefix}{key}:")
                        lines.append(dump_yaml(nested, indent=indent + 4))
                    else:
                        lines.append(f"{spaces}{prefix}{key}: {_format_scalar(nested)}")
                    first = False
            elif isinstance(item, list):
                lines.append(f"{spaces}-")
                lines.append(dump_yaml(item, indent=indent + 2))
            else:
                lines.append(f"{spaces}- {_format_scalar(item)}")
        return "\n".join(lines)
    return f"{spaces}{_format_scalar(value)}"


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    if text == "" or text.strip() != text or any(char in text for char in [":", "#", "[", "]", "{", "}"]):
        return json.dumps(text, ensure_ascii=False)
    return text


def write_yaml_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(payload) + "\n", encoding="utf-8")


def _scan_for_authorization_semantics(value: Any, path: str, findings: list[ProjectFinding]) -> None:
    if path == "$.not_authorized" or path.startswith("$.not_authorized["):
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).lower()
            if any(term in key_text for term in AUTHORIZATION_KEYWORDS):
                add_finding(
                    findings,
                    "ERROR",
                    "E_PROJECT_SCALE_AUTHORIZATION_SEMANTICS",
                    f"PROJECT-SCALE.yaml contains forbidden authorization or gate mutation key: {path}.{key}",
                    key=f"{path}.{key}",
                )
            _scan_for_authorization_semantics(nested, f"{path}.{key}", findings)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_for_authorization_semantics(item, f"{path}[{index}]", findings)
    elif isinstance(value, str):
        lowered = value.lower()
        if any(term in lowered for term in AUTHORIZATION_KEYWORDS):
            add_finding(
                findings,
                "ERROR",
                "E_PROJECT_SCALE_AUTHORIZATION_SEMANTICS",
                f"PROJECT-SCALE.yaml contains forbidden authorization or gate mutation text at {path}",
                key=path,
            )


def _known_gate_profiles(project_root: Path) -> set[str]:
    profiles = gate_profiles.load_gate_profiles(project_root).get("profiles") or {}
    if not isinstance(profiles, dict):
        return set()
    return set(profiles)


def validate_project_scale_payload(
    payload: dict[str, Any],
    *,
    project_root: Path,
) -> tuple[ProjectScale | None, list[ProjectFinding]]:
    findings: list[ProjectFinding] = []
    _scan_for_authorization_semantics(payload, "$", findings)
    if payload.get("schema_version") != PROJECT_SCALE_SCHEMA_VERSION:
        add_finding(findings, "ERROR", "schema_version", f"PROJECT-SCALE.yaml schema_version must be {PROJECT_SCALE_SCHEMA_VERSION}", key="schema_version")
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        add_finding(findings, "ERROR", "missing_required", "PROJECT-SCALE.yaml project_id must be a non-empty string", key="project_id")
    scale_level = payload.get("scale_level")
    if scale_level not in SCALE_LEVELS:
        add_finding(findings, "ERROR", "scale_level", "PROJECT-SCALE.yaml scale_level must be one of: lite, standard, full", key="scale_level")
    scale_reason = payload.get("scale_reason")
    if not isinstance(scale_reason, list) or not scale_reason or not all(isinstance(item, str) and item for item in scale_reason):
        add_finding(findings, "ERROR", "scale_reason", "PROJECT-SCALE.yaml scale_reason must be a non-empty list of strings", key="scale_reason")

    gate_bias = payload.get("gate_profile_bias")
    if not isinstance(gate_bias, dict):
        add_finding(findings, "ERROR", "gate_profile_bias", "PROJECT-SCALE.yaml gate_profile_bias must be an object", key="gate_profile_bias")
        gate_bias = {}
    else:
        default_profile = gate_bias.get("default_profile", "")
        if default_profile not in ("", None):
            if not isinstance(default_profile, str):
                add_finding(findings, "ERROR", "gate_profile_bias.default_profile", "gate_profile_bias.default_profile must be a string or empty", key="gate_profile_bias.default_profile")
            elif default_profile not in _known_gate_profiles(project_root):
                add_finding(findings, "ERROR", "gate_profile_bias.default_profile", f"gate_profile_bias.default_profile is not a known gate profile: {default_profile}", key="gate_profile_bias.default_profile")
        if gate_bias.get("mode") != "recommendation":
            add_finding(findings, "ERROR", "gate_profile_bias.mode", "gate_profile_bias.mode must be recommendation", key="gate_profile_bias.mode")
        if not isinstance(gate_bias.get("reason"), str) or not gate_bias.get("reason"):
            add_finding(findings, "ERROR", "gate_profile_bias.reason", "gate_profile_bias.reason must be a non-empty string", key="gate_profile_bias.reason")

    review_bias = payload.get("review_cadence_bias", {})
    if not isinstance(review_bias, dict):
        add_finding(findings, "ERROR", "review_cadence_bias", "review_cadence_bias must be an object", key="review_cadence_bias")
        review_bias = {}
    elif review_bias and review_bias.get("mode") != "recommendation":
        add_finding(findings, "ERROR", "review_cadence_bias.mode", "review_cadence_bias.mode must be recommendation", key="review_cadence_bias.mode")

    not_authorized = payload.get("not_authorized")
    if not isinstance(not_authorized, list) or not all(isinstance(item, str) and item for item in not_authorized):
        add_finding(findings, "ERROR", "not_authorized", "PROJECT-SCALE.yaml not_authorized must be a non-empty list of strings", key="not_authorized")
        not_authorized_values: set[str] = set()
    else:
        not_authorized_values = set(not_authorized)
        missing = sorted(REQUIRED_NOT_AUTHORIZED - not_authorized_values)
        if missing:
            add_finding(findings, "ERROR", "not_authorized", "PROJECT-SCALE.yaml not_authorized is missing required boundaries: " + ", ".join(missing), key="not_authorized")

    source_refs = payload.get("source_refs", [])
    if source_refs in (None, ""):
        source_refs = []
    if not isinstance(source_refs, list) or not all(isinstance(item, dict) for item in source_refs):
        add_finding(findings, "ERROR", "source_refs", "PROJECT-SCALE.yaml source_refs must be a list of objects", key="source_refs")
        source_refs = []
    updated_at = payload.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at:
        add_finding(findings, "ERROR", "updated_at", "PROJECT-SCALE.yaml updated_at must be a non-empty string", key="updated_at")

    if any(finding.severity == "ERROR" for finding in findings):
        return None, findings
    return (
        ProjectScale(
            project_id=str(project_id),
            scale_level=str(scale_level),
            gate_profile_bias=dict(gate_bias),
            review_cadence_bias=dict(review_bias),
            not_authorized=tuple(not_authorized_values),
            source_refs=tuple(source_refs),
            updated_at=str(updated_at),
        ),
        findings,
    )


def validate_project_scale(project_root: Path, ref: str | Path = PROJECT_SCALE_REL) -> tuple[ProjectScale | None, list[ProjectFinding]]:
    path = project_root.resolve() / ref
    if not path.is_file():
        return None, [ProjectFinding("ERROR", "E_PROJECT_SCALE_MISSING", f"PROJECT-SCALE.yaml missing: {path}")]
    try:
        payload = load_yaml_object(path)
    except (OSError, ValueError) as exc:
        return None, [ProjectFinding("ERROR", "E_PROJECT_SCALE_INVALID", str(exc))]
    return validate_project_scale_payload(payload, project_root=project_root.resolve())
