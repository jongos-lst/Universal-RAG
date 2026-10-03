"""Explicit remote sources. Website connections pin a validated public IP."""

import ipaddress
from contextlib import closing
from dataclasses import dataclass
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import urllib3
from unibot_RAG.ingestion.loaders import SUPPORTED


@dataclass(frozen=True)
class WebsiteContent:
    content: bytes
    media_type: str

    @property
    def filename(self):
        return "website.txt" if self.media_type == "text/plain" else "website.html"


# A system DNS resolver cannot be interrupted safely. Limit outstanding workers
# so stalled DNS (or cleanup) cannot create unbounded background threads.
_WEBSITE_WORKERS = threading.BoundedSemaphore(8)


class _WebsiteDeadline:
    def __init__(self, timeout):
        self.ends_at = time.monotonic() + timeout
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.sockets = []

    def remaining(self):
        remaining = self.ends_at - time.monotonic()
        if self.cancelled.is_set() or remaining <= 0:
            raise ValueError("Website exceeded byte/time limit")
        return remaining

    @staticmethod
    def shutdown(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # Already closed, or connect has not completed.

    def track(self, sock):
        with self.lock:
            self.sockets.append(sock)
            if self.cancelled.is_set():
                self.shutdown(sock)

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            for sock in self.sockets:
                self.shutdown(sock)


class _WebsiteConnection(urllib3.connection.HTTPSConnection):
    def __init__(self, *args, website_deadline, **kwargs):
        super().__init__(*args, **kwargs)
        self.website_deadline = website_deadline

    def connect(self):
        self.timeout = self.website_deadline.remaining()
        super().connect()
        # Keep the transport even when Connection: close transfers ownership to
        # the response's buffered reader. Closing that reader from another thread
        # can block on its read lock; socket shutdown interrupts the actual read.
        self.website_deadline.track(self.sock)
        self.website_deadline.remaining()


def website_target(url, settings):
    parsed = urlsplit(url)
    hosts = {h.strip().lower() for h in settings.website_hosts.split(",") if h.strip()}
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname.lower() not in hosts
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Website must use HTTPS and an explicitly allowed hostname")
    addresses = {
        item[4][0]
        for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    }
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("Website resolves to a non-public address")
    return parsed, sorted(addresses)[0]


def fetch_website(url, settings):
    deadline = _WebsiteDeadline(settings.request_timeout)
    if not _WEBSITE_WORKERS.acquire(timeout=deadline.remaining()):
        raise ValueError("Website exceeded byte/time limit")
    finished = threading.Event()
    outcome = {}

    def fetch():
        try:
            outcome["page"] = _fetch_website(url, settings, deadline)
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            _WEBSITE_WORKERS.release()
            finished.set()

    worker = threading.Thread(target=fetch, daemon=True, name="website-fetch")
    try:
        worker.start()
    except BaseException:
        _WEBSITE_WORKERS.release()
        raise
    try:
        if not finished.wait(deadline.remaining()):
            raise ValueError("Website exceeded byte/time limit")
        deadline.remaining()
        if "error" in outcome:
            raise outcome["error"]
        return outcome["page"]
    finally:
        # Never wait on response.close() or join a stuck resolver in the caller.
        # The worker owns cleanup; cancellation also prevents late DNS from
        # starting a connection after the caller's deadline.
        deadline.cancel()


def _fetch_website(url, settings, deadline):
    deadline.remaining()
    parsed, ip = website_target(url, settings)
    remaining = deadline.remaining()
    # Connect to the checked IP, retaining the original hostname for TLS/SNI and Host.
    pool = urllib3.HTTPSConnectionPool(
        ip,
        port=443,
        server_hostname=parsed.hostname,
        assert_hostname=parsed.hostname,
        maxsize=1,
        timeout=urllib3.Timeout(total=remaining),
        retries=False,
        website_deadline=deadline,
    )
    pool.ConnectionCls = _WebsiteConnection
    response = None
    try:
        deadline.remaining()
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        response = pool.urlopen(
            "GET",
            target,
            headers={"Host": parsed.hostname, "User-Agent": "UniversalRAG/2"},
            redirect=False,
            preload_content=False,
        )
        if response.status != 200:
            raise ValueError("Website failed or redirected; redirects are not followed")
        deadline.remaining()
        media = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if media not in {"text/html", "text/plain", "application/xhtml+xml"}:
            raise ValueError("Unsupported website content type")
        chunks, size = [], 0
        for chunk in response.stream(65536, decode_content=True):
            size += len(chunk)
            deadline.remaining()
            if size > settings.max_input_bytes:
                raise ValueError("Website exceeded byte/time limit")
            chunks.append(chunk)
        deadline.remaining()
        return WebsiteContent(b"".join(chunks), media)
    finally:
        if response is not None:
            response.close()
        pool.close()


def ingest_gcs(service):
    from google.cloud import storage

    settings = service.settings
    if not settings.gcs_bucket_name:
        raise ValueError("GCS_BUCKET_NAME is not configured")
    reports = []
    with closing(storage.Client()) as client:
        for number, blob in enumerate(
            client.list_blobs(
                settings.gcs_bucket_name,
                prefix=settings.gcs_prefix,
                max_results=settings.max_records + 1,
            ),
            1,
        ):
            if number > settings.max_records:
                raise ValueError("GCS source limit exceeded")
            if Path(blob.name).suffix.lower() not in SUPPORTED:
                continue
            if blob.size is None or blob.size > settings.max_input_bytes:
                raise ValueError("GCS object exceeds byte limit")
            content = blob.download_as_bytes(
                if_generation_match=blob.generation,
                timeout=settings.request_timeout,
                start=0,
                end=settings.max_input_bytes,
                retry=None,
            )
            reports.append(
                service.ingest_bytes(
                    blob.name, content, f"gs://{settings.gcs_bucket_name}/{blob.name}"
                )
            )
    return reports
