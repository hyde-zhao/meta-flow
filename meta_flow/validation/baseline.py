"""Phase green baseline lifecycle（STORY-CR075-S06，MF-GAP-04）。

`meta-flow phase-baseline plan|apply|check|invalidate|inspect`：
- baseline 绑定 phase_id + fingerprint 集（source/command/environment/
  provider/manifest，与 S04 共享归属算法）
- apply 走 exact-file typed transaction（target namespace=system，P0 成果）
- baseline bytes append-only（修订 version+1，永不改写历史）
- full 失败与 baseline 对比输出五类归属（既存漂移/环境漂移/provider
  漂移/新回归/不可归属）
- 读取走四态 typed loader（missing/occupied/malformed/ok），损坏文件
  fail-closed 为 BASELINE_FILE_MALFORMED，不得被静默当作「无基线」
  rebaseline（V4 门禁整改项 2）；symlink/非 regular 占用 fail-closed 为
  BASELINE_TARGET_OCCUPIED（V5 整改阻断三：不得当 missing）；loader 校验
  kind/phase_id 绑定/scope_digest/fingerprint 六维/entry digest/时间戳
  状态一致性（V5 整改阻断三：错误身份基线不得产出归属结论）；writer
  （plan/invalidation）构造的 READY payload 必须通过同一 loader 自洽终检；
  history 快照携带 entry_digest 供读取端篡改检测
- V6 整改（DQ-075-C7-V5-01 第 1/2 项）：process_root→baseline 的全部
  路径组件逐级检查——祖先 symlink 与越界段 typed occupied（禁止跟随
  symlink 逃逸读取 process_root 外内容），resolved containment 兜底；
  scope_digest 按 phase_ref+entries 重算严格绑定，空/重复 entries、
  current_fingerprint 六维缺维、非 mapping plan target、读取 OSError
  一律稳定 typed BLOCKED，任何路径不暴露 traceback
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.execution_control.exact_file_transaction import (
    ExactFileAuthorizationV1,
    ExactFileTargetV1,
    apply_exact_file_plan,
    build_exact_file_plan,
)

SCHEMA_VERSION = 1
BASELINE_FILENAME = "BASELINE.json"

_EXISTING_DRIFT_CODES = {
    "SOURCE_FINGERPRINT_DRIFT",
    "PROFILE_DRIFT",
    "SOURCE_MANIFEST_DRIFT",
}
_ENVIRONMENT_DRIFT_CODES = {"ENVIRONMENT_DRIFT"}
_PROVIDER_DRIFT_CODES = {"PROVIDER_IDENTITY_DRIFT"}

# V5 整改阻断三：payload 身份与指纹完备性常量。kind 与六维 fingerprint
# 键集和 PhaseGreenBaselineV1.as_dict / check_baseline 归属矩阵共享——
# 缺任一维的基线没有完整身份，归属会静默降级为 NEW_REGRESSION。
_BASELINE_KIND = "PhaseGreenBaselineV1"
_REQUIRED_FINGERPRINT_KEYS = (
    "source_fingerprint",
    "command_identity",
    "environment",
    "provider_identity_digest",
    "source_manifest_digest",
    "profile_digest",
)


@dataclass(frozen=True)
class PhaseGreenBaselineV1:
    """Phase 绿基线（evidence 性质；修订 append version+1）。"""

    schema_version: int
    phase_id: str
    version: int
    scope_digest: str
    fingerprint: dict[str, str]
    entries: tuple[dict[str, str], ...]
    created_at: str = ""
    invalidated_at: str = ""
    invalidation_reasons: tuple[str, ...] = ()
    # V3 整改：revision append-only 历史。每次失效把当前代快照 append 进
    # history；rebaseline 只能原样携带（前缀不变），不得删除或改写。
    history: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "PhaseGreenBaselineV1",
            "phase_id": self.phase_id,
            "version": self.version,
            "scope_digest": self.scope_digest,
            "fingerprint": dict(sorted(self.fingerprint.items())),
            "entries": [dict(entry) for entry in self.entries],
            "created_at": self.created_at,
            "invalidated_at": self.invalidated_at,
            "invalidation_reasons": list(self.invalidation_reasons),
            "history": [dict(item) for item in self.history],
        }


def baseline_ref(phase_ref: str) -> str:
    parts = phase_ref.strip("/").split("/")
    return "/".join([*parts[:-1], BASELINE_FILENAME]) if parts[-1].endswith(".yaml") else "/".join(
        [*parts, BASELINE_FILENAME]
    )


def _is_hex64(value: Any) -> bool:
    """64 位小写 hex 判定（scope_digest / entry_digest 形态）。"""

    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _valid_history_item(item: Any) -> bool:
    """V4 门禁整改项 2：history item schema + entry_digest 篡改检测。

    合法形态与 plan_invalidation append 的快照一致：dict 且含 version
    （int>0）、scope_digest（64 位小写 hex）、created_at/invalidated_at
    （str）、invalidation_reasons（list[str]）。每项必须携带 entry_digest
    且与重算值一致——改字段值/删字段后 digest 不再匹配；不含 digest 的
    历史项一律不接受（fail-closed）。
    """

    if not isinstance(item, dict) or "entry_digest" not in item:
        return False
    if type(item.get("version")) is not int or item["version"] <= 0:
        return False
    if not _is_hex64(item.get("scope_digest")):
        return False
    if not isinstance(item.get("created_at"), str) or not isinstance(
        item.get("invalidated_at"), str
    ):
        return False
    reasons = item.get("invalidation_reasons")
    if not isinstance(reasons, list) or any(
        not isinstance(reason, str) for reason in reasons
    ):
        return False
    content = {key: value for key, value in item.items() if key != "entry_digest"}
    return item["entry_digest"] == canonical_digest(content)


def _scope_digest_for(phase_ref: str, entries: list[dict[str, Any]]) -> str:
    """scope_digest 唯一构造口径（writer/reader 共用，V6 严格绑定）。

    plan_baseline 与 typed loader 必须经由同一函数重算——两侧任何形态
    分叉都会让合法基线被判 malformed（writer-reader 自洽由构造统一保证）。
    """

    return canonical_digest(
        {"phase_ref": phase_ref, "entries": [dict(entry) for entry in entries]}
    )


def _path_occupied(process_root: Path, rel_ref: str) -> bool:
    """V6 整改第 1 项：process_root→baseline 全部路径组件安全预检。

    任一祖先组件是 symlink 即视为占用（跟随它会逃逸到 process_root 之外
    读取/写入）；路径含空段或越界段（``..``）同样占用。只做 lstat 级
    逐级检查，绝不跟随 symlink——「检查路径」本身不得成为越界读取。
    """

    parts = Path(rel_ref).parts
    if any(part in ("", ".", "..") for part in parts):
        return True
    current = process_root
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _valid_baseline_payload(payload: Any, *, phase_id: str | None = None) -> bool:
    """基线文件 schema 校验（typed，fail-closed）。

    V4 门禁整改项 2 建立基础 schema 面；V5 整改阻断三补齐身份与完备性：
    - kind 必须等于 PhaseGreenBaselineV1（错误 kind 不得被当绿基线消费）
    - phase_id 提供时必须与 phase_ref 严格相等（错误 phase 的基线文件
      放错目录不得产出归属结论）
    - 顶层 scope_digest 必须是 64 位小写 hex
    - fingerprint 六维键全部必填且为非空 str（check_baseline 归属矩阵
      逐一比较这六键；缺维即静默降级）
    - entries result_digest 必须是 64 位小写 hex
    - created_at/invalidated_at 为 str、invalidation_reasons 为 list[str]，
      且失效状态自洽：invalidated_at 非空 ⇔ invalidation_reasons 非空
    """

    if not isinstance(payload, dict):
        return False
    # type is int 同时排除 bool（True == 1 会误过相等比较）。
    if type(payload.get("schema_version")) is not int:
        return False
    if payload["schema_version"] != SCHEMA_VERSION:
        return False
    if payload.get("kind") != _BASELINE_KIND:
        return False
    if phase_id is not None and payload.get("phase_id") != phase_id:
        return False
    if not isinstance(payload.get("phase_id"), str) or not payload["phase_id"]:
        return False
    version = payload.get("version")
    if type(version) is not int or version <= 0:
        return False
    if not _is_hex64(payload.get("scope_digest")):
        return False
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return False
    # V6 整改第 2 项：空基线与重复 check_id 都没有合法绿集语义。
    if not entries:
        return False
    check_ids = []
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        if not isinstance(entry.get("check_id"), str) or not entry["check_id"]:
            return False
        if not _is_hex64(entry.get("result_digest")):
            return False
        check_ids.append(entry["check_id"])
    if len(set(check_ids)) != len(check_ids):
        return False
    # V6 整改第 2 项：scope_digest 重算严格绑定——篡改 entries（改值/
    # 重排/增删项）而不同步重算 scope_digest 的文件一律 malformed。
    if payload["scope_digest"] != _scope_digest_for(payload["phase_id"], entries):
        return False
    fingerprint = payload.get("fingerprint")
    if not isinstance(fingerprint, dict):
        return False
    if any(not isinstance(value, str) or not value for value in fingerprint.values()):
        return False
    if any(key not in fingerprint for key in _REQUIRED_FINGERPRINT_KEYS):
        return False
    if not isinstance(payload.get("created_at"), str):
        return False
    invalidated_at = payload.get("invalidated_at")
    if not isinstance(invalidated_at, str):
        return False
    reasons = payload.get("invalidation_reasons")
    if not isinstance(reasons, list) or any(
        not isinstance(reason, str) for reason in reasons
    ):
        return False
    # 失效状态一致性：只允许「未失效（双空）」或「已失效（双非空）」。
    if bool(invalidated_at) != bool(reasons):
        return False
    history = payload.get("history", [])
    if not isinstance(history, list) or any(
        not _valid_history_item(item) for item in history
    ):
        return False
    return True


def load_baseline_state(
    process_root: Path, phase_ref: str
) -> tuple[str, dict[str, Any] | None]:
    """四态 typed loader：区分 missing / occupied / malformed（V5 整改阻断三）。

    返回值：
    - ("missing", None)：路径不存在
    - ("occupied", None)：symlink 或目录/fifo 等非 regular file 占用——
      不是 missing：当作 missing 会产出新建 READY，随后 read_bytes/
      exact-file 写入会跟随 symlink 逃逸 process_root；V6 起祖先组件
      symlink 与越界段（``..``）同样 occupied（不做任何越界读取）
    - ("malformed", None)：JSON 解析失败 / 顶层非 dict / schema 校验失败
      （含 kind/phase_id 绑定/scope_digest 重算绑定/fingerprint 六维/
      digest 形态/时间戳状态一致性）；V6 起读取 OSError（权限/IO 竞态）
      同样 fail-closed 为 malformed——不可读的基线不得产出任何结论
    - ("ok", payload)：通过校验的原始 payload
    """

    ref = baseline_ref(phase_ref)
    # V6 整改第 1 项：先查祖先组件再触碰最终路径——中间目录是 symlink
    # 时 path.is_symlink() 为 False 而 exists() 为 True，直接 read 会越界。
    if _path_occupied(process_root, ref):
        return ("occupied", None)
    path = process_root / ref
    if path.is_symlink():
        return ("occupied", None)
    if not path.exists():
        return ("missing", None)
    if not path.is_file():
        return ("occupied", None)
    try:
        # resolved containment 兜底：逐组件检查之外的其他逃逸形态（如
        # process_root 本身携带 symlink 前缀）在此拦截，仍归 occupied。
        path.resolve().relative_to(process_root.resolve())
    except ValueError:
        return ("occupied", None)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        # 含 UnicodeDecodeError（非法字节）、JSONDecodeError（截断/损坏）
        # 与读取 OSError（权限/IO 竞态）——统一 fail-closed。
        return ("malformed", None)
    if not _valid_baseline_payload(payload, phase_id=phase_ref):
        return ("malformed", None)
    return ("ok", payload)


def load_baseline(process_root: Path, phase_ref: str) -> dict[str, Any] | None:
    """兼容只读入口：仅供展示层消费，禁止用于 gate 判定路径。

    V4 门禁整改项 2 后 missing 与 malformed 都退化为 None；V5 整改后
    occupied 同样退化为 None；gate 判定必须使用 load_baseline_state
    四态 loader（本文件内调用点已全部迁移；meta_flow 内无其他调用方）。
    """

    _, payload = load_baseline_state(process_root, phase_ref)
    return payload


def plan_baseline(
    process_root: Path,
    *,
    phase_ref: str,
    entries: list[dict[str, str]],
    fingerprint: dict[str, str],
) -> dict[str, Any]:
    """零写收集当前绿集并产出冻结计划。"""

    if not phase_ref.strip("/"):
        return _blocked("PHASE_REF_INVALID")
    normalized = tuple(
        {"check_id": str(item.get("check_id") or ""), "result_digest": str(item.get("result_digest") or "")}
        for item in sorted(entries, key=lambda item: str(item.get("check_id") or ""))
        if str(item.get("check_id") or "")
    )
    if not normalized:
        return _blocked("BASELINE_ENTRIES_EMPTY")
    # V5 整改阻断三（反例 C·输入收紧）：writer 不得接受空/非 hex 的
    # result_digest——否则产出的 payload 会被自家 typed loader 判
    # malformed，writer-reader 不自洽。
    if any(not _is_hex64(entry["result_digest"]) for entry in normalized):
        return _blocked("BASELINE_ENTRY_DIGEST_INVALID")
    # V5 整改阻断三（反例 A·输入收紧）：fingerprint 六维必填且非空 str。
    # 缺维基线没有完整身份，check_baseline 归属矩阵会静默降级。
    if not isinstance(fingerprint, dict) or any(
        not isinstance(fingerprint.get(key), str) or not fingerprint[key]
        for key in _REQUIRED_FINGERPRINT_KEYS
    ):
        return _blocked("BASELINE_FINGERPRINT_INCOMPLETE")
    # 路径安全：phase_ref 拒绝绝对路径/越界段/symlink 占用。
    candidate = Path(phase_ref)
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        return _blocked("PHASE_REF_UNSAFE")
    phase_path = process_root / phase_ref
    if phase_path.is_symlink() or not phase_path.is_file():
        return _blocked("PHASE_FILE_MISSING")
    scope_digest = _scope_digest_for(phase_ref, [dict(entry) for entry in normalized])
    # V4 门禁整改项 2：typed loader 先行——损坏基线（JSON 坏/顶层非 dict/
    # schema 违规/history 篡改）不得被静默当作「无基线」rebaseline 出
    # version=1 的新建 READY（会抹掉真实历史）。
    # V5 整改阻断三（反例 B）：occupied（symlink/非 regular 占用）不是
    # missing，typed BLOCKED，不得产出新建 READY。
    state, existing = load_baseline_state(process_root, phase_ref)
    if state == "occupied":
        return _blocked("BASELINE_TARGET_OCCUPIED")
    if state == "malformed":
        return _blocked("BASELINE_FILE_MALFORMED")
    # 5e 整改：valid baseline 不可原位覆盖；只有已失效基线才允许 rebaseline
    # （version+1）。历史保留模型：单一 BASELINE.json 承载当前代，失效代以
    # version 单调递增 + invalidated_at/reasons append 记录，不可回退重写。
    if existing and not existing.get("invalidated_at"):
        return _blocked("BASELINE_ALREADY_ACTIVE")
    carried_history: tuple[dict[str, Any], ...] = ()
    if existing:
        # append-only 守卫：history schema 与 entry_digest 篡改检测已由
        # typed loader 覆盖，此处原样携带前缀，不得静默重置。
        carried_history = tuple(dict(item) for item in existing.get("history") or [])
    next_version = (int(existing.get("version") or 0) + 1) if existing else 1
    payload = PhaseGreenBaselineV1(
        SCHEMA_VERSION,
        phase_ref,
        next_version,
        scope_digest,
        dict(sorted(fingerprint.items())),
        normalized,
        history=carried_history,
    ).as_dict()
    # V5 整改阻断三（反例 C·自洽终检）：writer 生成的任何 READY payload 都
    # 必须能立即通过同一 typed loader；不过检说明 writer 自身缺陷，
    # fail-closed 而不是写出 reader 自拒的文件。
    if not _valid_baseline_payload(payload, phase_id=phase_ref):
        return _blocked("BASELINE_PLAN_PAYLOAD_INVALID")
    after_bytes = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    ref = baseline_ref(phase_ref)
    # V6 整改第 2 项：读取 OSError（权限/IO 竞态）稳定 typed BLOCKED，
    # 不得向上抛 traceback。
    try:
        before = (
            (process_root / ref).read_bytes() if (process_root / ref).is_file() else b""
        )
    except OSError:
        return _blocked("BASELINE_READ_ERROR")
    import hashlib

    target = ExactFileTargetV1(
        ref,
        bool(before),
        hashlib.sha256(before).hexdigest(),
        after_bytes,
        hashlib.sha256(after_bytes).hexdigest(),
        namespace="system",
    )
    exact_plan = build_exact_file_plan(
        "phase-baseline.apply",
        (target,),
        semantic_binding_digest=canonical_digest(
            {"phase_ref": phase_ref, "scope_digest": scope_digest}
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "PhaseBaselinePlanV1",
        "decision": "READY",
        "phase_ref": phase_ref,
        "baseline_ref": ref,
        "scope_digest": scope_digest,
        "entries": [dict(entry) for entry in normalized],
        "exact_plan": exact_plan.as_dict(),
        "exact_plan_digest": exact_plan.plan_digest,
        "mutation_count": 0,
    }


def apply_baseline(
    process_root: Path,
    *,
    plan_payload: dict[str, Any],
    authorization: ExactFileAuthorizationV1,
) -> dict[str, Any]:
    """typed apply：exact-file 事务（system namespace target）。"""

    exact_payload = dict(plan_payload.get("exact_plan") or {})
    targets = []
    import base64

    # V6 整改第 2 项：非 mapping plan target / 缺必备键 / 非法 base64
    # 一律稳定 typed BLOCKED，不得在 item["ref"] 或 b64decode 处抛
    # traceback。
    for item in exact_payload.get("targets", []):
        if not isinstance(item, dict):
            return _blocked("PLAN_TARGET_INVALID")
        try:
            targets.append(
                ExactFileTargetV1(
                    str(item["ref"]),
                    bool(item["before_exists"]),
                    str(item["before_digest"]),
                    base64.b64decode(str(item["after_bytes_b64"]), validate=True),
                    str(item["after_digest"]),
                    namespace=str(item.get("namespace") or "system"),
                )
            )
        except (KeyError, TypeError, ValueError):
            return _blocked("PLAN_TARGET_INVALID")
    exact_plan = build_exact_file_plan(
        "phase-baseline.apply",
        tuple(targets),
        semantic_binding_digest=str(exact_payload.get("semantic_binding_digest") or ""),
    )
    if exact_plan.plan_digest != plan_payload.get("exact_plan_digest"):
        return _blocked("PLAN_DIGEST_MISMATCH")
    authorization.validate_for(exact_plan)
    return apply_exact_file_plan(process_root, exact_plan, authorization)


def check_baseline(
    process_root: Path,
    *,
    phase_ref: str,
    current_fingerprint: dict[str, str],
    failing_checks: list[str],
) -> dict[str, Any]:
    """现集 vs baseline：diff + 五类归属（与 S04 共享算法）。"""

    # V4 门禁整改项 2：typed loader 先行——entries 元素被篡改为非 dict
    # （list/str/int）时不再在下方 entry.get 处抛 AttributeError 暴露
    # traceback，而是 typed BLOCKED。
    # V5 整改阻断三（反例 A/B）：occupied typed BLOCKED；身份/指纹不完备
    # 的 payload 在 loader 层即判 malformed，不得产出归属结论。
    state, baseline = load_baseline_state(process_root, phase_ref)
    if state == "occupied":
        return _blocked("BASELINE_TARGET_OCCUPIED")
    if state == "malformed":
        return _blocked("BASELINE_FILE_MALFORMED")
    if baseline is None:
        return _blocked("BASELINE_MISSING")
    # V6 整改第 2 项：current_fingerprint 六维必填——缺维调用不得进入
    # 归属矩阵（缺维比较被跳过会让漂移静默漏检、归属错误降级）。
    # 置于 baseline 状态判定之后：missing/occupied/malformed 语义优先。
    if not isinstance(current_fingerprint, dict) or any(
        not isinstance(current_fingerprint.get(key), str)
        or not current_fingerprint[key]
        for key in _REQUIRED_FINGERPRINT_KEYS
    ):
        return _blocked("CURRENT_FINGERPRINT_INCOMPLETE")
    if baseline.get("invalidated_at"):
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "PhaseBaselineCheckV1",
            "decision": "NEEDS_REVIEW",
            "reason_codes": ["BASELINE_INVALIDATED"],
            "invalidation_reasons": list(baseline.get("invalidation_reasons") or []),
            "mutation_count": 0,
        }
    reasons: list[str] = []
    stored = dict(baseline.get("fingerprint") or {})
    comparisons = (
        ("SOURCE_FINGERPRINT_DRIFT", "source_fingerprint"),
        ("COMMAND_IDENTITY_DRIFT", "command_identity"),
        ("ENVIRONMENT_DRIFT", "environment"),
        ("PROVIDER_IDENTITY_DRIFT", "provider_identity_digest"),
        ("SOURCE_MANIFEST_DRIFT", "source_manifest_digest"),
        ("PROFILE_DRIFT", "profile_digest"),
    )
    for code, key in comparisons:
        if key in current_fingerprint and str(current_fingerprint[key]) != str(
            stored.get(key, current_fingerprint[key])
        ):
            reasons.append(code)
    reason_set = set(reasons)
    green = {str(entry.get("check_id") or "") for entry in baseline.get("entries") or []}
    failing = {str(item) for item in failing_checks if str(item)}
    regression = sorted(failing & green)
    outside = sorted(failing - green)
    # V3 整改：归属矩阵--
    #   绿转失败 + 源/manifest/profile 漂移 -> EXISTING_SOURCE_DRIFT；
    #   绿转失败 + 仅环境漂移 -> ENVIRONMENT_DRIFT；
    #   绿转失败 + provider 漂移（无源/环境漂移）-> PROVIDER_DRIFT；
    #   绿转失败且 fingerprint 不漂移 -> NEW_REGRESSION（baseline 证明同
    #   指纹下该检查曾绿，无外部漂移可解释即为新回归）；
    #   baseline 外失败 -> UNATTRIBUTABLE（无历史证据，不得称新回归）。
    attribution: dict[str, list[str]] = {}
    if regression:
        if reason_set & _EXISTING_DRIFT_CODES:
            attribution["EXISTING_SOURCE_DRIFT"] = regression
        elif reason_set & _ENVIRONMENT_DRIFT_CODES:
            attribution["ENVIRONMENT_DRIFT"] = regression
        elif reason_set & _PROVIDER_DRIFT_CODES:
            attribution["PROVIDER_DRIFT"] = regression
        else:
            attribution["NEW_REGRESSION"] = regression
    if outside:
        attribution["UNATTRIBUTABLE"] = sorted(
            {*outside, *attribution.get("UNATTRIBUTABLE", [])}
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "PhaseBaselineCheckV1",
        # 5d 整改：存在 failing 不得无条件 PASS。
        "decision": "FAILINGS_PRESENT" if failing else "PASS",
        "phase_ref": phase_ref,
        "baseline_version": int(baseline.get("version") or 0),
        "drift_reason_codes": sorted(reason_set),
        "failing_count": len(failing),
        "failing_not_in_baseline": outside,
        "attribution": {key: value for key, value in attribution.items() if value},
        "mutation_count": 0,
    }


def plan_invalidation(
    process_root: Path,
    *,
    phase_ref: str,
    reasons: list[str],
    at: str,
) -> dict[str, Any]:
    """5a 整改：失效走 typed plan（零写；apply 需 exact-file authorization）。"""

    # V4 门禁整改项 2：typed loader 先行（同 plan_baseline/check_baseline）。
    # V5 整改阻断三：occupied 同样 typed BLOCKED（不得当 missing）。
    state, baseline = load_baseline_state(process_root, phase_ref)
    if state == "occupied":
        return _blocked("BASELINE_TARGET_OCCUPIED")
    if state == "malformed":
        return _blocked("BASELINE_FILE_MALFORMED")
    if baseline is None:
        return _blocked("BASELINE_MISSING")
    if baseline.get("invalidated_at"):
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "PhaseBaselineInvalidationPlanV1",
            "decision": "NO_CHANGE",
            "idempotent": True,
            "version": int(baseline.get("version") or 0),
            "mutation_count": 0,
        }
    payload = dict(baseline)
    # V3 整改：失效即把当前代快照 append 进 history（只增长、不回改）。
    # V4 门禁整改项 2：快照携带 entry_digest（对去 digest 后内容重算），
    # 读取端（typed loader）重算比对实现篡改检测；history schema 已由
    # typed loader 保证，此处不再重复守卫。
    dying_reasons = sorted(set(str(item) for item in reasons))
    snapshot: dict[str, Any] = {
        "version": int(baseline.get("version") or 0),
        "scope_digest": str(baseline.get("scope_digest") or ""),
        "created_at": str(baseline.get("created_at") or ""),
        "invalidated_at": at,
        "invalidation_reasons": dying_reasons,
    }
    snapshot["entry_digest"] = canonical_digest(snapshot)
    payload["history"] = [
        *(dict(item) for item in baseline.get("history") or []),
        snapshot,
    ]
    payload["version"] = int(baseline.get("version") or 0) + 1
    payload["invalidated_at"] = at
    payload["invalidation_reasons"] = dying_reasons
    # V5 整改阻断三（反例 C·自洽终检，同 plan_baseline）：失效修订后的
    # payload 也必须通过同一 typed loader（invalidated_at 与 reasons 的
    # 状态一致性由此兜底），否则 fail-closed 不写出。
    if not _valid_baseline_payload(payload, phase_id=phase_ref):
        return _blocked("BASELINE_PLAN_PAYLOAD_INVALID")
    ref = baseline_ref(phase_ref)
    import hashlib

    # V6 整改第 2 项：读取 OSError（loader 通过后的权限/IO 竞态）稳定
    # typed BLOCKED，不得向上抛 traceback。
    try:
        before = (process_root / ref).read_bytes()
    except OSError:
        return _blocked("BASELINE_READ_ERROR")
    after_bytes = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    target = ExactFileTargetV1(
        ref,
        True,
        hashlib.sha256(before).hexdigest(),
        after_bytes,
        hashlib.sha256(after_bytes).hexdigest(),
        namespace="system",
    )
    exact_plan = build_exact_file_plan(
        "phase-baseline.invalidate",
        (target,),
        semantic_binding_digest=canonical_digest(
            {"phase_ref": phase_ref, "invalidated_at": at, "reasons": sorted(set(reasons))}
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "PhaseBaselineInvalidationPlanV1",
        "decision": "READY",
        "phase_ref": phase_ref,
        "baseline_ref": ref,
        "next_version": payload["version"],
        "invalidation_reasons": sorted(set(str(item) for item in reasons)),
        "exact_plan": exact_plan.as_dict(),
        "exact_plan_digest": exact_plan.plan_digest,
        "mutation_count": 0,
    }


def apply_invalidation(
    process_root: Path,
    *,
    plan_payload: dict[str, Any],
    authorization: ExactFileAuthorizationV1,
) -> dict[str, Any]:
    """typed apply：与 baseline apply 同一 exact-file 事务内核（可恢复）。"""

    import base64

    exact_payload = dict(plan_payload.get("exact_plan") or {})
    targets = []
    # V6 整改第 2 项：同 apply_baseline——非 mapping target/缺键/非法
    # base64 稳定 typed BLOCKED，不抛 traceback。
    for item in exact_payload.get("targets", []):
        if not isinstance(item, dict):
            return _blocked("PLAN_TARGET_INVALID")
        try:
            targets.append(
                ExactFileTargetV1(
                    str(item["ref"]),
                    bool(item["before_exists"]),
                    str(item["before_digest"]),
                    base64.b64decode(str(item["after_bytes_b64"]), validate=True),
                    str(item["after_digest"]),
                    namespace=str(item.get("namespace") or "system"),
                )
            )
        except (KeyError, TypeError, ValueError):
            return _blocked("PLAN_TARGET_INVALID")
    exact_plan = build_exact_file_plan(
        "phase-baseline.invalidate",
        tuple(targets),
        semantic_binding_digest=str(exact_payload.get("semantic_binding_digest") or ""),
    )
    if exact_plan.plan_digest != plan_payload.get("exact_plan_digest"):
        return _blocked("PLAN_DIGEST_MISMATCH")
    authorization.validate_for(exact_plan)
    return apply_exact_file_plan(process_root, exact_plan, authorization)


def inspect_baseline(process_root: Path, *, phase_ref: str) -> dict[str, Any]:
    """审计视图（零 mutation）。"""

    # V4 门禁整改项 2：审计视图同样消费 typed loader——损坏文件报
    # BASELINE_FILE_MALFORMED，不得误导为 BASELINE_MISSING。
    # V5 整改阻断三：occupied（symlink/非 regular 占用）typed BLOCKED。
    state, baseline = load_baseline_state(process_root, phase_ref)
    if state == "occupied":
        return _blocked("BASELINE_TARGET_OCCUPIED")
    if state == "malformed":
        return _blocked("BASELINE_FILE_MALFORMED")
    if baseline is None:
        return _blocked("BASELINE_MISSING")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "PhaseBaselineInspectV1",
        "decision": "PASS",
        "baseline": baseline,
        "mutation_count": 0,
    }


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "decision": "BLOCKED",
        "reason_codes": [reason],
        "mutation_count": 0,
    }


def baseline_main(argv: list[str] | None = None) -> int:
    """CLI：``meta-flow phase-baseline plan|apply|check|invalidate|inspect``。"""

    parser = argparse.ArgumentParser(prog="meta-flow phase-baseline")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("command", choices=("plan", "apply", "check", "invalidate", "inspect"))
    parser.add_argument("--phase-ref", required=True)
    parser.add_argument("--entries", type=Path, default=None)
    parser.add_argument("--fingerprint", type=Path, default=None)
    parser.add_argument("--current-fingerprint", type=Path, default=None)
    parser.add_argument("--failing-checks", type=Path, default=None)
    parser.add_argument("--reasons", default="")
    parser.add_argument("--at", default="")
    parser.add_argument("--plan", type=Path, default=None)
    parser.add_argument("--authorization", type=Path, default=None)
    parsed = parser.parse_args(argv or [])
    from meta_flow.project.process_route import require_process_route

    try:
        process_root = require_process_route(parsed.project_root.resolve()).process_root
    except Exception as exc:
        print(
            json.dumps(
                {"decision": "BLOCKED", "reason_codes": ["PROCESS_ROUTE_UNHEALTHY"],
                 "detail": f"{type(exc).__name__}: {exc}", "mutation_count": 0}
            )
        )
        return 2

    def _load_json(path: Path | None) -> dict[str, Any]:
        if path is None:
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        if parsed.command == "plan":
            payload = plan_baseline(
                process_root,
                phase_ref=parsed.phase_ref,
                entries=list(_load_json(parsed.entries).get("entries", [])),
                fingerprint=dict(_load_json(parsed.fingerprint)),
            )
        elif parsed.command == "apply":
            from meta_flow.execution_control.exact_file_transaction import (
                ExactFileAuthorizationV1 as _Auth,
            )

            plan_payload = _load_json(parsed.plan)
            authorization = _Auth.from_mapping(_load_json(parsed.authorization))
            payload = apply_baseline(
                process_root, plan_payload=plan_payload, authorization=authorization
            )
        elif parsed.command == "check":
            payload = check_baseline(
                process_root,
                phase_ref=parsed.phase_ref,
                current_fingerprint=dict(_load_json(parsed.current_fingerprint)),
                failing_checks=list(_load_json(parsed.failing_checks).get("failing", [])),
            )
        elif parsed.command == "invalidate":
            if parsed.plan is not None and parsed.authorization is not None:
                plan_payload = _load_json(parsed.plan)
                authorization = ExactFileAuthorizationV1.from_mapping(
                    _load_json(parsed.authorization)
                )
                payload = apply_invalidation(
                    process_root, plan_payload=plan_payload, authorization=authorization
                )
            elif parsed.plan is None and parsed.authorization is None:
                # 零写 plan 阶段：产出 typed 失效计划（apply 需重新带 --plan/--authorization）。
                payload = plan_invalidation(
                    process_root,
                    phase_ref=parsed.phase_ref,
                    reasons=[item for item in parsed.reasons.split(",") if item],
                    at=parsed.at,
                )
            else:
                payload = _blocked("INVALIDATION_REQUIRES_PLAN_AND_AUTHORIZATION")
        else:
            payload = inspect_baseline(process_root, phase_ref=parsed.phase_ref)
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"decision": "BLOCKED", "detail": f"{type(exc).__name__}: {exc}", "mutation_count": 0}
            )
        )
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    decision = str(payload.get("decision") or "")
    return 0 if decision in {"PASS", "READY", "NO_CHANGE"} else 2
