from __future__ import annotations

import ast
import inspect
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from functools import partial
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from cr_lifecycle_test_support import LifecycleFixtureCollaborators
from cr_lifecycle_test_support import init_binding_project as _init_binding_project
from cr_lifecycle_test_support import write_cr as _write_cr

from meta_flow.project.onboarding import (
    ProjectInitRequest,
    apply_project_init,
    plan_project_init,
)
from meta_flow.project.onboarding_contract import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_SOURCE,
    OnboardingAuthorization,
)
from meta_flow.project.process_route import _resolve_runtime_ref
from meta_flow.project.scale import dump_yaml, load_yaml_object
from meta_flow.work.scope import WorkScope
from meta_flow.workflow import (
    cr_analysis,
    cr_lifecycle,
    cr_records,
    cr_termination,
)

_FIXTURE_COLLABORATORS = LifecycleFixtureCollaborators(
    project_init_request=ProjectInitRequest,
    plan_project_init=plan_project_init,
    apply_project_init=apply_project_init,
    onboarding_authorization=OnboardingAuthorization,
    authorization_source=AUTHORIZATION_SOURCE,
    authorization_kind=AUTHORIZATION_KIND,
    resolve_runtime_ref=_resolve_runtime_ref,
    dump_yaml=dump_yaml,
    load_yaml_object=load_yaml_object,
    work_scope=WorkScope,
)
write_cr = partial(_write_cr, collaborators=_FIXTURE_COLLABORATORS)
init_binding_project = partial(
    _init_binding_project,
    collaborators=_FIXTURE_COLLABORATORS,
)


class CRLifecycleFacadeSeamTests(unittest.TestCase):
    """只验证 facade 的重导出、调用时注入和转发兼容。"""

    _direct_attributes = (
        "AggregateCompletionProjector",
        "CR_INDEX_REL",
        "STATUS_SYNC_AUTHORIZATION_KIND",
        "STATUS_SYNC_AUTHORIZATION_SOURCE",
        "STATUS_SYNC_OPERATION",
        "StatusSyncAuthorization",
        "StatusSyncPlan",
        "BootstrapCRPlanV1",
        "TERMINATION_AUTHORIZATION_KIND",
        "TERMINATION_AUTHORIZATION_SOURCE",
        "TERMINATION_OPERATION",
        "TerminationAuthorization",
        "TerminationPlan",
        "_acquire_status_sync_writer_lock",
        "_atomic_write_text",
        "_release_status_sync_writer_lock",
        "_status_sync_writer_lock_path",
        "_update_current_active_change",
        "append_ledger_event",
        "apply_bootstrap_cr",
        "apply_cr_termination",
        "apply_status_sync",
        "build_impact_report",
        "build_cr_lifecycle_check_report",
        "build_index",
        "collect_check_errors",
        "current",
        "inspect_bootstrap_transactions",
        "inspect_status_sync_transactions",
        "load_ledger_events",
        "load_status_sync_authorization",
        "main",
        "parse_frontmatter",
        "plan_bootstrap_cr",
        "plan_cr_termination",
        "plan_index",
        "plan_status_sync",
        "project_native_cr_status",
        "recover_bootstrap_transaction",
        "recover_status_sync_transaction",
        "render_cr_brief",
        "render_goal_brief",
        "summary_from_cr_file",
        "sync_cr_status",
        "validate_index_payload",
        "write_index",
        "write_summary",
    )

    _public_union = (
        "AggregateCompletionProjector",
        "BootstrapCRPlanV1",
        "CR_INDEX_REL",
        "CR_SUMMARY_ROOT_REL",
        "STATUS_SYNC_AUTHORIZATION_KIND",
        "STATUS_SYNC_AUTHORIZATION_SOURCE",
        "STATUS_SYNC_OPERATION",
        "StatusSyncAuthorization",
        "StatusSyncPlan",
        "TERMINATION_AUTHORIZATION_KIND",
        "TERMINATION_AUTHORIZATION_SOURCE",
        "TERMINATION_OPERATION",
        "TerminationAuthorization",
        "TerminationPlan",
        "append_ledger_event",
        "apply_bootstrap_cr",
        "apply_cr_termination",
        "apply_status_sync",
        "build_impact_report",
        "build_cr_lifecycle_check_report",
        "build_index",
        "collect_check_errors",
        "close_cr",
        "discover_formal_crs",
        "inspect_bootstrap_transactions",
        "inspect_status_sync_transactions",
        "load_ledger_events",
        "load_status_sync_authorization",
        "main",
        "parse_frontmatter",
        "plan_bootstrap_cr",
        "plan_cr_termination",
        "plan_index",
        "plan_status_sync",
        "project_native_cr_status",
        "recover_bootstrap_transaction",
        "recover_status_sync_transaction",
        "render_cr_brief",
        "render_goal_brief",
        "summary_from_cr_file",
        "sync_cr_status",
        "validate_index_payload",
        "write_index",
        "write_summary",
    )

    def _write_converged_projection_fixture(self, root: Path) -> dict[str, object]:
        cr_path = write_cr(root, "CR-101")
        text = cr_path.read_text(encoding="utf-8")
        cr_path.write_text(
            text.replace(
                'lifecycle_status: "active"\nreadiness_status: "NOT_READY"\n'
                'gate_status: "cp8_pending"',
                'lifecycle_status: "closed"\n'
                'readiness_status: "READY_WITH_RISK"\n'
                'gate_status: "cp8_closed"',
            ),
            encoding="utf-8",
        )
        cr_lifecycle.write_index(root)
        cr_lifecycle.write_summary(
            root,
            "CR-101",
            cr_lifecycle.summary_from_cr_file(root, cr_path),
        )
        cr_lifecycle.append_ledger_event(
            root,
            {
                "event": "status_sync",
                "event_id": "CR-101-CLOSED",
                "event_type": "status_sync",
                "id": "CR-101",
                "status": "closed",
                "readiness": "READY_WITH_RISK",
                "gate_status": "cp8_closed",
                "full_ref": "process/changes/CR-101.md",
                "summary_ref": "process/changes/summaries/CR-101.summary.json",
            },
        )
        return cr_lifecycle.load_index(root)

    def test_facade_has_exact_wrappers_and_loc_ceiling(self) -> None:
        source = Path(cr_lifecycle.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        members = {
            node.name for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        }
        self.assertEqual(
            {
                "AggregateCompletionProjector",
                "append_ledger_event",
                "project_native_cr_status",
                "close_cr",
                "sync_cr_status",
                "main",
            },
            members,
        )
        self.assertLessEqual(len(source.splitlines()), 700)
        self.assertLessEqual(
            sum(
                bool(line.strip()) and not line.lstrip().startswith("#")
                for line in source.splitlines()
            ),
            620,
        )
        main_node = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        self.assertFalse(any(isinstance(node, ast.If) for node in ast.walk(main_node)))

    def test_analysis_public_surface_is_direct_owner_reexport(self) -> None:
        surfaces = (
            "collect_check_errors",
            "build_cr_lifecycle_check_report",
            "build_impact_report",
            "render_cr_brief",
            "render_goal_brief",
        )
        for name in surfaces:
            with self.subTest(name=name):
                facade_value = getattr(cr_lifecycle, name)
                owner_value = getattr(cr_analysis, name)
                self.assertIs(owner_value, facade_value)
                self.assertEqual(
                    inspect.signature(owner_value),
                    inspect.signature(facade_value),
                )

    def test_termination_public_surface_is_direct_owner_reexport(self) -> None:
        surfaces = (
            "TERMINATION_AUTHORIZATION_KIND",
            "TERMINATION_AUTHORIZATION_SOURCE",
            "TERMINATION_OPERATION",
            "TerminationAuthorization",
            "TerminationPlan",
            "plan_cr_termination",
            "apply_cr_termination",
        )
        for name in surfaces:
            with self.subTest(name=name):
                facade_value = getattr(cr_lifecycle, name)
                owner_value = getattr(cr_termination, name)
                self.assertIs(owner_value, facade_value)
                if callable(owner_value):
                    self.assertEqual(
                        inspect.signature(owner_value),
                        inspect.signature(facade_value),
                    )

    def test_attributes_and_explicit_export_contract_are_complete(self) -> None:
        public_or_private = set(cr_lifecycle.__all__) | set(
            cr_lifecycle._PRIVATE_COMPATIBILITY_AVAILABILITY
        )
        self.assertEqual(self._public_union, cr_lifecycle.__all__)
        self.assertEqual(len(self._direct_attributes), len(set(self._direct_attributes)))
        self.assertEqual(
            set(self._direct_attributes),
            public_or_private & set(self._direct_attributes),
        )
        self.assertNotIn("current", cr_lifecycle.__all__)
        self.assertEqual(
            "external-private-alias",
            cr_lifecycle._PRIVATE_COMPATIBILITY_AVAILABILITY["current"],
        )
        self.assertEqual(
            ("_rel", "_resolve_runtime_ref"),
            tuple(
                sorted(
                    symbol
                    for symbol, classification in (
                        cr_lifecycle._PRIVATE_COMPATIBILITY_AVAILABILITY.items()
                    )
                    if classification == "injected-call-time-path-helper"
                )
            ),
        )
        self.assertEqual(
            (
                "project_root",
                "transaction_id",
                "action",
                "typed_authorized",
            ),
            tuple(inspect.signature(cr_lifecycle.recover_status_sync_transaction).parameters),
        )

    def test_five_patch_surfaces_are_post_import_patchable(self) -> None:
        expected = {
            "close_cr",
            "sync_cr_status",
            "append_ledger_event",
            "_resolve_runtime_ref",
            "_rel",
        }
        self.assertEqual(expected, cr_lifecycle._CALL_TIME_COMPATIBILITY_SURFACES)
        for symbol in sorted(expected):
            with self.subTest(symbol=symbol):
                original = getattr(cr_lifecycle, symbol)
                marker = Mock(name=f"patched_{symbol}")
                with patch.object(cr_lifecycle, symbol, marker):
                    getattr(cr_lifecycle, symbol)("post-import")
                    marker.assert_called_once_with("post-import")
                self.assertIs(original, getattr(cr_lifecycle, symbol))

    def test_main_consumes_current_post_import_close_and_sync_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = Mock()
            authorization = object()
            patched_close = Mock(return_value={"status": "PASS", "mutation_count": 0})
            patched_sync = Mock(return_value={"status": "PASS", "mutation_count": 0})
            with (
                patch.object(cr_lifecycle, "plan_status_sync", return_value=plan),
                patch.object(
                    cr_lifecycle,
                    "load_status_sync_authorization",
                    return_value=authorization,
                ),
                patch.object(cr_lifecycle, "close_cr", patched_close),
                patch.object(cr_lifecycle, "sync_cr_status", patched_sync),
                redirect_stdout(StringIO()),
            ):
                common = [
                    "--id",
                    "CR-101",
                    "--apply",
                    "--authorization-file",
                    str(root / "authorization.json"),
                    "--project-root",
                    str(root),
                ]
                self.assertEqual(0, cr_lifecycle.main(["close", *common]))
                self.assertEqual(0, cr_lifecycle.main(["status-sync", *common]))

            self.assertTrue(patched_close.called)
            self.assertTrue(patched_close.call_args.kwargs["_return_apply_result"])
            self.assertIs(authorization, patched_close.call_args.kwargs["authorization"])
            self.assertTrue(patched_sync.called)
            self.assertIs(plan, patched_sync.call_args.kwargs["_plan"])
            self.assertTrue(patched_sync.call_args.kwargs["_return_apply_result"])

    def test_runtime_helper_is_looked_up_at_call_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CR-LEDGER.ndjson"
            calls: list[tuple[Path, str]] = []

            def resolve(project_root: Path, logical_ref: str) -> Path:
                calls.append((project_root, logical_ref))
                return target

            with patch.object(cr_lifecycle, "_resolve_runtime_ref", side_effect=resolve):
                self.assertEqual(
                    target,
                    cr_lifecycle.append_ledger_event(Path(directory), {"id": "I3"}),
                )
            self.assertEqual(
                [(Path(directory), "process/state/CR-LEDGER.ndjson")],
                calls,
            )

    def test_projection_injects_current_resolver_rel_and_internal_index_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _process = init_binding_project(Path(directory))
            index = self._write_converged_projection_fixture(root)
            logical_refs: list[str] = []
            formal_ref = "process/changes/CR-101.md"
            formal_path = _resolve_runtime_ref(root, formal_ref)

            def resolve(project_root: Path, logical_ref: str) -> Path:
                self.assertEqual(root, project_root)
                logical_refs.append(logical_ref)
                return _resolve_runtime_ref(root, logical_ref)

            with (
                patch.object(
                    cr_lifecycle,
                    "_resolve_runtime_ref",
                    side_effect=resolve,
                ) as resolver,
                patch.object(cr_lifecycle, "_rel", return_value=formal_ref) as rel,
                patch.object(cr_lifecycle, "load_index", return_value=index) as loader,
                patch.object(
                    cr_records,
                    "_resolve_runtime_ref",
                    side_effect=AssertionError("leaf import-time resolver alias was called"),
                ) as leaf_resolver,
                patch.object(
                    cr_records,
                    "_rel",
                    side_effect=AssertionError("leaf import-time rel alias was called"),
                ) as leaf_rel,
            ):
                projection = cr_lifecycle.project_native_cr_status(root, cr_id="CR-101")

            self.assertEqual("PASS", projection.decision)
            self.assertEqual(formal_ref, projection.formal_cr_ref)
            self.assertNotIn(
                str(root.resolve()),
                json.dumps(projection.as_dict(), sort_keys=True),
            )
            self.assertEqual(
                {
                    "process/changes",
                    "process/changes/summaries/CR-101.summary.json",
                    "process/state/CR-LEDGER.ndjson",
                },
                set(logical_refs),
            )
            rel.assert_called_once_with(root, formal_path)
            loader.assert_called_once_with(root, resolve_runtime_ref_fn=resolver)
            leaf_resolver.assert_not_called()
            leaf_rel.assert_not_called()

    def test_rel_helper_is_looked_up_by_close_cr_at_call_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cr_path = root / "process" / "changes" / "CR-I3.md"
            paths = {
                "sentinel-cr": cr_path,
                "process/changes/summaries/CR-I3.summary.json": root / "summary.json",
                "process/archive/CR-I3/evidence-index.json": root / "evidence.json",
                "process/changes/CR-INDEX.json": root / "index.json",
                "process/state/CR-LEDGER.ndjson": root / "ledger.ndjson",
            }
            with (
                patch.object(cr_lifecycle, "plan_status_sync", return_value=Mock()),
                patch.object(
                    cr_lifecycle,
                    "apply_status_sync",
                    return_value={"status": "PASS", "paths": paths},
                ),
                patch.object(
                    cr_lifecycle,
                    "discover_formal_crs",
                    return_value={"CR-I3": cr_path},
                ),
                patch.object(cr_lifecycle, "_rel", return_value="sentinel-cr") as rel,
            ):
                returned = cr_lifecycle.close_cr(
                    root,
                    "CR-I3",
                    readiness="READY",
                    work_id="I3",
                    effective_at="2026-08-02T00:00:00+00:00",
                    expected_process_oid="",
                    expected_plan_digest="",
                    authorization=None,
                )
            rel.assert_called_once_with(root, cr_path)
            self.assertEqual(cr_path, returned["cr"])

    def test_compatibility_entrypoints_do_not_capture_patch_points_in_defaults(self) -> None:
        source = Path(cr_lifecycle.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name in (
            "append_ledger_event",
            "project_native_cr_status",
            "close_cr",
            "sync_cr_status",
            "main",
        ):
            with self.subTest(entrypoint=name):
                node = functions[name]
                defaults = [*node.args.defaults, *(node.args.kw_defaults or [])]
                default_names = {
                    nested.id
                    for default in defaults
                    if default is not None
                    for nested in ast.walk(default)
                    if isinstance(nested, ast.Name)
                }
                self.assertFalse(default_names & cr_lifecycle._CALL_TIME_COMPATIBILITY_SURFACES)


if __name__ == "__main__":
    unittest.main()
