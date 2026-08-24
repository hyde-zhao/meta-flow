from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from meta_flow.state import current as state_current
from meta_flow.state import projection_transaction


def _targets(prefix: str) -> dict[str, bytes]:
    return {
        "process/state/STATE.current.json": json.dumps({"state": prefix}).encode(),
        "process/STATE.md": f"state={prefix}\n".encode(),
        "process/current/CURRENT.json": json.dumps({"current": prefix}).encode(),
    }


def _authorization(plan: dict, authorization_id: str = "AUTH-CORRECT-TEST-V1") -> dict:
    return {
        "schema_version": 2,
        "kind": "state-projection-correct-authorization-v2",
        "authorization_id": authorization_id,
        "corrected_transaction_id": plan["transaction_id"],
        "drift_refs": plan["drift_refs"],
        "preimage_digests": plan["preimage_digests"],
        "old_manifest_digest": plan["old_manifest_digest"],
        "expires_at": "2999-01-01T00:00:00+00:00",
        "writer_provenance": {
            "mode": "unknown-writer",
            "writer_id": None,
            "evidence_ref": None,
            "evidence_digest": None,
            "reason": "test fixture deliberately mutates a projection outside the writer",
        },
    }


def _drifted_root(tmp_path: Path) -> dict:
    projection_transaction.apply_state_projection_transaction(tmp_path, _targets("after"))
    (tmp_path / "process/STATE.md").write_text("external drift\n", encoding="utf-8")
    plan = projection_transaction.plan_state_projection_correction(tmp_path)
    assert plan["decision"] == "READY"
    assert plan["drift_refs"] == ["process/STATE.md"]
    return plan


def test_projection_correct_reanchors_drifted_terminal_without_touching_files(
    tmp_path: Path,
) -> None:
    plan = _drifted_root(tmp_path)
    authorization = projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(
        _authorization(plan)
    )

    receipt = projection_transaction.correct_state_projection_transaction(
        tmp_path, authorization
    )

    assert receipt["decision"] == "PASS"
    assert receipt["kind"] == "StateProjectionCorrectionReceiptV2"
    assert receipt["schema_version"] == 2
    assert receipt["corrected_transaction_id"] == plan["transaction_id"]
    # 矫正不触碰投影文件本身。
    assert (tmp_path / "process/STATE.md").read_text(encoding="utf-8") == "external drift\n"
    inspection = projection_transaction.inspect_state_projection_transaction(tmp_path)
    assert inspection["decision"] == "PASS"
    assert inspection["transaction_id"] == receipt["new_transaction_id"]
    manifest = json.loads(
        (tmp_path / projection_transaction.MANIFEST_REL).read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == 2
    assert manifest["kind"] == "StateProjectionTransactionV2"
    assert manifest["correction"]["corrected_transaction_id"] == plan["transaction_id"]
    assert manifest["correction"]["authorization_id"] == "AUTH-CORRECT-TEST-V1"
    # 单次消费 receipt 落盘。
    receipt_path = (
        tmp_path / projection_transaction.CORRECTION_ROOT_REL / "AUTH-CORRECT-TEST-V1.json"
    )
    assert receipt_path.is_file()


def test_projection_correct_authorization_is_single_use(tmp_path: Path) -> None:
    plan = _drifted_root(tmp_path)
    authorization = projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(
        _authorization(plan)
    )
    projection_transaction.correct_state_projection_transaction(tmp_path, authorization)

    with pytest.raises(ValueError, match="already consumed"):
        projection_transaction.correct_state_projection_transaction(tmp_path, authorization)


def test_projection_correct_rejects_mismatched_binding(tmp_path: Path) -> None:
    plan = _drifted_root(tmp_path)
    good = _authorization(plan)
    stale = dict(good, corrected_transaction_id="0" * 32)
    authorization = projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(stale)
    with pytest.raises(ValueError, match="does not bind the current transaction"):
        projection_transaction.correct_state_projection_transaction(tmp_path, authorization)

    drifted_preimage = dict(
        good, preimage_digests={ref: "0" * 64 for ref in good["drift_refs"]}
    )
    authorization = projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(
        drifted_preimage
    )
    with pytest.raises(ValueError, match="preimage drifted"):
        projection_transaction.correct_state_projection_transaction(tmp_path, authorization)


def test_projection_correct_rejects_healthy_and_unresolved_states(tmp_path: Path) -> None:
    projection_transaction.apply_state_projection_transaction(tmp_path, _targets("after"))

    plan = projection_transaction.plan_state_projection_correction(tmp_path)
    assert plan["decision"] == "BLOCKED"
    authorization = projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(
        _authorization(
            {
                "transaction_id": plan.get("transaction_id", "0" * 32),
                "drift_refs": ["process/STATE.md"],
                "preimage_digests": {"process/STATE.md": "0" * 64},
                "old_manifest_digest": "0" * 64,
            }
        )
    )
    with pytest.raises(ValueError, match="not READY"):
        projection_transaction.correct_state_projection_transaction(tmp_path, authorization)


def test_projection_correct_authorization_validates_strictly() -> None:
    with pytest.raises(ValueError, match="expired"):
        projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(
            _authorization(
                {
                    "transaction_id": "a" * 32,
                    "drift_refs": ["process/STATE.md"],
                    "preimage_digests": {"process/STATE.md": "b" * 64},
                    "old_manifest_digest": "c" * 64,
                },
            )
            | {"expires_at": "2000-01-01T00:00:00+00:00"}
        )
    with pytest.raises(ValueError, match="fields mismatch"):
        projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping({"kind": "x"})

    plan = {
        "transaction_id": "a" * 32,
        "drift_refs": ["process/STATE.md"],
        "preimage_digests": {"process/STATE.md": "b" * 64},
        "old_manifest_digest": "c" * 64,
    }
    invalid_provenance = _authorization(plan) | {
        "writer_provenance": {
            "mode": "unknown-writer",
            "writer_id": None,
            "evidence_ref": None,
            "evidence_digest": None,
            "reason": "short",
        }
    }
    with pytest.raises(ValueError, match="unknown writer declaration"):
        projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(
            invalid_provenance
        )


def test_projection_correct_v1_authorization_remains_history_decodable() -> None:
    payload = {
        "schema_version": 1,
        "kind": "state-projection-correct-authorization-v1",
        "authorization_id": "AUTH-HISTORICAL-V1",
        "corrected_transaction_id": "a" * 32,
        "drift_refs": ["process/STATE.md"],
        "preimage_digests": {"process/STATE.md": "b" * 64},
        "old_manifest_digest": "c" * 64,
        "expires_at": "2999-01-01T00:00:00+00:00",
    }

    decoded = projection_transaction.ProjectionCorrectAuthorizationV1.from_mapping(payload)

    assert decoded.schema_version == 1
    assert decoded.authorization_id == "AUTH-HISTORICAL-V1"


def test_projection_correct_apply_rejects_historical_v1_authorization(
    tmp_path: Path,
) -> None:
    plan = _drifted_root(tmp_path)
    historical = projection_transaction.ProjectionCorrectAuthorizationV1.from_mapping(
        {
            "schema_version": 1,
            "kind": "state-projection-correct-authorization-v1",
            "authorization_id": "AUTH-HISTORICAL-APPLY-V1",
            "corrected_transaction_id": plan["transaction_id"],
            "drift_refs": plan["drift_refs"],
            "preimage_digests": plan["preimage_digests"],
            "old_manifest_digest": plan["old_manifest_digest"],
            "expires_at": "2999-01-01T00:00:00+00:00",
        }
    )

    with pytest.raises(ValueError, match="requires V2"):
        projection_transaction.correct_state_projection_transaction(
            tmp_path,
            historical,  # type: ignore[arg-type]
        )


def test_projection_correct_v2_accepts_bounded_source_writer_evidence() -> None:
    plan = {
        "transaction_id": "a" * 32,
        "drift_refs": ["process/STATE.md"],
        "preimage_digests": {"process/STATE.md": "b" * 64},
        "old_manifest_digest": "c" * 64,
    }
    payload = _authorization(plan) | {
        "writer_provenance": {
            "mode": "source-writer-evidence",
            "writer_id": "meta_flow.work.close",
            "evidence_ref": "process/works/W-001/CLOSE-RECEIPT.json",
            "evidence_digest": "d" * 64,
            "reason": None,
        }
    }

    decoded = projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(payload)

    assert decoded.writer_provenance["writer_id"] == "meta_flow.work.close"
    assert decoded.writer_provenance["evidence_digest"] == "d" * 64


def test_projection_correct_rejects_symlinked_receipt_directory(tmp_path: Path) -> None:
    plan = _drifted_root(tmp_path)
    authorization = projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(
        _authorization(plan, authorization_id="AUTH-UNSAFE-RECEIPT-V2")
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    receipt_dir = tmp_path / projection_transaction.CORRECTION_ROOT_REL
    receipt_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="receipt directory is unsafe"):
        projection_transaction.correct_state_projection_transaction(tmp_path, authorization)

    assert list(outside.iterdir()) == []


def test_projection_correct_restores_old_manifest_when_receipt_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _drifted_root(tmp_path)
    authorization = projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(
        _authorization(plan, authorization_id="AUTH-RECEIPT-FAILURE-V2")
    )
    manifest_path = tmp_path / projection_transaction.MANIFEST_REL
    manifest_before = manifest_path.read_bytes()
    receipt_path = (
        tmp_path
        / projection_transaction.CORRECTION_ROOT_REL
        / "AUTH-RECEIPT-FAILURE-V2.json"
    )
    original_replace = projection_transaction._replace_bytes

    def fail_receipt(path: Path, value: bytes) -> None:
        if path == receipt_path:
            raise OSError("injected receipt failure")
        original_replace(path, value)

    monkeypatch.setattr(projection_transaction, "_replace_bytes", fail_receipt)

    with pytest.raises(OSError, match="injected receipt failure"):
        projection_transaction.correct_state_projection_transaction(tmp_path, authorization)

    assert manifest_path.read_bytes() == manifest_before
    assert not receipt_path.exists()
    inspection = projection_transaction.inspect_state_projection_transaction(tmp_path)
    assert inspection["decision"] == "BLOCKED"
    assert "TERMINAL_GENERATION_DRIFT:process/STATE.md" in inspection["findings"]


def test_manifest_loader_accepts_correction_provenance(tmp_path: Path) -> None:
    plan = _drifted_root(tmp_path)
    authorization = projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(
        _authorization(plan)
    )
    projection_transaction.correct_state_projection_transaction(tmp_path, authorization)

    _path, payload = projection_transaction._load_manifest(tmp_path)

    assert payload is not None and payload["state"] == "COMMITTED"
    assert payload["schema_version"] == 2
    assert payload["kind"] == "StateProjectionTransactionV2"
    assert set(payload["correction"]) == projection_transaction.CORRECTION_V2_FIELDS
    assert payload["correction"]["writer_provenance"] == authorization.writer_provenance


def test_manifest_loader_keeps_hotfix_v1_correction_history_decodable(
    tmp_path: Path,
) -> None:
    plan = _drifted_root(tmp_path)
    authorization = projection_transaction.ProjectionCorrectAuthorizationV2.from_mapping(
        _authorization(plan)
    )
    projection_transaction.correct_state_projection_transaction(tmp_path, authorization)
    manifest_path = tmp_path / projection_transaction.MANIFEST_REL
    historical = json.loads(manifest_path.read_text(encoding="utf-8"))
    historical["schema_version"] = 1
    historical["kind"] = "StateProjectionTransactionV1"
    manifest_path.write_text(
        json.dumps(historical, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    _path, payload = projection_transaction._load_manifest(tmp_path)

    assert payload is not None
    assert payload["schema_version"] == 1
    assert payload["kind"] == "StateProjectionTransactionV1"
    assert payload["correction"]["authorization_id"] == authorization.authorization_id


@pytest.mark.parametrize(
    "operation",
    (
        lambda root: state_current.plan_init_current_state(root),
        lambda root: state_current.plan_migrate_legacy_state(root),
        lambda root: state_current.write_current_state(
            root,
            state_current.default_current_state(root),
            force=True,
        ),
    ),
)
def test_state_bootstrap_is_blocked_after_projection_manifest_exists(
    tmp_path: Path,
    operation,
) -> None:
    projection_transaction.apply_state_projection_transaction(tmp_path, _targets("after"))

    with pytest.raises(ValueError, match="bootstrap is forbidden"):
        operation(tmp_path)


def test_projection_inspect_reports_a_direct_core_projection_write(tmp_path: Path) -> None:
    projection_transaction.apply_state_projection_transaction(tmp_path, _targets("after"))
    (tmp_path / "process/STATE.md").write_text("bypass\n", encoding="utf-8")

    report = projection_transaction.inspect_state_projection_transaction(tmp_path)

    assert report["decision"] == "BLOCKED"
    assert "TERMINAL_GENERATION_DRIFT:process/STATE.md" in report["findings"]


def test_product_code_has_no_known_low_level_state_projection_writer_callers() -> None:
    """防止三个核心投影的已知低层 writer 再被产品模块直接调用。"""

    package_root = Path(__file__).parents[1] / "meta_flow"
    allowed = {
        Path("state/current.py"): {
            "_apply_core_state_projection",
            "_write_current_state_file",
        },
        Path("state/projection_transaction.py"): {"_replace_bytes"},
        # Work close 是持有 shared projection lock 的 typed transaction owner；
        # 这里的同名 helper 只写入已绑定 preimage 的事务 target。
        Path("work/lifecycle_transaction.py"): {"_replace_bytes"},
        # exact-file 事务（CR-074 起）与其原语 facade（CR-075 P0 起）同为只写
        # 已绑定 preimage 的事务 target 的 typed transaction owner/kernel。
        # 注：0.6.3 基线上 exact_file_transaction 的 recover 调用已使本守卫失败
        # （pre-existing，非 CR-075 回归），P0 收敛时补正白名单并留证。
        Path("execution_control/exact_file_transaction.py"): {"_replace_bytes"},
        # status-transition 聚合事务与 CURRENT/HANDOFF child adapter 同为
        # preimage-bound typed transaction writer（经 parent writer 动态分发）。
        Path("work/status_transition.py"): {"_replace_bytes"},
        Path("work/transaction_child.py"): {"_replace_bytes"},
    }
    forbidden = {
        "_apply_core_state_projection",
        "_write_current_state_file",
        "_replace_bytes",
    }
    findings: list[str] = []
    for source_path in sorted(package_root.rglob("*.py")):
        relative = source_path.relative_to(package_root)
        permitted = allowed.get(relative, set())
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(relative))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if name in forbidden and name not in permitted:
                findings.append(f"{relative}:{node.lineno}:{name}")

    assert findings == []
