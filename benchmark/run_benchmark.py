#!/usr/bin/env python3
"""Evaluate retrieval quality on a labeled JSONL dataset.

The runner captures the corpus in an isolated temporary store, retrieves the
top-k results for every query, and reports Recall@k, MRR, and nDCG@k.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load_jsonl(path: Path) -> list[dict]:
    """Load non-empty JSON Lines records from ``path``."""
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def dcg(gains: list[float]) -> float:
    """Calculate discounted cumulative gain for an ordered gain list."""
    return sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))


def ndcg_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    """Calculate binary normalized discounted cumulative gain at ``k``."""
    gains = [1.0 if item_id in relevant else 0.0 for item_id in ranked_ids[:k]]
    ideal = [1.0] * min(len(relevant), k)
    ideal_dcg = dcg(ideal)
    return dcg(gains) / ideal_dcg if ideal_dcg else 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5, help="number of results to evaluate")
    parser.add_argument("--per-query", action="store_true", help="print every ranked list")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable summary")
    parser.add_argument("--corpus", default="corpus.jsonl", help="corpus path or file name")
    parser.add_argument("--queries", default="queries.jsonl", help="query path or file name")
    return parser.parse_args()


def resolve_dataset(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else HERE / path


def main() -> None:
    args = parse_args()
    if args.k <= 0:
        raise SystemExit("--k must be greater than zero")

    corpus_path = resolve_dataset(args.corpus)
    queries_path = resolve_dataset(args.queries)
    corpus = load_jsonl(corpus_path)
    queries = load_jsonl(queries_path)

    descriptor, temporary_path = tempfile.mkstemp(suffix=".json")
    os.close(descriptor)
    try:
        os.environ["AGENT_MEMORY_PATH"] = temporary_path
        sys.path.insert(0, str(ROOT))
        from agent_memory_engine.service import capture, make_observation, retrieve, set_memory_path

        set_memory_path(temporary_path)
        for row in corpus:
            observation = make_observation(row["summary"], tags=row.get("tags", []))
            observation["id"] = row["id"]
            capture(observation)

        recalls: list[float] = []
        reciprocal_ranks: list[float] = []
        ndcgs: list[float] = []
        details: list[dict] = []

        for row in queries:
            relevant = set(row["relevant_ids"])
            ranked_ids = [item["id"] for item in retrieve(row["query"], args.k)]
            recall = len(set(ranked_ids) & relevant) / len(relevant) if relevant else 0.0
            reciprocal_rank = next(
                (1.0 / rank for rank, item_id in enumerate(ranked_ids, 1) if item_id in relevant),
                0.0,
            )
            normalized_dcg = ndcg_at_k(ranked_ids, relevant, args.k)
            recalls.append(recall)
            reciprocal_ranks.append(reciprocal_rank)
            ndcgs.append(normalized_dcg)
            details.append(
                {
                    "query": row["query"],
                    "ranked_ids": ranked_ids,
                    "relevant_ids": sorted(relevant),
                    "recall": recall,
                    "reciprocal_rank": reciprocal_rank,
                    "ndcg": normalized_dcg,
                }
            )

        def average(values: list[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        hybrid_enabled = (
            os.environ.get("AGENT_MEMORY_HYBRID") or os.environ.get("PI_MEMORY_HYBRID")
        ) == "1"
        engine = "hybrid" if hybrid_enabled else "bm25"
        summary = {
            "engine": engine,
            "corpus_size": len(corpus),
            "query_count": len(queries),
            "k": args.k,
            "recall": average(recalls),
            "mrr": average(reciprocal_ranks),
            "ndcg": average(ndcgs),
        }

        if args.json:
            payload = {**summary, "queries": details} if args.per_query else summary
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        print(f"Memory retrieval benchmark — {engine}, k={args.k}")
        print(f"Dataset: {len(corpus)} memories, {len(queries)} queries")
        if args.per_query:
            for detail in details:
                status = "PASS" if detail["recall"] else "MISS"
                print(f"\n[{status}] {detail['query']}")
                print(f"  retrieved: {detail['ranked_ids']}")
                print(f"  relevant:  {detail['relevant_ids']}")
        print(f"\nRecall@{args.k}: {summary['recall']:.3f}")
        print(f"MRR:      {summary['mrr']:.3f}")
        print(f"nDCG@{args.k}:  {summary['ndcg']:.3f}")
    finally:
        Path(temporary_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
