from __future__ import annotations

import json
import subprocess
from pathlib import Path

from meta_flow.project import governance_projection


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_all(root: Path, message: str) -> str:
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Meta Flow Test",
        "-c",
        "user.email=meta-flow@example.invalid",
        "commit",
        "-m",
        message,
    )
    return _git(root, "rev-parse", "HEAD")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    release = tmp_path / "release"
    process = tmp_path / "process"
    release.mkdir()
    process.mkdir()
    _git(release, "init", "-b", "main")
    _git(process, "init", "-b", "main")
    _write(release / "README.md", "# release\n")
    release_oid = _commit_all(release, "release baseline")

    _write(
        process / "PROJECT.yaml",
        """schema_version: 1
project_id: demo
name: Demo
status: active
objective: demo governance
roadmap_ref: ROADMAP.yaml
""",
    )
    _write(
        process / "ROADMAP.yaml",
        """schema_version: 1
project_id: demo
outcome: demo
status: active
phase_refs:
  - phases/P1/PHASE.yaml
  - phases/P2/PHASE.yaml
""",
    )
    _write(
        process / "phases/P1/PHASE.yaml",
        """schema_version: 1
project_id: demo
phase_id: P1
objective: completed
status: completed
work_refs: []
result_refs:
  - phases/P1/RESULT.json
""",
    )
    _write(process / "phases/P1/RESULT.json", "{}\n")
    _write(
        process / "phases/P2/PHASE.yaml",
        """schema_version: 1
project_id: demo
phase_id: P2
objective: active
status: active
work_refs: []
result_refs:
  - governance/GOVERNANCE-BASELINE.json
  - phases/P2/RESULT.json
""",
    )
    _write(process / "phases/P2/RESULT.json", "{}\n")
    projection_path = process / governance_projection.GOVERNANCE_PROJECTION_REL
    _write(projection_path, "{}\n")
    process_baseline_oid = _commit_all(process, "process truth baseline")

    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": governance_projection.GOVERNANCE_PROJECTION_KIND,
        **governance_projection.build_governance_truth(process),
        "immutable_commit_roles": [
            {
                "role": "release_input_baseline",
                "repository": "release",
                "oid": release_oid,
            },
            {
                "role": "process_evidence_baseline",
                "repository": "process",
                "oid": process_baseline_oid,
            },
        ],
        "runtime_identity_roles": list(
            governance_projection.RUNTIME_IDENTITY_ROLES
        ),
    }
    payload["semantic_digest"] = governance_projection.semantic_digest(payload)
    projection_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _commit_all(process, "publish governance projection")
    return release, process, payload


def test_governance_projection_rebuilds_declared_truth_and_runtime_identity(
    tmp_path: Path,
) -> None:
    release, process, payload = _fixture(tmp_path)

    result = governance_projection.validate_governance_projection(release, process)

    assert result["decision"] == "PASS"
    assert result["errors"] == []
    assert result["runtime_identity"] == {
        "release_head": _git(release, "rev-parse", "HEAD"),
        "process_head": _git(process, "rev-parse", "HEAD"),
    }
    assert "release_head_oid" not in payload
    assert "process_head_oid" not in payload
    assert payload["active_phase_refs"] == ["process/phases/P2/PHASE.yaml"]


def test_governance_projection_blocks_phase_status_drift(tmp_path: Path) -> None:
    release, process, _payload = _fixture(tmp_path)
    phase = process / "phases/P1/PHASE.yaml"
    phase.write_text(
        phase.read_text(encoding="utf-8").replace(
            "status: completed", "status: planned"
        ),
        encoding="utf-8",
    )

    result = governance_projection.validate_governance_projection(release, process)

    assert result["decision"] == "BLOCKED"
    assert "governance projection phase_statuses differs from declared truth" in result["errors"]


def test_governance_projection_blocks_duplicate_active_phase(tmp_path: Path) -> None:
    release, process, _payload = _fixture(tmp_path)
    phase = process / "phases/P1/PHASE.yaml"
    phase.write_text(
        phase.read_text(encoding="utf-8").replace(
            "status: completed", "status: active"
        ),
        encoding="utf-8",
    )

    result = governance_projection.validate_governance_projection(release, process)

    assert result["decision"] == "BLOCKED"
    assert result["errors"] == [
        "an active PROJECT must have exactly one active declared Phase: found 2"
    ]


def test_governance_projection_blocks_repository_role_mixup(tmp_path: Path) -> None:
    release, process, payload = _fixture(tmp_path)
    roles = payload["immutable_commit_roles"]
    assert isinstance(roles, list)
    roles[0]["repository"] = "process"  # type: ignore[index]
    payload["semantic_digest"] = governance_projection.semantic_digest(payload)
    (process / governance_projection.GOVERNANCE_PROJECTION_REL).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = governance_projection.validate_governance_projection(release, process)

    assert result["decision"] == "BLOCKED"
    assert any(
        "immutable commit role release_input_baseline does not exist in process" in error
        for error in result["errors"]
    )
