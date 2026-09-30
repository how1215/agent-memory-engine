"""Behavioral checks for the governed, encrypted memory path."""
import base64
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_memory_engine.bridge import Bridge, serve
from agent_memory_engine.managed import MemoryEngine
from agent_memory_engine.storage.sqlite_secure import SQLiteMemoryStore


@pytest.fixture
def memory(tmp_path):
    path = tmp_path / "managed.sqlite"
    key = bytes(range(32))
    store = SQLiteMemoryStore(str(path), key)
    yield MemoryEngine(store), store, path, key
    store.close()


def test_review_gate_and_scope(memory):
    engine, store, _, _ = memory
    personal = engine.create_candidate("Always use pnpm")
    project_a = engine.create_candidate(
        "Use pnpm for this repository", scope="workspace", workspace_id="a"
    )
    project_b = engine.create_candidate(
        "Use pnpm for this repository", scope="workspace", workspace_id="b"
    )
    sensitive = engine.create_candidate("My private pnpm token", sensitivity="sensitive")
    assert engine.retrieve("pnpm", workspace_id="a") == []
    for item in (personal, project_a, project_b, sensitive):
        engine.approve(item.id)
    assert {r.id for r in engine.retrieve("pnpm", workspace_id="a")} == {personal.id, project_a.id}
    assert {r.id for r in engine.retrieve("pnpm", workspace_id="b")} == {personal.id, project_b.id}
    assert {r.id for r in engine.retrieve("pnpm")} == {personal.id}
    assert sensitive.id in {
        r.id for r in engine.retrieve("pnpm", authorized_sensitive_ids=(sensitive.id,))
    }
    assert len({personal.id, project_a.id, project_b.id}) == 3
    assert all(r.status == "approved" for r in store.visible("a", ()))


def test_revision_and_delete_remove_all_versions(memory):
    engine, store, path, _ = memory
    old = engine.create_candidate("Use npm")
    engine.approve(old.id)
    revised = engine.revise(old.id, "Use pnpm")
    assert [r.id for r in engine.retrieve("npm")] == [old.id]
    engine.approve(revised.id)
    assert engine.retrieve("npm") == []
    assert [r.id for r in engine.retrieve("pnpm")] == [revised.id]
    assert store.get(old.id).status == "superseded"
    assert engine.delete(revised.id) == 2
    assert engine.retrieve("pnpm") == []
    assert store.get(old.id) is None and store.get(revised.id) is None
    assert b"Use npm" not in path.read_bytes() and b"Use pnpm" not in path.read_bytes()


def test_deleted_memory_stays_absent_after_restart(memory):
    engine, store, path, key = memory
    item = engine.create_candidate("A durable but deletable fact")
    engine.approve(item.id)
    engine.delete(item.id)
    store.close()
    reopened = SQLiteMemoryStore(str(path), key)
    assert reopened.get(item.id) is None
    assert MemoryEngine(reopened).retrieve("durable") == []
    reopened.close()


def test_rejected_revision_leaves_original_active(memory):
    engine, _, _, _ = memory
    old = engine.create_candidate("Use pnpm")
    engine.approve(old.id)
    revision = engine.revise(old.id, "Use npm")
    engine.reject(revision.id)
    assert [r.id for r in engine.retrieve("pnpm")] == [old.id]
    assert engine.retrieve("npm") == []


def test_encrypted_persistence_and_wrong_key(memory):
    engine, store, path, key = memory
    item = engine.create_candidate("secret phrase only for encryption check")
    engine.approve(item.id)
    store.close()
    assert b"secret phrase" not in path.read_bytes()
    reopened = SQLiteMemoryStore(str(path), key)
    assert reopened.get(item.id).content == item.content
    reopened.close()
    with pytest.raises(Exception):
        SQLiteMemoryStore(str(path), b"x" * 32)


def test_edit_candidate_and_exact_duplicate_review(memory):
    engine, store, _, _ = memory
    first = engine.create_candidate("Use pnpm")
    second = engine.create_candidate("use PNPM")
    assert [item.id for item in engine.find_exact_duplicates(second.id)] == [first.id]
    edited = engine.edit_candidate(
        second.id, content="Use uv", kind="decision", scope="workspace",
        workspace_id="project-a", sensitivity="sensitive",
    )
    assert edited.kind == "decision" and edited.workspace_id == "project-a"
    assert edited.sensitivity == "sensitive"
    assert engine.find_exact_duplicates(edited.id) == []
    engine.approve(edited.id)
    assert store.get(edited.id).content == "Use uv"
    assert engine.retrieve("uv", workspace_id="project-a") == []
    assert [r.id for r in engine.retrieve(
        "uv", workspace_id="project-a", authorized_sensitive_ids=(edited.id,)
    )] == [edited.id]


def test_model_output_is_validated_before_any_candidate_is_written(memory):
    engine, store, _, _ = memory

    class BrokenModel:
        def propose(self, _text):
            return [
                {"content": "Use pnpm", "kind": "preference", "sensitivity": "normal"},
                {"content": "", "kind": "preference", "sensitivity": "normal"},
            ]

    engine.model = BrokenModel()
    with pytest.raises(ValueError):
        engine.propose("I prefer pnpm")
    assert store.list() == []


def test_legacy_import_is_review_only_and_idempotent(memory, tmp_path):
    engine, store, _, _ = memory
    source = tmp_path / "old.json"
    items = [
        {"id": "old1", "summary": "Use pnpm", "tags": ["build"], "unknown": {"keep": True}},
        {"id": "bad"},
    ]
    source.write_text(json.dumps(items), encoding="utf-8")
    before = source.read_bytes()
    assert engine.import_legacy(str(source)) == {"imported": 1, "skipped": 0, "invalid": 1}
    assert engine.import_legacy(str(source)) == {"imported": 0, "skipped": 1, "invalid": 1}
    assert source.read_bytes() == before
    assert engine.retrieve("pnpm") == []
    imported = store.list()[0]
    assert imported.status == "candidate"
    assert imported.legacy_payload == items[0]


def test_model_port_skips_sensitive_candidates(memory):
    engine, _, _, _ = memory

    class FakeModel:
        def propose(self, user_text):
            assert user_text == "I prefer pnpm"
            return [
                {"content": "Prefer pnpm", "kind": "preference", "sensitivity": "normal"},
                {"content": "Private health detail", "kind": "preference", "sensitivity": "sensitive"},
            ]

    engine.model = FakeModel()
    proposals = engine.propose("I prefer pnpm", source_id="message-1")
    assert len(proposals) == 1
    assert proposals[0].status == "candidate"
    assert proposals[0].source_id == "message-1"


def test_bridge_protocol_and_review_gate(tmp_path):
    bridge = Bridge()
    key = base64.b64encode(bytes(range(32))).decode()

    def call(request_id, op, args=None, version=1):
        return bridge.handle({"version": version, "id": request_id, "op": op, "args": args or {}})

    assert call(1, "health")["result"] == {"ready": False}
    assert call(2, "list")["error"]["code"] == "RuntimeError"
    assert call(3, "init", {"path": str(tmp_path / "bridge.sqlite"), "key": key})["ok"]
    created = call(4, "create_candidate", {"content": "Use pnpm"})
    assert created["ok"] and created["id"] == 4
    record_id = created["result"]["id"]
    assert call(5, "retrieve", {"query": "pnpm"})["result"] == []
    assert call(6, "approve", {"id": record_id})["ok"]
    assert call(7, "retrieve", {"query": "pnpm"})["result"][0]["id"] == record_id
    assert call(8, "unknown")["error"]["code"] == "ValueError"
    assert not call(9, "health", version=2)["ok"]
    assert call(10, "shutdown")["ok"]


def test_bridge_json_lines_round_trip(tmp_path):
    key = base64.b64encode(bytes(range(32))).decode()
    requests = [
        {"version": 1, "id": "a", "op": "health"},
        {"version": 1, "id": "b", "op": "init", "args": {
            "path": str(tmp_path / "memory.sqlite"), "key": key,
        }},
        {"version": 1, "id": "c", "op": "create_candidate", "args": {
            "content": "Remember to use pnpm",
        }},
        {"version": 1, "id": "d", "op": "shutdown"},
    ]
    output = io.StringIO()
    serve(io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n"), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [r["id"] for r in responses] == ["a", "b", "c", "d"]
    assert responses[0]["result"]["ready"] is False
    assert responses[2]["result"]["status"] == "candidate"
    assert responses[3]["result"]["ready"] is False


@pytest.mark.skipif(sys.platform != "darwin" or shutil.which("swift") is None,
                    reason="Swift CryptoKit is only available on macOS")
def test_swift_can_decrypt_python_memory(memory, tmp_path):
    engine, store, _, key = memory
    record = engine.create_candidate("Cross-language encrypted memory")
    blob = store.db.execute("SELECT payload FROM memories WHERE id = ?", (record.id,)).fetchone()[0]
    request = {
        "key": base64.b64encode(key).decode(),
        "blob": base64.b64encode(blob).decode(),
        "id": record.id,
    }
    script = Path(__file__).with_name("crypto_interop.swift")
    run = subprocess.run(
        ["swift", str(script)], input=json.dumps(request) + "\n",
        text=True, capture_output=True, check=True, timeout=120,
    )
    assert json.loads(run.stdout)["content"] == record.content
