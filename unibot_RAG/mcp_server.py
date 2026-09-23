"""Local stdio MCP adapter. No write tools or arbitrary command execution."""

from contextlib import asynccontextmanager
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from unibot_RAG.service import RAGService


def create_server(service=None):
    holder = {"service": service}

    def get_service():
        if holder["service"] is None:
            holder["service"] = RAGService()
        return holder["service"]

    @asynccontextmanager
    async def lifespan(server):
        yield {}
        if service is None and holder["service"] is not None:
            holder["service"].close()

    mcp = FastMCP("Universal RAG", lifespan=lifespan)

    @mcp.tool()
    def search_knowledge(
        question: Annotated[str, Field(min_length=1, max_length=4000)],
        source_id: Annotated[str | None, Field(max_length=1024)] = None,
    ) -> dict:
        """Retrieve cited knowledge passages without generating an answer."""
        try:
            return {"sources": get_service().search(question, source_id)}
        except Exception:
            raise RuntimeError("Knowledge retrieval unavailable") from None

    @mcp.tool()
    def answer_question(
        question: Annotated[str, Field(min_length=1, max_length=4000)],
    ) -> dict:
        """Answer using retrieved evidence, or explicitly abstain."""
        try:
            return get_service().answer(question)
        except Exception:
            raise RuntimeError("Answer service unavailable") from None

    @mcp.tool()
    async def propose_sql(
        question: Annotated[str, Field(min_length=1, max_length=4000)],
    ) -> dict:
        """Generate a Wren-validated SQL proposal. Never executes SQL."""
        from unibot_RAG.integrations.wren import propose_sql as wren_propose

        try:
            svc = get_service()
            return await wren_propose(question, svc.settings, svc.ai)
        except Exception:
            raise RuntimeError("SQL proposal unavailable") from None

    return mcp


if __name__ == "__main__":
    create_server().run(transport="stdio")
