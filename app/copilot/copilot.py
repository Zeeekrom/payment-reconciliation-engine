"""Payment Operations Copilot main flow — Phase B (AI-authored, Evan review).

The full loop for handling a question (the "tool call loop" / agent loop):
1. Send the question, along with the tool definitions (TOOL_SCHEMAS), to GLM.
2. The model either answers directly in text, or includes tool_calls in its
   response, saying "I want to call this tool first."
3. If it's the latter: actually execute the corresponding Python function
   locally, add the result as a new message (role="tool") to the
   conversation history, and ask the model again — now that the model has
   the tool's real result in hand, it may give a final answer or decide to
   call another tool.
4. Repeat steps 2-3 until the model gives a final text answer, or the
   maximum number of rounds is reached (to prevent an infinite loop).

The prompt content lives in prompts/copilot_system_v1.md (versioned rather
than hardcoded directly in this file, so that future prompt iterations keep
their history and can be compared — see the relevant entry in
docs/DESIGN_DECISIONS.md).
"""

import json
import time

from app.config import MODEL_CHEAP, MODEL_STRONG
from app.copilot.llm_client import BigModelAPIError, chat_completion
from app.copilot.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS

MAX_TOOL_ROUNDS = 5  # Prevents the model from getting stuck in a "keeps calling tools, never gives a final answer" loop — beyond this, force escalation to a human

with open("prompts/copilot_system_v1.md", encoding="utf-8") as f:
    _prompt_doc = f.read()
# Besides the actual prompt text, the prompt document also has explanatory
# text like version number, creation date, and reasons for changes; the
# actual prompt body is wrapped in a ``` code block, and only that block's
# content is taken here — this explanatory text is never sent to the model
# as part of the system prompt.
SYSTEM_PROMPT = _prompt_doc.split("```")[1].strip()


def ask(question: str, tier: str = "strong") -> dict:
    """Ask the Copilot a question and return a structured result: the
    answer, which tools were used (tool_trace), latency, model tier, etc.

    tier="cheap" uses MODEL_CHEAP, tier="strong" uses MODEL_STRONG — see
    app/config.py and docs/DESIGN_DECISIONS.md, D-001 for exactly which
    model each maps to.

    The default tier is "strong," not the cheaper "cheap" — this was
    changed based on real test results (see docs/DESIGN_DECISIONS.md, D-002):
    on questions that require combining multiple tools to answer correctly, the cheap tier
    often calls just 1 tool and gives a shallow, hand-wavy answer, while
    the strong tier correctly uses all 3 tools and cites the rule text
    directly. For an ops tool meant to provide "answers people can trust,"
    the latency/cost saved isn't worth the risk of a wrong or incomplete
    answer — tier="cheap" should only be passed explicitly when a question
    is known to be simple (e.g. for batch testing in the future).
    """
    model = MODEL_CHEAP if tier == "cheap" else MODEL_STRONG
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    tool_trace = []  # Records which tools were actually called during this conversation, with what arguments, and what they returned — used for display and post-hoc analysis
    start = time.perf_counter()

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            message = chat_completion(messages, model=model, tools=TOOL_SCHEMAS)
        except BigModelAPIError as exc:
            # The API call itself failed (network, auth, timeout) — the
            # user shouldn't see a raw 500 error; handle it under the same
            # "insufficient evidence / system error means escalate to a
            # human" principle instead of letting the exception propagate.
            latency_ms = int((time.perf_counter() - start) * 1000)
            return {
                "answer": f"Copilot call failed, recommend escalating to a human: {exc}",
                "tool_trace": tool_trace,
                "model": model,
                "latency_ms": latency_ms,
                "error": True,
            }

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            # The model didn't ask to call a tool, meaning it believes it
            # can already give a final answer — end the loop
            latency_ms = int((time.perf_counter() - start) * 1000)
            return {
                "answer": message.get("content", ""),
                "tool_trace": tool_trace,
                "model": model,
                "latency_ms": latency_ms,
                "error": False,
            }

        # The model asked to call one or more tools (a single response may
        # request several at once): first append the model's "I want to
        # call a tool" message itself to the history (required by the
        # OpenAI protocol), then actually execute each tool locally and
        # feed the results back as separate role="tool" messages.
        messages.append(message)
        for call in tool_calls:
            name = call["function"]["name"]
            arguments = json.loads(call["function"]["arguments"])  # The model returns arguments as a JSON string, which needs to be parsed into a dict
            result = TOOL_FUNCTIONS[name](**arguments)  # Dispatch by name to the actual Python function in tools.py
            tool_trace.append({"tool": name, "arguments": arguments, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],  # Must be passed back unchanged; the model uses this id to know which call this result belongs to
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        # No return here — continue to the next round of the loop, since
        # after feeding the tool result back, the model needs to be asked again

    # Still no final answer after MAX_TOOL_ROUNDS rounds — handled the same
    # way, by escalating to a human. The user shouldn't be left waiting on
    # a stuck request, and the loop shouldn't run forever wasting API calls.
    latency_ms = int((time.perf_counter() - start) * 1000)
    return {
        "answer": "Copilot still hasn't produced a clear answer after multiple tool calls; recommend escalating to a human.",
        "tool_trace": tool_trace,
        "model": model,
        "latency_ms": latency_ms,
        "error": True,
    }
