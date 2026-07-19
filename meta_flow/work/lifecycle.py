"""Work 状态转移与 expected-status 原子更新。"""

from __future__ import annotations

import os
from pathlib import Path

from meta_flow.project.scale import dump_yaml
from meta_flow.work.model import Work, load_work, with_status, work_path

ALLOWED_TRANSITIONS = {
    "planned": {"active", "cancelled"},
    "active": {"paused", "blocked", "ready_for_review", "ready_for_verification", "completed", "cancelled"},
    "paused": {"active", "blocked", "cancelled"},
    "blocked": {"active", "cancelled"},
    "ready_for_review": {"active", "ready_for_verification", "cancelled"},
    "ready_for_verification": {"active", "completed", "cancelled"},
    "completed": {"archived"},
    "cancelled": {"archived"},
    "archived": set(),
}


def transition_work(work: Work, new_status: str, *, result_ref: str = "") -> Work:
    allowed = ALLOWED_TRANSITIONS.get(work.status, set())
    if new_status not in allowed:
        raise ValueError(f"invalid Work transition: {work.status} -> {new_status}")
    if new_status == "completed" and not (result_ref or work.result_ref):
        raise ValueError("completed Work requires result_ref")
    return with_status(work, new_status, result_ref=result_ref)


def update_work_status(
    process_root: Path,
    work_id: str,
    *,
    expected_status: str,
    new_status: str,
    result_ref: str = "",
) -> Work:
    current = load_work(process_root, work_id)
    if current.status != expected_status:
        raise ValueError(
            f"Work status changed: expected {expected_status}, current {current.status}"
        )
    updated = transition_work(current, new_status, result_ref=result_ref)
    path = work_path(process_root, work_id)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"temporary Work path already exists: {temporary}")
    try:
        temporary.write_text(dump_yaml(updated.as_dict()) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
    return load_work(process_root, work_id)
