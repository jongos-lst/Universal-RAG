"""Exercise actual MCP stdio handshakes, schema validation, and tool calls."""

import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from unibot_RAG.integrations.wren import allowed_call, propose_with_session, read_result


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mcp_fixture.py"


@asynccontextmanager
async def fixture_session(mode: str, behavior: str = "valid"):
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(FIXTURE), mode, behavior],
        cwd=str(REPO_ROOT),
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(REPO_ROOT)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=15)
        ) as session:
            await session.initialize()
            yield session


async def test_rag_discovers_only_bounded_read_tools():
    async with fixture_session("rag") as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        assert set(tools) == {"search_knowledge", "answer_question", "propose_sql"}
        for tool in tools.values():
            schema = tool.inputSchema
            assert "question" in schema["required"]
            assert schema["properties"]["question"]["minLength"] == 1
            assert schema["properties"]["question"]["maxLength"] == 4000
        source_schema = tools["search_knowledge"].inputSchema["properties"]["source_id"]
        assert any(choice.get("maxLength") == 1024 for choice in source_schema["anyOf"])


async def test_rag_search_preserves_citations_and_requested_source_filter():
    async with fixture_session("rag") as session:
        result = await session.call_tool(
            "search_knowledge", {"question": "退款期限？", "source_id": "policy-v2"}
        )
        payload = read_result(result)
        assert payload["sources"] == [
            {
                "id": "chunk-1",
                "source_id": "policy-v2",
                "text": "退款期限為七天。",
                "metadata": {"record": 1},
            }
        ]


async def test_rag_answer_returns_original_evidence_and_citation():
    async with fixture_session("rag") as session:
        payload = read_result(
            await session.call_tool("answer_question", {"question": "退款期限？"})
        )
        assert payload["status"] == "success"
        assert payload["answer"] == "退款期限為七天。[1]"
        assert payload["sources"][0]["text"] == payload["source_document"]
        assert payload["sources"][0]["source_id"] == "handbook"


@pytest.mark.parametrize(
    "tool,args",
    [
        ("answer_question", {}),
        ("answer_question", {"question": ""}),
        ("answer_question", {"question": "x" * 4001}),
        ("search_knowledge", {"question": "policy", "source_id": "x" * 1025}),
        ("propose_sql", {"question": 42}),
    ],
)
async def test_rag_rejects_invalid_tool_arguments(tool: str, args: dict[str, Any]):
    async with fixture_session("rag") as session:
        assert (await session.call_tool(tool, args)).isError


async def test_rag_provider_failure_does_not_expose_private_error():
    async with fixture_session("rag") as session:
        result = await session.call_tool(
            "search_knowledge", {"question": "provider failure"}
        )
        assert result.isError
        text = " ".join(part.text for part in result.content if part.type == "text")
        assert "private-provider-token" not in text
        assert "Knowledge retrieval unavailable" in text


class RecordingAI:
    def __init__(self):
        self.requests = []

    def propose_sql(self, question, context):
        self.requests.append((question, context))
        return "SELECT SUM(amount) FROM orders"


class RecordingSession:
    def __init__(self, session):
        self.session = session
        self.calls = []

    async def list_tools(self):
        return await self.session.list_tools()

    async def call_tool(self, name, arguments):
        self.calls.append(name)
        return await self.session.call_tool(name, arguments)


async def test_wren_proposal_uses_semantic_context_and_never_executes_sql():
    ai = RecordingAI()
    async with fixture_session("wren") as session:
        tracked = RecordingSession(session)
        result = await propose_with_session("Total order amount?", tracked, ai)
        assert result["status"] == "proposed"
        assert result["executed"] is False
        assert result["validation"] == "transpiled"
        assert result["sql"] == "SELECT SUM(amount) FROM orders"
        assert result["plan"]["sql"] == result["sql"]
        assert tracked.calls == ["get_mdl", "get_instructions", "dry_plan"]
        assert ai.requests == [
            (
                "Total order amount?",
                {
                    "mdl": {
                        "models": [
                            {
                                "name": "orders",
                                "columns": [{"name": "amount", "type": "integer"}],
                            }
                        ]
                    },
                    "instructions": {"instructions": "Use the semantic orders model."},
                },
            )
        ]
        with pytest.raises(ValueError, match="not permitted"):
            await allowed_call(tracked, "run_sql", {"sql": result["sql"]})
        assert "run_sql" not in tracked.calls


@pytest.mark.parametrize(
    "behavior,error",
    [("empty", ValueError), ("error", RuntimeError), ("error_payload", RuntimeError)],
)
async def test_wren_rejects_empty_or_failed_responses_before_generation(
    behavior, error
):
    ai = RecordingAI()
    async with fixture_session("wren", behavior) as session:
        with pytest.raises(error):
            await propose_with_session("Total order amount?", session, ai)
        assert ai.requests == []


async def test_wren_timeout_closes_stdio_process(tmp_path):
    import time
    from types import SimpleNamespace
    from unibot_RAG.integrations.wren import propose_sql

    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "mdl.json").write_text("{}")
    pid_file = tmp_path / "pid"
    wrapper = tmp_path / "fixture-wren"
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os, sys, runpy\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "assert sys.argv[1:] == ['serve', 'mcp', '--project', os.getcwd(), '--no-connect', '--quiet']\n"
        "assert 'OPENAI_API_KEY' not in os.environ\n"
        "sys.argv = ['fixture', 'wren', 'hang']\n"
        f"runpy.run_path({str(FIXTURE)!r}, run_name='__main__')\n"
    )
    wrapper.chmod(0o700)
    settings = SimpleNamespace(
        wren_home=None,
        wren_project=str(tmp_path),
        wren_command=str(wrapper),
        wren_timeout=2,
    )
    started = time.monotonic()
    with pytest.raises((TimeoutError, BaseExceptionGroup)):
        await propose_sql("Total?", settings, RecordingAI())
    assert time.monotonic() - started < 10
    assert pid_file.exists()
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize("proposal", ["DELETE FROM orders", "SELECT FROM", ""])
async def test_sql_api_returns_422_for_validation_inside_real_stdio_session(
    tmp_path, monkeypatch, proposal
):
    from types import SimpleNamespace
    import httpx
    from unibot_RAG.api.main import create_app
    from unibot_RAG.integrations import wren

    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "mdl.json").write_text("{}")
    wrapper = tmp_path / "fixture-wren"
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import sys, runpy\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "sys.argv = ['fixture', 'wren', 'valid']\n"
        f"runpy.run_path({str(FIXTURE)!r}, run_name='__main__')\n"
    )
    wrapper.chmod(0o700)
    monkeypatch.setenv("WREN_PROJECT", str(tmp_path))
    monkeypatch.setenv("WREN_COMMAND", str(wrapper))
    calls = []
    allowed_call = wren.allowed_call

    async def track_call(session, name, arguments, schemas=None):
        calls.append(name)
        return await allowed_call(session, name, arguments, schemas)

    monkeypatch.setattr(wren, "allowed_call", track_call)
    ai = SimpleNamespace(propose_sql=lambda question, context: proposal)
    app = create_app(service=SimpleNamespace(ai=ai))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/sql/propose", json={"question": "Order total?"})
    assert response.status_code == 422
    assert response.json() == {"detail": "Input or provider response is invalid"}
    assert calls == ["get_mdl", "get_instructions"]
