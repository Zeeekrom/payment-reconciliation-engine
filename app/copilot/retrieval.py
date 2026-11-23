"""RAG retrieval — Phase B (AI-authored, Evan review).

The full pipeline: user question -> compute the question's vector
(embedding) -> compare that vector against the vector of every chunk in the
document store via cosine similarity -> pick the most relevant chunks ->
return the raw text to the caller (copilot.py), which then feeds it to the
LLM as supporting "material." Retrieval always happens before the LLM is
called — that's where the name RAG (Retrieval-Augmented Generation) comes
from.

**Why not ChromaDB**: the corpus is only the 4 documents under data/docs/.
Computing vectors via BigModel's embedding endpoint, storing them in memory
as a plain Python list, and comparing them with a hand-written cosine
similarity function is more than enough — the whole mechanism is fully
exposed in these few dozen lines of code instead of being hidden inside a
vector database's black box, which makes it easier to explain and easier to
debug. If the corpus grows much larger (say, hundreds or thousands of
documents, where it no longer fits in memory and a linear scan is too
slow), this simplification stops being appropriate and a real vector
database would be needed. At the current scale, this is a deliberate,
well-reasoned tradeoff — not a case of "doesn't know how to use ChromaDB."

Each document file is treated as one whole chunk (the smallest retrievable
unit), with no finer-grained splitting — the corpus itself is tiny, so
there's no need to add complexity just to "look more engineered" (YAGNI).
"""

import math
import os

from app.copilot.llm_client import embed_texts

DOCS_DIR = "data/docs"

# In-process cache: document embeddings only need to be computed once
# (document content rarely changes); caching them avoids recomputing via
# the embedding endpoint on every user question, saving both time and API
# calls.
_cache: dict = {}


class DocChunk:
    """A retrievable document chunk — in the current implementation, one
    chunk is one whole .md file."""

    def __init__(self, source: str, text: str, embedding: list[float]):
        self.source = source  # Filename, used to note "which document this content came from" when answering (the basis for citation)
        self.text = text
        self.embedding = embedding


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Hand-written cosine similarity: how close the "direction" of two
    vectors is — 1 means exactly the same direction, 0 means unrelated, a
    negative value means opposite directions. Not using numpy — the vector
    dimensionality is small (2048) and there are very few of them (4
    documents), so a plain Python loop is fast enough and doesn't warrant
    pulling in an extra dependency.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        # Edge case: a zero vector has no "direction," and the division
        # would raise ZeroDivisionError — treat this case as "completely
        # unrelated" instead of letting the program crash.
        return 0.0
    return dot / (norm_a * norm_b)


def _load_and_embed_docs(docs_dir: str = DOCS_DIR) -> list[DocChunk]:
    """Read all .md files under docs_dir and compute embeddings for all of
    them in one pass."""
    if docs_dir in _cache:
        return _cache[docs_dir]

    filenames = sorted(f for f in os.listdir(docs_dir) if f.endswith(".md"))
    texts = []
    for filename in filenames:
        with open(os.path.join(docs_dir, filename), encoding="utf-8") as f:
            texts.append(f.read())

    embeddings = embed_texts(texts)  # One API call computes embeddings for every document, saving request round-trips compared to calling one at a time
    chunks = [
        DocChunk(source=filename, text=text, embedding=embedding)
        for filename, text, embedding in zip(filenames, texts, embeddings)
    ]
    _cache[docs_dir] = chunks
    return chunks


def retrieve(query: str, top_k: int = 2, min_similarity: float = 0.3) -> list[dict]:
    """Retrieve the document chunks most relevant to query, sorted by
    similarity from highest to lowest, returning at most top_k results.

    min_similarity is the key to the "insufficient evidence" determination:
    results below this threshold are never returned, even if they're the
    "best of a bad lot" (relatively most relevant among a weak field). The
    caller (retrieve_rule in tools.py) sees an empty list and knows "no
    sufficient evidence was found" — it can't force-feed an actually
    irrelevant document as an answer, which avoids answering off-topic.

    This threshold has no theoretically "correct" value — it was chosen
    based on the score distribution the embedding-3 model produces on our
    actual corpus (in real testing, relevant content generally scored
    0.4-0.5+, while irrelevant content scored noticeably lower). If future
    use reveals frequent misjudgments — evidence that should have been
    kept getting filtered out, or irrelevant results getting let through —
    this number needs to be recalibrated against more real questions; it
    isn't something to set once and forget.
    """
    query_embedding = embed_texts([query])[0]
    chunks = _load_and_embed_docs()

    scored = [
        (chunk, _cosine_similarity(query_embedding, chunk.embedding))
        for chunk in chunks
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    results = [
        {"source": chunk.source, "text": chunk.text, "similarity": round(score, 4)}
        for chunk, score in scored[:top_k]
        if score >= min_similarity  # Sort and take the top_k first, then filter by threshold — so the final count returned may be less than top_k, even 0
    ]
    return results
