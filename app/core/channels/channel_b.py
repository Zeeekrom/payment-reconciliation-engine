"""Channel B (asynchronous, WeChat Pay-style) adapter — Phase A, hand-written baseline by Evan.

Responsibility boundary:
- Only responsible for packaging Channel B's raw asynchronous notification into a RawChannelEvent.
- Does not translate transaction status, does not perform payment business logic.
- raw_data preserves the complete original notification.
"""

import copy
from datetime import datetime, timezone

from app.core.events import RawChannelEvent

CHANNEL_ID = "channel_b"


def adapt_channel_b(raw: dict) -> RawChannelEvent:
    """Convert Channel B's raw asynchronous notification into a RawChannelEvent.

    Channel B example:
    {
        "商户订单号": "...",
        "微信支付订单号": "...",
        "通知ID": "...",
        "交易状态": "SUCCESS"
    }
    """
    if not isinstance(raw, dict):
        raise TypeError("Channel B raw data must be a dict")

    # Use the merchant order number our own system assigned when the order was created.
    # The WeChat Pay order number is an external channel transaction reference and should
    # not be used as the internal primary payment_id.
    payment_id = raw.get("商户订单号")
    if not isinstance(payment_id, str) or not payment_id.strip():
        raise ValueError("Channel B data is missing a valid '商户订单号' (merchant order number)")

    # The asynchronous channel provides a genuine notification ID, used to identify the
    # notification and detect duplicate delivery.
    # We deliberately do not fall back to a content hash here, since that could mask
    # incomplete upstream data and cannot accurately represent the identity of a real
    # notification.
    event_id = raw.get("通知ID")
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("Channel B data is missing a valid '通知ID' (notification ID)")

    return RawChannelEvent(
        payment_id=payment_id.strip(),
        event_id=event_id.strip(),
        channel_id=CHANNEL_ID,

        # Use the UTC time this system actually received the notification.
        received_at=datetime.now(timezone.utc),

        # Preserve the entire raw notification, including the channel's own transaction
        # reference and the raw transaction status.
        raw_data=copy.deepcopy(raw),
    )
