from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from meta_flow.work.validation_fingerprint import (
    build_validation_fingerprint,
    command_identity,
    source_from_file,
)


def _sources(root: Path):
    files = {
        "meta_flow/example.py": ("production", "value = 1\n"),
        "tests/test_example.py": ("test", "def test_value(): pass\n"),
        "pyproject.toml": ("config", "[project]\nname='demo'\n"),
        "uv.lock": ("lock", "version = 1\n"),
    }
    for ref, (_role, content) in files.items():
        path = root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tuple(source_from_file(root, ref, role=role) for ref, (role, _content) in files.items())


def test_fingerprint_is_canonical_and_any_source_change_invalidates_it(tmp_path: Path) -> None:
    profile_digest = sha256(b"layered-v1").hexdigest()
    first_sources = _sources(tmp_path)

    first = build_validation_fingerprint(
        "targeted",
        reversed(first_sources),
        profile_digest=profile_digest,
    )
    same = build_validation_fingerprint(
        "targeted",
        first_sources,
        profile_digest=profile_digest,
    )
    (tmp_path / "tests" / "test_example.py").write_text(
        "def test_value(): assert True\n",
        encoding="utf-8",
    )
    changed_sources = tuple(
        source_from_file(tmp_path, source.logical_ref, role=source.role)
        for source in first.sources
    )
    changed = build_validation_fingerprint(
        "targeted",
        changed_sources,
        profile_digest=profile_digest,
    )

    assert first == same
    assert changed.digest != first.digest
    assert {source.role for source in first.sources} == {"production", "test", "config", "lock"}


def test_profile_and_layer_are_part_of_fingerprint(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    one = build_validation_fingerprint(
        "targeted", sources, profile_digest=sha256(b"one").hexdigest()
    )
    two = build_validation_fingerprint(
        "compatibility", sources, profile_digest=sha256(b"two").hexdigest()
    )

    assert one.digest != two.digest


def test_fingerprint_requires_all_source_roles_and_safe_refs(tmp_path: Path) -> None:
    sources = _sources(tmp_path)

    with pytest.raises(ValueError, match="missing source roles"):
        build_validation_fingerprint(
            "targeted",
            sources[:-1],
            profile_digest=sha256(b"profile").hexdigest(),
        )
    with pytest.raises(ValueError, match="safe logical ref"):
        source_from_file(tmp_path, "../outside.py", role="production")


def test_command_identity_is_exact_without_persisting_command_text() -> None:
    first = command_identity(("uv", "run", "pytest", "-q", "tests/test_one.py"))
    same = command_identity(("uv", "run", "pytest", "-q", "tests/test_one.py"))
    changed = command_identity(("uv", "run", "pytest", "-q", "tests/test_two.py"))

    assert first == same
    assert first != changed
    assert len(first) == 64
    assert "pytest" not in first
