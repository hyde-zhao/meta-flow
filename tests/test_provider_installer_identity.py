from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from delivery.scripts import install


def _commit(root: Path) -> str:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    (root / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def test_installer_uses_full_oid_and_detects_dirty_source(tmp_path: Path) -> None:
    expected = _commit(tmp_path)

    assert install.canonical_commit(tmp_path) == expected
    assert len(expected) == 40
    assert install.source_worktree_clean(tmp_path) is True

    (tmp_path / "prospective.txt").write_text("dirty\n", encoding="utf-8")
    assert install.source_worktree_clean(tmp_path) is False


def test_provider_checkout_detection_does_not_claim_consumer_venv(
    tmp_path: Path,
) -> None:
    consumer = tmp_path / "consumer"
    (consumer / ".git").mkdir(parents=True)
    script = consumer / ".venv" / "site-packages" / "delivery" / "scripts" / "install.py"
    script.parent.mkdir(parents=True)
    script.write_text("# installed artifact\n", encoding="utf-8")

    assert install.find_provider_checkout_root(script.parents[1], script) is None

    checkout_script = consumer / "delivery" / "scripts" / "install.py"
    checkout_script.parent.mkdir(parents=True)
    checkout_script.write_text("# source checkout\n", encoding="utf-8")
    assert (
        install.find_provider_checkout_root(checkout_script.parents[1], checkout_script)
        == consumer
    )


def test_delivery_tree_digest_is_content_bound_and_root_shape_independent(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    delivery = checkout / "delivery"
    contract = delivery / "doc" / "PUBLIC-OPERATION-CONTRACTS.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text("{}\n", encoding="utf-8")

    from_checkout = install.source_delivery_tree_digest(checkout)
    from_delivery = install.source_delivery_tree_digest(delivery)
    contract.write_text('{"changed": true}\n', encoding="utf-8")

    assert from_checkout == from_delivery
    assert install.source_delivery_tree_digest(delivery) != from_delivery


def test_installed_payload_digest_ignores_uv_generated_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    site_packages = tmp_path / "site-packages"
    module = site_packages / "meta_flow" / "__init__.py"
    metadata_file = site_packages / "meta_flow-0.5.2.dist-info" / "METADATA"
    uv_cache = site_packages / "meta_flow-0.5.2.dist-info" / "uv_cache.json"
    module.parent.mkdir(parents=True)
    metadata_file.parent.mkdir(parents=True)
    module.write_text('__version__ = "0.5.2"\n', encoding="utf-8")
    metadata_file.write_text("Name: meta-flow\nVersion: 0.5.2\n", encoding="utf-8")
    uv_cache.write_text('{"generated": true}\n', encoding="utf-8")

    class Distribution:
        files = [
            Path("meta_flow/__init__.py"),
            Path("meta_flow-0.5.2.dist-info/METADATA"),
            Path("meta_flow-0.5.2.dist-info/uv_cache.json"),
        ]

        @staticmethod
        def locate_file(item: object) -> Path:
            return site_packages / Path(str(item))

    monkeypatch.setattr(install.metadata, "distribution", lambda _name: Distribution())
    before = install.installed_distribution_payload_digest()
    uv_cache.write_text('{"generated": "changed"}\n', encoding="utf-8")

    assert before
    assert install.installed_distribution_payload_digest() == before


def test_installer_provider_receipt_loader_rejects_incomplete_payload(
    tmp_path: Path,
    capsys,
) -> None:
    path = tmp_path / "receipt.json"
    path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        install.load_provider_receipt_facts(str(path))
    assert "字段不完整" in capsys.readouterr().err


def test_installer_provider_receipt_loader_returns_release_binding(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "kind": "ProviderArtifactReceiptV1",
        "distribution_name": "meta-flow",
        "distribution_version": "0.5.2",
        "source_commit": "a" * 40,
        "source_dirty": False,
        "source_tree_digest": "b" * 64,
        "artifact_filename": "meta_flow-0.5.2-py3-none-any.whl",
        "artifact_sha256": "c" * 64,
        "capability_profile_digest": "d" * 64,
        "installed_payload_digest": "e" * 64,
        "release_qualifying": True,
    }
    rendered = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["receipt_digest"] = sha256(rendered).hexdigest()
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert install.load_provider_receipt_facts(str(path)) == payload


def test_installer_provider_receipt_loader_rejects_digest_drift(
    tmp_path: Path,
    capsys,
) -> None:
    payload = {
        "schema_version": 1,
        "kind": "ProviderArtifactReceiptV1",
        "distribution_name": "meta-flow",
        "distribution_version": "0.5.2",
        "source_commit": "a" * 40,
        "source_dirty": False,
        "source_tree_digest": "b" * 64,
        "artifact_filename": "meta_flow-0.5.2-py3-none-any.whl",
        "artifact_sha256": "c" * 64,
        "capability_profile_digest": "d" * 64,
        "installed_payload_digest": "e" * 64,
        "release_qualifying": True,
        "receipt_digest": "e" * 64,
    }
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        install.load_provider_receipt_facts(str(path))
    assert "digest 不匹配" in capsys.readouterr().err
