"""Canonical payment event schema — Phase A, hand-written baseline.

Designed and implemented directly by Evan (Claude used only for code review, not for
authoring code).
Corresponds to the Module 1 discussion: RawChannelEvent (raw record, append-only) +
PaymentState (the system's current authoritative state, derived from RawChannelEvent) +
an Enum defining the valid status values.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

# TODO(Evan): Define the PaymentStatus Enum here,
# covering at minimum the statuses discussed in Module 1:
# PENDING / CHANNEL_CONFIRMED / CHANNEL_FAILED / NEEDS_REVIEW / RECONCILED_SUCCESS / RECONCILED_FAILED
class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    CHANNEL_CONFIRMED = "CHANNEL_CONFIRMED"
    CHANNEL_FAILED = "CHANNEL_FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    RECONCILED_SUCCESS = "RECONCILED_SUCCESS"
    RECONCILED_FAILED = "RECONCILED_FAILED"

# TODO(Evan): Define RawChannelEvent here (subclassing BaseModel).
# Reference the fields discussed: event_id, payment_id, channel_id, raw data, received timestamp...
# Add any other fields you think are missing.
class RawChannelEvent(BaseModel):
    event_id: str
    payment_id: str
    channel_id: str
    raw_data: dict
    received_at: datetime

# TODO(Evan): Define PaymentState here (subclassing BaseModel).
# Reference the fields discussed: payment_id, current status (using the Enum above),
# which RawChannelEvents it was derived from, last updated timestamp...
class PaymentState(BaseModel):
    payment_id: str
    status: PaymentStatus
    # source_events: list[RawChannelEvent]  # Changed because: storing the full objects duplicates
    # the data, and a single SQLite column can't hold a "list of objects".
    source_event_ids: list[str]  # Store only event_id; look up RawChannelEvent by ID for raw content
    last_updated: datetime
