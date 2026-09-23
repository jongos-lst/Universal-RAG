import pytest
from unibot_RAG.domain import Passage
from unibot_RAG.retrieval.ranking import reciprocal_rank_fusion, Reranker


def p(id):
    return Passage(id=id, text=id, source_id="source")


def test_fusion_rewards_agreement_and_deduplicates():
    result = reciprocal_rank_fusion([p("a"), p("b"), p("b")], [p("b"), p("c")], limit=3)
    assert [x.id for x in result] == ["b", "a", "c"]
    assert result[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert reciprocal_rank_fusion([], [], limit=5) == []


def test_rerank_rejects_invented_indices():
    with pytest.raises(ValueError):
        Reranker.validate([p("a")], {"results": [{"index": 3, "relevance_score": 1.0}]})


def test_rerank_preserves_identity():
    result = Reranker.validate(
        [p("a"), p("b")],
        {
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.1},
            ]
        },
    )
    assert [x.id for x in result] == ["b", "a"]
