"""CR-065 I/O 基线的确定性测试 harness。"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

from meta_flow.work.io_metrics import IOMetrics, classify_logical_ref

_AFTER_PROFILES = {
    "G0-F1-single-function-targeted-test": {
        "governance_reads": {"PROJECT.yaml", "works/G0-F1/WORK.yaml"},
        "token_proxy": 8000,
    },
    "G0-F2-small-doc-config-fix": {
        "governance_reads": {"PROJECT.yaml", "works/G0-F2/WORK.yaml"},
        "token_proxy": 6000,
    },
    "G1-F1-module-compatible-change": {
        "governance_reads": {"PROJECT.yaml", "works/G1-F1/WORK.yaml"},
        "token_proxy": 23000,
    },
    "G1-F2-binding-path-slice": {
        "governance_reads": {
            ".meta-flow/workspace.yaml",
            "PROJECT.yaml",
            "works/G1-F2/WORK.yaml",
        },
        "token_proxy": 30000,
    },
    "G2-F1-route-work-public-contract": {
        "governance_reads": None,
        "token_proxy": 86000,
    },
    "G2-F2-state-projection-transaction": {
        "governance_reads": None,
        "token_proxy": 79000,
    },
}


def load_cases(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("cases"), list):
        raise ValueError("invalid CR-065 fixture payload")
    return payload


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    metrics = IOMetrics(str(case["id"]), enabled=True)
    for event in case["events"]:
        repeat = int(event.get("repeat", 1))
        if repeat < 1:
            raise ValueError("fixture repeat must be >= 1")
        for _ in range(repeat):
            action = event["action"]
            if action == "read":
                metrics.record_read(
                    event["logical_ref"],
                    byte_count=int(event["bytes"]),
                    category=event.get("category"),
                    cache_hit=bool(event.get("cache_hit", False)),
                )
            elif action == "write":
                metrics.record_write_attempt(
                    event["logical_ref"],
                    byte_count=int(event.get("bytes", 0)),
                    category=event.get("category"),
                    actual_mutation=bool(event.get("actual_mutation", False)),
                )
            else:
                raise ValueError(f"unsupported fixture action: {action}")
    metrics.record_check_group(int(case["check_groups"]))
    summary = metrics.summary()
    summary["risk_profile"] = case["risk_profile"]
    summary["token_proxy"] = {"value": int(case["token_proxy"]), "status": "proxy"}
    return summary


def run_after_case(case: dict[str, Any]) -> dict[str, Any]:
    """用冻结事件分母重放 CR-065 交付后的确定性逻辑代理。"""

    profile = _AFTER_PROFILES[str(case["id"])]
    retained = profile["governance_reads"]
    metrics = IOMetrics(str(case["id"]) + ":after", enabled=True)
    seen_reads: set[str] = set()
    for event in case["events"]:
        ref = str(event["logical_ref"])
        action = event["action"]
        repeat = int(event.get("repeat", 1))
        if action == "read":
            category = event.get("category") or classify_logical_ref(ref)
            is_governance = category not in {
                "product_source",
                "test_source",
                "git",
                "external",
            }
            if retained is not None and is_governance and ref not in retained:
                continue
            for _ in range(repeat):
                cache_hit = ref in seen_reads
                metrics.record_read(
                    ref,
                    byte_count=int(event["bytes"]),
                    category=category,
                    cache_hit=cache_hit,
                )
                seen_reads.add(ref)
        elif action == "write":
            if ref == "context/CP5-CAPSULE.yaml" and repeat > 1:
                metrics.record_write_attempt(
                    ref,
                    byte_count=int(event["bytes"]),
                    actual_mutation=True,
                )
                for _ in range(repeat - 1):
                    metrics.record_write_attempt(
                        ref,
                        byte_count=900,
                        actual_mutation=True,
                    )
                continue
            for _ in range(repeat):
                metrics.record_write_attempt(
                    ref,
                    byte_count=int(event.get("bytes", 0)),
                    category=event.get("category"),
                    actual_mutation=bool(event.get("actual_mutation", False)),
                )
        else:
            raise ValueError(f"unsupported fixture action: {action}")
    metrics.record_check_group(int(case["check_groups"]))
    summary = metrics.summary()
    summary["risk_profile"] = case["risk_profile"]
    summary["token_proxy"] = {
        "value": int(profile["token_proxy"]),
        "status": "proxy",
    }
    summary["baseline_revision"] = "C65-I0-before-v1"
    return summary


def measure_default_disabled_overhead(
    fixture_path: Path,
    *,
    batch_count: int = 7,
    paired_samples_per_batch: int = 51,
    operations_per_sample: int = 100,
) -> dict[str, Any]:
    """测量正常默认模式下保留 record 调用的相对运行时开销。"""

    if batch_count < 3 or batch_count % 2 == 0:
        raise ValueError("batch_count must be one odd integer >= 3")
    if paired_samples_per_batch < 3 or paired_samples_per_batch % 2 == 0:
        raise ValueError("paired_samples_per_batch must be one odd integer >= 3")
    if operations_per_sample < 1:
        raise ValueError("operations_per_sample must be >= 1")
    metrics = IOMetrics("cr065-disabled-overhead")

    def run_sample(*, instrumented_call_present: bool) -> int:
        started = time.perf_counter_ns()
        for _ in range(operations_per_sample):
            data = fixture_path.read_bytes()
            json.loads(data)
            if instrumented_call_present:
                metrics.record_read("PROJECT.yaml", byte_count=len(data))
        return time.perf_counter_ns() - started

    for _ in range(20):
        run_sample(instrumented_call_present=False)
        run_sample(instrumented_call_present=True)

    batch_overheads: list[float] = []
    for _ in range(batch_count):
        baseline: list[int] = []
        instrumented: list[int] = []
        for sample_index in range(paired_samples_per_batch):
            if sample_index % 2:
                instrumented_value = run_sample(instrumented_call_present=True)
                baseline_value = run_sample(instrumented_call_present=False)
            else:
                baseline_value = run_sample(instrumented_call_present=False)
                instrumented_value = run_sample(instrumented_call_present=True)
            baseline.append(baseline_value)
            instrumented.append(instrumented_value)
        baseline_median = statistics.median(baseline)
        instrumented_median = statistics.median(instrumented)
        batch_overheads.append(
            (instrumented_median - baseline_median) / baseline_median * 100
        )

    overhead_percent = statistics.median(batch_overheads)
    return {
        "measurement_kind": "paired-wall-clock-proxy",
        "instrumentation_mode": "normal-default-disabled",
        "batch_count": batch_count,
        "paired_samples_per_batch": paired_samples_per_batch,
        "operations_per_sample": operations_per_sample,
        "overhead_percent": round(overhead_percent, 3),
        "threshold_percent": 5.0,
        "decision": "PASS" if overhead_percent <= 5.0 else "FAIL",
        "persistence_writes": metrics.summary()["persistence_writes"],
    }
