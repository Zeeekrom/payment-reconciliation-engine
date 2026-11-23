"""Tests for validation/normalization — Phase B, written by Claude (AI-assisted).

Evan hand-wrote app/core/validation.py; this test suite verifies it.

This module's responsibility: translate each channel's own raw status string
into a unified NormalizedOutcome (SUCCESS/FAILED/PENDING/UNKNOWN). The tests
focus on:
1. Whether known status values map to the correct outcome;
2. Whether unrecognized status values reliably fall back to UNKNOWN instead
   of raising an exception;
3. Whether a few deliberate design trade-offs (such as Channel B's REFUND
   handling) are locked in by tests, so they don't get accidentally reverted
   later.
"""

import pytest

from app.core.validation import (
    NormalizedOutcome,
    normalize_channel_a,
    normalize_channel_b,
    normalize_channel_c,
)


class TestNormalizeChannelA:
    """Channel A only has two real values, "definitely succeeded" and
    "definitely failed" — no PENDING, since it's a synchronous channel."""

    def test_success(self):
        assert normalize_channel_a("微信订单支付成功") == NormalizedOutcome.SUCCESS

    def test_failed(self):
        assert normalize_channel_a("微信订单支付失败") == NormalizedOutcome.FAILED

    def test_unrecognized_value_is_unknown(self):
        # An unrecognized string must fall through to UNKNOWN rather than
        # raising — UNKNOWN is handled explicitly downstream by the state
        # machine (routed to NEEDS_REVIEW), not silently swallowed.
        assert normalize_channel_a("从没见过的状态") == NormalizedOutcome.UNKNOWN

    def test_non_string_input_is_unknown(self):
        # Even a value of the wrong type (e.g. None) should not crash the
        # program — it also falls under UNKNOWN.
        assert normalize_channel_a(None) == NormalizedOutcome.UNKNOWN


class TestNormalizeChannelB:
    """Channel B is WeChat Pay-style, with more transaction status values
    and one special trade-off around refunds."""

    @pytest.mark.parametrize(
        "raw_status,expected",
        [
            ("SUCCESS", NormalizedOutcome.SUCCESS),
            ("NOTPAY", NormalizedOutcome.PENDING),      # not yet paid, may still proceed, counts as PENDING
            ("USERPAYING", NormalizedOutcome.PENDING),  # user is in the middle of paying, also PENDING
            ("CLOSED", NormalizedOutcome.FAILED),
            ("REVOKED", NormalizedOutcome.FAILED),
            ("PAYERROR", NormalizedOutcome.FAILED),
        ],
    )
    def test_known_trade_states(self, raw_status, expected):
        # Using parametrize to lay out multiple "input -> expected output"
        # pairs as a table — effectively encoding the decision table directly
        # into the test.
        assert normalize_channel_b(raw_status) == expected

    def test_refund_is_unknown_not_failed(self):
        """REFUND (a payment that succeeded and was later refunded) is
        deliberately not treated as a plain FAILED. This is an intentional
        design trade-off: refunds/chargebacks are out of scope for this
        version of the state machine (see the Module 1 Q4 discussion), so
        they fall under UNKNOWN and get routed to explicit manual review
        instead of being misclassified as "this payment failed." This test
        exists specifically to lock in that behavior and prevent someone
        from casually changing it to FAILED later."""
        assert normalize_channel_b("REFUND") == NormalizedOutcome.UNKNOWN

    def test_case_insensitive(self):
        # Case-insensitive — real transaction status codes are normally all
        # uppercase, but this guards against a channel occasionally sending
        # lowercase values and having them misclassified as UNKNOWN.
        assert normalize_channel_b("success") == NormalizedOutcome.SUCCESS

    def test_unrecognized_value_is_unknown(self):
        assert normalize_channel_b("SOME_NEW_STATE") == NormalizedOutcome.UNKNOWN


class TestNormalizeChannelC:
    """Channel C is, by design, prone to returning status codes we've never
    seen before; this class specifically verifies that the UNKNOWN fallback
    actually works."""

    def test_success(self):
        assert normalize_channel_c("SUCCESS") == NormalizedOutcome.SUCCESS

    def test_failed_and_fail_both_map_to_failed(self):
        # Two spellings of the same meaning (FAILED / FAIL) must both map
        # correctly — the code shouldn't only recognize one of them.
        assert normalize_channel_c("FAILED") == NormalizedOutcome.FAILED
        assert normalize_channel_c("FAIL") == NormalizedOutcome.FAILED

    def test_pending_and_processing_both_map_to_pending(self):
        assert normalize_channel_c("PENDING") == NormalizedOutcome.PENDING
        assert normalize_channel_c("PROCESSING") == NormalizedOutcome.PENDING

    def test_unrecognized_status_code_is_unknown(self):
        """Channel C is designed to occasionally produce status codes we've
        never seen before — this test verifies that Channel C's core design
        premise itself is handled correctly; it isn't just an arbitrary
        extra case."""
        assert normalize_channel_c("SOME_WEIRD_CODE_9527") == NormalizedOutcome.UNKNOWN
