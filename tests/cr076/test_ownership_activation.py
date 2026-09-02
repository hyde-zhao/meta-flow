"""STORY-CR076-S04 targeted 测试：assert_activatable 三类 ownership 断言
（IL-08）。

权威 = cr076-installation-lifecycle TEST-PLAN + S04 LLD v1.0 §6/§8。
比对口径与 can_remove_owned 一致：exact_file=installed_digest、
managed_block=block_digest、exact_leaf_set=逐 leaf 全量相等。
"""

from __future__ import annotations

import pytest

from meta_flow.installation.canonical import canonical_digest
from meta_flow.installation.contracts import InstallationContractError
from meta_flow.installation.ownership import assert_activatable, can_remove_owned

D_A, D_B, D_C = "a" * 64, "b" * 64, "c" * 64


def _signed(unsigned: dict) -> dict:
    entry = dict(unsigned)
    entry["ownership_digest"] = canonical_digest(unsigned)
    return entry


def _exact_file(state: str = "active", installed: str = D_B) -> dict:
    return _signed(
        {
            "ownership_id": "own-file-1",
            "ownership_type": "exact_file",
            "target_ref": "agents/a.md",
            "source_ref": "sources/a.md",
            "source_digest": D_A,
            "installed_digest": installed,
            "owner_ref": "owners/s04",
            "generation": 1,
            "state": state,
            "created_directories": ["agents"],
            "metadata": {
                "file_ref": "agents/a.md",
                "recorded_digest": installed,
                "created": True,
                "mode": "replace-only",
                "write_policy": "digest-match",
            },
        }
    )


def _managed_block(state: str = "active") -> dict:
    return _signed(
        {
            "ownership_id": "own-block-1",
            "ownership_type": "managed_block",
            "target_ref": "agents/b.md",
            "source_ref": "sources/b.md",
            "source_digest": D_A,
            "installed_digest": D_B,
            "owner_ref": "owners/s04",
            "generation": 1,
            "state": state,
            "created_directories": [],
            "metadata": {
                "begin_marker": "<!-- meta-flow:begin -->",
                "end_marker": "<!-- meta-flow:end -->",
                "block_digest": D_C,
                "render_digest": D_B,
                "platform": "claude",
                "content_ref": "contents/block-1",
                "preimage_ref": "preimages/block-1",
                "marker_version": 1,
            },
        }
    )


def _leaf(ref: str, digest: str) -> dict:
    unsigned = {
        "leaf_ref": ref,
        "source_ref": f"sources/{ref}",
        "installed_digest": digest,
        "state": "active",
        "created": True,
    }
    leaf = dict(unsigned)
    leaf["leaf_digest"] = canonical_digest(unsigned)
    return leaf


def _exact_leaf_set(state: str = "active", digests: tuple[str, str] = (D_B, D_C)) -> dict:
    leaves = [_leaf("skills/s/a.md", digests[0]), _leaf("skills/s/b.md", digests[1])]
    return _signed(
        {
            "ownership_id": "own-leaves-1",
            "ownership_type": "exact_leaf_set",
            "target_ref": "skills/s",
            "source_ref": "sources/skills-s",
            "source_digest": D_A,
            "installed_digest": D_A,
            "owner_ref": "owners/s04",
            "generation": 1,
            "state": state,
            "created_directories": ["skills", "skills/s"],
            "metadata": {
                "root_ref": "skills/s",
                "leaves": leaves,
                "created_directories": ["skills", "skills/s"],
                "leaf_count": 2,
                "prune_policy": "empty-recorded-directories-only",
            },
        }
    )


# ------------------------------------------------------------ IL-08 正向


def test_il08_exact_file_match_yields_no_conflicts() -> None:
    assert assert_activatable(_exact_file(), D_B) == ()


def test_il08_managed_block_matches_block_digest() -> None:
    assert assert_activatable(_managed_block(), D_C) == ()
    assert assert_activatable(_managed_block(), D_B) == ("OWNERSHIP-ACTIVATION-CONFLICT:agents/b.md:digest-mismatch",)


def test_il08_exact_leaf_set_requires_every_leaf_digest_equal() -> None:
    mapping = {"skills/s/a.md": D_B, "skills/s/b.md": D_C}
    assert assert_activatable(_exact_leaf_set(), mapping) == ()
    partial = {"skills/s/a.md": D_B, "skills/s/b.md": D_A}
    assert assert_activatable(_exact_leaf_set(), partial) == ("OWNERSHIP-ACTIVATION-CONFLICT:skills/s:digest-mismatch",)
    assert assert_activatable(_exact_leaf_set(), D_B) == ("OWNERSHIP-ACTIVATION-CONFLICT:skills/s:digest-mismatch",)


# ------------------------------------------------------------ IL-08 负向


def test_il08_exact_file_digest_mismatch_is_typed_conflict() -> None:
    conflicts = assert_activatable(_exact_file(), D_A)
    assert conflicts == ("OWNERSHIP-ACTIVATION-CONFLICT:agents/a.md:digest-mismatch",)
    assert all(code.startswith("OWNERSHIP-ACTIVATION-CONFLICT:") for code in conflicts)


def test_il08_missing_observed_digest_does_not_pass() -> None:
    assert assert_activatable(_exact_file(), None) != ()


@pytest.mark.parametrize("state", ["stale", "removed"])
def test_il08_non_active_state_blocks_activation(state: str) -> None:
    assert assert_activatable(_exact_file(state=state), D_B) == (
        f"OWNERSHIP-ACTIVATION-CONFLICT:agents/a.md:state={state}",
    )
    assert assert_activatable(_managed_block(state=state), D_C) == (
        f"OWNERSHIP-ACTIVATION-CONFLICT:agents/b.md:state={state}",
    )


def test_il08_malformed_entry_raises_contract_error() -> None:
    broken = _exact_file()
    broken.pop("ownership_digest")
    with pytest.raises(InstallationContractError):
        assert_activatable(broken, D_B)


# --------------------------------------------- 与 can_remove_owned 口径一致


def test_il08_matches_can_remove_owned_digest_semantics() -> None:
    """同一观察下，可激活 ⇔ 可精确移除（fail-closed 口径复用，LLD §8）。"""

    entry = _exact_file()
    for observed in (D_B, D_A):
        assert (assert_activatable(entry, observed) == ()) == (can_remove_owned(entry, observed) != ())
