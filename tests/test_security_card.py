"""MFP-0041 A1：安全卡模板与校验。"""

from __future__ import annotations

from meta_flow import templates, verify

VALID = """# SECURITY-CARD demo

## 信任边界

受保护资产：contract/任务文件；信任宿主会话标识与 OS 用户边界。

## 攻击者能力

可控制命令文本、参数、提交信息、环境变量；不可控制宿主会话标识与 OS 隔离。

## 可证明的 fail_closed 范围

入口×变形×shell×环境矩阵；仅对已列出的解释器/uv/mf 段拒绝锚点写入。

## 不可防范围（残余风险）

不可伪造宿主凭据、OS 级隔离、恶意本地用户；归属 R1。

## 风险接受人

- 接受人：meta-manager
- 接受日期：2026-11-27
- 接受范围：R0

## 验证证据

- tests/test_designer_role.py
"""


def test_security_card_valid(tmp_path):
    card = tmp_path / "SECURITY-CARD.md"
    card.write_text(VALID, encoding="utf-8")
    result = verify.security_card_check(card)
    assert result["ok"] is True, result["errors"]


def test_security_card_missing_section_fails(tmp_path):
    card = tmp_path / "SECURITY-CARD.md"
    card.write_text(VALID.replace("## 攻击者能力", "## 其他"), encoding="utf-8")
    result = verify.security_card_check(card)
    assert result["ok"] is False
    assert any("攻击者能力" in error for error in result["errors"])


def test_security_card_overclaim_fails(tmp_path):
    card = tmp_path / "SECURITY-CARD.md"
    card.write_text(VALID + "\n本工具完全防护所有绕过。\n", encoding="utf-8")
    result = verify.security_card_check(card)
    assert result["ok"] is False
    assert any("完全防护" in error for error in result["errors"])


def test_security_templates_registered():
    assert "SECURITY-CARD.md" in templates.STANDARDS
    assert "NEGATIVE-MATRIX.md" in templates.STANDARDS
    assert "不可防范围" in templates.STANDARDS["SECURITY-CARD.md"]
    assert "入口" in templates.STANDARDS["NEGATIVE-MATRIX.md"]
