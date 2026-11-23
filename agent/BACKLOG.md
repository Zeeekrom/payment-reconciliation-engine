# Agent backlog

Work top to bottom, one item per week. Tick an item only in the pull request that does it, so it
stays open if the pull request is closed. The owner may reorder, add or remove items.

- [ ] **Record the reviewer in `resolve_manual_review()`.** `app/core/state_machine.py` accepts
  `resolved_by` but never stores it, so the record cannot say who made the decision. Store who
  decided and when, with tests. Keep all other behaviour the same.
- [ ] **Test `resolve_manual_review()`.** Both decisions, the three `ValueError` cases, and a
  regression test that `last_updated` is timezone-aware UTC (FC011).
- [ ] **Test `app/core/db.py`** with a temporary SQLite file: a repeated event ID is stored once
  (`INSERT OR IGNORE`); upserting a payment state replaces the previous row.
- [ ] **Test `app/core/pipeline.py` end to end**, offline, with simulated payloads: a re-delivered
  notification, conflicting signals going to `NEEDS_REVIEW`, and Channel C returning nothing.

## Owner only (not for the agent)

- The poster was taken out of the repository in November 2026 because it was out of date; whether to
  make a new one is the owner's call.
- Licence and terms decisions.
