"""Redis Search storage with optimistic, atomic source revision publication."""

import hashlib
import json
import re

import numpy as np
import redis
from redis.commands.search.field import TagField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query
from redis.exceptions import ResponseError, WatchError

from unibot_RAG.config import Settings
from unibot_RAG.domain import IngestionConflict, Passage


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class RedisClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.index = settings.redis_index_name
        self.prefix = self.index + ":"
        self.redis = redis.Redis.from_url(
            settings.redis_url.get_secret_value(),
            password=settings.redis_password.get_secret_value()
            if settings.redis_password
            else None,
            socket_timeout=settings.request_timeout,
            socket_connect_timeout=5,
        )

    def ensure_index(self):
        signature = json.dumps(
            {
                "schema": 2,
                "dimensions": self.settings.embedding_dimensions,
                "model": self.settings.embedding_model,
                "provider": self.settings.openai_base_url,
            },
            sort_keys=True,
        ).encode()
        key = self.prefix + "schema"
        try:
            self.redis.ft(self.index).info()
        except ResponseError as exc:
            if (
                "unknown index" not in str(exc).lower()
                and "no such index" not in str(exc).lower()
            ):
                raise
            try:
                self.redis.ft(self.index).create_index(
                    [
                        TextField("text"),
                        TextField("enrichment"),
                        TagField("source"),
                        TagField("active"),
                        VectorField(
                            "vector",
                            "HNSW",
                            {
                                "TYPE": "FLOAT32",
                                "DIM": self.settings.embedding_dimensions,
                                "DISTANCE_METRIC": "COSINE",
                            },
                        ),
                    ],
                    definition=IndexDefinition(
                        prefix=[self.prefix + "chunk:"], index_type=IndexType.HASH
                    ),
                )
            except ResponseError as race:
                if "index already exists" not in str(race).lower():
                    raise
            self.redis.set(key, signature, nx=True)
        if self.redis.get(key) != signature:
            raise ValueError(
                "Index schema or embedding configuration differs; use a new versioned index"
            )

    def manifest(self, source_id: str) -> bytes | None:
        return self.redis.get(self.prefix + "source:" + digest(source_id))

    def is_current(self, source_id: str, revision: str) -> bool:
        manifest = self.manifest(source_id)
        return bool(manifest and json.loads(manifest)["revision"] == revision)

    def publish(
        self,
        source_id: str,
        revision: str,
        chunks: list[Passage],
        vectors: list,
        *,
        expected: bytes | None,
    ):
        array = np.asarray(vectors, dtype=np.float32)
        if (
            not chunks
            or len(chunks) > self.settings.max_chunks
            or array.shape != (len(chunks), self.settings.embedding_dimensions)
            or not np.isfinite(array).all()
            or np.any(np.linalg.norm(array, axis=1) == 0)
            or any(c.source_id != source_id for c in chunks)
        ):
            raise ValueError("Invalid chunk/vector batch")
        manifest_key = self.prefix + "source:" + digest(source_id)
        keys = [
            self.prefix + "chunk:" + digest(source_id) + ":" + revision + ":" + c.id
            for c in chunks
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate chunk identity")
        try:
            with self.redis.pipeline() as pipe:
                pipe.watch(manifest_key)
                if pipe.get(manifest_key) != expected:
                    raise IngestionConflict("Source changed; retry ingestion")
                previous = json.loads(expected)["keys"] if expected else []
                pipe.multi()
                for key in previous:
                    pipe.hset(key, "active", "0")
                for key, chunk, vector in zip(keys, chunks, array):
                    pipe.hset(
                        key,
                        mapping={
                            "text": chunk.text,
                            "source": digest(source_id),
                            "source_id": source_id,
                            "active": "1",
                            "id": chunk.id,
                            "metadata": json.dumps(chunk.metadata, ensure_ascii=False),
                            "enrichment": chunk.metadata.get("enrichment", ""),
                            "vector": vector.tobytes(),
                        },
                    )
                pipe.set(manifest_key, json.dumps({"revision": revision, "keys": keys}))
                pipe.incr(self.prefix + "epoch")
                pipe.execute()
        except WatchError as exc:
            raise IngestionConflict("Source changed; retry ingestion") from exc

    def search(
        self,
        vector: list,
        question: str,
        k: int,
        source_id: str | None = None,
        *,
        include_lexical=True,
    ):
        values = np.asarray(vector, dtype=np.float32)
        if (
            values.shape != (self.settings.embedding_dimensions,)
            or not np.isfinite(values).all()
            or not np.linalg.norm(values)
        ):
            raise ValueError("Invalid query embedding")
        if not 1 <= k <= 100:
            raise ValueError("Invalid candidate count")
        filters = "@active:{1}" + (
            f" @source:{{{digest(source_id)}}}" if source_id is not None else ""
        )
        # Keep only literal word tokens. User input cannot inject Redis query operators.
        terms = re.findall(r"[^\W_]+", question, flags=re.UNICODE)[:64]
        lexical_expr = "|".join(terms)
        fields = ("id", "text", "source_id", "metadata")
        for _ in range(3):
            epoch = self.redis.get(self.prefix + "epoch")
            dense = self.redis.ft(self.index).search(
                Query(f"({filters})=>[KNN {k} @vector $vec AS distance]")
                .sort_by("distance")
                .return_fields(*fields)
                .paging(0, k)
                .dialect(2),
                {"vec": values.tobytes()},
            )
            lexical = (
                self.redis.ft(self.index).search(
                    Query(f"({filters}) @text|enrichment:({lexical_expr})")
                    .scorer("BM25")
                    .return_fields(*fields)
                    .paging(0, k)
                    .dialect(2)
                )
                if terms and include_lexical
                else None
            )
            if epoch == self.redis.get(self.prefix + "epoch"):

                def convert(result):
                    return (
                        [
                            Passage(
                                id=d.id,
                                text=d.text,
                                source_id=d.source_id,
                                metadata=json.loads(d.metadata),
                            )
                            for d in result.docs
                        ]
                        if result
                        else []
                    )

                return convert(dense), convert(lexical)
        raise IngestionConflict("Knowledge changed during search; retry")

    def save_job(self, report: dict):
        self.redis.set(
            self.prefix + "job:" + report["job_id"], json.dumps(report), ex=604800
        )

    def get_job(self, job_id: str):
        raw = self.redis.get(self.prefix + "job:" + job_id)
        return json.loads(raw) if raw else None

    def close(self):
        self.redis.close()
