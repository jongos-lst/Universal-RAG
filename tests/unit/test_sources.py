import pytest
from unibot_RAG.config import Settings
from unibot_RAG.ingestion.sources import website_target


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://localhost",
        "file:///etc/passwd",
        "https://example.com:444",
        "https://u:p@example.com",
    ],
)
def test_bad_website_targets(url):
    with pytest.raises(ValueError):
        website_target(url, Settings(website_hosts="example.com"))


def test_private_dns_rejected(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))]
    )
    with pytest.raises(ValueError):
        website_target("https://example.com", Settings(website_hosts="example.com"))


def test_connection_uses_checked_public_ip(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    parsed, ip = website_target(
        "https://example.com/path", Settings(website_hosts="example.com")
    )
    assert ip == "93.184.216.34" and parsed.hostname == "example.com"


def test_gcs_generation_bound_download_and_cleanup(monkeypatch):
    from types import SimpleNamespace
    from unibot_RAG.ingestion.sources import ingest_gcs

    observed = {}

    def download(**kwargs):
        observed["download"] = kwargs
        return b"data"

    blob = SimpleNamespace(
        name="guide.txt", size=4, generation=12, download_as_bytes=download
    )

    class Client:
        def list_blobs(self, bucket, **kwargs):
            observed["listing"] = (bucket, kwargs)
            return [blob]

        def close(self):
            observed["closed"] = True

    monkeypatch.setattr("google.cloud.storage.Client", Client)
    service = SimpleNamespace(
        settings=Settings(gcs_bucket_name="fixture-bucket"),
        ingest_bytes=lambda *args: args,
    )
    result = ingest_gcs(service)
    assert result == [("guide.txt", b"data", "gs://fixture-bucket/guide.txt")]
    assert observed["download"]["if_generation_match"] == 12
    assert observed["download"]["end"] == service.settings.max_input_bytes
    assert observed["download"]["retry"] is None
    assert observed["closed"]


def test_gcs_closes_on_failed_ingestion(monkeypatch):
    from types import SimpleNamespace
    from unibot_RAG.ingestion.sources import ingest_gcs

    closed = []

    class Client:
        def list_blobs(self, *args, **kwargs):
            return [SimpleNamespace(name="guide.txt", size=999999999)]

        def close(self):
            closed.append(True)

    monkeypatch.setattr("google.cloud.storage.Client", Client)
    with pytest.raises(ValueError, match="byte limit"):
        ingest_gcs(SimpleNamespace(settings=Settings(gcs_bucket_name="fixture-bucket")))
    assert closed == [True]
