"""Channel C (unreliable) adapter — Phase A, hand-written by Evan.

Responsibility boundary:
- Only responsible for packaging Channel C's raw response data into a RawChannelEvent.
- Does not translate status, and does not judge whether a status is valid.
- Timeouts and malformed data use different exception types.
- raw_data preserves the complete original input.
"""

import copy
import hashlib
import json
from datetime import datetime, timezone

from app.core.events import RawChannelEvent

CHANNEL_ID = "channel_c"


class ChannelTimeoutError(Exception):
    """Raised when Channel C times out or returns no response."""


def _generate_event_id(raw: dict) -> str:
    """When the channel provides no response ID, generate a stable event_id from the full raw data.

    An identical raw response will generate the same ID, making it easy to identify
    duplicate events later.
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


def adapt_channel_c(raw: dict | None) -> RawChannelEvent:
    """Convert Channel C's raw response data into a RawChannelEvent.

    Normal input example:
    {
        "商户订单号": "order_001",
        "渠道交易号": "channel_tx_001",
        "响应ID": "response_001",
        "状态码": "SUCCESS"
    }

    Timeout input:
        None
    """

    # None explicitly indicates the channel returned no response at all.
    # This is not a field-format error, so it uses a dedicated timeout exception.
    if raw is None:
        raise ChannelTimeoutError("Channel C request timed out or returned no response")

    if not isinstance(raw, dict):
        raise TypeError("Channel C raw data must be a dict or None")

    payment_id = raw.get("商户订单号")
    if not isinstance(payment_id, str) or not payment_id.strip():
        raise ValueError("Channel C data is missing a valid '商户订单号' (merchant order number)")

    # Channel C may or may not provide a response ID.
    # If present, use it directly; if not, generate a stable hash from the full raw data.
    response_id = raw.get("响应ID")

    if response_id is not None and str(response_id).strip():
        event_id = str(response_id).strip()
    else:
        event_id = _generate_event_id(raw)

    return RawChannelEvent(
        payment_id=payment_id.strip(),
        event_id=event_id,
        channel_id=CHANNEL_ID,

        # Use the UTC time this system actually received the response.
        received_at=datetime.now(timezone.utc),

        # Preserve the complete raw response.
        # Unknown status codes are kept as-is, to be handled by downstream
        # validation/normalisation.
        raw_data=copy.deepcopy(raw),
    )
