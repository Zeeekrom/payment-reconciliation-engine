# Engineering Log — Known Limitations and Real Failures

This document records **known limitations** in the design and implementation — not a "TODO for later," but an honest record of "we know there's a gap here, and here's why we chose not to fill it right now." Every entry below happened during real development; none are hypothetical or written after the fact for effect.

Each entry follows the same shape: symptom → root cause → why it's acceptable for now (or how it was fixed) → what a full fix would require.

---

## FC001 — Content-hash deduplication on Channel A can't catch "the same real charge happening twice"

**Symptom**: `app/core/channels/channel_a.py` (and channel C's fallback path when no response ID is present, see `channel_c.py`) generate `event_id` by hashing "channel ID + raw payload" with SHA-256. If two notifications are byte-for-byte identical (same order ID, same status string), they produce the same `event_id`, and the second one gets dropped as a duplicate.

**Root cause / blast radius**: this mechanism can only detect "the same event delivered twice" (network retries, at-least-once message delivery). It **cannot detect "the same operation genuinely executed twice."** Example: a user double-taps "pay," and each tap triggers an independent real charge. If both channel notifications look identical (same order ID, same "success" text), the dedup logic treats the second as a duplicate notification and drops it — but if they actually correspond to two real charges, dropping the second one also throws away the signal that the user got charged twice.

**Why this is acceptable for now**: truly preventing "double-charging" means generating a unique idempotency key **before** the charge request is issued, the way Stripe does it ([Stripe Idempotent Requests](https://stripe.com/docs/idempotency)) — that's the responsibility of "initiating the payment," not "processing the channel's result." This project's scope is the latter, so the gap is acceptable within scope, but it has to be written down, not pretended away.

**What a real fix requires**: generating and passing a client-side idempotency key at charge-initiation time, and channel-side support for deduplicating on that key (not every channel supports this) — a bigger change than this project's scope.

**Category**: business-logic / architectural limitation (not a bug, not an AI reasoning error — Layer 1 involves no AI at all).

---

## FC002 — All automated tests pass, but a manual curl demo returns 500 (Windows/Git Bash encoding issue)

**Symptom**: after all 54 `pytest` tests (including end-to-end integration tests) passed, starting a real `uvicorn` server and submitting a Channel B event via manual curl returned 500, with the log showing `adapt_channel_b` complaining about a missing merchant order ID field — even though the request clearly included it.

**Root cause**: not a code bug. Using single-quoted inline JSON in Windows Git Bash, where the JSON contains a Chinese field name, corrupts the encoding at the shell layer — the server actually receives garbled field names and naturally can't find the expected key. Switching to a UTF-8 file passed via `curl --data-binary @file.json` fixed it immediately, with the exact same backend code.

**Why this is worth recording on its own**: a clean example of "automated tests passing ≠ actually usable." `pytest`'s `httpx`/`TestClient` takes the correct encoding path and can't surface this class of failure, which only happens because of how a human operates a shell tool. This is exactly why doing one real manual end-to-end pass (not just running the automated suite) mattered.

**Fix**: not a code change — documented the correct curl usage (file-based payload, not inline single quotes) for anyone doing manual demos.

**Category**: tooling/environment issue, not business logic and not an AI reasoning error — but a good answer to "why can't you just trust automated tests / trust the AI saying 'tests pass'?"

---

## FC003 — Printing Chinese text in a Windows terminal throws `UnicodeEncodeError` (same class as FC002, different location)

**Symptom**: while manually validating the Copilot layer, a Python script's embedding API call succeeded, but `print()`-ing Chinese text raised `UnicodeEncodeError: 'charmap' codec can't encode characters`, which looked like the call itself had failed.

**Root cause**: again, not a code bug. Windows terminals default to the `cp1252` code page and can't print Chinese characters directly. Same class of issue as FC002 (Windows + Chinese-text encoding), just a different spot — FC002 was encoding corruption before the request left the client; this one is encoding failure when printing a result to the terminal. Setting `PYTHONIOENCODING=utf-8` fixed it.

**Why record it separately**: reinforces the FC002 lesson — this class of problem resurfaces in different forms on Windows (request body, terminal output, ...) and isn't a one-time fix. When something "looks like a failure," check the environment before assuming the business logic is wrong.

**Fix**: prefix manual runs with `PYTHONIOENCODING=utf-8`; doesn't change how the API itself is called, only how Chinese output is displayed locally.

**Category**: tooling/environment issue.

---

## FC004 — The Copilot has no automated check on answer/tool-call quality

**Symptom**: a controlled comparison showed the cheap-tier model "cutting corners" on a question that required combining multiple tool calls — it called only one tool and gave a shallow answer, while the strong tier correctly called all three tools and gave a complete, rule-grounded answer. But the system as built **returns whatever the model produces, with nothing checking whether the answer is any good.**

**Root cause / blast radius**: this is a real architectural gap, not a line-level bug. If a caller explicitly requests the cheap tier (to save cost/latency), they could get an incomplete or misleading answer, and the system itself has no way to notice.

**Mitigation already in place**: switching the default tier from cheap to strong (see `DESIGN_DECISIONS.md`, D-002) lowers the odds of hitting this by default, but doesn't fix it — the risk is still there if `tier="cheap"` is passed explicitly.

**Why this is acceptable for now**: the real fix (an LLM-as-judge second pass, rule-based fallback checks, or human review) belongs to the evaluation layer, which was deliberately scoped separately to avoid scope creep mid-build.

**What a real fix requires**: at minimum a rule-based check (e.g. "the question mentions something that looks like an order ID, but the tool trace shows no lookup was made"), ideally combined with an LLM-as-judge second pass.

**Category**: architectural/systemic limitation, directly tied to "where might the AI give a misleading answer." This isn't a made-up example — it came from a real, deliberately-run comparison.

---

## FC005 — The AI made the same syntax mistake twice in a row while writing code

**Symptom**: while writing `app/copilot/tools.py` and `app/agents/code_review_agent.py`, the AI wrapped Chinese emphasis text in straight double quotes inside a JSON-schema `description` string that was itself already inside double quotes — in both files, independently, causing a Python `SyntaxError` that only surfaced via `ast.parse()`, not visible at a glance.

**Root cause**: a recurring generation habit, not a one-off slip — the model used straight quotes instead of a nesting-safe alternative when generating "quoted emphasis inside a string," and after the first file was fixed, it made the identical mistake writing the *next* file from scratch. "Fixed once" clearly did not mean "learned, won't happen again."

**Fix**: both instances fixed by using non-conflicting quote characters; the deeper fix is running `ast.parse()` on any newly generated `.py` file before assuming it's syntactically sound, rather than assuming "this one should be fine."

**Category**: AI reasoning/generation error (not an environment issue, not a design tradeoff) — and worth stating plainly: this was a **repeat** mistake. The model doesn't automatically remember "don't do that again" just because it was corrected once; the human verification step can't be skipped.

---

## FC006 — An overly tight LLM API timeout misread "still working" as "failed"

**Symptom**: during real, repeated runs of the AI development team, the Developer/Tester stages kept failing outright, and the first instinct was to suspect the model's reasoning was unreliable.

**Root cause**: the client's timeout was originally 30 seconds. The Developer/Tester prompts include a full block of reference source code (roughly 5,000 characters) and need to generate a fair amount of code/tests in response — the API frequently couldn't respond inside 30 seconds, and our own timeout logic marked that as a failure. **This wasn't the AI failing — it was our own infrastructure being configured too aggressively.**

**Fix**: raised the timeout to 90 seconds; `stage_failed` stopped appearing afterward.

**Category**: tooling/configuration issue (same class as FC002/FC003 — something that looks like an AI or business-logic failure but is actually a problem in the infrastructure wrapped around the AI).

---

## FC007 — A subprocess decoding bug silently corrupted test results, briefly making it look like the Reviewer was ignoring instructions

**Symptom**: `app/agents/orchestrate.py` uses `subprocess.run()` to actually execute AI-generated tests. During repeated real runs, there was a case where tests hadn't all passed but the Reviewer still approved — directly contradicting the explicit system-prompt rule "never approve unless all tests pass." The first instinct was to suspect the Reviewer was disregarding its instructions, which would have been a much more serious reliability problem.

**Root cause**: on Windows, `subprocess.run(..., text=True)` decodes subprocess output using the system code page (cp1252) by default. Chinese text in pytest's output (the generated test code and error messages were in Chinese at the time) caused a `UnicodeDecodeError` in a background reader thread — an exception that doesn't crash the main flow but **silently corrupts** the captured test results. The Reviewer was working from corrupted, incomplete data; it wasn't disregarding anything.

**Fix**: added `encoding="utf-8"` explicitly to `subprocess.run()`. This fix is correct — the problem was purely "decoding bytes with the wrong charset," and specifying the right encoding eliminates that specific bug.

**But the "tested 5 times, so it's 100% fixed" conclusion came too early**: after the encoding fix, further testing turned up *another* case of "tests didn't all pass, but the Reviewer approved anyway" — investigation traced it to a completely different, genuinely different root cause (a Windows file-cleanup timing issue, see FC008), not a recurrence of the encoding bug. Five passing runs is too small a sample to declare victory — a lesson in itself: consistency across a small sample isn't proof.

**Why this one is worth flagging**: the most instructive "doubt the measurement tool before doubting the AI's judgment" case in this project — concluding "the Reviewer is unreliable" without finding the real root cause would have been a wrong, unsubstantiated conclusion that wouldn't survive being questioned in detail.

**Category**: tooling/environment issue, but the investigation process itself is a direct demonstration of result-judgment discipline.

---

## FC008 — The Reviewer's reasonable judgment was allowed to bypass a hard rule; the fix was a code-level check, not a stronger prompt

**Symptom**: after the FC007 fix, further testing turned up another "tests didn't all pass, but the Reviewer approved anyway" case — this time not an environment bug. The real pytest output was "7 passed, 6 errors": all 7 business-logic assertions genuinely passed, but 6 tests hit a Windows-specific `PermissionError` during fixture cleanup (a temp SQLite file couldn't be deleted because the OS hadn't fully released the file handle yet). The orchestration code's own `passed = returncode == 0` check bluntly classified this as "failed" — but the Reviewer, looking at the full output, correctly identified that this was a cleanup-stage environment issue, not a code defect, and gave a reasonable, well-justified `approved: true`.

**Why this is more concerning than FC006/FC007**: this time the AI wasn't lying, and there was no environment bug shielding it — its reasoning was *correct*. But "this particular explanation happens to be reasonable" can't be allowed to override a hard rule ("never approve unless all tests pass"), or the rule is meaningless. This is the same underlying principle as "the LLM must not directly change final payment state," showing up again in a different layer.

**Fix**: not stronger prompt wording (the prompt already explicitly said "never suggest approved=true unless all tests pass," and the model still found a reasonable-sounding exception around it). Instead, added a **hard code-level check** inside `apply_approved_changes()`: before anything is actually written to disk, pytest is re-run for real, and `returncode` must be exactly 0 — no exceptions, regardless of what the Reviewer concluded. The corresponding API now returns 409 (Conflict) in this case.

**Category**: AI-reliability issue (a subtler failure mode than the AI lying — the AI produced a reasonable judgment that still shouldn't be the final word). This is the single highest-value case in the whole log.

---

## FC009 — The evaluation script's own database path was wrong, and it silently failed two questions the system had actually answered correctly

**Symptom**: on the first run of the evaluation script, two questions ("check an order's status" and "check a nonexistent order") appeared to fail — the Copilot answered "order not found," but the expected answer was a real status lookup.

**Root cause**: the evaluation script seeded test data into one database file, while the Copilot's tools were hardcoded to read from a *different* database file. The Copilot's "order not found" answer was completely correct given the database it actually queried — the bug was in the evaluation script seeding data into the wrong place. A second, independent bug: one expected-keyword check required two specific words to both appear, but the Copilot used a fully correct synonym instead, and got marked wrong by a too-literal string match.

**Fix**: pointed the evaluation script's `DB_PATH` at the same file the tools actually use; relaxed the keyword match to the words the Copilot actually produces rather than requiring an exact literal phrase. After the fix, all cases passed for real.

**Why this is worth recording too**: the third instance in this project of "doubt your own tooling before doubting the AI" — and this time it happened inside the tool whose entire job is to evaluate the AI. Treating those two questions as "the Copilot got it wrong" without finding the root cause would have produced an incorrect evaluation conclusion — the correctness of the measurement tool matters as much as the correctness of what's being measured.

**Category**: tooling/evaluation-script bug, not an AI reasoning error — but it directly affects how much you can trust the evaluation numbers.

---

## FC010 — A real UI walkthrough surfaced a self-contradicting generated test, the Reviewer's "reasonable but untrustworthy" pattern recurring, and the hard gate holding even after a human clicked approve

**Symptom**: not a staged test case. While doing a real walkthrough of the human-approval UI, an off-the-cuff task was given to the AI development team ("write a function that counts raw events received for a given payment ID, grouped by channel"), and the real four-agent pipeline produced a genuine result: `1 failed, 12 passed, 1 error`. After reviewing every stage's output (plan, code, tests, real pytest output, Reviewer's opinion), a human deliberately clicked "approve and write to project files" specifically to see how the hard gate would react — the backend returned HTTP 409 and refused the write, with the message explaining that the draft's tests hadn't cleanly passed and the check couldn't be bypassed.

**Root cause, and it's two genuinely different problems that shouldn't be lumped together**:

1. **A self-contradicting generated test — a real AI reasoning/generation error.** The Tester agent wrote a test meant to simulate "the database schema is wrong" by manually executing `CREATE TABLE raw_channel_events (...)` inside the test body — but the same test class's `setup_method()` (also written by the same agent, in the same generation pass) had already created that table via the normal init path. Both pieces of code came from the same generation, the same file, and directly contradicted each other, producing `sqlite3.OperationalError: table already exists`. The underlying cause: when generating a longer single file, the model didn't cross-check "state already established earlier in this file" against "an assumption made by a later test" — the same broad category as FC005 (a self-consistency gap in generation), just a different specific shape: FC005 repeated the same mistake across files, this one contradicts itself within one file.
2. **A Windows `PermissionError` — not an AI error, an environment issue.** In the same run, `teardown_method()` failed to delete a temp SQLite file because another handle to it hadn't been released yet — the same class of Windows environment issue as FC007/FC008, not a new phenomenon.

**The Reviewer's behavior is a second real occurrence of the FC008 pattern**: after seeing the real pytest output, the Reviewer approved anyway, reasoning that "the one failing test is a test-design problem, not a code problem, and 12/13 passing shows the implementation is correct." That reasoning holds up — the failure genuinely was in the Tester's own test logic, not the Developer's implementation. But exactly as in FC008: **"this explanation happens to be reasonable" still isn't grounds to bypass "never approve unless all tests pass."** A rule that only holds when it's convenient isn't a rule.

**Why this instance is more convincing than FC008**: FC008 was found through repeated backend script runs. This one was triggered through the real front-end UI by a real human click — the human reviewer approved it too, and the backend independently re-verified the actual `returncode` and returned 409 regardless. It confirms that "human approval is necessary but not sufficient" holds at the UI layer too, not just from the command line.

**Fix**: no code change needed — the draft files were correctly never written to the real project, which is exactly the intended outcome. If this feature were to actually be merged, a human would need to fix the Tester's contradictory test first, not bypass the gate.

**Category**: AI reasoning error (a self-consistency gap within one generated file) + AI-reliability issue (Reviewer producing a reasonable-but-untrustworthy judgment, second occurrence of the FC008 pattern) + tooling/environment issue (Windows `PermissionError`) — three different kinds of problems stacked in a single real run, and a good illustration that a single failure often isn't a single cause; each thread needs to be pulled apart rather than lumped into one bucket.

---

## FC011 — AI-generated code passed every test and human review, got merged, and still shipped a timezone bug that neither caught

**Symptom**: while wiring up an API endpoint for an existing but never-called AI-generated function, the first real end-to-end call surfaced a suspicious timestamp mismatch:

```
after a channel event was written (Layer 1 pipeline):        last_updated = 2026-08-10T12:36:42Z    ← UTC
after a human-review decision (the AI-generated function):   last_updated = 2026-08-10T22:36:42     ← local time, no timezone
```

Two different timezone conventions were mixed in the same table, 10 hours apart.

**Root cause**: the AI-generated line used `datetime.now()`, missing `timezone.utc`. Every other place in the project that writes a timestamp (three channel adapters plus the pipeline) uses `datetime.now(timezone.utc)` — this was the one line that didn't.

**Why none of the three safety layers caught it — this is the real value of this case**:

1. **All 6 AI-generated tests passed** — but the same model wrote both the implementation and its tests. The implementation used local time, so the test asserted against local time too (`result.last_updated > datetime(2023, 1, 1, 10, 0, 0)`, also naive). The tests verified the AI's own assumption, not the project's actual convention. **When the same model writes both the implementation and the tests, the tests tend to validate the bug rather than expose it.**
2. **The hard code-level gate let it through** — that gate only checks `returncode == 0` (did the generated tests cleanly pass). It guarantees "the AI didn't ship code that fails its own tests," not "the tests themselves are correct." That's a real, designed-in boundary of what the gate can catch, not a failure of the gate.
3. **Human review missed it too** — in a 40-line function, one missing argument is easy to miss when review attention is on business logic (is the state transition correct, is error handling complete), and `datetime.now()` reads as completely unremarkable at a glance.

**Why it took this long to surface**: this function had **no caller** after being merged — it had an implementation and tests, but no endpoint exposed it. Nobody had ever called it for real, so nobody had ever compared its output against the rest of the system. **Dead code hides bugs**: green tests don't mean much until the code is actually wired into a real path.

**Fix**:
- Corrected to `datetime.now(timezone.utc)`, with the original line kept as a comment explaining what was wrong and why (consistent with this project's habit of leaving a trace at every fixed mistake, not silently erasing it)
- Updated the tests to use timezone-aware datetimes, and added an assertion that didn't exist before: `assert result.last_updated.tzinfo is not None` — none of the original 6 tests checked timezone at all
- Wired the function into a real API endpoint so it's actually exercised going forward

**Category**: AI generation error + evaluation blind spot. **This is the only issue in the whole project that got past all three layers of defense** (automated tests → code-level hard check → human review) — every other case above was caught by at least one of them.

**Transferable takeaways**:
- **Letting the AI write both the implementation and its own tests is letting it grade its own homework.** Either have tests written by a human (or a separate, independent context), or at minimum manually check what the tests actually assert.
- **"All tests passed" deserves a follow-up question: who wrote these tests, and what do they actually assert?** None of the 6 tests here touched timezone handling at all.
- **Code merged into main with no real caller hasn't actually been validated.** Either wire it into a real path, or explicitly mark it as unverified.
