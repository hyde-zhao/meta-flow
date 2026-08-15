"""安装来源 identity 与 component alias 的唯一规范化入口。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from collections.abc import Iterable, Mapping
from hashlib import sha256
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from meta_flow.installation.contracts import (
    COMPONENT_SET_MEMBERS,
    SOURCE_IDENTITY_FIELDS,
    ContractErrorCode,
    InstallationContractError,
    require_exact_keys,
)

_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
PROVIDER_RUNTIME_IDENTITY_KIND = "ProviderRuntimeIdentityV2"
PROVIDER_RUNTIME_IDENTITY_SCHEMA_VERSION = 2
_COMPONENT_EXPANSIONS = {
    "rules": ("rules",),
    "agents": ("agents",),
    "skills": ("skills",),
    "full": COMPONENT_SET_MEMBERS,
    "agent": ("agents", "skills"),
}


def normalize_component(selector: str | Iterable[str]) -> tuple[str, ...]:
    """把 component selector 规范化为有序、唯一的实际 component_set。

    legacy ``agent`` 的唯一语义是 ``agents+skills``，不会产生第五个
    canonical component，也不会降格为仅 ``agents``。
    """

    raw = [selector] if isinstance(selector, str) else list(selector)
    if not raw:
        raise InstallationContractError(
            ContractErrorCode.MISSING_KEY,
            "component selector must not be empty",
        )
    selected: set[str] = set()
    for value in raw:
        if not isinstance(value, str):
            raise InstallationContractError(
                ContractErrorCode.NONCANONICAL_VALUE,
                "component selector values must be strings",
            )
        token = value.strip().lower()
        expansion = _COMPONENT_EXPANSIONS.get(token)
        if expansion is None:
            raise InstallationContractError(
                ContractErrorCode.INVALID_ENUM,
                f"unknown component selector: {token or '-'}",
            )
        selected.update(expansion)
    return tuple(component for component in COMPONENT_SET_MEMBERS if component in selected)


def component_display(selector: str | Iterable[str]) -> str:
    """返回稳定的人类可读 component selection。"""

    return "+".join(normalize_component(selector))


def validate_source_identity(payload: object) -> dict[str, str]:
    """校验并返回 canonical source identity 的独立副本。"""

    identity = require_exact_keys(payload, SOURCE_IDENTITY_FIELDS, field="source_identity")
    normalized = {key: identity[key] for key in SOURCE_IDENTITY_FIELDS}
    for key in ("source", "version"):
        value = normalized[key]
        if not isinstance(value, str) or not value.strip():
            raise InstallationContractError(
                ContractErrorCode.IDENTITY_INCOMPLETE,
                f"source_identity.{key} must be non-empty",
            )
        if value.startswith("/") or "\\" in value or "\x00" in value:
            raise InstallationContractError(
                ContractErrorCode.UNSAFE_PATH,
                f"source_identity.{key} must not contain an absolute workspace path",
            )
        normalized[key] = value.strip()

    oid = normalized["oid"]
    if not isinstance(oid, str) or not _OID_RE.fullmatch(oid.lower()):
        raise InstallationContractError(
            ContractErrorCode.IDENTITY_INCOMPLETE,
            "source_identity.oid must be one full 40-hex OID",
        )
    normalized["oid"] = oid.lower()
    for key in ("delivery_tree_digest", "rules_source_digest", "inventory_digest"):
        digest = normalized[key]
        if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest.lower()):
            raise InstallationContractError(
                ContractErrorCode.IDENTITY_INCOMPLETE,
                f"source_identity.{key} must be one 64-hex digest",
            )
        normalized[key] = digest.lower()
    return normalized


def source_identity_conflicts(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> tuple[dict[str, str], ...]:
    """返回 expected/observed source identity 的稳定字段级冲突。"""

    expected_identity = validate_source_identity(expected)
    observed_identity = validate_source_identity(observed)
    return tuple(
        {
            "code": ContractErrorCode.IDENTITY_CONFLICT.value,
            "field": field,
            "expected": expected_identity[field],
            "actual": observed_identity[field],
        }
        for field in SOURCE_IDENTITY_FIELDS
        if expected_identity[field] != observed_identity[field]
    )


def resolve_source_identity(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """解析 exact source identity；任一 drift 都 fail-closed。"""

    identity = validate_source_identity(expected)
    if observed is None:
        return identity
    conflicts = source_identity_conflicts(identity, observed)
    if conflicts:
        fields = [conflict["field"] for conflict in conflicts]
        raise InstallationContractError(
            ContractErrorCode.IDENTITY_CONFLICT,
            f"source identity conflicts at fields: {fields}",
        )
    return identity


def observe_checkout_source_identity(repo_root: Path) -> dict[str, str]:
    """从一个 source checkout 产生 exact OID/tree/rules/inventory identity。

    文件树 digest 覆盖当前 delivery bytes，因此即使工作树含未提交候选，
    diagnostics 也不会把 HEAD OID 单独冒充为完整来源身份。
    """

    root = repo_root.resolve()
    delivery = root / "delivery"
    if not delivery.is_dir():
        raise ValueError("source checkout has no delivery directory")
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    oid = completed.stdout.strip().lower()
    files = sorted(
        path
        for path in delivery.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    tree_records = {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    from meta_flow.installation.canonical import canonical_digest

    pyproject = root / "pyproject.toml"
    if not pyproject.is_file() or pyproject.is_symlink():
        raise ValueError("source checkout has no regular pyproject.toml")
    project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project")
    version = project.get("version") if isinstance(project, Mapping) else None
    if not isinstance(version, str) or not version:
        raise ValueError("source checkout project version is missing")
    rules = delivery / "rules" / "AGENTS.md"
    inventory = delivery / "doc" / "RULES-SEMANTIC-INVENTORY.json"
    if not rules.is_file() or not inventory.is_file():
        raise ValueError("source checkout has incomplete rules identity")
    return validate_source_identity(
        {
            "source": "checkout/meta-flow",
            "version": version,
            "oid": oid,
            "delivery_tree_digest": canonical_digest(tree_records),
            "rules_source_digest": sha256(rules.read_bytes()).hexdigest(),
            "inventory_digest": sha256(inventory.read_bytes()).hexdigest(),
        }
    )


def observe_checkout_delivery_status(repo_root: Path) -> dict[str, bool]:
    """区分可识别 checkout 与可由 HEAD 精确复现的 immutable delivery。"""

    root = repo_root.resolve()
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError("source checkout worktree status is unavailable")
    worktree_clean = not completed.stdout.strip()
    return {
        "worktree_clean": worktree_clean,
        "exact_commit_delivery": worktree_clean,
    }


def _canonical_digest(payload: object) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(rendered.encode("utf-8")).hexdigest()


def _git_root(path: Path) -> Path | None:
    current = path.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _package_checkout_root(imported_path: Path) -> Path | None:
    """仅当 imported module 本身属于源码树时返回 Git root。

    一个安装在 ``<repo>/.venv`` 中的普通 wheel 不因祖先目录存在 ``.git``
    而自动变成 editable checkout。
    """

    root = _git_root(imported_path)
    if root is None:
        return None
    expected = (root / "meta_flow" / "__init__.py").resolve()
    return root if expected == imported_path.resolve() else None


def _is_generated_distribution_file(relative: Path) -> bool:
    rendered = relative.as_posix()
    if "__pycache__" in relative.parts or relative.suffix == ".pyc":
        return True
    if ".dist-info/" not in rendered:
        return False
    return relative.name in {
        "INSTALLER",
        "RECORD",
        "REQUESTED",
        "direct_url.json",
        "uv_cache.json",
    }


def _direct_url_payload(distribution: metadata.Distribution) -> dict[str, Any]:
    raw = distribution.read_text("direct_url.json")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"_error": "DIRECT_URL_INVALID"}
    return payload if isinstance(payload, dict) else {"_error": "DIRECT_URL_INVALID"}


def _file_url_path(value: object) -> Path | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path)).resolve()


def _archive_sha256(payload: Mapping[str, Any]) -> str | None:
    archive = payload.get("archive_info")
    if not isinstance(archive, Mapping):
        return None
    raw_hash = archive.get("hash")
    candidates: list[object] = [raw_hash]
    hashes = archive.get("hashes")
    if isinstance(hashes, Mapping):
        candidates.append(hashes.get("sha256"))
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        value = candidate.removeprefix("sha256=").lower()
        if _DIGEST_RE.fullmatch(value):
            return value
    return None


def _installed_files_digest(
    distribution: metadata.Distribution,
    distribution_root: Path,
) -> str | None:
    records: dict[str, str] = {}
    for item in distribution.files or ():
        relative = Path(str(item))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or _is_generated_distribution_file(relative)
        ):
            continue
        candidate = (distribution_root / relative).resolve()
        try:
            candidate.relative_to(distribution_root)
        except ValueError:
            continue
        if not candidate.is_file() or candidate.is_symlink():
            continue
        records[relative.as_posix()] = sha256(candidate.read_bytes()).hexdigest()
    return _canonical_digest(records) if records else None


def _capability_profile_digest(root: Path) -> str | None:
    contract = root / "delivery" / "doc" / "PUBLIC-OPERATION-CONTRACTS.yaml"
    if not contract.is_file() or contract.is_symlink():
        return None
    return sha256(contract.read_bytes()).hexdigest()


def _schema_versions() -> dict[str, int]:
    return {
        "installation_plan": 2,
        "legacy_evidence_registry": 1,
        "phase_metadata": 1,
        "phase_transition": 1,
        "provider_runtime_identity": PROVIDER_RUNTIME_IDENTITY_SCHEMA_VERSION,
        "work_publication_receipt": 2,
    }


def observe_provider_runtime_identity(
    *,
    distribution_name: str = "meta-flow",
    module_path: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """观察当前实际导入 provider 的运行时身份。

    身份来源固定为已导入模块、distribution metadata 和显式
    ``META_FLOW_SOURCE``；普通当前工作目录从不参与 provider 归属判断。
    """

    from meta_flow import __file__ as imported_module_file

    env = dict(os.environ if environment is None else environment)
    imported_path = Path(module_path or imported_module_file).resolve()
    findings: list[str] = []
    try:
        distribution = metadata.distribution(distribution_name)
        distribution_version = distribution.version
        direct_url = _direct_url_payload(distribution)
    except metadata.PackageNotFoundError:
        distribution = None
        distribution_version = ""
        direct_url = {}
        findings.append("DISTRIBUTION_NOT_FOUND")

    distribution_root = imported_path.parent.parent
    editable = False
    source_root: Path | None = None
    identity_source = "installed-artifact"
    direct_url_root = _file_url_path(direct_url.get("url"))
    dir_info = direct_url.get("dir_info")
    if isinstance(dir_info, Mapping) and dir_info.get("editable") is True:
        if (
            direct_url_root is None
            or (direct_url_root / "meta_flow" / "__init__.py").resolve()
            != imported_path
        ):
            findings.append("DIRECT_URL_EDITABLE_MODULE_MISMATCH")
        else:
            editable = True
            identity_source = "editable-checkout"
            source_root = direct_url_root

    explicit_source = env.get("META_FLOW_SOURCE", "").strip()
    if explicit_source:
        explicit_root = Path(explicit_source).expanduser().resolve()
        expected_module = (explicit_root / "meta_flow" / "__init__.py").resolve()
        if expected_module != imported_path:
            findings.append("EXPLICIT_SOURCE_MODULE_MISMATCH")
        else:
            source_root = explicit_root
            editable = True
            identity_source = "explicit-development-source"

    checkout_root = _package_checkout_root(imported_path)
    if source_root is None and checkout_root is not None:
        source_root = checkout_root
        editable = True
        identity_source = "editable-checkout"
    if source_root is not None:
        distribution_root = source_root

    source_commit: str | None = None
    source_dirty: bool | None = None
    source_tree_digest: str | None = None
    worktree_clean: bool | None = None
    if source_root is not None:
        try:
            checkout_identity = observe_checkout_source_identity(source_root)
            checkout_status = observe_checkout_delivery_status(source_root)
        except (OSError, ValueError, subprocess.SubprocessError):
            findings.append("CHECKOUT_IDENTITY_INCOMPLETE")
        else:
            source_commit = checkout_identity["oid"]
            source_tree_digest = checkout_identity["delivery_tree_digest"]
            worktree_clean = checkout_status["worktree_clean"]
            source_dirty = not worktree_clean

    artifact_sha256 = _archive_sha256(direct_url)
    installed_files_digest = (
        _installed_files_digest(distribution, distribution_root)
        if distribution is not None
        else None
    )
    capability_profile_digest = _capability_profile_digest(distribution_root)
    if direct_url.get("_error"):
        findings.append(str(direct_url["_error"]))
    if capability_profile_digest is None:
        findings.append("CAPABILITY_PROFILE_MISSING")

    provider_receipt_path: str | None = None
    provider_receipt_digest: str | None = None
    receipt_reasons: list[str] = []
    receipt_path_raw = env.get("META_FLOW_PROVIDER_RECEIPT", "").strip()
    if receipt_path_raw:
        from meta_flow.installation.artifact import (
            artifact_receipt_conflicts,
            load_provider_artifact_receipt,
        )

        try:
            receipt_path = Path(receipt_path_raw).expanduser().resolve()
            receipt = load_provider_artifact_receipt(receipt_path)
        except (OSError, ValueError, json.JSONDecodeError):
            receipt_reasons.append("PROVIDER_RECEIPT_INVALID")
        else:
            provider_receipt_path = str(receipt_path)
            provider_receipt_digest = str(receipt["receipt_digest"])
            receipt_reasons.extend(
                artifact_receipt_conflicts(
                    receipt,
                    {
                        "distribution_name": distribution_name,
                        "distribution_version": distribution_version,
                        "artifact_sha256": artifact_sha256,
                        "capability_profile_digest": capability_profile_digest,
                        "installed_payload_digest": installed_files_digest,
                    },
                )
            )
            if not receipt_reasons and source_root is None:
                source_commit = str(receipt["source_commit"])
                source_tree_digest = str(receipt["source_tree_digest"])
                if artifact_sha256 is None:
                    artifact_sha256 = str(receipt["artifact_sha256"])
                    identity_source = "installed-artifact-receipt"
    else:
        receipt_reasons.append("PROVIDER_RECEIPT_MISSING")

    source_discovery_reasons = sorted(set(findings))
    source_discovery = {
        "decision": "PASS" if not source_discovery_reasons else "BLOCKED",
        "reason_codes": source_discovery_reasons,
    }
    release_reasons: list[str] = []
    if editable:
        release_reasons.append("EDITABLE_INSTALL")
    if source_dirty:
        release_reasons.append("SOURCE_DIRTY")
    if artifact_sha256 is None:
        release_reasons.append("ARTIFACT_SHA256_MISSING")
    if not editable and installed_files_digest is None:
        release_reasons.append("INSTALLED_FILES_DIGEST_MISSING")
    if capability_profile_digest is None:
        release_reasons.append("CAPABILITY_PROFILE_MISSING")
    release_reasons.extend(receipt_reasons)
    release_reasons.extend(source_discovery_reasons)
    release_reasons = sorted(set(release_reasons))
    release_readiness = {
        "decision": "PASS" if not release_reasons else "BLOCKED",
        "reason_codes": release_reasons,
    }

    payload: dict[str, Any] = {
        "schema_version": PROVIDER_RUNTIME_IDENTITY_SCHEMA_VERSION,
        "kind": PROVIDER_RUNTIME_IDENTITY_KIND,
        "distribution_name": distribution_name,
        "distribution_version": distribution_version,
        "module_path": str(imported_path),
        "distribution_path": str(distribution_root),
        "editable": editable,
        "identity_source": identity_source,
        "source_root": str(source_root) if source_root is not None else None,
        "source_commit": source_commit,
        "source_dirty": source_dirty,
        "source_tree_digest": source_tree_digest,
        "artifact_sha256": artifact_sha256,
        "installed_files_digest": installed_files_digest,
        "capability_profile_digest": capability_profile_digest,
        "provider_receipt_path": provider_receipt_path,
        "provider_receipt_digest": provider_receipt_digest,
        "schema_versions": _schema_versions(),
        "source_discovery": source_discovery,
        "release_readiness": release_readiness,
        "worktree_clean": worktree_clean,
        "exact_commit_delivery": release_readiness["decision"] == "PASS",
    }
    payload["identity_digest"] = _canonical_digest(payload)
    return payload


def evaluate_provider_runtime_admission(
    identity: Mapping[str, Any],
    *,
    mode: str,
    expected_identity_digest: str | None = None,
) -> dict[str, Any]:
    """按 development/release profile 评估 provider mutation 准入。"""

    if mode not in {"development", "release"}:
        raise ValueError("provider mode must be development or release")
    actual_digest = identity.get("identity_digest")
    reasons: list[str] = []
    if not isinstance(actual_digest, str) or not _DIGEST_RE.fullmatch(actual_digest):
        reasons.append("PROVIDER_IDENTITY_INVALID")
    if expected_identity_digest is not None and expected_identity_digest != actual_digest:
        reasons.append("PROVIDER_IDENTITY_DRIFT")
    if mode == "release":
        readiness = identity.get("release_readiness")
        if not isinstance(readiness, Mapping) or readiness.get("decision") != "PASS":
            reasons.extend(
                str(item)
                for item in (
                    readiness.get("reason_codes", [])
                    if isinstance(readiness, Mapping)
                    else ["RELEASE_READINESS_MISSING"]
                )
            )
    reasons = sorted(set(reasons))
    payload = {
        "schema_version": 1,
        "kind": "ProviderRuntimeAdmissionV1",
        "mode": mode,
        "decision": "READY" if not reasons else "BLOCKED",
        "reason_codes": reasons,
        "provider_identity_digest": actual_digest,
        "release_qualifying": mode == "release" and not reasons,
    }
    payload["admission_digest"] = _canonical_digest(payload)
    return payload


__all__ = [
    "component_display",
    "normalize_component",
    "observe_checkout_delivery_status",
    "observe_checkout_source_identity",
    "observe_provider_runtime_identity",
    "evaluate_provider_runtime_admission",
    "PROVIDER_RUNTIME_IDENTITY_KIND",
    "PROVIDER_RUNTIME_IDENTITY_SCHEMA_VERSION",
    "resolve_source_identity",
    "source_identity_conflicts",
    "validate_source_identity",
]
