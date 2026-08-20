from __future__ import annotations

from pathlib import Path

import pytest

from meta_flow.installation import artifact

ROOT = Path(__file__).parents[1]


def test_release_asset_set_is_closed_unique_and_digest_bound() -> None:
    observed = artifact.build_provider_release_asset_set("0.6.1")

    assert observed.distribution_name == "meta-flow"
    assert observed.required_count == 4
    assert (
        observed.wheel_filename,
        observed.sdist_filename,
        observed.receipt_filename,
        observed.sidecar_filename,
    ) == (
        "meta_flow-0.6.1-py3-none-any.whl",
        "meta_flow-0.6.1.tar.gz",
        "ProviderArtifactReceiptV1.json",
        "ProviderArtifactReceiptV1.digest-policy.json",
    )
    payload = observed.as_dict()
    semantic_digest = payload.pop("semantic_digest")
    assert set(payload) == {
        "schema_version",
        "distribution_name",
        "distribution_version",
        "wheel_filename",
        "sdist_filename",
        "receipt_filename",
        "sidecar_filename",
        "required_count",
    }
    assert semantic_digest == artifact._canonical_digest(payload)
    assert len(
        {
            observed.wheel_filename,
            observed.sdist_filename,
            observed.receipt_filename,
            observed.sidecar_filename,
        }
    ) == 4


@pytest.mark.parametrize(
    "version",
    ["", "0.6", "v0.6.1", "0.6.1rc1", "0.6.1/escape", " 0.6.1"],
)
def test_release_asset_set_rejects_non_canonical_versions(version: str) -> None:
    with pytest.raises(ValueError, match="major.minor.patch"):
        artifact.build_provider_release_asset_set(version)


def test_sidecar_requirement_has_one_version_boundary() -> None:
    assert artifact.digest_policy_sidecar_required("0.6.0") is False
    assert artifact.digest_policy_sidecar_required("0.6.1") is True
    assert artifact.digest_policy_sidecar_required("1.0.0") is True
    with pytest.raises(ValueError, match="major.minor.patch"):
        artifact.digest_policy_sidecar_required("0.6")


def test_readme_download_and_environment_examples_match_asset_set() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install_section = readme.split("### 2. 安装或升级 CLI provider", 1)[0]
    asset_set = artifact.build_provider_release_asset_set("0.6.2")

    assert "export META_FLOW_VERSION=0.6.2" in install_section
    assert "0.5.3" not in install_section
    for leaf in (
        asset_set.wheel_filename,
        asset_set.sdist_filename,
        asset_set.receipt_filename,
        asset_set.sidecar_filename,
    ):
        assert leaf.replace("0.6.2", "${META_FLOW_VERSION}") in install_section
    assert "在最终构建前不填写 0.6.2 SHA placeholder" in install_section

    systemd_section = readme.split("#### Linux systemd 用户服务变量", 1)[1].split(
        "#### Windows PowerShell 用户变量", 1
    )[0]
    assert 'META_FLOW_RECEIPT_PATH="$(realpath -- ' in systemd_section
    assert '"$META_FLOW_RECEIPT_PATH"' in systemd_section
    assert '> "$META_FLOW_ENVIRONMENT_DIR/50-meta-flow.conf"' in systemd_section
    assert "META_FLOW_PROVIDER_RECEIPT=$META_FLOW_RELEASE_DIR" not in systemd_section


def test_deploy_checklist_uses_canonical_receipt_bundle_names() -> None:
    checklist = (ROOT / "docs/release/DEPLOY-CHECKLIST.md").read_text(encoding="utf-8")
    asset_set = artifact.build_provider_release_asset_set("0.6.1")

    assert f"`{asset_set.receipt_filename}`" in checklist
    assert f"`{asset_set.sidecar_filename}`" in checklist
    assert "ProviderArtifactReceiptV1-0.6.1.json" not in checklist
    assert "ProviderArtifactReceiptV1-0.6.1.digest-policy.json" not in checklist
