# Universal-RAG component audit

Reviewed 2026-09-23 at baseline `ae2d807`. Findings below are from source inspection;
they are not claims of live-service verification. The repository had a clean
working tree, one commit, no tests, and no open PRs when inspected.

## Components and proposed improvements

| Component | Observed behavior / defect | Proposed change | Verification needed |
| --- | --- | --- | --- |
| API startup | `api/main.py` imports nonexistent `faq_langchain`, `redis`, and `api.utils` modules; calls GCS ingestion at module import; concatenates potentially missing `API_PATH`. | Correct imports, validated defaults, explicit ingestion, dependency lifecycle. | Import without cloud credentials; health request; configuration failures. |
| API response | Successful path assigns nonexistent `response.service`; success status is never set; failures return the default response. | Stable response contract with success, no-knowledge, and dependency-error states. | Exercise every status and upstream failure through HTTP. |
| FAQ ingestion | `process_df_for_vectorstore` returns three values but `ingest_table` unpacks two; generated IDs are unused. | Validate rows and preserve question, answer, context, source ID, and chunk identity. | Regression using a two-row FAQ file and repeat ingestion. |
| Redis content | Schema uses `answer` as content key while FAQ metadata also contains `answer`, risking collisions between passage text and metadata. | Separate canonical chunk content from FAQ answer and source metadata. | Read-back test checking exact persisted passage and metadata. |
| Embeddings | Provider URL, model and 1536 dimensions are fixed; ingestion constructs a store without explicitly supplying the configured Redis URL. | Explicit provider/configuration contract; dimension validation; consistent connection construction. | Custom endpoint and Redis URL; dimension mismatch; failed embedding request. |
| Document writes | Document ingestion computes embeddings separately and supplies version-sensitive `embeddings`/`ids` kwargs to LangChain; actual stored keys need verification. | Verify pinned adapter contract, embed once, deterministic keys and bounded batches. | Spy provider call counts and inspect real Redis keys after two ingestions. |
| Index lifecycle | No schema/version compatibility checks, update protocol, source manifest or concurrency control; `reset` is destructive. | New versioned index and explicit activation; staged source revisions, idempotent publication. | Interrupted update, concurrent writers, retry and rollback tests. |
| GCS source | Imports wrong Redis module, selects any filename containing `csv`, downloads into current directory, and never cleans up. | Bounded streamed/downloaded inputs, exact supported extensions, stable `gs://` source IDs, per-object reports. | Nested paths, same basenames, malformed object, cleanup after errors. |
| Website source | Unbounded `requests.get`, follows redirects, no URL/network policy, all failures become `None`; normalizer removes paragraph structure. | Host policy, redirect validation, timeout and byte limits, structured errors, preserve headings/paragraphs. | Private/loopback target rejection, redirect rejection, large response, HTML cleaning. |
| Input formats | Only strict FAQ CSV and extracted website text are wired. | Common document model; TXT, Markdown, HTML, CSV, JSON/JSONL, text PDF and DOCX loaders. | Golden fixtures for each supported format, encoding/size/type errors, provenance. |
| Chunking | One 400-token splitter using `p50k_base`, 20-token overlap, no format-aware handling. | Configurable token, recursive and heading/row-aware strategies; opt-in semantic splitting. | Hard token limits, overlap constraints, CJK, long paragraphs, table rows, headings. |
| Retrieval | Dense-only `k=1`; cannot combine exact identifiers with semantic matches. | Redis lexical and dense candidate searches, reciprocal-rank fusion, configurable candidate/final limits. | Exact-match and paraphrase fixtures; stable ties, deduplication, filters on both branches. |
| Reranking | None. | Optional bounded cross-encoder reranker, configurable timeout/failure policy. | Candidate preservation, ordering, stable IDs, disabled mode, failure behavior. |
| Generation | Hardcoded OpenRouter free model; direct `[0]` indexing on source documents; memory mode disables sources that response code requires. | Configurable model, bounded context, consistent abstention, cited sources, explicit session memory behavior. | Empty retrieval, source mapping, prompt-budget limits and memory regression. |
| Grounding | Prompt refusal differs from the string checked by the API. No relevance gate or answer-quality evaluation. | One abstention contract, evidence-aware response, labeled retrieval and grounded-answer evaluation. | Unanswerable questions, distractors and source attribution. |
| Streamlit | Recreates clients on reruns; empty chunk count is never populated; error path calls `.strip()` on `None`; source toggle indexes optional keys. | Shared service contract, actual ingestion report, safe errors and source rendering. | Upload/ingest/query flow, empty response, failure and retry behavior. |
| Feedback | Buttons display success, but persistence is TODO. | Clearly label feedback behavior; defer storage until a destination is configured. | UI must not claim data was saved when it was not. |
| Structured analytics | No database connector, semantic layer, SQL validation or execution policy. | WrenAI-backed schema-aware SQL proposal via MCP; explicit structured-query mode. | Joins/aggregations against sample semantics, invalid SQL, disabled execution, missing config. |
| MCP | No client/server support. | Local stdio server for bounded RAG tools plus an allowlisted Wren MCP client. | Real protocol initialize/list/call, schema errors, cancellation and process cleanup. |
| Runtime/dependencies | Python 3.11.6 in Docker but README says 3.9+; old pinned core packages and unpinned transitive/tool dependencies. | Select one supported Python version, resolve compatible pins, retain pip requirements. | Clean install, dependency consistency, imports and image build. |
| Containers | README describes API on port 80; image actually starts Streamlit on 8501. Redis uses mutable `latest` and password build arguments. | Separate API/UI entrypoints; pinned verified Redis version, runtime secret configuration and health checks. | Compose validation, isolated build/start/readiness and query smoke test. |
| Operational scripts | Redis setup mixes Homebrew with Debian/apt paths and systemd-style operations. | Document the supported Compose route and retire misleading setup instructions. | Follow setup from a clean environment. |
| Secret hygiene | Ignore rule is `credentials.json/`, which covers a directory rather than the mounted credential file. | Ignore the actual file; provide placeholders only. | Verify ignore behavior without printing secret values. |
| Observability/evaluation | Logs raw questions/answers; no timing, dataset, automated checks or quality baseline. | Content-free stage metrics and request IDs; checked-in synthetic evaluation corpus and CI. | No prompt/credential logging; reproducible recall, MRR/nDCG, latency and provider-cost report. |

## Priority and sequencing

1. Restore bootable, tested API and ingestion contracts.
2. Establish canonical documents, safe source loaders and repeatable ingestion.
3. Add versioned Redis storage, hybrid retrieval and optional reranking.
4. Integrate generation, citations and the UI with the same service functions.
5. Add opt-in AI ingestion enrichment and WrenAI/MCP integration.
6. Run integration tests and quality evaluation, then commit/push/open the upgrade PR.

All proposed ranking and chunking improvements require measurement. No retrieval
quality or latency improvement has yet been demonstrated. For each technique,
compare against a repaired dense-only baseline using the same corpus, embedding
model and candidate/context budgets.

## Current upstream considerations

- Redis's unified `FT.HYBRID` requires Redis 8.4+. Application-side rank fusion
  over separate queries is an option when retaining an earlier Redis Stack.
  Select and test one pinned deployment rather than depending on `latest`.
  [Redis command reference](https://redis.io/docs/latest/commands/ft.hybrid/)
- Redis renamed `BM25` to `BM25STD` in 8.4; lexical scoring must match the tested
  server version. [Scoring reference](https://redis.io/docs/latest/develop/ai/search-and-query/advanced-concepts/scoring/)
- Wren OSS currently exposes schema, planning and query tools over MCP. Its local
  HTTP mode has no bearer authentication, so stdio is the recommended initial
  integration. `--no-connect` disables database execution tools.
  [Wren MCP guide](https://docs.getwren.ai/oss/guides/mcp)
- Wren commercial SQL generation uses a separate API and plan entitlement. Do
  not assume this contract works against an OSS deployment.
  [Wren API overview](https://docs.getwren.ai/cp/guide/api-access/overview)
- Use the official MCP SDK for transport/session lifecycle and tool schemas.
  [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)

## Verification limitations at audit time

The host default is Python 3.9.6. An AST check parsed 10 of 11 Python files;
`api/model.py:51` fails on its starred expression in a type subscript under that
runtime. This contradicts the README's Python 3.9+ support claim; it is not a
claim that Python 3.11 rejects the syntax. The same check confirmed five missing
internal module imports and the processor's three-value return versus the
ingestion caller's two-value unpack.

Docker's socket was inaccessible inside the sandbox, but a host-side read-only
check succeeded and reported Docker Server 29.7.2. Isolated container tests
therefore appear feasible; no container build or startup has been attempted.
No dependency installation, live provider requests, ingestion, index mutation
or database queries were performed. Source-level defects above must receive
regression tests during implementation.
