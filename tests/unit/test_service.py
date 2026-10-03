import pytest
import json
from unibot_RAG.config import Settings
from unibot_RAG.service import RAGService


class Store:
    def __init__(self):
        self.current = None
        self.chunks = []
        self.jobs = {}

    def ensure_index(self):
        pass

    def manifest(self, source):
        return self.current

    def is_current(self, source, revision):
        return self.current == revision

    def publish(self, source, revision, chunks, vectors, *, expected):
        self.current, self.chunks = (
            json.dumps({"revision": revision, "keys": [c.id for c in chunks]}).encode(),
            chunks,
        )

    def save_job(self, report):
        self.jobs[report["job_id"]] = dict(report)

    def search(self, vector, question, k, source_id=None, *, include_lexical=True):
        return self.chunks, self.chunks

    def close(self):
        pass


class AI:
    calls = 0
    fail = False

    def embed(self, texts):
        self.calls += 1
        if self.fail:
            raise RuntimeError("upstream private detail")
        return [[1.0, 0.0, 0.0] for _ in texts]

    def answer(self, question, passages):
        return {
            "answer": "Bolt costs 12.",
            "supported": True,
            "source_ids": [passages[0].id],
        }

    def close(self):
        pass


def service(**kwargs):
    return RAGService(
        Settings(embedding_dimensions=3, **kwargs), store=Store(), ai=AI()
    )


def test_duplicate_ingestion_embeds_once():
    svc = service()
    a = svc.ingest_bytes("x.txt", b"Bolt costs 12.", "s")
    b = svc.ingest_bytes("x.txt", b"Bolt costs 12.", "s")
    assert a["status"] == "completed" and b["status"] == "unchanged"
    assert svc.ai.calls == 1
    assert a["chunk_count"] == 1


def test_failed_replacement_keeps_old_source_and_reports_job():
    svc = service()
    svc.ingest_bytes("x.txt", b"Old source.", "s")
    svc.ai.fail = True
    with pytest.raises(RuntimeError):
        svc.ingest_bytes("x.txt", b"New source.", "s")
    assert svc.store.chunks[0].text == "Old source."
    assert list(svc.store.jobs.values())[-1]["status"] == "failed"
    assert "private" not in str(svc.store.jobs)


def test_empty_retrieval_abstains_without_generation():
    svc = service()
    assert svc.answer("What is the price?")["status"] == "no_knowledge"


def test_answers_keep_citations():
    svc = service()
    svc.ingest_bytes("x.txt", b"Bolt costs 12.", "s")
    result = svc.answer("What is the price?")
    assert result["status"] == "success"
    assert result["sources"][0]["source_id"] == "s"
    assert result["source_document"] == "Bolt costs 12."


def test_hallucinated_citation_rejected():
    svc = service()
    svc.ingest_bytes("x.txt", b"Bolt costs 12.", "s")
    svc.ai.answer = lambda q, p: {
        "answer": "Invented",
        "supported": True,
        "source_ids": ["not-a-source"],
    }
    assert svc.answer("Price?")["status"] == "no_knowledge"


def test_dense_mode_disables_lexical_query():
    svc = service(retrieval_mode="dense")

    def search(*args, include_lexical):
        assert include_lexical is False
        return [], []

    svc.store.search = search
    assert svc.search("SKU123") == []


def test_blank_supported_answer_abstains():
    svc = service()
    svc.ingest_bytes("x.txt", b"Bolt costs 12.", "s")
    svc.ai.answer = lambda q, p: {
        "answer": " ",
        "supported": True,
        "source_ids": [p[0].id],
    }
    assert svc.answer("Price?")["status"] == "no_knowledge"
