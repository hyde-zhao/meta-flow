from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

_FIXTURE_RUNNER = runpy.run_path(
    str(
        Path(__file__).parent
        / "fixtures/gov006/fixture_runner.py"
    ),
    run_name="__gov006_fixture_runner__",
)
ISOLATED_FIXTURE_IDS = _FIXTURE_RUNNER["ISOLATED_FIXTURE_IDS"]
RESULT_FIELDS = _FIXTURE_RUNNER["RESULT_FIELDS"]
run_isolated_fixture = _FIXTURE_RUNNER["run_isolated_fixture"]


@pytest.mark.parametrize("fixture_id", ISOLATED_FIXTURE_IDS)
def test_six_isolated_lifecycle_executions(
    fixture_id: str,
    tmp_path: Path,
) -> None:
    root = tmp_path / fixture_id.lower()
    result = run_isolated_fixture(
        fixture_id,
        root,
        external_project_root=Path(__file__).parents[1],
    )

    assert tuple(result) == RESULT_FIELDS
    assert result["fixture_id"] == fixture_id
    assert result["network_calls"] == 0
    assert result["real_home_hits"] == 0
    assert result["external_project_hits"] == 0
    assert result["authorization_count"] in {0, 1}
    assert result["transaction_count"] == 1
    assert result["cleanup_complete"] is True
    assert result["mutation_allowlist"]
    assert not (root / "runtime").exists()
    evidence = json.loads(
        (root / result["evidence_ref"]).read_text(encoding="utf-8")
    )
    assert evidence["cleanup_complete"] is True
    assert "/home/" not in json.dumps(evidence, ensure_ascii=False)


def test_fixture_ids_are_exactly_registered() -> None:
    registry = json.loads(
        (
            Path(__file__).parent
            / "fixtures/gov006/CASE-REGISTRY.json"
        ).read_text(encoding="utf-8")
    )

    assert tuple(registry["isolated_fixture_ids"]) == ISOLATED_FIXTURE_IDS


def test_real_home_and_external_project_roots_are_rejected(
    tmp_path: Path,
) -> None:
    external = Path(__file__).parents[1]

    with pytest.raises(ValueError, match="forbidden"):
        run_isolated_fixture(
            "FIX-F3-01",
            external / "forbidden-fixture",
            external_project_root=external,
        )
    with pytest.raises(ValueError, match="forbidden"):
        run_isolated_fixture(
            "FIX-F3-01",
            Path.home() / "forbidden-fixture",
            external_project_root=external,
        )


def test_symlink_sandbox_root_is_rejected(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "link"
    link.symlink_to(actual, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        run_isolated_fixture(
            "FIX-F3-01",
            link,
            external_project_root=Path(__file__).parents[1],
        )
