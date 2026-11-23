"""Channel A (synchronous) adapter — Phase A, hand-written baseline by Evan.

Responsibility boundary:
- Only responsible for packaging Channel A's raw data into a RawChannelEvent.
- Does not translate status, does not perform payment business logic.
- raw_data preserves the complete original input.
"""

import copy
import hashlib
import json
from datetime import datetime, timezone

from app.core.events import RawChannelEvent

CHANNEL_ID = "channel_a"


def _generate_event_id(raw: dict) -> str:
    """When the channel provides no notification ID, generate a stable event_id from the raw event.

    Receiving identical data from the same channel produces the same ID,
    which can later be used for duplicate-event detection and idempotency handling.
    """
    canonical_data = json.dumps(
        {
            "channel_id": CHANNEL_ID,
            "raw_data": raw,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    digest = hashlib.sha256(canonical_data.encode("utf-8")).hexdigest()
    return f"{CHANNEL_ID}_{digest[:24]}"


def adapt_channel_a(raw: dict) -> RawChannelEvent:
    """Convert Channel A's raw response data into a RawChannelEvent.

    Channel A example:
    {
        "微信订单号": "...",
        "状态": "微信订单支付成功"
    }
    """
    if not isinstance(raw, dict):
        raise TypeError("Channel A raw data must be a dict")

    payment_id = raw.get("微信订单号")
    if not isinstance(payment_id, str) or not payment_id.strip():
        raise ValueError("Channel A data is missing a valid '微信订单号' (merchant order number)")

    # notification_id = raw.get("通知编号")  # Simplified: Channel A does not provide a notification
    # ID, so this branch is never reached.
    # if notification_id is not None and str(notification_id).strip():
    #     event_id = str(notification_id).strip()
    # else:
    #     event_id = _generate_event_id(raw)
    event_id = _generate_event_id(raw)  # Channel A has no notification ID, so we always use a content hash

    return RawChannelEvent(
        payment_id=payment_id.strip(),
        event_id=event_id,
        channel_id=CHANNEL_ID,

        # Use the time the system actually received this event, not the business
        # time claimed by the channel.
        received_at=datetime.now(timezone.utc),

        # Deep-copy the entire raw input to prevent external code from later mutating
        # raw and affecting the event record already created.
        raw_data=copy.deepcopy(raw),
    )
