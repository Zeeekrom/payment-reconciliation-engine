# Architecture

## Overview

```
Channel A/B/C events → Channel Adapters → Audit Log (raw_channel_events) → Validation/Normalisation
                                                                                    ↓
                                                                          State Machine (deterministic rules)
                                                                                    ↓
                                                                      Current State (payment_states)
                                                                      ↓ (read-only)          ↓ (read-only)
                                                          Layer 2: Ops Copilot        Layer 3: AI dev team
                                                       (RAG + 3 read-only tools)   (4-agent pipeline + human gate)
```

**Core architectural boundary, enforced across every layer: an LLM must never directly change final payment state.**

This isn't a slogan — each layer enforces it with a different, concrete mechanism:
- Layer 1 involves no LLM at all. State transitions are 100% deterministic rules.
- Layer 2's three tools (`query_payment_record`, `inspect_logs`, `retrieve_rule`) can't write anything — the Copilot can only read and suggest.
- Layer 3's generated code, even after the AI reviewer returns `approved: true`, still gets a hard, code-level re-check (`apply_approved_changes()` re-runs the real test suite and requires `returncode == 0`) before anything is written to disk — a check the AI's opinion cannot influence. See `ENGINEERING_LOG.md`, FC008 and FC010, for two real cases where a reasonable-sounding AI judgment was overridden by this check.

---

## Layer 1 — Deterministic Payment Core

**Responsibility**: turn differently-formatted raw notifications from three payment channels into one consistent payment status, with zero AI involvement anywhere in this layer.

**Canonical event schema** (`app/core/events.py`) — a deliberate two-layer design:
- `RawChannelEvent`: the audit log — append-only, raw payload never modified (`event_id`, `payment_id`, `channel_id`, `raw_data: dict`, `received_at`)
- `PaymentState`: the current state — can be overwritten as new evidence arrives (`payment_id`, `status`, `source_event_ids: list[str]`, `last_updated`)

**Why two separate tables, not one**: one is *raw evidence* (what the channel actually said — append-only, never edited), the other is a *derived conclusion* (what we currently believe the status is — can be revised by later events). Think of it like an ATM's cached balance versus the bank's real ledger — the cache can be recomputed or wrong, the ledger can't be silently rewritten. If a dispute ever comes up, you need to be able to go back to the raw evidence.

**Channel adapters** (`app/core/channels/`): three channels, each with real, meaningfully different shapes —

| | Channel A | Channel B | Channel C |
|---|---|---|---|
| **Delivery** | Synchronous | Synchronous | Asynchronous, **unreliable** |
| **Order-ID field name** | different field name | different field name | different field name |
| **Status format** | full-sentence string | English enum (`SUCCESS`/`NOTPAY`/`USERPAYING`/`CLOSED`/`REVOKED`/`PAYERROR`/`REFUND`) | short English code (`SUCCESS`/`FAILED`/`FAIL`/`PENDING`/`PROCESSING`) |
| **Unique event ID** | not provided by the channel → derived from a content hash | provided by the channel | provided by the channel, but sometimes missing → falls back to a content hash |
| **Notable behavior** | no `PENDING` state defined | `REFUND` is deliberately mapped to `UNKNOWN` (refunds are out of scope for this version's state machine) | can return **no response at all** → raises a timeout error |

The whole point of this table is that these differences are absorbed entirely inside the adapter and validation layers — the state machine downstream never needs to know which channel anything came from. Adding a fourth channel later means adding one adapter and one normalizer function; the state machine doesn't change at all.

**Validation/Normalisation** (`app/core/validation.py`): translates each channel's own status strings into a shared `NormalizedOutcome` enum (`SUCCESS`/`FAILED`/`PENDING`/`UNKNOWN`) — one `normalize_channel_x()` function per channel, each operating on a single event at a time, with no cross-event reasoning.

**State Machine** (`app/core/state_machine.py`): `compute_channel_status()` tallies a batch of `NormalizedOutcome` values with a `Counter` and applies 5 priority-ordered rules. These rules weren't guessed — they came from a decision-table exercise: enumerate every combination of SUCCESS/FAILED/UNKNOWN presence and check each cell. That exercise surfaced a real gap ("exactly one SUCCESS, nothing else") the original rules hadn't accounted for. Given this is a payment context, the resolution was **at least two independent confirmations required for `CHANNEL_CONFIRMED`** — a single confirmation isn't enough, similar in spirit to requiring multiple block confirmations for a cryptocurrency deposit.

Unrecognized status codes map to `UNKNOWN` rather than raising an exception — an explicit signal that downstream logic has to handle (it routes to manual review), instead of crashing the pipeline or silently being treated as a failure.

`resolve_manual_review()`, in the same file, is a second, independently-triggered function that converts `NEEDS_REVIEW` into a final `RECONCILED_SUCCESS`/`RECONCILED_FAILED` after a human decision. It's deliberately **not merged into `compute_channel_status()`** — the trigger (a human action vs. an incoming event) and the inputs are both different in kind, which is a different situation from "should this be one function or two" than the earlier rule-grouping question above (same input type, different branches of logic → keep it as one function; different trigger and input type entirely → keep it as two).

This function is also a real example of the human-in-the-loop AI development flow described below: it was written by the AI development-team pipeline, reviewed and approved by a human, passed the code-level hard check, and merged — see `ENGINEERING_LOG.md`, FC011, for a real bug this write-back path surfaced two days after merge.

**Persistence** (`app/core/db.py`): two SQLite tables — `raw_channel_events` (`event_id` primary key, `INSERT OR IGNORE` gives free idempotent deduplication) and `payment_states` (`payment_id` primary key, upsert).

**Pipeline** (`app/core/pipeline.py`): `process_channel_event()` routes "channel ID + raw payload" to the right adapter/normalizer and runs the full chain.

---

## Layer 2 — Payment Operations Copilot

**Responsibility**: answer natural-language questions about payment records for internal ops/support staff — **read-only, advisory only**, never changes any state.

**Retrieval** (`app/copilot/retrieval.py`): a hosted embedding model plus a hand-written cosine-similarity function — no vector database. This was a deliberate simplification (see `DESIGN_DECISIONS.md`, D-001): the knowledge base is a handful of short documents, and a vector database would be over-engineering at that scale. `retrieve(query, top_k=2, min_similarity=0.3)` returns "insufficient evidence" below the similarity threshold rather than forcing an answer.

**Tools** (`app/copilot/tools.py`): three read-only tools —
- `query_payment_record`: exact lookup by ID, used when there's a specific record to check — direct SQL, not semantic search. The boundary principle: **if you can look something up exactly, don't guess.**
- `inspect_logs`: pulls the full raw audit trail for a payment
- `retrieve_rule`: semantic retrieval, used only for open-ended "what does this mean / what's the rule" questions with no specific record ID

The boundary between the two query styles is deliberate: an exact key means a deterministic answer, so it goes straight to the database; an open-ended natural-language question with no key means "which document is most relevant," which is what semantic search is for. Doing it the other way around — running a specific ID through vector search — actually reduces precision. This isn't about data volume, it's about the nature of the question.

**Tool-calling loop** (`app/copilot/copilot.py`): `ask(question, tier="strong")`, capped at 5 tool-call rounds. Default tier is `strong`, not `cheap` — see `DESIGN_DECISIONS.md`, D-002, and `ENGINEERING_LOG.md`, FC004, for the real evidence behind that choice. The system prompt is version-controlled separately in `prompts/copilot_system_v1.md`.

**Known architectural limitation** (FC004): the Copilot currently has no automated check on answer/tool-call quality — whatever the model produces gets returned as-is. This is a deliberately deferred gap, not an oversight.

---

## Layer 3 — AI Development Workflow (agent team + human approval)

**Responsibility**: demonstrate a real "AI-assisted development" loop — four agents working in sequence, producing a draft, gated by human approval and a hard code-level check. **Nothing gets written to any real project file until it clears both.**

**Four agents** (`app/agents/dev_team.py`), each an independent real LLM call using structured tool-call output (forced to return a fixed JSON shape, not free text):

| Agent | Input | Output | Notable design detail |
|---|---|---|---|
| Planner | task description (natural language) | a structured plan (steps / target file / function signature / acceptance criteria) | |
| Developer | the plan + **real reference source code** | generated implementation | an earlier version didn't pass in real reference code, and the model hallucinated a module path that didn't exist; fixed by requiring import paths to exactly match the real reference source |
| Tester | the Developer's code + acceptance criteria + **real module path** | generated pytest code | hit the same path-hallucination issue independently, fixed the same way |
| Reviewer | code + tests + **real pytest execution output** | a structured review (approved / findings / reasoning) | advisory only — never the final word |

These four agents **have no file-reading ability** — all context is assembled by ordinary Python code ahead of time and passed into the prompt; the agents never read project files themselves. This is a deliberate constraint for **reproducibility**: identical input always sees identical context, which is what makes a controlled A/B comparison of prompt changes meaningful in the first place. The cost is flexibility — if a task needs a file that wasn't pre-loaded, the agent simply can't see it.

**Orchestration** (`app/agents/orchestrate.py`): `orchestrate(task_description)` runs all four agents in sequence, writes the draft to a scratch directory (never a real project file), and returns the full trace. `_run_pytest_on_draft()` genuinely executes the generated tests via `subprocess.run(encoding="utf-8")` — the `encoding` argument exists because of a real Windows decoding bug, see `ENGINEERING_LOG.md`, FC007.

**The human-approval gate** (`apply_approved_changes()`): the single most important function in the project. After a human clicks "approve," this function **re-runs the real test suite itself**, and `returncode` must be exactly 0 — regardless of what the Reviewer concluded, regardless of what the human clicked. If the tests didn't cleanly pass, it raises an error and the corresponding API returns HTTP 409. This check started as stricter prompt wording ("never suggest approval unless every test passes") and was still bypassed by a reasonable-sounding AI justification (`ENGINEERING_LOG.md`, FC008) — which is what led to the conclusion that **prompt-level constraints are a suggestion; code-level constraints are the actual guarantee.** The same pattern was independently reproduced later through a real front-end approval click (FC010).

**What this write-back step actually automates, and what it doesn't** — worth being precise about this rather than overselling it: `apply_approved_changes()` only does one thing — append the draft code to the end of the target file in append mode. The one real merge that happened this way (writing `resolve_manual_review()` into the state machine) still needed a human to deduplicate imports and relocate the generated test file into the real test suite. Concretely: it can only *append*, not modify an existing function; it doesn't deduplicate imports; it doesn't relocate test files; there's no branch/PR/CI step. A production version of this would look like branch → commit → PR → CI → human review → merge.

**Why write back to disk at all, given those limits**: if code can never actually land, the approval gate is theater — the gate only means something because the code genuinely can be merged; a checkpoint with nothing at stake isn't a checkpoint. And this design produced real value: the FC011 timezone bug only surfaced *because* the code was really merged and really wired into a real endpoint two days later. The point being demonstrated isn't "the write-back mechanism is production-ready" — it's "the approval gate holds even when code genuinely can land."

**Code Review Agent** (`app/agents/code_review_agent.py`): a separate tool, independent of the four-agent pipeline, simulating "have an AI do a first pass before a human reviews a diff" — paste code in, get back structured findings (severity / category / summary / explanation).

---

## On evaluation

The full project this is extracted from includes a fourth layer — a small evaluation harness that measures the AI development pipeline's real first-attempt success rate (not a hypothetical estimate) using the industry-standard `pass@1` definition: the fraction of runs where every generated test cleanly passes on the first attempt, all-or-nothing. Across two rounds of a small, deliberate prompt-quality iteration, that rate moved from roughly 40% to roughly 80% on the same five tasks — while the code-level approval gate held in every run, including the two documented above (FC008, FC010) where an AI reviewer's reasonable-but-wrong judgment tried to bypass it, and one case (FC011) where the gate's own boundary — "tests passed" isn't the same as "tests were correct" — let a real bug through until the code was actually wired into a live path. That evaluation harness and its raw data aren't included in this snapshot; the mechanism it measures is what `ENGINEERING_LOG.md` documents in detail.
