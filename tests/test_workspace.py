"""工作区核心逻辑测试。"""

from __future__ import annotations

import shutil

import pytest
import yaml

from meta_flow import templates
from meta_flow.workspace import (
    build_status,
    detect_role,
    doctor,
    init_workspace,
)


def _read_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path, data):
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


@pytest.fixture()
def workspace(tmp_path):
    root = init_workspace(
        tmp_path / "ws",
        "Demo App",
        ["frontend", "backend"],
        git=False,
    )
    return root


def test_init_creates_layout(workspace):
    assert (workspace / "mf.workspace.yaml").is_file()
    assert (workspace / "CLAUDE.md").is_file()
    assert (workspace / "contracts" / "project.yaml").is_file()
    assert (workspace / "contracts" / "project" / "PROJECT-PLAN.md").is_file()
    assert (workspace / "contracts" / "project" / "INIT-CHECKLIST.md").is_file()
    assert (workspace / "contracts" / "templates" / "SPEC.md").is_file()
    assert (workspace / "contracts" / "templates" / "TASK.yaml").is_file()
    assert (workspace / "contracts" / "policies" / "CONTEXT-POLICY.yaml").is_file()
    assert (workspace / "contracts" / "state" / "current.json").is_file()
    assert (workspace / "contracts" / "state" / "READ-LOG.ndjson").is_file()
    assert (workspace / "contracts" / "archive" / "README.md").is_file()
    assert (workspace / "contracts" / "requirements" / "INDEX.md").is_file()
    assert (workspace / "contracts" / "architecture" / "INDEX.md").is_file()
    assert (workspace / "contracts" / "dev-records").is_dir()
    assert (workspace / "contracts" / "roadmap" / "phases").is_dir()
    assert (workspace / "contracts" / "roadmap" / "ROADMAP.yaml").is_file()
    assert (workspace / "contracts" / "requirements" / "REQUIREMENTS.yaml").is_file()
    assert (workspace / "contracts" / "state" / "ledger.ndjson").is_file()
    assert (workspace / "contracts" / "standards" / "ACCEPTANCE.md").is_file()
    assert (workspace / "contracts" / "standards" / "BUGS.md").is_file()
    assert (workspace / "contracts" / "standards" / "KNOWLEDGE.md").is_file()
    assert (workspace / "contracts" / "standards" / "PROJECT.md").is_file()
    assert (workspace / "contracts" / "standards" / "ROADMAP.md").is_file()
    assert (workspace / "contracts" / "standards" / "DESIGN.md").is_file()
    assert (workspace / "contracts" / "standards" / "CONTEXT.md").is_file()
    assert len(templates.STANDARDS) == 15
    assert (workspace / "contracts" / "bugs" / "_TEMPLATE.yaml").is_file()
    assert (workspace / "contracts" / "knowledge" / "KNOWLEDGE.yaml").is_file()
    assert (workspace / "deliveries" / "frontend" / "delivery.yaml").is_file()
    assert (workspace / "deliveries" / "backend" / "RELEASE-NOTES.md").is_file()
    assert (workspace / "deliveries" / "frontend" / "USER-MANUAL.md").is_file()

    project = _read_yaml(workspace / "contracts" / "project.yaml")
    assert project["project_id"] == "demo-app"
    assert [item["id"] for item in project["deliveries"]] == ["frontend", "backend"]
    assert project["roadmap"] == "R1"
    assert project["version"] == "1.0.0-alpha.1"
    assert project["version_policy"] == "same-major"
    assert project["plan_ref"] == "project/PROJECT-PLAN.md"


def test_detect_role(workspace):
    root = workspace.resolve()
    assert detect_role(root) == ("maintainer", root)
    assert detect_role(root / "contracts")[0] == "manager"
    assert detect_role(root / "contracts" / "standards")[0] == "manager"
    assert detect_role(root / "deliveries")[0] == "worker"
    assert detect_role(root / "deliveries" / "frontend")[0] == "worker"


def test_detect_role_unbound(tmp_path):
    assert detect_role(tmp_path / "empty") == ("unbound", None)


def test_doctor_ok(workspace):
    assert doctor(workspace) == []


def test_doctor_missing_delivery(workspace):
    shutil.rmtree(workspace / "deliveries" / "frontend")
    errors = doctor(workspace)
    assert any("交付库目录不存在" in error for error in errors)


def test_doctor_version_mismatch(workspace):
    path = workspace / "deliveries" / "frontend" / "delivery.yaml"
    data = _read_yaml(path)
    data["version"] = "2.0.0"
    _write_yaml(path, data)
    errors = doctor(workspace)
    assert any("与路标 R1 不一致" in error for error in errors)


def test_doctor_plan_missing(workspace):
    (workspace / "contracts" / "project" / "PROJECT-PLAN.md").unlink()
    errors = doctor(workspace)
    assert any("缺少项目计划" in error for error in errors)


def test_doctor_knowledge_missing(workspace):
    (workspace / "contracts" / "knowledge" / "KNOWLEDGE.yaml").unlink()
    errors = doctor(workspace)
    assert any("KNOWLEDGE.yaml" in error for error in errors)


def test_doctor_template_missing(workspace):
    (workspace / "contracts" / "templates" / "SPEC.md").unlink()
    errors = doctor(workspace)
    assert any("缺少模板" in error for error in errors)


def test_doctor_state_too_large(workspace):
    state_path = workspace / "contracts" / "state" / "current.json"
    state_path.write_text("x" * 9000, encoding="utf-8")
    errors = doctor(workspace)
    assert any("超过 8KB" in error for error in errors)


def test_doctor_context_policy_missing(workspace):
    (workspace / "contracts" / "policies" / "CONTEXT-POLICY.yaml").unlink()
    errors = doctor(workspace)
    assert any("CONTEXT-POLICY.yaml" in error for error in errors)


def test_doctor_version_policy_exact(workspace):
    project_path = workspace / "contracts" / "project.yaml"
    project = _read_yaml(project_path)
    project["version_policy"] = "exact"
    project["version"] = "1.0.0"
    _write_yaml(project_path, project)

    delivery_path = workspace / "deliveries" / "frontend" / "delivery.yaml"
    delivery = _read_yaml(delivery_path)
    delivery["version"] = "1.0.1"
    _write_yaml(delivery_path, delivery)

    errors = doctor(workspace)
    assert any("必须等于项目版本" in error for error in errors)

    delivery["version"] = "1.0.0"
    _write_yaml(delivery_path, delivery)
    assert doctor(workspace) == []


def test_doctor_version_policy_invalid(workspace):
    project_path = workspace / "contracts" / "project.yaml"
    project = _read_yaml(project_path)
    project["version_policy"] = "whatever"
    _write_yaml(project_path, project)
    errors = doctor(workspace)
    assert any("version_policy 非法" in error for error in errors)


def test_doctor_contract_reference(workspace):
    delivery_path = workspace / "deliveries" / "frontend" / "delivery.yaml"
    data = _read_yaml(delivery_path)
    data["contracts"] = ["SPEC-API-001"]
    _write_yaml(delivery_path, data)

    errors = doctor(workspace)
    assert any("不存在的契约" in error for error in errors)

    spec = workspace / "contracts" / "specs" / "SPEC-API-001.md"
    spec.write_text("# API 契约\n", encoding="utf-8")
    assert doctor(workspace) == []


def test_status(workspace):
    data = build_status(workspace, "manager")
    assert data["project"]["name"] == "Demo App"
    assert data["project"]["id"] == "demo-app"
    assert data["role"] == "manager"
    assert data["roadmap"]["id"] == "R1"
    assert data["phase"] == "P1"
    assert len(data["deliveries"]) == 2
    assert data["tasks"] == {}
