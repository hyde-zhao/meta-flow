from __future__ import annotations

import base64
import json
from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.semantics.generation_lineage import committed_generation_head_digests

_MISSING = object()


def _write_manifest(
    root: Path,
    authorization_id: str,
    *,
    before: bytes,
    after: bytes,
    ordinal: int,
    predecessor: str | object = _MISSING,
) -> None:
    directory = root / authorization_id
    directory.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "kind": "work-close-transaction-v1",
        "authorization_id": authorization_id,
        "work_id": authorization_id.removeprefix("close-"),
        "plan_digest": "f" * 64,
        "state": "COMMITTED",
        "created_at": f"2026-01-01T00:00:0{ordinal}+00:00",
        "updated_at": f"2026-01-01T00:00:0{ordinal}+00:00",
        "attempted_refs": ["STATE.md"],
        "applied_refs": ["STATE.md"],
        "targets": [
            {
                "ref": "STATE.md",
                "before_digest": sha256(before).hexdigest(),
                "after_digest": sha256(after).hexdigest(),
                "before_bytes_b64": base64.b64encode(before).decode("ascii"),
                "after_bytes_b64": base64.b64encode(after).decode("ascii"),
            }
        ],
    }
    if predecessor is not _MISSING:
        payload["lineage"] = (
            {} if predecessor is None else {"STATE.md": str(predecessor)}
        )
    (directory / "manifest.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_legacy_manifests_are_ordered_as_one_compatibility_chain(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "close-w-000", before=b"0", after=b"1", ordinal=1)
    _write_manifest(tmp_path, "close-w-001", before=b"1", after=b"2", ordinal=2)

    heads = committed_generation_head_digests(tmp_path, refs=("STATE.md",))

    assert heads == {"STATE.md": sha256(b"2").hexdigest()}


def test_native_lineage_can_take_over_a_legacy_tail(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "close-w-000", before=b"0", after=b"1", ordinal=1)
    _write_manifest(tmp_path, "close-w-001", before=b"1", after=b"2", ordinal=2)
    _write_manifest(
        tmp_path,
        "close-w-002",
        before=b"2",
        after=b"3",
        ordinal=3,
        predecessor="close-w-001",
    )

    heads = committed_generation_head_digests(tmp_path, refs=("STATE.md",))

    assert heads == {"STATE.md": sha256(b"3").hexdigest()}


def test_duplicate_legacy_after_digest_is_one_equivalent_generation(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, "close-w-000", before=b"0", after=b"same", ordinal=1)
    _write_manifest(tmp_path, "close-w-001", before=b"other", after=b"same", ordinal=2)

    heads = committed_generation_head_digests(
        tmp_path,
        refs=("STATE.md",),
        current_digests={"STATE.md": sha256(b"same").hexdigest()},
    )

    assert heads == {"STATE.md": sha256(b"same").hexdigest()}


def test_lineage_fork_is_fail_closed(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "close-w-000",
        before=b"0",
        after=b"1",
        ordinal=1,
        predecessor=None,
    )
    for ordinal, work_id, after in (
        (2, "close-w-001", b"2"),
        (3, "close-w-002", b"3"),
    ):
        _write_manifest(
            tmp_path,
            work_id,
            before=b"1",
            after=after,
            ordinal=ordinal,
            predecessor="close-w-000",
        )

    with pytest.raises(ValueError, match="multiple successors"):
        committed_generation_head_digests(tmp_path, refs=("STATE.md",))


def test_manifest_digest_corruption_is_fail_closed(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "close-w-000",
        before=b"0",
        after=b"1",
        ordinal=1,
        predecessor=None,
    )
    path = tmp_path / "close-w-000/manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["targets"][0]["after_digest"] = "0" * 64
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="bytes/digest mismatch"):
        committed_generation_head_digests(tmp_path, refs=("STATE.md",))


def test_incomplete_manifest_cannot_authorize_a_successor_generation(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "close-w-000",
        before=b"0",
        after=b"1",
        ordinal=1,
        predecessor=None,
    )
    path = tmp_path / "close-w-000/manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("plan_digest")
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fields mismatch"):
        committed_generation_head_digests(tmp_path, refs=("STATE.md",))


def test_empty_target_terminal_manifest_does_not_hide_other_heads(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "close-w-000",
        before=b"0",
        after=b"1",
        ordinal=1,
        predecessor=None,
    )
    empty = {
        "schema_version": 1,
        "kind": "work-close-transaction-v1",
        "authorization_id": "close-noop",
        "work_id": "noop",
        "plan_digest": "e" * 64,
        "state": "COMMITTED",
        "created_at": "2026-01-01T00:00:02+00:00",
        "updated_at": "2026-01-01T00:00:02+00:00",
        "attempted_refs": [],
        "applied_refs": [],
        "targets": [],
        "lineage": {},
    }
    path = tmp_path / "close-noop/manifest.json"
    path.parent.mkdir()
    path.write_text(json.dumps(empty) + "\n", encoding="utf-8")

    assert committed_generation_head_digests(tmp_path, refs=("STATE.md",)) == {
        "STATE.md": sha256(b"1").hexdigest()
    }
