import os
import uuid
import pytest
from unibot_RAG.config import Settings
from unibot_RAG.domain import Passage, IngestionConflict
from unibot_RAG.redis_db.redis_client import RedisClient

pytestmark = pytest.mark.integration


@pytest.fixture
def store():
    url = os.getenv("TEST_REDIS_URL")
    if not url:
        pytest.skip("Set TEST_REDIS_URL to a disposable Redis Search instance")
    settings = Settings(
        redis_url=url,
        redis_index_name="test_" + uuid.uuid4().hex + "_v2",
        embedding_dimensions=3,
    )
    store = RedisClient(settings)
    store.ensure_index()
    yield store
    store.redis.ft(store.index).dropindex(delete_documents=True)
    keys = list(store.redis.scan_iter(match=store.prefix + "*"))
    if keys:
        store.redis.delete(*keys)
    store.close()


def passage(text="Bolt SKU123 costs 12", source="s", id="a"):
    return Passage(id=id, text=text, source_id=source, metadata={"record": 1})


def test_publish_read_replace_and_idempotence(store):
    p = passage()
    store.publish("s", "r1", [p], [[1, 0, 0]], expected=None)
    before = store.manifest("s")
    assert before and store.is_current("s", "r1")
    dense, lexical = store.search([1, 0, 0], "SKU123", 5, source_id="s")
    assert dense[0].text == p.text
    assert lexical[0].id == dense[0].id
    store.publish(
        "s", "r2", [passage("New stock SKU999", id="b")], [[0, 1, 0]], expected=before
    )
    assert not store.search([1, 0, 0], "SKU123", 5)[1]
    assert store.search([0, 1, 0], "SKU999", 5)[1][0].text == "New stock SKU999"


def test_conflicting_writer_cannot_replace_active_revision(store):
    store.publish("s", "r1", [passage()], [[1, 0, 0]], expected=None)
    with pytest.raises(IngestionConflict):
        store.publish("s", "r2", [passage("wrong", id="b")], [[0, 1, 0]], expected=None)
    assert store.is_current("s", "r1")


def test_invalid_vectors_leave_previous_revision(store):
    store.publish("s", "r1", [passage()], [[1, 0, 0]], expected=None)
    with pytest.raises(ValueError):
        store.publish(
            "s", "r2", [passage()], [[float("nan"), 0]], expected=store.manifest("s")
        )
    assert store.is_current("s", "r1")


def test_filters_and_query_syntax(store):
    store.publish("a", "r1", [passage(source="a")], [[1, 0, 0]], expected=None)
    store.publish("b", "r1", [passage(source="b", id="b")], [[1, 0, 0]], expected=None)
    dense, lexical = store.search([1, 0, 0], "SKU123", 5, source_id="a")
    assert all(p.source_id == "a" for p in dense + lexical)
    assert store.search([1, 0, 0], "* | @active:{1}", 5, source_id="missing") == (
        [],
        [],
    )


def test_schema_dimension_change_rejected(store):
    settings = store.settings.model_copy(update={"embedding_dimensions": 5})
    other = RedisClient(settings)
    try:
        with pytest.raises(ValueError):
            other.ensure_index()
    finally:
        other.close()


def test_real_pipeline_repeat_and_failed_update(store):
    from unibot_RAG.service import RAGService

    class AI:
        fail = False
        calls = 0

        def embed(self, texts):
            self.calls += 1
            if self.fail:
                raise RuntimeError("Private upstream details")
            return [[1, 0, 0] for _ in texts]

        def close(self):
            pass

    ai = AI()
    service = RAGService(store.settings, store=store, ai=ai)
    first = service.ingest_bytes(
        "faq.csv", b"Question,Answer,Context,uuid\nPrice?,Twelve,SKU123,a1", "faq"
    )
    repeat = service.ingest_bytes(
        "faq.csv", b"Question,Answer,Context,uuid\nPrice?,Twelve,SKU123,a1", "faq"
    )
    assert first["chunk_count"] == 1 and repeat["status"] == "unchanged"
    assert repeat["chunk_count"] == 1
    assert ai.calls == 1
    assert int(store.redis.ft(store.index).info()["num_docs"]) == 1
    ai.fail = True
    with pytest.raises(RuntimeError):
        service.ingest_bytes(
            "faq.csv", b"Question,Answer,Context,uuid\nPrice?,Wrong,SKU123,a1", "faq"
        )
    assert "Twelve" in store.search([1, 0, 0], "SKU123", 5)[0][0].text
    jobs = [
        store.get_job(k.decode().rsplit(":", 1)[1])
        for k in store.redis.scan_iter(match=store.prefix + "job:*")
    ]
    assert any(j["status"] == "failed" for j in jobs)
    assert "Private" not in str(jobs)


def test_two_simultaneous_writers_one_wins(store):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)

    def publish(revision):
        expected = store.manifest("s")
        barrier.wait()
        try:
            store.publish(
                "s", revision, [passage(revision)], [[1, 0, 0]], expected=expected
            )
            return "ok"
        except IngestionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, ["r1", "r2"]))
    assert sorted(results) == ["conflict", "ok"]
    assert len(store.search([1, 0, 0], "r1 r2", 10)[0]) == 1


def test_dense_mode_skips_lexical_results(store):
    store.publish("s", "r1", [passage()], [[1, 0, 0]], expected=None)
    dense, lexical = store.search([1, 0, 0], "SKU123", 5, include_lexical=False)
    assert len(dense) == 1 and lexical == []
