"""CR-075 V3 整改 R2：phase-baseline 公共 mutation admission 的真实 argv 判定。

门禁反馈：真实 CLI argv（--plan/--authorization 两段式，无 --apply）必须被
判为 mutation；invalidate 的 plan/apply 必须区分；契约 projector 必须指向
真实存在的函数（invalidate_baseline 并不存在）。
"""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from meta_flow import cli as provider_cli  # noqa: E402
from meta_flow.project.scale import load_yaml_object  # noqa: E402

_PROJECT_ROOT = Path(__file__).parents[2]
_PHASE_REF = "process/phases/P6-STAGE3/PHASE.yaml"


class PhaseBaselineAdmissionTests(unittest.TestCase):
    def test_real_apply_argv_is_provider_mutation(self) -> None:
        self.assertTrue(
            provider_cli._is_provider_mutation(
                "phase-baseline",
                [
                    "apply",
                    "--project-root",
                    ".",
                    "--phase-ref",
                    _PHASE_REF,
                    "--plan",
                    "process/phases/P6-STAGE3/baseline-plan.json",
                    "--authorization",
                    "AUTH-PHASE-BASELINE-APPLY-001",
                ],
            )
        )

    def test_apply_without_authorization_is_not_provider_mutation(self) -> None:
        # 缺 --authorization 时命令层自身 typed BLOCKED（见 test_phase_baseline），
        # provider admission 不应把只到 plan 层的调用判为 mutation。
        self.assertFalse(
            provider_cli._is_provider_mutation(
                "phase-baseline",
                [
                    "apply",
                    "--phase-ref",
                    _PHASE_REF,
                    "--plan",
                    "process/phases/P6-STAGE3/baseline-plan.json",
                ],
            )
        )

    def test_invalidate_plan_and_apply_are_distinguished(self) -> None:
        # 无参 invalidate = plan（零写预检）；--plan+--authorization = apply。
        self.assertFalse(
            provider_cli._is_provider_mutation(
                "phase-baseline", ["invalidate", "--phase-ref", _PHASE_REF]
            )
        )
        self.assertTrue(
            provider_cli._is_provider_mutation(
                "phase-baseline",
                [
                    "invalidate",
                    "--phase-ref",
                    _PHASE_REF,
                    "--plan",
                    "process/phases/P6-STAGE3/invalidation-plan.json",
                    "--authorization",
                    "AUTH-PHASE-BASELINE-INVALIDATE-001",
                ],
            )
        )

    def test_readonly_subcommands_are_never_provider_mutation(self) -> None:
        for subcommand in ("check", "inspect", "plan"):
            self.assertFalse(
                provider_cli._is_provider_mutation(
                    "phase-baseline", [subcommand, "--phase-ref", _PHASE_REF]
                )
            )

    def test_policies_use_typed_authorization_mode(self) -> None:
        self.assertEqual(
            "typed-authorization-flag",
            provider_cli.PUBLIC_OPERATION_ADMISSION_POLICIES[("phase-baseline", "apply")],
        )
        self.assertEqual(
            "typed-authorization-flag",
            provider_cli.PUBLIC_OPERATION_ADMISSION_POLICIES[
                ("phase-baseline", "invalidate")
            ],
        )

    def test_contract_projectors_resolve_to_real_functions(self) -> None:
        """契约 projector 必须能 import 到真实函数（防 invalidate_baseline 漂移）。"""

        contract = load_yaml_object(
            _PROJECT_ROOT / "delivery/doc/PUBLIC-OPERATION-CONTRACTS.yaml"
        )
        operations = {
            entry["operation"]: entry
            for entry in contract["operations"]
        }
        for operation in ("phase-baseline.apply", "phase-baseline.invalidate"):
            self.assertIn(operation, operations)
            projector = operations[operation]["projector"]
            module_name, _, function_name = projector.rpartition(".")
            module = importlib.import_module(module_name)
            function = getattr(module, function_name)
            self.assertTrue(callable(function))


if __name__ == "__main__":
    unittest.main()
