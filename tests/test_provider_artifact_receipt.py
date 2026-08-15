from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from meta_flow.installation import artifact


def _wheel(path: Path, *, version: str = "0.5.1") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"meta_flow-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: meta-flow\nVersion: {version}\n",
        )
        archive.writestr("meta_flow/__init__.py", f'__version__ = "{version}"\n')
    return path


def _source_identity() -> dict[str, str]:
    return {
        "source": "checkout/meta-flow",
        "version": "0.5.1",
        "oid": "a" * 40,
        "delivery_tree_digest": "b" * 64,
        "rules_source_digest": "c" * 64,
        "inventory_digest": "d" * 64,
    }


def test_artifact_receipt_binds_clean_source_and_wheel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    contract = source / "delivery" / "doc" / "PUBLIC-OPERATION-CONTRACTS.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text("{}\n", encoding="utf-8")
    wheel = _wheel(tmp_path / "meta_flow-0.5.1-py3-none-any.whl")
    monkeypatch.setattr(artifact, "observe_checkout_source_identity", lambda _root: _source_identity())
    monkeypatch.setattr(
        artifact,
        "observe_checkout_delivery_status",
        lambda _root: {"worktree_clean": True, "exact_commit_delivery": True},
    )

    receipt = artifact.build_provider_artifact_receipt(source, wheel)

    assert receipt["source_commit"] == "a" * 40
    assert receipt["source_dirty"] is False
    assert receipt["release_qualifying"] is True
    assert receipt["installed_payload_digest"] == artifact._wheel_payload_digest(wheel)
    assert artifact.validate_provider_artifact_receipt(receipt) == receipt


def test_dirty_source_receipt_is_not_release_qualifying(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    contract = source / "delivery" / "doc" / "PUBLIC-OPERATION-CONTRACTS.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text("{}\n", encoding="utf-8")
    wheel = _wheel(tmp_path / "meta_flow-0.5.1-py3-none-any.whl")
    monkeypatch.setattr(artifact, "observe_checkout_source_identity", lambda _root: _source_identity())
    monkeypatch.setattr(
        artifact,
        "observe_checkout_delivery_status",
        lambda _root: {"worktree_clean": False, "exact_commit_delivery": False},
    )

    receipt = artifact.build_provider_artifact_receipt(source, wheel)

    assert receipt["source_dirty"] is True
    assert receipt["release_qualifying"] is False
    assert artifact.validate_provider_artifact_receipt(receipt) == receipt


def test_receipt_digest_and_runtime_conflicts_fail_closed(tmp_path: Path) -> None:
    receipt = {
        "schema_version": 1,
        "kind": "ProviderArtifactReceiptV1",
        "distribution_name": "meta-flow",
        "distribution_version": "0.5.1",
        "source_commit": "a" * 40,
        "source_dirty": False,
        "source_tree_digest": "b" * 64,
        "artifact_filename": "meta_flow-0.5.1-py3-none-any.whl",
        "artifact_sha256": "c" * 64,
        "capability_profile_digest": "d" * 64,
        "installed_payload_digest": "f" * 64,
        "release_qualifying": True,
        "receipt_digest": "e" * 64,
    }
    with pytest.raises(ValueError, match="digest mismatch"):
        artifact.validate_provider_artifact_receipt(receipt)

    unsigned = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    receipt["receipt_digest"] = artifact._canonical_digest(unsigned)
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    loaded = artifact.load_provider_artifact_receipt(path)
    conflicts = artifact.artifact_receipt_conflicts(
        loaded,
        {
            "distribution_name": "meta-flow",
            "distribution_version": "0.5.1",
            "artifact_sha256": "f" * 64,
            "capability_profile_digest": "d" * 64,
            "installed_payload_digest": "f" * 64,
        },
    )
    assert conflicts == ("PROVIDER_RECEIPT_ARTIFACT_SHA256_MISMATCH",)


def test_runtime_payload_drift_is_rejected_even_when_archive_digest_matches() -> None:
    receipt = {
        "schema_version": 1,
        "kind": "ProviderArtifactReceiptV1",
        "distribution_name": "meta-flow",
        "distribution_version": "0.5.1",
        "source_commit": "a" * 40,
        "source_dirty": False,
        "source_tree_digest": "b" * 64,
        "artifact_filename": "meta_flow-0.5.1-py3-none-any.whl",
        "artifact_sha256": "c" * 64,
        "capability_profile_digest": "d" * 64,
        "installed_payload_digest": "e" * 64,
        "release_qualifying": True,
    }
    receipt["receipt_digest"] = artifact._canonical_digest(receipt)

    conflicts = artifact.artifact_receipt_conflicts(
        receipt,
        {
            "distribution_name": "meta-flow",
            "distribution_version": "0.5.1",
            "artifact_sha256": "c" * 64,
            "capability_profile_digest": "d" * 64,
            "installed_payload_digest": "f" * 64,
        },
    )

    assert conflicts == ("PROVIDER_RECEIPT_INSTALLED_PAYLOAD_DIGEST_MISMATCH",)
