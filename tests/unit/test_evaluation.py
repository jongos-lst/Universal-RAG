import math
import pytest
from unibot_RAG.evaluation import metrics


def test_rank_metrics_with_missing_and_duplicate_sources():
    result = metrics(["x", "x", "a"], ["a", "b"], 3)
    assert result["recall"] == 0.5
    assert result["mrr"] == 0.5
    assert result["ndcg"] == pytest.approx((1 / math.log2(3)) / (1 + 1 / math.log2(3)))
    assert metrics(["a"], [], 3) is None
    assert metrics(["x"], ["a"], 3) == {"recall": 0, "mrr": 0, "ndcg": 0}


def test_unanswerable_only_dataset_reports_no_ranking_average():
    from types import SimpleNamespace
    from unibot_RAG.evaluation import evaluate

    service = SimpleNamespace(settings=SimpleNamespace(top_k=5), search=lambda q: [])
    report = evaluate(
        service, {"questions": [{"question": "Unknown?", "relevant_sources": []}]}
    )
    assert report["aggregate"] == {"recall": None, "mrr": None, "ndcg": None}
    assert report["unanswerable_count"] == 1
