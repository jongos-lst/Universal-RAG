# Implementation checklist

- [ ] Documents/settings: validated limits and provider configuration; unit tests.
- [ ] Loaders: supported formats retain provenance and reject malformed input; fixture tests.
- [ ] Chunking: token/recursive/structure/semantic strategies enforce bounds; CJK tests.
- [ ] Redis: repeat ingestion, replacement, interruption and races; real Redis tests.
- [ ] Retrieval: dense/lexical fusion, optional reranking, source filters; retrieval tests.
- [ ] Generation: context budget, citations and abstention; provider contract tests.
- [ ] API/UI: regressions, ingestion reports, uploads, safe errors; HTTP/UI tests.
- [ ] Wren/MCP: schema-grounded proposal only, allowlisted tools; protocol tests.
- [ ] Evaluation: reproducible ranking ablations and explicit live-quality limits.
- [ ] Delivery: docs, Compose, CI, diff review, commits, push and PR verification.
