# AGENTS.md

Rules for AI agents working in this repository: the weekly maintenance agent, any other coding
agent, and automated reviewers such as Codex.

## What this repository is

A payment reconciliation engine: three simulated payment channels in, one auditable payment status
out. Layer 1 (`app/core/`) is deterministic and calls no model. Layer 2 (`app/copilot/`) calls a
paid hosted model. Layer 3 (the agent pipeline) and the production prompts are private and not in this
snapshot; `prompts/copilot_system_v1.md` is a public outline. All payment data is simulated. See
`README.md`. The architecture notes, engineering log and design decisions that code comments cite
(FC001–FC011, D-001–D-003) are private.

## Commands

- Install: `python -m pip install -r requirements.txt`
- Test: `python -m pytest -q` (offline; no API key needed)

## How to work

- One small, focused change per pull request. Branch name `claude/agent-<YYYY-MM-DD>`. Open it as a
  **draft** pull request titled `[agent] <what changed>`, and say that an AI agent made it.
- Every behaviour change comes with tests. All tests must pass before the pull request is opened.
- Keep `README.md` and `README.zh-CN.md` in step: same sections, same claims. The READMEs give no
  test count; do not add one.
- In the same pull request, tick the item in `agent/BACKLOG.md` and append an entry to
  `agent/LOG.md`.
- Never merge. The owner reviews and merges.
- When fixing a bug, keep the original line as a comment beside the fix, as the existing code does
  (see the FC011 comment in `app/core/state_machine.py`). The engineering log is private, so
  describe the problem in the pull request and in `agent/LOG.md`. Leave the existing comments that
  cite `docs/ENGINEERING_LOG.md` or `docs/DESIGN_DECISIONS.md` as they are; those files are private,
  not missing.

## Off-limits

- `LICENSE`, `film/`, the images in `docs/`, `.github/workflows/`, and repository settings.
- Paid model calls. Do not run Layer 2 or Layer 3, do not use or add `BIGMODEL_API_KEY`, and do not
  add tests that need a network connection.
- New or upgraded dependencies, unless the owner has approved them in an issue.
- Posting anywhere outside this repository.

## For reviewers

Flag: behaviour changes without tests; README drift between the two languages; any
change to an off-limits path; any new network call, paid call or dependency.
