"""Installation Lifecycle V2 的稳定兼容 facade。"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "AuthorizationClaims": "authorization",
    "DurableJournalStore": "recovery",
    "build_installation_guardrail_report": None,
    "build_plan": "canonical",
    "canonical_digest": "canonical",
    "dispatch_authorized_actions": "engine",
    "dispatch_lifecycle_adapter": "migration",
    "execute_asset_action": "asset_executor",
    "execute_cli_action": "cli_executor",
    "inspect_v1_for_migration": "migration",
    "normalize_component": "identity",
    "normalize_reinstall": "cli_executor",
    "recover": "recovery",
    "validate_authorization": "authorization",
    "validate_manifest_v2": "manifest",
    "validate_plan": "contracts",
}

__all__ = sorted(name for name, module in _EXPORTS.items() if module is not None)


def __getattr__(name: str):
    """延迟导出，避免 facade 初始化改变 owner 模块的 import DAG。"""

    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(f"meta_flow.installation.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value
