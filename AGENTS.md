# AGENTS.md

Rules for AI agents working in this repository: the weekly maintenance agent, any other coding
agent, and automated reviewers such as Codex.

## What this repository is

A payment reconciliation engine: three simulated payment channels in, one auditable payment status
out. Layer 1 (`app/core/`) is deterministic and calls no model. Layer 2 (`app/copilot/`) and
Layer 3 (`app/agents/`) call a paid hosted model. All payment data is simulated. See `README.md`
and `docs/ARCHITECTURE.md`.

## Commands

- Install: `python -m pip install -r requirements.txt`
- Test: `python -m pytest -q` (46 tests on 2026-11-18; offline; no API key needed)

## How to work

- One small, focused change per pull request. Branch name `claude/agent-<YYYY-MM-DD>`. Open it as a
  **draft** pull request titled `[agent] <what changed>`, and say that an AI agent made it.
- Every behaviour change comes with tests. All tests must pass before the pull request is opened.
- Keep `README.md` and `README.zh-CN.md` in step: same sections, same numbers. If the test count
  changes, update it in both.
- In the same pull request, tick the item in `agent/BACKLOG.md` and append an entry to
  `agent/LOG.md`.
- Never merge. The owner reviews and merges.
- When fixing a bug, keep the original line as a comment beside the fix with a pointer to the
  engineering log, as the existing code does (see FC011 in `docs/ENGINEERING_LOG.md`).
  Append to `docs/ENGINEERING_LOG.md` and `docs/DESIGN_DECISIONS.md`; never rewrite old entries.

## Off-limits

- `LICENSE`, `film/`, `docs/poster.jpg`, `.github/workflows/`, and repository settings.
- Paid model calls. Do not run Layer 2 or Layer 3, do not use or add `BIGMODEL_API_KEY`, and do not
  add tests that need a network connection.
- New or upgraded dependencies, unless the owner has approved them in an issue.
- Posting anywhere outside this repository.

## For reviewers

Flag: behaviour changes without tests; README or test-count drift between the two languages; any
change to an off-limits path; any new network call, paid call or dependency.
