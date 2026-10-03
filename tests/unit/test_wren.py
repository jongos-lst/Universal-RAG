import pytest
from mcp.types import CallToolResult, TextContent
from unibot_RAG.integrations.wren import read_result, allowed_call


def test_tool_error_cannot_be_a_successful_validation():
    result = CallToolResult(
        isError=True, content=[TextContent(type="text", text="private error")]
    )
    with pytest.raises(RuntimeError, match="Wren tool failed"):
        read_result(result)


def test_structured_and_text_responses():
    result = CallToolResult(content=[TextContent(type="text", text="SELECT 1")])
    assert read_result(result) == "SELECT 1"
    result = CallToolResult(content=[], structuredContent={"sql": "SELECT 1"})
    assert read_result(result) == {"sql": "SELECT 1"}


@pytest.mark.asyncio
async def test_execution_tool_denied_before_call():
    class Session:
        async def call_tool(self, *args, **kwargs):
            pytest.fail("Execution must never reach MCP")

    with pytest.raises(ValueError):
        await allowed_call(Session(), "run_sql", {"sql": "DELETE FROM orders"})


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE orders",
        "DELETE FROM orders",
        "SELECT 1; DROP TABLE orders",
        "SELECT * INTO copied FROM orders",
        "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
    ],
)
def test_non_readonly_proposal_rejected(sql):
    from unibot_RAG.integrations.wren import validate_sql_proposal

    with pytest.raises(ValueError):
        validate_sql_proposal(sql)


def test_join_and_aggregation_are_valid_proposals():
    from unibot_RAG.integrations.wren import validate_sql_proposal

    sql = "SELECT c.name, SUM(o.amount) FROM customers c JOIN orders o ON c.id=o.customer_id GROUP BY c.name"
    assert validate_sql_proposal(sql) == sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "datasource,sql",
    [
        ("mysql", "SELECT `order_id` FROM `orders`"),
        ("bigquery", "SELECT `order_id` FROM `orders`"),
        ("mssql", "SELECT TOP 10 [order_id] FROM [orders]"),
        ("postgres", "SELECT DISTINCT ON (order_id) order_id FROM orders"),
        ("local_file", "SELECT order_id FROM orders"),
        ("datafusion", "SELECT order_id FROM orders"),
    ],
)
async def test_proposal_is_validated_in_mdl_datasource_dialect(datasource, sql):
    from types import SimpleNamespace
    from unibot_RAG.integrations.wren import propose_with_session

    calls = []

    class Session:
        async def list_tools(self):
            return SimpleNamespace(tools=[
                SimpleNamespace(name=name, inputSchema={"type": "object"})
                for name in ["get_mdl", "get_instructions", "dry_plan"]
            ])

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            value = {"dataSource": datasource, "models": [{"name": "orders"}]}
            if name == "get_instructions":
                value = {"instructions": "Use orders"}
            elif name == "dry_plan":
                value = {"sql": arguments["sql"]}
            return CallToolResult(content=[], structuredContent=value)

    ai = SimpleNamespace(propose_sql=lambda question, context: sql)
    result = await propose_with_session("Orders?", Session(), ai)
    assert result["sql"] == sql
    assert result["executed"] is False
    assert calls[-1] == ("dry_plan", {"sql": sql})


@pytest.mark.parametrize("dialect", ["mysql", "bigquery", "tsql", "postgres", "duckdb"])
@pytest.mark.parametrize("sql", [
    "DELETE FROM orders",
    "SELECT * INTO copied FROM orders",
    "SELECT 1; DELETE FROM orders",
    "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
])
def test_dialect_validation_retains_readonly_gate(dialect, sql):
    from unibot_RAG.integrations.wren import validate_sql_proposal

    with pytest.raises(ValueError):
        validate_sql_proposal(sql, dialect=dialect)


@pytest.mark.asyncio
@pytest.mark.parametrize("errors,expected", [
    ([ValueError("invalid SQL")], ValueError),
    ([ExceptionGroup("nested", [ValueError("invalid SQL")])], ValueError),
    ([ValueError("invalid SQL"), ExceptionGroup("nested", [ValueError("invalid model")])], ValueError),
    ([RuntimeError("transport failed")], ExceptionGroup),
    ([ValueError("invalid SQL"), ExceptionGroup("nested", [RuntimeError("cleanup failed")])], ExceptionGroup),
])
async def test_only_pure_validation_groups_are_normalized(tmp_path, monkeypatch, errors, expected):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unibot_RAG.integrations import wren

    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "mdl.json").write_text("{}")
    failure = ExceptionGroup("private transport details", errors)

    @asynccontextmanager
    async def failed_transport(server):
        raise failure
        yield  # Keep the failure inside an async context manager.

    monkeypatch.setattr(wren, "stdio_client", failed_transport)
    settings = SimpleNamespace(
        wren_project=str(tmp_path), wren_home=None,
        wren_command="unused", wren_timeout=5,
    )
    with pytest.raises(expected) as caught:
        await wren.propose_sql("Orders?", settings, None)
    if expected is ExceptionGroup:
        # Preserve every error and the original group for unexpected/mixed failures.
        assert caught.value is failure
    else:
        assert "private transport details" not in str(caught.value)
