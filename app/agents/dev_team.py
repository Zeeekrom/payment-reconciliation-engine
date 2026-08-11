"""AI engineering workflow: Planner -> Developer -> Tester -> Reviewer — Layer 3 (AI-authored, reviewed by Evan).

Four stages, four **real, independent** GLM calls, run in sequence — not just for show:
1. Planner: task description -> structured plan (steps, files to change, acceptance criteria)
2. Developer: plan -> generated code
3. Tester: code -> generated test cases, which are **actually executed** (never just the model
   claiming "tests passed")
4. Reviewer: code + real test results -> structured review findings + approve/reject recommendation

**Human approval gate**: orchestrate() only returns the full record of the process (plan, draft
code, test results, review findings) — it never automatically writes the code into the project
files. Only after a human has reviewed and explicitly approved it does a separate function
actually commit the code to disk. This is the "human approval before accepting code changes"
explicitly required by the Layer 3 spec, not an optional nicety.

**What this team was asked to build**: a real, existing gap in the business logic — turning a
NEEDS_REVIEW state, once a human has reviewed it, into RECONCILED_SUCCESS/RECONCILED_FAILED
(see docs/DESIGN_DECISIONS.md, D007, and the standalone function that the
app/core/state_machine.py docstring had flagged as needed but never implemented). This wasn't
an arbitrarily chosen practice task.
"""

import json

from app.config import MODEL_STRONG
from app.copilot.llm_client import BigModelAPIError, chat_completion

PLANNER_SUBMIT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "submit_plan",
            "description": "Submit a structured development plan",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {"type": "array", "items": {"type": "string"}, "description": "Implementation steps, in order"},
                    "target_file": {"type": "string", "description": "Path of the file to add or modify"},
                    "function_signature": {"type": "string", "description": "Signature of the new function (name + parameters + return type)"},
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Acceptance criteria; each item should map directly to a test case",
                    },
                },
                "required": ["steps", "target_file", "function_signature", "acceptance_criteria"],
            },
        },
    }
]

DEVELOPER_SUBMIT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "submit_code",
            "description": "Submit the implementation code",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "The complete function/module code"},
                    "explanation": {"type": "string", "description": "A brief explanation of the implementation approach"},
                },
                "required": ["code", "explanation"],
            },
        },
    }
]

TESTER_SUBMIT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "submit_tests",
            "description": "Submit test code (pytest style)",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_code": {"type": "string", "description": "The complete pytest test code"},
                },
                "required": ["test_code"],
            },
        },
    }
]

REVIEWER_SUBMIT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "submit_review",
            "description": "Submit the final review verdict",
            "parameters": {
                "type": "object",
                "properties": {
                    "approved": {"type": "boolean", "description": "Whether to recommend accepting this change"},
                    "findings": {"type": "array", "items": {"type": "string"}, "description": "Issues found; an empty list if none"},
                    "reasoning": {"type": "string", "description": "The reasoning behind this verdict"},
                },
                "required": ["approved", "findings", "reasoning"],
            },
        },
    }
]


def _call_with_tool(system_prompt: str, user_prompt: str, tool_schema: list, tool_name: str) -> dict:
    """Shared call logic for all four agents: send the messages, force tool-calling, parse the arguments."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        message = chat_completion(messages, model=MODEL_STRONG, tools=tool_schema)
    except BigModelAPIError as exc:
        return {"error": str(exc)}

    tool_calls = message.get("tool_calls")
    if not tool_calls:
        return {"error": "Model did not call the tool as required", "raw_text": message.get("content", "")}

    return json.loads(tool_calls[0]["function"]["arguments"])


def planner_agent(task_description: str) -> dict:
    system_prompt = (
        "You are a backend engineering planner responsible for breaking a development task down "
        "into clear implementation steps. Project context: a Python + FastAPI + SQLite payment "
        "system, where Layer 1 is deterministic core logic and the LLM must never directly change "
        "the final payment state. You must submit your result via the submit_plan tool."
    )
    return _call_with_tool(system_prompt, task_description, PLANNER_SUBMIT_TOOL, "submit_plan")


def developer_agent(plan: dict, reference_code: str) -> dict:
    """reference_code: the actual function/class definitions that exist in the project and that this
    implementation will need (not a paraphrase — the real source).

    This parameter was added after a real early run where the Developer only received the
    Planner's natural-language summary of the plan, and hallucinated a nonexistent module path
    and an incorrect function signature based on "what a typical project usually looks like."
    Now the real source is fed to it directly, removing any room for guessing.
    """
    system_prompt = (
        "You are a backend engineer implementing code from a given plan. Write only the target "
        "function itself, matching the project's existing code style: type annotations, and a "
        "docstring that clearly states its responsibilities. Do not introduce new dependencies "
        "that aren't already in the project. Strict requirement: the actual function/class "
        "definitions that exist in the project will be provided below — your import paths and "
        "call conventions must match that source exactly. Do not assume a path or signature that "
        "'looks reasonable' but does not actually appear in the provided source. You must submit "
        "your result via the submit_code tool."
    )
    user_prompt = (
        f"Relevant code that actually exists in the project (import paths and call conventions "
        f"must match this exactly):\n"
        f"```python\n{reference_code}\n```\n\n"
        f"Implement the code according to this plan:\n{json.dumps(plan, ensure_ascii=False, indent=2)}"
    )
    return _call_with_tool(system_prompt, user_prompt, DEVELOPER_SUBMIT_TOOL, "submit_code")


def tester_agent(code: str, acceptance_criteria: list, reference_code: str, module_import_path: str) -> dict:
    """module_import_path: the real module path where the code under test will actually live.

    A new issue found on the second run: the Developer's code itself was correct, but the Tester
    didn't know which file/module the code would actually be saved in, and guessed a path that
    "sounded reasonable" but didn't exist (app.core.manual_review). Now the real path is passed
    in explicitly, removing the need to guess.
    """
    system_prompt = (
        "You are a test engineer writing pytest test cases for a piece of code, based on the "
        "given acceptance criteria. Cover the normal path plus at least one boundary/exception "
        "path. Any project function/class used in the tests must match the provided reference "
        "source exactly in import path and call convention. The real module path of the function "
        "under test will be given to you explicitly — do not guess or assume any other path."
        # v2 (2026-08-08): the following two rules were added based on real failures encountered,
        # not generic advice — the first corresponds to FC010 (the Tester manually issuing
        # CREATE TABLE inside a test body, conflicting with a table setup_method had already
        # created); the second corresponds to a missing import found in the same batch of tests
        # (using json.dumps without importing json, causing a NameError).
        "Before writing each test method, first check what setup_method/fixtures have already "
        "initialized (e.g., tables already created, data already prepared) — do not recreate in "
        "the test body something setup has already done. Every standard-library or third-party "
        "module used in the test code (e.g. json, datetime, sqlite3) must be imported at the top "
        "of the file — never assume a module is implicitly available."
        "You must submit your result via the submit_tests tool."
    )
    user_prompt = (
        f"Relevant code that actually exists in the project:\n```python\n{reference_code}\n```\n\n"
        f"The code under test will actually be saved as this module — tests must import from "
        f"here (do not guess a different path):\n"
        f"`from {module_import_path} import <function_name>`\n\n"
        f"Acceptance criteria:\n{json.dumps(acceptance_criteria, ensure_ascii=False, indent=2)}\n\n"
        f"Code to test:\n```python\n{code}\n```"
    )
    return _call_with_tool(system_prompt, user_prompt, TESTER_SUBMIT_TOOL, "submit_tests")


def reviewer_agent(code: str, test_code: str, test_result: dict) -> dict:
    system_prompt = (
        "You are a senior code reviewer giving a final verdict based on the code itself and the "
        "real test execution results. If the tests did not all pass, you must not recommend "
        "approved=true. You must submit your result via the submit_review tool."
    )
    user_prompt = (
        f"Code:\n```python\n{code}\n```\n\n"
        f"Test code:\n```python\n{test_code}\n```\n\n"
        f"Real test execution result: {json.dumps(test_result, ensure_ascii=False)}"
    )
    return _call_with_tool(system_prompt, user_prompt, REVIEWER_SUBMIT_TOOL, "submit_review")
