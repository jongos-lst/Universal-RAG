"""Compatibility entrypoint for explicit GCS ingestion (never on import)."""

from unibot_RAG.ingestion.sources import ingest_gcs
from unibot_RAG.service import RAGService


def ingest_data_from_gcs():
    service = RAGService()
    try:
        return ingest_gcs(service)
    finally:
        service.close()
