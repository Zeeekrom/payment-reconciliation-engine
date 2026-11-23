"""The three Copilot tools — Phase B (AI-authored, Evan review).

The first two are precise lookups (reading Layer 1's SQLite data directly);
the third is semantic retrieval (RAG). The division of labor between them:
when there's a specific key (payment_id), use a precise lookup — the answer
is uniquely determined; when there's no key and only a natural-language
question, use retrieval instead, which is a fuzzy "which is most relevant"
match. This isn't about the size of the data being searched — it's a
difference in the nature of the question. Using them the other way around
(e.g. running a precise key through vector retrieval) would actually reduce
accuracy.

TOOL_SCHEMAS holds OpenAI-style function-calling tool definitions (JSON
Schema format) that are fed directly to BigModel's chat/completions
endpoint. The model reads these descriptions and decides for itself whether
to call a tool, which one, and with what arguments — this is the mechanism
behind "the AI routes itself"; we don't need to hardcode logic like "this
phrase always goes to that tool." TOOL_FUNCTIONS is a mapping from tool name
to the actual Python function; after copilot.py receives the model's
tool_calls, it looks up the matching function in this dict by name and
executes it (see the line TOOL_FUNCTIONS[name](**arguments) in copilot.py).
"""

from app.core.db import get_connection, get_events_for_payment, get_payment_state, init_db
from app.copilot.retrieval import retrieve

DB_PATH = "data/db/payments.db"  # Shares the same database file as Layer 1 — Copilot only reads, it never creates a new one


def query_payment_record(payment_id: str) -> dict:
    """Precise lookup: the current state of this payment. Reuses Layer 1's
    db.py directly rather than reimplementing the query logic."""
    conn = get_connection(DB_PATH)
    try:
        init_db(conn)  # No-op if the tables already exist; kept here so calling this function standalone never fails due to missing tables
        state = get_payment_state(conn, payment_id)
    finally:
        conn.close()

    if state is None:
        # Not found isn't an error (this payment_id may simply never have
        # occurred) — return an explicit found=False structure so the LLM
        # can understand "this payment doesn't exist" instead of guessing.
        return {"found": False, "payment_id": payment_id}
    return {
        "found": True,
        "payment_id": state.payment_id,
        "status": state.status.value,  # PaymentStatus is an Enum; .value extracts a plain string, convenient for JSON
        "source_event_ids": state.source_event_ids,
        "last_updated": state.last_updated.isoformat(),
    }


def inspect_logs(payment_id: str) -> dict:
    """Precise lookup: the complete audit log (raw event history) for this
    payment.

    The difference from query_payment_record: that one only returns a
    single conclusion — "what's the current state" — while this one
    returns "what actually happened, the raw content of every
    notification." For "why did this happen" style questions, a conclusion
    alone isn't enough; the LLM needs to see the raw evidence and analyze
    it itself.
    """
    conn = get_connection(DB_PATH)
    try:
        init_db(conn)
        events = get_events_for_payment(conn, payment_id)
    finally:
        conn.close()

    return {
        "payment_id": payment_id,
        "event_count": len(events),
        "events": [
            {
                "event_id": e.event_id,
                "channel_id": e.channel_id,
                "raw_data": e.raw_data,  # Returned as-is with no processing, so the LLM sees the most faithful information
                "received_at": e.received_at.isoformat(),
            }
            for e in events
        ],
    }


def retrieve_rule(question: str) -> dict:
    """Semantic retrieval: find content relevant to the question from the
    channel documentation and internal rule documents.

    The actual retrieval logic lives in retrieve() in
    app/copilot/retrieval.py; this is just a thin wrapper that reshapes the
    result into a structure the LLM can understand more easily (adding the
    explicit found_evidence boolean).

    found_evidence=False means "no sufficiently relevant evidence was
    found" — this is filtered out by the similarity threshold in
    retrieval.py, not something the LLM decides for itself. The system
    prompt (see prompts/copilot_system_v1.md) requires the model, on seeing
    this field as false, to explicitly tell the user "the evidence is
    insufficient" rather than making up an answer that merely sounds
    plausible.
    """
    results = retrieve(question)
    return {"query": question, "results": results, "found_evidence": len(results) > 0}


TOOL_FUNCTIONS = {
    "query_payment_record": query_payment_record,
    "inspect_logs": inspect_logs,
    "retrieve_rule": retrieve_rule,
}

# The TOOL_SCHEMAS below are sent to the BigModel API as-is. The more
# clearly each description is written, the more accurately the model can
# judge "should I call this tool" — this is itself part of "prompt
# quality," not an afterthought: all three descriptions deliberately give
# concrete examples of "what kind of question this fits," rather than just
# an abstract description of what the function does.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_payment_record",
            "description": "Look up the current deterministic state of a payment (PENDING/CHANNEL_CONFIRMED/CHANNEL_FAILED/NEEDS_REVIEW/RECONCILED_SUCCESS/RECONCILED_FAILED). Use for questions like 'what state is this payment in right now' where a specific payment ID is known.",
            "parameters": {
                "type": "object",
                "properties": {
                    "payment_id": {"type": "string", "description": "Payment ID"},
                },
                "required": ["payment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_logs",
            "description": "Look up the complete raw event history (audit log) for a payment, including which channel each notification came from, its raw content, and when it was received. Use for questions like 'what actually happened with this payment' that require looking at the history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "payment_id": {"type": "string", "description": "Payment ID"},
                },
                "required": ["payment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_rule",
            "description": "Retrieve relevant content from the channel documentation and internal business rule documents. Use for questions like 'why did this happen', 'what does this status code mean', or 'what is our rule for this' — conceptual/rule questions that aren't about a specific payment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question or keywords to search for"},
                },
                "required": ["question"],
            },
        },
    },
]
