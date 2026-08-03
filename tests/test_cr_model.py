from __future__ import annotations  # noqa: I001

import ast
from pathlib import Path

from meta_flow.workflow import cr_lifecycle, cr_model


MODEL_MEMBERS = {
    "CR_ID_RE", "FRONTMATTER_RE", "ALLOWED_LIFECYCLE_STATUSES", "FINISHED_STATUSES",
    "CLOSED_GATE_STATUS", "SAFE_AUTHORIZATION_ID_RE", "OID_RE", "DIGEST_RE",
    "ALLOWED_CR_TYPES", "CR_TYPE_ALIASES", "CRRecord", "now_utc", "_strip_scalar",
    "_frontmatter", "_replace_frontmatter", "parse_frontmatter", "_format_frontmatter_value",
    "render_frontmatter_fields", "parse_inline_list", "parse_bool", "normalize_cr_type",
}


def _public_top_level(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else node.targets[0].id
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign))
        and (not isinstance(node, ast.Assign) or not node.targets[0].id.startswith("__"))
    }


def test_model_exact_owner_and_facade_reexport() -> None:
    assert MODEL_MEMBERS <= _public_top_level(Path(cr_model.__file__))
    assert len(MODEL_MEMBERS) == 21
    assert cr_lifecycle.CRRecord is cr_model.CRRecord
    assert cr_lifecycle.parse_frontmatter is cr_model.parse_frontmatter


def test_parse_frontmatter_returns_existing_fields() -> None:
    text = '''---
schema_version: 1
cr_id: "CR-101"
lifecycle_status: "active"
impact_surface: ["meta_flow/workflow/cr_lifecycle.py"]
product_baseline_refresh_required: true
---

## 变更描述
'''

    assert cr_model.parse_frontmatter(text) == {
        "schema_version": "1",
        "cr_id": "CR-101",
        "lifecycle_status": "active",
        "impact_surface": '["meta_flow/workflow/cr_lifecycle.py"]',
        "product_baseline_refresh_required": "true",
    }


def test_parse_frontmatter_without_frontmatter_returns_empty_mapping() -> None:
    assert cr_model.parse_frontmatter("## 变更描述\n\n无 frontmatter。\n") == {}


def test_scalar_frontmatter_render_parse_round_trip() -> None:
    text = '''---
schema_version: 1
lifecycle_status: "active"
readiness_status: "NOT_READY"
gate_status: "cp8_pending"
impact_surface: ["meta_flow/workflow/cr_lifecycle.py"]
product_baseline_refresh_required: true
---

## 变更描述

本 CR 用于测试生命周期治理。
'''

    rendered = cr_model.render_frontmatter_fields(
        text,
        {
            "lifecycle_status": "closed",
            "readiness_status": "READY_WITH_RISK",
            "gate_status": "cp8_closed",
        },
    )
    fields = cr_model.parse_frontmatter(rendered)

    assert fields["lifecycle_status"] == "closed"
    assert fields["readiness_status"] == "READY_WITH_RISK"
    assert fields["gate_status"] == "cp8_closed"
    assert fields["impact_surface"] == '["meta_flow/workflow/cr_lifecycle.py"]'
    assert fields["product_baseline_refresh_required"] == "true"
    assert "本 CR 用于测试生命周期治理。" in rendered
