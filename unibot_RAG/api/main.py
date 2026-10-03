"""HTTP adapter; import/startup never ingests documents or opens provider clients."""

import logging
import secrets
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from unibot_RAG.api.model import (
    IngestRequest,
    SearchRequest,
    URLRequest,
    unibotRequest,
    unibotResponse,
)
from unibot_RAG.config import Settings
from unibot_RAG.domain import IngestionConflict
from unibot_RAG.service import RAGService

logger = logging.getLogger(__name__)


def create_app(service=None, admin_token=None):
    settings = Settings()
    token = admin_token or (
        settings.admin_token.get_secret_value() if settings.admin_token else None
    )
    holder = {"service": service}
    lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        if service is None and holder["service"] is not None:
            holder["service"].close()

    app = FastAPI(title="Universal RAG", lifespan=lifespan)

    def get_service():
        with lock:
            if holder["service"] is None:
                holder["service"] = RAGService(settings)
        return holder["service"]

    def require_admin(authorization: str | None = Header(default=None)):
        if (
            not token
            or not authorization
            or not secrets.compare_digest(
                authorization.encode(), ("Bearer " + token).encode()
            )
        ):
            raise HTTPException(
                status_code=403, detail="Administrator authorization required"
            )

    def call(operation):
        try:
            return operation()
        except IngestionConflict:
            raise HTTPException(
                status_code=409, detail="Knowledge changed; retry request"
            ) from None
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Input or provider response is invalid"
            ) from None
        except Exception as exc:
            logger.warning("request_failed error_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=503, detail="Service temporarily unavailable"
            ) from None

    @app.get("/unibot/health_check")
    def health_check():
        return {"status": "ok"}

    @app.post("/unibot/v1/users/get-unibot-response/", response_model=unibotResponse)
    def answer(request: unibotRequest):
        return call(lambda: get_service().answer(request.question))

    @app.post("/v1/search")
    def search(request: SearchRequest):
        return {
            "sources": call(
                lambda: get_service().search(
                    request.question, source_id=request.source_id
                )
            )
        }

    @app.put("/unibot/admin/ingest-data", dependencies=[Depends(require_admin)])
    def ingest(request: IngestRequest):
        return call(
            lambda: get_service().ingest_bytes(
                request.filename, request.content.encode(), request.source_id
            )
        )

    @app.post("/v1/admin/upload", dependencies=[Depends(require_admin)])
    def upload(
        file: UploadFile = File(), source_id: str = Form(min_length=1, max_length=1024)
    ):
        try:
            content = file.file.read(settings.max_input_bytes + 1)
            if len(content) > settings.max_input_bytes:
                raise HTTPException(status_code=413, detail="Input byte limit exceeded")
            return call(
                lambda: get_service().ingest_bytes(
                    file.filename or "", content, source_id
                )
            )
        finally:
            file.file.close()

    @app.post("/v1/admin/website", dependencies=[Depends(require_admin)])
    def website(request: URLRequest):
        from unibot_RAG.ingestion.sources import fetch_website

        def ingest_website():
            page = fetch_website(request.url, settings)
            return get_service().ingest_bytes(page.filename, page.content, request.url)

        return call(ingest_website)

    @app.get("/v1/admin/jobs/{job_id}", dependencies=[Depends(require_admin)])
    def job(job_id: str):
        report = call(lambda: get_service().store.get_job(job_id))
        if report is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return report

    @app.post("/v1/sql/propose")
    def sql(request: unibotRequest):
        import asyncio
        from unibot_RAG.integrations.wren import propose_sql

        return call(
            lambda: asyncio.run(
                propose_sql(request.question, settings, get_service().ai)
            )
        )

    return app


app = create_app()
