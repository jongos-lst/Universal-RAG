"""Failure and resource boundaries using real parsers and fake external I/O."""

import copy
import io
import json
import socket
import zipfile

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from unibot_RAG.config import Settings
from unibot_RAG.domain import Passage
from unibot_RAG.ingestion.loaders import load_documents
from unibot_RAG.ingestion.sources import fetch_website, website_target
from unibot_RAG.service import RAGService


def pdf_bytes(*pages, encrypted=False):
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
                }
            )
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = stream
    if encrypted:
        writer.encrypt("test-only-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_extracts_text_and_preserves_original_page_numbers():
    docs = load_documents(
        "policy.pdf", pdf_bytes("", "Refunds within seven days"), "policy", Settings()
    )
    assert len(docs) == 1
    assert docs[0].text == "Refunds within seven days"
    assert docs[0].metadata["page"] == 2
    assert docs[0].metadata["format"] == "pdf"


def test_pdf_with_no_extractable_text_explicitly_requires_ocr():
    with pytest.raises(ValueError, match="OCR"):
        load_documents("scanned.pdf", pdf_bytes(""), "policy", Settings())


def test_pdf_page_limit_counts_blank_pages():
    with pytest.raises(ValueError, match="page limit"):
        load_documents(
            "policy.pdf", pdf_bytes("", "Text"), "policy", Settings(max_records=1)
        )


def test_encrypted_pdf_rejected_before_extraction():
    with pytest.raises(ValueError, match="Encrypted"):
        load_documents(
            "policy.pdf", pdf_bytes("Private", encrypted=True), "policy", Settings()
        )


def test_docx_expansion_is_checked_before_word_parser():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"x" * 30_000)
    content = output.getvalue()
    assert len(content) < 2000
    with pytest.raises(ValueError, match="expansion limit"):
        load_documents(
            "oversized.docx", content, "policy", Settings(max_input_bytes=2000)
        )


def test_byte_limit_counts_utf8_bytes_and_accepts_exact_limit():
    content = "政策".encode()
    assert load_documents(
        "policy.txt", content, "policy", Settings(max_input_bytes=len(content))
    )
    with pytest.raises(ValueError, match="byte limit"):
        load_documents(
            "policy.txt", content, "policy", Settings(max_input_bytes=len(content) - 1)
        )


@pytest.mark.parametrize("source_id", ["", " \t ", "x" * 1025])
def test_invalid_source_identity_rejected(source_id):
    with pytest.raises(ValueError, match="source_id"):
        load_documents("policy.txt", b"Policy", source_id, Settings())


@pytest.mark.parametrize(
    "filename,content",
    [
        ("data.csv", b"name\nfirst\nsecond"),
        ("data.json", b'[{"name":"first"},{"name":"second"}]'),
        ("data.jsonl", b'{"name":"first"}\n{"name":"second"}'),
    ],
)
def test_structured_record_limits_reject_entire_input(filename, content):
    with pytest.raises(ValueError):
        load_documents(filename, content, "records", Settings(max_records=1))


class WebsiteResponse:
    def __init__(self, *, status=200, chunks=(b"Policy",), media="text/html"):
        self.status = status
        self.headers = {"Content-Type": media, "Location": "https://private.example/"}
        self.chunks = chunks
        self.closed = False
        self.read = False

    def stream(self, amount, decode_content):
        self.read = True
        yield from self.chunks

    def close(self):
        self.closed = True


class WebsitePool:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False

    def urlopen(self, *args, **kwargs):
        self.requests.append((args, kwargs))
        return self.response

    def close(self):
        self.closed = True


def mock_website(monkeypatch, response):
    pool = WebsitePool(response)
    created = []
    dns_queries = []

    def dns(host, port, **kwargs):
        dns_queries.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    def connect(*args, **kwargs):
        created.append((args, kwargs))
        return pool

    monkeypatch.setattr("unibot_RAG.ingestion.sources.socket.getaddrinfo", dns)
    monkeypatch.setattr(
        "unibot_RAG.ingestion.sources.urllib3.HTTPSConnectionPool", connect
    )
    return pool, created, dns_queries


def test_website_connects_to_validated_ip_with_original_tls_and_host(monkeypatch):
    response = WebsiteResponse(
        chunks=(b"Hello ", b"world"), media="text/html; charset=utf-8"
    )
    pool, created, queries = mock_website(monkeypatch, response)
    assert (
        fetch_website(
            "https://example.com/policy?lang=zh", Settings(website_hosts="example.com")
        )
        == b"Hello world"
    )
    assert queries == [("example.com", 443)]
    assert created[0][0] == ("93.184.216.34",)
    assert created[0][1]["server_hostname"] == "example.com"
    assert created[0][1]["assert_hostname"] == "example.com"
    args, kwargs = pool.requests[0]
    assert args == ("GET", "/policy?lang=zh")
    assert kwargs["headers"]["Host"] == "example.com"
    assert kwargs["redirect"] is False
    assert kwargs["preload_content"] is False
    assert response.closed and pool.closed


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_website_redirect_is_never_followed_and_resources_close(monkeypatch, status):
    response = WebsiteResponse(status=status)
    pool, _, _ = mock_website(monkeypatch, response)
    with pytest.raises(ValueError, match="redirect"):
        fetch_website("https://example.com", Settings(website_hosts="example.com"))
    assert len(pool.requests) == 1
    assert not response.read
    assert response.closed and pool.closed


def test_website_oversized_stream_aborts_and_closes(monkeypatch):
    response = WebsiteResponse(chunks=(b"1234", b"5678"))
    pool, _, _ = mock_website(monkeypatch, response)
    with pytest.raises(ValueError, match="byte/time limit"):
        fetch_website(
            "https://example.com",
            Settings(website_hosts="example.com", max_input_bytes=6),
        )
    assert response.closed and pool.closed


def test_website_total_deadline_is_enforced_during_stream(monkeypatch):
    response = WebsiteResponse()
    pool, _, _ = mock_website(monkeypatch, response)
    times = iter([10.0, 12.0])
    monkeypatch.setattr(
        "unibot_RAG.ingestion.sources.time.monotonic", lambda: next(times)
    )
    with pytest.raises(ValueError, match="byte/time limit"):
        fetch_website(
            "https://example.com",
            Settings(website_hosts="example.com", request_timeout=1),
        )
    assert response.closed and pool.closed


def test_website_rejects_mixed_public_private_dns_answers(monkeypatch):
    monkeypatch.setattr(
        "unibot_RAG.ingestion.sources.socket.getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
            for ip in ["93.184.216.34", "169.254.169.254"]
        ],
    )
    with pytest.raises(ValueError, match="non-public"):
        website_target("https://example.com", Settings(website_hosts="example.com"))


class MemoryStore:
    def __init__(self):
        self.jobs = []
        self.published = []
        self.passages = [
            Passage(id="evidence", source_id="policy", text="Refunds within seven days")
        ]

    def ensure_index(self):
        pass

    def manifest(self, source_id):
        return None

    def save_job(self, report):
        self.jobs.append(copy.deepcopy(report))

    def publish(self, source_id, revision, chunks, vectors, *, expected):
        self.published.append((source_id, chunks, vectors))

    def search(self, vector, question, k, source_id=None, *, include_lexical=True):
        return self.passages, self.passages


class EnrichmentAI:
    def __init__(self, fail=False):
        self.fail = fail
        self.embedded = []

    def enrich(self, text):
        if self.fail:
            raise RuntimeError("private-enrichment-provider-detail")
        return json.dumps(
            {"title": "Refund policy", "summary": "Seven days", "keywords": ["refund"]}
        )

    def embed(self, texts):
        self.embedded.extend(texts)
        return [[1.0, 0.0] for text in texts]


def test_enrichment_fail_policy_prevents_publish_and_embedding():
    store, ai = MemoryStore(), EnrichmentAI(fail=True)
    service = RAGService(
        Settings(enrichment_enabled=True, enrichment_failure="fail"), store=store, ai=ai
    )
    with pytest.raises(RuntimeError):
        service.ingest_bytes("policy.txt", b"Refunds within seven days", "policy")
    assert not store.published and not ai.embedded
    assert store.jobs[-1]["status"] == "failed"
    assert store.jobs[-1]["stage"] == "enrich"
    assert "private-enrichment" not in json.dumps(store.jobs)


def test_enrichment_skip_policy_reports_warning_and_keeps_evidence():
    store, ai = MemoryStore(), EnrichmentAI(fail=True)
    service = RAGService(
        Settings(enrichment_enabled=True, enrichment_failure="skip"), store=store, ai=ai
    )
    report = service.ingest_bytes("policy.txt", b"Refunds within seven days", "policy")
    assert report["status"] == "completed"
    chunk = store.published[0][1][0]
    assert chunk.text == "Refunds within seven days"
    assert "enrichment" not in chunk.metadata
    assert report["warnings"] == ["enrichment_skipped:" + chunk.id]
    assert ai.embedded == [chunk.text]


def test_successful_enrichment_keeps_original_text_as_embedding_and_evidence():
    store, ai = MemoryStore(), EnrichmentAI()
    service = RAGService(Settings(enrichment_enabled=True), store=store, ai=ai)
    service.ingest_bytes("policy.txt", b"Refunds within seven days", "policy")
    chunk = store.published[0][1][0]
    assert chunk.text == "Refunds within seven days"
    assert json.loads(chunk.metadata["enrichment"])["title"] == "Refund policy"
    assert ai.embedded == [chunk.text]


@pytest.mark.parametrize("policy", ["fail", "fallback"])
def test_reranker_timeout_obeys_configured_policy_and_reports_fallback(
    monkeypatch, caplog, policy
):
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("private-reranker-token")

    monkeypatch.setattr(httpx.Client, "post", timeout)
    store = MemoryStore()
    service = RAGService(
        Settings(rerank_url="https://rerank.example/v2/rerank", rerank_failure=policy),
        store=store,
        ai=EnrichmentAI(),
    )
    if policy == "fail":
        with pytest.raises(httpx.ReadTimeout):
            service.search("Refund deadline?")
    else:
        results = service.search("Refund deadline?")
        assert results[0]["id"] == "evidence"
        assert results[0]["text"] == store.passages[0].text
        assert "rerank_fallback" in caplog.text
    assert "private-reranker-token" not in caplog.text
