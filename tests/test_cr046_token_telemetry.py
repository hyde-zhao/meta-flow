from __future__ import annotations

import unittest

from meta_flow.evidence.telemetry import TokenUsage, aggregate_usage, usage_from_event, validate_usage


class TokenTelemetryTests(unittest.TestCase):
    def test_platform_measured_usage_is_accepted(self) -> None:
        usage = TokenUsage("measured", "platform-reported", input_tokens=10, output_tokens=5, total_tokens=15, model="model-a")
        self.assertEqual([], validate_usage(usage))

    def test_estimate_cannot_be_mislabeled_measured(self) -> None:
        usage = TokenUsage("measured", "chars_div_4", total_tokens=15)
        self.assertIn("measured usage requires source=platform-reported", validate_usage(usage))

    def test_unavailable_does_not_claim_token_fields(self) -> None:
        usage = TokenUsage("unavailable", "platform-unavailable", total_tokens=15)
        self.assertIn("unavailable/estimated usage must not populate measured token fields", validate_usage(usage))

    def test_aggregate_keeps_unavailable_separate(self) -> None:
        aggregate = aggregate_usage((TokenUsage("measured", "platform-reported", total_tokens=9), TokenUsage("unavailable", "platform-unavailable")))
        self.assertEqual(9, aggregate["measured_total_tokens"])
        self.assertEqual(1, aggregate["measurement_status_counts"]["unavailable"])

    def test_event_receipt_is_not_estimated_when_platform_data_absent(self) -> None:
        self.assertIsNone(usage_from_event({"event_id": "no-usage"}))
        usage = usage_from_event({"usage": {"measurement_status": "unavailable", "source": "platform-unavailable"}})
        self.assertIsNotNone(usage)
        self.assertEqual([], validate_usage(usage))


if __name__ == "__main__":
    unittest.main()
