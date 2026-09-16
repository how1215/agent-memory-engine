"""Deterministic BM25 ranking with lightweight multilingual tokenization."""
from __future__ import annotations
import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """Return lowercase alphanumeric tokens and individual CJK characters."""
    return _TOKEN_RE.findall(text.lower())


def bm25_search(
    query: str,
    docs: list[dict],
    k: int = 8,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[dict]:
    """Rank documents with Okapi BM25.

    Documents must contain ``id`` and ``text`` keys. Ties retain input order,
    which keeps benchmark runs reproducible.

      score(q,d) = Σ_qi IDF(qi) * (tf*(k1+1)) / (tf + k1*(1 - b + b*|d|/avgdl))
      IDF(qi)    = ln( (N - n + 0.5)/(n + 0.5) + 1 )
    """
    if not docs or k <= 0:
        return []

    tokenized = [tokenize(d["text"]) for d in docs]
    doc_lens = [len(toks) for toks in tokenized]
    N = len(docs)
    total_len = sum(doc_lens)
    avgdl = total_len / N if total_len > 0 else 1.0

    df: dict[str, int] = {}
    for toks in tokenized:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1

    tf_per_doc = [Counter(toks) for toks in tokenized]
    query_terms = tokenize(query)

    results: list[dict] = []
    for i, doc in enumerate(docs):
        score = 0.0
        dl = doc_lens[i]
        tf = tf_per_doc[i]
        for term in query_terms:
            term_tf = tf.get(term, 0)
            if term_tf == 0:
                continue
            n = df[term]
            idf = math.log((N - n + 0.5) / (n + 0.5) + 1)
            denom = term_tf + k1 * (1 - b + b * dl / avgdl)
            score += idf * (term_tf * (k1 + 1)) / denom
        results.append({"id": doc["id"], "score": score})

    results.sort(key=lambda r: -r["score"])
    return results[:k]
