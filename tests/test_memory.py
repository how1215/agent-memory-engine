"""Unit and integration tests for the deterministic memory pipeline."""
import os
import tempfile
import pytest

from agent_memory_engine.retrieval.bm25 import tokenize, bm25_search

DOCS = [
    {"id": "d1", "text": "this project uses pnpm test"},
    {"id": "d2", "text": "the project readme is in docs"},
    {"id": "d3", "text": "run pnpm test before commit"},
]


def test_tokenize_basic():
    assert tokenize("Run pnpm Test!") == ["run", "pnpm", "test"]


def test_tokenize_cjk():
    # CJK characters are indexed individually to avoid a segmenter dependency.
    assert tokenize("資料庫 schema") == ["資", "料", "庫", "schema"]


def test_bm25_ranking_example():
    # Both documents containing the complete query should rank above the distractor.
    top = [s["id"] for s in bm25_search("pnpm test", DOCS, 2)]
    assert "d1" in top and "d3" in top
    assert "d2" not in top


def test_bm25_irrelevant_zero():
    allres = bm25_search("pnpm test", DOCS, 3)
    d2 = next(s for s in allres if s["id"] == "d2")
    assert d2["score"] == pytest.approx(0.0, abs=1e-6)


def test_bm25_idf_rare_term_wins():
    docs = [{"id": "a", "text": "the the the pnpm"}, {"id": "b", "text": "the the the the"}]
    top = bm25_search("the pnpm", docs, 1)[0]
    assert top["id"] == "a"  # The document containing the rare term wins.


@pytest.fixture
def tmp_store(monkeypatch):
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    from agent_memory_engine import service
    service.set_memory_path(f.name)
    yield f.name
    os.unlink(f.name)


def test_capture_retrieve(tmp_store):
    from agent_memory_engine.service import capture, retrieve, make_observation
    capture(make_observation("this project uses pnpm"))
    capture(make_observation("deploy with docker compose"))
    hits = retrieve("how to run pnpm", 1)
    assert "pnpm" in hits[0]["summary"]


def test_dedup(tmp_store):
    from agent_memory_engine.service import capture, retrieve, make_observation
    capture(make_observation("use pnpm"))
    capture(make_observation("use pnpm"))
    assert len(retrieve("pnpm", 10)) == 1


def test_persistence(tmp_store):
    from agent_memory_engine import service
    from agent_memory_engine.service import capture, retrieve, make_observation
    capture(make_observation("use pnpm not npm"))
    service.set_memory_path(tmp_store)  # Simulate a process restart and reload.
    assert len(retrieve("pnpm", 5)) == 1


def test_injection_budget(tmp_store):
    from agent_memory_engine.service import capture, build_injection, make_observation
    for i in range(50):
        capture(make_observation(f"pnpm fact number {i} about the build system"))
    out = build_injection("pnpm build", token_budget=80)
    assert len(out) < 80 * 4 + 50
    assert "[Relevant memories" in out


def test_custom_store_can_be_injected():
    from agent_memory_engine.service import capture, make_observation, retrieve, set_store

    class InMemoryStore:
        def __init__(self):
            self.items = []

        def add(self, observation):
            self.items.append(observation)
            return True

        def all(self):
            return list(self.items)

        def clear(self):
            self.items.clear()

    set_store(InMemoryStore())
    capture(make_observation("use pnpm for package installation"))
    assert retrieve("pnpm", 1)[0]["summary"] == "use pnpm for package installation"


# Edge cases

def test_bm25_empty_docs():
    # An empty corpus should return cleanly.
    assert bm25_search("anything", [], 5) == []


def test_bm25_empty_query():
    # The ranker keeps its documented all-zero behavior for an empty query.
    res = bm25_search("", DOCS, 3)
    assert all(s["score"] == pytest.approx(0.0, abs=1e-9) for s in res)


def test_bm25_stable_order_on_ties():
    # Exact ties retain input order for reproducible results.
    docs = [
        {"id": "a", "text": "alpha beta"},
        {"id": "b", "text": "alpha beta"},
        {"id": "c", "text": "alpha beta"},
    ]
    order = [s["id"] for s in bm25_search("alpha", docs, 3)]
    assert order == ["a", "b", "c"]


def test_store_ignores_non_list_json(tmp_store):
    # A valid JSON value with the wrong shape is treated as an empty store.
    import json
    with open(tmp_store, "w", encoding="utf-8") as f:
        json.dump({"not": "a list"}, f)
    from agent_memory_engine import service
    service.set_memory_path(tmp_store)
    from agent_memory_engine.service import retrieve
    assert retrieve("anything", 5) == []


def test_retrieve_empty_query_returns_no_memories(tmp_store):
    from agent_memory_engine.service import capture, make_observation, retrieve

    capture(make_observation("use pnpm"))
    assert retrieve("   ", 5) == []


def test_retrieve_excludes_zero_score_documents(tmp_store):
    from agent_memory_engine.service import capture, make_observation, retrieve

    capture(make_observation("deploy with Docker Compose"))
    assert retrieve("unrelated vocabulary", 5) == []


def test_zero_injection_budget_returns_empty_string(tmp_store):
    from agent_memory_engine.service import build_injection, capture, make_observation

    capture(make_observation("use pnpm"))
    assert build_injection("pnpm", token_budget=0) == ""


def test_store_creates_missing_parent_directory(tmp_path):
    from agent_memory_engine.storage.json_store import JsonStore

    path = tmp_path / "nested" / "memory.json"
    store = JsonStore(str(path))
    assert store.add({"id": "one", "summary": "durable fact"}) is True
    assert path.exists()


def test_store_rejects_observation_without_id(tmp_path):
    from agent_memory_engine.storage.json_store import JsonStore

    store = JsonStore(str(tmp_path / "memory.json"))
    with pytest.raises(ValueError, match="must contain"):
        store.add({"summary": "missing identifier"})
