"""Sequential orchestration + real test execution + human approval gate — Layer 3 (AI-authored, reviewed by Evan).

orchestrate() runs through the four stages Planner -> Developer -> Tester -> Reviewer, and
**does not automatically write the generated code into the project's real files** — the
generated code only ever lands in the app/agents/_draft/ scratch directory (already added
to .gitignore, never committed), and pytest is actually run against the generated tests, with
the real pass/fail result handed to the Reviewer for judgment. The Reviewer is never allowed
to conclude "should be fine" just because the Developer said so.

Only calling apply_approved_changes() — which represents explicit human review and approval —
copies the code from _draft/ into the real project files. This is the "human approval gate",
and it is not just for show.
"""

import subprocess
import sys

from app.agents.dev_team import developer_agent, planner_agent, reviewer_agent, tester_agent

DRAFT_DIR = "app/agents/_draft"
DRAFT_MODULE_PATH = f"{DRAFT_DIR}/draft_module.py"
DRAFT_TEST_PATH = f"{DRAFT_DIR}/test_draft_module.py"


def _run_pytest_on_draft() -> dict:
    """Actually runs pytest — never lets the LLM simply claim whether the tests passed.

    encoding="utf-8" must be passed explicitly: on Windows, subprocess decodes the child
    process's output using the system code page (cp1252) by default, and the generated test
    code / error messages often contain Chinese characters, which triggers a UnicodeDecodeError
    (yet another Windows Chinese-encoding pitfall, in the same family as FC002/FC003 — see
    docs/ENGINEERING_LOG.md, FC007). This error happens on a background reader thread, so it
    doesn't crash the main flow outright — instead it silently corrupts the `passed` verdict
    returned here, which makes it very easy to miss.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", DRAFT_TEST_PATH, "-v"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    return {
        "passed": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _load_reference_code() -> str:
    """Reads the actual code that exists in the project and that the Developer/Tester will need
    to reference — not a paraphrase, the real source — so the agent doesn't hallucinate a
    nonexistent module path based on "typical" patterns (a real early failure this fixed).
    """
    parts = []
    for path in ["app/core/events.py", "app/core/db.py"]:
        with open(path, encoding="utf-8") as f:
            parts.append(f"# --- {path} ---\n{f.read()}")
    return "\n\n".join(parts)


def orchestrate(task_description: str) -> dict:
    """Runs all four stages and returns the full trace of the process; does not write to the real project files."""
    trace = {"task": task_description}
    reference_code = _load_reference_code()

    plan = planner_agent(task_description)
    trace["plan"] = plan
    if "error" in plan:
        trace["stage_failed"] = "planner"
        return trace

    dev_result = developer_agent(plan, reference_code)
    trace["developer"] = dev_result
    if "error" in dev_result:
        trace["stage_failed"] = "developer"
        return trace

    code = dev_result["code"]
    with open(DRAFT_MODULE_PATH, "w", encoding="utf-8") as f:
        f.write(code)

    module_import_path = "app.agents._draft.draft_module"
    test_result = tester_agent(code, plan.get("acceptance_criteria", []), reference_code, module_import_path)
    trace["tester"] = test_result
    if "error" in test_result:
        trace["stage_failed"] = "tester"
        return trace

    test_code = test_result["test_code"]
    with open(DRAFT_TEST_PATH, "w", encoding="utf-8") as f:
        f.write(test_code)

    execution_result = _run_pytest_on_draft()
    trace["test_execution"] = execution_result

    review = reviewer_agent(code, test_code, execution_result)
    trace["reviewer"] = review

    return trace


class UnsafeToApplyError(Exception):
    """Raised when the draft's tests did not cleanly pass in full — the write is refused, even if the Reviewer approved it."""


def apply_approved_changes(target_file: str) -> None:
    """Called only after explicit human approval — writes the draft code into the real project file.

    This adds a **hard, code-level check** on top of that: rather than simply trusting the
    caller's claim that "a human has approved this," it re-runs pytest right before actually
    writing the file, and only proceeds if the returncode is strictly equal to 0.

    Why the Reviewer's `approved` field alone cannot be trusted: a real situation, documented in
    detail, showed pytest reporting "7 passed, 6 errors" (all business logic passed; the errors
    were only a PermissionError during temporary database file cleanup under Windows). The
    Reviewer judged this to be a "test environment issue that doesn't affect code quality" and
    returned approved=true. That reasoning is actually defensible on its own — but if "the AI
    decided this failure doesn't matter" were allowed to bypass the hard rule every time, the
    rule would become meaningless.

    This is the same principle as Layer 1's rule that "the LLM must never directly change the
    final payment state": the decisive judgment of whether something is safe to apply must be
    delegated to deterministic code — never to however plausible the AI's explanation happens to
    sound at the time.
    """
    execution = _run_pytest_on_draft()
    if execution["returncode"] != 0:
        raise UnsafeToApplyError(
            "The draft's tests did not cleanly pass in full (returncode != 0); refusing to write "
            "to the real file. If you're confident the failure is environmental (e.g. Windows file "
            "cleanup), fix the test code itself first — do not bypass this check."
        )

    with open(DRAFT_MODULE_PATH, encoding="utf-8") as f:
        code = f.read()
    with open(target_file, "a", encoding="utf-8") as f:
        f.write("\n\n" + code)
