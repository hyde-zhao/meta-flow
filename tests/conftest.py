from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _declare_source_test_provider_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """源码测试必须显式使用 development provider，不冒充 artifact release。"""

    monkeypatch.setenv("META_FLOW_PROVIDER_MODE", "development")
