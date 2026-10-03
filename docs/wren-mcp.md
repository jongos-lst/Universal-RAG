# WrenAI SQL proposal and MCP

The adapter targets the Wren OSS 0.15.0 MCP contract, inspected in its published
wheel. This is not Wren Cloud's SQL-generation REST endpoint or legacy GenBI
Classic. Install Wren in a separate environment because it brings its own engine,
dataframe and native runtime dependencies:

```sh
python3.11 -m venv /path/to/wren-venv
/path/to/wren-venv/bin/pip install 'wrenai[mcp]==0.15.0' 'mcp==1.26.0' 'sqlglot==29.0.1'
```

Prepare your Wren project and compile `target/mdl.json` using the Wren project
workflow. Set `WREN_COMMAND=/path/to/wren-venv/bin/wren` and
`WREN_PROJECT=/absolute/path/to/project` in the backend environment. A container
needs that runtime and project installed/mounted explicitly; the default API
image does not bundle Wren or database credentials.

Set `WREN_HOME` to a dedicated Wren configuration directory. Wren 0.15 still
requires a datasource selector in its profile/connection configuration even with
`--no-connect`; the project's MDL `dataSource` alone is insufficient. For the
synthetic DuckDB transpilation fixture, that directory contains
`connection_info.json` with `{"datasource":"duckdb"}` and no credentials. Configure
the appropriate Wren profile for other dialects. If `WREN_HOME` is omitted, Wren
uses its normal user configuration. Keep this deployment configuration controlled
by the operator.

The published native engine has macOS ARM and Linux x86_64 wheels, but no Linux
ARM wheel for 0.8.0. Our Linux ARM slim-image attempt required native compilation
and failed without a linker; use a supported wheel platform or provision Wren's
native build prerequisites. The verified macOS ARM runtime can be reproduced with:

```sh
/path/to/wren-venv/bin/python tests/wren_smoke.py
```

This creates and removes a synthetic project, uses actual stdio MCP and the native
engine, and substitutes only the SQL-generating LLM. It needs no database.

The app launches exactly:

```sh
wren serve mcp --project /absolute/path/to/project --no-connect --quiet
```

It initializes an MCP session, discovers input schemas, calls `get_mdl` and
`get_instructions`, asks the configured LLM to propose SQL, and calls
`dry_plan(sql=...)`. The response contains the proposed SQL, transpiled plan,
`validation="transpiled"` and `executed=false`. Transpilation is not validation
against live rows or proof of answer correctness.

Only those three tools are allowlisted. The adapter never follows remote tool
instructions, runs SQL, stores query history, accepts a caller-provided command,
or exposes execution tools through the RAG MCP server. Wren runs with a minimal
environment; the RAG API key, admin token and Redis password are not forwarded.
Timeouts bound MCP operations and provider requests; session/subprocess cleanup
uses the official SDK context managers.

For an MCP client, configure a stdio server with command pointing to this repo's
`.venv/bin/python`, arguments `["-m", "unibot_RAG.mcp_server"]`, and working
directory set to the repository root. The RAG server is local; it does not expose
a remote HTTP MCP listener.

Sources: [Wren MCP guide](https://docs.getwren.ai/oss/guides/mcp),
[Wren CLI reference](https://docs.getwren.ai/oss/reference/cli),
[MCP SDK](https://py.sdk.modelcontextprotocol.io/).
