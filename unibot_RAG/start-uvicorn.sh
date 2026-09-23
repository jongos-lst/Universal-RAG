#!/bin/sh
set -eu
exec python -m uvicorn unibot_RAG.api.main:app --host 0.0.0.0 --port 8000
