"""Validated process configuration; constructing settings performs no network I/O."""

from typing import Literal
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    redis_url: SecretStr = SecretStr("redis://localhost:6379")
    redis_password: SecretStr | None = None
    redis_index_name: str = Field(default="unibot_v2", pattern=r"^[A-Za-z0-9_]+_v2$")
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    chat_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=2, le=8192)
    # None preserves compatibility: known text-embedding-3 models send the
    # optional API parameter; custom endpoints opt in only when supported.
    embedding_send_dimensions: bool | None = None
    embedding_batch_size: int = Field(default=32, ge=1, le=128)
    request_timeout: float = Field(default=30, gt=0, le=120)
    chunk_strategy: Literal["token", "recursive", "structure", "semantic"] = "structure"
    chunk_tokens: int = Field(default=400, ge=16, le=2000)
    chunk_overlap: int = Field(default=40, ge=0)
    semantic_threshold: float = Field(default=0.7, ge=-1, le=1)
    max_input_bytes: int = Field(default=5_000_000, ge=1, le=20_000_000)
    max_chunks: int = Field(default=1000, ge=1, le=5000)
    max_records: int = Field(default=1000, ge=1, le=5000)
    candidate_k: int = Field(default=20, ge=1, le=100)
    top_k: int = Field(default=5, ge=1, le=20)
    retrieval_mode: Literal["dense", "hybrid"] = "hybrid"
    context_tokens: int = Field(default=6000, ge=128, le=32000)
    enrichment_enabled: bool = False
    enrichment_failure: Literal["fail", "skip"] = "fail"
    rerank_url: str | None = None
    rerank_api_key: SecretStr | None = None
    rerank_model: str = "rerank-v3.5"
    rerank_failure: Literal["fail", "fallback"] = "fail"
    admin_token: SecretStr | None = None
    website_hosts: str = ""
    wren_home: str | None = None
    wren_project: str | None = None
    wren_command: str = "wren"
    wren_timeout: float = Field(default=30, gt=0, le=120)
    gcs_bucket_name: str | None = None
    gcs_prefix: str = ""

    @model_validator(mode="after")
    def check_limits(self):
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("chunk_overlap must be smaller than chunk_tokens")
        if self.top_k > self.candidate_k:
            raise ValueError("top_k must not exceed candidate_k")
        if self.embedding_model == "text-embedding-ada-002" and self.embedding_dimensions != 1536:
            raise ValueError("text-embedding-ada-002 requires 1536 embedding dimensions")
        return self

    def ingestion_fingerprint(self) -> dict:
        names = (
            "chunk_strategy",
            "chunk_tokens",
            "chunk_overlap",
            "semantic_threshold",
            "embedding_model",
            "embedding_dimensions",
            "embedding_send_dimensions",
            "openai_base_url",
            "enrichment_enabled",
            "enrichment_failure",
            "chat_model",
        )
        return {"pipeline_version": 2, **self.model_dump(include=set(names))}
