# Spec: Universal-RAG upgrade

Status: scope approved by the user on 2026-09-23; implementation and local verification complete. See [validation evidence](validation.md).

## Objective

Upgrade the current single-source, dense-only prototype into a testable RAG
system supporting structured and unstructured ingestion, hybrid retrieval,
reranking, configurable chunking, optional AI enrichment, WrenAI text-to-SQL
and MCP. Keep FastAPI, Streamlit, Redis and pip-based dependency management.
The companion [component audit](component-audit.md) records existing defects.

Completion means functional upgrades and their tests are present, setup
documentation matches the runtime, and a verified commit is pushed to
`jongos-lst/Universal-RAG:codex/rag-system-upgrade` with a PR against `main`.
Creating the branch, commit, push and PR is already authorized by the user.

## Assumptions proposed for review

- Implement the full scope in verifiable increments on one upgrade branch.
- Default local development remains usable without Wren, reranker downloads,
  GCS credentials or AI enrichment. Provider calls require explicit configuration.
- Target Python 3.11 and resolve/test compatible dependency versions before
  changing requirements. Keep requirements files; do not add a package manager.
- Treat Wren OSS via local MCP as the initial integration. Generate SQL from
  Wren semantics with the configured LLM, then ask Wren to validate/transpile.
  This is distinct from Wren Cloud's hosted SQL-generation endpoint.
- SQL execution is disabled by default. Do not connect to or modify any existing
  user database as part of development. Use an isolated synthetic fixture only.
- Multi-tenant authorization, OCR for scanned PDFs, audio/video transcription,
  graph RAG and distributed scheduling are later work, not implicit claims.

## Proposed behavior and acceptance criteria

### 1. Runtime correctness

- API imports and starts without performing ingestion or requiring GCS.
- Query responses consistently represent success, no evidence and unavailable
  dependencies; the existing question endpoint remains supported.
- Configure provider/model/base URL, Redis URL/index/dimensions and retrieval
  limits in one validated settings layer; reject incompatible index dimensions.
- API and UI run as separate Compose services with documented ports.

### 2. Ingestion workflow

- Local/API upload, website and GCS sources normalize into documents with
  source URI, source revision, content, format and record/page/section metadata.
- Support TXT, Markdown, HTML, FAQ/general CSV, JSON/JSONL, text PDF and DOCX.
  Reject unsupported/scanned-only inputs explicitly instead of indexing nothing.
- Stages: acquire → validate → parse → chunk → optional enrich → embed → stage
  → publish → report. Expose source-level status, counts and safe failure details.
- Enforce byte/document/chunk limits, website host/redirect policy and timeouts.
- Repeating unchanged ingestion creates no duplicates; changed sources replace
  their active revision only after all required chunks are written successfully.
- Interruptions and concurrent writes cannot publish mixed revisions. Keep
  previous revisions available for recovery; do not drop the existing index.
- Use an explicit job command/API, with persisted status and bounded retry.
  A distributed queue is unnecessary for the initial single-worker workflow.

### 3. Chunking and AI enrichment

- Provide token-window, recursive and structure-aware strategies. Preserve
  headings, table-row labels, page/record positions and provenance.
- Configure token size and overlap with validation and hard upper bounds;
  include Traditional Chinese and mixed-language fixtures.
- Offer optional embedding-based semantic boundaries as a measured experiment.
- Offer opt-in AI title/keyword/summary enrichment with strict output schemas,
  bounded calls and timeouts. Preserve original text as citation evidence;
  generated text must not replace source evidence.
- Record the strategy/model/version in source fingerprints so changes cause
  deliberate reprocessing. Make enrichment failure policy visible.

### 4. Retrieval and reranking

- Retrieve lexical and vector candidates independently from the same index
  revision with identical source filters; combine using reciprocal-rank fusion.
- Configurable candidate count, final count and stable deduplication by chunk ID.
- Retain dense-only mode for ablation. Escape user query syntax; empty or
  punctuation-only queries must not become unrestricted wildcard searches.
- Optional cross-encoder reranking acts only on bounded retrieved candidates.
  Preserve IDs/sources; validate scores and make timeout fallback observable.
- Never present a fusion score as calibrated confidence. Choose abstention
  behavior from labeled evaluation rather than an arbitrary RRF threshold.

### 5. Grounded responses and UI

- Build bounded context from retrieved passages, return source citations and
  handle empty retrieval without indexing the first element unconditionally.
- Keep source instructions separate from system instructions. Standardize
  abstention and provider-error behavior and test session isolation if memory is used.
- Streamlit uses the same query/ingestion service contracts, reports real chunk
  counts and renders missing sources/errors safely.

### 6. WrenAI and MCP

- Expose local stdio MCP tools for bounded knowledge search and grounded answers.
  Keep ingestion mutations outside the initial tool surface.
- Add an optional Wren MCP client with a configured executable/project, fixed
  arguments, tool allowlist, response schema checks, deadlines and deterministic
  subprocess/session cleanup. Never accept an executable from a query.
- Structured-query mode obtains schema/business context from Wren, generates a
  SQL proposal, validates it and returns SQL plus validation/provenance state.
- Default Wren invocation uses `--no-connect`; it must not call `run_sql`,
  `query_cube`, `dry_run` or write tools in proposal mode.
- If execution is later enabled, require server-side read-only database
  credentials, statement/row/time limits and separately tested authorization.
  A string-prefix check on SQL is not an execution security boundary.
- Unconfigured Wren returns a clear unavailable result; it does not invent SQL
  results or silently route an analytics question into document search.

### 7. Evaluation and delivery

- Synthetic fixture corpus covers identifiers, paraphrases, CJK, tables,
  multi-passage questions, unanswerable prompts and malicious source instructions.
- Compare dense-only, hybrid, hybrid+reranker and chunk strategies using
  Recall@k, MRR/nDCG, citation correctness, abstention and measured latency/cost.
- Offline contract tests use deterministic embeddings and provider doubles;
  they do not prove model quality. Mark live-model evaluation separately.
- CI runs deterministic tests and isolated Redis integration tests on PRs.
- Report every skipped external-service test and the remaining limitation.
- Commit and push reviewed changes, create a PR with exact validation evidence,
  then verify its head SHA and observed CI state. No automatic merge/deployment.

## Project structure

Existing `unibot_RAG/api`, `redis_db`, `utils` and Streamlit entrypoint remain.
Proposed modules: `ingestion/` for loaders/chunking/jobs, `retrieval/` for fusion
and reranking, `integrations/` for Wren, and `mcp_server.py` for the tool entrypoint.
`tests/` contains unit, API, integration and fixture suites; `docs/` contains
operator and evaluation instructions. Detailed tasks will live in `tasks/` after
scope review.

## Commands

The repository currently has no test command. Establish these during
implementation; they are proposed commands, not successful runs:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r unibot_RAG/requirements.txt -r requirements-dev.txt
.venv/bin/python -m pip check
.venv/bin/python -m pytest tests/unit tests/api -q
.venv/bin/python -m pytest tests/integration -q
.venv/bin/python -m unibot_RAG.evaluation --dataset tests/fixtures/evaluation.json
docker compose config --quiet
docker compose build
.venv/bin/python -m uvicorn unibot_RAG.api.main:app --host 127.0.0.1 --port 8000
.venv/bin/python -m streamlit run unibot_RAG/streamlit_chatbot.py
```

Integration commands must target a disposable test Redis index and synthetic
data. Do not run a migration, reset, bulk reindex or index switch on a preexisting
deployment without the separately required confirmation.

## Code style

Use typed Python functions and small explicit services with injected I/O
dependencies. Validate external input at the boundary. Example interface:

```python
def retrieve(self, question: str, *, source_id: str | None = None) -> list[Passage]:
    dense = self.store.vector_search(question, source_id=source_id)
    lexical = self.store.lexical_search(question, source_id=source_id)
    return reciprocal_rank_fusion(dense, lexical, limit=self.settings.top_k)
```

Use snake_case for new identifiers; retain compatibility wrappers where needed.
Do not hide exceptions behind generic success responses or log raw documents,
questions, SQL result rows or credentials by default.

## Testing strategy

Write focused regressions for observed defects, then unit/property-style cases
for chunk limits, identity, fusion, schema validation and ingestion transitions.
HTTP tests exercise real request/response validation with fake external providers.
Redis tests inspect stored keys, text, vector dimensions and query results on the
pinned server. MCP tests perform actual initialization, tool discovery and calls.
Wren integration uses a fixture semantic model and records the tested version.
Run failure paths for interruption, concurrency, provider outage and invalid input.

## Boundaries

- Always: preserve unrelated work, verify provider contracts, test meaningful
  failures, account for each changed file, update configuration/setup docs.
- Review: this scope and Wren deployment choice; then concrete implementation
  tasks before architectural changes, as required by the selected workflow.
- Already authorized: relevant code/config/dependency/test changes; new branch;
  local commits, push to the named upgrade branch and open a PR against `main`.
- Confirm separately: production/staging deployment, actual index/data migration,
  PR merge, destructive cleanup, credential/access changes or external messages.
- Never: commit secrets, overwrite the existing knowledge index, fabricate test
  evidence, equate mocked integration with verified live behavior.

## Accepted decisions and verification limits

The user approved the full scope with Wren OSS via local MCP. SQL execution is
absent from the tool surface. The configured LLM generates proposals using Wren
semantics; Wren transpiles them with `--no-connect`.

The implementation prepares chunks and embeddings in memory, then publishes one
bounded Redis transaction rather than writing a separate staging index. Existing
LangChain orchestration was replaced with direct SDK calls to make identity and
publication explicit. Jobs remain synchronous and source-level retries are bounded.

Deterministic provider contracts, real Redis/MCP, Docker/UI runtime checks and
published Wren native transpilation were verified. Live-model comparisons and
production corpus quality/cost measurements remain explicitly unverified because
no representative corpus or provider credentials were supplied. Synthetic scores
are regression evidence, not evidence of model quality. Details and commands are
in [validation](validation.md) and [operations](operations.md).
