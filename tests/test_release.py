"""release freeze 阶段策略矩阵（BUG-0016 / R0-P4-T023）。

VERSION.md §6（2026-11-26 用户确认）：
- P1/P2 禁止冻结/发布；
- P3 active 仅允许 alpha/预发布；P3 exited/done 后允许正式发布；
- P4/P5 修复/补丁可随时冻结，不要求阶段结束或 P5 退出。
阶段门属用户门禁：--force 只能绕过技术校验，不能绕过阶段策略。

MFP-0028：pyproject/源码常量/RELEASE-NOTES/delivery.yaml/release 清单/tag
必须版本一致；release freeze/check 不一致时失败，不得静默沿用旧版本号。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from meta_flow import __version__, state, verify
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root, upgrade_project
from meta_flow.workspace import workspace_init


@pytest.fixture()
def env(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo")
    return root, root / "demo-contract"


def _set_stage(contract, *, phase, phase_status="active"):
    current = state.read_current(contract)
    current.update({"phase": phase, "phase_status": phase_status})
    state.write_current(contract, current)


@pytest.mark.parametrize("phase", ["P1", "P2"])
def test_release_rejected_for_planning_and_design(env, phase):
    root, contract = env
    _set_stage(contract, phase=phase)
    with pytest.raises(verify.VerifyError, match="不允许冻结发布"):
        verify.release_freeze(root, version="1.0.0")


@pytest.mark.parametrize("phase", ["P1", "P2"])
def test_force_cannot_bypass_stage_gate(env, phase):
    root, contract = env
    _set_stage(contract, phase=phase)
    with pytest.raises(verify.VerifyError, match="不允许冻结发布"):
        verify.release_freeze(
            root, version="1.0.0", force=True, reason="尝试绕过", approved_by="user"
        )


def test_p3_active_rejects_formal_version_even_with_force(env):
    root, contract = env
    _set_stage(contract, phase="P3", phase_status="active")
    with pytest.raises(verify.VerifyError, match="仅允许 alpha/预发布"):
        verify.release_freeze(root, version="1.0.0")
    # +build 元数据不等于预发布（正式版本）
    with pytest.raises(verify.VerifyError, match="仅允许 alpha/预发布"):
        verify.release_freeze(root, version="1.0.0+build.1")
    with pytest.raises(verify.VerifyError, match="仅允许 alpha/预发布"):
        verify.release_freeze(
            root, version="1.0.0", force=True, reason="尝试绕过", approved_by="user"
        )


def test_p3_active_allows_prerelease(env):
    root, contract = env
    _set_stage(contract, phase="P3", phase_status="active")
    result = verify.release_freeze(root, version="1.0.0-alpha.1")
    assert result["version"] == "1.0.0-alpha.1"
    assert result["stage"] == {"phase": "P3", "phase_status": "active"}
    assert result["published"] is False
    manifest = yaml.safe_load(
        (contract / "release" / "RELEASE-1.0.0-alpha.1.yaml").read_text(encoding="utf-8")
    )
    assert manifest["stage"] == {"phase": "P3", "phase_status": "active"}


@pytest.mark.parametrize("status", ["exited", "done"])
def test_p3_completed_allows_formal_release(env, status):
    root, contract = env
    _set_stage(contract, phase="P3", phase_status=status)
    result = verify.release_freeze(root, version="1.0.0")
    assert result["version"] == "1.0.0"


@pytest.mark.parametrize("phase", ["P4", "P5"])
@pytest.mark.parametrize("status", ["active", "exited", "done"])
def test_p4_p5_patch_release_allowed(env, phase, status):
    root, contract = env
    _set_stage(contract, phase=phase, phase_status=status)
    result = verify.release_freeze(root, version="1.0.1", note="P4/P5 patch")
    assert result["version"] == "1.0.1"
    assert result["stage"] == {"phase": phase, "phase_status": status}
    manifest = yaml.safe_load(
        (contract / "release" / "RELEASE-1.0.1.yaml").read_text(encoding="utf-8")
    )
    assert manifest["stage"] == {"phase": phase, "phase_status": status}
    assert manifest["note"] == "P4/P5 patch"
    assert manifest["published"] is False


def test_p4_patch_release_keeps_version_policy(env):
    root, contract = env
    _set_stage(contract, phase="P4", phase_status="active")
    with pytest.raises(verify.VerifyError, match="MAJOR"):
        verify.release_freeze(root, version="2.0.0")
    with pytest.raises(verify.VerifyError, match="--reason"):
        verify.release_freeze(root, version="2.0.0", force=True)
    forced = verify.release_freeze(
        root,
        version="2.0.0",
        force=True,
        reason="用户批准的例外",
        approved_by="product-owner",
    )
    assert forced["version"] == "2.0.0"
    manifest = yaml.safe_load(
        (contract / "release" / "RELEASE-2.0.0.yaml").read_text(encoding="utf-8")
    )
    assert manifest["override"]["reason"] == "用户批准的例外"
    assert manifest["override"]["approved_by"] == "product-owner"


# --- MFP-0028：版本单源与发布一致性校验 ---


def _make_delivery(
    path: Path,
    version: str,
    *,
    pyproject: str | None = None,
    source_version: str | None = None,
    delivery_version: str | None = None,
    notes_version: str | None = None,
) -> Path:
    """构造交付库版本元数据（模拟 meta-flow 布局）。"""
    src = path / "src" / "meta_flow"
    src.mkdir(parents=True, exist_ok=True)
    (src / "__init__.py").write_text(
        f'__version__ = "{source_version or version}"\n', encoding="utf-8"
    )
    (path / "pyproject.toml").write_text(
        f'[project]\nname = "meta-flow"\nversion = "{pyproject or version}"\n',
        encoding="utf-8",
    )
    (path / "delivery.yaml").write_text(
        yaml.safe_dump(
            {"id": "meta-flow", "version": delivery_version or version},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (path / "RELEASE-NOTES.md").write_text(
        f"# 发布说明\n\n## {notes_version or version}（测试发布）\n", encoding="utf-8"
    )
    return path


def _git_init_with_commit(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "release"], check=True, capture_output=True
    )


def _freeze(env, version: str = "1.0.1"):
    root, contract = env
    _set_stage(contract, phase="P4")
    verify.release_freeze(root, version=version)
    return root, contract


def test_repository_version_single_source():
    """MFP-0028 防复发：交付仓自身 pyproject/源码常量/RELEASE-NOTES/delivery.yaml 一致。"""
    repo = Path(__file__).resolve().parents[1]
    pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
    source = (repo / "src" / "meta_flow" / "__init__.py").read_text(encoding="utf-8")
    notes = (repo / "RELEASE-NOTES.md").read_text(encoding="utf-8")
    delivery = yaml.safe_load((repo / "delivery.yaml").read_text(encoding="utf-8"))
    assert verify._parse_pyproject_version(pyproject) == __version__
    assert verify._parse_source_version(source) == __version__
    assert str(delivery["version"]) == __version__
    assert re.search(rf"^##\s+{re.escape(__version__)}", notes, re.MULTILINE)


def test_install_manifest_tool_version_sync(env):
    """A4：安装后 install.yaml 的 tool_version 与源码版本一致。"""
    root, _contract = env
    manifest = yaml.safe_load((root / ".meta-flow" / "install.yaml").read_text(encoding="utf-8"))
    assert manifest["tool_version"] == __version__


def test_upgrade_syncs_tool_version(env):
    """A4：升级后 install.yaml 的 tool_version 重新同步到当前源码版本。"""
    root, _contract = env
    path = root / ".meta-flow" / "install.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["tool_version"] = "0.0.0"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    upgrade_project(root)
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert manifest["tool_version"] == __version__


def test_release_check_passes_when_sources_consistent(env, tmp_path):
    root, _contract = _freeze(env)
    delivery = _make_delivery(tmp_path / "delivery", "1.0.1")
    result = verify.release_check(root, version="1.0.1", source_dir=delivery)
    assert result["ok"] is True, result["errors"]
    names = {item["name"] for item in result["checks"]}
    assert {
        "release_manifest",
        "pyproject",
        "source_version",
        "delivery_yaml",
        "release_notes",
        "git_tag",
    } <= names


def test_release_check_skips_missing_tag_without_require_tag(env, tmp_path):
    root, _contract = _freeze(env)
    delivery = _make_delivery(tmp_path / "delivery", "1.0.1")
    result = verify.release_check(root, version="1.0.1", source_dir=delivery)
    tag = next(item for item in result["checks"] if item["name"] == "git_tag")
    assert tag["skipped"] is True


@pytest.mark.parametrize(
    ("field", "check_name"),
    [
        ("pyproject", "pyproject"),
        ("source_version", "source_version"),
        ("delivery_version", "delivery_yaml"),
        ("notes_version", "release_notes"),
    ],
)
def test_release_check_detects_version_drift(env, tmp_path, field, check_name):
    """任一处版本不一致（MFP-0028）时必须失败，不能静默。"""
    root, _contract = _freeze(env)
    delivery = _make_delivery(tmp_path / "delivery", "1.0.1", **{field: "0.1.1"})
    result = verify.release_check(root, version="1.0.1", source_dir=delivery)
    assert result["ok"] is False
    failed = {item["name"] for item in result["checks"] if not item["ok"]}
    assert check_name in failed
    assert result["errors"]


def test_release_check_requires_release_manifest(env, tmp_path):
    root, contract = env
    _set_stage(contract, phase="P4")
    delivery = _make_delivery(tmp_path / "delivery", "1.0.1")
    result = verify.release_check(root, version="1.0.1", source_dir=delivery)
    assert result["ok"] is False
    failed = {item["name"] for item in result["checks"] if not item["ok"]}
    assert "release_manifest" in failed


def test_release_freeze_rejects_version_mismatch(env, tmp_path):
    """冻结前校验交付版本单源；不一致时不写清单（MFP-0028）。"""
    root, contract = env
    _set_stage(contract, phase="P4")
    delivery = _make_delivery(tmp_path / "delivery", "1.0.1", source_version="0.1.1")
    with pytest.raises(verify.VerifyError, match="版本一致性校验失败"):
        verify.release_freeze(root, version="1.0.1", source_dir=delivery)
    assert not (contract / "release" / "RELEASE-1.0.1.yaml").exists()


def test_release_freeze_accepts_consistent_delivery(env, tmp_path):
    root, _contract = env
    _set_stage(_contract, phase="P4")
    delivery = _make_delivery(tmp_path / "delivery", "1.0.1")
    result = verify.release_freeze(root, version="1.0.1", source_dir=delivery)
    assert result["version"] == "1.0.1"


def test_release_check_require_tag(env, tmp_path):
    root, _contract = _freeze(env)
    delivery = _make_delivery(tmp_path / "delivery", "1.0.1")
    _git_init_with_commit(delivery)
    result = verify.release_check(root, version="1.0.1", source_dir=delivery, require_tag=True)
    assert result["ok"] is False
    failed = {item["name"] for item in result["checks"] if not item["ok"]}
    assert "git_tag" in failed
    subprocess.run(["git", "-C", str(delivery), "tag", "v1.0.1"], check=True)
    result = verify.release_check(root, version="1.0.1", source_dir=delivery, require_tag=True)
    assert result["ok"] is True, result["errors"]


def test_release_check_detects_wrong_tag_content(env, tmp_path):
    """v1.0.1 tag 指向 0.1.1 的提交（MFP-0028 实际场景）时必须失败。"""
    root, _contract = _freeze(env)
    delivery = _make_delivery(tmp_path / "delivery", "1.0.1", source_version="0.1.1")
    _git_init_with_commit(delivery)
    subprocess.run(["git", "-C", str(delivery), "tag", "v1.0.1"], check=True)
    # 工作区修复源码版本，但 tag 仍指向旧提交
    (delivery / "src" / "meta_flow" / "__init__.py").write_text(
        '__version__ = "1.0.1"\n', encoding="utf-8"
    )
    result = verify.release_check(root, version="1.0.1", source_dir=delivery, require_tag=True)
    assert result["ok"] is False
    failed = {item["name"] for item in result["checks"] if not item["ok"]}
    assert "git_tag_source_version" in failed
