import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import Response
from unibot_RAG.api.faq_langchain import unibot_FAQ
from unibot_RAG.api.model import unibotRequest, unibotResponse, OpenAIErrors
from unibot_RAG.redis.redis_client import RedisClient
from unibot_RAG.redis.utils import ingest_data_from_gcs
from unibot_RAG.api.utils import parse_log_status

logger = logging.getLogger("uvicorn")

# Ingest data from GCS into Redis
ingest_data_from_gcs()


app = FastAPI(
    title=os.getenv("PROJECT_NAME"),
    openapi_url=os.getenv("API_PATH") + "/openapi.json",
    docs_url=os.getenv("API_PATH") + "/docs",
)

@app.post("/unibot/v1/users/get-unibot-response/")
async def get_unibot_response(request: unibotRequest) -> unibotResponse:
    response = unibotResponse()
    logger.info(f"User query: {request.question}")

    # * Call unibot
    unibot_RAG_status = "response_before_unibot_RAG"

    try:
        logger.info("Calling unibot")
        unibot_redis_client = RedisClient.from_os_env()
        vector_store = unibot_redis_client.vectorstore
        unibot_RAG = unibot_FAQ(vector_store)

        reply = unibot_RAG.get_response(request.question)
        logger.info(f"Original unibot response: {reply}")

        if reply["answer"] == "Sorry, unibot doesn't have knowledge.":
            # If unibot is confused, set status to "unibot_RAG_no_knowledge"
            unibot_RAG_status = "unibot_RAG_no_knowledge"
        else:
            # Reply normally, set status to "unibot_RAG_success"
            unibot_RAG_status = "unibot_RAG_success"
            response.answer = reply["answer"]
            response.service = reply["service"]
    except Exception as e:
        logger.error("unibot failed")
        logger.error(e)
        unibot_RAG_status = f"unibot_RAG_{OpenAIErrors.get(type(e), 'unknown_error')}"
    is_unibot_RAG_failed = unibot_RAG_status != "unibot_RAG_success"
    logger.info(f"unibot status: {unibot_RAG_status}")

    # Send qa pair to collection api to retrieve id
    return response


@app.put("/unibot/admin/ingest-data")
def ingest_data():
    try:
        ingest_data_from_gcs()
    except Exception as e:
        return Response(status_code=500, content=str(e))
    return Response(status_code=200, content="ok")


@app.get("/unibot/health_check")
def health_check() -> Response:
    return Response(status_code=200, content="ok")
