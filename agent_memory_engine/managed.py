"""User-governed memory lifecycle, separate from the legacy observation API."""
from __future__ import annotations

import time
import uuid
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from .retrieval.bm25 import bm25_search

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    content: str
    kind: str
    status: str
    scope: str
    workspace_id: str | None
    sensitivity: str
    source_id: str | None
    source_excerpt: str | None
    version: int
    supersedes_id: str | None
    created_at: float
    updated_at: float
    legacy_payload: dict | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.id or not self.content.strip():
            raise ValueError("memory id and content are required")
        if self.kind not in {"preference", "decision"}:
            raise ValueError("invalid memory kind")
        if self.status not in {"candidate", "approved", "rejected", "superseded"}:
            raise ValueError("invalid memory status")
        if self.scope not in {"personal", "workspace"}:
            raise ValueError("invalid memory scope")
        if self.scope == "workspace" and not self.workspace_id:
            raise ValueError("workspace scope requires workspace_id")
        if self.scope == "personal" and self.workspace_id is not None:
            raise ValueError("personal scope cannot have workspace_id")
        if self.sensitivity not in {"normal", "sensitive"}:
            raise ValueError("invalid memory sensitivity")
        if self.version < 1:
            raise ValueError("memory version must be positive")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported memory schema version")


class MemoryModel(Protocol):
    """An app-provided model adapter; the engine does not import an LLM SDK."""

    def propose(self, user_text: str) -> list[dict]: ...


class RecordStore(Protocol):
    def put(self, record: MemoryRecord, *, legacy_key: str | None = None) -> None: ...
    def get(self, record_id: str) -> MemoryRecord | None: ...
    def list(self) -> list[MemoryRecord]: ...
    def visible(
        self, workspace_id: str | None, authorized_sensitive_ids: tuple[str, ...]
    ) -> list[MemoryRecord]: ...
    def set_status(self, record_id: str, status: str) -> None: ...
    def update_candidate(self, record: MemoryRecord) -> None: ...
    def approve_revision(self, candidate: MemoryRecord) -> None: ...
    def delete_family(self, record_id: str) -> int: ...
    def has_legacy_key(self, legacy_key: str) -> bool: ...
    def legacy_fingerprint(self, source: str, old_id: str) -> str: ...


class MemoryEngine:
    def __init__(self, store: RecordStore, model: MemoryModel | None = None):
        self.store = store
        self.model = model

    def create_candidate(
        self,
        content: str,
        *,
        kind: str = "preference",
        scope: str = "personal",
        workspace_id: str | None = None,
        sensitivity: str = "normal",
        source_id: str | None = None,
        source_excerpt: str | None = None,
        legacy_payload: dict | None = None,
        legacy_key: str | None = None,
    ) -> MemoryRecord:
        now = time.time()
        record = MemoryRecord(
            id=str(uuid.uuid4()), content=content.strip(), kind=kind,
            status="candidate", scope=scope, workspace_id=workspace_id,
            sensitivity=sensitivity, source_id=source_id,
            source_excerpt=source_excerpt, version=1, supersedes_id=None,
            created_at=now, updated_at=now, legacy_payload=legacy_payload,
        )
        self.store.put(record, legacy_key=legacy_key)
        return record

    def propose(
        self, user_text: str, *, source_id: str | None = None,
        scope: str = "personal", workspace_id: str | None = None,
    ) -> list[MemoryRecord]:
        if self.model is None:
            raise RuntimeError("no memory model configured")
        proposed = self.model.propose(user_text)
        if not isinstance(proposed, list):
            raise ValueError("model must return a candidate list")
        normal = []
        for item in proposed:
            if not isinstance(item, dict) or not isinstance(item.get("content"), str):
                raise ValueError("invalid model candidate")
            if item.get("sensitivity") != "normal":
                continue  # Only explicitly classified normal items can be proposed.
            if not item["content"].strip() or item.get("kind") not in {"preference", "decision"}:
                raise ValueError("invalid model candidate")
            normal.append(item)
        candidates = []
        for item in normal:
            candidates.append(self.create_candidate(
                item["content"], kind=item["kind"], scope=scope,
                workspace_id=workspace_id, source_id=source_id,
                source_excerpt=user_text[:240],
            ))
        return candidates

    def approve(self, record_id: str) -> MemoryRecord:
        record = self._candidate(record_id)
        if record.supersedes_id:
            self.store.approve_revision(record)
        else:
            self.store.set_status(record_id, "approved")
        return self._required(record_id)

    def reject(self, record_id: str) -> MemoryRecord:
        self._candidate(record_id)
        self.store.set_status(record_id, "rejected")
        return self._required(record_id)

    def edit_candidate(
        self, record_id: str, *, content: str, kind: str | None = None,
        sensitivity: str | None = None, scope: str | None = None,
        workspace_id: str | None = None,
    ) -> MemoryRecord:
        prior = self._candidate(record_id)
        edited = replace(
            prior, content=content.strip(), kind=kind or prior.kind,
            sensitivity=sensitivity or prior.sensitivity,
            scope=scope or prior.scope,
            workspace_id=workspace_id if scope is not None else prior.workspace_id,
            updated_at=time.time(),
        )
        self.store.update_candidate(edited)
        return edited

    def find_exact_duplicates(self, record_id: str) -> list[MemoryRecord]:
        target = self._required(record_id)
        return [
            item for item in self.store.list()
            if item.id != target.id and item.status in {"candidate", "approved"}
            and item.content.casefold() == target.content.casefold()
            and item.scope == target.scope and item.workspace_id == target.workspace_id
        ]

    def revise(self, record_id: str, content: str) -> MemoryRecord:
        prior = self._required(record_id)
        if prior.status != "approved":
            raise ValueError("only approved memories can be revised")
        now = time.time()
        candidate = replace(
            prior, id=str(uuid.uuid4()), content=content.strip(),
            status="candidate", version=prior.version + 1,
            supersedes_id=prior.id, created_at=now, updated_at=now,
            legacy_payload=None,
        )
        self.store.put(candidate)
        return candidate

    def retrieve(
        self, query: str, *, workspace_id: str | None = None,
        authorized_sensitive_ids: tuple[str, ...] = (), k: int = 8,
    ) -> list[MemoryRecord]:
        if not query.strip() or k <= 0:
            return []
        records = self.store.visible(workspace_id, authorized_sensitive_ids)
        docs = [{"id": item.id, "text": item.content} for item in records]
        ranked = [r for r in bm25_search(query, docs, k) if r["score"] > 0]
        by_id = {item.id: item for item in records}
        return [by_id[row["id"]] for row in ranked]

    def delete(self, record_id: str) -> int:
        self._required(record_id)
        return self.store.delete_family(record_id)

    def import_legacy(self, path: str) -> dict[str, int]:
        """Copy valid v0 observations into review, leaving the source untouched."""
        source = Path(path).expanduser().resolve()
        with source.open(encoding="utf-8") as file:
            items = json.load(file)
        if not isinstance(items, list):
            raise ValueError("legacy store must contain a JSON array")
        report = {"imported": 0, "skipped": 0, "invalid": 0}
        for item in items:
            if not (
                isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and isinstance(item.get("summary"), str)
                and item["summary"].strip()
            ):
                report["invalid"] += 1
                continue
            key = self.store.legacy_fingerprint(str(source), item["id"])
            if self.store.has_legacy_key(key):
                report["skipped"] += 1
                continue
            self.create_candidate(
                item["summary"], kind="decision", source_id=f"legacy:{key}",
                source_excerpt=item["summary"], legacy_payload=item,
                legacy_key=key,
            )
            report["imported"] += 1
        return report

    def _required(self, record_id: str) -> MemoryRecord:
        record = self.store.get(record_id)
        if record is None:
            raise KeyError(record_id)
        return record

    def _candidate(self, record_id: str) -> MemoryRecord:
        record = self._required(record_id)
        if record.status != "candidate":
            raise ValueError("memory is not awaiting review")
        return record
