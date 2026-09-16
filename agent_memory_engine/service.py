"""Public capture, retrieval, and prompt-injection pipeline."""
from __future__ import annotations
import hashlib
import time
from .config import default_store_path, env
from .retrieval.bm25 import bm25_search
from .storage.base import MemoryStore
from .storage.json_store import JsonStore

_store_path = default_store_path()
_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = JsonStore(_store_path)
    return _store


def set_memory_path(path: str) -> None:
    """Select the JSON backend path and reload it, primarily for local use and tests."""
    global _store_path, _store
    _store_path = path
    _store = JsonStore(_store_path)


def set_store(store: MemoryStore) -> None:
    """Inject a storage backend implementing ``MemoryStore``.

    This is the extension point for future SQLite, service, or vector-backed
    stores without coupling the application service to their implementation.
    """
    global _store
    _store = store


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """Estimate token usage without adding a tokenizer dependency."""
    return max(1, len(text) // 4)


def make_observation(summary: str, session_id: str = "s", tool_name: str = "remember",
                     tags: list[str] | None = None) -> dict:
    """Build the canonical observation record used by every integration."""
    return {
        "id": sha256(summary),
        "sessionId": session_id,
        "timestamp": int(time.time() * 1000),
        "toolName": tool_name,
        "summary": summary,
        "tags": tags or [],
    }


def capture(obs: dict) -> bool:
    """Persist one observation and report whether it was newly added."""
    return _get_store().add(obs)


def retrieve(query: str, k: int) -> list[dict]:
    """Return the top observations using lexical or optional hybrid search."""
    if not query.strip() or k <= 0:
        return []
    all_obs = _get_store().all()
    docs = [{"id": o["id"], "text": " ".join([o["summary"], *o.get("tags", [])])} for o in all_obs]
    if env("AGENT_MEMORY_HYBRID", "PI_MEMORY_HYBRID") == "1":
        from .retrieval.hybrid import hybrid_search
        ranked = hybrid_search(query, docs, k)
    else:
        # Zero-score documents are not relevant merely because the store is small.
        ranked = [result for result in bm25_search(query, docs, k) if result["score"] > 0]
    by_id = {o["id"]: o for o in all_obs}
    return [by_id[r["id"]] for r in ranked if r["id"] in by_id]


def build_injection(query: str, token_budget: int = 2000, k: int = 8) -> str:
    """Format retrieved memories for an agent without exceeding a token budget."""
    if token_budget <= 0:
        return ""
    hits = retrieve(query, k)
    header = "[Relevant memories from previous sessions]"
    lines, used = [], estimate_tokens(header)
    for h in hits:
        line = f"- {h['summary']}"
        cost = estimate_tokens(line)
        if used + cost > token_budget:
            break
        lines.append(line)
        used += cost
    return "\n".join([header, *lines]) if lines else ""
