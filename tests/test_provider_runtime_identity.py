from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from meta_flow import cli
from meta_flow.installation import identity


def _version_identity(*reasons: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "ProviderRuntimeIdentityV2",
        "distribution_name": "meta-flow",
        "distribution_version": "0.6.1",
        "module_path": "/provider/meta_flow/__init__.py",
        "distribution_path": "/provider",
        "editable": False,
        "identity_source": "installed-artifact",
        "source_root": None,
        "source_commit": "a" * 40,
        "source_dirty": False,
        "source_tree_digest": "b" * 64,
        "artifact_sha256": "c" * 64,
        "installed_files_digest": "d" * 64,
        "capability_profile_digest": "e" * 64,
        "provider_receipt_path": None,
        "provider_receipt_digest": None,
        "schema_versions": {"provider_runtime_identity": 2},
        "source_discovery": {"decision": "PASS", "reason_codes": []},
        "release_readiness": {
            "decision": "BLOCKED" if reasons else "PASS",
            "reason_codes": list(reasons),
        },
        "worktree_clean": None,
        "exact_commit_delivery": not reasons,
        "identity_digest": "f" * 64,
    }


class _FakeDistribution:
    def __init__(self, root: Path, *, direct_url: dict[str, object]) -> None:
        self.version = "0.5.2"
        self.files = [
            Path("meta_flow/__init__.py"),
            Path("delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml"),
        ]
        self._root = root
        self._direct_url = direct_url

    def read_text(self, name: str) -> str | None:
        if name == "direct_url.json":
            return json.dumps(self._direct_url)
        return None

    def locate_file(self, item: object) -> Path:
        return self._root / Path(str(item))


def test_runtime_identity_is_not_owned_by_current_working_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    unrelated = tmp_path / "unrelated"
    (unrelated / "delivery" / "scripts").mkdir(parents=True)
    (unrelated / "delivery" / "scripts" / "install.py").write_text(
        "raise RuntimeError('wrong provider')\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(unrelated)

    observed = identity.observe_provider_runtime_identity()

    assert observed["source_root"] != str(unrelated)
    assert observed["module_path"].endswith("meta_flow/__init__.py")
    assert observed["identity_source"] == "editable-checkout"


def test_explicit_source_must_own_the_imported_module(tmp_path: Path) -> None:
    observed = identity.observe_provider_runtime_identity(
        environment={"META_FLOW_SOURCE": str(tmp_path)},
    )

    assert observed["source_discovery"]["decision"] == "BLOCKED"
    assert "EXPLICIT_SOURCE_MODULE_MISMATCH" in observed["source_discovery"][
        "reason_codes"
    ]


def test_explicit_source_cannot_claim_a_provider_through_a_parent_directory(
    tmp_path: Path,
) -> None:
    imported = tmp_path / "provider" / "meta_flow" / "__init__.py"
    imported.parent.mkdir(parents=True)
    imported.write_text("\n", encoding="utf-8")

    observed = identity.observe_provider_runtime_identity(
        module_path=imported,
        environment={"META_FLOW_SOURCE": str(tmp_path)},
    )

    assert observed["source_root"] is None
    assert observed["source_discovery"]["decision"] == "BLOCKED"
    assert "EXPLICIT_SOURCE_MODULE_MISMATCH" in observed["source_discovery"][
        "reason_codes"
    ]


def test_editable_direct_url_must_own_the_imported_module(
    tmp_path: Path,
    monkeypatch,
) -> None:
    imported = tmp_path / "actual" / "meta_flow" / "__init__.py"
    imported.parent.mkdir(parents=True)
    imported.write_text("\n", encoding="utf-8")
    claimed = tmp_path / "claimed"
    claimed.mkdir()
    distribution = _FakeDistribution(
        tmp_path,
        direct_url={"url": claimed.as_uri(), "dir_info": {"editable": True}},
    )
    monkeypatch.setattr(identity.metadata, "distribution", lambda _name: distribution)

    observed = identity.observe_provider_runtime_identity(
        module_path=imported,
        environment={},
    )

    assert observed["source_root"] is None
    assert observed["source_discovery"]["decision"] == "BLOCKED"
    assert "DIRECT_URL_EDITABLE_MODULE_MISMATCH" in observed["source_discovery"][
        "reason_codes"
    ]


def test_non_editable_archive_identity_is_release_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    site_packages = tmp_path / "venv" / "site-packages"
    module_path = site_packages / "meta_flow" / "__init__.py"
    contract = site_packages / "delivery" / "doc" / "PUBLIC-OPERATION-CONTRACTS.yaml"
    module_path.parent.mkdir(parents=True)
    contract.parent.mkdir(parents=True)
    module_path.write_text('__version__ = "0.5.2"\n', encoding="utf-8")
    contract.write_text("{}\n", encoding="utf-8")
    archive_digest = "a" * 64
    capability_digest = sha256(contract.read_bytes()).hexdigest()
    installed_payload_digest = identity._canonical_digest(
        {
            "delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml": capability_digest,
            "meta_flow/__init__.py": sha256(module_path.read_bytes()).hexdigest(),
        }
    )
    receipt_path = tmp_path / "provider-receipt.json"
    receipt = {
        "schema_version": 1,
        "kind": "ProviderArtifactReceiptV1",
        "distribution_name": "meta-flow",
        "distribution_version": "0.5.2",
        "source_commit": "b" * 40,
        "source_dirty": False,
        "source_tree_digest": "c" * 64,
        "artifact_filename": "meta_flow-0.5.2-py3-none-any.whl",
        "artifact_sha256": archive_digest,
        "capability_profile_digest": capability_digest,
        "installed_payload_digest": installed_payload_digest,
        "release_qualifying": True,
    }
    receipt["receipt_digest"] = sha256(
        json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    distribution = _FakeDistribution(
        site_packages,
        direct_url={
            "url": (tmp_path / "meta_flow-0.5.2-py3-none-any.whl").as_uri(),
            "archive_info": {"hash": f"sha256={archive_digest}"},
        },
    )
    monkeypatch.setattr(identity.metadata, "distribution", lambda _name: distribution)

    observed = identity.observe_provider_runtime_identity(
        module_path=module_path,
        environment={"META_FLOW_PROVIDER_RECEIPT": str(receipt_path)},
    )

    assert observed["editable"] is False
    assert observed["identity_source"] == "installed-artifact"
    assert observed["artifact_sha256"] == archive_digest
    assert observed["source_commit"] == "b" * 40
    assert observed["provider_receipt_digest"] == receipt["receipt_digest"]
    assert observed["installed_files_digest"]
    assert observed["release_readiness"] == {"decision": "PASS", "reason_codes": []}
    assert observed["exact_commit_delivery"] is True


def test_release_receipt_attests_artifact_when_uv_omits_direct_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    site_packages = tmp_path / "venv" / "site-packages"
    module_path = site_packages / "meta_flow" / "__init__.py"
    contract = site_packages / "delivery" / "doc" / "PUBLIC-OPERATION-CONTRACTS.yaml"
    dist_info = site_packages / "meta_flow-0.5.2.dist-info"
    module_path.parent.mkdir(parents=True)
    contract.parent.mkdir(parents=True)
    dist_info.mkdir(parents=True)
    module_path.write_text('__version__ = "0.5.2"\n', encoding="utf-8")
    contract.write_text("{}\n", encoding="utf-8")
    (dist_info / "uv_cache.json").write_text('{"generated": true}\n', encoding="utf-8")
    capability_digest = sha256(contract.read_bytes()).hexdigest()
    installed_payload_digest = identity._canonical_digest(
        {
            "delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml": capability_digest,
            "meta_flow/__init__.py": sha256(module_path.read_bytes()).hexdigest(),
        }
    )
    receipt = {
        "schema_version": 1,
        "kind": "ProviderArtifactReceiptV1",
        "distribution_name": "meta-flow",
        "distribution_version": "0.5.2",
        "source_commit": "b" * 40,
        "source_dirty": False,
        "source_tree_digest": "c" * 64,
        "artifact_filename": "meta_flow-0.5.2-py3-none-any.whl",
        "artifact_sha256": "a" * 64,
        "capability_profile_digest": capability_digest,
        "installed_payload_digest": installed_payload_digest,
        "release_qualifying": True,
    }
    receipt["receipt_digest"] = sha256(
        json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    receipt_path = tmp_path / "provider-receipt.json"
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    distribution = _FakeDistribution(site_packages, direct_url={})
    distribution.files.append(Path("meta_flow-0.5.2.dist-info/uv_cache.json"))
    monkeypatch.setattr(identity.metadata, "distribution", lambda _name: distribution)

    observed = identity.observe_provider_runtime_identity(
        module_path=module_path,
        environment={"META_FLOW_PROVIDER_RECEIPT": str(receipt_path)},
    )

    assert observed["artifact_sha256"] == "a" * 64
    assert observed["identity_source"] == "installed-artifact-receipt"
    assert observed["installed_files_digest"] == installed_payload_digest
    assert observed["release_readiness"] == {"decision": "PASS", "reason_codes": []}
    assert observed["exact_commit_delivery"] is True


def test_non_editable_venv_inside_git_checkout_is_not_misclassified_as_editable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "consumer"
    (repo / ".git").mkdir(parents=True)
    site_packages = repo / ".venv" / "lib" / "python3.11" / "site-packages"
    module_path = site_packages / "meta_flow" / "__init__.py"
    contract = site_packages / "delivery" / "doc" / "PUBLIC-OPERATION-CONTRACTS.yaml"
    module_path.parent.mkdir(parents=True)
    contract.parent.mkdir(parents=True)
    module_path.write_text('__version__ = "0.5.2"\n', encoding="utf-8")
    contract.write_text("{}\n", encoding="utf-8")
    distribution = _FakeDistribution(
        site_packages,
        direct_url={
            "url": (tmp_path / "meta_flow-0.5.2-py3-none-any.whl").as_uri(),
            "archive_info": {"hash": f"sha256={'a' * 64}"},
        },
    )
    monkeypatch.setattr(identity.metadata, "distribution", lambda _name: distribution)

    observed = identity.observe_provider_runtime_identity(
        module_path=module_path,
        environment={},
    )

    assert observed["editable"] is False
    assert observed["source_root"] is None
    assert observed["identity_source"] == "installed-artifact"


def test_checkout_identity_reads_version_from_the_target_checkout(
    tmp_path: Path,
) -> None:
    delivery = tmp_path / "delivery"
    (delivery / "rules").mkdir(parents=True)
    (delivery / "doc").mkdir(parents=True)
    (delivery / "rules" / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    (delivery / "doc" / "RULES-SEMANTIC-INVENTORY.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "meta-flow"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
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
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    observed = identity.observe_checkout_source_identity(tmp_path)

    assert observed["version"] == "9.9.9"


def test_release_admission_rejects_editable_and_detects_digest_drift() -> None:
    observed = identity.observe_provider_runtime_identity()

    release = identity.evaluate_provider_runtime_admission(observed, mode="release")
    development = identity.evaluate_provider_runtime_admission(
        observed,
        mode="development",
    )
    drifted = identity.evaluate_provider_runtime_admission(
        observed,
        mode="development",
        expected_identity_digest="f" * 64,
    )

    assert release["decision"] == "BLOCKED"
    assert "EDITABLE_INSTALL" in release["reason_codes"]
    assert development["decision"] == "READY"
    assert development["release_qualifying"] is False
    assert drifted["decision"] == "BLOCKED"
    assert drifted["reason_codes"] == ["PROVIDER_IDENTITY_DRIFT"]


def test_external_consumer_mutation_is_blocked_for_dirty_editable_provider(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv("META_FLOW_PROVIDER_MODE", raising=False)

    with pytest.raises(SystemExit) as raised:
        cli._guard_provider_mutation(
            "project",
            ["phase-transition", "apply", "--project-root", str(tmp_path)],
        )
    assert raised.value.code == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload["decision"] == "BLOCKED"
    assert payload["mutation_count"] == 0
    assert payload["operation"] == "project.phase-transition"


def test_development_override_is_non_release_and_read_only_plan_is_ungated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("META_FLOW_PROVIDER_MODE", "development")

    cli._guard_provider_mutation(
        "project",
        ["phase-transition", "apply", "--project-root", str(tmp_path)],
    )
    cli._guard_provider_mutation(
        "project",
        ["phase-transition", "--dry-run", "--project-root", str(tmp_path)],
    )


def test_invalid_provider_mode_fails_without_entering_domain_operation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("META_FLOW_PROVIDER_MODE", "unsafe")

    with pytest.raises(SystemExit) as raised:
        cli._guard_provider_mutation(
            "project",
            ["phase-transition", "apply", "--project-root", str(tmp_path)],
        )
    assert raised.value.code == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload["reason_codes"] == ["INVALID_PROVIDER_MODE"]


def test_provider_mutation_classifier_covers_apply_append_and_direct_status() -> None:
    assert cli._is_provider_mutation("project", ["phase-metadata", "apply"])
    assert cli._is_provider_mutation("event", ["append", "--ledger", "events.ndjson"])
    assert not cli._is_provider_mutation("work", ["start", "--work-id", "W-1"])
    assert cli._is_provider_mutation("work", ["start", "--work-id", "W-1", "--apply"])
    assert cli._is_provider_mutation("work", ["usage-add", "--work-id", "W-1"])
    assert cli._is_provider_mutation("context", ["build", "--project-root", "."])
    assert cli._is_provider_mutation("cp", ["ledger-append", "--project-root", "."])
    assert cli._is_provider_mutation("quality", ["init", "--project-root", "."])
    assert cli._is_provider_mutation("workspace", ["push", "--project-root", "."])
    assert cli._is_provider_mutation("work", ["close-recover", "--authorization-id", "A1"])
    assert cli._is_provider_mutation(
        "project",
        ["phase-transition", "apply", "--project-root", "."],
    )
    assert cli._is_provider_mutation(
        "project",
        ["phase-metadata", "recover", "--project-root", "."],
    )
    assert cli._is_provider_mutation("cr", ["status-sync-rollback"])
    assert cli._is_provider_mutation("ask-user", ["human-gate", "--output", "gate.md"])
    assert cli._is_provider_mutation("policy", ["check", "--write-default"])
    assert cli._is_provider_mutation("eval", ["run", "--out", "run"])
    assert cli._is_provider_mutation(
        "story",
        ["revalidate-cp6", "--action", "recover"],
    )
    assert not cli._is_provider_mutation("project", ["phase-transition", "--dry-run"])
    assert not cli._is_provider_mutation("project", ["phase-transition", "plan"])
    assert not cli._is_provider_mutation("project", ["phase-metadata", "inspect"])
    assert not cli._is_provider_mutation("state", ["projection-refresh"])
    assert cli._is_provider_mutation("state", ["projection-refresh", "--apply"])
    assert not cli._is_provider_mutation("ask-user", ["human-gate"])
    assert not cli._is_provider_mutation("workspace", ["push", "--dry-run"])
    assert not cli._is_provider_mutation("eval", ["validate", "--eval", "fixture"])
    assert not cli._is_provider_mutation(
        "story",
        ["revalidate-cp6", "--action", "inspect"],
    )
    assert not cli._is_provider_mutation("check", ["cr-tracking"])


def test_receipt_path_classifier_distinguishes_missing_not_found_and_unsafe(
    tmp_path: Path,
) -> None:
    regular = tmp_path / "receipt.json"
    regular.write_text("{}\n", encoding="utf-8")
    directory = tmp_path / "receipt-dir"
    directory.mkdir()
    symlink = tmp_path / "receipt-link.json"
    symlink.symlink_to(regular)
    broken = tmp_path / "broken-receipt.json"
    broken.symlink_to(tmp_path / "absent-target.json")
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)

    assert identity.classify_provider_receipt_path("") == (
        None,
        "PROVIDER_RECEIPT_MISSING",
    )
    assert identity.classify_provider_receipt_path(
        str(tmp_path / "absent.json")
    )[1] == "PROVIDER_RECEIPT_NOT_FOUND"
    assert identity.classify_provider_receipt_path(str(directory))[1] == (
        "PROVIDER_RECEIPT_UNSAFE"
    )
    assert identity.classify_provider_receipt_path(str(symlink))[1] == (
        "PROVIDER_RECEIPT_UNSAFE"
    )
    assert identity.classify_provider_receipt_path(str(broken))[1] == (
        "PROVIDER_RECEIPT_UNSAFE"
    )
    assert identity.classify_provider_receipt_path(
        str(linked_parent / regular.name)
    )[1] == "PROVIDER_RECEIPT_UNSAFE"
    assert identity.classify_provider_receipt_path(str(regular)) == (
        regular,
        None,
    )


@pytest.mark.parametrize(
    ("reason", "expected"),
    (
        ("PROVIDER_RECEIPT_MISSING", "PROVIDER_RECEIPT_MISSING"),
        ("PROVIDER_RECEIPT_NOT_FOUND", "PROVIDER_RECEIPT_BLOCKED"),
        ("PROVIDER_RECEIPT_UNSAFE", "PROVIDER_RECEIPT_BLOCKED"),
        ("PROVIDER_RECEIPT_INVALID", "PROVIDER_RECEIPT_BLOCKED"),
        (
            "PROVIDER_RECEIPT_DISTRIBUTION_VERSION_MISMATCH",
            "PROVIDER_RECEIPT_BLOCKED",
        ),
        ("SOURCE_DIRTY", "IDENTITY_INCOMPLETE"),
    ),
)
def test_provider_runtime_status_has_a_closed_diagnostic_taxonomy(
    reason: str,
    expected: str,
) -> None:
    observed = _version_identity(reason)
    admission = {"decision": "BLOCKED", "reason_codes": [reason]}

    assert identity.provider_runtime_status(observed, admission) == expected


def test_provider_runtime_status_is_ready_only_when_both_inputs_pass() -> None:
    assert identity.provider_runtime_status(
        _version_identity(),
        {"decision": "READY", "reason_codes": []},
    ) == "READY"
    assert identity.provider_runtime_status(
        _version_identity(),
        {"decision": "BLOCKED", "reason_codes": ["PROVIDER_IDENTITY_DRIFT"]},
    ) == "IDENTITY_INCOMPLETE"


@pytest.mark.parametrize(
    ("environment", "expected_reason"),
    (
        ({}, "PROVIDER_RECEIPT_MISSING"),
        (
            {"META_FLOW_PROVIDER_RECEIPT": "missing-provider-receipt.json"},
            "PROVIDER_RECEIPT_NOT_FOUND",
        ),
    ),
)
def test_runtime_observation_preserves_receipt_path_reason(
    environment: dict[str, str],
    expected_reason: str,
) -> None:
    observed = identity.observe_provider_runtime_identity(environment=environment)

    assert expected_reason in observed["release_readiness"]["reason_codes"]


def test_invalid_and_symlink_receipts_fail_closed_without_rewriting(
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json\n", encoding="utf-8")
    link = tmp_path / "receipt.json"
    link.symlink_to(invalid)
    before = invalid.read_bytes()

    invalid_observation = identity.observe_provider_runtime_identity(
        environment={"META_FLOW_PROVIDER_RECEIPT": str(invalid)},
    )
    symlink_observation = identity.observe_provider_runtime_identity(
        environment={"META_FLOW_PROVIDER_RECEIPT": str(link)},
    )

    assert "PROVIDER_RECEIPT_INVALID" in invalid_observation[
        "release_readiness"
    ]["reason_codes"]
    assert "PROVIDER_RECEIPT_UNSAFE" in symlink_observation[
        "release_readiness"
    ]["reason_codes"]
    assert invalid.read_bytes() == before


@pytest.mark.parametrize(
    ("reasons", "expected"),
    (
        ((), "READY"),
        (("PROVIDER_RECEIPT_MISSING",), "PROVIDER_RECEIPT_MISSING"),
        (("PROVIDER_RECEIPT_NOT_FOUND",), "PROVIDER_RECEIPT_BLOCKED"),
        (
            ("PROVIDER_RECEIPT_DISTRIBUTION_VERSION_MISMATCH",),
            "PROVIDER_RECEIPT_BLOCKED",
        ),
    ),
)
def test_version_cli_consumes_the_shared_runtime_status(
    reasons: tuple[str, ...],
    expected: str,
) -> None:
    observed = _version_identity(*reasons)
    admission = {
        "decision": "BLOCKED" if reasons else "READY",
        "reason_codes": list(reasons),
    }
    output = StringIO()

    with (
        patch(
            "meta_flow.installation.identity.observe_provider_runtime_identity",
            return_value=observed,
        ),
        patch(
            "meta_flow.installation.identity.evaluate_provider_runtime_admission",
            return_value=admission,
        ),
        patch("sys.stdout", output),
    ):
        cli._run_version(["--format", "json"])

    payload = json.loads(output.getvalue())
    assert payload["status"] == expected
