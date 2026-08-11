# Design Decisions Log

A running log of the project's key decisions, in the order they were made, each with the reasoning behind it. Entries are append-only — if a later decision reverses an earlier one, a new entry is added explaining why, and the old one is left in place rather than rewritten.

This is a curated subset focused on decisions that generalize beyond this specific project — mostly what got left out, and why.

---

## D-001 — Model stack: one provider, two tiers, no local model

**Decision**: the Copilot layer and the AI development-team layer both use a single hosted LLM provider (an OpenAI-compatible chat + embeddings API), with a cheap/fast tier for routine calls and a stronger tier for cases that need it. No local model (e.g. Ollama) was integrated.

**Reasoning**: under a tight timeline, a real hosted API (key-based auth, usage-based billing, rate limits) was worth more than adding a second integration path. Two tiers from the same provider were already enough to demonstrate the cheap/strong tradeoff that matters for the rest of the project (see D-002 below) — a three-way comparison including a local model would have made that comparison marginally richer, but at the cost of an extra client integration and abstraction layer that wasn't necessary to prove the point. Flagged as a reasonable stretch goal if time allowed later, not treated as a must-have from day one.

**Impact**: the LLM client only has to support one OpenAI-compatible interface, which every downstream module (Copilot tools, the four-agent development pipeline) depends on.

---

## D-002 — Switch the Copilot's default tier from cheap to strong

**Background**: a real, deliberately-run comparison (not hypothetical) showed the cheap-tier model "cutting corners" on a question that required combining multiple tool calls — it called only one tool and produced a shallow answer. The strong tier correctly called all three available tools and gave a complete, rule-grounded answer. See `ENGINEERING_LOG.md`, FC004, for the architectural gap this exposed (there's still no automated check on answer quality regardless of tier).

**Decision**: the Copilot's default tier switched from cheap to strong.

**Reasoning**: this is a cheap, immediately effective mitigation — not a complete fix. It lowers the odds of hitting the problem *by default*, but the risk is still present if a caller explicitly requests the cheap tier. The real fix (an automated quality check, independent of which tier answered) is a separate, larger piece of work, deliberately scoped out of this change so it wouldn't derail whatever was being built at the time.

**Why this is worth keeping in the log**: it's an honest example of "notice a risk → apply the smallest fix that helps → write down explicitly that the full fix is deferred, and to where" — not a claim that the problem is solved.

---

## D-003 — Before handing an AI agent team a sub-task, check that it actually connects to the real problem

**Background**: at one point, the plan was to have a four-agent pipeline (planner → developer → tester → reviewer) build a generic evaluation script from scratch. On reflection, that script is a testing tool, not part of the actual payment-reconciliation problem the rest of the project addresses — assigning it to the agent team would have been "standard engineering work" without being *relevant* work. The task was changed to something that actually closes a real gap in the payment system itself: handling a manual-review decision and writing back the resulting state change.

**Why the earlier layers of the project didn't have this problem**: every other module either *is* the core problem (the reconciliation logic itself) or directly serves the same system (the Copilot's tools and knowledge base) — there was never a point where a separate task had to be chosen on its own. This decision point only exists once you start handing an agent team an open-ended assignment; that's a new degree of freedom, and it needs its own check.

**Decision**: whenever an AI/agent is assigned a discrete sub-task that isn't the core problem itself, first verify the task actually connects to the real system or business flow — "this is standard engineering practice" is not, on its own, sufficient justification.

**Category**: a process lesson, not a specific technical decision — but one of the more transferable ones in this log.
