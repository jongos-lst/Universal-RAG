# Universal RAG

FastAPI + Streamlit knowledge assistant with Redis lexical/vector retrieval,
reciprocal-rank fusion, optional reranking, cited answers and explicit abstention.
Ingestion accepts TXT, Markdown, HTML, CSV, JSON/JSONL, text PDF and DOCX. WrenAI
integration generates and transpiles SQL proposals through local MCP; it never
executes them.

## Run locally with Docker

Requires Docker Compose 2.24+ and an OpenAI-compatible provider for embeddings and
answers. Python containers use 3.11; local development is tested on 3.12 as well.

```sh
cp .env.example .env
# Set OPENAI_API_KEY and a nonempty ADMIN_TOKEN in .env.
docker compose up --build
```

Open [the UI](http://localhost:8501) or [API docs](http://localhost:8000/docs).
Health and documentation work without provider credentials. Redis is internal to
Compose; API/UI bind to loopback. The example Redis password is for local use.
Set your own runtime password before sharing an environment. The API has no
multi-tenant read authorization; keep it local or place it behind your own
identity/authorization boundary before exposing private knowledge.

This version uses a **new `unibot_v2` index and `redis_v2_data` volume**. Existing
knowledge is not changed or migrated. See [upgrade and rollback](docs/operations.md).

## Ingest and query

Use the sidebar to upload a document with a stable source ID and admin token.
Reusing a source ID replaces its visible revision only after the complete new
source has been processed successfully. Repeating identical input skips embedding
and returns `unchanged`. Different source IDs are independent documents.

The API supports:

| Method / path | Purpose |
| --- | --- |
| `GET /unibot/health_check` | Process liveness, no external work |
| `POST /unibot/v1/users/get-unibot-response/` | `{ "question": "..." }`, optional legacy `phone_number` |
| `POST /v1/search` | `{ "question": "...", "source_id": "optional" }` |
| `PUT /unibot/admin/ingest-data` | UTF-8 JSON `{ "filename": "x.txt", "content": "...", "source_id": "x" }` |
| `POST /v1/admin/upload` | Multipart `file` and `source_id` |
| `POST /v1/admin/website` | `{ "url": "https://allowed-host/path" }` |
| `GET /v1/admin/jobs/{job_id}` | Persisted ingestion report |
| `POST /v1/sql/propose` | Wren SQL proposal, no execution |

Admin routes require `Authorization: Bearer <ADMIN_TOKEN>`. Empty tokens disable
admin access. Query errors use 422 for invalid input/contract, 409 for concurrent
knowledge changes, and 503 for unavailable dependencies. Successful answers include
`status`, `answer`, `sources`, `metadata`, and `source_document`. There is no fake
feedback persistence or shared conversation memory.

## Development

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r unibot_RAG/requirements.txt -r requirements-dev.txt -r requirements-lint.txt
.venv/bin/python -c 'import tiktoken; tiktoken.get_encoding("cl100k_base")'
.venv/bin/python -m uvicorn unibot_RAG.api.main:app --host 127.0.0.1 --port 8000
```

Install `requirements-ui.txt` separately to run Streamlit locally:

```sh
.venv/bin/python -m pip install -r requirements-ui.txt
.venv/bin/python -m streamlit run unibot_RAG/streamlit_chatbot.py
# Optional UI regression check:
.venv/bin/python tests/ui_smoke.py
```

Explicit ingestion commands (run at repository root):

```sh
.venv/bin/python -m unibot_RAG.ingestion --file ./handbook.md --source-id handbook --attempts 3
.venv/bin/python -m unibot_RAG.ingestion --url https://example.com/guide
.venv/bin/python -m unibot_RAG.ingestion --gcs
```

Website fetching requires `WEBSITE_HOSTS` (comma-separated exact hostnames), HTTPS,
public IP resolution and no redirects. Connections pin the checked IP with TLS
hostname verification. GCS uses `GCS_BUCKET_NAME`, optional `GCS_PREFIX`, and normal
Application Default Credentials; credentials are never bundled into images.

## Retrieval and chunking

- `CHUNK_STRATEGY=token|recursive|structure|semantic`; default `structure` preserves
  Markdown/HTML heading boundaries and CSV/JSON record provenance.
- `CHUNK_TOKENS=400`, `CHUNK_OVERLAP=40`: limits measured with `cl100k_base`, with
  Unicode-safe boundaries. Overlap applies to token windows; recursive/structure
  boundaries keep complete units when they fit. Semantic mode uses extra embedding calls and its
  `SEMANTIC_THRESHOLD` is experimental.
- `RETRIEVAL_MODE=hybrid|dense`, `CANDIDATE_K=20`, `TOP_K=5`.
- `RERANK_URL` enables a Cohere v2-compatible cross-encoder endpoint, with optional
  `RERANK_API_KEY` and configurable `RERANK_MODEL`. `RERANK_FAILURE=fail|fallback`
  controls outages; fallback emits a content-free warning.
- `ENRICHMENT_ENABLED=true` adds AI titles/summaries/keywords to lexical metadata,
  with a 32-chunk/source call budget. Original passages remain citation evidence.
  `ENRICHMENT_FAILURE=fail|skip` makes partial enrichment explicit in job warnings.

Redis 7.4 Stack supplies BM25 and HNSW; fusion runs in Python, so `FT.HYBRID` and
Redis 8.4 are not required. Model, provider and embedding dimensions are recorded
with the index. A mismatch is rejected: choose a new name ending in `_v2` and
reingest explicitly. Vector and BM25 scores are rank signals, not confidence.

## MCP and WrenAI

Run the local RAG server with:

```sh
.venv/bin/python -m unibot_RAG.mcp_server
```

It exposes `search_knowledge`, `answer_question`, and `propose_sql` over stdio.
No ingestion or SQL execution tools are exposed. See [Wren setup](docs/wren-mcp.md)
for its separately installed runtime and semantic project.

## Verification

```sh
.venv/bin/python -m pip check
.venv/bin/ruff check unibot_RAG tests
.venv/bin/python -m pytest tests/unit tests/api tests/integration/test_mcp.py -q
```

Real Redis tests require a disposable Redis Search instance, never a production
endpoint. The suite creates unique test indexes and removes only those indexes.

```sh
docker run --rm -p 127.0.0.1:16389:6379 redis/redis-stack-server:7.4.0-v8
TEST_REDIS_URL=redis://localhost:16389 .venv/bin/python -m pytest -q
TEST_REDIS_URL=redis://localhost:16389 .venv/bin/python -m unibot_RAG.evaluation
```

Without `TEST_REDIS_URL`, only Redis tests are explicitly skipped. MCP tests spawn
real protocol sessions against a synthetic Wren server. They are not proof of
live model quality or production database correctness. See [validation notes](docs/validation.md)
and the [original audit](docs/component-audit.md).
