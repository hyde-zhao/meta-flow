"""CR-051 source/artifact Git 目标策略的纯函数真相源。

该模块不导入 Git、worktree、journal 或持久化实现。生命周期执行器与聚合器
必须共同消费这里的 mode/ref 规则，避免调用方把自声明 mode 当成信任根。
"""

from __future__ import annotations

import re

SOURCE_MODE = "source-default"
ARTIFACT_MODE = "shared-artifact-project-first"

_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CR_ID = re.compile(r"^CR-[0-9]+$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_REF = re.compile(r"^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]*$")
_PROTECTED_ARTIFACT_BRANCHES = {
    "default",
    "develop",
    "development",
    "main",
    "master",
    "trunk",
}


def canonical_project_id(project_id: str) -> str:
    if (
        not isinstance(project_id, str)
        or not _PROJECT.fullmatch(project_id)
        or project_id.startswith("-")
        or ".." in project_id
    ):
        raise ValueError("project_id_invalid")
    return project_id.lower()


def canonical_cr_id(cr_id: str) -> str:
    if not isinstance(cr_id, str) or not _CR_ID.fullmatch(cr_id):
        raise ValueError("cr_id_invalid")
    return cr_id.lower()


def canonical_slug(slug: str) -> str:
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ValueError("slug_invalid")
    return slug


def canonical_artifact_integration_ref(project_id: str) -> str:
    return f"refs/heads/projects/{canonical_project_id(project_id)}/integration"


def canonical_artifact_active_ref(project_id: str, cr_id: str, slug: str) -> str:
    return (
        f"refs/heads/projects/{canonical_project_id(project_id)}/cr/"
        f"{canonical_cr_id(cr_id)}-{canonical_slug(slug)}"
    )


def canonical_source_active_ref(cr_id: str, slug: str) -> str:
    return f"refs/heads/cr/{canonical_cr_id(cr_id)}-{canonical_slug(slug)}"


def is_canonical_head_ref(ref: object) -> bool:
    if not isinstance(ref, str) or not _REF.fullmatch(ref):
        return False
    return not (".." in ref or "//" in ref or "@{" in ref or ref.endswith(("/", ".", ".lock")))


def is_protected_artifact_ref(ref: object) -> bool:
    if not isinstance(ref, str) or not ref.startswith("refs/heads/"):
        return False
    branch = ref.removeprefix("refs/heads/").strip("/").lower()
    return branch in _PROTECTED_ARTIFACT_BRANCHES or branch.startswith("control/")


def target_policy_errors(
    *,
    leg_kind: object,
    mode: object,
    project_id: str,
    cr_id: str,
    base_ref: object,
    target_ref: object,
    active_ref: object,
) -> tuple[str, ...]:
    """独立重算 published leg 的 mode/ref 策略并返回稳定错误码。"""

    errors: list[str] = []
    try:
        project = canonical_project_id(project_id)
        normalized_cr = canonical_cr_id(cr_id)
    except ValueError as error:
        return (str(error),)
    if not all(is_canonical_head_ref(ref) for ref in (base_ref, target_ref, active_ref)):
        errors.append("target_ref_invalid")
        return tuple(errors)

    if leg_kind == "artifact":
        expected_integration = canonical_artifact_integration_ref(project)
        expected_prefix = f"refs/heads/projects/{project}/cr/{normalized_cr}-"
        if mode != ARTIFACT_MODE:
            errors.append("artifact_mode_mismatch")
        if base_ref != expected_integration or target_ref != expected_integration:
            errors.append("artifact_integration_target_mismatch")
        if not isinstance(active_ref, str) or not active_ref.startswith(expected_prefix):
            errors.append("artifact_active_ref_mismatch")
        if any(is_protected_artifact_ref(ref) for ref in (base_ref, target_ref, active_ref)):
            errors.append("artifact_protected_ref_forbidden")
    elif leg_kind == "source":
        expected_prefix = f"refs/heads/cr/{normalized_cr}-"
        if mode != SOURCE_MODE:
            errors.append("source_mode_mismatch")
        if base_ref != target_ref:
            errors.append("source_default_target_mismatch")
        if not isinstance(active_ref, str) or not active_ref.startswith(expected_prefix):
            errors.append("source_active_ref_mismatch")
        if isinstance(base_ref, str) and base_ref.startswith("refs/heads/projects/"):
            errors.append("source_project_namespace_forbidden")
    else:
        errors.append("leg_kind_invalid")
    return tuple(dict.fromkeys(errors))


__all__ = [
    "ARTIFACT_MODE",
    "SOURCE_MODE",
    "canonical_artifact_active_ref",
    "canonical_artifact_integration_ref",
    "canonical_cr_id",
    "canonical_project_id",
    "canonical_slug",
    "canonical_source_active_ref",
    "is_canonical_head_ref",
    "is_protected_artifact_ref",
    "target_policy_errors",
]
