from typing import Any
from pydantic import BaseModel, Field


class Document(BaseModel):
    text: str
    source_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Passage(Document):
    id: str
    score: float = 0.0


class IngestionConflict(RuntimeError):
    """Another writer published this source while an ingestion was preparing."""
