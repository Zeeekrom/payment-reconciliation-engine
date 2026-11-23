"""State machine — Phase A, implemented by Evan.

Responsibility: given all the NormalizedOutcomes (already-normalized observations) recorded
under a payment_id, determine which PaymentStatus it should currently be in.

Not responsible for:
- Does not know, and does not need to know, any channel-specific details — that is exactly
  what the normalize layer exists for.

Final rules (each branch has been checked individually against a decision table, nothing missed):
1. SUCCESS and FAILED both present (conflict) -> NEEDS_REVIEW
2. UNKNOWN present (and no conflict as above) -> NEEDS_REVIEW
3. Only FAILED present (no SUCCESS, no UNKNOWN) -> CHANNEL_FAILED
4. Only SUCCESS present (no FAILED, no UNKNOWN):
   - SUCCESS count >= 2 -> CHANNEL_CONFIRMED
   - Only 1 SUCCESS -> PENDING (for a financial/payment system, it's better to wait for one
     more confirmation than to accept the risk of confirming off a single observation — this
     is a deliberate design choice, not an arbitrary one)
5. Only PENDING, or no observations at all -> PENDING

The second half of this file, resolve_manual_review(), is a separate function that converts a
manually approved/rejected review into RECONCILED_SUCCESS/RECONCILED_FAILED. Its trigger
(a manual action) and its inputs differ from compute_channel_status() (event-driven), so it
was deliberately kept as a separate function rather than merged into one.
Implemented by a Layer 3 Planner -> Developer -> Tester -> Reviewer team (AI-authored,
human-reviewed and approved by Evan).
"""

from collections import Counter
from datetime import datetime, timezone

from app.core.db import get_connection, get_payment_state, upsert_payment_state
from app.core.events import PaymentState, PaymentStatus
from app.core.validation import NormalizedOutcome


def compute_channel_status(outcomes: list[NormalizedOutcome]) -> PaymentStatus:
    """Given a list of normalized observations, determine which PaymentStatus applies.

    TODO(Evan): Implement following the 5 rules already defined above in the docstring.
    Hint: first count how many times SUCCESS/FAILED/UNKNOWN appear in outcomes
    (e.g. using collections.Counter), then check them in priority order from top to bottom.
    """

    # TODO(Evan): Implement here

    # Use Counter to tally how many times each normalized outcome occurs.
    # PENDING doesn't need to participate separately in the first four rules' priority
    # check: when SUCCESS, FAILED, and UNKNOWN are all absent, PENDING is returned at the end.
    counts = Counter(outcomes)

    success_count = counts[NormalizedOutcome.SUCCESS]
    failed_count = counts[NormalizedOutcome.FAILED]
    unknown_count = counts[NormalizedOutcome.UNKNOWN]

    # Rule 1:
    # The same payment_id has both success and failure observations, meaning different
    # events conflict with each other. The system cannot automatically pick a side, so it
    # must go to manual review.
    if success_count > 0 and failed_count > 0:
        return PaymentStatus.NEEDS_REVIEW

    # Rule 2:
    # No SUCCESS/FAILED conflict, but an unrecognized channel status appeared.
    # UNKNOWN must not be automatically interpreted as success, failure, or pending.
    if unknown_count > 0:
        return PaymentStatus.NEEDS_REVIEW

    # Rule 3:
    # FAILED is present, and we've already confirmed there's no SUCCESS and no UNKNOWN.
    # Even if PENDING is also present, an explicit failure result still takes priority.
    if failed_count > 0:
        return PaymentStatus.CHANNEL_FAILED

    # Rule 4:
    # SUCCESS is present, and we've already confirmed there's no FAILED and no UNKNOWN.
    # Only two or more success observations are considered sufficiently confirmed on the
    # channel side.
    if success_count >= 2:
        return PaymentStatus.CHANNEL_CONFIRMED

    # With only one success observation, don't confirm yet — keep waiting for more evidence.
    if success_count == 1:
        return PaymentStatus.PENDING

    # Rule 5:
    # Reaching here means there's no SUCCESS, FAILED, or UNKNOWN.
    # outcomes may be empty, or may contain only one or more PENDING entries.
    return PaymentStatus.PENDING


def resolve_manual_review(
    payment_id: str, decision: str, resolved_by: str, db_path: str = "data/db/payments.db"
) -> PaymentState:
    """Process a manual review decision, converting a NEEDS_REVIEW status into a final status.

    Args:
        payment_id: The order ID
        decision: The review decision, must be 'approve_success' or 'approve_failed'
        resolved_by: Identifier of the reviewer
        db_path: Database path

    Returns:
        The updated PaymentState

    Raises:
        ValueError: If the order does not exist, its status is not NEEDS_REVIEW, or the
            decision is invalid
    """
    if decision not in ("approve_success", "approve_failed"):
        raise ValueError(f"Invalid decision parameter: {decision}. Must be 'approve_success' or 'approve_failed'")

    conn = get_connection(db_path)
    try:
        current_state = get_payment_state(conn, payment_id)
        if current_state is None:
            raise ValueError(f"Order does not exist: {payment_id}")

        if current_state.status != PaymentStatus.NEEDS_REVIEW:
            raise ValueError(f"Order status is not NEEDS_REVIEW, current status: {current_state.status}")

        new_status = PaymentStatus.RECONCILED_SUCCESS if decision == "approve_success" else PaymentStatus.RECONCILED_FAILED
        new_state = PaymentState(
            payment_id=payment_id,
            status=new_status,
            source_event_ids=current_state.source_event_ids,  # Keep the original event IDs unchanged
            # last_updated=datetime.now(),
            # ^ Original AI-generated version, fixed on 2026-08-10 (see docs/ENGINEERING_LOG.md,
            # FC011): it was missing timezone.utc, producing a naive local timestamp that could
            # differ from the UTC timestamps written by pipeline.py and the three channel
            # adapters by 8-10 hours (depending on the machine's timezone). Mixing two different
            # timezone semantics of timestamps within the same payment_states table would cause
            # incorrect time-difference calculations when investigating payment disputes.
            last_updated=datetime.now(timezone.utc),
        )

        upsert_payment_state(conn, new_state)
        return new_state
    finally:
        conn.close()
