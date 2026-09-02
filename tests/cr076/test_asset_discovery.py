"""STORY-CR076-S03 targeted 测试：naming 规范化与四资产发现 fail-closed
（BIT-03 + BIT-N01/N08 发现侧）。

权威 = cr076-bundle-identity-transport TEST-PLAN + LLD v1.2 §4.2/§7.2。
"""

from __future__ import annotations

from hashlib import sha256

import pytest

from meta_flow.release.asset_discovery import (
    discover_release_assets,
    normalize_naming,
    observe_asset_digests,
)

_WHEEL = "meta_flow-1.2.3-py3-none-any.whl"
_SDIST = "meta_flow-1.2.3.tar.gz"
_RECEIPT = "ProviderArtifactReceiptV1.json"
_SIDECAR = "ProviderArtifactReceiptV1.digest-policy.json"


def _seed(directory, *, wheel: str = _WHEEL) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / wheel).write_bytes(b"wheel-bytes")
    (directory / _SDIST).write_bytes(b"sdist-bytes")
    (directory / _RECEIPT).write_bytes(b"receipt-bytes")
    (directory / _SIDECAR).write_bytes(b"sidecar-bytes")


def test_bit03_normalize_naming() -> None:
    naming = normalize_naming(project_name="Meta-Flow", wheel_filename=_WHEEL)
    assert naming == {
        "project_name": "Meta-Flow",
        "wheel_tag": "py3-none-any",
        "normalized_prefix": "meta_flow-1.2.3",
    }
    # 段不足 / distribution 段与项目名不符 / 空项目名 → ASSET-UNSAFE。
    with pytest.raises(ValueError, match="ASSET-UNSAFE"):
        normalize_naming(project_name="meta-flow", wheel_filename="meta_flow-py3.whl")
    with pytest.raises(ValueError, match="ASSET-UNSAFE"):
        normalize_naming(project_name="other-project", wheel_filename=_WHEEL)
    with pytest.raises(ValueError, match="ASSET-UNSAFE"):
        normalize_naming(project_name="  ", wheel_filename=_WHEEL)


def test_bit03_discover_exactly_four(tmp_path) -> None:
    _seed(tmp_path)
    naming = normalize_naming(project_name="meta-flow", wheel_filename=_WHEEL)
    found = discover_release_assets(tmp_path, naming)
    assert set(found) == {"wheel", "sdist", "build_receipt", "sidecar"}
    assert found["wheel"].name == _WHEEL and found["sidecar"].name == _SIDECAR
    # observe：物理域 sha256 与文件内容一致（sidecar 是物理 bytes digest）。
    digests = observe_asset_digests(tmp_path, naming)
    assert digests["wheel"] == sha256(b"wheel-bytes").hexdigest()
    assert digests["sidecar"] == sha256(b"sidecar-bytes").hexdigest()


def test_bit03_missing_slot(tmp_path) -> None:
    _seed(tmp_path)
    (tmp_path / _SDIST).unlink()
    naming = normalize_naming(project_name="meta-flow", wheel_filename=_WHEEL)
    with pytest.raises(ValueError, match="ASSET-MISSING"):
        discover_release_assets(tmp_path, naming)


def test_bit03_duplicate_identical_bytes(tmp_path) -> None:
    _seed(tmp_path)
    # 同公共前缀、不同 tag、bytes 相同 → 两个等价候选，仍拒绝（要求恰好一个）。
    (tmp_path / "meta_flow-1.2.3-py3-none-many.whl").write_bytes(b"wheel-bytes")
    naming = normalize_naming(project_name="meta-flow", wheel_filename=_WHEEL)
    with pytest.raises(ValueError, match="ASSET-DUPLICATE"):
        discover_release_assets(tmp_path, naming)


def test_n01_ambiguous_candidates(tmp_path) -> None:
    _seed(tmp_path)
    # sdist 模糊前缀命中两个不同 bytes 候选（1.2.3 与 1.2.30）。
    (tmp_path / "meta_flow-1.2.30.tar.gz").write_bytes(b"different-bytes")
    naming = normalize_naming(project_name="meta-flow", wheel_filename=_WHEEL)
    with pytest.raises(ValueError, match="ASSET-AMBIGUOUS"):
        observe_asset_digests(tmp_path, naming)
    # wheel 多候选同理（不同 tag）。
    _seed(tmp_path)
    (tmp_path / "meta_flow-1.2.3-py3-none-many.whl").write_bytes(b"other-wheel")
    with pytest.raises(ValueError, match="ASSET-AMBIGUOUS"):
        discover_release_assets(tmp_path, naming)


def test_n08_symlink_sidecar_rejected(tmp_path) -> None:
    _seed(tmp_path)
    outside = tmp_path.parent / "outside-sidecar.bin"
    outside.write_bytes(b"sidecar-bytes")
    (tmp_path / _SIDECAR).unlink()
    (tmp_path / _SIDECAR).symlink_to(outside)
    naming = normalize_naming(project_name="meta-flow", wheel_filename=_WHEEL)
    with pytest.raises(ValueError, match="ASSET-UNSAFE"):
        discover_release_assets(tmp_path, naming)


def test_directory_must_be_real(tmp_path) -> None:
    naming = normalize_naming(project_name="meta-flow", wheel_filename=_WHEEL)
    # 不存在的目录 / symlink 目录 → ASSET-UNSAFE。
    with pytest.raises(ValueError, match="ASSET-UNSAFE"):
        discover_release_assets(tmp_path / "missing", naming)
    real = tmp_path / "real"
    _seed(real)
    linked = tmp_path / "linked"
    linked.symlink_to(real)
    with pytest.raises(ValueError, match="ASSET-UNSAFE"):
        discover_release_assets(linked, naming)
    # naming 结构不符（字段缺失）→ ASSET-UNSAFE。
    with pytest.raises(ValueError, match="ASSET-UNSAFE"):
        discover_release_assets(real, {"project_name": "meta-flow"})
