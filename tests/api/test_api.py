"""HTTP contract regressions; provider work is isolated behind a small fake."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from unibot_RAG.api import main
from unibot_RAG.api.main import create_app


ANSWER_PATH = "/unibot/v1/users/get-unibot-response/"
INGEST_PATH = "/unibot/admin/ingest-data"
PRIVATE_ERROR = "private-provider-key=never-return-this"
SOURCE = {"chunk_id": "chunk-1", "source_id": "handbook", "text": "退款期限為七天。"}


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.error: Exception | None = None
        self.answer_result = {
            "status": "success",
            "answer": "退款期限為七天。",
            "sources": [SOURCE],
            "metadata": {"retrieval_mode": "hybrid"},
            "source_document": "退款期限為七天。",
        }

    def answer(self, question: str) -> dict[str, Any]:
        self.calls.append(("answer", question))
        if self.error:
            raise self.error
        return self.answer_result

    def search(
        self, question: str, source_id: str | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append(("search", question, source_id))
        if self.error:
            raise self.error
        return [SOURCE]

    def ingest_bytes(
        self, filename: str, content: bytes, source_id: str
    ) -> dict[str, Any]:
        self.calls.append(("ingest", filename, content, source_id))
        if self.error:
            raise self.error
        return {"job_id": "job-1", "status": "published", "chunk_count": 1}


@pytest.fixture
def service() -> FakeService:
    return FakeService()


@pytest.fixture
def client(service: FakeService) -> Iterator[TestClient]:
    with TestClient(
        create_app(service=service, admin_token="test-admin")
    ) as test_client:
        yield test_client


def test_health_and_startup_do_not_trigger_ingestion_or_provider_work(
    client: TestClient, service: FakeService
) -> None:
    response = client.get("/unibot/health_check")
    assert response.status_code == 200
    assert service.calls == []


def test_default_app_defers_service_creation_until_a_provider_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_initialization(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Health checks and application startup must not create providers")

    monkeypatch.setattr(main, "RAGService", unexpected_initialization)
    with TestClient(create_app()) as test_client:
        assert test_client.get("/unibot/health_check").status_code == 200


@pytest.mark.parametrize("legacy_fields", [{}, {"phone_number": "legacy-client"}])
def test_answer_accepts_optional_legacy_phone_and_preserves_citations(
    client: TestClient, service: FakeService, legacy_fields: dict[str, str]
) -> None:
    response = client.post(
        ANSWER_PATH, json={"question": "退款期限？", **legacy_fields}
    )
    assert response.status_code == 200
    assert response.json() == service.answer_result
    assert service.calls == [("answer", "退款期限？")]


def test_no_knowledge_is_a_successful_explicit_response(
    client: TestClient, service: FakeService
) -> None:
    service.answer_result = {
        "status": "no_knowledge",
        "answer": "No supporting evidence was found.",
        "sources": [],
        "metadata": {},
        "source_document": "",
    }
    response = client.post(ANSWER_PATH, json={"question": "Unknown fact?"})
    assert response.status_code == 200
    assert response.json() == service.answer_result


@pytest.mark.parametrize("question", [None, "", "   ", "x" * 4001])
@pytest.mark.parametrize("path", [ANSWER_PATH, "/v1/search"])
def test_invalid_question_never_reaches_provider(
    client: TestClient, service: FakeService, path: str, question: Any
) -> None:
    response = client.post(path, json={"question": question})
    assert response.status_code == 422
    assert service.calls == []


def test_maximum_length_question_is_accepted(client: TestClient) -> None:
    response = client.post(ANSWER_PATH, json={"question": "x" * 4000})
    assert response.status_code == 200


@pytest.mark.parametrize("path", [ANSWER_PATH, "/v1/search"])
@pytest.mark.parametrize(
    "error,status",
    [(ValueError(PRIVATE_ERROR), 422), (RuntimeError(PRIVATE_ERROR), 503)],
)
def test_query_failures_have_safe_http_errors(
    client: TestClient, service: FakeService, path: str, error: Exception, status: int
) -> None:
    service.error = error
    response = client.post(path, json={"question": "What is the policy?"})
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str)
    assert PRIVATE_ERROR not in response.text


@pytest.mark.parametrize("source_id", [None, "handbook"])
def test_search_preserves_optional_source_filter(
    client: TestClient, service: FakeService, source_id: str | None
) -> None:
    payload = {"question": "退款期限？"}
    if source_id is not None:
        payload["source_id"] = source_id
    response = client.post("/v1/search", json=payload)
    assert response.status_code == 200
    assert response.json() == {"sources": [SOURCE]}
    assert service.calls == [("search", "退款期限？", source_id)]


@pytest.mark.parametrize(
    "authorization", [None, "Bearer wrong-token", "Basic test-admin"]
)
def test_ingestion_requires_admin_bearer_token(
    client: TestClient, service: FakeService, authorization: str | None
) -> None:
    headers = {"Authorization": authorization} if authorization else {}
    response = client.put(
        INGEST_PATH,
        headers=headers,
        json={"filename": "policy.txt", "content": "policy", "source_id": "handbook"},
    )
    assert response.status_code in {401, 403}
    assert service.calls == []


def test_unconfigured_admin_endpoint_rejects_requests(
    service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    with TestClient(create_app(service=service, admin_token=None)) as test_client:
        response = test_client.put(
            INGEST_PATH,
            headers={"Authorization": "Bearer test-admin"},
            json={
                "filename": "policy.txt",
                "content": "policy",
                "source_id": "handbook",
            },
        )
    assert response.status_code in {401, 403, 503}
    assert service.calls == []


def test_authorized_ingestion_encodes_unicode_and_returns_actual_job_counts(
    client: TestClient, service: FakeService
) -> None:
    response = client.put(
        INGEST_PATH,
        headers={"Authorization": "Bearer test-admin"},
        json={
            "filename": "policy.txt",
            "content": "退款期限為七天。",
            "source_id": "handbook",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "job_id": "job-1",
        "status": "published",
        "chunk_count": 1,
    }
    assert service.calls == [
        ("ingest", "policy.txt", "退款期限為七天。".encode(), "handbook")
    ]


@pytest.mark.parametrize(
    "error,status",
    [(ValueError(PRIVATE_ERROR), 422), (RuntimeError(PRIVATE_ERROR), 503)],
)
def test_ingestion_failure_does_not_expose_provider_details(
    client: TestClient, service: FakeService, error: Exception, status: int
) -> None:
    service.error = error
    response = client.put(
        INGEST_PATH,
        headers={"Authorization": "Bearer test-admin"},
        json={"filename": "policy.txt", "content": "policy", "source_id": "handbook"},
    )
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str)
    assert PRIVATE_ERROR not in response.text


def test_upload_preserves_bytes_and_source_id(client, service):
    response = client.post(
        "/v1/admin/upload",
        headers={"Authorization": "Bearer test-admin"},
        data={"source_id": "handbook"},
        files={"file": ("guide.txt", b"Guide content", "text/plain")},
    )
    assert response.status_code == 200
    assert service.calls == [("ingest", "guide.txt", b"Guide content", "handbook")]


def test_upload_limit_rejects_before_ingestion(client, service):
    response = client.post(
        "/v1/admin/upload",
        headers={"Authorization": "Bearer test-admin"},
        data={"source_id": "handbook"},
        files={"file": ("guide.txt", b"x" * 5_000_001)},
    )
    assert response.status_code == 413
    assert service.calls == []


def test_missing_job_is_404(client, service):
    from types import SimpleNamespace

    service.store = SimpleNamespace(get_job=lambda job: None)
    response = client.get(
        "/v1/admin/jobs/missing", headers={"Authorization": "Bearer test-admin"}
    )
    assert response.status_code == 404


def test_sql_unconfigured_is_safe_unavailable(client):
    response = client.post("/v1/sql/propose", json={"question": "Total sales?"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Service temporarily unavailable"
