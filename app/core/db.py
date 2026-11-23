"""SQLite persistence — Phase B (AI-authored, human-reviewed).

The two tables correspond to the two-layer design settled on in Module 1:
- raw_channel_events: an append-only audit log, with event_id as the primary key —
  insertion naturally provides idempotent de-duplication (the mechanism discussed in
  Module 1 Q3; this is where it's actually implemented).
- payment_states: the system's current authoritative status, one row per payment_id,
  which can be overwritten/updated.
"""

import json
import os
import sqlite3
from datetime import datetime

from app.core.events import PaymentState, PaymentStatus, RawChannelEvent

DEFAULT_DB_PATH = "data/db/payments.db"


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_channel_events (
            event_id TEXT PRIMARY KEY,
            payment_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            raw_data TEXT NOT NULL,
            received_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_states (
            payment_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            source_event_ids TEXT NOT NULL,
            last_updated TEXT NOT NULL
        )
        """
    )
    conn.commit()


def insert_raw_event(conn: sqlite3.Connection, event: RawChannelEvent) -> bool:
    """Insert a single raw event. If event_id already exists, it is silently skipped (INSERT OR IGNORE).

    Returns True if a new record was actually inserted, False if it was a duplicate
    delivery that got skipped by de-duplication.
    """
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO raw_channel_events
            (event_id, payment_id, channel_id, raw_data, received_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.payment_id,
            event.channel_id,
            json.dumps(event.raw_data, ensure_ascii=False),
            event.received_at.isoformat(),
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_events_for_payment(conn: sqlite3.Connection, payment_id: str) -> list[RawChannelEvent]:
    rows = conn.execute(
        "SELECT * FROM raw_channel_events WHERE payment_id = ? ORDER BY received_at",
        (payment_id,),
    ).fetchall()
    return [
        RawChannelEvent(
            event_id=row["event_id"],
            payment_id=row["payment_id"],
            channel_id=row["channel_id"],
            raw_data=json.loads(row["raw_data"]),
            received_at=datetime.fromisoformat(row["received_at"]),
        )
        for row in rows
    ]


def upsert_payment_state(conn: sqlite3.Connection, state: PaymentState) -> None:
    conn.execute(
        """
        INSERT INTO payment_states (payment_id, status, source_event_ids, last_updated)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(payment_id) DO UPDATE SET
            status = excluded.status,
            source_event_ids = excluded.source_event_ids,
            last_updated = excluded.last_updated
        """,
        (
            state.payment_id,
            state.status.value,
            json.dumps(state.source_event_ids),
            state.last_updated.isoformat(),
        ),
    )
    conn.commit()


def get_payment_state(conn: sqlite3.Connection, payment_id: str) -> PaymentState | None:
    row = conn.execute(
        "SELECT * FROM payment_states WHERE payment_id = ?", (payment_id,)
    ).fetchone()
    if row is None:
        return None
    return PaymentState(
        payment_id=row["payment_id"],
        status=PaymentStatus(row["status"]),
        source_event_ids=json.loads(row["source_event_ids"]),
        last_updated=datetime.fromisoformat(row["last_updated"]),
    )
