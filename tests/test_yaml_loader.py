from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_flow.project.scale import dump_yaml, load_yaml_object


def _load(tmp_path: Path, text: str) -> dict[str, object]:
    path = tmp_path / "fixture.yaml"
    path.write_text(text, encoding="utf-8")
    return load_yaml_object(path)


def test_block_scalars_support_literal_folded_and_chomping(tmp_path: Path) -> None:
    payload = _load(
        tmp_path,
        """literal_clip: |
  alpha
  beta
literal_strip: |-
  alpha
  beta
literal_keep: |+
  alpha
  beta

folded_clip: >
  alpha
  beta
folded_strip: >-
  alpha
  beta
folded_keep: >+
  alpha
  beta

""",
    )

    assert payload["literal_clip"] == "alpha\nbeta\n"
    assert payload["literal_strip"] == "alpha\nbeta"
    assert payload["literal_keep"] == "alpha\nbeta\n\n"
    assert payload["folded_clip"] == "alpha beta\n"
    assert payload["folded_strip"] == "alpha beta"
    assert payload["folded_keep"] == "alpha beta\n\n"


def test_yaml_loader_preserves_existing_json_like_scalar_semantics(tmp_path: Path) -> None:
    payload = _load(
        tmp_path,
        """truth: true
falsehood: false
nothing: null
tilde: ~
count: -12
decimal_text: 1.25
date_text: 2026-08-12
yes_text: yes
no_text: no
on_text: on
off_text: off
quoted: "true"
inline: [true, false, null, 7, 1.5, yes, 2026-08-12]
""",
    )

    assert payload == {
        "truth": True,
        "falsehood": False,
        "nothing": None,
        "tilde": None,
        "count": -12,
        "decimal_text": "1.25",
        "date_text": "2026-08-12",
        "yes_text": "yes",
        "no_text": "no",
        "on_text": "on",
        "off_text": "off",
        "quoted": "true",
        "inline": [True, False, None, 7, "1.5", "yes", "2026-08-12"],
    }


def test_yaml_loader_keeps_json_input_semantics(tmp_path: Path) -> None:
    payload = {"schema_version": 1, "ratio": 1.25, "enabled": True}
    assert _load(tmp_path, json.dumps(payload)) == payload


def test_dump_yaml_round_trips_indicator_and_typed_strings(tmp_path: Path) -> None:
    payload = {
        "comparison": ">=",
        "literal_marker": "|value",
        "tag_marker": "!value",
        "integer_text": "12",
        "boolean_text": "true",
        "plain": "alpha-beta",
    }

    assert _load(tmp_path, dump_yaml(payload) + "\n") == payload


@pytest.mark.parametrize(
    "text, message",
    [
        ("value: !!python/object/apply:os.system ['id']\n", "invalid YAML"),
        ("value: !!timestamp 2026-08-12\n", "unsupported YAML value type"),
        ("1: value\n", "non-string mapping key"),
        ("value: &self [*self]\n", "recursive YAML alias"),
        ("---\na: 1\n---\nb: 2\n", "invalid YAML"),
    ],
)
def test_yaml_loader_rejects_unsafe_or_non_json_values(
    tmp_path: Path,
    text: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, text)


def test_yaml_loader_requires_object_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must contain a YAML object"):
        _load(tmp_path, "- one\n- two\n")
