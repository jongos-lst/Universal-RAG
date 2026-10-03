"""Synthetic stdio servers for protocol tests; never contacts external providers."""

import sys
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from unibot_RAG.mcp_server import create_server


class FakeService:
    def search(
        self, question: str, source_id: str | None = None
    ) -> list[dict[str, Any]]:
        if question == "provider failure":
            raise RuntimeError("private-provider-token=secret")
        return [
            {
                "id": "chunk-1",
                "source_id": source_id or "handbook",
                "text": "退款期限為七天。",
                "metadata": {"record": 1},
            }
        ]

    def answer(self, question: str) -> dict[str, Any]:
        return {
            "status": "success",
            "answer": "退款期限為七天。[1]",
            "sources": self.search(question),
            "source_document": "退款期限為七天。",
            "metadata": {"retrieval_mode": "hybrid"},
        }


def wren_fixture(behavior: str) -> FastMCP:
    server = FastMCP("Synthetic Wren")

    @server.tool()
    async def get_mdl() -> Any:
        if behavior == "hang":
            import asyncio

            await asyncio.sleep(60)
        if behavior == "empty":
            return CallToolResult(content=[TextContent(type="text", text="")])
        if behavior == "error":
            raise RuntimeError("Synthetic Wren failure")
        if behavior == "error_payload":
            return {"success": False, "error": "Invalid semantic model"}
        return {
            "models": [
                {"name": "orders", "columns": [{"name": "amount", "type": "integer"}]}
            ]
        }

    @server.tool()
    def get_instructions() -> dict[str, str]:
        return {"instructions": "Use the semantic orders model."}

    @server.tool()
    def dry_plan(sql: str) -> dict[str, str]:
        return {"sql": sql, "plan": "SELECT SUM(amount) FROM orders"}

    @server.tool()
    def run_sql(sql: str) -> dict:
        raise AssertionError("SQL execution is forbidden in proposal mode")

    return server


if __name__ == "__main__":
    if sys.argv[1] == "rag":
        server = create_server(FakeService())
    elif sys.argv[1] == "wren":
        server = wren_fixture(sys.argv[2] if len(sys.argv) > 2 else "valid")
    else:
        raise ValueError("Unknown fixture mode")
    server.run(transport="stdio")
