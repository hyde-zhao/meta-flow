"""MFP 改进包测试。"""

from __future__ import annotations

import pytest
import yaml

from meta_flow.global_store import bootstrap
from meta_flow.improve import (
    import_improvement,
    list_improvements,
    new_improvement,
    source_import,
    source_list,
    source_update,
    submit_improvement,
    validate_improvement,
)
from meta_flow.install import install_root, install_worker
from meta_flow.workspace import workspace_init


@pytest.fixture()
def mfp_env(tmp_path, monkeypatch):
    home = tmp_path / "global"
    monkeypatch.setenv("META_FLOW_HOME", str(home))
    bootstrap()
    root = tmp_path / "demo"
    root.mkdir()
    install_root(root)
    workspace_init(root, "Demo")
    return {"root": root, "contract": root / "demo-contract", "home": home, "tmp": tmp_path}


def _fill(path, **overrides):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.update(
        {
            "problem": "CLI 缺少 X 命令，阻塞任务推进",
            "context": {
                "scenario": "worker 需要 X",
                "reproduction": ["运行 mf X", "得到 invalid choice"],
                "expected": "mf X 正常执行",
                "actual": "invalid choice",
                "evidence": [{"path": "logs/mf-X.log", "note": "命令输出"}],
                "affected": ["cli"],
            },
            "acceptance": [
                {
                    "id": "A1",
                    "method": "automated",
                    "command": "mf X --help",
                    "expect": "exit_code=0",
                }
            ],
            "testing_plan": "uv run pytest tests/test_cli.py",
            "privacy": {"sanitized": True, "removed": []},
        }
    )
    data.update(overrides)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return data


def _source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='meta-flow'\n", encoding="utf-8")
    return source


def test_new_validate_submit(mfp_env):
    root = mfp_env["root"]
    path = new_improvement(root, "增加 X 命令")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["id"] == "MFP-0001"
    assert data["status"] == "draft"
    assert validate_improvement(data)

    data = _fill(path)
    assert validate_improvement(data) == []

    inbox = submit_improvement(root, "MFP-0001")
    assert inbox.is_file()
    submitted = yaml.safe_load(inbox.read_text(encoding="utf-8"))
    assert submitted["status"] == "submitted"


def test_worker_local_import(mfp_env):
    root = mfp_env["root"]
    sub = root / "frontend"
    install_worker(sub, "frontend", workspace_root=root)
    local = new_improvement(sub, "worker 发现工具缺口", local=True)
    _fill(local)
    assert list_improvements(sub, scope="local")
    target = import_improvement(root, local)
    assert target.is_file()
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert data["imported_from"] == str(local)


def test_source_import_already_implemented(mfp_env, tmp_path):
    root = mfp_env["root"]
    path = new_improvement(root, "已实现的缺陷")
    _fill(path)
    submit_improvement(root, "MFP-0001")
    source = _source(tmp_path)
    result = source_import(
        "demo/MFP-0001",
        source=source,
        kind="bug",
        already_implemented=True,
        version="0.1.1",
        commit="abc123",
        note="already done",
    )
    assert result["classification"] == "bug"
    assert result["record"] == "BUG-0001"
    assert (source / "improvements" / "closed" / "MFP-0001.yaml").is_file()
    record = yaml.safe_load(
        (source / "improvements" / "records" / "BUG-0001.yaml").read_text(encoding="utf-8")
    )
    assert record["status"] == "done"


def test_source_import_open_and_update(mfp_env, tmp_path):
    root = mfp_env["root"]
    path = new_improvement(root, "新增能力")
    _fill(path)
    submit_improvement(root, "MFP-0001")
    source = _source(tmp_path)
    result = source_import("demo/MFP-0001", source=source, kind="requirement")
    assert result["record"] == "REQ-0001"
    assert (source / "improvements" / "open" / "MFP-0001.yaml").is_file()
    items = source_list(source=source, scope="open")
    assert items["open"][0]["status"] == "accepted"

    path = source_update(
        "MFP-0001",
        "verified",
        source=source,
        version="0.1.2",
        commit="def456",
        note="tested",
    )
    assert path.parent.name == "closed"
    record = yaml.safe_load(
        (source / "improvements" / "records" / "REQ-0001.yaml").read_text(encoding="utf-8")
    )
    assert record["status"] == "done"


def test_sensitive_info_rejected(mfp_env):
    root = mfp_env["root"]
    path = new_improvement(root, "敏感信息")
    data = _fill(path, problem="token=abc123")
    errors = validate_improvement(data)
    assert any("敏感信息" in error for error in errors)
