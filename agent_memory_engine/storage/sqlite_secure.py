"""Encrypted, transactional SQLite storage for reviewed memories."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from dataclasses import asdict, replace
from pathlib import Path

from ..managed import MemoryRecord


class SQLiteMemoryStore:
    def __init__(self, path: str, key: bytes):
        if len(key) != 32:
            raise ValueError("memory encryption key must be 32 bytes")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self._cipher = AESGCM(key)
        self._key = key
        destination = Path(path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(destination)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise ValueError("unsupported database schema version")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                scope TEXT NOT NULL,
                workspace_id TEXT,
                sensitivity TEXT NOT NULL,
                source_id TEXT,
                supersedes_id TEXT,
                legacy_key TEXT UNIQUE,
                payload BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS memories_visible
                ON memories(status, scope, workspace_id, sensitivity);
            CREATE INDEX IF NOT EXISTS memories_source ON memories(source_id);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                memory_id TEXT NOT NULL,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        check = self.db.execute("SELECT value FROM metadata WHERE key = 'key_check'").fetchone()
        if check:
            if self._decrypt(check[0], b"key-check") != b"agent-memory-engine:v1":
                raise ValueError("invalid memory encryption key")
        else:
            with self.db:
                self.db.execute(
                    "INSERT INTO metadata(key, value) VALUES ('key_check', ?)",
                    (self._encrypt(b"agent-memory-engine:v1", b"key-check"),),
                )
        if version == 0:
            self.db.execute("PRAGMA user_version=1")

    def close(self) -> None:
        self.db.close()

    def _encrypt(self, clear: bytes, associated_data: bytes) -> bytes:
        nonce = os.urandom(12)
        return b"AME1" + nonce + self._cipher.encrypt(nonce, clear, associated_data)

    def _decrypt(self, blob: bytes, associated_data: bytes) -> bytes:
        if not blob.startswith(b"AME1") or len(blob) < 32:
            raise ValueError("invalid encrypted memory payload")
        nonce = blob[4:16]
        return self._cipher.decrypt(nonce, blob[16:], associated_data)

    def _seal(self, record: MemoryRecord) -> bytes:
        clear = json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":")).encode()
        return self._encrypt(clear, record.id.encode())

    def _unseal(self, row: sqlite3.Row) -> MemoryRecord:
        blob = row["payload"]
        clear = self._decrypt(blob, row["id"].encode())
        record = MemoryRecord(**json.loads(clear))
        for field in ("id", "status", "scope", "workspace_id", "sensitivity", "source_id", "supersedes_id"):
            if getattr(record, field) != row[field]:
                raise ValueError("memory metadata does not match encrypted payload")
        return record

    def _write(self, record: MemoryRecord, *, legacy_key: str | None = None) -> None:
        self.db.execute(
            """INSERT INTO memories
               (id, status, scope, workspace_id, sensitivity, source_id,
                supersedes_id, legacy_key, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record.id, record.status, record.scope, record.workspace_id,
             record.sensitivity, record.source_id, record.supersedes_id,
             legacy_key, self._seal(record)),
        )

    def put(self, record: MemoryRecord, *, legacy_key: str | None = None) -> None:
        with self.db:
            self._write(record, legacy_key=legacy_key)

    def get(self, record_id: str) -> MemoryRecord | None:
        row = self.db.execute("SELECT * FROM memories WHERE id = ?", (record_id,)).fetchone()
        return self._unseal(row) if row else None

    def list(self) -> list[MemoryRecord]:
        rows = self.db.execute("SELECT * FROM memories ORDER BY rowid").fetchall()
        return [self._unseal(row) for row in rows]

    def visible(
        self, workspace_id: str | None, authorized_sensitive_ids: tuple[str, ...]
    ) -> list[MemoryRecord]:
        # Filter before decryption; the caller must authorize each sensitive ID.
        rows = self.db.execute(
            """SELECT * FROM memories WHERE status = 'approved'
               AND (scope = 'personal' OR (scope = 'workspace' AND workspace_id = ?))
               ORDER BY rowid""",
            (workspace_id,),
        ).fetchall()
        authorized = set(authorized_sensitive_ids)
        return [self._unseal(row) for row in rows
                if row["sensitivity"] == "normal" or row["id"] in authorized]

    def _update(self, record: MemoryRecord) -> None:
        self.db.execute(
            """UPDATE memories SET status = ?, scope = ?, workspace_id = ?,
               sensitivity = ?, source_id = ?, supersedes_id = ?, payload = ?
               WHERE id = ?""",
            (record.status, record.scope, record.workspace_id,
             record.sensitivity, record.source_id, record.supersedes_id,
             self._seal(record), record.id),
        )

    def set_status(self, record_id: str, status: str) -> None:
        record = self.get(record_id)
        if record is None:
            raise KeyError(record_id)
        with self.db:
            self._update(replace(record, status=status, updated_at=time.time()))

    def update_candidate(self, record: MemoryRecord) -> None:
        current = self.get(record.id)
        if current is None or current.status != "candidate" or record.status != "candidate":
            raise ValueError("only candidates can be edited")
        with self.db:
            self._update(record)

    def approve_revision(self, candidate: MemoryRecord) -> None:
        if not candidate.supersedes_id:
            raise ValueError("revision must supersede an existing memory")
        with self.db:
            prior = self.get(candidate.supersedes_id)
            current = self.get(candidate.id)
            if prior is None or prior.status != "approved" or current is None or current.status != "candidate":
                raise ValueError("revision is no longer valid")
            now = time.time()
            self._update(replace(prior, status="superseded", updated_at=now))
            self._update(replace(current, status="approved", updated_at=now))

    def delete_family(self, record_id: str) -> int:
        rows = self.db.execute("SELECT id, supersedes_id FROM memories").fetchall()
        parents = {row["id"]: row["supersedes_id"] for row in rows}
        if record_id not in parents:
            raise KeyError(record_id)
        root = record_id
        while parents[root] is not None and parents[root] in parents:
            root = parents[root]
        family = {root}
        while True:
            children = {child for child, parent in parents.items() if parent in family}
            if children <= family:
                break
            family |= children
        with self.db:
            for member in family:
                self.db.execute("DELETE FROM memories WHERE id = ?", (member,))
                self.db.execute(
                    "INSERT INTO audit(event, memory_id) VALUES ('deleted', ?)",
                    (member,),
                )
        return len(family)

    def legacy_fingerprint(self, source: str, old_id: str) -> str:
        data = f"{source}\0{old_id}".encode()
        return hmac.new(self._key, data, hashlib.sha256).hexdigest()

    def has_legacy_key(self, legacy_key: str) -> bool:
        row = self.db.execute("SELECT 1 FROM memories WHERE legacy_key = ?", (legacy_key,)).fetchone()
        return row is not None
