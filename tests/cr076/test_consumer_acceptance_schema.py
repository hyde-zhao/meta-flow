"""CAC-01/08：schema 模块（加载路由/尺寸/解析/variant 校验/journey 键与覆盖/RBI）。"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from conftest import J24, result_document
from jsonschema import Draft7Validator

from meta_flow.ingestion.consumer_acceptance_schema import (
    BUNDLE_IDENTITY_SCHEMA_NAME,
    CONSUMER_RESULT_SCHEMA_NAME,
    COVERAGE_INSUFFICIENT,
    JOURNEY_DUPLICATE_KEY,
    NATURAL_LANGUAGE_UNSUPPORTED,
    RESULT_OVERSIZE,
    RESULT_UNREADABLE,
    SCHEMA_INVALID,
    SCHEMA_LOAD_FAILED,
    ConsumerAcceptanceBlocked,
    check_journey_coverage,
    check_journey_unique_keys,
    ensure_result_within_size,
    load_bundle_identity_schema,
    load_design_schema,
    parse_result_document,
    validate_consumer_result,
)

HEX64 = re.compile(r"^[a-f0-9]{64}$")


class TestLoadDesignSchema:
    def test_loads_via_process_route_and_caches(self, routed):
        release, _ = routed
        loaded = load_design_schema(Path(release), CONSUMER_RESULT_SCHEMA_NAME)
        assert loaded.name == CONSUMER_RESULT_SCHEMA_NAME
        assert HEX64.match(loaded.digest)
        assert load_design_schema(Path(release), CONSUMER_RESULT_SCHEMA_NAME) is loaded  # (path,mtime) 缓存

    def test_unknown_name_blocks(self, routed):
        release, _ = routed
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            load_design_schema(Path(release), "no-such-schema")
        assert excinfo.value.code == SCHEMA_LOAD_FAILED

    def test_missing_file_blocks(self, routed):
        release, process = routed
        (process / "docs" / "design" / "CR-076" / "schemas" / f"{CONSUMER_RESULT_SCHEMA_NAME}.schema.json").unlink()
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            load_design_schema(Path(release), CONSUMER_RESULT_SCHEMA_NAME)
        assert excinfo.value.code == SCHEMA_LOAD_FAILED


class TestSizeAndParse:
    def test_oversize_result_blocks_before_parse(self):
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            ensure_result_within_size(b"x" * (256 * 1024 + 1))
        assert excinfo.value.code == RESULT_OVERSIZE

    def test_non_json_blocks_as_natural_language(self):
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            parse_result_document("看起来成功了，全部通过".encode())
        assert excinfo.value.code == NATURAL_LANGUAGE_UNSUPPORTED

    def test_damaged_json_blocks(self):
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            parse_result_document(b'{"kind": ')
        assert excinfo.value.code == RESULT_UNREADABLE

    def test_non_dict_top_level_blocks(self):
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            parse_result_document(b"[1,2,3]")
        assert excinfo.value.code == RESULT_UNREADABLE


class TestValidateConsumerResult:
    def test_valid_document_passes(self, routed):
        release, _ = routed
        schema = load_design_schema(Path(release), CONSUMER_RESULT_SCHEMA_NAME)
        findings = validate_consumer_result(result_document("R-X", "source-candidate-replay"), schema)
        assert findings.ok, findings.errors

    def test_missing_required_field_blocks(self, routed):
        release, _ = routed
        schema = load_design_schema(Path(release), CONSUMER_RESULT_SCHEMA_NAME)
        document = result_document("R-X", "source-candidate-replay")
        del document["authorization"]
        findings = validate_consumer_result(document, schema)
        assert not findings.ok and findings.code == SCHEMA_INVALID

    def test_variant_cross_swap_blocks_at_schema_layer(self, routed):
        release, _ = routed
        schema = load_design_schema(Path(release), CONSUMER_RESULT_SCHEMA_NAME)
        # 错装字段组在 schema 层拒绝（schema P1 allOf 已锁死 top×artifact 交叉；
        # VARIANT_CROSS_MISMATCH 为导入器侧防御码，合法 schema 文档不可触达）
        document = result_document("R-X", "installed-artifact-replay")
        document["artifact"] = result_document("R-Y", "source-candidate-replay")["artifact"]
        findings = validate_consumer_result(document, schema)
        assert not findings.ok and findings.code == SCHEMA_INVALID
        assert any("artifact.variant" in error for error in findings.errors)


class TestJourneyChecks:
    def _payload(self):
        return {"execution": {"journeys": copy.deepcopy(J24)}}

    def test_duplicate_journey_key_blocks(self):
        payload = self._payload()
        rows = payload["execution"]["journeys"]
        rows[1]["journey"], rows[1]["round"], rows[1]["case"] = rows[0]["journey"], rows[0]["round"], rows[0]["case"]
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            check_journey_unique_keys(payload)
        assert excinfo.value.code == JOURNEY_DUPLICATE_KEY

    def test_missing_journey_cell_blocks(self):
        payload = self._payload()
        rows = payload["execution"]["journeys"]
        for row in rows:  # W4 三行整体改挂 W5 名下 → journey×case 缺 W4 三格
            if row["journey"] == "W4":
                row["journey"] = "W5"
        with pytest.raises(ConsumerAcceptanceBlocked) as excinfo:
            check_journey_coverage(payload)
        assert excinfo.value.code == COVERAGE_INSUFFICIENT

    def test_full_matrix_passes(self):
        check_journey_unique_keys(self._payload())
        check_journey_coverage(self._payload())


class TestBundleIdentitySchema:
    def test_root_is_oneof_seven_frozen_defs(self, routed):
        _, process = routed
        schema = json.loads(
            (process / "docs" / "design" / "CR-076" / "schemas" / f"{BUNDLE_IDENTITY_SCHEMA_NAME}.schema.json").read_bytes()
        )
        assert set(schema["$defs"]) == {
            "ImmutableBaseBundleManifestV1",
            "TransportReceiptV1",
            "InstallationReceiptV1",
            "ConsumerAcceptanceAttestationV1",
            "PublicationReceiptV1",
            "PublishedVerifiedReceiptV1",
            "BundleLineageIndexV1",
        }
        assert len(schema["oneOf"]) == 7

    def test_bundle_schema_helper_loads(self, routed):
        release, _ = routed
        loaded = load_bundle_identity_schema(Path(release))
        assert loaded.name == BUNDLE_IDENTITY_SCHEMA_NAME
        assert Draft7Validator(loaded.document).is_valid({"schema_version": 1, "kind": "UnknownV1"}) is False
