# Managed memory v1

The managed API adds user review and scoped retrieval without changing the
existing `capture` / `retrieve` JSON API. Install `.[managed]` to use encrypted
SQLite storage. The baseline installation still has no model, network, or
cryptography dependency.

## Lifecycle

```python
from agent_memory_engine import MemoryEngine, SQLiteMemoryStore

store = SQLiteMemoryStore("managed.sqlite", key=key_from_app_keychain)
engine = MemoryEngine(store)
candidate = engine.create_candidate("Prefer pnpm", kind="preference")
engine.approve(candidate.id)
hits = engine.retrieve("package manager", workspace_id="project-a")
store.close()
```

The app creates and owns the 32-byte encryption key. It passes the key to the
local helper through stdin, never through command-line arguments or environment
variables. `MemoryEngine.propose` accepts an injected `MemoryModel`; the core
does not import an LLM SDK. Automatic proposals accept only items the model
explicitly marks as normal; this classification cannot guarantee that all
sensitive content was detected. Sensitive memories can be entered manually and retrieval requires
their IDs in `authorized_sensitive_ids` on each request. The app must still
obtain the user's permission before passing those IDs.

Candidates and rejected records are never retrieved. A revision remains a
candidate until approval atomically supersedes its predecessor. Deleting any
version deletes its entire revision family and leaves only content-free audit
events. Exact duplicates can be shown for review with
`find_exact_duplicates`; they are not silently merged.

## Storage and compatibility

`SQLiteMemoryStore` keeps record content, source excerpts, and legacy payloads
inside an authenticated AES-256-GCM blob. The blob starts with `AME1`, followed
by a 12-byte nonce, ciphertext, and a 16-byte tag; the record ID is associated
data. Swift CryptoKit can open the combined nonce/ciphertext/tag after removing
the `AME1` prefix. Database metadata needed for scope filtering remains
unencrypted but is checked against the authenticated payload before use. The
store has no persisted plaintext search or embedding index; it decrypts only
approved in-scope rows in memory, then uses the existing BM25 ranker.

The schema and bridge protocol are version 1. An incompatible future database
version fails to open. A key check prevents an existing managed database from
silently opening with the wrong key. The app must preserve the Keychain key or
restore through its encrypted backup flow; this module does not create
backups or manage Keychain.

`import_legacy(path)` copies valid observations from a v0 JSON array into
pending review. It preserves unknown source fields inside the encrypted legacy
payload, reports malformed entries, and is idempotent for a given source path
and legacy ID. It never edits or removes the original JSON file. The app should
tell the user that this original may still contain plaintext.

## Local bridge

`agent-memory-bridge` reads one JSON request per stdin line and writes one JSON
response per stdout line. Every request has `version: 1`, an `id`, an `op`, and
an `args` object. Responses echo the ID and contain either `ok: true` with
`result`, or `ok: false` with a structured `error`. Send `init` first with the
database `path` and base64-encoded key in `args`. The app-specific adapter may
inject a model provider when starting `serve`; without one, manual candidate
operations work and `propose` returns a configuration error.

Operations: `health`, `init`, `create_candidate`, `propose`, `edit_candidate`,
`find_exact_duplicates`, `approve`, `reject`, `revise`, `retrieve`, `get`,
`list`, `delete`, `import_legacy`, `shutdown`. The bridge keeps state in one
process until `shutdown`; the app owns timeout, cancellation, and restart.

## Verification

Run `uv run --extra managed --extra test pytest -q`. On macOS, the test suite
also checks that Swift CryptoKit decrypts a Python-produced record. The
existing lexical benchmark remains `Recall@5 0.810`, `MRR 0.810`, and
`nDCG@5 0.802` on its 30-memory/21-query fixture; the ranking code is
unchanged. Scope, review, and sensitive-memory behavior are tested separately.

## Personal Agent integration status (2026-09-30)

The separate [Personal Agent repository](https://github.com/how1215/personal-agent)
contains the SwiftUI macOS app, Google/OpenAI model adapters, encrypted
conversation snapshots, Keychain data-key management, and password-protected
backup/restore. API credentials are manually supplied for each app session.
These app-specific features are implemented outside this engine. The app
build script bundles a source snapshot of this package and records its Git
revision and SHA-256 manifest.

The managed v1 engine changes are verified by 35 passing tests on macOS,
including Swift CryptoKit interoperability. The original JSON API remains
available; encrypted storage requires the optional managed dependency.
The app's successful live API conversation and full clean-user GUI acceptance
remain pending; a reported Google 503 has been addressed with app-level
bounded retries and mock HTTP tests.
