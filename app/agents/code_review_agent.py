"""Code Review Agent — Layer 3 (AI-authored, reviewed by Evan).

Calls GLM to produce structured review findings for a piece of code. Uses the same
"structured output" technique as the Layer 2 Copilot: instead of letting the model freely
write review prose and then hoping to parse structure back out of it (prone to format
errors), it's given a "tool" (submit_findings) that forces the result into fixed fields —
so what comes back is always structured data, with no fragile text parsing required.

**How this was validated**: rather than testing on an arbitrary snippet, it was fed two
historical snapshots of real bugs from app/agents/fixtures/ (the earliest Phase A version,
later fixed through human review), to see whether it could independently rediscover the same
issues a human had originally found. This verifies whether the agent is actually useful rather
than just talking to itself (see docs/DESIGN_DECISIONS.md, D007, and the rule established
afterward: tasks must be tied to real business logic / real scenarios).
"""

import json

from app.config import MODEL_STRONG
from app.copilot.llm_client import BigModelAPIError, chat_completion

SUBMIT_FINDINGS_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "submit_findings",
            "description": "Submit the list of issues found during code review. Pass an empty list if no issues were found — do not fabricate issues just to appear to have found something.",
            "parameters": {
                "type": "object",
                "properties": {
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "summary": {"type": "string", "description": "One-sentence description of the issue"},
                                "severity": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                    "description": "high = will cause incorrect results or data problems; medium = poor design but not necessarily a bug; low = style/readability suggestion",
                                },
                                "category": {
                                    "type": "string",
                                    "description": "Issue category, e.g.: business logic error, maintainability issue, security risk, etc.",
                                },
                                "explanation": {"type": "string", "description": "Why this is an issue and what consequences it could have"},
                            },
                            "required": ["summary", "severity", "category", "explanation"],
                        },
                    },
                },
                "required": ["findings"],
            },
        },
    }
]

SYSTEM_PROMPT = """You are a senior backend code reviewer examining Python code for a payment system.
Core principles of this system:
1. RawChannelEvent is an audit log — it must be append-only and store the raw data from the
   channel exactly as received.
2. PaymentState is the current state derived from RawChannelEvent, and should not duplicate
   storage of the full raw event object.
3. Validation logic should not be stricter than actually necessary — only validate fields that
   are genuinely used, to avoid wrongly rejecting legitimate data.

Read the code carefully and identify issues that genuinely exist (do not fabricate issues just
to appear to have found something). You must submit your result via the submit_findings tool —
do not answer with free text only."""


def review_code(code: str, filename: str = "") -> dict:
    """Runs a structured review on a piece of code, returning {findings: [...], raw_tool_called: bool}."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Review this code (filename: {filename or 'not provided'}):\n\n```python\n{code}\n```"},
    ]

    try:
        message = chat_completion(messages, model=MODEL_STRONG, tools=SUBMIT_FINDINGS_TOOL)
    except BigModelAPIError as exc:
        return {"findings": [], "error": str(exc), "raw_tool_called": False}

    tool_calls = message.get("tool_calls")
    if not tool_calls:
        # The model did not call the tool as required; fall back to returning the raw text
        # content. This situation is itself worth recording (the prompt failed to 100% force
        # the model down the structured path) — don't silently ignore it.
        return {
            "findings": [],
            "raw_text_fallback": message.get("content", ""),
            "raw_tool_called": False,
        }

    arguments = json.loads(tool_calls[0]["function"]["arguments"])
    return {"findings": arguments.get("findings", []), "raw_tool_called": True}
