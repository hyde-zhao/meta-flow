from __future__ import annotations

import json
import runpy
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

from delivery.scripts import digest_policy

ROOT = Path(__file__).parents[1]
GUARDRAIL = runpy.run_path(
    str(ROOT / "scripts/check_delivery_guardrails.py"),
    run_name="__digest_policy_guardrail_test__",
)
collect_digest_exclusion_policy_errors = GUARDRAIL[
    "collect_digest_exclusion_policy_errors"
]


def _write_manifest(delivery: Path, refs: list[str] | None = None) -> None:
    path = delivery / "doc" / "SOURCE-DIGEST-GENERATED-MANIFEST.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "SourceDigestGeneratedManifestV1",
                "generated_refs": refs or [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _fixture(root: Path) -> Path:
    delivery = root / "delivery"
    _write_manifest(delivery)
    source = delivery / "doc" / "source-generated-name.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    return delivery


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_python_cache_bytes_do_not_change_delivery_digest(tmp_path: Path) -> None:
    delivery = _fixture(tmp_path)
    before = digest_policy.observe_delivery_tree(tmp_path)
    cache = delivery / "scripts" / "__pycache__" / "install.cpython-311.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"one")
    first = digest_policy.observe_delivery_tree(tmp_path)
    cache.write_bytes(b"two")
    second = digest_policy.observe_delivery_tree(tmp_path)

    assert first.included_manifest_digest == before.included_manifest_digest
    assert second.included_manifest_digest == before.included_manifest_digest
    assert first.excluded_counts_by_reason["__pycache__"] == 1


def test_only_delivery_root_build_and_dist_are_excluded(tmp_path: Path) -> None:
    delivery = _fixture(tmp_path)
    before = digest_policy.observe_delivery_tree(tmp_path).included_manifest_digest
    for root_name in ("build", "dist"):
        generated = delivery / root_name / "payload.bin"
        generated.parent.mkdir()
        generated.write_bytes(root_name.encode())
    excluded = digest_policy.observe_delivery_tree(tmp_path)

    assert excluded.included_manifest_digest == before
    assert excluded.excluded_counts_by_reason["build"] == 1
    assert excluded.excluded_counts_by_reason["dist"] == 1

    nested = delivery / "doc" / "build" / "legitimate.py"
    nested.parent.mkdir()
    nested.write_text("VALUE = 1\n", encoding="utf-8")
    assert digest_policy.observe_delivery_tree(tmp_path).included_manifest_digest != before


def test_generated_substring_source_is_included_and_content_bound(tmp_path: Path) -> None:
    delivery = _fixture(tmp_path)
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "add", ".")
    before = digest_policy.observe_delivery_tree(tmp_path).included_manifest_digest
    source = delivery / "doc" / "source-generated-name.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")

    assert digest_policy.observe_delivery_tree(tmp_path).included_manifest_digest != before


def test_tracked_generated_is_a_guardrail_failure(tmp_path: Path) -> None:
    delivery = _fixture(tmp_path)
    cache = delivery / "scripts" / "__pycache__" / "install.cpython-311.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"tracked")
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "add", ".", "-f")

    errors = collect_digest_exclusion_policy_errors(tmp_path)

    assert errors == [
        "delivery digest policy violation: "
        "TRACKED_GENERATED:delivery/scripts/__pycache__/install.cpython-311.pyc"
    ]


def test_nested_git_marker_is_blocked_without_relying_on_git_inventory(
    tmp_path: Path,
) -> None:
    delivery = _fixture(tmp_path)
    marker = delivery / "skills" / "nested" / ".git"
    marker.parent.mkdir(parents=True)
    marker.write_text("gitdir: /outside\n", encoding="utf-8")

    with pytest.raises(digest_policy.DigestPolicyViolation) as raised:
        digest_policy.observe_delivery_tree(tmp_path)

    assert "SUBMODULE_MARKER:delivery/skills/nested/.git" in raised.value.findings


@pytest.mark.parametrize(
    ("kind", "finding"),
    [
        ("outside", "OUTSIDE_ROOT:../outside.py"),
        ("duplicate", "DUPLICATE_LOGICAL_OWNER:delivery/doc/source.py"),
        ("symlink", "SYMLINK:delivery/doc/link.py"),
    ],
)
def test_wheel_blocks_unsafe_or_duplicate_logical_owners(
    tmp_path: Path,
    kind: str,
    finding: str,
) -> None:
    wheel = tmp_path / f"{kind}.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        if kind == "outside":
            archive.writestr("../outside.py", "bad")
        elif kind == "duplicate":
            archive.writestr("delivery/doc/source.py", "one")
            archive.writestr("delivery/doc/source.py", "two")
        else:
            info = zipfile.ZipInfo("delivery/doc/link.py")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../outside.py")

    with zipfile.ZipFile(wheel) as archive, pytest.raises(
        digest_policy.DigestPolicyViolation,
    ) as raised:
        digest_policy.observe_wheel_payload(archive, known_generated_refs=())

    assert finding in raised.value.findings


def test_source_and_wheel_delivery_payload_use_one_normalization(tmp_path: Path) -> None:
    delivery = _fixture(tmp_path)
    (delivery / "scripts").mkdir()
    (delivery / "scripts" / "install.py").write_text("VALUE = 1\n", encoding="utf-8")
    (delivery / "scripts" / "__pycache__").mkdir()
    (delivery / "scripts" / "__pycache__" / "install.pyc").write_bytes(b"cache")
    source = digest_policy.observe_delivery_tree(tmp_path)
    wheel = tmp_path / "provider.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path in sorted(delivery.rglob("*")):
            if path.is_file():
                archive.writestr(
                    (Path("delivery") / path.relative_to(delivery)).as_posix(),
                    path.read_bytes(),
                )
        archive.writestr("meta_flow/__init__.py", "__version__ = '1.0'\n")
        archive.writestr("meta_flow-1.0.dist-info/RECORD", "generated")

    with zipfile.ZipFile(wheel) as archive:
        payload = digest_policy.observe_wheel_payload(
            archive,
            known_generated_refs=(),
        )

    assert payload.delivery_manifest_digest == source.included_manifest_digest
    assert payload.delivery_file_count == source.included_file_count
    assert payload.excluded_counts_by_reason["__pycache__"] == 1
    assert payload.excluded_counts_by_reason["distribution_metadata"] == 1


def test_wheel_root_build_is_content_bound_but_delivery_root_build_is_excluded(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "provider.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("build/legitimate-payload.bin", b"content-bound")
        archive.writestr("delivery/build/generated.bin", b"excluded")
        archive.writestr("delivery/doc/source.py", b"VALUE = 1\n")

    with zipfile.ZipFile(wheel) as archive:
        payload = digest_policy.observe_wheel_payload(
            archive,
            known_generated_refs=(),
        )

    assert "build/legitimate-payload.bin" in payload.records
    assert "delivery/build/generated.bin" not in payload.records
    assert payload.excluded_counts_by_reason["build"] == 1


def test_sidecar_binds_policy_manifest_and_invalidates_on_policy_change(
    tmp_path: Path,
) -> None:
    delivery = _fixture(tmp_path)
    sidecar = digest_policy.build_digest_policy_sidecar(tmp_path)
    receipt_path = tmp_path / "ProviderArtifactReceiptV1.json"
    sidecar_path = digest_policy.sidecar_path_for_receipt(receipt_path)
    sidecar_path.write_text(json.dumps(sidecar) + "\n", encoding="utf-8")

    loaded, warnings = digest_policy.load_digest_policy_sidecar(
        receipt_path,
        expected_included_manifest_digest=sidecar["included_manifest_digest"],
    )

    assert warnings == ()
    assert loaded == sidecar

    generated = delivery / "doc" / "rendered.json"
    generated.write_text("{}\n", encoding="utf-8")
    _write_manifest(delivery, ["delivery/doc/rendered.json"])
    with pytest.raises(ValueError, match="policy digest mismatch"):
        digest_policy.validate_digest_policy_sidecar(
            sidecar,
            expected_included_manifest_digest=sidecar["included_manifest_digest"],
            expected_policy_digest=digest_policy.exclusion_policy_digest(
                ("delivery/doc/rendered.json",)
            ),
        )


def test_missing_sidecar_has_one_version_legacy_warning(tmp_path: Path) -> None:
    receipt_path = tmp_path / "ProviderArtifactReceiptV1.json"

    sidecar, warnings = digest_policy.load_digest_policy_sidecar(
        receipt_path,
        expected_included_manifest_digest="a" * 64,
        allow_missing=True,
    )

    assert sidecar is None
    assert warnings == ("DIGEST_POLICY_SIDECAR_MISSING_LEGACY",)
