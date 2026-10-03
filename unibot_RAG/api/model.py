from typing import Literal
from pydantic import BaseModel, Field, field_validator


class unibotRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    phone_number: str | None = None

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value


class SearchRequest(unibotRequest):
    source_id: str | None = Field(default=None, min_length=1, max_length=1024)


class IngestRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    source_id: str = Field(min_length=1, max_length=1024)
    content: str = Field(min_length=1, max_length=5_000_000)


class URLRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class unibotResponse(BaseModel):
    status: Literal["success", "no_knowledge", "busy_or_error"]
    answer: str
    sources: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    source_document: str = ""
