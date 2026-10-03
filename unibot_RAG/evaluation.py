"""Ranking evaluation. Fixture embeddings test plumbing, not model quality."""

import argparse
import json
import math
import os
import re
import time
import uuid
from pathlib import Path

from unibot_RAG.config import Settings
from unibot_RAG.service import RAGService


class FixtureEmbeddings:
    """Transparent synthetic semantic dimensions; no network or secret needed."""

    groups = [
        r"sku123|bolt|cost|price|stock",
        r"return|refund|money back",
        r"shipping|delivery|parcel|arrive",
        r"support|email",
        r"退貨|收據|七天",
        r"discount",
    ]

    def embed(self, texts):
        vectors = []
        for text in texts:
            values = [
                float(bool(re.search(group, text.lower()))) for group in self.groups
            ] + [0.1]
            vectors.append(values)
        return vectors

    def close(self):
        pass


def metrics(ranked, relevant, k):
    ranked = list(dict.fromkeys(ranked))[:k]
    relevant = set(relevant)
    if not relevant:
        return None  # Retrieval must return candidates; abstention is evaluated separately.
    hits = [i + 1 for i, source in enumerate(ranked) if source in relevant]
    dcg = sum(1 / math.log2(rank + 1) for rank in hits)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
    return {
        "recall": len(hits) / len(relevant),
        "mrr": 1 / hits[0] if hits else 0,
        "ndcg": dcg / ideal,
    }


def evaluate(service, dataset):
    outcomes = []
    for item in dataset["questions"]:
        started = time.monotonic()
        sources = service.search(item["question"])
        result = metrics(
            [p["source_id"] for p in sources],
            item["relevant_sources"],
            service.settings.top_k,
        )
        outcomes.append(
            {
                "question": item["question"],
                "metrics": result,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            }
        )
    measured = [r["metrics"] for r in outcomes if r["metrics"] is not None]
    return {
        "aggregate": {
            name: round(sum(m[name] for m in measured) / len(measured), 4)
            if measured
            else None
            for name in ["recall", "mrr", "ndcg"]
        },
        "questions": outcomes,
        "unanswerable_count": sum(r["metrics"] is None for r in outcomes),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset", type=Path, default=Path("tests/fixtures/evaluation.json")
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Read configured index using real providers; may incur cost",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text())
    if args.live:
        service = RAGService()
    else:
        if not os.getenv("TEST_REDIS_URL"):
            parser.error(
                "Fixture mode requires TEST_REDIS_URL pointing at disposable Redis Search"
            )
        settings = Settings(
            redis_url=os.environ["TEST_REDIS_URL"],
            redis_index_name="eval_" + uuid.uuid4().hex + "_v2",
            embedding_dimensions=7,
            embedding_model="synthetic-fixture",
            top_k=3,
        )
        service = RAGService(settings, ai=FixtureEmbeddings())
    report = {
        "mode": "live" if args.live else "synthetic-fixture",
        "answer_quality": "Not measured; run representative grounded-answer evaluation separately",
        "provider_cost": "Not measured" if args.live else 0,
        "ablations": {},
    }
    try:
        if not args.live:
            for doc in dataset["documents"]:
                service.ingest_bytes(
                    doc["source_id"] + ".txt", doc["text"].encode(), doc["source_id"]
                )
        configured_reranker = service.settings.rerank_url
        service.settings.rerank_url = None
        for mode in ["dense", "hybrid"]:
            service.settings.retrieval_mode = mode
            report["ablations"][mode] = evaluate(service, dataset)
        if configured_reranker:
            service.settings.rerank_url = configured_reranker
            report["ablations"]["hybrid_reranked"] = evaluate(service, dataset)
        text = json.dumps(report, indent=2, ensure_ascii=False)
        if args.output:
            args.output.write_text(text + "\n")
        print(text)
    finally:
        if not args.live:
            service.store.redis.ft(service.store.index).dropindex(delete_documents=True)
            keys = list(service.store.redis.scan_iter(match=service.store.prefix + "*"))
            if keys:
                service.store.redis.delete(*keys)
        service.close()


if __name__ == "__main__":
    main()
