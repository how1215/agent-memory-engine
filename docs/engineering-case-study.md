# Agent Memory Engine engineering case study

## Problem

A coding agent's context window is temporary. Once a session ends, durable facts
such as package-manager choices, test commands, deployment conventions, and user
preferences disappear. Repeating that context wastes time and makes the agent's
behavior inconsistent between sessions.

Agent Memory Engine begins with a local-first solution containing four explicit stages:

1. **Capture** a concise observation through an agent tool.
2. **Store** it in an inspectable, persistent format.
3. **Retrieve** the observations most relevant to a new prompt.
4. **Inject** only what fits within a controlled context budget.

## Design priorities

The current implementation optimizes for a single developer running a local
agent. The priorities are predictable behavior, zero required services, easy
debugging, and graceful failure. The package itself is framework-neutral; Pi is
the first adapter under `adapters/pi/`.

The deterministic path contains tokenization, BM25 scoring, deduplication,
persistence, result ordering, and prompt-budget enforcement. The optional model
path contributes only semantic similarity. This boundary means the system still
works when a model is unavailable, while the baseline remains straightforward
to test and explain.

## Persistence model

Each observation records an ID, session ID, millisecond timestamp, source tool,
summary, and tags. The ID is the SHA-256 digest of the summary, making repeated
captures idempotent. JSON was chosen over a database because the intended data
volume is small and direct inspection is valuable during local development.

Writes use a temporary file followed by `os.replace`. This prevents an
interrupted write from leaving a partially serialized memory file. Missing,
malformed, or incorrectly shaped stores load as empty so memory cannot prevent
the coding agent from starting.

This design does not provide multi-process locking. The engine now exposes a
`MemoryStore` protocol and `set_store()` seam, but JSON is still the only shipped
backend. A production version would use SQLite or another transactional store
once concurrent writers or a large corpus become measured requirements.

## Retrieval design

### Lexical baseline

The default retriever implements Okapi BM25:

```text
score(q, d) = Σ IDF(qᵢ) × tf(qᵢ, d) × (k₁ + 1)
                         / (tf(qᵢ, d) + k₁ × (1 − b + b × |d| / avgdl))
```

with `k1=1.5` and `b=0.75`. A regular-expression tokenizer extracts lowercase
alphanumeric terms and individual CJK characters. This keeps the default engine
dependency-free and supports exact multilingual matches, although it does not
perform stemming or full word segmentation.

### Semantic extension

BM25 cannot recover a memory when the prompt and stored fact share no terms.
Examples include a category-to-product relationship such as “payment provider”
versus “Stripe,” synonyms such as “picture” versus “image,” and cross-language
queries.

Hybrid mode encodes the query and observations with a local multilingual
sentence-transformers model, then combines cosine similarity with normalized
BM25 scores. The model is imported and loaded lazily, so users of the baseline
do not install or initialize the heavier ML stack.

An alpha sweep over `{0.3, 0.4, 0.5, 0.6, 0.7}` favored `0.3` on both included
datasets. In these fixtures, conversational questions and terse engineering
facts often use different vocabulary, so semantic similarity carries more
signal than exact term overlap.

## Evaluation methodology

The benchmark uses fixed JSONL corpora and labeled relevant IDs. Each run creates
an isolated temporary store, captures every corpus item through the public API,
executes retrieval for each query, and computes three metrics:

- **Recall@5** measures whether all labeled memories appear in the visible set.
- **MRR** emphasizes the rank of the first relevant memory.
- **nDCG@5** evaluates relevance throughout the ordered result list.

| Dataset | Retriever | Recall@5 | MRR | nDCG@5 |
| --- | --- | ---: | ---: | ---: |
| Compact: 30 / 21 | BM25 | 0.810 | 0.810 | 0.802 |
| Compact: 30 / 21 | Hybrid | **1.000** | **0.914** | **0.936** |
| Extended: 100 / 40 | BM25 | 0.838 | 0.826 | 0.795 |
| Extended: 100 / 40 | Hybrid | **0.938** | **0.943** | **0.910** |

The extended dataset deliberately contains more same-topic distractors and
multilingual records. Hybrid retrieval improved Recall@5 by 10 percentage points
and MRR by 11.7 percentage points on that set. These measurements demonstrate
behavior on the checked-in fixtures; they should not be generalized as a
production quality claim.

## Error analysis

The remaining difficult cases expose a limitation of compact embedding models:
they may recognize synonymy and cross-language similarity without reliably
connecting an abstract category to a specific vendor or tool. “Package manager”
to “pnpm” and “payment provider” to “Stripe” are examples.

Potential next steps include query expansion, a stronger embedding model,
reciprocal-rank fusion instead of raw score interpolation, or a learned reranker.
Any change should be evaluated against a larger held-out dataset to avoid tuning
to the included examples.

## Context-budget trade-off

When an adapter requests context construction, the default injection budget is
2,000 approximate tokens. The Pi adapter makes retrieval opt-in with the
`@memory` prefix, avoiding retrieval and new context on unmarked requests. A
larger budget raises the chance of including useful facts but consumes context, increases inference
latency, and can distract the model. A smaller budget protects the active task
but may omit supporting memories.

Token count is estimated as `characters / 4` to keep the core dependency-free.
That heuristic is intentionally simple and can be inaccurate for CJK text or a
specific model tokenizer. An integration serving a known model should replace it
with that model's tokenizer and select the budget as a fraction of the available
context window.

## Memory versus conversation compaction

Conversation compaction and persistent memory solve different lifecycle
problems. Compaction compresses history inside one long session. This project
selects durable facts across separate sessions. They are complementary: a
high-signal session summary can become a memory, while retrieval can seed a new
session without restoring the entire old conversation.

## Security and production considerations

The store may contain user preferences, project details, or other sensitive
information. The current local prototype does not encrypt or classify records.
Before production use, the design should add explicit retention controls,
redaction, encryption at rest, per-project isolation, prompt-injection defenses,
and user-visible deletion. Concurrent access would also require locking or a
transactional database.

## Evolution toward a general engine

The original prototype coupled package names, configuration, and file layout to
Pi. The current structure separates the framework-neutral
`agent_memory_engine/` package from `adapters/pi/`, uses generic
`AGENT_MEMORY_*` configuration, and defines a minimal storage protocol. Legacy
Pi command/configuration aliases remain temporarily for migration.

This separation is a foundation, not proof of production maturity. The next
architectural steps are typed/versioned records, an instantiable engine instead
of process globals, scoped repository queries, backend contract tests, explicit
retriever/reranker interfaces, and a second adapter that validates there are no
hidden Pi assumptions. Security, conflict resolution, lifecycle policy, and
observability must precede autonomous memory consolidation. See
[`architecture.md`](architecture.md) and [`roadmap.md`](roadmap.md).

## What this project demonstrates

- Designing a reliable boundary around an optional ML component
- Implementing and evaluating an information-retrieval pipeline
- Integrating Python and TypeScript through a small process interface
- Protecting local state with idempotency and atomic persistence
- Communicating benchmark results together with their limitations

