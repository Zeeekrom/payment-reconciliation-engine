# Agent log

Newest entry last. Each entry: date · item · outcome · what was learned · suggested next step.

## 2026-11-18 · setup

- Added `AGENTS.md`, `agent/BACKLOG.md`, this log and a tests workflow for pull requests.
- `main` is protected: changes go through pull requests, the `tests` check must pass, force-push and
  deletion are blocked, and nobody can bypass.
- Baseline: 46 tests pass (`python -m pytest -q`, Python 3.12).
- Next: the first weekly run takes backlog item 1.
