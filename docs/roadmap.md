# Maturity roadmap

Managed v1 now implements a separate, opt-in path for typed preference/decision
records, user review, workspace filtering, encrypted SQLite storage, legacy
import, and a local JSON-lines bridge. The original JSON observation API is
unchanged. The phases below describe remaining platform maturity; their
"current" labels refer to the original API and should not be read as denying
the managed v1 path. See [managed memory v1](managed-memory.md).

This roadmap separates implemented behavior from planned work. Milestones are
ordered by dependency and risk rather than novelty.

## Definition of a mature system

Agent Memory Engine is considered production-capable when it has versioned data,
transactional persistence, tenant/workspace isolation, explicit lifecycle and
conflict policies, privacy controls, observable quality/latency, stable adapter
contracts, and tested recovery procedures. Adding a vector database alone does
not satisfy this definition.

## Phase 0 — framework-neutral foundation (current)

Delivered:

- framework-neutral package and CLI naming;
- layered `retrieval/`, `storage/`, and `adapters/` directories;
- `MemoryStore` protocol and `set_store()` injection seam;
- JSON, BM25, optional hybrid retrieval, context budget, Pi adapter;
- offline Recall/MRR/nDCG benchmark;
- `AGENT_MEMORY_*` configuration with deprecated Pi aliases.

Exit check: existing deterministic tests and benchmark continue to pass after
restructuring.

## Phase 1 — typed data and user control

### Deliverables

- typed, versioned `MemoryRecord` and validation errors;
- migration from schema-zero JSON observations;
- memory kinds, provenance, source, workspace, and optional expiration;
- `list`, `get`, `delete`, `export`, and `import` APIs/CLI;
- dry-run cleanup and audit entries;
- exact and semantic duplicate review instead of silent semantic deletion.

### Acceptance criteria

- old stores migrate without data loss and migration is idempotent;
- malformed records are reported rather than silently erasing the whole store;
- delete/export behavior has integration tests;
- every record can answer where and why it was captured.

## Phase 2 — retrieval and policy quality

### Deliverables

- retriever and reranker interfaces with score explanations;
- metadata/scope filters applied before ranking;
- reciprocal-rank fusion comparison against score interpolation;
- recency, confidence, and memory-kind policy;
- conflict/supersession model for changed decisions;
- model-aware token counting and long-record truncation;
- hybrid-to-BM25 fallback.

### Acceptance criteria

- held-out datasets include negatives, stale facts, conflicts, paraphrases, and
  multilingual queries;
- Precision@k, Recall@k, MRR, nDCG, no-result accuracy, and p50/p95 latency are
  tracked by configuration;
- retrieval changes cannot merge without regression evidence;
- unrelated memories do not enter context solely because a corpus is small.

## Phase 3 — transactional local runtime

### Deliverables

- SQLite backend with migrations, indexes, transactions, and WAL policy;
- backend contract test suite shared by JSON and SQLite;
- workspace isolation and concurrent reader/writer tests;
- persisted embedding cache and invalidation strategy;
- asynchronous Pi bridge with timeout, cancellation, and output limits;
- structured local logs and health diagnostics.

### Acceptance criteria

- concurrent capture does not lose acknowledged writes;
- crash/restart and backup/restore tests pass;
- adapter latency and failure rates are observable;
- optional embedding failures degrade to lexical retrieval without blocking the
  agent.

## Phase 4 — secure multi-agent service

### Deliverables

- instantiable `MemoryEngine` replacing process-global state;
- versioned HTTP/gRPC or Unix-socket service and Python/TypeScript SDKs;
- tenant authentication/authorization and quotas;
- PostgreSQL/object storage/vector index options where justified;
- encryption at rest/in transit, secret/PII redaction, retention enforcement;
- append-only audit trail and deletion propagation;
- OpenTelemetry metrics/traces with content-safe defaults.

### Acceptance criteria

- cross-tenant access tests fail closed;
- threat model and incident/recovery runbooks are documented;
- deletion SLA includes derived embeddings, caches, and backups;
- load tests establish supported corpus size, throughput, and p95 latency.

## Phase 5 — adaptive memory lifecycle

### Candidate work

- extraction candidates with confidence and user confirmation;
- consolidation of episodes into semantic knowledge;
- access-aware decay and archival;
- contradiction detection and temporal validity;
- feedback-driven reranking;
- memory citations and answer-grounding evaluation.

These features should remain gated until privacy, provenance, rollback, and
quality evaluation exist. Learned automation must not silently rewrite durable
user memory.

## Near-term implementation order

1. Add typed schema and migration tests.
2. Add inspection/deletion/export commands.
3. Introduce an instantiable engine configuration while keeping CLI wrappers.
4. Add retriever result metadata and negative-query benchmarks.
5. Implement hybrid fallback and latency metrics.
6. Add SQLite only after backend contract tests are stable.
7. Add a second adapter to validate framework neutrality.

## Suggested second adapter

Choose an integration with a small lifecycle surface, such as a generic Python
SDK callback or LangChain-compatible tool, rather than deeply coupling to
another framework. Its purpose is to test the adapter contract and expose Pi
assumptions in the core.

## Non-goals until measured need exists

- distributed vector infrastructure for a small local corpus;
- autonomous deletion without reversible review;
- claiming hallucination prevention from retrieval metrics;
- replacing deterministic lexical retrieval with an opaque model-only path;
- optimizing benchmark fixtures without a held-out set.
