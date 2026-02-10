#!/bin/bash
set -e
# Start Uvicorn with live reload
exec uvicorn --host 0.0.0.0 --port 80 --log-level info "unibot_RAG.api.main:app"
