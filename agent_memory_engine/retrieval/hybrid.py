"""Hybrid retrieval combining BM25 with embedding cosine similarity.

The semantic component bridges vocabulary and language gaps that lexical
matching cannot resolve. It is opt-in through ``AGENT_MEMORY_HYBRID=1`` and the
embedding model is loaded lazily on first use.
"""
from __future__ import annotations
from functools import lru_cache

from ..config import env
from .bm25 import bm25_search

_DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=1)
def _get_model():
    """Load and cache the configured sentence-transformers model."""
    from sentence_transformers import SentenceTransformer
    name = env("AGENT_MEMORY_EMBED_MODEL", "PI_MEMORY_EMBED_MODEL", _DEFAULT_MODEL)
    return SentenceTransformer(name)


def _normalize_max(scores: list[float]) -> list[float]:
    """Normalize positive scores by their maximum."""
    if not scores:
        return scores
    mx = max(scores)
    if mx <= 0:
        return [0.0] * len(scores)
    return [s / mx for s in scores]


def hybrid_search(
    query: str,
    docs: list[dict],
    k: int = 8,
    alpha: float = 0.3,
) -> list[dict]:
    """final_score = alpha * normalized_BM25 + (1 - alpha) * cosine_similarity

    ``alpha`` controls lexical weight and can be overridden with
    ``AGENT_MEMORY_HYBRID_ALPHA``. Invalid overrides fall back to the argument.
    """
    a = env("AGENT_MEMORY_HYBRID_ALPHA", "PI_MEMORY_HYBRID_ALPHA")
    if a is not None:
        try:
            candidate = float(a)
            if 0.0 <= candidate <= 1.0:
                alpha = candidate
        except ValueError:
            pass
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be between 0 and 1")
    if not docs or k <= 0:
        return []

    full_bm25 = bm25_search(query, docs, k=len(docs))
    bm25_by_id = {r["id"]: r["score"] for r in full_bm25}
    bm25_scores = [bm25_by_id.get(d["id"], 0.0) for d in docs]
    bm25_norm = _normalize_max(bm25_scores)

    model = _get_model()
    doc_embs = model.encode(
        [d["text"] for d in docs],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    q_emb = model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
    cos_scores = (doc_embs @ q_emb).tolist()

    results = []
    for i, doc in enumerate(docs):
        score = alpha * bm25_norm[i] + (1.0 - alpha) * float(cos_scores[i])
        results.append({"id": doc["id"], "score": score})

    results.sort(key=lambda r: -r["score"])
    return results[:k]
