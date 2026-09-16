"""Dependency-free tests for hybrid score composition and validation."""

import pytest

from agent_memory_engine.retrieval.hybrid import _normalize_max, hybrid_search


class _VectorResult:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class _DocumentEmbeddings:
    def __init__(self, values):
        self.values = values

    def __matmul__(self, _query_embedding):
        return _VectorResult(self.values)


class _FakeModel:
    def encode(self, texts, **_kwargs):
        if len(texts) == 1 and texts[0] == "semantic query":
            return [[1.0]]
        return _DocumentEmbeddings([0.2, 0.9])


def test_normalize_max():
    assert _normalize_max([0.0, 2.0, 1.0]) == [0.0, 1.0, 0.5]
    assert _normalize_max([0.0, 0.0]) == [0.0, 0.0]


def test_hybrid_semantic_signal_can_change_ranking(monkeypatch):
    monkeypatch.setattr("agent_memory_engine.retrieval.hybrid._get_model", lambda: _FakeModel())
    docs = [
        {"id": "lexical", "text": "semantic query"},
        {"id": "semantic", "text": "different words"},
    ]

    results = hybrid_search("semantic query", docs, k=2, alpha=0.3)

    assert [result["id"] for result in results] == ["semantic", "lexical"]


def test_hybrid_rejects_invalid_alpha():
    with pytest.raises(ValueError, match="between 0 and 1"):
        hybrid_search("query", [{"id": "one", "text": "query"}], alpha=1.1)


def test_hybrid_returns_empty_for_non_positive_k():
    assert hybrid_search("query", [{"id": "one", "text": "query"}], k=0) == []
