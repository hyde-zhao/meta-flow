"""发布导致 OID 合法变化后，对 paused Work 执行受权原子关闭。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from meta_flow.execution_control.contract import canonical_digest
from meta_flow.project.model import is_safe_ref
from meta_flow.project.process_route import (
    require_process_route,
    require_project_process_route,
    resolve_process_ref,
)
from meta_flow.project.scale import load_yaml_object
from meta_flow.repository.publisher import observe_repo
from meta_flow.work.handoff import handoff_path, load_handoff
from meta_flow.work.lifecycle_transaction import (
    WorkClosePlanV1,
    WorkCloseReceiptV1,
    WorkPublicationBindingV1,
    apply_work_close,
    plan_work_close,
)
from meta_flow.work.model import Work, load_work
from meta_flow.work.scope import check_scope
from meta_flow.workspace.git_sync import query_exact_remote_ref, run_git

PUBLICATION_RECEIPT_KIND = "WorkPublicationReceiptV1"
PUBLICATION_RECEIPT_V2_KIND = "WorkPublicationReceiptV2"
PUBLICATION_AUTHORIZATION_KIND = "work-publication-close-authorization-v1"
_OID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TRANSACTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_BRANCH_REF_RE = re.compile(r"^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
_REPOSITORY_FIELDS = {
    "paused_oid",
    "published_oid",
    "remote",
    "ref",
    "changed_paths",
    "pending_paths",
    "commit_authorization_ids",
    "push_authorization_ids",
}
_PRIOR_WORK_COVERAGE_FIELDS = {
    "coverage_type",
    "paths",
    "owner_work_ref",
    "owner_scope_digest",
    "owner_result_ref",
    "owner_terminal_status",
}
_CANDIDATE_SET_COVERAGE_FIELDS = {
    "coverage_type",
    "paths",
    "candidate_set_digest",
    "commit_authorization_ids",
    "push_authorization_ids",
}
_RECOVERY_WORK_FIELDS = {"work_ref", "scope_digest", "required_status"}


def _digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _safe_id(value: str, *, label: str) -> str:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")
    return value


def _safe_transaction_id(value: str, *, label: str) -> str:
    if not _TRANSACTION_ID_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")
    return value


def _safe_oid(value: str, *, label: str) -> str:
    if not _OID_RE.fullmatch(value):
        raise ValueError(f"{label} must be one lowercase full OID")
    return value


def _safe_paths(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of safe paths")
    normalized = tuple(value)
    if len(normalized) != len(set(normalized)) or tuple(sorted(normalized)) != normalized:
        raise ValueError(f"{label} must be unique and sorted")
    if any(not is_safe_ref(item) for item in normalized):
        raise ValueError(f"{label} contains an unsafe path")
    return normalized


def _safe_authorization_ids(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of authorization IDs")
    normalized = tuple(value)
    if len(normalized) != len(set(normalized)) or tuple(sorted(normalized)) != normalized:
        raise ValueError(f"{label} must be unique and sorted")
    for item in normalized:
        _safe_id(item, label=label)
    return normalized


@dataclass(frozen=True, slots=True)
class PublishedRepositoryV1:
    paused_oid: str
    published_oid: str
    remote: str
    ref: str
    changed_paths: tuple[str, ...]
    pending_paths: tuple[str, ...]
    commit_authorization_ids: tuple[str, ...]
    push_authorization_ids: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, role: str) -> PublishedRepositoryV1:
        if set(payload) != _REPOSITORY_FIELDS:
            raise ValueError(f"publication receipt {role} repository fields mismatch")
        paused_oid = _safe_oid(str(payload.get("paused_oid") or ""), label=f"{role}.paused_oid")
        published_oid = _safe_oid(
            str(payload.get("published_oid") or ""), label=f"{role}.published_oid"
        )
        remote = str(payload.get("remote") or "")
        ref = str(payload.get("ref") or "")
        if (
            not remote
            or remote.startswith("-")
            or any(char in remote for char in "\x00\r\n")
            or not _SAFE_BRANCH_REF_RE.fullmatch(ref)
            or ".." in ref
            or ref.endswith("/")
        ):
            raise ValueError(f"publication receipt {role} remote/ref is invalid")
        changed_paths = _safe_paths(payload.get("changed_paths"), label=f"{role}.changed_paths")
        pending_paths = _safe_paths(payload.get("pending_paths"), label=f"{role}.pending_paths")
        commit_ids = _safe_authorization_ids(
            payload.get("commit_authorization_ids"),
            label=f"{role}.commit_authorization_ids",
        )
        push_ids = _safe_authorization_ids(
            payload.get("push_authorization_ids"),
            label=f"{role}.push_authorization_ids",
        )
        changed = paused_oid != published_oid
        if changed and (not changed_paths or not commit_ids or not push_ids):
            raise ValueError(
                f"publication receipt {role} changed OID requires paths and commit/push authorization IDs"
            )
        if not changed and (changed_paths or commit_ids or push_ids):
            raise ValueError(
                f"publication receipt {role} unchanged OID must not claim publication mutations"
            )
        return cls(
            paused_oid=paused_oid,
            published_oid=published_oid,
            remote=remote,
            ref=ref,
            changed_paths=changed_paths,
            pending_paths=pending_paths,
            commit_authorization_ids=commit_ids,
            push_authorization_ids=push_ids,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "paused_oid": self.paused_oid,
            "published_oid": self.published_oid,
            "remote": self.remote,
            "ref": self.ref,
            "changed_paths": list(self.changed_paths),
            "pending_paths": list(self.pending_paths),
            "commit_authorization_ids": list(self.commit_authorization_ids),
            "push_authorization_ids": list(self.push_authorization_ids),
        }


@dataclass(frozen=True, slots=True)
class PublicationPathCoverageV2:
    coverage_type: str
    paths: tuple[str, ...]
    owner_work_ref: str = ""
    owner_scope_digest: str = ""
    owner_result_ref: str = ""
    owner_terminal_status: str = ""
    candidate_set_digest: str = ""
    commit_authorization_ids: tuple[str, ...] = ()
    push_authorization_ids: tuple[str, ...] = ()

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        role: str,
        repository: PublishedRepositoryV1,
    ) -> PublicationPathCoverageV2:
        coverage_type = str(payload.get("coverage_type") or "")
        paths = _safe_paths(payload.get("paths"), label=f"{role}.path_coverage.paths")
        if not paths:
            raise ValueError(f"{role} publication path coverage paths must not be empty")
        if coverage_type == "prior_work":
            if set(payload) != _PRIOR_WORK_COVERAGE_FIELDS:
                raise ValueError(f"{role} prior_work path coverage fields mismatch")
            owner_work_ref = str(payload.get("owner_work_ref") or "")
            owner_result_ref = str(payload.get("owner_result_ref") or "")
            if any(
                not ref.startswith("process/") or not is_safe_ref(ref)
                for ref in (owner_work_ref, owner_result_ref)
            ):
                raise ValueError(
                    f"{role} prior_work coverage refs must be safe process refs"
                )
            owner_scope_digest = str(payload.get("owner_scope_digest") or "")
            if not _DIGEST_RE.fullmatch(owner_scope_digest):
                raise ValueError(f"{role} prior_work owner_scope_digest is invalid")
            if payload.get("owner_terminal_status") != "completed":
                raise ValueError(f"{role} prior_work owner must declare completed status")
            return cls(
                coverage_type=coverage_type,
                paths=paths,
                owner_work_ref=owner_work_ref,
                owner_scope_digest=owner_scope_digest,
                owner_result_ref=owner_result_ref,
                owner_terminal_status="completed",
            )
        if coverage_type == "typed_candidate_set_authorization":
            if set(payload) != _CANDIDATE_SET_COVERAGE_FIELDS:
                raise ValueError(
                    f"{role} typed_candidate_set_authorization fields mismatch"
                )
            commit_ids = _safe_authorization_ids(
                payload.get("commit_authorization_ids"),
                label=f"{role}.path_coverage.commit_authorization_ids",
            )
            push_ids = _safe_authorization_ids(
                payload.get("push_authorization_ids"),
                label=f"{role}.path_coverage.push_authorization_ids",
            )
            if (
                not commit_ids
                or not push_ids
                or commit_ids != repository.commit_authorization_ids
                or push_ids != repository.push_authorization_ids
            ):
                raise ValueError(
                    f"{role} candidate-set authorization IDs must exactly match repository authorization IDs"
                )
            candidate_set_digest = str(payload.get("candidate_set_digest") or "")
            expected_digest = publication_candidate_set_digest(
                role=role,
                paused_oid=repository.paused_oid,
                published_oid=repository.published_oid,
                paths=paths,
                commit_authorization_ids=commit_ids,
                push_authorization_ids=push_ids,
            )
            if candidate_set_digest != expected_digest:
                raise ValueError(f"{role} candidate_set_digest mismatch")
            return cls(
                coverage_type=coverage_type,
                paths=paths,
                candidate_set_digest=candidate_set_digest,
                commit_authorization_ids=commit_ids,
                push_authorization_ids=push_ids,
            )
        raise ValueError(f"{role} publication path coverage type is unsupported")

    def as_dict(self) -> dict[str, Any]:
        if self.coverage_type == "prior_work":
            return {
                "coverage_type": self.coverage_type,
                "paths": list(self.paths),
                "owner_work_ref": self.owner_work_ref,
                "owner_scope_digest": self.owner_scope_digest,
                "owner_result_ref": self.owner_result_ref,
                "owner_terminal_status": self.owner_terminal_status,
            }
        return {
            "coverage_type": self.coverage_type,
            "paths": list(self.paths),
            "candidate_set_digest": self.candidate_set_digest,
            "commit_authorization_ids": list(self.commit_authorization_ids),
            "push_authorization_ids": list(self.push_authorization_ids),
        }


def publication_candidate_set_digest(
    *,
    role: str,
    paused_oid: str,
    published_oid: str,
    paths: tuple[str, ...] | list[str],
    commit_authorization_ids: tuple[str, ...] | list[str],
    push_authorization_ids: tuple[str, ...] | list[str],
) -> str:
    """计算批量发布候选集的公开、确定性摘要。"""

    if role not in {"release", "process"}:
        raise ValueError("publication candidate-set role must be release or process")
    normalized_paths = _safe_paths(list(paths), label=f"{role}.candidate_set.paths")
    commit_ids = _safe_authorization_ids(
        list(commit_authorization_ids), label=f"{role}.candidate_set.commit_authorization_ids"
    )
    push_ids = _safe_authorization_ids(
        list(push_authorization_ids), label=f"{role}.candidate_set.push_authorization_ids"
    )
    return canonical_digest(
        {
            "schema_version": 1,
            "kind": "PublicationCandidateSetAuthorizationV1",
            "repository_role": role,
            "paused_oid": _safe_oid(paused_oid, label=f"{role}.paused_oid"),
            "published_oid": _safe_oid(published_oid, label=f"{role}.published_oid"),
            "paths": list(normalized_paths),
            "commit_authorization_ids": list(commit_ids),
            "push_authorization_ids": list(push_ids),
        }
    )


@dataclass(frozen=True, slots=True)
class PublishedRepositoryV2:
    publication: PublishedRepositoryV1
    path_coverage: tuple[PublicationPathCoverageV2, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, role: str) -> PublishedRepositoryV2:
        if set(payload) != _REPOSITORY_FIELDS | {"path_coverage"}:
            raise ValueError(f"publication receipt {role} repository v2 fields mismatch")
        publication = PublishedRepositoryV1.from_mapping(
            {key: payload[key] for key in _REPOSITORY_FIELDS}, role=role
        )
        raw_coverage = payload.get("path_coverage")
        if not isinstance(raw_coverage, list) or not all(
            isinstance(item, Mapping) for item in raw_coverage
        ):
            raise ValueError(f"{role} publication path_coverage must be a list of objects")
        coverage = tuple(
            PublicationPathCoverageV2.from_mapping(
                item, role=role, repository=publication
            )
            for item in raw_coverage
        )
        covered_paths = tuple(path for item in coverage for path in item.paths)
        if len(covered_paths) != len(set(covered_paths)):
            raise ValueError(f"{role} publication path coverage contains duplicates")
        if tuple(sorted(covered_paths)) != publication.changed_paths:
            raise ValueError(
                f"{role} publication path coverage must exactly partition changed_paths"
            )
        ordering = tuple((item.paths[0], item.coverage_type) for item in coverage)
        if ordering != tuple(sorted(ordering)):
            raise ValueError(f"{role} publication path coverage must be sorted")
        return cls(publication=publication, path_coverage=coverage)

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.publication.as_dict(),
            "path_coverage": [item.as_dict() for item in self.path_coverage],
        }


@dataclass(frozen=True, slots=True)
class RecoveryWorkBindingV1:
    work_ref: str
    scope_digest: str
    required_status: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> RecoveryWorkBindingV1:
        if set(payload) != _RECOVERY_WORK_FIELDS:
            raise ValueError("publication receipt recovery_work fields mismatch")
        work_ref = str(payload.get("work_ref") or "")
        scope_digest = str(payload.get("scope_digest") or "")
        required_status = str(payload.get("required_status") or "")
        if not work_ref.startswith("process/works/") or not is_safe_ref(work_ref):
            raise ValueError("publication receipt recovery_work ref is invalid")
        if not _DIGEST_RE.fullmatch(scope_digest):
            raise ValueError("publication receipt recovery_work scope_digest is invalid")
        if required_status != "active":
            raise ValueError("publication receipt recovery_work required_status must be active")
        return cls(work_ref, scope_digest, required_status)

    def as_dict(self) -> dict[str, str]:
        return {
            "work_ref": self.work_ref,
            "scope_digest": self.scope_digest,
            "required_status": self.required_status,
        }


@dataclass(frozen=True, slots=True)
class WorkPublicationReceiptV1:
    project_id: str
    work_id: str
    scope_digest: str
    result_ref: str
    repositories: tuple[tuple[str, PublishedRepositoryV1], ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> WorkPublicationReceiptV1:
        expected = {
            "schema_version",
            "kind",
            "decision",
            "project_id",
            "work_id",
            "scope_digest",
            "result_ref",
            "repositories",
        }
        if set(payload) != expected:
            raise ValueError("publication receipt fields mismatch")
        if (
            payload.get("schema_version") != 1
            or payload.get("kind") != PUBLICATION_RECEIPT_KIND
            or payload.get("decision") != "PASS"
        ):
            raise ValueError("publication receipt kind/version/decision mismatch")
        project_id = _safe_id(str(payload.get("project_id") or ""), label="project_id")
        work_id = _safe_id(str(payload.get("work_id") or ""), label="work_id")
        scope_digest = str(payload.get("scope_digest") or "")
        if not _DIGEST_RE.fullmatch(scope_digest):
            raise ValueError("publication receipt scope_digest is invalid")
        result_ref = str(payload.get("result_ref") or "")
        if not result_ref.startswith("process/") or not is_safe_ref(result_ref):
            raise ValueError("publication receipt result_ref must be one logical process ref")
        repositories = payload.get("repositories")
        if not isinstance(repositories, Mapping) or set(repositories) != {"release", "process"}:
            raise ValueError("publication receipt repositories must contain release and process")
        parsed: list[tuple[str, PublishedRepositoryV1]] = []
        for role in ("release", "process"):
            item = repositories[role]
            if not isinstance(item, Mapping):
                raise ValueError(f"publication receipt {role} repository must be an object")
            parsed.append((role, PublishedRepositoryV1.from_mapping(item, role=role)))
        if not any(repo.paused_oid != repo.published_oid for _role, repo in parsed):
            raise ValueError("publication-close requires at least one published OID change")
        return cls(project_id, work_id, scope_digest, result_ref, tuple(parsed))

    def repository(self, role: str) -> PublishedRepositoryV1:
        return dict(self.repositories)[role]


@dataclass(frozen=True, slots=True)
class WorkPublicationReceiptV2:
    project_id: str
    work_id: str
    scope_digest: str
    result_ref: str
    recovery_work: RecoveryWorkBindingV1 | None
    repositories: tuple[tuple[str, PublishedRepositoryV2], ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> WorkPublicationReceiptV2:
        expected = {
            "schema_version",
            "kind",
            "decision",
            "project_id",
            "work_id",
            "scope_digest",
            "result_ref",
            "recovery_work",
            "repositories",
        }
        if set(payload) != expected:
            raise ValueError("publication receipt v2 fields mismatch")
        if (
            payload.get("schema_version") != 2
            or payload.get("kind") != PUBLICATION_RECEIPT_V2_KIND
            or payload.get("decision") != "PASS"
        ):
            raise ValueError("publication receipt v2 kind/version/decision mismatch")
        project_id = _safe_id(str(payload.get("project_id") or ""), label="project_id")
        work_id = _safe_id(str(payload.get("work_id") or ""), label="work_id")
        scope_digest = str(payload.get("scope_digest") or "")
        if not _DIGEST_RE.fullmatch(scope_digest):
            raise ValueError("publication receipt v2 scope_digest is invalid")
        result_ref = str(payload.get("result_ref") or "")
        if not result_ref.startswith("process/") or not is_safe_ref(result_ref):
            raise ValueError("publication receipt v2 result_ref must be one logical process ref")
        raw_recovery = payload.get("recovery_work")
        if raw_recovery is not None and not isinstance(raw_recovery, Mapping):
            raise ValueError("publication receipt recovery_work must be null or one object")
        recovery_work = (
            RecoveryWorkBindingV1.from_mapping(raw_recovery)
            if isinstance(raw_recovery, Mapping)
            else None
        )
        repositories = payload.get("repositories")
        if not isinstance(repositories, Mapping) or set(repositories) != {"release", "process"}:
            raise ValueError("publication receipt v2 repositories must contain release and process")
        parsed: list[tuple[str, PublishedRepositoryV2]] = []
        for role in ("release", "process"):
            item = repositories[role]
            if not isinstance(item, Mapping):
                raise ValueError(f"publication receipt v2 {role} repository must be an object")
            parsed.append((role, PublishedRepositoryV2.from_mapping(item, role=role)))
        if not any(
            repository.publication.paused_oid != repository.publication.published_oid
            for _role, repository in parsed
        ):
            raise ValueError("publication-close requires at least one published OID change")
        return cls(
            project_id,
            work_id,
            scope_digest,
            result_ref,
            recovery_work,
            tuple(parsed),
        )

    def repository(self, role: str) -> PublishedRepositoryV1:
        return dict(self.repositories)[role].publication


WorkPublicationReceipt = WorkPublicationReceiptV1 | WorkPublicationReceiptV2


def _publication_receipt_from_mapping(payload: Mapping[str, Any]) -> WorkPublicationReceipt:
    if payload.get("schema_version") == 1 and payload.get("kind") == PUBLICATION_RECEIPT_KIND:
        return WorkPublicationReceiptV1.from_mapping(payload)
    if payload.get("schema_version") == 2 and payload.get("kind") == PUBLICATION_RECEIPT_V2_KIND:
        return WorkPublicationReceiptV2.from_mapping(payload)
    raise ValueError("publication receipt kind/version is unsupported")


@dataclass(frozen=True, slots=True)
class WorkPublicationCloseAuthorizationV1:
    schema_version: int
    kind: str
    authorization_id: str
    work_id: str
    plan_digest: str
    target_refs: tuple[str, ...]
    scope_digest: str
    result_ref: str
    handoff_ref: str
    handoff_digest: str
    publication_receipt_ref: str
    publication_receipt_digest: str
    repository_facts_digest: str
    paused_oids: tuple[tuple[str, str], ...]
    published_oids: tuple[tuple[str, str], ...]
    expires_at: str
    single_use: bool

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> WorkPublicationCloseAuthorizationV1:
        expected = {
            "schema_version",
            "kind",
            "authorization_id",
            "work_id",
            "plan_digest",
            "target_refs",
            "scope_digest",
            "result_ref",
            "handoff_ref",
            "handoff_digest",
            "publication_receipt_ref",
            "publication_receipt_digest",
            "repository_facts_digest",
            "paused_oids",
            "published_oids",
            "expires_at",
            "single_use",
        }
        if set(payload) != expected:
            raise ValueError("publication-close authorization fields mismatch")
        refs = payload.get("target_refs")
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError("publication-close target_refs must be a list of strings")
        binding = WorkPublicationBindingV1.from_mapping(
            {
                "schema_version": 1,
                "kind": "WorkPublicationBindingV1",
                "work_id": payload.get("work_id"),
                "scope_digest": payload.get("scope_digest"),
                "result_ref": payload.get("result_ref"),
                "handoff_ref": payload.get("handoff_ref"),
                "handoff_digest": payload.get("handoff_digest"),
                "publication_receipt_ref": payload.get("publication_receipt_ref"),
                "publication_receipt_digest": payload.get("publication_receipt_digest"),
                "repository_facts_digest": payload.get("repository_facts_digest"),
                "paused_oids": payload.get("paused_oids"),
                "published_oids": payload.get("published_oids"),
            }
        )
        return cls(
            schema_version=int(payload.get("schema_version") or 0),
            kind=str(payload.get("kind") or ""),
            authorization_id=_safe_transaction_id(
                str(payload.get("authorization_id") or ""), label="authorization_id"
            ),
            work_id=binding.work_id,
            plan_digest=str(payload.get("plan_digest") or ""),
            target_refs=tuple(refs),
            scope_digest=binding.scope_digest,
            result_ref=binding.result_ref,
            handoff_ref=binding.handoff_ref,
            handoff_digest=binding.handoff_digest,
            publication_receipt_ref=binding.publication_receipt_ref,
            publication_receipt_digest=binding.publication_receipt_digest,
            repository_facts_digest=binding.repository_facts_digest,
            paused_oids=binding.paused_oids,
            published_oids=binding.published_oids,
            expires_at=str(payload.get("expires_at") or ""),
            single_use=payload.get("single_use") is True,
        )

    def validate_for(self, plan: WorkClosePlanV1) -> None:
        binding = plan.publication_binding
        if (
            self.schema_version != 1
            or self.kind != PUBLICATION_AUTHORIZATION_KIND
            or self.single_use is not True
        ):
            raise ValueError("publication-close authorization kind/version/single_use mismatch")
        if plan.operation != "work.publication-close" or binding is None:
            raise ValueError("publication-close authorization requires one publication-close plan")
        if self.work_id != plan.work_id or self.plan_digest != plan.plan_digest:
            raise ValueError("publication-close authorization does not bind the current plan")
        if self.target_refs != tuple(target.ref for target in plan.targets):
            raise ValueError("publication-close authorization target_refs mismatch")
        expected_binding = WorkPublicationBindingV1(
            self.work_id,
            self.scope_digest,
            self.result_ref,
            self.handoff_ref,
            self.handoff_digest,
            self.publication_receipt_ref,
            self.publication_receipt_digest,
            self.repository_facts_digest,
            self.paused_oids,
            self.published_oids,
        )
        if expected_binding != binding:
            raise ValueError("publication-close authorization binding mismatch")
        if not _DIGEST_RE.fullmatch(self.plan_digest):
            raise ValueError("publication-close authorization plan_digest is invalid")
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("publication-close authorization expires_at is invalid") from exc
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("publication-close authorization is expired")


def _logical_process_path(project_root: Path, logical_ref: str) -> tuple[Path, str]:
    if not logical_ref.startswith("process/") or not is_safe_ref(logical_ref):
        raise ValueError("publication-close refs must use safe process/... logical refs")
    route = require_process_route(project_root.resolve())
    path = resolve_process_ref(project_root.resolve(), logical_ref)
    relative = path.relative_to(route.process_root).as_posix()
    if not relative or not is_safe_ref(relative):
        raise ValueError("publication-close resolved ref is invalid")
    return path, relative


def _git_value(root: Path, args: list[str], *, label: str) -> str:
    result = run_git(args, cwd=root)
    if not result.ok:
        raise ValueError(result.stderr.strip() or f"unable to observe {label}")
    return result.stdout.strip()


def _historical_changed_paths(root: Path, before_oid: str, after_oid: str) -> tuple[str, ...]:
    if before_oid == after_oid:
        return ()
    ancestry = run_git(["merge-base", "--is-ancestor", before_oid, after_oid], cwd=root)
    if not ancestry.ok:
        raise ValueError("published OID is not a descendant of the paused OID")
    result = run_git(
        ["diff", "--name-only", "-z", f"{before_oid}..{after_oid}", "--"], cwd=root
    )
    if not result.ok:
        raise ValueError(result.stderr.strip() or "unable to inspect published paths")
    paths = tuple(sorted(item for item in result.stdout.split("\0") if item))
    if len(paths) != len(set(paths)) or any(not is_safe_ref(item) for item in paths):
        raise ValueError("Git returned unsafe or duplicate published paths")
    return paths


def _repository_facts(
    root: Path,
    repository: PublishedRepositoryV1,
    *,
    role: str,
) -> dict[str, Any]:
    observation = observe_repo(root)
    upstream_ref = _git_value(
        root,
        ["rev-parse", "--symbolic-full-name", "@{upstream}"],
        label=f"{role} upstream ref",
    )
    upstream_oid = _git_value(root, ["rev-parse", "@{upstream}"], label=f"{role} upstream OID")
    expected_tracking_ref = (
        f"refs/remotes/{repository.remote}/"
        f"{repository.ref.removeprefix('refs/heads/')}"
    )
    if upstream_ref != expected_tracking_ref:
        raise ValueError(f"{role} upstream ref differs from publication receipt")
    remote = query_exact_remote_ref(root, repository.remote, repository.ref)
    changed_paths = _historical_changed_paths(
        root, repository.paused_oid, repository.published_oid
    )
    if observation.head_oid != repository.published_oid:
        raise ValueError(f"{role} local HEAD differs from publication receipt")
    if upstream_oid != repository.published_oid:
        raise ValueError(f"{role} upstream OID differs from publication receipt")
    if remote.decision != "PRESENT" or remote.oid != repository.published_oid:
        raise ValueError(f"{role} live remote OID differs from publication receipt")
    if changed_paths != repository.changed_paths:
        raise ValueError(f"{role} committed path inventory differs from publication receipt")
    if observation.changed_paths != repository.pending_paths:
        raise ValueError(f"{role} pending path inventory differs from publication receipt")
    return {
        "role": role,
        "head_oid": observation.head_oid,
        "upstream_ref": upstream_ref,
        "upstream_oid": upstream_oid,
        "remote": repository.remote,
        "ref": repository.ref,
        "remote_oid": remote.oid,
        "changed_paths": list(changed_paths),
        "pending_paths": list(observation.changed_paths),
    }


def _path_allowed(
    work: Work,
    *,
    role: str,
    path: str,
    native_process_refs: set[str],
) -> bool:
    if role == "process":
        if path in native_process_refs:
            return True
        logical = f"process/{path}"
        return check_scope(work.scope, "write", logical).allowed or check_scope(
            work.scope, "write", path
        ).allowed
    return check_scope(work.scope, "write", path).allowed


def _work_id_from_ref(internal_ref: str) -> str:
    parts = Path(internal_ref).parts
    if len(parts) != 3 or parts[0] != "works" or parts[2] != "WORK.yaml":
        raise ValueError("publication coverage Work ref must be works/<work-id>/WORK.yaml")
    return _safe_id(parts[1], label="coverage work_id")


def _validate_exact_pass_result(process_root: Path, work: Work, result_ref: str) -> Path:
    result_path = process_root / result_ref
    if result_path.is_symlink() or not result_path.is_file():
        raise ValueError(f"prior Work result is missing or not regular: {result_ref}")
    payload = load_yaml_object(result_path)
    if (
        set(payload) != {"schema_version", "work_id", "decision"}
        or payload.get("schema_version") != 1
        or payload.get("work_id") != work.work_id
        or payload.get("decision") != "PASS"
    ):
        raise ValueError("prior Work coverage requires one exact matching PASS result")
    return result_path


def _load_recovery_work(
    project_root: Path,
    process_root: Path,
    primary_work: Work,
    binding: RecoveryWorkBindingV1 | None,
) -> tuple[Work | None, dict[str, Any] | None]:
    if binding is None:
        return None, None
    work_path, internal_ref = _logical_process_path(project_root, binding.work_ref)
    recovery_id = _work_id_from_ref(internal_ref)
    if recovery_id == primary_work.work_id:
        raise ValueError("recovery Work must differ from the publication Work")
    if work_path.is_symlink() or not work_path.is_file():
        raise ValueError("publication recovery Work is missing or not regular")
    recovery = load_work(process_root, recovery_id)
    if (
        recovery.project_id != primary_work.project_id
        or recovery.scope.digest != binding.scope_digest
        or recovery.status != binding.required_status
    ):
        raise ValueError("publication recovery Work identity, scope, or status mismatch")
    return recovery, {
        "work_ref": internal_ref,
        "work_digest": _digest_bytes(work_path.read_bytes()),
        "work_id": recovery.work_id,
        "scope_digest": recovery.scope.digest,
        "status": recovery.status,
    }


def _prior_work_coverage_facts(
    project_root: Path,
    process_root: Path,
    primary_work: Work,
    coverage: PublicationPathCoverageV2,
    *,
    role: str,
) -> dict[str, Any]:
    work_path, work_ref = _logical_process_path(project_root, coverage.owner_work_ref)
    owner_id = _work_id_from_ref(work_ref)
    if work_path.is_symlink() or not work_path.is_file():
        raise ValueError("prior Work coverage owner is missing or not regular")
    owner = load_work(process_root, owner_id)
    result_path, result_ref = _logical_process_path(
        project_root, coverage.owner_result_ref
    )
    if (
        owner.project_id != primary_work.project_id
        or owner.status != "completed"
        or owner.scope.digest != coverage.owner_scope_digest
        or owner.result_ref != result_ref
    ):
        raise ValueError("prior Work coverage owner identity, status, scope, or result mismatch")
    validated_result_path = _validate_exact_pass_result(process_root, owner, result_ref)
    if validated_result_path != result_path:
        raise ValueError("prior Work coverage result route mismatch")
    for path in coverage.paths:
        if not _path_allowed(
            owner,
            role=role,
            path=path,
            native_process_refs=set(),
        ):
            raise ValueError(
                f"{role} publication path is outside prior Work scope {owner.work_id}: {path}"
            )
    return {
        "coverage_type": coverage.coverage_type,
        "paths": list(coverage.paths),
        "owner_work_ref": work_ref,
        "owner_work_digest": _digest_bytes(work_path.read_bytes()),
        "owner_scope_digest": owner.scope.digest,
        "owner_result_ref": result_ref,
        "owner_result_digest": _digest_bytes(result_path.read_bytes()),
        "owner_terminal_status": owner.status,
    }


def _historical_coverage_facts(
    project_root: Path,
    process_root: Path,
    primary_work: Work,
    receipt: WorkPublicationReceipt,
    *,
    role: str,
) -> dict[str, Any]:
    repository = receipt.repository(role)
    if isinstance(receipt, WorkPublicationReceiptV1):
        for path in repository.changed_paths:
            if not _path_allowed(
                primary_work,
                role=role,
                path=path,
                native_process_refs=set(),
            ):
                raise ValueError(f"{role} publication path is outside Work scope: {path}")
        return {
            "mode": "single_work_v1",
            "covered_path_count": len(repository.changed_paths),
            "owner_work_id": primary_work.work_id,
            "owner_scope_digest": primary_work.scope.digest,
        }

    repository_v2 = dict(receipt.repositories)[role]
    coverage_facts: list[dict[str, Any]] = []
    for coverage in repository_v2.path_coverage:
        if coverage.coverage_type == "prior_work":
            coverage_facts.append(
                _prior_work_coverage_facts(
                    project_root,
                    process_root,
                    primary_work,
                    coverage,
                    role=role,
                )
            )
        else:
            coverage_facts.append(coverage.as_dict())
    return {
        "mode": "exact_partition_v2",
        "covered_path_count": sum(len(item.paths) for item in repository_v2.path_coverage),
        "path_coverage": coverage_facts,
    }


def _pending_coverage_facts(
    primary_work: Work,
    recovery_work: Work | None,
    repository: PublishedRepositoryV1,
    *,
    role: str,
    native_process_refs: set[str],
) -> dict[str, Any]:
    coverage: list[dict[str, str]] = []
    for path in repository.pending_paths:
        source = ""
        if role == "process" and path in native_process_refs:
            source = "native_close_target"
        elif _path_allowed(
            primary_work,
            role=role,
            path=path,
            native_process_refs=set(),
        ):
            source = "publication_work"
        elif recovery_work is not None and _path_allowed(
            recovery_work,
            role=role,
            path=path,
            native_process_refs=set(),
        ):
            source = "recovery_work"
        if not source:
            raise ValueError(f"{role} pending publication path is outside authorized scope: {path}")
        coverage.append({"path": path, "source": source})
    return {
        "covered_path_count": len(coverage),
        "path_coverage": coverage,
    }


def require_external_publication_authorization_path(
    project_root: Path,
    authorization_path: Path,
) -> Path:
    """要求 apply authorization 位于 release/process 仓之外，避免 plan 漂移。"""

    project_root = project_root.resolve()
    route = require_process_route(project_root)
    lexical = authorization_path.absolute()
    resolved = authorization_path.resolve()
    for repository_root in (project_root, route.process_root.resolve()):
        if lexical.is_relative_to(repository_root) or resolved.is_relative_to(repository_root):
            raise ValueError(
                "publication-close authorization must be stored outside release/process repositories"
            )
    return resolved


def _blocked_plan(
    work_id: str,
    result_ref: str,
    blockers: tuple[str, ...],
    *,
    binding: WorkPublicationBindingV1 | None = None,
) -> WorkClosePlanV1:
    fields = {
        "schema_version": 1,
        "operation": "work.publication-close",
        "work_id": work_id,
        "expected_status": "paused",
        "outcome": "completed",
        "result_ref": result_ref,
        "targets": [],
        "lineage": {},
        "blockers": list(blockers),
        "publication_binding": None if binding is None else binding.as_dict(),
    }
    return WorkClosePlanV1(
        operation="work.publication-close",
        decision="BLOCKED",
        work_id=work_id,
        expected_status="paused",
        outcome="completed",
        result_ref=result_ref,
        targets=(),
        lineage=(),
        blockers=blockers,
        plan_digest=canonical_digest(fields),
        publication_binding=binding,
    )


def plan_work_publication_close(
    project_root: Path,
    work_id: str,
    *,
    result_ref: str,
    publication_receipt_ref: str,
) -> WorkClosePlanV1:
    """零写验证授权 publication 是否精确解释 paused Work 的 OID 漂移。"""

    normalized_result_ref = result_ref.removeprefix("process/")
    try:
        project_root = project_root.resolve()
        route = require_process_route(project_root)
        process_root = route.process_root
        receipt_path, receipt_internal_ref = _logical_process_path(
            project_root, publication_receipt_ref
        )
        result_path, result_internal_ref = _logical_process_path(project_root, result_ref)
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise ValueError("publication receipt is missing or not regular")
        if result_path.is_symlink() or not result_path.is_file():
            raise ValueError("publication-close result is missing or not regular")
        receipt_bytes = receipt_path.read_bytes()
        receipt_payload = load_yaml_object(receipt_path)
        receipt = _publication_receipt_from_mapping(receipt_payload)
        work = load_work(process_root, work_id)
        require_project_process_route(project_root, project_id=work.project_id)
        handoff = load_handoff(process_root, work_id)
        handoff_ref = f"works/{work_id}/HANDOFF.yaml"
        handoff_file = handoff_path(process_root, work_id)
        if handoff_file.is_symlink() or not handoff_file.is_file():
            raise ValueError("paused Work handoff is missing or not regular")
        if work.status != "paused" or handoff.work_status != "paused":
            raise ValueError("publication-close requires one paused Work and paused HANDOFF")
        if (
            receipt.project_id != work.project_id
            or receipt.work_id != work.work_id
            or receipt.scope_digest != work.scope.digest
            or receipt.result_ref != f"process/{result_internal_ref}"
            or handoff.project_id != work.project_id
            or handoff.work_id != work.work_id
            or handoff.scope_digest != work.scope.digest
        ):
            raise ValueError("publication receipt/HANDOFF identity or scope mismatch")
        release_receipt = receipt.repository("release")
        process_receipt = receipt.repository("process")
        if (
            release_receipt.paused_oid != handoff.release_oid
            or process_receipt.paused_oid != handoff.process_oid
        ):
            raise ValueError("publication receipt paused OIDs differ from immutable HANDOFF")
        recovery_binding = (
            receipt.recovery_work
            if isinstance(receipt, WorkPublicationReceiptV2)
            else None
        )
        recovery_work, recovery_facts = _load_recovery_work(
            project_root,
            process_root,
            work,
            recovery_binding,
        )
        facts: dict[str, Any] = {
            "release": _repository_facts(
                project_root, release_receipt, role="release"
            ),
            "process": _repository_facts(
                process_root, process_receipt, role="process"
            ),
        }
        preliminary_binding = WorkPublicationBindingV1(
            work_id=work.work_id,
            scope_digest=work.scope.digest,
            result_ref=result_internal_ref,
            handoff_ref=handoff_ref,
            handoff_digest=_digest_bytes(handoff_file.read_bytes()),
            publication_receipt_ref=receipt_internal_ref,
            publication_receipt_digest=_digest_bytes(receipt_bytes),
            repository_facts_digest=canonical_digest(facts),
            paused_oids=(
                ("release", release_receipt.paused_oid),
                ("process", process_receipt.paused_oid),
            ),
            published_oids=(
                ("release", release_receipt.published_oid),
                ("process", process_receipt.published_oid),
            ),
        )
        preliminary_close_plan = plan_work_close(
            process_root,
            work_id,
            expected_status="paused",
            outcome="completed",
            result_ref=result_internal_ref,
            _publication_binding=preliminary_binding,
        )
        if not preliminary_close_plan.ready:
            return preliminary_close_plan
        native_refs = {
            target.ref for target in preliminary_close_plan.targets
        } | {
            handoff_ref,
            f"works/{work_id}/WORK.yaml",
            result_internal_ref,
            receipt_internal_ref,
        }
        if recovery_facts is not None:
            facts["recovery_work"] = recovery_facts
        for role in ("release", "process"):
            repository = receipt.repository(role)
            facts[role]["historical_coverage"] = _historical_coverage_facts(
                project_root,
                process_root,
                work,
                receipt,
                role=role,
            )
            facts[role]["pending_coverage"] = _pending_coverage_facts(
                work,
                recovery_work,
                repository,
                role=role,
                native_process_refs=native_refs,
            )
        binding = WorkPublicationBindingV1(
            work_id=work.work_id,
            scope_digest=work.scope.digest,
            result_ref=result_internal_ref,
            handoff_ref=handoff_ref,
            handoff_digest=_digest_bytes(handoff_file.read_bytes()),
            publication_receipt_ref=receipt_internal_ref,
            publication_receipt_digest=_digest_bytes(receipt_bytes),
            repository_facts_digest=canonical_digest(facts),
            paused_oids=(
                ("release", release_receipt.paused_oid),
                ("process", process_receipt.paused_oid),
            ),
            published_oids=(
                ("release", release_receipt.published_oid),
                ("process", process_receipt.published_oid),
            ),
        )
        close_plan = plan_work_close(
            process_root,
            work_id,
            expected_status="paused",
            outcome="completed",
            result_ref=result_internal_ref,
            _publication_binding=binding,
        )
        if tuple(target.ref for target in close_plan.targets) != tuple(
            target.ref for target in preliminary_close_plan.targets
        ):
            raise ValueError("publication-close target set drifted during coverage planning")
        return close_plan
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _blocked_plan(
            work_id,
            normalized_result_ref,
            (str(exc),),
            binding=locals().get("binding") or locals().get("preliminary_binding"),
        )


def apply_work_publication_close(
    project_root: Path,
    plan: WorkClosePlanV1,
    authorization: WorkPublicationCloseAuthorizationV1,
) -> WorkCloseReceiptV1:
    """fresh-plan 后复用 Work-close 持久事务；不改写历史 HANDOFF/base OID/usage。"""

    if not plan.ready or plan.operation != "work.publication-close":
        raise ValueError("blocked publication-close plan cannot be applied")
    authorization.validate_for(plan)
    binding = plan.publication_binding
    assert binding is not None
    fresh = plan_work_publication_close(
        project_root,
        plan.work_id,
        result_ref=f"process/{binding.result_ref}",
        publication_receipt_ref=f"process/{binding.publication_receipt_ref}",
    )
    if not fresh.ready or fresh.plan_digest != plan.plan_digest:
        raise ValueError("publication-close plan drifted before apply")
    route = require_process_route(project_root.resolve())
    return apply_work_close(route.process_root, fresh, authorization)


__all__ = [
    "PUBLICATION_AUTHORIZATION_KIND",
    "PUBLICATION_RECEIPT_KIND",
    "PUBLICATION_RECEIPT_V2_KIND",
    "PublicationPathCoverageV2",
    "PublishedRepositoryV1",
    "PublishedRepositoryV2",
    "RecoveryWorkBindingV1",
    "WorkPublicationCloseAuthorizationV1",
    "WorkPublicationReceiptV1",
    "WorkPublicationReceiptV2",
    "apply_work_publication_close",
    "plan_work_publication_close",
    "publication_candidate_set_digest",
    "require_external_publication_authorization_path",
]
