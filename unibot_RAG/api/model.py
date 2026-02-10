from typing import Literal

import openai
from pydantic import BaseModel

# fmt: off
from openai import (
    APIError,
    OpenAIError,
    ConflictError,
    NotFoundError,
    APIStatusError,
    RateLimitError,
    APITimeoutError,
    BadRequestError,
    APIConnectionError,
    AuthenticationError,
    InternalServerError,
    PermissionDeniedError,
    UnprocessableEntityError,
    APIResponseValidationError,
)
# fmt: on


class unibotRequest(BaseModel):
    question: str
    phone_number: str

OpenAIErrors = [
    APIError,
    OpenAIError,
    ConflictError,
    NotFoundError,
    APIStatusError,
    RateLimitError,
    APITimeoutError,
    BadRequestError,
    APIConnectionError,
    AuthenticationError,
    InternalServerError,
    PermissionDeniedError,
    UnprocessableEntityError,
    APIResponseValidationError,
]

OpenAIErrors = {error: error.__name__ for error in OpenAIErrors}

unibotResponseStatusType = Literal[
    "response_before_unibot",
    *map(lambda x: f"unibot_{x}", OpenAIErrors.values()),
    "unibot_unknown_error",
    "unibot_no_knowledge",
    "unibot_success",
]


unibotLogStatusType = tuple[
    unibotResponseStatusType,
]

unibotResponseStatusType = Literal["success", "no_knowledge", "busy_or_error"]


class unibotResponse(BaseModel):
    status: unibotResponseStatusType = "busy_or_error"
    answer: str = "Sorry, unibot doesn't have knowledge."
    id: str = ""
