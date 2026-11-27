"""分层验证记录与版本冻结。"""

from __future__ import annotations

import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import bug
from .state import ledger_append, read_current, refresh_current, write_current
from .workspace import resolve_contract

LAYERS = ("implementation", "design", "requirement")
RESULTS = ("PASS", "PASS_WITH_RISK", "FAIL", "BLOCKED")
RELEASE_STATUSES = {"verified", "released", "deferred", "rejected"}


class VerifyError(Exception):
    """验证/发布操作失败。"""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise VerifyError(f"{path} 不是合法 YAML: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _vr_paths(contract: Path) -> list[Path]:
    return sorted((contract / "verification").glob("VR-*.yaml"))


def _next_vr(contract: Path) -> str:
    numbers = [int(path.stem[3:]) for path in _vr_paths(contract) if path.stem[3:].isdigit()]
    return f"VR-{max(numbers, default=0) + 1:04d}"


def record_verification(
    project: str | Path,
    *,
    layer: str,
    scope: str,
    result: str,
    requirement_refs: list[str] | None = None,
    design_refs: list[str] | None = None,
    task_refs: list[str] | None = None,
    method: str = "artifact",
    evidence: list[str] | None = None,
    bugs: list[str] | None = None,
    verifier: str = "meta-manager",
    notes: str = "",
) -> dict[str, Any]:
    contract = resolve_contract(project)
    if layer not in LAYERS:
        raise VerifyError(f"layer 只能是 {'|'.join(LAYERS)}")
    if result not in RESULTS:
        raise VerifyError(f"result 只能是 {'|'.join(RESULTS)}")
    if not scope.strip():
        raise VerifyError("验证记录必须有 scope")
    if result == "FAIL" and not bugs:
        raise VerifyError("FAIL 验证记录必须关联至少一个 BUG")
    state = read_current(contract)
    vr_id = _next_vr(contract)
    item = {
        "id": vr_id,
        "layer": layer,
        "scope": scope,
        "roadmap": str(state.get("roadmap") or "R1"),
        "phase": str(state.get("phase") or "P1"),
        "requirement_refs": requirement_refs or [],
        "design_refs": design_refs or [],
        "task_refs": task_refs or [],
        "method": method,
        "result": result,
        "evidence": evidence or [],
        "bugs": bugs or [],
        "verifier": verifier,
        "date": _now(),
        "notes": notes,
    }
    path = contract / "verification" / f"{vr_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(item, sort_keys=False, allow_unicode=True), encoding="utf-8")
    for bug_id in bugs or []:
        try:
            current = bug.show_bug(project, bug_id)
            if result in {"PASS", "PASS_WITH_RISK"} and current.get("status") in {
                "open",
                "triaged",
                "in_progress",
                "reopened",
            }:
                bug.update_bug(project, bug_id, status="verifying")
            elif result == "FAIL":
                bug.update_bug(project, bug_id, status="reopened")
        except bug.BugError:
            continue
    ledger_append(contract, {"event": "verify.record", "vr": vr_id, "layer": layer, "result": result})
    return item


def list_verifications(
    project: str | Path,
    *,
    layer: str | None = None,
    result: str | None = None,
    roadmap: str | None = None,
) -> list[dict[str, Any]]:
    contract = resolve_contract(project)
    items = []
    for path in _vr_paths(contract):
        data = _load_yaml(path)
        if layer and data.get("layer") != layer:
            continue
        if result and data.get("result") != result:
            continue
        if roadmap and data.get("roadmap") not in {None, roadmap}:
            continue
        items.append(data)
    return items


def show_verification(project: str | Path, vr_id: str) -> dict[str, Any]:
    for item in list_verifications(project):
        if item.get("id") == vr_id:
            return item
    raise VerifyError(f"验证记录不存在: {vr_id}")


def _requirements(contract: Path) -> list[dict[str, Any]]:
    data = _load_yaml(contract / "requirements" / "REQUIREMENTS.yaml")
    return list(data.get("requirements") or [])


def _tasks(contract: Path, roadmap_id: str) -> list[dict[str, Any]]:
    items = []
    for path in sorted((contract / "roadmap" / roadmap_id).glob("phases/*/tasks/T*/TASK.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


def _bugs(contract: Path) -> list[dict[str, Any]]:
    items = []
    for path in sorted((contract / "bugs").glob("BUG-*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


def open_blocking_bugs(contract: Path) -> list[dict[str, Any]]:
    return [
        bug
        for bug in _bugs(contract)
        if bug.get("status") in {"open", "triaged", "in_progress", "reopened", "verifying"}
        and bug.get("severity") in {"blocker", "critical"}
    ]


def _declared_major(roadmap: dict[str, Any], roadmap_id: str) -> tuple[int, str]:
    """返回路标声明的项目版本 MAJOR 与声明来源。

    优先 ROADMAP.yaml 的 version_major（项目版本策略），其次 version_range
    （如 1.0.x / 1.x）；都没有时回退旧规则 R{n}=MAJOR。显式声明用于
    R0/V1 1.0.x 这类项目映射（D2/MFP-0006）。
    """
    declared = roadmap.get("version_major")
    if declared is not None:
        try:
            return int(declared), "version_major"
        except (TypeError, ValueError):
            pass
    raw_range = str(roadmap.get("version_range") or "").strip()
    match = re.match(r"^(\d+)(?:\.|\b)", raw_range)
    if match:
        return int(match.group(1)), "version_range"
    try:
        return int(str(roadmap_id).lstrip("R")), "roadmap_id"
    except ValueError:
        return 0, "default"


PRE_RELEASE_RE = re.compile(r"^\d+\.\d+\.\d+-[0-9A-Za-z][0-9A-Za-z.+-]*$")


def _is_prerelease(version: str) -> bool:
    """x.y.z-alpha.1 / -rc2 等预发布；+build 元数据不算预发布。"""
    core = str(version).split("+", 1)[0]
    return PRE_RELEASE_RE.fullmatch(core) is not None


def release_stage_policy(phase: str, phase_status: str, version: str) -> str | None:
    """返回阶段门拒绝原因；None 表示允许冻结（standards/VERSION.md §6）。

    - P1/P2：禁止冻结/发布；
    - P3 active：仅允许 alpha/预发布；P3 exited/done：允许正式发布；
    - P4/P5（active/exited/done）：修复/补丁可随时冻结，不要求阶段结束或
      P5 退出（BUG-0016）；
    - done/closed：路标已结束，沿用允许语义。
    阶段门属用户门禁，--force 不可绕过。
    """
    current = str(phase or "P1")
    status = str(phase_status or "")
    if current in {"P1", "P2"}:
        return (
            f"阶段 {current}/{status or 'unknown'} 不允许冻结发布："
            "P1/P2 为规划/设计阶段，发布需等 P3 阶段结束"
        )
    if current == "P3":
        if status in {"exited", "done"}:
            return None
        if _is_prerelease(str(version)):
            return None
        return (
            f"阶段 P3/{status or 'unknown'} 仅允许 alpha/预发布版本冻结："
            f"{version} 不是预发布版本（如 x.y.z-alpha.1）；"
            "正式版本需等 P3 阶段结束（mf phase exit）后再冻结"
        )
    if current in {"P4", "P5", "done", "closed"}:
        return None
    return f"阶段 {current}/{status or 'unknown'} 不允许冻结发布"


PYPROJECT_REL = Path("pyproject.toml")
SOURCE_VERSION_REL = Path("src/meta_flow/__init__.py")
DELIVERY_YAML_REL = Path("delivery.yaml")
RELEASE_NOTES_REL = Path("RELEASE-NOTES.md")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")


def _parse_source_version(text: str) -> str | None:
    """解析源码版本常量 ``__version__ = "x.y.z"``。"""
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return match.group(1) if match else None


def _parse_pyproject_version(text: str) -> str | None:
    """解析 pyproject.toml 的 ``[project].version``。"""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    project = data.get("project") if isinstance(data, dict) else None
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    return str(version) if version is not None else None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, OSError):
        return None


def _version_check(
    name: str,
    path: Path | None,
    expected: str,
    actual: str | None,
    *,
    detail: str = "",
) -> dict[str, Any]:
    ok = actual == expected
    if not ok and not detail:
        detail = "文件缺失或无法解析" if actual is None else f"{actual} ≠ {expected}"
    return {
        "name": name,
        "path": str(path) if path is not None else None,
        "expected": expected,
        "actual": actual,
        "ok": ok,
        "skipped": False,
        "detail": detail,
    }


def _skipped_check(name: str, expected: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "path": None,
        "expected": expected,
        "actual": None,
        "ok": True,
        "skipped": True,
        "detail": detail,
    }


def _git(source: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _is_git_repo(source: Path) -> bool:
    result = _git(source, "rev-parse", "--is-inside-work-tree")
    return result is not None and result.returncode == 0 and result.stdout.strip() == "true"


def _tag_checks(source: Path, version: str, *, require_tag: bool) -> list[dict[str, Any]]:
    """校验 git tag v<version>：存在性（require_tag 时强制）与 tag 内容版本。

    tag 存在但指向的 pyproject/源码常量版本与 version 不一致时失败
    （MFP-0028：v1.0.1 曾指向 0.1.1 的提交）。
    """
    tag = f"v{version}"
    if not _is_git_repo(source):
        return [_skipped_check("git_tag", tag, "非 git 仓库或 git 不可用，跳过 tag 校验")]
    listed = _git(source, "tag", "--list", tag)
    exists = listed is not None and listed.returncode == 0 and listed.stdout.strip() != ""
    if not exists:
        if require_tag:
            return [_version_check("git_tag", source, tag, None, detail=f"git tag {tag} 不存在")]
        return [
            _skipped_check(
                "git_tag",
                tag,
                f"git tag {tag} 不存在（发布时创建；--require-tag 可强制校验）",
            )
        ]
    checks = [_version_check("git_tag", source, tag, tag)]
    for name, relative, parser in (
        ("git_tag_pyproject", PYPROJECT_REL, _parse_pyproject_version),
        ("git_tag_source_version", SOURCE_VERSION_REL, _parse_source_version),
    ):
        shown = _git(source, "show", f"{tag}:{relative.as_posix()}")
        actual = parser(shown.stdout) if shown is not None and shown.returncode == 0 else None
        detail = "" if actual is not None else f"git tag {tag} 中缺少 {relative.as_posix()}"
        checks.append(_version_check(name, source, version, actual, detail=detail))
    return checks


def delivery_version_checks(
    source: Path,
    version: str,
    *,
    require_tag: bool = False,
) -> list[dict[str, Any]]:
    """校验交付库版本单源：pyproject/源码常量/delivery.yaml/RELEASE-NOTES/tag。"""
    checks: list[dict[str, Any]] = []
    for name, relative, parser in (
        ("pyproject", PYPROJECT_REL, _parse_pyproject_version),
        ("source_version", SOURCE_VERSION_REL, _parse_source_version),
    ):
        path = source / relative
        text = _read_text(path)
        actual = parser(text) if text is not None else None
        detail = "" if text is not None else f"{relative.as_posix()} 不存在"
        checks.append(_version_check(name, path, version, actual, detail=detail))
    manifest_path = source / DELIVERY_YAML_REL
    data = _load_yaml(manifest_path)
    actual = str(data.get("version")) if data.get("version") is not None else None
    detail = "" if manifest_path.is_file() else "delivery.yaml 不存在"
    checks.append(_version_check("delivery_yaml", manifest_path, version, actual, detail=detail))
    notes_path = source / RELEASE_NOTES_REL
    notes = _read_text(notes_path)
    if notes is None:
        checks.append(
            _version_check(
                "release_notes", notes_path, version, None, detail="RELEASE-NOTES.md 不存在"
            )
        )
    else:
        pattern = re.compile(rf"^##\s+{re.escape(version)}(?:\s|$|[（(])", re.MULTILINE)
        found = version if pattern.search(notes) else None
        checks.append(
            _version_check(
                "release_notes",
                notes_path,
                version,
                found,
                detail="" if found else f"RELEASE-NOTES.md 缺少 ## {version} 小节",
            )
        )
    checks.extend(_tag_checks(source, version, require_tag=require_tag))
    return checks


def release_manifest_check(contract: Path, version: str) -> dict[str, Any]:
    path = contract / "release" / f"RELEASE-{version}.yaml"
    data = _load_yaml(path)
    actual = str(data.get("project_version")) if data.get("project_version") is not None else None
    detail = "" if path.is_file() else f"发布清单 {path.name} 不存在"
    return _version_check("release_manifest", path, version, actual, detail=detail)


def _resolve_source_dir(source_dir: str | Path | None, contract: Path) -> Path | None:
    """定位交付源码目录：显式参数 > 当前目录 > 契约同级交付库。"""
    if source_dir is not None:
        path = Path(source_dir).expanduser().resolve()
        if not path.is_dir():
            raise VerifyError(f"交付源码目录不存在: {path}")
        return path
    sibling = contract.parent / contract.name.removesuffix("-contract")
    for candidate in (Path.cwd(), sibling):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if (resolved / PYPROJECT_REL).is_file() and (resolved / DELIVERY_YAML_REL).is_file():
            return resolved
    return None


def release_check(
    project: str | Path,
    *,
    version: str | None = None,
    source_dir: str | Path | None = None,
    require_tag: bool = False,
) -> dict[str, Any]:
    """发布一致性校验：发布清单 + 交付库版本单源（MFP-0028）。

    任一处不一致时 ok=False，调用方必须非零退出；不得静默沿用旧版本号。
    """
    contract = resolve_contract(project)
    state = read_current(contract)
    release_info = state.get("release") or {}
    version = str(version or release_info.get("version") or "")
    if not version:
        raise VerifyError("没有可校验的发布版本；用 --version 指定，或先 mf release freeze")
    if VERSION_RE.fullmatch(version) is None:
        raise VerifyError(f"版本必须形如 x.y.z[-pre]: {version}")
    source = _resolve_source_dir(source_dir, contract)
    if source is None:
        raise VerifyError(
            "找不到交付源码目录：用 --source-dir 指定"
            "（版本一致性校验需要 pyproject/源码版本/RELEASE-NOTES/delivery.yaml）"
        )
    checks = [
        release_manifest_check(contract, version),
        *delivery_version_checks(source, version, require_tag=require_tag),
    ]
    errors: list[str] = []
    for item in checks:
        if item["ok"]:
            continue
        if item.get("detail"):
            errors.append(f"{item['name']}：{item['detail']}")
        else:
            errors.append(f"{item['name']}：期望 {item['expected']}，实际 {item.get('actual')}")
    return {
        "version": version,
        "ok": not errors,
        "contract": str(contract),
        "source_dir": str(source),
        "checks": checks,
        "errors": errors,
        "skipped": [item["name"] for item in checks if item.get("skipped")],
    }


def release_freeze(
    project: str | Path,
    *,
    version: str | None = None,
    note: str | None = None,
    force: bool = False,
    reason: str | None = None,
    approved_by: str | None = None,
    source_dir: str | Path | None = None,
) -> dict[str, Any]:
    contract = resolve_contract(project)
    state = read_current(contract)
    roadmap_id = str(state.get("roadmap") or "R1")
    roadmap_data = _load_yaml(contract / "roadmap" / "ROADMAP.yaml")
    roadmap = next(
        (item for item in roadmap_data.get("roadmaps") or [] if item.get("id") == roadmap_id),
        {},
    )
    version = version or str(roadmap.get("version_target") or "0.0.0")
    version_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", str(version))
    if version_match is None:
        raise VerifyError(f"版本必须形如 x.y.z[-pre]: {version}")
    version_major = int(version_match.group(1))
    expected_major, declared_by = _declared_major(roadmap, roadmap_id)
    override: dict[str, Any] | None = None
    if version_major != expected_major:
        if not force:
            raise VerifyError(
                f"路标 {roadmap_id} 声明版本 MAJOR={expected_major}（{declared_by}），"
                f"与版本 {version} 不一致；用 --force --reason ... --approved-by ... 才能冻结"
            )
        if not reason or not approved_by:
            raise VerifyError(
                "MAJOR 不一致的 --force 冻结必须记录 --reason 与 --approved-by（可审计例外）"
            )
        override = {
            "reason": reason,
            "approved_by": approved_by,
            "version": version,
            "roadmap": roadmap_id,
            "expected_major": expected_major,
            "declared_by": declared_by,
            "at": _now(),
        }
    phase = str(state.get("phase") or "P1")
    phase_status = str(state.get("phase_status") or "")
    stage_error = release_stage_policy(phase, phase_status, version)
    if stage_error:
        # 阶段门属用户门禁：--force 只能绕过技术校验，不能绕过阶段策略
        raise VerifyError(stage_error)

    # MFP-0028：冻结前校验交付库版本单源；不一致时失败，不得静默沿用旧版本号。
    # 版本一致性属技术校验，--force 不可绕过。
    source = _resolve_source_dir(source_dir, contract)
    if source is not None:
        failures = [item for item in delivery_version_checks(source, version) if not item["ok"]]
        if failures:
            detail = "；".join(
                f"{item['name']}="
                f"{item['actual'] if item['actual'] is not None else '缺失'}（期望 {item['expected']}）"
                for item in failures
            )
            raise VerifyError(
                f"版本一致性校验失败（MFP-0028）：{detail}；"
                "同步 pyproject/源码版本/RELEASE-NOTES/delivery.yaml 后再冻结"
            )

    requirements = _requirements(contract)
    scoped_reqs = [req for req in requirements if req.get("roadmap") == roadmap_id]
    bad_reqs = [req for req in scoped_reqs if req.get("status") not in RELEASE_STATUSES]
    bugs = _bugs(contract)
    blockers = [
        bug
        for bug in bugs
        if bug.get("status") in {"open", "triaged", "in_progress", "reopened", "verifying"}
        and bug.get("severity") in {"blocker", "critical"}
        and bug.get("roadmap") in {None, roadmap_id}
    ]
    tasks = _tasks(contract, roadmap_id)
    unfinished = [task for task in tasks if task.get("status") not in {"accepted", "cancelled"}]
    errors = []
    if bad_reqs:
        errors.append(f"{len(bad_reqs)} 个需求未达到 verified/released/deferred/rejected")
    if blockers:
        errors.append(f"{len(blockers)} 个 blocker/critical BUG 未关闭")
    if unfinished:
        errors.append(f"{len(unfinished)} 个任务未验收")
    if errors and not force:
        raise VerifyError("；".join(errors) + "；确认后用 --force")

    vr = [
        item
        for item in list_verifications(project)
        if item.get("roadmap") in {None, roadmap_id}
    ]
    scoped_bugs = [
        bug_item
        for bug_item in bugs
        if bug_item.get("roadmap") in {None, roadmap_id}
    ]
    manifest = {
        "schema": 1,
        "project_version": version,
        "roadmap": roadmap_id,
        "roadmap_version_target": roadmap.get("version_target"),
        "stage": {"phase": phase, "phase_status": phase_status},
        "frozen_at": _now(),
        "status": "frozen",
        "published": False,
        "note": note or "冻结不等于发布；发布需另行授权",
        "requirements": [
            {
                "id": req.get("id"),
                "title": req.get("title"),
                "status": req.get("status"),
                "priority": req.get("priority"),
            }
            for req in scoped_reqs
        ],
        "tasks": {
            "total": len(tasks),
            "accepted": len([task for task in tasks if task.get("status") == "accepted"]),
            "unfinished": [task.get("id") for task in unfinished],
        },
        "verification": {
            "total": len(vr),
            "results": {
                result: len([item for item in vr if item.get("result") == result]) for result in RESULTS
            },
            "records": [item.get("id") for item in vr],
        },
        "known_issues": [
            {
                "id": bug.get("id"),
                "severity": bug.get("severity"),
                "status": bug.get("status"),
                "title": bug.get("title"),
            }
            for bug in scoped_bugs
            if bug.get("status") not in {"closed", "wontfix", "deferred"}
        ],
    }
    if override is not None:
        manifest["override"] = override
    path = contract / "release" / f"RELEASE-{version}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    state["release"] = {"version": version, "manifest": str(path.relative_to(contract)), "frozen_at": manifest["frozen_at"]}
    state["release_status"] = "frozen"
    write_current(contract, state)
    refresh_current(contract)
    ledger_append(
        contract,
        {
            "event": "release.freeze",
            "version": version,
            "roadmap": roadmap_id,
            "force": bool(override),
            "override_reason": reason if override else None,
            "approved_by": approved_by if override else None,
        },
    )
    return {
        "version": version,
        "roadmap": roadmap_id,
        "stage": {"phase": phase, "phase_status": phase_status},
        "manifest": str(path),
        "manifest_relative": str(path.relative_to(contract)),
        "published": False,
        "known_issues": len(manifest["known_issues"]),
    }


def show_release(project: str | Path, version: str | None = None) -> dict[str, Any]:
    contract = resolve_contract(project)
    state = read_current(contract)
    if version is None:
        release = state.get("release") or {}
        version = release.get("version")
    if not version:
        raise VerifyError("没有已冻结的发布版本；先运行 mf release freeze")
    release = state.get("release") or {}
    manifest_relative = release.get("manifest")
    path = contract / str(manifest_relative) if manifest_relative else contract / "release" / f"RELEASE-{version}.yaml"
    if not path.is_file():
        path = contract / "release" / f"RELEASE-{version}.yaml"
    if not path.is_file():
        raise VerifyError(f"发布清单不存在: {path}")
    data = _load_yaml(path)
    return data


SECURITY_CARD_SECTIONS = (
    "信任边界",
    "攻击者能力",
    "可证明的 fail_closed 范围",
    "不可防范围（残余风险）",
    "风险接受人",
    "验证证据",
)


def security_card_check(path: str | Path) -> dict[str, Any]:
    """校验安全卡模板/内容（MFP-0041 A1）。

    fail_closed 只写可证明范围；必须写明不可防残余与风险接受人。
    """
    card = Path(path).expanduser()
    if not card.is_file():
        raise VerifyError(f"安全卡不存在: {card}")
    text = card.read_text(encoding="utf-8")
    errors: list[str] = []
    for section in SECURITY_CARD_SECTIONS:
        match = re.search(
            rf"^##\s*{re.escape(section)}\s*$(.*?)(?=^##\s|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if match is None or not match.group(1).strip():
            errors.append(f"缺少或为空: {section}")
    if re.search(r"完全防|不可绕过|100%\s*(防护|安全)|绝对安全", text):
        errors.append("fail_closed 只能写可证明范围，不得声称完全防护/不可绕过")
    if re.search(r"接受人\s*[:：]\s*$", text, re.MULTILINE):
        errors.append("风险接受人不能为空")
    return {"ok": not errors, "path": str(card), "errors": errors}
