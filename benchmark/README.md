# Agent Memory Engine retrieval benchmark

This directory contains two labeled datasets for measuring retrieval quality.
The compact dataset is useful for quick iteration; the larger dataset adds
same-topic distractors and multilingual records to stress semantic retrieval.

| Dataset | Corpus | Queries | Size |
| --- | --- | --- | --- |
| Compact | `corpus.jsonl` | `queries.jsonl` | 30 memories / 21 queries |
| Extended | `corpus_large.jsonl` | `queries_large.jsonl` | 100 memories / 40 queries |

The non-English records are intentional evaluation fixtures. They test whether
the multilingual embedding model can match a query and a memory across language
boundaries; all project-facing documentation and program output remain English.

## Run the evaluation

```bash
# Deterministic lexical baseline
python benchmark/run_benchmark.py --k 5 --per-query

# Larger dataset
python benchmark/run_benchmark.py \
  --corpus corpus_large.jsonl \
  --queries queries_large.jsonl \
  --k 5

# Optional semantic + lexical retrieval
AGENT_MEMORY_HYBRID=1 python benchmark/run_benchmark.py --k 5

# Machine-readable output for experiment tracking
python benchmark/run_benchmark.py --json
```

The runner reports three complementary metrics:

- **Recall@k** measures how many labeled memories were retrieved.
- **MRR** rewards placing the first relevant result near the top.
- **nDCG@k** evaluates the quality of the complete top-k ranking.

Each run uses a temporary JSON store and removes it afterward, so benchmarking
never changes the user's real memory file.

## Evaluation roadmap

The current benchmark measures retrieval only. Before treating the engine as a
mature service, extend it with held-out and adversarial sets containing
no-relevant-result queries, stale/conflicting facts, tenant/workspace isolation,
paraphrases, multilingual queries, and same-topic distractors. Track
Precision@k, no-result accuracy, p50/p95 latency, indexing throughput, context
precision, and end-to-end answer grounding in addition to the current metrics.

Every retriever, fusion, reranking, embedding-model, or lifecycle-policy change
should record its configuration and compare against the deterministic BM25
baseline. Production claims must not be inferred from the checked-in fixtures.
