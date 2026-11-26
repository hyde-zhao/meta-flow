"""release freeze 阶段策略矩阵（BUG-0016 / R0-P4-T023）。

VERSION.md §6（2026-11-26 用户确认）：
- P1/P2 禁止冻结/发布；
- P3 active 仅允许 alpha/预发布；P3 exited/done 后允许正式发布；
- P4/P5 修复/补丁可随时冻结，不要求阶段结束或 P5 退出。
阶段门属用户门禁：--force 只能绕过技术校验，不能绕过阶段策略。
"""

from __future__ import annotations

import pytest
import yaml

from meta_flow import state, verify
from meta_flow.global_store import bootstrap
from meta_flow.install import install_root
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
