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
- [ ] **Check Channel B in `docs/ARCHITECTURE.md`.** The table says its delivery is synchronous.
  Compare with the adapter code and tests and make the document match the code.
- [ ] **Remove dangling references.** `app/agents/code_review_agent.py` and `app/agents/dev_team.py`
  cite `docs/DESIGN_DECISIONS.md` "D007" and `app/agents/fixtures/`, which are not in this
  repository. Reword the comments so they no longer point at missing files.
- [ ] **Keep README numbers current.** Whenever the test count changes, update "At a glance" and
  "Verification evidence" in `README.md` and `README.zh-CN.md`.

## Owner only (not for the agent)

- The poster (`docs/poster.jpg`) says 77 automated tests; the repository has 46.
- Licence and terms decisions.
