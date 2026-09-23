# Approved RAG upgrade implementation plan

Scope approved by the user on 2026-09-23; see docs/upgrade-spec.md.

Dependency order and verification checkpoints:
1. Settings, canonical documents and offline loader/chunking tests.
2. Provider contracts and versioned Redis writes; test on disposable Redis.
3. Hybrid fusion, reranking and grounded answer service; deterministic evaluations.
4. API regressions and Streamlit integration against that shared service.
5. Local MCP and Wren schema-to-SQL proposal; protocol tests and timeout cases.
6. Operator docs, Compose and CI; full clean-install/runtime checks and PR delivery.

Use Python 3.11 in containers/CI and additionally verify on available host 3.12.
Use the existing Redis/OpenAI SDKs directly for explicit index and identity control;
remove the obsolete LangChain orchestration adapter rather than maintaining two stores.
Keep the original index untouched: default new index is unibot_v2.
Knowledge writes publish one bounded source revision in a Redis transaction after
all parsing/enrichment/embedding succeeds. WATCH prevents lost concurrent updates.
No hosted provider or existing knowledge/database calls are required for tests.

Risks: external model quality requires separate live evaluation; Wren interface
must be verified against installed SDK/project; PDF/DOCX parsers need size limits;
new index requires operator-managed reingestion/cutover, never implicit migration.
