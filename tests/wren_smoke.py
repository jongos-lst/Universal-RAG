import asyncio
import json
import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace
from wren.context import convert_mdl_to_project, write_project_files, build_json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unibot_RAG.integrations.wren import propose_sql

mdl = {
    "catalog": "wren",
    "schema": "public",
    "dataSource": "duckdb",
    "models": [
        {
            "name": "orders",
            "refSql": "SELECT 1 AS id, 1 AS customer_id, 12 AS amount",
            "columns": [
                {"name": "id", "type": "integer", "expression": "id"},
                {"name": "customer_id", "type": "integer", "expression": "customer_id"},
                {"name": "amount", "type": "integer", "expression": "amount"},
            ],
            "primaryKey": "id",
        },
        {
            "name": "customers",
            "refSql": "SELECT 1 AS id, 'Ada' AS name",
            "columns": [
                {"name": "id", "type": "integer", "expression": "id"},
                {"name": "name", "type": "varchar", "expression": "name"},
            ],
            "primaryKey": "id",
        },
    ],
}


class AI:
    def propose_sql(self, question, context):
        assert len(context["mdl"]["models"]) == 2
        return "SELECT c.name, SUM(o.amount) AS total FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.name"


with tempfile.TemporaryDirectory(prefix="rag-wren-project-") as root:
    project = Path(root)
    write_project_files(convert_mdl_to_project(mdl), project)
    (project / "connection_info.json").write_text(json.dumps({"datasource": "duckdb"}))
    (project / "target").mkdir(exist_ok=True)
    (project / "target" / "mdl.json").write_text(json.dumps(build_json(project)))
    settings = SimpleNamespace(
        wren_home=root,
        wren_project=root,
        wren_command=str(Path(sys.executable).parent / "wren"),
        wren_timeout=60,
    )
    result = asyncio.run(propose_sql("Total by customer?", settings, AI()))
    assert result["executed"] is False and result["validation"] == "transpiled"
    print(json.dumps(result, indent=2))

print(
    "Published Wren 0.15 MCP + native engine: join/aggregation transpilation passed; no query execution"
)
