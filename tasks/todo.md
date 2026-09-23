# Implementation checklist

- [x] Documents/settings: validated limits and provider configuration; unit tests.
- [x] Loaders: supported formats retain provenance and reject malformed input; fixture tests.
- [x] Chunking: token/recursive/structure/semantic strategies enforce bounds; CJK tests.
- [x] Redis: repeat ingestion, replacement, interruption and races; real Redis tests.
- [x] Retrieval: dense/lexical fusion, optional reranking, source filters; retrieval tests.
- [x] Generation: context budget, citations and abstention; provider contract tests.
- [x] API/UI: regressions, ingestion reports, uploads, safe errors; HTTP/UI tests.
- [x] Wren/MCP: schema-grounded proposal only, allowlisted tools; protocol tests.
- [x] Evaluation: reproducible ranking ablations and explicit live-quality limits.
- [ ] Delivery: docs, Compose, CI, diff review, commits, push and PR verification.
