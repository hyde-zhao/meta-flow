"""MFP 改进包测试。"""

from __future__ import annotations

import pytest
import yaml

from meta_flow.global_store import bootstrap
from meta_flow.improve import (
    ImproveError,
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


# ---------------------------------------------------------------- N14 路径穿越（T010）


def _package(root, **overrides):
    path = new_improvement(root, "路径校验包")
    return _fill(path, **overrides)


def _write_inbox(home, data, *, name="MFP-0001", project="demo"):
    inbox = home / "improvements" / "inbox" / project
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{name}.yaml"
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return path


@pytest.mark.parametrize(
    "bad_id",
    ["../../escaped", "/tmp/x", "a/b", "a\\b", "..", ".", "", "MFP-0001/../../x"],
)
def test_source_import_rejects_unsafe_content_id(mfp_env, tmp_path, bad_id):
    data = _package(mfp_env["root"], id=bad_id)
    _write_inbox(mfp_env["home"], data)
    source = _source(tmp_path)
    with pytest.raises(ImproveError):
        source_import("demo/MFP-0001", source=source, kind="requirement")
    assert not [p for p in tmp_path.rglob("escaped*") if p.is_file()]


@pytest.mark.parametrize(
    "ref",
    ["../etc/passwd", "demo/../../x", "/tmp/MFP-0001", "demo/..%2f", "demo/../MFP-0001"],
)
def test_source_import_rejects_unsafe_ref(mfp_env, tmp_path, ref):
    source = _source(tmp_path)
    with pytest.raises(ImproveError):
        source_import(ref, source=source, kind="requirement")


def test_source_import_rejects_symlink_escape(mfp_env, tmp_path):
    data = _package(mfp_env["root"])
    _write_inbox(mfp_env["home"], data)
    source = _source(tmp_path)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (source / "improvements").mkdir()
    (source / "improvements" / "open").symlink_to(outside_dir)
    with pytest.raises(ImproveError):
        source_import("demo/MFP-0001", source=source, kind="requirement")
    assert list(outside_dir.iterdir()) == []

    # 目标文件为符号链接同样拒绝，且不覆盖链接目标
    (source / "improvements" / "open").unlink()
    (source / "improvements" / "open").mkdir()
    outside_file = tmp_path / "outside.yaml"
    outside_file.write_text("original", encoding="utf-8")
    (
        source / "improvements" / "open" / "MFP-0001.yaml"
    ).symlink_to(outside_file)
    with pytest.raises(ImproveError):
        source_import("demo/MFP-0001", source=source, kind="requirement")
    assert outside_file.read_text(encoding="utf-8") == "original"


def test_source_import_chain_rejects_traversal(mfp_env, tmp_path):
    path = new_improvement(mfp_env["root"], "链路穿越")
    _fill(path, id="../../escaped2")
    submit_improvement(mfp_env["root"], "MFP-0001")
    source = _source(tmp_path)
    with pytest.raises(ImproveError):
        source_import("MFP-0001", source=source, kind="requirement")
    assert not [p for p in tmp_path.rglob("escaped2*") if p.is_file()]
    assert not [p for p in tmp_path.rglob("escaped*") if p.is_file()]


def test_source_import_missing_id_uses_inbox_filename(mfp_env, tmp_path):
    data = _package(mfp_env["root"])
    data.pop("id", None)
    _write_inbox(mfp_env["home"], data, name="MFP-0007")
    source = _source(tmp_path)
    result = source_import("demo/MFP-0007", source=source, kind="requirement")
    assert result["mfp"] == "MFP-0007"
    assert (source / "improvements" / "open" / "MFP-0007.yaml").is_file()


def test_source_update_rejects_unsafe_id(mfp_env, tmp_path):
    data = _package(mfp_env["root"])
    source = _source(tmp_path)
    open_dir = source / "improvements" / "open"
    open_dir.mkdir(parents=True)
    (open_dir / "MFP-0001.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    evil = source / "improvements" / "evil.yaml"
    evil.write_text("original", encoding="utf-8")
    for bad_id in ("../evil", "/tmp/x", "a/b", "..", ""):
        with pytest.raises(ImproveError):
            source_update(bad_id, "verified", source=source)
    assert evil.read_text(encoding="utf-8") == "original"
    # 合法更新行为不变
    target = source_update("MFP-0001", "verified", source=source)
    assert target.parent.name == "closed"
    assert (source / "improvements" / "closed" / "MFP-0001.yaml").is_file()


def test_source_update_rejects_unsafe_record_ref(mfp_env, tmp_path):
    data = _package(mfp_env["root"], source_record="../../evil-record")
    source = _source(tmp_path)
    open_dir = source / "improvements" / "open"
    open_dir.mkdir(parents=True)
    (open_dir / "MFP-0001.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    outside = tmp_path / "evil-record.yaml"
    outside.write_text("original", encoding="utf-8")
    with pytest.raises(ImproveError):
        source_update("MFP-0001", "verified", source=source)
    assert outside.read_text(encoding="utf-8") == "original"
    assert not (source / "improvements" / "closed" / "evil-record.yaml").exists()
