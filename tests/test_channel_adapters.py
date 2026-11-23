"""Tests for the Channel A / B / C adapters — Phase B, written by Claude (AI-assisted).

Evan hand-wrote app/core/channels/channel_a.py, channel_b.py, and
channel_c.py; this test suite verifies them.

Each of the three channels has a different "personality," so the test focus
differs accordingly:
- Channel A (synchronous): has no natural notification ID, so the focus is on
  the mechanism that generates event_id from a content hash.
- Channel B (asynchronous, WeChat Pay-style): has two different order
  numbers, so the focus is on making sure payment_id is pulled from the
  correct field.
- Channel C (unstable): can time out and can return status codes we've never
  seen before, so the focus is on using a dedicated exception type for
  timeouts and not raising on unknown status codes.

When reviewing, it's enough to read each test method's name plus the comment
above it — no need to dig into the assertion details.
"""

import copy

import pytest

from app.core.channels.channel_a import adapt_channel_a
from app.core.channels.channel_b import adapt_channel_b
from app.core.channels.channel_c import ChannelTimeoutError, adapt_channel_c
from app.core.events import RawChannelEvent


class TestChannelA:
    """Channel A: a synchronous channel with no built-in notification ID."""

    def test_valid_input_produces_raw_channel_event(self):
        # Happy path: valid input produces a RawChannelEvent with fields mapped correctly.
        raw = {"微信订单号": "ORDER_001", "状态": "微信订单支付成功"}

        event = adapt_channel_a(raw)

        assert isinstance(event, RawChannelEvent)
        assert event.payment_id == "ORDER_001"
        assert event.channel_id == "channel_a"
        assert event.raw_data == raw

    def test_event_id_is_deterministic_for_identical_input(self):
        # Channel A has no notification ID, so event_id is generated from a
        # content hash. Identical content must always produce the same
        # event_id, otherwise it can't be used for deduplication (idempotency).
        raw = {"微信订单号": "ORDER_001", "状态": "微信订单支付成功"}

        event_1 = adapt_channel_a(raw)
        event_2 = adapt_channel_a(copy.deepcopy(raw))

        assert event_1.event_id == event_2.event_id

    def test_event_id_differs_for_different_input(self):
        # Different content (here, a different status) must produce a
        # different event_id, otherwise a "success" notification and a
        # "failed" notification would be mistaken for the same duplicate event.
        raw_success = {"微信订单号": "ORDER_001", "状态": "微信订单支付成功"}
        raw_failed = {"微信订单号": "ORDER_001", "状态": "微信订单支付失败"}

        event_success = adapt_channel_a(raw_success)
        event_failed = adapt_channel_a(raw_failed)

        assert event_success.event_id != event_failed.event_id

    def test_raw_data_is_deep_copied_not_referenced(self):
        # The adapter uses copy.deepcopy(raw) internally; this verifies the
        # effect: if the caller later mutates the original raw dict, the
        # already-created RawChannelEvent must not be affected.
        raw = {"微信订单号": "ORDER_001", "状态": "微信订单支付成功"}

        event = adapt_channel_a(raw)
        raw["状态"] = "被后续代码改动"  # simulate the caller mutating the original dict afterward

        assert event.raw_data["状态"] == "微信订单支付成功"

    def test_missing_payment_id_raises_value_error(self):
        # Missing "微信订单号" (the field we treat as the payment_id source)
        # must raise an error rather than silently passing through.
        with pytest.raises(ValueError):
            adapt_channel_a({"状态": "微信订单支付成功"})

    def test_non_dict_input_raises_type_error(self):
        # When the input type itself is wrong (e.g. a plain string), it
        # should raise TypeError immediately rather than crashing somewhere
        # downstream.
        with pytest.raises(TypeError):
            adapt_channel_a("not a dict")


class TestChannelB:
    """Channel B: an asynchronous channel (WeChat Pay-style) whose raw data
    contains two different order numbers."""

    def _valid_raw(self, **overrides):
        # A template of valid raw data for tests; each test overrides fields as needed.
        raw = {
            "商户订单号": "ORDER_001",       # the payment_id our own system recognizes
            "微信支付订单号": "WX_TXN_001",   # the channel's own transaction number, not the payment_id
            "通知ID": "NOTIFY_001",           # this notification's own ID, used as the event_id
            "交易状态": "SUCCESS",
        }
        raw.update(overrides)
        return raw

    def test_valid_input_uses_merchant_order_no_as_payment_id(self):
        raw = self._valid_raw()

        event = adapt_channel_b(raw)

        assert isinstance(event, RawChannelEvent)
        # This is the most critical design decision for Channel B: payment_id
        # must come from "商户订单号" (merchant order number), not the
        # channel's own "微信支付订单号" (that's an external transaction
        # number whose generation timing we don't control).
        assert event.payment_id == "ORDER_001"
        assert event.event_id == "NOTIFY_001"
        assert event.channel_id == "channel_b"
        assert event.raw_data == raw

    def test_missing_merchant_order_no_raises_value_error(self):
        raw = self._valid_raw()
        del raw["商户订单号"]

        with pytest.raises(ValueError):
            adapt_channel_b(raw)

    def test_missing_notify_id_raises_value_error(self):
        # Channel B has a real notification ID, so a missing one should raise
        # an error — unlike Channel A, it can't fall back to a content hash,
        # because doing so would mask the fact that the upstream data is
        # incomplete.
        raw = self._valid_raw()
        del raw["通知ID"]

        with pytest.raises(ValueError):
            adapt_channel_b(raw)

    def test_missing_channel_transaction_id_does_not_raise(self):
        """Regression test: this covers a point that was changed during code
        review; the test exists specifically to keep it from being reverted.

        When the channel's transaction field ("微信支付订单号") is missing
        (e.g. for a NOTPAY status, where no actual transaction has happened
        yet), this should not raise, because the adapter never stores that
        value into any dedicated field on RawChannelEvent (raw_data already
        preserves the whole notification as-is). An earlier version enforced
        this field as required, which incorrectly rejected these legitimate
        notifications; that was fixed during review.
        """
        raw = self._valid_raw(交易状态="NOTPAY")
        del raw["微信支付订单号"]

        event = adapt_channel_b(raw)

        assert event.payment_id == "ORDER_001"
        assert "微信支付订单号" not in event.raw_data

    def test_non_dict_input_raises_type_error(self):
        with pytest.raises(TypeError):
            adapt_channel_b("not a dict")


class TestChannelC:
    """Channel C: an unstable channel — it can time out and can return
    status codes we've never seen before."""

    def _valid_raw(self, **overrides):
        raw = {
            "商户订单号": "ORDER_001",
            "渠道交易号": "channel_tx_001",
            "响应ID": "RESPONSE_001",   # Channel C may or may not provide this
            "状态码": "SUCCESS",
        }
        raw.update(overrides)
        return raw

    def test_valid_input_uses_response_id_as_event_id(self):
        # When Channel C provides a "响应ID" (response ID), it's used
        # directly as the event_id, with no hash fallback needed.
        raw = self._valid_raw()

        event = adapt_channel_c(raw)

        assert isinstance(event, RawChannelEvent)
        assert event.payment_id == "ORDER_001"
        assert event.event_id == "RESPONSE_001"
        assert event.channel_id == "channel_c"
        assert event.raw_data == raw

    def test_missing_response_id_falls_back_to_stable_hash(self):
        # When Channel C doesn't provide a "响应ID", it falls back to a
        # content hash to generate event_id, just like Channel A — and
        # identical content must still produce the same event_id
        # (idempotency).
        raw = self._valid_raw()
        del raw["响应ID"]

        event_1 = adapt_channel_c(raw)
        event_2 = adapt_channel_c(copy.deepcopy(raw))

        assert event_1.event_id == event_2.event_id

    def test_none_raises_channel_timeout_error(self):
        """None represents a channel timeout / no response — a fundamentally
        different problem from "malformed data." It must raise a dedicated
        ChannelTimeoutError rather than being lumped in with
        ValueError/TypeError, so that upstream code can distinguish "should
        retry" from "the data itself is bad."""
        with pytest.raises(ChannelTimeoutError):
            adapt_channel_c(None)

    def test_missing_payment_id_raises_value_error(self):
        raw = self._valid_raw()
        del raw["商户订单号"]

        with pytest.raises(ValueError):
            adapt_channel_c(raw)

    def test_non_dict_non_none_input_raises_type_error(self):
        # An input that is neither None (timeout) nor a dict (normal data) is
        # a genuine format error.
        with pytest.raises(TypeError):
            adapt_channel_c("not a dict")

    def test_unrecognized_status_code_does_not_raise(self):
        """Channel C is designed to occasionally return status codes we've
        never seen before. The adapter's responsibility boundary is
        "package the data, don't interpret the status," so it should not
        raise here — it just needs to store the value as-is in raw_data and
        let the next layer (validation/normalization) decide what to do with
        it."""
        raw = self._valid_raw(状态码="SOME_WEIRD_CODE_9527")

        event = adapt_channel_c(raw)

        assert event.raw_data["状态码"] == "SOME_WEIRD_CODE_9527"
