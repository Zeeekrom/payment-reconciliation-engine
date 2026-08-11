"""Tests for the state machine — Phase B, written by Claude (AI-assisted).

Evan hand-wrote app/core/state_machine.py; this test suite verifies it,
covering every combination from the decision table Evan drew up.

state_machine.py's evaluation priority (useful to have side-by-side when
reviewing):
1. SUCCESS and FAILED both present (conflict) -> NEEDS_REVIEW
2. UNKNOWN present (no conflict) -> NEEDS_REVIEW
3. Only FAILED -> CHANNEL_FAILED
4. Only SUCCESS, with >= 2 observations -> CHANNEL_CONFIRMED; with exactly 1
   -> PENDING (a financial scenario, so it's safer to wait for more signal)
5. Only PENDING, or no observations at all -> PENDING

Each test method name below corresponds roughly to one row of the decision
table — the name itself describes which scenario that row covers.
"""

from app.core.events import PaymentStatus
from app.core.state_machine import compute_channel_status
from app.core.validation import NormalizedOutcome as O


class TestComputeChannelStatus:
    # --- Rule 5: nothing has happened yet ---

    def test_no_events_yet_is_pending(self):
        # No observations at all (order just created) — the most basic default state.
        assert compute_channel_status([]) == PaymentStatus.PENDING

    def test_only_pending_observations_stays_pending(self):
        assert compute_channel_status([O.PENDING, O.PENDING]) == PaymentStatus.PENDING

    # --- Rule 4: only SUCCESS observations — testing how many are "enough" ---

    def test_single_success_is_not_enough_stays_pending(self):
        """This covers a gap the decision table surfaced: with exactly 1
        SUCCESS observation, no conflict, and no UNKNOWN, the original rules
        left the resulting state undefined. Since this is a financial/payment
        scenario, the decision was to not accept the risk of confirming on a
        single signal — stay at PENDING and wait for a second, independent
        confirmation. This is the single most important test in this design;
        it directly reflects a real design rework.
        """
        assert compute_channel_status([O.SUCCESS]) == PaymentStatus.PENDING

    def test_two_success_confirms(self):
        # Only once 2 independent SUCCESS observations accumulate is the
        # channel side considered truly confirmed.
        assert compute_channel_status([O.SUCCESS, O.SUCCESS]) == PaymentStatus.CHANNEL_CONFIRMED

    def test_more_than_two_success_still_confirms(self):
        # More than 2 is still CONFIRMED — a higher count doesn't change the
        # outcome; the rule only cares whether the threshold of 2 is met.
        assert compute_channel_status([O.SUCCESS] * 5) == PaymentStatus.CHANNEL_CONFIRMED

    def test_success_with_pending_still_needs_two_success(self):
        # Mixing in PENDING observations doesn't affect the outcome — PENDING
        # by itself carries no "confirming" or "denying" information; what
        # actually matters is still whether the SUCCESS count is sufficient.
        assert compute_channel_status([O.PENDING, O.SUCCESS]) == PaymentStatus.PENDING

    # --- Rule 3: only FAILED ---

    def test_single_failed_fails(self):
        # FAILED doesn't need multiple observations to take effect — this is
        # intentionally asymmetric with SUCCESS, because assuming failure is
        # safer than mistakenly assuming success (under-crediting a user is a
        # far smaller risk than over-crediting one).
        assert compute_channel_status([O.FAILED]) == PaymentStatus.CHANNEL_FAILED

    def test_failed_takes_priority_over_pending(self):
        assert compute_channel_status([O.PENDING, O.FAILED]) == PaymentStatus.CHANNEL_FAILED

    # --- Rule 1: SUCCESS and FAILED both present = channel conflict ---

    def test_success_and_failed_conflict_needs_review(self):
        # Even if SUCCESS has already reached the threshold of 2, the
        # presence of a FAILED observation means the system must not
        # automatically pick a side — it has to route to NEEDS_REVIEW. This
        # is a direct application of the "never auto-resolve a conflict"
        # principle established for this design (see Q5).
        assert compute_channel_status([O.SUCCESS, O.SUCCESS, O.FAILED]) == PaymentStatus.NEEDS_REVIEW

    # --- Rule 2: UNKNOWN present ---

    def test_unknown_alone_needs_review(self):
        # UNKNOWN appearing on its own (with no SUCCESS/FAILED) is enough by
        # itself to trigger manual review — it isn't waved through just
        # because it "doesn't look like a big deal."
        assert compute_channel_status([O.PENDING, O.UNKNOWN]) == PaymentStatus.NEEDS_REVIEW

    def test_unknown_with_success_still_needs_review(self):
        # Even with a SUCCESS observation present, an UNKNOWN still prevents
        # an automatic success determination — an uncertain signal must be
        # seen by a human, not drowned out by a signal that "looks fine."
        assert compute_channel_status([O.SUCCESS, O.UNKNOWN]) == PaymentStatus.NEEDS_REVIEW

    def test_unknown_with_conflict_still_needs_review(self):
        # A conflict plus an UNKNOWN together still resolves to NEEDS_REVIEW
        # (both paths converge on the same outcome), verifying that the
        # priority ordering of Rule 1 and Rule 2 doesn't conflict with itself.
        assert compute_channel_status([O.SUCCESS, O.FAILED, O.UNKNOWN]) == PaymentStatus.NEEDS_REVIEW
