"""Deterministic first-init interleavings without a running Redis server."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock, current_thread

import pytest
from redis.exceptions import ResponseError

from unibot_RAG.config import Settings
from unibot_RAG.redis_db.redis_client import RedisClient


class RacingRedis:
    def __init__(self):
        self.arrivals = Barrier(2)
        self.loser_observed = Event()
        self.lock = Lock()
        self.creator = None
        self.signature = None
        self.writers = []

    def ft(self, index):
        return self

    def info(self):
        self.arrivals.wait(timeout=2)
        raise ResponseError("Unknown Index name")

    def create_index(self, *args, **kwargs):
        with self.lock:
            if self.creator is not None:
                raise ResponseError("Index already exists")
            self.creator = current_thread().name
        # Let the losing creator reach signature handling before the winner.
        assert self.loser_observed.wait(timeout=2)

    def set(self, key, value, nx=False):
        with self.lock:
            self.writers.append(current_thread().name)
            if current_thread().name != self.creator:
                self.loser_observed.set()
            if nx and self.signature is not None:
                return False
            self.signature = value
            return True

    def get(self, key):
        if current_thread().name != self.creator:
            self.loser_observed.set()
        return self.signature


@pytest.mark.parametrize("different", [False, True])
def test_only_index_creator_publishes_schema_signature(different):
    redis = RacingRedis()

    def initialize(dimensions):
        store = RedisClient(Settings(embedding_dimensions=dimensions))
        original = store.redis
        store.redis = redis
        try:
            store.ensure_index()
            return current_thread().name, True
        except ValueError:
            return current_thread().name, False
        finally:
            original.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(initialize, [3, 5 if different else 3]))
    assert redis.writers == [redis.creator]
    assert results[redis.creator] is True
    assert sum(results.values()) == (1 if different else 2)


def test_existing_index_without_signature_is_not_adopted():
    store = RedisClient(Settings(request_timeout=0.02))
    original = store.redis

    class ExistingRedis:
        def ft(self, index):
            return self

        def info(self):
            return {}

        def get(self, key):
            return None

        def set(self, *args, **kwargs):
            pytest.fail("An existing unsigned index must not be adopted")

    store.redis = ExistingRedis()
    try:
        with pytest.raises(ValueError, match="schema|configuration"):
            store.ensure_index()
    finally:
        original.close()
