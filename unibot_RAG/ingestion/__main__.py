"""Explicit ingestion command with bounded retries for transient dependencies."""

import argparse
import json
import time
from pathlib import Path

import httpx
import openai
from redis.exceptions import ConnectionError as RedisConnectionError
from unibot_RAG.domain import IngestionConflict
from unibot_RAG.ingestion.sources import fetch_website, ingest_gcs
from unibot_RAG.service import RAGService


def main():
    parser = argparse.ArgumentParser()
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--file", type=Path)
    sources.add_argument("--url")
    sources.add_argument("--gcs", action="store_true")
    parser.add_argument("--source-id")
    parser.add_argument("--attempts", type=int, choices=[1, 2, 3], default=1)
    args = parser.parse_args()
    service = RAGService()
    try:
        for attempt in range(args.attempts):
            try:
                if args.file:
                    with args.file.open("rb") as stream:
                        content = stream.read(service.settings.max_input_bytes + 1)
                    result = service.ingest_bytes(
                        args.file.name,
                        content,
                        args.source_id or args.file.resolve().as_uri(),
                    )
                elif args.url:
                    page = fetch_website(args.url, service.settings)
                    result = service.ingest_bytes(
                        page.filename,
                        page.content,
                        args.source_id or args.url,
                    )
                else:
                    result = ingest_gcs(service)
                print(json.dumps(result, ensure_ascii=False))
                return
            except (
                httpx.TransportError,
                openai.APIConnectionError,
                openai.RateLimitError,
                RedisConnectionError,
                IngestionConflict,
            ):
                if attempt + 1 == args.attempts:
                    raise
                time.sleep(0.5 * 2**attempt)
    finally:
        service.close()


if __name__ == "__main__":
    main()
