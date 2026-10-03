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

## PR review fixes — 2026-10-03

Local Python 3.12 verification: `python -m pytest -q` passed **180 tests** with
**9 Redis integration tests skipped**. Ruff, `python -m pip check`, compileall,
`tests/ui_smoke.py`, and `git diff --check` passed. One upstream Starlette/AnyIO
deprecation warning remains. The cloud proxy required an environment-only `socksio`
installation; application dependency pins were unchanged.

The follow-up patch addresses first-initialization schema metadata races, embedding
request dimensions, Wren datasource-aware SQL validation, website media/deadline
handling, blocking MCP tools, and stale results after a failed UI question.

- Deterministic two-thread tests reproduce the Redis creator/loser interleaving;
  only the successful `FT.CREATE` process may publish the embedding signature.
  An additional real-Redis test checks concurrent initializers against the physical
  vector dimensions in `FT.INFO`.
- Provider tests inspect serialized SDK HTTP requests for shortened vectors,
  legacy `ada-002`, and custom endpoint parameter opt-in/opt-out.
- SQL tests cover MySQL/BigQuery quoting, MSSQL `TOP`, datasource aliases, and
  write/multi-statement rejection. These use the pinned SQLGlot parser and a
  controlled Wren MCP session; no live SQL/model/database was used for this patch.
- Website regressions exercise the real loaders through API, CLI and legacy
  helpers, plus real urllib3 buffering over socket pairs with trickling body and
  header data. DNS, worker saturation and blocked cleanup have deadline tests.
- Actual FastMCP dispatch tests check execution threads, concurrent progress and
  both asyncio and AnyIO cancellation. A cancelled synchronous provider call may
  finish in its worker under the provider's own timeout; cancellation does not
  force-kill Python threads.
- The Streamlit test reuses a successful query session before simulating a new
  failed question, checking that neither old SQL nor an old answer remains.

This cloud workspace has no Docker or Redis Search daemon. Local Redis tests are
explicitly skipped, and remote CI must verify them on the exact pushed commit.
The earlier image builds and native Wren smoke test above describe the original
upgrade, not reruns against this follow-up patch. Live provider quality, GCS,
production data and deployment remain outside this validation.

## Runtime QA fixes — 2026-10-03

A later isolated runtime check installed disposable Redis Stack and the native
Wren runtime, superseding the earlier local Redis/native-Wren verification limit.
It reproduced and then verified two fixes:

- MCP task-group teardown wraps SQL validation errors in nested exception groups.
  The Wren adapter now normalizes groups only when every leaf is a `ValueError`,
  restoring HTTP 422 for invalid/write SQL. Unexpected or mixed groups remain
  intact and produce a safe dependency failure. SQL remains proposal-only;
  invalid statements never reach `dry_plan` or an execution tool.
- A new document or website ingestion attempt clears the previous sidebar report.
  Failure no longer leaves an earlier completed job visible as the current result.
  Regression checks cover authorization, validation, dependency and connection
  failures, repeated attempts and successful recovery.

Verification on Python 3.12 passed **197 tests with no skips**, including all nine
real Redis integration tests, plus **59 live runtime checks**. The live stack used
Redis 7.4.7 / RediSearch 2.10.20 and published Wren 0.15.0 / native engine 0.8.0.
The checks exercised actual HTTP APIs, production MCP subprocesses, native Wren
transpilation and HTTP-backed Streamlit AppTest flows. AppTest's file-widget input
was supplied by a test double; uploads themselves used the real multipart API.
Embeddings and generation came from a deterministic local HTTP fixture, not a
paid model. All eight document formats, replacement/failed replacement, source
filters, citations, abstention and ingestion reports were included.

The new automated regressions failed on the prior code and passed after the fix.
Ruff, pip check, compileall, the Streamlit smoke script, patch whitespace checks
and synthetic retrieval evaluation passed. Independent review found no actionable
issue. Existing upstream Starlette/AnyIO and native-Wren warnings remain.

These are private, isolated test services, not a deployment or user-accessible
preview. No real provider credentials, paid APIs, GCS access, production data,
database query execution, migration, image rebuild or merge was involved. Native
Wren transpilation can accept an unknown column; it does not prove SQL semantic
correctness or real-model quality. Remote CI should be checked for the exact
published revision.

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
