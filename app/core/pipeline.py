"""Event-processing pipeline — Phase B (AI-authored, human-reviewed).

Wires together adapter -> validation/normalisation -> state machine -> persistence.
This is the **only** place in the whole project that "knows which channels exist in the
system" — it dispatches by channel_id to the corresponding adapter / normalize function /
raw status field name. The other modules (adapter, validation, state machine) have no
knowledge of each other; only this module connects them together.
"""

from datetime import datetime, timezone

from app.core.channels.channel_a import adapt_channel_a
from app.core.channels.channel_b import adapt_channel_b
from app.core.channels.channel_c import ChannelTimeoutError, adapt_channel_c
from app.core.db import (
    DEFAULT_DB_PATH,
    get_connection,
    get_events_for_payment,
    init_db,
    insert_raw_event,
    upsert_payment_state,
)
from app.core.events import PaymentState
from app.core.state_machine import compute_channel_status
from app.core.validation import normalize_channel_a, normalize_channel_b, normalize_channel_c

# Three "routing tables": given a channel_id, look up which function/field name to use to
# process it. To add channel D in the future, just add one row to each of these three
# tables — no need to change the process_channel_event logic below.

ADAPTERS = {
    "channel_a": adapt_channel_a,
    "channel_b": adapt_channel_b,
    "channel_c": adapt_channel_c,
}

NORMALIZERS = {
    "channel_a": normalize_channel_a,
    "channel_b": normalize_channel_b,
    "channel_c": normalize_channel_c,
}

# What each channel calls the "status" field in its own raw data — matches the examples
# in each channel's docstring.
# (Channel A calls it "状态", Channel B calls it "交易状态", Channel C calls it "状态码" —
# the three channels deliberately use different field names, precisely to demonstrate that
# "each channel has its own format, so this routing layer is required to adapt between them.")
STATUS_FIELD_BY_CHANNEL = {
    "channel_a": "状态",
    "channel_b": "交易状态",
    "channel_c": "状态码",
}


class UnknownChannelError(Exception):
    """Raised when a request specifies a channel_id the system doesn't recognize (not in the
    three routing tables above)."""


class ChannelTimeoutOccurred(Exception):
    """Channel timeout — this exception exists specifically to carry a payment_id, so that
    upstream (the FastAPI layer) can clearly report which order's request timed out.

    Why not just use the ChannelTimeoutError raised by the channel adapter directly: that
    exception doesn't carry a payment_id (the channel returned no data at all, so the adapter
    has no way to parse a payment_id out of it). But whoever calls this pipeline function
    already made this call specifically to look up a particular payment_id, so this layer
    re-wraps the payment_id into a new exception and propagates it upward.
    """

    def __init__(self, payment_id: str):
        self.payment_id = payment_id
        super().__init__(f"Channel timeout, no response received: payment_id={payment_id}")


def process_channel_event(
    channel_id: str,
    payment_id: str,
    raw,
    db_path: str = DEFAULT_DB_PATH,
) -> PaymentState:
    """Process a single channel event end to end, in five steps:

    1. Look up the corresponding adapter by channel_id and package raw into a RawChannelEvent.
    2. Store this event in the audit log table (if event_id is a duplicate, the database
       automatically de-duplicates it and it won't be stored twice).
    3. Re-read **the entire** history of events for this order (not just the new one).
    4. Re-normalize every historical event, and hand them to the state machine to jointly
       determine the latest status.
    5. Store the latest status in the database and return it to the caller.

    Note on steps 3-4: every call "recomputes the entire history from scratch" rather than
    "incrementally updating on top of the previous state." This is simpler and less
    bug-prone (no need to worry about whether the previous intermediate result was correct),
    and is good enough for a small-scale simulated scenario like this one; if order volume
    ever grows to thousands of events per order, this would become a performance
    bottleneck and would need to be changed to incremental computation — that optimization
    is deliberately not done now (YAGNI).

    The payment_id parameter is mainly used for error context if step 1 fails (timeout);
    in the normal case, the payment_id actually persisted to the database is the one parsed
    by the adapter from raw, not the payment_id passed in by the caller (to avoid confusion
    about which one takes precedence if they disagree).
    """
    if channel_id not in ADAPTERS:
        raise UnknownChannelError(channel_id)

    adapter = ADAPTERS[channel_id]
    try:
        event = adapter(raw)
    except ChannelTimeoutError:
        # The channel adapter's timeout exception is "translated" here into a version that
        # carries payment_id context, then re-raised.
        raise ChannelTimeoutOccurred(payment_id) from None

    conn = get_connection(db_path)
    try:
        init_db(conn)  # Creates tables if they don't exist; a no-op otherwise, safe to call every time
        insert_raw_event(conn, event)  # Duplicate event_id is silently de-duplicated (idempotent)

        # Key point: this queries "all events belonging to this order", not just the one
        # just inserted. The state machine needs to see the full history to correctly
        # detect conflicts, count confirmations, etc.
        events = get_events_for_payment(conn, event.payment_id)

        outcomes = []
        for e in events:
            # Each historical event may come from a different channel, so look up each
            # one's own channel_id in the tables to get the right normalize function and
            # the right status field name for that channel.
            normalize = NORMALIZERS[e.channel_id]
            status_field = STATUS_FIELD_BY_CHANNEL[e.channel_id]
            outcomes.append(normalize(e.raw_data.get(status_field)))

        status = compute_channel_status(outcomes)
        state = PaymentState(
            payment_id=event.payment_id,
            status=status,
            source_event_ids=[e.event_id for e in events],
            last_updated=datetime.now(timezone.utc),
        )
        upsert_payment_state(conn, state)  # Updates if it exists, inserts if it doesn't
        return state
    finally:
        # Whether the block above succeeded or raised, the connection must be closed —
        # it must never leak.
        conn.close()
