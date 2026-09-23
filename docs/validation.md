# Upgrade validation — 2026-09-23

## Verified locally

- Python 3.12: `TEST_REDIS_URL=redis://localhost:16389 .venv/bin/python -m pytest -q`
  passed **133 tests**, including eight tests against disposable Redis Search
  7.4.0-v8 and actual MCP stdio sessions. One upstream Starlette/AnyIO
  deprecation warning remains.
- `ruff check unibot_RAG tests`, `python -m pip check` and `git diff --check` passed.
- API tests cover lazy startup, legacy responses, input validation, source filters,
  admin authentication, upload bytes/limits, jobs and safe failures.
- Redis tests cover complete source replacement, unchanged input, failed embedding,
  stale/concurrent writers, source isolation, invalid vectors and schema mismatch.
- Loader/chunk tests cover all supported formats, PDF page provenance/encryption,
  DOCX expansion, record limits, Unicode boundaries and all four strategies.
- Provider tests use controlled responses: batching/order, citation identity,
  malformed reranker results, explicit fallback, enrichment fail/skip and separation
  of untrusted evidence from system instructions. They do not prove model robustness.
- MCP tests initialize actual subprocess sessions, discover tools, call them and
  reject execution tools; timeout verification confirms the child process exits.
- Website/GCS tests use controlled I/O, including DNS/IP/TLS selection, redirects,
  byte/deadline limits, generation matching and resource cleanup.
- Backend and frontend Docker images built on Linux ARM with Python 3.11. Both
  served their HTTP health endpoints on isolated loopback ports. Backend `pip check`
  and `docker compose config --quiet` passed. No existing Redis volume was mounted.
- `tests/ui_smoke.py` passed inside the final frontend image: disabled initial
  actions, answer/citation rendering, SQL proposal display and safe API errors.
- Published `wrenai==0.15.0`, `wren-core-py==0.8.0`, `mcp==1.26.0` and
  `sqlglot==29.0.1` passed `tests/wren_smoke.py` on macOS ARM/Python 3.12. This uses
  actual Wren stdio MCP and native join/aggregation transpilation, a temporary
  two-model project and a fixed SQL-generating double. `--no-connect` is set;
  no database query is executed.

The first Wren Linux ARM slim-image installation failed because the native engine
has no matching wheel and compilation lacked a linker. The supported macOS ARM
wheel worked. Wren remains separately installed; see [setup](wren-mcp.md).

## Retrieval evaluation

The six-question synthetic corpus runs through real Redis ingestion and search.
Five questions have source labels; one unanswerable question is counted separately.
Token, recursive, structure and semantic chunking each completed dense and hybrid
ablations. Recall@3, MRR@3 and nDCG@3 were all 1.0 for both retrieval modes on this
small fixture. These embeddings are deliberately simple and contain known semantic
categories. The scores verify regression behavior, **not a quality improvement**.
They do not distinguish the chunking strategies on short documents.

The evaluation command also supports an optional configured reranker and a
`--live` read of a real index. No live OpenAI/Cohere calls, GCS bucket reads or user
corpus/database access were performed. Reranker/model quality, citation factuality,
real-world abstention, prompt-injection resistance, cost and production latency
remain unmeasured. Use representative labeled questions before choosing defaults
for production or claiming an improvement.

## Delivery and operational boundaries

CI defines Python 3.11/3.12 tests with isolated Redis and a separate Streamlit UI
job. Consult the PR checks for their observed remote outcome. No production or
staging service was deployed and no existing knowledge index was migrated.

Jobs are synchronous, parser isolation and multi-tenant read authorization are
outside this scope, and old inactive revisions require operator-managed retention.
The new `_v2` index/volume and explicit reingestion path preserve existing data.
See [operations](operations.md) for failure recovery and rollback.
