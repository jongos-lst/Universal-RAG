# Ingestion, upgrade and recovery

## Source revision workflow

Each synchronous ingestion creates a seven-day Redis job record, then performs
parse, chunk, optional enrichment, embedding and publication stages. Source
fingerprints include bytes, filename, source ID, chunk settings and provider/model
configuration. All required embedding batches finish before knowledge writes.
A bounded Redis transaction switches old chunks inactive, writes new chunks and
updates the manifest. WATCH rejects a stale writer; retrying unchanged input does
not duplicate chunks. Retrieval retries if publication changes its snapshot while
its dense and lexical searches are running.

The old revision stays stored but inactive; active chunks are the only searchable
ones. There is no automatic garbage collection. Monitor Redis memory and arrange
explicit retention/backup procedures before large deployments. The default
`noeviction` policy fails writes instead of silently removing source data. This
is a single-node Redis transaction design, not Redis Cluster support.

Jobs run within the calling request/process. They are not a distributed queue.
If a process dies, a `running` job can remain until its seven-day expiry; re-submit
the source to recover. Do not interpret that state as a live worker heartbeat.
The CLI retries only explicit transient exceptions, at most three attempts.
Failures after a completed publication but before final job reporting can leave
published content with a stale job state; repeating the source resolves it as
`unchanged`. Source publication is the correctness boundary.

## Limits

Defaults: 5 MB raw input, 1000 records/pages, 1000 chunks, 400 tokens/chunk, 32 AI
enrichment calls/source. DOCX ZIP expansion and extracted text are bounded to
10 times the raw byte limit. Scanned PDFs need an external OCR pipeline and are
rejected when no text is extractable. Parsers run in-process; hostile complex
PDFs may still use disproportionate CPU/memory. Only trusted administrators may
ingest; isolate parser workers before accepting anonymous/untrusted public uploads.

Website fetches enforce `REQUEST_TIMEOUT` across worker admission, DNS, connection,
response headers/body and cleanup. A timeout shuts down captured transport sockets
without waiting for a buffered reader's close lock. OS DNS resolution cannot be
force-cancelled safely, so it may finish in the background; cancelled fetches do not
connect after DNS returns. Each process caps outstanding website workers at eight,
including stalled DNS/cleanup, and admission waits share the same deadline.

Provider calls have configured HTTP timeouts and bounded retries. Job logs contain
IDs, counts, durations and error types, not question/document text or credentials.
The liveness endpoint checks the process, not provider health. A successful health
check does not prove retrieval works; use a representative cited query as a smoke test.

## Existing installations

The former LangChain schema stored `answer` as content and used inconsistent IDs.
Do not attach the new writer to that index. This branch defaults to a new `_v2`
index and new Compose volume. The legacy query HTTP path remains, but Python
`RedisClient` construction and legacy LangChain vector-store injection changed.
`unibot_RAG` is now a compatibility adapter over `RAGService`; shared memory is
explicitly rejected.

1. Back up the old Redis data and record its model, dimensions and deployment.
2. Build the new app with a distinct `_v2` index and provider configuration.
3. Reingest the original source files into that separate index only after the
   operator authorizes this data operation.
4. Run labeled retrieval/answer evaluation and manual cited queries.
5. Switch clients to the new API only after accepting results.

Rollback routes clients to the old deployment/index. No destructive reset or
automatic migration command is included. Changing embeddings/dimensions requires
another distinct `_v2`-suffixed index, not silently rewriting an existing one.

## Reproducible quality evaluation

`python -m unibot_RAG.evaluation` creates and cleans up a unique fixture index.
It uses documented synthetic embeddings to exercise the actual Redis ingestion,
search and rank-fusion path; its scores are regression evidence only. Change
`CHUNK_STRATEGY` between runs to compare processing strategies on those fixtures.
Use a larger representative dataset of `questions` and `relevant_sources` before
choosing production retrieval/chunking/reranking settings.

`--live --dataset ...` evaluates the configured index using real providers and may
incur cost. It does not ingest or migrate sources. Recall, MRR and nDCG are source-
level metrics; latency is observed wall time on this machine. Questions with no
relevant sources are excluded from ranking averages and counted separately.
Grounded answer correctness, calibrated abstention, model cost and prompt-injection
resistance require separate reviewed answer labels/live-model runs; they cannot be
inferred from perfect synthetic retrieval scores.
