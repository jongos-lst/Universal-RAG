"""Schema-grounded SQL proposal through Wren OSS MCP; no SQL execution tools."""

import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path

import anyio
from jsonschema import validate
from sqlglot import exp, parse
from sqlglot.errors import ParseError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ALLOWED_TOOLS = {"get_mdl", "get_instructions", "dry_plan"}


def read_result(result):
    if result.isError:
        raise RuntimeError("Wren tool failed")
    if result.structuredContent is not None:
        value = result.structuredContent
    else:
        parts = [part.text for part in result.content if part.type == "text"]
        value = "\n".join(parts)
        if not value.strip():
            raise ValueError("Empty Wren response")
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    if not value:
        raise ValueError("Empty Wren response")
    if len(json.dumps(value)) > 100_000:
        raise ValueError("Wren response exceeds context limit")
    if isinstance(value, dict) and (
        value.get("error") or value.get("success") is False
    ):
        raise RuntimeError("Wren tool failed")
    return value


async def allowed_call(session, name, arguments, schemas=None):
    if name not in ALLOWED_TOOLS:
        raise ValueError("Wren tool is not permitted")
    if schemas is not None:
        if name not in schemas:
            raise ValueError("Configured Wren version is missing required tools")
        validate(arguments, schemas[name])
    return read_result(await session.call_tool(name, arguments))


def validate_sql_proposal(sql):
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 20000:
        raise ValueError("Invalid SQL proposal")
    try:
        statements = parse(sql)
    except ParseError as exc:
        raise ValueError("SQL proposal could not be parsed") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise ValueError("SQL proposal must be one query")
    if any(
        isinstance(node, (exp.DML, exp.DDL, exp.Into, exp.Lock))
        for node in statements[0].walk()
    ):
        raise ValueError("SQL proposal contains a write operation")
    return sql


async def propose_with_session(question, session, ai):
    listed = await session.list_tools()
    schemas = {tool.name: tool.inputSchema for tool in listed.tools}
    mdl = await allowed_call(session, "get_mdl", {}, schemas)
    instructions = await allowed_call(session, "get_instructions", {}, schemas)
    # Model work runs off the event loop; provider enforces its own HTTP deadline.
    sql = await anyio.to_thread.run_sync(
        lambda: ai.propose_sql(question, {"mdl": mdl, "instructions": instructions})
    )
    sql = validate_sql_proposal(sql)
    plan = await allowed_call(session, "dry_plan", {"sql": sql}, schemas)
    return {
        "status": "proposed",
        "sql": sql,
        "validation": "transpiled",
        "plan": plan,
        "executed": False,
        "provider": "wren-mcp",
    }


async def propose_sql(question, settings, ai):
    if not settings.wren_project:
        raise RuntimeError("Wren is not configured")
    project = Path(settings.wren_project).resolve()
    if not (project / "target" / "mdl.json").is_file():
        raise ValueError("Wren requires a compiled target/mdl.json")
    # Do not give subprocesses the RAG provider key, Redis password or admin token.
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "SYSTEMROOT")
        if key in os.environ
    }
    if settings.wren_home:
        env["WREN_HOME"] = str(Path(settings.wren_home).resolve())
    server = StdioServerParameters(
        command=settings.wren_command,
        args=["serve", "mcp", "--project", str(project), "--no-connect", "--quiet"],
        env=env,
        cwd=str(project),
    )
    async with asyncio.timeout(settings.wren_timeout):
        async with stdio_client(server) as (read, write):
            async with ClientSession(
                read,
                write,
                read_timeout_seconds=timedelta(seconds=settings.wren_timeout),
            ) as session:
                await session.initialize()
                return await propose_with_session(question, session, ai)
