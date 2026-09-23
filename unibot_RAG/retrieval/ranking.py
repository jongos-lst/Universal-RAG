import math
import httpx
from unibot_RAG.domain import Passage


def reciprocal_rank_fusion(*rankings: list[Passage], limit: int = 5) -> list[Passage]:
    scores, passages = {}, {}
    for ranking in rankings:
        seen = set()
        for rank, passage in enumerate(ranking, 1):
            if passage.id in seen:
                continue
            seen.add(passage.id)
            passages[passage.id] = passage
            scores[passage.id] = scores.get(passage.id, 0) + 1 / (60 + rank)
    return [
        passages[id].model_copy(update={"score": scores[id]})
        for id in sorted(scores, key=lambda id: (-scores[id], id))[:limit]
    ]


class Reranker:
    """Cohere v2-compatible bounded cross-encoder service."""

    def __init__(self, settings):
        self.settings = settings

    @staticmethod
    def validate(passages, payload):
        results = payload.get("results")
        if not isinstance(results, list) or len(results) != len(passages):
            raise ValueError("Incomplete reranker result")
        seen, ranked = set(), []
        for item in results:
            index, score = item.get("index"), item.get("relevance_score")
            if (
                type(index) is not int
                or not 0 <= index < len(passages)
                or index in seen
                or type(score) not in (int, float)
                or not math.isfinite(score)
            ):
                raise ValueError("Invalid reranker result")
            seen.add(index)
            ranked.append(passages[index].model_copy(update={"score": float(score)}))
        return sorted(ranked, key=lambda p: (-p.score, p.id))

    def rerank(self, question, passages):
        if not passages:
            return []
        headers = {}
        if self.settings.rerank_api_key:
            headers["Authorization"] = (
                "Bearer " + self.settings.rerank_api_key.get_secret_value()
            )
        with httpx.Client(
            timeout=self.settings.request_timeout, follow_redirects=False
        ) as client:
            response = client.post(
                self.settings.rerank_url,
                headers=headers,
                json={
                    "model": self.settings.rerank_model,
                    "query": question,
                    "documents": [p.text for p in passages],
                    "top_n": len(passages),
                },
            )
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                raise ValueError("Reranker response too large")
            return self.validate(passages, response.json())
