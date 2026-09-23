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
