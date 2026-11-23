"""Minimal wrapper around the BigModel (Zhipu AI, GLM) API — Phase B (AI-authored, Evan review).

"Minimal wrapper" means: other code in the project that needs to talk to
BigModel doesn't have to handle HTTP requests, timeouts, error handling, or
parsing the response JSON itself — it just calls the two functions in this
file (chat_completion, embed_texts). All of that plumbing is "wrapped" into
this one file.
"Minimal" means only what's actually needed was written: no caching, no
automatic retries, no third-party SDK such as openai/zhipuai. BigModel's v4
API is itself OpenAI-compatible (the request field names and the
authentication scheme are essentially the same as OpenAI's), and the surface
area is small enough that writing this layer by hand keeps the entire call
mechanism in our own code, readable line by line, without having to dig
through a third-party library's source.

Reference: https://open.bigmodel.cn/api/paas/v4/chat/completions
           https://open.bigmodel.cn/api/paas/v4/embeddings
"""

import httpx

from app.config import BIGMODEL_API_KEY, BIGMODEL_BASE_URL

# 90s, not 30s — see docs/ENGINEERING_LOG.md, FC006: repeated real-world test
# runs by the Layer 3 dev team showed that a large share of "failures" were
# actually timeouts (not model inference errors); the root cause was that
# 30s was too tight for "long context + long code generation" scenarios.
# Copilot's simple Q&A use case rarely needs this long, but since the same
# client is shared by both, it's safer to relax the timeout uniformly — the
# only cost is that a genuinely dead request takes a little longer to be
# reported as an error.
_TIMEOUT_SECONDS = 90


class BigModelAPIError(Exception):
    """Raised when a BigModel API request fails. Network issues,
    authentication failures (missing or invalid key), timeouts, and non-200
    status codes are all folded into this single exception type, so the
    caller (copilot.py) can uniformly treat "this call failed, recommend
    escalating to a human" without handling each failure mode separately.
    """


def _headers() -> dict:
    """Build the request headers. If no key is configured in .env, raise
    right here instead of waiting until the request actually goes out and
    fails authentication.
    """
    if not BIGMODEL_API_KEY:
        raise BigModelAPIError(
            "BIGMODEL_API_KEY is not set — check whether a .env file exists in the project root and contains a real key"
        )
    return {
        "Authorization": f"Bearer {BIGMODEL_API_KEY}",  # BigModel auth scheme: Bearer + raw key, no extra signing required
        "Content-Type": "application/json",
    }


def chat_completion(messages: list[dict], model: str, tools: list[dict] | None = None) -> dict:
    """Call the chat/completions endpoint and return the first choice.message
    (a dict) from the raw response.

    messages: conversation history, in the form
    [{"role": "system"/"user"/"assistant"/"tool", "content": "..."}] — the
    standard OpenAI-style format.

    tools: OpenAI-style function-calling tool definitions (see TOOL_SCHEMAS in
    app/copilot/tools.py). If tools are passed, the model may not answer
    directly after reading the question — instead, the returned message may
    carry a tool_calls field saying "I want to call this tool first, with
    these arguments." The caller (copilot.py) is responsible for detecting
    this field, actually executing the corresponding Python function, and
    feeding the result back. This file itself doesn't care how the "tool
    call loop" is driven — it only handles a single request/response.
    """
    payload = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools

    try:
        response = httpx.post(
            f"{BIGMODEL_BASE_URL}/chat/completions",
            headers=_headers(),
            json=payload,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()  # Raise proactively on non-2xx status codes, so an error page is never passed downstream as a normal result
    except httpx.TimeoutException as exc:
        raise BigModelAPIError(f"BigModel API request timed out ({_TIMEOUT_SECONDS}s)") from exc
    except httpx.HTTPStatusError as exc:
        raise BigModelAPIError(
            f"BigModel API returned error status {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except httpx.RequestError as exc:
        # Network-level issues (DNS resolution failure, connection refused, etc.) — a different case from "the server returned an error status" above
        raise BigModelAPIError(f"BigModel API request failed: {exc}") from exc

    data = response.json()
    # OpenAI-compatible format: choices is a list (supports returning
    # multiple candidate answers at once); we only use the first one, which
    # is the most common and simplest usage.
    return data["choices"][0]["message"]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Call the embeddings endpoint to convert a batch of texts into vectors
    (embeddings), returned in the same order as the input.

    Uses the embedding-3 model (BigModel's vector model, purpose-built for
    turning text into vectors — a completely different model from the chat
    model used by chat_completion). Passing a batch of texts in and
    computing them all at once saves request round-trips compared to
    calling one at a time.
    """
    try:
        response = httpx.post(
            f"{BIGMODEL_BASE_URL}/embeddings",
            headers=_headers(),
            json={"model": "embedding-3", "input": texts},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise BigModelAPIError(f"BigModel embedding request timed out ({_TIMEOUT_SECONDS}s)") from exc
    except httpx.HTTPStatusError as exc:
        raise BigModelAPIError(
            f"BigModel embedding returned error status {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except httpx.RequestError as exc:
        raise BigModelAPIError(f"BigModel embedding request failed: {exc}") from exc

    data = response.json()
    # data["data"] is a list where each item corresponds to the text at the
    # same position in the input texts list; ["embedding"] is the actual
    # vector (a long list of floats).
    return [item["embedding"] for item in data["data"]]
