"""Website media survives adapters; slow peers cannot extend the total deadline."""

import io
import socket
import sys
import threading
import time

import pytest
import urllib3
from fastapi.testclient import TestClient

from unibot_RAG.api.main import create_app
from unibot_RAG.config import Settings
from unibot_RAG.ingestion import __main__ as cli
from unibot_RAG.ingestion.loaders import load_documents
from unibot_RAG.ingestion.sources import fetch_website
from unibot_RAG.utils.data_proc import extract_website_content


URL = "https://example.com/instructions.html"


class LoaderService:
    def __init__(self):
        self.settings = Settings(website_hosts="example.com")
        self.documents = []
        self.closed = False

    def ingest_bytes(self, filename, content, source_id):
        self.documents.extend(
            load_documents(filename, content, source_id, self.settings)
        )
        return {"status": "completed"}

    def close(self):
        self.closed = True


def public_dns(monkeypatch):
    monkeypatch.setattr(
        "unibot_RAG.ingestion.sources.socket.getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


def served_page(monkeypatch, media, content):
    public_dns(monkeypatch)
    response = urllib3.response.HTTPResponse(
        body=io.BytesIO(content),
        status=200,
        headers={"Content-Type": media},
        preload_content=False,
    )

    class Pool:
        def urlopen(self, *args, **kwargs):
            return response

        def close(self):
            pass

    monkeypatch.setattr(
        "unibot_RAG.ingestion.sources.urllib3.HTTPSConnectionPool",
        lambda *args, **kwargs: Pool(),
    )


@pytest.mark.parametrize("adapter", ["api", "cli", "legacy"])
@pytest.mark.parametrize(
    "media,content,expected,format_name",
    [
        (
            "text/plain; charset=utf-8",
            b"Set <token> and <endpoint> exactly.",
            "Set <token> and <endpoint> exactly.",
            "txt",
        ),
        (
            " Text/Plain ; charset=UTF-8",
            b"Set <token> and <endpoint> exactly.",
            "Set <token> and <endpoint> exactly.",
            "txt",
        ),
        (
            "text/html",
            b"<p>Set &lt;token&gt; exactly.</p><script>hidden()</script>",
            "Set <token> exactly.",
            "html",
        ),
        (
            "application/xhtml+xml",
            b"<p>Set &lt;token&gt; exactly.</p>",
            "Set <token> exactly.",
            "html",
        ),
    ],
)
def test_website_media_selects_loader_through_every_adapter(
    monkeypatch, capsys, adapter, media, content, expected, format_name
):
    served_page(monkeypatch, media, content)
    monkeypatch.setenv("WEBSITE_HOSTS", "example.com")
    service = LoaderService()
    if adapter == "api":
        with TestClient(
            create_app(service=service, admin_token="test-admin")
        ) as client:
            result = client.post(
                "/v1/admin/website",
                headers={"Authorization": "Bearer test-admin"},
                json={"url": URL},
            )
        assert result.status_code == 200
    elif adapter == "cli":
        monkeypatch.setattr(cli, "RAGService", lambda: service)
        monkeypatch.setattr(
            sys, "argv", ["ingest", "--url", URL, "--source-id", "manual"]
        )
        cli.main()
        assert service.closed
        assert "completed" in capsys.readouterr().out
    else:
        assert extract_website_content(URL) == expected
        return
    assert len(service.documents) == 1
    assert service.documents[0].text == expected
    assert service.documents[0].metadata["format"] == format_name
    assert service.documents[0].source_id == ("manual" if adapter == "cli" else URL)


@pytest.mark.parametrize("phase", ["body", "headers"])
def test_trickling_http_peer_cannot_extend_total_deadline(monkeypatch, phase):
    """Use real urllib3/http.client buffering, replacing only the TLS transport."""
    public_dns(monkeypatch)
    gate = threading.BoundedSemaphore(1)
    monkeypatch.setattr("unibot_RAG.ingestion.sources._WEBSITE_WORKERS", gate)
    sockets = []
    server_finished = threading.Event()

    def connect(connection):
        client, peer = socket.socketpair()
        client.settimeout(connection.timeout)
        connection.sock = client
        connection.is_verified = True
        sockets.append(client)

        def serve():
            try:
                with peer:
                    request = b""
                    while b"\r\n\r\n" not in request:
                        request += peer.recv(4096)
                    headers = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 20\r\nConnection: close\r\n\r\n"
                    if phase == "headers":
                        for byte in headers[:20]:
                            peer.sendall(bytes([byte]))
                            time.sleep(0.025)
                        peer.sendall(headers[20:] + b"x" * 20)
                    else:
                        peer.sendall(headers)
                        for _ in range(20):
                            peer.sendall(b"x")
                            time.sleep(0.025)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                server_finished.set()

        threading.Thread(target=serve, daemon=True).start()

    monkeypatch.setattr(urllib3.connection.HTTPSConnection, "connect", connect)
    started = time.monotonic()
    with pytest.raises(ValueError, match="byte/time limit"):
        fetch_website(URL, Settings(website_hosts="example.com", request_timeout=0.12))
    elapsed = time.monotonic() - started
    assert elapsed < 0.35, f"A 0.12s deadline took {elapsed:.3f}s"
    assert server_finished.wait(0.35), "Timed-out peer was left connected"
    assert gate.acquire(timeout=0.35), "Timed-out worker did not finish cleanup"
    gate.release()
    assert all(sock.fileno() == -1 for sock in sockets)


def test_deadline_includes_dns_and_does_not_connect_after_cancellation(monkeypatch):
    resolver_finished = threading.Event()
    connected = []

    def resolve(*args, **kwargs):
        time.sleep(0.5)
        resolver_finished.set()
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr("unibot_RAG.ingestion.sources.socket.getaddrinfo", resolve)

    class Pool:
        def urlopen(self, *args, **kwargs):
            connected.append(True)
            return urllib3.response.HTTPResponse(
                body=io.BytesIO(b"text"),
                status=200,
                headers={"Content-Type": "text/plain"},
                preload_content=False,
            )

        def close(self):
            pass

    monkeypatch.setattr(
        "unibot_RAG.ingestion.sources.urllib3.HTTPSConnectionPool",
        lambda *a, **kw: Pool(),
    )
    started = time.monotonic()
    with pytest.raises(ValueError, match="byte/time limit"):
        fetch_website(URL, Settings(website_hosts="example.com", request_timeout=0.12))
    assert time.monotonic() - started < 0.35
    assert resolver_finished.wait(1)
    assert connected == []


def test_deadline_does_not_wait_for_blocked_cleanup(monkeypatch):
    public_dns(monkeypatch)
    cleanup_started = threading.Event()
    cleanup_finished = threading.Event()

    class Pool:
        def urlopen(self, *args, **kwargs):
            return urllib3.response.HTTPResponse(
                body=io.BytesIO(b"text"),
                status=200,
                headers={"Content-Type": "text/plain"},
                preload_content=False,
            )

        def close(self):
            cleanup_started.set()
            time.sleep(0.5)
            cleanup_finished.set()

    monkeypatch.setattr(
        "unibot_RAG.ingestion.sources.urllib3.HTTPSConnectionPool",
        lambda *a, **kw: Pool(),
    )
    started = time.monotonic()
    with pytest.raises(ValueError, match="byte/time limit"):
        fetch_website(URL, Settings(website_hosts="example.com", request_timeout=0.12))
    assert time.monotonic() - started < 0.35
    assert cleanup_started.is_set()
    assert cleanup_finished.wait(1)


def test_stalled_dns_has_bounded_workers_and_no_late_network_requests(monkeypatch):
    from unibot_RAG.ingestion import sources

    release_dns = threading.Event()
    resolved = threading.Event()
    calls = []
    connected = []
    gate = threading.BoundedSemaphore(2)
    monkeypatch.setattr(sources, "_WEBSITE_WORKERS", gate)

    def resolve(*args, **kwargs):
        calls.append(True)
        release_dns.wait(2)
        if len(calls) == 2:
            resolved.set()
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(sources.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        sources.urllib3, "HTTPSConnectionPool", lambda *a, **kw: connected.append(True)
    )
    try:
        for _ in range(3):
            with pytest.raises(ValueError, match="byte/time limit"):
                fetch_website(
                    URL, Settings(website_hosts="example.com", request_timeout=0.05)
                )
        assert len(calls) == 2
        assert connected == []
    finally:
        release_dns.set()
    assert resolved.wait(1)
    # Acquiring both slots proves both cancelled resolver workers have finished.
    assert gate.acquire(timeout=1)
    assert gate.acquire(timeout=1)
    gate.release()
    gate.release()
    assert connected == []
