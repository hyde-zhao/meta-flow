from __future__ import annotations

import json
import runpy
import subprocess
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest

from delivery.scripts.digest_policy import canonical_digest
from meta_flow.installation import artifact

ROOT = Path(__file__).parents[1]
QUALIFICATION = runpy.run_path(
    str(ROOT / "scripts/qualify_provider_artifact.py"),
    run_name="__provider_artifact_qualification_test__",
)


def _wheel(path: Path, *, version: str = "0.5.1") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"meta_flow-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: meta-flow\nVersion: {version}\n",
        )
        archive.writestr("meta_flow/__init__.py", f'__version__ = "{version}"\n')
        archive.writestr("delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml", "{}\n")
    return path


def _source_identity() -> dict[str, str]:
    return {
        "source": "checkout/meta-flow",
        "version": "0.5.1",
        "oid": "a" * 40,
        "delivery_tree_digest": canonical_digest(
            {
                "delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml": sha256(
                    b"{}\n"
                ).hexdigest()
            }
        ),
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


def test_qualification_entrypoint_writes_receipt_and_policy_sidecar(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    delivery = source / "delivery"
    files = {
        "doc/PUBLIC-OPERATION-CONTRACTS.yaml": "{}\n",
        "doc/RULES-SEMANTIC-INVENTORY.json": "{}\n",
        "doc/SOURCE-DIGEST-GENERATED-MANIFEST.json": json.dumps(
            {
                "schema_version": 1,
                "kind": "SourceDigestGeneratedManifestV1",
                "generated_refs": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "rules/AGENTS.md": "# Rules\n",
    }
    for relative, content in files.items():
        path = delivery / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (source / "pyproject.toml").write_text(
        '[project]\nname = "meta-flow"\nversion = "0.5.1"\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Meta Flow Test",
            "-c",
            "user.email=meta-flow@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=source,
        check=True,
        capture_output=True,
    )
    wheel = tmp_path / "meta_flow-0.5.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "meta_flow-0.5.1.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: meta-flow\nVersion: 0.5.1\n",
        )
        archive.writestr("meta_flow/__init__.py", '__version__ = "0.5.1"\n')
        for path in sorted(delivery.rglob("*")):
            if path.is_file():
                archive.writestr(
                    (Path("delivery") / path.relative_to(delivery)).as_posix(),
                    path.read_bytes(),
                )
    output = tmp_path / "ProviderArtifactReceiptV1.json"

    exit_code = QUALIFICATION["main"](
        [
            "--source-root",
            str(source),
            "--wheel",
            str(wheel),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    receipt = artifact.load_provider_artifact_receipt(output)
    sidecar_path = artifact.sidecar_path_for_receipt(output)
    assert sidecar_path.is_file()
    assert receipt["source_tree_digest"] == json.loads(
        sidecar_path.read_text(encoding="utf-8")
    )["included_manifest_digest"]
    assert set(receipt) == artifact._FIELDS


def test_qualification_bundle_restores_both_preimages_when_commit_marker_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "ProviderArtifactReceiptV1.json"
    sidecar_path = artifact.sidecar_path_for_receipt(output)
    before_receipt = b'{"legacy":"receipt"}\n'
    before_sidecar = b'{"legacy":"sidecar"}\n'
    output.write_bytes(before_receipt)
    sidecar_path.write_bytes(before_sidecar)
    original_write = QUALIFICATION["_write_bytes_atomic"]
    calls: list[Path] = []

    def fail_receipt_commit(path: Path, rendered: bytes) -> None:
        calls.append(path)
        if len(calls) == 2:
            raise OSError("injected receipt commit failure")
        original_write(path, rendered)

    monkeypatch.setitem(
        QUALIFICATION["_write_bundle_atomic"].__globals__,
        "_write_bytes_atomic",
        fail_receipt_commit,
    )

    with pytest.raises(OSError, match="injected receipt commit failure"):
        QUALIFICATION["_write_bundle_atomic"](
            output,
            {"new": "receipt"},
            {"new": "sidecar"},
        )

    assert output.read_bytes() == before_receipt
    assert sidecar_path.read_bytes() == before_sidecar


@pytest.mark.parametrize("unsafe_leaf", ["receipt", "sidecar"])
def test_qualification_bundle_rejects_symlink_leaf_without_mutation(
    tmp_path: Path,
    unsafe_leaf: str,
) -> None:
    output = tmp_path / "ProviderArtifactReceiptV1.json"
    sidecar_path = artifact.sidecar_path_for_receipt(output)
    victim = tmp_path / f"{unsafe_leaf}-victim.json"
    victim_bytes = b'{"do_not":"overwrite"}\n'
    victim.write_bytes(victim_bytes)
    unsafe_path = output if unsafe_leaf == "receipt" else sidecar_path
    unsafe_path.symlink_to(victim)

    with pytest.raises(ValueError, match="regular file or absent"):
        QUALIFICATION["_write_bundle_atomic"](
            output,
            {"new": "receipt"},
            {"new": "sidecar"},
        )

    assert unsafe_path.is_symlink()
    assert victim.read_bytes() == victim_bytes
    other = sidecar_path if unsafe_leaf == "receipt" else output
    assert not other.exists()


def test_provider_receipt_reader_rejects_symlink_leaf(tmp_path: Path) -> None:
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
    target = tmp_path / "target.json"
    target.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    link = tmp_path / "receipt.json"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="regular file"):
        artifact.load_provider_artifact_receipt(link)


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


def test_receipt_owns_artifact_digest_when_installer_omits_direct_url() -> None:
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

    assert artifact.artifact_receipt_conflicts(
        receipt,
        {
            "distribution_name": "meta-flow",
            "distribution_version": "0.5.1",
            "artifact_sha256": None,
            "capability_profile_digest": "d" * 64,
            "installed_payload_digest": "e" * 64,
        },
    ) == ()
