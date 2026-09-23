"""Explicit remote sources. Website connections pin a validated public IP."""

import ipaddress
from contextlib import closing
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit

import urllib3
from unibot_RAG.ingestion.loaders import SUPPORTED


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
    parsed, ip = website_target(url, settings)
    # Connect to the checked IP, retaining the original hostname for TLS/SNI and Host.
    pool = urllib3.HTTPSConnectionPool(
        ip,
        port=443,
        server_hostname=parsed.hostname,
        assert_hostname=parsed.hostname,
        maxsize=1,
        timeout=urllib3.Timeout(total=settings.request_timeout),
        retries=False,
    )
    response = None
    started = time.monotonic()
    try:
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
        media = response.headers.get("Content-Type", "").split(";")[0]
        if media not in {"text/html", "text/plain", "application/xhtml+xml"}:
            raise ValueError("Unsupported website content type")
        chunks, size = [], 0
        for chunk in response.stream(65536, decode_content=True):
            size += len(chunk)
            if (
                size > settings.max_input_bytes
                or time.monotonic() - started > settings.request_timeout
            ):
                raise ValueError("Website exceeded byte/time limit")
            chunks.append(chunk)
        return b"".join(chunks)
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
