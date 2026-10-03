import hashlib
import json
import logging
import re
import time
import threading
import uuid

from unibot_RAG.config import Settings
from unibot_RAG.ingestion.chunking import chunk_documents, token_count
from unibot_RAG.ingestion.loaders import load_documents
from unibot_RAG.providers import AIProvider
from unibot_RAG.redis_db.redis_client import RedisClient
from unibot_RAG.retrieval.ranking import Reranker, reciprocal_rank_fusion

logger = logging.getLogger(__name__)
ABSTENTION = (
    "I'm sorry, but I don't have enough information in my records to answer that."
)


class RAGService:
    def __init__(self, settings=None, *, store=None, ai=None):
        self.settings = settings or Settings()
        self.store = store if store is not None else RedisClient(self.settings)
        self._ai = ai
        self._ai_lock = threading.Lock()

    @property
    def ai(self):
        with self._ai_lock:
            if self._ai is None:
                self._ai = AIProvider(self.settings)
            return self._ai

    def ingest_bytes(self, filename, content, source_id):
        self.store.ensure_index()
        report = {
            "job_id": uuid.uuid4().hex,
            "status": "running",
            "stage": "parse",
            "chunk_count": 0,
            "started_at": time.time(),
            "warnings": [],
        }
        self.store.save_job(report)
        started = time.monotonic()
        try:
            revision = hashlib.sha256(
                content
                + json.dumps(
                    [filename, source_id, self.settings.ingestion_fingerprint()],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            expected = self.store.manifest(source_id)
            if expected and json.loads(expected)["revision"] == revision:
                report.update(
                    status="unchanged",
                    stage="complete",
                    chunk_count=len(json.loads(expected)["keys"]),
                )
            else:
                docs = load_documents(filename, content, source_id, self.settings)
                report["stage"] = "chunk"
                self.store.save_job(report)
                chunks = chunk_documents(
                    docs,
                    self.settings,
                    embed=self.ai.embed
                    if self.settings.chunk_strategy == "semantic"
                    else None,
                )
                report.update(stage="enrich", chunk_count=len(chunks))
                self.store.save_job(report)
                if self.settings.enrichment_enabled:
                    if len(chunks) > 32:
                        raise ValueError(
                            "AI enrichment is limited to 32 chunks per source"
                        )
                    for chunk in chunks:
                        try:
                            chunk.metadata["enrichment"] = self.ai.enrich(chunk.text)
                        except Exception:
                            if self.settings.enrichment_failure == "fail":
                                raise
                            report["warnings"].append("enrichment_skipped:" + chunk.id)
                report["stage"] = "embed"
                self.store.save_job(report)
                vectors = self.ai.embed([c.text for c in chunks])
                report["stage"] = "publish"
                self.store.save_job(report)
                self.store.publish(
                    source_id, revision, chunks, vectors, expected=expected
                )
                report.update(status="completed", stage="complete")
        except Exception as exc:
            report.update(
                status="failed",
                error=type(exc).__name__,
                elapsed_ms=round((time.monotonic() - started) * 1000, 2),
            )
            self.store.save_job(report)
            logger.warning(
                "ingestion_failed job_id=%s stage=%s error_type=%s",
                report["job_id"],
                report["stage"],
                type(exc).__name__,
            )
            raise
        finally:
            report["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
        self.store.save_job(report)
        logger.info(
            "ingestion job_id=%s status=%s chunks=%s elapsed_ms=%s",
            report["job_id"],
            report["status"],
            report["chunk_count"],
            report["elapsed_ms"],
        )
        return report

    def search(self, question, source_id=None):
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question) > 4000
        ):
            raise ValueError("Question must contain 1 to 4000 characters")
        if not re.search(r"\w", question):
            return []
        started = time.monotonic()
        self.store.ensure_index()
        dense, lexical = self.store.search(
            self.ai.embed([question])[0],
            question,
            self.settings.candidate_k,
            source_id,
            include_lexical=self.settings.retrieval_mode == "hybrid",
        )
        candidates = reciprocal_rank_fusion(
            dense,
            *([lexical] if self.settings.retrieval_mode == "hybrid" else []),
            limit=self.settings.candidate_k,
        )
        if self.settings.rerank_url:
            try:
                candidates = Reranker(self.settings).rerank(question, candidates)
            except Exception as exc:
                if self.settings.rerank_failure == "fail":
                    raise
                logger.warning("rerank_fallback error_type=%s", type(exc).__name__)
        result = [p.model_dump() for p in candidates[: self.settings.top_k]]
        logger.info(
            "retrieval count=%s elapsed_ms=%.2f",
            len(result),
            (time.monotonic() - started) * 1000,
        )
        return result

    def answer(self, question):
        from unibot_RAG.domain import Passage

        candidates = [Passage.model_validate(p) for p in self.search(question)]
        evidence = []
        for p in candidates:
            cost = token_count(
                json.dumps(
                    [{"id": item.id, "text": item.text} for item in evidence + [p]],
                    ensure_ascii=False,
                )
            )
            if cost <= self.settings.context_tokens:
                evidence.append(p)
        fallback = {
            "status": "no_knowledge",
            "answer": ABSTENTION,
            "sources": [],
            "metadata": {},
            "source_document": "",
        }
        if not evidence:
            return fallback
        answer = self.ai.answer(question, evidence)
        ids = set(answer["source_ids"])
        if (
            not answer["supported"]
            or not answer["answer"].strip()
            or not ids
            or not ids <= {p.id for p in evidence}
        ):
            return fallback
        cited = [p for p in evidence if p.id in ids]
        return {
            "status": "success",
            "answer": answer["answer"],
            "sources": [p.model_dump() for p in cited],
            "metadata": cited[0].metadata,
            "source_document": cited[0].text,
        }

    def close(self):
        self.store.close()
        if self._ai is not None:
            self._ai.close()
